"""Per-surface soundstage imaging — balance, position, width, and per band.

The case that justifies the module is the one the broadband lens documents as
its blind spot: a surface mono below a crossover and decorrelated above it
averages to an unremarkable broadband number, and nothing anywhere says where
the image actually lives. ``TestBandSplit`` pins that. The rest pin the pan-bug
detector, the two ends of the width scale, and the refusal to invent a reading
for something inaudible.
"""
from __future__ import annotations

import math

import numpy as np
import pytest

from hallucinote.audio.attribution import BANDS
from hallucinote.audio.imaging import measure_imaging
from tests.unit.audio.fixtures import SAMPLE_RATE, pink_noise, silence, sine


def _stereo(left: np.ndarray, right: np.ndarray) -> np.ndarray:
    return np.stack([left, right], axis=1).astype(np.float32)


def _band(metrics, name: str):
    return next(b for b in metrics.band_images if b.band == name)


class TestBalanceAndPosition:
    """The pan-bug detector: which side is the energy on, and how far."""

    def test_hard_left_reads_negative_balance_and_full_left_position(self) -> None:
        x = sine(220.0, 1.0)[:, 0]
        m = measure_imaging(
            _stereo(x, np.zeros_like(x)), sample_rate=SAMPLE_RATE
        )
        assert m.skipped is None
        assert m.balance_db < -100.0
        assert math.isfinite(m.balance_db)
        assert m.position == pytest.approx(-1.0)

    def test_hard_right_reads_positive_balance_and_full_right_position(self) -> None:
        x = sine(220.0, 1.0)[:, 0]
        m = measure_imaging(
            _stereo(np.zeros_like(x), x), sample_rate=SAMPLE_RATE
        )
        assert m.balance_db > 100.0
        assert math.isfinite(m.balance_db)
        assert m.position == pytest.approx(1.0)

    def test_centred_source_is_balanced(self) -> None:
        m = measure_imaging(pink_noise(1.0), sample_rate=SAMPLE_RATE)
        assert m.balance_db == pytest.approx(0.0, abs=1e-6)
        assert m.position == pytest.approx(0.0, abs=1e-6)

    def test_partial_pan_lands_between_centre_and_the_edge(self) -> None:
        """A pan-law pan, which is the shape a real pan bug takes."""
        x = pink_noise(1.0)[:, 0]
        theta = math.radians(30.0)  # left-leaning: cos > sin
        m = measure_imaging(
            _stereo(x * math.cos(theta), x * math.sin(theta)),
            sample_rate=SAMPLE_RATE,
        )
        assert -1.0 < m.position < 0.0
        assert m.balance_db < 0.0
        # Panning does not decorrelate: the two channels stay scalar multiples
        # of each other, so a panned mono source is still a point source.
        assert m.width == pytest.approx(0.0, abs=0.01)

    def test_position_is_the_mid_side_cross_power(self) -> None:
        """The docstring says ``position`` and the mid/side cross-power are the
        same fact, and a reader must be able to reproduce the number. This
        recomputes it the other way round."""
        rng = np.random.default_rng(77)
        base = rng.standard_normal(24000).astype(np.float64)
        left = (base * 0.9 + rng.standard_normal(24000) * 0.2).astype(np.float32)
        right = (base * 0.4 + rng.standard_normal(24000) * 0.2).astype(np.float32)
        m = measure_imaging(_stereo(left, right), sample_rate=SAMPLE_RATE)

        mid = 0.5 * (left.astype(np.float64) + right.astype(np.float64))
        side = 0.5 * (left.astype(np.float64) - right.astype(np.float64))
        from_mid_side = -2.0 * float(np.mean(mid * side)) / float(
            np.mean(mid**2) + np.mean(side**2)
        )
        assert m.position == pytest.approx(from_mid_side, abs=1e-9)

    def test_position_stays_bounded(self) -> None:
        rng = np.random.default_rng(4242)
        for _ in range(5):
            left = rng.standard_normal(9600).astype(np.float32)
            right = rng.standard_normal(9600).astype(np.float32) * rng.uniform(0.1, 4.0)
            m = measure_imaging(_stereo(left, right), sample_rate=SAMPLE_RATE)
            assert -1.0 <= m.position <= 1.0
            assert 0.0 <= m.width <= 1.0


class TestWidth:
    """The two ends of the scale, and what sits between them."""

    def test_centred_mono_source_reads_zero_width_and_unity_correlation(self) -> None:
        m = measure_imaging(pink_noise(1.0), sample_rate=SAMPLE_RATE)
        assert m.width == 0.0
        # Every band that carries signal agrees: identical channels correlate
        # at +1 inside every band, not only on average.
        sounding = [b for b in m.band_images if not math.isnan(b.correlation)]
        assert len(sounding) == len(BANDS)
        for b in sounding:
            assert b.correlation == pytest.approx(1.0)
            assert b.width == pytest.approx(0.0, abs=1e-9)
        # No side content at all — the clamped reading, not -inf.
        assert m.mid_side_ratio_db > 100.0
        assert math.isfinite(m.mid_side_ratio_db)

    def test_decorrelated_pair_reads_wide(self) -> None:
        left = pink_noise(1.0, rng=np.random.default_rng(101))[:, 0]
        right = pink_noise(1.0, rng=np.random.default_rng(202))[:, 0]
        m = measure_imaging(_stereo(left, right), sample_rate=SAMPLE_RATE)
        assert m.width > 0.9
        # Independent channels put equal energy in mid and side.
        assert m.mid_side_ratio_db == pytest.approx(0.0, abs=1.0)

    def test_anti_phase_reads_wide_with_no_centre_image(self) -> None:
        """Cancellation is not a THIRD width reading — it is a missing centre.

        ``width`` saturates at 1 and ``mid_side_ratio_db`` carries the
        cancellation, so the pair reads "fully spread, nothing in the middle"
        rather than a centred source at position 0.
        """
        x = sine(220.0, 1.0)[:, 0]
        m = measure_imaging(_stereo(x, -x), sample_rate=SAMPLE_RATE)
        assert m.width == pytest.approx(1.0)
        assert m.position == pytest.approx(0.0, abs=1e-6)
        assert m.mid_side_ratio_db < -100.0
        assert math.isfinite(m.mid_side_ratio_db)

    def test_hard_panned_point_source_is_not_called_wide(self) -> None:
        """A hard pan has one empty channel, so there is no pair to be
        decorrelated FROM — it is a point at the edge, continuous with the
        pan just inside it (see ``test_partial_pan_lands_between...``)."""
        x = sine(440.0, 1.0)[:, 0]
        m = measure_imaging(_stereo(x, np.zeros_like(x)), sample_rate=SAMPLE_RATE)
        assert m.width == 0.0

    def test_partial_decorrelation_sits_between_the_ends(self) -> None:
        base = pink_noise(1.0, rng=np.random.default_rng(5))[:, 0]
        spray = pink_noise(1.0, amplitude=0.1, rng=np.random.default_rng(6))[:, 0]
        m = measure_imaging(_stereo(base + spray, base - spray), sample_rate=SAMPLE_RATE)
        assert 0.0 < m.width < 1.0


class TestBandSplit:
    """The case the broadband lens cannot see: mono low end, wide top."""

    def _mono_low_wide_top(self) -> np.ndarray:
        low = sine(80.0, 2.0, amplitude=0.5)[:, 0]
        # Quadrature 8 kHz: exactly orthogonal over whole cycles, so the top
        # band is fully decorrelated without needing a noise source whose
        # spectrum would bleed into the bands under test.
        #
        # Only the two occupied bands are asserted. The four between them hold
        # nothing but the two tones' filter skirts plus the cosine channel's
        # buffer-edge step, so their readings are real measurements of an
        # artifact — meaningful to neither the fixture nor the lens.
        top_left = sine(8000.0, 2.0, amplitude=0.3)[:, 0]
        top_right = sine(8000.0, 2.0, amplitude=0.3, phase=math.pi / 2)[:, 0]
        return _stereo(low + top_left, low + top_right)

    def test_low_band_reads_mono_and_top_band_reads_wide(self) -> None:
        m = measure_imaging(self._mono_low_wide_top(), sample_rate=SAMPLE_RATE)
        low = _band(m, "low_60_200")
        assert low.correlation > 0.99
        assert low.width < 0.02
        air = _band(m, "air_6k_plus")
        assert abs(air.correlation) < 0.15
        assert air.width > 0.85

    def test_the_broadband_number_hides_the_split(self) -> None:
        """Why the per-band split exists at all: averaged over the spectrum
        the surface reads middling, and the top's full decorrelation
        disappears into the mono low end's energy."""
        m = measure_imaging(self._mono_low_wide_top(), sample_rate=SAMPLE_RATE)
        air = _band(m, "air_6k_plus")
        assert m.width < 0.5
        assert air.width > m.width + 0.3

    def test_every_band_is_reported_in_order(self) -> None:
        """A missing entry cannot be told apart from a band nobody measured."""
        m = measure_imaging(self._mono_low_wide_top(), sample_rate=SAMPLE_RATE)
        assert [b.band for b in m.band_images] == [name for name, _, _ in BANDS]

    def test_a_band_with_no_energy_is_unmeasurable_not_correlated(self) -> None:
        """Correlating the filter's numerical residue would invent an image
        where there is no sound."""
        m = measure_imaging(sine(80.0, 1.0), sample_rate=SAMPLE_RATE)
        air = _band(m, "air_6k_plus")
        assert math.isnan(air.correlation)
        assert math.isnan(air.width)

    def test_a_one_sided_band_reads_as_a_point_not_a_spread(self) -> None:
        low = sine(80.0, 1.0, amplitude=0.5)[:, 0]
        top = sine(8000.0, 1.0, amplitude=0.3)[:, 0]
        m = measure_imaging(_stereo(low + top, low), sample_rate=SAMPLE_RATE)
        air = _band(m, "air_6k_plus")
        assert math.isnan(air.correlation)
        assert air.width == 0.0


class TestUnmeasurable:
    """Silence and near-silence are skipped with a reason, never guessed."""

    def test_silence_is_skipped_with_a_structured_reason(self) -> None:
        m = measure_imaging(silence(1.0), sample_rate=SAMPLE_RATE)
        assert m.skipped == "below_silence_floor"
        assert math.isnan(m.balance_db)
        assert math.isnan(m.mid_side_ratio_db)
        assert math.isnan(m.position)
        assert math.isnan(m.width)
        assert m.band_images == []

    def test_dither_level_noise_is_below_the_floor(self) -> None:
        """The healthy reading is also the failure signature, so an inaudible
        surface must not be handed a confident 'centred mono'."""
        rng = np.random.default_rng(9)
        tiny = (rng.standard_normal(48000) * 1e-7).astype(np.float32)
        m = measure_imaging(_stereo(tiny, tiny), sample_rate=SAMPLE_RATE)
        assert m.skipped == "below_silence_floor"

    def test_empty_window_is_skipped(self) -> None:
        m = measure_imaging(np.zeros((0, 2), dtype=np.float32), sample_rate=SAMPLE_RATE)
        assert m.skipped == "empty_window"
        assert m.band_images == []

    def test_invalid_sample_rate_is_skipped_rather_than_assumed(self) -> None:
        m = measure_imaging(pink_noise(0.5), sample_rate=0)
        assert m.skipped == "invalid_sample_rate"

    def test_window_too_short_to_filter_still_reports_broadband(self) -> None:
        """The bands need the filter's padding; the balance does not, and a
        real reading must not be thrown away because a derived one is
        unavailable."""
        x = sine(440.0, 1.0)[:, 0][:32]
        m = measure_imaging(_stereo(x, np.zeros_like(x)), sample_rate=SAMPLE_RATE)
        assert m.skipped is None
        assert m.position == pytest.approx(-1.0)
        assert all(math.isnan(b.correlation) for b in m.band_images)
        assert all(math.isnan(b.width) for b in m.band_images)


class TestInputHandling:
    def test_mono_input_is_rejected_rather_than_guessed(self) -> None:
        with pytest.raises(ValueError, match="stereo"):
            measure_imaging(np.zeros((4800, 1), dtype=np.float32), sample_rate=SAMPLE_RATE)

    def test_three_channel_input_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="stereo"):
            measure_imaging(np.zeros((4800, 3), dtype=np.float32), sample_rate=SAMPLE_RATE)
