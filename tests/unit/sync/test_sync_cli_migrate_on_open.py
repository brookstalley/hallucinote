"""Regression: the sync CLIs migrate an older on-disk DB to the current schema
when they open it, instead of reading it raw and crashing.

Background. A song DB built by an earlier release is missing the columns later
schema bumps added (here: the RTE-1K9T track-routing columns). The push/pull
planners read those columns off a ``SELECT *`` row; a column that isn't in the
result set makes ``sqlite3.Row`` raise ``IndexError: No item with that key``.
The additive-column migration that exists precisely to bring old DBs forward
(``_ensure_added_columns``) only runs inside ``init_db`` — so the fix routes the
sync CLIs' DB-open through ``init_db`` (via ``_open_db``) rather than bare
``connect()``. ``run_build`` already opens every existing song this way.

These tests build a *legacy* DB by hand (a ``tracks`` table predating the seven
routing columns), confirm the un-migrated raw open still reproduces the original
crash, then assert ``_open_db`` migrates the schema so the routing planner runs
clean.
"""
from __future__ import annotations

import argparse
import sqlite3

import pytest

from hallucinote.db.connection import connect
from hallucinote.sync import compat, pull_cli, push_cli
from hallucinote.sync.push._core import PushPlan
from hallucinote.sync.push.routing import plan_push_routing


# The seven columns RTE-1K9T added to ``tracks`` — absent on a pre-0.9.5 DB, and
# what the routing planner reads. Migrating on open must restore all of them.
_ROUTING_COLUMNS = (
    "output_routing_kind",
    "output_routing_target_id",
    "output_routing_channel",
    "input_routing_kind",
    "input_routing_target_id",
    "input_routing_channel",
    "monitoring_state",
)


def _make_legacy_db(path) -> str:
    """Write a DB with a ``tracks`` shape that predates the routing columns.

    Built with the stdlib driver directly (not ``init_db``) so the routing
    columns are genuinely absent — the real shape of a song authored before the
    schema bump. Returns the song id.
    """
    raw = sqlite3.connect(str(path))
    raw.executescript(
        """
        CREATE TABLE songs (
            id   TEXT PRIMARY KEY,
            name TEXT,
            key  TEXT
        );
        CREATE TABLE tracks (
            id          TEXT PRIMARY KEY,
            song_id     TEXT REFERENCES songs(id),
            name        TEXT,
            track_index INTEGER,
            kind        TEXT
        );
        INSERT INTO songs (id, name, key) VALUES ('song1', 't', 'Dm');
        INSERT INTO tracks (id, song_id, name, track_index, kind)
            VALUES ('trk1', 'song1', 'Bass', 1, 'midi');
        """
    )
    raw.commit()
    raw.close()
    return "song1"


def _track_columns(conn: sqlite3.Connection) -> set[str]:
    return {r["name"] for r in conn.execute("PRAGMA table_info(tracks)").fetchall()}


def _ns(db_path) -> argparse.Namespace:
    """The minimal arg surface ``_resolve_db_path`` reads: ``--db`` wins, so
    ``song`` is irrelevant here."""
    return argparse.Namespace(db=str(db_path), song=None)


def test_legacy_db_lacks_routing_columns(tmp_path):
    """Sanity: the hand-built legacy DB really is missing the routing columns —
    otherwise the migration assertions below would pass vacuously."""
    db_path = tmp_path / "legacy.db"
    _make_legacy_db(db_path)
    raw = connect(db_path)
    try:
        assert _ROUTING_COLUMNS[0] not in _track_columns(raw)
    finally:
        raw.close()


def test_raw_open_reproduces_routing_planner_crash(tmp_path):
    """The pre-fix behavior: opening the legacy DB raw (bare ``connect``) and
    running the routing planner raises ``IndexError`` on the missing column.
    This is the exact failure the fix targets."""
    db_path = tmp_path / "legacy.db"
    song_id = _make_legacy_db(db_path)
    raw = connect(db_path)
    try:
        with pytest.raises(IndexError):
            plan_push_routing(raw, song_id=song_id, session_id="s1")
    finally:
        raw.close()


@pytest.mark.parametrize("open_db", [push_cli._open_db, pull_cli._open_db])
def test_open_db_migrates_routing_columns(tmp_path, open_db):
    """Both sync CLIs open via ``init_db``, so a legacy DB gains every routing
    column the current schema declares — the migration runs on open."""
    db_path = tmp_path / "legacy.db"
    _make_legacy_db(db_path)
    conn = open_db(_ns(db_path))
    try:
        cols = _track_columns(conn)
        missing = [c for c in _ROUTING_COLUMNS if c not in cols]
        assert not missing, f"routing columns not migrated in: {missing}"
    finally:
        conn.close()


def _make_legacy_song_db(path) -> str:
    """A legacy DB whose ``songs`` row carries ``title`` (so ``check_song`` can
    build its report) but whose ``tracks`` still predate the routing columns.
    No tracks/devices — ``check_song`` then walks nothing and reports clean; the
    point is that it opens via ``init_db`` and migrates the schema first."""
    raw = sqlite3.connect(str(path))
    raw.executescript(
        """
        CREATE TABLE songs (
            id    TEXT PRIMARY KEY,
            name  TEXT,
            title TEXT,
            key   TEXT
        );
        CREATE TABLE tracks (
            id          TEXT PRIMARY KEY,
            song_id     TEXT REFERENCES songs(id),
            name        TEXT,
            track_index INTEGER,
            kind        TEXT
        );
        INSERT INTO songs (id, name, title, key)
            VALUES ('song1', 'swell', 'Swell', 'Dm');
        """
    )
    raw.commit()
    raw.close()
    return "song1"


def test_compat_check_song_migrates_legacy_db(tmp_path):
    """``compat.check_song`` reads post-0.9.0 device columns, so it must also open
    through ``init_db``. Running it against a legacy DB migrates the schema on
    open (routing columns appear) and returns a report instead of crashing."""
    db_path = tmp_path / "legacy.db"
    _make_legacy_song_db(db_path)
    report = compat.check_song(db_path)
    assert report is not None
    after = connect(db_path)
    try:
        assert "output_routing_kind" in _track_columns(after)
    finally:
        after.close()


def test_push_cli_open_unblocks_routing_planner(tmp_path):
    """End-to-end of the fix: opening the legacy DB through ``push_cli._open_db``
    lets the routing planner that previously crashed run clean and return a
    ``PushPlan`` (the track carries no routing, so the plan is empty — the point
    is that the column reads no longer raise)."""
    db_path = tmp_path / "legacy.db"
    song_id = _make_legacy_db(db_path)
    conn = push_cli._open_db(_ns(db_path))
    try:
        plan = plan_push_routing(conn, song_id=song_id, session_id="s1")
        assert isinstance(plan, PushPlan)
    finally:
        conn.close()
