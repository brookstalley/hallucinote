"""Stem-sum vs master reconciliation — the one number that validates the whole
capture rather than any surface inside it.

Every other lens in the report analyses the surfaces it was handed, one at a
time or pairwise, and grades what it finds. None of them can ask the prior
question: **was that set of surfaces complete?** A stem that was never captured,
a send that never reached the master, a track muted in the capture but audible
in the render — none of that is visible to a lens that only ever sees the stems
it was given. It is visible here, because the master is an independent witness:
if the stems, summed at their fader gains, do not reconstruct the captured
master, then something reached the master that the model does not know about,
or something the model knows about never reached the master. That is the class
of failure this module exists to surface, and it is the only place in the
report where a *missing* surface can announce itself.

**This lens reports a residual and its distribution. It does not assert a
pass/fail, and it must not be read as one.** Two independent reasons:

* The reconstruction is approximate by construction. ``levels.py`` rebuilds
  mix level from the static fader curve only — no volume automation, and
  deliberately no pan (see its module doc). ``masking.py``, which depends on
  the same reconstruction, carries the same known accuracy limits. So a small
  residual is the expected steady state of a healthy render, not a defect.
* **The master chain is allowed to be nonlinear.** A limiter, a saturator, a
  bus compressor or a clipper on the master will produce a residual no linear
  sum can ever cancel. That residual is a *true fact about the render* — the
  master chain did something — and not an error in this math. A mix with a
  hard-working master limiter and a mix with an unrouted stem can both read
  "residual -12 dB"; only a human reading the shape below can tell them apart.

There is therefore no threshold in this module that decides which residual is
acceptable. Instead the returned shape is built so the four interesting
outcomes look *different from each other*:

* **The sum is faithful** — ``residual_db`` far below the master, ``correlation``
  near 1, ``gain_offset_db`` near 0, band residuals all low, no offender.
* **The sum is off by a flat gain** — ``gain_offset_db`` carries it, and because
  the residual is measured *after* gain matching, the residual stays low. A
  trim somewhere in the master chain looks nothing like a missing part.
* **The sum is off in one band** — one entry in ``band_residuals`` stands far
  above its neighbours. An EQ move, a high-pass on the master, or a sub-only
  element that never made it. Read the band residuals **against each other**,
  not against an absolute floor: they share one broadband gain match, so a
  discrepancy large enough to move that fit lifts every band by the same trim.
  The separation between bands is the finding; the common offset is not.
* **One stem is the culprit** — ``worst_offender`` names the stem whose exclusion
  from the sum most improves the fit: a stem the master does not actually
  contain (an unrouted send, a track muted downstream of the tap).

The asymmetry in that last one is deliberate and worth stating: leave-one-out
can only name a stem it was *given*. A surface that was never captured at all
raises the residual and names nobody — a high residual with no offender is
itself the signature of "there is something in this master we never saw".

Measurement domain
==================

Everything is measured on the mono sum. The captured stems are pre-fader and
therefore also **pre-pan** (Live applies pan after the device chain the
analyzer taps), so a per-channel comparison against a panned master would
attribute the pan law to a residual it cannot fix. Mono-summing removes most of
that, but not all of it: constant-power pan leaves a hard-panned element up to
~3 dB down in the mono sum relative to a centred one, so a wide mix carries a
real, unavoidable residual floor here. Pan-blindness is a limit of this lens,
not a defect it detects.

Time offset is measured, reported and then compensated before the residual is
computed. The master is captured from a device sitting in the master chain, so
any lookahead in that chain delays it relative to the stems by a fixed amount;
that offset is a genuine finding (``best_lag_samples``), which is why it is
surfaced rather than quietly removed. ``alignment.py`` is this repo's home for
lag machinery; the peak-lag search below is local to this module and is a
candidate for de-duplication once that module carries a shared helper.

Pure DSP, DB-agnostic, like the rest of the package: the caller hands over
whatever audio it wants reconciled and this module has no opinion about tempo,
sections or beats.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

import numpy as np

# The band edges and the zero-phase filter that measures energy inside them are
# one thing, and attribution.py is where it lives — importing the measurement
# alongside the edges keeps a single definition of "energy in this band" rather
# than two that can drift apart.
from .attribution import BANDS, band_energy
from .levels import apply_stem_gains, live_fader_gain
from .onsets import to_mono

# The peak-lag search is bounded because an unbounded argmax over a long
# capture will happily match the wrong cycle of a periodic signal and call it a
# latency. Every real offset this lens can encounter is a device-chain
# lookahead: even a mastering limiter's lookahead is a few tens of
# milliseconds, so a quarter second is generous by an order of magnitude, and a
# "lag" beyond it is a different failure (the wrong master paired with these
# stems) that a larger search window would only dress up as a small one.
_MAX_LAG_S = 0.25

# Residual floor. An exact reconstruction cancels to the arithmetic noise of
# float32 accumulation, which is around -140 dB; reporting -infinity or -280 dB
# invites a reader to compare two numbers that both mean "identical". Anything
# at or below this is reported as this value and means "identical within the
# precision the capture format can even represent".
_MIN_RESIDUAL_DB = -120.0

# A band the master has essentially no energy in has no residual worth quoting:
# the ratio of two near-zero RMS values is numerically meaningless and reads as
# a huge finding. A band whose master RMS is more than this far below the
# broadband master RMS is reported as NaN — honestly unmeasured — the same
# sentinel the rest of the report uses for "nothing to measure here".
_BAND_ENERGY_FLOOR_DB = 80.0

# Leave-one-out names a stem only when removing it improves the fit by more
# than this. Below it the "improvement" is inside the reconstruction's own
# accuracy (static-fader-only levels, pan-blindness, a nonlinear master chain),
# so naming a suspect would be asserting more than the evidence carries. This
# is a floor on the DIAGNOSTIC, not a verdict on the residual: it decides
# whether a stem may be named, never whether a render is acceptable.
_OFFENDER_MIN_IMPROVEMENT_DB = 1.0

_EPS = 1e-20


@dataclass(frozen=True)
class BandResidual:
    """Residual in one of ``attribution.BANDS``, relative to the master's own
    energy in that band. ``residual_db`` is NaN (→ JSON ``null``) when the
    master carries no meaningful energy in the band — nothing to reconcile."""

    band: str
    residual_db: float


@dataclass(frozen=True)
class SumReconciliation:
    """How well the gain-applied stem sum reconstructs the captured master.

    Diagnostic evidence, never a verdict — see the module doc for why no field
    here decides whether a render is acceptable.

      ``residual_db``       RMS of (master − aligned, gain-matched sum) relative
                            to the RMS of the master, in dB. Lower is a closer
                            reconstruction; ``_MIN_RESIDUAL_DB`` means identical
                            to within float precision.
      ``correlation``       Pearson correlation between the aligned sum and the
                            master. Near 1 means the sum has the right shape
                            even where it has the wrong level; a low value means
                            the sum and the master are not the same material.
      ``best_lag_samples``  Samples by which the master lags the stem sum.
                            Positive = the master arrives later (the expected
                            master-chain lookahead case). Non-zero is itself a
                            finding; the residual is measured after compensating
                            for it, so a latency never masquerades as a missing
                            part.
      ``gain_offset_db``    Least-squares flat gain applied to the sum to best
                            match the master, in dB. Positive = the master is
                            hotter than the summed stems. Separated from the
                            residual on purpose: "everything is 2 dB quiet" and
                            "one part is missing" must not look alike. NaN when
                            the best fit is a NEGATIVE gain — the sum is
                            polarity-inverted against the master, which
                            ``correlation`` carries as a negative value.
      ``band_residuals``    The same residual per ``attribution.BANDS`` band,
                            after the SAME broadband gain match — so a
                            band-limited discrepancy stands out against its
                            neighbours instead of being averaged away.
      ``worst_offender``    The stem whose exclusion from the sum most improves
                            the fit, or ``None`` when no exclusion helps by more
                            than ``_OFFENDER_MIN_IMPROVEMENT_DB``. Turns "the
                            capture does not add up" into "it is this track".
      ``gains_assumed_unity``  True when no fader gain was supplied for any
                            stem, so the sum is of raw captures. Every number
                            above is then a reconstruction of a mix nobody set
                            the levels of, which is worth knowing before reading
                            them.
      ``skipped``           A structured reason when nothing could be measured,
                            in which case the float fields are NaN. The complete
                            set is ``invalid_sample_rate`` / ``no_stems`` /
                            ``empty_audio`` / ``silent_master`` /
                            ``silent_stem_sum``.
    """

    residual_db: float
    correlation: float
    best_lag_samples: int
    gain_offset_db: float
    band_residuals: list[BandResidual]
    worst_offender: str | None
    gains_assumed_unity: bool = False
    skipped: str | None = None


def reconcile_stem_sum(
    stems: Sequence[tuple[str, np.ndarray]],
    master: np.ndarray,
    *,
    sample_rate: int,
    stem_gains: Mapping[str, float] | None = None,
) -> SumReconciliation:
    """Sum ``stems`` at their fader gains and compare against ``master``.

    ``stems`` entries are ``(track_id, audio)``, mono ``(n,)`` or stereo
    ``(n, 2)``; ``master`` is the captured master surface in either shape.
    ``stem_gains`` maps track_id → Live's **normalized 0..1 fader volume** (the
    value ``tracks.volume`` carries), converted here through the calibrated
    curve in ``levels.py``. A track missing from the map is summed at unity, the
    same pass-through ``levels.apply_stem_gains`` documents; omitting the map
    entirely sums raw captures and says so via ``gains_assumed_unity``.

    Surfaces of unequal length are compared over their common leading samples,
    which is the invariant ``alignment.trim_to_common_length`` establishes for
    the real capture path.
    """
    if sample_rate <= 0:
        return _skip(f"invalid_sample_rate: sample_rate={sample_rate}")
    if not stems:
        return _skip("no_stems: nothing to sum against the master")

    supplied = dict(stem_gains) if stem_gains else {}
    gains_assumed_unity = not any(track_id in supplied for track_id, _ in stems)

    # Live's normalized fader value is not a gain — the curve between them is
    # calibrated in levels.py, and this is its second read-side consumer.
    linear_gains = {
        track_id: live_fader_gain(value) for track_id, value in supplied.items()
    }
    scaled = apply_stem_gains(
        [(track_id, to_mono(audio).astype(np.float64)) for track_id, audio in stems],
        linear_gains,
    )

    master_mono = to_mono(master).astype(np.float64)
    common = min([master_mono.shape[0], *(a.shape[0] for _, a in scaled)])
    if common == 0:
        return _skip(
            "empty_audio: a surface has no samples",
            gains_assumed_unity=gains_assumed_unity,
        )

    master_mono = master_mono[:common]
    scaled = [(track_id, audio[:common]) for track_id, audio in scaled]
    summed = np.sum([audio for _, audio in scaled], axis=0)

    if _rms(master_mono) <= _EPS:
        return _skip(
            "silent_master: the master carries no energy to reconcile against",
            gains_assumed_unity=gains_assumed_unity,
        )
    if _rms(summed) <= _EPS:
        return _skip(
            "silent_stem_sum: every stem summed to silence, so the master's "
            "content is entirely unaccounted for",
            gains_assumed_unity=gains_assumed_unity,
        )

    lag = _peak_lag(summed, master_mono, sample_rate)
    sum_seg, master_seg = _overlap_at_lag(summed, master_mono, lag)
    if sum_seg.shape[0] == 0 or _rms(master_seg) <= _EPS:
        return _skip(
            "empty_audio: the lag-compensated overlap carries no signal",
            gains_assumed_unity=gains_assumed_unity,
        )

    gain, residual = _gain_matched_residual(sum_seg, master_seg)

    return SumReconciliation(
        residual_db=_relative_db(_rms(residual), _rms(master_seg)),
        correlation=_correlation(sum_seg, master_seg),
        best_lag_samples=lag,
        gain_offset_db=_amplitude_db(gain),
        band_residuals=_band_residuals(residual, master_seg, sample_rate),
        worst_offender=_worst_offender(scaled, master_mono, lag),
        gains_assumed_unity=gains_assumed_unity,
    )


# --------------------------------------------------------------------------- #
# Reconstruction comparison
# --------------------------------------------------------------------------- #

def _gain_matched_residual(
    sum_seg: np.ndarray, master_seg: np.ndarray
) -> tuple[float, np.ndarray]:
    """Least-squares flat gain for the sum, and what the master keeps after it.

    Solving for the single scalar that best explains the master is what makes
    the flat-gain question independent of the missing-content question: a
    console trim, a master-fader move or an unapplied fader calibration is
    absorbed into ``gain``, leaving ``residual`` to carry only what no level
    change could have fixed.
    """
    denominator = float(np.dot(sum_seg, sum_seg))
    gain = float(np.dot(sum_seg, master_seg) / denominator) if denominator > 0.0 else 0.0
    return gain, master_seg - gain * sum_seg


def _band_residuals(
    residual: np.ndarray, master_seg: np.ndarray, sample_rate: int
) -> list[BandResidual]:
    """Per-band residual under the broadband gain match, in ``BANDS`` order.

    Deliberately NOT re-gain-matched per band: a per-band fit would absorb the
    very thing the band split exists to expose — a high-pass on the master or a
    sub element that never arrived would be flattened into six healthy numbers.
    """
    master_broadband = _rms(master_seg)
    floor = master_broadband * 10.0 ** (-_BAND_ENERGY_FLOOR_DB / 20.0)
    out: list[BandResidual] = []
    for band_name, lo_hz, hi_hz in BANDS:
        master_band = band_energy(master_seg, sample_rate, lo_hz, hi_hz)
        if master_band <= floor:
            out.append(BandResidual(band=band_name, residual_db=float("nan")))
            continue
        residual_band = band_energy(residual, sample_rate, lo_hz, hi_hz)
        out.append(
            BandResidual(
                band=band_name,
                residual_db=_relative_db(residual_band, master_band),
            )
        )
    return out


def _worst_offender(
    scaled: Sequence[tuple[str, np.ndarray]],
    master_mono: np.ndarray,
    lag: int,
) -> str | None:
    """The stem whose removal from the sum most improves the fit.

    Leave-one-out at the SAME lag as the full sum: re-deriving a lag per subset
    would let a spurious peak on a thinned sum masquerade as an improvement,
    and the offset being tested here is a property of the master chain, not of
    which stems are in the sum. Each subset is re-gain-matched, so a stem is
    named for the content it contributes, never for the level it sits at.
    """
    if len(scaled) < 2:
        return None

    total = np.sum([audio for _, audio in scaled], axis=0)
    baseline = _residual_db_at_lag(total, master_mono, lag)
    if not np.isfinite(baseline):
        return None

    best_name: str | None = None
    best_improvement = _OFFENDER_MIN_IMPROVEMENT_DB
    for track_id, audio in scaled:
        without = _residual_db_at_lag(total - audio, master_mono, lag)
        if not np.isfinite(without):
            continue
        improvement = baseline - without
        if improvement > best_improvement:
            best_improvement = improvement
            best_name = track_id
    return best_name


def _residual_db_at_lag(
    summed: np.ndarray, master_mono: np.ndarray, lag: int
) -> float:
    """Gain-matched residual of one candidate sum, in dB relative to the master."""
    sum_seg, master_seg = _overlap_at_lag(summed, master_mono, lag)
    if sum_seg.shape[0] == 0 or _rms(master_seg) <= _EPS:
        return float("nan")
    _, residual = _gain_matched_residual(sum_seg, master_seg)
    return _relative_db(_rms(residual), _rms(master_seg))


# --------------------------------------------------------------------------- #
# Lag
# --------------------------------------------------------------------------- #
# alignment.py is the repo's home for lag machinery; this search is local so
# this module stands alone, and is a de-duplication candidate the moment that
# module exposes a shared peak-lag helper.

def _peak_lag(summed: np.ndarray, master_mono: np.ndarray, sample_rate: int) -> int:
    """Sample lag at which the master is best explained by the stem sum.

    Positive = the master arrives later than the sum. Both signals are
    mean-removed first so a DC offset in either cannot drag the correlation
    peak toward zero lag.
    """
    from scipy.signal import correlate, correlation_lags

    a = summed - float(np.mean(summed))
    b = master_mono - float(np.mean(master_mono))
    xcorr = correlate(b, a, mode="full", method="fft")
    lags = correlation_lags(b.size, a.size, mode="full")

    max_lag = int(_MAX_LAG_S * sample_rate)
    in_range = np.abs(lags) <= max_lag
    if not np.any(in_range):
        return 0
    candidates = xcorr[in_range]
    return int(lags[in_range][int(np.argmax(np.abs(candidates)))])


def _overlap_at_lag(
    summed: np.ndarray, master_mono: np.ndarray, lag: int
) -> tuple[np.ndarray, np.ndarray]:
    """The region where the two signals describe the same instant, given ``lag``."""
    n = min(summed.shape[0], master_mono.shape[0])
    if lag >= 0:
        if lag >= n:
            return summed[:0], master_mono[:0]
        return summed[: n - lag], master_mono[lag:n]
    shift = -lag
    if shift >= n:
        return summed[:0], master_mono[:0]
    return summed[shift:n], master_mono[: n - shift]


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #

def _skip(reason: str, *, gains_assumed_unity: bool = False) -> SumReconciliation:
    """A reading that did not happen, saying why — never a zero dressed as one."""
    return SumReconciliation(
        residual_db=float("nan"),
        correlation=float("nan"),
        best_lag_samples=0,
        gain_offset_db=float("nan"),
        band_residuals=[],
        worst_offender=None,
        gains_assumed_unity=gains_assumed_unity,
        skipped=reason,
    )


def _rms(signal: np.ndarray) -> float:
    if signal.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(np.square(signal))))


def _relative_db(value: float, reference: float) -> float:
    """``value`` relative to ``reference`` in dB, floored at ``_MIN_RESIDUAL_DB``."""
    if reference <= 0.0:
        return float("nan")
    if value <= 0.0:
        return _MIN_RESIDUAL_DB
    return max(20.0 * float(np.log10(value / reference)), _MIN_RESIDUAL_DB)


def _amplitude_db(gain: float) -> float:
    if gain <= 0.0:
        return float("nan")
    return 20.0 * float(np.log10(gain))


def _correlation(a: np.ndarray, b: np.ndarray) -> float:
    a_centered = a - float(np.mean(a))
    b_centered = b - float(np.mean(b))
    denominator = float(np.linalg.norm(a_centered) * np.linalg.norm(b_centered))
    if denominator <= 0.0:
        return float("nan")
    return float(np.dot(a_centered, b_centered) / denominator)


__all__ = [
    "BandResidual",
    "SumReconciliation",
    "reconcile_stem_sum",
]
