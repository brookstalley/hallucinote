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

# Accent measurement window (seconds) after each onset. The accent feature
# (C8c) is the PEAK absolute sample value over this window — "how hard was this
# hit struck", the dimension the grouping/polymeter decoders read. A C8c-1
# calibration pass (run amplitude-scaled clicks through the real pipeline, eyeball
# the recovered strengths) showed peak-amplitude is the faithful choice: flat on
# equal-velocity hits, linear with amplitude, and an accurate accent ratio —
# whereas the spectral-flux envelope value compresses accents and a single
# envelope frame is corrupted by sub-hop onset alignment, and an RMS window
# varies with how the short transient lands in it. 30 ms brackets a struck
# transient without bleeding into the next 16th at fast tempi.
DEFAULT_ACCENT_WINDOW_S = 0.030


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


def detect_onsets_with_strength(
    mono: np.ndarray,
    sample_rate: int,
    hop_length: int = DEFAULT_HOP,
    accent_window_s: float = DEFAULT_ACCENT_WINDOW_S,
) -> tuple[np.ndarray, np.ndarray]:
    """Onset sample indices PLUS each onset's accent strength.

    The accent dimension C8c needs (``docs/polyrhythms.md`` §5 #1: the cycle /
    grouping signature lives in the accent pattern, not onset timing). Onset
    *detection* is unchanged — the same spectral-flux + backtracked peak pick as
    :func:`detect_onset_samples`. What's added is a per-onset accent **strength**
    = the peak absolute sample value over ``accent_window_s`` from the onset.

    Why peak amplitude, not the flux-envelope height: a C8c-1 calibration pass
    showed a single flux frame is corrupted by sub-hop onset alignment (identical
    hits read a spurious period-4 ramp), the flux value compresses real accents
    (a 2× louder hit is barely more spectral *change*), and an RMS window varies
    with how a short transient lands in it. Peak amplitude is flat on
    equal-velocity hits, linear with amplitude, and preserves the accent ratio —
    it measures how hard the hit was struck, which is the accent.

    Returns ``(samples, strengths)``, index-aligned and time-ordered:
      * ``samples`` — sample-accurate onset times (backtracked to the preceding
        energy minimum), identical to :func:`detect_onset_samples`.
      * ``strengths`` — peak ``|mono|`` over ``[onset, onset + accent_window]``.

    Returns two empty arrays for audio too short to frame or with no onset
    energy. (The very first onset of a buffer that starts at sample 0 is not
    detectable — spectral flux needs preceding frames — so callers must not rely
    on absolute onset phase; the grouping decoder is rotation-agnostic.)
    """
    samples = detect_onset_samples(mono, sample_rate, hop_length)
    if samples.size == 0:
        return samples, np.asarray([], dtype=np.float64)
    window = max(1, int(round(accent_window_s * sample_rate)))
    strengths = np.empty(samples.size, dtype=np.float64)
    n = mono.shape[0]
    for i, s in enumerate(samples):
        seg = mono[int(s):min(int(s) + window, n)]
        strengths[i] = float(np.max(np.abs(seg))) if seg.size else 0.0
    return samples, strengths


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


def dedup_onsets_with_strength(
    onset_beats: np.ndarray,
    strengths: np.ndarray,
    min_separation_beats: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Strength-carrying :func:`dedup_onsets`: one musical event → one onset.

    Same greedy left-to-right merge as :func:`dedup_onsets` — the earliest onset
    of each tight cluster sets the kept TIME — but the kept STRENGTH is the
    **max** over the cluster, not the first. A flam or a kick's pitch-sweep
    double-trigger should contribute the energy of the loudest sub-hit to the
    accent series, not whichever transient librosa happened to detect first.
    Returns ``(kept_beats, kept_strengths)``, index-aligned.
    """
    if onset_beats.size == 0:
        return onset_beats, strengths
    if onset_beats.size == 1 or min_separation_beats <= 0:
        return onset_beats, strengths
    kept_beats = [float(onset_beats[0])]
    kept_strengths = [float(strengths[0])]
    for b, s in zip(onset_beats[1:], strengths[1:]):
        if float(b) - kept_beats[-1] >= min_separation_beats:
            kept_beats.append(float(b))
            kept_strengths.append(float(s))
        else:
            # Within the merge window — fold into the current event, keeping the
            # loudest accent.
            kept_strengths[-1] = max(kept_strengths[-1], float(s))
    return (
        np.asarray(kept_beats, dtype=np.float64),
        np.asarray(kept_strengths, dtype=np.float64),
    )


def to_mono(audio: np.ndarray) -> np.ndarray:
    """Mono-sum a (n,) or (n, 2) buffer."""
    if audio.ndim == 2:
        return 0.5 * (audio[:, 0] + audio[:, 1])
    return audio


__all__ = [
    "DEFAULT_HOP",
    "DEFAULT_MIN_ONSET_SEPARATION_BEATS",
    "detect_onset_samples",
    "detect_onsets_with_strength",
    "dedup_onsets",
    "dedup_onsets_with_strength",
    "to_mono",
]
