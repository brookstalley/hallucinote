"""Tests for `hallucinote.sync.envelope_curve` — the authored curve, the
staircase push sends in its place, and the comparison pull makes against it."""
from __future__ import annotations

import pytest

from hallucinote.sync import envelope_curve as ec


def _bp(t, v, curve="linear"):
    return {"time_beats": t, "value": v, "curve": curve}


# ---------- sample_authored_curve ----------


@pytest.mark.parametrize("curve, expected", [
    ("linear", 0.5),
    ("fast", 0.75),   # 1 - (1 - 0.5)**2
    ("slow", 0.25),   # 0.5**2
    ("hold", 0.0),
])
def test_curve_shapes_at_the_segment_midpoint(curve, expected):
    bps = [_bp(0.0, 0.0, curve), _bp(2.0, 1.0)]
    assert ec.sample_authored_curve(bps, 1.0) == pytest.approx(expected)


def test_value_holds_before_the_first_and_after_the_last_breakpoint():
    bps = [_bp(1.0, 0.2), _bp(3.0, 0.8)]
    assert ec.sample_authored_curve(bps, 0.0) == 0.2
    assert ec.sample_authored_curve(bps, 3.0) == 0.8
    assert ec.sample_authored_curve(bps, 9.0) == 0.8


def test_a_single_breakpoint_is_constant():
    bps = [_bp(1.0, 0.4)]
    for t in (0.0, 1.0, 5.0):
        assert ec.sample_authored_curve(bps, t) == 0.4


def test_absent_curve_means_linear_the_db_default():
    bps = [{"time_beats": 0.0, "value": 0.0}, {"time_beats": 1.0, "value": 1.0}]
    assert ec.sample_authored_curve(bps, 0.25) == pytest.approx(0.25)


def test_sampling_matches_the_perform_route_interpolator():
    """Parity lock. The perform route rides the authored curve through the
    MCP handler's own interpolator; the session-clip staircase samples it
    here. Two routes playing one envelope must agree on its shape."""
    from hallucinote_mcp.handlers.automation import _interp_performed_value
    bps = [
        _bp(0.0, 0.1, "linear"),
        _bp(1.0, 0.9, "fast"),
        _bp(2.0, 0.3, "slow"),
        _bp(3.0, 0.7, "hold"),
        _bp(3.0, 0.2, "linear"),   # a duplicate time: an instant jump
        _bp(4.5, 0.6, "linear"),
    ]
    beats = [i / 32 for i in range(-8, 6 * 32)]
    for t in beats:
        assert ec.sample_authored_curve(bps, t) == pytest.approx(
            _interp_performed_value(bps, t)
        ), t


# ---------- render_staircase ----------


def test_a_hold_only_envelope_is_returned_untouched():
    bps = [_bp(0.0, 0.5, "hold"), _bp(1.0, 0.0, "hold")]
    out, step = ec.render_staircase(bps)
    assert out == bps
    assert all(a is b for a, b in zip(out, bps))
    assert step == ec.STAIRCASE_STEP_BEATS


def test_a_non_hold_envelope_with_no_value_change_is_returned_untouched():
    bps = [_bp(0.0, 0.5), _bp(1.0, 0.5), _bp(2.0, 0.5)]
    out, _step = ec.render_staircase(bps)
    assert out == bps


def test_a_linear_ramp_is_cut_into_equal_steps_that_land_on_its_end():
    bps = [_bp(0.0, 0.5), _bp(1.0, 0.0)]
    out, step = ec.render_staircase(bps)
    assert step == 0.0625
    assert len(out) == 17  # 16 steps across one beat, then the end point
    assert [o["time_beats"] for o in out] == [k / 16 for k in range(17)]
    assert out[0]["value"] == 0.5
    assert out[-1]["value"] == 0.0
    assert {o["curve"] for o in out} == {"hold"}


def test_every_authored_breakpoint_survives_at_its_exact_time_and_value():
    bps = [
        _bp(0.0, 0.1, "linear"), _bp(1.3, 0.9, "fast"),
        _bp(2.0, 0.3, "hold"), _bp(2.7, 0.6, "slow"), _bp(4.0, 0.2),
    ]
    out, _step = ec.render_staircase(bps)
    wire = {(o["time_beats"], o["value"]) for o in out}
    for b in bps:
        assert (b["time_beats"], b["value"]) in wire


def test_a_hold_segment_inside_a_ramping_envelope_stays_one_step():
    bps = [_bp(0.0, 0.0), _bp(1.0, 1.0, "hold"), _bp(2.0, 0.5)]
    out, _step = ec.render_staircase(bps)
    in_hold = [o for o in out if 1.0 <= o["time_beats"] < 2.0]
    assert in_hold == [{"time_beats": 1.0, "value": 1.0, "curve": "hold"}]


def test_a_duplicate_time_at_the_start_steps_from_the_second_value():
    """Two breakpoints at one beat are an instant jump. The ramp after it
    starts from the SECOND value, not the first."""
    bps = [_bp(0.0, 0.0), _bp(0.0, 1.0), _bp(1.0, 0.0)]
    out, _step = ec.render_staircase(bps)
    assert (out[0]["time_beats"], out[0]["value"]) == (0.0, 0.0)
    assert (out[1]["time_beats"], out[1]["value"]) == (0.0, 1.0)
    assert out[2]["value"] < 1.0
    assert (out[-1]["time_beats"], out[-1]["value"]) == (1.0, 0.0)


def test_a_ramp_past_the_cap_widens_its_step_and_still_arrives():
    bps = [_bp(0.0, 0.0), _bp(64.0, 1.0)]
    out, step = ec.render_staircase(bps, max_steps=100)
    assert len(out) <= 100
    assert step > ec.STAIRCASE_STEP_BEATS
    assert (out[-1]["time_beats"], out[-1]["value"]) == (64.0, 1.0)
    widths = {
        round(b["time_beats"] - a["time_beats"], 9) for a, b in zip(out, out[1:])
    }
    assert max(widths) <= step


def test_the_default_cap_covers_a_sixteen_bar_ramp_at_full_resolution():
    out, step = ec.render_staircase([_bp(0.0, 0.0), _bp(64.0, 1.0)])
    assert step == ec.STAIRCASE_STEP_BEATS
    assert len(out) == 64 * 16 + 1  # every 1/16-beat step, then the end point


def test_an_envelope_denser_than_the_cap_terminates_at_one_step_per_segment():
    """More authored breakpoints than the cap allows can't be widened under
    — the floor is one point per breakpoint, and rendering must still end."""
    bps = [_bp(float(i), float(i % 2)) for i in range(40)]
    out, _step = ec.render_staircase(bps, max_steps=10)
    assert len(out) == 40


# ---------- staircase_matches ----------


def _changes(bps):
    return [{"time_beats": b["time_beats"], "value": b["value"]} for b in bps]


def test_the_rendered_staircase_matches_itself_read_back():
    rendered, _ = ec.render_staircase([_bp(0.0, 0.5), _bp(1.0, 0.0)])
    assert ec.staircase_matches(
        rendered, _changes(rendered), time_eps=0.0115, value_eps=1e-3,
    )


def test_a_read_back_late_by_less_than_the_time_tolerance_still_matches():
    rendered, _ = ec.render_staircase([_bp(0.0, 0.5), _bp(1.0, 0.0)])
    late = [
        {"time_beats": b["time_beats"] + (0.01 if i else 0.0), "value": b["value"]}
        for i, b in enumerate(rendered)
    ]
    assert ec.staircase_matches(rendered, late, time_eps=0.0115, value_eps=1e-3)


def test_one_moved_step_is_a_mismatch():
    rendered, _ = ec.render_staircase([_bp(0.0, 0.5), _bp(1.0, 0.0)])
    edited = _changes(rendered)
    edited[5] = {**edited[5], "value": edited[5]["value"] + 0.05}
    assert not ec.staircase_matches(
        rendered, edited, time_eps=0.0115, value_eps=1e-3,
    )


def test_a_live_ride_before_the_authored_envelope_is_a_mismatch():
    """The DB says nothing about time before its first breakpoint, so a Live
    value there is not something the staircase can vouch for."""
    rendered, _ = ec.render_staircase([_bp(1.0, 0.5), _bp(2.0, 0.0)])
    live = [{"time_beats": 0.0, "value": 0.8}] + _changes(rendered)
    assert not ec.staircase_matches(
        rendered, live, time_eps=0.0115, value_eps=1e-3,
    )


def test_a_truncated_read_back_is_a_mismatch():
    rendered, _ = ec.render_staircase([_bp(0.0, 0.5), _bp(1.0, 0.0)])
    assert not ec.staircase_matches(
        rendered, _changes(rendered)[:8], time_eps=0.0115, value_eps=1e-3,
    )


# ---------- is_flat_at ----------


def test_unknown_static_value_is_never_flat():
    assert not ec.is_flat_at([0.5, 0.5], None)


def test_every_value_at_static_is_flat():
    assert ec.is_flat_at([0.7, 0.7, 0.7], 0.7)


def test_a_value_just_off_static_is_a_real_ride():
    assert not ec.is_flat_at([0.7, 0.701], 0.7)
