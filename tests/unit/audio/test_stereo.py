"""Per-surface stereo metrics — correlation and mono-sum loss (STR-4C8N).

The motivating case is in the acceptance criteria of
``.prawduct/artifacts/plans/STR-4C8N/build-plan.md``: a flanger declared to give
a mono guitar chain stereo, whose automation verified as recorded AND playing
while the rendered stem stayed bit-exact mono. These tests pin the measurement
that catches it.
"""
from __future__ import annotations

import math

import numpy as np
import pytest

from hallucinote.audio.stereo import measure_stereo


def _stereo(left: np.ndarray, right: np.ndarray) -> np.ndarray:
    return np.stack([left, right], axis=1).astype(np.float32)


def _tone(n: int = 4800, freq: float = 220.0, sr: int = 48000) -> np.ndarray:
    t = np.arange(n) / sr
    return np.sin(2 * math.pi * freq * t).astype(np.float32)


class TestBitExactMono:
    """The failure the whole lens exists to catch."""

    def test_identical_channels_report_unity_and_no_loss(self) -> None:
        x = _tone()
        m = measure_stereo(_stereo(x, x))
        assert m.correlation == pytest.approx(1.0)
        # Summing identical channels loses nothing — it IS the same signal.
        assert m.mono_sum_loss_db == pytest.approx(0.0, abs=1e-6)

    def test_silent_stereo_does_not_divide_by_zero(self) -> None:
        z = np.zeros(4800, dtype=np.float32)
        m = measure_stereo(_stereo(z, z))
        # Silence is unmeasurable, not "mono" — NaN is the report's silent
        # sentinel (it serializes to null), matching TimbreMetrics.
        assert math.isnan(m.correlation)
        assert math.isnan(m.mono_sum_loss_db)

    def test_empty_window_is_unmeasurable(self) -> None:
        empty = np.zeros((0, 2), dtype=np.float32)
        m = measure_stereo(empty)
        assert math.isnan(m.correlation)
        assert math.isnan(m.mono_sum_loss_db)


class TestDecorrelation:
    def test_anti_phase_collapses_in_mono(self) -> None:
        x = _tone()
        m = measure_stereo(_stereo(x, -x))
        assert m.correlation == pytest.approx(-1.0)
        # The mono sum cancels to silence. Floored rather than -inf so the
        # report stays valid JSON.
        assert m.mono_sum_loss_db <= -100.0
        assert math.isfinite(m.mono_sum_loss_db)

    def test_uncorrelated_channels_lose_about_3_db(self) -> None:
        rng = np.random.default_rng(20260810)
        left = rng.standard_normal(48000).astype(np.float32)
        right = rng.standard_normal(48000).astype(np.float32)
        m = measure_stereo(_stereo(left, right))
        assert abs(m.correlation) < 0.05
        # Two equal-power uncorrelated signals summed and halved: sqrt(1/2).
        assert m.mono_sum_loss_db == pytest.approx(-3.01, abs=0.15)

    def test_partial_decorrelation_sits_between(self) -> None:
        """A widened-but-related pair — the shape of a working flanger."""
        rng = np.random.default_rng(7)
        base = _tone(48000)
        side = rng.standard_normal(48000).astype(np.float32) * 0.3
        m = measure_stereo(_stereo(base + side, base - side))
        assert 0.0 < m.correlation < 1.0
        assert -3.0 < m.mono_sum_loss_db < 0.0


class TestRealRenderValues:
    """Reproduce the hand-computed numbers from the-argument's render.

    These are the plan's A1 acceptance criteria. They are expressed as the
    RELATIONSHIPS that made each case diagnostic, not as frozen constants — a
    re-render legitimately shifts the third decimal, and a test that pins noise
    would have to be weakened later, which tests must never be.
    """

    def test_no_op_width_control_is_distinguishable_from_real_width(self) -> None:
        # Drone: 165% declared width, +0.898 correlation, -0.23 dB loss — an
        # aggressive setting doing almost nothing, because there is barely any
        # side signal to multiply.
        rng = np.random.default_rng(11)
        base = rng.standard_normal(48000).astype(np.float32)
        near_mono = measure_stereo(
            _stereo(base + base * 0.0, base + rng.standard_normal(48000).astype(np.float32) * 0.05)
        )
        # Brass: -0.174 correlation, -3.84 dB — real width, costing mono level.
        wide = measure_stereo(
            _stereo(base, -base + rng.standard_normal(48000).astype(np.float32) * 0.5)
        )
        assert near_mono.correlation > wide.correlation
        assert near_mono.mono_sum_loss_db > wide.mono_sum_loss_db
        # The separation is the whole point: a no-op reads near 0 dB loss while
        # genuine width costs real mono level.
        assert near_mono.mono_sum_loss_db > -1.0
        assert wide.mono_sum_loss_db < -3.0


class TestInputHandling:
    def test_mono_input_is_rejected_rather_than_guessed(self) -> None:
        with pytest.raises(ValueError, match="stereo"):
            measure_stereo(np.zeros((4800, 1), dtype=np.float32))

    def test_correlation_is_bounded(self) -> None:
        rng = np.random.default_rng(3)
        for _ in range(5):
            a = rng.standard_normal(2400).astype(np.float32)
            b = rng.standard_normal(2400).astype(np.float32)
            m = measure_stereo(_stereo(a, b))
            assert -1.0 <= m.correlation <= 1.0
