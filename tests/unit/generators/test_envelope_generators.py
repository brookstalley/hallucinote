"""Tests for envelope-producing generators (volume_swell, sidechain_trigger)."""
from __future__ import annotations

import pytest

from hallucinote.generators import GeneratorOutput
from hallucinote.generators.envelopes import (
    sidechain_trigger,
    volume_swell,
)


# --------------------------------------------------------------------------
# volume_swell
# --------------------------------------------------------------------------


def test_volume_swell_basic_shape():
    out = volume_swell(
        target_track_id="t1",
        start_beat=0.0,
        length_beats=8.0,
        peak_value=0.85,
        floor_value=0.0,
    )
    assert isinstance(out, GeneratorOutput)
    assert out.notes == []
    assert len(out.envelopes) == 1
    env = out.envelopes[0]
    assert env["target_kind"] == "mixer_volume"
    assert env["target_track_id"] == "t1"
    assert len(env["breakpoints"]) == 2


def test_volume_swell_breakpoints_floor_to_peak():
    out = volume_swell(
        target_track_id="t1",
        start_beat=4.0,
        length_beats=8.0,
        peak_value=0.85,
        floor_value=0.1,
    )
    bps = out.envelopes[0]["breakpoints"]
    assert bps[0] == {"time_beats": 4.0, "value": 0.1, "curve_kind": "linear"}
    assert bps[1] == {"time_beats": 12.0, "value": 0.85, "curve_kind": "linear"}


def test_volume_swell_return_to_floor_adds_third_breakpoint():
    out = volume_swell(
        target_track_id="t1",
        start_beat=0.0,
        length_beats=4.0,
        peak_value=0.9,
        return_to_floor=True,
    )
    bps = out.envelopes[0]["breakpoints"]
    assert len(bps) == 3
    assert bps[-1]["value"] == 0.0
    assert bps[-1]["time_beats"] == 8.0  # length 4 + fall 4 (default)


def test_volume_swell_custom_fall_length():
    out = volume_swell(
        target_track_id="t1",
        start_beat=0.0,
        length_beats=4.0,
        peak_value=0.9,
        return_to_floor=True,
        fall_length_beats=2.0,
    )
    bps = out.envelopes[0]["breakpoints"]
    assert bps[-1]["time_beats"] == 6.0  # 4 rise + 2 fall


def test_volume_swell_curve_kind_threaded():
    out = volume_swell(
        target_track_id="t1",
        start_beat=0.0, length_beats=4.0, peak_value=0.8,
        curve_kind="hold",
    )
    assert all(bp["curve_kind"] == "hold" for bp in out.envelopes[0]["breakpoints"])


def test_volume_swell_rejects_zero_length():
    with pytest.raises(ValueError, match="length_beats"):
        volume_swell(target_track_id="t1", start_beat=0.0, length_beats=0.0, peak_value=0.5)


def test_volume_swell_rejects_out_of_range_values():
    with pytest.raises(ValueError, match="peak_value"):
        volume_swell(target_track_id="t1", start_beat=0.0, length_beats=4.0, peak_value=1.5)
    with pytest.raises(ValueError, match="floor_value"):
        volume_swell(target_track_id="t1", start_beat=0.0, length_beats=4.0,
                     peak_value=0.5, floor_value=-0.1)


def test_volume_swell_rejects_negative_start_beat():
    with pytest.raises(ValueError, match="start_beat"):
        volume_swell(target_track_id="t1", start_beat=-1.0, length_beats=4.0, peak_value=0.5)


# --------------------------------------------------------------------------
# sidechain_trigger
# --------------------------------------------------------------------------


def test_sidechain_trigger_single_hit_three_breakpoints():
    out = sidechain_trigger(
        target_track_id="t1",
        at_beats=[4.0],
        rest_value=1.0,
        duck_value=0.3,
        attack_beats=0.02,
        recovery_beats=0.5,
    )
    env = out.envelopes[0]
    assert env["target_kind"] == "mixer_volume"
    assert env["target_track_id"] == "t1"
    bps = env["breakpoints"]
    assert len(bps) == 3
    # Anchor rest just before the hit
    assert bps[0]["time_beats"] == pytest.approx(3.98)
    assert bps[0]["value"] == 1.0
    # Duck at the hit
    assert bps[1]["time_beats"] == 4.0
    assert bps[1]["value"] == 0.3
    # Recovery
    assert bps[2]["time_beats"] == pytest.approx(4.5)
    assert bps[2]["value"] == 1.0


def test_sidechain_trigger_multiple_hits_emit_per_hit_triple():
    out = sidechain_trigger(
        target_track_id="t1",
        at_beats=[4.0, 8.0],
        attack_beats=0.02,
        recovery_beats=0.5,
    )
    bps = out.envelopes[0]["breakpoints"]
    # Two non-overlapping hits => 6 breakpoints
    assert len(bps) == 6


def test_sidechain_trigger_coalesces_overlapping_hits():
    # Two hits 0.1 beats apart; recovery is 0.5 — second hit's attack starts
    # at 4.10 - 0.02 = 4.08, which is well before the first recovery_end (4.5).
    # The second hit should NOT emit a fresh "rest anchor" breakpoint.
    out = sidechain_trigger(
        target_track_id="t1",
        at_beats=[4.0, 4.1],
        attack_beats=0.02,
        recovery_beats=0.5,
    )
    bps = out.envelopes[0]["breakpoints"]
    # First hit: anchor + duck + recovery = 3
    # Second hit: duck + recovery (no fresh anchor) = 2
    assert len(bps) == 5


def test_sidechain_trigger_sorts_unsorted_hits():
    out = sidechain_trigger(target_track_id="t1", at_beats=[8.0, 4.0])
    bps = out.envelopes[0]["breakpoints"]
    times = [bp["time_beats"] for bp in bps]
    assert times == sorted(times)


def test_sidechain_trigger_clamps_negative_anchor_to_zero():
    # Attack at time 0.01 would put the anchor at -0.01; should clamp to 0.
    out = sidechain_trigger(
        target_track_id="t1", at_beats=[0.01], attack_beats=0.02,
    )
    bps = out.envelopes[0]["breakpoints"]
    assert bps[0]["time_beats"] == 0.0


def test_sidechain_trigger_clamps_first_anchor_to_envelope_start():
    """P1: envelope_start_beats floors the first attack window's rest anchor
    so the envelope's beat range stays inside a section's session clip. A
    kick on the chorus downbeat would otherwise emit a pre-attack anchor
    at (hit - attack_beats) — outside the chorus clip, refused by Live's
    session-clip-only envelope routing."""
    out = sidechain_trigger(
        target_track_id="t1",
        at_beats=[124.0, 128.0],  # chorus downbeats
        attack_beats=0.02,
        recovery_beats=0.5,
        envelope_start_beats=124.0,
    )
    bps = out.envelopes[0]["breakpoints"]
    # First anchor lands AT chorus_start (124.0), not 123.98.
    assert bps[0]["time_beats"] == 124.0
    # Every breakpoint is >= envelope_start_beats.
    assert all(bp["time_beats"] >= 124.0 for bp in bps)


def test_sidechain_trigger_drops_anchor_when_clamped_at_hit():
    """When envelope_start_beats coincides with the hit (no leading-ramp
    room), the rest anchor is dropped — the duck breakpoint is the
    envelope's first."""
    out = sidechain_trigger(
        target_track_id="t1",
        at_beats=[124.0],
        attack_beats=0.02,
        recovery_beats=0.5,
        envelope_start_beats=124.0,
    )
    bps = out.envelopes[0]["breakpoints"]
    # Without envelope_start_beats this would be 3 breakpoints (anchor +
    # duck + recovery). With the clamp at the hit, the leading anchor is
    # absorbed into the duck — 2 breakpoints.
    assert len(bps) == 2
    assert bps[0]["time_beats"] == 124.0
    assert bps[0]["value"] != bps[1]["value"]  # duck then recovery


def test_sidechain_trigger_rejects_hit_before_envelope_start():
    """A hit timed before envelope_start_beats can't be ducked because the
    duck breakpoint would land outside the section. Reject loudly rather
    than emit a silently-clipped envelope."""
    with pytest.raises(ValueError, match="envelope_start_beats"):
        sidechain_trigger(
            target_track_id="t1",
            at_beats=[123.5, 124.0],
            envelope_start_beats=124.0,
        )


def test_sidechain_trigger_rejects_empty_hits():
    with pytest.raises(ValueError, match="at_beats"):
        sidechain_trigger(target_track_id="t1", at_beats=[])


def test_sidechain_trigger_rejects_negative_hit():
    with pytest.raises(ValueError, match="at_beats"):
        sidechain_trigger(target_track_id="t1", at_beats=[1.0, -0.5])


def test_sidechain_trigger_rejects_duplicate_hits():
    # Same hit twice would produce two breakpoints at the same time, leaving the
    # envelope value undefined at that instant.
    with pytest.raises(ValueError, match="duplicate"):
        sidechain_trigger(target_track_id="t1", at_beats=[4.0, 4.0])


def test_sidechain_trigger_rejects_duck_above_rest():
    with pytest.raises(ValueError, match="duck_value"):
        sidechain_trigger(target_track_id="t1", at_beats=[0.0], duck_value=0.9, rest_value=0.5)


def test_sidechain_trigger_rejects_out_of_range_values():
    with pytest.raises(ValueError, match="rest_value"):
        sidechain_trigger(target_track_id="t1", at_beats=[0.0], rest_value=1.5)


def test_sidechain_trigger_rejects_zero_attack():
    with pytest.raises(ValueError, match="attack_beats"):
        sidechain_trigger(target_track_id="t1", at_beats=[0.0], attack_beats=0.0)


# --------------------------------------------------------------------------
# Both generators play nice with the mutator surface
# --------------------------------------------------------------------------


def test_volume_swell_output_matches_create_envelope_kwargs():
    """Smoke: the EnvelopeDict shape lines up with create_envelope's required kwargs.

    Specifically: mixer_volume requires target_track_id and forbids parameter_path.
    """
    out = volume_swell(
        target_track_id="t1", start_beat=0.0, length_beats=4.0, peak_value=0.8,
    )
    env = out.envelopes[0]
    assert env["target_kind"] == "mixer_volume"
    assert env["target_track_id"] == "t1"
    assert "parameter_path" not in env  # forbidden for mixer_volume
    # Breakpoints have the shape replace_breakpoints expects
    for bp in env["breakpoints"]:
        assert set(bp.keys()) == {"time_beats", "value", "curve_kind"}


def test_sidechain_trigger_output_persists_via_mutators(tmp_path):
    """End-to-end: persist the envelope through real mutators."""
    from hallucinote.db import init_db, mutations as M

    db_path = tmp_path / "swell.db"
    conn = init_db(db_path)
    try:
        song_id = M.create_song(conn, name="test", key="C")
        track_id = M.create_track(
            conn, song_id=song_id, track_index=0, name="kick", kind="midi",
        )
        out = sidechain_trigger(target_track_id=track_id, at_beats=[0.0, 4.0])
        for env_spec in out.envelopes:
            bps = env_spec.pop("breakpoints")
            env_id = M.create_envelope(conn, song_id=song_id, **env_spec)
            M.replace_breakpoints(conn, envelope_id=env_id, breakpoints=bps)

        # Verify it landed.
        from hallucinote.db import queries as Q
        envs = Q.get_envelopes_for_track(conn, track_id)
        assert len(envs) == 1
        assert envs[0]["target_kind"] == "mixer_volume"
        bps = Q.get_breakpoints(conn, envelope_id=envs[0]["id"])
        # First hit at 0.0 → attack_start clamps to 0.0 == hit, so the
        # leading rest anchor is dropped (no leading-ramp room) → 2
        # breakpoints (duck + recovery). Second hit at 4.0 has space →
        # 3 breakpoints (anchor + duck + recovery). Total = 5.
        assert len(bps) == 5
    finally:
        conn.close()
