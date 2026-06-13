"""Routing planner: per-track output/input routing + monitor state (RTE-1K9T).

The ``routing`` phase materializes the DB's track-routing columns in Live —
the keystone of the PRE-MAIN submaster pattern (route instrument tracks' output
to an audio bus → route the bus to master → set the bus Monitor='In'). It runs
after ``mix`` and after ``devices`` (RTE-2P9X): an instrument-bearing MIDI track
exposes *audio* output routing — the only kind that can target an audio
submaster bus — only once its instrument is loaded, so ``devices`` must precede
it. Routing also needs every track linked (created in the ``tracks`` phase).

Reference resolution (D6). The DB stores the routing target as a SEMANTIC
reference — ``*_routing_kind`` + an FK ``*_routing_target_id`` when
``kind='track'`` — never Live's ``display_name``. This planner resolves that
reference to the ``display_name`` the MCP routing actions expect: a non-track
kind maps to its fixed Live name ('Main' / 'Sends Only' / 'Ext. Out' / 'Ext. In'
/ 'No Input' / 'Resampling'); ``kind='track'`` resolves the FK to the target
track's own ``name`` (which IS its Live display_name — push creates the track
with that exact name, so the two always agree). Resolving at push time is the
whole point of the FK: the submaster link survives renames + re-pushes.

Dangling target (D6). ``ON DELETE SET NULL`` on the FK leaves a legal dangling
state (``kind='track'``, ``target_id=NULL``) when a routing target is deleted.
That direction is "target gone": the planner ``alert()``s (operator-actionable,
drained into the push report's benign warnings — never a silent drop) and emits
no routing call for it.

No fingerprint gating (D7). Unlike ``performed_automation`` — which gates
because every changed arc costs real wall-clock transport time — a routing set
is a cheap, idempotent LOM write, exactly like the ``mix`` / ``devices``
planners' set_property / set_parameter calls. Those siblings re-emit
unconditionally and rely on idempotent set effects; routing does the same.
"Re-push is a no-op" holds at the EFFECT level (re-setting the same route
changes nothing), not by emitting an empty plan. A pure-data planner cannot read
Live's live routing state to gate against it anyway (planners read the DB only;
the agent executes the MCP calls), and no per-track "last-pushed routing"
fingerprint is stored — adding one would be unjustified complexity no sibling
planner carries.
"""
from __future__ import annotations

import sqlite3

from hallucinote.db import queries as Q

from ..routing_names import (
    OUTPUT_KIND_DISPLAY_NAME as _OUTPUT_KIND_DISPLAY_NAME,
    INPUT_KIND_DISPLAY_NAME as _INPUT_KIND_DISPLAY_NAME,
)
from ._core import PushPlan, ToolCall


def plan_push_routing(
    conn: sqlite3.Connection,
    *,
    song_id: str,
    session_id: str,
) -> PushPlan:
    """Plan the push of per-track routing — output + input routing + monitor.

    For each linked non-master track that carries any routing column, emit up to
    three idempotent ``ableton_track`` calls:
      * ``set_output_routing`` — when ``output_routing_kind`` is set;
      * ``set_input_routing``  — when ``input_routing_kind`` is set;
      * ``set_monitoring_state`` — when ``monitoring_state`` is set.

    Pre-conditions (planner warns / alerts; doesn't fix):
      * A track not yet linked in this session is flagged and skipped — the
        ``tracks`` phase (which runs first) creates+links it, so this only
        bites a partial/out-of-order push.
      * A dangling track-route (``kind='track'``, ``target_id=NULL`` — the
        target was deleted) is alerted as "target gone" and that direction is
        skipped (D6).

    Master tracks are skipped: the master strip has no Live-side routing
    surface and no ``ableton_link`` index to address.
    """
    plan = PushPlan()
    tracks = Q.get_tracks_for_song(conn, song_id)
    if not tracks:
        plan.warn("no tracks to route for this song")
        return plan

    # Target resolution reads from the same song's tracks (the FK + cross-song
    # check in set_track_routing guarantee a track-target is in this list).
    by_id = {t["id"]: t for t in tracks}

    for t in tracks:
        if t["kind"] == "master":
            continue
        has_routing = (
            t["output_routing_kind"] is not None
            or t["input_routing_kind"] is not None
            or t["monitoring_state"] is not None
        )
        if not has_routing:
            continue

        track_at = Q.get_ableton_link(
            conn, session_id=session_id, db_kind="track", db_id=t["id"]
        )
        if track_at is None:
            # `warn()` (diagnostic notes), NOT `alert()` — deliberate and
            # consistent with the mix/devices planners' identical unlinked-track
            # skip. "not linked yet" is transient noise the execute path
            # explicitly suppresses (push_execute._drain_plan_warnings drains
            # `alerts`, not `notes`): the `tracks` phase links every track
            # before `routing` runs, and execute halts at a phase boundary on a
            # tracks-phase failure, so this branch is unreachable on the gated
            # full-push path — it only fires when a caller invokes this planner
            # directly (tests / interactive iteration), where plan.notes IS
            # visible. Contrast the dangling-target case below, which IS
            # reachable + permanently unmaterializable, so it `alert()`s.
            plan.warn(
                f"track {t['name']!r} ({t['id']}) not linked in session — "
                "create it via the tracks phase first, then re-run plan_push_routing"
            )
            continue

        _plan_routing_direction(
            plan, track=t, track_at=track_at, by_id=by_id, direction="output"
        )
        _plan_routing_direction(
            plan, track=t, track_at=track_at, by_id=by_id, direction="input"
        )

        if t["monitoring_state"] is not None:
            plan.add(ToolCall(
                tool="ableton_track",
                args={
                    "action": "set_monitoring_state",
                    "track_index": track_at,
                    "state": t["monitoring_state"],
                },
                key=f"track_monitor:{t['id']}",
                purpose=f"set {t['name']} monitor to {t['monitoring_state']}",
            ))

    return plan


def _plan_routing_direction(
    plan: PushPlan,
    *,
    track: sqlite3.Row,
    track_at: int,
    by_id: dict[str, sqlite3.Row],
    direction: str,  # 'output' | 'input'
) -> None:
    """Emit one ``set_{output,input}_routing`` call for one direction of one
    track, resolving the semantic reference (D6) to a Live ``display_name``.

    Skips silently when the direction has no kind set. ``alert()``s and skips
    when the direction is a dangling track-route (target deleted) — the route
    is unmaterializable until the target is re-authored, and the operator
    should know it wasn't pushed.
    """
    kind = track[f"{direction}_routing_kind"]
    if kind is None:
        return

    if kind == "track":
        target_id = track[f"{direction}_routing_target_id"]
        if target_id is None:
            # Dangling state (D6): ON DELETE SET NULL fired — the target track
            # was deleted. "Target gone" — alert + skip, never a silent drop.
            plan.alert(
                f"track {track['name']!r} {direction} routing targets a track "
                "that no longer exists (target deleted); routing NOT pushed for "
                "this direction — re-author the route to a live target"
            )
            return
        target = by_id.get(target_id)
        if target is None:
            # Defensive: the FK + same-song invariant make this unreachable for
            # consistent data, but a target outside this song's track set must
            # not silently no-op past the planner.
            plan.alert(
                f"track {track['name']!r} {direction} routing target "
                f"{target_id!r} is not among this song's tracks; routing NOT "
                "pushed for this direction"
            )
            return
        type_display_name = target["name"]
    else:
        mapping = (
            _OUTPUT_KIND_DISPLAY_NAME if direction == "output"
            else _INPUT_KIND_DISPLAY_NAME
        )
        type_display_name = mapping.get(kind)
        if type_display_name is None:
            # kind is one of the closed mutator-validated vocabularies (minus
            # 'track', handled above), so this is unreachable for consistent
            # data — but the input domain is open/hardware-bound (D6: no schema
            # CHECK), so degrade gracefully (alert + skip this direction, like
            # the dangling-target case) rather than crash the whole push if a
            # future kind isn't mapped here yet.
            plan.alert(
                f"track {track['name']!r} {direction} routing kind {kind!r} "
                "has no known Live display_name mapping; routing NOT pushed "
                "for this direction"
            )
            return

    action = "set_output_routing" if direction == "output" else "set_input_routing"
    args: dict[str, object] = {
        "action": action,
        "track_index": track_at,
        "type_display_name": type_display_name,
    }
    channel = track[f"{direction}_routing_channel"]
    if channel is not None:
        args["channel_display_name"] = channel

    plan.add(ToolCall(
        tool="ableton_track",
        args=args,
        key=f"track_{direction}_routing:{track['id']}",
        purpose=(
            f"route {track['name']} {direction} to {type_display_name!r}"
            + (f" (channel {channel!r})" if channel is not None else "")
        ),
    ))
