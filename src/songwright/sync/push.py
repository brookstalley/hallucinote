"""DB -> Ableton planner.

Produces a list of `ToolCall` objects describing what the agent should run.
After the agent executes the plan, it calls `apply_push_results` to write
Ableton-side IDs back into the DB.

Why a plan rather than direct calls: MCP tools are invoked by the agent, not
by Python. Returning a plan keeps this layer pure, testable, and reorder-safe.

Sessions: every plan/apply takes a `session_id` (an `ableton_sessions` row).
Bindings live in `ableton_links`, not on core rows — so a song can be bound
to multiple Live sets at the same time without aliasing. Open one with
`mutations.create_ableton_session`.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field, asdict
from typing import Any

from songwright.db import mutations as M, queries as Q

# Live's default meter when a song has no `time_signature_map` rows.
_DEFAULT_NUMERATOR = 4
_DEFAULT_DENOMINATOR = 4


@dataclass
class ToolCall:
    """One MCP tool invocation. `key` lets results be matched back to ops.

    Names are *canonical* (post-Wave-1). Agent uses `mcp_names.resolve` to
    map onto today's surface.
    """
    tool: str
    args: dict[str, Any]
    key: str  # caller-chosen identifier; used in apply_push_results
    purpose: str = ""  # human-readable hint for the agent


@dataclass
class PushPlan:
    calls: list[ToolCall] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)  # human notes / warnings

    def add(self, call: ToolCall) -> None:
        self.calls.append(call)

    def warn(self, msg: str) -> None:
        self.notes.append(msg)

    def to_dict(self) -> dict[str, Any]:
        return {
            "calls": [asdict(c) for c in self.calls],
            "notes": self.notes,
        }


# ---------------------------------------------------------------------------
# Note conversion: DB -> MCP
# ---------------------------------------------------------------------------


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
    bar_int = int(bar_pos)
    frac = bar_pos - bar_int
    num, den = _meter_at_bar(bar_pos, ts_points)
    return bar_int, frac * _beats_per_bar(num, den)


def _notes_for_mcp(notes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """DB notes carry tags + extra fields; MCP wants the bare quartet."""
    return [
        {
            "pitch": n["pitch"],
            "start_time": n["start_beats"],
            "duration": n["duration_beats"],
            "velocity": n["velocity"],
            "mute": bool(n["mute"]),
        }
        for n in notes
    ]


# ---------------------------------------------------------------------------
# Planning
# ---------------------------------------------------------------------------


def plan_push_clip(
    conn: sqlite3.Connection,
    *,
    clip_id: str,
    session_id: str,
) -> PushPlan:
    """Plan the push of a single session clip (track + notes) to Ableton.

    Three cases:
      1. Track not yet linked in this session -> create_midi_track_with, then ...
      2. Clip not yet linked in this session  -> replace_session_clip (atomic)
      3. Clip already linked                  -> set_clip_notes (in-place)
    """
    plan = PushPlan()

    clip = Q.get_clip(conn, clip_id)
    if clip is None:
        raise ValueError(f"clip {clip_id} not found")

    track_row = Q.get_track(conn, clip["track_id"])
    if track_row is None:
        raise ValueError(f"track {clip['track_id']} not found for clip {clip_id}")
    notes = Q.get_notes_for_clip(conn, clip_id)

    track_at = Q.get_ableton_link(
        conn, session_id=session_id, db_kind="track", db_id=track_row["id"]
    )
    clip_at = Q.get_ableton_link(
        conn, session_id=session_id, db_kind="clip", db_id=clip_id
    )

    if track_at is None:
        plan.add(ToolCall(
            tool="create_midi_track_with",
            args={
                "name": track_row["name"],
                "instrument_uri": track_row["instrument_uri"],
                "index": -1,
            },
            key=f"track:{track_row['id']}",
            purpose=f"create track '{track_row['name']}' (db track_id={track_row['id']})",
        ))
        plan.warn(
            f"track {track_row['id']} has no ableton link in session {session_id} yet — "
            f"after create_midi_track_with returns, call apply_push_results to record it."
        )
        # Subsequent calls in this plan can't run until we know the new track index.
        # The agent should execute the track-creation, capture the result, call
        # apply_push_results, then re-plan to pick up the now-linked track.
        return plan

    if clip_at is None:
        plan.add(ToolCall(
            tool="replace_session_clip",
            args={
                "track_index": track_at,
                "clip_index": clip["slot"],
                "length": clip["length_beats"],
                "name": clip["name"],
                "notes": _notes_for_mcp(notes),
            },
            key=f"clip:{clip_id}",
            purpose=f"create+populate session clip slot {clip['slot']} on track {track_at}",
        ))
    else:
        plan.add(ToolCall(
            tool="set_clip_notes",
            args={
                "track_index": track_at,
                "clip_index": clip_at,
                "notes": _notes_for_mcp(notes),
            },
            key=f"clip:{clip_id}",
            purpose=f"replace notes in existing clip ({len(notes)} notes)",
        ))

    return plan


def plan_push_arrangement(
    conn: sqlite3.Connection,
    *,
    song_id: str,
    session_id: str,
) -> PushPlan:
    """Plan rebuilding the arrangement for a song.

    Strategy: clear all existing arrangement clips for the involved tracks,
    then duplicate session clips into the arrangement at their target bars.
    Single batch_arrangement_layout call.

    Pre-conditions (planner asserts and warns; doesn't fix):
      - All tracks involved have a `track` link in this session
      - All clips involved have a `clip` link in this session
    """
    plan = PushPlan()
    arr_rows = Q.get_arrangement_for_song(conn, song_id)
    if not arr_rows:
        plan.warn("no arrangement rows for this song")
        return plan

    operations: list[dict[str, Any]] = []
    track_indices_seen: set[int] = set()

    for row in arr_rows:
        track_at = Q.get_ableton_link(
            conn, session_id=session_id, db_kind="track", db_id=row["track_id"]
        )
        if track_at is None:
            plan.warn(f"arrangement {row['id']}: track not linked in this session — skipping")
            continue
        clip_at = Q.get_ableton_link(
            conn, session_id=session_id, db_kind="clip", db_id=row["clip_id"]
        )
        if clip_at is None:
            plan.warn(
                f"arrangement {row['id']}: clip {row['clip_id']} not linked in this session — skipping"
            )
            continue
        track_indices_seen.add(track_at)
        operations.append({
            "op": "duplicate",
            "track_index": track_at,
            "clip_index": clip_at,
            "destination_bar": row["start_bar"],
            "key": f"arrangement:{row['id']}",
        })

    # Clear pass: caller-controlled. Conservative default — assume agent wipes
    # arrangement clips on listed tracks before this batch runs. We could add
    # explicit delete ops here once the planner knows what's currently in the
    # arrangement (requires a get_arrangement_info pre-call).
    if operations:
        plan.add(ToolCall(
            tool="batch_arrangement_layout",
            args={"operations": operations},
            key=f"arrangement_batch:{song_id}",
            purpose=f"rebuild arrangement: {len(operations)} duplicates "
                    f"across {len(track_indices_seen)} tracks",
        ))
    plan.warn("planner does not yet emit pre-clear ops — agent must clear target tracks first")
    return plan


# ---------------------------------------------------------------------------
# Score-half planners: tempo / meter / cue points / sections
# ---------------------------------------------------------------------------


def plan_push_tempo_map(
    conn: sqlite3.Connection,
    *,
    song_id: str,
) -> PushPlan:
    """Emit canonical `write_tempo_point` calls — one per row in `tempo_map`.

    Positions are emitted as `(bar, beat)` matching the rest of the MCP surface
    (see mcp-requirements.md). The (bar, beat) pair is computed via the song's
    time_signature_map (defaulting to 4/4 if empty, with a warning).
    """
    plan = PushPlan()
    rows = Q.get_tempo_map(conn, song_id)
    if not rows:
        plan.warn("no tempo_map rows for this song; nothing to push")
        return plan
    ts_points = Q.get_time_signature_map(conn, song_id)
    if not ts_points:
        plan.warn(
            "no time_signature_map; assuming 4/4 for tempo-map bar/beat split"
        )
    for r in rows:
        bar, beat = _split_bar(r["start_bar"], ts_points)
        plan.add(ToolCall(
            tool="write_tempo_point",
            args={
                "bar": bar,
                "beat": beat,
                "bpm": r["tempo_bpm"],
                "ramp": r["ramp"],
            },
            key=f"tempo_point:{r['id']}",
            purpose=f"set tempo to {r['tempo_bpm']:g} bpm at bar {r['start_bar']:g} "
                    f"(ramp={r['ramp']})",
        ))
    if len(rows) > 1 or any(r["ramp"] == "linear" for r in rows):
        plan.warn(
            "multi-point or ramped tempo maps require full tempo-automation MCP "
            "support (see docs/mcp-requirements.md, P2)"
        )
    return plan


def plan_push_time_signature_map(
    conn: sqlite3.Connection,
    *,
    song_id: str,
) -> PushPlan:
    """Emit canonical `write_time_signature_point` calls — one per meter change.

    Live exposes no MCP tool for arrangement-level meter changes today; the
    planner produces canonical (bar, beat, numerator, denominator) calls and
    warns about the MCP gap so apply can no-op until support lands.
    """
    plan = PushPlan()
    rows = Q.get_time_signature_map(conn, song_id)
    if not rows:
        plan.warn("no time_signature_map rows for this song; nothing to push")
        return plan
    for r in rows:
        # A time-signature point's own position is in its own meter context —
        # use `rows` (the map itself) as the time-sig reference.
        bar, beat = _split_bar(r["start_bar"], rows)
        plan.add(ToolCall(
            tool="write_time_signature_point",
            args={
                "bar": bar,
                "beat": beat,
                "numerator": r["numerator"],
                "denominator": r["denominator"],
            },
            key=f"time_signature_point:{r['id']}",
            purpose=f"set meter to {r['numerator']}/{r['denominator']} "
                    f"at bar {r['start_bar']:g}",
        ))
    plan.warn(
        "time-signature change writes are an MCP gap "
        "(see docs/mcp-requirements.md, P2)"
    )
    return plan


def plan_push_cue_points(
    conn: sqlite3.Connection,
    *,
    song_id: str,
) -> PushPlan:
    """Emit `create_cue_point` calls for every row in `cue_points`.

    Live's MCP `create_cue_point(bar, beat, name)` is callable today, with
    `bar` 1-based int and `beat` 0-based float within that bar. The planner
    splits each row's fractional `position_bar` accordingly using the song's
    time_signature_map.
    """
    plan = PushPlan()
    rows = Q.get_cue_points(conn, song_id)
    if not rows:
        plan.warn("no cue_points for this song; nothing to push")
        return plan
    ts_points = Q.get_time_signature_map(conn, song_id)
    if not ts_points:
        plan.warn(
            "no time_signature_map; assuming 4/4 for cue-point bar/beat split"
        )
    for r in rows:
        bar, beat = _split_bar(r["position_bar"], ts_points)
        plan.add(ToolCall(
            tool="create_cue_point",
            args={"bar": bar, "beat": beat, "name": r["name"] or ""},
            key=f"cue_point:{r['id']}",
            purpose=f"create cue point '{r['name'] or ''}' at bar {r['position_bar']:g}",
        ))
    return plan


def plan_push_sections(
    conn: sqlite3.Connection,
    *,
    song_id: str,
) -> PushPlan:
    """Sections are DB-only metadata today — Live has no section-marker concept
    distinct from cue points. The planner emits no calls; it surfaces the
    section count as a warn so callers can decide whether to mirror sections
    as cue points themselves."""
    plan = PushPlan()
    rows = Q.get_sections_for_song(conn, song_id)
    if rows:
        plan.warn(
            f"{len(rows)} section(s) are DB-only; Live exposes no section-marker "
            "tool. Consider creating matching cue_points for visibility."
        )
    return plan


# ---------------------------------------------------------------------------
# Mix-half planner: track mixer + returns + sends
# ---------------------------------------------------------------------------


# Mixer fields that have a direct, callable MCP tool today. mute/solo/arm/color
# require emulation (see mcp_names.ALIASES_TODAY).
_DIRECT_MIXER_TOOLS = {
    "volume": ("set_track_volume", "volume"),
    "pan":    ("set_track_panning", "panning"),
}


def plan_push_mix(
    conn: sqlite3.Connection,
    *,
    song_id: str,
    session_id: str,
) -> PushPlan:
    """Plan the push of mix state — track volume/pan/sends + return tracks + master.

    Pre-conditions (planner warns; doesn't fix):
      - Tracks/returns that aren't yet linked in this session are flagged as a
        create step. Track creation lives in `plan_push_clip`; for returns,
        this planner emits the (gap-flagged) `create_return_track` call.
      - mute/solo/arm/color/master writes are MCP gaps today — calls are
        emitted under canonical names so the alias table tracks the gap.
    """
    plan = PushPlan()
    tracks = Q.get_tracks_for_song(conn, song_id)
    returns = Q.get_returns_for_song(conn, song_id)
    sends = Q.get_sends_for_song(conn, song_id)

    if not tracks and not returns and not sends:
        plan.warn("no mix state to push for this song")
        return plan

    # ---- Tracks: volume / pan via direct MCP tools, mute/solo/arm/color via gap-flagged emulation
    for t in tracks:
        if t["kind"] == "master":
            # Master strip: no track_index. Volume/pan writes are MCP gaps.
            if t["volume"] is not None:
                plan.add(ToolCall(
                    tool="set_master_volume",
                    args={"value": t["volume"]},
                    key=f"master_volume:{t['id']}",
                    purpose=f"set master volume to {t['volume']:g}",
                ))
            if t["pan"] is not None:
                plan.add(ToolCall(
                    tool="set_master_panning",
                    args={"value": t["pan"]},
                    key=f"master_pan:{t['id']}",
                    purpose=f"set master pan to {t['pan']:g}",
                ))
            continue

        if t["kind"] == "return":
            # 'return' kind on a `tracks` row is reserved; real returns live in
            # `returns`. Skip silently — replay won't put rows here today.
            continue

        track_at = Q.get_ableton_link(
            conn, session_id=session_id, db_kind="track", db_id=t["id"]
        )
        if track_at is None:
            plan.warn(
                f"track {t['name']!r} ({t['id']}) not linked in session — "
                "create it via plan_push_clip first, then re-run plan_push_mix"
            )
            continue

        for mixer_field, (tool, arg) in _DIRECT_MIXER_TOOLS.items():
            value = t[mixer_field]
            if value is None:
                continue
            plan.add(ToolCall(
                tool=tool,
                args={"track_index": track_at, arg: value},
                key=f"track_{mixer_field}:{t['id']}",
                purpose=f"set {t['name']} {mixer_field} to {value:g}",
            ))

        # mute/solo/arm/color are gap-flagged.
        for mixer_field, gap_tool in (
            ("mute", "set_track_mute"),
            ("solo", "set_track_solo"),
            ("arm",  "set_track_arm"),
            ("color", "set_track_color"),
        ):
            value = t[mixer_field]
            if value is None:
                continue
            plan.add(ToolCall(
                tool=gap_tool,
                args={"track_index": track_at, "value": value},
                key=f"track_{mixer_field}:{t['id']}",
                purpose=f"set {t['name']} {mixer_field} to {value} (MCP gap)",
            ))

    # ---- Returns: create unlinked, then push volume/pan (currently no MCP for return mixer state)
    for r in returns:
        return_at = Q.get_ableton_link(
            conn, session_id=session_id, db_kind="return", db_id=r["id"]
        )
        if return_at is None:
            plan.add(ToolCall(
                tool="create_return_track",
                args={"name": r["name"]},
                key=f"return:{r['id']}",
                purpose=f"create return track '{r['name']}' (MCP gap — emulation needed)",
            ))
            plan.warn(
                f"return {r['name']!r} not linked yet; apply_push_results will record "
                "the new return_index when create_return_track returns"
            )

    if returns:
        plan.warn(
            "return-track volume/pan writes are not in scope — set_track_volume "
            "operates on session tracks only. Track this as an MCP gap if return "
            "mixer state needs programmatic push."
        )

    # ---- Sends: cross product of (linked track) x (linked return)
    for s in sends:
        track_at = Q.get_ableton_link(
            conn, session_id=session_id, db_kind="track", db_id=s["from_track_id"]
        )
        return_at = Q.get_ableton_link(
            conn, session_id=session_id, db_kind="return", db_id=s["to_return_id"]
        )
        if track_at is None or return_at is None:
            plan.warn(
                f"send {s['from_track_name']} -> {s['return_name']}: missing link "
                f"(track={track_at}, return={return_at}); skipping"
            )
            continue
        plan.add(ToolCall(
            tool="set_track_send",
            args={
                "track_index": track_at,
                "return_index": return_at,
                "value": s["level"],
            },
            key=f"send:{s['from_track_id']}:{s['to_return_id']}",
            purpose=f"send {s['from_track_name']} -> {s['return_name']} = {s['level']:g}",
        ))

    return plan


# ---------------------------------------------------------------------------
# Result application
# ---------------------------------------------------------------------------


# Key kinds that record an `ableton_links` binding when the agent reports
# success. Each entry maps the `ToolCall.key` prefix to (db_kind, result field
# the agent's result dict must carry).
_LINK_KINDS: dict[str, tuple[str, str]] = {
    "track":       ("track",       "track_index"),
    "clip":        ("clip",        "clip_index"),
    "arrangement": ("arrangement", "arrangement_clip_index"),
    "return":      ("return",      "return_index"),
}

# Key kinds that have no DB binding to record but are valid acks — the planner
# emits them and the agent reports success/failure, but songwright has nothing
# to write. Membership here is a contract: every key kind the planner emits
# MUST appear in either `_LINK_KINDS` or `_ACK_ONLY_KINDS`, or
# `apply_push_results` raises. This makes the dispatch surface auditable: when
# a planner grows a new key kind, the developer is forced to declare its
# resolution here, which surfaces silent-drop bugs at write time.
_ACK_ONLY_KINDS: frozenset[str] = frozenset({
    # Chunk 2 (score)
    "arrangement_batch",     # batch_arrangement_layout outer envelope; inner ops carry `arrangement:` keys
    "tempo_point",           # write_tempo_point
    "time_signature_point",  # write_time_signature_point
    "cue_point",             # create_cue_point
    # Chunk 3 (mix)
    "track_volume",          # set_track_volume
    "track_pan",             # set_track_panning
    "track_mute",            # set_track_mute (MCP gap)
    "track_solo",            # set_track_solo (MCP gap)
    "track_arm",             # set_track_arm (MCP gap)
    "track_color",           # set_track_color (MCP gap)
    "master_volume",         # set_master_volume (MCP gap)
    "master_pan",            # set_master_panning (MCP gap)
    "send",                  # set_track_send
})


def apply_push_results(
    conn: sqlite3.Connection,
    results: list[dict[str, Any]],
    *,
    session_id: str,
    actor: str = "sync",
    request_id: str | None = None,
    reason: str | None = None,
) -> None:
    """After the agent runs the plan, feed structured results back here so the
    DB knows what's now in Ableton. Bindings are recorded in `ableton_links`
    for `session_id`, not on core rows.

    Each result dict shape:
        {
          "key": "<the ToolCall.key from the plan>",
          "ok": bool,
          "tool": "<canonical tool name>",
          "result": { ... tool-specific shape ... },
          "error": "...optional..."
        }

    Dispatch is table-driven: see `_LINK_KINDS` (writes a link binding) and
    `_ACK_ONLY_KINDS` (no DB write). An unknown kind raises `ValueError` so a
    new planner-emitted key kind can't silently no-op past this layer.

    Failed results (`ok=False`) are skipped — the agent layer is the source
    of truth for tool-side errors; songwright records nothing for them.
    """
    with conn:
        for r in results:
            if not r.get("ok"):
                continue
            key = r.get("key", "")
            kind, _, db_id = key.partition(":")
            if not kind:
                raise ValueError(f"push result missing 'key': {r!r}")

            if kind in _ACK_ONLY_KINDS:
                continue

            if kind in _LINK_KINDS:
                if not db_id:
                    raise ValueError(
                        f"push result key {key!r} missing db_id after {kind!r}:"
                    )
                db_kind, result_field = _LINK_KINDS[kind]
                res = r.get("result") or {}
                if result_field not in res:
                    # Tool ran but didn't return the binding field (e.g.
                    # set_clip_notes for `clip:` keys — no new index to record).
                    # Skip; nothing to link.
                    continue
                M.link_db_to_ableton(
                    conn,
                    session_id=session_id,
                    db_kind=db_kind,
                    db_id=db_id,
                    ableton_index=res[result_field],
                    actor=actor,
                    request_id=request_id,
                    reason=reason,
                )
                continue

            raise ValueError(
                f"unknown push result key kind {kind!r} (full key={key!r}). "
                f"Declare it in _LINK_KINDS or _ACK_ONLY_KINDS in sync/push.py."
            )
