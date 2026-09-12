"""Neutral shared bar/beat + envelope geometry for the sync layer.

This is the leaf module both `sync.push` and `sync.pull` import from — it has
NO imports from either package. It exists so:

  - the bar/beat conversions the sync layer needs are adapted from ONE ruler in
    one place — `hallucinote.meter`, which owns the arithmetic and is shared
    with the authoring side — instead of being split across the two package
    cores, and
  - the pull (inbound) path no longer depends on the push (outbound) path for
    envelope placement geometry (`_resolve_envelope_session_clip`,
    `_envelope_beat_range`, `_CoveringPlacement`). Those covering-placement
    helpers are direction-neutral: push uses them to write, pull uses them to
    read, and neither owns them.

The bar/beat functions below are thin adapters: they take `time_signature_map`
rows, hand them to `MeterMap`, and keep the row-shaped signatures their callers
already use. The rule that bars before the first map point take that point's
meter lives in `MeterMap` now, which is what makes the forward and inverse
conversions true inverses on a map with no bar-1 row (they were not, before:
the forward walk used the first point's meter and the inverse assumed 4/4).

Keep this module free of imports from `push` / `pull` / their submodules so the
sync package's import graph stays acyclic with geometry as the leaf.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from typing import Any

from hallucinote.db import queries as Q
from hallucinote.meter import MeterMap


def _meter_at_bar(
    bar: float,
    ts_points: list[sqlite3.Row],
) -> tuple[int, int]:
    """Return (numerator, denominator) effective at a 1-based bar position.

    Empty ts_points fall back to 4/4. Bars before the first map point use the
    first point's meter — matches Live's behavior for unmarked regions.
    """
    return MeterMap.from_rows(ts_points).meter_at(bar)


def _beats_per_bar_at(
    bar: float,
    ts_points: list[sqlite3.Row],
) -> float:
    """Beats in the bar at a 1-based bar position — the meter there, counted in
    quarter notes."""
    return MeterMap.from_rows(ts_points).beats_per_bar_at(bar)


def _split_bar(
    bar_pos: float,
    ts_points: list[sqlite3.Row],
) -> tuple[int, float]:
    """Split a 1-based fractional bar position into (bar_int, beat_within_bar).

    Matches the `(bar: int 1-based, beat: float 0-based-within-bar)` shape that
    Live's MCP tools use throughout. `bar_pos=4.5` in 4/4 -> (4, 2.0).
    """
    return MeterMap.from_rows(ts_points).split_bar(bar_pos)


def _position_bar_to_beats(
    bar_pos: float,
    ts_points: list[sqlite3.Row],
) -> float:
    """Convert a 1-based fractional bar position to cumulative beats from song start.

    Live's arrangement time is measured in BEATS (quarter notes) regardless of
    meter — `position_beats` on every ableton_arrangement / ableton_clip
    arrangement-side action. Inverse-ish of :func:`_split_bar`: that returns
    ``(bar_int, beat_within_bar)``; this returns the total beats from bar 1's
    downbeat to the requested fractional bar.

    Walks the time_signature_map so meter changes accumulate correctly. Bars
    before ``ts_points[0].start_bar`` use ``ts_points[0]``'s meter (matches
    :func:`_meter_at_bar`'s fallback). Empty map → 4/4 throughout.

    Examples (in 4/4):
      - ``bar_pos=1.0`` -> 0.0
      - ``bar_pos=17.0`` -> 64.0    (16 bars × 4 beats)
      - ``bar_pos=17.5`` -> 66.0    (16 bars × 4 + half-bar = 2 beats)
    """
    return MeterMap.from_rows(ts_points).beats_at(bar_pos)


def uniform_bar_math_divergences(
    bar_positions: list[float],
    ts_points: list[sqlite3.Row],
) -> list[tuple[float, float, float]]:
    """Which bar positions land somewhere else than uniform-meter math expects.

    A HISTORICAL detector. `hallucinote.arrangement` no longer accumulates bars
    against one `beats_per_bar` — it walks the same meter map push does — so no
    writer produces a diverging position any more. What remains is rows written
    BEFORE that: `bar_ruler='uniform'` rows, and rows predating the column
    entirely, whose positions may encode the old arithmetic. This tells a
    correct odd-meter song from one of those.

    The uniform baseline is the bar-1 meter, which is what a `beats_per_bar`-style
    author would have used for the whole song. Positions agree everywhere until a
    meter change, and only for positions AFTER one do they part — so the mere
    existence of a non-bar-1 row says nothing.

    Returns ``(bar_position, meter_map_beats, uniform_beats)`` for each
    diverging position, in the order given. Empty means the two agree on every
    position passed — including the common case of a single-meter song, and of a
    meter change that no placement sits after.
    """
    if not ts_points:
        return []
    meter_map = MeterMap.from_rows(ts_points)
    uniform_bpb = meter_map.points[0].beats_per_bar
    out: list[tuple[float, float, float]] = []
    for bar_pos in bar_positions:
        mapped = meter_map.beats_at(bar_pos)
        uniform = (bar_pos - 1.0) * uniform_bpb
        if abs(mapped - uniform) > 1e-9:
            out.append((bar_pos, mapped, uniform))
    return out


def _join_bar_beat(
    bar: int,
    beat: float,
    ts_points: list[sqlite3.Row],
) -> float:
    """Inverse of :func:`_split_bar`: combine a 1-based bar int + 0-based beat
    float into a fractional `position_bar` using the song's time-signature
    map. Empty `ts_points` defaults to 4/4."""
    return MeterMap.from_rows(ts_points).join_bar_beat(bar, beat)


def _beats_to_position_bar(
    beats: float, ts_points: list[sqlite3.Row]
) -> float:
    """Convert a beats-from-song-start position into a fractional bar position.

    The wire format for cue positions is `position_beats` (meter-agnostic); the
    DB stores `position_bar`. This bridges. True inverse of
    :func:`_position_bar_to_beats`, including on a map whose earliest point is
    not at bar 1 — both take that point's meter for the bars before it.
    """
    return MeterMap.from_rows(ts_points).bar_at_beats(beats)


@dataclass
class _CoveringPlacement:
    """An arrangement_clip placement that covers an envelope's beat range.

    ``clip_id`` is the source session clip; ``start_beats`` is the
    placement's arrangement-time offset, which becomes the subtractive
    offset for converting envelope time_beats → clip-local time_beats.
    ``other_placement_starts`` lists the arrangement starts of OTHER
    placements of the same source session clip — those will also receive
    the envelope as snapshot copies after ``duplicate_to_arrangement``
    fires (W4-A finding: duplicate is a snapshot copy, not a live link).

    W4-B defensive-warn fields:
      - ``other_covering_clip_ids``: other DISTINCT session clips on the
        same track whose arrangement-time range also covered the envelope.
        Non-empty means the planner had to disambiguate; the warn names
        all overlapping clips so the author can resolve the ambiguity
        DB-side.
      - ``trimmed_end_beats``: when the placement's ``end_bar`` is
        SHORTER than the source clip's natural length, this is the
        arrangement-time end of the trimmed placement. None when the
        placement isn't trimmed. Used to warn when ``env_max`` exceeds
        the trimmed extent (the envelope WOULD fit the un-trimmed clip
        but won't play past the trim point in this placement).
    """
    clip_id: str
    start_beats: float
    other_placement_starts: list[float]
    other_covering_clip_ids: list[str] = field(default_factory=list)
    trimmed_end_beats: float | None = None


def _resolve_envelope_session_clip(
    conn: sqlite3.Connection,
    *,
    song_id: str,
    target_track_id: str,
    env_min: float,
    env_max: float,
) -> _CoveringPlacement | None:
    """Find an arrangement_clip placement on ``target_track_id`` whose
    arrangement-time range covers [env_min, env_max]. Returns the source
    session clip + arrangement offset, or None if no placement covers.

    Coverage uses the SOURCE session clip's ``length_beats`` rather than
    the placement's ``end_bar``: ``duplicate_to_arrangement`` creates an
    arrangement clip of the source's natural length (W4-A finding), and
    envelopes are bound to clip-local [0, length_beats]. A placement
    whose ``end_bar`` trims the clip shorter than its source length
    cannot host envelope breakpoints past ``end_bar``, but the source
    clip's full length is what the session clip exposes for envelope
    addressing.
    """
    rows = Q.get_arrangement_placements_with_clip_length(conn, target_track_id)
    if not rows:
        return None
    ts_points = Q.get_time_signature_map(conn, song_id)
    matched = None
    matched_start = None
    matched_trimmed_end: float | None = None
    other_covering_clip_ids: list[str] = []
    for r in rows:
        start_b = _position_bar_to_beats(r["start_bar"], ts_points)
        source_end_b = start_b + float(r["length_beats"])
        if not (env_min >= start_b and env_max <= source_end_b):
            continue
        if matched is None:
            matched = r
            matched_start = start_b
            placement_end_b = _position_bar_to_beats(r["end_bar"], ts_points)
            if placement_end_b < source_end_b:
                matched_trimmed_end = placement_end_b
        elif r["clip_id"] != matched["clip_id"]:
            # A DIFFERENT distinct session clip on the same track also
            # covers the envelope's range. W4-B defensive warn — the
            # planner picks the earliest by start_bar, but ambiguity is
            # worth surfacing.
            if r["clip_id"] not in other_covering_clip_ids:
                other_covering_clip_ids.append(r["clip_id"])
    if matched is None:
        return None
    assert matched_start is not None  # bound together with `matched` in the loop
    others = [
        _position_bar_to_beats(r["start_bar"], ts_points)
        for r in rows
        if r["clip_id"] == matched["clip_id"] and r["id"] != matched["id"]
    ]
    return _CoveringPlacement(
        clip_id=matched["clip_id"],
        start_beats=matched_start,
        other_placement_starts=others,
        other_covering_clip_ids=other_covering_clip_ids,
        trimmed_end_beats=matched_trimmed_end,
    )


def _envelope_beat_range(
    breakpoints_mcp: list[dict[str, Any]],
) -> tuple[float, float]:
    """Return (min, max) ``time_beats`` across the breakpoints."""
    times = [float(bp["time_beats"]) for bp in breakpoints_mcp]
    return min(times), max(times)
