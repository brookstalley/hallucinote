"""Pairwise phase integrity — the lens that sees two surfaces DESTROYING each
other.

Every other lens in this package looks at one surface, or at one surface's
level against another's. ``stereo.py`` reads L against R *inside* a single
stem. ``masking.py`` reads magnitude overlap between two stems and answers "B
is buried under A". Neither can answer the question this module exists for:
**"A and B destroyed each other"** — the kick and the sub whose low ends
subtract instead of adding, the stem that came back from a plugin with its
polarity flipped, the part that arrives a few milliseconds late because a
device in its chain under-reported its latency. Those are not level problems.
Summing them louder makes them worse.

Three readings per pair, all of them physical:

  ``correlation``               Zero-lag Pearson on the two mono sums. ``+1`` is
                                the same signal, ``0`` unrelated material,
                                strongly negative means the two are fighting.
  ``lag_samples`` / ``lag_ms``  Where the cross-correlation peaks. Non-zero
                                means one surface arrives after the other.
  ``*_cancellation_db``         The level of ``A + B`` against the level the two
                                parts would predict if they added coherently —
                                broadband, and again per band. Negative means
                                energy went missing on the way into the sum.

**Why the lag half matters beyond phase.** An uncompensated plugin delay does
not announce itself as a delay. It announces itself as *feel*: ``timing.py``
reads the part's onsets against the grid and faithfully reports it sitting
6 ms behind the beat, which is a perfectly good description of a laid-back
performance and a perfectly wrong description of a compensation bug. Nothing
downstream can tell those apart, because at the audio they are the same thing.
A lag reading here is what stops a tooling defect being read as authorship —
the same offset, seen from the one angle where it has a cause.

**Where the line is drawn** (this module measures, it does not grade). A
polarity inversion, a sample offset and a disappeared band of energy are facts
about the audio, recoverable to arbitrary precision from the samples alone —
which is why this lens carries no listening-calibrated threshold and needs no
by-ear campaign to be trusted. What it deliberately does NOT decide is how much
cancellation is musically acceptable: two pads whose low mids partly subtract
may be exactly the arrangement the writer wanted, and a mix that reads -4 dB
between two parts sharing a register may be fine, thin, or ruined depending on
what the song is doing. That reading belongs to the interpreter, against
declared intent, like every other lens in this package.

**How to read the cancellation number.** ``0 dB`` means the two parts added
coherently — every bit of level both carried survived the sum. Two *unrelated*
parts land near ``-3 dB`` and that is the healthy, expected reading, not a
finding: uncorrelated signals sum in power, so their combined RMS is
``sqrt(2)`` times one of them where a coherent sum would be ``2`` times. Only
below that is energy genuinely being destroyed, and a deep negative on a band
where both parts are loud is the kick/sub signature this lens was built to
catch. (Same convention, same reason, as ``stereo.mono_sum_loss_db``.)

**Honest limits.**

* The cancellation is measured **as heard** — at zero lag, with whatever time
  offset the pair actually has left in place, because that offset is part of
  what destroys the energy. So a pair with a large lag reports both a lag and
  the cancellation that lag causes; they are one problem seen twice, not two.
* ``correlation`` and ``polarity_inverted`` are read at **zero lag**, so a
  flipped stem that is also offset by more than a few milliseconds reads as a
  lag rather than a flip. The lag is the more actionable of the two, and the
  flip surfaces once the offset is compensated.
* Everything here is a whole-window average. A pair that cancels hard in one
  bar and adds fine in the rest reads as mild cancellation throughout; the
  caller slices to the window it wants measured, like the rest of this package.
"""
from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
from typing import Sequence

import numpy as np

from .alignment import cross_correlation_peak_lag
from .attribution import BANDS
from .onsets import to_mono
from .stereo import QUIET_RMS

# A polarity flip on shared material reads at or near -1: the two mono sums are
# the same waveform with the sign changed. Two unrelated parts scatter around
# 0, and even a pair that genuinely fights in one register rarely sustains a
# strong negative across a whole window. -0.5 sits far from both, so no
# unrelated pair reaches it by accident, and a real flip clears it with room to
# spare even when the two surfaces are not bit-identical — different sends, a
# little reverb, a level difference. It is a bound on a one-bit fault, not a
# tuned musical threshold.
_POLARITY_CORRELATION = -0.5

# Default bound on the lag search, in seconds. A cross-correlation left free to
# roam a whole song will happily peak on a musical coincidence — two parts
# sharing a downbeat one bar apart correlate strongly at a lag no device chain
# could ever produce, and that number would be read as a delay. 50 ms is well
# past any plugin latency a session realistically carries (a lookahead limiter
# or a linear-phase EQ costs a few thousand samples) while staying far short of
# a musical interval at any tempo. A caller that knows better passes its own
# ``max_lag_samples``.
_DEFAULT_MAX_LAG_S = 0.050

# A fully-cancelling sum is -inf dB, which is neither valid JSON nor a useful
# reading. Floor it deep enough to read unambiguously as "gone" while staying
# finite: -180 dB is far below anything a capture can carry.
_CANCELLATION_FLOOR_DB = -180.0

# Zero-phase Butterworth order for the band split — matches the band energy
# work elsewhere in this package. Zero phase is not optional here: a causal
# filter gives each band its own group delay, which would introduce exactly the
# time offset this module is trying to measure.
_BAND_FILTER_ORDER = 4


@dataclass(frozen=True)
class BandCancellation:
    """How much level one band lost in the sum of a pair.

    ``sum_minus_parts_db`` is ``0`` for a coherent add, about ``-3`` for
    uncorrelated material, and deeply negative where the band cancels. ``NaN``
    where neither surface carries enough energy in the band to predict
    anything — an unmeasurable band, never a healthy 0.
    """

    band: str
    sum_minus_parts_db: float


@dataclass(frozen=True)
class PhaseRelation:
    """The phase relationship between two captured surfaces.

    When ``skipped`` is set every numeric field is unmeasurable rather than
    measured — the floats are ``NaN``, ``lag_samples`` is ``0`` and
    ``band_cancellation`` is empty. The skip is the reading. Its values are a
    closed set: ``empty_window`` (the surfaces have no samples), ``silent_a`` /
    ``silent_b`` / ``silent_both`` (one or both sides sit below the package's
    silence floor over this window, so there is no signal to relate — a
    correlation between two noise floors is an invented number).
    """

    track_id_a: str
    track_id_b: str
    correlation: float
    polarity_inverted: bool
    lag_samples: int
    lag_ms: float
    broadband_cancellation_db: float
    band_cancellation: list[BandCancellation]
    skipped: str | None = None


def measure_phase_relations(
    surfaces: Sequence[tuple[str, np.ndarray]],
    *,
    sample_rate: int,
    max_lag_samples: int | None = None,
) -> list[PhaseRelation]:
    """Measure the phase relationship of every pair of surfaces.

    Args:
        surfaces: ``(track_id, audio)`` entries, each ``(frames, 2)`` float —
            the shape the capture loader guarantees. Every surface must be the
            same length; ``alignment.trim_to_common_length`` is what makes that
            true of a real capture.
        sample_rate: samples per second, used for the lag bound and to convert
            the recovered lag into milliseconds.
        max_lag_samples: bound on the lag search, ± samples. ``None`` uses
            ``_DEFAULT_MAX_LAG_S`` at ``sample_rate`` — a plugin-latency-sized
            window rather than the whole buffer, so the peak cannot land on a
            musical coincidence and be reported as a delay.

    Returns:
        One :class:`PhaseRelation` per unordered pair, in input order (surface
        0 against 1, 0 against 2, … ). Pairs are never dropped: a pair that
        could not be measured comes back with ``skipped`` naming why.

    Raises:
        ValueError: a surface is not ``(frames, 2)``, the surfaces are not all
            the same length, or ``sample_rate`` is not positive. Each is a
            caller bug rather than an edge case — guessing a channel layout or
            relating two windows that cover different spans of time would
            produce a reading for something that was never measured.
    """
    if sample_rate <= 0:
        raise ValueError(
            f"sample_rate must be positive, got {sample_rate!r} — the lag "
            f"bound and the band edges are both defined in Hz."
        )
    for track_id, audio in surfaces:
        if audio.ndim != 2 or audio.shape[1] != 2:
            raise ValueError(
                f"surface {track_id!r} must be a stereo (frames, 2) array, got "
                f"shape={audio.shape!r} — every captured surface is float32 "
                f"stereo (see audio/io.py load_capture)."
            )
    lengths = {audio.shape[0] for _, audio in surfaces}
    if len(lengths) > 1:
        raise ValueError(
            f"every surface must cover the same window; got lengths "
            f"{sorted(lengths)}. Phase is a relationship between two signals "
            f"at the same instants, so unequal windows have no answer."
        )

    if max_lag_samples is None:
        max_lag_samples = int(round(_DEFAULT_MAX_LAG_S * sample_rate))

    # Mono-sum and band-split each surface ONCE. The bands are the expensive
    # part (a zero-phase filter pass per band per surface) and every pair a
    # surface takes part in wants the same split.
    monos = [to_mono(audio).astype(np.float64) for _, audio in surfaces]
    rms = [_rms(mono) for mono in monos]
    bands = [_split_bands(mono, sample_rate) for mono in monos]

    relations: list[PhaseRelation] = []
    for i, j in combinations(range(len(surfaces)), 2):
        track_a, audio_a = surfaces[i]
        track_b, audio_b = surfaces[j]
        skip = _skip_reason(monos[i], rms[i], rms[j])
        if skip is not None:
            relations.append(_unmeasurable(track_a, track_b, skip))
            continue

        correlation = _correlation(monos[i], monos[j])
        lag = cross_correlation_peak_lag(
            audio_a, audio_b, max_lag_samples=max_lag_samples
        )
        relations.append(PhaseRelation(
            track_id_a=track_a,
            track_id_b=track_b,
            correlation=correlation,
            polarity_inverted=correlation <= _POLARITY_CORRELATION,
            lag_samples=lag,
            lag_ms=lag / sample_rate * 1000.0,
            broadband_cancellation_db=_cancellation_db(monos[i], monos[j]),
            band_cancellation=[
                BandCancellation(
                    band=name,
                    sum_minus_parts_db=_cancellation_db(bands[i][name], bands[j][name]),
                )
                for name, _, _ in BANDS
            ],
        ))
    return relations


def _skip_reason(mono: np.ndarray, rms_a: float, rms_b: float) -> str | None:
    """Why this pair cannot be related, or ``None`` if it can.

    Silence is not a phase relationship. Two noise floors correlate at whatever
    their dither happens to do, and reporting that as a reading would put a
    number on nothing — the same trap ``stereo.py`` refuses when it returns NaN
    for a quiet window rather than the +1.0 that would read as healthy mono.
    """
    if mono.size == 0:
        return "empty_window"
    quiet_a = rms_a <= QUIET_RMS
    quiet_b = rms_b <= QUIET_RMS
    if quiet_a and quiet_b:
        return "silent_both"
    if quiet_a:
        return "silent_a"
    if quiet_b:
        return "silent_b"
    return None


def _unmeasurable(track_a: str, track_b: str, reason: str) -> PhaseRelation:
    return PhaseRelation(
        track_id_a=track_a,
        track_id_b=track_b,
        correlation=float("nan"),
        polarity_inverted=False,
        lag_samples=0,
        lag_ms=float("nan"),
        broadband_cancellation_db=float("nan"),
        band_cancellation=[],
        skipped=reason,
    )


def _rms(x: np.ndarray) -> float:
    if x.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(x**2)))


def _correlation(a: np.ndarray, b: np.ndarray) -> float:
    """Zero-lag Pearson between two mono sums.

    A constant signal has no variance, so Pearson is undefined; the honest
    answer is 0 — no shared variation means no evidence of either coherence or
    cancellation. (A pair of identical constants is not special-cased the way
    ``stereo.py`` special-cases bit-identical channels: two surfaces holding
    the same DC value is a defect for ``integrity.py`` to name, not a phase
    relationship.)
    """
    var_a = float(np.var(a))
    var_b = float(np.var(b))
    if var_a <= 0.0 or var_b <= 0.0:
        return 0.0
    corr = float(np.corrcoef(a, b)[0, 1])
    if not np.isfinite(corr):
        return 0.0
    # Float error lets a perfectly correlated pair land at 1.0000000000000002,
    # which breaks any bounded-range assertion downstream.
    return max(-1.0, min(1.0, corr))


def _cancellation_db(a: np.ndarray, b: np.ndarray) -> float:
    """Level of ``a + b`` against the level a coherent add would predict.

    The reference is the ARITHMETIC sum of the two RMS levels, which is what
    two perfectly in-phase signals actually reach — so a coherent pair reads
    exactly 0 dB and every reading below that is level the sum failed to keep.
    (Referencing the power sum instead would put in-phase material at +3 dB and
    make "no cancellation" a number nobody can hold in their head.)
    """
    rms_a = _rms(a)
    rms_b = _rms(b)
    predicted = rms_a + rms_b
    if predicted <= QUIET_RMS:
        # Neither side carries enough here to predict anything, so there is
        # nothing that could have cancelled. Unmeasurable, not 0 dB.
        return float("nan")
    actual = _rms(a + b)
    if actual <= 0.0:
        return _CANCELLATION_FLOOR_DB
    return max(_CANCELLATION_FLOOR_DB, 20.0 * float(np.log10(actual / predicted)))


def _split_bands(mono: np.ndarray, sample_rate: int) -> dict[str, np.ndarray]:
    """Band-split one mono sum into the package's shared bands.

    Returns the filtered SIGNALS, not their energies, because the cancellation
    question needs the sum of the two band-limited parts and not just their
    levels. Filtering is linear, so filtering each part and adding is the same
    signal as filtering the sum — one pass per surface per band serves every
    pair that surface appears in.
    """
    from scipy.signal import butter, sosfiltfilt

    out: dict[str, np.ndarray] = {}
    nyquist = sample_rate / 2.0
    for name, lo_hz, hi_hz in BANDS:
        hi = min(hi_hz, nyquist * 0.99)
        # A zero-phase filter pads by three times its section count at each
        # end, so a window shorter than that has nothing to filter and scipy
        # raises rather than returning something. An empty band-limited signal
        # reads as an unmeasurable band, which is the truth: the window is too
        # short to say anything about frequency at all. The broadband reading
        # above needs no such window and still stands. A band that starts above
        # Nyquist is empty for the same honest reason: this capture cannot hold
        # it.
        too_short = mono.size <= 3 * (2 * _BAND_FILTER_ORDER + 1)
        if too_short or lo_hz >= hi:
            out[name] = np.zeros_like(mono)
            continue
        sos = butter(
            _BAND_FILTER_ORDER, [lo_hz, hi], btype="band", fs=sample_rate,
            output="sos",
        )
        out[name] = sosfiltfilt(sos, mono)
    return out


__all__ = [
    "BandCancellation",
    "PhaseRelation",
    "measure_phase_relations",
]
