"""BS.1770-4 loudness + 4×-oversampled true peak.

``pyloudnorm`` provides the K-weighted, block-gated integrated loudness
(LUFS-I). We wrap it with:

  - LUFS-S median (50th percentile of 3-second short-term blocks)
  - LUFS-M peak (max of 400 ms momentary blocks)
  - True peak in dBTP, 4× oversampled per BS.1770 §A.2 (catches
    inter-sample peaks invisible to naive sample-peak detection)

LUFS-S and LUFS-M come from ``Meter.blockwise_loudness`` populated as a
side-effect of ``integrated_loudness()``; we run two passes (default
400 ms block for momentary, 3 s block for short-term).

Per spike §3 — "True peak NOT in pyloudnorm — 15 lines: 4×
``scipy.signal.resample_poly`` then ``np.max(np.abs(...))``."
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .report import LoudnessMetrics

# Success criterion #3 (build plan Chunk 3-A): per-stem LUFS-I must land
# within this tolerance of a calibrated reference. The pink-noise
# calibration in tests/unit/audio/fixtures.py round-trips through the
# same Meter, so the tolerance is dominated by floating-point + block-
# alignment noise rather than algorithm drift. 0.2 LU mirrors the
# spike's §9.7 success criterion verbatim.
LOUDNESS_TOLERANCE_LU = 0.2

# pyloudnorm's default block size is 400 ms; signals shorter than that
# produce a NaN integrated value silently. Pre-check and teach.
_MIN_DURATION_S_DEFAULT_BLOCK = 0.4

# Short-term measurement per EBU R 128 — 3-second sliding window.
_SHORT_TERM_BLOCK_S = 3.0

# Momentary measurement per EBU R 128 — 400 ms sliding window. Matches
# pyloudnorm's default block size, so we reuse the integrated meter for
# momentary peak (the same blockwise_loudness array carries it).
_MOMENTARY_BLOCK_S = 0.4

# True-peak oversampling factor. BS.1770 §A.2 prescribes ≥4×.
_TRUE_PEAK_OVERSAMPLE = 4


@dataclass(frozen=True)
class _ShortTermResult:
    median: float
    peak: float


def measure_loudness(audio: np.ndarray, *, sr: int) -> LoudnessMetrics:
    """Measure LUFS-I / S-median / M-peak / true-peak on a stereo float32
    buffer.

    ``audio`` shape: ``(n_samples, n_channels)`` — matches pyloudnorm's
    expected shape and the synthetic fixture format.

    Raises ``ValueError`` if the clip is too short for the default 400 ms
    BS.1770 block — silently returning NaN would propagate into MixReport
    and ship as a meaningless number.

    Returns ``LoudnessMetrics`` (frozen dataclass from ``audio.report``).
    """
    if audio.ndim != 2:
        raise ValueError(
            f"audio must be 2-D (n_samples, n_channels); got shape {audio.shape}"
        )
    n_samples = audio.shape[0]
    duration_s = n_samples / sr
    if duration_s < _MIN_DURATION_S_DEFAULT_BLOCK:
        raise ValueError(
            f"audio is too short for LUFS measurement: duration={duration_s:.3f}s, "
            f"minimum={_MIN_DURATION_S_DEFAULT_BLOCK}s "
            f"(pyloudnorm's BS.1770 block size is 400 ms; shorter signals "
            f"would silently return NaN)"
        )

    # pyloudnorm mutates its input via filter.apply_filter — use a float64
    # copy so we don't disturb caller-owned float32 arrays.
    work = audio.astype(np.float64, copy=True)

    lufs_i = _integrated_loudness(work, sr)
    lufs_m_peak = _momentary_peak(work, sr)
    short_term = _short_term(work, sr, duration_s)
    true_peak_dbtp = _true_peak_dbtp(audio)

    return LoudnessMetrics(
        lufs_i=lufs_i,
        lufs_s_median=short_term.median,
        lufs_m_peak=lufs_m_peak,
        true_peak_dbtp=true_peak_dbtp,
    )


def _integrated_loudness(audio_f64: np.ndarray, sr: int) -> float:
    import pyloudnorm

    meter = pyloudnorm.Meter(sr)
    value = float(meter.integrated_loudness(audio_f64))
    # BS.1770 returns -inf on pure silence (all blocks below -70 LUFS
    # gate). NaN should not occur for inputs ≥ 400 ms; if it does we
    # surface a sentinel rather than letting it propagate into MixReport.
    if np.isnan(value):
        return float("-inf")
    return value


def _momentary_peak(audio_f64: np.ndarray, sr: int) -> float:
    """Max 400 ms-block loudness — captures momentary peaks that the
    gated integrated measurement smooths over.

    pyloudnorm's default block size (400 ms) IS the momentary block.
    After ``integrated_loudness`` runs, ``meter.blockwise_loudness`` holds
    the per-block values; take the max for the peak.
    """
    import pyloudnorm

    meter = pyloudnorm.Meter(sr, block_size=_MOMENTARY_BLOCK_S)
    meter.integrated_loudness(audio_f64.copy())
    blocks = [b for b in meter.blockwise_loudness if np.isfinite(b)]
    if not blocks:
        return float("-inf")
    return float(max(blocks))


def _short_term(audio_f64: np.ndarray, sr: int, duration_s: float) -> _ShortTermResult:
    """LUFS-S — 3-second blocks per EBU R 128.

    For clips shorter than the short-term block, fall back to using the
    momentary block values as the short-term proxy (better than NaN, and
    flagged in the MVP scope: section-windowed analysis is P1 backlog).
    """
    import pyloudnorm

    if duration_s < _SHORT_TERM_BLOCK_S:
        # Shorter than 3s — use the momentary blocks as a proxy. Median
        # of momentary blocks is a defensible degraded value rather than
        # NaN.
        return _short_term_from_momentary(audio_f64, sr)

    meter = pyloudnorm.Meter(sr, block_size=_SHORT_TERM_BLOCK_S)
    meter.integrated_loudness(audio_f64.copy())
    blocks = [b for b in meter.blockwise_loudness if np.isfinite(b)]
    if not blocks:
        return _ShortTermResult(median=float("-inf"), peak=float("-inf"))
    return _ShortTermResult(
        median=float(np.median(blocks)),
        peak=float(max(blocks)),
    )


def _short_term_from_momentary(audio_f64: np.ndarray, sr: int) -> _ShortTermResult:
    import pyloudnorm

    meter = pyloudnorm.Meter(sr, block_size=_MOMENTARY_BLOCK_S)
    meter.integrated_loudness(audio_f64.copy())
    blocks = [b for b in meter.blockwise_loudness if np.isfinite(b)]
    if not blocks:
        return _ShortTermResult(median=float("-inf"), peak=float("-inf"))
    return _ShortTermResult(
        median=float(np.median(blocks)),
        peak=float(max(blocks)),
    )


def _true_peak_dbtp(audio: np.ndarray) -> float:
    """4× oversampled true-peak in dBTP per BS.1770 §A.2.

    Spike §3 sketch: ``4× scipy.signal.resample_poly`` then
    ``np.max(np.abs(...))``. resample_poly takes (up, down); polyphase
    filtering avoids the spectral leakage that naïve linear interpolation
    would introduce around inter-sample peaks.
    """
    from scipy.signal import resample_poly

    # Per-channel oversample, then max. Empty input → -inf (no peak).
    if audio.size == 0:
        return float("-inf")
    peak = 0.0
    for ch in range(audio.shape[1]):
        oversampled = resample_poly(
            audio[:, ch].astype(np.float64),
            up=_TRUE_PEAK_OVERSAMPLE,
            down=1,
        )
        ch_peak = float(np.max(np.abs(oversampled)))
        if ch_peak > peak:
            peak = ch_peak
    if peak <= 0.0:
        return float("-inf")
    return 20.0 * float(np.log10(peak))


__all__ = [
    "LOUDNESS_TOLERANCE_LU",
    "measure_loudness",
]
