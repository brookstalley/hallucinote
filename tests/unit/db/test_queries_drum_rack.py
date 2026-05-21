"""Direct unit coverage for ``Q.get_linked_drum_racks_for_session``.

The query is exercised end-to-end by ``test_push_execute.py`` (the
pad-probe walker depends on it), but those tests cover only the
track-parent happy path. This module pins the other SQL branches
explicitly so a join regression in the COALESCE / LEFT subquery shape
surfaces here instead of in a downstream integration test.

Covers: track parent, return parent, missing link (link rows not yet
written), multiple Drum Racks on the same parent.
"""
from __future__ import annotations

import pytest

from hallucinote.db import init_db, mutations as M, queries as Q


@pytest.fixture
def conn(tmp_path):
    c = init_db(tmp_path / "drum_rack_queries.db")
    yield c
    c.close()


@pytest.fixture
def song(conn):
    return M.create_song(conn, name="t", key="Dm")


@pytest.fixture
def session(conn, song):
    return M.create_ableton_session(conn, song_id=song, name="draft")


def _drum_rack_on_track(conn, song_id: str, *, track_index: int, name: str = "Drums"):
    """Create one track with one DrumGroupDevice. Returns
    ``(track_id, device_id, chain_id)``."""
    tid = M.create_track(
        conn, song_id=song_id, track_index=track_index, name=name, kind="midi",
    )
    chain_id = M.create_device_chain(conn, parent_track_id=tid, position=0)
    did = M.create_device(
        conn, chain_id=chain_id, position=1,
        kind="DrumGroupDevice", display_name=f"{name} Rack",
    )
    return tid, did, chain_id


def _drum_rack_on_return(conn, song_id: str, *, position: int, name: str = "FX"):
    """Create one return with one DrumGroupDevice (unusual but valid —
    exercises the return-parent branch of the COALESCE)."""
    rid = M.create_return(conn, song_id=song_id, position=position, name=name)
    chain_id = M.create_device_chain(conn, parent_return_id=rid, position=0)
    did = M.create_device(
        conn, chain_id=chain_id, position=1,
        kind="DrumGroupDevice", display_name=f"{name} Rack",
    )
    return rid, did, chain_id


def test_query_returns_track_parent_drum_rack(conn, song, session):
    """Track-parent branch: the CASE expression flags parent_kind='track'
    and both the parent-link and device-link subqueries resolve."""
    tid, did, _ = _drum_rack_on_track(conn, song, track_index=1)
    # Link parent track and the device.
    M.link_db_to_ableton(conn, session_id=session, db_kind="track",
                         db_id=tid, ableton_index=1)
    M.link_db_to_ableton(conn, session_id=session, db_kind="device",
                         db_id=did, ableton_index=1)
    rows = Q.get_linked_drum_racks_for_session(conn, session)
    assert len(rows) == 1
    row = rows[0]
    assert row["device_id"] == did
    assert row["parent_kind"] == "track"
    assert row["parent_ableton_index"] == 1
    assert row["device_ableton_index"] == 1
    assert row["device_position"] == 1


def test_query_returns_return_parent_drum_rack(conn, song, session):
    """Return-parent branch: the CASE expression flags parent_kind='return'
    and COALESCE picks the second subquery (parent_track_id is NULL)."""
    rid, did, _ = _drum_rack_on_return(conn, song, position=1)
    M.link_db_to_ableton(conn, session_id=session, db_kind="return",
                         db_id=rid, ableton_index=1)
    M.link_db_to_ableton(conn, session_id=session, db_kind="device",
                         db_id=did, ableton_index=1)
    rows = Q.get_linked_drum_racks_for_session(conn, session)
    assert len(rows) == 1
    row = rows[0]
    assert row["parent_kind"] == "return"
    assert row["parent_ableton_index"] == 1
    assert row["device_ableton_index"] == 1


def test_query_returns_null_addressing_when_links_missing(conn, song, session):
    """Drum Rack exists in DB but parent/device aren't linked yet (a
    first-push-state condition or a probe_and_link run that hasn't
    fired). The query still returns the row — the walker filters out
    rows with NULL addressing and the next push retries the probe."""
    _drum_rack_on_track(conn, song, track_index=1)
    # Note: NO link rows written.
    rows = Q.get_linked_drum_racks_for_session(conn, session)
    assert len(rows) == 1
    row = rows[0]
    # Both addressing columns come back NULL because the inner subqueries
    # find no matching ableton_links rows.
    assert row["parent_ableton_index"] is None
    assert row["device_ableton_index"] is None


def test_query_returns_empty_when_no_drum_racks(conn, song, session):
    """Non-Drum-Rack devices are filtered by the WHERE kind = 'DrumGroupDevice'
    clause — a song with only synths returns nothing."""
    tid = M.create_track(conn, song_id=song, track_index=1, name="Synth", kind="midi")
    chain_id = M.create_device_chain(conn, parent_track_id=tid, position=0)
    M.create_device(
        conn, chain_id=chain_id, position=1,
        kind="Operator", display_name="Sub Bass",
    )
    assert Q.get_linked_drum_racks_for_session(conn, session) == []


def test_query_returns_multiple_drum_racks_ordered_by_position(conn, song, session):
    """A track with multiple Drum Racks at distinct positions surfaces both,
    ordered by device.position ASC (matches the schema's chain ordering)."""
    tid = M.create_track(conn, song_id=song, track_index=1, name="Drums", kind="midi")
    chain_id = M.create_device_chain(conn, parent_track_id=tid, position=0)
    # Two racks on the same chain at positions 1 and 2.
    did1 = M.create_device(
        conn, chain_id=chain_id, position=1,
        kind="DrumGroupDevice", display_name="Primary",
    )
    did2 = M.create_device(
        conn, chain_id=chain_id, position=2,
        kind="DrumGroupDevice", display_name="Layered",
    )
    M.link_db_to_ableton(conn, session_id=session, db_kind="track",
                         db_id=tid, ableton_index=1)
    M.link_db_to_ableton(conn, session_id=session, db_kind="device",
                         db_id=did1, ableton_index=1)
    M.link_db_to_ableton(conn, session_id=session, db_kind="device",
                         db_id=did2, ableton_index=2)
    rows = Q.get_linked_drum_racks_for_session(conn, session)
    assert [r["device_id"] for r in rows] == [did1, did2]
    assert [r["device_position"] for r in rows] == [1, 2]
