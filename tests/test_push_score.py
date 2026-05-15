"""Tests for chunk-2 score-half push planners: tempo, time-signature, cue
points, and sections. The planners are pure: they read the DB and produce
ToolCall objects without invoking MCP."""
from __future__ import annotations

import math

import pytest

from songwright.db import init_db, mutations as M
from songwright.sync import push


@pytest.fixture
def conn(tmp_path):
    c = init_db(tmp_path / "p.db")
    yield c
    c.close()


@pytest.fixture
def song(conn):
    return M.create_song(conn, name="t", key="Dm")


# ---------- _bar_to_beats (the bars->beats translator) ----------


def test_bar_to_beats_empty_map_defaults_to_4_4():
    assert push._bar_to_beats(0.0, []) == 0.0
    assert push._bar_to_beats(4.0, []) == 16.0
    assert push._bar_to_beats(1.5, []) == 6.0


def test_bar_to_beats_single_4_4_point_at_zero(conn, song):
    M.add_time_signature_point(
        conn, song_id=song, start_bar=0.0, numerator=4, denominator=4
    )
    points = list(conn.execute(
        "SELECT * FROM time_signature_map WHERE song_id=? ORDER BY start_bar",
        (song,),
    ).fetchall())
    assert push._bar_to_beats(0.0, points) == 0.0
    assert push._bar_to_beats(8.0, points) == 32.0


def test_bar_to_beats_6_8_compound_meter(conn, song):
    M.add_time_signature_point(
        conn, song_id=song, start_bar=0.0, numerator=6, denominator=8
    )
    points = list(conn.execute(
        "SELECT * FROM time_signature_map WHERE song_id=? ORDER BY start_bar",
        (song,),
    ).fetchall())
    # 6/8 -> 3 beats per bar
    assert math.isclose(push._bar_to_beats(4.0, points), 12.0)


def test_bar_to_beats_handles_meter_change(conn, song):
    M.add_time_signature_point(
        conn, song_id=song, start_bar=0.0, numerator=4, denominator=4
    )
    M.add_time_signature_point(
        conn, song_id=song, start_bar=8.0, numerator=3, denominator=4
    )
    points = list(conn.execute(
        "SELECT * FROM time_signature_map WHERE song_id=? ORDER BY start_bar",
        (song,),
    ).fetchall())
    # Bars 0..8 are 4/4 (32 beats), bars 8..12 are 3/4 (12 beats) -> 44 total
    assert math.isclose(push._bar_to_beats(12.0, points), 44.0)


# ---------- plan_push_tempo_map ----------


def test_plan_push_tempo_map_empty_warns(conn, song):
    plan = push.plan_push_tempo_map(conn, song_id=song)
    assert plan.calls == []
    assert any("no tempo_map" in n for n in plan.notes)


def test_plan_push_tempo_map_single_point(conn, song):
    pid = M.add_tempo_point(conn, song_id=song, start_bar=0.0, tempo_bpm=132.0)
    plan = push.plan_push_tempo_map(conn, song_id=song)
    assert len(plan.calls) == 1
    call = plan.calls[0]
    assert call.tool == "write_tempo_point"
    assert call.args == {"at_beat_position": 0.0, "bpm": 132.0, "ramp": "hold"}
    assert call.key == f"tempo_point:{pid}"
    # 4/4 default warning expected since no time_signature_map present
    assert any("4/4" in n for n in plan.notes)


def test_plan_push_tempo_map_multi_point_emits_warn_and_calls(conn, song):
    M.add_time_signature_point(
        conn, song_id=song, start_bar=0.0, numerator=4, denominator=4
    )
    M.add_tempo_point(conn, song_id=song, start_bar=0.0, tempo_bpm=132.0)
    M.add_tempo_point(conn, song_id=song, start_bar=16.0, tempo_bpm=80.0, ramp="linear")
    plan = push.plan_push_tempo_map(conn, song_id=song)
    assert len(plan.calls) == 2
    # Second point at bar 16 -> beat 64 in 4/4
    assert plan.calls[1].args["at_beat_position"] == 64.0
    assert plan.calls[1].args["ramp"] == "linear"
    assert any("multi-point or ramped" in n for n in plan.notes)


# ---------- plan_push_time_signature_map ----------


def test_plan_push_time_signature_map_empty_warns(conn, song):
    plan = push.plan_push_time_signature_map(conn, song_id=song)
    assert plan.calls == []
    assert any("no time_signature_map" in n for n in plan.notes)


def test_plan_push_time_signature_map_emits_canonical_call_and_gap_warn(conn, song):
    pid = M.add_time_signature_point(
        conn, song_id=song, start_bar=0.0, numerator=4, denominator=4
    )
    plan = push.plan_push_time_signature_map(conn, song_id=song)
    assert len(plan.calls) == 1
    call = plan.calls[0]
    assert call.tool == "write_time_signature_point"
    assert call.args == {"at_beat_position": 0.0, "numerator": 4, "denominator": 4}
    assert call.key == f"time_signature_point:{pid}"
    assert any("MCP gap" in n for n in plan.notes)


# ---------- plan_push_cue_points ----------


def test_plan_push_cue_points_empty_warns(conn, song):
    plan = push.plan_push_cue_points(conn, song_id=song)
    assert plan.calls == []
    assert any("no cue_points" in n for n in plan.notes)


def test_plan_push_cue_points_uses_canonical_create_cue_point(conn, song):
    M.add_time_signature_point(
        conn, song_id=song, start_bar=0.0, numerator=4, denominator=4
    )
    cid = M.add_cue_point(conn, song_id=song, position_bar=8.0, name="chorus")
    plan = push.plan_push_cue_points(conn, song_id=song)
    assert len(plan.calls) == 1
    call = plan.calls[0]
    assert call.tool == "create_cue_point"
    assert call.args == {"time": 32.0, "name": "chorus"}  # 8 bars * 4 beats
    assert call.key == f"cue_point:{cid}"


def test_plan_push_cue_points_warns_when_no_ts_map(conn, song):
    M.add_cue_point(conn, song_id=song, position_bar=4.0, name="x")
    plan = push.plan_push_cue_points(conn, song_id=song)
    assert plan.calls[0].args["time"] == 16.0  # default 4/4
    assert any("4/4" in n for n in plan.notes)


# ---------- plan_push_sections ----------


def test_plan_push_sections_emits_no_calls(conn, song):
    M.create_section(conn, song_id=song, name="verse", start_bar=0.0, end_bar=16.0)
    plan = push.plan_push_sections(conn, song_id=song)
    assert plan.calls == []
    assert any("DB-only" in n for n in plan.notes)


def test_plan_push_sections_empty_is_silent(conn, song):
    plan = push.plan_push_sections(conn, song_id=song)
    assert plan.calls == []
    assert plan.notes == []
