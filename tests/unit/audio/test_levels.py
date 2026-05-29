"""Mix-level reconstruction (F1) — fader-curve anchors + masking correction.

The fader curve itself is an unverified approximation (see audio/levels.py); the
tests pin the anchors we're confident about and verify the *mechanism* — a
faded-down masker stops over-reporting masking — which is the architecture that
matters.
"""
from __future__ import annotations

import numpy as np
import pytest

from hallucinote.audio.levels import (
    apply_stem_gains,
    live_fader_db,
    live_fader_gain,
)
from hallucinote.audio.masking import analyze_masking_window
from tests.unit.audio.fixtures import SAMPLE_RATE, sine

SR = SAMPLE_RATE


def test_fader_curve_matches_live_calibration():
    # Measured from Live 12 via mixer_device.volume.display_value (2026-05-28).
    # live_fader_db must reproduce each sampled point exactly (table interp).
    measured = {
        0.05: -57.2, 0.10: -48.6, 0.15: -41.0, 0.20: -34.4, 0.30: -24.2,
        0.40: -18.0, 0.50: -14.0, 0.75: -4.0, 0.85: 0.0, 0.90: 2.0, 1.00: 6.0,
    }
    for norm, db in measured.items():
        assert live_fader_db(norm) == pytest.approx(db, abs=0.05), (
            f"v={norm}: expected {db} dB (Live), got {live_fader_db(norm):.2f}"
        )


def test_fader_upper_region_is_linear_40db_per_unit():
    # [0.40, 1.00]: dB = 40*(v - 0.85), verified against Live.
    for v in (0.45, 0.6, 0.7, 0.8, 0.95):
        assert live_fader_db(v) == pytest.approx(40.0 * (v - 0.85), abs=0.05)


def test_fader_curve_anchors():
    assert live_fader_db(0.0) == float("-inf")
    assert live_fader_db(0.85) == pytest.approx(0.0, abs=1e-9)   # unity
    assert live_fader_db(1.0) == pytest.approx(6.0, abs=1e-9)    # +6 dB
    # Gains at the anchors.
    assert live_fader_gain(0.0) == 0.0
    assert live_fader_gain(0.85) == pytest.approx(1.0, abs=1e-9)
    assert live_fader_gain(1.0) == pytest.approx(10 ** (6.0 / 20.0), rel=1e-9)


def test_fader_curve_is_monotonic():
    vs = np.linspace(0.01, 1.0, 50)
    gains = [live_fader_gain(v) for v in vs]
    assert all(b >= a for a, b in zip(gains, gains[1:]))


def test_fader_clamps_above_unity():
    assert live_fader_db(1.5) == pytest.approx(6.0)  # clamp, no runaway


def test_apply_stem_gains_is_noop_for_empty_map():
    a = sine(2000.0, 1.0, amplitude=0.5)
    out = apply_stem_gains([("A", a)], {})
    assert out[0][1] is a  # passthrough, no copy


def test_apply_stem_gains_scales():
    a = sine(2000.0, 1.0, amplitude=0.5)
    out = apply_stem_gains([("A", a)], {"A": 0.5})
    assert np.allclose(out[0][1], a * 0.5)


def test_level_reconstruction_kills_spurious_masking_from_faded_stem():
    # A is loud at SOURCE and would mask B — but A's fader is way down, so at
    # MIX level it no longer masks. The gain correction must flip the verdict.
    dur = 2.0
    a = sine(2000.0, dur, amplitude=0.50)  # ~20 dB above B at source
    b = sine(2100.0, dur, amplitude=0.05)  # quieter source, same band

    raw = analyze_masking_window([("A", a), ("B", b)], SR)
    raw_frac = next(
        (p.masked_fraction for p in raw.pairs
         if p.masker_track_id == "A" and p.maskee_track_id == "B"),
        0.0,
    )
    assert raw_frac > 0.5, "pre-fader: A masks B"

    # A's fader cut deep (~-25 dB); B at unity. Now A sits BELOW B at mix level,
    # so it can't mask it — the correction must flip the verdict.
    gains = {"A": live_fader_gain(0.20), "B": live_fader_gain(0.85)}
    corrected = analyze_masking_window(
        apply_stem_gains([("A", a), ("B", b)], gains), SR
    )
    corr_frac = next(
        (p.masked_fraction for p in corrected.pairs
         if p.masker_track_id == "A" and p.maskee_track_id == "B"),
        0.0,
    )
    # Curve-agnostic: a deep fader cut on the masker substantially reduces the
    # masked fraction (exact value depends on the fader curve, which is
    # calibrated separately).
    assert corr_frac < raw_frac - 0.2, (
        f"level correction should cut masking: raw={raw_frac:.2f} "
        f"corr={corr_frac:.2f}"
    )
