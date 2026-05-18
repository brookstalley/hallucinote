"""Tests for tools/migrate_returns_strip_prefix.py.

W4-C: one-shot migration to strip Live's `<slot-letter>-` prefix from
existing DBs created before the cross-layer fix.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from hallucinote.db import init_db, mutations as M, queries as Q

_ROOT = Path(__file__).resolve().parents[3]
_MIGRATE_PATH = _ROOT / "tools" / "migrate_returns_strip_prefix.py"


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "migrate_returns_strip_prefix", _MIGRATE_PATH,
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "song.db"


def test_migration_strips_a_through_z_prefix(db_path):
    """Every return whose name matches `^[A-Z]-` is stripped; others are
    untouched. The mutation count equals the number actually stripped."""
    conn = init_db(db_path)
    sid = M.create_song(conn, name="t", key="Dm")
    M.create_return(conn, song_id=sid, name="A-Reverb", position=1)
    M.create_return(conn, song_id=sid, name="B-Delay", position=2)
    M.create_return(conn, song_id=sid, name="Stereo Bus", position=3)  # no prefix
    conn.commit()
    conn.close()

    mod = _load_module()
    counts = mod.migrate(db_path)
    assert counts["rows_examined"] == 3
    assert counts["rows_stripped"] == 2

    conn = init_db(db_path)
    rows = sorted(
        (r["name"] for r in Q.get_returns_for_song(conn, sid)),
        key=str,
    )
    assert rows == ["Delay", "Reverb", "Stereo Bus"]
    conn.close()


def test_migration_is_idempotent(db_path):
    """Re-running on an already-stripped DB is a no-op."""
    conn = init_db(db_path)
    sid = M.create_song(conn, name="t", key="Dm")
    M.create_return(conn, song_id=sid, name="A-Reverb", position=1)
    conn.commit()
    conn.close()

    mod = _load_module()
    first = mod.migrate(db_path)
    assert first["rows_stripped"] == 1
    second = mod.migrate(db_path)
    assert second["rows_stripped"] == 0
    assert second["rows_examined"] == 1


def test_migration_strips_only_one_prefix(db_path):
    """`A-B-Comp` → `B-Comp` (one strip), not `Comp` (recursive)."""
    conn = init_db(db_path)
    sid = M.create_song(conn, name="t", key="Dm")
    M.create_return(conn, song_id=sid, name="A-B-Comp", position=1)
    conn.commit()
    conn.close()

    mod = _load_module()
    mod.migrate(db_path)
    conn = init_db(db_path)
    rows = Q.get_returns_for_song(conn, sid)
    assert rows[0]["name"] == "B-Comp"
    conn.close()


def test_migration_leaves_non_slot_prefixes_alone(db_path):
    """`Ghost-Reverb` (multi-letter first segment), `a-mine` (lowercase),
    `Bus` (no hyphen) — all pass through unchanged."""
    conn = init_db(db_path)
    sid = M.create_song(conn, name="t", key="Dm")
    M.create_return(conn, song_id=sid, name="Ghost-Reverb", position=1)
    M.create_return(conn, song_id=sid, name="a-mine",       position=2)
    M.create_return(conn, song_id=sid, name="Bus",          position=3)
    conn.commit()
    conn.close()

    mod = _load_module()
    counts = mod.migrate(db_path)
    assert counts["rows_stripped"] == 0
    conn = init_db(db_path)
    names = sorted(r["name"] for r in Q.get_returns_for_song(conn, sid))
    assert names == ["Bus", "Ghost-Reverb", "a-mine"]
    conn.close()
