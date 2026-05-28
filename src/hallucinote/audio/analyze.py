"""``analyze_mix`` — the audio-analysis MVP's single entry point.

Reads a captures directory + a song's DB intent, runs the three MVP
analyses (per-stem loudness, master-bus contribution attribution,
declared-send reverb verification), and returns a populated
``MixReport``.

The MCP handler (``hallucinote_mcp.handlers.analysis``) is a thin
wrapper that resolves the song DB connection, calls this function,
serializes the report to JSON at
``songs/<slug>/analysis/<iso-ts>.json``, and returns the path.

Intent extraction is intentionally narrow in MVP: the DB does not yet
carry declared RT60s per send (a future schema addition — backlog will
absorb that work). When no intent is declared, the reverb-verification
section is emitted as a structured ``skipped_analyses`` entry rather
than silently absent — per CLAUDE.md "Never silently drop a
requirement."
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from .attribution import (
    OvershootWindow,
    find_master_overshoots,
    master_bus_attribution,
)
from .io import CaptureSet, load_capture
from .loudness import measure_loudness
from .report import (
    Finding,
    MasterOvershoot,
    MixReport,
    ReverbVerification,
    StemMetrics,
)
from .reverb import verify_reverb_send


@dataclass(frozen=True)
class DeclaredReverbSend:
    """One declared dry→wet send with target RT60.

    Today this is supplied by the caller (or empty for MVP). Once the
    song DB grows a ``reverb_send_intent`` table, ``analyze_mix`` will
    populate this list from the DB rather than requiring the caller to.
    """
    dry_track_id: str
    wet_return_track_id: str
    declared_rt60_s: float


def analyze_mix(
    captures_dir: Path | str,
    *,
    song_db_conn: sqlite3.Connection | None = None,
    declared_reverb_sends: Sequence[DeclaredReverbSend] = (),
) -> MixReport:
    """Run the audio-analysis MVP pipeline against a captures directory.

    Three passes:

      1. Per-surface loudness — master, every stem, every return.
      2. Master-bus overshoot detection + per-stem contribution
         attribution.
      3. For each declared dry→wet send: Wiener-deconvolve IR, measure
         RT60, compare to declared. If none declared, emit a
         ``skipped_analyses`` entry.

    ``song_db_conn`` is accepted for future intent lookup; the MVP
    doesn't yet query it (no schema for declared decay times) but the
    parameter is plumbed so callers don't churn when the lookup lands.
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
        song_db_conn=song_db_conn,
    )

    findings = _derive_findings(
        master=master_metrics,
        stems=stem_metrics,
        overshoots=overshoots,
        reverbs=reverb_verifications,
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
    Section-windowed analysis with variable tempo is a P1 backlog item.
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
    song_db_conn: sqlite3.Connection | None,
) -> tuple[list[ReverbVerification], list[dict]]:
    """Run one verification per declared send; record skips otherwise.

    DB-driven intent extraction is a future schema addition (the MVP DB
    has no ``reverb_send_intent`` table). When ``declared_sends`` is
    empty AND no DB intent surfaces, emit a structured skip record so
    the report explains *why* the section is empty.
    """
    if not declared_sends:
        skipped = [{
            "kind": "reverb_verification",
            "reason": (
                "no declared RT60 sends — pass them via "
                "analyze_mix(declared_reverb_sends=...) or wait for the "
                "DB schema to grow a reverb_send_intent table"
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


def _derive_findings(
    *,
    master: StemMetrics,
    stems: list[StemMetrics],
    overshoots: list[MasterOvershoot],
    reverbs: list[ReverbVerification],
) -> list[Finding]:
    """Translate raw metrics into structured findings.

    The MVP populates three kinds:

      - ``master_overshoot`` (warning) — one per detected overshoot
        window where peak_dbtp > 0.
      - ``reverb_out_of_tolerance`` (warning) — one per declared send
        whose measured RT60 falls outside tolerance.
      - ``master_clipping_risk`` (info) — when master true-peak ≥ -0.1 dBTP
        but no overshoots crossed 0.

    Findings are intentionally narrow in MVP — the LLM ranks/filters by
    ``kind`` + ``severity`` rather than parsing prose. Candidate
    mutation proposals (the "fix" side) are P2 backlog.
    """
    findings: list[Finding] = []

    for o in overshoots:
        findings.append(Finding(
            kind="master_overshoot",
            severity="warning",
            subject="master",
            metric="peak_dbtp",
            observed=o.peak_dbtp,
            expected=0.0,
            db_reference=f"bar:{o.start_beat:.2f}-{o.end_beat:.2f}",
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
    "analyze_mix",
]
