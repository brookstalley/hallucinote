"""Synthetic corpus for the masking analyzer — the corpus IS the spec.

There is no labelled inter-stem masking ground truth for real music, so
correctness is *defined* by constructed fixtures (per masking-analyzer-spec.md
§7): a loud stem co-timed with a quiet one in the same band must read high; no
frequency or time overlap must read ~0; the bed mode must catch buildup pairwise
misses. Constants are calibrated here.
"""
from __future__ import annotations

import time

import numpy as np
import pytest

from hallucinote.audio.masking import analyze_masking_window
from tests.unit.audio.fixtures import SAMPLE_RATE, concat, silence, sine

SR = SAMPLE_RATE
DUR = 2.0  # seconds; plenty of STFT frames at 2048/512


def _frac_for(result, masker, maskee):
    for p in result.pairs:
        if p.masker_track_id == masker and p.maskee_track_id == maskee:
            return p.masked_fraction
    return 0.0


def _bed_frac(result, maskee):
    for b in result.bed:
        if b.maskee_track_id == maskee:
            return b.masked_fraction
    return 0.0


def test_clear_mask_same_band_reads_high():
    # A loud, B quiet, same Bark band (~2000-2320 Hz), co-timed → A masks B.
    a = sine(2000.0, DUR, amplitude=0.8)
    b = sine(2100.0, DUR, amplitude=0.01)
    result = analyze_masking_window([("A", a), ("B", b)], SR)
    assert _frac_for(result, "A", "B") > 0.8
    # The dominant direction is A→B, so B→A is not separately reported.
    assert _frac_for(result, "B", "A") == 0.0
    # And it localizes to the presence region.
    pair = result.pairs[0]
    assert pair.masker_track_id == "A" and pair.maskee_track_id == "B"
    assert pair.dominant_region_hz[0] <= 2100.0 < pair.dominant_region_hz[1]
    assert "presence" in pair.dominant_band


def test_no_frequency_overlap_reads_low():
    a = sine(80.0, DUR, amplitude=0.8)      # lows
    b = sine(11000.0, DUR, amplitude=0.5)   # air, ~22 Bark bands away
    result = analyze_masking_window([("A", a), ("B", b)], SR)
    assert _frac_for(result, "A", "B") < 0.05
    assert _frac_for(result, "B", "A") < 0.05


def test_no_time_overlap_reads_low():
    half = DUR / 2.0
    a = concat(sine(2000.0, half, amplitude=0.8), silence(half))
    b = concat(silence(half), sine(2100.0, half, amplitude=0.5))
    result = analyze_masking_window([("A", a), ("B", b)], SR)
    # They never sound together, so neither masks the other.
    assert _frac_for(result, "A", "B") < 0.1
    assert _frac_for(result, "B", "A") < 0.1


def test_partial_overlap_reads_mid():
    half = DUR / 2.0
    # A (loud) present only in the first half; B (quiet, same band) throughout.
    a = concat(sine(2000.0, half, amplitude=0.8), silence(half))
    b = sine(2100.0, DUR, amplitude=0.01)
    result = analyze_masking_window([("A", a), ("B", b)], SR)
    frac = _frac_for(result, "A", "B")
    assert 0.2 < frac < 0.8


def test_identical_copies_do_not_mask():
    # Two identical parts neither buries the other (neither is offset-dB below).
    a = sine(2000.0, DUR, amplitude=0.5)
    result = analyze_masking_window([("A", a), ("B", a.copy())], SR)
    assert _frac_for(result, "A", "B") < 0.05
    assert _frac_for(result, "B", "A") < 0.05


def test_silent_stem_excluded_no_div_by_zero():
    a = sine(2000.0, DUR, amplitude=0.5)
    b = silence(DUR)
    # Only one energized stem → no pairs, no crash.
    result = analyze_masking_window([("A", a), ("B", b)], SR)
    assert result.pairs == []
    assert result.bed == []


def test_too_short_segment_yields_empty():
    short = sine(2000.0, 0.005, amplitude=0.5)  # < n_fft samples
    result = analyze_masking_window([("A", short), ("B", short.copy())], SR)
    assert result.pairs == []


def test_determinism():
    a = sine(2000.0, DUR, amplitude=0.8)
    b = sine(2100.0, DUR, amplitude=0.02)
    r1 = analyze_masking_window([("A", a), ("B", b)], SR)
    r2 = analyze_masking_window([("A", a), ("B", b)], SR)
    assert _frac_for(r1, "A", "B") == _frac_for(r2, "A", "B")
    assert [p.masked_fraction for p in r1.pairs] == [
        p.masked_fraction for p in r2.pairs
    ]


def test_bed_catches_distributed_buildup_pairwise_misses():
    # B is a quiet wideband part. Each single bandlimited bed stem only covers
    # part of B's range, so no single pair fully masks it — but together they
    # blanket it. The bed mode must read higher than any single pair.
    n = int(DUR * SR)
    t = np.arange(n) / SR
    # B: quiet sum of tones spanning body+presence.
    b_mono = 0.01 * sum(np.sin(2 * np.pi * f * t) for f in (700, 1500, 2500, 3500))
    b = np.stack([b_mono, b_mono], axis=1).astype(np.float32)
    beds = []
    for i, f in enumerate((700.0, 1500.0, 2500.0, 3500.0)):
        s = sine(f, DUR, amplitude=0.6)
        beds.append((f"bed{i}", s))
    stems = [("B", b), *beds]
    result = analyze_masking_window(stems, SR)
    bed_frac = _bed_frac(result, "B")
    worst_pair_on_b = max(
        (_frac_for(result, m, "B") for m, _ in beds), default=0.0
    )
    assert bed_frac > worst_pair_on_b
    assert bed_frac > 0.6


@pytest.mark.parametrize("amp", [0.02, 0.2])
def test_louder_masker_is_monotone(amp):
    # Property: a louder masker never DECREASES the maskee's masked fraction.
    b = sine(2100.0, DUR, amplitude=0.01)
    quiet = analyze_masking_window(
        [("A", sine(2000.0, DUR, amplitude=0.05)), ("B", b)], SR
    )
    louder = analyze_masking_window(
        [("A", sine(2000.0, DUR, amplitude=amp)), ("B", b)], SR
    )
    assert _frac_for(louder, "A", "B") >= _frac_for(quiet, "A", "B") - 1e-9


def test_fraction_in_unit_interval():
    a = sine(2000.0, DUR, amplitude=0.8)
    b = sine(2100.0, DUR, amplitude=0.02)
    result = analyze_masking_window([("A", a), ("B", b)], SR)
    for p in result.pairs:
        assert 0.0 <= p.masked_fraction <= 1.0
    for bd in result.bed:
        assert 0.0 <= bd.masked_fraction <= 1.0


def test_perf_twelve_stems_within_budget():
    np.random.default_rng(1)
    stems = []
    for i in range(12):
        f = 100.0 * (i + 1)
        stems.append((f"s{i}", sine(f, DUR, amplitude=0.3)))
    start = time.perf_counter()
    result = analyze_masking_window(stems, SR)
    elapsed = time.perf_counter() - start
    # One 2s window of 12 stems must be well under a second.
    assert elapsed < 2.0
    assert len(result.pairs) <= 5  # top_n
