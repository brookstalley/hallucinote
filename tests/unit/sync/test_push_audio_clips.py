"""SMP-6V2K — the clips and arrangement phases materialize audio (R1.1).

An authored ``kind='audio'`` row used to warn and skip in both phases. It now
becomes a real Live clip in the session and in the arrangement, conformed as
authored. Two cases that once refused pending a Live probe are now settled by
its recorded verdicts (``docs/research/audio-first-class/lom-probe-results.md``
rows 16-16c):

  * a linked row whose ``audio_file`` CHANGED, or whose linked slot holds a
    MIDI clip, is a delete → create → conform → re-emit-envelopes sequence
    (``Clip.file_path`` is read-only, create into an occupied slot is a hard
    error, and a recreate drops every envelope the clip hosted), and
  * an audio placement whose source clip HOSTS an envelope takes the duplicate
    route, like a MIDI one (the duplicate carries the ride — and the conform —
    off an audio session clip); envelope-free placements keep the direct create.

Plus the two properties a destructive reconcile breaks first: a missing sample
fails its clip BEFORE the call is planned, and a second push of an unchanged
song plans nothing.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from hallucinote.db import init_db, mutations as M, queries as Q
from hallucinote.sync import push


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def song_dir(tmp_path):
    """The DB lives IN the song dir, which is what an ``audio_file`` reference
    resolves against (``paths.resolve_audio_path``)."""
    (tmp_path / "assets").mkdir()
    return tmp_path


@pytest.fixture
def conn(song_dir):
    c = init_db(song_dir / "aud.db")
    yield c
    c.close()


@pytest.fixture
def song(conn):
    return M.create_song(conn, name="dialogue", key="Dm")


@pytest.fixture
def session(conn, song):
    return M.create_ableton_session(conn, song_id=song, name="draft")


@pytest.fixture
def sample(song_dir) -> str:
    """A real file on disk, referenced song-relatively the way build.py does."""
    (song_dir / "assets" / "line.wav").write_bytes(b"RIFF....WAVEfmt ")
    return "assets/line.wav"


@pytest.fixture
def audio_track(conn, song, session):
    tid = M.create_track(
        conn, song_id=song, track_index=1, name="Dialogue", kind="audio",
    )
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="track", db_id=tid, ableton_index=4,
    )
    return tid


def _link_clip(conn, *, session, clip_id, index=1):
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="clip", db_id=clip_id,
        ableton_index=index,
    )


def _live_slot(clip_index: int, file_path: str, **conform) -> dict:
    """One populated entry as ``ableton_clip(action='list', location='session')``
    reports it for an audio clip (chunk 02's read surface)."""
    entry = {
        "clip_index": clip_index,
        "empty": False,
        "name": "line",
        "length": 8.0,
        "is_audio": True,
        "file_path": file_path,
    }
    entry.update(conform)
    return entry


# ---------------------------------------------------------------------------
# Session clips — create from an authored row
# ---------------------------------------------------------------------------


def test_authored_audio_row_creates_a_real_clip(
    conn, song, session, audio_track, sample, song_dir,
):
    """The headline: an unlinked audio row plans one create carrying the
    RESOLVED ABSOLUTE path (Live resolves nothing), on the track's Live index,
    in the row's slot."""
    cid = M.create_audio_clip(
        conn, track_id=audio_track, slot=2, length_beats=8.0,
        audio_file=sample, name="line",
    )
    plan = push.plan_push_clip(conn, clip_id=cid, session_id=session)

    assert plan.blocked_reasons == []
    create = plan.calls[0]
    assert create.key == f"clip:{cid}"
    assert create.tool == "ableton_clip"
    assert create.args["action"] == "create"
    assert create.args["location"] == "session"
    assert create.args["kind"] == "audio"
    assert create.args["track_index"] == 4
    assert create.args["clip_index"] == 2
    assert create.args["audio_path"] == str(song_dir / "assets" / "line.wav")
    assert Path(create.args["audio_path"]).is_absolute()
    assert create.args["name"] == "line"
    # No `notes` and no `length`: an audio clip has no note array and takes its
    # length from the file (the wire refuses notes on kind='audio').
    assert "notes" not in create.args
    assert "length" not in create.args


def test_authored_conform_rides_along_with_the_create(
    conn, song, session, audio_track, sample,
):
    """Conform is authorship, not a mix-time todo: the authored gain /
    transpose / warp / markers are planned with the clip. A NULL column means
    'never authored' and is not written."""
    cid = M.create_audio_clip(
        conn, track_id=audio_track, slot=1, length_beats=8.0,
        audio_file=sample, name="line",
        gain=0.6, pitch_coarse=-3, warping=1, warp_mode=6, start_marker=0.5,
    )
    plan = push.plan_push_clip(conn, clip_id=cid, session_id=session)

    conform = [c for c in plan.calls if c.key.startswith("clip_conform:")]
    written = {c.args["property"]: c.args["value"] for c in conform}
    assert written == {
        "gain": 0.6,
        "pitch_coarse": -3,
        "warping": True,   # DB stores 0/1; the wire and Live speak bool
        "warp_mode": 6,
        "start_marker": 0.5,
    }
    assert all(c.args["action"] == "set_property" for c in conform)
    assert all(c.args["clip_index"] == 1 for c in conform)
    assert all(c.args["location"] == "session" for c in conform)
    # pitch_fine / end_marker were never authored → never written.
    assert "pitch_fine" not in written
    assert "end_marker" not in written


def test_absolute_audio_file_passes_through_unchanged(
    conn, song, session, audio_track, tmp_path,
):
    """``clips.audio_file`` may be absolute (a sample outside the song dir);
    the resolver passes it through and push uses it verbatim."""
    outside = tmp_path.parent / "elsewhere.wav"
    outside.write_bytes(b"RIFF")
    cid = M.create_audio_clip(
        conn, track_id=audio_track, slot=1, length_beats=8.0,
        audio_file=str(outside), name="line",
    )
    plan = push.plan_push_clip(conn, clip_id=cid, session_id=session)
    assert plan.calls[0].args["audio_path"] == str(outside)


# ---------------------------------------------------------------------------
# The loud failures
# ---------------------------------------------------------------------------


def test_missing_sample_fails_the_clip_before_the_call_is_planned(
    conn, song, session, audio_track, song_dir,
):
    """A clip that pushes and then plays silence is a phase reporting OK
    without having determined its state. NO call is planned, and the run is
    INCOMPLETE (blocked), not a clean skip."""
    cid = M.create_audio_clip(
        conn, track_id=audio_track, slot=1, length_beats=8.0,
        audio_file="assets/absent.wav", name="ghost",
    )
    plan = push.plan_push_clip(conn, clip_id=cid, session_id=session)

    assert plan.calls == [], "a missing sample must plan nothing at all"
    assert len(plan.blocked_reasons) == 1
    reason = plan.blocked_reasons[0]
    assert "not on disk" in reason
    assert str(song_dir / "assets" / "absent.wav") in reason
    # blocked is strictly stronger than alert, and rides both channels.
    assert set(plan.blocked_reasons) <= set(plan.alerts)


def _host_a_ride(conn, *, song, track, clip, start_bar=1.0):
    """Give ``clip`` a mixer_volume ride it HOSTS: a covering placement plus
    an envelope whose span that placement covers (breakpoints in arrangement
    time, so they sit under the placement wherever it starts; 4/4 assumed).
    Returns the envelope id."""
    _place(conn, song=song, track=track, clip=clip, start_bar=start_bar)
    offset = (start_bar - 1.0) * 4.0
    env = M.create_envelope(
        conn, song_id=song, target_kind="mixer_volume", target_track_id=track,
    )
    M.add_breakpoint(conn, envelope_id=env, time_beats=offset, value=0.5)
    M.add_breakpoint(conn, envelope_id=env, time_beats=offset + 4.0, value=0.9)
    from hallucinote.sync.push.envelopes import envelope_hosting_clip_ids
    assert clip in envelope_hosting_clip_ids(conn, song), (
        "fixture precondition: the clip must actually host the envelope"
    )
    return env


def test_changed_audio_file_is_delete_create_conform_then_envelopes_in_order(
    conn, song, session, audio_track, sample, song_dir,
):
    """THE reconcile rule (probe rows 16, 16b). ``Clip.file_path`` is
    read-only and a create into an occupied slot is a hard error, so a
    re-pointed row is an explicit delete, then a create, then the conform,
    then every envelope the row hosts written again — because a recreate
    drops them, and a ride the author wrote must not go missing because the
    file under it changed. One planned sequence, in that order."""
    cid = M.create_audio_clip(
        conn, track_id=audio_track, slot=1, length_beats=8.0,
        audio_file=sample, name="line", gain=0.6, warp_mode=6,
    )
    _link_clip(conn, session=session, clip_id=cid, index=1)
    env = _host_a_ride(conn, song=song, track=audio_track, clip=cid)
    probe = {4: [_live_slot(1, str(song_dir / "assets" / "OTHER.wav"), gain=0.6)]}

    plan = push.plan_push_clip(
        conn, clip_id=cid, session_id=session,
        live_session_clips_by_track=probe,
    )

    assert plan.blocked_reasons == [], plan.blocked_reasons
    actions = [c.args["action"] for c in plan.calls]
    assert actions == [
        "delete", "create", "set_property", "set_property", "write_envelope",
    ], actions

    delete, create = plan.calls[0], plan.calls[1]
    assert delete.key == f"clip_delete:{cid}"
    assert delete.args == {
        "action": "delete", "location": "session",
        "track_index": 4, "clip_index": 1,
    }
    assert create.key == f"clip:{cid}"
    assert create.args["kind"] == "audio"
    assert create.args["clip_index"] == 1, "same slot, same link — no positional guess"
    assert create.args["audio_path"] == str(song_dir / "assets" / "line.wav")
    assert "replace" not in create.args, (
        "the explicit delete is the one destructive step; a replace would hide a second"
    )

    # The conform is written in full — the new clip is at Live's defaults, so
    # the probe's `gain=0.6` on the OLD clip must not suppress the write.
    conform = {c.args["property"]: c.args["value"] for c in plan.calls[2:4]}
    assert conform == {"gain": 0.6, "warp_mode": 6}

    ride = plan.calls[4]
    assert ride.key == f"envelope:{env}", (
        "the re-emit IS an envelope write; its result carries the index the link layer records"
    )
    assert ride.tool == "ableton_automation"
    assert ride.args["target_kind"] == "mixer_volume"
    assert ride.args["location"] == "session"
    assert ride.args["clip_index"] == 1
    assert ride.args["track_index"] == 4

    # Said where the operator will see it, because a clip they had was deleted.
    assert any("CHANGED" in a and "DELETED" in a and "OTHER.wav" in a for a in plan.alerts)


def test_changed_audio_file_re_emits_exactly_what_the_envelopes_phase_would(
    conn, song, session, audio_track, sample, song_dir,
):
    """Reuse, not a copy: the re-emitted call is byte-for-byte the call the
    envelopes phase plans for that envelope, so the two phases can never
    disagree about a route, a clip-local translation, or a warning."""
    cid = M.create_audio_clip(
        conn, track_id=audio_track, slot=1, length_beats=8.0,
        audio_file=sample, name="line",
    )
    _link_clip(conn, session=session, clip_id=cid, index=1)
    _host_a_ride(conn, song=song, track=audio_track, clip=cid, start_bar=3.0)
    probe = {4: [_live_slot(1, str(song_dir / "assets" / "OTHER.wav"))]}

    clips_plan = push.plan_push_clip(
        conn, clip_id=cid, session_id=session,
        live_session_clips_by_track=probe,
    )
    envelopes_plan = push.plan_push_envelopes(conn, song_id=song, session_id=session)

    reemitted = [c for c in clips_plan.calls if c.key.startswith("envelope:")]
    assert len(reemitted) == 1
    assert [(c.key, c.args) for c in reemitted] == [
        (c.key, c.args) for c in envelopes_plan.calls
    ]


def test_changed_audio_file_with_no_hosted_envelope_re_emits_nothing(
    conn, song, session, audio_track, sample, song_dir,
):
    """No envelope hosted → nothing to re-emit; the sequence is just
    delete, create, conform. Nothing is written 'just in case'."""
    cid = M.create_audio_clip(
        conn, track_id=audio_track, slot=1, length_beats=8.0,
        audio_file=sample, name="line", gain=0.6,
    )
    _link_clip(conn, session=session, clip_id=cid, index=1)
    probe = {4: [_live_slot(1, str(song_dir / "assets" / "OTHER.wav"))]}

    plan = push.plan_push_clip(
        conn, clip_id=cid, session_id=session,
        live_session_clips_by_track=probe,
    )
    assert [c.args["action"] for c in plan.calls] == ["delete", "create", "set_property"]
    assert not any(c.key.startswith("envelope:") for c in plan.calls)


def test_linked_slot_holding_a_non_audio_clip_is_recreated_as_audio(
    conn, song, session, audio_track, sample, song_dir,
):
    """Same rule as a changed file: the DB says audio, Live's slot holds a
    MIDI clip, and the DB is the projection's author — so the slot becomes
    what the row says by the one route Live allows, delete then create."""
    cid = M.create_audio_clip(
        conn, track_id=audio_track, slot=1, length_beats=8.0,
        audio_file=sample, name="line",
    )
    _link_clip(conn, session=session, clip_id=cid, index=1)
    probe = {4: [{"clip_index": 1, "empty": False, "name": "x", "is_audio": False}]}

    plan = push.plan_push_clip(
        conn, clip_id=cid, session_id=session,
        live_session_clips_by_track=probe,
    )
    assert plan.blocked_reasons == []
    assert [c.args["action"] for c in plan.calls] == ["delete", "create"]
    assert plan.calls[0].key == f"clip_delete:{cid}"
    assert plan.calls[1].args["kind"] == "audio"
    assert any("NOT audio" in a and "DELETED" in a for a in plan.alerts)


def test_recreate_needs_a_successful_probe_so_the_unprobed_paths_stay_non_destructive(
    conn, song, session, audio_track, sample,
):
    """The recreate is the ONE destructive branch, and only a successful probe
    reaches it. Without a probe at all, and with a per-track probe failure,
    nothing is deleted — the tri-state reader still guards the destruction."""
    cid = M.create_audio_clip(
        conn, track_id=audio_track, slot=1, length_beats=8.0,
        audio_file=sample, name="line", gain=0.6,
    )
    _link_clip(conn, session=session, clip_id=cid, index=1)
    for probe in (None, {9: []}):
        plan = push.plan_push_clip(
            conn, clip_id=cid, session_id=session,
            live_session_clips_by_track=probe,
        )
        assert not any(c.args["action"] in ("delete", "create") for c in plan.calls), probe


def test_apply_accepts_the_clip_delete_key_and_the_create_relinks_the_slot(
    conn, song, session, audio_track, sample,
):
    """The apply layer's key registry is a contract: an undeclared kind RAISES
    and halts the phase mid-run. `clip_delete` is ack-only (a delete records
    no binding) and the `clip:` create that follows re-records the link."""
    from hallucinote.db import queries as Q
    cid = M.create_audio_clip(
        conn, track_id=audio_track, slot=1, length_beats=8.0,
        audio_file=sample, name="line",
    )
    _link_clip(conn, session=session, clip_id=cid, index=1)
    push.apply_push_results(
        conn,
        results=[
            {"key": f"clip_delete:{cid}", "ok": True, "tool": "ableton_clip",
             "result": {"track_index": 4, "location": "session",
                        "clip_index": 1, "deleted": True}},
            {"key": f"clip:{cid}", "ok": True, "tool": "ableton_clip",
             "result": {"track_index": 4, "location": "session",
                        "clip_index": 1}},
        ],
        session_id=session,
    )
    assert Q.get_ableton_link(
        conn, session_id=session, db_kind="clip", db_id=cid,
    ) == 1


def test_an_in_memory_db_cannot_resolve_a_relative_reference():
    """The song dir is the directory holding the DB file. With no file there is
    no anchor — say so rather than resolving against the process cwd."""
    conn = init_db(":memory:")
    try:
        sid = M.create_song(conn, name="x", key="C")
        sess = M.create_ableton_session(conn, song_id=sid, name="s")
        tid = M.create_track(
            conn, song_id=sid, track_index=1, name="A", kind="audio",
        )
        M.link_db_to_ableton(
            conn, session_id=sess, db_kind="track", db_id=tid, ableton_index=1,
        )
        cid = M.create_audio_clip(
            conn, track_id=tid, slot=1, length_beats=4.0,
            audio_file="assets/line.wav", name="line",
        )
        plan = push.plan_push_clip(conn, clip_id=cid, session_id=sess)
        assert plan.calls == []
        assert any("no database file on disk" in b for b in plan.blocked_reasons)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Idempotency — the property a destructive reconcile breaks first
# ---------------------------------------------------------------------------


def test_second_push_of_an_unchanged_song_plans_nothing(
    conn, song, session, audio_track, sample, song_dir,
):
    """THE idempotency pin. With the Live session-clip probe in hand, a linked
    audio clip whose file and conform values Live already holds plans ZERO
    calls — no create, no delete, not even a redundant conform write."""
    cid = M.create_audio_clip(
        conn, track_id=audio_track, slot=1, length_beats=8.0,
        audio_file=sample, name="line",
        gain=0.6, pitch_coarse=-3, pitch_fine=12.5, warping=1, warp_mode=6,
        start_marker=0.5, end_marker=4.0,
    )
    _link_clip(conn, session=session, clip_id=cid, index=1)
    probe = {4: [_live_slot(
        1, str(song_dir / "assets" / "line.wav"),
        gain=0.6, pitch_coarse=-3, pitch_fine=12.5, warping=True, warp_mode=6,
        start_marker=0.5, end_marker=4.0,
    )]}

    plan = push.plan_push_clips(
        conn, song_id=song, session_id=session,
        live_session_clips_by_track=probe,
    )
    assert plan.calls == [], f"unchanged song must plan no work; got {[c.args for c in plan.calls]}"
    assert plan.blocked_reasons == []
    assert plan.errors == []


def test_a_changed_conform_value_is_the_only_thing_rewritten(
    conn, song, session, audio_track, sample, song_dir,
):
    """The diff is per-property: edit the gain in build.py and re-push, and
    exactly one write goes out."""
    cid = M.create_audio_clip(
        conn, track_id=audio_track, slot=1, length_beats=8.0,
        audio_file=sample, name="line", gain=0.75, warping=1, warp_mode=6,
    )
    _link_clip(conn, session=session, clip_id=cid, index=1)
    probe = {4: [_live_slot(
        1, str(song_dir / "assets" / "line.wav"),
        gain=0.6, warping=True, warp_mode=6,
    )]}

    plan = push.plan_push_clip(
        conn, clip_id=cid, session_id=session,
        live_session_clips_by_track=probe,
    )
    assert [c.args["property"] for c in plan.calls] == ["gain"]
    assert plan.calls[0].args["value"] == 0.75


def test_second_push_without_a_probe_plans_nothing_destructive(
    conn, song, session, audio_track, sample,
):
    """Without the probe the file behind the link cannot be verified, so the
    planner writes the conform in place and NEVER recreates. The unverified
    check is stated on the operator channel, not swallowed."""
    cid = M.create_audio_clip(
        conn, track_id=audio_track, slot=1, length_beats=8.0,
        audio_file=sample, name="line", gain=0.6,
    )
    _link_clip(conn, session=session, clip_id=cid, index=1)

    plan = push.plan_push_clips(conn, song_id=song, session_id=session)

    actions = {c.args["action"] for c in plan.calls}
    assert actions == {"set_property"}, "no create and no delete on a re-push"
    assert plan.blocked_reasons == []
    assert any("WITHOUT a Live session-clip probe" in a for a in plan.alerts)


def test_the_unverified_alert_is_raised_once_per_song_not_once_per_clip(
    conn, song, session, audio_track, sample,
):
    """One alert for the song, the same shape as the arrangement projection's
    'planned WITHOUT a Live arrangement probe' — N of them would be noise, and
    noise is how a real signal gets routed around."""
    for slot in (1, 2, 3):
        cid = M.create_audio_clip(
            conn, track_id=audio_track, slot=slot, length_beats=8.0,
            audio_file=sample, name=f"line{slot}",
        )
        _link_clip(conn, session=session, clip_id=cid, index=slot)

    plan = push.plan_push_clips(conn, song_id=song, session_id=session)
    unverified = [a for a in plan.alerts if "WITHOUT a Live session-clip probe" in a]
    assert len(unverified) == 1
    assert "line1" in unverified[0] and "line3" in unverified[0]


def test_probed_empty_slot_recreates_rather_than_refusing(
    conn, song, session, audio_track, sample,
):
    """A stale link pointing at a slot Live has emptied is not the recreate
    hazard: there is nothing to destroy, so create it."""
    cid = M.create_audio_clip(
        conn, track_id=audio_track, slot=1, length_beats=8.0,
        audio_file=sample, name="line",
    )
    _link_clip(conn, session=session, clip_id=cid, index=1)

    plan = push.plan_push_clip(
        conn, clip_id=cid, session_id=session,
        live_session_clips_by_track={4: []},
    )
    assert plan.blocked_reasons == []
    assert plan.calls[0].args["action"] == "create"
    assert plan.calls[0].args["kind"] == "audio"


# ---------------------------------------------------------------------------
# The aggregator
# ---------------------------------------------------------------------------


def test_aggregator_carries_per_clip_blocked_reasons_up(
    conn, song, session, audio_track, sample,
):
    """A blocked reason that did not reach the song-level plan would be a push
    reporting OK over work it did not do — the exact failure `blocked` exists
    to prevent."""
    M.create_audio_clip(
        conn, track_id=audio_track, slot=1, length_beats=8.0,
        audio_file="assets/absent.wav", name="ghost",
    )
    M.create_audio_clip(
        conn, track_id=audio_track, slot=2, length_beats=8.0,
        audio_file=sample, name="line",
    )
    plan = push.plan_push_clips(conn, song_id=song, session_id=session)

    assert any("not on disk" in b for b in plan.blocked_reasons)
    assert set(plan.blocked_reasons) <= set(plan.alerts)
    # The healthy sibling still materializes — one bad reference does not
    # take the song's other clips with it.
    assert [c.args["clip_index"] for c in plan.calls
            if c.args["action"] == "create"] == [2]


def test_audio_refusal_leaves_midi_siblings_untouched(
    conn, song, session, audio_track,
):
    """Regression guard kept from the refuse-and-skip era: whatever audio does,
    a MIDI sibling still gets its kind='midi' create."""
    midi_track = M.create_track(
        conn, song_id=song, track_index=2, name="Keys", kind="midi",
    )
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="track", db_id=midi_track,
        ableton_index=5,
    )
    mc = M.create_clip(
        conn, track_id=midi_track, slot=1, length_beats=4.0, name="loop_a",
    )
    M.create_audio_clip(
        conn, track_id=audio_track, slot=1, length_beats=8.0,
        audio_file="assets/absent.wav", name="ghost",
    )
    plan = push.plan_push_clips(conn, song_id=song, session_id=session)
    assert [c.key for c in plan.calls] == [f"clip:{mc}"]
    assert plan.calls[0].args["kind"] == "midi"


# ---------------------------------------------------------------------------
# Arrangement projection
# ---------------------------------------------------------------------------


def _place(conn, *, song, track, clip, start_bar=1.0, end_bar=None):
    return M.add_arrangement_clip(
        conn, song_id=song, track_id=track, clip_id=clip,
        start_bar=start_bar,
        end_bar=start_bar + 4.0 if end_bar is None else end_bar,
    )


def test_audio_placement_materializes_into_the_arrangement(
    conn, song, session, audio_track, sample, song_dir,
):
    """An audio track the DB HAS placements for is projectable like any other:
    clear the lane, then create the placement directly from the sample path."""
    cid = M.create_audio_clip(
        conn, track_id=audio_track, slot=1, length_beats=8.0,
        audio_file=sample, name="line",
    )
    M.add_time_signature_point(
        conn, song_id=song, start_bar=1.0, numerator=4, denominator=4,
    )
    aid = _place(conn, song=song, track=audio_track, clip=cid, start_bar=3.0)

    live = {4: [{"arrangement_clip_index": 1, "start_beats": 0.0}]}
    plan = push.plan_push_arrangement(
        conn, song_id=song, session_id=session,
        live_arrangement_clips_by_track=live,
    )

    assert plan.blocked_reasons == []
    kinds = [c.args["action"] for c in plan.calls]
    assert kinds == ["delete", "create"], "clear first, then materialize"
    create = plan.calls[1]
    assert create.key == f"arrangement_clip:{aid}"
    assert create.args["location"] == "arrangement"
    assert create.args["kind"] == "audio"
    assert create.args["track_index"] == 4
    assert create.args["start_beats"] == 8.0  # bar 3 in 4/4
    assert create.args["audio_path"] == str(song_dir / "assets" / "line.wav")
    assert "notes" not in create.args


def test_envelope_hosting_audio_placement_takes_the_duplicate_route(
    conn, song, session, audio_track, sample, song_dir,
):
    """Probe row 16c: ``duplicate_clip_to_arrangement`` carries a ride off an
    AUDIO session clip exactly as off a MIDI one. So an audio placement whose
    source clip hosts an envelope duplicates onto the cleared region like a
    MIDI one — the same call, the same key kind — and NOT the direct create,
    which carries no envelope. The duplicate copies the CONFORMED session
    clip, so the per-placement conform gap must not fire for it."""
    cid = M.create_audio_clip(
        conn, track_id=audio_track, slot=1, length_beats=8.0,
        audio_file=sample, name="line", gain=0.6, warp_mode=6,
    )
    _link_clip(conn, session=session, clip_id=cid, index=1)
    M.add_time_signature_point(
        conn, song_id=song, start_bar=1.0, numerator=4, denominator=4,
    )
    _host_a_ride(conn, song=song, track=audio_track, clip=cid, start_bar=3.0)

    live = {4: [{"arrangement_clip_index": 1, "start_beats": 0.0}]}
    plan = push.plan_push_arrangement(
        conn, song_id=song, session_id=session,
        live_arrangement_clips_by_track=live,
    )

    assert plan.blocked_reasons == [], plan.blocked_reasons
    assert [c.args["action"] for c in plan.calls] == [
        "delete", "duplicate_to_arrangement",
    ], "clear first, then duplicate — never a direct audio create for this row"
    dup = plan.calls[1]
    assert dup.key.startswith("arrangement_clip:")
    assert dup.args == {
        "action": "duplicate_to_arrangement",
        "track_index": 4,
        "clip_index": 1,
        "start_beats": 8.0,  # bar 3 in 4/4
    }
    assert "audio_path" not in dup.args
    # The conform travelled with the duplicate — no gap is reported for it.
    assert not any("did NOT travel" in b for b in plan.blocked_reasons)
    assert not any("did NOT travel" in a for a in plan.alerts)
    # The BLOCK still does not travel (it is the session clip's length, and
    # Live's Clip.end_time has no setter) — said on the operator channel, once
    # for the phase, naming the placement and the route that placed it. The
    # copy's playable REGION does travel, in the post-apply region pass.
    block = [a for a in plan.alerts if "BLOCK each copy occupies" in a]
    assert len(block) == 1 and "duplicate route" in block[0], plan.alerts
    assert "region set to the authored span" in block[0], block[0]
    # The summary counts it as both a duplicate and an audio placement.
    assert any("duplicated 1" in n and "placed 1 audio" in n for n in plan.notes), plan.notes


def test_envelope_hosting_audio_placement_needs_its_source_clip_linked(
    conn, song, session, audio_track, sample,
):
    """The duplicate route addresses the SESSION clip, so — exactly as for an
    envelope-bearing MIDI placement — an unlinked source blocks the track
    (§6a: never clear what cannot be fully rebuilt). This is the one way an
    envelope-hosting audio placement differs from an envelope-free one, which
    needs no session counterpart at all."""
    cid = M.create_audio_clip(
        conn, track_id=audio_track, slot=1, length_beats=8.0,
        audio_file=sample, name="line",
    )
    _host_a_ride(conn, song=song, track=audio_track, clip=cid)

    plan = push.plan_push_arrangement(
        conn, song_id=song, session_id=session,
        live_arrangement_clips_by_track={4: [{"arrangement_clip_index": 1, "start_beats": 0.0}]},
    )
    assert plan.calls == []
    assert any("not linked" in b and "duplicate route" in b for b in plan.blocked_reasons)


def test_envelope_free_audio_placement_keeps_the_direct_create_and_its_gap(
    conn, song, session, audio_track, sample,
):
    """The verdict licenses the envelope case and nothing more: an audio
    placement with no hosted envelope is still a direct
    ``Track.create_audio_clip`` — its clip need not be linked — and the
    authored-conform gap keeps firing for it, because the fresh clip is at
    Live's defaults and the copy cannot be addressed in the same plan."""
    cid = M.create_audio_clip(
        conn, track_id=audio_track, slot=1, length_beats=8.0,
        audio_file=sample, name="line", gain=0.6,
    )
    _place(conn, song=song, track=audio_track, clip=cid)

    plan = push.plan_push_arrangement(
        conn, song_id=song, session_id=session,
        live_arrangement_clips_by_track={4: []},
    )
    assert [c.args["action"] for c in plan.calls] == ["create"]
    assert plan.calls[0].args["kind"] == "audio"
    assert any("did NOT travel" in b and "gain" in b for b in plan.blocked_reasons)


def test_mixed_track_routes_each_audio_placement_by_whether_its_clip_hosts_a_ride(
    conn, song, session, audio_track, sample,
):
    """Two audio placements on one track, one hosting a ride and one not: the
    first duplicates, the second creates directly. Routing is per row."""
    ride = M.create_audio_clip(
        conn, track_id=audio_track, slot=1, length_beats=8.0,
        audio_file=sample, name="ride",
    )
    _link_clip(conn, session=session, clip_id=ride, index=1)
    plain = M.create_audio_clip(
        conn, track_id=audio_track, slot=2, length_beats=8.0,
        audio_file=sample, name="plain",
    )
    _host_a_ride(conn, song=song, track=audio_track, clip=ride, start_bar=1.0)
    _place(conn, song=song, track=audio_track, clip=plain, start_bar=9.0)

    plan = push.plan_push_arrangement(
        conn, song_id=song, session_id=session,
        live_arrangement_clips_by_track={4: []},
    )
    assert plan.blocked_reasons == []
    assert [c.args["action"] for c in plan.calls] == [
        "duplicate_to_arrangement", "create",
    ]


def test_arrangement_missing_sample_blocks_the_track_without_clearing_it(
    conn, song, session, audio_track,
):
    cid = M.create_audio_clip(
        conn, track_id=audio_track, slot=1, length_beats=8.0,
        audio_file="assets/absent.wav", name="ghost",
    )
    _place(conn, song=song, track=audio_track, clip=cid)
    live = {4: [{"arrangement_clip_index": 1, "start_beats": 0.0}]}
    plan = push.plan_push_arrangement(
        conn, song_id=song, session_id=session,
        live_arrangement_clips_by_track=live,
    )
    assert plan.calls == []
    assert any("not on disk" in b for b in plan.blocked_reasons)


def test_arrangement_says_what_the_direct_create_did_not_carry(
    conn, song, session, audio_track, sample,
):
    """The direct create loads a FRESH clip at Live's defaults, so an authored
    conform does not reach the arrangement copy — and the planner cannot
    address that copy in the same plan (its index only exists after apply;
    predicting it is the positional guess ARR-PROJ diagnosed). The placement
    still lands; the run says what did not."""
    cid = M.create_audio_clip(
        conn, track_id=audio_track, slot=1, length_beats=8.0,
        audio_file=sample, name="line", gain=0.6, warp_mode=6,
    )
    _place(conn, song=song, track=audio_track, clip=cid)
    plan = push.plan_push_arrangement(
        conn, song_id=song, session_id=session,
        live_arrangement_clips_by_track={4: []},
    )
    assert any(c.args.get("kind") == "audio" for c in plan.calls)
    gap = "\n".join(plan.blocked_reasons)
    assert "did NOT travel" in gap
    assert "gain" in gap and "warp_mode" in gap


def test_conform_gap_is_not_reported_for_a_track_that_was_skipped(
    conn, song, session, audio_track, sample,
):
    """A gap on a track nobody built would name work nobody attempted."""
    good = M.create_audio_clip(
        conn, track_id=audio_track, slot=1, length_beats=8.0,
        audio_file=sample, name="line", gain=0.6,
    )
    ghost = M.create_audio_clip(
        conn, track_id=audio_track, slot=2, length_beats=8.0,
        audio_file="assets/absent.wav", name="ghost",
    )
    _place(conn, song=song, track=audio_track, clip=good, start_bar=1.0)
    _place(conn, song=song, track=audio_track, clip=ghost, start_bar=5.0)

    plan = push.plan_push_arrangement(
        conn, song_id=song, session_id=session,
        live_arrangement_clips_by_track={4: []},
    )
    assert plan.calls == []
    assert not any("did NOT travel" in b for b in plan.blocked_reasons)


def test_an_audio_track_with_no_db_placements_is_left_untouched_and_named(
    conn, song, session, audio_track, sample,
):
    """Hand-placed audio on a track the DB says nothing about survives — by
    construction, since the projection loop is driven by DB rows. The report
    says so, because 'untouched' and 'forgotten' read identically otherwise."""
    hand = M.create_track(
        conn, song_id=song, track_index=2, name="HandDropped", kind="audio",
    )
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="track", db_id=hand, ableton_index=5,
    )
    cid = M.create_audio_clip(
        conn, track_id=audio_track, slot=1, length_beats=8.0,
        audio_file=sample, name="line",
    )
    _place(conn, song=song, track=audio_track, clip=cid)

    live = {
        4: [],
        5: [{"arrangement_clip_index": 1, "start_beats": 0.0}],
    }
    plan = push.plan_push_arrangement(
        conn, song_id=song, session_id=session,
        live_arrangement_clips_by_track=live,
    )
    assert not any(
        c.args["action"] == "delete" and c.args["track_index"] == 5
        for c in plan.calls
    ), "never clear a lane the DB has no placements for"
    # On the operator channel: "untouched" and "forgotten" read the same in a
    # report that does not mention it, and the executor shows alerts only.
    assert any("HandDropped" in a and "UNTOUCHED" in a for a in plan.alerts)
    assert not any(a in plan.blocked_reasons for a in plan.alerts if "UNTOUCHED" in a)


def test_arrangement_projection_is_the_same_plan_every_push(
    conn, song, session, audio_track, sample,
):
    """Idempotent by construction: same DB + same probed lane → same calls."""
    cid = M.create_audio_clip(
        conn, track_id=audio_track, slot=1, length_beats=8.0,
        audio_file=sample, name="line",
    )
    _place(conn, song=song, track=audio_track, clip=cid)
    live = {4: []}
    first = push.plan_push_arrangement(
        conn, song_id=song, session_id=session,
        live_arrangement_clips_by_track=live,
    )
    second = push.plan_push_arrangement(
        conn, song_id=song, session_id=session,
        live_arrangement_clips_by_track=live,
    )
    assert [c.args for c in first.calls] == [c.args for c in second.calls]
    assert [c.key for c in first.calls] == [c.key for c in second.calls]


# ---------------------------------------------------------------------------
# The wire boundary — every emitted call must be one the MCP surface accepts
# ---------------------------------------------------------------------------


def test_every_emitted_audio_call_validates_against_the_real_mcp_surface(
    conn, song, session, audio_track, sample,
):
    """The mirror-direction boundary check (chunk 02 owns the producer, this
    planner is the consumer): build a real ``wire.Request`` for each emitted
    call and let the dispatcher judge tool / action / param shape. Anything
    other than 'validated, needs Live' means the planner drifted from the wire.
    """
    from hallucinote_mcp import schema, wire
    from hallucinote_mcp import actions as _actions  # noqa: F401 — populates the registry
    from hallucinote_mcp.dispatcher import dispatch

    schema.register_help_actions()

    cid = M.create_audio_clip(
        conn, track_id=audio_track, slot=1, length_beats=8.0,
        audio_file=sample, name="line",
        gain=0.6, pitch_coarse=-3, pitch_fine=12.5, warping=1, warp_mode=6,
        start_marker=0.5, end_marker=4.0,
    )
    M.add_time_signature_point(
        conn, song_id=song, start_bar=1.0, numerator=4, denominator=4,
    )
    _place(conn, song=song, track=audio_track, clip=cid)

    calls = list(push.plan_push_clip(conn, clip_id=cid, session_id=session).calls)
    calls += list(push.plan_push_arrangement(
        conn, song_id=song, session_id=session,
        live_arrangement_clips_by_track={4: []},
    ).calls)
    assert calls, "the fixture must actually emit audio calls"

    for call in calls:
        args = dict(call.args)
        action = args.pop("action")
        resp = dispatch(
            wire.Request(tool=call.tool, action=action, params=args),
            context=None,
        )
        assert getattr(resp, "needs_remote", False) or resp.ok, (
            f"{call.tool}({action}) rejected by the MCP dispatcher: "
            f"{getattr(resp, 'error', None)}"
        )


# ---------------------------------------------------------------------------
# An unknown slot is not an empty one (Critic R-1 / R-12)
# ---------------------------------------------------------------------------


def test_probe_records_a_track_only_on_success_so_failure_stays_absent():
    """The probe's KEY PRESENCE is the signal consumers read.

    A track that probed successfully must be present even when it holds no
    clips; a track whose probe FAILED must be absent. Collapsing those is what
    lets a consumer answer "unknown" with a destructive recreate, so the
    encoding is pinned at the producer as well as the consumer.
    """
    from hallucinote.sync import push_cli

    class _Resp:
        def __init__(self, ok, result=None):
            self.ok, self.result = ok, result

    def send_fn(req):
        idx = req.params["track_index"]
        if idx == 2:
            return _Resp(False)                       # this track's probe FAILED
        if idx == 3:
            return _Resp(True, {"clips": [{"clip_index": 1, "empty": True}]})
        return _Resp(True, {"clips": [
            {"clip_index": 1, "empty": False, "name": "a", "is_audio": True},
        ]})

    out = push_cli._probe_live_session_clips_via_mcp(
        live_tracks=[{"track_index": 1}, {"track_index": 2}, {"track_index": 3}],
        send_fn=send_fn,
    )
    assert 1 in out and len(out[1]) == 1      # populated
    assert 3 in out and out[3] == []          # probed, genuinely empty
    assert 2 not in out                       # FAILED — absent, not empty


def test_live_session_entry_distinguishes_unknown_from_empty():
    """The reader is tri-state, and this is the distinction that matters."""
    from hallucinote.sync.push import clips as pc

    probed = {5: [{"clip_index": 2, "is_audio": True}]}
    # slot holds the clip
    assert pc._live_session_entry(probed, track_at=5, clip_index=2) is not None
    # track probed, slot genuinely empty
    assert pc._live_session_entry(probed, track_at=5, clip_index=9) is None
    # track absent from the map: its probe failed -> UNKNOWN, never "empty"
    assert pc._live_session_entry(probed, track_at=6, clip_index=1) is pc.PROBE_UNKNOWN
    # no probe at all -> also UNKNOWN
    assert pc._live_session_entry(None, track_at=5, clip_index=2) is pc.PROBE_UNKNOWN


def test_a_track_missing_from_the_probe_map_plans_nothing_destructive(
    conn, song, session, audio_track, sample, song_dir,
):
    """The composed behaviour R-1 named, at planner level.

    A probe was taken, but THIS track's per-track probe failed, so its key is
    absent from the map. That is "unknown", not "empty" — and the difference is
    a clip the operator still has. The phase must conform in place and plan no
    create and no delete.

    THE CHANNEL IS PART OF THE CONTRACT, not a detail. `warn` writes to `notes`,
    which the operator is never shown, so reporting there would exit 0 having
    written a conform without verifying which file Live's slot holds — the
    "reported OK without determining its state" failure the sync contract
    forbids. The arrangement phase rules an identical per-track probe failure
    the same way. Asserting `blocked_reasons` is what pins that.
    """
    cid = M.create_audio_clip(
        conn, track_id=audio_track, slot=1, length_beats=8.0,
        audio_file=sample, name="line", gain=0.6,
    )
    _link_clip(conn, session=session, clip_id=cid, index=1)

    # A map that PROBED (not None) but does not carry track 4 — its probe failed.
    plan = push.plan_push_clips(
        conn, song_id=song, session_id=session,
        live_session_clips_by_track={9: []},
    )

    actions = {c.args["action"] for c in plan.calls}
    assert actions <= {"set_property"}, (
        f"an unknown slot must not be answered with a create/replace; got {actions}"
    )
    assert not any(c.args.get("replace") for c in plan.calls)
    assert any(
        "probe for track" in b and "FAILED" in b for b in plan.blocked_reasons
    ), plan.blocked_reasons


def test_extent_gap_is_reported_even_with_nothing_authored_and_does_not_block(
    conn, song, session, audio_track, sample, song_dir,
):
    """The arrangement copy's BLOCK never travels, and that must be said even
    when the row authors no conform columns at all.

    `Track.create_audio_clip` takes a path and a position and no length, and
    Live exposes `Clip.end_time` with NO SETTER, so the block the copy occupies
    is the file's length and no later write moves it. The notice used to be
    gated on some conform column being authored, which hid the case with the
    loudest symptom: a bare placement with an end_bar simply ran long, silently.

    Updated against probe row 27 (Live 12.4.5), which disproved the belief this
    test used to encode — that nothing about the copy's length was reachable.
    `end_marker` and `loop_end` ARE writable on a placed clip, so the alert now
    has to say the two-part truth: the playable region travels, the block does
    not.

    It is an ALERT, not a block, and that split is the point. The block extent
    is true of every audio placement ever planned; routing it as blocked would
    make every song carrying a stem exit non-zero forever. An authored conform
    that did not travel is a different fact — the song asked for something it
    did not get — and that one does block. And it is an alert rather than a note
    because `notes` is the channel the executor discards: a fact the operator
    may have to act on (shorten the block in Live) that never reaches them is
    the silent-drop failure.
    """
    cid = M.create_audio_clip(          # no gain / pitch / warp / markers
        conn, track_id=audio_track, slot=1, length_beats=8.0,
        audio_file=sample, name="line",
    )
    M.add_time_signature_point(
        conn, song_id=song, start_bar=1.0, numerator=4, denominator=4,
    )
    _place(conn, song=song, track=audio_track, clip=cid, start_bar=3.0)

    plan = push.plan_push_arrangement(
        conn, song_id=song, session_id=session,
        live_arrangement_clips_by_track={4: []},
    )
    assert plan.blocked_reasons == [], plan.blocked_reasons
    block = [a for a in plan.alerts if "BLOCK each copy occupies" in a]
    assert len(block) == 1, plan.alerts
    assert "placement end_bar 7" in block[0], block[0]
    # Both halves of the truth, each said exactly once for the phase.
    assert block[0].count("PLAYABLE REGION") == 1, block[0]
    assert block[0].count("Clip.end_time has no setter") == 1, block[0]
    assert not any(
        "BLOCK each copy occupies" in n for n in plan.notes
    ), "operator channel, not notes"


def test_extent_alert_is_one_per_phase_not_one_per_placement(
    conn, song, session, audio_track, sample,
):
    """A stem-heavy song must not bury its report under one alert per
    placement: the block-extent limit is said ONCE for the phase, naming each
    placement (capped, with the cap stated)."""
    cid = M.create_audio_clip(
        conn, track_id=audio_track, slot=1, length_beats=8.0,
        audio_file=sample, name="line",
    )
    for bar in (1.0, 5.0, 9.0, 13.0, 17.0, 21.0, 25.0, 29.0, 33.0, 37.0):
        _place(conn, song=song, track=audio_track, clip=cid, start_bar=bar)

    plan = push.plan_push_arrangement(
        conn, song_id=song, session_id=session,
        live_arrangement_clips_by_track={4: []},
    )
    block = [a for a in plan.alerts if "BLOCK each copy occupies" in a]
    assert len(block) == 1, plan.alerts
    assert "10 audio placement(s)" in block[0]
    assert "and 2 more" in block[0]


# ---------------------------------------------------------------------------
# Unlinked row into an OCCUPIED slot — the pull-ingested seam (#507)
# ---------------------------------------------------------------------------


def test_unlinked_row_into_an_occupied_slot_alerts_the_operator(
    conn, song, session, audio_track, sample,
):
    """Pull writes no link for a clip it ingests, so on the next push the row
    reaches the planner unlinked and its create carries ``replace=True`` —
    the delete is inside the handler, invisible in the plan. When the probe
    shows the slot occupied, the run must say on the operator channel that
    the clip Live holds is deleted and rebuilt, and that hand-set warp
    markers do not survive; a silent replace of a clip the operator dragged
    in is the failure this guards."""
    cid = M.create_audio_clip(
        conn, track_id=audio_track, slot=3, length_beats=8.0,
        audio_file=sample, name="dragged",
    )
    probe = {4: [_live_slot(3, "/anywhere/dragged.wav")]}

    plan = push.plan_push_clip(
        conn, clip_id=cid, session_id=session,
        live_session_clips_by_track=probe,
    )

    assert plan.blocked_reasons == []
    assert plan.calls[0].args["action"] == "create"
    assert plan.calls[0].args["replace"] is True
    alert = next(a for a in plan.alerts if "DELETED" in a)
    assert "slot 3" in alert and "track 4" in alert
    assert "dragged.wav" in alert and "line.wav" in alert
    assert "never pulled" in alert and "warp markers" in alert


def test_unlinked_row_into_an_empty_or_unprobed_slot_is_silent(
    conn, song, session, audio_track, sample,
):
    """The alert is about a clip that exists. An empty slot, or a track the
    probe did not cover, plans the same replace-create and says nothing —
    an alert on every first push would be noise that trains the operator to
    ignore the one that matters."""
    cid = M.create_audio_clip(
        conn, track_id=audio_track, slot=3, length_beats=8.0,
        audio_file=sample, name="fresh",
    )

    empty = push.plan_push_clip(
        conn, clip_id=cid, session_id=session,
        live_session_clips_by_track={4: [_live_slot(1, "/x/other.wav")]},
    )
    unprobed = push.plan_push_clip(
        conn, clip_id=cid, session_id=session,
        live_session_clips_by_track=None,
    )

    for plan in (empty, unprobed):
        assert plan.calls[0].args["action"] == "create"
        assert plan.calls[0].args["replace"] is True
        assert not any("DELETED" in a for a in plan.alerts), plan.alerts


# ---------------------------------------------------------------------------
# The playable-region pass — what Live DOES let a push write on a placed copy
# ---------------------------------------------------------------------------


def _link_placement(conn, *, session, placement_id, index):
    """Record the binding `apply_push_results` writes from the create's
    ``arrangement_clip_index``. The region pass reads THIS, never a position."""
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="arrangement_clip",
        db_id=placement_id, ableton_index=index,
    )


def test_the_region_pass_bounds_a_placed_copy_to_the_authored_span(
    conn, song, session, audio_track, sample,
):
    """Probe row 27 (Live 12.4.5): ``end_marker`` and ``loop_end`` ARE writable
    on a placed arrangement clip, on both routes. So the copy's PLAYABLE REGION
    reaches the arrangement even though its block cannot.

    Both properties, not one: a clip that runs once is bounded by the marker, a
    LOOPING one repeats its brace instead (row 27's clip was ``looping=true``),
    and the planner cannot see which state Live left the copy in — so it moves
    both and the copy sounds the authored span either way.
    """
    cid = M.create_audio_clip(
        conn, track_id=audio_track, slot=1, length_beats=8.0,
        audio_file=sample, name="line",
    )
    M.add_time_signature_point(
        conn, song_id=song, start_bar=1.0, numerator=4, denominator=4,
    )
    aid = _place(conn, song=song, track=audio_track, clip=cid,
                 start_bar=3.0, end_bar=7.0)  # 4 bars = 16 beats
    _link_placement(conn, session=session, placement_id=aid, index=2)

    plan = push.plan_push_arrangement_audio_regions(
        conn, song_id=song, session_id=session,
    )
    assert plan.blocked_reasons == [], plan.blocked_reasons
    assert [c.args["property"] for c in plan.calls] == ["end_marker", "loop_end"]
    for call in plan.calls:
        assert call.tool == "ableton_clip"
        assert call.args["action"] == "set_property"
        assert call.args["location"] == "arrangement"
        assert call.args["track_index"] == 4
        assert call.args["clip_index"] == 2
        assert call.args["value"] == 16.0
        assert call.key.startswith(f"arrangement_clip_region:{aid}:")


def test_the_region_pass_addresses_the_copy_by_its_link_never_by_position(
    conn, song, session, audio_track, sample,
):
    """The whole reason this is a second pass: an arrangement clip's index
    exists only in the create's RESULT. Live's index for a placement need not
    match its ordinal among the song's placements — the region pass reads the
    recorded binding, so a copy Live put at index 9 is addressed at 9."""
    cid = M.create_audio_clip(
        conn, track_id=audio_track, slot=1, length_beats=8.0,
        audio_file=sample, name="line",
    )
    M.add_time_signature_point(
        conn, song_id=song, start_bar=1.0, numerator=4, denominator=4,
    )
    first = _place(conn, song=song, track=audio_track, clip=cid,
                   start_bar=1.0, end_bar=3.0)
    second = _place(conn, song=song, track=audio_track, clip=cid,
                    start_bar=9.0, end_bar=13.0)
    _link_placement(conn, session=session, placement_id=first, index=9)
    _link_placement(conn, session=session, placement_id=second, index=3)

    plan = push.plan_push_arrangement_audio_regions(
        conn, song_id=song, session_id=session,
    )
    by_placement = {}
    for call in plan.calls:
        by_placement.setdefault(call.key.split(":")[1], set()).add(
            (call.args["clip_index"], call.args["value"])
        )
    assert by_placement[first] == {(9, 8.0)}, "8 beats = 2 bars, at Live's 9"
    assert by_placement[second] == {(3, 16.0)}, "16 beats = 4 bars, at Live's 3"


def test_the_region_pass_starts_at_the_conformed_start_marker_on_the_duplicate_route(
    conn, song, session, audio_track, sample,
):
    """The write moves the END of the playable region and nothing else, so it
    has to start from where that region already starts. The duplicate route
    carries the session clip's conformed ``start_marker`` onto the copy, so the
    authored span runs from there — not from Live's 0."""
    cid = M.create_audio_clip(
        conn, track_id=audio_track, slot=1, length_beats=8.0,
        audio_file=sample, name="line", start_marker=2.0, end_marker=8.0,
    )
    _link_clip(conn, session=session, clip_id=cid, index=1)
    M.add_time_signature_point(
        conn, song_id=song, start_bar=1.0, numerator=4, denominator=4,
    )
    _host_a_ride(conn, song=song, track=audio_track, clip=cid, start_bar=1.0)
    aid = Q.get_arrangement_for_song(conn, song)[0]["id"]
    _link_placement(conn, session=session, placement_id=aid, index=1)

    plan = push.plan_push_arrangement_audio_regions(
        conn, song_id=song, session_id=session,
    )
    # _host_a_ride places bars 1→5 (16 beats), and the copy's region already
    # starts at 2.0.
    assert {c.args["value"] for c in plan.calls} == {18.0}


def test_the_direct_create_region_starts_at_zero_because_the_conform_did_not_travel(
    conn, song, session, audio_track, sample,
):
    """The mirror of the duplicate case, and the reason the two are not one
    rule: on the direct-create route the authored ``start_marker`` stays on the
    session clip (that is the conform gap the arrangement phase reports), so the
    copy sits at Live's own 0 and the span must be measured from there."""
    cid = M.create_audio_clip(
        conn, track_id=audio_track, slot=1, length_beats=8.0,
        audio_file=sample, name="line", start_marker=2.0, end_marker=8.0,
    )
    M.add_time_signature_point(
        conn, song_id=song, start_bar=1.0, numerator=4, denominator=4,
    )
    aid = _place(conn, song=song, track=audio_track, clip=cid,
                 start_bar=1.0, end_bar=5.0)
    _link_placement(conn, session=session, placement_id=aid, index=1)

    plan = push.plan_push_arrangement_audio_regions(
        conn, song_id=song, session_id=session,
    )
    assert {c.args["value"] for c in plan.calls} == {16.0}


def test_the_region_pass_refuses_the_beats_domain_on_an_unwarped_clip(
    conn, song, session, audio_track, sample,
):
    """Live's markers carry a dual unit — beats when the clip is warped,
    SECONDS when it is not. A row that authors ``warping = 0`` is saying the
    copy reads seconds, and the authored span is in bars, so the write is
    skipped and said rather than made wrong."""
    cid = M.create_audio_clip(
        conn, track_id=audio_track, slot=1, length_beats=8.0,
        audio_file=sample, name="line", warping=0,
    )
    M.add_time_signature_point(
        conn, song_id=song, start_bar=1.0, numerator=4, denominator=4,
    )
    aid = _place(conn, song=song, track=audio_track, clip=cid)
    _link_placement(conn, session=session, placement_id=aid, index=1)

    plan = push.plan_push_arrangement_audio_regions(
        conn, song_id=song, session_id=session,
    )
    assert plan.calls == []
    assert any("warping=0" in a and "seconds" in a for a in plan.alerts), plan.alerts
    # And the arrangement phase's own line says the same thing, so the operator
    # is not told the region travelled and then told it did not.
    arr = push.plan_push_arrangement(
        conn, song_id=song, session_id=session,
        live_arrangement_clips_by_track={4: []},
    )
    block = [a for a in arr.alerts if "BLOCK each copy occupies" in a]
    assert len(block) == 1 and "region NOT set" in block[0], arr.alerts


def test_the_region_pass_says_which_copies_it_could_not_reach(
    conn, song, session, audio_track, sample,
):
    """A placement with no recorded copy did not materialize. The pass says so
    on the operator channel — a copy left playing its whole file must never be
    a silent surprise — but does NOT block: the arrangement phase already
    reported the reason, and raising it twice would double-count one failure."""
    cid = M.create_audio_clip(
        conn, track_id=audio_track, slot=1, length_beats=8.0,
        audio_file=sample, name="line",
    )
    _place(conn, song=song, track=audio_track, clip=cid)

    plan = push.plan_push_arrangement_audio_regions(
        conn, song_id=song, session_id=session,
    )
    assert plan.calls == []
    assert plan.blocked_reasons == []
    assert any("no recorded arrangement clip" in a for a in plan.alerts), plan.alerts


def test_a_song_with_no_audio_placements_plans_no_region_work(
    conn, song, session, audio_track, sample,
):
    """A MIDI-only arrangement is not this pass's business, and an empty plan
    from it must read as 'nothing to do', never as blocked work."""
    midi_track = M.create_track(
        conn, song_id=song, track_index=2, name="Keys", kind="midi",
    )
    cid = M.create_clip(conn, track_id=midi_track, slot=1, length_beats=8.0)
    _place(conn, song=song, track=midi_track, clip=cid)

    plan = push.plan_push_arrangement_audio_regions(
        conn, song_id=song, session_id=session,
    )
    assert plan.calls == []
    assert plan.blocked_reasons == [] and plan.alerts == []


def test_the_region_key_kind_resolves_in_the_apply_layer(
    conn, song, session, audio_track, sample,
):
    """Multi-hop: the pass's results come back to ``apply_push_results``, which
    raises on any key kind nobody declared — the bug class that shipped twice
    as ``device_param_override`` / ``device_chain_props``. A region write
    records no binding (the copy's link is what it addressed), so it must
    resolve as an ack, and the link it used must survive the round trip."""
    cid = M.create_audio_clip(
        conn, track_id=audio_track, slot=1, length_beats=8.0,
        audio_file=sample, name="line",
    )
    M.add_time_signature_point(
        conn, song_id=song, start_bar=1.0, numerator=4, denominator=4,
    )
    aid = _place(conn, song=song, track=audio_track, clip=cid)
    _link_placement(conn, session=session, placement_id=aid, index=5)

    plan = push.plan_push_arrangement_audio_regions(
        conn, song_id=song, session_id=session,
    )
    assert plan.calls, "fixture precondition"
    push.apply_push_results(
        conn,
        [{"key": c.key, "ok": True, "tool": c.tool, "result": {}}
         for c in plan.calls],
        session_id=session, actor="sync", reason="test",
    )
    assert Q.get_ableton_link(
        conn, session_id=session, db_kind="arrangement_clip", db_id=aid,
    ) == 5


def test_every_emitted_region_call_validates_against_the_real_mcp_surface(
    conn, song, session, audio_track, sample,
):
    """The wire boundary for the new pass: a region write that the MCP's
    ``set_property`` would reject is a planner that drifted from the surface it
    is addressing."""
    from hallucinote_mcp import schema, wire
    from hallucinote_mcp import actions as _actions  # noqa: F401 — populates the registry
    from hallucinote_mcp.dispatcher import dispatch

    schema.register_help_actions()

    cid = M.create_audio_clip(
        conn, track_id=audio_track, slot=1, length_beats=8.0,
        audio_file=sample, name="line",
    )
    M.add_time_signature_point(
        conn, song_id=song, start_bar=1.0, numerator=4, denominator=4,
    )
    aid = _place(conn, song=song, track=audio_track, clip=cid)
    _link_placement(conn, session=session, placement_id=aid, index=1)

    calls = push.plan_push_arrangement_audio_regions(
        conn, song_id=song, session_id=session,
    ).calls
    assert calls, "fixture precondition"
    for call in calls:
        args = dict(call.args)
        action = args.pop("action")
        resp = dispatch(
            wire.Request(tool=call.tool, action=action, params=args),
            context=None,
        )
        assert getattr(resp, "needs_remote", False) or resp.ok, (
            f"{call.tool}({action}) rejected by the MCP dispatcher: "
            f"{getattr(resp, 'error', None)}"
        )
