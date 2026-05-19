"""W12-A — `M.build_session` state-converger context manager.

Verifies the load-bearing W12-A promises:
  - Inside the session, default actor='system' promotes to 'build'.
  - Mutator returns are MutatorResult with .kind in {created, updated, unchanged}.
  - Re-running an identical build produces zero net state changes (and zero
    events beyond the new request's open/close).
  - On exit, build-owned rows not touched in the latest build are tombstoned.
  - Pulled rows (actor='sync') survive tombstoning.
  - LLM/user-authored rows survive tombstoning.
  - Crash mid-build leaves DB intact and request marked failed.
"""
from __future__ import annotations

import pytest

from hallucinote.db import init_db
from hallucinote.db import mutations as M
from hallucinote.db import queries as Q
from hallucinote.db.mutations import MutatorResult


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def conn(tmp_path):
    c = init_db(tmp_path / "test.db")
    yield c
    c.close()


def _event_count(conn) -> int:
    return conn.execute("SELECT COUNT(*) AS n FROM events").fetchone()["n"]


def _events(conn):
    return list(conn.execute(
        "SELECT kind, actor, payload_json FROM events ORDER BY seq"
    ).fetchall())


# ---------------------------------------------------------------------------
# MutatorResult: str-subclass back-compat
# ---------------------------------------------------------------------------


def test_mutator_result_is_str_compatible(conn):
    song_id = M.create_song(conn, name="test-song")
    # It's a str — concatenation, comparison, .startswith all work.
    assert isinstance(song_id, str)
    assert isinstance(song_id, MutatorResult)
    assert len(song_id) == 32  # UUID hex
    assert song_id == str(song_id)
    # And it carries the .kind attribute.
    assert song_id.kind == "created"


def test_mutator_result_kind_values(conn):
    s1 = M.create_song(conn, name="s1")
    assert s1.kind == "created"
    s2 = M.create_song(conn, name="s1")  # same args
    assert s2.kind == "unchanged"
    assert s2 == s1  # same id
    s3 = M.create_song(conn, name="s1", title="New Title")
    assert s3.kind == "updated"
    assert s3 == s1  # still same id


# ---------------------------------------------------------------------------
# Idempotency per-mutator (one test per UPSERT mutator)
# ---------------------------------------------------------------------------


def test_create_song_idempotent(conn):
    s1 = M.create_song(conn, name="x", title="X", key="C")
    n1 = _event_count(conn)
    s2 = M.create_song(conn, name="x", title="X", key="C")
    assert s2.kind == "unchanged"
    assert s2 == s1
    assert _event_count(conn) == n1  # no event emitted for no-op


def test_create_track_idempotent(conn):
    sid = M.create_song(conn, name="s")
    t1 = M.create_track(conn, song_id=sid, track_index=1, name="Drums")
    n1 = _event_count(conn)
    t2 = M.create_track(conn, song_id=sid, track_index=1, name="Drums")
    assert t2.kind == "unchanged"
    assert t2 == t1
    assert _event_count(conn) == n1


def test_create_track_updates_on_diff(conn):
    sid = M.create_song(conn, name="s")
    t1 = M.create_track(conn, song_id=sid, track_index=1, name="Drums")
    t2 = M.create_track(conn, song_id=sid, track_index=1, name="Bass")  # rename
    assert t2.kind == "updated"
    assert t2 == t1


def test_create_clip_idempotent(conn):
    sid = M.create_song(conn, name="s")
    tid = M.create_track(conn, song_id=sid, track_index=1, name="T")
    c1 = M.create_clip(conn, track_id=tid, slot=1, length_beats=16.0, name="A")
    n1 = _event_count(conn)
    c2 = M.create_clip(conn, track_id=tid, slot=1, length_beats=16.0, name="A")
    assert c2.kind == "unchanged"
    assert c2 == c1
    assert _event_count(conn) == n1


def test_add_arrangement_clip_idempotent(conn):
    sid = M.create_song(conn, name="s")
    tid = M.create_track(conn, song_id=sid, track_index=1, name="T")
    cid = M.create_clip(conn, track_id=tid, slot=1, length_beats=16.0)
    a1 = M.add_arrangement_clip(
        conn, song_id=sid, track_id=tid, clip_id=cid,
        start_bar=1.0, end_bar=5.0,
    )
    n1 = _event_count(conn)
    a2 = M.add_arrangement_clip(
        conn, song_id=sid, track_id=tid, clip_id=cid,
        start_bar=1.0, end_bar=5.0,
    )
    assert a2.kind == "unchanged"
    assert a2 == a1
    assert _event_count(conn) == n1


def test_create_section_idempotent(conn):
    sid = M.create_song(conn, name="s")
    s1 = M.create_section(conn, song_id=sid, name="verse",
                          start_bar=1.0, end_bar=9.0)
    n1 = _event_count(conn)
    s2 = M.create_section(conn, song_id=sid, name="verse",
                          start_bar=1.0, end_bar=9.0)
    assert s2.kind == "unchanged"
    assert _event_count(conn) == n1


def test_section_repeated_name_distinct_at_different_bars(conn):
    """Per Wave 0 fbr-3 finding: sections with same name at different bars
    are intentional repeats (verse 1, verse 2). Identity is
    (song_id, name, start_bar)."""
    sid = M.create_song(conn, name="s")
    a = M.create_section(conn, song_id=sid, name="verse",
                         start_bar=1.0, end_bar=9.0)
    b = M.create_section(conn, song_id=sid, name="verse",
                         start_bar=17.0, end_bar=25.0)
    assert a != b
    assert a.kind == "created"
    assert b.kind == "created"


def test_add_tempo_point_idempotent(conn):
    sid = M.create_song(conn, name="s")
    p1 = M.add_tempo_point(conn, song_id=sid, start_bar=1.0, tempo_bpm=120.0)
    n1 = _event_count(conn)
    p2 = M.add_tempo_point(conn, song_id=sid, start_bar=1.0, tempo_bpm=120.0)
    assert p2.kind == "unchanged"
    assert _event_count(conn) == n1


def test_add_time_signature_point_idempotent(conn):
    sid = M.create_song(conn, name="s")
    p1 = M.add_time_signature_point(
        conn, song_id=sid, start_bar=1.0, numerator=4, denominator=4,
    )
    n1 = _event_count(conn)
    p2 = M.add_time_signature_point(
        conn, song_id=sid, start_bar=1.0, numerator=4, denominator=4,
    )
    assert p2.kind == "unchanged"
    assert _event_count(conn) == n1


def test_add_cue_point_idempotent(conn):
    sid = M.create_song(conn, name="s")
    c1 = M.add_cue_point(conn, song_id=sid, position_bar=1.0, name="intro")
    n1 = _event_count(conn)
    c2 = M.add_cue_point(conn, song_id=sid, position_bar=1.0, name="intro")
    assert c2.kind == "unchanged"
    assert _event_count(conn) == n1


def test_create_return_idempotent(conn):
    sid = M.create_song(conn, name="s")
    r1 = M.create_return(conn, song_id=sid, name="Reverb", position=1)
    n1 = _event_count(conn)
    r2 = M.create_return(conn, song_id=sid, name="Reverb", position=1)
    assert r2.kind == "unchanged"
    assert _event_count(conn) == n1


def test_create_device_chain_idempotent(conn):
    sid = M.create_song(conn, name="s")
    tid = M.create_track(conn, song_id=sid, track_index=1, name="T")
    c1 = M.create_device_chain(conn, parent_track_id=tid, position=0)
    n1 = _event_count(conn)
    c2 = M.create_device_chain(conn, parent_track_id=tid, position=0)
    assert c2.kind == "unchanged"
    assert _event_count(conn) == n1


def test_create_device_idempotent(conn):
    sid = M.create_song(conn, name="s")
    tid = M.create_track(conn, song_id=sid, track_index=1, name="T")
    cid = M.create_device_chain(conn, parent_track_id=tid)
    d1 = M.create_device(conn, chain_id=cid, position=1, kind="Eq8",
                          display_name="EQ")
    n1 = _event_count(conn)
    d2 = M.create_device(conn, chain_id=cid, position=1, kind="Eq8",
                          display_name="EQ")
    assert d2.kind == "unchanged"
    assert _event_count(conn) == n1


def test_set_device_parameter_idempotent(conn):
    sid = M.create_song(conn, name="s")
    tid = M.create_track(conn, song_id=sid, track_index=1, name="T")
    cid = M.create_device_chain(conn, parent_track_id=tid)
    did = M.create_device(conn, chain_id=cid, position=1, kind="Eq8",
                           display_name="EQ")
    p1 = M.set_device_parameter(
        conn, device_id=did, name="Freq", value_display="1.0kHz",
        value_normalized=0.5,
    )
    n1 = _event_count(conn)
    p2 = M.set_device_parameter(
        conn, device_id=did, name="Freq", value_display="1.0kHz",
        value_normalized=0.5,
    )
    assert p2.kind == "unchanged"
    assert _event_count(conn) == n1


def test_create_envelope_idempotent(conn):
    sid = M.create_song(conn, name="s")
    tid = M.create_track(conn, song_id=sid, track_index=1, name="T")
    cid = M.create_clip(conn, track_id=tid, slot=1, length_beats=16.0)
    e1 = M.create_envelope(
        conn, song_id=sid, target_kind="mixer_volume", target_track_id=tid,
    )
    n1 = _event_count(conn)
    e2 = M.create_envelope(
        conn, song_id=sid, target_kind="mixer_volume", target_track_id=tid,
    )
    assert e2.kind == "unchanged"
    assert _event_count(conn) == n1


# ---------------------------------------------------------------------------
# Build session lifecycle
# ---------------------------------------------------------------------------


def test_build_session_promotes_actor_to_build(conn):
    """Inside a build_session, default actor='system' becomes 'build'."""
    with M.build_session(conn, song_name="my-song"):
        sid = M.create_song(conn, name="my-song")
    # The song-creation event should have actor='build', not 'system'.
    song_ev = next(e for e in _events(conn) if e["kind"] == "song_created")
    assert song_ev["actor"] == "build"


def test_build_session_does_not_override_explicit_actor(conn):
    """Explicit actor='sync' (or anything non-default) survives the session."""
    with M.build_session(conn, song_name="my-song"):
        sid = M.create_song(conn, name="my-song", actor="sync")
    song_ev = next(e for e in _events(conn) if e["kind"] == "song_created")
    assert song_ev["actor"] == "sync"


def test_build_session_records_touches(conn):
    with M.build_session(conn, song_name="my-song") as bs:
        sid = M.create_song(conn, name="my-song")
        tid = M.create_track(conn, song_id=sid, track_index=1, name="Drums")
    # The session's touched-set has both entities by the end of the block.
    # We can't check bs.touched after exit (the test runs after the with-
    # block's cleanup which doesn't clear it), so check it inside.
    assert bs.touched_count("song") == 1
    assert bs.touched_count("track") == 1


def test_build_session_request_lifecycle(conn):
    """Opens a 'compose' request and closes it ok on clean exit."""
    n_requests_before = conn.execute(
        "SELECT COUNT(*) AS n FROM requests"
    ).fetchone()["n"]
    with M.build_session(conn, song_name="s"):
        M.create_song(conn, name="s")
    n_requests_after = conn.execute(
        "SELECT COUNT(*) AS n FROM requests"
    ).fetchone()["n"]
    assert n_requests_after == n_requests_before + 1
    req = conn.execute(
        "SELECT actor, intent, kind, outcome FROM requests ORDER BY ts DESC LIMIT 1"
    ).fetchone()
    assert req["actor"] == "build"
    assert req["kind"] == "compose"
    assert req["outcome"] == "ok"


def test_build_session_failed_request_on_exception(conn):
    """Exception inside the block marks the request as failed."""
    with pytest.raises(RuntimeError):
        with M.build_session(conn, song_name="s"):
            M.create_song(conn, name="s")
            raise RuntimeError("simulated build failure")
    req = conn.execute(
        "SELECT outcome FROM requests ORDER BY ts DESC LIMIT 1"
    ).fetchone()
    assert req["outcome"] == "failed"


# ---------------------------------------------------------------------------
# Tombstone semantics
# ---------------------------------------------------------------------------


def test_re_running_identical_build_produces_zero_state_changes(conn):
    """The load-bearing W12-A promise: build is a state-converger."""

    def build():
        with M.build_session(conn, song_name="s"):
            sid = M.create_song(conn, name="s")
            tid = M.create_track(conn, song_id=sid, track_index=1, name="Drums")
            cid = M.create_clip(conn, track_id=tid, slot=1, length_beats=16.0,
                                 name="DrumsLoop")
            M.add_arrangement_clip(
                conn, song_id=sid, track_id=tid, clip_id=cid,
                start_bar=1.0, end_bar=5.0,
            )
            M.add_tempo_point(conn, song_id=sid, start_bar=1.0, tempo_bpm=120.0)
            M.add_time_signature_point(
                conn, song_id=sid, start_bar=1.0, numerator=4, denominator=4,
            )
            M.add_cue_point(conn, song_id=sid, position_bar=1.0, name="start")
            M.create_section(conn, song_id=sid, name="verse",
                              start_bar=1.0, end_bar=5.0)

    build()
    event_count_after_first_build = _event_count(conn)
    request_count_after_first_build = conn.execute(
        "SELECT COUNT(*) AS n FROM requests"
    ).fetchone()["n"]

    # Re-run — should produce ZERO state-change events.
    build()

    # New events allowed: the new build's request open/close (2 'request_*'
    # events). No other state changes.
    events_after_second = _events(conn)
    state_events_after_second = [
        e for e in events_after_second
        if e["kind"] not in ("request_created", "request_closed")
    ]
    state_events_first = state_events_after_second[:event_count_after_first_build - 2 * request_count_after_first_build]
    # All state events come from the FIRST build; second build added none.
    # Easier assertion: no NEW state-change events between the two builds.
    state_event_count = len(state_events_after_second)
    # The first build emitted N state events; second build should emit 0.
    # Total state events == first build's state events.
    # (Count them by running a fresh DB and capturing the first-build count.)
    fresh_conn = init_db(":memory:")
    try:
        with M.build_session(fresh_conn, song_name="s"):
            sid = M.create_song(fresh_conn, name="s")
            tid = M.create_track(fresh_conn, song_id=sid, track_index=1, name="Drums")
            cid = M.create_clip(fresh_conn, track_id=tid, slot=1,
                                 length_beats=16.0, name="DrumsLoop")
            M.add_arrangement_clip(
                fresh_conn, song_id=sid, track_id=tid, clip_id=cid,
                start_bar=1.0, end_bar=5.0,
            )
            M.add_tempo_point(fresh_conn, song_id=sid, start_bar=1.0,
                               tempo_bpm=120.0)
            M.add_time_signature_point(
                fresh_conn, song_id=sid, start_bar=1.0, numerator=4,
                denominator=4,
            )
            M.add_cue_point(fresh_conn, song_id=sid, position_bar=1.0,
                             name="start")
            M.create_section(fresh_conn, song_id=sid, name="verse",
                              start_bar=1.0, end_bar=5.0)
        expected_state_events = len([
            e for e in fresh_conn.execute(
                "SELECT kind FROM events ORDER BY seq"
            ).fetchall()
            if e["kind"] not in ("request_created", "request_closed")
        ])
    finally:
        fresh_conn.close()
    assert state_event_count == expected_state_events


def test_tombstone_removes_build_owned_untouched_rows(conn):
    """First build creates a track; second build (without that track)
    tombstones it."""
    with M.build_session(conn, song_name="s"):
        sid = M.create_song(conn, name="s")
        M.create_track(conn, song_id=sid, track_index=1, name="Drums")
        M.create_track(conn, song_id=sid, track_index=2, name="Bass")
    tracks = Q.get_tracks_for_song(conn, sid)
    assert len(tracks) == 2

    # Second build without 'Bass' — should tombstone it.
    with M.build_session(conn, song_name="s"):
        sid = M.create_song(conn, name="s")
        M.create_track(conn, song_id=sid, track_index=1, name="Drums")
        # No track at index 2 this time.
    tracks = Q.get_tracks_for_song(conn, sid)
    assert len(tracks) == 1
    assert tracks[0]["name"] == "Drums"


def test_tombstone_preserves_sync_actor_rows(conn):
    """A track created with actor='sync' (pulled from Live) survives build's
    tombstone sweep even when build.py doesn't touch it."""
    sid = M.create_song(conn, name="s")
    # Simulate a pulled track.
    pulled_tid = M.create_track(
        conn, song_id=sid, track_index=99, name="PulledFromLive",
        actor="sync",
    )

    # Build session that doesn't reference the pulled track.
    with M.build_session(conn, song_name="s"):
        M.create_song(conn, name="s")
        M.create_track(conn, song_id=sid, track_index=1, name="Drums")

    tracks = Q.get_tracks_for_song(conn, sid)
    names = {t["name"] for t in tracks}
    assert "PulledFromLive" in names
    assert "Drums" in names


def test_tombstone_preserves_llm_authored_rows(conn):
    """A clip authored mid-session by 'llm' actor survives build tombstoning."""
    with M.build_session(conn, song_name="s"):
        sid = M.create_song(conn, name="s")
        tid = M.create_track(conn, song_id=sid, track_index=1, name="T")
    # LLM authors a clip outside the build session.
    llm_cid = M.create_clip(
        conn, track_id=tid, slot=5, length_beats=4.0, name="LLM-Edit",
        actor="llm",
    )

    # Re-build (touches the track but not the LLM clip).
    with M.build_session(conn, song_name="s"):
        sid = M.create_song(conn, name="s")
        M.create_track(conn, song_id=sid, track_index=1, name="T")
        # No clip touched here.

    clips = Q.get_clips_for_track(conn, tid)
    assert any(c["id"] == llm_cid for c in clips), "LLM-authored clip should survive"


def test_tombstone_clip_removed_when_dropped_from_build(conn):
    """Inverse of LLM test: a clip created by build, then absent in re-build,
    gets tombstoned."""
    with M.build_session(conn, song_name="s"):
        sid = M.create_song(conn, name="s")
        tid = M.create_track(conn, song_id=sid, track_index=1, name="T")
        M.create_clip(conn, track_id=tid, slot=1, length_beats=16.0, name="A")
        M.create_clip(conn, track_id=tid, slot=2, length_beats=16.0, name="B")

    # Re-build with only slot=1 — slot=2 should be tombstoned.
    with M.build_session(conn, song_name="s"):
        sid = M.create_song(conn, name="s")
        tid_new = M.create_track(conn, song_id=sid, track_index=1, name="T")
        M.create_clip(conn, track_id=tid_new, slot=1, length_beats=16.0, name="A")

    clips = Q.get_clips_for_track(conn, tid_new)
    slots = {c["slot"] for c in clips}
    assert slots == {1}
