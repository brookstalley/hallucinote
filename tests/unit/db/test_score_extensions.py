"""Tests for chunk-2 score-half schema: sections, tempo_map, time_signature_map,
cue_points, and songs.timing_mode."""
from __future__ import annotations

import json
import sqlite3

import pytest

from hallucinote.db import init_db, mutations as M, queries as Q
from hallucinote.db import events as E


@pytest.fixture
def conn(tmp_path):
    c = init_db(tmp_path / "score.db")
    yield c
    c.close()


@pytest.fixture
def song(conn):
    return M.create_song(conn, name="t", key="Dm")


def _events(conn) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT kind, payload_json, actor, song_id FROM events ORDER BY seq"
    ).fetchall()


# ---------- timing_mode ----------


def test_create_song_defaults_to_native_timing_mode(conn):
    sid = M.create_song(conn, name="x")
    row = conn.execute("SELECT timing_mode FROM songs WHERE id=?", (sid,)).fetchone()
    assert row["timing_mode"] == "native"


def test_create_song_accepts_grid_timing_mode(conn):
    sid = M.create_song(conn, name="x", timing_mode="grid")
    row = conn.execute("SELECT timing_mode FROM songs WHERE id=?", (sid,)).fetchone()
    assert row["timing_mode"] == "grid"
    payload = json.loads(
        conn.execute("SELECT payload_json FROM events WHERE song_id=?", (sid,))
        .fetchone()["payload_json"]
    )
    assert payload["timing_mode"] == "grid"


def test_create_song_rejects_invalid_timing_mode(conn):
    with pytest.raises(ValueError, match="invalid timing_mode"):
        M.create_song(conn, name="x", timing_mode="polytempic")


def test_set_song_timing_mode_emits_event(conn, song):
    M.set_song_timing_mode(conn, song_id=song, timing_mode="grid")
    row = conn.execute("SELECT timing_mode FROM songs WHERE id=?", (song,)).fetchone()
    assert row["timing_mode"] == "grid"
    last = _events(conn)[-1]
    assert last["kind"] == E.SONG_TIMING_MODE_SET
    assert json.loads(last["payload_json"])["timing_mode"] == "grid"


def test_set_song_timing_mode_rejects_invalid(conn, song):
    with pytest.raises(ValueError, match="invalid timing_mode"):
        M.set_song_timing_mode(conn, song_id=song, timing_mode="weird")


def test_songs_tempo_and_time_signature_columns_removed(conn):
    cols = {r[1] for r in conn.execute("PRAGMA table_info(songs)").fetchall()}
    assert "tempo" not in cols
    assert "time_signature" not in cols
    assert "timing_mode" in cols


# ---------- sections ----------


def test_create_section_emits_event_and_returns_uuid(conn, song):
    sid = M.create_section(
        conn,
        song_id=song,
        name="verse",
        start_bar=1.0,
        end_bar=17.0,
        color=0x4080FF,
        notes_md="four chord progression",
    )
    assert isinstance(sid, str) and len(sid) == 32
    rows = Q.get_sections_for_song(conn, song)
    assert len(rows) == 1
    assert rows[0]["name"] == "verse"
    assert rows[0]["color"] == 0x4080FF
    assert rows[0]["notes_md"] == "four chord progression"
    last = _events(conn)[-1]
    assert last["kind"] == E.SECTION_CREATED
    payload = json.loads(last["payload_json"])
    assert payload["section_id"] == sid
    assert payload["start_bar"] == 1.0 and payload["end_bar"] == 17.0


def test_create_section_rejects_inverted_span(conn, song):
    with pytest.raises(ValueError, match="must exceed start_bar"):
        M.create_section(conn, song_id=song, name="bad", start_bar=8.0, end_bar=4.0)


def test_update_section_changes_fields_and_emits_event(conn, song):
    sid = M.create_section(conn, song_id=song, name="verse", start_bar=1.0, end_bar=9.0)
    M.update_section(conn, section_id=sid, end_bar=17.0, name="long-verse")
    row = Q.get_sections_for_song(conn, song)[0]
    assert row["end_bar"] == 17.0 and row["name"] == "long-verse"
    last = _events(conn)[-1]
    assert last["kind"] == E.SECTION_UPDATED
    payload = json.loads(last["payload_json"])
    assert payload["changes"] == {"end_bar": 17.0, "name": "long-verse"}


def test_update_section_rejects_inverted_resulting_span(conn, song):
    sid = M.create_section(conn, song_id=song, name="v", start_bar=1.0, end_bar=9.0)
    with pytest.raises(ValueError, match="must exceed start_bar"):
        M.update_section(conn, section_id=sid, start_bar=10.0)


def test_update_section_rejects_unknown_field(conn, song):
    sid = M.create_section(conn, song_id=song, name="v", start_bar=1.0, end_bar=9.0)
    with pytest.raises(ValueError, match="unsupported fields"):
        M.update_section(conn, section_id=sid, bogus=1)


def test_delete_section_emits_event(conn, song):
    sid = M.create_section(conn, song_id=song, name="v", start_bar=1.0, end_bar=9.0)
    M.delete_section(conn, section_id=sid)
    assert Q.get_sections_for_song(conn, song) == []
    last = _events(conn)[-1]
    assert last["kind"] == E.SECTION_DELETED


def test_section_delete_cascades_with_song(conn, song):
    M.create_section(conn, song_id=song, name="v", start_bar=1.0, end_bar=9.0)
    conn.execute("DELETE FROM songs WHERE id=?", (song,))
    assert (
        conn.execute("SELECT COUNT(*) FROM sections WHERE song_id=?", (song,))
        .fetchone()[0]
        == 0
    )


# ---------- tempo_map ----------


def test_add_tempo_point_emits_event(conn, song):
    pid = M.add_tempo_point(conn, song_id=song, start_bar=1.0, tempo_bpm=132.0)
    rows = Q.get_tempo_map(conn, song)
    assert len(rows) == 1 and rows[0]["tempo_bpm"] == 132.0 and rows[0]["ramp"] == "hold"
    last = _events(conn)[-1]
    assert last["kind"] == E.TEMPO_POINT_ADDED
    assert json.loads(last["payload_json"])["point_id"] == pid


def test_add_tempo_point_accepts_linear_ramp(conn, song):
    M.add_tempo_point(conn, song_id=song, start_bar=1.0, tempo_bpm=132.0)
    M.add_tempo_point(conn, song_id=song, start_bar=17.0, tempo_bpm=80.0, ramp="linear")
    rows = Q.get_tempo_map(conn, song)
    assert [r["start_bar"] for r in rows] == [1.0, 17.0]
    assert rows[1]["ramp"] == "linear"


def test_add_tempo_point_rejects_invalid_ramp(conn, song):
    with pytest.raises(ValueError, match="invalid ramp"):
        M.add_tempo_point(conn, song_id=song, start_bar=1.0, tempo_bpm=132.0, ramp="curve")


def test_add_tempo_point_rejects_nonpositive_bpm(conn, song):
    with pytest.raises(ValueError, match="positive"):
        M.add_tempo_point(conn, song_id=song, start_bar=1.0, tempo_bpm=0.0)


def test_tempo_map_unique_per_bar(conn, song):
    M.add_tempo_point(conn, song_id=song, start_bar=1.0, tempo_bpm=132.0)
    with pytest.raises(sqlite3.IntegrityError):
        M.add_tempo_point(conn, song_id=song, start_bar=1.0, tempo_bpm=100.0)


def test_remove_tempo_point_emits_event(conn, song):
    pid = M.add_tempo_point(conn, song_id=song, start_bar=1.0, tempo_bpm=132.0)
    M.remove_tempo_point(conn, point_id=pid)
    assert Q.get_tempo_map(conn, song) == []
    last = _events(conn)[-1]
    assert last["kind"] == E.TEMPO_POINT_REMOVED


# ---------- time_signature_map ----------


def test_add_time_signature_point_emits_event(conn, song):
    pid = M.add_time_signature_point(
        conn, song_id=song, start_bar=1.0, numerator=4, denominator=4
    )
    rows = Q.get_time_signature_map(conn, song)
    assert len(rows) == 1 and rows[0]["numerator"] == 4 and rows[0]["denominator"] == 4
    last = _events(conn)[-1]
    assert last["kind"] == E.TIME_SIGNATURE_POINT_ADDED
    assert json.loads(last["payload_json"])["point_id"] == pid


def test_add_time_signature_point_supports_compound_meter(conn, song):
    M.add_time_signature_point(
        conn, song_id=song, start_bar=1.0, numerator=6, denominator=8
    )
    row = Q.get_time_signature_map(conn, song)[0]
    assert (row["numerator"], row["denominator"]) == (6, 8)


def test_add_time_signature_point_rejects_nonpositive(conn, song):
    with pytest.raises(ValueError, match="positive"):
        M.add_time_signature_point(
            conn, song_id=song, start_bar=1.0, numerator=0, denominator=4
        )


def test_remove_time_signature_point_emits_event(conn, song):
    pid = M.add_time_signature_point(
        conn, song_id=song, start_bar=1.0, numerator=4, denominator=4
    )
    M.remove_time_signature_point(conn, point_id=pid)
    assert Q.get_time_signature_map(conn, song) == []
    last = _events(conn)[-1]
    assert last["kind"] == E.TIME_SIGNATURE_POINT_REMOVED


# ---------- cue_points ----------


def test_add_cue_point_emits_event(conn, song):
    pid = M.add_cue_point(
        conn, song_id=song, position_bar=8.0, name="chorus start", color=0xFF8000
    )
    rows = Q.get_cue_points(conn, song)
    assert len(rows) == 1 and rows[0]["name"] == "chorus start"
    last = _events(conn)[-1]
    assert last["kind"] == E.CUE_POINT_ADDED
    assert json.loads(last["payload_json"])["cue_id"] == pid


def test_cue_points_returned_in_order(conn, song):
    M.add_cue_point(conn, song_id=song, position_bar=16.0, name="b")
    M.add_cue_point(conn, song_id=song, position_bar=1.0, name="a")
    M.add_cue_point(conn, song_id=song, position_bar=8.0, name="middle")
    names = [r["name"] for r in Q.get_cue_points(conn, song)]
    assert names == ["a", "middle", "b"]


def test_remove_cue_point_emits_event(conn, song):
    pid = M.add_cue_point(conn, song_id=song, position_bar=1.0, name="start")
    M.remove_cue_point(conn, cue_id=pid)
    assert Q.get_cue_points(conn, song) == []
    last = _events(conn)[-1]
    assert last["kind"] == E.CUE_POINT_REMOVED


# ---------- cascade ----------


def test_score_tables_cascade_with_song(conn):
    sid = M.create_song(conn, name="cascading")
    M.create_section(conn, song_id=sid, name="v", start_bar=1.0, end_bar=9.0)
    M.add_tempo_point(conn, song_id=sid, start_bar=1.0, tempo_bpm=120.0)
    M.add_time_signature_point(
        conn, song_id=sid, start_bar=1.0, numerator=4, denominator=4
    )
    M.add_cue_point(conn, song_id=sid, position_bar=1.0, name="x")
    conn.execute("DELETE FROM songs WHERE id=?", (sid,))
    for table in ("sections", "tempo_map", "time_signature_map", "cue_points"):
        cnt = conn.execute(
            f"SELECT COUNT(*) FROM {table} WHERE song_id=?", (sid,)
        ).fetchone()[0]
        assert cnt == 0, f"{table} did not cascade"
