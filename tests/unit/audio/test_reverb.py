"""Reverb RT60 verification — per-return decay-tail measurement (AUD-6R2M).

RT60 is measured per RETURN from its own captured ring-out via Schroeder
backward energy integration, dry-source-free. These pin:

  - a known-RT60 ring-out is recovered within tolerance (the calibration);
  - the recovered RT60 is INVARIANT to how many / which dry sources fed the
    return — the property the old single-dry deconvolution catastrophically
    failed (it returned 252–370 s on a real 5–6-send return);
  - a capture with no usable ring-out yields an honest ``sufficient_tail=False``
    / NaN skip, never a fabricated number;
  - ``find_decay_onset`` locates the decay start after the last excitation.
"""
from __future__ import annotations

import numpy as np

from hallucinote.audio.reverb import (
    REVERB_REL_TOLERANCE,
    REVERB_TOLERANCE_FLOOR_S,
    find_decay_onset,
    measure_return_rt60,
    reverb_tolerance_s,
)

from .fixtures import (
    SAMPLE_RATE,
    convolve,
    kick_onset,
    pink_noise,
    silence,
    sine,
    synthetic_ir,
)


def _ring_out(
    rt60_s: float,
    *,
    sources: list,
    input_s: float = 2.0,
    total_s: float = 5.0,
) -> np.ndarray:
    """A return ring-out: ``sources`` (summed dry inputs) play over
    ``[0, input_s]`` then stop; convolved with a known-RT60 IR, the return
    decays into silence over ``[input_s, total_s]``. The decay region's slope
    is the IR's — independent of the source content (the physics the
    source-invariance test exercises)."""
    ir = synthetic_ir(rt60_s, duration_s=total_s)
    tot_n = int(round(total_s * SAMPLE_RATE))
    in_n = int(round(input_s * SAMPLE_RATE))
    dry = np.zeros((tot_n, 2), dtype=np.float32)
    for src in sources:
        seg = src[:in_n]
        dry[: seg.shape[0]] += seg
    return convolve(dry, ir)


def _measure(ring: np.ndarray, *, declared: float, input_s: float = 2.0):
    onset = find_decay_onset(
        ring,
        search_start_sample=int(round(input_s * SAMPLE_RATE)),
        sample_rate=SAMPLE_RATE,
    )
    return measure_return_rt60(
        ring,
        sample_rate=SAMPLE_RATE,
        decay_onset_sample=onset,
        declared_rt60_s=declared,
        return_track_id="return:1",
    )


def test_recovers_known_rt60_from_ringout():
    """Calibration: a known-RT60 ring-out is recovered within tolerance."""
    rt60 = 1.2
    ring = _ring_out(rt60, sources=[sine(220.0, 2.0)], total_s=5.0)
    r = _measure(ring, declared=rt60)
    assert r.sufficient_tail
    assert r.measurement_method == "decay_tail"
    assert abs(r.measured_rt60_s - rt60) <= REVERB_TOLERANCE_FLOOR_S, (
        f"declared={rt60} measured={r.measured_rt60_s}"
    )
    assert r.within_tolerance is True


def test_rt60_invariant_to_number_of_sources():
    """The property the old single-dry deconvolution FAILED. A return fed by one
    source and one fed by five recover the SAME RT60, because we measure the
    return's own decay rather than deconvolving by a single dry stem."""
    rt60 = 1.0
    one = _ring_out(rt60, sources=[sine(330.0, 2.0)])
    five = _ring_out(rt60, sources=[
        sine(330.0, 2.0), sine(110.0, 2.0), pink_noise(2.0),
        kick_onset(), sine(550.0, 2.0),
    ])
    r1 = _measure(one, declared=rt60)
    r5 = _measure(five, declared=rt60)
    assert r1.sufficient_tail and r5.sufficient_tail
    assert abs(r1.measured_rt60_s - rt60) <= REVERB_TOLERANCE_FLOOR_S
    assert abs(r5.measured_rt60_s - rt60) <= REVERB_TOLERANCE_FLOOR_S
    # Source-count invariance: the two agree despite totally different inputs.
    assert abs(r1.measured_rt60_s - r5.measured_rt60_s) <= REVERB_TOLERANCE_FLOOR_S


def test_no_decay_continuous_signal_is_honest_insufficient_tail():
    """A return that never decays (continuous content to the last sample — the
    real sun-zone-done capture) yields an honest skip, not a fabricated RT60.
    This is the AUD-6R2M correctness floor: no garbage 252–370 s value."""
    ring = pink_noise(2.0, amplitude=0.5)  # stationary — no ring-out
    r = measure_return_rt60(
        ring, sample_rate=SAMPLE_RATE, decay_onset_sample=0,
        declared_rt60_s=1.0, return_track_id="return:1",
    )
    assert r.sufficient_tail is False
    assert np.isnan(r.measured_rt60_s)
    assert r.within_tolerance is False
    assert r.tail_span_db < 20.0  # below the clean-decay-span gate


def test_short_tail_is_insufficient():
    """A decay region shorter than a real ring-out → insufficient, no
    extrapolation from a sliver."""
    ring = synthetic_ir(0.8, duration_s=2.0)
    onset = ring.shape[0] - int(round(0.1 * SAMPLE_RATE))  # < _MIN_TAIL_S left
    r = measure_return_rt60(
        ring, sample_rate=SAMPLE_RATE, decay_onset_sample=onset,
        declared_rt60_s=0.8, return_track_id="return:1",
    )
    assert r.sufficient_tail is False
    assert np.isnan(r.measured_rt60_s)


def test_out_of_tolerance_when_actual_differs_from_declared():
    """A 2.0 s ring-out declared as 0.5 s → measured outside tolerance."""
    ring = _ring_out(2.0, sources=[sine(220.0, 2.0)], total_s=6.0)
    r = _measure(ring, declared=0.5)
    assert r.sufficient_tail
    assert r.within_tolerance is False
    assert r.measured_rt60_s > 0.5 + REVERB_TOLERANCE_FLOOR_S


def test_find_decay_onset_locates_last_excitation():
    """Onset lands near the end of input (the last excitation), not at the
    start — so the release/buildup is kept out of the decay fit."""
    ring = _ring_out(1.0, sources=[sine(220.0, 2.0)], input_s=2.0, total_s=5.0)
    onset = find_decay_onset(
        ring, search_start_sample=int(round(1.9 * SAMPLE_RATE)),
        sample_rate=SAMPLE_RATE,
    )
    assert int(round(1.9 * SAMPLE_RATE)) <= onset <= int(round(2.6 * SAMPLE_RATE))


def test_find_decay_onset_returns_n_when_search_starts_at_end():
    """No region to search → returns n (the no-ring-out case)."""
    ring = silence(1.0)
    n = ring.shape[0]
    assert find_decay_onset(ring, search_start_sample=n, sample_rate=SAMPLE_RATE) == n


def test_reverb_tolerance_s_is_relative_with_floor():
    """AUD-3T6L: the verdict band scales with declared RT60 but never drops
    below the absolute floor."""
    # Long RT60s get a proportional band (the device-nonlinearity error scales).
    assert reverb_tolerance_s(3.0) == REVERB_REL_TOLERANCE * 3.0  # 0.60
    assert reverb_tolerance_s(2.0) == REVERB_REL_TOLERANCE * 2.0  # 0.40
    # Short RT60s clamp to the floor (0.20 × 0.5 = 0.10 < 0.15).
    assert reverb_tolerance_s(0.5) == REVERB_TOLERANCE_FLOOR_S
    # Boundary: floor and relative meet at declared = floor / rel = 0.75 s.
    boundary = REVERB_TOLERANCE_FLOOR_S / REVERB_REL_TOLERANCE
    assert reverb_tolerance_s(boundary) == REVERB_TOLERANCE_FLOOR_S


def test_clean_long_decay_passes_relative_band_not_old_absolute():
    """AUD-3T6L regression: a clean long-decay capture whose realized RT60
    diverges from declared intent by MORE than the old fixed ±0.15 s absolute
    floor — but within the relative band — no longer reads as out-of-tolerance.
    (The sun-zone A-Plate 3.37-vs-3.0 false positive.) FAILS under pre-AUD-3T6L.

    Robust to the measurement under-reading long RT60s: we declare intent at a
    fixed FRACTION below the *actual* measured value, so the realized gap is
    ``0.15 × measured`` — always past the 0.15 s floor (measured > 1 s) yet
    inside the relative band, independent of the exact measurement."""
    ring = _ring_out(3.4, sources=[sine(180.0, 2.0)], input_s=2.0, total_s=12.0)
    onset = find_decay_onset(
        ring, search_start_sample=int(round(2.0 * SAMPLE_RATE)),
        sample_rate=SAMPLE_RATE,
    )
    measured = measure_return_rt60(
        ring, sample_rate=SAMPLE_RATE, decay_onset_sample=onset,
        declared_rt60_s=1.0, return_track_id="return:1",
    ).measured_rt60_s
    assert measured > 1.0  # a long-decay capture → a > floor realized gap below

    # Declare intent 15% under the realized RT60 — a divergence past the old
    # absolute ±0.15 s floor (measured > 1 s) but within the relative band.
    declared = measured * 0.85
    r = measure_return_rt60(
        ring, sample_rate=SAMPLE_RATE, decay_onset_sample=onset,
        declared_rt60_s=declared, return_track_id="return:1",
    )
    gap = abs(r.measured_rt60_s - declared)
    assert gap > REVERB_TOLERANCE_FLOOR_S          # old absolute band would WARN
    assert gap <= reverb_tolerance_s(declared)     # new relative band accepts
    assert r.within_tolerance is True
