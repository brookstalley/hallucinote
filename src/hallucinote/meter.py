"""hallucinote.meter — the song's one bar ruler.

A song's meter is a **map**: an ordered set of points, each saying "from this bar
on, the meter is num/den". Everything that converts between bars and beats walks
that map. There is no second ruler and no ``beats_per_bar`` scalar standing in
for one — a scalar cannot express a song that changes meter, and a codebase that
carries both grows two answers to "where does bar 13 start?".

This module is a **leaf**: it imports nothing else from ``hallucinote``. That is
what lets the authoring side (``hallucinote.arrangement``) and the sync side
(``hallucinote.sync.geometry``) share one ruler without either depending on the
other — an import inversion between those two is exactly how a second ruler
would grow back.

The unit throughout is Live's: a **beat is a quarter note regardless of meter**,
so a bar of 6/8 is 3 beats and a bar of 7/8 is 3.5. Bar positions are 1-based and
may be fractional (bar 4.5 is halfway through bar 4); beat positions are 0-based
from the song's downbeat.

**Bars before the first point take that point's meter.** A map is a description
of the whole song, so a map whose earliest point is at bar 5 says nothing
different about bars 1-4 than about bar 5. This matches Live's treatment of an
unmarked region, and it is the rule every conversion here obeys in both
directions — ``beats_at`` and ``bar_at_beats`` are inverses on such a map, not
only on one with an explicit bar-1 point.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Sequence

# The meter assumed by a song that has declared none.
DEFAULT_NUMERATOR = 4
DEFAULT_DENOMINATOR = 4

# How far off a bar line or a bar's midpoint a note may sit and still read as
# landing on it. A sixty-fourth at 120bpm is ~0.06 beats, so this admits
# notation-grade rounding without admitting a deliberate off-beat placement.
STRONG_BEAT_TOLERANCE = 1e-6


def beats_per_bar(numerator: int, denominator: int) -> float:
    """Beats (quarter notes) in one bar of ``numerator``/``denominator``.

    Live counts a beat as a quarter note whatever the meter, so the count is
    ``numerator * (4 / denominator)``: 4/4 -> 4, 7/4 -> 7, 6/8 -> 3, 7/8 -> 3.5.
    """
    return numerator * (4.0 / denominator)


def parse_meter(meter: str) -> tuple[int, int]:
    """Parse the authoring spelling ``"7/4"`` into ``(7, 4)``."""
    text = meter.strip()
    num_text, sep, den_text = text.partition("/")
    if not sep:
        raise ValueError(f"meter must be spelled 'num/den' (e.g. '7/4'), got {meter!r}")
    try:
        numerator, denominator = int(num_text), int(den_text)
    except ValueError:
        raise ValueError(
            f"meter must be spelled 'num/den' with whole numbers, got {meter!r}"
        ) from None
    if numerator <= 0 or denominator <= 0:
        raise ValueError(
            f"meter numerator/denominator must be positive, got {meter!r}"
        )
    return numerator, denominator


def format_meter(numerator: int, denominator: int) -> str:
    """The inverse of :func:`parse_meter` — ``(7, 4)`` -> ``"7/4"``."""
    return f"{numerator}/{denominator}"


@dataclass(frozen=True)
class MeterPoint:
    """One entry in the map: from ``start_bar`` on, the meter is num/den.

    ``start_bar`` is 1-based, matching ``time_signature_map.start_bar``, and may
    be fractional only in the sense the schema allows — in practice a meter
    change begins at a bar line.
    """

    start_bar: float
    numerator: int
    denominator: int

    def __post_init__(self) -> None:
        if self.start_bar < 1.0:
            raise ValueError(
                f"MeterPoint.start_bar must be >= 1.0 per the 1-based bar "
                f"convention, got {self.start_bar!r}"
            )
        if self.numerator <= 0 or self.denominator <= 0:
            raise ValueError(
                f"MeterPoint numerator/denominator must be positive, got "
                f"{self.numerator}/{self.denominator}"
            )

    @property
    def beats_per_bar(self) -> float:
        return beats_per_bar(self.numerator, self.denominator)

    @property
    def meter(self) -> str:
        return format_meter(self.numerator, self.denominator)


@dataclass(frozen=True)
class BarGrid:
    """The bar lines of one span, measured from the span's own start.

    A read-side lens grades a note against *its* bar — where the bar line is and
    how long the bar runs — and a span that crosses a meter change has bars of
    different lengths in it. That is the whole difference between this and the
    ``beats_per_bar`` scalar it replaces: the scalar can only answer
    ``beat % beats_per_bar``, which is wrong for every bar after a change.

    ``bar_starts[i]`` is bar ``i``'s downbeat as a span-relative beat offset;
    ``bar_lengths[i]`` is its length in beats. Always at least one bar.
    """

    bar_starts: tuple[float, ...]
    bar_lengths: tuple[float, ...]

    def __post_init__(self) -> None:
        if not self.bar_starts:
            raise ValueError("BarGrid must cover at least one bar")
        if len(self.bar_starts) != len(self.bar_lengths):
            raise ValueError(
                f"BarGrid bar_starts/bar_lengths length mismatch: "
                f"{len(self.bar_starts)} vs {len(self.bar_lengths)}"
            )

    @classmethod
    def uniform(cls, beats_per_bar_: float, length_beats: float) -> "BarGrid":
        """The single-meter grid — what a ``beats_per_bar`` scalar meant."""
        if beats_per_bar_ <= 0:
            raise ValueError(f"beats_per_bar must be > 0, got {beats_per_bar_}")
        count = max(1, int(round(length_beats / beats_per_bar_)))
        return cls(
            bar_starts=tuple(i * beats_per_bar_ for i in range(count)),
            bar_lengths=tuple(beats_per_bar_ for _ in range(count)),
        )

    def bar_index_at(self, beat: float) -> int:
        """Which bar of the span ``beat`` falls in (clamped to the span)."""
        index = 0
        for i, start in enumerate(self.bar_starts):
            if start <= beat + STRONG_BEAT_TOLERANCE:
                index = i
            else:
                break
        return index

    def beats_per_bar_at(self, beat: float) -> float:
        """The length of the bar ``beat`` falls in."""
        return self.bar_lengths[self.bar_index_at(beat)]

    def is_strong_beat(self, beat: float, *, tolerance: float) -> bool:
        """Does ``beat`` land on its own bar's downbeat or midpoint?

        The canonical strong beats of a common-time-like bar are 1 and the
        halfway point — read against the bar the note is actually in, so a 7/4
        bar's midpoint is beat 3.5 of that bar and not the song's beat 2.
        """
        index = self.bar_index_at(beat)
        offset = beat - self.bar_starts[index]
        length = self.bar_lengths[index]
        return (
            abs(offset) <= tolerance
            or abs(offset - length / 2.0) <= tolerance
            or abs(offset - length) <= tolerance
        )


class MeterMap:
    """A song's meter, as the ordered set of points that define it.

    Construct from authored points, from ``time_signature_map`` rows
    (:meth:`from_rows`), or as a single-meter song (:meth:`uniform`). Immutable:
    :meth:`with_point` returns a new map.
    """

    __slots__ = ("_points",)

    def __init__(self, points: Iterable[MeterPoint] = ()) -> None:
        ordered = sorted(points, key=lambda p: p.start_bar)
        for earlier, later in zip(ordered, ordered[1:]):
            if abs(earlier.start_bar - later.start_bar) < 1e-9:
                raise ValueError(
                    f"two meter points declared at bar {earlier.start_bar}: "
                    f"{earlier.meter} and {later.meter} — a bar has one meter"
                )
        self._points: tuple[MeterPoint, ...] = tuple(ordered)

    # -- construction ------------------------------------------------------

    @classmethod
    def uniform(
        cls,
        beats_per_bar_: float = 4.0,
        *,
        denominator: int = DEFAULT_DENOMINATOR,
    ) -> "MeterMap":
        """A single-meter song expressed as a one-point map.

        This is the bridge from the ``beats_per_bar`` scalar: 4.0 -> 4/4,
        3.0 -> 3/4, 7.0 -> 7/4. A scalar cannot distinguish 6/8 from 3/4 (both
        are 3 beats) — that is one of the reasons it is not the ruler — so a
        song that means 6/8 declares ``"6/8"`` rather than passing 3.0.
        """
        if beats_per_bar_ <= 0:
            raise ValueError(f"beats_per_bar must be > 0, got {beats_per_bar_}")
        numerator = beats_per_bar_ * denominator / 4.0
        if abs(numerator - round(numerator)) > 1e-9:
            raise ValueError(
                f"beats_per_bar={beats_per_bar_} is not a whole number of "
                f"1/{denominator} notes; declare the meter as 'num/den' instead"
            )
        return cls((MeterPoint(1.0, int(round(numerator)), denominator),))

    @classmethod
    def from_rows(cls, rows: Sequence[Any] | None) -> "MeterMap":
        """Adapt ``time_signature_map`` rows — the one place DB rows become a map.

        Accepts anything indexable by column name (``sqlite3.Row``, a dict).
        """
        if not rows:
            return cls(())
        return cls(
            MeterPoint(
                float(row["start_bar"]),
                int(row["numerator"]),
                int(row["denominator"]),
            )
            for row in rows
        )

    @classmethod
    def parse(cls, meter: str) -> "MeterMap":
        """A single-meter map from the authoring spelling — ``"7/4"``."""
        numerator, denominator = parse_meter(meter)
        return cls((MeterPoint(1.0, numerator, denominator),))

    def with_point(self, point: MeterPoint) -> "MeterMap":
        """This map plus ``point``. Redeclaring a bar's meter identically is a
        no-op; redeclaring it differently raises, because the composer has said
        two things about one bar and neither of us should pick."""
        for existing in self._points:
            if abs(existing.start_bar - point.start_bar) < 1e-9:
                if (existing.numerator, existing.denominator) == (
                    point.numerator,
                    point.denominator,
                ):
                    return self
                raise ValueError(
                    f"bar {point.start_bar:g} is already declared "
                    f"{existing.meter}; cannot also declare {point.meter}"
                )
        return MeterMap(self._points + (point,))

    # -- the map itself ----------------------------------------------------

    @property
    def points(self) -> tuple[MeterPoint, ...]:
        return self._points

    @property
    def is_uniform(self) -> bool:
        """True when the whole song is one meter (zero or one point)."""
        return len(self._points) <= 1

    def as_rows(self) -> list[dict[str, Any]]:
        """The map as ``time_signature_map``-shaped dicts, in bar order."""
        return [
            {
                "start_bar": p.start_bar,
                "numerator": p.numerator,
                "denominator": p.denominator,
            }
            for p in self._points
        ]

    def describe(self) -> str:
        """One line per point — what a composer prints to check what they said."""
        if not self._points:
            return f"{DEFAULT_NUMERATOR}/{DEFAULT_DENOMINATOR} throughout (declared none)"
        return " · ".join(f"bar {p.start_bar:g} -> {p.meter}" for p in self._points)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, MeterMap):
            return NotImplemented
        return self._points == other._points

    def __hash__(self) -> int:
        return hash(self._points)

    def __repr__(self) -> str:
        return f"MeterMap({self.describe()})"

    # -- reading the ruler -------------------------------------------------

    def meter_at(self, bar: float) -> tuple[int, int]:
        """The (numerator, denominator) in force at a 1-based bar position."""
        if not self._points:
            return (DEFAULT_NUMERATOR, DEFAULT_DENOMINATOR)
        chosen = self._points[0]
        for point in self._points:
            if point.start_bar <= bar:
                chosen = point
            else:
                break
        return (chosen.numerator, chosen.denominator)

    def beats_per_bar_at(self, bar: float) -> float:
        """Beats in the bar at a 1-based bar position."""
        return beats_per_bar(*self.meter_at(bar))

    def beats_at(self, bar: float) -> float:
        """Beats from the song's downbeat to a 1-based fractional bar position.

        ``beats_at(1.0)`` is 0.0. In 4/4, ``beats_at(17.0)`` is 64.0 and
        ``beats_at(17.5)`` is 66.0. Across a change the accumulated beats carry
        each region's own bar length.
        """
        if bar < 1.0:
            raise ValueError(
                f"bar must be >= 1.0 per the 1-based bar convention, got {bar!r}"
            )
        if not self._points:
            return (bar - 1.0) * beats_per_bar(DEFAULT_NUMERATOR, DEFAULT_DENOMINATOR)

        beats = 0.0
        current_bar = 1.0
        current_bpb = self._points[0].beats_per_bar
        for point in self._points:
            if point.start_bar <= current_bar:
                # At or before where the walk starts — adopt its meter and go on.
                # This is both the ordinary bar-1 point and the rule that bars
                # before the first point take that point's meter.
                current_bpb = point.beats_per_bar
                continue
            if bar < point.start_bar:
                return beats + (bar - current_bar) * current_bpb
            beats += (point.start_bar - current_bar) * current_bpb
            current_bar = point.start_bar
            current_bpb = point.beats_per_bar
        return beats + (bar - current_bar) * current_bpb

    def bar_at_beats(self, beats: float) -> float:
        """The inverse of :meth:`beats_at` — a 1-based fractional bar position."""
        if not self._points:
            return 1.0 + float(beats) / beats_per_bar(
                DEFAULT_NUMERATOR, DEFAULT_DENOMINATOR
            )

        target = float(beats)
        cumulative = 0.0
        current_bar = 1.0
        current_bpb = self._points[0].beats_per_bar
        for point in self._points:
            if point.start_bar <= current_bar:
                current_bpb = point.beats_per_bar
                continue
            span = (point.start_bar - current_bar) * current_bpb
            if cumulative + span > target - 1e-9:
                return current_bar + (target - cumulative) / current_bpb
            cumulative += span
            current_bar = point.start_bar
            current_bpb = point.beats_per_bar
        return current_bar + (target - cumulative) / current_bpb

    def split_bar(self, bar: float) -> tuple[int, float]:
        """Split a 1-based fractional bar into ``(bar_int, beat_within_bar)``.

        The ``(bar: int 1-based, beat: float 0-based within the bar)`` shape
        Live's MCP tools use. ``4.5`` in 4/4 -> ``(4, 2.0)``.
        """
        if bar < 1.0:
            raise ValueError(
                f"bar must be >= 1.0 per the 1-based bar convention, got {bar!r}"
            )
        bar_int = int(bar)
        return bar_int, (bar - bar_int) * self.beats_per_bar_at(bar)

    def join_bar_beat(self, bar: int, beat: float) -> float:
        """The inverse of :meth:`split_bar`."""
        return float(bar) + (float(beat) / self.beats_per_bar_at(bar))

    def grid_for(self, start_bar: float, end_bar: float) -> BarGrid:
        """The bar lines of ``[start_bar, end_bar)``, relative to ``start_bar``.

        What a read-side lens grades against: each bar's downbeat as an offset
        from the span's start, and each bar's own length.
        """
        if end_bar <= start_bar:
            raise ValueError(
                f"grid_for needs end_bar > start_bar, got {start_bar} -> {end_bar}"
            )
        origin = self.beats_at(start_bar)
        starts: list[float] = []
        lengths: list[float] = []
        bar = float(start_bar)
        while bar < end_bar - 1e-9:
            next_bar = min(bar + 1.0, float(end_bar))
            starts.append(self.beats_at(bar) - origin)
            lengths.append(self.beats_at(next_bar) - self.beats_at(bar))
            bar = next_bar
        return BarGrid(tuple(starts), tuple(lengths))


__all__ = [
    "DEFAULT_DENOMINATOR",
    "DEFAULT_NUMERATOR",
    "STRONG_BEAT_TOLERANCE",
    "BarGrid",
    "MeterMap",
    "MeterPoint",
    "beats_per_bar",
    "format_meter",
    "parse_meter",
]
