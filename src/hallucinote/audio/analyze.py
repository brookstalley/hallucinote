"""``analyze_mix`` — the audio-analysis MVP's single entry point.

Reads a captures directory + a song's DB intent, runs the analyses
(per-stem loudness, master-bus contribution attribution, declared-send
reverb verification, and per-section loudness windowing) and returns a
populated ``MixReport``.

The MCP handler (``hallucinote_mcp.handlers.analysis``) is a thin
wrapper that resolves the song DB connection, calls this function,
serializes the report to JSON at
``songs/<slug>/analysis/<iso-ts>.json``, and returns the path.

Intent extraction is narrow: DB-declared RT60s flow in via the
``sends.intended_rt60_s`` column (see ``set_send_intended_rt60`` +
``get_reverb_send_intents_for_song``). The MCP handler reads them and
passes ``declared_reverb_sends=...`` here; this module is DB-agnostic
and does the work on the list it's given. When no intent is declared,
the reverb-verification section is emitted as a structured
``skipped_analyses`` entry rather than silently absent — per CLAUDE.md
"Never silently drop a requirement."
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from .attribution import (
    OvershootWindow,
    find_master_overshoots,
    master_bus_attribution,
)
from .io import CaptureSet, Surface, load_capture
from .loudness import measure_loudness
from .report import (
    Finding,
    MasterOvershoot,
    MixReport,
    ReverbVerification,
    SectionMetrics,
    StemMetrics,
)
from .reverb import verify_reverb_send
from .section import SectionWindow, WindowSlice, intersect_window, slice_audio


@dataclass(frozen=True)
class DeclaredReverbSend:
    """One declared dry→wet send with target RT60.

    The MCP handler builds these from ``sends.intended_rt60_s`` rows
    (``get_reverb_send_intents_for_song``). Callers invoking ``analyze_mix``
    directly can construct them by hand for synthetic-fixture work.
    """
    dry_track_id: str
    wet_return_track_id: str
    declared_rt60_s: float


def analyze_mix(
    captures_dir: Path | str,
    *,
    declared_reverb_sends: Sequence[DeclaredReverbSend] = (),
    sections: Sequence[SectionWindow] = (),
) -> MixReport:
    """Run the audio-analysis MVP pipeline against a captures directory.

    Four passes:

      1. Per-surface loudness — master, every stem, every return.
      2. Master-bus overshoot detection + per-stem contribution
         attribution.
      3. For each declared dry→wet send: Wiener-deconvolve IR, measure
         RT60, compare to declared. If none declared, emit a
         ``skipped_analyses`` entry.
      4. Per-section loudness — the pass-1 metrics scoped to each named
         section window. If no sections are declared, emit a
         ``skipped_analyses`` entry.

    DB intent extraction is the handler's job: it walks
    ``sends.intended_rt60_s`` rows (for ``declared_reverb_sends``) and the
    ``sections`` table converted to beats (for ``sections``), then passes
    populated lists. This function stays DB-agnostic so synthetic-fixture
    tests can drive it without a song DB.
    """
    captures_dir = Path(captures_dir)
    manifest_path = captures_dir / "manifest.json"
    capture = load_capture(manifest_path)

    master_metrics = _measure_surface(capture.master)
    stem_metrics = [_measure_surface(s) for s in capture.stems]
    return_metrics = [_measure_surface(r) for r in capture.returns]

    overshoot_windows = find_master_overshoots(
        capture.master.audio,
        capture.sample_rate,
    )
    attributed = master_bus_attribution(
        capture.master.audio,
        capture.stems,
        capture.sample_rate,
        overshoot_windows,
    )
    overshoots = [_rebeat_overshoot(o, capture) for o in attributed]

    reverb_verifications, skipped = _run_reverb_verifications(
        capture=capture,
        declared_sends=declared_reverb_sends,
    )

    per_section, section_skips = _measure_sections(
        capture=capture,
        sections=sections,
    )
    skipped.extend(section_skips)

    findings = _derive_findings(
        master=master_metrics,
        stems=stem_metrics,
        overshoots=overshoots,
        reverbs=reverb_verifications,
        sections=sections,
    )

    return MixReport(
        song_slug=capture.song_slug,
        captures_dir=str(capture.captures_dir),
        captured_at=capture.captured_at,
        analyzer_signature=capture.analyzer_signature,
        master=master_metrics,
        stems=stem_metrics,
        returns=return_metrics,
        overshoots=overshoots,
        reverb_verifications=reverb_verifications,
        per_section=per_section,
        findings=findings,
        skipped_analyses=skipped,
    )


def _measure_surface(surface) -> StemMetrics:
    loudness = measure_loudness(surface.audio, sr=surface.sample_rate)
    return StemMetrics(
        track_id=surface.track_id,
        surface_kind=surface.surface_kind,
        surface_name=surface.surface_name,
        loudness=loudness,
    )


def _rebeat_overshoot(o: MasterOvershoot, capture: CaptureSet) -> MasterOvershoot:
    """Convert the seconds-domain start/end from ``attribution.master_bus_attribution``
    into beats using the capture's transport window.

    Beats-per-second is derived from (stop_at_beat - start_at_beat) /
    audio_duration_s — assumes constant tempo across the captured window.
    Section windowing (``_measure_sections``) shares this linear beat↔sample
    map; variable-tempo-accurate windowing remains a backlog follow-on.
    """
    duration_s = capture.master.audio.shape[0] / capture.sample_rate
    span_beats = capture.stop_at_beat - capture.start_at_beat
    if duration_s <= 0 or span_beats <= 0:
        # Degenerate capture — leave the seconds-domain values in place
        # rather than dividing by zero. The agent reading the report can
        # detect the absurd start_beat==end_beat case.
        return o
    beats_per_second = span_beats / duration_s
    return MasterOvershoot(
        start_beat=capture.start_at_beat + o.start_beat * beats_per_second,
        end_beat=capture.start_at_beat + o.end_beat * beats_per_second,
        peak_dbtp=o.peak_dbtp,
        dominant_band=o.dominant_band,
        attribution=list(o.attribution),
    )


def _run_reverb_verifications(
    *,
    capture: CaptureSet,
    declared_sends: Sequence[DeclaredReverbSend],
) -> tuple[list[ReverbVerification], list[dict]]:
    """Run one verification per declared send; record skips otherwise.

    Empty ``declared_sends`` produces a structured skip record so the
    report explains *why* the section is empty (rather than ambiguously
    "no reverbs verified — analyzed OK or no intent declared?").
    """
    if not declared_sends:
        skipped = [{
            "kind": "reverb_verification",
            "reason": (
                "no declared RT60 sends — call "
                "set_send_intended_rt60(from_track_id, to_return_id, "
                "intended_rt60_s=<seconds>) on each reverb-bus send to "
                "declare composer intent the analyzer can verify"
            ),
        }]
        return [], skipped

    verifications: list[ReverbVerification] = []
    skipped: list[dict] = []
    stems_by_id = {s.track_id: s for s in capture.stems}
    returns_by_id = {r.track_id: r for r in capture.returns}

    for send in declared_sends:
        dry = stems_by_id.get(send.dry_track_id)
        wet = returns_by_id.get(send.wet_return_track_id)
        if dry is None or wet is None:
            skipped.append({
                "kind": "reverb_verification",
                "reason": (
                    f"declared dry={send.dry_track_id} or "
                    f"wet={send.wet_return_track_id} not in capture "
                    f"(stems present: {sorted(stems_by_id)}; "
                    f"returns present: {sorted(returns_by_id)})"
                ),
            })
            continue
        verifications.append(verify_reverb_send(
            dry.audio, wet.audio,
            sample_rate=capture.sample_rate,
            declared_rt60_s=send.declared_rt60_s,
            dry_track_id=send.dry_track_id,
            wet_return_track_id=send.wet_return_track_id,
        ))
    return verifications, skipped


def _measure_sections(
    *,
    capture: CaptureSet,
    sections: Sequence[SectionWindow],
) -> tuple[list[SectionMetrics], list[dict]]:
    """Measure per-surface loudness scoped to each named section window.

    Each section's beat window is intersected with the captured transport
    span and measured over only the overlapping audio. A section that
    falls entirely outside the captured window is recorded as a skip
    (rather than emitted with empty/−inf metrics) so the report explains
    *why* it's absent — per CLAUDE.md "Never silently drop a requirement."

    Empty ``sections`` produces one structured skip teaching the caller to
    declare sectional structure via ``create_section`` — symmetric with the
    reverb-verification skip.
    """
    if not sections:
        return [], [{
            "kind": "section_windowed",
            "reason": (
                "no sections declared — call create_section(name, "
                "start_bar, end_bar) on the song to define verse / chorus "
                "/ bridge spans the analyzer can scope loudness to"
            ),
        }]

    n_samples = capture.master.audio.shape[0]
    per_section: list[SectionMetrics] = []
    skipped: list[dict] = []

    for window in sections:
        sl = intersect_window(
            window,
            n_samples=n_samples,
            capture_start_beat=capture.start_at_beat,
            capture_stop_beat=capture.stop_at_beat,
        )
        if not sl.covered:
            skipped.append({
                "kind": "section_windowed",
                "reason": (
                    f"section {window.name!r} "
                    f"(beats {window.start_beat:.2f}..{window.end_beat:.2f}) "
                    f"falls outside the captured window "
                    f"(beats {capture.start_at_beat:.2f}.."
                    f"{capture.stop_at_beat:.2f}) — render the arrangement "
                    f"span that includes this section to analyze it"
                ),
            })
            continue
        per_section.append(SectionMetrics(
            section_name=window.name,
            start_beat=window.start_beat,
            end_beat=window.end_beat,
            master=_measure_window(capture.master, sl),
            stems=[_measure_window(s, sl) for s in capture.stems],
            returns=[_measure_window(r, sl) for r in capture.returns],
        ))

    return per_section, skipped


def _measure_window(surface: Surface, window_slice: WindowSlice) -> StemMetrics:
    """Loudness of one surface over a clamped section window."""
    sliced = slice_audio(surface.audio, window_slice)
    loudness = measure_loudness(sliced, sr=surface.sample_rate)
    return StemMetrics(
        track_id=surface.track_id,
        surface_kind=surface.surface_kind,
        surface_name=surface.surface_name,
        loudness=loudness,
    )


def _section_name_for_beat(
    beat: float,
    sections: Sequence[SectionWindow],
) -> str | None:
    """The name of the section whose half-open window contains ``beat``.

    First match wins (sections shouldn't overlap, but if they do the
    earliest-starting one in iteration order is reported). ``None`` when
    no section covers the beat or none were declared."""
    for window in sections:
        if window.start_beat <= beat < window.end_beat:
            return window.name
    return None


def _derive_findings(
    *,
    master: StemMetrics,
    stems: list[StemMetrics],
    overshoots: list[MasterOvershoot],
    reverbs: list[ReverbVerification],
    sections: Sequence[SectionWindow] = (),
) -> list[Finding]:
    """Translate raw metrics into structured findings.

    The MVP populates three kinds:

      - ``master_overshoot`` (warning) — one per detected overshoot
        window where peak_dbtp > 0.
      - ``reverb_out_of_tolerance`` (warning) — one per declared send
        whose measured RT60 falls outside tolerance.
      - ``master_clipping_risk`` (info) — when master true-peak ≥ -0.1 dBTP
        but no overshoots crossed 0.

    When ``sections`` are declared, each ``master_overshoot`` finding's
    ``db_reference`` names the section the overshoot lands in
    (``"section:chorus1 (beat:...)"``) — the read-side tie between the
    headline attribution and the song's sectional structure. Falls back to
    the bare beat range when no section covers the overshoot.

    Findings are intentionally narrow in MVP — the LLM ranks/filters by
    ``kind`` + ``severity`` rather than parsing prose. Candidate
    mutation proposals (the "fix" side) are P2 backlog.
    """
    findings: list[Finding] = []

    for o in overshoots:
        section_name = _section_name_for_beat(o.start_beat, sections)
        beat_ref = f"beat:{o.start_beat:.2f}-{o.end_beat:.2f}"
        db_reference = (
            f"section:{section_name} ({beat_ref})"
            if section_name is not None
            else beat_ref
        )
        findings.append(Finding(
            kind="master_overshoot",
            severity="warning",
            subject="master",
            metric="peak_dbtp",
            observed=o.peak_dbtp,
            expected=0.0,
            db_reference=db_reference,
        ))

    if not overshoots and master.loudness.true_peak_dbtp >= -0.1:
        findings.append(Finding(
            kind="master_clipping_risk",
            severity="info",
            subject="master",
            metric="true_peak_dbtp",
            observed=master.loudness.true_peak_dbtp,
            expected=-1.0,  # canonical "safe" headroom target
            db_reference=None,
        ))

    for r in reverbs:
        if not r.within_tolerance:
            findings.append(Finding(
                kind="reverb_out_of_tolerance",
                severity="warning",
                subject=f"{r.dry_track_id} → {r.wet_return_track_id}",
                metric="rt60_s",
                observed=r.measured_rt60_s,
                expected=r.declared_rt60_s,
                db_reference=None,
            ))

    return findings


__all__ = [
    "DeclaredReverbSend",
    "SectionWindow",
    "analyze_mix",
]
