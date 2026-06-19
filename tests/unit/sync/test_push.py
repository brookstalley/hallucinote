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


def test_plan_push_clip_raises_when_track_not_linked(conn, session, clip):
    """W3-C: plan_push_clip is strict on track-link precondition. The
    old behavior — silently emit a per-clip ableton_track(create) — was
    a footgun (8-track / 32-clip songs produced 32 redundant create
    calls). The strict raise forces callers onto the correct flow:
    plan_push_song_tracks → apply → plan_push_clip."""
    with pytest.raises(ValueError, match="plan_push_song_tracks.*first"):
        push.plan_push_clip(conn, clip_id=clip, session_id=session)


# --- plan_push_song_tracks (W3-C pre-pass) ---


def test_plan_push_song_tracks_emits_one_call_per_unique_unlinked_track(
    conn, song, session
):
    """Headline: an N-track song with M clips/track produces N calls
    (the unique-track count), not N×M. Dedupe is structural."""
    # 3 tracks, no links, each with multiple clips.
    track_ids = []
    for i in (1, 2, 3):
        tid = M.create_track(
            conn, song_id=song, track_index=i, name=f"T{i}", kind="midi",
        )
        track_ids.append(tid)
        for slot in (1, 2, 3, 4):
            M.create_clip(conn, track_id=tid, slot=slot, name=f"T{i}-c{slot}", length_beats=4.0)

    plan = push.plan_push_song_tracks(conn, song_id=song, session_id=session)

    assert len(plan.calls) == 3, "one create call per unique unlinked track (3 tracks, NOT 12 clips)"
    keys = sorted(c.key for c in plan.calls)
    assert keys == sorted(f"track:{tid}" for tid in track_ids)
    for call in plan.calls:
        assert call.tool == "ableton_track"
        assert call.args["action"] == "create"
        assert call.args["kind"] == "midi"


def test_plan_push_song_tracks_skips_master(conn, song, session):
    """Master is not a Live-side createable surface. The mutator allows
    creating a kind='master' row in `tracks` (Hallucinote's projection);
    push must not try to ableton_track(create) it."""
    M.create_track(conn, song_id=song, track_index=0, name="Master", kind="master")
    plan = push.plan_push_song_tracks(conn, song_id=song, session_id=session)
    assert plan.calls == []


def test_plan_push_song_tracks_skips_already_linked(conn, song, session):
    """Idempotent: re-running after a partial push doesn't re-emit
    creates for tracks now linked."""
    tid_a = M.create_track(conn, song_id=song, track_index=1, name="A", kind="midi")
    tid_b = M.create_track(conn, song_id=song, track_index=2, name="B", kind="midi")
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="track", db_id=tid_a, ableton_index=1,
    )

    plan = push.plan_push_song_tracks(conn, song_id=song, session_id=session)
    assert len(plan.calls) == 1
    assert plan.calls[0].key == f"track:{tid_b}"


def test_plan_push_song_tracks_isolates_by_session(conn, song):
    """A track linked under session A is still unlinked under session B —
    plan_push_song_tracks must respect the session boundary."""
    a = M.create_ableton_session(conn, song_id=song, name="A")
    b = M.create_ableton_session(conn, song_id=song, name="B")
    tid = M.create_track(conn, song_id=song, track_index=1, name="Solo", kind="midi")
    M.link_db_to_ableton(conn, session_id=a, db_kind="track", db_id=tid, ableton_index=4)

    plan_a = push.plan_push_song_tracks(conn, song_id=song, session_id=a)
    assert plan_a.calls == []
    plan_b = push.plan_push_song_tracks(conn, song_id=song, session_id=b)
    assert len(plan_b.calls) == 1
    assert plan_b.calls[0].key == f"track:{tid}"


def test_plan_push_song_tracks_propagates_instrument_uri(conn, song, session):
    """When a DB track has an instrument_uri, the create call carries it
    so apply_push_results can record the agent's follow-up device load."""
    tid = M.create_track(
        conn, song_id=song, track_index=1, name="Op",
        instrument_uri="query:Synths#Operator", kind="midi",
    )
    plan = push.plan_push_song_tracks(conn, song_id=song, session_id=session)
    assert plan.calls[0].args["instrument_uri"] == "query:Synths#Operator"


def test_plan_push_song_tracks_no_calls_when_empty_song(conn, song, session):
    """Vacuously-correct empty case."""
    plan = push.plan_push_song_tracks(conn, song_id=song, session_id=session)
    assert plan.calls == []
    assert plan.notes == []


# --- plan_push_song_returns (W3-C pre-pass) ---


def test_plan_push_song_returns_emits_one_call_per_unique_unlinked(conn, song, session):
    rid_a = M.create_return(conn, song_id=song, name="A-Reverb", position=1)
    rid_b = M.create_return(conn, song_id=song, name="B-Delay", position=2)
    plan = push.plan_push_song_returns(conn, song_id=song, session_id=session)
    assert {c.key for c in plan.calls} == {f"return:{rid_a}", f"return:{rid_b}"}
    for c in plan.calls:
        assert c.tool == "ableton_return"
        assert c.args["action"] == "create"


def test_plan_push_song_returns_skips_already_linked(conn, song, session):
    rid_a = M.create_return(conn, song_id=song, name="A-Reverb", position=1)
    rid_b = M.create_return(conn, song_id=song, name="B-Delay", position=2)
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="return", db_id=rid_a, ableton_index=1,
    )
    plan = push.plan_push_song_returns(conn, song_id=song, session_id=session)
    assert len(plan.calls) == 1
    assert plan.calls[0].key == f"return:{rid_b}"


def test_plan_push_song_returns_idempotent_after_probe_and_link(
    conn, song, session,
):
    """W10-A / C2 regression: probe-and-link on a Live set whose returns
    carry the slot-letter prefix ('A-Reverb', 'B-Delay') must link them
    to the DB's suffix-only names ('Reverb', 'Delay'), and the returns
    planner must then emit ZERO create calls.

    Pre-fix C2 bug: even though probe-and-link strips the prefix, a
    naming-only mismatch (the DB stored 'Foo Reverb' while Live's
    default is 'A-Reverb') would leave returns unmatched, the planner
    would emit `create`, and Live would end up with both default
    returns AND a duplicate song-named return. This test pins the
    happy-path matched case end-to-end so a regression in either the
    probe matcher OR the planner skip surfaces here.
    """
    M.create_return(conn, song_id=song, name="Reverb", position=1)
    M.create_return(conn, song_id=song, name="Delay", position=2)
    # Simulate Live's default new-set scaffolding.
    result = push.probe_and_link(
        conn, song_id=song, session_id=session,
        live_tracks=[],
        live_returns=[
            {"return_index": 1, "name": "A-Reverb"},
            {"return_index": 2, "name": "B-Delay"},
        ],
    )
    assert len(result.matched_returns) == 2, result
    # The returns planner now sees both linked → must emit nothing.
    plan = push.plan_push_song_returns(
        conn, song_id=song, session_id=session,
    )
    assert plan.calls == [], (
        f"returns plan should be empty post-probe-and-link but got: "
        f"{[c.args for c in plan.calls]}"
    )


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
    """Linking in session A doesn't satisfy plan_push_clip under session B.
    Post-W3-C: the strict raise must fire — wrong-session links are
    indistinguishable from missing links."""
    a = M.create_ableton_session(conn, song_id=song, name="a")
    b = M.create_ableton_session(conn, song_id=song, name="b")
    M.link_db_to_ableton(
        conn, session_id=a, db_kind="track", db_id=track, ableton_index=4
    )
    # Under session b, the track is still unlinked → strict raise.
    with pytest.raises(ValueError, match="plan_push_song_tracks.*first"):
        push.plan_push_clip(conn, clip_id=clip, session_id=b)


# --- arrangement clips ---


def test_plan_push_arrangement_skips_on_unlinked_track(
    conn, song, session, track, clip
):
    """W10-G post-Wave-0 normalization: planners skip-and-warn instead of
    raising on unlinked deps. Wave 0's full-band-rock canary surfaced the
    prior strict-raise as a Python traceback through the CLI when an
    earlier phase failed partway — agent had no way to continue. Now the
    row is skipped, a teaching note appears, and the rest of the
    arrangement still planned (the agent can choose to abort if any row
    skips, but the choice is theirs)."""
    M.add_arrangement_clip(
        conn, song_id=song, track_id=track, clip_id=clip, start_bar=1, end_bar=16
    )
    plan = push.plan_push_arrangement(conn, song_id=song, session_id=session)
    assert plan.calls == []  # nothing emitted (track not linked)
    assert any(
        "not linked" in n and "plan_push_song_tracks" in n
        for n in plan.notes
    ), f"expected teaching note pointing at plan_push_song_tracks; got {plan.notes}"


def test_plan_push_arrangement_skips_on_unlinked_clip(
    conn, song, session, track, clip
):
    """When track IS linked but the session clip isn't, the note points
    at the clip-create phase. Same skip-and-warn shape as the unlinked-
    track case (W10-G)."""
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="track", db_id=track, ableton_index=2
    )
    M.add_arrangement_clip(
        conn, song_id=song, track_id=track, clip_id=clip, start_bar=1, end_bar=16
    )
    plan = push.plan_push_arrangement(conn, song_id=song, session_id=session)
    assert plan.calls == []
    assert any(
        "not linked" in n and "clip-create phase" in n
        for n in plan.notes
    ), f"expected teaching note pointing at clip-create phase; got {plan.notes}"


def test_plan_push_arrangement_partial_state_emits_linked_rows_only(
    conn, song, session, track, clip,
):
    """W10-G: when some rows are linked and others aren't, the planner
    emits calls for the linked ones and warns about the rest — partial
    progress is the right shape (vs. all-or-nothing raising)."""
    # Track is linked; only one of two clips is.
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="track", db_id=track, ableton_index=1
    )
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="clip", db_id=clip, ableton_index=1,
    )
    # Add a second clip; do NOT link it.
    other_clip = M.create_clip(
        conn, track_id=track, slot=2, length_beats=16.0, name="other"
    )
    M.add_arrangement_clip(
        conn, song_id=song, track_id=track, clip_id=clip,
        start_bar=1, end_bar=5,
    )
    M.add_arrangement_clip(
        conn, song_id=song, track_id=track, clip_id=other_clip,
        start_bar=5, end_bar=9,
    )
    plan = push.plan_push_arrangement(conn, song_id=song, session_id=session)
    assert len(plan.calls) == 1  # only the linked clip's placement
    assert any("not linked" in n for n in plan.notes)


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


# --- arrangement idempotency (W10-A) ---


def test_plan_push_arrangement_refreshes_notes_on_already_linked_placements(
    conn, song, session, track, clip
):
    """PSH-6W2J: a re-push must NOT re-duplicate an already-linked placement
    (W10-A's idempotency intent), but it MUST refresh the placement's notes.

    The pre-PSH-6W2J behavior `assert plan.calls == []` ENCODED THE BUG: an
    arrangement clip is a distinct Live copy, so skipping the linked placement
    entirely left it frozen at first-materialization — a later note edit to the
    session clip never reached the arrangement (silent stale render/playback).
    The corrected contract: emit exactly one `replace_notes`/`location=arrangement`
    refresh (idempotent on placement — no `duplicate_to_arrangement`), keyed
    `arrangement_clip_notes:` so apply records no new binding.
    """
    M.add_time_signature_point(
        conn, song_id=song, start_bar=1.0, numerator=4, denominator=4
    )
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="track", db_id=track, ableton_index=2,
    )
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="clip", db_id=clip, ableton_index=1,
    )
    aid = M.add_arrangement_clip(
        conn, song_id=song, track_id=track, clip_id=clip,
        start_bar=1.0, end_bar=16.0,
    )
    # First push lands and apply_push_results records the binding.
    push.apply_push_results(
        conn,
        [{
            "key": f"arrangement_clip:{aid}",
            "ok": True,
            "tool": "ableton_clip",
            "result": {"arrangement_clip_index": 3},
        }],
        session_id=session,
    )
    # Re-run the planner — it must refresh (not re-duplicate) the linked placement.
    plan = push.plan_push_arrangement(conn, song_id=song, session_id=session)
    assert len(plan.calls) == 1, (
        f"re-push should emit exactly one note-refresh call, got: "
        f"{[c.args for c in plan.calls]}"
    )
    call = plan.calls[0]
    assert call.key == f"arrangement_clip_notes:{aid}"
    assert call.tool == "ableton_clip"
    assert call.args["action"] == "replace_notes"
    assert call.args["location"] == "arrangement"
    assert call.args["track_index"] == 2
    assert call.args["clip_index"] == 3  # the recorded arrangement_clip_index
    assert len(call.args["notes"]) == 2  # the `clip` fixture's two notes
    # No re-duplication.
    assert all(
        c.args.get("action") != "duplicate_to_arrangement" for c in plan.calls
    ), "must not re-duplicate an already-linked placement"
    # Idempotency note reflects the refresh, not a silent skip.
    assert any(
        "refreshed notes" in n and "no re-duplication" in n
        for n in plan.notes
    ), f"expected a refresh idempotency note, got: {plan.notes}"


def test_plan_push_arrangement_partial_state_emits_unlinked_only(
    conn, song, session, track, clip
):
    """W10-A: when SOME placements are linked and others aren't, only
    the unlinked ones emit. Mixed-state re-runs (e.g., a partial
    apply_push_results between two pushes) must not re-duplicate
    already-pushed placements.
    """
    M.add_time_signature_point(
        conn, song_id=song, start_bar=1.0, numerator=4, denominator=4
    )
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="track", db_id=track, ableton_index=2,
    )
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="clip", db_id=clip, ableton_index=1,
    )
    aids = [
        M.add_arrangement_clip(
            conn, song_id=song, track_id=track, clip_id=clip,
            start_bar=bar, end_bar=bar + 16.0,
        )
        for bar in (1.0, 17.0, 33.0)
    ]
    # First push lands for the first two placements only — the third
    # never made it to apply (network blip, batched run cut short, etc).
    push.apply_push_results(
        conn,
        [
            {"key": f"arrangement_clip:{aids[0]}", "ok": True,
             "tool": "ableton_clip", "result": {"arrangement_clip_index": 0}},
            {"key": f"arrangement_clip:{aids[1]}", "ok": True,
             "tool": "ableton_clip", "result": {"arrangement_clip_index": 1}},
        ],
        session_id=session,
    )
    plan = push.plan_push_arrangement(conn, song_id=song, session_id=session)
    # PSH-6W2J: the two linked placements now emit note-refresh calls, and the
    # third (unlinked) emits a duplicate. Exactly one duplicate; two refreshes.
    dup_calls = [c for c in plan.calls if c.args["action"] == "duplicate_to_arrangement"]
    refresh_calls = [c for c in plan.calls if c.args["action"] == "replace_notes"]
    assert len(dup_calls) == 1
    assert dup_calls[0].key == f"arrangement_clip:{aids[2]}"
    assert sorted(c.key for c in refresh_calls) == sorted(
        f"arrangement_clip_notes:{aids[i]}" for i in (0, 1)
    )


def test_plan_push_arrangement_clear_warn_only_for_unlinked_placements(
    conn, song, session, track, clip
):
    """W10-A: the 'agent must clear existing arrangement clips' warn
    targets the C3 paper-cut (user re-pushes onto a Live set whose
    arrangement isn't empty). It should NOT fire when every placement
    is already linked — that's the idempotent re-run case and there's
    nothing to clear or duplicate.
    """
    M.add_time_signature_point(
        conn, song_id=song, start_bar=1.0, numerator=4, denominator=4
    )
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="track", db_id=track, ableton_index=2,
    )
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="clip", db_id=clip, ableton_index=1,
    )
    aid = M.add_arrangement_clip(
        conn, song_id=song, track_id=track, clip_id=clip,
        start_bar=1.0, end_bar=16.0,
    )
    push.apply_push_results(
        conn,
        [{"key": f"arrangement_clip:{aid}", "ok": True,
          "tool": "ableton_clip", "result": {"arrangement_clip_index": 0}}],
        session_id=session,
    )
    plan = push.plan_push_arrangement(conn, song_id=song, session_id=session)
    assert all(
        "clear existing arrangement clips" not in n for n in plan.notes
    ), (
        "the 'must clear' warn must NOT fire when re-push has nothing to "
        f"emit, but got: {plan.notes}"
    )


def test_plan_push_arrangement_clear_warn_still_fires_on_truly_new_push(
    conn, song, session, track, clip
):
    """Counterpart to the above: the 'must clear' warn still surfaces
    for the actual case it targets — a first-time push with unlinked
    placements. We don't want to lose the C3 teaching just to suppress
    the idempotent-case false fire.
    """
    M.add_time_signature_point(
        conn, song_id=song, start_bar=1.0, numerator=4, denominator=4
    )
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="track", db_id=track, ableton_index=2,
    )
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="clip", db_id=clip, ableton_index=1,
    )
    M.add_arrangement_clip(
        conn, song_id=song, track_id=track, clip_id=clip,
        start_bar=1.0, end_bar=16.0,
    )
    plan = push.plan_push_arrangement(conn, song_id=song, session_id=session)
    assert len(plan.calls) == 1
    assert any(
        "clear existing arrangement clips" in n for n in plan.notes
    )


# --- PSH-6W2J: arrangement-copy note propagation ---


def _link_and_place(conn, *, song, session, track, clip, start_bar, arr_index):
    """Add an arrangement placement and record its (track, arrangement_clip)
    links as if a first push had materialized it. Returns the placement id."""
    aid = M.add_arrangement_clip(
        conn, song_id=song, track_id=track, clip_id=clip,
        start_bar=start_bar, end_bar=start_bar + 16.0,
    )
    push.apply_push_results(
        conn,
        [{"key": f"arrangement_clip:{aid}", "ok": True, "tool": "ableton_clip",
          "result": {"arrangement_clip_index": arr_index}}],
        session_id=session,
    )
    return aid


def test_plan_push_arrangement_clip_notes_one_call_per_linked_placement(
    conn, song, session, track, clip
):
    """A session clip placed at three arrangement positions refreshes all three
    copies — one replace_notes(location='arrangement') per linked placement."""
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="track", db_id=track, ableton_index=2,
    )
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="clip", db_id=clip, ableton_index=1,
    )
    aids = [
        _link_and_place(
            conn, song=song, session=session, track=track, clip=clip,
            start_bar=bar, arr_index=idx,
        )
        for bar, idx in ((1.0, 0), (17.0, 1), (33.0, 2))
    ]
    plan = push.plan_push_arrangement_clip_notes(
        conn, clip_id=clip, session_id=session
    )
    assert sorted(c.key for c in plan.calls) == sorted(
        f"arrangement_clip_notes:{aid}" for aid in aids
    )
    for c in plan.calls:
        assert c.args["action"] == "replace_notes"
        assert c.args["location"] == "arrangement"
        assert c.args["track_index"] == 2
        assert len(c.args["notes"]) == 2


def test_plan_push_arrangement_clip_notes_skips_unlinked_placement(
    conn, song, session, track, clip
):
    """An arrangement placement with no recorded link is NOT refreshed — it will
    be created by the duplicate path, not refreshed in place."""
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="track", db_id=track, ableton_index=2,
    )
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="clip", db_id=clip, ableton_index=1,
    )
    # Placement exists in the DB but was never materialized/linked.
    M.add_arrangement_clip(
        conn, song_id=song, track_id=track, clip_id=clip,
        start_bar=1.0, end_bar=16.0,
    )
    plan = push.plan_push_arrangement_clip_notes(
        conn, clip_id=clip, session_id=session
    )
    assert plan.calls == []


def test_plan_push_arrangement_clip_notes_skips_audio_source(
    conn, song, session
):
    """An audio source clip has no notes — its arrangement copy is not
    refreshed (audio-clip sync is CLP-AUD2 scope)."""
    atrack = M.create_track(
        conn, song_id=song, track_index=2, name="Stems", kind="audio",
    )
    aclip = M.create_audio_clip(
        conn, track_id=atrack, slot=1, length_beats=16.0,
        audio_file="assets/stab.wav", name="stab",
    )
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="track", db_id=atrack, ableton_index=2,
    )
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="clip", db_id=aclip, ableton_index=1,
    )
    _link_and_place(
        conn, song=song, session=session, track=atrack, clip=aclip,
        start_bar=1.0, arr_index=0,
    )
    plan = push.plan_push_arrangement_clip_notes(
        conn, clip_id=aclip, session_id=session
    )
    assert plan.calls == []


def test_plan_push_arrangement_unrefreshable_linked_placement_named_in_note(
    conn, song, session, track, clip
):
    """A linked placement whose TRACK link is missing can't be refreshed; the
    idempotency note must name the gap rather than claim everything was refreshed
    (a silent stale copy is the whole bug PSH-6W2J fixes)."""
    M.add_time_signature_point(
        conn, song_id=song, start_bar=1.0, numerator=4, denominator=4
    )
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="clip", db_id=clip, ableton_index=1,
    )
    aid = M.add_arrangement_clip(
        conn, song_id=song, track_id=track, clip_id=clip,
        start_bar=1.0, end_bar=16.0,
    )
    # Record the arrangement_clip link but NOT the track link.
    push.apply_push_results(
        conn,
        [{"key": f"arrangement_clip:{aid}", "ok": True, "tool": "ableton_clip",
          "result": {"arrangement_clip_index": 0}}],
        session_id=session,
    )
    plan = push.plan_push_arrangement(conn, song_id=song, session_id=session)
    assert plan.calls == [], "no refresh emitted when the track link is missing"
    assert any("not refreshed" in n for n in plan.notes), (
        f"expected the note to name the unrefreshed placement, got: {plan.notes}"
    )


# --- check_coherence (W18-A) ---


def test_check_coherence_ok_when_links_match_probe(conn, song, session):
    """Happy path: links written by probe-and-link match a fresh probe →
    coherence passes, execute is safe."""
    tid = M.create_track(conn, song_id=song, track_index=1, name="Drums", kind="midi")
    M.create_return(conn, song_id=song, name="Reverb", position=1)
    push.probe_and_link(
        conn, song_id=song, session_id=session,
        live_tracks=[{"track_index": 5, "name": "Drums", "kind": "midi"}],
        live_returns=[{"return_index": 1, "name": "A-Reverb"}],
    )

    result = push.check_coherence(
        conn,
        session_id=session,
        live_tracks=[{"track_index": 5, "name": "Drums"}],
        live_returns=[{"return_index": 1, "name": "A-Reverb"}],
    )
    assert result.ok is True
    assert result.errors == []


def test_check_coherence_refuses_when_session_missing(conn):
    """Session row absent (e.g. build.py --reset wiped ableton_sessions) →
    refuse with session_missing + recovery hint pointing at --auto-session."""
    result = push.check_coherence(
        conn,
        session_id="nonexistent-session-id",
        live_tracks=[],
        live_returns=[],
    )
    assert result.ok is False
    assert len(result.errors) == 1
    err = result.errors[0]
    assert err["kind"] == "session_missing"
    assert "nonexistent-session-id" in err["detail"]
    assert "--auto-session" in err["recovery"]


def test_check_coherence_refuses_on_stale_track_link(conn, song, session):
    """The punk-fate post-cleanup repro: user deletes Live track 5 after
    probe-and-link wrote the link → fresh probe omits index 5 → refuse
    and surface recovery hint."""
    tid = M.create_track(conn, song_id=song, track_index=1, name="Drums", kind="midi")
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="track", db_id=tid, ableton_index=5,
    )

    # Fresh probe shows index 5 gone (user deleted that track in Live).
    result = push.check_coherence(
        conn,
        session_id=session,
        live_tracks=[{"track_index": 1, "name": "1-MIDI"}],
        live_returns=[],
    )
    assert result.ok is False
    assert len(result.errors) == 1
    err = result.errors[0]
    assert err["kind"] == "stale_track_links"
    assert "5" in err["detail"]
    assert "probe-and-link" in err["recovery"]


def test_check_coherence_refuses_on_stale_return_link(conn, song, session):
    """Same shape for returns: link points at return_index that's no longer
    in the live probe."""
    rid = M.create_return(conn, song_id=song, name="Reverb", position=1)
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="return", db_id=rid, ableton_index=2,
    )

    result = push.check_coherence(
        conn,
        session_id=session,
        live_tracks=[],
        live_returns=[{"return_index": 1, "name": "A-Reverb"}],
    )
    assert result.ok is False
    assert len(result.errors) == 1
    assert result.errors[0]["kind"] == "stale_return_links"


def test_check_coherence_accumulates_track_and_return_errors(conn, song, session):
    """Both stale track and stale return → two distinct error entries so
    the user sees the full picture in one refusal."""
    tid = M.create_track(conn, song_id=song, track_index=1, name="Drums", kind="midi")
    rid = M.create_return(conn, song_id=song, name="Reverb", position=1)
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="track", db_id=tid, ableton_index=7,
    )
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="return", db_id=rid, ableton_index=3,
    )

    result = push.check_coherence(
        conn,
        session_id=session,
        live_tracks=[{"track_index": 1, "name": "T"}],
        live_returns=[{"return_index": 1, "name": "A-Reverb"}],
    )
    assert result.ok is False
    kinds = {e["kind"] for e in result.errors}
    assert kinds == {"stale_track_links", "stale_return_links"}


def test_check_coherence_passes_session_with_no_links_yet(conn, song, session):
    """First-push scenario: session minted via --auto-session but no
    probe-and-link links exist yet → check passes with an informational
    note (push will create from scratch — fine if Live truly has no
    matching tracks)."""
    result = push.check_coherence(
        conn,
        session_id=session,
        live_tracks=[{"track_index": 1, "name": "1-MIDI"}],
        live_returns=[{"return_index": 1, "name": "A-Reverb"}],
    )
    assert result.ok is True
    assert result.errors == []
    assert any("no ableton_links rows" in n for n in result.notes)


def test_check_coherence_ignores_nested_link_kinds(conn, song, session):
    """clip / device / device_chain links are nested under track / return;
    a stale parent link cascade-invalidates them. The check focuses on
    parent-level integrity — nested kinds aren't validated directly
    (would require deep MCP traffic for marginal extra safety)."""
    tid = M.create_track(conn, song_id=song, track_index=1, name="T", kind="midi")
    cid = M.create_clip(conn, track_id=tid, slot=1, length_beats=4.0, name="c")
    # Link the track validly, plus a clip link whose ableton_index we
    # don't have probe data for.
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="track", db_id=tid, ableton_index=3,
    )
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="clip", db_id=cid, ableton_index=0,
    )

    # Probe shows track 3 still there. Nested clip link is not validated;
    # check passes.
    result = push.check_coherence(
        conn,
        session_id=session,
        live_tracks=[{"track_index": 3, "name": "T"}],
        live_returns=[],
    )
    assert result.ok is True


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
