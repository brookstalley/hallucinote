"""Auto-provenance helper for the MCP dispatcher.

Covers ``hallucinote_mcp.provenance.auto_request`` — the context manager
that wraps server-side, DB-writing handler calls in an
``M.request(kind='mutate', ...)`` so every emitted event ties back to the
MCP call that produced it.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from hallucinote.db import mutations as M
from hallucinote.db import queries as Q
from hallucinote.db.connection import init_db
from hallucinote_mcp import provenance


@pytest.fixture()
def song_db(tmp_path: Path) -> tuple[Path, str, str]:
    """Minimal per-song DB: one song row. Returns (db_path, song_id, slug)."""
    db_path = tmp_path / "fake-slug.db"
    conn = init_db(db_path)
    slug = "fake-slug"
    song_id = M.create_song(conn, name=slug)
    conn.commit()
    conn.close()
    return db_path, song_id, slug


@pytest.fixture(autouse=True)
def _route_resolver(song_db, monkeypatch):
    db_path, _song_id, _slug = song_db
    monkeypatch.setattr(
        provenance, "_resolve_song_db_path", lambda _slug: db_path
    )


def test_auto_request_yields_request_id_when_song_exists(song_db):
    _db, song_id, slug = song_db
    with provenance.auto_request(
        tool="ableton_annotation",
        action_name="add",
        params={"song_slug": slug, "kind": "intent", "body": "foo"},
    ) as rid:
        assert rid is not None

    db_path, _, _ = song_db
    conn = init_db(db_path)
    try:
        row = Q.get_request(conn, rid)
        assert row is not None
        assert row["kind"] == "mutate"
        assert row["actor"] == "llm"
        assert row["song_id"] == song_id
        assert row["outcome"] == "ok"
        assert row["intent"] == "ableton_annotation('add')"
    finally:
        conn.close()


def test_auto_request_records_failed_outcome_on_exception(song_db):
    _db, _song_id, slug = song_db
    captured_rid: list[str] = []

    class _BoomError(Exception):
        pass

    with pytest.raises(_BoomError):
        with provenance.auto_request(
            tool="ableton_annotation",
            action_name="add",
            params={"song_slug": slug, "kind": "intent", "body": "foo"},
        ) as rid:
            assert rid is not None
            captured_rid.append(rid)
            raise _BoomError("handler blew up")

    db_path, _, _ = song_db
    conn = init_db(db_path)
    try:
        row = Q.get_request(conn, captured_rid[0])
        assert row["outcome"] == "failed"
    finally:
        conn.close()


def test_auto_request_yields_none_when_song_slug_missing():
    with provenance.auto_request(
        tool="ableton_annotation",
        action_name="add",
        params={"kind": "intent", "body": "foo"},
    ) as rid:
        assert rid is None


def test_auto_request_yields_none_when_db_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(
        provenance,
        "_resolve_song_db_path",
        lambda _slug: tmp_path / "definitely-not-here.db",
    )
    with provenance.auto_request(
        tool="ableton_annotation",
        action_name="add",
        params={"song_slug": "missing", "kind": "intent", "body": "foo"},
    ) as rid:
        assert rid is None


def test_auto_request_yields_none_when_resolver_raises(monkeypatch):
    def _explode(_slug: str) -> Path:
        raise RuntimeError("resolver blew up")

    monkeypatch.setattr(provenance, "_resolve_song_db_path", _explode)
    with provenance.auto_request(
        tool="ableton_annotation",
        action_name="add",
        params={"song_slug": "fake-slug", "kind": "intent", "body": "foo"},
    ) as rid:
        assert rid is None


def test_auto_request_yields_none_when_slug_not_a_string():
    with provenance.auto_request(
        tool="ableton_annotation",
        action_name="add",
        params={"song_slug": 42, "kind": "intent", "body": "foo"},
    ) as rid:
        assert rid is None


def test_auto_request_records_payload_and_metadata(song_db):
    _db, _song_id, slug = song_db
    params = {"song_slug": slug, "kind": "intent", "body": "weight getting worse"}
    with provenance.auto_request(
        tool="ableton_annotation",
        action_name="add",
        params=params,
    ) as rid:
        assert rid is not None

    db_path, _, _ = song_db
    conn = init_db(db_path)
    try:
        row = Q.get_request(conn, rid)
        # payload_json carries the validated params verbatim — the LLM's
        # call shape is part of the audit trail.
        import json
        payload = json.loads(row["payload_json"])
        assert payload == {"params": params}
        # metadata_json is best-effort (git + hostname); inside a repo it
        # at least carries SOMETHING, but the test stays tolerant.
        if row["metadata_json"] is not None:
            assert isinstance(json.loads(row["metadata_json"]), dict)
    finally:
        conn.close()
