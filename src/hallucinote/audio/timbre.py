"""Standing per-surface timbre descriptors (AUD-8T3K) — the noisiness /
brightness lens.

The mix report carries loudness only, so a "make X noisier / brighter / grittier"
edit could be judged by ear but never verified against a number. ``measure_timbre``
fills that gap with three standing descriptors per surface — spectral centroid
(brightness), spectral flatness (noisiness, tonal↔noise), spectral rolloff (a
second brightness/edge cue) — each the MEDIAN over silence-gated STFT frames.

Read-side only — neutral measurement, never a grade or a re-authoring (consistent
with the energy lens's never-grades stance). The interpreter reads the numbers
against declared intent like every other lens.

Two methodology choices (see ``build-plan-aud-8t3k-timbre.md`` for the full
rationale):

  * **Flatness over Bark band powers, NOT raw FFT bins.** Raw bins crush the
    geometric mean to ~0 for any pitched material; the 24 Zwicker Bark bands
    (shared via ``bark.py``) give a meaningful tonal↔noise axis.
  * **Median over silence-gated frames, NOT p90.** The silence gate drops
    inter-onset quiet before aggregating, so the median describes timbre *while
    the surface is sounding* — for sparse percussive material only the hit frames
    survive, so their median is the brightness *during hits*. That removes the
    "median understates transient content" concern without p90's
    single-bright-frame noise sensitivity.
"""
from __future__ import annotations

import numpy as np

from .bark import aggregate_to_bands, bark_band_map
from .onsets import to_mono
from .report import TimbreMetrics

# STFT calibration — match masking.py (48 kHz: 2048 / 512 ≈ 43 ms / 11 ms) so the
# two spectral lenses read the same frame grid.
_N_FFT = 2048
_HOP = 512

# Rolloff energy fraction (Scheirer & Slaney convention).
_ROLLOFF_FRACTION = 0.85

# Silence gate: a frame whose total power is more than this many dB below the
# window's loudest frame is inter-onset silence / noise floor and is dropped
# before aggregating. Scale-invariant (relative to the loudest frame), matching
# masking's energy-gate philosophy. This is what makes the median fair.
_SILENCE_GATE_DB = 60.0

# Per-frame floor for the flatness geometric mean, relative to that frame's
# loudest band, so an exactly-zero Bark band doesn't send geomean to 0 while
# staying scale-invariant (a pure tone still reads ~0, white noise ~1).
_FLATNESS_REL_FLOOR = 1e-10

_NAN = float("nan")
# The honest "no measurable timbre" sentinel — empty / too short / silent.
_SILENT = TimbreMetrics(_NAN, _NAN, _NAN)


def measure_timbre(
    audio: np.ndarray, sr: int, *, n_fft: int = _N_FFT, hop_length: int = _HOP,
) -> TimbreMetrics:
    """Median timbre descriptors over the silence-gated frames of ``audio``.

    ``audio`` is mono ``(n,)`` or stereo ``(n, 2)``. Returns an all-``NaN``
    :class:`TimbreMetrics` (→ JSON ``null``) when the surface is empty, too
    short to STFT, or silent — the honest "no measurable timbre" sentinel.
    """
    mono = to_mono(audio).astype(np.float64)
    if mono.shape[0] < n_fft:
        return _SILENT

    import librosa

    stft = librosa.stft(
        mono.astype(np.float32), n_fft=n_fft, hop_length=hop_length,
        window="hann", center=True,
    )
    power = (np.abs(stft) ** 2).astype(np.float64)   # [n_bins, n_frames]
    frame_total = power.sum(axis=0)                  # [n_frames]
    if frame_total.size == 0:
        return _SILENT
    peak = float(frame_total.max())
    if peak <= 0.0:
        return _SILENT

    # Keep only frames within _SILENCE_GATE_DB of the loudest frame.
    keep = frame_total >= peak * 10.0 ** (-_SILENCE_GATE_DB / 10.0)
    if not np.any(keep):
        return _SILENT
    power = power[:, keep]
    frame_total = frame_total[keep]

    freqs = np.fft.rfftfreq(n_fft, d=1.0 / sr)       # [n_bins]

    centroid = (freqs[:, None] * power).sum(axis=0) / frame_total
    rolloff = _rolloff_hz(power, frame_total, freqs)
    flatness = _band_flatness(aggregate_to_bands(power, bark_band_map(sr, n_fft)))

    return TimbreMetrics(
        spectral_centroid_hz=float(np.median(centroid)),
        spectral_flatness=float(np.median(flatness)),
        spectral_rolloff_hz=float(np.median(rolloff)),
    )


def spectral_centroid_hz(mono: np.ndarray, sample_rate: int) -> float:
    """Magnitude-weighted mean frequency (Hz) of a whole window — a coarse but
    robust timbre proxy. Distortion / brightness pushes it up; a darker setting
    pulls it down. ``0.0`` for an empty/silent window.

    The single-FFT whole-window form used by the automation verifier's
    before/after timbre delta (lifted here from ``automation.py`` so the centroid
    math lives in one place — AUD-8T3K). Distinct from :func:`measure_timbre`'s
    framed median, which is the standing per-surface descriptor.
    """
    if mono.size == 0:
        return 0.0
    spec = np.abs(np.fft.rfft(mono))
    total = float(spec.sum())
    if total <= 0.0:
        return 0.0
    freqs = np.fft.rfftfreq(mono.size, d=1.0 / sample_rate)
    return float((freqs * spec).sum() / total)


def _rolloff_hz(
    power: np.ndarray, frame_total: np.ndarray, freqs: np.ndarray,
) -> np.ndarray:
    """Per-frame rolloff (Hz): the lowest frequency at or below which
    ``_ROLLOFF_FRACTION`` of the frame's energy lies. The top bin always
    satisfies the threshold (cumulative == total ≥ fraction·total), so every
    frame resolves."""
    cumulative = np.cumsum(power, axis=0)
    reached = cumulative >= (_ROLLOFF_FRACTION * frame_total)[None, :]
    return freqs[reached.argmax(axis=0)]   # argmax → first True per frame


def _band_flatness(band_power: np.ndarray) -> np.ndarray:
    """Per-frame Wiener-entropy flatness over Bark band powers → ``[n_frames]``.

    geometric_mean ÷ arithmetic_mean across the bands, in 0..1 (tonal → ~0,
    white noise → ~1). A per-frame relative floor protects the geometric mean
    against an exactly-zero band while preserving scale-invariance. A frame with
    no in-Bark-range energy (all power above the top edge) reads 0.0."""
    col_max = band_power.max(axis=0)                 # [n_frames]
    flatness = np.zeros(band_power.shape[1], dtype=np.float64)
    ok = col_max > 0.0
    if np.any(ok):
        bp = band_power[:, ok]
        floored = np.maximum(bp, (col_max[ok] * _FLATNESS_REL_FLOOR)[None, :])
        geo = np.exp(np.mean(np.log(floored), axis=0))
        arith = np.mean(floored, axis=0)
        flatness[ok] = geo / arith
    return flatness
