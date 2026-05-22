"""Shape test for sun-zone-done's build.py.

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
    spec = importlib.util.spec_from_file_location("sun_zone_done_build", BUILD_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "DB_PATH", tmp_path / "sun-zone-done.db")
    return module


def test_build_runs_clean_and_produces_shape(build_module):
    """Running build(--reset) populates the scaffold's structure."""
    from hallucinote.db import init_db, queries as Q

    song_id = build_module.build(reset=True)
    assert song_id

    conn = init_db(build_module.DB_PATH)
    try:
        # Sections — scaffold-defined; tighten as the song matures.
        sections = Q.get_sections_for_song(conn, song_id)
        section_names = [s["name"] for s in sections]
        assert section_names == ['intro', 'verse1', 'chorus1', 'verse2', 'chorus2', 'bridge', 'chorus3', 'outro']

        # Tracks — 4 from synthetic snapshot + master.
        tracks = Q.get_tracks_for_song(conn, song_id)
        assert len(tracks) >= 5  # 4 + master, more once you author

        # Tempo + time signature points exist.
        tempo = Q.get_tempo_map(conn, song_id)
        assert len(tempo) >= 1
        assert tempo[0]["tempo_bpm"] == 180.0

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


def test_build_authors_amp_type_enum_envelope(build_module):
    """E1 empirical driver: the Amp Type envelope is the song's reason for
    existing. Lock the shape — Clean ↔ Heavy across all 8 sections."""
    from hallucinote.db import init_db

    build_module.build(reset=True)
    conn = init_db(build_module.DB_PATH)
    try:
        envs = conn.execute(
            """SELECT id, parameter_path FROM envelopes
               WHERE target_kind = 'device_parameter'
                 AND parameter_path = 'Amp Type'"""
        ).fetchall()
        assert len(envs) == 1, "expected exactly one Amp Type envelope"
        bps = conn.execute(
            """SELECT time_beats, value, curve_kind
                 FROM automation_breakpoints
                WHERE envelope_id = ?
                ORDER BY time_beats""",
            (envs[0]["id"],),
        ).fetchall()
        # All values resolved to Clean (0.0) or Heavy (3.0).
        assert {r["value"] for r in bps} == {0.0, 3.0}, (
            f"unexpected enum values: {sorted({r['value'] for r in bps})}"
        )
        # All step-shaped (enum envelopes can't ramp).
        assert {r["curve_kind"] for r in bps} == {"hold"}
        # 28 breakpoints (build.py's section schedule) — locked exact-shape.
        assert len(bps) == 28
    finally:
        conn.close()
