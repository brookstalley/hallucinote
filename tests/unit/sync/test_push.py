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
    M.create_track(
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


def test_plan_push_arrangement_fresh_materialize_creates_and_fills(
    conn, song, session, track, clip
):
    """ARR-PROJ: a note-only placement materializes via create+fill — a FRESH
    arrangement clip filled directly from the DB notes (``ableton_clip(action=
    'create', location='arrangement')``), NOT ``duplicate_to_arrangement``. So
    Live's B-24 overlap-split cannot occur and no ``replace_notes``-in-place
    (the §6b-A orphan path) is used. Empty probe → no clear (fresh timeline)."""
    M.add_time_signature_point(
        conn, song_id=song, start_bar=1.0, numerator=4, denominator=4
    )
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="track", db_id=track, ableton_index=2
    )
    aid = M.add_arrangement_clip(
        conn, song_id=song, track_id=track, clip_id=clip, start_bar=1.0, end_bar=16.0
    )
    plan = push.plan_push_arrangement(
        conn, song_id=song, session_id=session,
        live_arrangement_clips_by_track={2: []},  # track linked, timeline empty
    )
    assert len(plan.calls) == 1
    call = plan.calls[0]
    assert call.tool == "ableton_clip"
    assert call.args["action"] == "create"
    assert call.args["location"] == "arrangement"
    assert call.args["kind"] == "midi"
    assert call.args["track_index"] == 2
    assert call.args["start_beats"] == 0.0  # bar 1 -> beat 0
    assert call.args["length"] == 16.0  # clip.length_beats
    assert call.args["name"] == "verse_drums"
    assert len(call.args["notes"]) == 2  # the fixture's two notes
    assert call.key == f"arrangement_clip:{aid}"
    # No duplicate, no replace_notes anywhere.
    assert all(c.args["action"] == "create" for c in plan.calls)


def test_plan_push_arrangement_create_fill_needs_no_clip_link(
    conn, song, session, track, clip
):
    """ARR-PROJ vs the old duplicate model: create+fill reads notes from the DB
    and writes a fresh arrangement clip, so a note-only placement does NOT need
    the session clip linked (the old duplicate path did). Only the TRACK link is
    required."""
    M.add_time_signature_point(
        conn, song_id=song, start_bar=1.0, numerator=4, denominator=4
    )
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="track", db_id=track, ableton_index=2
    )
    # clip deliberately NOT linked
    M.add_arrangement_clip(
        conn, song_id=song, track_id=track, clip_id=clip, start_bar=1.0, end_bar=16.0
    )
    plan = push.plan_push_arrangement(
        conn, song_id=song, session_id=session,
        live_arrangement_clips_by_track={2: []},
    )
    assert len(plan.calls) == 1
    assert plan.calls[0].args["action"] == "create"


def test_plan_push_arrangement_rematerialize_clears_descending_then_creates(
    conn, song, session, track, clip
):
    """ARR-PROJ keystone: re-materializing onto an OCCUPIED timeline emits the
    track's existing clips as descending-index deletes FIRST, then the
    create+fill — clear-then-rebuild, never stack onto the old clips. This is
    the structural reason the 2026-06-21 stacking witness (ARR-9X4T) cannot be
    produced. Descending order keeps each delete valid against the pre-clear
    snapshot (Live renumbers indices down after each delete)."""
    M.add_time_signature_point(
        conn, song_id=song, start_bar=1.0, numerator=4, denominator=4
    )
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="track", db_id=track, ableton_index=2
    )
    aid = M.add_arrangement_clip(
        conn, song_id=song, track_id=track, clip_id=clip, start_bar=1.0, end_bar=16.0
    )
    # Live already has 3 arrangement clips on track 2 (a prior push / hand edit).
    live = {2: [
        {"arrangement_clip_index": 1, "start_beats": 0.0},
        {"arrangement_clip_index": 2, "start_beats": 16.0},
        {"arrangement_clip_index": 3, "start_beats": 32.0},
    ]}
    plan = push.plan_push_arrangement(
        conn, song_id=song, session_id=session,
        live_arrangement_clips_by_track=live,
    )
    # 3 deletes (descending index) THEN 1 create — exact dispatch order.
    seq = [(c.args["action"], c.args.get("clip_index")) for c in plan.calls]
    assert seq == [
        ("delete", 3), ("delete", 2), ("delete", 1), ("create", None),
    ]
    deletes = [c for c in plan.calls if c.args["action"] == "delete"]
    assert all(c.args["location"] == "arrangement" for c in deletes)
    assert all(c.key.startswith("arrangement_clip_clear:") for c in deletes)
    create = plan.calls[-1]
    assert create.key == f"arrangement_clip:{aid}"


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
    M.add_arrangement_clip(
        conn, song_id=song, track_id=track, clip_id=clip,
        start_bar=17.0, end_bar=33.0,
    )
    plan = push.plan_push_arrangement(
        conn, song_id=song, session_id=session,
        live_arrangement_clips_by_track={2: []},
    )
    assert plan.calls[0].args["action"] == "create"
    assert plan.calls[0].args["start_beats"] == 64.0


def test_plan_push_arrangement_alerts_only_on_placements_past_a_meter_change(
    conn, song, session, track, clip
):
    """The two-ruler alert has to discriminate, or it is noise on every
    odd-meter song. A placement BEFORE the first meter change translates
    identically under both rulers, so it must not raise the alert; one AFTER
    it does, and the alert names the two beat positions."""
    M.add_time_signature_point(
        conn, song_id=song, start_bar=1.0, numerator=4, denominator=4
    )
    M.add_time_signature_point(
        conn, song_id=song, start_bar=9.0, numerator=7, denominator=4
    )
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="track", db_id=track, ableton_index=2
    )
    # Bar 5 is before the change: map and uniform math both say beat 16.
    M.add_arrangement_clip(
        conn, song_id=song, track_id=track, clip_id=clip,
        start_bar=5.0, end_bar=9.0,
    )
    plan = push.plan_push_arrangement(
        conn, song_id=song, session_id=session,
        live_arrangement_clips_by_track={2: []},
    )
    assert not any("bar rulers" in a for a in plan.alerts), (
        "a placement before the meter change diverges nowhere — alerting on "
        "it makes the signal unreadable on every legitimate odd-meter song"
    )

    # Bar 13 is four 7/4 bars past the change: 32 + 28 = 60, not 48.
    M.add_arrangement_clip(
        conn, song_id=song, track_id=track, clip_id=clip,
        start_bar=13.0, end_bar=17.0,
    )
    plan = push.plan_push_arrangement(
        conn, song_id=song, session_id=session,
        live_arrangement_clips_by_track={2: []},
    )
    hit = next(a for a in plan.alerts if "bar rulers" in a)
    assert "1 of 2 arrangement placements" in hit
    assert "beat 60" in hit and "48" in hit
    assert "Affected bars: 13" in hit, (
        "the alert has to say WHERE, not just how many — it is the only "
        "channel carrying the repair site, and there is no logger on this path"
    )


def test_plan_push_arrangement_alert_enumerates_every_diverging_bar(
    conn, song, session, track, clip
):
    """Naming one bar out of many tells an operator a repair is needed and not
    where. Past the cap the list is cut, and the alert has to SAY it was cut —
    a silent truncation is the same defect wearing a shorter message."""
    M.add_time_signature_point(
        conn, song_id=song, start_bar=1.0, numerator=4, denominator=4
    )
    M.add_time_signature_point(
        conn, song_id=song, start_bar=9.0, numerator=7, denominator=4
    )
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="track", db_id=track, ableton_index=2
    )
    for start in range(10, 15):
        M.add_arrangement_clip(
            conn, song_id=song, track_id=track, clip_id=clip,
            start_bar=float(start), end_bar=float(start) + 1.0,
        )
    plan = push.plan_push_arrangement(
        conn, song_id=song, session_id=session,
        live_arrangement_clips_by_track={2: []},
    )
    hit = next(a for a in plan.alerts if "bar rulers" in a)
    assert "Affected bars: 10, 11, 12, 13, 14" in hit
    assert "more" not in hit, "five bars is under the cap; nothing was dropped"

    # Nine diverging bars is one past the cap of eight.
    for start in range(15, 19):
        M.add_arrangement_clip(
            conn, song_id=song, track_id=track, clip_id=clip,
            start_bar=float(start), end_bar=float(start) + 1.0,
        )
    plan = push.plan_push_arrangement(
        conn, song_id=song, session_id=session,
        live_arrangement_clips_by_track={2: []},
    )
    hit = next(a for a in plan.alerts if "bar rulers" in a)
    assert "Affected bars: 10, 11, 12, 13, 14, 15, 16, 17, and 1 more" in hit


def test_plan_push_arrangement_alert_collapses_a_bar_shared_across_tracks(
    conn, song, session, track, clip
):
    """A bar carries one diverging entry PER TRACK, so a section boundary that
    lands on several tracks at once would fill the whole cap with repeats of one
    number and bury every other diverging bar behind it. The ordinary song is
    the bad case here, not the pathological one."""
    M.add_time_signature_point(
        conn, song_id=song, start_bar=1.0, numerator=4, denominator=4
    )
    M.add_time_signature_point(
        conn, song_id=song, start_bar=9.0, numerator=7, denominator=4
    )
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="track", db_id=track, ableton_index=2
    )
    probe = {2: []}
    # The same three bars on a second and third track, plus one bar only the
    # first track reaches — which is exactly what the repeats would hide.
    for idx, bars in ((5, (10.0, 11.0, 12.0)), (6, (10.0, 11.0, 12.0))):
        tid = M.create_track(
            conn, song_id=song, track_index=idx, name=f"T{idx}",
            instrument_uri="query:Drums#Kit_X",
        )
        cid = M.create_clip(
            conn, track_id=tid, slot=1, length_beats=4.0, name=f"c{idx}",
            section_role="verse",
        )
        M.link_db_to_ableton(
            conn, session_id=session, db_kind="track", db_id=tid, ableton_index=idx,
        )
        probe[idx] = []
        for b in bars:
            M.add_arrangement_clip(
                conn, song_id=song, track_id=tid, clip_id=cid,
                start_bar=b, end_bar=b + 1.0,
            )
    for b in (10.0, 11.0, 12.0, 20.0):
        M.add_arrangement_clip(
            conn, song_id=song, track_id=track, clip_id=clip,
            start_bar=b, end_bar=b + 1.0,
        )

    plan = push.plan_push_arrangement(
        conn, song_id=song, session_id=session,
        live_arrangement_clips_by_track=probe,
    )
    hit = next(a for a in plan.alerts if "bar rulers" in a)
    # Pin the WHOLE clause, up to its terminating period. A prefix assertion
    # passes on the undeduped list too, because that list happens to start with
    # these same four bars before it begins repeating them.
    assert "Affected bars: 10, 11, 12, 20. " in hit, (
        "bars repeat once per track; collapsing them is what keeps the rarest "
        "diverging bar visible"
    )
    # The opening clause still counts placements, not distinct bars.
    assert "10 of 10 arrangement placements" in hit


def test_plan_push_arrangement_multiple_placements_create_separate_calls(
    conn, song, session, track, clip
):
    """Three arrangement placements → three independent create+fill calls,
    ascending start, distinct ``arrangement_clip:{db_id}`` keys (the planner
    doesn't collapse them)."""
    M.add_time_signature_point(
        conn, song_id=song, start_bar=1.0, numerator=4, denominator=4
    )
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="track", db_id=track, ableton_index=2
    )
    for bar in (1.0, 17.0, 33.0):
        M.add_arrangement_clip(
            conn, song_id=song, track_id=track, clip_id=clip,
            start_bar=bar, end_bar=bar + 16.0,
        )
    plan = push.plan_push_arrangement(
        conn, song_id=song, session_id=session,
        live_arrangement_clips_by_track={2: []},
    )
    creates = [c for c in plan.calls if c.args["action"] == "create"]
    assert len(creates) == 3
    beats = [c.args["start_beats"] for c in creates]
    assert beats == [0.0, 64.0, 128.0]  # ascending start order
    keys = {c.key for c in creates}
    assert len(keys) == 3
    assert all(k.startswith("arrangement_clip:") for k in keys)


def test_plan_push_arrangement_skips_unlinked_track_entirely(
    conn, song, session, track, clip
):
    """A track that isn't linked yet emits NOTHING (no clear, no create) and an
    alert — the projection can't address it. (Normally the tracks phase links it
    first.) The alert (operator-visible) is used, not a benign note, because a
    whole track's content failed to materialize."""
    M.add_arrangement_clip(
        conn, song_id=song, track_id=track, clip_id=clip, start_bar=1, end_bar=16
    )
    plan = push.plan_push_arrangement(
        conn, song_id=song, session_id=session,
        live_arrangement_clips_by_track={},
    )
    assert plan.calls == []
    assert any("not linked" in a for a in plan.alerts)


def test_plan_push_arrangement_none_probe_emits_no_clear_alert(
    conn, song, session, track, clip
):
    """No probe (``live_arrangement_clips_by_track=None``) → create+fill only,
    NO clear, plus a loud alert that the timeline must be empty. The idempotency
    guarantee holds only with the probe; the execute path always probes."""
    M.add_time_signature_point(
        conn, song_id=song, start_bar=1.0, numerator=4, denominator=4
    )
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="track", db_id=track, ableton_index=2
    )
    M.add_arrangement_clip(
        conn, song_id=song, track_id=track, clip_id=clip, start_bar=1.0, end_bar=16.0
    )
    plan = push.plan_push_arrangement(conn, song_id=song, session_id=session)
    assert all(c.args["action"] == "create" for c in plan.calls)
    assert not any(c.args["action"] == "delete" for c in plan.calls)
    assert any("WITHOUT a Live arrangement probe" in a for a in plan.alerts)


def test_plan_push_arrangement_skips_track_absent_from_probe(
    conn, song, session, track, clip
):
    """A probe WAS provided but this track's lane is ABSENT (the per-track probe
    FAILED — distinct from a present-but-empty lane = genuinely no clips). The
    lane state is unknown, so the planner skips it + alerts rather than
    create+fill onto unprobed clips (which could stack — the failure the
    projection prevents)."""
    M.add_time_signature_point(
        conn, song_id=song, start_bar=1.0, numerator=4, denominator=4
    )
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="track", db_id=track, ableton_index=2
    )
    M.add_arrangement_clip(
        conn, song_id=song, track_id=track, clip_id=clip, start_bar=1.0, end_bar=16.0
    )
    # Probe provided but track 2's lane is ABSENT (only an unrelated lane probed).
    plan = push.plan_push_arrangement(
        conn, song_id=song, session_id=session,
        live_arrangement_clips_by_track={9: []},
    )
    assert plan.calls == []
    assert any("the per-track probe failed" in a for a in plan.alerts)


# --- PSH-ARRPROBE: severity of a skip — "nothing to do" vs "couldn't tell" ---


def test_failed_probe_skip_is_blocked_not_a_benign_alert(
    conn, song, session, track, clip
):
    """A lane absent from the probe means the probe FAILED for that track. The
    planner is right to skip it, but the skip is un-determined work, not a
    no-op: it must land in ``blocked_reasons`` so the executor can report the
    push INCOMPLETE instead of "skipped (idempotent)" over an empty timeline.
    (It stays an alert too — blocked is the stronger subset.)"""
    M.add_time_signature_point(
        conn, song_id=song, start_bar=1.0, numerator=4, denominator=4
    )
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="track", db_id=track, ableton_index=2
    )
    M.add_arrangement_clip(
        conn, song_id=song, track_id=track, clip_id=clip, start_bar=1.0, end_bar=16.0
    )
    plan = push.plan_push_arrangement(
        conn, song_id=song, session_id=session,
        live_arrangement_clips_by_track={9: []},
    )
    assert plan.calls == []
    assert any("the per-track probe failed" in b for b in plan.blocked_reasons)
    assert set(plan.blocked_reasons) <= set(plan.alerts)


def test_unlinked_track_skip_is_blocked(conn, song, session, track, clip):
    """Same severity for a track with no session link: the song asked for a
    timeline this push could not address."""
    M.add_arrangement_clip(
        conn, song_id=song, track_id=track, clip_id=clip, start_bar=1.0, end_bar=16.0
    )
    plan = push.plan_push_arrangement(
        conn, song_id=song, session_id=session,
        live_arrangement_clips_by_track={},
    )
    assert any("not linked" in b for b in plan.blocked_reasons)


def test_audio_track_is_not_blocked(conn, song, session, tmp_path):
    """The counterweight: an audio track whose placements CAN be materialized
    is ordinary work, not an incomplete push — otherwise every song with a
    vocal stem exits non-zero forever. (SMP-6V2K: it used to be a deliberate
    no-op; now it is a real projection, and the invariant is the same.)"""
    (tmp_path / "assets").mkdir(exist_ok=True)
    (tmp_path / "assets" / "vox.wav").write_bytes(b"RIFF")
    atrack = M.create_track(
        conn, song_id=song, track_index=3, name="Vox", kind="audio",
    )
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="track", db_id=atrack, ableton_index=3,
    )
    aclip = M.create_audio_clip(
        conn, track_id=atrack, slot=1, length_beats=16.0,
        audio_file="assets/vox.wav", name="vox",
    )
    M.add_arrangement_clip(
        conn, song_id=song, track_id=atrack, clip_id=aclip,
        start_bar=1.0, end_bar=16.0,
    )
    plan = push.plan_push_arrangement(
        conn, song_id=song, session_id=session,
        live_arrangement_clips_by_track={3: []},
    )
    assert plan.blocked_reasons == []
    assert [c.args["kind"] for c in plan.calls] == ["audio"]


def test_no_probe_at_all_is_an_alert_not_blocked(conn, song, session, track, clip):
    """``None`` means "no probe was taken" (a non-execute caller). The planner
    still materializes everything — it just can't clear — so it warns loudly
    without claiming work went undone."""
    M.add_time_signature_point(
        conn, song_id=song, start_bar=1.0, numerator=4, denominator=4
    )
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="track", db_id=track, ableton_index=2
    )
    M.add_arrangement_clip(
        conn, song_id=song, track_id=track, clip_id=clip, start_bar=1.0, end_bar=16.0
    )
    plan = push.plan_push_arrangement(conn, song_id=song, session_id=session)
    assert plan.calls, "everything is still planned; only the clear is missing"
    assert plan.blocked_reasons == []
    assert any("WITHOUT a Live arrangement probe" in a for a in plan.alerts)


# --- PSH-ARRPROBE: the probe map may be a thunk, resolved at phase time ---


def test_resolve_live_arrangement_probe_passes_through_dict_and_none():
    assert push.resolve_live_arrangement_probe(None) is None
    assert push.resolve_live_arrangement_probe({2: []}) == {2: []}


def test_resolve_live_arrangement_probe_calls_a_thunk():
    calls = []

    def thunk():
        calls.append(1)
        return {5: []}

    assert push.resolve_live_arrangement_probe(thunk) == {5: []}
    assert calls == [1]


def test_plan_push_song_does_not_resolve_the_probe_thunk_eagerly(
    conn, song, session, track, clip
):
    """The load-bearing bit: building the phase list must NOT probe. The
    arrangement lane map is only valid once the `tracks` phase has created the
    song's Live tracks — probing at plan_push_song time is what produced a map
    keyed by the PRE-push track indices and a silently empty arrangement."""
    M.add_time_signature_point(
        conn, song_id=song, start_bar=1.0, numerator=4, denominator=4
    )
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="track", db_id=track, ableton_index=5
    )
    M.add_arrangement_clip(
        conn, song_id=song, track_id=track, clip_id=clip, start_bar=1.0, end_bar=16.0
    )
    calls = []

    def thunk():
        calls.append(1)
        return {5: []}

    phases = push.plan_push_song(
        conn, song_id=song, session_id=session,
        live_arrangement_clips_by_track=thunk,
    )
    assert calls == [], "plan_push_song must not touch Live"

    arrangement = next(p for p in phases if p.name == "arrangement")
    plan = arrangement.plan_fn()
    assert calls == [1], "the arrangement phase resolves it, once"
    assert plan.blocked_reasons == []
    assert [c.args["track_index"] for c in plan.calls] == [5]


# --- arrangement projection: routing + §6a all-or-nothing ---


def test_plan_push_arrangement_routes_envelope_bearing_to_duplicate(
    conn, song, session, track, clip, monkeypatch
):
    """An envelope-bearing placement (its clip hosts a clip-bound envelope —
    detected by :func:`envelope_hosting_clip_ids`) routes to
    ``duplicate_to_arrangement`` onto the CLEARED region, NOT create+fill:
    create+fill writes notes only and would drop the snapshot-copied clip
    envelope (§5/§9). The duplicate route needs the clip linked in a session
    slot. (The host-detection itself is unit-tested against real envelopes in
    test_push_envelopes; here we stub it to isolate the planner's routing.)"""
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
    monkeypatch.setattr(
        "hallucinote.sync.push.arrangement.envelope_hosting_clip_ids",
        lambda conn, song_id: {clip},
    )
    plan = push.plan_push_arrangement(
        conn, song_id=song, session_id=session,
        live_arrangement_clips_by_track={2: []},
    )
    creates = [c for c in plan.calls if c.args["action"] == "create"]
    dups = [c for c in plan.calls if c.args["action"] == "duplicate_to_arrangement"]
    assert not creates, "envelope-bearing clip must NOT create+fill (would drop envelope)"
    assert len(dups) == 1
    assert dups[0].args == {
        "action": "duplicate_to_arrangement",
        "track_index": 2,
        "clip_index": 1,
        "start_beats": 0.0,
    }
    assert dups[0].key == f"arrangement_clip:{aid}"


def test_plan_push_arrangement_all_or_nothing_on_unresolved_envelope_clip(
    conn, song, session, track, clip, monkeypatch
):
    """§6a all-or-nothing: the clear is DESTRUCTIVE, so a track with an
    envelope-bearing placement whose source clip isn't linked (needed for the
    duplicate route) emits NOTHING — no clear, no rebuild — and an alert. Never
    clear a track we cannot fully rebuild, or a re-push would wipe its clips and
    fail to recreate the envelope-bearing one.
    """
    M.add_time_signature_point(
        conn, song_id=song, start_bar=1.0, numerator=4, denominator=4
    )
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="track", db_id=track, ableton_index=2
    )
    # clip is the envelope host but is NOT linked → duplicate route can't resolve.
    M.add_arrangement_clip(
        conn, song_id=song, track_id=track, clip_id=clip, start_bar=1.0, end_bar=16.0
    )
    monkeypatch.setattr(
        "hallucinote.sync.push.arrangement.envelope_hosting_clip_ids",
        lambda conn, song_id: {clip},
    )
    live = {2: [{"arrangement_clip_index": 1, "start_beats": 0.0}]}
    plan = push.plan_push_arrangement(
        conn, song_id=song, session_id=session,
        live_arrangement_clips_by_track=live,
    )
    assert plan.calls == [], (
        "no clear (and no rebuild) when the track can't be fully rebuilt; got: "
        f"{[c.args for c in plan.calls]}"
    )
    assert any(
        "envelope-bearing" in a and "not linked" in a for a in plan.alerts
    ), f"expected an all-or-nothing alert, got: {plan.alerts}"


def test_plan_push_arrangement_projects_an_audio_track(
    conn, song, session, tmp_path
):
    """SMP-6V2K: an audio track the DB HAS placements for is projected like any
    other — the lane is cleared and the placement materialized from the row's
    sample. (Before, the whole track was left untouched because audio could not
    be rebuilt; a track the DB has NO placements for is still untouched, and
    `test_plan_push_arrangement_audio_track_without_placements_untouched`
    pins that half.)"""
    (tmp_path / "assets").mkdir(exist_ok=True)
    (tmp_path / "assets" / "vox.wav").write_bytes(b"RIFF")
    atrack = M.create_track(
        conn, song_id=song, track_index=3, name="Vox", kind="audio",
    )
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="track", db_id=atrack, ableton_index=3,
    )
    aclip = M.create_audio_clip(
        conn, track_id=atrack, slot=1, length_beats=16.0,
        audio_file="assets/vox.wav", name="vox",
    )
    M.add_arrangement_clip(
        conn, song_id=song, track_id=atrack, clip_id=aclip,
        start_bar=1.0, end_bar=16.0,
    )
    live = {3: [{"arrangement_clip_index": 1, "start_beats": 0.0}]}
    plan = push.plan_push_arrangement(
        conn, song_id=song, session_id=session,
        live_arrangement_clips_by_track=live,
    )
    assert [c.args["action"] for c in plan.calls] == ["delete", "create"]
    assert plan.calls[1].args["kind"] == "audio"
    assert plan.calls[1].args["audio_path"] == str(tmp_path / "assets" / "vox.wav")


def test_plan_push_arrangement_audio_track_without_placements_untouched(
    conn, song, session, track, clip
):
    """The half that did NOT change: a lane the DB has no placements for is
    never cleared, so audio dropped into Live by hand survives a push. It is
    true by construction (the loop is driven by DB rows) and the report names
    the track so 'untouched' can't be read as 'forgotten'."""
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="track", db_id=track, ableton_index=2,
    )
    M.add_arrangement_clip(
        conn, song_id=song, track_id=track, clip_id=clip,
        start_bar=1.0, end_bar=5.0,
    )
    atrack = M.create_track(
        conn, song_id=song, track_index=3, name="Vox", kind="audio",
    )
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="track", db_id=atrack, ableton_index=3,
    )
    M.create_audio_clip(
        conn, track_id=atrack, slot=1, length_beats=16.0,
        audio_file="assets/vox.wav", name="vox",
    )
    live = {
        2: [],
        3: [{"arrangement_clip_index": 1, "start_beats": 0.0}],
    }
    plan = push.plan_push_arrangement(
        conn, song_id=song, session_id=session,
        live_arrangement_clips_by_track=live,
    )
    assert not any(
        c.args["track_index"] == 3 for c in plan.calls
    ), "no DB placements → nothing to project on that lane, and nothing to clear"
    # On the operator channel (alerts), not `notes` — the executor shows the
    # operator alerts only, and "untouched" must not read as "forgotten".
    assert any("Vox" in a and "UNTOUCHED" in a for a in plan.alerts)


def test_plan_push_arrangement_sibling_track_unaffected_by_skip(
    conn, song, session, track, clip
):
    """§6a all-or-nothing is PER TRACK: a skipped (unresolvable) track does NOT
    prevent a sibling fully-resolved track from being cleared + rebuilt."""
    M.add_time_signature_point(
        conn, song_id=song, start_bar=1.0, numerator=4, denominator=4
    )
    # The fixture track is linked (Live index 2) → materializable.
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="track", db_id=track, ableton_index=2,
    )
    M.add_arrangement_clip(
        conn, song_id=song, track_id=track, clip_id=clip, start_bar=1.0, end_bar=16.0
    )
    # A second track, NOT linked → must be skipped without touching the first.
    t2 = M.create_track(
        conn, song_id=song, track_index=2, name="Bass",
        instrument_uri="query:Bass#X",
    )
    c2 = M.create_clip(conn, track_id=t2, slot=1, length_beats=16.0, name="bass")
    M.add_arrangement_clip(
        conn, song_id=song, track_id=t2, clip_id=c2, start_bar=1.0, end_bar=16.0
    )
    live = {2: [{"arrangement_clip_index": 1, "start_beats": 0.0}]}
    plan = push.plan_push_arrangement(
        conn, song_id=song, session_id=session,
        live_arrangement_clips_by_track=live,
    )
    creates = [c for c in plan.calls if c.args["action"] == "create"]
    assert len(creates) == 1, "the linked sibling track is still rebuilt"
    assert creates[0].args["track_index"] == 2
    # The unlinked track is skipped with an operator alert.
    assert any("not linked" in a for a in plan.alerts)


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
    refreshed by the notes phase; the clips and arrangement phases own it."""
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


# ARR-PROJ Chunk 2: the old `plan_push_arrangement` refresh-in-place machinery
# (replace_notes on already-linked placements) is DELETED — the projection model
# always clears + rebuilds, so there is no "unrefreshable linked placement" case
# to name. The scoped compose-loop propagation (plan_push_arrangement_clip_notes,
# tested below) still uses the refresh path and is unchanged by Chunk 2.


# --- check_coherence (W18-A) ---


def test_check_coherence_ok_when_links_match_probe(conn, song, session):
    """Happy path: links written by probe-and-link match a fresh probe →
    coherence passes, execute is safe."""
    M.create_track(conn, song_id=song, track_index=1, name="Drums", kind="midi")
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


def test_apply_results_arrangement_clip_clear_is_ack_only(conn, session, track):
    """ARR-PROJ Chunk 2: the projection planner's clear emits delete results
    keyed `arrangement_clip_clear:{track}:{idx}`. apply_push_results must treat
    it as ACK-ONLY (record no binding, do not raise on the unknown prefix) — the
    delete carries no index to bind and the rebuild re-records the placement
    under `arrangement_clip:`. Without the ack-only registration the arrangement
    phase HALTS on the first clear result."""
    # Must not raise (the unknown-key terminal raise is the bug this guards).
    push.apply_push_results(
        conn,
        [
            {"key": "arrangement_clip_clear:2:3", "ok": True,
             "tool": "ableton_clip", "result": {"deleted": True}},
        ],
        session_id=session,
    )
    # No binding recorded for the clear key kind.
    assert Q.get_ableton_link(
        conn, session_id=session, db_kind="arrangement_clip", db_id="2:3"
    ) is None


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


# ---------------------------------------------------------------------------
# Emitted-key-kind contract — every key a sync planner emits must resolve in
# its apply step. Bug-class guard for the device_param_override (2026-06-18) /
# device_chain_props (2026-06-20) twins, generalized to BOTH the push apply
# (apply_push_results) and the symmetric pull apply (apply_pull_results), which
# share the same table-driven-dispatch-with-catch-all-raise shape.
# ---------------------------------------------------------------------------


# Planner keys whose KIND segment (the text before the first ':') is itself
# f-string-interpolated, mapped to the concrete kinds each can produce. A static
# source scan can't expand these, so they're declared here explicitly — and the
# guard asserts BOTH directions (every template found in source is in the table;
# every template in the table is still emitted), so a table can't silently rot.
_PUSH_INTERPOLATED_KEY_EXPANSIONS: dict[str, set[str]] = {
    # mix.py: per-field track mixer state via ableton_track(set_property).
    "track_{db_field}": {
        "track_volume", "track_pan", "track_mute",
        "track_solo", "track_arm", "track_color",
    },
    # mix.py: per-field return mixer state via ableton_return(set_property)
    # (returns have no arm).
    "return_{db_field}": {
        "return_volume", "return_pan", "return_mute",
        "return_solo", "return_color",
    },
    # routing.py: per-direction track routing via ableton_track(set_*_routing).
    "track_{direction}_routing": {
        "track_output_routing", "track_input_routing",
    },
}

_PULL_INTERPOLATED_KEY_EXPANSIONS: dict[str, set[str]] = {
    # pull/devices.py: top-level device chain pulled per linked parent — the
    # parent_kind is "track" or "return" (see _iter_linked_parents).
    "{parent_kind}_devices": {"track_devices", "return_devices"},
}


def _emitted_key_kinds(planner_dir) -> tuple[set[str], set[str]]:
    """Scan every planner module in ``planner_dir`` for the kind segment of each
    emitted ``key=...`` literal. Returns ``(static_kinds, interpolated_kinds)``.

    Robust because both the push and pull layers emit every key as an INLINE
    string literal on a ``key=f"..."`` / ``key="..."`` line — no key is built in
    a variable first (verified by grep at authoring time on both dirs), so a
    source scan sees them all. The regex is quote-agnostic (single or double)
    and ignores ``key=lambda`` sort keys and the apply-side error-message
    f-strings (``key={key!r}`` — no quote right after ``key=``).
    """
    import re

    pat = re.compile(r"""key=f?["']([^"']*)["']""")
    static_kinds: set[str] = set()
    interpolated_kinds: set[str] = set()
    for module in sorted(planner_dir.glob("*.py")):
        for literal in pat.findall(module.read_text()):
            # The kind is the text before the first ':'. For interpolated keys
            # (track_{db_field}:… / {parent_kind}_devices:…) the '{' lands in
            # this segment.
            kind = literal.split(":", 1)[0]
            (interpolated_kinds if "{" in kind else static_kinds).add(kind)
    return static_kinds, interpolated_kinds


def _assert_every_emitted_kind_is_declared(
    *, planner_dir, declared, expansions, must_find, side, declare_hint,
):
    """Shared core for the push/pull emitted-key-kind contract guards."""
    static_kinds, interpolated_kinds = _emitted_key_kinds(planner_dir)

    # Sanity: the scan actually found keys (a no-op scan would pass vacuously).
    # Pin known kinds so each guard provably covers its bug-class anchor.
    assert must_find <= static_kinds, (
        f"the {side} emitted-key scan did not find {sorted(must_find)} — the "
        "scan is broken, not the contract"
    )

    # Every interpolated kind template found in source must be expanded here…
    unmapped = interpolated_kinds - set(expansions)
    assert not unmapped, (
        f"new interpolated {side} key kind(s) {sorted(unmapped)} — add their "
        "concrete expansions to the expansion table in this test so the guard "
        "can check each against the apply-side declarations."
    )
    # …and no stale entries (a removed interpolated key must drop its row).
    stale = set(expansions) - interpolated_kinds
    assert not stale, (
        f"the {side} interpolated-key expansion table has entries no planner "
        f"emits anymore: {sorted(stale)} — remove them."
    )

    concrete = set(static_kinds)
    for template in interpolated_kinds:
        concrete |= expansions[template]

    undeclared = concrete - declared
    assert not undeclared, (
        f"{side} planner(s) emit key kind(s) {sorted(undeclared)} that the "
        f"apply step does NOT resolve — a full {side} will CRASH in the "
        "result-apply step the moment one is produced (see the "
        f"device_param_override / device_chain_props bugs). {declare_hint}"
    )


def test_every_emitted_push_key_kind_is_declared():
    """Every key kind the push planners emit MUST resolve in
    ``apply_push_results`` — i.e. appear in ``_LINK_KINDS``, ``_ACK_ONLY_KINDS``,
    or the dedicated ``perform_batch`` branch. Otherwise a full push CRASHES in
    the result-apply step the moment that key is produced, halting every phase
    after it (the song never finishes materializing).

    This is the bug-class guard for two siblings that each shipped this exact
    way: ``device_param_override`` (2026-06-18) and its direct twin
    ``device_chain_props`` (2026-06-20) — a new planner-emitted key kind that
    nobody declared on the apply side. The plan.py docstring already states the
    contract ("every key kind the planner emits MUST appear in …"); this test
    enforces it mechanically so the next sibling can't regress silently.
    """
    import pathlib

    from hallucinote.sync.push import plan

    declared = (
        set(plan._LINK_KINDS)
        | set(plan._ACK_ONLY_KINDS)
        | {"perform_batch"}  # dedicated branch in apply_push_results
    )
    _assert_every_emitted_kind_is_declared(
        planner_dir=pathlib.Path(plan.__file__).parent,
        declared=declared,
        expansions=_PUSH_INTERPOLATED_KEY_EXPANSIONS,
        must_find={"device_param_override", "device_chain_props"},
        side="push",
        declare_hint=(
            "Declare each in _LINK_KINDS or _ACK_ONLY_KINDS (or add a dedicated "
            "branch) in sync/push/plan.py."
        ),
    )


def test_every_emitted_pull_key_kind_is_declared():
    """Symmetric guard for the PULL side: ``apply_pull_results`` is the inverse
    twin of the push apply — the same table-driven dispatch
    (``_HANDLERS``) with the same catch-all ``raise ValueError('unknown pull
    result key kind …')``. An undeclared pull key would regress exactly the way
    ``device_chain_props`` did on push: silent until it crashes a real pull.
    Locking it here closes the bug class on both apply surfaces, not just the
    one that happened to surface a report first.
    """
    import pathlib

    from hallucinote.sync.pull import plan as pull_plan

    _assert_every_emitted_kind_is_declared(
        planner_dir=pathlib.Path(pull_plan.__file__).parent,
        declared=set(pull_plan._HANDLERS),
        expansions=_PULL_INTERPOLATED_KEY_EXPANSIONS,
        must_find={"device_parameters", "device_sidechain_source"},
        side="pull",
        declare_hint="Declare each in _HANDLERS in sync/pull/plan.py.",
    )


# --- ARR-ORPHAN2: the clear must remove orphans, and a lane it cannot
# read is corruption, not a benign skip ---


def test_plan_push_arrangement_clears_unlinked_orphan_clip(
    conn, song, session, track, clip
):
    """ARR-ORPHAN2 regression. An ORPHAN arrangement clip — one with no DB
    placement and no ``ableton_link`` binding, e.g. a hand edit or a leftover
    from a mis-materialized push — must be deleted by the clear like any other.
    The clear is driven purely by the probe inventory, never by "clips I can map
    back to a DB row"; the witness bug (a surviving orphan on Lead Gtr while the
    lane's three real placements vanished) is only reproducible when the lane was
    never probed at all, not when a probed clip was spared."""
    M.add_time_signature_point(
        conn, song_id=song, start_bar=1.0, numerator=4, denominator=4
    )
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="track", db_id=track, ableton_index=4
    )
    M.add_arrangement_clip(
        conn, song_id=song, track_id=track, clip_id=clip,
        start_bar=57.0, end_bar=61.0,  # beat 224
    )
    # Live's lane holds ONLY an orphan at beat 0 (no DB placement there, and no
    # arrangement_clip link was ever recorded for it).
    live = {4: [
        {"arrangement_clip_index": 1, "start_beats": 0.0, "name": "Lead Gtr 2"},
    ]}
    plan = push.plan_push_arrangement(
        conn, song_id=song, session_id=session,
        live_arrangement_clips_by_track=live,
    )
    seq = [(c.args["action"], c.args.get("clip_index")) for c in plan.calls]
    assert seq == [("delete", 1), ("create", None)]
    assert plan.calls[0].key == "arrangement_clip_clear:4:1"
    assert plan.calls[1].args["start_beats"] == 224.0


def test_plan_push_arrangement_full_extent_clip_at_zero_does_not_block_creates(
    conn, song, session, track, clip
):
    """ARR-ORPHAN2 regression: a single clip at beat 0 whose LENGTH spans the
    whole arrangement must not swallow later placements. The projection deletes
    it FIRST, so every subsequent create lands on empty timeline — the creates
    are never issued into an occupied region (where Live would refuse and the MCP
    create handler would fail loud)."""
    M.add_time_signature_point(
        conn, song_id=song, start_bar=1.0, numerator=4, denominator=4
    )
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="track", db_id=track, ableton_index=4
    )
    for start_bar in (57.0, 60.5, 66.5):  # beats 224 / 238 / 262
        M.add_arrangement_clip(
            conn, song_id=song, track_id=track, clip_id=clip,
            start_bar=start_bar, end_bar=start_bar + 4.0,
        )
    live = {4: [
        # One clip at 0 covering the entire song (length 400 beats).
        {"arrangement_clip_index": 1, "start_beats": 0.0, "length": 400.0,
         "name": "Lead Gtr 2"},
    ]}
    plan = push.plan_push_arrangement(
        conn, song_id=song, session_id=session,
        live_arrangement_clips_by_track=live,
    )
    actions = [c.args["action"] for c in plan.calls]
    assert actions == ["delete", "create", "create", "create"]
    assert [c.args["start_beats"] for c in plan.calls[1:]] == [224.0, 238.0, 262.0]


# --- arrangement projection: routing + §6a all-or-nothing ---
