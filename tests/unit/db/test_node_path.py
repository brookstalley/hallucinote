"""NODE-ADDR (design §1a) — the DB-side address inverse: `get_node_path`
(device id → positional NodeAddr) and `render_node_addr` (device id → human
string). Both walk UP the nested-rack hierarchy with no Live round-trips.

The fixture builds one song with the full terminal spread — a track (with a
depth-2 nested rack), a return, and the master — so the parent classification
and the path/render walk are exercised across every parent kind and depth.
"""
from __future__ import annotations

import pytest

from hallucinote.db import init_db
from hallucinote.db import mutations as M
from hallucinote.db import queries as Q


@pytest.fixture
def song(tmp_path):
    """A song with:
      track 2 "Guitar"  ▸ "EQ Eight" (top)              [d_eq]
                        ▸ "Guitar-Dual Amped Heavy" (rack)
                            ▸ chain 1 ▸ "Tube Saturator" (depth-1)   [d_sat]
                                      ▸ "Inner Rack" (rack)
                                          ▸ chain 1 ▸ "Deep EQ" (depth-2) [d_deep]
      return 1 "Reverb" ▸ "Hybrid Reverb"               [d_rev]
      master            ▸ "Limiter"                      [d_lim]
    """
    conn = init_db(tmp_path / "song.db")
    song_id = M.create_song(conn, name="node-path-fixture")

    guitar = M.create_track(
        conn, song_id=song_id, track_index=2, name="Guitar", kind="midi"
    )
    top_chain = M.create_device_chain(conn, parent_track_id=guitar, position=0)
    d_eq = M.create_device(
        conn, chain_id=top_chain, position=1, kind="EQ Eight",
        display_name="EQ Eight",
    )
    rack = M.create_device(
        conn, chain_id=top_chain, position=2, kind="AudioEffectGroupDevice",
        display_name="Guitar-Dual Amped Heavy",
    )
    rack_chain = M.create_device_chain(conn, parent_rack_device_id=rack, position=1)
    d_sat = M.create_device(
        conn, chain_id=rack_chain, position=1, kind="Saturator",
        display_name="Tube Saturator",
    )
    inner = M.create_device(
        conn, chain_id=rack_chain, position=2, kind="AudioEffectGroupDevice",
        display_name="Inner Rack",
    )
    inner_chain = M.create_device_chain(conn, parent_rack_device_id=inner, position=1)
    d_deep = M.create_device(
        conn, chain_id=inner_chain, position=1, kind="EQ Eight",
        display_name="Deep EQ",
    )

    reverb = M.create_return(conn, song_id=song_id, name="Reverb", position=1)
    rev_chain = M.create_device_chain(conn, parent_return_id=reverb, position=0)
    d_rev = M.create_device(
        conn, chain_id=rev_chain, position=1, kind="Hybrid Reverb",
        display_name="Hybrid Reverb",
    )

    # Master's track_index is deliberately a non-1 sentinel: the address must
    # IGNORE it (master is a singleton terminal with no index).
    master = M.create_track(
        conn, song_id=song_id, track_index=99, name="Master", kind="master"
    )
    m_chain = M.create_device_chain(conn, parent_track_id=master, position=0)
    d_lim = M.create_device(
        conn, chain_id=m_chain, position=1, kind="Limiter", display_name="Limiter",
    )

    ids = dict(
        d_eq=d_eq, rack=rack, d_sat=d_sat, inner=inner, d_deep=d_deep,
        d_rev=d_rev, d_lim=d_lim,
    )
    yield conn, ids
    conn.close()


# ---------------------------------------------------------------------------
# get_node_path — device id → positional NodeAddr
# ---------------------------------------------------------------------------


def test_get_node_path_top_level_track_device(song):
    conn, ids = song
    assert Q.get_node_path(conn, ids["d_eq"]) == {
        "parent": {"kind": "track", "index": 2},
        "terminal": "device",
        "device_index": 1,
    }


def test_get_node_path_depth_1_nested(song):
    conn, ids = song
    assert Q.get_node_path(conn, ids["d_sat"]) == {
        "parent": {"kind": "track", "index": 2},
        "terminal": "device",
        "device_index": 2,
        "path": [{"chain_index": 1, "device_position": 1}],
    }


def test_get_node_path_depth_2_nested(song):
    conn, ids = song
    assert Q.get_node_path(conn, ids["d_deep"]) == {
        "parent": {"kind": "track", "index": 2},
        "terminal": "device",
        "device_index": 2,
        "path": [
            {"chain_index": 1, "device_position": 2},
            {"chain_index": 1, "device_position": 1},
        ],
    }


def test_get_node_path_return_device(song):
    conn, ids = song
    assert Q.get_node_path(conn, ids["d_rev"]) == {
        "parent": {"kind": "return", "index": 1},
        "terminal": "device",
        "device_index": 1,
    }


def test_get_node_path_master_device_has_no_index(song):
    conn, ids = song
    addr = Q.get_node_path(conn, ids["d_lim"])
    assert addr == {
        "parent": {"kind": "master"},
        "terminal": "device",
        "device_index": 1,
    }
    assert "index" not in addr["parent"]


def test_get_node_path_missing_device_is_none(song):
    conn, _ = song
    assert Q.get_node_path(conn, "does-not-exist") is None


def test_get_node_path_path_matches_nesting_path_primitive(song):
    """The generalization must agree with the existing primitive on the nested
    steps — no two sources of truth for the same hierarchy."""
    conn, ids = song
    for key in ("d_eq", "d_sat", "d_deep"):
        addr = Q.get_node_path(conn, ids[key])
        assert addr.get("path", []) == Q.get_device_nesting_path(conn, ids[key])


# ---------------------------------------------------------------------------
# render_node_addr — device id → stable human string
# ---------------------------------------------------------------------------


def test_render_top_level_track_device(song):
    conn, ids = song
    assert Q.render_node_addr(conn, ids["d_eq"]) == 'track 2 ▸ "EQ Eight"'


def test_render_depth_1_nested(song):
    conn, ids = song
    assert Q.render_node_addr(conn, ids["d_sat"]) == (
        'track 2 ▸ "Guitar-Dual Amped Heavy" ▸ "Tube Saturator"'
    )


def test_render_depth_2_nested(song):
    conn, ids = song
    assert Q.render_node_addr(conn, ids["d_deep"]) == (
        'track 2 ▸ "Guitar-Dual Amped Heavy" ▸ "Inner Rack" ▸ "Deep EQ"'
    )


def test_render_return_device(song):
    conn, ids = song
    assert Q.render_node_addr(conn, ids["d_rev"]) == 'return 1 ▸ "Hybrid Reverb"'


def test_render_master_device(song):
    conn, ids = song
    assert Q.render_node_addr(conn, ids["d_lim"]) == 'master ▸ "Limiter"'


def test_render_missing_device_is_none(song):
    conn, _ = song
    assert Q.render_node_addr(conn, "does-not-exist") is None


# ---------------------------------------------------------------------------
# Refactor regression: the shared walker still serves the legacy primitives.
# ---------------------------------------------------------------------------


def test_top_level_device_resolves_through_shared_walker(song):
    conn, ids = song
    top = Q.get_top_level_device(conn, ids["d_deep"])
    assert top["id"] == ids["rack"]
    assert Q.get_device_nesting_path(conn, ids["d_eq"]) == []
