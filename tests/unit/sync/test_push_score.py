"""Tests for chunk-2 score-half push planners: tempo, time-signature, cue
points, and sections. The planners are pure: they read the DB and produce
ToolCall objects without invoking MCP."""
from __future__ import annotations

import math

import pytest

from hallucinote.db import init_db, mutations as M
from hallucinote.sync import push


@pytest.fixture
def conn(tmp_path):
    c = init_db(tmp_path / "p.db")
    yield c
    c.close()


@pytest.fixture
def song(conn):
    return M.create_song(conn, name="t", key="Dm")


# ---------- _split_bar / _meter_at_bar (bar-position translation) ----------


def _ts_rows(conn, song_id) -> list:
    return list(conn.execute(
        "SELECT * FROM time_signature_map WHERE song_id=? ORDER BY start_bar",
        (song_id,),
    ).fetchall())


def test_split_bar_empty_map_defaults_to_4_4():
    assert push._split_bar(1.0, []) == (1, 0.0)
    assert push._split_bar(4.5, []) == (4, 2.0)  # half bar in 4/4 -> 2 beats
    assert push._split_bar(8.0, []) == (8, 0.0)


def test_split_bar_rejects_below_one():
    with pytest.raises(ValueError, match="1-based bar convention"):
        push._split_bar(0.0, [])
    with pytest.raises(ValueError, match="1-based bar convention"):
        push._split_bar(0.999, [])


def test_split_bar_single_4_4_point(conn, song):
    M.add_time_signature_point(
        conn, song_id=song, start_bar=1.0, numerator=4, denominator=4
    )
    points = _ts_rows(conn, song)
    assert push._split_bar(1.0, points) == (1, 0.0)
    assert push._split_bar(8.0, points) == (8, 0.0)
    assert math.isclose(push._split_bar(4.25, points)[1], 1.0)


def test_split_bar_6_8_compound_meter(conn, song):
    M.add_time_signature_point(
        conn, song_id=song, start_bar=1.0, numerator=6, denominator=8
    )
    points = _ts_rows(conn, song)
    # 6/8 -> 3 beats per bar. A half-bar is 1.5 beats.
    bar, beat = push._split_bar(4.5, points)
    assert bar == 4 and math.isclose(beat, 1.5)


def test_meter_at_bar_picks_active_meter(conn, song):
    M.add_time_signature_point(
        conn, song_id=song, start_bar=1.0, numerator=4, denominator=4
    )
    M.add_time_signature_point(
        conn, song_id=song, start_bar=9.0, numerator=3, denominator=4
    )
    points = _ts_rows(conn, song)
    assert push._meter_at_bar(1.0, points) == (4, 4)
    assert push._meter_at_bar(8.0, points) == (4, 4)
    assert push._meter_at_bar(9.0, points) == (3, 4)
    assert push._meter_at_bar(12.0, points) == (3, 4)


def test_meter_at_bar_before_first_point_uses_first(conn, song):
    M.add_time_signature_point(
        conn, song_id=song, start_bar=5.0, numerator=6, denominator=8
    )
    points = _ts_rows(conn, song)
    assert push._meter_at_bar(1.0, points) == (6, 8)
    assert push._meter_at_bar(4.99, points) == (6, 8)


# ---------- plan_push_tempo_map ----------


def test_plan_push_tempo_map_empty_warns(conn, song):
    plan = push.plan_push_tempo_map(conn, song_id=song)
    assert plan.calls == []
    assert any("no tempo_map" in n for n in plan.notes)


def test_plan_push_tempo_map_single_point(conn, song):
    pid = M.add_tempo_point(conn, song_id=song, start_bar=1.0, tempo_bpm=132.0)
    plan = push.plan_push_tempo_map(conn, song_id=song)
    assert len(plan.calls) == 1
    call = plan.calls[0]
    assert call.tool == "write_tempo_point"
    assert call.args == {"bar": 1, "beat": 0.0, "bpm": 132.0, "ramp": "hold"}
    assert call.key == f"tempo_point:{pid}"
    # 4/4 default warning expected since no time_signature_map present
    assert any("4/4" in n for n in plan.notes)


def test_plan_push_tempo_map_multi_point_emits_warn_and_calls(conn, song):
    M.add_time_signature_point(
        conn, song_id=song, start_bar=1.0, numerator=4, denominator=4
    )
    M.add_tempo_point(conn, song_id=song, start_bar=1.0, tempo_bpm=132.0)
    M.add_tempo_point(conn, song_id=song, start_bar=16.5, tempo_bpm=80.0, ramp="linear")
    plan = push.plan_push_tempo_map(conn, song_id=song)
    assert len(plan.calls) == 2
    # Second point at bar 16.5 -> (bar=16, beat=2.0) in 4/4
    assert plan.calls[1].args["bar"] == 16
    assert math.isclose(plan.calls[1].args["beat"], 2.0)
    assert plan.calls[1].args["ramp"] == "linear"
    assert any("multi-point or ramped" in n for n in plan.notes)


# ---------- plan_push_time_signature_map ----------


def test_plan_push_time_signature_map_empty_warns(conn, song):
    plan = push.plan_push_time_signature_map(conn, song_id=song)
    assert plan.calls == []
    assert any("no time_signature_map" in n for n in plan.notes)


def test_plan_push_time_signature_map_emits_canonical_call_and_gap_warn(conn, song):
    pid = M.add_time_signature_point(
        conn, song_id=song, start_bar=1.0, numerator=4, denominator=4
    )
    plan = push.plan_push_time_signature_map(conn, song_id=song)
    assert len(plan.calls) == 1
    call = plan.calls[0]
    assert call.tool == "write_time_signature_point"
    assert call.args == {"bar": 1, "beat": 0.0, "numerator": 4, "denominator": 4}
    assert call.key == f"time_signature_point:{pid}"
    assert any("MCP gap" in n for n in plan.notes)


# ---------- _position_bar_to_beats (W3-B inverse of _split_bar) ----------


def test_position_bar_to_beats_empty_map_4_4_default():
    assert push._position_bar_to_beats(1.0, []) == 0.0
    assert push._position_bar_to_beats(17.0, []) == 64.0
    assert push._position_bar_to_beats(17.5, []) == 66.0


def test_position_bar_to_beats_rejects_below_one():
    with pytest.raises(ValueError, match="1-based bar convention"):
        push._position_bar_to_beats(0.0, [])
    with pytest.raises(ValueError, match="1-based bar convention"):
        push._position_bar_to_beats(0.999, [])


def test_position_bar_to_beats_single_4_4_at_bar_1(conn, song):
    M.add_time_signature_point(
        conn, song_id=song, start_bar=1.0, numerator=4, denominator=4
    )
    points = _ts_rows(conn, song)
    # Falling-walking cues: 1, 17, 32, 40, 48, 56, 60 in 4/4.
    assert push._position_bar_to_beats(1.0, points) == 0.0
    assert push._position_bar_to_beats(17.0, points) == 64.0
    assert push._position_bar_to_beats(32.0, points) == 124.0
    assert push._position_bar_to_beats(60.0, points) == 236.0


def test_position_bar_to_beats_6_8_compound(conn, song):
    """6/8 = 3 quarter-note-beats per bar (Live's "1 beat = 1 quarter")."""
    M.add_time_signature_point(
        conn, song_id=song, start_bar=1.0, numerator=6, denominator=8
    )
    points = _ts_rows(conn, song)
    assert push._position_bar_to_beats(1.0, points) == 0.0
    assert push._position_bar_to_beats(2.0, points) == 3.0
    assert push._position_bar_to_beats(5.0, points) == 12.0


def test_position_bar_to_beats_across_meter_change(conn, song):
    """4/4 from bar 1; switches to 6/8 at bar 5. A cue at bar 7 = 4 bars × 4
    beats (4/4 segment) + 2 bars × 3 beats (6/8 segment) = 22 beats."""
    M.add_time_signature_point(
        conn, song_id=song, start_bar=1.0, numerator=4, denominator=4
    )
    M.add_time_signature_point(
        conn, song_id=song, start_bar=5.0, numerator=6, denominator=8
    )
    points = _ts_rows(conn, song)
    assert push._position_bar_to_beats(5.0, points) == 16.0  # boundary
    assert push._position_bar_to_beats(7.0, points) == 22.0  # 16 + 2×3
    assert push._position_bar_to_beats(6.5, points) == 20.5  # 16 + 1.5×3


def test_position_bar_to_beats_before_first_ts_point_uses_first_meter(conn, song):
    """Bars before ts_points[0].start_bar use ts_points[0]'s meter (matches
    _meter_at_bar fallback). Mirrors the J-6 invariant: songs SHOULD have a
    bar-1 point, but if they don't we don't blow up."""
    M.add_time_signature_point(
        conn, song_id=song, start_bar=5.0, numerator=6, denominator=8
    )
    points = _ts_rows(conn, song)
    # Bar 3 in 6/8 (from the first point's meter, even though it starts at bar 5):
    # 2 bars × 3 beats = 6 beats.
    assert push._position_bar_to_beats(3.0, points) == 6.0


# ---------- plan_push_cue_points ----------


def test_plan_push_cue_points_empty_warns(conn, song):
    plan = push.plan_push_cue_points(conn, song_id=song)
    assert plan.calls == []
    assert any("no cue_points" in n for n in plan.notes)


def test_plan_push_cue_points_emits_single_batched_call(conn, song):
    """W3-B: planner emits one ableton_arrangement(cue_create_batch) call
    carrying all cues — one round-trip instead of N. Locks the canonical
    shape after the W3-B drift fix."""
    M.add_time_signature_point(
        conn, song_id=song, start_bar=1.0, numerator=4, denominator=4
    )
    M.add_cue_point(conn, song_id=song, position_bar=1.0, name="intro")
    M.add_cue_point(conn, song_id=song, position_bar=17.0, name="verse")
    M.add_cue_point(conn, song_id=song, position_bar=32.0, name="chorus")

    plan = push.plan_push_cue_points(conn, song_id=song)

    assert len(plan.calls) == 1, "cue push must be a single batched call"
    call = plan.calls[0]
    assert call.tool == "ableton_arrangement"
    assert call.args["action"] == "cue_create_batch"
    assert call.args["cues"] == [
        {"position_beats": 0.0, "name": "intro"},
        {"position_beats": 64.0, "name": "verse"},
        {"position_beats": 124.0, "name": "chorus"},
    ]
    assert call.key == f"cue_batch:{song}"


def test_plan_push_cue_points_fractional_position_converts_correctly(conn, song):
    """A cue at bar 8.5 in 4/4 = (8-1)*4 + 0.5*4 = 30 beats."""
    M.add_time_signature_point(
        conn, song_id=song, start_bar=1.0, numerator=4, denominator=4
    )
    M.add_cue_point(conn, song_id=song, position_bar=8.5, name="halfway")
    plan = push.plan_push_cue_points(conn, song_id=song)
    cues = plan.calls[0].args["cues"]
    assert len(cues) == 1
    assert math.isclose(cues[0]["position_beats"], 30.0)


def test_plan_push_cue_points_warns_when_no_ts_map(conn, song):
    """Bar→beats falls back to 4/4 with a planner warn."""
    M.add_cue_point(conn, song_id=song, position_bar=4.0, name="x")
    plan = push.plan_push_cue_points(conn, song_id=song)
    cues = plan.calls[0].args["cues"]
    assert cues == [{"position_beats": 12.0, "name": "x"}]  # (4-1)*4
    assert any("4/4" in n for n in plan.notes)


def test_plan_push_cue_points_nameless_emits_empty_string(conn, song):
    """The MCP cue_create_batch takes name as optional string. None → ''."""
    M.add_cue_point(conn, song_id=song, position_bar=1.0, name=None)
    plan = push.plan_push_cue_points(conn, song_id=song)
    cues = plan.calls[0].args["cues"]
    assert cues == [{"position_beats": 0.0, "name": ""}]


def test_plan_push_cue_points_respects_meter_change(conn, song):
    """Cue at bar 7 across a 4/4→6/8 change at bar 5 = 22 beats."""
    M.add_time_signature_point(
        conn, song_id=song, start_bar=1.0, numerator=4, denominator=4
    )
    M.add_time_signature_point(
        conn, song_id=song, start_bar=5.0, numerator=6, denominator=8
    )
    M.add_cue_point(conn, song_id=song, position_bar=7.0, name="post-change")
    plan = push.plan_push_cue_points(conn, song_id=song)
    cues = plan.calls[0].args["cues"]
    assert cues == [{"position_beats": 22.0, "name": "post-change"}]


# ---------- plan_push_sections ----------


def test_plan_push_sections_emits_no_calls(conn, song):
    M.create_section(conn, song_id=song, name="verse", start_bar=1.0, end_bar=17.0)
    plan = push.plan_push_sections(conn, song_id=song)
    assert plan.calls == []
    assert any("DB-only" in n for n in plan.notes)


def test_plan_push_sections_empty_is_silent(conn, song):
    plan = push.plan_push_sections(conn, song_id=song)
    assert plan.calls == []
    assert plan.notes == []
