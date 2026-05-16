"""Tests for chunk-4b envelope schema: envelopes + automation_breakpoints."""
from __future__ import annotations

import sqlite3

import pytest

from songwright.db import init_db, mutations as M, queries as Q
from songwright.db import events as E


@pytest.fixture
def conn(tmp_path):
    c = init_db(tmp_path / "env.db")
    yield c
    c.close()


@pytest.fixture
def song(conn):
    return M.create_song(conn, name="t", key="Dm")


@pytest.fixture
def track(conn, song):
    return M.create_track(conn, song_id=song, track_index=1, name="Drums")


@pytest.fixture
def ret(conn, song):
    return M.create_return(conn, song_id=song, name="A-Reverb", position=1)


@pytest.fixture
def clip(conn, track):
    return M.create_clip(conn, track_id=track, slot=1, length_beats=8.0, name="loop")


@pytest.fixture
def note(conn, clip):
    return M.insert_notes(
        conn, clip_id=clip,
        notes=[{"pitch": 60, "start_beats": 0.0, "duration_beats": 1.0, "velocity": 100}],
    )[0]


@pytest.fixture
def device(conn, track):
    cid = M.create_device_chain(conn, parent_track_id=track)
    return M.create_device(
        conn, chain_id=cid, position=1, kind="Compressor2", display_name="Comp",
    )


def _events(conn) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT kind, payload_json, actor, song_id FROM events ORDER BY seq"
    ).fetchall()


# ---------- target_kind validation per-kind ----------


def test_create_clip_cc_envelope(conn, song, clip):
    eid = M.create_envelope(
        conn, song_id=song, target_kind="clip_cc",
        target_clip_id=clip, parameter_path="64",
    )
    row = Q.get_envelope(conn, eid)
    assert row["target_kind"] == "clip_cc"
    assert row["target_clip_id"] == clip
    assert row["parameter_path"] == "64"


def test_create_clip_pitch_bend_envelope(conn, song, clip):
    eid = M.create_envelope(
        conn, song_id=song, target_kind="clip_pitch_bend", target_clip_id=clip,
    )
    row = Q.get_envelope(conn, eid)
    assert row["target_clip_id"] == clip
    assert row["parameter_path"] is None


def test_create_note_expression_envelope_microtonal(conn, song, note):
    """The schema path to microtonal: per-note pitch envelope in semitones."""
    eid = M.create_envelope(
        conn, song_id=song, target_kind="note_expression",
        target_note_id=note, parameter_path="pitch",
    )
    M.replace_breakpoints(
        conn, envelope_id=eid,
        breakpoints=[
            {"time_beats": 0.0, "value": 0.0, "curve_kind": "linear"},
            {"time_beats": 0.5, "value": 0.25, "curve_kind": "linear"},
            {"time_beats": 1.0, "value": 0.0, "curve_kind": "linear"},
        ],
    )
    bps = Q.get_breakpoints(conn, eid)
    assert [b["value"] for b in bps] == [0.0, 0.25, 0.0]


def test_create_device_parameter_envelope(conn, song, device):
    eid = M.create_envelope(
        conn, song_id=song, target_kind="device_parameter",
        target_device_id=device, parameter_path="Threshold",
    )
    row = Q.get_envelope(conn, eid)
    assert row["target_device_id"] == device
    assert row["parameter_path"] == "Threshold"


def test_create_mixer_volume_envelope(conn, song, track):
    eid = M.create_envelope(
        conn, song_id=song, target_kind="mixer_volume", target_track_id=track,
    )
    assert Q.get_envelope(conn, eid)["target_track_id"] == track


def test_create_mixer_pan_envelope(conn, song, track):
    eid = M.create_envelope(
        conn, song_id=song, target_kind="mixer_pan", target_track_id=track,
    )
    assert Q.get_envelope(conn, eid)["target_kind"] == "mixer_pan"


def test_create_send_level_envelope(conn, song, track, ret):
    eid = M.create_envelope(
        conn, song_id=song, target_kind="send_level",
        target_track_id=track, target_send_return_id=ret,
    )
    row = Q.get_envelope(conn, eid)
    assert row["target_track_id"] == track
    assert row["target_send_return_id"] == ret


# ---------- target_kind validation: rejects ----------


def test_invalid_target_kind_rejected(conn, song, clip):
    with pytest.raises(ValueError, match="invalid target_kind"):
        M.create_envelope(
            conn, song_id=song, target_kind="bogus", target_clip_id=clip,
        )


def test_missing_required_target_rejected(conn, song):
    with pytest.raises(ValueError, match="requires kwarg target_clip_id"):
        M.create_envelope(conn, song_id=song, target_kind="clip_cc",
                          parameter_path="64")


def test_extra_target_rejected(conn, song, clip, track):
    """mixer_volume only takes target_track_id; passing target_clip_id is a kind mismatch."""
    with pytest.raises(ValueError, match="forbids kwarg target_clip_id"):
        M.create_envelope(
            conn, song_id=song, target_kind="mixer_volume",
            target_track_id=track, target_clip_id=clip,
        )


def test_send_level_requires_both_targets(conn, song, track):
    with pytest.raises(ValueError, match="requires kwarg target_send_return_id"):
        M.create_envelope(
            conn, song_id=song, target_kind="send_level", target_track_id=track,
        )


def test_parameter_path_required_for_clip_cc(conn, song, clip):
    with pytest.raises(ValueError, match="requires parameter_path"):
        M.create_envelope(
            conn, song_id=song, target_kind="clip_cc", target_clip_id=clip,
        )


def test_parameter_path_required_for_device_parameter(conn, song, device):
    with pytest.raises(ValueError, match="requires parameter_path"):
        M.create_envelope(
            conn, song_id=song, target_kind="device_parameter",
            target_device_id=device,
        )


def test_parameter_path_forbidden_for_mixer(conn, song, track):
    with pytest.raises(ValueError, match="does not use parameter_path"):
        M.create_envelope(
            conn, song_id=song, target_kind="mixer_volume",
            target_track_id=track, parameter_path="bogus",
        )


def test_note_expression_axis_validated(conn, song, note):
    with pytest.raises(ValueError, match="not in"):
        M.create_envelope(
            conn, song_id=song, target_kind="note_expression",
            target_note_id=note, parameter_path="bogus_axis",
        )


def test_clip_cc_parameter_path_must_be_int(conn, song, clip):
    with pytest.raises(ValueError, match="must be an integer CC number"):
        M.create_envelope(
            conn, song_id=song, target_kind="clip_cc",
            target_clip_id=clip, parameter_path="not-a-number",
        )


def test_clip_cc_parameter_path_must_be_in_midi_range(conn, song, clip):
    with pytest.raises(ValueError, match="out of MIDI range"):
        M.create_envelope(
            conn, song_id=song, target_kind="clip_cc",
            target_clip_id=clip, parameter_path="128",
        )
    with pytest.raises(ValueError, match="out of MIDI range"):
        M.create_envelope(
            conn, song_id=song, target_kind="clip_cc",
            target_clip_id=clip, parameter_path="-1",
        )


# ---------- schema CHECK is the last-line defense ----------


def test_check_rejects_orphan_envelope(conn):
    """Raw insert with no targets must fail the schema CHECK."""
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        conn.execute(
            "INSERT INTO envelopes (id, song_id, target_kind) VALUES (?, ?, ?)",
            ("x", "fake-song", "clip_cc"),
        )


def test_check_rejects_wrong_target_for_kind(conn, song, track):
    """Raw insert with target_track_id but kind=clip_cc must fail the schema CHECK."""
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        conn.execute(
            """INSERT INTO envelopes
                   (id, song_id, target_kind, target_track_id, parameter_path)
               VALUES (?, ?, 'clip_cc', ?, '64')""",
            ("x", song, track),
        )


# ---------- events + provenance ----------


def test_envelope_create_emits_event_with_song(conn, song, clip):
    M.create_envelope(
        conn, song_id=song, target_kind="clip_cc",
        target_clip_id=clip, parameter_path="64",
    )
    evs = [e for e in _events(conn) if e["kind"] == E.ENVELOPE_CREATED]
    assert len(evs) == 1
    assert evs[0]["song_id"] == song


def test_note_expression_event_carries_clip_id(conn, song, clip, note):
    """Provenance: note_expression envelope events resolve clip_id via the note
    so audit-trail queries by clip find them (the polymorphic FK alone wouldn't).
    """
    M.create_envelope(
        conn, song_id=song, target_kind="note_expression",
        target_note_id=note, parameter_path="pitch",
    )
    ev = conn.execute(
        "SELECT clip_id FROM events WHERE kind = ? ORDER BY seq DESC LIMIT 1",
        (E.ENVELOPE_CREATED,),
    ).fetchone()
    assert ev["clip_id"] == clip


def test_envelope_delete_emits_event(conn, song, clip):
    eid = M.create_envelope(
        conn, song_id=song, target_kind="clip_cc",
        target_clip_id=clip, parameter_path="64",
    )
    M.delete_envelope(conn, envelope_id=eid)
    kinds = [e["kind"] for e in _events(conn)]
    assert E.ENVELOPE_DELETED in kinds


def test_delete_missing_envelope_emits_no_event(conn, song):
    M.delete_envelope(conn, envelope_id="does-not-exist")
    assert not any(e["kind"] == E.ENVELOPE_DELETED for e in _events(conn))


# ---------- breakpoints ----------


def test_add_breakpoint_creates(conn, song, clip):
    eid = M.create_envelope(
        conn, song_id=song, target_kind="clip_cc",
        target_clip_id=clip, parameter_path="64",
    )
    bid = M.add_breakpoint(
        conn, envelope_id=eid, time_beats=0.0, value=0.5,
    )
    bps = Q.get_breakpoints(conn, eid)
    assert len(bps) == 1
    assert bps[0]["id"] == bid
    assert bps[0]["curve_kind"] == "linear"


def test_replace_breakpoints_is_atomic(conn, song, clip):
    eid = M.create_envelope(
        conn, song_id=song, target_kind="clip_cc",
        target_clip_id=clip, parameter_path="64",
    )
    M.add_breakpoint(conn, envelope_id=eid, time_beats=0.0, value=0.0)
    M.add_breakpoint(conn, envelope_id=eid, time_beats=1.0, value=0.5)
    M.replace_breakpoints(
        conn, envelope_id=eid,
        breakpoints=[
            {"time_beats": 0.0, "value": 1.0, "curve_kind": "hold"},
            {"time_beats": 2.0, "value": 0.0, "curve_kind": "fast"},
        ],
    )
    bps = Q.get_breakpoints(conn, eid)
    assert len(bps) == 2
    assert [b["curve_kind"] for b in bps] == ["hold", "fast"]
    # One BREAKPOINTS_REPLACED event regardless of N.
    replaces = [e for e in _events(conn) if e["kind"] == E.BREAKPOINTS_REPLACED]
    assert len(replaces) == 1


def test_remove_breakpoint(conn, song, clip):
    eid = M.create_envelope(
        conn, song_id=song, target_kind="clip_cc",
        target_clip_id=clip, parameter_path="64",
    )
    bid = M.add_breakpoint(conn, envelope_id=eid, time_beats=0.0, value=0.0)
    M.remove_breakpoint(conn, breakpoint_id=bid)
    assert Q.get_breakpoints(conn, eid) == []
    kinds = [e["kind"] for e in _events(conn)]
    assert E.BREAKPOINT_REMOVED in kinds


def test_invalid_curve_kind_rejected(conn, song, clip):
    eid = M.create_envelope(
        conn, song_id=song, target_kind="clip_cc",
        target_clip_id=clip, parameter_path="64",
    )
    with pytest.raises(ValueError, match="invalid curve_kind"):
        M.add_breakpoint(
            conn, envelope_id=eid, time_beats=0.0, value=0.0, curve_kind="cubic",
        )


def test_negative_time_beats_rejected(conn, song, clip):
    eid = M.create_envelope(
        conn, song_id=song, target_kind="clip_cc",
        target_clip_id=clip, parameter_path="64",
    )
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        M.add_breakpoint(conn, envelope_id=eid, time_beats=-0.5, value=0.0)


# ---------- cascade ----------


def test_delete_clip_cascades_envelopes(conn, song, clip):
    eid = M.create_envelope(
        conn, song_id=song, target_kind="clip_cc",
        target_clip_id=clip, parameter_path="64",
    )
    M.add_breakpoint(conn, envelope_id=eid, time_beats=0.0, value=0.0)
    M.delete_clip(conn, clip_id=clip)
    assert Q.get_envelope(conn, eid) is None
    assert conn.execute(
        "SELECT COUNT(*) FROM automation_breakpoints WHERE envelope_id=?", (eid,)
    ).fetchone()[0] == 0


def test_delete_note_cascades_envelope(conn, song, note):
    eid = M.create_envelope(
        conn, song_id=song, target_kind="note_expression",
        target_note_id=note, parameter_path="pressure",
    )
    M.delete_notes(conn, note_ids=[note])
    assert Q.get_envelope(conn, eid) is None


def test_delete_device_cascades_envelope(conn, song, device):
    eid = M.create_envelope(
        conn, song_id=song, target_kind="device_parameter",
        target_device_id=device, parameter_path="Threshold",
    )
    M.delete_device(conn, device_id=device)
    assert Q.get_envelope(conn, eid) is None


def test_delete_track_cascades_mixer_envelope(conn, song, track):
    eid = M.create_envelope(
        conn, song_id=song, target_kind="mixer_volume", target_track_id=track,
    )
    conn.execute("DELETE FROM tracks WHERE id=?", (track,))
    assert Q.get_envelope(conn, eid) is None


def test_delete_return_cascades_send_envelope(conn, song, track, ret):
    eid = M.create_envelope(
        conn, song_id=song, target_kind="send_level",
        target_track_id=track, target_send_return_id=ret,
    )
    M.delete_return(conn, return_id=ret)
    assert Q.get_envelope(conn, eid) is None


# ---------- queries ----------


def test_queries_filter_by_target(conn, song, clip, note, device, track, ret):
    cc = M.create_envelope(conn, song_id=song, target_kind="clip_cc",
                           target_clip_id=clip, parameter_path="1")
    pb = M.create_envelope(conn, song_id=song, target_kind="clip_pitch_bend",
                           target_clip_id=clip)
    ne = M.create_envelope(conn, song_id=song, target_kind="note_expression",
                           target_note_id=note, parameter_path="pitch")
    dp = M.create_envelope(conn, song_id=song, target_kind="device_parameter",
                           target_device_id=device, parameter_path="Threshold")
    mv = M.create_envelope(conn, song_id=song, target_kind="mixer_volume",
                           target_track_id=track)
    se = M.create_envelope(conn, song_id=song, target_kind="send_level",
                           target_track_id=track, target_send_return_id=ret)
    all_for_song = {e["id"] for e in Q.get_envelopes_for_song(conn, song)}
    assert all_for_song == {cc, pb, ne, dp, mv, se}
    clip_ids = {e["id"] for e in Q.get_envelopes_for_clip(conn, clip)}
    assert clip_ids == {cc, pb}
    assert {e["id"] for e in Q.get_envelopes_for_note(conn, note)} == {ne}
    assert {e["id"] for e in Q.get_envelopes_for_device(conn, device)} == {dp}
    # mixer + send envelopes (track-anchored); device_parameter is NOT included.
    assert {e["id"] for e in Q.get_envelopes_for_track(conn, track)} == {mv, se}


def test_get_breakpoints_orders_by_time(conn, song, clip):
    eid = M.create_envelope(conn, song_id=song, target_kind="clip_cc",
                            target_clip_id=clip, parameter_path="64")
    M.add_breakpoint(conn, envelope_id=eid, time_beats=2.0, value=0.5)
    M.add_breakpoint(conn, envelope_id=eid, time_beats=0.0, value=0.0)
    M.add_breakpoint(conn, envelope_id=eid, time_beats=1.0, value=1.0)
    bps = Q.get_breakpoints(conn, eid)
    assert [b["time_beats"] for b in bps] == [0.0, 1.0, 2.0]
