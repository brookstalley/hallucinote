"""Tests for the DB->Ableton planner and result application."""
from __future__ import annotations

import pytest

from hallucinote.db import init_db, mutations as M, queries as Q
from hallucinote.sync import push


@pytest.fixture
def conn(tmp_path):
    c = init_db(tmp_path / "p.db")
    yield c
    c.close()


@pytest.fixture
def song(conn):
    return M.create_song(conn, name="t", key="Dm")


@pytest.fixture
def session(conn, song):
    return M.create_ableton_session(conn, song_id=song, name="draft")


@pytest.fixture
def track(conn, song):
    return M.create_track(
        conn, song_id=song, track_index=1, name="Drums", instrument_uri="query:Drums#Kit_X"
    )


@pytest.fixture
def clip(conn, track):
    cid = M.create_clip(
        conn, track_id=track, slot=1, length_beats=16.0, name="verse_drums",
        section_role="verse",
    )
    M.insert_notes(
        conn,
        clip_id=cid,
        notes=[
            {"pitch": 36, "start_beats": 0.0, "duration_beats": 0.25, "velocity": 110,
             "tags": ["kick", "downbeat"]},
            {"pitch": 38, "start_beats": 1.04, "duration_beats": 0.25, "velocity": 100,
             "tags": ["snare", "backbeat"]},
        ],
    )
    return cid


# --- planning ---


def test_plan_push_clip_creates_track_when_unlinked(conn, session, track, clip):
    """Wave M-5: retargeted to unified ableton_track(action='create')."""
    plan = push.plan_push_clip(conn, clip_id=clip, session_id=session)
    assert len(plan.calls) == 1
    call = plan.calls[0]
    assert call.tool == "ableton_track"
    assert call.args["action"] == "create"
    assert call.args["kind"] == "midi"
    assert call.args["name"] == "Drums"
    assert call.args["instrument_uri"] == "query:Drums#Kit_X"
    assert call.key == f"track:{track}"
    # Should warn that we need to re-plan after track is linked
    assert any("track" in n for n in plan.notes)


def test_plan_push_clip_emits_atomic_create_when_track_linked_clip_unlinked(
    conn, session, track, clip
):
    """Wave M+1-1: planner emits the atomic single-call create with
    replace=True (instead of the prior 3-step `replace_session_clip`
    emulation). One round-trip instead of three; same end state."""
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="track", db_id=track, ableton_index=2
    )
    plan = push.plan_push_clip(conn, clip_id=clip, session_id=session)
    assert len(plan.calls) == 1
    call = plan.calls[0]
    assert call.tool == "ableton_clip"
    assert call.args["action"] == "create"
    assert call.args["location"] == "session"
    assert call.args["kind"] == "midi"
    assert call.args["replace"] is True
    assert call.args["track_index"] == 2
    assert call.args["clip_index"] == 1
    assert call.args["length"] == 16.0
    assert len(call.args["notes"]) == 2
    # Notes are converted to MCP shape (start_time / duration, no tags)
    n0 = call.args["notes"][0]
    assert "start_time" in n0 and "duration" in n0
    assert "tags" not in n0


def test_plan_push_clip_args_match_mcp_create_action_schema(
    conn, session, track, clip
):
    """Structural contract: every arg the planner emits for the unlinked-clip
    case must be a known param on `ableton_clip(action='create')`, and every
    required param on that action must be present in the planner's args
    (with `action` itself satisfying the dispatch). Catches drift in either
    direction — schema rename, schema removes a param, planner forgets a
    required param.

    Per the "Sync planner discipline" learning: a directly-callable tool
    (no alias) trusts the planner to match the real signature."""
    from hallucinote_mcp.actions import clip as _clip_actions  # noqa: F401 — registers
    from hallucinote_mcp.schema import all_actions

    create_action = next(
        a for a in all_actions()
        if a.tool == "ableton_clip" and a.name == "create"
    )
    schema_param_names = {p.name for p in create_action.params}
    required_param_names = {
        p.name for p in create_action.params if getattr(p, "required", True)
    }

    M.link_db_to_ableton(
        conn, session_id=session, db_kind="track", db_id=track, ableton_index=2
    )
    call = push.plan_push_clip(conn, clip_id=clip, session_id=session).calls[0]
    emitted = set(call.args.keys()) - {"action"}

    unknown = emitted - schema_param_names
    assert not unknown, (
        f"planner emitted args not on ableton_clip(create) schema: {sorted(unknown)}"
    )
    missing_required = required_param_names - emitted
    assert not missing_required, (
        "planner missing required ableton_clip(create) params: "
        f"{sorted(missing_required)}"
    )


def test_plan_push_clip_uses_replace_notes_when_already_linked(
    conn, session, track, clip
):
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="track", db_id=track, ableton_index=2
    )
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="clip", db_id=clip, ableton_index=1
    )
    plan = push.plan_push_clip(conn, clip_id=clip, session_id=session)
    # Wave M-3: in-place note replace retargets to the unified clip tool.
    call = plan.calls[0]
    assert call.tool == "ableton_clip"
    assert call.args["action"] == "replace_notes"
    assert call.args["location"] == "session"
    assert call.args["track_index"] == 2
    assert call.args["clip_index"] == 1
    # No `length` on in-place replace — that's a create-time field only.
    assert "length" not in call.args


def test_plan_push_clip_isolates_by_session(conn, song, track, clip):
    """Linking in session A doesn't affect planning under session B."""
    a = M.create_ableton_session(conn, song_id=song, name="a")
    b = M.create_ableton_session(conn, song_id=song, name="b")
    M.link_db_to_ableton(
        conn, session_id=a, db_kind="track", db_id=track, ableton_index=4
    )
    plan_b = push.plan_push_clip(conn, clip_id=clip, session_id=b)
    # Under session b, the track is still unlinked -> create call.
    # Wave M-5: unified ableton_track(action='create').
    assert plan_b.calls[0].tool == "ableton_track"
    assert plan_b.calls[0].args["action"] == "create"


# --- arrangement clips ---


def test_plan_push_arrangement_skips_unlinked_and_warns(
    conn, song, session, track, clip
):
    M.add_arrangement_clip(
        conn, song_id=song, track_id=track, clip_id=clip, start_bar=1, end_bar=16
    )
    plan = push.plan_push_arrangement(conn, song_id=song, session_id=session)
    # Track unlinked -> no batch op emitted, only warnings
    assert plan.calls == []
    assert any("track" in n.lower() for n in plan.notes)


def test_plan_push_arrangement_emits_one_duplicate_per_arrangement_clip(
    conn, song, session, track, clip
):
    """W3-D: planner emits N ``ableton_clip(duplicate_to_arrangement, …)``
    calls directly — one per arrangement_clips row. No more emulator
    batch wrapper; no agent-side decomposition burden.

    ``destination_bar`` (1-based) is converted to ``start_beats`` (cumulative
    beats from song start) via the meter-aware walker.
    """
    M.add_time_signature_point(
        conn, song_id=song, start_bar=1.0, numerator=4, denominator=4
    )
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="track", db_id=track, ableton_index=2
    )
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="clip", db_id=clip, ableton_index=1
    )
    aid = M.add_arrangement_clip(
        conn, song_id=song, track_id=track, clip_id=clip, start_bar=1.0, end_bar=16.0
    )
    plan = push.plan_push_arrangement(conn, song_id=song, session_id=session)
    assert len(plan.calls) == 1
    call = plan.calls[0]
    assert call.tool == "ableton_clip"
    assert call.args == {
        "action": "duplicate_to_arrangement",
        "track_index": 2,
        "clip_index": 1,
        "start_beats": 0.0,  # bar 1 -> beat 0
    }
    assert call.key == f"arrangement_clip:{aid}"
    # Pre-clear hygiene warning still surfaces.
    assert any("clear existing arrangement clips" in n for n in plan.notes)


def test_plan_push_arrangement_converts_bar_to_beats_per_meter(
    conn, song, session, track, clip
):
    """Bars convert with meter awareness. Bar 17 in 4/4 → 64 beats."""
    M.add_time_signature_point(
        conn, song_id=song, start_bar=1.0, numerator=4, denominator=4
    )
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="track", db_id=track, ableton_index=2
    )
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="clip", db_id=clip, ableton_index=1
    )
    M.add_arrangement_clip(
        conn, song_id=song, track_id=track, clip_id=clip,
        start_bar=17.0, end_bar=33.0,
    )
    plan = push.plan_push_arrangement(conn, song_id=song, session_id=session)
    assert plan.calls[0].args["start_beats"] == 64.0


def test_plan_push_arrangement_multiple_clips_emit_separate_calls(
    conn, song, session, track, clip
):
    """Three arrangement placements → three independent duplicate calls.
    Verifies the planner doesn't accidentally collapse them into one."""
    M.add_time_signature_point(
        conn, song_id=song, start_bar=1.0, numerator=4, denominator=4
    )
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="track", db_id=track, ableton_index=2
    )
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="clip", db_id=clip, ableton_index=1
    )
    for bar in (1.0, 17.0, 33.0):
        M.add_arrangement_clip(
            conn, song_id=song, track_id=track, clip_id=clip,
            start_bar=bar, end_bar=bar + 16.0,
        )
    plan = push.plan_push_arrangement(conn, song_id=song, session_id=session)
    assert len(plan.calls) == 3
    beats = [c.args["start_beats"] for c in plan.calls]
    assert sorted(beats) == [0.0, 64.0, 128.0]
    # Each call has a distinct arrangement_clip:{db_id} key.
    keys = {c.key for c in plan.calls}
    assert len(keys) == 3
    assert all(k.startswith("arrangement_clip:") for k in keys)


# --- apply_push_results ---


def test_apply_results_links_track_and_clip(conn, session, track, clip):
    push.apply_push_results(
        conn,
        [
            {"key": f"track:{track}", "ok": True, "tool": "ableton_track",
             "result": {"track_index": 5}},
            {"key": f"clip:{clip}", "ok": True, "tool": "ableton_clip",
             "result": {"clip_index": 3}},
        ],
        session_id=session,
    )
    assert Q.get_ableton_link(conn, session_id=session, db_kind="track", db_id=track) == 5
    assert Q.get_ableton_link(conn, session_id=session, db_kind="clip", db_id=clip) == 3


def test_apply_results_skips_failed_calls(conn, session, track):
    push.apply_push_results(
        conn,
        [
            {"key": f"track:{track}", "ok": False, "tool": "ableton_track",
             "error": "boom"},
        ],
        session_id=session,
    )
    assert Q.get_ableton_link(conn, session_id=session, db_kind="track", db_id=track) is None


def test_apply_results_links_arrangement_clip(conn, song, session, track, clip):
    """W3-D: per-call duplicate result carries `arrangement_clip_index`
    on the unified `ableton_clip(duplicate_to_arrangement)` tool."""
    aid = M.add_arrangement_clip(conn, song_id=song, track_id=track, clip_id=clip,
                                 start_bar=1.0, end_bar=16.0)
    push.apply_push_results(
        conn,
        [
            {"key": f"arrangement_clip:{aid}", "ok": True, "tool": "ableton_clip",
             "result": {"arrangement_clip_index": 0}},
        ],
        session_id=session,
    )
    assert (
        Q.get_ableton_link(conn, session_id=session, db_kind="arrangement_clip", db_id=aid)
        == 0
    )


def test_apply_results_accepts_cue_batch_ack(conn, song, session):
    """W3-B introduced `cue_batch:{song_id}` as the single-key result of
    the batched cue creation call. Apply must recognize the kind and
    treat it as ack-only (no DB binding to record — cue indexes aren't
    tracked in `ableton_links`)."""
    push.apply_push_results(
        conn,
        [
            {"key": f"cue_batch:{song}", "ok": True, "tool": "ableton_arrangement",
             "result": {"cue_count": 3,
                        "cues": [{"cue_index": 1, "position_beats": 0.0, "name": "intro"}]}},
        ],
        session_id=session,
    )
    # No exception = test passes (the bug pre-fix was unknown-kind raise).


def test_apply_results_rejects_obsolete_arrangement_batch_key(conn, song, session):
    """W3-D dropped the `arrangement_batch:` kind. A stale caller that
    still emits it must FAIL LOUDLY rather than silently no-op, so the
    drift surfaces at the boundary."""
    with pytest.raises(ValueError, match="unknown push result key kind 'arrangement_batch'"):
        push.apply_push_results(
            conn,
            [
                {"key": f"arrangement_batch:{song}", "ok": True,
                 "tool": "batch_arrangement_layout", "result": {}},
            ],
            session_id=session,
        )


def test_apply_results_rejects_obsolete_cue_point_key(conn, song, session):
    """W3-B dropped the per-cue `cue_point:` kind in favor of batched
    `cue_batch:`. A stale caller emitting `cue_point:` must FAIL LOUDLY."""
    with pytest.raises(ValueError, match="unknown push result key kind 'cue_point'"):
        push.apply_push_results(
            conn,
            [
                {"key": "cue_point:abc123", "ok": True,
                 "tool": "create_cue_point", "result": {}},
            ],
            session_id=session,
        )


def test_apply_results_records_actor_sync_by_default(conn, session, track):
    push.apply_push_results(
        conn,
        [
            {"key": f"track:{track}", "ok": True, "tool": "ableton_track",
             "result": {"track_index": 5}},
        ],
        session_id=session,
    )
    rows = conn.execute(
        "SELECT actor FROM events WHERE kind='ableton_link_set' ORDER BY seq"
    ).fetchall()
    assert [r["actor"] for r in rows] == ["sync"]


def test_apply_results_rolls_back_on_mid_batch_failure(conn, session, track, clip):
    """A mid-batch unknown-kind raise must undo every link applied so far.

    Regression for the "with conn:" no-op (autocommit mode) — previously the
    first track-link committed before the unknown-kind raised, leaving the
    session half-updated.
    """
    pre_track_link = Q.get_ableton_link(
        conn, session_id=session, db_kind="track", db_id=track,
    )
    pre_clip_link = Q.get_ableton_link(
        conn, session_id=session, db_kind="clip", db_id=clip,
    )
    assert pre_track_link is None and pre_clip_link is None

    with pytest.raises(ValueError, match="unknown push result key kind"):
        push.apply_push_results(
            conn,
            [
                # This one would succeed in isolation.
                {"key": f"track:{track}", "ok": True,
                 "tool": "ableton_track", "result": {"track_index": 5}},
                # This raises mid-batch.
                {"key": "frobnicate:abc123", "ok": True,
                 "tool": "frobnicate", "result": {}},
                # This never runs.
                {"key": f"clip:{clip}", "ok": True,
                 "tool": "ableton_clip", "result": {"clip_index": 3}},
            ],
            session_id=session,
        )

    # Neither link landed.
    assert (
        Q.get_ableton_link(conn, session_id=session, db_kind="track", db_id=track)
        is None
    )
    assert (
        Q.get_ableton_link(conn, session_id=session, db_kind="clip", db_id=clip)
        is None
    )


# ---------------------------------------------------------------------------
# ALIASES_TODAY ceiling — locked at <=5 per Wave M-5 build plan
# ---------------------------------------------------------------------------


def test_aliases_today_at_or_below_ceiling():
    """The build plan's M-5 goal was 'final alias table cleanup: <=5 entries
    remain (only genuinely-not-ready things).' Lock the contraction so a
    well-meaning future PR that adds a planner-canonical name without an
    MCP-side implementation gets caught: any growth past 5 should be a
    deliberate decision, not an accident.

    Each remaining entry is a genuine multi-step emulation or hard MCP
    gap; see `mcp_names.py` docstring + per-entry comments for the
    canonical inventory (don't restate the count here — that's drift bait).
    """
    from hallucinote.sync.mcp_names import ALIASES_TODAY
    assert len(ALIASES_TODAY) <= 5, (
        f"ALIASES_TODAY grew to {len(ALIASES_TODAY)} entries — Wave M-5 set "
        "the ceiling at 5. Either: (a) retarget the new alias to a unified "
        "MCP action, OR (b) document why it's a genuine emulation and bump "
        "the ceiling deliberately. Current entries: "
        f"{sorted(ALIASES_TODAY.keys())}"
    )
