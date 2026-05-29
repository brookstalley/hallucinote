"""Per-part cross-rhythm / subdivision analysis — naming the grid a part is on.

The read-side sibling of the timing analyzer (``timing.py``, C7) and the
counterpart to the question it leaves open. C7 measures a part's onset
deviation from a single straight grid (16th subdivisions of the known beat);
when a part plays *against* the grid — a 3-over-2 hemiola, a 4-against-3, a
quintuplet run — C7 honestly reports low confidence / high stdev ("this isn't
on the straight grid") but cannot say *what it is on*. This module closes that:
it recovers the part's own base pulse and names the relationship.

This is PURE DSP and DB-agnostic — it operates on windowed stem audio plus the
window's grid geometry (start beat + tempo), exactly like ``masking`` and
``timing``. The corpus *defines* correctness (there is no labelled polyrhythm
ground truth for real audio); see ``tests/unit/audio/test_cross_rhythm.py``.

Pipeline per window, per stem (``docs/polyrhythms.md`` §3 — the validated
algorithm):

  1. **Detect onsets** — shared front-end (``onsets.py``), same as C7.
  2. **Base period P** = MODE of inter-onset intervals (beats). The modal
     adjacent interval tracks the true pulse; rests/skips are minority large
     outliers that don't move the mode (a median would be dragged). Refined by
     averaging the IOIs clustered around the modal value. Resolution-free.
  3. **Density floor** — P < 1/8 beat (> 8 hits/beat) → ``roll`` / tremolo,
     low-confidence; no ratio named (buzz rolls land here).
  4. **Rational approximation** — P ≈ M/N, denominator N ≤ 8 (continued
     fraction). An IOI of M/N beats means N onsets span M beats → an
     **N-against-M** cross-rhythm; M=1 is a plain **N-per-beat** subdivision.
  5. **Grid-fit on P** — fold onsets onto a free-offset P-periodic grid; the
     residual stdev (tightness) and occupancy (filled / expected pulse slots)
     drive confidence — NOT a raw-IOI variance, which rests break.
  6. **Rubato gate** — a strong monotonic IOI trend (|corr| > 0.6) with a poor
     constant-period fit → ``rubato``; the tempo is moving, not a polyrhythm.
  7. **Swing deference** — a triplet (3/beat) at partial occupancy whose C7
     ``swing_ratio`` sits in the swing band (≈1.3–2.3) → ``swing(see-timing)``,
     not a triplet cross-rhythm. C8 composes with C7 instead of double-reporting.
  8. **Verdict + confidence** — a clean ratio with M>1 or a non-binary
     N ∈ {3,5,6,7} → ``cross-rhythm``; N ∈ {1,2,4,8}, M=1 → ``subdivision``;
     else ``low-confidence``.

Honest limitations (``docs/polyrhythms.md`` §5), every one resolving to an
explicit low-confidence / rubato / roll verdict rather than a confident wrong
answer: additive grouping (3+3+2) is not decoded; bar-level polymeter is not
detected; rubato within a window is flagged not tracked; one rhythmic line per
stem; sparse parts can't be judged; onset detection is timbre-dependent; the
swing/triplet boundary is a heuristic; ratios are capped at denominator 8.

Citation: Bello et al. (2005) "A Tutorial on Onset Detection in Music Signals".
"""
from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from typing import Mapping, Sequence

import numpy as np

from .onsets import (
    DEFAULT_MIN_ONSET_SEPARATION_BEATS,
    dedup_onsets,
    detect_onset_samples,
    to_mono,
)
from .report import PartCrossRhythm, Phasing

# Largest denominator in the rational approximation P ≈ M/N. 8 covered every
# musical case in the validation corpus; raising it trades naming reach for
# false-precision risk (9:8, nested ratios round to the nearest representable).
_MAX_DENOMINATOR = 8

# Density floor (beats). A base period below this — more than 8 onsets per beat
# — is a roll/tremolo, not a nameable pulse. A septuplet (P ≈ 0.143) sits just
# above it; a buzz roll falls below.
_DENSITY_FLOOR_BEATS = 1.0 / 8.0

# Below this many onsets a part has too few inter-onset intervals to assert a
# pulse — confidence is scaled toward zero (a one-drop kick can't be judged).
_MIN_ONSETS = 5

# Half-width (beats) of the cluster around the modal IOI used to estimate the
# base period. Wide enough to absorb onset-detection jitter (~0.01–0.02 beat),
# narrow enough to keep a quintuplet (0.2) distinct from 16ths (0.25).
_MODE_CLUSTER_BEATS = 0.035

# Grid-fit residual stdev (beats) at which tightness confidence reaches zero.
# A part whose onsets scatter this far from a consistent P-periodic grid is not
# a trustworthy pulse reading (additive grouping, a smeared ensemble). ~0.05
# beat ≈ 25 ms @ 120 bpm.
_TIGHTNESS_SCALE_BEATS = 0.05

# |corr(IOI index, IOI value)| above this, combined with a poor constant-period
# fit, means the tempo is trending (accel/rit) — rubato, not a polyrhythm.
_RUBATO_CORR = 0.6

# Below this occupancy a triplet read is "partial" — the gap pattern of swung
# 8ths rather than a filled triplet. Combined with a swing-band swing_ratio,
# the read defers to C7.
_SWING_PARTIAL_OCCUPANCY = 0.85
_SWING_BAND = (1.3, 2.3)

# Non-binary subdivisions (and any M>1 ratio) fight the straight binary grid;
# these N values mark a cross-rhythm even when M=1 (triplet, quintuplet, ...).
_NON_BINARY_N = frozenset({3, 5, 6, 7})

# Phasing: length (beats) of one analysis cycle. The window is sliced into
# cycles and the mean inter-part offset is sampled per cycle; the drift across
# cycles is the phasing signal. 4 beats ≈ a bar — the natural pattern-repeat
# unit, and what ``drift_beats_per_cycle`` is reported against.
_PHASING_CYCLE_BEATS = 4.0

# Fewest cycles with a measurable offset before a drift trend can be asserted.
# Two points define any line; three is the minimum that can be NON-monotonic,
# so it's the floor for trusting a monotonic-drift claim.
_PHASING_MIN_CYCLES = 3


@dataclass(frozen=True)
class PhasingResult:
    """Two-part phasing relationships for one (pre-sliced) window."""
    pairs: list[Phasing]


@dataclass(frozen=True)
class CrossRhythmResult:
    """Per-part cross-rhythm reads for one (pre-sliced) window."""
    parts: list[PartCrossRhythm]


def analyze_cross_rhythm_window(
    stem_segments: Sequence[tuple[str, np.ndarray]],
    sample_rate: int,
    *,
    window_start_beat: float,
    bpm: float,
    swing_ratios: "Mapping[str, float | None] | None" = None,
    min_onset_separation_beats: float = DEFAULT_MIN_ONSET_SEPARATION_BEATS,
) -> CrossRhythmResult:
    """Name each part's base pulse over a single window.

    ``stem_segments`` entries are ``(track_id, audio)`` (mono ``(n,)`` or stereo
    ``(n, 2)``); the caller slices each stem to the section window first.
    ``window_start_beat`` / ``bpm`` describe the window's constant-tempo grid —
    only ``bpm`` actually matters here (it maps samples→beats); the start beat
    is carried for parity with the timing analyzer and future absolute-phase
    use. ``swing_ratios`` maps ``track_id`` → C7 ``swing_ratio`` (or ``None``)
    and drives the swing-deference step (the one cross-module input).

    Returns one :class:`PartCrossRhythm` per stem that produced any onsets,
    sorted by ``confidence`` descending. Stems with no onsets are omitted (a
    part that didn't play has no rhythm to read). No confidence floor is applied
    here — that integration-level filtering is the orchestrator's job (mirrors
    masking's ``reporting_floor`` and timing's confidence gate).
    """
    if bpm <= 0 or sample_rate <= 0:
        return CrossRhythmResult(parts=[])
    swing_ratios = swing_ratios or {}
    beats_per_sample = bpm / 60.0 / sample_rate

    parts: list[PartCrossRhythm] = []
    for track_id, audio in stem_segments:
        mono = to_mono(audio)
        onset_samples = detect_onset_samples(mono, sample_rate)
        if onset_samples.size == 0:
            continue
        onset_beats = window_start_beat + onset_samples * beats_per_sample
        onset_beats = dedup_onsets(onset_beats, min_onset_separation_beats)
        parts.append(_part_cross_rhythm(
            track_id, onset_beats, swing_ratios.get(track_id),
        ))

    parts.sort(key=lambda p: p.confidence, reverse=True)
    return CrossRhythmResult(parts=parts)


def analyze_phasing_window(
    stem_segments: Sequence[tuple[str, np.ndarray]],
    sample_rate: int,
    *,
    window_start_beat: float,
    bpm: float,
    cycle_beats: float = _PHASING_CYCLE_BEATS,
    min_onset_separation_beats: float = DEFAULT_MIN_ONSET_SEPARATION_BEATS,
) -> PhasingResult:
    """Detect Reich-style phasing between every pair of parts over one window.

    Phasing is two parts playing the same figure at fractionally different
    tempi: one slides against the other so their relative alignment drifts
    monotonically while each stays individually steady. We slice the window into
    ``cycle_beats``-long cycles, measure the mean nearest-onset offset of B
    relative to A per cycle, and fit the trend — a strong monotonic drift is
    phasing (``docs/polyrhythms.md`` §3 "two-part pass").

    Returns a :class:`Phasing` per unordered pair that produced enough
    co-occurring onsets to fit a trend, with the measured drift rate and a
    confidence from the trend's monotonicity. Locked parts read ≈ 0 drift; the
    integration layer floors out the non-phasing pairs (mirrors masking's
    ``reporting_floor``). Same caveat as the dataclass: nearest-onset matching
    wraps once accumulated drift exceeds half a pulse, so this reads the onset
    of a phase relationship, not its full trajectory.
    """
    if bpm <= 0 or sample_rate <= 0:
        return PhasingResult(pairs=[])
    beats_per_sample = bpm / 60.0 / sample_rate

    # One onset pass per part, shared across all pairs.
    onsets_by_part: list[tuple[str, np.ndarray]] = []
    for track_id, audio in stem_segments:
        mono = to_mono(audio)
        onset_samples = detect_onset_samples(mono, sample_rate)
        if onset_samples.size == 0:
            continue
        beats = window_start_beat + onset_samples * beats_per_sample
        onsets_by_part.append((track_id, dedup_onsets(beats, min_onset_separation_beats)))

    pairs: list[Phasing] = []
    for i in range(len(onsets_by_part)):
        for j in range(i + 1, len(onsets_by_part)):
            id_a, onsets_a = onsets_by_part[i]
            id_b, onsets_b = onsets_by_part[j]
            ph = _phasing_for_pair(id_a, onsets_a, id_b, onsets_b, cycle_beats)
            if ph is not None:
                pairs.append(ph)

    pairs.sort(key=lambda p: p.confidence, reverse=True)
    return PhasingResult(pairs=pairs)


def _phasing_for_pair(
    id_a: str,
    onsets_a: np.ndarray,
    id_b: str,
    onsets_b: np.ndarray,
    cycle_beats: float,
) -> Phasing | None:
    """Fit the per-cycle inter-part offset trend; return a :class:`Phasing` or None.

    For each cycle, the offset is the MEDIAN signed distance from each B onset to
    its nearest A onset (B − A). A linear fit of offset vs cycle-centre beat
    gives the drift rate (scaled to one cycle) and the trend strength
    (|correlation|) → confidence. Returns ``None`` when there aren't enough
    populated cycles to assert a trend (the caller skips the pair).

    Only B onsets inside A's onset span are matched: a faster part overruns the
    slower part's last onset, and those overhanging onsets would match back to
    A's final onset with a large wrong-sign offset that poisons the cycle. The
    median (over the mean) further shrugs off the odd mismatched onset.
    """
    if onsets_a.size == 0 or onsets_b.size == 0 or cycle_beats <= 0:
        return None
    a_lo, a_hi = float(onsets_a[0]), float(onsets_a[-1])
    matchable_b = onsets_b[(onsets_b >= a_lo) & (onsets_b <= a_hi)]
    if matchable_b.size == 0:
        return None
    lo = float(min(onsets_a[0], matchable_b[0]))
    hi = float(max(onsets_a[-1], matchable_b[-1]))
    n_cycles = int((hi - lo) // cycle_beats) + 1
    if n_cycles < _PHASING_MIN_CYCLES:
        return None

    centres: list[float] = []
    offsets: list[float] = []
    for c in range(n_cycles):
        c_lo = lo + c * cycle_beats
        c_hi = c_lo + cycle_beats
        b_in = matchable_b[(matchable_b >= c_lo) & (matchable_b < c_hi)]
        if b_in.size == 0:
            continue
        # Nearest A onset to each B onset → signed offset (B leads = negative).
        nearest_idx = np.abs(onsets_a[None, :] - b_in[:, None]).argmin(axis=1)
        offset = float(np.median(b_in - onsets_a[nearest_idx]))
        centres.append(c_lo + cycle_beats / 2.0)
        offsets.append(offset)

    if len(offsets) < _PHASING_MIN_CYCLES:
        return None

    centres_arr = np.asarray(centres, dtype=np.float64)
    offsets_arr = np.asarray(offsets, dtype=np.float64)
    # Slope (beats of offset per beat of time) via least squares; ×cycle_beats
    # to report drift per cycle. A flat offset (locked parts) → slope ≈ 0.
    slope = float(np.polyfit(centres_arr, offsets_arr, 1)[0])
    drift_per_cycle = slope * cycle_beats
    # Monotonicity: |corr| of offset vs time. Strong = a clean phase march;
    # weak = noise (two unrelated rhythms, or locked parts with jitter).
    if np.std(offsets_arr) == 0.0:
        confidence = 0.0
    else:
        confidence = abs(float(np.corrcoef(centres_arr, offsets_arr)[0, 1]))
    return Phasing(
        track_a=id_a,
        track_b=id_b,
        drift_beats_per_cycle=drift_per_cycle,
        confidence=confidence,
    )


# --------------------------------------------------------------------------- #
# Core per-part computation
# --------------------------------------------------------------------------- #

def _part_cross_rhythm(
    track_id: str,
    onset_beats: np.ndarray,
    swing_ratio: float | None,
) -> PartCrossRhythm:
    """Turn one part's absolute-beat onsets into a neutral cross-rhythm read."""
    n = int(onset_beats.size)
    iois = np.diff(onset_beats)

    # Too few intervals to assert any pulse — honest low-confidence (limit #5).
    if iois.size < 2:
        period = float(iois[0]) if iois.size == 1 else 0.0
        return PartCrossRhythm(
            track_id=track_id,
            pulse_ratio=None,
            against_meter=False,
            base_period_beats=period,
            occupancy=0.0,
            confidence=0.0,
            verdict="low-confidence",
        )

    period = _base_period(iois)
    count_factor = min(n / float(_MIN_ONSETS), 1.0)

    # Density floor — a pulse faster than 8/beat is a roll/tremolo, not a
    # nameable ratio (buzz rolls land here). Reported before fitting a grid.
    if period < _DENSITY_FLOOR_BEATS:
        return PartCrossRhythm(
            track_id=track_id,
            pulse_ratio=None,
            against_meter=False,
            base_period_beats=period,
            occupancy=0.0,
            confidence=min(0.2, count_factor * 0.2),
            verdict="roll",
        )

    drift_stdev = _grid_fit_stdev(onset_beats, period)
    occupancy = _occupancy(onset_beats, period)
    tightness_factor = max(0.0, 1.0 - drift_stdev / _TIGHTNESS_SCALE_BEATS)
    confidence = count_factor * tightness_factor

    # Rubato gate — a strong monotonic IOI trend with a poor constant-period
    # fit is a moving tempo, not a polyrhythm. Flag it (never mislabel as a
    # bizarre ratio); confidence stays low because the fit is poor.
    if _is_rubato(iois, drift_stdev):
        return PartCrossRhythm(
            track_id=track_id,
            pulse_ratio=None,
            against_meter=False,
            base_period_beats=period,
            occupancy=occupancy,
            confidence=min(confidence, 0.2),
            verdict="rubato",
        )

    m, denom = _rational(period)  # period ≈ m / denom (denom = N onsets / M=m beats)
    against_meter = (m > 1) or (denom in _NON_BINARY_N)

    # Swing deference — a partially-filled triplet whose C7 swing_ratio is in
    # the swing band is swung 8ths, not a triplet cross-rhythm. Defer to C7.
    if (
        m == 1 and denom == 3
        and occupancy < _SWING_PARTIAL_OCCUPANCY
        and swing_ratio is not None
        and _SWING_BAND[0] <= swing_ratio <= _SWING_BAND[1]
    ):
        return PartCrossRhythm(
            track_id=track_id,
            pulse_ratio=None,
            against_meter=False,
            base_period_beats=period,
            occupancy=occupancy,
            confidence=confidence,
            verdict="swing(see-timing)",
        )

    label = _label(m, denom)

    # A poor fit (no single clean pulse — additive grouping like 3+3+2) reads as
    # low-confidence honestly, with no ratio asserted.
    if confidence < 0.3:
        return PartCrossRhythm(
            track_id=track_id,
            pulse_ratio=None,
            against_meter=False,
            base_period_beats=period,
            occupancy=occupancy,
            confidence=confidence,
            verdict="low-confidence",
        )

    verdict = "cross-rhythm" if against_meter else "subdivision"
    return PartCrossRhythm(
        track_id=track_id,
        pulse_ratio=label,
        against_meter=against_meter,
        base_period_beats=period,
        occupancy=occupancy,
        confidence=confidence,
        verdict=verdict,
    )


def _base_period(iois: np.ndarray) -> float:
    """Base pulse period = mode of inter-onset intervals (beats).

    Robust to rests/skips: the modal adjacent interval is the true pulse, and a
    rest (an IOI at ~2×P) is a minority outlier that doesn't move the mode (a
    median would be dragged toward it). Found resolution-free by picking the IOI
    with the most neighbours within ``_MODE_CLUSTER_BEATS``, then averaging that
    cluster to refine the estimate (one bin around the modal bin).
    """
    iois = np.sort(iois)
    best_center = float(iois[0])
    best_count = -1
    for candidate in iois:
        lo = candidate - _MODE_CLUSTER_BEATS
        hi = candidate + _MODE_CLUSTER_BEATS
        count = int(np.count_nonzero((iois >= lo) & (iois <= hi)))
        if count > best_count:
            best_count = count
            best_center = float(candidate)
    cluster = iois[
        (iois >= best_center - _MODE_CLUSTER_BEATS)
        & (iois <= best_center + _MODE_CLUSTER_BEATS)
    ]
    return float(np.mean(cluster)) if cluster.size else best_center


def _grid_fit_stdev(onset_beats: np.ndarray, period: float) -> float:
    """Stdev (beats) of onset residuals against a free-offset P-periodic grid.

    Snaps each onset to the nearest multiple of ``period`` from the first onset
    (a free phase offset, so a constant displacement — C7's drift — doesn't
    spoil the fit), then measures the spread of the residuals. Low = onsets sit
    cleanly on the P-grid (a real pulse); high = no single clean pulse (additive
    grouping, a smeared ensemble).
    """
    if period <= 0:
        return float("inf")
    rel = onset_beats - onset_beats[0]
    k = np.round(rel / period)
    residual = rel - k * period
    return float(np.std(residual))


def _occupancy(onset_beats: np.ndarray, period: float) -> float:
    """Fraction of expected pulse slots that carry an onset (0..1).

    Expected slots = (span / P) + 1 over the onset span; occupancy = actual /
    expected, clamped to 1. A 3:2 that rests once a cycle reads ~0.82 — the
    holes are surfaced without losing the ratio (the mode is rest-robust).
    """
    if period <= 0:
        return 0.0
    span = float(onset_beats[-1] - onset_beats[0])
    expected = span / period + 1.0
    if expected <= 0:
        return 0.0
    return float(min(onset_beats.size / expected, 1.0))


def _is_rubato(iois: np.ndarray, drift_stdev: float) -> bool:
    """A strong monotonic IOI trend plus a poor constant-period fit = rubato.

    Accel/rit moves the tempo, so the IOIs trend with their index (corr → ±1)
    and no single period fits (high ``drift_stdev``). We require BOTH so a clean
    steady pulse with a stray slow drift isn't over-flagged.
    """
    if iois.size < 3:
        return False
    idx = np.arange(iois.size, dtype=np.float64)
    if np.std(iois) == 0.0:
        return False
    corr = float(np.corrcoef(idx, iois)[0, 1])
    return abs(corr) > _RUBATO_CORR and drift_stdev > _TIGHTNESS_SCALE_BEATS


def _rational(period: float) -> tuple[int, int]:
    """Approximate ``period`` as M/N with denominator N ≤ ``_MAX_DENOMINATOR``.

    Returns ``(M, N)`` in lowest terms. period = M/N beats means N onsets span M
    beats → an N-against-M cross-rhythm (M=1 → a plain N-per-beat subdivision).
    """
    frac = Fraction(period).limit_denominator(_MAX_DENOMINATOR)
    return frac.numerator, frac.denominator


def _label(m: int, denom: int) -> str:
    """Musician's-terms label for an M/N base period.

    ``M=1`` → ``"N/beat"`` (N-per-beat subdivision / tuplet); ``M>1`` →
    ``"N:M"`` (N-against-M cross-rhythm).
    """
    if m == 1:
        return f"{denom}/beat"
    return f"{denom}:{m}"


__all__ = [
    "CrossRhythmResult",
    "PhasingResult",
    "analyze_cross_rhythm_window",
    "analyze_phasing_window",
]
