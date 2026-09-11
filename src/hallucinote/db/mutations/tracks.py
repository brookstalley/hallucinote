"""Tracks: create, re-index, mixer state, and the delete helpers."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from typing import Any

from ._core import (
    E,
    MutatorResult,
    _atomic,
    _emit,
    _record_touch_if_session,
    _resolve_actor_and_request,
    _touch_song,
    _touches,
    _uuid,
)
from .links import ABLETON_LINK_KINDS, unlink_db_from_ableton


TRACK_KINDS = frozenset({"midi", "audio", "master", "group"})


@_atomic
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


@_atomic
def reindex_tracks(
    conn: sqlite3.Connection,
    *,
    song_id: str,
    moves: dict[str, int],
    actor: str = "system",
    request_id: str | None = None,
    reason: str | None = None,
) -> dict[str, int]:
    """Move existing track rows to new ``track_index`` positions, atomically.

    ``moves`` maps track id -> the index that row should end up at. Rows
    already sitting where they are asked to sit are skipped; the return value
    is the subset that actually moved, id -> new index.

    This is what demotes ``track_index`` from an identity to an attribute. A
    track's index is a POSITION, and the system renumbers positions (capture's
    dense rank around an excluded default scaffold does exactly that). Without
    a way to MOVE a row, the only way to make the DB agree with a renumbered
    snapshot is to upsert the incoming name onto whatever row happens to hold
    the incoming index — which renames a real row and strands the one it came
    from. Replay reconciles by name and calls this to carry each matched row to
    its new position.

    **The intermediate state is never observable as a conflict.** Moving a row
    into an index another row still holds violates ``UNIQUE(song_id,
    track_index)``, and every non-trivial renumber contains such a step (moving
    ``Drums`` from 5 to 1 while something still sits at 1). So the move runs in
    two passes inside one transaction: every moving row is first parked at a
    unique NEGATIVE index — a range no real track can occupy (Live's tracks are
    1-based and 0 is the master sentinel) — and only then dropped onto its
    final index. No caller has to order its moves, and no build fails on a
    constraint violation that is an artefact of the reconciliation rather than
    of the data.

    Refuses, before writing anything, a ``moves`` map that is not satisfiable:
    two rows sent to the same index, or a target index held by a row that is
    NOT itself moving. Both mean the caller's reconciliation is wrong, and
    silently letting the second one through would resurrect the very bug this
    exists to fix.

    Row UUIDs are untouched, so ``ableton_links`` and every child row (device
    chains, devices, parameters, sends, clips, notes, envelopes) stay pointed
    at valid targets.
    """
    rows = {
        r["id"]: r for r in conn.execute(
            """SELECT id, track_index, name, instrument_uri, kind
               FROM tracks WHERE song_id = ?""",
            (song_id,),
        )
    }
    unknown = sorted(set(moves) - set(rows))
    if unknown:
        raise ValueError(
            f"reindex_tracks: {unknown} are not track rows of song {song_id!r}"
        )
    actual = {
        tid: int(idx) for tid, idx in moves.items()
        if rows[tid]["track_index"] != int(idx)
    }
    if not actual:
        return {}

    targets: dict[int, str] = {}
    for tid, idx in actual.items():
        clash = targets.get(idx)
        if clash is not None:
            raise ValueError(
                f"reindex_tracks: {tid!r} and {clash!r} both move to index {idx}"
            )
        targets[idx] = tid
    for tid, row in rows.items():
        if tid in actual:
            continue
        holder = targets.get(row["track_index"])
        if holder is not None:
            raise ValueError(
                f"reindex_tracks: {holder!r} moves to index "
                f"{row['track_index']}, which {row['name']!r} holds and is not "
                "moving out of"
            )

    actor, request_id = _resolve_actor_and_request(actor, request_id)
    # Pass 1: park every mover out of the reachable index space.
    for parking, tid in enumerate(actual, start=1):
        conn.execute(
            "UPDATE tracks SET track_index = ? WHERE id = ?", (-parking, tid),
        )
    # Pass 2: land each on its final index, now provably free.
    for tid, idx in actual.items():
        row = rows[tid]
        conn.execute(
            "UPDATE tracks SET track_index = ? WHERE id = ?", (idx, tid),
        )
        _emit(
            conn,
            E.TRACK_UPDATED,
            {"track_id": tid, "track_index": idx, "name": row["name"],
             "instrument_uri": row["instrument_uri"], "kind": row["kind"]},
            song_id=song_id,
            actor=actor,
            request_id=request_id,
            reason=reason,
        )
        _record_touch_if_session("track", tid)
    _touch_song(conn, song_id)
    return actual


_MIXER_FIELDS = {"volume", "pan", "mute", "solo", "arm", "color"}


@_touches("track", "track_id")
@_atomic
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
    conn: sqlite3.Connection, *, track_id: str, song_id: str,
    changes: dict[str, Any], merged: dict[str, Any],
) -> None:
    """Validate the MERGED routing state, but only the parts the caller touched.

    Enum + cross-field checks fire only for fields/directions present in
    `changes`, so an unrelated update on a track whose target was deleted out
    from under it (FK ON DELETE SET NULL leaves kind='track', target_id=NULL —
    a legal dangling state) is never spuriously blocked.

    A track-target is additionally constrained to a real routing target: not the
    source track itself (a track never routes to itself) and not a master row
    (route TO the master via kind='master', never as a kind='track' target). Both
    mirror the source-side master reject — a reference the pull resolver refuses
    to PRODUCE must not be authorable either, or push fails confusingly later.
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
            if target == track_id:
                raise ValueError(
                    f"{target_field} {target!r} is the track itself; a track "
                    "cannot route to itself"
                )
            trow = conn.execute(
                "SELECT song_id, kind FROM tracks WHERE id = ?", (target,)
            ).fetchone()
            if trow is None:
                raise ValueError(
                    f"{target_field} {target!r} does not reference an existing track"
                )
            if trow["song_id"] != song_id:
                raise ValueError(
                    f"{target_field} {target!r} belongs to a different song"
                )
            if trow["kind"] == "master":
                raise ValueError(
                    f"{target_field} {target!r} is a master track; route TO the "
                    f"master via {kind_field}='master', not as a track target"
                )


@_touches("track", "track_id")
@_atomic
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
    _validate_track_routing(
        conn, track_id=track_id, song_id=row["song_id"],
        changes=changes, merged=merged,
    )
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


# ---------------------------------------------------------------------------
# Operator-invoked prune of an orphaned track row
# ---------------------------------------------------------------------------
# A replay whose snapshot no longer defines a track REPORTS the surviving row
# and never deletes it: the row can be carrying pulled human work — its mixer
# state, its sends, its device chain with tuned parameters, its clips and notes
# — none of which a build without `--reset` re-authors. But an orphan is not
# inert either (the next push materializes it as a junk track in Live), so the
# report has to be actionable. This is the remedy: an operator names the row,
# sees everything that goes with it, and confirms.
#
# The enumeration is derived from the SCHEMA, not from a hand-written list,
# because "refuses on anything it cannot fully enumerate" is only a real
# promise if it survives someone adding a table next year. A hand-written list
# silently under-reports the day it goes stale.

# ableton_links.db_id carries no foreign key (the projection is deliberately
# not FK-bound), so a cascade cannot reach it — deleting a track would leave
# links pointing at rows that no longer exist. These are the link kinds whose
# rows can hang off a track; the prune drops them explicitly.
_LINK_KIND_BY_TABLE: dict[str, str] = {
    "tracks": "track",
    "clips": "clip",
    "arrangement_clips": "arrangement_clip",
    "notes": "note",
    "devices": "device",
    "envelopes": "envelope",
}


# The one link kind that can never name a row inside a track's cascade closure:
# real returns live in their own table and hang off the song, not off a track.
# Every OTHER kind must appear in `_LINK_KIND_BY_TABLE`, or the prune has no
# way to find that kind's links and refuses — so adding a link kind without
# mapping its table fails loudly here instead of leaving dangling links behind.
_LINK_KINDS_NOT_UNDER_A_TRACK: frozenset[str] = frozenset({"return"})


@dataclass
class TrackDeletionPlan:
    """Everything deleting one track row would take with it.

    ``deletes`` maps table -> row count that CASCADEs away with the track.
    ``detaches`` maps table -> row count that survives with its reference to
    this track set to NULL (a routing target, a device's sidechain source, a
    markdown ref). ``links`` maps ``ableton_links.db_kind`` -> count of
    projection rows the prune removes by hand, because that table is not
    FK-bound and no cascade reaches it.

    A non-empty ``blockers`` means the plan is INCOMPLETE and the prune must
    refuse: something references a track (or one of its cascade children) in a
    way this walk cannot follow. Deleting what you could not describe first is
    the failure the whole orphan-reporting design exists to avoid.
    """

    track_id: str
    track_index: int
    name: str
    deletes: dict[str, int] = field(default_factory=dict)
    detaches: dict[str, int] = field(default_factory=dict)
    links: dict[str, int] = field(default_factory=dict)
    blockers: list[str] = field(default_factory=list)
    link_rows: list[tuple[str, str, str]] = field(
        default_factory=list, repr=False,
    )

    @property
    def can_proceed(self) -> bool:
        return not self.blockers

    def summary(self) -> str:
        """One line naming what goes, in descending count order. Empty-safe:
        a bare track row reads 'nothing else'."""
        parts = [
            f"{count} {table}" for table, count in
            sorted(self.deletes.items(), key=lambda kv: (-kv[1], kv[0]))
            if count
        ]
        parts += [
            f"{count} {kind} link(s)" for kind, count in
            sorted(self.links.items()) if count
        ]
        parts += [
            f"{count} {table} detached" for table, count in
            sorted(self.detaches.items()) if count
        ]
        return ", ".join(parts) if parts else "nothing else"


def _fk_graph(conn: sqlite3.Connection) -> dict[str, list[dict[str, Any]]]:
    """parent table -> the foreign keys pointing AT it, read off the live
    schema. Each entry is ``{child, from, to, on_delete}``."""
    graph: dict[str, list[dict[str, Any]]] = {}
    tables = [
        r["name"] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' "
            "AND name NOT LIKE 'sqlite_%'"
        )
    ]
    for table in tables:
        for fk in conn.execute(f'PRAGMA foreign_key_list("{table}")'):
            graph.setdefault(fk["table"], []).append({
                "child": table,
                "from": fk["from"],
                "to": fk["to"] or "id",
                "on_delete": (fk["on_delete"] or "NO ACTION").upper(),
            })
    return graph


def _has_id_column(conn: sqlite3.Connection, table: str) -> bool:
    return any(
        r["name"] == "id" for r in conn.execute(f'PRAGMA table_info("{table}")')
    )


def describe_track_deletion(
    conn: sqlite3.Connection, *, track_id: str,
) -> TrackDeletionPlan | None:
    """Walk the schema outward from one track row and report what deleting it
    would take with it. Returns None when the row does not exist.

    Read-only. The walk follows every foreign key that points at a table
    already in the closure: ``ON DELETE CASCADE`` extends the closure,
    ``ON DELETE SET NULL`` is recorded as a detach and stops there, and
    anything else (or an edge this walk cannot follow) becomes a blocker
    rather than a silent omission.
    """
    row = conn.execute(
        "SELECT id, song_id, track_index, name FROM tracks WHERE id = ?",
        (track_id,),
    ).fetchone()
    if row is None:
        return None
    plan = TrackDeletionPlan(
        track_id=track_id, track_index=row["track_index"], name=row["name"],
    )

    graph = _fk_graph(conn)
    ids: dict[str, set[str]] = {"tracks": {track_id}}
    frontier: list[tuple[str, str, set[str]]] = [("tracks", "id", {track_id})]
    while frontier:
        parent, col, values = frontier.pop()
        for fk in graph.get(parent, []):
            child, from_col = fk["child"], fk["from"]
            if fk["to"] != col:
                plan.blockers.append(
                    f"{child}.{from_col} references {parent}.{fk['to']}, a "
                    f"column this walk does not hold values for"
                )
                continue
            marks = ", ".join("?" * len(values))
            if fk["on_delete"] == "SET NULL":
                found = conn.execute(
                    f'SELECT COUNT(*) AS n FROM "{child}" '
                    f'WHERE "{from_col}" IN ({marks})',
                    tuple(values),
                ).fetchone()["n"]
                if found:
                    plan.detaches[child] = plan.detaches.get(child, 0) + found
                continue
            if fk["on_delete"] != "CASCADE":
                plan.blockers.append(
                    f"{child}.{from_col} is ON DELETE {fk['on_delete']} — "
                    "deleting the track would fail or strand it"
                )
                continue
            if not _has_id_column(conn, child):
                if graph.get(child):
                    plan.blockers.append(
                        f"{child} cascades from {parent} but has no `id` "
                        "column, so its own children cannot be enumerated"
                    )
                found = conn.execute(
                    f'SELECT COUNT(*) AS n FROM "{child}" '
                    f'WHERE "{from_col}" IN ({marks})',
                    tuple(values),
                ).fetchone()["n"]
                if found:
                    plan.deletes[child] = plan.deletes.get(child, 0) + found
                continue
            found_ids = {
                r["id"] for r in conn.execute(
                    f'SELECT id FROM "{child}" WHERE "{from_col}" IN ({marks})',
                    tuple(values),
                )
            }
            fresh = found_ids - ids.get(child, set())
            if not fresh:
                continue
            ids.setdefault(child, set()).update(fresh)
            plan.deletes[child] = plan.deletes.get(child, 0) + len(fresh)
            frontier.append((child, "id", fresh))

    # The projection rows no cascade reaches.
    unmapped = sorted(
        ABLETON_LINK_KINDS
        - set(_LINK_KIND_BY_TABLE.values())
        - _LINK_KINDS_NOT_UNDER_A_TRACK
    )
    for kind in unmapped:
        plan.blockers.append(
            f"ableton_links kind {kind!r} has no table mapped, so links of "
            "that kind onto this track's rows cannot be found"
        )
    for table, kind in _LINK_KIND_BY_TABLE.items():
        row_ids = ids.get(table)
        if not row_ids:
            continue
        marks = ", ".join("?" * len(row_ids))
        for link in conn.execute(
            "SELECT session_id, db_id FROM ableton_links "
            f"WHERE db_kind = ? AND db_id IN ({marks})",
            (kind, *row_ids),
        ):
            plan.link_rows.append((link["session_id"], kind, link["db_id"]))
            plan.links[kind] = plan.links.get(kind, 0) + 1
    return plan


@_atomic
def prune_track(
    conn: sqlite3.Connection,
    *,
    track_id: str,
    actor: str = "system",
    request_id: str | None = None,
    reason: str | None = None,
) -> TrackDeletionPlan:
    """Delete one track row and everything that hangs off it. Returns the plan
    that was executed, so the caller can report exactly what went.

    Refuses (``ValueError``) on a row that does not exist, and on a plan
    carrying blockers — the "cannot fully enumerate" refusal. The
    ``ableton_links`` rows for the whole cascade closure are unlinked FIRST,
    through the normal mutator, so the projection never keeps a binding to a
    row that stopped existing.

    This is the operator's remedy for the orphan a replay reports, never
    something replay calls for itself. Replay reconciles and reports; deleting
    a row that may carry pulled human work stays a decision a person makes.
    """
    plan = describe_track_deletion(conn, track_id=track_id)
    if plan is None:
        raise ValueError(f"no track row with id {track_id!r}")
    if not plan.can_proceed:
        raise ValueError(
            f"refusing to prune track {plan.name!r}: "
            + "; ".join(plan.blockers)
        )
    for session_id, db_kind, db_id in plan.link_rows:
        unlink_db_from_ableton(
            conn, session_id=session_id, db_kind=db_kind, db_id=db_id,
            actor=actor, request_id=request_id,
            reason=reason or f"prune orphaned track {plan.name!r}",
        )
    _delete_track(
        conn, track_id=track_id, actor=actor, request_id=request_id,
        reason=reason or f"prune orphaned track {plan.name!r}",
    )
    return plan


@_atomic
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
    "TrackDeletionPlan",
    "_delete_track",
    "create_track",
    "describe_track_deletion",
    "prune_track",
    "reindex_tracks",
    "set_track_mixer",
    "set_track_routing",
]
