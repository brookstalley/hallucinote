"""Shared onset front-end for the per-part rhythm analyzers.

Both the timing analyzer (``timing.py``, C7) and the cross-rhythm analyzer
(``cross_rhythm.py``, C8) start from the same step: turn windowed stem audio
into a clean, sample-accurate, de-duplicated list of onset times. That front
end was factored out of ``timing.py`` so the two modules share one calibrated
implementation — a coarse hop or a sloppy dedup window corrupts BOTH the
drift/swing measurement and the inter-onset-interval ratio detection, so they
must agree by construction, not by parallel copies that can drift apart.

Pure DSP, DB-agnostic, no MixReport coupling — the lowest layer of the audio
package. ``detect_onset_samples`` returns sample indices; ``dedup_onsets``
collapses near-coincident onsets (a kick's pitch sweep, a flam) into one
musical event. Callers map samples→beats and measure from there.

Citation: Bello et al. (2005) "A Tutorial on Onset Detection in Music Signals"
(spectral-flux onset strength + peak picking — librosa's default).
"""
from __future__ import annotations

import numpy as np

# librosa STFT hop for the onset envelope. 128 @ 48k ≈ 2.7 ms frames; with
# backtrack this sets onset-time resolution, which is load-bearing for both
# analyzers (a coarse hop quantizes onsets and corrupts the drift/swing
# measurement AND the inter-onset-interval ratios cross-rhythm reads).
DEFAULT_HOP = 128

# Onsets closer than this are merged (one musical event → one onset). A hair
# under a 16th's eighth so it kills double-triggers (a kick's pitch sweep, a
# flam) without merging real adjacent subdivisions.
DEFAULT_MIN_ONSET_SEPARATION_BEATS = 0.06


def detect_onset_samples(
    mono: np.ndarray, sample_rate: int, hop_length: int = DEFAULT_HOP,
) -> np.ndarray:
    """Onset sample indices via librosa spectral-flux + backtracked peak pick.

    Backtracking snaps each detected peak back to the preceding local energy
    minimum, giving sample-accurate onset *times* (not hop-quantized frame
    centres) — load-bearing for both timing measurement and IOI-ratio
    detection. Returns an empty array for audio too short to frame.
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


def dedup_onsets(onset_beats: np.ndarray, min_separation_beats: float) -> np.ndarray:
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


def to_mono(audio: np.ndarray) -> np.ndarray:
    """Mono-sum a (n,) or (n, 2) buffer."""
    if audio.ndim == 2:
        return 0.5 * (audio[:, 0] + audio[:, 1])
    return audio


__all__ = [
    "DEFAULT_HOP",
    "DEFAULT_MIN_ONSET_SEPARATION_BEATS",
    "detect_onset_samples",
    "dedup_onsets",
    "to_mono",
]
