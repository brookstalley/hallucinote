"""Shape test for missing's build.py.

W12-A: build.py is a state-converger — re-running with no source changes
produces zero net state-change events. `test_build_is_idempotent_state_converger`
locks that promise; shape assertions lock what the build minimally produces.

Filename convention: per-song test names MUST be unique across all songs
(see pyproject.toml). Use `test_<slug>_build.py`, not bare `test_build.py`.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SONG_ROOT = Path(__file__).resolve().parents[1]
BUILD_PATH = SONG_ROOT / "build.py"


@pytest.fixture
def build_module(tmp_path, monkeypatch):
    """Import build.py with DB_PATH redirected to a temp file."""
    spec = importlib.util.spec_from_file_location("missing_build", BUILD_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "DB_PATH", tmp_path / "missing.db")
    return module


def test_build_runs_clean_and_produces_shape(build_module):
    """Running build(--reset) populates the scaffold's structure."""
    from hallucinote.db import init_db, queries as Q

    song_id = build_module.build(reset=True)
    assert song_id

    conn = init_db(build_module.DB_PATH)
    try:
        # Sections — locked bar map (decisions/11-bar-map.md), ~4:48 @ 100 BPM.
        # verse3 is deliberately half-length (8 bars) — the "disabuse" drop.
        sections = Q.get_sections_for_song(conn, song_id)
        section_names = [s["name"] for s in sections]
        assert section_names == ['intro', 'verse1', 'chorus1', 'verse2', 'chorus2', 'break', 'verse3', 'finalchorus', 'coda']

        section_bars = [(s["name"], s["start_bar"], s["end_bar"]) for s in sections]
        assert section_bars == [
            ('intro',         1.0,   9.0),   # 8 bars
            ('verse1',        9.0,  25.0),   # 16
            ('chorus1',      25.0,  41.0),   # 16
            ('verse2',       41.0,  57.0),   # 16
            ('chorus2',      57.0,  73.0),   # 16
            ('break',        73.0,  89.0),   # 16
            ('verse3',       89.0,  97.0),   # 8  (half-length — the disabuse)
            ('finalchorus',  97.0, 113.0),   # 16
            ('coda',        113.0, 129.0),   # 16
        ]

        # Tracks — 4 from synthetic snapshot + master.
        tracks = Q.get_tracks_for_song(conn, song_id)
        assert len(tracks) >= 5  # 4 + master, more once you author

        # Tempo + time signature points exist.
        tempo = Q.get_tempo_map(conn, song_id)
        assert len(tempo) >= 1
        assert tempo[0]["tempo_bpm"] == 100.0

        sig = Q.get_time_signature_map(conn, song_id)
        assert len(sig) >= 1
        assert (sig[0]["numerator"], sig[0]["denominator"]) == (4, 4)
    finally:
        conn.close()


def test_build_is_idempotent_state_converger(build_module):
    """W12-A: re-running the build over an existing DB produces zero net
    state-change events. The load-bearing converger promise."""
    from hallucinote.db import init_db

    song_id = build_module.build(reset=True)
    conn = init_db(build_module.DB_PATH)
    try:
        state_events_first = len([
            r["kind"] for r in conn.execute(
                "SELECT kind FROM events "
                "WHERE kind NOT IN ('request_created', 'request_closed') "
                "ORDER BY seq"
            ).fetchall()
        ])
    finally:
        conn.close()

    # Second build — no reset, expect zero new state-change events.
    song_id_2 = build_module.build(reset=False)
    assert song_id_2 == song_id

    conn = init_db(build_module.DB_PATH)
    try:
        state_events_after = len([
            r["kind"] for r in conn.execute(
                "SELECT kind FROM events "
                "WHERE kind NOT IN ('request_created', 'request_closed') "
                "ORDER BY seq"
            ).fetchall()
        ])
        assert state_events_after == state_events_first, (
            f"Re-running build produced {state_events_after - state_events_first} "
            f"extra state-change events — converger discipline broken."
        )
    finally:
        conn.close()
