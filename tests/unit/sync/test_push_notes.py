"""Tests for scoped note push (build-plan B1) — the incremental compose loop's
materialize step.

Strategy mirrors test_push_execute: build a tiny song, inject a fake ``send_fn``
shaped like ``hallucinote_mcp.client.send``. The track is pre-linked so
``plan_push_clip`` chooses create (unlinked clip) then replace_notes (linked
clip) without a full eleven-phase push. Tests assert on the dispatched call log and
the returned counts-only summary — notes never appear.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

import pytest

from hallucinote.db import init_db, mutations as M
from hallucinote.sync import push_notes


@dataclass
class FakeResponse:
    ok: bool
    result: dict | None = None
    error: str | None = None
    hint: str | None = None


def _make_send_fn(*, fail_on=frozenset(), raise_on=frozenset()):
    """Fake dispatcher. Returns clip_index for clip-create (so the link gets
    recorded), {} for replace_notes. ``fail_on`` / ``raise_on`` are sets of
    ``"tool:action"`` composites for failure / connection-loss simulation.
    """
    counter = {"n": 0}
    call_log: list[dict] = []

    def send(req):
        composite = f"{req.tool}:{req.action}"
        call_log.append({"tool": req.tool, "action": req.action,
                         "params_keys": sorted(req.params.keys())})
        if composite in raise_on:
            raise ConnectionRefusedError("simulated Live unreachable")
        if composite in fail_on:
            return FakeResponse(ok=False, error=f"simulated failure {composite}")
        if req.tool == "ableton_clip" and req.action == "create":
            counter["n"] += 1
            return FakeResponse(ok=True, result={"clip_index": counter["n"]})
        return FakeResponse(ok=True, result={})

    send.call_log = call_log  # type: ignore[attr-defined]
    return send


_N1 = [
    {"pitch": 60, "velocity": 100, "start_beats": 0.0, "duration_beats": 0.5, "mute": 0},
    {"pitch": 62, "velocity": 110, "start_beats": 1.0, "duration_beats": 0.5, "mute": 0},
]
_N2 = [
    {"pitch": 64, "velocity": 90, "start_beats": 0.0, "duration_beats": 1.0, "mute": 0},
]


@pytest.fixture
def conn(tmp_path):
    c = init_db(tmp_path / "notes.db")
    yield c
    c.close()


@pytest.fixture
def state_dir(tmp_path):
    return tmp_path / "state"


@pytest.fixture
def song(conn):
    return M.create_song(conn, name="t", key="Dm")


@pytest.fixture
def session(conn, song):
    return M.create_ableton_session(conn, song_id=song, name="draft")


@pytest.fixture
def linked_song(conn, song, session):
    """1 linked track + 2 clips (A: 2 notes, B: 1 note). Track pre-linked so
    plan_push_clip works without a full push."""
    tid = M.create_track(conn, song_id=song, track_index=1, name="Drums", kind="midi")
    M.link_db_to_ableton(conn, session_id=session, db_kind="track", db_id=tid,
                         ableton_index=1, actor="sync")
    a = M.create_clip(conn, track_id=tid, slot=1, length_beats=4.0, name="A")
    b = M.create_clip(conn, track_id=tid, slot=2, length_beats=4.0, name="B")
    M.insert_notes(conn, clip_id=a, notes=_N1)
    M.insert_notes(conn, clip_id=b, notes=_N2)
    return {"track_id": tid, "clip_a": a, "clip_b": b, "song_id": song}


# ---------------------------------------------------------------------------
# Fingerprint helper
# ---------------------------------------------------------------------------


def test_fingerprint_stable_for_reordered_identical_notes():
    fp_sorted = push_notes.clip_fingerprint(_N1)
    fp_rev = push_notes.clip_fingerprint(list(reversed(_N1)))
    assert fp_sorted == fp_rev


def test_fingerprint_changes_when_a_note_moves():
    moved = [dict(_N1[0], start_beats=0.25), _N1[1]]
    assert push_notes.clip_fingerprint(moved) != push_notes.clip_fingerprint(_N1)


def test_fingerprint_unaffected_by_tags_only_change():
    # tags aren't sent to Live, so they must not force a re-push.
    tagged = [dict(n, tags=["ghost"]) for n in _N1]
    assert push_notes.clip_fingerprint(tagged) == push_notes.clip_fingerprint(_N1)


# ---------------------------------------------------------------------------
# Scope
# ---------------------------------------------------------------------------


def test_explicit_scope_pushes_only_targeted_clip(conn, session, linked_song, state_dir):
    send = _make_send_fn()
    res = push_notes.push_notes(
        conn, song_id=linked_song["song_id"], session_id=session,
        state_dir=state_dir, clip_ids=[linked_song["clip_a"]], send_fn=send,
    )
    assert [p["clip_id"] for p in res.pushed] == [linked_song["clip_a"]]
    assert res.skipped == []
    # exactly one create call dispatched (clip A), nothing for clip B
    assert len(send.call_log) == 1
    assert send.call_log[0] == {
        "tool": "ableton_clip", "action": "create",
        "params_keys": sorted(["location", "kind", "track_index", "clip_index",
                               "length", "name", "notes", "replace"]),
    }


def test_whole_song_pushes_all_clips(conn, session, linked_song, state_dir):
    send = _make_send_fn()
    res = push_notes.push_notes(
        conn, song_id=linked_song["song_id"], session_id=session,
        state_dir=state_dir, send_fn=send,
    )
    assert {p["clip_id"] for p in res.pushed} == {linked_song["clip_a"], linked_song["clip_b"]}
    assert len(res.pushed) == 2


def test_audio_clip_is_skipped_never_reported_pushed(
    conn, session, linked_song, state_dir
):
    """CLP-AUD1: a kind='audio' clip in scope is skipped with a teaching
    reason — without the guard, plan_push_clip's refuse-loudly empty plan
    would fall through and misreport the clip as pushed (note_count 0)."""
    audio_tid = M.create_track(
        conn, song_id=linked_song["song_id"], track_index=2, name="Stems",
        kind="audio",
    )
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="track", db_id=audio_tid,
        ableton_index=2, actor="sync",
    )
    ac = M.create_audio_clip(
        conn, track_id=audio_tid, slot=1, length_beats=16.0,
        audio_file="assets/gtr.wav", name="gtr",
    )
    send = _make_send_fn()
    res = push_notes.push_notes(
        conn, song_id=linked_song["song_id"], session_id=session,
        state_dir=state_dir, send_fn=send,
    )
    assert {p["clip_id"] for p in res.pushed} == {
        linked_song["clip_a"], linked_song["clip_b"],
    }
    assert [s["clip_id"] for s in res.skipped] == [ac]
    # The reason must explain that an audio clip HAS no notes — a permanent
    # fact — and must not promise a pending scope. It used to name CLP-AUD2,
    # which has now shipped: the clip itself IS pushed, by the clips phase, so
    # a reason saying "authored but not synced" would send a reader looking for
    # a gap that closed.
    reason = res.skipped[0]["reason"]
    assert "no notes" in reason
    assert "CLP-AUD2" not in reason
    assert "not synced" not in reason
    # No wire call was dispatched for the audio clip (2 MIDI creates only).
    assert len(send.call_log) == 2
    assert all(c["action"] == "create" for c in send.call_log)


# ---------------------------------------------------------------------------
# changed_only — content fingerprint
# ---------------------------------------------------------------------------


def test_changed_only_skips_unchanged_on_second_run(conn, session, linked_song, state_dir):
    push_notes.push_notes(conn, song_id=linked_song["song_id"], session_id=session,
                          state_dir=state_dir, send_fn=_make_send_fn())
    send2 = _make_send_fn()
    res = push_notes.push_notes(conn, song_id=linked_song["song_id"], session_id=session,
                                state_dir=state_dir, changed_only=True, send_fn=send2)
    assert res.pushed == []
    assert {s["clip_id"] for s in res.skipped} == {linked_song["clip_a"], linked_song["clip_b"]}
    assert send2.call_log == []  # nothing dispatched


def test_changed_only_repushes_modified_clip_skips_others(conn, session, linked_song, state_dir):
    push_notes.push_notes(conn, song_id=linked_song["song_id"], session_id=session,
                          state_dir=state_dir, send_fn=_make_send_fn())
    # Move a note in clip A.
    M.replace_clip_notes(conn, clip_id=linked_song["clip_a"],
                         notes=[dict(_N1[0], start_beats=0.25), _N1[1]])
    send2 = _make_send_fn()
    res = push_notes.push_notes(conn, song_id=linked_song["song_id"], session_id=session,
                                state_dir=state_dir, changed_only=True, send_fn=send2)
    assert [p["clip_id"] for p in res.pushed] == [linked_song["clip_a"]]
    assert [s["clip_id"] for s in res.skipped] == [linked_song["clip_b"]]
    # clip A is now linked -> replace_notes, not create
    assert [c["action"] for c in send2.call_log] == ["replace_notes"]


def test_changed_only_detects_total_replace(conn, session, linked_song, state_dir):
    push_notes.push_notes(conn, song_id=linked_song["song_id"], session_id=session,
                          state_dir=state_dir, send_fn=_make_send_fn())
    # Delete all, add a totally different set.
    M.replace_clip_notes(conn, clip_id=linked_song["clip_a"], notes=[
        {"pitch": 40 + i, "velocity": 80, "start_beats": float(i) * 0.25,
         "duration_beats": 0.25} for i in range(8)
    ])
    send2 = _make_send_fn()
    res = push_notes.push_notes(conn, song_id=linked_song["song_id"], session_id=session,
                                state_dir=state_dir, changed_only=True, send_fn=send2)
    assert [p["clip_id"] for p in res.pushed] == [linked_song["clip_a"]]
    assert res.pushed[0]["note_count"] == 8


def test_changed_only_skips_rebuilt_identical_clip(conn, session, linked_song, state_dir):
    """A whole-DB rebuild that reproduces identical content must NOT re-push —
    the fingerprint is content-based, not event-based."""
    push_notes.push_notes(conn, song_id=linked_song["song_id"], session_id=session,
                          state_dir=state_dir, send_fn=_make_send_fn())
    # Rewrite clip A with byte-identical content (simulates build.py re-run).
    M.replace_clip_notes(conn, clip_id=linked_song["clip_a"], notes=_N1)
    send2 = _make_send_fn()
    res = push_notes.push_notes(conn, song_id=linked_song["song_id"], session_id=session,
                                state_dir=state_dir, changed_only=True, send_fn=send2)
    assert res.pushed == []
    assert send2.call_log == []


# ---------------------------------------------------------------------------
# Summary shape — counts, never notes
# ---------------------------------------------------------------------------


def test_summary_carries_counts_never_notes(conn, session, linked_song, state_dir):
    res = push_notes.push_notes(conn, song_id=linked_song["song_id"], session_id=session,
                                state_dir=state_dir, send_fn=_make_send_fn())
    summary = res.to_summary()
    blob = json.dumps(summary)
    assert '"notes"' not in blob
    assert "start_beats" not in blob and "start_time" not in blob
    assert all(isinstance(p["note_count"], int) for p in summary["pushed"])
    assert summary["counts"]["pushed"] == 2


# ---------------------------------------------------------------------------
# Error + abort paths
# ---------------------------------------------------------------------------


def test_unknown_clip_id_surfaces_as_error(conn, session, linked_song, state_dir):
    res = push_notes.push_notes(conn, song_id=linked_song["song_id"], session_id=session,
                                state_dir=state_dir, clip_ids=["does-not-exist"],
                                send_fn=_make_send_fn())
    assert res.pushed == []
    assert len(res.errors) == 1
    assert "not found" in res.errors[0]["error"]


def test_unlinked_track_surfaces_teaching_error(conn, session, song, state_dir):
    # Clip on a track that was never linked in this session.
    tid = M.create_track(conn, song_id=song, track_index=1, name="X", kind="midi")
    cid = M.create_clip(conn, track_id=tid, slot=1, length_beats=4.0, name="orphan")
    M.insert_notes(conn, clip_id=cid, notes=_N2)
    res = push_notes.push_notes(conn, song_id=song, session_id=session,
                                state_dir=state_dir, clip_ids=[cid],
                                send_fn=_make_send_fn())
    assert res.pushed == []
    assert len(res.errors) == 1
    assert "not linked" in res.errors[0]["error"]


def test_connection_loss_aborts_and_records_partial_fingerprints(
    conn, session, linked_song, state_dir,
):
    # Raise on clip create — but A succeeds first, B raises.
    # Force A to succeed by making the raise fire only on the 2nd call: use a
    # send that raises on create AFTER the first. Simpler: explicit order A,B
    # with a counting wrapper.
    calls = {"n": 0}
    base = _make_send_fn()

    def send_fn(req):
        calls["n"] += 1
        if calls["n"] == 2:  # second dispatched call (clip B)
            raise ConnectionRefusedError("Live gone")
        return base(req)

    res = push_notes.push_notes(
        conn, song_id=linked_song["song_id"], session_id=session,
        state_dir=state_dir,
        clip_ids=[linked_song["clip_a"], linked_song["clip_b"]],
        send_fn=send_fn,
    )
    assert res.connection_lost is True
    assert [p["clip_id"] for p in res.pushed] == [linked_song["clip_a"]]
    assert any(e["clip_id"] == linked_song["clip_b"] for e in res.errors)
    # A's fingerprint persisted so a re-run skips it.
    state = json.loads((state_dir / push_notes.NOTES_PUSH_STATE).read_text())
    assert linked_song["clip_a"] in state["fingerprints"]
    assert linked_song["clip_b"] not in state["fingerprints"]


# ---------------------------------------------------------------------------
# B1b — clip-prune planner (pure)
# ---------------------------------------------------------------------------

from hallucinote.sync import push  # noqa: E402


def test_prune_planner_flags_orphan_keeps_db_backed():
    plan = push.plan_clip_prune([{
        "track_index": 1, "track_name": "Drums",
        "db_slots": {1},
        "live_clips": [{"clip_index": 1, "name": "keep"},
                       {"clip_index": 2, "name": "orphan"}],
    }])
    assert [(t.track_index, t.clip_index, t.name) for t in plan.prunable] == [(1, 2, "orphan")]
    assert plan.refusals == []


def test_prune_planner_never_prunes_db_backed_slot():
    plan = push.plan_clip_prune([{
        "track_index": 1, "track_name": "Bass", "db_slots": {1, 2, 3},
        "live_clips": [{"clip_index": 1, "name": "a"}, {"clip_index": 2, "name": "b"}],
    }])
    assert plan.prunable == []


def test_prune_planner_refuses_whole_track_orphan():
    plan = push.plan_clip_prune([{
        "track_index": 4, "track_name": "Stray", "db_slots": None,
        "live_clips": [{"clip_index": 1, "name": "x"}],
    }])
    assert plan.prunable == []
    assert len(plan.refusals) == 1
    assert plan.refusals[0]["kind"] == "no_db_track_linked"
    assert plan.refusals[0]["track_index"] == 4


def test_prune_planner_unlinked_empty_track_is_silent():
    plan = push.plan_clip_prune([{
        "track_index": 4, "track_name": "Empty", "db_slots": None, "live_clips": [],
    }])
    assert plan.prunable == []
    assert plan.refusals == []


def test_prune_planner_to_dict_shape():
    plan = push.plan_clip_prune([{
        "track_index": 1, "track_name": "T", "db_slots": set(),
        "live_clips": [{"clip_index": 5, "name": "z"}],
    }])
    # db_slots is an empty set (linked track, zero DB clips) -> every live clip
    # is an orphan and prunable (distinct from db_slots=None / unlinked).
    d = plan.to_dict()
    assert d["prunable"] == [{"track_index": 1, "track_name": "T",
                              "clip_index": 5, "name": "z"}]
    assert d["refusals"] == []


# ---------------------------------------------------------------------------
# PSH-6W2J — scoped push propagates note edits to arrangement copies
# ---------------------------------------------------------------------------


def _make_recording_send():
    """Like `_make_send_fn` but records each call's `location` VALUE, so a
    session replace_notes (location='session') is distinguishable from an
    arrangement refresh (location='arrangement') — both carry the same param
    KEYS, so key-only logging can't tell them apart."""
    counter = {"n": 0}
    call_log: list[dict] = []

    def send(req):
        call_log.append({
            "tool": req.tool, "action": req.action,
            "location": req.params.get("location"),
        })
        if req.tool == "ableton_clip" and req.action == "create":
            counter["n"] += 1
            return FakeResponse(ok=True, result={"clip_index": counter["n"]})
        return FakeResponse(ok=True, result={})

    send.call_log = call_log  # type: ignore[attr-defined]
    return send


def _place_and_link_arrangement(conn, *, session, song, track_id, clip_id, arr_index):
    """Materialize+link an arrangement copy of a session clip, as a prior full
    push would have. Returns the arrangement_clip id."""
    aid = M.add_arrangement_clip(
        conn, song_id=song, track_id=track_id, clip_id=clip_id,
        start_bar=1.0, end_bar=5.0,
    )
    push.apply_push_results(
        conn,
        [{"key": f"arrangement_clip:{aid}", "ok": True, "tool": "ableton_clip",
          "result": {"arrangement_clip_index": arr_index}}],
        session_id=session,
    )
    return aid


def test_scoped_push_refreshes_linked_arrangement_copy(
    conn, session, linked_song, state_dir
):
    """The bug: a scoped note push updated the session clip but not its
    arrangement copy (silent stale render). Now pushing a clip with a linked
    arrangement placement dispatches a replace_notes(location='arrangement') too.
    """
    a = linked_song["clip_a"]
    # Link the session clip (so the session push is replace_notes), then
    # materialize+link one arrangement copy of it.
    M.link_db_to_ableton(conn, session_id=session, db_kind="clip", db_id=a,
                         ableton_index=1, actor="sync")
    _place_and_link_arrangement(
        conn, session=session, song=linked_song["song_id"],
        track_id=linked_song["track_id"], clip_id=a, arr_index=2,
    )
    send = _make_recording_send()
    res = push_notes.push_notes(
        conn, song_id=linked_song["song_id"], session_id=session,
        state_dir=state_dir, clip_ids=[a], send_fn=send,
    )
    assert [p["clip_id"] for p in res.pushed] == [a]
    assert res.errors == []
    # Two replace_notes calls: the session clip + the arrangement copy refresh.
    locations = [
        c["location"] for c in send.call_log
        if c["tool"] == "ableton_clip" and c["action"] == "replace_notes"
    ]
    assert sorted(locations) == ["arrangement", "session"], (
        f"expected one session + one arrangement refresh, got: {send.call_log}"
    )


def test_scoped_push_no_arrangement_call_when_clip_has_no_placement(
    conn, session, linked_song, state_dir
):
    """A clip with no arrangement copy dispatches only the session push — the
    propagation is additive, not a blanket extra round-trip."""
    a = linked_song["clip_a"]
    M.link_db_to_ableton(conn, session_id=session, db_kind="clip", db_id=a,
                         ableton_index=1, actor="sync")
    send = _make_recording_send()
    push_notes.push_notes(
        conn, song_id=linked_song["song_id"], session_id=session,
        state_dir=state_dir, clip_ids=[a], send_fn=send,
    )
    assert len(send.call_log) == 1
    assert send.call_log[0]["action"] == "replace_notes"
    assert send.call_log[0]["location"] == "session"  # session form only


def test_scoped_changed_only_unchanged_clip_skips_arrangement_too(
    conn, session, linked_song, state_dir
):
    """When changed_only skips an unchanged session clip, its arrangement copy
    is skipped too — an unchanged session clip means an unchanged copy."""
    a = linked_song["clip_a"]
    M.link_db_to_ableton(conn, session_id=session, db_kind="clip", db_id=a,
                         ableton_index=1, actor="sync")
    _place_and_link_arrangement(
        conn, session=session, song=linked_song["song_id"],
        track_id=linked_song["track_id"], clip_id=a, arr_index=2,
    )
    # First push records the fingerprint (session + arrangement dispatched).
    push_notes.push_notes(
        conn, song_id=linked_song["song_id"], session_id=session,
        state_dir=state_dir, clip_ids=[a], send_fn=_make_send_fn(),
    )
    # Second push, unchanged + changed_only: nothing dispatched at all.
    send2 = _make_send_fn()
    res = push_notes.push_notes(
        conn, song_id=linked_song["song_id"], session_id=session,
        state_dir=state_dir, clip_ids=[a], changed_only=True, send_fn=send2,
    )
    assert res.pushed == []
    assert send2.call_log == []


def test_push_writes_a_self_ignore_beside_its_state_file(
    conn, session, linked_song, state_dir,
):
    """WSP-3R7K: the push's own bookkeeping ignores itself where it lands.

    `.last-notes-push.json` sits in the song dir next to authored work, so a
    workspace created before `init-workspace` shipped its managed root block
    (or by a bare `git init`) surfaced it — and the MixReports and snapshot
    backups beside it — as committable on every push. The ignore is written by
    the tool that generates the file, so it needs no root-.gitignore edit and
    travels with the artifact.
    """
    from hallucinote.paths import SONG_DIR_IGNORED_FILES

    push_notes.push_notes(
        conn, song_id=linked_song["song_id"], session_id=session,
        state_dir=state_dir, send_fn=_make_send_fn(),
    )

    gitignore = state_dir / ".gitignore"
    assert gitignore.exists(), (
        "the push wrote .last-notes-push.json but left it committable"
    )
    lines = gitignore.read_text().splitlines()
    assert "*" not in lines, (
        "the song dir holds build.py and captured_session.json — a blanket "
        "ignore here would swallow the song itself"
    )
    for name in SONG_DIR_IGNORED_FILES:
        assert name in lines


# ---------------------------------------------------------------------------
# SYN-4T7B (#328) — "--changed reported 0 pushed after a change".
#
# Investigation item, filed WITH its own confound: the reporting session had a
# stray second DB for one song (WSP-8Q4M, since fixed — `resolve_db_path` now
# probes the branch in the song's OWN repo for both root forms). These tests
# pin the contract against a SINGLE DB and a SINGLE state dir, which is the
# repro the item asked for, plus the cross-DB shape the confound actually has.
# ---------------------------------------------------------------------------


def test_a_rebuild_that_changes_pitches_is_pushed_and_nothing_else_is(
    conn, session, linked_song, state_dir,
):
    """The item's acceptance criterion, both halves.

    Push, rebuild one clip's PITCHES, push `--changed`: exactly that clip is
    reported pushed and exactly it is dispatched. Then push `--changed` again:
    `pushed: 0` AND zero calls dispatched — which is what makes the count
    evidence about Live rather than a claim beside it.
    """
    push_notes.push_notes(conn, song_id=linked_song["song_id"], session_id=session,
                          state_dir=state_dir, send_fn=_make_send_fn())
    # The reported shape: same note grid, different pitches.
    M.replace_clip_notes(conn, clip_id=linked_song["clip_a"], notes=[
        dict(n, pitch=n["pitch"] - 21) for n in _N1
    ])

    send2 = _make_send_fn()
    res = push_notes.push_notes(
        conn, song_id=linked_song["song_id"], session_id=session,
        state_dir=state_dir, changed_only=True, send_fn=send2,
    )
    assert [p["clip_id"] for p in res.pushed] == [linked_song["clip_a"]]
    assert [s["clip_id"] for s in res.skipped] == [linked_song["clip_b"]]
    assert [c["action"] for c in send2.call_log] == ["replace_notes"]

    send3 = _make_send_fn()
    res3 = push_notes.push_notes(
        conn, song_id=linked_song["song_id"], session_id=session,
        state_dir=state_dir, changed_only=True, send_fn=send3,
    )
    assert res3.pushed == []
    assert send3.call_log == [], (
        "a run reporting pushed: 0 must leave Live untouched — a dispatched "
        "call under a zero count is the discrepancy SYN-4T7B reported"
    )


def test_the_fingerprint_ledger_is_one_file_per_song_dir_not_per_db(tmp_path):
    """The confound, made concrete — and one correction to how it was filed.

    SYN-4T7B assumed each of the two DBs carried "its own fingerprint state".
    It does not: per-branch DBs are siblings in ONE song dir, and
    `NOTES_PUSH_STATE` is a fixed filename, so `state_dir = db_path.parent`
    resolves to the SAME ledger for every branch's DB.

    What keeps that safe is that clip ids are per-DB, so the ledger accumulates
    two disjoint key sets and one DB's push can never mark another DB's clip
    "unchanged". What it does NOT prevent is the reported sequence: a rebuild
    that lands in DB B leaves DB A genuinely unchanged, so a `--changed` run
    reading DB A correctly reports `pushed: 0` while Live holds what a push
    from DB B put there. The counts were right about the DB they were given.
    """
    song_dir = tmp_path / "songs" / "the-argument"
    song_dir.mkdir(parents=True)

    built = []
    for db_name in ("the-argument-main.db", "the-argument-feat--x.db"):
        c = init_db(song_dir / db_name)
        song_id = M.create_song(c, name="the-argument", key="Dm")
        sess = M.create_ableton_session(c, song_id=song_id, name="draft")
        tid = M.create_track(c, song_id=song_id, track_index=1, name="Bass",
                             kind="midi")
        M.link_db_to_ableton(c, session_id=sess, db_kind="track", db_id=tid,
                             ableton_index=1, actor="sync")
        clip = M.create_clip(c, track_id=tid, slot=1, length_beats=4.0, name="A")
        M.insert_notes(c, clip_id=clip, notes=_N1)
        built.append({"conn": c, "song_id": song_id, "session": sess,
                      "clip": clip})

    a, b = built
    # One ledger, written by whichever DB pushed last.
    state_dir = song_dir
    push_notes.push_notes(a["conn"], song_id=a["song_id"],
                          session_id=a["session"], state_dir=state_dir,
                          send_fn=_make_send_fn())
    ledger = json.loads((state_dir / push_notes.NOTES_PUSH_STATE).read_text())
    assert list(ledger["fingerprints"]) == [a["clip"]]

    # DB B pushes into the same file: the key sets are disjoint, so B's clip
    # is NOT pre-skipped by A's entry even though the note content is identical.
    send_b = _make_send_fn()
    res_b = push_notes.push_notes(b["conn"], song_id=b["song_id"],
                                  session_id=b["session"], state_dir=state_dir,
                                  changed_only=True, send_fn=send_b)
    assert [p["clip_id"] for p in res_b.pushed] == [b["clip"]]
    ledger = json.loads((state_dir / push_notes.NOTES_PUSH_STATE).read_text())
    assert sorted(ledger["fingerprints"]) == sorted([a["clip"], b["clip"]])

    # Now the reported sequence: the REBUILD lands in DB B only.
    M.replace_clip_notes(b["conn"], clip_id=b["clip"], notes=[
        dict(n, pitch=n["pitch"] - 21) for n in _N1
    ])
    send_a2 = _make_send_fn()
    res_a2 = push_notes.push_notes(a["conn"], song_id=a["song_id"],
                                   session_id=a["session"], state_dir=state_dir,
                                   changed_only=True, send_fn=send_a2)
    assert res_a2.pushed == []
    assert [s["reason"] for s in res_a2.skipped] == ["unchanged"]
    assert send_a2.call_log == []
    for entry in built:
        entry["conn"].close()
