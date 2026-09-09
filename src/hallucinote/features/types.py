"""Shapes every feature extractor produces and every consumer reads.

``FeatureStream`` is measured in seconds against the file; ``BeatStream`` is
the same series in song beats, produced by ``FeatureStream.to_beats`` through
a ``BeatMap``. Keeping the two as distinct types is what stops a generator
from consuming seconds as if they were beats — the mistake is a type error,
not a subtly wrong part.

The package stays free of DB and MCP imports so generators may import it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol, runtime_checkable

import numpy as np


@runtime_checkable
class BeatMap(Protocol):
    """Seconds ↔ song-absolute beats, for one placed clip.

    ``audio/section.py``'s ``BeatSampleMap`` carries the tempo-aware maths;
    the wrapper that anchors it to a clip's placement and sample rate is what
    satisfies this protocol.
    """

    def seconds_to_beats(self, seconds: float) -> float: ...

    def beats_to_seconds(self, beats: float) -> float: ...


def _validate_series(
    times: np.ndarray, values: np.ndarray, confidence: np.ndarray | None, *, axis_name: str
) -> tuple[np.ndarray, np.ndarray, np.ndarray | None]:
    t = np.asarray(times, dtype=np.float64)
    v = np.asarray(values)
    if t.ndim != 1:
        raise ValueError(f"{axis_name} must be 1-D; got shape {t.shape}")
    if v.shape[:1] != t.shape:
        raise ValueError(
            f"values' first axis must match {axis_name} ({t.shape[0]}); got {v.shape}"
        )
    if t.size > 1 and np.any(np.diff(t) < 0):
        raise ValueError(f"{axis_name} must be non-decreasing")
    c: np.ndarray | None = None
    if confidence is not None:
        c = np.asarray(confidence, dtype=np.float64)
        if c.shape != t.shape:
            raise ValueError(
                f"confidence must match {axis_name} shape {t.shape}; got {c.shape}"
            )
        finite = c[np.isfinite(c)]
        if finite.size and (finite.min() < 0.0 or finite.max() > 1.0):
            raise ValueError("confidence must lie in [0, 1]")
    return t, v, c


@dataclass(frozen=True, eq=False)
class FeatureStream:
    """A feature measured over time, in seconds against the file.

    ``values`` is ``(n,)`` for a scalar feature (F0 in Hz, energy in dBFS) or
    ``(n, k)`` for a vector one (bark-band energies). Unmeasurable frames —
    unvoiced F0 — carry ``nan``, never zero: zero is a value, and a consumer
    that quantizes it gets a note nobody sang. ``confidence`` in ``[0, 1]``
    is optional and per frame.
    """

    name: str
    times_s: np.ndarray
    values: np.ndarray
    units: str
    confidence: np.ndarray | None = None

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("FeatureStream.name must be non-empty")
        t, v, c = _validate_series(self.times_s, self.values, self.confidence, axis_name="times_s")
        object.__setattr__(self, "times_s", t)
        object.__setattr__(self, "values", v)
        object.__setattr__(self, "confidence", c)

    def __len__(self) -> int:
        return int(self.times_s.shape[0])

    def to_beats(self, beat_map: BeatMap) -> "BeatStream":
        """Map the time axis through the clip's placement; values are untouched."""
        beats = np.asarray(
            [beat_map.seconds_to_beats(float(s)) for s in self.times_s], dtype=np.float64
        )
        return BeatStream(
            name=self.name,
            beats=beats,
            values=self.values,
            units=self.units,
            confidence=self.confidence,
        )


@dataclass(frozen=True, eq=False)
class BeatStream:
    """A feature stream in song-absolute beats — what a generator consumes."""

    name: str
    beats: np.ndarray
    values: np.ndarray
    units: str
    confidence: np.ndarray | None = None

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("BeatStream.name must be non-empty")
        b, v, c = _validate_series(self.beats, self.values, self.confidence, axis_name="beats")
        object.__setattr__(self, "beats", b)
        object.__setattr__(self, "values", v)
        object.__setattr__(self, "confidence", c)

    def __len__(self) -> int:
        return int(self.beats.shape[0])


@dataclass(frozen=True)
class Segment:
    """A span of the file with a kind — an onset-bounded chunk, a phrase, a rest."""

    start_s: float
    end_s: float
    kind: str
    label: str | None = None

    def __post_init__(self) -> None:
        if self.end_s < self.start_s:
            raise ValueError(
                f"Segment end {self.end_s} precedes start {self.start_s}"
            )
        if not self.kind:
            raise ValueError("Segment.kind must be non-empty")

    @property
    def duration_s(self) -> float:
        return self.end_s - self.start_s


@dataclass(frozen=True)
class FeatureEvent:
    """A moment a detector fired, in seconds; ``beat`` once mapped.

    ``payload`` carries what the detector saw (the pitch class crossed, the
    energy at the onset) so a consumer can gate on it without re-measuring.
    """

    time_s: float
    kind: str
    payload: Mapping[str, Any] = field(default_factory=dict)
    beat: float | None = None

    def __post_init__(self) -> None:
        if not self.kind:
            raise ValueError("FeatureEvent.kind must be non-empty")
        if self.time_s < 0:
            raise ValueError(f"FeatureEvent.time_s must be >= 0; got {self.time_s}")
