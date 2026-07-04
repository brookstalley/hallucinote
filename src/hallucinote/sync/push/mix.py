"""Mix-half planner: track mixer + returns + master + sends."""
from __future__ import annotations

import sqlite3

from hallucinote.db import queries as Q

from ._core import PushPlan, ToolCall


# Wave M-2 collapsed the per-property mixer surface to a single
# ableton_track(action='set_property', property=..., value=...) emitter. No
# more dict of tool-name lookups; all 6 properties go through the same shape.
# DB column → action property name (only 'pan' → 'panning' differs).
_MIXER_FIELDS: tuple[tuple[str, str], ...] = (
    ("volume",  "volume"),
    ("pan",     "panning"),
    ("mute",    "mute"),
    ("solo",    "solo"),
    ("arm",     "arm"),
    ("color",   "color"),
)


def plan_push_mix(
    conn: sqlite3.Connection,
    *,
    song_id: str,
    session_id: str,
) -> PushPlan:
    """Plan the push of mix state — track mixer + return tracks + master + sends.

    Under Wave M-2, every per-track mixer write emits a single unified
    ``ableton_track(action='set_property', property=..., value=...)`` call —
    the mute/solo/arm/color "MCP gap" disappears because the new surface
    exposes them all. Master mixer state goes through ``ableton_session``
    (Wave M-1). Returns go through ``ableton_return``.

    Pre-conditions (planner warns; doesn't fix):
      - Tracks not yet linked in this session are flagged. Track creation
        lives in the ``tracks`` phase (``plan_push_song_tracks``, W3-C),
        which runs before ``mix`` in the master push order.
      - Unlinked returns are emitted as ``ableton_return(action='create')``
        with the recorded name; apply records the new return_index when the
        call returns.
    """
    plan = PushPlan()
    tracks = Q.get_tracks_for_song(conn, song_id)
    returns = Q.get_returns_for_song(conn, song_id)
    sends = Q.get_sends_for_song(conn, song_id)

    if not tracks and not returns and not sends:
        plan.warn("no mix state to push for this song")
        return plan

    # ---- Tracks: every mixer field goes through ableton_track(set_property).
    for t in tracks:
        if t["kind"] == "master":
            # Master strip: no track_index. Master mixer state lives at
            # ableton_session(action='set_master_property') (Wave M-1).
            if t["volume"] is not None:
                plan.add(ToolCall(
                    tool="ableton_session",
                    args={
                        "action": "set_master_property",
                        "property": "volume",
                        "value": t["volume"],
                    },
                    key=f"master_volume:{t['id']}",
                    purpose=f"set master volume to {t['volume']:g}",
                ))
            if t["pan"] is not None:
                plan.add(ToolCall(
                    tool="ableton_session",
                    args={
                        "action": "set_master_property",
                        "property": "panning",
                        "value": t["pan"],
                    },
                    key=f"master_pan:{t['id']}",
                    purpose=f"set master pan to {t['pan']:g}",
                ))
            continue

        track_at = Q.get_ableton_link(
            conn, session_id=session_id, db_kind="track", db_id=t["id"]
        )
        if track_at is None:
            plan.warn(
                f"track {t['name']!r} ({t['id']}) not linked in session — "
                "create it via the tracks phase (plan_push_song_tracks) first, "
                "then re-run plan_push_mix"
            )
            continue

        for db_field, property_name in _MIXER_FIELDS:
            value = t[db_field]
            if value is None:
                continue
            plan.add(ToolCall(
                tool="ableton_track",
                args={
                    "action": "set_property",
                    "track_index": track_at,
                    "property": property_name,
                    "value": value,
                },
                key=f"track_{db_field}:{t['id']}",
                purpose=f"set {t['name']} {property_name} to {value}",
            ))

    # ---- Returns: create unlinked, then push mixer state.
    for r in returns:
        return_at = Q.get_ableton_link(
            conn, session_id=session_id, db_kind="return", db_id=r["id"]
        )
        if return_at is None:
            plan.add(ToolCall(
                tool="ableton_return",
                args={"action": "create", "name": r["name"]},
                key=f"return:{r['id']}",
                purpose=f"create return track '{r['name']}'",
            ))
            plan.warn(
                f"return {r['name']!r} not linked yet; apply_push_results will "
                "record the new return_index when the call returns"
            )
            continue

        for db_field, property_name in _MIXER_FIELDS:
            # Returns have no 'arm' — schema enum on ableton_return excludes it.
            if property_name == "arm":
                continue
            if db_field not in r.keys():
                continue
            value = r[db_field]
            if value is None:
                continue
            plan.add(ToolCall(
                tool="ableton_return",
                args={
                    "action": "set_property",
                    "return_index": return_at,
                    "property": property_name,
                    "value": value,
                },
                key=f"return_{db_field}:{r['id']}",
                purpose=f"set return '{r['name']}' {property_name} to {value}",
            ))

    # ---- Sends: cross product of (linked track) x (linked return).
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
            tool="ableton_track",
            args={
                "action": "set_send",
                "track_index": track_at,
                "return_index": return_at,
                "value": s["level"],
            },
            key=f"send:{s['from_track_id']}:{s['to_return_id']}",
            purpose=f"send {s['from_track_name']} -> {s['return_name']} = {s['level']:g}",
        ))

    return plan
