"""Bark critical-band mapping — the shared psychoacoustic frequency grid.

Extracted from ``masking.py`` (AUD-8T3K) so more than one lens can bin an STFT
into Zwicker critical bands without duplicating the bin→band map or the
aggregation. ``masking.py`` uses it for inter-stem masking; ``timbre.py`` uses
it for spectral flatness (which must be computed over band powers, not raw FFT
bins — raw bins crush the geometric mean to ~0 for any pitched material).

The grid is the standard Zwicker & Fastl critical-band table; bands are
half-open ``[edge[i], edge[i+1])``. A single ``(sample_rate, n_fft)`` produces
one :class:`BarkMap`; ``aggregate_to_bands`` then sums any STFT power matrix
into that map's bands.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

# Zwicker critical-band edges in Hz (Bark 1..24 lower edges + top). Standard
# table from Zwicker & Fastl; bands are [edge[i], edge[i+1]). The DSP needs
# critical-band resolution — coarser than attribution's 6 musical bands.
BARK_EDGES_HZ: tuple[float, ...] = (
    0.0, 100.0, 200.0, 300.0, 400.0, 510.0, 630.0, 770.0, 920.0, 1080.0,
    1270.0, 1480.0, 1720.0, 2000.0, 2320.0, 2700.0, 3150.0, 3700.0, 4400.0,
    5300.0, 6400.0, 7700.0, 9500.0, 12000.0, 15500.0,
)


@dataclass(frozen=True)
class BarkMap:
    """Precomputed FFT-bin → Bark-band assignment for one (sr, n_fft)."""
    n_bands: int
    bin_band: np.ndarray   # [n_bins] band index per FFT bin (-1 = out of range)
    edges_hz: np.ndarray   # [n_bands + 1] band edge frequencies


def bark_band_map(sample_rate: int, n_fft: int) -> BarkMap:
    nyq = sample_rate / 2.0
    edges = [e for e in BARK_EDGES_HZ if e < nyq]
    # Cap the top band at Nyquist only when Nyquist falls *inside* the Bark
    # range; when Nyquist is above the top edge (the 44.1/48 kHz case) the list
    # already ends at the top edge, so appending would create a zero-width band.
    if nyq < BARK_EDGES_HZ[-1]:
        edges.append(nyq)
    edges_arr = np.asarray(edges, dtype=np.float64)
    n_bands = len(edges_arr) - 1

    freqs = np.fft.rfftfreq(n_fft, d=1.0 / sample_rate)
    # Band index for each bin: edges[k] <= f < edges[k+1].
    idx = np.searchsorted(edges_arr, freqs, side="right") - 1
    idx[(freqs < edges_arr[0]) | (freqs >= edges_arr[-1])] = -1
    return BarkMap(n_bands=n_bands, bin_band=idx, edges_hz=edges_arr)


def aggregate_to_bands(power: np.ndarray, bark: BarkMap) -> np.ndarray:
    """Sum a ``[n_bins, n_frames]`` STFT power matrix into Bark bands →
    ``[n_bands, n_frames]``. Bins outside the Bark range (``bin_band == -1``)
    are dropped."""
    n_frames = power.shape[1]
    band_power = np.zeros((bark.n_bands, n_frames), dtype=np.float64)
    valid = bark.bin_band >= 0
    np.add.at(band_power, bark.bin_band[valid], power[valid])
    return band_power
