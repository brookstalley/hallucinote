"""Tests for scoped note push (build-plan B1) — the incremental compose loop's
materialize step.

Strategy mirrors test_push_execute: build a tiny song, inject a fake ``send_fn``
shaped like ``hallucinote_mcp.client.send``. The track is pre-linked so
``plan_push_clip`` chooses create (unlinked clip) then replace_notes (linked
clip) without a full ten-phase push. Tests assert on the dispatched call log and
the returned counts-only summary — notes never appear.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

import pytest

from hallucinote.db import init_db, mutations as M, queries as Q
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
    send = _make_send_fn(raise_on={"ableton_clip:create"})
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
