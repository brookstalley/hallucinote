"""Tests for hallucinote.tempo conversion helpers."""
from __future__ import annotations

import math

import pytest

from hallucinote.tempo import to_live_bpm


# ---------- canonical canary case ----------


def test_eighth_pulse_168_converts_to_quarter_84():
    """The Wave-0 odd-meter-experimental canary case: 168 BPM eighth-pulse
    in 7/8 is the same speed as 84 BPM quarter-pulse (which is what Live
    wants)."""
    assert to_live_bpm(168.0, "eighth") == 84.0


# ---------- identity + simple ratios ----------


@pytest.mark.parametrize("pulse_kind,expected_ratio", [
    ("whole",   4.0),
    ("half",    2.0),
    ("quarter", 1.0),
    ("eighth",  0.5),
    ("sixteenth", 0.25),
])
def test_simple_pulse_ratios(pulse_kind, expected_ratio):
    """100 BPM at any pulse converts to 100 * (pulse/quarter) BPM quarter."""
    assert to_live_bpm(100.0, pulse_kind) == 100.0 * expected_ratio


# ---------- dotted + triplet ----------


def test_dotted_quarter_pulse():
    """120 BPM dotted-quarter (1.5 quarters) -> 180 BPM quarter."""
    assert to_live_bpm(120.0, "dotted_quarter") == 180.0


def test_dotted_eighth_pulse():
    """120 BPM dotted-eighth (0.75 quarters) -> 90 BPM quarter."""
    assert to_live_bpm(120.0, "dotted_eighth") == 90.0


def test_triplet_eighth_pulse():
    """120 BPM triplet-eighth (1/3 quarter) -> 40 BPM quarter."""
    assert math.isclose(to_live_bpm(120.0, "triplet_eighth"), 40.0)


def test_dotted_half_pulse():
    """60 BPM dotted-half (3 quarters) -> 180 BPM quarter. The 'one beat per
    bar in 6/8 treating dotted-half-bar as the pulse' authoring shortcut."""
    assert to_live_bpm(60.0, "dotted_half") == 180.0


# ---------- argument validation ----------


def test_unknown_pulse_kind_raises_with_accepted_list():
    with pytest.raises(ValueError, match=r"unknown pulse_kind 'beat'"):
        to_live_bpm(120.0, "beat")
    # Error message lists the accepted set (helps the author recover).
    with pytest.raises(ValueError, match=r"accepted:.*'quarter'"):
        to_live_bpm(120.0, "beat")


def test_zero_or_negative_pulse_bpm_raises():
    with pytest.raises(ValueError, match=r"pulse_bpm must be > 0"):
        to_live_bpm(0.0, "quarter")
    with pytest.raises(ValueError, match=r"pulse_bpm must be > 0"):
        to_live_bpm(-10.0, "quarter")


def test_time_signature_accepted_but_unused():
    """The arg is reserved for a future variant. Today it doesn't change
    output — the pulse-to-quarter ratio is meter-independent."""
    assert to_live_bpm(168.0, "eighth", time_signature="7/8") == 84.0
    assert to_live_bpm(168.0, "eighth", time_signature=None) == 84.0
    assert to_live_bpm(168.0, "eighth") == 84.0


def test_fractional_pulse_bpm_preserved():
    """132.5 quarter-pulse should round-trip identity-wise."""
    assert to_live_bpm(132.5, "quarter") == 132.5
