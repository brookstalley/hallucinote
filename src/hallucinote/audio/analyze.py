"""``analyze_mix`` — the audio-analysis MVP's single entry point.

Reads a captures directory + a song's DB intent, runs the analyses
(per-stem loudness, master-bus contribution attribution, declared-send
reverb verification, and per-section loudness windowing) and returns a
populated ``MixReport``.

The MCP handler (``hallucinote_mcp.server_side.analysis``) is a thin
wrapper that resolves the song DB connection, calls this function,
serializes the report to JSON at
``songs/<slug>/analysis/<iso-ts>.json``, and returns the path.

Declared intent arrives as ARGUMENTS, never by reaching into the DB —
this module is DB-agnostic and does the work on the lists it is given.
The MCP handler resolves each from the song DB and passes it in:
``declared_reverb_sends`` (``sends.intended_rt60_s``),
``declared_envelopes`` (automation to verify), ``declared_width_controls``
(dialled stereo-width params), ``sections`` and ``declared_energy``. The
join is always on capture ``surface_id``, which is why no DB import
belongs here.

When a declared analysis has no intent to work from, it is emitted as a
structured ``skipped_analyses`` entry rather than silently absent — per
CLAUDE.md "Never silently drop a requirement."
"""
from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Mapping, Sequence

if TYPE_CHECKING:
    # Type-only: this module stays numpy-free at runtime (arrays arrive
    # pre-loaded from .io), but its "np.ndarray" annotations need the name.
    import numpy as np

from ..paths import portable_path
from .alignment import trim_to_common_length
from .compare import diff_reports, ensure_comparable, resolve_baseline
from .attribution import (
    band_attribution,
    find_master_overshoots,
    master_bus_attribution,
)
from .io import CaptureSet, Surface, load_capture
from .levels import apply_stem_gains, live_fader_db
from .loudness import MIN_LOUDNESS_DURATION_S, measure_loudness
from .stereo import measure_stereo
from .timbre import measure_timbre
from .cross_rhythm import (
    analyze_cross_rhythm_window,
    analyze_phasing_window,
    analyze_polymeter_window,
)
from .automation import DeclaredEnvelope, verify_envelope_realization
from .density import section_onset_density
from .energy import LOUDNESS, ONSET_DENSITY, SPECTRAL_CENTROID, realize_energy
from .masking import analyze_masking_window
from .report import (
    SCHEMA_VERSION,
    EnergyRealization,
    EnvelopeVerification,
    Finding,
    MasterOvershoot,
    MixReport,
    PartCrossRhythm,
    PartTiming,
    Phasing,
    Polymeter,
    ReverbVerification,
    SectionEnergy,
    SectionMetrics,
    StemMetrics,
    WidthRealization,
)
from .reverb import find_decay_onset, measure_return_rt60
from .section import (
    BeatSampleMap,
    SectionWindow,
    TempoSegment,
    WindowSlice,
    intersect_window,
    slice_audio,
)
from .timing import analyze_timing_window


# Product reporting floor for masking — pairs/bed below this masked fraction are
# noise, not signal, and are dropped from the report (the DSP itself returns the
# raw value; this is the integration-level "don't surface trivia" gate). The
# holistic interpreter still grades what survives against intent.
_MASKING_REPORTING_FLOOR = 0.15

# Product reporting floor for timing — parts whose onset-vs-grid confidence is
# below this are too transient-poor (pads, washes) to trust a feel reading on,
# so they're dropped from the report. Same integration-level "don't surface
# untrustworthy numbers" gate as the masking floor; the DSP returns every part
# with onsets and the interpreter grades what survives against intent.
_TIMING_MIN_CONFIDENCE = 0.25

# Product reporting floor for cross-rhythm. Mirrors the timing gate: a part
# whose pulse read is below this confidence (too sparse, or no clean pulse) is
# dropped from the report. Unlike timing, the LOW-confidence verdicts here
# (roll / rubato / low-confidence) are themselves informative — but they're the
# DSP's honest "I can't name this", not section-level evidence the interpreter
# acts on, so the same don't-surface-untrustworthy-numbers gate applies.
_CROSS_RHYTHM_MIN_CONFIDENCE = 0.25

# Product reporting floors for phasing (the two-part cross-rhythm pass). A pair
# only surfaces as phasing when its relative offset drifts both fast enough to
# matter (``DRIFT_FLOOR``, beats/cycle — locked or constant-offset pairs sit
# below it) AND cleanly enough to trust (``MIN_CONFIDENCE`` — a strong monotonic
# trend, not jittered noise). Both gates are needed: a constant phase offset can
# read a high trend correlation off detection jitter yet near-zero drift, so the
# drift floor is what rejects locked-but-offset parts.
_PHASING_DRIFT_FLOOR_BEATS = 0.02
_PHASING_MIN_CONFIDENCE = 0.6

# Product reporting floor for polymeter (two parts looping different cell
# lengths). A pair surfaces only when both cells resolved cleanly enough to
# trust — the confidence is the weaker part's accent-autocorrelation peak.
_POLYMETER_MIN_CONFIDENCE = 0.5

# DR-5 (ARR-7M3D) — the "notable inversion" surfacing gate for the
# energy-realization lens. How big a measured inversion (the magnitude of a
# wrong-direction rank flip) before /mix-review treats it as worth a producer
# question (vs DSP noise) is a PERCEPTUAL judgment, calibrated like
# _MASKING_REPORTING_FLOOR / _TIMING_MIN_CONFIDENCE — NOT guessed.
#
# PENDING CALIBRATION: Live was unattended this run, so the final value awaits a
# human-ear pass against the measured inversion distribution from a real
# sun-zone-done render (declared 0.25→1.0 across 9 sections). Until then this is
# the CONSERVATIVE SURFACE-EVERYTHING default (0.0): the lens records EVERY
# measured inversion as neutral evidence and /mix-review's intent gate (not a
# magnitude floor) decides what becomes a question. Surfacing-everything can
# never hide a real inversion; it only risks surfacing trivia, which the
# intent gate already filters. See .prawduct/operator-verification.md for the
# queued render-based calibration. The lens itself (energy.realize_energy)
# reports all inversions; this floor is the integration-level surfacing gate.
_ENERGY_INVERSION_SURFACING_FLOOR = 0.0


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


@dataclass(frozen=True)
class DeclaredWidthControl:
    """One authored width control, to be read beside what the audio did.

    The MCP handler builds these from the song's dialled device parameters; this
    module stays DB-agnostic and joins on ``surface_id`` alone. ``declared_display``
    is carried verbatim rather than parsed to a number on purpose — the report
    quotes what the author wrote ("165 %"), and the *measurement* beside it is
    what carries the argument, so nothing depends on parsing a unit string.
    """
    surface_id: str
    device_name: str
    parameter_name: str
    declared_display: str


def analyze_mix(
    captures_dir: Path | str,
    *,
    declared_reverb_sends: Sequence[DeclaredReverbSend] = (),
    declared_envelopes: Sequence[DeclaredEnvelope] = (),
    declared_width_controls: Sequence[DeclaredWidthControl] = (),
    sections: Sequence[SectionWindow] = (),
    declared_energy: Sequence[SectionEnergy] = (),
    tempo_map: Sequence[TempoSegment] = (),
    analyze_masking: bool = False,
    analyze_timing: bool = False,
    analyze_cross_rhythm: bool = False,
    stem_gains: "Mapping[str, float] | None" = None,
    master_fader_volume: float | None = None,
    compare_to: int | Path | str | None = None,
    analysis_dir: Path | str | None = None,
) -> MixReport:
    """Run the audio-analysis MVP pipeline against a captures directory.

    Four passes:

      1. Per-surface loudness — master, every stem, every return.
      2. Master-bus overshoot detection + per-stem contribution
         attribution.
      3. Per return with a declared send: measure RT60 from the return's
         own captured ring-out (Schroeder decay-tail, dry-source-free),
         compare to declared. If none declared, emit a
         ``skipped_analyses`` entry.
      4. Per-section loudness — the pass-1 metrics scoped to each named
         section window. If no sections are declared, emit a
         ``skipped_analyses`` entry.

    DB intent extraction is the handler's job: it walks
    ``sends.intended_rt60_s`` rows (for ``declared_reverb_sends``) and the
    ``sections`` table converted to beats (for ``sections``), then passes
    populated lists. This function stays DB-agnostic so synthetic-fixture
    tests can drive it without a song DB.

    ``analysis_dir`` does double duty: it is the pool a ``compare_to`` seq
    resolves against, and its parent is the **song directory** every path the
    report records is written relative to (``captures_dir``,
    ``compare_to.baseline.ref``) — see ``hallucinote.paths.portable_path`` and
    the ``MixReport`` docstring for why a persisted absolute path is a defect.

    ``compare_to`` selects a baseline for a before/after diff: an ``int`` is
    a song audit-log seq, resolved against ``analysis_dir`` (the directory
    of previously-written analysis JSONs — required for the seq form) via
    ``compare.resolve_baseline``; a path names a baseline JSON directly.
    The finished report is diffed against it (per-surface loudness deltas +
    significance flags, see ``compare.diff_reports``) and the result lands
    in ``MixReport.compare_to``. Deltas are neutral evidence graded against
    intent by the consumer — no findings are derived from them.
    """
    captures_dir = Path(captures_dir)
    manifest_path = captures_dir / "manifest.json"
    capture = load_capture(manifest_path)

    # Anchor for every path this report WRITES DOWN. The report JSON is
    # git-tracked (see .gitignore: the heavy captures/ WAVs are ignored, the
    # small analysis/ reports are kept), so an absolute path in it commits the
    # authoring machine's home directory — non-portable, undiffable across
    # machines, and refused outright by tools/tour_transcript.py's publish gate.
    # The song dir is the anchor because it is the one the reader can rediscover
    # from the artifact alone: the report lives at <song_dir>/analysis/<ts>.json,
    # so song_dir == report_path.parent.parent. None when the caller passed no
    # analysis_dir (a direct/synthetic-fixture call, which writes nothing);
    # portable_path then falls back to ~-collapsed or absolute — never an
    # account-bearing path. See hallucinote.paths.portable_path.
    song_dir = Path(analysis_dir).parent if analysis_dir is not None else None

    # Resolve + load + validate the baseline up front so a bad seq / path /
    # song fails fast, before the expensive DSP passes — the diff itself
    # runs at the end. diff_reports re-checks via the same shared
    # ensure_comparable; this earlier call just moves the refusal ahead of
    # the analysis cost.
    baseline: dict | None = None
    baseline_ref: str | None = None
    if compare_to is not None:
        if isinstance(compare_to, bool):
            raise TypeError("compare_to must be a seq int or a path, not a bool")
        if isinstance(compare_to, int):
            if analysis_dir is None:
                raise ValueError(
                    "compare_to=<seq> requires analysis_dir — the directory "
                    "of previous analysis JSONs to resolve the seq against"
                )
            baseline_path = resolve_baseline(analysis_dir, compare_to)
        else:
            baseline_path = Path(compare_to)
        # Portable for the same reason captures_dir is: baseline_ref is recorded
        # in the report's compare_to.baseline block (and quoted in the
        # comparability refusals below).
        baseline_ref = portable_path(baseline_path, base=song_dir)
        baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
        ensure_comparable(
            SCHEMA_VERSION, capture.song_slug, baseline, baseline_ref=baseline_ref
        )

    # Trim every surface to the common length (AUD-1C7K). Per-surface sfrecord~
    # instances finalize at staggered times, so the raw WAVs differ in length;
    # their starts are sample-aligned (calibration-verified), so trimming the
    # tails to the shortest surface yields equal-length, phase-aligned stems —
    # the invariant the cross-surface passes (attribution, masking) depend on.
    # No-op on already-equal-length synthetic fixtures.
    capture, alignment_report = trim_to_common_length(capture)

    # One beat↔sample map for the whole capture, shared by overshoot rebeat-ing
    # and section windowing. Variable-tempo accurate when a tempo_map is
    # supplied; degenerates to the constant-tempo linear map otherwise.
    #
    # The recorded audio spans [start_at_beat, stop_at_beat + ring_out_beats]:
    # the dry arrangement plays through stop_at_beat, then the render keeps
    # recording the reverb ring-out for ring_out_beats more (0 for pre-ring-out
    # captures). The map must cover the FULL recording so beat→sample stays
    # correct — section windows live in [start, stop] (the leading portion) and
    # the ring-out region [stop, stop+ring_out] maps to the trailing samples,
    # where reverb RT60 is measured.
    beat_map = BeatSampleMap(
        capture.start_at_beat,
        capture.stop_at_beat + capture.ring_out_beats,
        capture.master.audio.shape[0],
        tempo_map,
    )

    master_metrics = _measure_surface(capture.master)
    stem_metrics = [_measure_surface(s) for s in capture.stems]
    return_metrics = [_measure_surface(r) for r in capture.returns]

    # The master metrics are PRE master-fader — the HallucinoteAnalyzer taps the
    # master DEVICE CHAIN, before the master mixer volume. When the caller supplies
    # the master fader volume, surface the post-fader DELIVERED true-peak (bus TP +
    # the calibrated fader gain) so the report answers "is the delivered output
    # clipping?" — the master fader is a linear gain after the captured chain.
    master_fader_db: float | None = None
    delivered_true_peak_dbtp: float | None = None
    if master_fader_volume is not None:
        master_fader_db = live_fader_db(float(master_fader_volume))
        delivered_true_peak_dbtp = (
            master_metrics.loudness.true_peak_dbtp + master_fader_db
        )

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
    overshoots = [_rebeat_overshoot(o, capture, beat_map) for o in attributed]

    reverb_verifications, skipped = _run_reverb_verifications(
        capture=capture,
        declared_sends=declared_reverb_sends,
        beat_map=beat_map,
    )

    automation_verifications, automation_skips = _run_automation_verifications(
        capture=capture,
        declared_envelopes=declared_envelopes,
        beat_map=beat_map,
        stem_gains=stem_gains or {},
    )
    skipped.extend(automation_skips)

    per_section, section_skips = _measure_sections(
        capture=capture,
        sections=sections,
        beat_map=beat_map,
        analyze_masking=analyze_masking,
        analyze_timing=analyze_timing,
        analyze_cross_rhythm=analyze_cross_rhythm,
        stem_gains=stem_gains or {},
    )
    skipped.extend(section_skips)

    energy_realization, energy_skips = _realize_energy(declared_energy, per_section)
    skipped.extend(energy_skips)

    width_realizations, width_skips = _realize_widths(
        declared_width_controls, [*stem_metrics, *return_metrics]
    )
    skipped.extend(width_skips)

    findings = _derive_findings(
        master=master_metrics,
        stems=stem_metrics,
        overshoots=overshoots,
        reverbs=reverb_verifications,
        automation=automation_verifications,
        sections=sections,
    )

    report = MixReport(
        song_slug=capture.song_slug,
        captures_dir=portable_path(capture.captures_dir, base=song_dir),
        captured_at=capture.captured_at,
        analyzer_signature=capture.analyzer_signature,
        master=master_metrics,
        stems=stem_metrics,
        returns=return_metrics,
        overshoots=overshoots,
        reverb_verifications=reverb_verifications,
        automation_verifications=automation_verifications,
        width_realizations=width_realizations,
        per_section=per_section,
        findings=findings,
        skipped_analyses=skipped,
        energy_realization=energy_realization,
        alignment=alignment_report.to_json_dict(),
        db_seq=capture.db_seq,
        master_fader_volume=master_fader_volume,
        master_fader_db=master_fader_db,
        delivered_true_peak_dbtp=delivered_true_peak_dbtp,
    )

    if baseline is not None:
        report.compare_to = diff_reports(
            report.to_json_dict(), baseline, baseline_ref=baseline_ref
        )

    return report


def _measure_surface(surface) -> StemMetrics:
    loudness = measure_loudness(surface.audio, sr=surface.sample_rate)
    return StemMetrics(
        track_id=surface.track_id,
        surface_kind=surface.surface_kind,
        surface_name=surface.surface_name,
        loudness=loudness,
        timbre=measure_timbre(surface.audio, surface.sample_rate),
        stereo=measure_stereo(surface.audio),
    )


def _realize_widths(
    declared: Sequence[DeclaredWidthControl],
    surfaces: Sequence[StemMetrics],
) -> tuple[list[WidthRealization], list[dict]]:
    """Pair each declared width control with the measured image on its surface.

    ``surfaces`` is tracks AND returns — a width control on a reverb bus is an
    ordinary move, and a join that saw only tracks would report such a control as
    unmeasurable when the audio for it was captured all along.

    Neutral evidence only: the declared value beside what the audio did. No
    threshold, no severity, no verdict — a control doing nothing may be an
    oversight or may be a part with no side content to widen, and only the
    reader knows which. ``/mix-review`` grades it against declared intent.

    Catching this needs BOTH halves — the declaration and the rendered audio —
    which is why no DAW reports it and why the join lives here.
    """
    if not declared:
        return [], [{
            "kind": "width_realization",
            "reason": (
                "no declared width controls were RECOGNISED, so there is no "
                "declared-vs-measured pairing to make (the per-stem `stereo` "
                "block is still measured and reported). Recognition is a closed "
                "set of exact parameter names on top-level track and return "
                "devices; a width control under another name, or inside a rack's "
                "nested chain, is not seen — so this is 'none recognised', NOT "
                "'none authored'"
            ),
        }]

    by_surface = {s.track_id: s for s in surfaces}
    realizations: list[WidthRealization] = []
    skipped: list[dict] = []
    for control in declared:
        stem = by_surface.get(control.surface_id)
        if stem is None or stem.stereo is None:
            skipped.append({
                "kind": "width_realization",
                "reason": (
                    f"declared width control {control.parameter_name!r} on "
                    f"{control.device_name!r} targets surface "
                    f"{control.surface_id!r}, which this capture has no measured "
                    f"stereo for — the control cannot be checked against audio "
                    f"that wasn't captured"
                ),
            })
            continue
        realizations.append(WidthRealization(
            surface_id=control.surface_id,
            surface_name=stem.surface_name,
            device_name=control.device_name,
            parameter_name=control.parameter_name,
            declared_display=control.declared_display,
            correlation=stem.stereo.correlation,
            mono_sum_loss_db=stem.stereo.mono_sum_loss_db,
        ))
    return realizations, skipped


def _rebeat_overshoot(
    o: MasterOvershoot, capture: CaptureSet, beat_map: BeatSampleMap,
) -> MasterOvershoot:
    """Convert the seconds-domain start/end from ``master_bus_attribution``
    into song-absolute beats via the capture's :class:`BeatSampleMap`.

    The overshoot positions arrive in seconds (``o.start_beat`` is a seconds
    placeholder); ``seconds * sample_rate`` gives the sample index, which the
    map turns into a beat. Variable-tempo accurate when a tempo_map was
    supplied; identical to the old constant-tempo linear map otherwise. A
    degenerate capture leaves the seconds-domain values in place rather than
    dividing by zero — the agent can detect the absurd start==end case.
    """
    if beat_map.degenerate:
        return o
    sr = capture.sample_rate
    return MasterOvershoot(
        start_beat=beat_map.sample_to_beat(o.start_beat * sr),
        end_beat=beat_map.sample_to_beat(o.end_beat * sr),
        peak_dbtp=o.peak_dbtp,
        dominant_band=o.dominant_band,
        attribution=list(o.attribution),
    )


def _modal_rt60(values: Sequence[float]) -> float:
    """Most frequently-declared RT60; ties resolve to the smallest for
    determinism. Picks the value to measure against when sends into one return
    declare different RT60s (the disagreement is surfaced separately)."""
    counts = Counter(values)
    top = max(counts.values())
    return min(v for v, c in counts.items() if c == top)


def _run_reverb_verifications(
    *,
    capture: CaptureSet,
    declared_sends: Sequence[DeclaredReverbSend],
    beat_map: BeatSampleMap,
) -> tuple[list[ReverbVerification], list[dict]]:
    """Measure RT60 once per RETURN from its captured ring-out.

    RT60 is a property of a return's reverb *device*, so declared sends are
    GROUPED by target return (a return fed by N sends declares RT60 N times,
    redundantly). Each return is measured once, dry-source-free, from its own
    decay tail — sidestepping the multi-source ill-posedness of the old
    single-dry deconvolution. Sends into one return that declare DIFFERENT
    RT60s are a contradiction (one device, one decay time) surfaced via
    ``conflicting_declarations``.

    The decay region is the captured ring-out after the arrangement's dry input
    stops (``capture.stop_at_beat`` → end). A capture made without ring-out
    capture has no such region, so ``measure_return_rt60`` returns an honest
    ``sufficient_tail=False`` verdict (NaN RT60) — never a fabricated number.

    Empty ``declared_sends`` produces a structured skip record so the report
    explains *why* the section is empty (rather than ambiguously "no reverbs
    verified — analyzed OK or no intent declared?").
    """
    if not declared_sends:
        skipped: list[dict] = [{
            "kind": "reverb_verification",
            "reason": (
                "no declared RT60 sends — call "
                "set_send_intended_rt60(from_track_id, to_return_id, "
                "intended_rt60_s=<seconds>) on each reverb-bus send to "
                "declare composer intent the analyzer can verify"
            ),
        }]
        return [], skipped

    returns_by_id = {r.track_id: r for r in capture.returns}

    # Group declared sends by target return, preserving first-seen order.
    by_return: "dict[str, list[DeclaredReverbSend]]" = {}
    for send in declared_sends:
        by_return.setdefault(send.wet_return_track_id, []).append(send)

    verifications: list[ReverbVerification] = []
    skipped = []
    # The dry input stops at the arrangement end; the ring-out follows.
    stop_sample = beat_map.beat_to_sample(capture.stop_at_beat)

    for return_id, sends in by_return.items():
        ret = returns_by_id.get(return_id)
        if ret is None:
            skipped.append({
                "kind": "reverb_verification",
                "reason": (
                    f"declared return {return_id} not in capture "
                    f"(returns present: {sorted(returns_by_id)})"
                ),
            })
            continue

        declared_values = [s.declared_rt60_s for s in sends]
        distinct = sorted(set(declared_values))
        conflicting = tuple(distinct) if len(distinct) > 1 else ()

        onset = find_decay_onset(
            ret.audio,
            search_start_sample=stop_sample,
            sample_rate=capture.sample_rate,
        )
        verification = measure_return_rt60(
            ret.audio,
            sample_rate=capture.sample_rate,
            decay_onset_sample=onset,
            declared_rt60_s=_modal_rt60(declared_values),
            return_track_id=return_id,
        )
        verifications.append(replace(
            verification,
            contributing_track_ids=tuple(s.dry_track_id for s in sends),
            conflicting_declarations=conflicting,
        ))
    return verifications, skipped


def _run_automation_verifications(
    *,
    capture: CaptureSet,
    declared_envelopes: Sequence[DeclaredEnvelope],
    beat_map: BeatSampleMap,
    stem_gains: Mapping[str, float],
) -> tuple[list[EnvelopeVerification], list[dict]]:
    """Verify each declared automation envelope was realized in the audio.

    Looks each envelope's target surface up in the capture, windows it around
    every value-changing breakpoint, and confirms the expected change (timbre
    shift for device_parameter, level step for send_level, master-bus level /
    L−R balance step for mixer_volume / mixer_pan — AUD-3F8M; pan's
    prediction uses the stem's static fader gain from ``stem_gains``, unity
    when unknown).

    Empty ``declared_envelopes`` produces a structured skip teaching the caller
    to author automation — symmetric with the reverb and section skips.
    """
    if not declared_envelopes:
        return [], [{
            "kind": "automation_verification",
            "reason": (
                "no declared automation envelopes — author time-varying intent "
                "(create_enum_envelope for a device-parameter flip, "
                "generators.envelopes.volume_swell / a dynamic send) so the "
                "analyzer can confirm it was realized in the render"
            ),
        }]

    surfaces = {s.track_id: s for s in (*capture.stems, *capture.returns)}
    verifications: list[EnvelopeVerification] = []
    skipped: list[dict] = []
    for env in declared_envelopes:
        surface = surfaces.get(env.target_surface_id)
        if surface is None:
            skipped.append({
                "kind": "automation_verification",
                "reason": (
                    f"declared envelope target {env.target_surface_id} "
                    f"({env.target_kind}) not in capture (surfaces present: "
                    f"{sorted(surfaces)})"
                ),
            })
            continue
        verifications.extend(verify_envelope_realization(
            env, surface.audio,
            sample_rate=capture.sample_rate,
            beat_map=beat_map,
            master_audio=capture.master.audio,
            stem_gain=stem_gains.get(env.target_surface_id, 1.0),
        ))
    return verifications, skipped


def _measure_sections(
    *,
    capture: CaptureSet,
    sections: Sequence[SectionWindow],
    beat_map: BeatSampleMap,
    analyze_masking: bool = False,
    analyze_timing: bool = False,
    analyze_cross_rhythm: bool = False,
    stem_gains: Mapping[str, float] = {},
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
            beat_map=beat_map,
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
        # A covered-but-tiny overlap (a section overhanging the capture by a
        # few hundred samples, or a genuinely short section at fast tempo)
        # would make measure_loudness raise — which would discard the whole
        # report. Record a skip instead, same discipline as the no-overlap
        # case. The threshold is loudness.py's BS.1770 400 ms block minimum.
        overlap_s = (sl.end_sample - sl.start_sample) / capture.sample_rate
        if overlap_s < MIN_LOUDNESS_DURATION_S:
            skipped.append({
                "kind": "section_windowed",
                "reason": (
                    f"section {window.name!r} overlaps the captured window "
                    f"by only {overlap_s * 1000:.0f} ms — shorter than the "
                    f"{MIN_LOUDNESS_DURATION_S * 1000:.0f} ms BS.1770 block "
                    f"minimum, so LUFS can't be measured for it. Capture the "
                    f"full section span or merge it with an adjacent section"
                ),
            })
            continue
        sliced_stems = [
            (s.track_id, slice_audio(s.audio, sl)) for s in capture.stems
        ]
        masking_pairs = []
        bed_masking = []
        if analyze_masking:
            # Reconstruct mix-level before masking (captures are pre-fader, F1).
            # Empty stem_gains is a no-op, so synthetic fixtures are unaffected.
            mres = analyze_masking_window(
                apply_stem_gains(sliced_stems, stem_gains),
                capture.sample_rate,
                reporting_floor=_MASKING_REPORTING_FLOOR,
            )
            masking_pairs = mres.pairs
            bed_masking = mres.bed
        # Timing and cross-rhythm share the window's grid geometry and C7's
        # swing read, so compute the geometry once and thread it to both. The
        # swing ratios feed cross-rhythm's swing-deference (its one cross-module
        # input) — so even when the timing report is off, an enabled
        # cross-rhythm pass still gets the swing context it needs.
        timing = []
        cross_rhythm = []
        phasing = []
        polymeter = []
        onset_density = None
        if analyze_timing or analyze_cross_rhythm:
            geom = _window_grid_geometry(sl, capture, beat_map)
            if geom is not None:
                start_beat, bpm = geom
                # Onset density (ARR-7M3D's second energy correlate) shares the
                # window's grid geometry. window_beats = the covered slice length
                # in beats at the window's effective tempo. Level-blind, so it
                # reads the raw sliced stems (no stem_gains), like the timing pass.
                window_beats = (
                    (sl.end_sample - sl.start_sample) / capture.sample_rate
                    * bpm / 60.0
                )
                onset_density = section_onset_density(
                    sliced_stems, capture.sample_rate, window_beats=window_beats,
                )
                timing_parts = _all_window_timing(
                    sliced_stems, capture, start_beat, bpm,
                )
                if analyze_timing:
                    timing = [
                        p for p in timing_parts
                        if p.confidence >= _TIMING_MIN_CONFIDENCE
                    ]
                if analyze_cross_rhythm:
                    swing_ratios = {p.track_id: p.swing_ratio for p in timing_parts}
                    cross_rhythm = _measure_window_cross_rhythm(
                        sliced_stems, capture, start_beat, bpm, swing_ratios,
                    )
                    phasing = _measure_window_phasing(
                        sliced_stems, capture, start_beat, bpm,
                    )
                    polymeter = _measure_window_polymeter(
                        sliced_stems, capture, start_beat, bpm,
                    )
        per_section.append(SectionMetrics(
            section_name=window.name,
            section_id=window.section_id,
            start_beat=window.start_beat,
            end_beat=window.end_beat,
            master=_measure_window(capture.master, sl),
            stems=[_measure_window(s, sl) for s in capture.stems],
            returns=[_measure_window(r, sl) for r in capture.returns],
            attribution=band_attribution(sliced_stems, capture.sample_rate),
            masking=masking_pairs,
            bed_masking=bed_masking,
            timing=timing,
            cross_rhythm=cross_rhythm,
            phasing=phasing,
            polymeter=polymeter,
            onset_density=onset_density,
        ))

    return per_section, skipped


def _realize_energy(
    declared_energy: Sequence[SectionEnergy],
    per_section: Sequence[SectionMetrics],
) -> tuple["EnergyRealization | None", list[dict]]:
    """Build the energy-realization read from the declared curve + measured
    per-section correlates (ARR-7M3D).

    The measured correlates are lifted from ``per_section``, keyed by
    ``start_beat`` (the lens join key — NOT name): LUFS-S median loudness and
    onset density. The lens itself (``energy.realize_energy``) is pure and
    DB-agnostic; this orchestrator only assembles its inputs and turns the
    "no energy declared / too few sections" case into a structured
    ``skipped_analyses`` entry — never a fabricated ρ.
    """
    declared = list(declared_energy)
    if not declared:
        return None, [{
            "kind": "energy_realization",
            "reason": (
                "no per-section energy declared — author energy via "
                "Arrangement.section(energy=) (or create_section(energy=)) so "
                "the lens can rank declared intensity intent against the "
                "rendered per-section intensity (LUFS-S + onset density)"
            ),
        }]

    loudness_by_beat: dict[float, "float | None"] = {}
    density_by_beat: dict[float, "float | None"] = {}
    centroid_by_beat: dict[float, "float | None"] = {}
    for sm in per_section:
        loudness_by_beat[sm.start_beat] = sm.master.loudness.lufs_s_median
        density_by_beat[sm.start_beat] = sm.onset_density
        # Section brightness (AUD-8T3K, DR-3): the section MASTER's spectral
        # centroid. None when no timbre was measured (silent window) — the lens
        # excludes + names it like any unavailable correlate (W2).
        centroid_by_beat[sm.start_beat] = (
            sm.master.timbre.spectral_centroid_hz
            if sm.master.timbre is not None
            else None
        )

    measured = {
        LOUDNESS: loudness_by_beat,
        ONSET_DENSITY: density_by_beat,
        SPECTRAL_CENTROID: centroid_by_beat,
    }
    realization = realize_energy(
        declared, measured,
        surfacing_floor=_ENERGY_INVERSION_SURFACING_FLOOR,
    )
    if realization is None:
        return None, [{
            "kind": "energy_realization",
            "reason": (
                f"only {len(declared)} energy-declared section(s) — Spearman "
                f"rank-correlation needs at least 2 to rank declared intensity "
                f"against measured intensity"
            ),
        }]
    return realization, []


def _window_grid_geometry(
    sl: WindowSlice,
    capture: CaptureSet,
    beat_map: BeatSampleMap,
) -> tuple[float, float] | None:
    """The window's ``(start_beat, bpm)`` grid geometry, or ``None`` if unusable.

    Derives the song-absolute beat at the window's first sample and the
    effective (constant) tempo across the window's covered samples from the
    shared :class:`BeatSampleMap`. A degenerate map or a zero-length window
    yields ``None`` rather than a divide-by-zero — the onset analyzers then skip
    the window and the section still reports its other metrics. Shared by the
    timing and cross-rhythm passes so they measure on the same grid.
    """
    if beat_map.degenerate:
        return None
    start_beat = beat_map.sample_to_beat(sl.start_sample)
    end_beat = beat_map.sample_to_beat(sl.end_sample)
    span_beats = end_beat - start_beat
    span_s = (sl.end_sample - sl.start_sample) / capture.sample_rate
    if span_beats <= 0 or span_s <= 0:
        return None
    return start_beat, span_beats / span_s * 60.0


def _all_window_timing(
    sliced_stems: list[tuple[str, "np.ndarray"]],
    capture: CaptureSet,
    start_beat: float,
    bpm: float,
) -> list[PartTiming]:
    """Every part's onset-vs-grid timing over one window (no confidence floor).

    Returns the raw per-part timing — the caller applies the reporting floor for
    the timing field, and reads ``swing_ratio`` off every part (floor-free) to
    feed cross-rhythm's swing-deference. Onset timing is level-blind (gain
    doesn't move onsets), so this runs on the raw pre-fader slices — no
    ``stem_gains`` reconstruction, unlike masking.
    """
    return analyze_timing_window(
        sliced_stems,
        capture.sample_rate,
        window_start_beat=start_beat,
        bpm=bpm,
    ).parts


def _measure_window_cross_rhythm(
    sliced_stems: list[tuple[str, "np.ndarray"]],
    capture: CaptureSet,
    start_beat: float,
    bpm: float,
    swing_ratios: "Mapping[str, float | None]",
) -> list[PartCrossRhythm]:
    """Per-part cross-rhythm read over one section window.

    Level-blind like timing (gain doesn't move onsets — no ``stem_gains``).
    ``swing_ratios`` is C7's per-part swing read, threaded through for the
    swing-deference step. Parts below the confidence floor (sparse, or no clean
    pulse) are dropped — same integration-level gate as the timing floor; the
    interpreter grades what survives against intent.
    """
    cres = analyze_cross_rhythm_window(
        sliced_stems,
        capture.sample_rate,
        window_start_beat=start_beat,
        bpm=bpm,
        swing_ratios=swing_ratios,
    )
    return [
        p for p in cres.parts if p.confidence >= _CROSS_RHYTHM_MIN_CONFIDENCE
    ]


def _measure_window_phasing(
    sliced_stems: list[tuple[str, "np.ndarray"]],
    capture: CaptureSet,
    start_beat: float,
    bpm: float,
) -> list[Phasing]:
    """Two-part phasing over one section window (the cross-rhythm two-part pass).

    Level-blind like timing/cross-rhythm (gain doesn't move onsets). Surfaces
    only pairs whose relative offset drifts both fast enough (above the drift
    floor — locked or constant-offset pairs sit below) and cleanly enough (above
    the confidence floor). Both gates are required; see the floor constants.
    """
    pres = analyze_phasing_window(
        sliced_stems,
        capture.sample_rate,
        window_start_beat=start_beat,
        bpm=bpm,
    )
    return [
        p for p in pres.pairs
        if abs(p.drift_beats_per_cycle) >= _PHASING_DRIFT_FLOOR_BEATS
        and p.confidence >= _PHASING_MIN_CONFIDENCE
    ]


def _measure_window_polymeter(
    sliced_stems: list[tuple[str, "np.ndarray"]],
    capture: CaptureSet,
    start_beat: float,
    bpm: float,
) -> list[Polymeter]:
    """Two-part polymeter over one section window (different cell lengths).

    Level-blind like the other rhythm passes. Surfaces only pairs whose two
    cells both resolved above the confidence floor (the weaker part's accent-
    autocorrelation peak). Equal-velocity parts surface no cell, so no pair.
    """
    pres = analyze_polymeter_window(
        sliced_stems,
        capture.sample_rate,
        window_start_beat=start_beat,
        bpm=bpm,
    )
    return [
        p for p in pres.pairs if p.confidence >= _POLYMETER_MIN_CONFIDENCE
    ]


def _measure_window(surface: Surface, window_slice: WindowSlice) -> StemMetrics:
    """Loudness of one surface over a clamped section window."""
    sliced = slice_audio(surface.audio, window_slice)
    loudness = measure_loudness(sliced, sr=surface.sample_rate)
    return StemMetrics(
        track_id=surface.track_id,
        surface_kind=surface.surface_kind,
        surface_name=surface.surface_name,
        loudness=loudness,
        timbre=measure_timbre(sliced, surface.sample_rate),
        stereo=measure_stereo(sliced),
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
    automation: Sequence[EnvelopeVerification] = (),
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
        if r.conflicting_declarations:
            findings.append(Finding(
                kind="reverb_conflicting_declaration",
                severity="warning",
                subject=r.return_track_id,
                metric="rt60_s",
                observed=r.declared_rt60_s,
                expected=r.declared_rt60_s,
                db_reference=(
                    "sends into this return declare different RT60s "
                    f"{list(r.conflicting_declarations)} — one reverb device "
                    "has one decay time; measured against the most-declared "
                    f"value ({r.declared_rt60_s})"
                ),
            ))
        if not r.sufficient_tail:
            # Two distinct failure modes need two distinct remedies — the old
            # one-size message ("re-render with a larger ring_out_beats") is
            # wrong for the second. tail_span_db tells them apart:
            #   • ~0 dB  → no decaying tail captured at all: the ring-out was
            #     too short, OR the dry-stop landed in trailing dead-air where
            #     the reverb had already decayed (the render now anchors the
            #     dry-stop to content end, so the latter should be rare). More
            #     ring_out_beats is the right fix.
            #   • >0 dB but too shallow to fit → a tail WAS captured, but the
            #     return's wet path is too quiet to decay measurably above the
            #     capture's noise floor. A longer ring-out adds TIME, not LEVEL
            #     — it won't help. Raise the send into the return, or verify the
            #     return in isolation (solo'd).
            if r.tail_span_db <= 0.0:
                reason = (
                    "no reverb ring-out captured (clean decay span "
                    f"{r.tail_span_db:.1f} dB) — re-render with a larger "
                    "ring_out_beats; if the ring-out is already long, the "
                    "dry-stop may have landed past the song's content"
                )
            else:
                reason = (
                    f"the captured ring-out affords only {r.tail_span_db:.1f} dB "
                    "of clean decay above the noise floor — too little to fit a "
                    "reliable RT60. The return's wet path is too quiet; raise its "
                    "send level or verify the return in isolation. A longer "
                    "ring_out_beats won't help (it adds time, not level)"
                )
            findings.append(Finding(
                kind="reverb_insufficient_tail",
                severity="warning",
                subject=r.return_track_id,
                metric="tail_span_db",
                observed=r.tail_span_db,
                expected=r.declared_rt60_s,
                db_reference=reason,
            ))
            continue
        if not r.within_tolerance:
            findings.append(Finding(
                kind="reverb_out_of_tolerance",
                severity="warning",
                subject=r.return_track_id,
                metric="rt60_s",
                observed=r.measured_rt60_s,
                expected=r.declared_rt60_s,
                db_reference=None,
            ))

    for e in automation:
        if e.measurable and not e.realized:
            findings.append(Finding(
                kind="automation_not_realized",
                severity="warning",
                subject=f"{e.target_surface_id} {e.parameter_path or e.target_kind}",
                metric=e.metric,
                observed=e.after,
                expected=e.before,
                db_reference=e.note,
            ))

    return findings


__all__ = [
    "DeclaredEnvelope",
    "DeclaredReverbSend",
    "SectionWindow",
    "analyze_mix",
]
