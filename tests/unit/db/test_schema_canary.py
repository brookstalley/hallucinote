"""Tests for the schema-vs-_ADDED_COLUMNS consistency canary.

Convention: every additive column gets two declarations — one in
``schema.sql`` (fresh DB CREATE TABLE) and one in ``_ADDED_COLUMNS``
(the ALTER pass for existing DBs). The canary verifies the schema.sql
side hasn't drifted; missing entries there would be papered over by
the ALTER pass on fresh DBs, hiding the bug.

Most recent drift: ``devices.browser_path_json`` (Arc 7-tail / E3,
2026-05-22).
"""
from __future__ import annotations

import sqlite3

import pytest

from hallucinote.db import connection as conn_mod
from hallucinote.db import init_db


@pytest.fixture(autouse=True)
def _reset_canary_flag():
    """Reset the once-per-process flag so each test exercises the check."""
    original = conn_mod._SCHEMA_CANARY_CHECKED
    conn_mod._SCHEMA_CANARY_CHECKED = False
    yield
    conn_mod._SCHEMA_CANARY_CHECKED = original


def test_canary_passes_on_current_schema(tmp_path):
    """The current schema.sql declares every _ADDED_COLUMNS column.
    Round-trip: init_db succeeds without raising and the canary flag
    flips to True.
    """
    conn = init_db(tmp_path / "ok.db")
    try:
        assert conn_mod._SCHEMA_CANARY_CHECKED is True
    finally:
        conn.close()


def test_canary_raises_when_added_columns_declares_a_missing_column(
    tmp_path, monkeypatch,
):
    """If _ADDED_COLUMNS declares a column that schema.sql's CREATE TABLE
    doesn't include, the canary names the missing (table, col) pair and
    refuses to proceed. The drift case the canary was built to catch.
    """
    phantom = ("devices", "phantom_column", "TEXT")
    monkeypatch.setattr(
        conn_mod, "_ADDED_COLUMNS",
        conn_mod._ADDED_COLUMNS + (phantom,),
    )
    with pytest.raises(RuntimeError) as exc:
        init_db(tmp_path / "drifted.db")
    msg = str(exc.value)
    assert "devices.phantom_column" in msg
    assert "schema.sql" in msg


def _make_pre_energy_db(db_path) -> None:
    """Build a full schema DB but with the ARR-7M3D ``sections.energy`` column
    stripped from the CREATE TABLE — the exact shape of a DB built before the
    column was added. Built from the real ``schema.sql`` (minus the one column
    line + its trailing comment block) so every OTHER ``_ADDED_COLUMNS`` table
    is present, matching what ``_ensure_added_columns`` walks.
    """
    schema = conn_mod._SCHEMA_PATH.read_text()
    # Drop only the energy column declaration line (and its leading comment
    # block) so the rest of the sections CREATE TABLE — and every other table —
    # is byte-identical to today's schema.
    lines = schema.splitlines(keepends=True)
    kept = []
    skip_comment = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("-- Authored per-section energy"):
            skip_comment = True
            continue
        if skip_comment:
            # The energy comment block ends at the energy column line itself.
            if stripped.startswith("energy"):
                skip_comment = False
                continue
            continue
        kept.append(line)
    pre_schema = "".join(kept)
    assert "energy" not in pre_schema, "energy column not fully stripped"
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(pre_schema)
        conn.commit()
    finally:
        conn.close()


def test_added_column_migration_lands_once_on_pre_column_db(tmp_path):
    """ARR-7M3D's ``sections.energy`` ALTER lands exactly once on a pre-column
    DB and is a no-op on re-open. Exercises ``_ensure_added_columns`` directly
    (it's the idempotent ALTER pass) against a full schema that predates the
    energy column — the migration the dual-declaration convention requires.
    """
    db_path = tmp_path / "pre_column.db"
    _make_pre_energy_db(db_path)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        # Pre-migration: no energy column.
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(sections)")}
        assert "energy" not in cols

        # First migration: ALTER lands.
        conn_mod._ensure_added_columns(conn)
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(sections)")}
        assert "energy" in cols

        # Re-open / re-run: no-op (no duplicate-column error, column still there).
        conn_mod._ensure_added_columns(conn)
        cols2 = {r["name"] for r in conn.execute("PRAGMA table_info(sections)")}
        assert cols2 == cols

        # The migrated column accepts NULL and rejects out-of-range energy
        # (the CHECK rode the ALTER definition).
        conn.execute("INSERT INTO songs (id, name) VALUES ('s1', 'migrated-song')")
        conn.execute(
            "INSERT INTO sections (id, song_id, name, start_bar, end_bar, energy) "
            "VALUES ('x', 's1', 'v', 1.0, 9.0, NULL)"
        )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO sections (id, song_id, name, start_bar, end_bar, energy) "
                "VALUES ('y', 's1', 'c', 1.0, 9.0, 2.0)"
            )
    finally:
        conn.close()


def test_canary_runs_once_per_process(tmp_path, monkeypatch):
    """The canary caches its result via a module-level flag so it runs
    once per process regardless of how many DBs init_db opens. After the
    first init_db, _SCHEMA_CANARY_CHECKED is True; a second init_db with
    drifted _ADDED_COLUMNS would normally raise, but the flag short-
    circuits the check — proving the cache works.
    """
    conn = init_db(tmp_path / "first.db")
    conn.close()
    assert conn_mod._SCHEMA_CANARY_CHECKED is True
    # Now drift _ADDED_COLUMNS; the second init_db skips the canary check.
    phantom = ("devices", "phantom_column", "TEXT")
    monkeypatch.setattr(
        conn_mod, "_ADDED_COLUMNS",
        conn_mod._ADDED_COLUMNS + (phantom,),
    )
    conn = init_db(tmp_path / "second.db")
    conn.close()
