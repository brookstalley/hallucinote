"""Neutral shared bar/beat + envelope geometry for the sync layer.

This is the leaf module both `sync.push` and `sync.pull` import from — it has
NO imports from either package. It exists so:

  - the bar/beat conversion math (forward bar→beats and inverse beats→bar) has
    one home instead of being split awkwardly across the two package cores, and
  - the pull (inbound) path no longer depends on the push (outbound) path for
    envelope placement geometry (`_resolve_envelope_session_clip`,
    `_envelope_beat_range`, `_CoveringPlacement`). Those covering-placement
    helpers are direction-neutral: push uses them to write, pull uses them to
    read, and neither owns them.

Keep this module free of imports from `push` / `pull` / their submodules so the
sync package's import graph stays acyclic with geometry as the leaf.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from typing import Any

from hallucinote.db import queries as Q

# Live's default meter when a song has no `time_signature_map` rows.
_DEFAULT_NUMERATOR = 4
_DEFAULT_DENOMINATOR = 4


def _beats_per_bar(numerator: int, denominator: int) -> float:
    """Live counts a beat as a quarter note regardless of meter, so the beat
    count per bar is `numerator * (4 / denominator)` (e.g., 6/8 -> 3 beats,
    7/4 -> 7 beats, 4/4 -> 4 beats)."""
    return numerator * (4.0 / denominator)


def _meter_at_bar(
    bar: float,
    ts_points: list[sqlite3.Row],
) -> tuple[int, int]:
    """Return (numerator, denominator) effective at a 1-based bar position.

    Empty ts_points fall back to 4/4. Bars before the first map point use the
    first point's meter — matches Live's behavior for unmarked regions.
    """
    if not ts_points:
        return (_DEFAULT_NUMERATOR, _DEFAULT_DENOMINATOR)
    chosen = ts_points[0]
    for p in ts_points:
        if p["start_bar"] <= bar:
            chosen = p
        else:
            break
    return (chosen["numerator"], chosen["denominator"])


def _split_bar(
    bar_pos: float,
    ts_points: list[sqlite3.Row],
) -> tuple[int, float]:
    """Split a 1-based fractional bar position into (bar_int, beat_within_bar).

    Matches the `(bar: int 1-based, beat: float 0-based-within-bar)` shape that
    Live's MCP tools use throughout. `bar_pos=4.5` in 4/4 -> (4, 2.0).
    """
    if bar_pos < 1.0:
        raise ValueError(
            f"bar_pos must be >= 1.0 per 1-based bar convention (got {bar_pos!r})"
        )
    bar_int = int(bar_pos)
    frac = bar_pos - bar_int
    num, den = _meter_at_bar(bar_pos, ts_points)
    return bar_int, frac * _beats_per_bar(num, den)


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
    if bar_pos < 1.0:
        raise ValueError(
            f"bar_pos must be >= 1.0 per 1-based bar convention (got {bar_pos!r})"
        )
    if not ts_points:
        return (bar_pos - 1.0) * _beats_per_bar(
            _DEFAULT_NUMERATOR, _DEFAULT_DENOMINATOR,
        )

    beats = 0.0
    current_bar = 1.0
    current_bpb = _beats_per_bar(
        ts_points[0]["numerator"], ts_points[0]["denominator"],
    )

    for p in ts_points:
        change_at = float(p["start_bar"])
        if change_at <= current_bar:
            # Already at or past this point's bar (the canonical case for
            # ts_points[0] when its start_bar == 1.0). Adopt this point's
            # meter; nothing to accumulate.
            current_bpb = _beats_per_bar(p["numerator"], p["denominator"])
            continue
        if bar_pos < change_at:
            return beats + (bar_pos - current_bar) * current_bpb
        beats += (change_at - current_bar) * current_bpb
        current_bar = change_at
        current_bpb = _beats_per_bar(p["numerator"], p["denominator"])

    return beats + (bar_pos - current_bar) * current_bpb


def _join_bar_beat(
    bar: int,
    beat: float,
    ts_points: list[sqlite3.Row],
) -> float:
    """Inverse of :func:`_split_bar`: combine a 1-based bar int + 0-based beat
    float into a fractional `position_bar` using the song's time-signature
    map. Empty `ts_points` defaults to 4/4."""
    num, den = (4, 4)
    if ts_points:
        # Use the latest signature at-or-before this bar.
        chosen = ts_points[0]
        for p in ts_points:
            if p["start_bar"] <= bar:
                chosen = p
            else:
                break
        num, den = (chosen["numerator"], chosen["denominator"])
    return float(bar) + (float(beat) / _beats_per_bar(num, den))


def _beats_to_position_bar(
    beats: float, ts_points: list[sqlite3.Row]
) -> float:
    """Walk the time-signature map to convert a beats-from-song-start
    position into a fractional bar position.

    Wave M-5: the wire format for cue positions is now `position_beats`
    (meter-agnostic, per principle 2). The DB stores `position_bar`. This
    helper bridges. For songs with no ts_points the assumption is 4/4
    throughout — same convention as the rest of the planner's bar math.
    """
    if not ts_points:
        # 4/4 fallback: 4 beats per bar, 1-based.
        return 1.0 + (float(beats) / 4.0)
    # Sort ts points by start_bar to walk forward.
    points = sorted(ts_points, key=lambda r: float(r["start_bar"]))
    # The first ts point should be at bar 1; if not, prepend a synthetic 4/4 at bar 1.
    if float(points[0]["start_bar"]) > 1.0 + 1e-9:
        first_bpb = 4.0  # 4/4 default for bars before the first explicit ts
    else:
        first_bpb = _beats_per_bar(
            int(points[0]["numerator"]), int(points[0]["denominator"])
        )

    cumulative_beats = 0.0
    current_bar = 1.0
    current_bpb = first_bpb

    for i, point in enumerate(points):
        point_bar = float(point["start_bar"])
        # Beats consumed up to this ts boundary (in the *previous* meter)
        bars_in_section = point_bar - current_bar
        beats_in_section = bars_in_section * current_bpb
        if cumulative_beats + beats_in_section > float(beats) - 1e-9:
            # Target beat is in this section.
            remaining = float(beats) - cumulative_beats
            return current_bar + (remaining / current_bpb)
        # Cross into the next section.
        cumulative_beats += beats_in_section
        current_bar = point_bar
        current_bpb = _beats_per_bar(
            int(point["numerator"]), int(point["denominator"])
        )

    # Beyond the last ts point — extrapolate in the current meter.
    remaining = float(beats) - cumulative_beats
    return current_bar + (remaining / current_bpb)


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
