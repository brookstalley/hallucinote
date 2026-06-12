"""Tracks: create, mixer state, and the tombstone-time delete helper."""
from __future__ import annotations

import sqlite3
from typing import Any

from ._core import (
    E,
    MutatorResult,
    _emit,
    _record_touch_if_session,
    _resolve_actor_and_request,
    _touch_song,
    _uuid,
)


TRACK_KINDS = frozenset({"midi", "audio", "master", "group"})


def create_track(
    conn: sqlite3.Connection,
    *,
    song_id: str,
    track_index: int,
    name: str,
    instrument_uri: str | None = None,
    kind: str = "midi",
    actor: str = "system",
    request_id: str | None = None,
    reason: str | None = None,
) -> str:
    """Create a track. `kind` selects 'midi' (default), 'audio', 'master', or
    'group'. Real returns live in the `returns` table — the `'return'` kind
    on a `tracks` row was dropped V1 close-out 2026-05-17 (schema CHECK
    rejects). Mixer state lives on the row but is set separately via
    `set_track_mixer`."""
    if kind not in TRACK_KINDS:
        raise ValueError(f"invalid kind {kind!r}; expected one of {sorted(TRACK_KINDS)}")
    actor, request_id = _resolve_actor_and_request(actor, request_id)
    existing = conn.execute(
        """SELECT id, name, instrument_uri, kind FROM tracks
           WHERE song_id = ? AND track_index = ?""",
        (song_id, track_index),
    ).fetchone()
    if existing is not None:
        tid = existing["id"]
        if (existing["name"], existing["instrument_uri"], existing["kind"]) == (
            name, instrument_uri, kind,
        ):
            _record_touch_if_session("track", tid)
            return MutatorResult(tid, "unchanged")
        conn.execute(
            """UPDATE tracks SET name = ?, instrument_uri = ?, kind = ?
               WHERE id = ?""",
            (name, instrument_uri, kind, tid),
        )
        _emit(
            conn,
            E.TRACK_UPDATED,
            {"track_id": tid, "track_index": track_index, "name": name,
             "instrument_uri": instrument_uri, "kind": kind},
            song_id=song_id,
            actor=actor,
            request_id=request_id,
            reason=reason,
        )
        _touch_song(conn, song_id)
        _record_touch_if_session("track", tid)
        return MutatorResult(tid, "updated")
    tid = _uuid()
    conn.execute(
        """INSERT INTO tracks
               (id, song_id, track_index, name, instrument_uri, kind)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (tid, song_id, track_index, name, instrument_uri, kind),
    )
    _emit(
        conn,
        E.TRACK_CREATED,
        {
            "track_id": tid,
            "track_index": track_index,
            "name": name,
            "instrument_uri": instrument_uri,
            "kind": kind,
        },
        song_id=song_id,
        actor=actor,
        request_id=request_id,
        reason=reason,
    )
    _touch_song(conn, song_id)
    _record_touch_if_session("track", tid)
    return MutatorResult(tid, "created")


_MIXER_FIELDS = {"volume", "pan", "mute", "solo", "arm", "color"}


def set_track_mixer(
    conn: sqlite3.Connection,
    *,
    track_id: str,
    actor: str = "system",
    request_id: str | None = None,
    reason: str | None = None,
    **changes: Any,
) -> None:
    """Partial mixer update. `changes` keys must be in _MIXER_FIELDS.

    Volume is normalized 0.0–1.0 (Live convention); pan is -1.0..+1.0;
    mute/solo/arm are 0/1; color is RGB int. Schema CHECKs enforce ranges.
    """
    bad = set(changes) - _MIXER_FIELDS
    if bad:
        raise ValueError(f"unsupported fields: {sorted(bad)}")
    if not changes:
        return
    actor, request_id = _resolve_actor_and_request(actor, request_id)
    # Fetch existing values so we can skip when state already matches.
    cols = ", ".join(["song_id"] + list(changes))
    row = conn.execute(
        f"SELECT {cols} FROM tracks WHERE id = ?", (track_id,)
    ).fetchone()
    if row is None:
        return
    # W12-A: idempotent — diff per-field; skip event when no field changes.
    actual_changes = {k: v for k, v in changes.items() if row[k] != v}
    if not actual_changes:
        return
    sets = [f"{k} = ?" for k in actual_changes]
    vals = list(actual_changes.values()) + [track_id]
    conn.execute(f"UPDATE tracks SET {', '.join(sets)} WHERE id = ?", vals)
    _emit(
        conn,
        E.TRACK_MIXER_SET,
        {"track_id": track_id, "changes": actual_changes},
        song_id=row["song_id"],
        actor=actor,
        request_id=request_id,
        reason=reason,
    )
    _touch_song(conn, row["song_id"])


# RTE-1K9T routing vocabularies (D6). OUTPUT + MONITOR domains are closed and
# live-probed certain (also CHECK-constrained in schema.sql); INPUT is open and
# hardware-bound, so it is validated HERE only (extensible without a destructive
# schema migration). Keep these in sync with schema.sql's CHECK clauses for the
# two constrained columns.
OUTPUT_ROUTING_KINDS = frozenset({"master", "track", "sends_only", "ext_out"})
INPUT_ROUTING_KINDS = frozenset({"ext_in", "resampling", "no_input", "track"})
MONITORING_STATES = frozenset({"In", "Auto", "Off"})

_ROUTING_FIELDS = frozenset({
    "output_routing_kind", "output_routing_target_id", "output_routing_channel",
    "input_routing_kind", "input_routing_target_id", "input_routing_channel",
    "monitoring_state",
})


def _check_routing_enum(value: Any, allowed: frozenset[str], field: str) -> None:
    if value is not None and value not in allowed:
        raise ValueError(
            f"invalid {field} {value!r}; expected one of {sorted(allowed)} or None"
        )


def _validate_track_routing(
    conn: sqlite3.Connection, *, song_id: str, changes: dict[str, Any],
    merged: dict[str, Any],
) -> None:
    """Validate the MERGED routing state, but only the parts the caller touched.

    Enum + cross-field checks fire only for fields/directions present in
    `changes`, so an unrelated update on a track whose target was deleted out
    from under it (FK ON DELETE SET NULL leaves kind='track', target_id=NULL —
    a legal dangling state) is never spuriously blocked.
    """
    if "output_routing_kind" in changes:
        _check_routing_enum(merged["output_routing_kind"], OUTPUT_ROUTING_KINDS,
                            "output_routing_kind")
    if "input_routing_kind" in changes:
        _check_routing_enum(merged["input_routing_kind"], INPUT_ROUTING_KINDS,
                            "input_routing_kind")
    if "monitoring_state" in changes:
        _check_routing_enum(merged["monitoring_state"], MONITORING_STATES,
                            "monitoring_state")
    for kind_field, target_field in (
        ("output_routing_kind", "output_routing_target_id"),
        ("input_routing_kind", "input_routing_target_id"),
    ):
        if kind_field not in changes and target_field not in changes:
            continue
        kind_val = merged[kind_field]
        target = merged[target_field]
        if kind_val == "track" and target is None:
            raise ValueError(f"{kind_field}='track' requires {target_field}")
        if kind_val != "track" and target is not None:
            raise ValueError(
                f"{target_field} is only valid when {kind_field}='track' "
                f"(got {kind_field}={kind_val!r})"
            )
        if target is not None:
            trow = conn.execute(
                "SELECT song_id FROM tracks WHERE id = ?", (target,)
            ).fetchone()
            if trow is None:
                raise ValueError(
                    f"{target_field} {target!r} does not reference an existing track"
                )
            if trow["song_id"] != song_id:
                raise ValueError(
                    f"{target_field} {target!r} belongs to a different song"
                )


def set_track_routing(
    conn: sqlite3.Connection,
    *,
    track_id: str,
    actor: str = "system",
    request_id: str | None = None,
    reason: str | None = None,
    **changes: Any,
) -> None:
    """Partial track routing + monitor update. `changes` keys must be in
    `_ROUTING_FIELDS`.

    The routing target is a SEMANTIC reference, never Live's display_name:
    - `output_routing_kind` in {master, track, sends_only, ext_out}; when
      'track', `output_routing_target_id` FKs the destination track (the
      submaster bus) — survives renames + re-pushes. Push resolves the FK to
      Live's display_name; pull maps the display_name back to a reference.
    - `input_routing_kind` in {ext_in, resampling, no_input, track} — validated
      here, not at the schema level (input's domain is open/hardware-bound; D6).
    - `*_routing_channel` carry Live's channel display_name (Pre FX / Post Mixer
      / Track In / …).
    - `monitoring_state` in {In, Auto, Off}; a summing bus wants 'In' to pass
      routed audio through.

    None is a MEANINGFUL value (clearing a route), so — like `set_track_mixer` —
    only keys actually present in `changes` are touched; pass a field as None to
    clear it. To clear a track-route, clear BOTH its kind and target_id.
    """
    bad = set(changes) - _ROUTING_FIELDS
    if bad:
        raise ValueError(f"unsupported fields: {sorted(bad)}")
    if not changes:
        return
    actor, request_id = _resolve_actor_and_request(actor, request_id)
    select_cols = ", ".join(["song_id", "kind", *sorted(_ROUTING_FIELDS)])
    row = conn.execute(
        f"SELECT {select_cols} FROM tracks WHERE id = ?", (track_id,)
    ).fetchone()
    if row is None:
        return
    if row["kind"] == "master":
        # The master row has no addressable routing surface in the push path
        # (it carries no ableton_link track index, and plan_push_routing skips
        # it), so persisting routing here would silently vanish at push. Reject
        # at authoring time rather than accept a dead-end. To send another
        # track's output to the master, set THAT track's
        # output_routing_kind='master' (routing TO master, not ON it).
        raise ValueError(
            "routing on a master track is not supported (the master has no "
            "addressable routing surface in the push path); route other tracks "
            "TO the master via output_routing_kind='master' on those tracks"
        )
    # Merge requested changes over current state; validate the MERGED row so a
    # partial update can never leave an inconsistent reference.
    merged = {f: (changes[f] if f in changes else row[f]) for f in _ROUTING_FIELDS}
    _validate_track_routing(conn, song_id=row["song_id"], changes=changes, merged=merged)
    # Idempotent — diff per field; skip the event when no field changes.
    actual_changes = {k: v for k, v in changes.items() if row[k] != v}
    if not actual_changes:
        return
    sets = [f"{k} = ?" for k in actual_changes]
    vals = [*actual_changes.values(), track_id]
    conn.execute(f"UPDATE tracks SET {', '.join(sets)} WHERE id = ?", vals)
    _emit(
        conn,
        E.TRACK_ROUTING_SET,
        {"track_id": track_id, "changes": actual_changes},
        song_id=row["song_id"],
        actor=actor,
        request_id=request_id,
        reason=reason,
    )
    _touch_song(conn, row["song_id"])


def _delete_track(
    conn: sqlite3.Connection, *,
    track_id: str,
    actor: str = "system",
    request_id: str | None = None,
    reason: str | None = None,
) -> None:
    """Tombstone-time helper: delete a track row. The schema already cascades
    to clips/arrangement_clips/device_chains/etc, but mutations.py didn't
    historically expose a `delete_track` mutator because the only path that
    needed it was `delete_song` (which doesn't exist either). W12-A's
    BuildSession needs it for tombstoning."""
    row = conn.execute(
        "SELECT song_id FROM tracks WHERE id = ?", (track_id,)
    ).fetchone()
    if row is None:
        return
    conn.execute("DELETE FROM tracks WHERE id = ?", (track_id,))
    _emit(
        conn, E.TRACK_DELETED,
        {"track_id": track_id},
        song_id=row["song_id"],
        actor=actor,
        request_id=request_id,
        reason=reason,
    )
    _touch_song(conn, row["song_id"])


__all__ = [
    "INPUT_ROUTING_KINDS",
    "MONITORING_STATES",
    "OUTPUT_ROUTING_KINDS",
    "TRACK_KINDS",
    "_delete_track",
    "create_track",
    "set_track_mixer",
    "set_track_routing",
]
