"""Unit tests for the hoisted song-build plumbing — the bookkeeping every song's
build.py used to duplicate (`generator-altitude-policy.md`: rulers belong shared).

  - `Q.tracks_by_name` / `Q.returns_by_name` (db.queries) — name->id maps
  - `arrange_section` / `run_build` (hallucinote.authoring)
"""
from __future__ import annotations

from hallucinote.authoring import arrange_section, run_build
from hallucinote.db import init_db, mutations as M, queries as Q


def _db(tmp_path):
    return init_db(str(tmp_path / "t.db"))


def test_tracks_by_name_maps_name_to_id(tmp_path):
    conn = _db(tmp_path)
    try:
        song_id = M.create_song(conn, name="t", title="t", key="Em")
        a = M.create_track(conn, song_id=song_id, track_index=1, name="01 Drums")
        b = M.create_track(conn, song_id=song_id, track_index=2, name="02 Bass")
        assert Q.tracks_by_name(conn, song_id) == {"01 Drums": a, "02 Bass": b}
    finally:
        conn.close()


def test_returns_by_name_maps_name_to_id(tmp_path):
    conn = _db(tmp_path)
    try:
        song_id = M.create_song(conn, name="t", title="t", key="Em")
        r = M.create_return(conn, song_id=song_id, name="Plate", position=1)
        assert Q.returns_by_name(conn, song_id) == {"Plate": r}
    finally:
        conn.close()


def test_arrange_section_places_each_clip_on_its_track(tmp_path):
    conn = _db(tmp_path)
    try:
        song_id = M.create_song(conn, name="t", title="t", key="Em")
        d = M.create_track(conn, song_id=song_id, track_index=1, name="01 Drums")
        bss = M.create_track(conn, song_id=song_id, track_index=2, name="02 Bass")
        dc = M.create_clip(conn, track_id=d, slot=1, length_beats=16.0)
        bc = M.create_clip(conn, track_id=bss, slot=1, length_beats=16.0)
        tracks = Q.tracks_by_name(conn, song_id)
        arrange_section(conn, song_id, tracks, {"01 Drums": dc, "02 Bass": bc},
                        start_bar=1.0, end_bar=5.0)
        placed = {p["track_id"]: p for p in Q.get_arrangement_for_song(conn, song_id)}
        assert placed[d]["clip_id"] == dc and placed[d]["start_bar"] == 1.0
        assert placed[bss]["clip_id"] == bc and placed[bss]["end_bar"] == 5.0
    finally:
        conn.close()


def test_run_build_runs_compose_in_a_session_and_returns_song_id(tmp_path):
    db = str(tmp_path / "t.db")
    calls = []

    def compose(conn):
        calls.append("composed")
        song_id = M.create_song(conn, name="t", title="t", key="Em")
        M.create_track(conn, song_id=song_id, track_index=1, name="01 Drums")
        return song_id

    song_id = run_build(db, "t", compose)
    assert calls == ["composed"]
    conn = init_db(db)
    try:
        assert Q.get_song_by_name(conn, "t")["id"] == song_id
        assert [t["name"] for t in Q.get_tracks_for_song(conn, song_id)] == ["01 Drums"]
    finally:
        conn.close()


def test_run_build_reset_is_a_clean_converging_re_run(tmp_path):
    db = str(tmp_path / "t.db")

    def compose(conn):
        song_id = M.create_song(conn, name="t", title="t", key="Em")
        M.create_track(conn, song_id=song_id, track_index=1, name="01 Drums")
        return song_id

    first = run_build(db, "t", compose)
    second = run_build(db, "t", compose, reset=True)  # soft-reset then rebuild
    assert first == second  # same song row (the converger contract)
    conn = init_db(db)
    try:
        assert [t["name"] for t in Q.get_tracks_for_song(conn, second)] == ["01 Drums"]
    finally:
        conn.close()
