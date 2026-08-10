"""Per-surface stereo metrics — the image lens (STR-4C8N).

The report already answers "how loud", "how bright" and "who masks whom". It
could not answer **"is this actually stereo, and what does it cost in mono?"** —
so a width control could be dialled confidently and do nothing, and nothing
anywhere would say so.

Two numbers per surface, both neutral measurement (never a grade — the
interpreter reads them against declared intent, like every other lens):

  ``correlation``        Pearson L/R over the window, -1..+1. ``+1`` is bit-exact
                         mono (or a perfectly correlated pair), ``0`` fully
                         decorrelated, negative means the channels partly cancel.
  ``mono_sum_loss_db``   How much level the surface LOSES when summed to mono:
                         ``20·log10(rms(mono) / rms(stereo))``. ``0 dB`` = nothing
                         lost, ``-3 dB`` ≈ two equal uncorrelated channels, large
                         negatives mean the part partly cancels itself on any mono
                         playback (a phone speaker, a club sub, a Bluetooth box).

**Why dB and not just correlation.** Correlation is the physics; the loss is what
a listener loses, in the units a composer already thinks in. "-3.8 dB in mono"
is actionable where "-0.174" needs a decoder ring.

**Honest limits.** Both are BROADBAND: a part wide in the highs and mono in the
lows averages to something unremarkable, and neither number localises the
frequency where the image lives. Per-band correlation is the obvious extension
and is deliberately not here — see the plan's out-of-scope note.

NaN is the "unmeasurable" sentinel (a silent or empty window), matching
``TimbreMetrics``; the report's ``_finite_or_none`` collapses it to JSON ``null``.
"""
from __future__ import annotations

import numpy as np

from .report import StereoMetrics

# A fully-cancelling mono sum is -inf dB, which is not valid JSON and not a
# useful reading. Floor it deep enough to read unambiguously as "gone" while
# staying finite. (-180 dBFS is far below any real signal; it is this module's
# own choice, not a shared constant — nothing else in the codebase defines one.)
_SILENCE_FLOOR_DB = -180.0

# Below this RMS the window carries no signal to characterise — reporting a
# correlation for dither-level noise would be inventing a reading.
#
# Deliberately the SAME value as ``automation._QUIET_RMS``, and for a sharper
# reason than tidiness: this lens's "healthy" reading (+1.0 correlation, 0 dB
# loss) is also its FAILURE SIGNATURE — bit-exact mono. A floor low enough to
# measure an inaudible stem would hand back that signature for a track nobody can
# hear, which reads as "declared wide, measured mono" and sends a producer
# chasing a width bug on silence. Anything too quiet for the automation lens to
# characterise is too quiet for this one to accuse.
_QUIET_RMS = 1e-5


def measure_stereo(audio: np.ndarray) -> StereoMetrics:
    """Measure L/R correlation and mono-sum loss for one stereo window.

    Args:
        audio: ``(frames, 2)`` float array — the capture loader guarantees
            float32 stereo for every surface.

    Raises:
        ValueError: the array is not two-channel. Guessing a channel layout
            would silently produce a reading for something that isn't stereo.
    """
    if audio.ndim != 2 or audio.shape[1] != 2:
        raise ValueError(
            f"measure_stereo expects a stereo (frames, 2) array, got "
            f"shape={audio.shape!r} — every captured surface is float32 stereo "
            f"(see audio/io.py load_capture), so a mono array here means the "
            f"caller collapsed the channels before measuring."
        )

    if audio.shape[0] == 0:
        return StereoMetrics(correlation=float("nan"), mono_sum_loss_db=float("nan"))

    left = audio[:, 0].astype(np.float64)
    right = audio[:, 1].astype(np.float64)

    stereo_rms = float(np.sqrt(np.mean(audio.astype(np.float64) ** 2)))
    if stereo_rms <= _QUIET_RMS:
        # Silence is unmeasurable, NOT "perfectly mono" — a silent stem must not
        # read as a healthy correlation of 1.0 and get graded as fine.
        return StereoMetrics(correlation=float("nan"), mono_sum_loss_db=float("nan"))

    mono = (left + right) / 2.0
    mono_rms = float(np.sqrt(np.mean(mono**2)))
    if mono_rms <= _QUIET_RMS:
        loss_db = _SILENCE_FLOOR_DB
    else:
        loss_db = 20.0 * float(np.log10(mono_rms / stereo_rms))

    return StereoMetrics(
        correlation=_correlation(left, right),
        mono_sum_loss_db=loss_db,
    )


def _correlation(left: np.ndarray, right: np.ndarray) -> float:
    """Pearson correlation, with the degenerate cases decided rather than raised.

    A constant channel has zero variance, so Pearson is undefined. The honest
    reading depends on WHY it is constant: two identical constant channels are
    genuinely a mono signal (+1), whereas one constant channel against a moving
    one carries no shared variation to correlate (0 — no evidence of width, no
    evidence of cancellation).
    """
    if np.array_equal(left, right):
        return 1.0

    left_var = float(np.var(left))
    right_var = float(np.var(right))
    if left_var <= 0.0 or right_var <= 0.0:
        return 0.0

    corr = float(np.corrcoef(left, right)[0, 1])
    if not np.isfinite(corr):
        return 0.0
    # Guard the float error that lets a perfectly correlated pair land at
    # 1.0000000000000002 and break a bounded-range assertion downstream.
    return max(-1.0, min(1.0, corr))
