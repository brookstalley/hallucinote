"""set_chain_properties — per-DrumChain choke_group / out_note (NODE-ADDR Chunk C).

The DB-storage half of per-drum authorship: a partial, idempotent, change-detecting
update that rides DEVICE_CHAIN_PROPS_SET (symmetric with set_track_routing, not
create). Mirrors the clear-on-None contract — None clears a property to the Live
default, which is how the pull diff lands a now-default value.
"""
from __future__ import annotations

import json

import pytest

from hallucinote.db import init_db, mutations as M, queries as Q
from hallucinote.db import events as E


@pytest.fixture
def conn(tmp_path):
    c = init_db(tmp_path / "test.db")
    yield c
    c.close()


@pytest.fixture
def song(conn):
    return M.create_song(conn, name="t", key="Dm")


@pytest.fixture
def drum_chain(conn, song):
    """A nested rack chain (a drum-rack pad's chain) hung off a rack device."""
    track = M.create_track(conn, song_id=song, track_index=1, name="Drums")
    top_chain = M.create_device_chain(conn, parent_track_id=track, position=0)
    rack = M.create_device(
        conn, chain_id=top_chain, position=1,
        kind="Drum Rack", display_name="Drum Rack",
    )
    return M.create_device_chain(conn, parent_rack_device_id=rack, position=1)


def _props_events(conn):
    return conn.execute(
        "SELECT payload_json, actor FROM events "
        "WHERE kind = ? ORDER BY seq", (E.DEVICE_CHAIN_PROPS_SET,),
    ).fetchall()


def test_set_choke_group_persists_and_emits(conn, drum_chain):
    res = M.set_chain_properties(conn, chain_id=drum_chain, choke_group=3)
    assert res.kind == "updated"
    row = Q.get_device_chain(conn, drum_chain)
    assert row["choke_group"] == 3 and row["out_note"] is None
    events = _props_events(conn)
    assert len(events) == 1
    assert json.loads(events[0]["payload_json"]) == {
        "chain_id": drum_chain, "changes": {"choke_group": 3},
    }


def test_set_both_props_at_once(conn, drum_chain):
    M.set_chain_properties(conn, chain_id=drum_chain, choke_group=2, out_note=60)
    row = Q.get_device_chain(conn, drum_chain)
    assert row["choke_group"] == 2 and row["out_note"] == 60


def test_partial_update_leaves_unpassed_field(conn, drum_chain):
    M.set_chain_properties(conn, chain_id=drum_chain, choke_group=1, out_note=48)
    # out_note not passed -> untouched; choke_group changes.
    M.set_chain_properties(conn, chain_id=drum_chain, choke_group=5)
    row = Q.get_device_chain(conn, drum_chain)
    assert row["choke_group"] == 5 and row["out_note"] == 48


def test_none_clears_to_default(conn, drum_chain):
    M.set_chain_properties(conn, chain_id=drum_chain, choke_group=4, out_note=72)
    res = M.set_chain_properties(conn, chain_id=drum_chain, choke_group=None)
    assert res.kind == "updated"
    row = Q.get_device_chain(conn, drum_chain)
    assert row["choke_group"] is None and row["out_note"] == 72


def test_idempotent_no_event_when_unchanged(conn, drum_chain):
    M.set_chain_properties(conn, chain_id=drum_chain, choke_group=3)
    res = M.set_chain_properties(conn, chain_id=drum_chain, choke_group=3)
    assert res.kind == "unchanged"
    assert len(_props_events(conn)) == 1  # only the first write emitted


def test_no_fields_passed_is_a_noop(conn, drum_chain):
    res = M.set_chain_properties(conn, chain_id=drum_chain)
    assert res.kind == "unchanged"
    assert _props_events(conn) == []


def test_missing_chain_raises(conn):
    with pytest.raises(ValueError, match="no device_chains row"):
        M.set_chain_properties(conn, chain_id="nope", choke_group=1)


@pytest.mark.parametrize("bad", [-1, 1.5, True, "3"])
def test_choke_group_validation(conn, drum_chain, bad):
    with pytest.raises(ValueError, match="choke_group"):
        M.set_chain_properties(conn, chain_id=drum_chain, choke_group=bad)


@pytest.mark.parametrize("bad", [-1, 128, 1.5, True, "60"])
def test_out_note_validation(conn, drum_chain, bad):
    with pytest.raises(ValueError, match="out_note"):
        M.set_chain_properties(conn, chain_id=drum_chain, out_note=bad)


def test_props_set_protects_chain_from_tombstoning(conn, drum_chain):
    """A non-build actor touching a chain's props flips its latest actor, so the
    tombstone pass won't reclaim it — mirrors track_routing_set on a track."""
    from hallucinote.db.mutations.build import _latest_actor_for

    M.set_chain_properties(
        conn, chain_id=drum_chain, choke_group=1, actor="llm",
    )
    assert _latest_actor_for(conn, row_kind="device_chain", row_id=drum_chain) \
        == "llm"
