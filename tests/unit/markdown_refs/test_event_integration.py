"""Event integration tests — request lifecycle + MARKDOWN_REF_RECORDED."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from hallucinote.db import init_db, mutations as M, queries as Q
from hallucinote.db import events as E
from hallucinote.markdown_refs import reindex_corpus


@pytest.fixture
def conn(tmp_path: Path):
    c = init_db(tmp_path / "test.db")
    yield c
    c.close()


def _events(conn, kind: str | None = None):
    if kind is None:
        return conn.execute("SELECT * FROM events ORDER BY seq").fetchall()
    return conn.execute(
        "SELECT * FROM events WHERE kind = ? ORDER BY seq", (kind,)
    ).fetchall()


# ---------- schema migration idempotency ----------


def test_init_db_is_idempotent_on_existing_db(tmp_path: Path):
    db_path = tmp_path / "x.db"
    init_db(db_path).close()
    # Re-init should add no new columns and not raise.
    c = init_db(db_path)
    info = c.execute("PRAGMA table_info(requests)").fetchall()
    cols = {r["name"] for r in info}
    assert {"kind", "duration_ms", "outcome"} <= cols
    c.close()


def test_added_columns_present_on_requests(conn):
    info = conn.execute("PRAGMA table_info(requests)").fetchall()
    cols = {r["name"] for r in info}
    assert "kind" in cols
    assert "duration_ms" in cols
    assert "outcome" in cols


def test_added_columns_present_on_devices(conn):
    """Sweep B: devices.preset_query column landed via _ADDED_COLUMNS so
    existing DBs from v0.9.0 don't crash on the first create_device call
    after upgrade."""
    info = conn.execute("PRAGMA table_info(devices)").fetchall()
    cols = {r["name"] for r in info}
    assert "preset_query" in cols


def test_migration_adds_preset_query_to_pre_sweepb_devices_table(tmp_path: Path):
    """Regression test for the schema-migration gap the Critic caught:
    a DB created BEFORE Sweep B (no preset_query column) must gain the
    column via _ADDED_COLUMNS on the next init_db open, not crash when
    create_device is called."""

    db_path = tmp_path / "pre-sweepb.db"
    # Simulate a v0.9.0 DB: build the devices table without preset_query.
    raw = sqlite3.connect(db_path)
    raw.execute(
        """CREATE TABLE devices (
            id              TEXT PRIMARY KEY,
            chain_id        TEXT NOT NULL,
            position        INTEGER NOT NULL,
            kind            TEXT NOT NULL,
            display_name    TEXT NOT NULL,
            preset_uri      TEXT,
            UNIQUE(chain_id, position)
        )"""
    )
    raw.commit()
    raw.close()

    # Now open with init_db — migration must add preset_query.
    c = init_db(db_path)
    try:
        info = c.execute("PRAGMA table_info(devices)").fetchall()
        cols = {r["name"] for r in info}
        assert "preset_query" in cols, (
            "Sweep B's preset_query column missing on a pre-Sweep-B DB — "
            "the _ADDED_COLUMNS migration must add it on init_db."
        )
    finally:
        c.close()


# ---------- create_request with kind ----------


def test_create_request_default_kind_is_mutate(conn):
    rid = M.create_request(conn, actor="user", intent="x")
    row = Q.get_request(conn, rid)
    assert row["kind"] == "mutate"


def test_create_request_accepts_kind(conn):
    rid = M.create_request(
        conn, actor="llm", intent="build chorus", kind="compose"
    )
    row = Q.get_request(conn, rid)
    assert row["kind"] == "compose"
    # REQUEST_CREATED event payload carries the kind too
    ev = _events(conn, E.REQUEST_CREATED)[-1]
    payload = json.loads(ev["payload_json"])
    assert payload["kind"] == "compose"


def test_create_request_rejects_invalid_kind(conn):
    with pytest.raises(ValueError, match="invalid kind"):
        M.create_request(conn, actor="user", intent="x", kind="invalid")


# ---------- close_request ----------


def test_close_request_sets_outcome_and_emits_event(conn):
    rid = M.create_request(conn, actor="llm", intent="x", kind="compose")
    M.close_request(conn, request_id=rid, outcome="ok", duration_ms=1234)

    row = Q.get_request(conn, rid)
    assert row["outcome"] == "ok"
    assert row["duration_ms"] == 1234

    closed = _events(conn, E.REQUEST_CLOSED)
    assert len(closed) == 1
    payload = json.loads(closed[0]["payload_json"])
    assert payload == {"request_id": rid, "outcome": "ok", "duration_ms": 1234}
    assert closed[0]["request_id"] == rid


def test_close_request_rejects_invalid_outcome(conn):
    rid = M.create_request(conn, actor="user", intent="x")
    with pytest.raises(ValueError, match="invalid outcome"):
        M.close_request(conn, request_id=rid, outcome="meh")


def test_close_request_raises_when_unknown(conn):
    with pytest.raises(ValueError, match="not found"):
        M.close_request(conn, request_id="deadbeef", outcome="ok")


# ---------- request context manager ----------


def test_request_context_manager_happy_path(conn):
    with M.request(conn, actor="llm", intent="x", kind="compose") as rid:
        assert isinstance(rid, str)
    row = Q.get_request(conn, rid)
    assert row["outcome"] == "ok"
    assert row["duration_ms"] is not None
    assert row["duration_ms"] >= 0


def test_request_context_manager_marks_failed_on_exception(conn):
    rid_seen = []
    with pytest.raises(RuntimeError):
        with M.request(conn, actor="llm", intent="x", kind="push") as rid:
            rid_seen.append(rid)
            raise RuntimeError("boom")
    row = Q.get_request(conn, rid_seen[0])
    assert row["outcome"] == "failed"
    assert row["duration_ms"] is not None


def test_request_context_manager_threads_request_id_through_mutators(conn):
    """The whole point of the lifecycle: mutator events nest under request."""
    sid_seen = []
    with M.request(conn, actor="llm", intent="x", kind="compose") as rid:
        sid = M.create_song(
            conn, name="s", key="Dm",
            actor="llm", request_id=rid,
        )
        sid_seen.append(sid)
    # Find SONG_CREATED event; its request_id should be rid
    song_events = _events(conn, E.SONG_CREATED)
    assert len(song_events) == 1
    assert song_events[0]["request_id"] == rid


# ---------- record_markdown_ref ----------


def test_record_markdown_ref_emits_event(conn):
    sid = M.create_song(conn, name="s", key="Dm")
    M.record_markdown_ref(
        conn,
        path="songs/s/decisions/2026-05-19-x.md",
        content_hash="abc",
        song_id=sid,
        frontmatter={"kind": "decision", "scope": "song"},
    )
    evs = _events(conn, E.MARKDOWN_REF_RECORDED)
    assert len(evs) == 1
    payload = json.loads(evs[0]["payload_json"])
    assert payload["path"] == "songs/s/decisions/2026-05-19-x.md"
    assert payload["content_hash"] == "abc"
    assert payload["frontmatter"]["kind"] == "decision"
    assert evs[0]["song_id"] == sid


def test_record_markdown_ref_threads_request_id(conn):
    sid = M.create_song(conn, name="s", key="Dm")
    with M.request(conn, actor="llm", intent="add decision",
                   kind="compose", song_id=sid) as rid:
        M.record_markdown_ref(
            conn,
            path="songs/s/decisions/x.md",
            content_hash="abc",
            song_id=sid,
            request_id=rid,
            frontmatter={"kind": "decision", "scope": "song"},
        )
    ev = _events(conn, E.MARKDOWN_REF_RECORDED)[-1]
    assert ev["request_id"] == rid


# ---------- cross-reference query ----------


def test_find_markdown_refs_for_request(tmp_path: Path):
    """End-to-end: open request, write file, record event, reindex,
    cross-reference."""
    # Set up a synthetic mini-repo
    songs_root = tmp_path / "songs"
    songs_root.mkdir()
    conn = init_db(tmp_path / "test.db")
    try:
        sid = M.create_song(conn, name="tunesong", key="Dm")

        # Write the decision file on disk
        deco = tmp_path / "songs/tunesong/decisions/2026-05-19-x.md"
        deco.parent.mkdir(parents=True)
        deco.write_text(
            "---\nkind: decision\nscope: song\ndate: 2026-05-19\n---\n"
            "body\n", encoding="utf-8",
        )

        # Reindex builds the projection row
        reindex_corpus(conn, songs_root=songs_root, repo_root=tmp_path)

        # Open a request, emit the audit event
        with M.request(conn, actor="llm", intent="decision X",
                       kind="compose", song_id=sid) as rid:
            M.record_markdown_ref(
                conn,
                path=str(deco.relative_to(tmp_path)),
                content_hash="abc",
                song_id=sid,
                request_id=rid,
                frontmatter={"kind": "decision", "scope": "song"},
            )

        # Cross-reference: what refs were recorded during this request?
        rows = Q.find_markdown_refs_for_request(conn, rid)
        assert len(rows) == 1
        assert rows[0]["path"].endswith("2026-05-19-x.md")
        assert rows[0]["kind"] == "decision"
        # `recorded_at` column from events.ts is exposed
        assert rows[0]["recorded_at"] is not None
    finally:
        conn.close()


# ---------- write_markdown_ref (LLM one-call surface) ----------


def test_write_markdown_ref_creates_file_and_indexes_and_emits(tmp_path: Path):
    from hallucinote.markdown_refs import write_markdown_ref

    songs_root = tmp_path / "songs"
    songs_root.mkdir()
    conn = init_db(tmp_path / "test.db")
    try:
        sid = M.create_song(conn, name="tunesong", key="Dm")
        with M.request(conn, actor="llm", intent="rec",
                       kind="compose", song_id=sid) as rid:
            doc = write_markdown_ref(
                conn,
                path=Path("songs/tunesong/decisions/2026-05-19-x.md"),
                repo_root=tmp_path,
                body="Why we did this.",
                frontmatter={
                    "kind": "decision", "scope": "song",
                    "date": "2026-05-19",
                },
                request_id=rid,
            )

        # File on disk
        on_disk = tmp_path / "songs/tunesong/decisions/2026-05-19-x.md"
        assert on_disk.exists()
        text = on_disk.read_text(encoding="utf-8")
        assert "kind: decision" in text
        assert "Why we did this." in text

        # markdown_refs upserted
        row = Q.get_markdown_ref(
            conn, "songs/tunesong/decisions/2026-05-19-x.md"
        )
        assert row is not None
        assert row["kind"] == "decision"
        assert row["content_hash"] == doc.content_hash

        # MARKDOWN_REF_RECORDED event threaded to the request
        ev = _events(conn, E.MARKDOWN_REF_RECORDED)[-1]
        assert ev["request_id"] == rid

        # Cross-reference query finds it
        rows = Q.find_markdown_refs_for_request(conn, rid)
        assert len(rows) == 1
        assert rows[0]["path"].endswith("2026-05-19-x.md")
    finally:
        conn.close()


def test_write_markdown_ref_raises_on_invalid_frontmatter(tmp_path: Path):
    from hallucinote.markdown_refs import write_markdown_ref

    (tmp_path / "songs").mkdir()
    conn = init_db(tmp_path / "test.db")
    try:
        with pytest.raises(ValueError, match="invalid kind"):
            write_markdown_ref(
                conn,
                path=Path("songs/x/decisions/x.md"),
                repo_root=tmp_path,
                body="x",
                frontmatter={"kind": "speculation", "scope": "song"},
            )
    finally:
        conn.close()


def test_find_markdown_refs_for_request_returns_tombstoned(tmp_path: Path):
    """Historical query stays valid even after the file is removed."""
    songs_root = tmp_path / "songs"
    songs_root.mkdir()
    conn = init_db(tmp_path / "test.db")
    try:
        sid = M.create_song(conn, name="tunesong", key="Dm")
        deco = tmp_path / "songs/tunesong/decisions/2026-05-19-x.md"
        deco.parent.mkdir(parents=True)
        deco.write_text(
            "---\nkind: decision\nscope: song\ndate: 2026-05-19\n---\nbody\n",
            encoding="utf-8",
        )
        reindex_corpus(conn, songs_root=songs_root, repo_root=tmp_path)
        with M.request(conn, actor="llm", intent="x", kind="compose",
                       song_id=sid) as rid:
            M.record_markdown_ref(
                conn,
                path=str(deco.relative_to(tmp_path)),
                content_hash="abc",
                song_id=sid,
                request_id=rid,
            )

        # File vanishes → tombstoned
        deco.unlink()
        reindex_corpus(conn, songs_root=songs_root, repo_root=tmp_path)

        # Cross-reference still works
        rows = Q.find_markdown_refs_for_request(conn, rid)
        assert len(rows) == 1
        assert rows[0]["tombstoned_at"] is not None
    finally:
        conn.close()
