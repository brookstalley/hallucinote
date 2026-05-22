"""Tests for chunk-3 mix-half schema: tracks.kind + mixer state, returns, sends."""
from __future__ import annotations

import json
import sqlite3

import pytest

from hallucinote.db import init_db, mutations as M, queries as Q
from hallucinote.db import events as E


@pytest.fixture
def conn(tmp_path):
    c = init_db(tmp_path / "mix.db")
    yield c
    c.close()


@pytest.fixture
def song(conn):
    return M.create_song(conn, name="t", key="Dm")


def _events(conn) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT kind, payload_json, actor, song_id FROM events ORDER BY seq"
    ).fetchall()


# ---------- tracks.kind ----------


def test_create_track_defaults_to_midi_kind(conn, song):
    tid = M.create_track(conn, song_id=song, track_index=1, name="Drums")
    row = conn.execute("SELECT kind FROM tracks WHERE id=?", (tid,)).fetchone()
    assert row["kind"] == "midi"


def test_create_track_accepts_all_valid_kinds(conn, song):
    for i, kind in enumerate(("midi", "audio", "master", "group"), start=1):
        M.create_track(conn, song_id=song, track_index=i, name=f"t{i}", kind=kind)
    kinds = {r["kind"] for r in conn.execute("SELECT kind FROM tracks").fetchall()}
    assert kinds == {"midi", "audio", "master", "group"}


def test_create_track_rejects_invalid_kind(conn, song):
    with pytest.raises(ValueError, match="invalid kind"):
        M.create_track(conn, song_id=song, track_index=1, name="x", kind="aux")


def test_create_track_event_records_kind(conn, song):
    M.create_track(conn, song_id=song, track_index=1, name="Master", kind="master")
    last = _events(conn)[-1]
    assert last["kind"] == E.TRACK_CREATED
    assert json.loads(last["payload_json"])["kind"] == "master"


# ---------- set_track_mixer ----------


def test_set_track_mixer_partial_update(conn, song):
    tid = M.create_track(conn, song_id=song, track_index=1, name="Drums")
    M.set_track_mixer(conn, track_id=tid, volume=0.6, pan=-0.25)
    row = conn.execute(
        "SELECT volume, pan, mute, solo, arm FROM tracks WHERE id=?", (tid,)
    ).fetchone()
    assert row["volume"] == pytest.approx(0.6)
    assert row["pan"] == pytest.approx(-0.25)
    assert row["mute"] is None
    assert row["solo"] is None
    assert row["arm"] is None


def test_set_track_mixer_emits_event_with_changes_only(conn, song):
    tid = M.create_track(conn, song_id=song, track_index=1, name="Drums")
    M.set_track_mixer(conn, track_id=tid, mute=1)
    last = _events(conn)[-1]
    assert last["kind"] == E.TRACK_MIXER_SET
    assert json.loads(last["payload_json"])["changes"] == {"mute": 1}


def test_set_track_mixer_rejects_unknown_field(conn, song):
    tid = M.create_track(conn, song_id=song, track_index=1, name="x")
    with pytest.raises(ValueError, match="unsupported fields"):
        M.set_track_mixer(conn, track_id=tid, gain=10)


def test_set_track_mixer_volume_check_constraint(conn, song):
    tid = M.create_track(conn, song_id=song, track_index=1, name="x")
    with pytest.raises(sqlite3.IntegrityError):
        M.set_track_mixer(conn, track_id=tid, volume=1.5)


def test_set_track_mixer_pan_check_constraint(conn, song):
    tid = M.create_track(conn, song_id=song, track_index=1, name="x")
    with pytest.raises(sqlite3.IntegrityError):
        M.set_track_mixer(conn, track_id=tid, pan=2.0)


def test_set_track_mixer_noop_when_changes_empty(conn, song):
    tid = M.create_track(conn, song_id=song, track_index=1, name="x")
    before = len(_events(conn))
    M.set_track_mixer(conn, track_id=tid)
    assert len(_events(conn)) == before


# ---------- returns ----------


def test_create_return_emits_event_and_returns_uuid(conn, song):
    rid = M.create_return(
        conn, song_id=song, name="A-Reverb", position=1, volume=0.85, color=0xFF00FF
    )
    assert isinstance(rid, str) and len(rid) == 32
    rows = Q.get_returns_for_song(conn, song)
    assert len(rows) == 1
    # Arc 7 / P7: M.create_return strips Live's `<letter>-` slot prefix
    # at the mutator boundary — DB stores SUFFIX-only names (W4-C).
    assert rows[0]["name"] == "Reverb"
    assert rows[0]["position"] == 1
    last = _events(conn)[-1]
    assert last["kind"] == E.RETURN_CREATED
    assert json.loads(last["payload_json"])["return_id"] == rid


def test_update_return_partial(conn, song):
    rid = M.create_return(conn, song_id=song, name="A", position=1)
    M.update_return(conn, return_id=rid, volume=0.9, name="A-Reverb")
    row = Q.get_return(conn, rid)
    # Arc 7 / P7: M.update_return strips the slot prefix from `name`
    # (mirrors create_return) — DB stores SUFFIX-only names (W4-C).
    assert row["name"] == "Reverb"
    assert row["volume"] == pytest.approx(0.9)


def test_update_return_rejects_unknown_field(conn, song):
    rid = M.create_return(conn, song_id=song, name="A", position=1)
    with pytest.raises(ValueError, match="unsupported fields"):
        M.update_return(conn, return_id=rid, gain=1.0)


def test_delete_return_cascades_sends(conn, song):
    tid = M.create_track(conn, song_id=song, track_index=1, name="Drums")
    rid = M.create_return(conn, song_id=song, name="A", position=1)
    M.set_send_level(conn, from_track_id=tid, to_return_id=rid, level=0.4)
    assert Q.get_sends_for_song(conn, song)
    M.delete_return(conn, return_id=rid)
    assert not Q.get_returns_for_song(conn, song)
    assert not Q.get_sends_for_song(conn, song)


def test_returns_upsert_per_position(conn, song):
    """W12-A: re-adding at the same position upserts (not raises). Different
    name → updated; same args → unchanged."""
    r1 = M.create_return(conn, song_id=song, name="A", position=1)
    assert r1.kind == "created"
    r2 = M.create_return(conn, song_id=song, name="B", position=1)
    assert r2.kind == "updated"
    assert r2 == r1
    r3 = M.create_return(conn, song_id=song, name="B", position=1)
    assert r3.kind == "unchanged"
    assert r3 == r1


def test_returns_volume_check_constraint(conn, song):
    with pytest.raises(sqlite3.IntegrityError):
        M.create_return(conn, song_id=song, name="A", position=1, volume=1.2)


# ---------- sends ----------


def test_set_send_level_upserts(conn, song):
    tid = M.create_track(conn, song_id=song, track_index=1, name="Drums")
    rid = M.create_return(conn, song_id=song, name="A-Reverb", position=1)
    M.set_send_level(conn, from_track_id=tid, to_return_id=rid, level=0.3)
    M.set_send_level(conn, from_track_id=tid, to_return_id=rid, level=0.6)
    sends = Q.get_sends_for_track(conn, tid)
    assert len(sends) == 1
    assert sends[0]["level"] == pytest.approx(0.6)


def test_set_send_level_emits_event_per_call(conn, song):
    tid = M.create_track(conn, song_id=song, track_index=1, name="Drums")
    rid = M.create_return(conn, song_id=song, name="A", position=1)
    before = len([e for e in _events(conn) if e["kind"] == E.SEND_SET])
    M.set_send_level(conn, from_track_id=tid, to_return_id=rid, level=0.3)
    M.set_send_level(conn, from_track_id=tid, to_return_id=rid, level=0.6)
    after = len([e for e in _events(conn) if e["kind"] == E.SEND_SET])
    assert after - before == 2


def test_set_send_level_range_check(conn, song):
    tid = M.create_track(conn, song_id=song, track_index=1, name="Drums")
    rid = M.create_return(conn, song_id=song, name="A", position=1)
    with pytest.raises(ValueError, match="out of range"):
        M.set_send_level(conn, from_track_id=tid, to_return_id=rid, level=1.5)


def test_set_send_level_cross_song_rejected(conn):
    s1 = M.create_song(conn, name="s1")
    s2 = M.create_song(conn, name="s2")
    tid = M.create_track(conn, song_id=s1, track_index=1, name="x")
    rid = M.create_return(conn, song_id=s2, name="A", position=1)
    with pytest.raises(ValueError, match="cross-song send"):
        M.set_send_level(conn, from_track_id=tid, to_return_id=rid, level=0.5)


def test_remove_send_emits_event_when_present(conn, song):
    tid = M.create_track(conn, song_id=song, track_index=1, name="Drums")
    rid = M.create_return(conn, song_id=song, name="A", position=1)
    M.set_send_level(conn, from_track_id=tid, to_return_id=rid, level=0.4)
    M.remove_send(conn, from_track_id=tid, to_return_id=rid)
    assert not Q.get_sends_for_track(conn, tid)
    kinds = [e["kind"] for e in _events(conn)]
    assert kinds[-1] == E.SEND_REMOVED


def test_remove_send_silent_when_missing(conn, song):
    tid = M.create_track(conn, song_id=song, track_index=1, name="Drums")
    rid = M.create_return(conn, song_id=song, name="A", position=1)
    before = len(_events(conn))
    M.remove_send(conn, from_track_id=tid, to_return_id=rid)
    assert len(_events(conn)) == before


def test_get_sends_for_song_returns_matrix(conn, song):
    t1 = M.create_track(conn, song_id=song, track_index=1, name="Drums")
    t2 = M.create_track(conn, song_id=song, track_index=2, name="Pad")
    r1 = M.create_return(conn, song_id=song, name="A-Reverb", position=1)
    r2 = M.create_return(conn, song_id=song, name="B-Delay", position=2)
    M.set_send_level(conn, from_track_id=t1, to_return_id=r1, level=0.2)
    M.set_send_level(conn, from_track_id=t1, to_return_id=r2, level=0.0)
    M.set_send_level(conn, from_track_id=t2, to_return_id=r1, level=0.4)
    rows = Q.get_sends_for_song(conn, song)
    assert len(rows) == 3
    # Sorted by track_index then return position. Arc 7 / P7: return
    # names are stripped at the mutator boundary, so "A-Reverb" /
    # "B-Delay" land as "Reverb" / "Delay" in the DB.
    assert (rows[0]["from_track_name"], rows[0]["return_name"]) == ("Drums", "Reverb")
    assert (rows[1]["from_track_name"], rows[1]["return_name"]) == ("Drums", "Delay")
    assert (rows[2]["from_track_name"], rows[2]["return_name"]) == ("Pad", "Reverb")
