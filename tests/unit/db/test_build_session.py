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
    d1 = M.create_device(conn, chain_id=cid, position=1, kind="EQ Eight",
                          display_name="EQ")
    n1 = _event_count(conn)
    d2 = M.create_device(conn, chain_id=cid, position=1, kind="EQ Eight",
                          display_name="EQ")
    assert d2.kind == "unchanged"
    assert _event_count(conn) == n1


def test_set_device_parameter_idempotent(conn):
    sid = M.create_song(conn, name="s")
    tid = M.create_track(conn, song_id=sid, track_index=1, name="T")
    cid = M.create_device_chain(conn, parent_track_id=tid)
    did = M.create_device(conn, chain_id=cid, position=1, kind="EQ Eight",
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


def test_llm_note_edits_protect_clip_from_tombstone(conn):
    """PR review correctness check: if an LLM revises notes on a build-owned
    clip (via M.replace_clip_notes(actor='llm')), a later build that drops
    the clip from build.py must NOT tombstone it (CASCADE would lose the
    LLM's note edits)."""
    # Build creates a clip.
    with M.build_session(conn, song_name="s"):
        sid = M.create_song(conn, name="s")
        tid = M.create_track(conn, song_id=sid, track_index=1, name="T")
        clip_id = M.create_clip(conn, track_id=tid, slot=1,
                                 length_beats=4.0, name="Original")

    # LLM edits notes on the clip outside the session.
    M.replace_clip_notes(
        conn, clip_id=clip_id,
        notes=[{"pitch": 60, "start_beats": 0.0, "duration_beats": 1.0,
                "velocity": 80}],
        actor="llm",
    )

    # Re-build that drops the clip from build.py.
    with M.build_session(conn, song_name="s"):
        sid = M.create_song(conn, name="s")
        M.create_track(conn, song_id=sid, track_index=1, name="T")
        # No clip touched this time.

    # The clip must survive — LLM's last edit overrides build's ownership.
    clips = Q.get_clips_for_track(conn, tid)
    assert any(c["id"] == clip_id for c in clips), (
        "LLM-edited clip should survive tombstoning (latest event actor='llm')"
    )


def test_request_id_threaded_for_non_default_actor_inside_session(conn):
    """PR review correctness check: sync/generator/llm actors used INSIDE
    a build_session must still get the session's request_id (so the audit
    trail can answer 'which build cycle produced this row?')."""
    with M.build_session(conn, song_name="s") as bs:
        # sync-actor event (mimics replay_capture inside build_session).
        sid = M.create_song(conn, name="s", actor="sync")
    # Find the song_created event and verify its request_id matches bs.request_id.
    ev = conn.execute(
        "SELECT actor, request_id FROM events WHERE kind = 'song_created' "
        "ORDER BY seq DESC LIMIT 1"
    ).fetchone()
    assert ev["actor"] == "sync"  # explicit actor preserved
    assert ev["request_id"] == bs.request_id  # session request_id injected


def test_generator_actor_envelope_survives_tombstone(conn):
    """Same family as the LLM-note test but for the generator-actor case:
    envelopes authored by `actor='generator'` (e.g., _author_envelopes) on
    a build-owned target must survive build tombstoning even if not touched."""
    with M.build_session(conn, song_name="s"):
        sid = M.create_song(conn, name="s")
        tid = M.create_track(conn, song_id=sid, track_index=1, name="T")

    # Generator authors an envelope outside the session.
    env_id = M.create_envelope(
        conn, song_id=sid, target_kind="mixer_volume", target_track_id=tid,
        actor="generator",
    )

    # Re-build that touches the track but not the envelope.
    with M.build_session(conn, song_name="s"):
        sid = M.create_song(conn, name="s")
        M.create_track(conn, song_id=sid, track_index=1, name="T")

    envs = Q.get_envelopes_for_song(conn, sid)
    assert any(e["id"] == env_id for e in envs), (
        "Generator-authored envelope should survive tombstoning"
    )


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


def test_tombstone_walks_into_nested_rack_chains(conn):
    """Arc 7 / P4: chains parented by `parent_rack_device_id` (inside a
    Drum Rack / Instrument Rack / Audio Effect Rack) used to be invisible
    to the tombstone walker — its SELECT joined only through
    `parent_track_id` / `parent_return_id`, so a build-owned nested-rack
    inner chain (and its devices) would survive even when build dropped
    them. With the WITH RECURSIVE CTE, the walker enumerates nested
    chains and tombstones their build-owned rows correctly.

    Scenario: first build creates a track with a Drum Rack device + one
    inner chain holding a kit piece. Second build keeps the rack but
    drops the inner chain — the inner chain (and its inner device) must
    tombstone."""
    # First build: track + rack device + inner chain + inner device.
    with M.build_session(conn, song_name="s"):
        sid = M.create_song(conn, name="s")
        tid = M.create_track(conn, song_id=sid, track_index=1, name="Drums")
        top_chain = M.create_device_chain(conn, parent_track_id=tid)
        rack = M.create_device(
            conn, chain_id=top_chain, position=1, kind="DrumGroupDevice",
            display_name="Drum Rack",
        )
        inner_chain = M.create_device_chain(
            conn, parent_rack_device_id=rack,
        )
        M.create_device(
            conn, chain_id=inner_chain, position=1, kind="Sampler",
            display_name="Kick",
        )

    # Confirm pre-state: the inner chain + inner device exist.
    pre = conn.execute(
        "SELECT COUNT(*) AS n FROM device_chains "
        "WHERE parent_rack_device_id IS NOT NULL"
    ).fetchone()
    assert pre["n"] == 1
    pre_devs = conn.execute(
        "SELECT COUNT(*) AS n FROM devices d "
        "JOIN device_chains dc ON dc.id = d.chain_id "
        "WHERE dc.parent_rack_device_id IS NOT NULL"
    ).fetchone()
    assert pre_devs["n"] == 1

    # Second build: rack stays, inner chain is NOT touched → must tombstone.
    with M.build_session(conn, song_name="s"):
        sid = M.create_song(conn, name="s")
        tid_new = M.create_track(conn, song_id=sid, track_index=1, name="Drums")
        top_chain_new = M.create_device_chain(conn, parent_track_id=tid_new)
        M.create_device(
            conn, chain_id=top_chain_new, position=1, kind="DrumGroupDevice",
            display_name="Drum Rack",
        )
        # Deliberately do NOT recreate the inner chain.

    post = conn.execute(
        "SELECT COUNT(*) AS n FROM device_chains "
        "WHERE parent_rack_device_id IS NOT NULL"
    ).fetchone()
    assert post["n"] == 0, (
        "Inner chain should have been tombstoned; the walker now "
        "enumerates chains via parent_rack_device_id"
    )
    post_devs = conn.execute(
        "SELECT COUNT(*) AS n FROM devices d "
        "JOIN device_chains dc ON dc.id = d.chain_id "
        "WHERE dc.parent_rack_device_id IS NOT NULL"
    ).fetchone()
    assert post_devs["n"] == 0, (
        "Inner device should have been tombstoned alongside its chain"
    )


def test_tombstone_preserves_touched_nested_rack_chain(conn):
    """Companion to nested-rack tombstone: when build *does* touch the
    inner chain (idempotent re-build), the walker must NOT tombstone it.
    Guards against false positives from the recursive enumeration."""
    # First build creates the nested structure.
    with M.build_session(conn, song_name="s"):
        sid = M.create_song(conn, name="s")
        tid = M.create_track(conn, song_id=sid, track_index=1, name="Drums")
        top_chain = M.create_device_chain(conn, parent_track_id=tid)
        rack = M.create_device(
            conn, chain_id=top_chain, position=1, kind="DrumGroupDevice",
            display_name="Drum Rack",
        )
        M.create_device_chain(conn, parent_rack_device_id=rack)

    rack_id_before = conn.execute(
        "SELECT id FROM device_chains WHERE parent_rack_device_id IS NOT NULL"
    ).fetchone()["id"]

    # Second build: re-touch the same structure (idempotent).
    with M.build_session(conn, song_name="s"):
        sid = M.create_song(conn, name="s")
        tid_new = M.create_track(conn, song_id=sid, track_index=1, name="Drums")
        top_chain_new = M.create_device_chain(conn, parent_track_id=tid_new)
        rack_new = M.create_device(
            conn, chain_id=top_chain_new, position=1, kind="DrumGroupDevice",
            display_name="Drum Rack",
        )
        M.create_device_chain(conn, parent_rack_device_id=rack_new)

    rack_id_after = conn.execute(
        "SELECT id FROM device_chains WHERE parent_rack_device_id IS NOT NULL"
    ).fetchone()
    assert rack_id_after is not None
    assert rack_id_after["id"] == rack_id_before


def test_audio_clip_survives_identical_rebuild_reconcile(conn):
    """CLP-AUD1: an authored audio clip touched by the build survives the
    build-session tombstone sweep on an identical re-run (the sweep is
    kind-agnostic; `create_audio_clip`'s touch recording is what protects
    the row — this pins it)."""

    def build():
        with M.build_session(conn, song_name="s"):
            sid = M.create_song(conn, name="s")
            atid = M.create_track(
                conn, song_id=sid, track_index=1, name="Vox", kind="audio",
            )
            M.create_audio_clip(
                conn, track_id=atid, slot=1, length_beats=16.0,
                audio_file="assets/vox_take3.wav", gain=0.8,
            )
        return sid

    sid = build()
    sid = build()  # identical re-run — sweep must keep the touched audio clip
    rows = conn.execute(
        """SELECT c.kind, c.audio_file FROM clips c
           JOIN tracks t ON t.id = c.track_id WHERE t.song_id = ?""",
        (sid,),
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["kind"] == "audio"
    assert rows[0]["audio_file"] == "assets/vox_take3.wav"

    # And the sweep still owns it: a rebuild WITHOUT the clip tombstones it.
    with M.build_session(conn, song_name="s"):
        sid = M.create_song(conn, name="s")
        M.create_track(conn, song_id=sid, track_index=1, name="Vox", kind="audio")
    rows = conn.execute(
        """SELECT c.id FROM clips c JOIN tracks t ON t.id = c.track_id
           WHERE t.song_id = ?""",
        (sid,),
    ).fetchall()
    assert rows == []
