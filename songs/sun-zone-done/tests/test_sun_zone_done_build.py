"""Shape tests for the sun-zone-done v2 rebuild.

Validates the rebuild's structural intent:
  - 5 instrument tracks + master + 3 returns
  - 7 sections (intro / verse1 / chorus1 / verse2 / chorus2 / bridge / outro)
  - Rhythm Gtr is MONOLITHIC: 1 session clip spanning the whole song
    (the Amp Type envelope's clip-coverage requirement is the structural
    reason — see build.py docstring)
  - Other instrument tracks are per-section
  - Organ drops out in metal sections (4 clips, not 7)
  - Exactly 1 envelope (target=device_parameter on Amp Type), 5 breakpoints
    at section boundaries (Clean ↔ Heavy)
  - 7 cue points (one per section start)
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


_SONG_DIR = Path(__file__).resolve().parent.parent
_BUILD_PATH = _SONG_DIR / "build.py"


@pytest.fixture(scope="module")
def build_module(tmp_path_factory):
    """Import build.py with DB_PATH redirected to a temp path so xdist
    parallel workers don't share state with each other (or with hand-runs
    of `python build.py`)."""
    spec = importlib.util.spec_from_file_location(
        "sun_zone_done_build", _BUILD_PATH,
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.DB_PATH = tmp_path_factory.mktemp("sun_zone_done") / "test.db"
    return mod


@pytest.fixture(scope="module")
def built(build_module):
    """Run a clean --reset build and return the song_id."""
    return build_module.build(reset=True)


def test_build_produces_canonical_shape(build_module, built):
    from hallucinote.db import init_db, queries as Q
    conn = init_db(build_module.DB_PATH)
    try:
        song_id = built
        # Tracks: 5 instrument + 1 master = 6
        tracks = Q.get_tracks_for_song(conn, song_id)
        track_names = sorted(t["name"] for t in tracks)
        assert track_names == sorted([
            "01 Drums", "02 Bass", "03 Rhythm Gtr", "04 Organ", "05 Lead",
            "Master",
        ]), track_names

        # Returns: 3, named Plate / Room / DubDelay (stored stripped)
        returns = Q.get_returns_for_song(conn, song_id)
        return_names = sorted(r["name"] for r in returns)
        assert return_names == ["DubDelay", "Plate", "Room"], return_names

        # Sections: 7
        sections = Q.get_sections_for_song(conn, song_id)
        assert len(sections) == 7, [s["name"] for s in sections]

        # Per-track clip counts
        clip_counts: dict[str, int] = {}
        for t in tracks:
            if t["name"] == "Master":
                continue
            clip_counts[t["name"]] = len(Q.get_clips_for_track(conn, t["id"]))
        # Per-section tracks have 7 clips each (one per section)
        assert clip_counts["01 Drums"] == 7
        assert clip_counts["02 Bass"] == 7
        assert clip_counts["05 Lead"] == 7
        # Rhythm gtr is monolithic — exactly 1 clip
        assert clip_counts["03 Rhythm Gtr"] == 1
        # Organ drops out in metal — 4 clips (intro / verse1 / verse2 / outro)
        assert clip_counts["04 Organ"] == 4

        # Envelopes: exactly 1, device_parameter on Amp Type, 5 breakpoints
        envs = Q.get_envelopes_for_song(conn, song_id)
        assert len(envs) == 1
        env = envs[0]
        assert env["target_kind"] == "device_parameter"
        assert env["parameter_path"] == "Amp Type"
        bps = Q.get_breakpoints(conn, env["id"])
        assert len(bps) == 5
        # Breakpoints alternate Clean (0.0) and Heavy (5.0) per the genre
        # alternation. Section starts: intro=0, chorus1=64, verse2=96,
        # chorus2=128, outro=224. Bridge follows chorus2 in same value, so
        # no breakpoint at the bridge boundary (160).
        bp_pairs = [(bp["time_beats"], bp["value"]) for bp in bps]
        assert bp_pairs == [
            (0.0,   0.0),   # intro: Clean
            (64.0,  5.0),   # chorus1: Heavy
            (96.0,  0.0),   # verse2: Clean
            (128.0, 5.0),   # chorus2: Heavy (carries through bridge)
            (224.0, 0.0),   # outro: Clean
        ], bp_pairs

        # Arrangement: 26 placements (7 drums + 7 bass + 1 gtr + 4 organ + 7 lead)
        arr = Q.get_arrangement_for_song(conn, song_id)
        assert len(arr) == 26, [(a["start_bar"], a["end_bar"]) for a in arr]

        # Cue points: 7
        cues = Q.get_cue_points(conn, song_id)
        assert len(cues) == 7
        cue_positions = sorted(c["position_bar"] for c in cues)
        assert cue_positions == [1.0, 9.0, 17.0, 25.0, 33.0, 41.0, 57.0]
    finally:
        conn.close()


def test_rhythm_gtr_clip_spans_full_song(build_module, built):
    """The structural fix for the Amp envelope: rhythm gtr is ONE clip
    256 beats long (64 bars × 4), hosting the section-boundary envelope.
    """
    from hallucinote.db import init_db, queries as Q
    conn = init_db(build_module.DB_PATH)
    try:
        tracks = Q.get_tracks_for_song(conn, built)
        gtr = next(t for t in tracks if t["name"] == "03 Rhythm Gtr")
        clips = Q.get_clips_for_track(conn, gtr["id"])
        assert len(clips) == 1
        assert clips[0]["length_beats"] == 256.0
    finally:
        conn.close()


def test_build_is_idempotent_state_converger(build_module):
    """W12-A: re-running the build over an existing DB produces zero net
    state-change events. Validates the load-bearing state-converger promise
    on the real sun-zone-done build (not a synthetic one)."""
    from hallucinote.db import init_db

    # First build.
    song_id = build_module.build(reset=True)
    conn = init_db(build_module.DB_PATH)
    try:
        state_events_first = [
            r["kind"] for r in conn.execute(
                "SELECT kind FROM events "
                "WHERE kind NOT IN ('request_created', 'request_closed') "
                "ORDER BY seq"
            ).fetchall()
        ]
        n_state_first = len(state_events_first)
    finally:
        conn.close()

    # Second build — no reset, expect zero new state-change events.
    song_id_2 = build_module.build(reset=False)
    assert song_id_2 == song_id  # same song row

    conn = init_db(build_module.DB_PATH)
    try:
        state_events_after = [
            r["kind"] for r in conn.execute(
                "SELECT kind FROM events "
                "WHERE kind NOT IN ('request_created', 'request_closed') "
                "ORDER BY seq"
            ).fetchall()
        ]
        assert len(state_events_after) == n_state_first, (
            f"Re-running build produced {len(state_events_after) - n_state_first} "
            f"extra state-change events — converger discipline broken."
        )
    finally:
        conn.close()


def test_metal_lead_uses_phrygian_b2(build_module, built):
    """The metal chorus melody includes F (E Phrygian's b2) — the
    harmonic trademark of the genre flip. This guards against accidentally
    sliding into Dorian on the metal side."""
    from hallucinote.db import init_db, queries as Q
    conn = init_db(build_module.DB_PATH)
    try:
        tracks = Q.get_tracks_for_song(conn, built)
        lead = next(t for t in tracks if t["name"] == "05 Lead")
        clips = sorted(Q.get_clips_for_track(conn, lead["id"]),
                       key=lambda c: c["slot"])
        # Chorus1 is slot 3 (section index 2)
        chorus1 = clips[2]
        assert chorus1["section_role"] == "chorus1"
        notes = Q.get_notes_for_clip(conn, chorus1["id"])
        pitches = {n["pitch"] for n in notes}
        # F4 (65) is the Phrygian b2 in the metal lead melody
        assert 65 in pitches, sorted(pitches)
    finally:
        conn.close()
