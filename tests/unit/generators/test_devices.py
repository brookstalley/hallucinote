"""Tests for chunk-4a device schema: device_chains, devices, device_parameters."""
from __future__ import annotations

import sqlite3

import pytest

from hallucinote.db import init_db, mutations as M, queries as Q
from hallucinote.db import events as E


@pytest.fixture
def conn(tmp_path):
    c = init_db(tmp_path / "dev.db")
    yield c
    c.close()


@pytest.fixture
def song(conn):
    return M.create_song(conn, name="t", key="Dm")


@pytest.fixture
def track(conn, song):
    return M.create_track(conn, song_id=song, track_index=1, name="Drums")


@pytest.fixture
def ret(conn, song):
    return M.create_return(conn, song_id=song, name="A-Reverb", position=1)


def _events(conn) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT kind, payload_json, actor, song_id FROM events ORDER BY seq"
    ).fetchall()


# ---------- device_chains ----------


def test_create_chain_on_track(conn, song, track):
    cid = M.create_device_chain(conn, parent_track_id=track)
    row = conn.execute("SELECT * FROM device_chains WHERE id=?", (cid,)).fetchone()
    assert row["parent_track_id"] == track
    assert row["parent_return_id"] is None
    assert row["parent_rack_device_id"] is None
    assert row["position"] == 0


def test_create_chain_on_return(conn, song, ret):
    cid = M.create_device_chain(conn, parent_return_id=ret)
    row = conn.execute("SELECT parent_return_id FROM device_chains WHERE id=?", (cid,)).fetchone()
    assert row["parent_return_id"] == ret


def test_create_chain_requires_exactly_one_parent(conn, song, track, ret):
    with pytest.raises(ValueError, match="exactly one parent kwarg"):
        M.create_device_chain(conn)
    with pytest.raises(ValueError, match="exactly one parent kwarg"):
        M.create_device_chain(conn, parent_track_id=track, parent_return_id=ret)


def test_check_constraint_rejects_orphan_chain(conn):
    """The schema CHECK is the last-line defense if a raw insert bypasses the mutator."""
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        conn.execute("INSERT INTO device_chains (id, position) VALUES (?, 0)", ("x",))


def test_check_constraint_rejects_double_parent(conn, song, track, ret):
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        conn.execute(
            """INSERT INTO device_chains
                   (id, parent_track_id, parent_return_id, position)
               VALUES (?, ?, ?, 0)""",
            ("x", track, ret),
        )


def test_chain_emits_event_with_song_id(conn, song, track):
    M.create_device_chain(conn, parent_track_id=track)
    evs = [e for e in _events(conn) if e["kind"] == E.DEVICE_CHAIN_CREATED]
    assert len(evs) == 1
    assert evs[0]["song_id"] == song


def test_delete_chain_cascades_devices(conn, song, track):
    cid = M.create_device_chain(conn, parent_track_id=track)
    did = M.create_device(conn, chain_id=cid, position=1, kind="Eq8", display_name="EQ Eight")
    M.delete_device_chain(conn, chain_id=cid)
    assert conn.execute("SELECT COUNT(*) FROM devices WHERE id=?", (did,)).fetchone()[0] == 0


def test_delete_track_cascades_chains_devices_params(conn, song, track):
    cid = M.create_device_chain(conn, parent_track_id=track)
    did = M.create_device(conn, chain_id=cid, position=1, kind="Compressor2", display_name="Comp")
    M.set_device_parameter(conn, device_id=did, name="Threshold",
                           value_display="-20 dB", value_normalized=0.5)
    conn.execute("DELETE FROM tracks WHERE id=?", (track,))
    assert conn.execute("SELECT COUNT(*) FROM device_chains WHERE parent_track_id=?", (track,)).fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM devices WHERE chain_id=?", (cid,)).fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM device_parameters WHERE device_id=?", (did,)).fetchone()[0] == 0


# ---------- devices ----------


def test_create_device_basic(conn, song, track):
    cid = M.create_device_chain(conn, parent_track_id=track)
    did = M.create_device(
        conn, chain_id=cid, position=1, kind="Operator", display_name="Sub Bass",
        preset_uri="query:Synths#Operator",
    )
    row = Q.get_device(conn, did)
    assert row["kind"] == "Operator"
    assert row["display_name"] == "Sub Bass"
    assert row["position"] == 1
    assert row["preset_uri"] == "query:Synths#Operator"


def test_device_position_must_be_positive(conn, song, track):
    cid = M.create_device_chain(conn, parent_track_id=track)
    with pytest.raises(ValueError, match="position 0 must be >= 1"):
        M.create_device(conn, chain_id=cid, position=0, kind="Eq8", display_name="EQ")


def test_device_upserts_per_chain_position(conn, song, track):
    """W12-A: re-creating at the same position upserts (not raises). Different
    kind/display_name → updated; identical args → unchanged."""
    cid = M.create_device_chain(conn, parent_track_id=track)
    d1 = M.create_device(conn, chain_id=cid, position=1, kind="Eq8", display_name="EQ")
    assert d1.kind == "created"
    d2 = M.create_device(conn, chain_id=cid, position=1, kind="Reverb", display_name="Rev")
    assert d2.kind == "updated"
    assert d2 == d1
    d3 = M.create_device(conn, chain_id=cid, position=1, kind="Reverb", display_name="Rev")
    assert d3.kind == "unchanged"
    assert d3 == d1


def test_create_device_with_preset_query_stores_json(conn, song, track):
    """Sweep B: preset_query is stored as JSON-serialized string in the DB."""
    cid = M.create_device_chain(conn, parent_track_id=track)
    did = M.create_device(
        conn, chain_id=cid, position=1, kind="Drum Rack",
        display_name="Some Kit",
        preset_query={"root": "drums", "pattern": "909", "mode": "substring"},
    )
    row = Q.get_device(conn, did)
    assert row["preset_uri"] is None
    assert row["preset_query"] is not None
    import json
    parsed = json.loads(row["preset_query"])
    assert parsed == {"root": "drums", "pattern": "909", "mode": "substring"}


def test_create_device_refuses_both_preset_uri_and_preset_query(conn, song, track):
    """Strict — mutually exclusive selectors."""
    cid = M.create_device_chain(conn, parent_track_id=track)
    with pytest.raises(ValueError, match="mutually exclusive"):
        M.create_device(
            conn, chain_id=cid, position=1, kind="Drum Rack",
            display_name="X",
            preset_uri="query:Drums#FileId_1",
            preset_query={"root": "drums", "pattern": "x"},
        )


def test_create_device_preset_query_idempotent_unchanged(conn, song, track):
    """Idempotent re-create with the same preset_query is 'unchanged'."""
    cid = M.create_device_chain(conn, parent_track_id=track)
    q = {"root": "drums", "pattern": "909"}
    d1 = M.create_device(
        conn, chain_id=cid, position=1, kind="Drum Rack",
        display_name="K", preset_query=q,
    )
    d2 = M.create_device(
        conn, chain_id=cid, position=1, kind="Drum Rack",
        display_name="K", preset_query=q,
    )
    assert d2.kind == "unchanged"


def test_delete_device_emits_event(conn, song, track):
    cid = M.create_device_chain(conn, parent_track_id=track)
    did = M.create_device(conn, chain_id=cid, position=1, kind="Eq8", display_name="EQ")
    M.delete_device(conn, device_id=did)
    kinds = [e["kind"] for e in _events(conn)]
    assert E.DEVICE_DELETED in kinds


def test_delete_device_noop_for_missing(conn, song):
    M.delete_device(conn, device_id="does-not-exist")
    assert not any(e["kind"] == E.DEVICE_DELETED for e in _events(conn))


# ---------- device_parameters ----------


def test_set_device_parameter_creates(conn, song, track):
    cid = M.create_device_chain(conn, parent_track_id=track)
    did = M.create_device(conn, chain_id=cid, position=1, kind="Operator", display_name="Op")
    pid = M.set_device_parameter(
        conn, device_id=did, name="Volume",
        value_display="-18 dB", value_normalized=0.4,
    )
    rows = Q.get_device_parameters(conn, did)
    assert len(rows) == 1
    assert rows[0]["id"] == pid
    assert rows[0]["name"] == "Volume"
    assert rows[0]["value_display"] == "-18 dB"
    assert rows[0]["value_normalized"] == 0.4


def test_set_device_parameter_upserts(conn, song, track):
    cid = M.create_device_chain(conn, parent_track_id=track)
    did = M.create_device(conn, chain_id=cid, position=1, kind="Operator", display_name="Op")
    pid1 = M.set_device_parameter(conn, device_id=did, name="Volume",
                                   value_display="-18 dB", value_normalized=0.4)
    pid2 = M.set_device_parameter(conn, device_id=did, name="Volume",
                                   value_display="-12 dB", value_normalized=0.5)
    assert pid1 == pid2  # same row, updated in place
    rows = Q.get_device_parameters(conn, did)
    assert len(rows) == 1
    assert rows[0]["value_display"] == "-12 dB"
    assert rows[0]["value_normalized"] == 0.5


def test_set_device_parameter_accepts_null_normalized(conn, song, track):
    """Discrete-enum params (e.g., Filter Type = 'Lowpass') have no continuous form."""
    cid = M.create_device_chain(conn, parent_track_id=track)
    did = M.create_device(conn, chain_id=cid, position=1, kind="Operator", display_name="Op")
    M.set_device_parameter(
        conn, device_id=did, name="Filter Type", value_display="Lowpass",
    )
    rows = Q.get_device_parameters(conn, did)
    assert rows[0]["value_normalized"] is None


def test_set_device_parameter_rejects_out_of_range(conn, song, track):
    cid = M.create_device_chain(conn, parent_track_id=track)
    did = M.create_device(conn, chain_id=cid, position=1, kind="Operator", display_name="Op")
    with pytest.raises(ValueError, match="out of range"):
        M.set_device_parameter(conn, device_id=did, name="V",
                               value_display="200%", value_normalized=2.0)


def test_remove_device_parameter(conn, song, track):
    cid = M.create_device_chain(conn, parent_track_id=track)
    did = M.create_device(conn, chain_id=cid, position=1, kind="Op", display_name="Op")
    M.set_device_parameter(conn, device_id=did, name="V",
                           value_display="0 dB", value_normalized=0.7)
    M.remove_device_parameter(conn, device_id=did, name="V")
    assert Q.get_device_parameters(conn, did) == []
    kinds = [e["kind"] for e in _events(conn)]
    assert E.DEVICE_PARAMETER_REMOVED in kinds


def test_remove_missing_parameter_emits_no_event(conn, song, track):
    cid = M.create_device_chain(conn, parent_track_id=track)
    did = M.create_device(conn, chain_id=cid, position=1, kind="Op", display_name="Op")
    M.remove_device_parameter(conn, device_id=did, name="nonexistent")
    assert not any(e["kind"] == E.DEVICE_PARAMETER_REMOVED for e in _events(conn))


# ---------- nested rack chains ----------


def test_rack_device_can_carry_nested_chain(conn, song, track):
    """A rack device (e.g., DrumGroupDevice) owns nested chains."""
    top_chain = M.create_device_chain(conn, parent_track_id=track)
    rack_id = M.create_device(
        conn, chain_id=top_chain, position=1,
        kind="Drum Rack", display_name="Late Nite Kit",
    )
    inner_chain = M.create_device_chain(
        conn, parent_rack_device_id=rack_id, position=1,
    )
    inner_device = M.create_device(
        conn, chain_id=inner_chain, position=1,
        kind="Simpler", display_name="Kick",
    )
    # Deleting the rack device cascades to the nested chain AND its devices.
    M.delete_device(conn, device_id=rack_id)
    assert Q.get_device(conn, inner_device) is None
    assert conn.execute(
        "SELECT COUNT(*) FROM device_chains WHERE id=?", (inner_chain,)
    ).fetchone()[0] == 0


def test_nested_chain_event_carries_song_id(conn, song, track):
    """Event provenance must walk nested-rack parents up to song."""
    top_chain = M.create_device_chain(conn, parent_track_id=track)
    rack_id = M.create_device(
        conn, chain_id=top_chain, position=1,
        kind="Instrument Rack", display_name="Rack",
    )
    M.create_device_chain(conn, parent_rack_device_id=rack_id, position=1)
    chain_events = [e for e in _events(conn) if e["kind"] == E.DEVICE_CHAIN_CREATED]
    assert len(chain_events) == 2
    assert all(e["song_id"] == song for e in chain_events)


# ---------- queries ----------


def test_query_chains_per_parent(conn, song, track, ret):
    ct = M.create_device_chain(conn, parent_track_id=track)
    cr = M.create_device_chain(conn, parent_return_id=ret)
    assert [c["id"] for c in Q.get_device_chains_for_track(conn, track)] == [ct]
    assert [c["id"] for c in Q.get_device_chains_for_return(conn, ret)] == [cr]


def test_query_devices_for_track_orders_by_chain_then_position(conn, song, track):
    cid = M.create_device_chain(conn, parent_track_id=track)
    d2 = M.create_device(conn, chain_id=cid, position=2, kind="Eq8", display_name="EQ")
    d1 = M.create_device(conn, chain_id=cid, position=1, kind="Operator", display_name="Op")
    rows = Q.get_devices_for_track(conn, track)
    assert [r["id"] for r in rows] == [d1, d2]


def test_query_chains_for_rack_device(conn, song, track):
    top = M.create_device_chain(conn, parent_track_id=track)
    rack = M.create_device(conn, chain_id=top, position=1,
                           kind="Drum Rack", display_name="Kit")
    inner = M.create_device_chain(conn, parent_rack_device_id=rack, position=1)
    rows = Q.get_device_chains_for_rack_device(conn, rack)
    assert [r["id"] for r in rows] == [inner]
