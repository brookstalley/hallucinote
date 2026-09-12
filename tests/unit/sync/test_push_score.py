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


def _ts_point(
    conn, song_id, start_bar: float, numerator: int, denominator: int,
) -> str:
    """Add a meter point through the mutator. Non-bar-1 rows are ordinary
    authored state — the DB records the song's true meter and the planner
    reports what Live cannot show — so these tests need no raw INSERT."""
    return M.add_time_signature_point(
        conn, song_id=song_id, start_bar=start_bar,
        numerator=numerator, denominator=denominator,
    )


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
    _ts_point(conn, song, 9.0, 3, 4)
    points = _ts_rows(conn, song)
    assert push._meter_at_bar(1.0, points) == (4, 4)
    assert push._meter_at_bar(8.0, points) == (4, 4)
    assert push._meter_at_bar(9.0, points) == (3, 4)
    assert push._meter_at_bar(12.0, points) == (3, 4)


def test_meter_at_bar_before_first_point_uses_first(conn, song):
    _ts_point(conn, song, 5.0, 6, 8)
    points = _ts_rows(conn, song)
    assert push._meter_at_bar(1.0, points) == (6, 8)
    assert push._meter_at_bar(4.99, points) == (6, 8)


# ---------- plan_push_tempo_map ----------


def test_plan_push_tempo_map_empty_warns(conn, song):
    plan = push.plan_push_tempo_map(conn, song_id=song)
    assert plan.calls == []
    assert any("no tempo_map" in n for n in plan.notes)


def test_plan_push_tempo_map_single_bar1_point_emits_set_tempo(conn, song):
    pid = M.add_tempo_point(conn, song_id=song, start_bar=1.0, tempo_bpm=132.0)
    plan = push.plan_push_tempo_map(conn, song_id=song)
    assert len(plan.calls) == 1
    call = plan.calls[0]
    assert call.tool == "ableton_session"
    assert call.args == {"action": "set_tempo", "bpm": 132.0}
    assert call.key == f"tempo_point:{pid}"
    # Bar-1-only: no MCP-gap warn.
    assert plan.notes == []


def test_plan_push_tempo_map_multi_point_emits_bar1_call_and_gap_warn(conn, song):
    """Per-bar tempo automation is an MCP gap on Live 12.4. The bar-1
    row goes through `set_tempo`; non-bar-1 rows skip with a warn.
    """
    M.add_time_signature_point(
        conn, song_id=song, start_bar=1.0, numerator=4, denominator=4
    )
    pid_1 = M.add_tempo_point(
        conn, song_id=song, start_bar=1.0, tempo_bpm=132.0
    )
    M.add_tempo_point(
        conn, song_id=song, start_bar=16.5, tempo_bpm=80.0, ramp="linear"
    )
    plan = push.plan_push_tempo_map(conn, song_id=song)
    assert len(plan.calls) == 1
    call = plan.calls[0]
    assert call.tool == "ableton_session"
    assert call.args == {"action": "set_tempo", "bpm": 132.0}
    assert call.key == f"tempo_point:{pid_1}"
    assert any(
        "song_tempo" in n and "1 non-bar-1" in n for n in plan.alerts
    ), "the skipped rows must reach the operator channel, not diagnostic notes"


def test_plan_push_tempo_map_no_bar1_row_warns_and_emits_no_calls(conn, song):
    """A tempo_map without a bar-1 row leaves Live's global tempo
    unaddressable; the planner warns about both the missing bar-1
    anchor AND the multi-bar MCP gap.
    """
    M.add_tempo_point(
        conn, song_id=song, start_bar=5.0, tempo_bpm=132.0
    )
    plan = push.plan_push_tempo_map(conn, song_id=song)
    assert plan.calls == []
    assert any(
        "no row at start_bar=1.0" in n for n in plan.notes
    )
    assert any("song_tempo" in n for n in plan.alerts)


# ---------- plan_push_time_signature_map ----------


def test_plan_push_time_signature_map_empty_warns(conn, song):
    plan = push.plan_push_time_signature_map(conn, song_id=song)
    assert plan.calls == []
    assert any("no time_signature_map" in n for n in plan.notes)


def test_plan_push_time_signature_map_bar1_emits_set_signature(conn, song):
    pid = M.add_time_signature_point(
        conn, song_id=song, start_bar=1.0, numerator=4, denominator=4
    )
    plan = push.plan_push_time_signature_map(conn, song_id=song)
    assert len(plan.calls) == 1
    call = plan.calls[0]
    assert call.tool == "ableton_session"
    assert call.args == {
        "action": "set_signature", "numerator": 4, "denominator": 4,
    }
    assert call.key == f"time_signature_point:{pid}"
    # Bar-1-only: no MCP-gap warn.
    assert plan.notes == []


def test_plan_push_time_signature_map_multi_point_emits_bar1_and_gap_warn(
    conn, song,
):
    """Per-bar meter automation is an MCP gap. Bar-1 row goes through
    `set_signature`; non-bar-1 rows skip with a warn.
    """
    pid_1 = M.add_time_signature_point(
        conn, song_id=song, start_bar=1.0, numerator=4, denominator=4
    )
    _ts_point(conn, song, 9.0, 6, 8)
    plan = push.plan_push_time_signature_map(conn, song_id=song)
    assert len(plan.calls) == 1
    call = plan.calls[0]
    assert call.tool == "ableton_session"
    assert call.args == {
        "action": "set_signature", "numerator": 4, "denominator": 4,
    }
    assert call.key == f"time_signature_point:{pid_1}"
    assert any(
        "song_signature" in n and "1 non-bar-1" in n for n in plan.alerts
    ), "the skipped rows must reach the operator channel, not diagnostic notes"


def test_plan_push_time_signature_map_alert_names_the_projection(conn, song):
    """The planner is the ONE place the Live reach limit is stated, so it has
    to say what is lost and what is not: Live's RULER shows the bar-1 meter for
    the whole song, while playback is unaffected because every position is
    authored in absolute beats.

    On `alerts`, not `notes` — the executor drains alerts into the push
    report and discards notes as diagnostic noise, so a statement the operator
    must read cannot live in `notes`.
    """
    M.add_time_signature_point(
        conn, song_id=song, start_bar=1.0, numerator=4, denominator=4
    )
    _ts_point(conn, song, 9.0, 7, 4)
    plan = push.plan_push_time_signature_map(conn, song_id=song)
    gap = next(n for n in plan.alerts if "song_signature" in n)
    assert "PLAYBACK IS UNAFFECTED" in gap
    assert "number bars as 4/4 throughout" in gap


def test_the_alert_tells_the_operator_which_changes_to_add_by_hand(conn, song):
    """The reach limit's advice used to be "carry the felt meter in note
    placement and accent" — written when the DB refused to record a within-song
    map at all. The DB has held the song's true meter since #221 and the engine
    places against it since #566, so the operator's actual move is the hand-add,
    and nothing told them what to add or where."""
    M.add_time_signature_point(
        conn, song_id=song, start_bar=1.0, numerator=4, denominator=4
    )
    _ts_point(conn, song, 87.0, 4, 4)
    _ts_point(conn, song, 86.0, 7, 4)
    plan = push.plan_push_time_signature_map(conn, song_id=song)
    gap = next(n for n in plan.alerts if "song_signature" in n)

    assert "bar 86 -> 7/4, bar 87 -> 4/4" in gap, "named, in bar order"
    assert "optional" in gap
    assert "accent" not in gap, "the advice to abandon the literal meter is gone"


def test_the_hand_add_list_is_capped(conn, song):
    """A song changing meter every other bar must not turn one alert into a
    wall; the count is stated in the clause above the list."""
    M.add_time_signature_point(
        conn, song_id=song, start_bar=1.0, numerator=4, denominator=4
    )
    for bar in range(2, 15):
        _ts_point(conn, song, float(bar), 7 if bar % 2 else 4, 4)
    gap = next(
        n for n in push.plan_push_time_signature_map(conn, song_id=song).alerts
        if "song_signature" in n
    )
    assert "13 non-bar-1" in gap
    assert "and 5 more" in gap


def test_plan_push_time_signature_map_no_bar1_row_warns_no_calls(conn, song):
    """A time_signature_map without a bar-1 row leaves Live's global
    meter unaddressable; warn on both the missing anchor and the
    multi-bar MCP gap.
    """
    _ts_point(conn, song, 5.0, 6, 8)
    plan = push.plan_push_time_signature_map(conn, song_id=song)
    assert plan.calls == []
    assert any("no row at start_bar=1.0" in n for n in plan.notes)
    assert any("song_signature" in n for n in plan.alerts)


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
    _ts_point(conn, song, 5.0, 6, 8)
    points = _ts_rows(conn, song)
    assert push._position_bar_to_beats(5.0, points) == 16.0  # boundary
    assert push._position_bar_to_beats(7.0, points) == 22.0  # 16 + 2×3
    assert push._position_bar_to_beats(6.5, points) == 20.5  # 16 + 1.5×3


def test_position_bar_to_beats_before_first_ts_point_uses_first_meter(conn, song):
    """Bars before ts_points[0].start_bar use ts_points[0]'s meter (matches
    _meter_at_bar fallback). Mirrors the J-6 invariant: songs SHOULD have a
    bar-1 point, but if they don't we don't blow up."""
    _ts_point(conn, song, 5.0, 6, 8)
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


def test_plan_push_cue_points_alerts_on_cues_past_a_meter_change(conn, song):
    """A cue's position resolves through the meter map exactly as an
    arrangement placement's does, so it diverges from uniform bar math the same
    way and needs the same alert. Cues before the change must stay quiet — and
    so must cues whose row does not record uniform authorship (#496), which is
    why these two declare the ruler that wrote them."""
    M.add_time_signature_point(
        conn, song_id=song, start_bar=1.0, numerator=4, denominator=4
    )
    _ts_point(conn, song, 9.0, 7, 4)
    M.add_cue_point(
        conn, song_id=song, position_bar=5.0, name="early", bar_ruler="uniform",
    )
    plan = push.plan_push_cue_points(conn, song_id=song)
    assert not any("UNIFORM bar math" in a for a in plan.alerts)

    M.add_cue_point(
        conn, song_id=song, position_bar=13.0, name="late", bar_ruler="uniform",
    )
    plan = push.plan_push_cue_points(conn, song_id=song)
    hit = next(a for a in plan.alerts if "UNIFORM bar math" in a)
    assert "1 of 2 cue points" in hit
    assert "beat 60" in hit and "48" in hit
    assert "Affected bars: 13" in hit


def test_plan_push_cue_points_alert_enumerates_every_diverging_bar(conn, song):
    """Same contract as the arrangement alert: name every diverging cue, and
    when the list is cut past the cap, say that it was cut."""
    M.add_time_signature_point(
        conn, song_id=song, start_bar=1.0, numerator=4, denominator=4
    )
    _ts_point(conn, song, 9.0, 7, 4)
    for bar in range(10, 15):
        M.add_cue_point(
            conn, song_id=song, position_bar=float(bar), name=f"c{bar}",
            bar_ruler="uniform",
        )
    plan = push.plan_push_cue_points(conn, song_id=song)
    hit = next(a for a in plan.alerts if "UNIFORM bar math" in a)
    assert "Affected bars: 10, 11, 12, 13, 14" in hit
    assert "more" not in hit

    for bar in range(15, 19):
        M.add_cue_point(
            conn, song_id=song, position_bar=float(bar), name=f"c{bar}",
            bar_ruler="uniform",
        )
    plan = push.plan_push_cue_points(conn, song_id=song)
    hit = next(a for a in plan.alerts if "UNIFORM bar math" in a)
    assert "Affected bars: 10, 11, 12, 13, 14, 15, 16, 17, and 1 more" in hit


def test_cue_points_authored_against_the_map_raise_no_divergence_alert(conn, song):
    """#496 acceptance 1, cue half. A 7/4 song's cues sit after the meter
    change by design; authored against the map, they land exactly where the
    song asked, and an alert about them is noise on every push."""
    M.add_time_signature_point(
        conn, song_id=song, start_bar=1.0, numerator=4, denominator=4
    )
    _ts_point(conn, song, 9.0, 7, 4)
    for bar in (10.0, 13.0):
        M.add_cue_point(
            conn, song_id=song, position_bar=bar, name=f"c{bar:g}",
            bar_ruler="map",
        )
    plan = push.plan_push_cue_points(conn, song_id=song)
    assert not any("UNIFORM bar math" in a for a in plan.alerts), plan.alerts
    assert not any("PROVISIONAL" in a for a in plan.alerts), plan.alerts


def test_a_cue_with_no_recorded_ruler_gets_the_provisional_alert(conn, song):
    """#496 R6, cue half — its own alert, naming the fix, never merged into
    the uniform-math message."""
    M.add_time_signature_point(
        conn, song_id=song, start_bar=1.0, numerator=4, denominator=4
    )
    _ts_point(conn, song, 9.0, 7, 4)
    cid = M.add_cue_point(
        conn, song_id=song, position_bar=13.0, name="late", bar_ruler="map",
    )
    conn.execute("UPDATE cue_points SET bar_ruler = NULL WHERE id = ?", (cid,))
    plan = push.plan_push_cue_points(conn, song_id=song)
    provisional = next(a for a in plan.alerts if "PROVISIONAL" in a)
    assert "Affected bars: 13" in provisional
    assert "build.py" in provisional
    assert not any("UNIFORM bar math" in a for a in plan.alerts), plan.alerts


def test_plan_push_cue_points_sets_if_exists_skip(conn, song):
    """R-1.1: re-push idempotency. The planner explicitly sets
    ``if_exists='skip'`` so a second push of the same DB against a Live
    set that already has the same-named cues is a no-op the second time
    (instead of failing on every cue with 'a cue already exists').

    Pinned here so a future planner edit can't silently drop the param
    and bring the partial-push debug loop back.
    """
    M.add_time_signature_point(
        conn, song_id=song, start_bar=1.0, numerator=4, denominator=4
    )
    M.add_cue_point(conn, song_id=song, position_bar=1.0, name="intro")
    M.add_cue_point(conn, song_id=song, position_bar=17.0, name="verse")

    plan = push.plan_push_cue_points(conn, song_id=song)
    assert plan.calls[0].args.get("if_exists") == "skip"


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


def test_plan_push_cue_points_disambiguates_repeated_names(conn, song):
    """W19-E: a song with 3 cues named 'chorus' renders as
    'chorus-1' / 'chorus-2' / 'chorus-3' in Live's locator strip.
    Disambiguation is in declaration order (matches what the user wrote
    in build.py)."""
    M.add_time_signature_point(
        conn, song_id=song, start_bar=1.0, numerator=4, denominator=4
    )
    M.add_cue_point(conn, song_id=song, position_bar=1.0, name="intro")
    M.add_cue_point(conn, song_id=song, position_bar=9.0, name="chorus")
    M.add_cue_point(conn, song_id=song, position_bar=17.0, name="verse")
    M.add_cue_point(conn, song_id=song, position_bar=25.0, name="chorus")
    M.add_cue_point(conn, song_id=song, position_bar=33.0, name="chorus")
    plan = push.plan_push_cue_points(conn, song_id=song)
    names = [c["name"] for c in plan.calls[0].args["cues"]]
    assert names == ["intro", "chorus-1", "verse", "chorus-2", "chorus-3"]


def test_plan_push_cue_points_singleton_names_unsuffixed(conn, song):
    """W19-E: names that appear exactly once stay unsuffixed (the suffix
    convention is purely for disambiguation, not a stylistic marker)."""
    M.add_time_signature_point(
        conn, song_id=song, start_bar=1.0, numerator=4, denominator=4
    )
    M.add_cue_point(conn, song_id=song, position_bar=1.0, name="intro")
    M.add_cue_point(conn, song_id=song, position_bar=9.0, name="verse")
    M.add_cue_point(conn, song_id=song, position_bar=17.0, name="chorus")
    plan = push.plan_push_cue_points(conn, song_id=song)
    names = [c["name"] for c in plan.calls[0].args["cues"]]
    assert names == ["intro", "verse", "chorus"]


def test_plan_push_cue_points_does_not_disambiguate_unnamed_cues(conn, song):
    """W19-E: empty/null names stay empty — Live displays them as
    'Unnamed' already, so suffixing would only make the locator strip
    less readable. The disambiguation is for the user-meaningful name
    collision case."""
    M.add_time_signature_point(
        conn, song_id=song, start_bar=1.0, numerator=4, denominator=4
    )
    M.add_cue_point(conn, song_id=song, position_bar=1.0, name=None)
    M.add_cue_point(conn, song_id=song, position_bar=9.0, name=None)
    plan = push.plan_push_cue_points(conn, song_id=song)
    names = [c["name"] for c in plan.calls[0].args["cues"]]
    assert names == ["", ""]


def test_plan_push_cue_points_respects_meter_change(conn, song):
    """Cue at bar 7 across a 4/4→6/8 change at bar 5 = 22 beats."""
    M.add_time_signature_point(
        conn, song_id=song, start_bar=1.0, numerator=4, denominator=4
    )
    _ts_point(conn, song, 5.0, 6, 8)
    M.add_cue_point(conn, song_id=song, position_bar=7.0, name="post-change")
    plan = push.plan_push_cue_points(conn, song_id=song)
    cues = plan.calls[0].args["cues"]
    assert cues == [{"position_beats": 22.0, "name": "post-change"}]


# ---------- plan_push_cue_points arrangement-extent warn (Wave 0) ----------


def _make_arrangement_clip(conn, song_id: str, start_bar: float, end_bar: float):
    """Helper: create a minimal track+clip+arrangement-clip row at the given span."""
    tid = M.create_track(conn, song_id=song_id, track_index=1, name="t1")
    # length_beats covers the full placement span at 4 beats/bar (test default).
    cid = M.create_clip(
        conn, track_id=tid, name="c1", slot=1,
        length_beats=(end_bar - start_bar) * 4.0,
    )
    M.add_arrangement_clip(
        conn, song_id=song_id, track_id=tid, clip_id=cid,
        start_bar=start_bar, end_bar=end_bar,
    )


def test_plan_push_cue_points_defers_when_no_arrangement(conn, song):
    """SYN-6B4Q skeleton case: cues exist but the DB has no arrangement_clips
    yet — the song isn't composed. Cues are DEFERRED, not failed. The planner
    emits the batch with ``on_out_of_range='skip'`` (so Live's handler skips
    cues past its empty extent and reports them rather than failing the whole
    batch atomically) and warns. No ``plan.error`` — deferral is benign; the
    cues land on the next push once arrangement content covers them."""
    M.add_time_signature_point(
        conn, song_id=song, start_bar=1.0, numerator=4, denominator=4
    )
    M.add_cue_point(conn, song_id=song, position_bar=17.0, name="verse")
    plan = push.plan_push_cue_points(conn, song_id=song)
    assert plan.errors == []
    assert len(plan.calls) == 1
    assert plan.calls[0].args["on_out_of_range"] == "skip"
    assert any("deferred" in n for n in plan.notes)


def test_plan_push_cue_points_sets_on_out_of_range_skip(conn, song):
    """SYN-6B4Q: the planner explicitly sets ``on_out_of_range='skip'`` so a
    cue ahead of Live's current arrangement extent (skeleton push, or an
    arrangement that hasn't built yet) defers instead of failing the batch.
    Pinned so a future edit can't silently drop the param and reintroduce the
    false-PARTIAL friction."""
    M.add_time_signature_point(
        conn, song_id=song, start_bar=1.0, numerator=4, denominator=4
    )
    _make_arrangement_clip(conn, song, start_bar=1.0, end_bar=17.0)
    M.add_cue_point(conn, song_id=song, position_bar=1.0, name="intro")
    plan = push.plan_push_cue_points(conn, song_id=song)
    assert plan.calls[0].args.get("on_out_of_range") == "skip"


def test_plan_push_cue_points_errors_when_cue_past_composed_length(conn, song):
    """SYN-6B4Q: arrangement covers bars 1–17 but a cue sits at bar 32 — past
    the composed song length. A cue that references content which can never
    exist is a hard authoring error, NOT a deferral: the planner refuses
    (``plan.error``) and emits no calls. The operator extends the arrangement
    or moves the cue, then re-pushes (idempotent)."""
    M.add_time_signature_point(
        conn, song_id=song, start_bar=1.0, numerator=4, denominator=4
    )
    _make_arrangement_clip(conn, song, start_bar=1.0, end_bar=17.0)
    M.add_cue_point(conn, song_id=song, position_bar=8.0, name="mid")
    M.add_cue_point(conn, song_id=song, position_bar=32.0, name="late")
    plan = push.plan_push_cue_points(conn, song_id=song)
    # Hard error → no calls emitted (nothing half-applies in Live).
    assert plan.calls == []
    assert len(plan.errors) == 1
    err = plan.errors[0]
    assert "late@bar32.00" in err
    assert "17.00" in err  # names the composed extent
    # The in-extent cue is not named as an offender.
    assert "mid@bar" not in err


def test_plan_push_cue_points_no_error_when_all_cues_within_arrangement(conn, song):
    """Cues at bars 1, 5, 16; arrangement extends to bar 17. No overrun and no
    skeleton deferral warn — the batch is emitted with ``on_out_of_range='skip'``
    (a silent runtime-extent safety net) and no ``plan.error``."""
    M.add_time_signature_point(
        conn, song_id=song, start_bar=1.0, numerator=4, denominator=4
    )
    _make_arrangement_clip(conn, song, start_bar=1.0, end_bar=17.0)
    M.add_cue_point(conn, song_id=song, position_bar=1.0, name="intro")
    M.add_cue_point(conn, song_id=song, position_bar=5.0, name="b")
    M.add_cue_point(conn, song_id=song, position_bar=16.0, name="c")
    plan = push.plan_push_cue_points(conn, song_id=song)
    assert plan.errors == []
    assert len(plan.calls) == 1
    assert plan.calls[0].args["on_out_of_range"] == "skip"
    assert not any("deferred" in n for n in plan.notes)


def test_plan_push_cue_points_cue_at_exact_composed_extent_is_ok(conn, song):
    """Boundary: a cue exactly at the composed extent (bar 17, end_bar 17) is
    within the song — not an overrun. It's emitted, not errored."""
    M.add_time_signature_point(
        conn, song_id=song, start_bar=1.0, numerator=4, denominator=4
    )
    _make_arrangement_clip(conn, song, start_bar=1.0, end_bar=17.0)
    M.add_cue_point(conn, song_id=song, position_bar=17.0, name="end")
    plan = push.plan_push_cue_points(conn, song_id=song)
    assert plan.errors == []
    assert len(plan.calls) == 1


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
