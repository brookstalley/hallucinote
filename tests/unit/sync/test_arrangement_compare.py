"""ARR-PROJ Chunk 3 — the arrangement integrity comparator (pure)."""
from __future__ import annotations

from hallucinote.sync.arrangement_compare import (
    NoteLite,
    compare_clip_notes,
)


def db(pitch, start, dur=1.0, vel=100):
    return {"pitch": pitch, "start_beats": start, "duration_beats": dur, "velocity": vel}


def live(pitch, start, dur=1.0, vel=100):
    # MCP note-API shape (start_time / duration).
    return {"pitch": pitch, "start_time": start, "duration": dur, "velocity": vel}


def test_identical_sets_are_faithful():
    notes = [db(60, 0.0), db(62, 1.0), db(64, 2.0)]
    lv = [live(60, 0.0), live(62, 1.0), live(64, 2.0)]
    assert compare_clip_notes(notes, lv).faithful


def test_wildness_stack_is_faithful_not_divergent():
    """Normalization #1: build.py stacks notes sharing (pitch, start) with
    different dur/vel (add_wildness); Live holds ONE per (pitch, start). The
    collapsed set matches → faithful, NOT a false missing/extra. This is the
    exact false-positive a raw-count compare would fire (alien Human Riff
    chorus3: 332 raw DB → 305 Live, faithful)."""
    db_notes = [
        db(60, 0.0, dur=1.0, vel=100),
        db(60, 0.0, dur=0.5, vel=120),  # same (pitch,start), different dur/vel
        db(60, 0.0, dur=2.0, vel=80),
        db(62, 1.0),
    ]
    # Live collapsed to one note per (pitch,start) — keeps one of the stack.
    lv = [live(60, 0.0, dur=0.5, vel=120), live(62, 1.0)]
    diff = compare_clip_notes(db_notes, lv)
    assert diff.faithful, diff.summary()


def test_float_round_trip_noise_is_faithful():
    """Normalization #2: start/dur within eps, velocity within tolerance — a
    capture/probe round-trip's ~1e-7 noise must NOT read as divergence."""
    db_notes = [db(60, 1.0, dur=0.25, vel=100)]
    lv = [live(60, 1.0 + 7e-8, dur=0.25 - 5e-8, vel=100)]
    assert compare_clip_notes(db_notes, lv).faithful


def test_velocity_within_tolerance_is_faithful():
    db_notes = [db(60, 0.0, vel=100)]
    lv = [live(60, 0.0, vel=101)]  # off by 1 == DEFAULT_VEL_TOL
    assert compare_clip_notes(db_notes, lv).faithful


def test_dropped_note_reads_missing():
    """The 2026-06-21 bulk-drop: a DB note absent from Live → missing."""
    db_notes = [db(60, 0.0), db(62, 1.0)]
    lv = [live(60, 0.0)]  # 62@1.0 dropped
    diff = compare_clip_notes(db_notes, lv)
    assert not diff.faithful
    assert [n.pitch for n in diff.missing] == [62]
    assert diff.extra == []


def test_orphan_survivor_reads_extra():
    """The 2026-06-22 replace_notes orphan: a Live note with no DB key → extra."""
    db_notes = [db(60, 0.0)]
    lv = [live(60, 0.0), live(67, 3.0)]  # 67@3.0 is a stale orphan
    diff = compare_clip_notes(db_notes, lv)
    assert not diff.faithful
    assert [n.pitch for n in diff.extra] == [67]
    assert diff.missing == []


def test_dur_vel_drift_beyond_tolerance_reads_mismatch():
    """A matched (pitch, start) key whose Live note matches NO DB stack member
    within tolerance → mismatch (not missing/extra)."""
    db_notes = [db(60, 0.0, dur=1.0, vel=100)]
    lv = [live(60, 0.0, dur=1.0, vel=40)]  # velocity drifted far
    diff = compare_clip_notes(db_notes, lv)
    assert diff.missing == [] and diff.extra == []
    assert len(diff.mismatch) == 1
    db_repr, live_note = diff.mismatch[0]
    assert db_repr.vel == 100 and live_note.vel == 40


def test_wildness_key_with_one_matching_member_is_faithful():
    """When a key carries a stack, Live's surviving note matching ANY member
    (here the longest) is faithful — even if it differs from the first member."""
    db_notes = [
        db(60, 0.0, dur=1.0, vel=100),
        db(60, 0.0, dur=4.0, vel=60),  # Live happens to keep this one
    ]
    lv = [live(60, 0.0, dur=4.0, vel=60)]
    assert compare_clip_notes(db_notes, lv).faithful


def test_empty_both_is_faithful():
    assert compare_clip_notes([], []).faithful


def test_notelite_inputs_accepted():
    """The comparator accepts NoteLite directly (used by the assert path)."""
    a = [NoteLite(60, 0.0, 1.0, 100)]
    b = [NoteLite(60, 0.0, 1.0, 100)]
    assert compare_clip_notes(a, b).faithful
