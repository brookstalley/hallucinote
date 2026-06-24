"""Bark critical-band grid (extracted from masking.py for AUD-8T3K).

The 24-band map test moved here with the code it covers; the aggregation test
pins the shared bin→band summation both masking and timbre depend on.
"""
from __future__ import annotations

import numpy as np
import pytest

from hallucinote.audio.bark import aggregate_to_bands, bark_band_map


def test_bark_map_has_24_bands_at_standard_rates_no_degenerate():
    # 44.1/48 kHz: Nyquist is above the top Bark edge, so the map must be the
    # full 24 critical bands with NO zero-width trailing band.
    for sr in (44_100, 48_000):
        bark = bark_band_map(sr, 2048)
        assert bark.n_bands == 24, f"{sr}: expected 24 bands, got {bark.n_bands}"
        widths = np.diff(bark.edges_hz)
        assert np.all(widths > 0), f"{sr}: zero-width band {bark.edges_hz}"


def test_low_sample_rate_caps_top_band_at_nyquist():
    # When Nyquist falls inside the Bark range, the top band is clamped to it
    # (no band straddles Nyquist) and stays positive-width.
    bark = bark_band_map(16_000, 2048)
    assert bark.edges_hz[-1] == pytest.approx(8_000.0)
    assert np.all(np.diff(bark.edges_hz) > 0)


def test_aggregate_to_bands_conserves_in_range_power():
    bark = bark_band_map(48_000, 2048)
    n_bins = bark.bin_band.shape[0]
    power = np.ones((n_bins, 1), dtype=np.float64)  # unit power per bin, 1 frame

    bands = aggregate_to_bands(power, bark)

    assert bands.shape == (bark.n_bands, 1)
    # Only out-of-range bins (band == -1) are dropped; the rest are conserved.
    in_range = int(np.count_nonzero(bark.bin_band >= 0))
    assert bands.sum() == pytest.approx(float(in_range))
    # Each band holds exactly the count of bins assigned to it.
    for b in range(bark.n_bands):
        expected = float(np.count_nonzero(bark.bin_band == b))
        assert bands[b, 0] == pytest.approx(expected)
