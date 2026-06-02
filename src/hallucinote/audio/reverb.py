"""Reverb RT60 verification — measure a return's decay time from its own tail.

RT60 is a property of a return's reverb *device*, so it is measured **once
per return**, from the return's own captured **ring-out** (the decay after the
arrangement's dry input stops), via Schroeder backward energy integration
(``pyroomacoustics.experimental.rt60.measure_rt60``). This is **dry-source-free**:
no deconvolution, no dry stem, no send-gain calibration.

Why not deconvolve the wet return by a dry stem (the original MVP)? A real
return is fed by *many* sends at once, so the wet signal is
``IR ⊗ Σ(gain·dry_i)``. Deconvolving by a single ``dry_i`` leaves every other
send as unexplained signal → a noise-like "IR" → a wildly wrong RT60
(252–370 s observed on a real multi-send capture; see AUD-6R2M). Measuring the
return's own decay sidesteps the multi-source problem entirely — and RT60 is a
decay *time*, hence scale-invariant, so we don't need to know how loud the
input was either.

The one requirement is a usable ring-out in the capture: the render must keep
recording past the arrangement end so the reverb decays into silence (see
``render`` ``ring_out_beats``). When the capture lacks one (the dry input plays
to the file's last sample), ``measure_return_rt60`` returns
``sufficient_tail=False`` with a NaN measurement rather than extrapolating RT60
from noise — an honest skip, not a fabricated number.
"""
from __future__ import annotations

import math

import numpy as np

from .report import ReverbVerification

# Success criterion #5 (audio-analysis MVP): measured vs declared RT60 must
# agree within this tolerance on a synthetic known-RT60 ring-out. Real-world
# noisy material gets wider tolerance per the audio-analysis spike §7.
REVERB_TOLERANCE_S = 0.15

# Below this, the decay region is too short to be a ring-out at all (e.g. a
# capture with no recorded tail — the dry input played to the last sample).
_MIN_TAIL_S = 0.30

# Minimum clean decay span (dB, onset → noise floor) the tail must afford for
# even an RT10 fit to be trustworthy. Below this we refuse to measure.
_MIN_DECAY_SPAN_DB = 20.0

# Energy-frame window for the decay-span estimate (10 ms).
_FRAME_S = 0.010

# Energy-frame window for decay-onset detection (20 ms). Coarser than the
# span estimate — it locates the last excitation, not a fine decay slope.
_ONSET_FRAME_S = 0.020


def _insufficient(
    *,
    return_track_id: str,
    declared_rt60_s: float,
    tolerance_s: float,
    tail_span_db: float,
) -> ReverbVerification:
    """A verdict for a capture with no usable ring-out: NaN measurement,
    ``sufficient_tail=False``. We do NOT extrapolate RT60 from noise."""
    return ReverbVerification(
        return_track_id=return_track_id,
        declared_rt60_s=declared_rt60_s,
        measured_rt60_s=float("nan"),
        within_tolerance=False,
        tolerance_s=tolerance_s,
        measurement_method="decay_tail",
        decay_db_used=0.0,
        tail_span_db=tail_span_db,
        sufficient_tail=False,
    )


def find_decay_onset(
    return_audio: np.ndarray,
    *,
    search_start_sample: int,
    sample_rate: int,
) -> int:
    """Sample where the ring-out's monotone decay begins.

    The dry arrangement stops at the arrangement end (``search_start_sample``
    is that boundary in samples); instrument release tails keep feeding the
    return briefly past it. The decay onset is the peak of the return's own
    short-time energy envelope within ``[search_start_sample:]`` — the last
    moment it was re-excited, after which it only decays. Integrating RT60 from
    here keeps the release tail out of the early decay curve.

    Returns ``n`` (no usable region) when ``search_start_sample`` is at/after
    the end — the no-ring-out case, which :func:`measure_return_rt60` then
    reports as an honest insufficient-tail skip.
    """
    n = return_audio.shape[0]
    start = max(0, min(int(search_start_sample), n))
    if n - start < 1:
        return n
    mono = 0.5 * (return_audio[start:, 0] + return_audio[start:, 1])
    win = max(1, int(_ONSET_FRAME_S * sample_rate))
    n_frames = mono.shape[0] // win
    if n_frames < 1:
        return start
    frame_pow = np.mean(
        (mono[: n_frames * win].astype(np.float64) ** 2).reshape(n_frames, win),
        axis=1,
    )
    peak_frame = int(np.argmax(frame_pow))
    return start + peak_frame * win


def measure_return_rt60(
    return_audio: np.ndarray,
    *,
    sample_rate: int,
    decay_onset_sample: int,
    declared_rt60_s: float,
    return_track_id: str,
    tolerance_s: float = REVERB_TOLERANCE_S,
) -> ReverbVerification:
    """Measure a return's RT60 from its ring-out, compare to declared.

    ``return_audio`` is the return surface's stereo (n, 2) float capture.
    ``decay_onset_sample`` is the sample where the ring-out begins — the point
    after which the return is no longer being re-excited (the caller detects it
    from the return's own energy envelope; see ``analyze._decay_onset_sample``).

    Returns a per-return :class:`ReverbVerification`. When the tail is too short
    or affords too little clean decay, ``sufficient_tail`` is False and
    ``measured_rt60_s`` is NaN — the honest "no usable ring-out" outcome, whose
    remedy is a re-render with a longer ``ring_out_beats``.
    """
    if return_audio.ndim != 2 or return_audio.shape[1] != 2:
        raise ValueError(
            f"return_audio must be stereo (n, 2); got shape {return_audio.shape}"
        )
    n = return_audio.shape[0]
    onset = max(0, min(int(decay_onset_sample), n))
    tail = (0.5 * (return_audio[onset:, 0] + return_audio[onset:, 1])).astype(
        np.float64
    )

    if tail.size < int(_MIN_TAIL_S * sample_rate):
        return _insufficient(
            return_track_id=return_track_id,
            declared_rt60_s=declared_rt60_s,
            tolerance_s=tolerance_s,
            tail_span_db=0.0,
        )

    # Clean decay span = onset energy → noise-floor energy, in dB. A real
    # ring-out decays from its peak down to the capture's noise floor; a tail
    # cut off mid-decay (or pure noise) affords little span. Frame energies at
    # 10 ms; peak vs the median of the last 10% (assumed post-decay floor).
    win = max(1, int(_FRAME_S * sample_rate))
    n_frames = tail.size // win
    if n_frames < 4:
        return _insufficient(
            return_track_id=return_track_id,
            declared_rt60_s=declared_rt60_s,
            tolerance_s=tolerance_s,
            tail_span_db=0.0,
        )
    frame_pow = np.maximum(
        np.mean(tail[: n_frames * win].reshape(n_frames, win) ** 2, axis=1),
        1e-20,
    )
    peak_pow = float(np.max(frame_pow))
    floor_pow = float(np.median(frame_pow[int(0.9 * n_frames):]))
    tail_span_db = 10.0 * math.log10(peak_pow / max(floor_pow, 1e-20))

    if tail_span_db < _MIN_DECAY_SPAN_DB:
        return _insufficient(
            return_track_id=return_track_id,
            declared_rt60_s=declared_rt60_s,
            tolerance_s=tolerance_s,
            tail_span_db=tail_span_db,
        )

    # Fit the largest standard decay window that stays clear of the noise floor:
    # measure_rt60 fits from -5 dB to -(5 + decay_db), so keep that endpoint
    # ~10 dB above the floor. RT20/RT30 are extrapolated ×(60/decay_db) to RT60.
    if tail_span_db >= 45.0:
        decay_db = 30.0
    elif tail_span_db >= 35.0:
        decay_db = 20.0
    else:
        decay_db = 10.0

    from pyroomacoustics.experimental.rt60 import measure_rt60

    try:
        measured = float(measure_rt60(tail, fs=sample_rate, decay_db=decay_db))
    except (ValueError, FloatingPointError, ZeroDivisionError):
        measured = float("nan")

    if not math.isfinite(measured) or measured <= 0.0:
        return _insufficient(
            return_track_id=return_track_id,
            declared_rt60_s=declared_rt60_s,
            tolerance_s=tolerance_s,
            tail_span_db=tail_span_db,
        )

    within = abs(measured - declared_rt60_s) <= tolerance_s
    return ReverbVerification(
        return_track_id=return_track_id,
        declared_rt60_s=declared_rt60_s,
        measured_rt60_s=measured,
        within_tolerance=within,
        tolerance_s=tolerance_s,
        measurement_method="decay_tail",
        decay_db_used=decay_db,
        tail_span_db=tail_span_db,
        sufficient_tail=True,
    )


__all__ = [
    "REVERB_TOLERANCE_S",
    "find_decay_onset",
    "measure_return_rt60",
]
