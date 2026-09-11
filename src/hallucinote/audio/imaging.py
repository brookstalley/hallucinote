"""Per-surface soundstage imaging — where a part sits, how wide it is, and
where in the spectrum its width actually lives.

``stereo.py`` answers "is this actually stereo, and what does it cost in mono?"
with two BROADBAND numbers, and says plainly what it cannot see: a part wide in
the top over a mono low end averages to something unremarkable, and neither
number localises the frequency where the image lives. This module is that
missing half. The two are complementary, not competing — ``stereo.py`` stays as
it is, and this one imports its silence floor and its correlation so the two
lenses cannot drift apart on the same signal.

Four readings per surface, all neutral measurement (never a grade — whether a
stage is *well* arranged is read against declared intent by ``/mix-review``,
like every other lens):

  ``balance_db``          L/R energy ratio in dB, positive = right louder. One
                          number, and a pan bug reads straight off it: a stem
                          meant to sit centre at ``+11 dB`` is not a taste
                          question.
  ``mid_side_ratio_db``   ``20·log10(rms(M) / rms(S))`` over ``M = (L+R)/2``,
                          ``S = (L-R)/2``. Positive = more centre than sides;
                          large positive = no side content at all.
  ``position``            ``-1`` hard left .. ``0`` centre .. ``+1`` hard right.
  ``width``               ``0`` mono .. ``1`` fully decorrelated.
  ``band_images``         The same correlation-and-width pair per frequency
                          band, which is what localises "mono low end, wide
                          top" or the inverse.

**How ``position`` is defined, and why it is also the mid/side reading.** It is
the signed energy balance ``(E_R - E_L) / (E_R + E_L)`` — bounded, zero at equal
energy, ``±1`` when one channel is empty. That is not a second, competing
statement about the image: the mid/side cross-power satisfies
``mean(M·S) = (E_L - E_R) / 4`` identically, so ``position`` is exactly
``-2·mean(M·S) / (E_M + E_S)`` — *how much of the side signal is in phase with
the mid signal*, which is the same fact the L/R balance carries. It is computed
from the energies because that form has no cancellation error, and it is
reported alongside ``mid_side_ratio_db`` because the ratio says how much centre
image there is to place while ``position`` says where it sits. An anti-phase
pair reads ``position = 0`` with a deeply negative ratio, which together say
"no centre image at all", not "a centred source".

**How ``width`` is defined, and why it is not an energy ratio.** ``width`` is
``1 - correlation``, clamped to ``[0, 1]``. A bit-exact mono pair correlates at
``+1`` and reads ``0``; a fully decorrelated pair correlates at ``0`` and reads
``1``; a partly cancelling pair correlates negative and also reads ``1`` —
beyond decorrelation the channels are not *wider*, they are cancelling, and
that is what ``mid_side_ratio_db`` and ``stereo.mono_sum_loss_db`` report. The
obvious alternative, the side-energy fraction ``E_S / (E_M + E_S)``, was
rejected because it cannot separate the two shapes this lens exists to
separate: a hard-panned mono source and a decorrelated pair BOTH sit at exactly
half side energy, so an energy ratio calls a point source at the edge equally
wide as a genuine spread. Correlation can tell them apart.

**The one-sided reading.** Panning a mono source with any ordinary pan law
leaves L and R perfectly correlated, so ``width`` reads ``0`` at every pan
position — until the hard extreme, where one channel is empty, there is no
shared variation, and Pearson is undefined. Reporting ``1`` there would put a
discontinuity at exactly the pan a bug lands on. So a surface (or a band) with
signal in one channel and nothing in the other reads ``width = 0`` — a point
source at the edge — with its ``correlation`` left unmeasurable rather than
correlated against dither. Read it with ``position``: ``position ±1, width 0``
is a hard-panned point source, and it is continuous with the ``position 0.9,
width 0`` just inside it.

**Silence is skipped, never guessed.** A bit-exact mono pair is simultaneously
this lens's healthy reading and its failure signature, so an inaudible surface
must never be handed one: below ``stereo.QUIET_RMS`` — the repo's single
definition of the silence floor — the result carries a structured ``skipped``
reason and NaN readings. NaN is the report's unmeasurable sentinel (matching
``TimbreMetrics`` and ``StereoMetrics``); ``_finite_or_none`` collapses it to
JSON ``null``.

**The line this lens draws.** Where a part sits and how wide it is are
determinate physical measurements of the captured audio, so they carry no
listening-day calibration. How much width is *right* for the part is not here.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .attribution import BANDS
# The silence floor and the degenerate-case correlation decisions (a bit-exact
# pair is +1; a constant channel against a moving one has no shared variation
# and is 0) are settled once in the broadband lens. Re-deriving them here would
# let two lenses disagree about the same signal, which is precisely the drift a
# per-band extension is most likely to introduce.
from .stereo import QUIET_RMS, channel_correlation

# Both dB readings here are ratios of two channel-energies, and either
# denominator can be exactly zero (a hard pan, a bit-exact mono pair). -inf is
# not valid JSON and not a useful reading, so both clamp to ±this. 144 dB is
# float32's own dynamic range: past it the quieter component is below the
# resolution of the capture format, so a larger number would be describing the
# arithmetic rather than the audio. Read a clamped value as "at least this far".
_RATIO_LIMIT_DB = 144.0

# Butterworth order for the per-band split, matching attribution.py and
# transients.py so the three band-wise lenses shape their bands the same way.
_BAND_FILTER_ORDER = 4

# ``sosfiltfilt`` pads by 3·(2·n_sections + 1) − 1 samples and refuses a window
# shorter than that. An order-4 bandpass is 4 biquads, so 26 samples; the margin
# keeps the guard correct if the order ever moves. A band that cannot be
# filtered reads unmeasurable rather than raising — the broadband numbers on a
# very short window are still real.
_MIN_BAND_SAMPLES = 64

_NAN = float("nan")


@dataclass(frozen=True)
class BandImage:
    """The image within one frequency band of ``attribution.BANDS``.

    ``correlation`` is the L/R Pearson inside the band and ``width`` its
    ``1 - correlation`` reading on the same ``[0, 1]`` scale as the broadband
    one. Both are NaN where the band carries nothing to measure; a band with
    signal on one side only reads ``correlation`` NaN with ``width`` 0, for the
    reason in the module docstring.
    """
    band: str
    correlation: float
    width: float


@dataclass(frozen=True)
class ImagingMetrics:
    """Where one surface sits across the stereo field, and how wide.

    ``skipped`` names why there is no reading, or is ``None`` when there is one
    — never a silent absence. The complete set is ``empty_window`` (a
    zero-length surface), ``below_silence_floor`` (nothing above
    ``stereo.QUIET_RMS`` to characterise) and ``invalid_sample_rate``. A skipped
    result carries NaN for every number and no band images.
    """
    balance_db: float
    mid_side_ratio_db: float
    position: float
    width: float
    band_images: list[BandImage]
    skipped: str | None


def measure_imaging(audio: np.ndarray, *, sample_rate: int) -> ImagingMetrics:
    """Measure one surface's soundstage: balance, position, width, per band.

    Args:
        audio: ``(n_samples, 2)`` float array — the capture loader guarantees
            float32 stereo for every surface (see ``audio/io.py``).
        sample_rate: samples per second, needed for the band split.

    Raises:
        ValueError: the array is not two-channel. A mono array here means the
            caller collapsed the channels before measuring, and every number in
            this lens is about the difference between them — guessing a channel
            layout would produce a confident reading of something that has no
            image at all.
    """
    if audio.ndim != 2 or audio.shape[1] != 2:
        raise ValueError(
            f"measure_imaging expects a stereo (n_samples, 2) array, got "
            f"shape={audio.shape!r} — every captured surface is float32 stereo "
            f"(see audio/io.py load_capture), so a mono array here means the "
            f"caller collapsed the channels before measuring."
        )

    if audio.shape[0] == 0:
        return _skip("empty_window")
    if sample_rate <= 0:
        return _skip("invalid_sample_rate")

    left = audio[:, 0].astype(np.float64)
    right = audio[:, 1].astype(np.float64)

    left_rms = _rms(left)
    right_rms = _rms(right)
    if max(left_rms, right_rms) <= QUIET_RMS:
        # Silence is unmeasurable, NOT "a centred mono source" — an inaudible
        # stem must not be handed this lens's healthy reading and graded fine.
        return _skip("below_silence_floor")

    mid = 0.5 * (left + right)
    side = 0.5 * (left - right)

    left_energy = left_rms**2
    right_energy = right_rms**2

    return ImagingMetrics(
        balance_db=_ratio_db(right_rms, left_rms),
        mid_side_ratio_db=_ratio_db(_rms(mid), _rms(side)),
        # Identical to -2·mean(M·S)/(E_M + E_S); see the module docstring.
        position=(right_energy - left_energy) / (right_energy + left_energy),
        width=_width(left, right, left_rms, right_rms),
        band_images=_band_images(left, right, sample_rate),
        skipped=None,
    )


def _skip(reason: str) -> ImagingMetrics:
    return ImagingMetrics(
        balance_db=_NAN,
        mid_side_ratio_db=_NAN,
        position=_NAN,
        width=_NAN,
        band_images=[],
        skipped=reason,
    )


def _rms(x: np.ndarray) -> float:
    return float(np.sqrt(np.mean(x * x))) if x.size else 0.0


def _ratio_db(numerator_rms: float, denominator_rms: float) -> float:
    """``20·log10(num/den)``, clamped finite at ``±_RATIO_LIMIT_DB``.

    Either term can be exactly zero, and both directions are meaningful
    readings rather than errors: an empty right channel is a hard-left pan, an
    empty side signal is a bit-exact mono pair.
    """
    if numerator_rms <= 0.0 and denominator_rms <= 0.0:
        return _NAN
    if denominator_rms <= 0.0:
        return _RATIO_LIMIT_DB
    if numerator_rms <= 0.0:
        return -_RATIO_LIMIT_DB
    ratio_db = 20.0 * float(np.log10(numerator_rms / denominator_rms))
    return max(-_RATIO_LIMIT_DB, min(_RATIO_LIMIT_DB, ratio_db))


def _width(
    left: np.ndarray, right: np.ndarray, left_rms: float, right_rms: float
) -> float:
    """``1 - correlation`` on a ``[0, 1]`` scale, with the one-sided case
    decided rather than left to Pearson (see the module docstring)."""
    if min(left_rms, right_rms) <= QUIET_RMS:
        return 0.0
    return max(0.0, min(1.0, 1.0 - channel_correlation(left, right)))


def _band_images(
    left: np.ndarray, right: np.ndarray, sample_rate: int
) -> list[BandImage]:
    """One correlation-and-width pair per band, in ``BANDS`` order.

    Every band is present whether or not it carries signal: a missing entry
    cannot be told apart from a band nobody measured, whereas NaN says "nothing
    here" in the sentinel the rest of the report already uses.
    """
    images: list[BandImage] = []
    for name, lo_hz, hi_hz in BANDS:
        band_left = _bandpass(left, sample_rate, lo_hz, hi_hz)
        band_right = _bandpass(right, sample_rate, lo_hz, hi_hz)
        if band_left is None or band_right is None:
            images.append(BandImage(band=name, correlation=_NAN, width=_NAN))
            continue

        band_left_rms = _rms(band_left)
        band_right_rms = _rms(band_right)
        if max(band_left_rms, band_right_rms) <= QUIET_RMS:
            # Nothing in this band on either side. Correlating the filter's own
            # numerical residue would invent an image where there is no sound.
            images.append(BandImage(band=name, correlation=_NAN, width=_NAN))
            continue
        if min(band_left_rms, band_right_rms) <= QUIET_RMS:
            # The band sits entirely on one side: no pair to correlate, and a
            # point at the edge has no width.
            images.append(BandImage(band=name, correlation=_NAN, width=0.0))
            continue

        correlation = channel_correlation(band_left, band_right)
        images.append(
            BandImage(
                band=name,
                correlation=correlation,
                width=max(0.0, min(1.0, 1.0 - correlation)),
            )
        )
    return images


def _bandpass(
    channel: np.ndarray, sample_rate: int, lo_hz: float, hi_hz: float
) -> np.ndarray | None:
    """ZERO-PHASE band-pass, or ``None`` where the band cannot be measured.

    Zero-phase because the two channels must stay sample-aligned: a causal
    filter's group delay is a phase shift, and a phase shift between L and R is
    exactly the quantity being measured — a causal filter would manufacture
    decorrelation in the low bands and report it as width.

    ``None`` means the band is unmeasurable on this input: above Nyquist for
    this sample rate, or a window shorter than the filter's own padding.
    """
    from scipy.signal import butter, sosfiltfilt

    if channel.size < _MIN_BAND_SAMPLES:
        return None
    nyquist = sample_rate / 2.0
    high = min(hi_hz, nyquist * 0.99)
    if lo_hz >= high:
        return None
    sos = butter(
        _BAND_FILTER_ORDER, [lo_hz, high], btype="band", fs=sample_rate, output="sos"
    )
    filtered: np.ndarray = sosfiltfilt(sos, channel)
    return filtered


__all__ = [
    "BandImage",
    "ImagingMetrics",
    "measure_imaging",
]
