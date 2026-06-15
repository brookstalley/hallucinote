"""W12-A BuildSession — the state-converger context manager + tombstoning.

A song's build.py wraps its mutator calls in `with M.build_session(...)`:

    with M.build_session(conn, song_name='falling-walking', owner='build.py'):
        song_id = M.create_song(conn, name='falling-walking', ...)
        M.create_track(conn, song_id=song_id, track_index=1, name='Drums')
        # ... 80+ more mutator calls

On enter:
  - Opens a `kind='compose'` request (or 'build' if added later) returning
    request_id.
  - Sets the `_current_build_session` ContextVar so subsequent mutator
    calls (within this context) promote default actor='system' to 'build'
    and tag the request_id automatically.

On exit (no exception):
  - For each managed kind owned by build, queries all rows for the song,
    finds rows NOT in `touched`, and for each candidate row checks the
    latest event actor. If the latest actor ∈ {'build', 'system'}, deletes
    the row (cascades children via schema FKs). 'sync'/'llm'/'user'/
    'generator' actor rows survive.
  - Closes the request with outcome='ok'.

On exit (exception):
  - Closes the request with outcome='failed' (or 'partial'); does NOT
    tombstone (errors leave state alone for inspection).
"""
from __future__ import annotations

import contextlib
import contextvars
import sqlite3
from typing import Any, Iterator

from ._core import _current_build_session

# The tombstone path resolves per-kind delete mutators via `globals()[verb]`,
# so every delete mutator must be importable into THIS module's namespace.
from .arrangement import remove_arrangement_clip, remove_cue_point
from .clips import delete_clip
from .devices import (
    delete_device,
    delete_device_chain,
    delete_envelope,
    remove_device_parameter,
)
from .requests import close_request, create_request, provenance_metadata
from .returns import delete_return
from .score import (
    delete_section,
    remove_tempo_point,
    remove_time_signature_point,
)
from .tracks import _delete_track


# Which (kind, song-scope) tables build owns + how to enumerate their ids
# given a song_id. The order here is the deletion order; respecting FK
# dependencies (children before parents) keeps cascade behavior predictable.
# Note: most cascades are handled by ON DELETE CASCADE in the schema; we
# delete the parent and trust the schema, but order from leaves inward
# anyway for visibility in event logs.
_BUILD_OWNED_KINDS: tuple[tuple[str, str, str], ...] = (
    # (kind, table, song_id column expression for SELECT id FROM <table>)
    ("envelope", "envelopes", "song_id"),
    ("arrangement_clip", "arrangement_clips", "song_id"),
    ("cue_point", "cue_points", "song_id"),
    ("tempo_point", "tempo_map", "song_id"),
    ("time_signature_point", "time_signature_map", "song_id"),
    ("section", "sections", "song_id"),
    # Devices live under chains under tracks/returns. Walking through chains
    # via JOIN; managed below via _build_owned_devices.
    ("device_parameter", "device_parameters", ""),  # special — joined via device->chain->track/return
    ("device", "devices", ""),                       # special — joined via chain->track/return
    ("device_chain", "device_chains", ""),           # special — joined via track/return
    ("return", "returns", "song_id"),
    ("clip", "clips", ""),  # special — joined via track
    ("track", "tracks", "song_id"),
)


# events.kind values whose payload's `<kind>_id` or `id` field names the entity
# the event acted on. Used to look up the "latest event actor" per row.
# Map: row-kind -> tuple of (event_kind, payload_field).
_LATEST_ACTOR_EVENTS: dict[str, tuple[tuple[str, str], ...]] = {
    "song":                  (("song_created", "song_id"), ("song_updated", "song_id")),
    "track":                 (("track_created", "track_id"), ("track_updated", "track_id"),
                              ("track_mixer_set", "track_id"),
                              ("track_routing_set", "track_id")),
    "clip":                  (("clip_created", "clip_id"), ("clip_updated", "clip_id")),
    "arrangement_clip":      (("arrangement_clip_added", "arrangement_clip_id"),),
    "section":               (("section_created", "section_id"),
                              ("section_updated", "section_id")),
    "tempo_point":           (("tempo_point_added", "point_id"),
                              ("tempo_point_updated", "point_id")),
    "time_signature_point":  (("time_signature_point_added", "point_id"),
                              ("time_signature_point_updated", "point_id")),
    "cue_point":             (("cue_point_added", "cue_id"),),
    "return":                (("return_created", "return_id"),
                              ("return_updated", "return_id")),
    "device_chain":          (("device_chain_created", "chain_id"),
                              ("device_chain_props_set", "chain_id")),
    "device":                (("device_created", "device_id"),
                              ("device_sidechain_set", "device_id")),
    "device_parameter":      (("device_parameter_set", "parameter_id"),),
    "envelope":              (("envelope_created", "envelope_id"),),
}


def _latest_actor_for(
    conn: sqlite3.Connection, *, row_kind: str, row_id: str,
) -> str | None:
    """Return the actor of the latest event referencing this row (None if
    no event references it). Used by tombstoning to decide whether build is
    allowed to delete the row (actor ∈ {'build','system'}) or must skip it.

    Special-case: row_kind='clip' uses the events.clip_id column directly so
    every clip-touching event (create, update, notes_replaced, notes_inserted,
    note_updated, notes_deleted, notes_bulk_updated) registers as a "touch
    on this clip" — so an LLM revising notes on a build-owned clip flips
    the clip's latest actor to 'llm' and protects it (and the notes that
    cascade with it) from tombstoning.
    """
    if row_kind == "clip":
        # Use the events.clip_id column — catches every clip-touching event
        # without needing per-event-kind payload introspection.
        row = conn.execute(
            "SELECT actor FROM events WHERE clip_id = ? "
            "ORDER BY seq DESC LIMIT 1",
            (row_id,),
        ).fetchone()
        return row["actor"] if row else None
    queries = _LATEST_ACTOR_EVENTS.get(row_kind)
    if not queries:
        return None
    # Build a UNION of per-event-kind queries, ordered by seq DESC, take 1.
    sql_parts = []
    params: list[Any] = []
    for ev_kind, field in queries:
        sql_parts.append(
            f"SELECT actor, seq FROM events "
            f"WHERE kind = ? AND json_extract(payload_json, '$.{field}') = ?"
        )
        params.extend([ev_kind, row_id])
    sql = " UNION ALL ".join(sql_parts) + " ORDER BY seq DESC LIMIT 1"
    row = conn.execute(sql, params).fetchone()
    return row["actor"] if row else None


_DELETE_VERBS: dict[str, str] = {
    # row-kind -> mutator that handles its delete (with proper event emission).
    "envelope":             "delete_envelope",
    "arrangement_clip":     "remove_arrangement_clip",
    "cue_point":            "remove_cue_point",
    "tempo_point":          "remove_tempo_point",
    "time_signature_point": "remove_time_signature_point",
    "section":              "delete_section",
    "device_parameter":     "remove_device_parameter",
    "device":               "delete_device",
    "device_chain":         "delete_device_chain",
    "return":               "delete_return",
    "clip":                 "delete_clip",
    "track":                "_delete_track",  # we add this below
}


class BuildSession:
    """State carried by `M.build_session`. Tracks touched (kind, id) pairs."""

    __slots__ = ("conn", "song_name", "song_id", "owner", "request_id",
                 "touched", "_token", "_outcome")

    def __init__(
        self, conn: sqlite3.Connection, *, song_name: str, owner: str,
    ) -> None:
        self.conn = conn
        self.song_name = song_name
        self.owner = owner
        self.song_id: str | None = None
        self.request_id: str | None = None
        self.touched: set[tuple[str, str]] = set()
        self._token: contextvars.Token | None = None
        self._outcome: str = "ok"

    def record_touch(self, kind: str, id_: str) -> None:
        """Called by mutators after their state write. Idempotent — duplicate
        touches in one build are fine (a build that creates then updates a
        row records two touches for the same id; the set dedups)."""
        self.touched.add((kind, id_))

    def touched_count(self, kind: str | None = None) -> int:
        """Diagnostic helper. With kind=None: total touches; with kind: touches of that kind."""
        if kind is None:
            return len(self.touched)
        return sum(1 for k, _ in self.touched if k == kind)


@contextlib.contextmanager
def build_session(
    conn: sqlite3.Connection,
    *,
    song_name: str,
    owner: str = "build.py",
    reason: str | None = None,
    prompt_text: str | None = None,
    parent_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> Iterator[BuildSession]:
    """State-converger context manager for a song's build.py (W12-A).

    Inside the `with` block:
      - Mutators default to actor='build' (unless caller passes otherwise).
      - Every mutator call's (kind, id) is recorded on the session.

    On clean exit:
      - For each managed kind owned by this song, build-owned rows
        (latest event actor ∈ {'build','system'}) NOT in the touched set
        are deleted (cascades naturally via schema FKs).
      - The session's request closes with outcome='ok'.

    On exception:
      - The session's request closes with outcome='failed'; no tombstoning.

    Resolves `song_id` lazily: build.py's first call inside the session is
    typically `M.create_song(name=song_name)`, which the tombstone path
    needs to find rows by song. If a song with `song_name` doesn't exist
    at exit time (e.g., create_song was never called), tombstone is a no-op.

    Arc 2 / B4 provenance: `prompt_text` (user's compose prompt) and
    `parent_id` (parent request, if this build runs inside an outer
    cycle) thread directly to `create_request`. `metadata` augments the
    auto-captured `provenance_metadata()` signals (git_sha, branch,
    hostname) — caller-provided keys override auto-captured ones. If
    nothing is provided, auto-capture still fires so every compose
    cycle gets the standard platform context.
    """
    bs = BuildSession(conn, song_name=song_name, owner=owner)
    # Auto-capture platform metadata so EVERY build session gets the
    # standard signals — callers don't need to remember to opt in. They
    # can still augment via the explicit `metadata=` kwarg; explicit
    # keys override auto-captured ones (the caller knows better).
    auto_meta = provenance_metadata()
    if metadata:
        auto_meta.update(metadata)
    # Open a request to carry the build's actor + provenance for child events.
    bs.request_id = create_request(
        conn,
        actor="build",
        intent=f"build {song_name} (owner={owner})",
        kind="compose",
        reason=reason,
        prompt_text=prompt_text,
        parent_id=parent_id,
        metadata=auto_meta if auto_meta else None,
    )
    bs._token = _current_build_session.set(bs)
    try:
        yield bs
    except BaseException:  # prawduct:ok-broad-except
        # On any failure (including KeyboardInterrupt), close the request as
        # failed and skip tombstoning. The DB stays in whatever partial state
        # the build left it (transaction discipline is the caller's; we do
        # NOT wrap the build in a transaction because builds are large and
        # callers may want partial-progress observability).
        bs._outcome = "failed"
        _current_build_session.reset(bs._token)
        close_request(conn, request_id=bs.request_id, outcome="failed")
        raise
    # Clean exit: resolve song_id (from create_song's touch or by name) and
    # tombstone non-touched build-owned rows.
    _current_build_session.reset(bs._token)
    song_row = conn.execute(
        "SELECT id FROM songs WHERE name = ?", (song_name,),
    ).fetchone()
    if song_row is None:
        # No song was created — nothing to tombstone.
        close_request(conn, request_id=bs.request_id, outcome="ok")
        return
    bs.song_id = song_row["id"]
    _tombstone_untouched(conn, bs)
    close_request(conn, request_id=bs.request_id, outcome="ok")


_NESTED_RACK_CHAINS_CTE = """
WITH RECURSIVE song_chains(id) AS (
    -- Anchor: top-level chains (parented by a track or return in this song).
    SELECT dc.id FROM device_chains dc
    LEFT JOIN tracks t ON t.id = dc.parent_track_id
    LEFT JOIN returns r ON r.id = dc.parent_return_id
    WHERE t.song_id = ? OR r.song_id = ?
    UNION
    -- Recursive: chains parented by a rack device that itself lives in
    -- a song-rooted chain. Walks nested-rack hierarchies of any depth;
    -- terminates naturally when no more chains reference the frontier.
    SELECT dc.id FROM device_chains dc
    JOIN devices d ON d.id = dc.parent_rack_device_id
    JOIN song_chains sc ON sc.id = d.chain_id
)
"""


def _tombstone_untouched(conn: sqlite3.Connection, bs: BuildSession) -> None:
    """Delete build-owned rows for this song not touched in this build.

    Build-owned = latest event actor ∈ {'build', 'system'}. 'sync'-actor
    rows (pulled from Live) survive; 'llm'/'user'/'generator'-actor rows
    survive too — only build's own droppings get cleaned up.

    Walks the kinds in `_BUILD_OWNED_KINDS` in dependency-leaf-first order.
    The schema FKs handle most cascades, but explicit per-kind deletion
    ensures each row's deletion event is emitted by the corresponding
    `M.<delete>` mutator (no silent cascades missing events).
    """
    assert bs.song_id is not None
    song_id = bs.song_id
    touched_by_kind: dict[str, set[str]] = {}
    for k, i in bs.touched:
        touched_by_kind.setdefault(k, set()).add(i)
    for kind, table, song_col in _BUILD_OWNED_KINDS:
        # Build the SELECT query — special-cases for chain/device/device_parameter/clip
        # that don't have direct song_id columns.
        if song_col:
            row_ids = [
                r["id"] for r in conn.execute(
                    f"SELECT id FROM {table} WHERE {song_col} = ?", (song_id,),
                ).fetchall()
            ]
        elif kind == "clip":
            row_ids = [
                r["id"] for r in conn.execute(
                    """SELECT c.id FROM clips c
                       JOIN tracks t ON t.id = c.track_id
                       WHERE t.song_id = ?""",
                    (song_id,),
                ).fetchall()
            ]
        elif kind == "device_chain":
            row_ids = [
                r["id"] for r in conn.execute(
                    _NESTED_RACK_CHAINS_CTE + "SELECT id FROM song_chains",
                    (song_id, song_id),
                ).fetchall()
            ]
        elif kind == "device":
            row_ids = [
                r["id"] for r in conn.execute(
                    _NESTED_RACK_CHAINS_CTE
                    + "SELECT d.id FROM devices d "
                    + "JOIN song_chains sc ON sc.id = d.chain_id",
                    (song_id, song_id),
                ).fetchall()
            ]
        elif kind == "device_parameter":
            row_ids = [
                r["id"] for r in conn.execute(
                    _NESTED_RACK_CHAINS_CTE
                    + "SELECT dp.id FROM device_parameters dp "
                    + "JOIN devices d ON d.id = dp.device_id "
                    + "JOIN song_chains sc ON sc.id = d.chain_id",
                    (song_id, song_id),
                ).fetchall()
            ]
        else:
            row_ids = []
        touched_ids = touched_by_kind.get(kind, set())
        for row_id in row_ids:
            if row_id in touched_ids:
                continue
            actor = _latest_actor_for(conn, row_kind=kind, row_id=row_id)
            # Treat None as 'system' (no event found = legacy/seed data,
            # tombstone-eligible per the design).
            if actor is not None and actor not in ("build", "system"):
                continue
            verb = _DELETE_VERBS.get(kind)
            if verb is None:
                continue
            mutator = globals()[verb]
            # Each kind's delete takes a kwarg whose name varies — map it.
            kwarg = _DELETE_KWARGS[kind]
            mutator(conn, actor="build", request_id=bs.request_id,
                    **{kwarg: row_id})


# Argument names accepted by each delete mutator (since they vary by kind).
_DELETE_KWARGS: dict[str, str] = {
    "envelope":             "envelope_id",
    "arrangement_clip":     "arrangement_clip_id",
    "cue_point":            "cue_id",
    "tempo_point":          "point_id",
    "time_signature_point": "point_id",
    "section":              "section_id",
    "device_chain":         "chain_id",
    "device":               "device_id",
    "return":               "return_id",
    "clip":                 "clip_id",
    "track":                "track_id",
}


# `device_parameter` doesn't fit the kwarg-by-id pattern (it's keyed by
# (device_id, name)). Tombstoning a device_parameter directly is rare — the
# parent device usually carries the tombstone. Skip device_parameter from
# top-level tombstoning by removing it from the _DELETE_VERBS map (its row
# gets caught when the parent device tombstones).
del _DELETE_VERBS["device_parameter"]


__all__ = [
    "BuildSession",
    "_latest_actor_for",
    "build_session",
]
