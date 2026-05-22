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
