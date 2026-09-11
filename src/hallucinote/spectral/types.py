"""Shapes the field builders, the mask and the operation exchange.

``SpectralField`` is a magnitude surface over (frequency, time). Where it came
from is a discriminator on one type, not two types: the operation does not
care, and a caller that wants to iterate symbolic and commit measured runs the
same code twice. ``ReferenceSchedule`` says which nodes are the reference over
which beats. ``MaskParams`` are musical, bounded, and may vary per frame.
``ResolutionReport`` says what precision a field actually has, so a bass carve
can report what it achieved rather than imply what it was asked for.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal, Union

import numpy as np

# Never to silence: a carve that removes a band entirely leaves a hole the ear
# reads as a dropout, not as space. 40 dB is well past inaudible for masking
# purposes and keeps the resynthesis numerically sane.
MAX_DEPTH_DB = 40.0

Origin = Literal["symbolic", "measured"]
Polarity = Literal["carve", "vocode"]

# The engine-side address of a reference node — the inverse of the wire
# NodeAddr. ('minus', track_id) is "everything but this track": the mix minus
# the target, so a sample is never carved against its own energy.
NodeRef = Union[
    tuple[Literal["track"], str],
    tuple[Literal["return"], str],
    tuple[Literal["master"]],
    tuple[Literal["minus"], str],
]

_NODE_KINDS_WITH_ID = ("track", "return", "minus")


def validate_node_ref(ref: object) -> NodeRef:
    """Refuse anything that is not one of the four node shapes, with the shapes named."""
    if not isinstance(ref, tuple) or not ref:
        raise ValueError(
            f"NodeRef must be a tuple like ('track', id), ('return', id), "
            f"('master',) or ('minus', track_id); got {ref!r}"
        )
    kind = ref[0]
    if kind == "master":
        if len(ref) != 1:
            raise ValueError(f"('master',) takes no id; got {ref!r}")
        return ("master",)
    if kind in _NODE_KINDS_WITH_ID:
        if len(ref) != 2 or not isinstance(ref[1], str) or not ref[1]:
            raise ValueError(f"({kind!r}, id) needs a non-empty string id; got {ref!r}")
        return (kind, ref[1])  # type: ignore[return-value]
    raise ValueError(
        f"unknown node kind {kind!r}: expected 'track', 'return', 'master' or 'minus'"
    )


@dataclass(frozen=True)
class ResolutionReport:
    """What a field's analysis window can and cannot resolve.

    ``bin_hz`` is the linear bin spacing; ``achieved_cents_at_hz`` says how
    wide one bin is, in cents, at a given pitch — the number that tells you a
    2048-point window cannot place a semitone at 55 Hz. A multi-resolution
    field records its low-band window in ``low_knee_hz`` / ``low_n_fft``.
    """

    n_fft: int
    hop: int
    sample_rate: int
    low_knee_hz: float | None = None
    low_n_fft: int | None = None

    def __post_init__(self) -> None:
        for name in ("n_fft", "hop", "sample_rate"):
            if getattr(self, name) <= 0:
                raise ValueError(f"ResolutionReport.{name} must be > 0")
        if (self.low_knee_hz is None) != (self.low_n_fft is None):
            raise ValueError("low_knee_hz and low_n_fft are set together or not at all")
        if self.low_n_fft is not None and self.low_n_fft <= self.n_fft:
            raise ValueError("low_n_fft must be longer than n_fft to gain resolution")

    @property
    def bin_hz(self) -> float:
        return self.sample_rate / self.n_fft

    def bin_hz_at(self, hz: float) -> float:
        """Bin spacing in force at ``hz`` — the long window below the knee."""
        if self.low_knee_hz is not None and self.low_n_fft is not None and hz < self.low_knee_hz:
            return self.sample_rate / self.low_n_fft
        return self.bin_hz

    def achieved_cents_at_hz(self, hz: float) -> float:
        if hz <= 0:
            raise ValueError(f"hz must be > 0; got {hz}")
        return 1200.0 * math.log2((hz + self.bin_hz_at(hz)) / hz)


@dataclass(frozen=True, eq=False)
class SpectralField:
    """A magnitude surface: ``magnitude[f, t]`` at ``freqs_hz[f]``, ``times_s[t]``.

    ``fingerprint`` identifies what the field was built from — the notes read
    for a symbolic field, the capture take and analysis-code signature for a
    measured one — so a derived asset carved against it can record what it
    was derived against.
    """

    freqs_hz: np.ndarray
    times_s: np.ndarray
    magnitude: np.ndarray
    origin: Origin
    resolution: ResolutionReport
    fingerprint: str

    def __post_init__(self) -> None:
        f = np.asarray(self.freqs_hz, dtype=np.float64)
        t = np.asarray(self.times_s, dtype=np.float64)
        m = np.asarray(self.magnitude, dtype=np.float64)
        if f.ndim != 1 or t.ndim != 1:
            raise ValueError("freqs_hz and times_s must be 1-D")
        if m.shape != (f.shape[0], t.shape[0]):
            raise ValueError(
                f"magnitude must be (n_freqs, n_times) = {(f.shape[0], t.shape[0])}; "
                f"got {m.shape}"
            )
        if f.size > 1 and np.any(np.diff(f) <= 0):
            raise ValueError("freqs_hz must be strictly increasing")
        if t.size > 1 and np.any(np.diff(t) < 0):
            raise ValueError("times_s must be non-decreasing")
        if m.size and np.nanmin(m) < 0:
            raise ValueError("magnitude must be non-negative")
        if self.origin not in ("symbolic", "measured"):
            raise ValueError(f"origin must be 'symbolic' or 'measured'; got {self.origin!r}")
        if not self.fingerprint:
            raise ValueError("SpectralField.fingerprint must be non-empty")
        object.__setattr__(self, "freqs_hz", f)
        object.__setattr__(self, "times_s", t)
        object.__setattr__(self, "magnitude", m)


@dataclass(frozen=True)
class ReferenceSpan:
    """Which nodes are the reference between two song-absolute beats."""

    start_beat: float
    end_beat: float
    nodes: tuple[NodeRef, ...]

    def __post_init__(self) -> None:
        if self.end_beat <= self.start_beat:
            raise ValueError(
                f"ReferenceSpan end {self.end_beat} must be after start {self.start_beat}"
            )
        if not self.nodes:
            raise ValueError("ReferenceSpan needs at least one node")
        object.__setattr__(self, "nodes", tuple(validate_node_ref(n) for n in self.nodes))


@dataclass(frozen=True)
class ReferenceSchedule:
    """An ordered, non-overlapping set of spans — the reference as score.

    Authored per section or per bar, so "only frequencies from an instrument
    pass through, but the instrument changes" is a schedule, and diffable.
    """

    spans: tuple[ReferenceSpan, ...]

    def __post_init__(self) -> None:
        if not self.spans:
            raise ValueError("ReferenceSchedule needs at least one span")
        ordered = tuple(sorted(self.spans, key=lambda s: s.start_beat))
        for prev, nxt in zip(ordered, ordered[1:]):
            if nxt.start_beat < prev.end_beat:
                raise ValueError(
                    f"ReferenceSchedule spans overlap: [{prev.start_beat}, {prev.end_beat}) "
                    f"and [{nxt.start_beat}, {nxt.end_beat})"
                )
        object.__setattr__(self, "spans", ordered)

    @property
    def start_beat(self) -> float:
        return self.spans[0].start_beat

    @property
    def end_beat(self) -> float:
        return self.spans[-1].end_beat

    def nodes_at(self, beat: float) -> tuple[NodeRef, ...]:
        """The reference in force at ``beat``; empty between spans."""
        for span in self.spans:
            if span.start_beat <= beat < span.end_beat:
                return span.nodes
        return ()


def _per_frame(value: float | np.ndarray, *, name: str, lo: float, hi: float, lo_open: bool) -> float | np.ndarray:
    arr = np.asarray(value, dtype=np.float64)
    if arr.ndim > 1:
        raise ValueError(f"MaskParams.{name} must be a scalar or a 1-D per-frame array")
    below = (arr <= lo) if lo_open else (arr < lo)
    if np.any(below) or np.any(arr > hi):
        bound = f"({lo}, {hi}]" if lo_open else f"[{lo}, {hi}]"
        raise ValueError(f"MaskParams.{name} must lie in {bound}; got {value!r}")
    return float(arr) if arr.ndim == 0 else arr


@dataclass(frozen=True, eq=False)
class MaskParams:
    """The musical parameters of a mask. Any float may be a per-frame array.

    ``notch_width_cents`` is scaled by each band's perceptual width at apply
    time; ``depth_db`` is bounded by ``MAX_DEPTH_DB`` so a carve never
    reaches silence; ``smoothing_s`` is the temporal smoothing of the mask.
    """

    polarity: Polarity
    harmonic_depth: int
    notch_width_cents: float | np.ndarray
    depth_db: float | np.ndarray
    smoothing_s: float = 0.0

    def __post_init__(self) -> None:
        if self.polarity not in ("carve", "vocode"):
            raise ValueError(f"polarity must be 'carve' or 'vocode'; got {self.polarity!r}")
        if int(self.harmonic_depth) < 1:
            raise ValueError("harmonic_depth must be >= 1 (the fundamental alone)")
        object.__setattr__(self, "harmonic_depth", int(self.harmonic_depth))
        object.__setattr__(
            self,
            "notch_width_cents",
            _per_frame(self.notch_width_cents, name="notch_width_cents", lo=0.0, hi=2400.0, lo_open=True),
        )
        object.__setattr__(
            self,
            "depth_db",
            _per_frame(self.depth_db, name="depth_db", lo=0.0, hi=MAX_DEPTH_DB, lo_open=True),
        )
        if self.smoothing_s < 0:
            raise ValueError("smoothing_s must be >= 0")
