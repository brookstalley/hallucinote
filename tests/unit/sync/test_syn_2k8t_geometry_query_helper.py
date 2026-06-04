"""SYN-2K8T: the arrangement_clips JOIN clips read used to resolve envelope
addressing must go through a query helper, not inline SQL in the caller.

`geometry._resolve_envelope_session_clip` previously ran a raw
`conn.execute("SELECT ... arrangement_clips JOIN clips ...")`. It now calls
`queries.get_arrangement_placements_with_clip_length`. These tests pin the
helper's contract (columns, ordering, source clip length) and a smoke test
that the resolver still finds a covering placement through the helper.
"""
from __future__ import annotations

import pytest

from hallucinote.db import init_db, mutations as M, queries as Q
from hallucinote.sync.geometry import _resolve_envelope_session_clip


@pytest.fixture
def conn(tmp_path):
    c = init_db(tmp_path / "geom.db")
    yield c
    c.close()


def _song_track_clip(conn):
    song = M.create_song(conn, name="t", key="Dm")
    track = M.create_track(conn, song_id=song, track_index=1, name="Synth")
    clip = M.create_clip(
        conn, track_id=track, slot=1, length_beats=16.0, name="Pad"
    )
    return song, track, clip


def test_helper_returns_joined_length_and_order(conn):
    song, track, clip = _song_track_clip(conn)
    # Two placements, authored out of start-bar order.
    M.add_arrangement_clip(
        conn, song_id=song, track_id=track, clip_id=clip,
        start_bar=5.0, end_bar=9.0,
    )
    M.add_arrangement_clip(
        conn, song_id=song, track_id=track, clip_id=clip,
        start_bar=1.0, end_bar=5.0,
    )

    rows = Q.get_arrangement_placements_with_clip_length(conn, track)
    assert len(rows) == 2
    # Ordered by start_bar.
    assert [r["start_bar"] for r in rows] == [1.0, 5.0]
    # Each row carries the SOURCE clip's natural length via the JOIN.
    assert all(r["length_beats"] == 16.0 for r in rows)
    assert all(r["clip_id"] == clip for r in rows)


def test_helper_empty_for_track_without_placements(conn):
    _song, track, _clip = _song_track_clip(conn)
    assert Q.get_arrangement_placements_with_clip_length(conn, track) == []


def test_resolver_finds_covering_placement_through_helper(conn):
    """Smoke test: the resolver, now reading via the helper, still resolves
    a placement whose source clip covers the envelope range."""
    song, track, clip = _song_track_clip(conn)
    # 4/4 base meter so bar->beats is the identity-ish mapping the resolver
    # relies on. Placement at bar 1 with a 16-beat source clip covers
    # [0, 16] in beats.
    M.add_arrangement_clip(
        conn, song_id=song, track_id=track, clip_id=clip,
        start_bar=1.0, end_bar=5.0,
    )

    covering = _resolve_envelope_session_clip(
        conn, song_id=song, target_track_id=track,
        env_min=0.0, env_max=8.0,
    )
    assert covering is not None
    assert covering.clip_id == clip
    assert covering.start_beats == 0.0
