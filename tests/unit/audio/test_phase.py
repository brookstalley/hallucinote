"""Pairwise phase integrity — polarity, time offset and cancellation.

Every reading this lens produces has physical ground truth, so every assertion
here is against a number the fixture PUT THERE: a sign flip, an injected sample
delay, a delay chosen to null one band and pass another. Nothing in this file
asserts a musical judgement, because the module makes none — where a threshold
appears (the polarity bound) the test pins the fault it must catch and the
healthy material it must not accuse, in both directions.
"""
from __future__ import annotations

import numpy as np
import pytest

from hallucinote.audio.attribution import BANDS
from hallucinote.audio.phase import measure_phase_relations
from tests.unit.audio import fixtures

SR = fixtures.SAMPLE_RATE


def _band(relation, name: str) -> float:
    """The one band reading by name, so a test says which band it means."""
    matches = [b.sum_minus_parts_db for b in relation.band_cancellation if b.band == name]
    assert len(matches) == 1, f"expected exactly one {name!r} band, got {matches}"
    return matches[0]


def _only(relations):
    assert len(relations) == 1, f"expected one pair, got {len(relations)}"
    return relations[0]


# --- polarity -----------------------------------------------------------------

def test_polarity_flip_is_detected():
    """A sign-flipped copy is the one-bit fault this lens exists to name."""
    stem = fixtures.pink_noise(2.0)
    rel = _only(measure_phase_relations(
        [("bass", stem), ("bass_flipped", -stem)], sample_rate=SR
    ))
    assert rel.skipped is None
    assert rel.polarity_inverted is True
    assert rel.correlation == pytest.approx(-1.0, abs=1e-6)


def test_polarity_flip_annihilates_the_sum():
    """The flip's cost, not just its sign: every band's energy disappears."""
    stem = fixtures.pink_noise(2.0)
    rel = _only(measure_phase_relations(
        [("bass", stem), ("bass_flipped", -stem)], sample_rate=SR
    ))
    assert rel.broadband_cancellation_db < -100.0
    for band in rel.band_cancellation:
        assert band.sum_minus_parts_db < -100.0, band.band


def test_in_phase_pair_is_not_called_inverted():
    """The over-flagging direction: identical material must read healthy."""
    stem = fixtures.pink_noise(2.0)
    rel = _only(measure_phase_relations(
        [("a", stem), ("b", stem)], sample_rate=SR
    ))
    assert rel.polarity_inverted is False
    assert rel.correlation == pytest.approx(1.0, abs=1e-9)


def test_unrelated_parts_are_not_called_inverted():
    """Two different instruments correlate near zero, which is not a fault."""
    a = fixtures.pink_noise(2.0, rng=np.random.default_rng(11))
    b = fixtures.pink_noise(2.0, rng=np.random.default_rng(99))
    rel = _only(measure_phase_relations([("a", a), ("b", b)], sample_rate=SR))
    assert rel.polarity_inverted is False
    assert abs(rel.correlation) < 0.5


# --- time offset --------------------------------------------------------------

def test_injected_lag_is_recovered_exactly():
    """The uncompensated-plugin-delay case: 512 samples in, 512 samples out."""
    stem = fixtures.pink_noise(2.0)
    delayed = fixtures.delayed_copy(stem, delay_samples=512)
    rel = _only(measure_phase_relations(
        [("stem", stem), ("stem_via_plugin", delayed)], sample_rate=SR
    ))
    assert rel.lag_samples == 512
    assert rel.lag_ms == pytest.approx(512 / SR * 1000.0)


def test_aligned_pair_reads_zero_lag():
    """No offset injected → no offset reported, so a clean pair is clean."""
    stem = fixtures.pink_noise(2.0)
    rel = _only(measure_phase_relations(
        [("a", stem), ("b", stem)], sample_rate=SR
    ))
    assert rel.lag_samples == 0
    assert rel.lag_ms == pytest.approx(0.0)


def test_lag_search_is_bounded_by_max_lag_samples():
    """The bound is real: a delay outside it cannot be reported as inside it.

    An offset the caller has declared impossible must not come back as a
    confident measurement of that offset — the peak is searched only where a
    delay could physically be.
    """
    stem = fixtures.pink_noise(2.0)
    delayed = fixtures.delayed_copy(stem, delay_samples=4000)
    unbounded = _only(measure_phase_relations(
        [("a", stem), ("b", delayed)], sample_rate=SR, max_lag_samples=8000
    ))
    assert unbounded.lag_samples == 4000

    bounded = _only(measure_phase_relations(
        [("a", stem), ("b", delayed)], sample_rate=SR, max_lag_samples=100
    ))
    assert abs(bounded.lag_samples) <= 100


# --- cancellation -------------------------------------------------------------

def test_in_phase_pair_loses_no_level():
    """A coherent add is 0 dB by construction, broadband and in every band."""
    stem = fixtures.pink_noise(2.0)
    rel = _only(measure_phase_relations(
        [("a", stem), ("b", stem)], sample_rate=SR
    ))
    assert rel.broadband_cancellation_db == pytest.approx(0.0, abs=0.01)
    assert len(rel.band_cancellation) == len(BANDS)
    for band in rel.band_cancellation:
        assert band.sum_minus_parts_db == pytest.approx(0.0, abs=0.01), band.band


def test_comb_filter_cancellation_is_band_localised():
    """A delay of half a 50 Hz period nulls the sub and leaves 4 kHz untouched.

    480 samples at 48 kHz is half a cycle at 50 Hz — so the two 50 Hz
    components arrive in opposition and subtract — and exactly 40 whole cycles
    at 4 kHz, so those arrive in phase and add. One delayed copy summed with
    its source, which is what a comb filter IS, and the two components land in
    different bands: the reading has to be per band or it averages the fault
    away.
    """
    sub = fixtures.sine(50.0, 2.0, amplitude=0.4)
    top = fixtures.sine(4000.0, 2.0, amplitude=0.4)
    signal = (sub + top).astype(np.float32)
    combed = fixtures.delayed_copy(signal, delay_samples=480)

    rel = _only(measure_phase_relations(
        [("pad", signal), ("pad_combed", combed)], sample_rate=SR
    ))
    assert rel.skipped is None
    assert _band(rel, "sub_20_60") < -20.0
    assert _band(rel, "high_mid_2k_6k") == pytest.approx(0.0, abs=0.5)
    # The broadband number is the average of a band that vanished and a band
    # that survived, which is why it cannot be the only reading reported.
    assert rel.broadband_cancellation_db > _band(rel, "sub_20_60")


def test_uncorrelated_parts_read_near_minus_three_db():
    """Two unrelated parts sum in power, not coherently — the healthy reading.

    Pinning this is what keeps -3 dB from being read as a defect: it is what
    every pair of different instruments does, and the finding lives below it.
    """
    a = fixtures.pink_noise(2.0, rng=np.random.default_rng(11))
    b = fixtures.pink_noise(2.0, rng=np.random.default_rng(99))
    rel = _only(measure_phase_relations([("a", a), ("b", b)], sample_rate=SR))
    assert rel.broadband_cancellation_db == pytest.approx(-3.0, abs=0.7)


# --- skips --------------------------------------------------------------------

def test_silent_side_is_skipped_with_a_reason():
    """A stem with no signal gets a named skip, never a correlation on noise."""
    stem = fixtures.pink_noise(2.0)
    rel = _only(measure_phase_relations(
        [("bass", stem), ("muted_pad", fixtures.silence(2.0))], sample_rate=SR
    ))
    assert rel.skipped == "silent_b"
    assert np.isnan(rel.correlation)
    assert np.isnan(rel.broadband_cancellation_db)
    assert rel.band_cancellation == []
    assert rel.polarity_inverted is False


def test_silent_first_side_names_which_side():
    """The skip says WHICH surface was silent — the fix differs per side."""
    stem = fixtures.pink_noise(2.0)
    rel = _only(measure_phase_relations(
        [("muted_pad", fixtures.silence(2.0)), ("bass", stem)], sample_rate=SR
    ))
    assert rel.skipped == "silent_a"


def test_two_silent_sides_are_named_as_such():
    rel = _only(measure_phase_relations(
        [("a", fixtures.silence(2.0)), ("b", fixtures.silence(2.0))],
        sample_rate=SR,
    ))
    assert rel.skipped == "silent_both"


def test_empty_window_is_skipped():
    rel = _only(measure_phase_relations(
        [("a", fixtures.silence(0.0)), ("b", fixtures.silence(0.0))],
        sample_rate=SR,
    ))
    assert rel.skipped == "empty_window"


# --- pairing and shape --------------------------------------------------------

def test_every_unordered_pair_is_reported_once():
    """Three surfaces make three pairs, in input order, none dropped."""
    a = fixtures.pink_noise(1.0, rng=np.random.default_rng(1))
    b = fixtures.pink_noise(1.0, rng=np.random.default_rng(2))
    c = fixtures.pink_noise(1.0, rng=np.random.default_rng(3))
    relations = measure_phase_relations(
        [("a", a), ("b", b), ("c", c)], sample_rate=SR
    )
    assert [(r.track_id_a, r.track_id_b) for r in relations] == [
        ("a", "b"), ("a", "c"), ("b", "c")
    ]


def test_single_surface_has_no_pairs():
    assert measure_phase_relations(
        [("a", fixtures.pink_noise(1.0))], sample_rate=SR
    ) == []


def test_mono_input_is_rejected():
    """Guessing a channel layout would measure something nobody captured."""
    mono = fixtures.pink_noise(1.0)[:, 0]
    with pytest.raises(ValueError):
        measure_phase_relations(
            [("a", mono), ("b", fixtures.pink_noise(1.0))], sample_rate=SR
        )


def test_unequal_window_lengths_are_rejected():
    """Phase relates two signals at the same instants; different spans have no
    answer, so this is a caller bug rather than a silent edge case."""
    with pytest.raises(ValueError):
        measure_phase_relations(
            [("a", fixtures.pink_noise(1.0)), ("b", fixtures.pink_noise(2.0))],
            sample_rate=SR,
        )


def test_non_positive_sample_rate_is_rejected():
    stem = fixtures.pink_noise(1.0)
    with pytest.raises(ValueError):
        measure_phase_relations([("a", stem), ("b", stem)], sample_rate=0)


class TestLagCorrelationSeparatesDelayFromCoincidence:
    """A cross-correlation always peaks somewhere, so a lag alone proves nothing.

    A real render made this concrete: every uncorrelated stem pair in a finished
    song reported a confident-looking offset of tens of milliseconds at r ~ 0.
    That is two parts sharing a downbeat, not a device delay — and a consumer
    that acted on it would chase a latency bug that does not exist.
    """

    def test_a_genuine_delay_has_a_strong_lag_correlation(self) -> None:
        source = fixtures.pink_noise(1.0, rng=np.random.default_rng(7))
        delayed = fixtures.delayed_copy(source, delay_samples=240)
        [rel] = measure_phase_relations(
            [("dry", source), ("delayed", delayed)], sample_rate=SR
        )
        assert rel.lag_samples != 0
        assert rel.lag_correlation > 0.9

    def test_unrelated_parts_report_a_lag_nobody_should_believe(self) -> None:
        [rel] = measure_phase_relations(
            [
                ("a", fixtures.pink_noise(1.0, rng=np.random.default_rng(1))),
                ("b", fixtures.pink_noise(1.0, rng=np.random.default_rng(2))),
            ],
            sample_rate=SR,
        )
        # The lag itself is not asserted — it is whatever the argmax landed on,
        # which is the point. What must hold is that the confidence says so.
        assert rel.lag_correlation < 0.5

    def test_a_delay_on_an_inverted_pair_is_still_a_confident_lag(self) -> None:
        source = fixtures.pink_noise(1.0, rng=np.random.default_rng(11))
        flipped_late = (-fixtures.delayed_copy(source, delay_samples=180)).astype(
            source.dtype
        )
        [rel] = measure_phase_relations(
            [("dry", source), ("wet", flipped_late)], sample_rate=SR
        )
        assert rel.lag_correlation > 0.9
