"""Smoke test for the falling-walking build.py end-to-end.

Exercises the post-migration authoring path: every clip flows through library
generators + mutators, arrangement entries place them in time, envelopes
demonstrate the GeneratorOutput pathway. This test is the migration's
production-complete proof: if build.py runs clean and the DB carries the
expected shape, chunk 5 is delivered.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SONG_ROOT = Path(__file__).resolve().parents[1]
BUILD_PATH = SONG_ROOT / "build.py"


@pytest.fixture
def build_module(tmp_path, monkeypatch):
    """Import build.py with DB_PATH redirected to a temp file."""
    spec = importlib.util.spec_from_file_location("falling_walking_build", BUILD_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "DB_PATH", tmp_path / "falling-walking.db")
    return module


def test_build_runs_clean_and_produces_full_song(build_module):
    """Running build(--reset) populates every section and lands envelopes."""
    from hallucinote.db import init_db, queries as Q

    song_id = build_module.build(reset=True)
    assert song_id

    conn = init_db(build_module.DB_PATH)
    try:
        # Sections — seven, one per song section.
        sections = Q.get_sections_for_song(conn, song_id)
        names = [s["name"] for s in sections]
        assert names == ["intro", "verse", "chorus", "chorus_twist",
                         "bridge", "tag", "outro"]

        # Tracks — 13 (12 from snapshot + master).
        tracks = Q.get_tracks_for_song(conn, song_id)
        assert len(tracks) == 13

        # Every authoring track has clips. The four placeholder tracks (1-MIDI
        # through 4-Audio) and the master have no clips.
        tracks_by_name = {t["name"]: t for t in tracks}
        authored = [
            "01 Drums", "02 Sub Bass", "03 Synth Bass", "04 Verse Pad",
            "05 Chorus Pluck", "06 Bell", "07 Bridge EP", "08 Chiptune Lead",
        ]
        for name in authored:
            clips = Q.get_clips_for_track(conn, tracks_by_name[name]["id"])
            assert clips, f"track {name!r} has no clips"

        # Arrangement entries: at least one per section per authoring track.
        arr = Q.get_arrangement_for_song(conn, song_id)
        assert len(arr) >= 25, f"expected >= 25 arrangement entries, got {len(arr)}"

        # Envelopes — at least the two demonstration envelopes from build.py.
        envs = Q.get_envelopes_for_song(conn, song_id)
        assert len(envs) >= 2
        kinds = {e["target_kind"] for e in envs}
        assert "mixer_volume" in kinds

        # Every envelope has breakpoints.
        for e in envs:
            bps = Q.get_breakpoints(conn, envelope_id=e["id"])
            assert bps, f"envelope {e['id']} has no breakpoints"

        # Total note count is a non-trivial musical work.
        total = sum(len(Q.get_notes_for_clip(conn, c["id"]))
                    for t in tracks
                    for c in Q.get_clips_for_track(conn, t["id"]))
        assert total > 1000, f"expected >1000 notes total, got {total}"
    finally:
        conn.close()


def test_build_is_idempotent_state_converger(build_module):
    """W12-A: re-running the build over an existing DB produces zero net
    state-change events. Validates the load-bearing state-converger promise
    on the real falling-walking build (not a synthetic one)."""
    from hallucinote.db import init_db

    # First build.
    song_id = build_module.build(reset=True)
    conn = init_db(build_module.DB_PATH)
    try:
        # State-change events from the first build.
        state_events_first = [
            r["kind"] for r in conn.execute(
                "SELECT kind FROM events "
                "WHERE kind NOT IN ('request_created', 'request_closed') "
                "ORDER BY seq"
            ).fetchall()
        ]
        n_state_first = len(state_events_first)
    finally:
        conn.close()

    # Second build — no reset, expect zero new state-change events.
    song_id_2 = build_module.build(reset=False)
    assert song_id_2 == song_id  # same song row

    conn = init_db(build_module.DB_PATH)
    try:
        state_events_after = [
            r["kind"] for r in conn.execute(
                "SELECT kind FROM events "
                "WHERE kind NOT IN ('request_created', 'request_closed') "
                "ORDER BY seq"
            ).fetchall()
        ]
        assert len(state_events_after) == n_state_first, (
            f"Re-running build produced {len(state_events_after) - n_state_first} "
            f"extra state-change events — converger discipline broken."
        )
    finally:
        conn.close()


def test_build_push_planners_run_without_error(build_module):
    """Every push planner runs without exceptions on the built song."""
    from hallucinote.db import init_db, mutations as M, queries as Q
    from hallucinote.sync import push

    song_id = build_module.build(reset=True)
    conn = init_db(build_module.DB_PATH)
    try:
        session_id = M.create_ableton_session(conn, song_id=song_id, name="smoke")

        # Song-only planners.
        for fn in (push.plan_push_tempo_map, push.plan_push_time_signature_map,
                   push.plan_push_sections, push.plan_push_cue_points):
            plan = fn(conn, song_id=song_id)
            assert plan is not None

        # W3-C song-level pre-pass: emits one create per unique unlinked
        # track / return. Validate count + simulate apply.
        tracks_plan = push.plan_push_song_tracks(conn, song_id=song_id, session_id=session_id)
        non_master_tracks = [
            t for t in Q.get_tracks_for_song(conn, song_id) if t["kind"] != "master"
        ]
        assert len(tracks_plan.calls) == len(non_master_tracks), (
            f"plan_push_song_tracks must emit exactly one call per unique unlinked "
            f"non-master track ({len(non_master_tracks)} expected, {len(tracks_plan.calls)} got)"
        )
        # Simulate apply: link every track at its declared track_index so the
        # downstream planners can run.
        for i, c in enumerate(tracks_plan.calls, start=1):
            track_db_id = c.key.partition(":")[2]
            M.link_db_to_ableton(
                conn, session_id=session_id, db_kind="track",
                db_id=track_db_id, ableton_index=i,
            )

        returns_plan = push.plan_push_song_returns(conn, song_id=song_id, session_id=session_id)
        for i, c in enumerate(returns_plan.calls, start=1):
            return_db_id = c.key.partition(":")[2]
            M.link_db_to_ableton(
                conn, session_id=session_id, db_kind="return",
                db_id=return_db_id, ableton_index=i,
            )

        # Session-required planners that don't depend on clip links: mix,
        # devices, envelopes.
        for fn in (push.plan_push_mix, push.plan_push_devices,
                   push.plan_push_envelopes):
            plan = fn(conn, song_id=song_id, session_id=session_id)
            assert plan is not None

        # plan_push_clip on every clip should emit at least one call.
        # Simulate apply by linking each clip at a synthetic slot so the
        # downstream arrangement planner (now strict post-W3-F-followup)
        # has all the links it needs.
        slot_counter: dict[str, int] = {}
        for t in Q.get_tracks_for_song(conn, song_id):
            for c in Q.get_clips_for_track(conn, t["id"]):
                plan = push.plan_push_clip(conn, clip_id=c["id"], session_id=session_id)
                assert plan.calls, f"plan_push_clip({c['name']}) emitted no calls"
                # Link the clip at its DB slot — matches what the agent
                # would record after running the create call.
                M.link_db_to_ableton(
                    conn, session_id=session_id, db_kind="clip",
                    db_id=c["id"], ableton_index=c["slot"],
                )

        # plan_push_arrangement is strict (W3-F follow-up): tracks AND
        # clips must be linked. With the loop above, they are.
        arrangement_plan = push.plan_push_arrangement(
            conn, song_id=song_id, session_id=session_id,
        )
        assert arrangement_plan is not None
    finally:
        conn.close()
