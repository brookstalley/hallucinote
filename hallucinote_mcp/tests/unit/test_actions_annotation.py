"""``ableton_annotation`` action surface.

Tests focus on the MCP-layer wrapping: schema correctness and the
song_slug → DB → song_id resolution path. The underlying W8-C mutators/
queries are covered in tests/unit/db/test_mutations.py — we don't re-test
their semantics here.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from hallucinote.db import mutations as M
from hallucinote.db.connection import init_db
from hallucinote_mcp.handlers import ableton_annotation as annotation_handlers


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def song_db(tmp_path: Path) -> tuple[Path, str, str]:
    """Build a minimal per-song DB at a temp path: one song row + two tracks.

    Returns (db_path, song_id, slug). The slug matches the song's
    ``name`` column (handlers look up by name).
    """
    db_path = tmp_path / "fake-slug.db"
    conn = init_db(db_path)
    slug = "fake-slug"
    song_id = str(M.create_song(conn, name=slug))
    M.create_track(conn, song_id=song_id, track_index=1, name="Drums")
    M.create_track(conn, song_id=song_id, track_index=2, name="Bass")
    conn.commit()
    conn.close()
    return db_path, song_id, slug


@pytest.fixture(autouse=True)
def _route_resolver(song_db, monkeypatch):
    """Redirect ``_resolve_song_db`` to the test fixture's DB path for the
    duration of every test in this module — handlers think they're
    resolving a real songs/<slug>/ layout but actually use tmp_path.
    Also routes ``hallucinote_mcp.provenance._resolve_song_db_path`` so
    the dispatcher's auto-provenance lands on the same fixture DB.
    """
    from hallucinote_mcp import provenance

    db_path, _song_id, _slug = song_db
    monkeypatch.setattr(
        annotation_handlers, "_resolve_song_db", lambda _slug: db_path
    )
    monkeypatch.setattr(
        provenance, "_resolve_song_db_path", lambda _slug: db_path
    )


# ---------------------------------------------------------------------------
# Schema sanity
# ---------------------------------------------------------------------------


def test_action_registry_has_six_annotation_actions():
    from hallucinote_mcp import schema

    names = {a.name for a in schema.actions_for("ableton_annotation")}
    assert names == {"help", "add", "list", "get_at_bar", "update", "delete"}


# ---------------------------------------------------------------------------
# add
# ---------------------------------------------------------------------------


def test_add_song_scoped_returns_dict_with_id(song_db):
    _db, song_id, slug = song_db
    result = annotation_handlers.add_handler(
        None,
        song_slug=slug,
        kind="intent",
        body="this song is sad",
    )
    assert "error" not in result
    assert result["body"] == "this song is sad"
    assert result["kind"] == "intent"
    assert result["song_id"] == song_id
    # Song-scoped: track + bars all NULL.
    assert result["track_id"] is None
    assert result["start_bar"] is None
    assert result["end_bar"] is None


def test_add_time_scoped_writes_bar_range(song_db):
    _db, _song_id, slug = song_db
    result = annotation_handlers.add_handler(
        None,
        song_slug=slug,
        kind="stylistic",
        body="bloom the reverb here",
        start_bar=16.0,
        end_bar=24.0,
    )
    assert result["start_bar"] == 16.0
    assert result["end_bar"] == 24.0
    assert result["track_id"] is None


def test_add_track_scoped_resolves_index_to_id(song_db):
    _db, song_id, slug = song_db
    result = annotation_handlers.add_handler(
        None,
        song_slug=slug,
        kind="structure",
        body="play softer on the bridge",
        track_index=2,
    )
    assert result["track_id"] is not None
    # Resolution sanity: round-trip via the queries layer.
    import sqlite3
    db_path = annotation_handlers._resolve_song_db(slug)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    track_row = conn.execute(
        "SELECT name FROM tracks WHERE id = ?", (result["track_id"],)
    ).fetchone()
    conn.close()
    assert track_row["name"] == "Bass"


def test_add_unknown_track_index_raises_teaching_error(song_db):
    """Handlers raise ValueError so the dispatcher's broad-except translates
    to a structured wire error response (ok=False). Returning an
    {error: ...} dict would surface as ok=True with the error buried in
    the result — the same shape every other hallucinote_mcp handler avoids."""
    _db, _song_id, slug = song_db
    with pytest.raises(ValueError) as excinfo:
        annotation_handlers.add_handler(
            None,
            song_slug=slug,
            kind="todo",
            body="nope",
            track_index=99,
        )
    msg = str(excinfo.value)
    assert "no track at index 99" in msg
    assert "ableton_track(action='list')" in msg


def test_add_unknown_slug_raises_teaching_error(tmp_path: Path, monkeypatch):
    """Override the resolver to point at a path that doesn't exist."""
    bogus = tmp_path / "does-not-exist.db"
    monkeypatch.setattr(
        annotation_handlers, "_resolve_song_db", lambda _slug: bogus
    )
    with pytest.raises(ValueError) as excinfo:
        annotation_handlers.add_handler(
            None,
            song_slug="ghost-song",
            kind="intent",
            body="x",
        )
    assert "ghost-song" in str(excinfo.value)


def test_add_rejects_invalid_kind_via_w8c_mutator(song_db):
    """Invalid kind reaches M.add_annotation, which raises; the dispatcher
    layer would translate that. Here at the handler level we expect a
    raised ValueError — the dispatcher's existing try/except catches it
    in the actual MCP flow."""
    _db, _song_id, slug = song_db
    with pytest.raises(ValueError, match="invalid annotation kind"):
        annotation_handlers.add_handler(
            None, song_slug=slug, kind="bogus", body="x"
        )


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------


def test_list_returns_annotations_in_canonical_order(song_db):
    _db, _song_id, slug = song_db
    annotation_handlers.add_handler(None, song_slug=slug, kind="intent", body="song A")
    annotation_handlers.add_handler(
        None, song_slug=slug, kind="structure", body="time A", start_bar=4.0
    )
    annotation_handlers.add_handler(
        None, song_slug=slug, kind="stylistic", body="time B", start_bar=12.0
    )
    result = annotation_handlers.list_handler(None, song_slug=slug)
    bodies = [a["body"] for a in result["annotations"]]
    # Song-scoped first, then time-scoped by start_bar.
    assert bodies == ["song A", "time A", "time B"]


def test_list_filters_by_kind(song_db):
    _db, _song_id, slug = song_db
    annotation_handlers.add_handler(None, song_slug=slug, kind="intent", body="i1")
    annotation_handlers.add_handler(None, song_slug=slug, kind="todo", body="t1")
    annotation_handlers.add_handler(None, song_slug=slug, kind="intent", body="i2")
    result = annotation_handlers.list_handler(None, song_slug=slug, kind="todo")
    assert {a["body"] for a in result["annotations"]} == {"t1"}


# ---------------------------------------------------------------------------
# get_at_bar
# ---------------------------------------------------------------------------


def test_get_at_bar_returns_overlapping_and_song_scoped(song_db):
    _db, _song_id, slug = song_db
    annotation_handlers.add_handler(None, song_slug=slug, kind="intent", body="always")
    annotation_handlers.add_handler(
        None,
        song_slug=slug,
        kind="stylistic",
        body="bars 4-12",
        start_bar=4.0,
        end_bar=12.0,
    )
    annotation_handlers.add_handler(
        None,
        song_slug=slug,
        kind="stylistic",
        body="bars 20-28",
        start_bar=20.0,
        end_bar=28.0,
    )
    result = annotation_handlers.get_at_bar_handler(None, song_slug=slug, bar=8.0)
    bodies = {a["body"] for a in result["annotations"]}
    assert bodies == {"always", "bars 4-12"}


# ---------------------------------------------------------------------------
# update
# ---------------------------------------------------------------------------


def test_update_patches_body_only(song_db):
    _db, _song_id, slug = song_db
    created = annotation_handlers.add_handler(
        None, song_slug=slug, kind="intent", body="original"
    )
    result = annotation_handlers.update_handler(
        None,
        song_slug=slug,
        annotation_id=created["id"],
        body="revised",
    )
    assert result["body"] == "revised"
    assert result["kind"] == "intent"  # unchanged


def test_update_with_no_fields_raises_teaching_error(song_db):
    _db, _song_id, slug = song_db
    created = annotation_handlers.add_handler(
        None, song_slug=slug, kind="intent", body="x"
    )
    with pytest.raises(ValueError, match="at least one of"):
        annotation_handlers.update_handler(
            None, song_slug=slug, annotation_id=created["id"]
        )


def test_update_unknown_id_raises_teaching_error(song_db):
    _db, _song_id, slug = song_db
    with pytest.raises(ValueError, match="no annotation with id"):
        annotation_handlers.update_handler(
            None,
            song_slug=slug,
            annotation_id="0" * 32,
            body="x",
        )


# ---------------------------------------------------------------------------
# delete
# ---------------------------------------------------------------------------


def test_delete_removes_annotation(song_db):
    _db, _song_id, slug = song_db
    created = annotation_handlers.add_handler(
        None, song_slug=slug, kind="intent", body="going away"
    )
    result = annotation_handlers.delete_handler(
        None, song_slug=slug, annotation_id=created["id"]
    )
    assert result["deleted"] is True
    listed = annotation_handlers.list_handler(None, song_slug=slug)
    assert listed["annotations"] == []


def test_delete_unknown_id_is_idempotent(song_db):
    """M.delete_annotation is documented as no-op on missing id; the
    handler must surface that as a clean success (no exception)."""
    _db, _song_id, slug = song_db
    result = annotation_handlers.delete_handler(
        None, song_slug=slug, annotation_id="0" * 32
    )
    assert result["deleted"] is True


def test_add_handler_returns_clean_dict_in_success_path(song_db):
    """Sanity: the success path does NOT carry an `error` key. Pairs with
    the raise-on-failure tests to lock the contract."""
    _db, _song_id, slug = song_db
    result = annotation_handlers.add_handler(
        None, song_slug=slug, kind="intent", body="success"
    )
    assert "error" not in result
    assert result["body"] == "success"


# ---------------------------------------------------------------------------
# Dispatcher integration — auto-provenance for db_writes actions (Arc 2 / B5)
# ---------------------------------------------------------------------------


def _events_for_annotation(db_path: Path, annotation_id: str) -> list[Any]:
    import sqlite3
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute(
            "SELECT * FROM events WHERE payload_json LIKE ? ORDER BY seq",
            (f'%"annotation_id":"{annotation_id}"%',),
        ).fetchall()
    finally:
        conn.close()


def test_dispatch_add_via_mcp_opens_kind_mutate_request(song_db):
    """End-to-end: dispatching an annotation `add` through ``dispatcher.dispatch``
    opens an ``M.request(kind='mutate')`` and threads its id into the
    ANNOTATION_ADDED event, so the audit trail has full provenance.
    """
    from hallucinote_mcp.dispatcher import dispatch
    from hallucinote_mcp.wire import Request

    db_path, song_id, slug = song_db

    resp = dispatch(Request(
        tool="ableton_annotation",
        action="add",
        params={"song_slug": slug, "kind": "intent", "body": "weight getting worse"},
    ))
    assert resp.ok, resp.error
    annotation_id = resp.result["id"]

    # ANNOTATION_ADDED event carries a request_id pointing at a kind='mutate' row.
    events = _events_for_annotation(db_path, annotation_id)
    added = [e for e in events if e["kind"] == "annotation_added"]
    assert len(added) == 1
    request_id = added[0]["request_id"]
    assert request_id is not None, "auto-provenance should have threaded a request_id"

    # The request row exists with kind='mutate' + outcome='ok' + bound to song.
    import sqlite3
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        req = conn.execute(
            "SELECT * FROM requests WHERE id = ?", (request_id,)
        ).fetchone()
    finally:
        conn.close()
    assert req["kind"] == "mutate"
    assert req["outcome"] == "ok"
    assert req["song_id"] == song_id
    assert req["actor"] == "llm"


def test_dispatch_update_via_mcp_threads_provenance(song_db):
    from hallucinote_mcp.dispatcher import dispatch
    from hallucinote_mcp.wire import Request

    db_path, _song_id, slug = song_db

    # Seed: add (auto-provenance) so we have an id to update.
    add_resp = dispatch(Request(
        tool="ableton_annotation",
        action="add",
        params={"song_slug": slug, "kind": "intent", "body": "initial"},
    ))
    annotation_id = add_resp.result["id"]

    update_resp = dispatch(Request(
        tool="ableton_annotation",
        action="update",
        params={
            "song_slug": slug,
            "annotation_id": annotation_id,
            "body": "revised",
        },
    ))
    assert update_resp.ok, update_resp.error

    events = _events_for_annotation(db_path, annotation_id)
    updates = [e for e in events if e["kind"] == "annotation_updated"]
    assert len(updates) == 1
    assert updates[0]["request_id"] is not None

    # The add and update events should belong to DIFFERENT request rows —
    # each MCP call opens its own kind='mutate' parent.
    added = [e for e in events if e["kind"] == "annotation_added"]
    assert added[0]["request_id"] != updates[0]["request_id"]


def test_dispatch_delete_via_mcp_threads_provenance(song_db):
    from hallucinote_mcp.dispatcher import dispatch
    from hallucinote_mcp.wire import Request

    db_path, _song_id, slug = song_db

    add_resp = dispatch(Request(
        tool="ableton_annotation",
        action="add",
        params={"song_slug": slug, "kind": "intent", "body": "doomed"},
    ))
    annotation_id = add_resp.result["id"]

    del_resp = dispatch(Request(
        tool="ableton_annotation",
        action="delete",
        params={"song_slug": slug, "annotation_id": annotation_id},
    ))
    assert del_resp.ok, del_resp.error

    events = _events_for_annotation(db_path, annotation_id)
    removed = [e for e in events if e["kind"] == "annotation_removed"]
    assert len(removed) == 1
    assert removed[0]["request_id"] is not None


def test_dispatch_list_via_mcp_does_not_open_request(song_db):
    """`list` is a read — db_writes=False — so the dispatcher must NOT open
    a provenance request. Sanity test that the flag actually gates.
    """
    from hallucinote_mcp.dispatcher import dispatch
    from hallucinote_mcp.wire import Request

    db_path, _song_id, slug = song_db

    before = _count_requests(db_path)
    resp = dispatch(Request(
        tool="ableton_annotation",
        action="list",
        params={"song_slug": slug},
    ))
    assert resp.ok
    after = _count_requests(db_path)
    assert after == before, "list is read-only; no kind='mutate' request should land"


def _count_requests(db_path: Path) -> int:
    import sqlite3
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute("SELECT COUNT(*) FROM requests").fetchone()[0]
    finally:
        conn.close()


def test_dispatch_add_with_missing_song_db_still_returns_teaching_error(tmp_path: Path, monkeypatch):
    """If the song DB doesn't exist yet, auto-provenance degrades silently
    (no request row) and the handler surfaces its own teaching error —
    the LLM sees the same diagnostic shape as before.
    """
    from hallucinote_mcp import provenance
    from hallucinote_mcp.dispatcher import dispatch
    from hallucinote_mcp.wire import Request

    bogus_path = tmp_path / "no-such-song.db"
    monkeypatch.setattr(
        annotation_handlers, "_resolve_song_db", lambda _slug: bogus_path
    )
    monkeypatch.setattr(
        provenance, "_resolve_song_db_path", lambda _slug: bogus_path
    )

    resp = dispatch(Request(
        tool="ableton_annotation",
        action="add",
        params={"song_slug": "ghost", "kind": "intent", "body": "x"},
    ))
    assert not resp.ok
    assert "ghost" in (resp.error or "")


def test_dispatch_handler_exception_closes_request_failed(song_db):
    """If the handler raises mid-flight, the auto-provenance request closes
    with outcome='failed' — the audit trail must show the cycle didn't
    complete.
    """
    from hallucinote_mcp.dispatcher import dispatch
    from hallucinote_mcp.wire import Request

    db_path, _song_id, slug = song_db
    # `track_index=99` → handler raises (no such track) AFTER auto-provenance
    # opened the request. The except-translate path in the dispatcher returns
    # a structured error response; the request row should be closed failed.
    resp = dispatch(Request(
        tool="ableton_annotation",
        action="add",
        params={
            "song_slug": slug,
            "kind": "todo",
            "body": "nope",
            "track_index": 99,
        },
    ))
    assert not resp.ok

    import sqlite3
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT * FROM requests WHERE kind = 'mutate' ORDER BY ts DESC LIMIT 1"
        ).fetchall()
    finally:
        conn.close()
    assert len(rows) == 1
    assert rows[0]["outcome"] == "failed"
