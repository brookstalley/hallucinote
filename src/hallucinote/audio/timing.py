"""Per-part timing-deviation analysis — the read-side counterpart to `feel`.

The `feel` pattern generator (``generators/primitives.py``) BAKES push/pull/
swing into note timing at compose time. This module RECOVERS the feel actually
present in the captured audio: per part, per section, how far each onset sits
from the metric grid (push/drag), how tight that placement is, and whether the
off-beats swing. It feeds the holistic interpreter exactly like ``masking`` —
neutral measurement here, intent-grading there. See
``.prawduct/artifacts/intent-architecture.md`` (the DSP↔intent split this
mirrors).

This module is PURE DSP and DB-agnostic — it operates on whatever windowed
stem audio it is handed plus the window's grid geometry (start beat + tempo),
exactly like ``masking.analyze_masking_window``. That keeps it synthetic-
fixture-testable: the corpus *defines* correctness (there is no labelled
groove ground truth for real audio).

Pipeline per window, per stem:

  1. Mono-sum, detect onsets (librosa onset-strength + peak pick, backtracked
     to the local energy minimum for sample-accurate onset times).
  2. Map each onset sample → song-absolute beat via the window's constant tempo.
  3. ``drift`` = signed distance from each onset's beat to the nearest grid
     subdivision (default 16th). Mean = push (<0, ahead) / drag (>0, behind);
     stdev = tightness (lower = more machine-tight).
  4. ``swing_ratio`` = long:short ratio inferred from where off-beat 8ths land
     (straight ≈ 1.0, triplet ≈ 2.0). ``None`` when too few off-beat onsets.
  5. ``confidence`` (0..1) scales with onset count and timing tightness, so
     sustained pads (few onsets) and parts that don't track the grid (a loose
     ensemble, a cross-rhythm) read as low-trust rather than confident nonsense.

Honest limitations baked into the wording, not hidden (parallel to masking's
F3/F4 caveats):

* **Constant-tempo-within-window.** Drift is measured against a constant-tempo
  grid spanning the window; a tempo change *inside* a single section degrades
  accuracy. Variable-tempo-within-section is a follow-on.
* **Swing and micro-timing interact.** A heavily swung part reads as a small
  push/drag on a fine grid (the swung off-beat snaps toward an adjacent
  subdivision). ``swing_ratio`` is the disambiguating metric; the interpreter
  carries the caveat.
* **Onset detection is timbre-dependent.** Reliable on transient-rich parts
  (drums, plucked, staccato); sustained/legato material yields few clean
  onsets — surfaced as low ``confidence``, not corrected.
* **Level-blind by design.** Onset *times* don't move under gain, so (unlike
  masking) no pre-fader level reconstruction is needed.

Citation: Bello et al. (2005) "A Tutorial on Onset Detection in Music Signals"
(spectral-flux onset strength + peak picking — librosa's default).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np

from .report import PartTiming

# Grid resolution for drift snapping (beats). 0.25 = 16th note in 4/4 — the
# finest subdivision most rhythmic material lands on. A calibration parameter.
_DEFAULT_GRID_SUBDIVISION_BEATS = 0.25

# Swing is an 8th-note feel by convention; fixed regardless of the drift grid.
_SWING_GRID_BEATS = 0.5

# Below this many onsets the part's timing stats are too sparse to trust —
# confidence is scaled down toward zero.
_DEFAULT_MIN_ONSETS = 4

# Need at least this many off-beat 8th onsets before reporting a swing ratio
# (one or two could be noise; a groove asserts swing repeatedly).
_DEFAULT_MIN_OFFBEAT_ONSETS = 3

# Drift stdev (beats) at which confidence reaches zero. A part whose onsets
# scatter this far from a consistent grid placement (a loose ensemble, or — the
# useful signal — a part playing a *different* grid than the 4/4 subdivision,
# e.g. a 3:2 polyrhythm) is not a trustworthy straight-grid feel reading.
# ~0.08 beat ≈ 40 ms @ 120 bpm: well past tight, into genuinely-loose territory.
_STDEV_CONFIDENCE_SCALE_BEATS = 0.08

# Onsets closer than this are merged (one musical event → one onset). A hair
# under a 16th's eighth so it kills double-triggers (a kick's pitch sweep, a
# flam) without merging real adjacent subdivisions.
_DEFAULT_MIN_ONSET_SEPARATION_BEATS = 0.06

# librosa STFT hop for the onset envelope. 128 @ 48k ≈ 2.7 ms frames; with
# backtrack this sets onset-time resolution, which is load-bearing for timing
# (a coarse hop quantizes onsets and corrupts the drift/swing measurement).
_DEFAULT_HOP = 128


@dataclass(frozen=True)
class TimingWindowResult:
    """Per-part timing measurements for one (pre-sliced) window."""
    parts: list[PartTiming]


def analyze_timing_window(
    stem_segments: Sequence[tuple[str, np.ndarray]],
    sample_rate: int,
    *,
    window_start_beat: float,
    bpm: float,
    grid_subdivision_beats: float = _DEFAULT_GRID_SUBDIVISION_BEATS,
    min_onsets: int = _DEFAULT_MIN_ONSETS,
    min_offbeat_onsets: int = _DEFAULT_MIN_OFFBEAT_ONSETS,
    min_onset_separation_beats: float = _DEFAULT_MIN_ONSET_SEPARATION_BEATS,
    hop_length: int = _DEFAULT_HOP,
) -> TimingWindowResult:
    """Measure per-part onset-vs-grid timing over a single window.

    ``stem_segments`` entries are ``(track_id, audio)`` where audio is mono
    ``(n,)`` or stereo ``(n, 2)`` — the caller slices each stem to the section
    window first. ``window_start_beat`` is the song-absolute beat at local
    sample 0; ``bpm`` is the (constant) tempo across the window. The caller owns
    windowing + tempo geometry; this function is otherwise DB-agnostic, like the
    rest of the audio package.

    Returns a :class:`TimingWindowResult` with one :class:`PartTiming` per stem
    that produced at least one detectable onset (sorted by ``confidence``
    descending). Stems with no onsets are omitted — a part that didn't play in
    the window has no feel to recover. No part is dropped by a confidence floor
    here; that integration-level filtering is the orchestrator's job (mirrors
    masking's ``reporting_floor``).
    """
    if bpm <= 0 or sample_rate <= 0:
        return TimingWindowResult(parts=[])
    beats_per_sample = bpm / 60.0 / sample_rate

    parts: list[PartTiming] = []
    for track_id, audio in stem_segments:
        mono = _to_mono(audio)
        onset_samples = _detect_onset_samples(mono, sample_rate, hop_length)
        if onset_samples.size == 0:
            continue
        onset_beats = window_start_beat + onset_samples * beats_per_sample
        onset_beats = _dedup_onsets(onset_beats, min_onset_separation_beats)
        parts.append(_part_timing(
            track_id,
            onset_beats,
            grid_subdivision_beats=grid_subdivision_beats,
            min_onsets=min_onsets,
            min_offbeat_onsets=min_offbeat_onsets,
        ))

    parts.sort(key=lambda p: p.confidence, reverse=True)
    return TimingWindowResult(parts=parts)


# --------------------------------------------------------------------------- #
# Core per-part computation
# --------------------------------------------------------------------------- #

def _part_timing(
    track_id: str,
    onset_beats: np.ndarray,
    *,
    grid_subdivision_beats: float,
    min_onsets: int,
    min_offbeat_onsets: int,
) -> PartTiming:
    """Turn one part's absolute-beat onsets into neutral timing metrics."""
    # Drift = signed distance to the nearest grid subdivision, in beats. The
    # snap bounds drift to ±half a subdivision, so this measures micro-timing
    # *within* the grid (push/drag), not gross note displacement.
    nearest = np.round(onset_beats / grid_subdivision_beats) * grid_subdivision_beats
    drift = onset_beats - nearest
    mean_drift = float(np.mean(drift))
    drift_stdev = float(np.std(drift))

    # Confidence: scales with onset count (sparse → untrustworthy) and timing
    # consistency (tight cluster → a clear pulse to trust; high scatter → a
    # loose ensemble or a part on a *different* grid, e.g. a 3:2 polyrhythm read
    # against the 4/4 subdivision — not a reliable straight-grid feel reading).
    # Tightness, not grid-alignment: a consistently-pushed part is a real feel
    # to report, and a constant onset-detection latency must not tank its trust.
    n = int(onset_beats.size)
    count_factor = min(n / float(min_onsets), 1.0) if min_onsets > 0 else 1.0
    tightness_factor = max(
        0.0, 1.0 - drift_stdev / _STDEV_CONFIDENCE_SCALE_BEATS
    )
    confidence = count_factor * tightness_factor

    swing_ratio = _swing_ratio(onset_beats, min_offbeat_onsets)

    return PartTiming(
        track_id=track_id,
        onset_count=n,
        mean_drift_beats=mean_drift,
        drift_stdev_beats=drift_stdev,
        swing_ratio=swing_ratio,
        confidence=confidence,
    )


def _swing_ratio(onset_beats: np.ndarray, min_offbeat_onsets: int) -> float | None:
    """Long:short ratio inferred from off-beat 8th placement.

    Each onset is binned to the nearest 8th-note slot. Odd slots are the
    off-beats (the "&"); their position *within the beat* (the fractional part)
    measures how late the swing sits: 0.5 = straight (ratio 1.0), 0.667 =
    triplet swing (ratio 2.0). ``ratio = p / (1 - p)``. Returns ``None`` when
    there are fewer than ``min_offbeat_onsets`` off-beat onsets.

    Uses the MEDIAN off-beat phase, not the mean: a swing groove asserts its
    feel repeatedly, but a stray onset (a spurious detection, a fill note off
    the swung grid) would drag a mean toward 0.5 and under-report the swing.
    The median tracks the dominant off-beat placement and shrugs off outliers.
    """
    slot = np.round(onset_beats / _SWING_GRID_BEATS).astype(np.int64)
    is_offbeat = (slot % 2) != 0
    if int(np.count_nonzero(is_offbeat)) < min_offbeat_onsets:
        return None
    # Position within the beat for each off-beat onset (fractional part of the
    # beat). Modulo 1.0 maps every off-beat onset onto a single [0,1) beat.
    phase = np.mod(onset_beats[is_offbeat], 1.0)
    p = float(np.median(phase))
    # Guard the degenerate edges (p≈0 or p≈1 would blow up the ratio); clamp to
    # a musically sane band so a stray near-downbeat onset can't explode it.
    p = min(max(p, 0.05), 0.95)
    return p / (1.0 - p)


def _dedup_onsets(onset_beats: np.ndarray, min_separation_beats: float) -> np.ndarray:
    """Drop onsets within ``min_separation_beats`` of the previous kept one.

    ``onset_beats`` arrives sorted ascending (librosa returns onsets in time
    order). Greedy left-to-right keep: the earliest onset of each tight cluster
    survives, later near-duplicates are dropped. One musical event → one onset.
    """
    if onset_beats.size <= 1 or min_separation_beats <= 0:
        return onset_beats
    kept = [float(onset_beats[0])]
    for b in onset_beats[1:]:
        if float(b) - kept[-1] >= min_separation_beats:
            kept.append(float(b))
    return np.asarray(kept, dtype=np.float64)


def _detect_onset_samples(
    mono: np.ndarray, sample_rate: int, hop_length: int,
) -> np.ndarray:
    """Onset sample indices via librosa spectral-flux + backtracked peak pick.

    Backtracking snaps each detected peak back to the preceding local energy
    minimum, giving sample-accurate onset *times* (not hop-quantized frame
    centres) — load-bearing for timing measurement. Returns an empty array for
    audio too short to frame.
    """
    import librosa

    if mono.shape[0] < hop_length * 2:
        return np.asarray([], dtype=np.int64)
    onset_env = librosa.onset.onset_strength(
        y=mono.astype(np.float32), sr=sample_rate, hop_length=hop_length,
    )
    if not np.any(onset_env > 0.0):
        return np.asarray([], dtype=np.int64)
    return librosa.onset.onset_detect(
        onset_envelope=onset_env,
        sr=sample_rate,
        hop_length=hop_length,
        backtrack=True,
        units="samples",
    )


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #

def _to_mono(audio: np.ndarray) -> np.ndarray:
    if audio.ndim == 2:
        return 0.5 * (audio[:, 0] + audio[:, 1])
    return audio


__all__ = [
    "TimingWindowResult",
    "analyze_timing_window",
]
