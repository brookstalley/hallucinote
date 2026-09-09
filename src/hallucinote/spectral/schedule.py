"""Author the reference schedule — which nodes are the reference, over which beats.

A ``ReferenceSchedule`` is score: "only frequencies from an instrument pass
through, but the instrument changes" is a list of spans, each naming the
nodes in force, authored per section or per bar and diffable like a part.
The shapes validate themselves (``types.py``); this module is how they are
built from the things an author already has — a handful of spans, the
song's sections, or a wire ``NodeAddr`` — and how a schedule is digested
into a fingerprint.

Discipline: this module reads no state at import. Generators and
``build.py`` import it, so the DB is reached only inside
``node_ref_from_addr``, lazily, where a wire address has to become a DB id.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from typing import Any, Callable, Iterable, Mapping, Protocol, Sequence

from hallucinote.spectral.types import (
    NodeRef,
    ReferenceSchedule,
    ReferenceSpan,
    validate_node_ref,
)

# Live's default meter, and the uniform ruler ``hallucinote.arrangement`` counts
# bars on when a song declares no meter change.
DEFAULT_BEATS_PER_BAR = 4.0

# The wire terminals that name a node with a captured surface. A device or a
# chain sits inside a node and has no surface of its own, so it cannot be a
# spectral reference.
_SURFACE_TERMINALS = ("track", "return", "master")


class SectionLike(Protocol):
    """What ``schedule_from_sections`` needs from a section: a ``sections``
    row or any mapping with ``name`` / ``start_bar`` / ``end_bar``."""

    def __getitem__(self, key: str) -> Any: ...


def schedule_from_spans(
    spans: Iterable[tuple[float, float, Sequence[NodeRef]]],
) -> ReferenceSchedule:
    """Build a schedule from ``(start_beat, end_beat, nodes)`` triples.

    The type refuses overlap, a reversed span and an empty node set; this
    adds only the teaching an empty list deserves, so an author who built
    the list from a filter that matched nothing hears that rather than a
    dataclass complaint.
    """
    built = [
        ReferenceSpan(start_beat=float(start), end_beat=float(end), nodes=tuple(nodes))
        for start, end, nodes in spans
    ]
    if not built:
        raise ValueError(
            "schedule_from_spans got no spans: a reference schedule needs at least "
            "one (start_beat, end_beat, nodes) span — use constant_schedule(...) "
            "for one reference over the whole range"
        )
    return ReferenceSchedule(spans=tuple(built))


def constant_schedule(
    start_beat: float, end_beat: float, nodes: Sequence[NodeRef]
) -> ReferenceSchedule:
    """One reference over one range — the schedule most carves start from."""
    return schedule_from_spans([(start_beat, end_beat, nodes)])


def schedule_from_sections(
    sections: Sequence[SectionLike],
    reference: Mapping[str, Sequence[NodeRef]],
    *,
    default: Sequence[NodeRef] | None = None,
    bar_to_beat: Callable[[float], float] | None = None,
    beats_per_bar: float = DEFAULT_BEATS_PER_BAR,
) -> ReferenceSchedule:
    """A reference per section, so the schedule reads like the arrangement.

    ``reference`` maps a section NAME to its nodes; a name that repeats
    (``vary()`` recapitulates names) applies to every section carrying it.
    ``default`` covers the sections not named; without it those sections get
    no span, which the schedule reports as no reference in force there.
    Bars become beats through ``bar_to_beat`` when given — pass the song's
    meter walk (``symbolic.bar_to_beat_for_song``) so a meter change lands
    where push puts it — else on the uniform ``beats_per_bar`` ruler.
    """
    names = [str(s["name"]) for s in sections]
    unknown = sorted(set(reference) - set(names))
    if unknown:
        raise ValueError(
            f"reference names sections that do not exist: {unknown}; the song's "
            f"sections are {sorted(set(names))}"
        )
    if bar_to_beat is None and beats_per_bar <= 0:
        raise ValueError(f"beats_per_bar must be > 0; got {beats_per_bar}")

    def uniform(bar: float) -> float:
        return (float(bar) - 1.0) * beats_per_bar

    ruler = bar_to_beat if bar_to_beat is not None else uniform

    ordered = sorted(sections, key=lambda s: (float(s["start_bar"]), float(s["end_bar"])))
    for prev, nxt in zip(ordered, ordered[1:]):
        if float(nxt["start_bar"]) < float(prev["end_bar"]):
            raise ValueError(
                f"sections {prev['name']!r} [{prev['start_bar']}, {prev['end_bar']}) and "
                f"{nxt['name']!r} [{nxt['start_bar']}, {nxt['end_bar']}) overlap in bars, "
                "so no single reference can be in force there — fix the sections "
                "or author the schedule with schedule_from_spans"
            )

    spans: list[tuple[float, float, Sequence[NodeRef]]] = []
    for section in ordered:
        nodes = reference.get(str(section["name"]), default)
        if nodes is None:
            continue
        spans.append(
            (ruler(float(section["start_bar"])), ruler(float(section["end_bar"])), nodes)
        )
    if not spans:
        raise ValueError(
            "no section received a reference: name at least one section in "
            "`reference`, or pass `default` for the rest"
        )
    return schedule_from_spans(spans)


def schedule_digest(schedule: ReferenceSchedule) -> str:
    """A stable content hash of the schedule, for a field's fingerprint.

    Spans are already ordered by the type, and node tuples are JSON-able, so
    two schedules that say the same thing digest the same.
    """
    blob = json.dumps(
        [[s.start_beat, s.end_beat, [list(n) for n in s.nodes]] for s in schedule.spans],
        separators=(",", ":"),
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def node_ref_from_addr(
    addr: Mapping[str, Any],
    *,
    conn: sqlite3.Connection,
    song_id: str,
    complement: bool = False,
) -> NodeRef:
    """The engine-side ``NodeRef`` for a wire ``NodeAddr``.

    The wire address names a parent by its DB-native 1-based index
    (``track_index`` / return ``position``) — the shape ``queries.get_node_path``
    emits — and a ``terminal``. Only a node with a captured surface can be a
    reference, so the terminal must be ``track`` / ``return`` / ``master``; a
    device or chain address is refused with the host node named as the fix.
    ``complement`` turns a track into ``('minus', track_id)``: the mix minus
    that track, so a sample is never carved against its own energy.
    """
    parent = addr.get("parent")
    if not isinstance(parent, Mapping) or "kind" not in parent:
        raise ValueError(
            "NodeAddr must carry parent {kind[, index]}; got "
            f"{dict(addr)!r}"
        )
    kind = parent["kind"]
    terminal = addr.get("terminal")
    if terminal is None:
        raise ValueError(
            "NodeAddr has no terminal, which on the wire means a device — a device "
            "has no captured surface, so it cannot be a spectral reference. Address "
            f"the host node instead: {{'parent': {dict(parent)!r}, 'terminal': {kind!r}}}"
        )
    if terminal not in _SURFACE_TERMINALS:
        raise ValueError(
            f"NodeAddr terminal {terminal!r} names something inside a node; a "
            "spectral reference is a node with a captured surface (terminal "
            f"'track', 'return' or 'master'). Address the host node: "
            f"{{'parent': {dict(parent)!r}, 'terminal': {kind!r}}}"
        )
    if terminal != kind:
        raise ValueError(
            f"NodeAddr terminal {terminal!r} does not match parent kind {kind!r}"
        )

    if kind == "master":
        if complement:
            raise ValueError(
                "complement=True means the mix minus one track; the master is the "
                "whole mix — give the track's address instead"
            )
        return validate_node_ref(("master",))

    index = parent.get("index")
    if not isinstance(index, int) or isinstance(index, bool) or index < 1:
        raise ValueError(
            f"NodeAddr parent.index must be a positive int (1-based {kind}); got {index!r}"
        )

    # Reached lazily: the module stays importable without the DB, and this is
    # the one place a wire index has to become a DB id.
    from hallucinote.db import queries as Q

    if kind == "track":
        rows = Q.get_tracks_for_song(conn, song_id)
        by_index = {int(r["track_index"]): r for r in rows}
        row = by_index.get(index)
        if row is None:
            raise ValueError(
                f"no track at track_index {index} in song {song_id!r}; the song's "
                f"track indices are {sorted(by_index)}"
            )
        if complement:
            return validate_node_ref(("minus", str(row["id"])))
        return validate_node_ref(("track", str(row["id"])))

    if complement:
        raise ValueError(
            "complement=True means the mix minus one track; a return is a bus — "
            "give the track's address instead"
        )
    returns = Q.get_returns_for_song(conn, song_id)
    by_position = {int(r["position"]): r for r in returns}
    ret = by_position.get(index)
    if ret is None:
        raise ValueError(
            f"no return at position {index} in song {song_id!r}; the song's return "
            f"positions are {sorted(by_position)}"
        )
    return validate_node_ref(("return", str(ret["id"])))


__all__ = [
    "DEFAULT_BEATS_PER_BAR",
    "SectionLike",
    "constant_schedule",
    "node_ref_from_addr",
    "schedule_digest",
    "schedule_from_sections",
    "schedule_from_spans",
]
