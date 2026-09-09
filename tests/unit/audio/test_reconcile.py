"""Stem-sum vs master reconciliation — behavioural contract.

The lens exists to answer one question the rest of the report cannot ask: does
the set of surfaces we analysed actually account for the master? These tests
build masters out of known stems, then break the relationship one way at a time
— a level trim, a band-limited change, a latency, an unrouted stem — and pin
that each break lands in ITS OWN field. That separation is the whole design: a
reader has to be able to tell "everything is 2 dB quiet" from "one part is
missing" without a threshold telling them which is worse.
"""
from __future__ import annotations

import numpy as np
import pytest

from hallucinote.audio.attribution import BANDS
from hallucinote.audio.reconcile import reconcile_stem_sum
from tests.unit.audio import fixtures

SR = fixtures.SAMPLE_RATE

# A faithful float32 sum cancels to arithmetic noise, far below anything a
# capture could represent; anything above this is a real discrepancy.
FAITHFUL_RESIDUAL_DB = -60.0


def _three_stems() -> list[tuple[str, np.ndarray]]:
    """Three spectrally distinct parts, so a band split can separate them."""
    return [
        ("kick", fixtures.concat(
            fixtures.kick_onset(duration_s=0.5),
            fixtures.silence(0.5),
            fixtures.kick_onset(duration_s=0.5),
            fixtures.silence(0.5),
        )),
        ("bass", fixtures.sine(80.0, 2.0, amplitude=0.4)),
        ("lead", fixtures.sine(1200.0, 2.0, amplitude=0.25)),
    ]


def _sum_of(stems, exclude: str | None = None) -> np.ndarray:
    total = np.zeros_like(stems[0][1])
    for track_id, audio in stems:
        if track_id == exclude:
            continue
        total = total + audio
    return total.astype(np.float32)


def _band_map(result) -> dict[str, float]:
    return {b.band: b.residual_db for b in result.band_residuals}


# --------------------------------------------------------------------------- #
# The faithful case
# --------------------------------------------------------------------------- #

def test_exact_sum_reconciles_to_a_near_zero_residual():
    """A master built as the literal sum of its stems has nothing unaccounted
    for: no residual, no lag, no gain offset, no offender."""
    stems = _three_stems()
    master = _sum_of(stems)

    result = reconcile_stem_sum(stems, master, sample_rate=SR)

    assert result.skipped is None
    assert result.residual_db < FAITHFUL_RESIDUAL_DB
    assert result.correlation > 0.999
    assert result.best_lag_samples == 0
    assert result.gain_offset_db == pytest.approx(0.0, abs=0.01)
    assert result.worst_offender is None


def test_faithful_sum_is_faithful_in_every_band():
    """Every band the master carries energy in reconciles too — a broadband
    number alone could hide a band that cancels against another."""
    stems = _three_stems()
    master = _sum_of(stems)

    result = reconcile_stem_sum(stems, master, sample_rate=SR)

    measured = [
        db for db in _band_map(result).values() if not np.isnan(db)
    ]
    assert measured, "the fixture must energize at least one band"
    assert all(db < FAITHFUL_RESIDUAL_DB for db in measured)


def test_supplied_gains_are_LINEAR_and_applied_as_given():
    """``stem_gains`` carries LINEAR gains, already off Live's calibrated curve.

    The unit matters more than it looks: the handler that reads ``tracks.volume``
    converts once, and every other consumer in this package takes the converted
    value. Converting a second time here would mis-level a unity fader by +6 dB
    and a -14 dB fader by -20 dB, and would do it while ``gains_assumed_unity``
    reported ``False`` — the report asserting that levels were modelled while
    they were wrong. This test passes the gains a real caller passes.
    """
    stems = _three_stems()
    minus_four_db = 10.0 ** (-4.0 / 20.0)
    gains = {"kick": 1.0, "bass": minus_four_db, "lead": minus_four_db}
    scaled = [
        (track_id, (audio * gains[track_id]).astype(np.float32))
        for track_id, audio in stems
    ]
    master = _sum_of(scaled)

    result = reconcile_stem_sum(stems, master, sample_rate=SR, stem_gains=gains)

    assert result.residual_db < FAITHFUL_RESIDUAL_DB
    assert result.gains_assumed_unity is False


def test_absent_gains_are_reported_not_guessed():
    """No gain map means the sum is of raw captures, and the result says so
    rather than letting a reader assume mix levels were reconstructed."""
    stems = _three_stems()
    master = _sum_of(stems)

    assert reconcile_stem_sum(
        stems, master, sample_rate=SR
    ).gains_assumed_unity is True
    assert reconcile_stem_sum(
        stems, master, sample_rate=SR, stem_gains={}
    ).gains_assumed_unity is True
    assert reconcile_stem_sum(
        stems, master, sample_rate=SR, stem_gains={"kick": 0.85}
    ).gains_assumed_unity is False


# --------------------------------------------------------------------------- #
# One stem the master does not contain
# --------------------------------------------------------------------------- #

def test_unrouted_stem_raises_the_residual_and_is_named():
    """A stem we were handed that never reached the master: the residual rises
    and leave-one-out points at the track responsible."""
    stems = _three_stems()
    master = _sum_of(stems, exclude="lead")

    result = reconcile_stem_sum(stems, master, sample_rate=SR)

    assert result.skipped is None
    assert result.residual_db > FAITHFUL_RESIDUAL_DB
    assert result.worst_offender == "lead"


def test_removing_the_named_offender_restores_the_reconciliation():
    """The offender is named for the content it contributes, not for noise —
    dropping it from the sum makes the capture add up again."""
    stems = _three_stems()
    master = _sum_of(stems, exclude="lead")

    named = reconcile_stem_sum(stems, master, sample_rate=SR).worst_offender
    without = reconcile_stem_sum(
        [(t, a) for t, a in stems if t != named], master, sample_rate=SR
    )

    assert without.residual_db < FAITHFUL_RESIDUAL_DB
    assert without.worst_offender is None


def test_uncaptured_surface_raises_the_residual_and_names_nobody():
    """The failure only this lens can see: the master contains material no stem
    we hold accounts for. High residual, no offender — leave-one-out can only
    name a stem it was given, and that asymmetry is the signature."""
    stems = _three_stems()
    never_captured = fixtures.sine(3000.0, 2.0, amplitude=0.4)
    master = (_sum_of(stems) + never_captured).astype(np.float32)

    result = reconcile_stem_sum(stems, master, sample_rate=SR)

    assert result.residual_db > FAITHFUL_RESIDUAL_DB
    assert result.worst_offender is None


# --------------------------------------------------------------------------- #
# A flat gain is not a missing part
# --------------------------------------------------------------------------- #

def test_flat_master_gain_lands_in_gain_offset_not_in_the_residual():
    """A trim on the master is a level fact, and the post-match residual must
    stay low so it never reads as unaccounted-for content."""
    stems = _three_stems()
    trim_db = -2.0
    master = (_sum_of(stems) * 10.0 ** (trim_db / 20.0)).astype(np.float32)

    result = reconcile_stem_sum(stems, master, sample_rate=SR)

    assert result.gain_offset_db == pytest.approx(trim_db, abs=0.05)
    assert result.residual_db < FAITHFUL_RESIDUAL_DB
    assert result.worst_offender is None


def test_a_boosted_master_reads_as_a_positive_offset():
    """Sign convention: positive means the master is hotter than the stem sum."""
    stems = _three_stems()
    master = (_sum_of(stems) * 10.0 ** (3.0 / 20.0)).astype(np.float32)

    result = reconcile_stem_sum(stems, master, sample_rate=SR)

    assert result.gain_offset_db == pytest.approx(3.0, abs=0.05)


# --------------------------------------------------------------------------- #
# A band-limited discrepancy
# --------------------------------------------------------------------------- #

def test_band_limited_change_shows_in_that_band():
    """A master whose sub arrived 20 dB down localizes to the sub band.

    The band split's job is to say WHERE the sum and the master disagree, so
    the contract is that the affected band stands far above its neighbours —
    not that the neighbours read zero. The broadband gain match is common to
    every band, so a discrepancy big enough to move it lifts them all a little
    (see the module doc); the separation is what carries the finding.
    """
    stems = [
        ("sub_part", fixtures.sine(40.0, 2.0, amplitude=0.2)),
        ("mid_part", fixtures.sine(900.0, 2.0, amplitude=0.6)),
        ("high_part", fixtures.sine(4000.0, 2.0, amplitude=0.4)),
    ]
    quiet_sub = (stems[0][1] * 0.1).astype(np.float32)
    master = (quiet_sub + stems[1][1] + stems[2][1]).astype(np.float32)

    bands = _band_map(reconcile_stem_sum(stems, master, sample_rate=SR))

    others = [
        db for name, db in bands.items()
        if name != "sub_20_60" and not np.isnan(db)
    ]
    assert bands["sub_20_60"] > 0.0, "the sub band's residual exceeds its content"
    assert bands["sub_20_60"] > max(others) + 20.0


def test_a_band_limited_change_does_not_read_as_a_broadband_one():
    """The same fixture from the other side: a band-limited fault must not be
    mistaken for a level trim, and must not name an innocent stem."""
    stems = [
        ("sub_part", fixtures.sine(40.0, 2.0, amplitude=0.2)),
        ("mid_part", fixtures.sine(900.0, 2.0, amplitude=0.6)),
        ("high_part", fixtures.sine(4000.0, 2.0, amplitude=0.4)),
    ]
    quiet_sub = (stems[0][1] * 0.1).astype(np.float32)
    master = (quiet_sub + stems[1][1] + stems[2][1]).astype(np.float32)

    result = reconcile_stem_sum(stems, master, sample_rate=SR)

    assert result.residual_db > FAITHFUL_RESIDUAL_DB
    assert abs(result.gain_offset_db) < 1.0, "not a flat trim"


def test_band_the_master_has_no_energy_in_is_unmeasured_not_zero():
    """A band with nothing in it reports NaN — honestly unmeasured — rather
    than a ratio of two near-zero numbers dressed up as a finding."""
    stems = [("bass", fixtures.sine(80.0, 2.0, amplitude=0.5))]
    master = _sum_of(stems)

    bands = _band_map(reconcile_stem_sum(stems, master, sample_rate=SR))

    assert set(bands) == {name for name, _, _ in BANDS}
    assert np.isnan(bands["air_6k_plus"])
    assert not np.isnan(bands["low_60_200"])


# --------------------------------------------------------------------------- #
# Latency
# --------------------------------------------------------------------------- #

def test_injected_lag_is_recovered_and_compensated():
    """A master-chain lookahead delays the master against the stems. The offset
    is surfaced, and the residual is measured after compensating for it so a
    latency never masquerades as missing content."""
    stems = _three_stems()
    master = fixtures.delayed_copy(_sum_of(stems), delay_samples=512)

    result = reconcile_stem_sum(stems, master, sample_rate=SR)

    assert result.best_lag_samples == 512
    assert result.residual_db < FAITHFUL_RESIDUAL_DB


def test_a_master_leading_the_stems_reads_as_a_negative_lag():
    """The sign is unambiguous in both directions — a master that arrives early
    is a different fault from one that arrives late."""
    stems = _three_stems()
    master = fixtures.delayed_copy(_sum_of(stems), delay_samples=-256)

    assert reconcile_stem_sum(
        stems, master, sample_rate=SR
    ).best_lag_samples == -256


# --------------------------------------------------------------------------- #
# Nonlinearity is evidence, not an error
# --------------------------------------------------------------------------- #

def test_a_nonlinear_master_chain_leaves_a_residual_and_no_offender():
    """A clipper on the master produces a residual no linear sum can cancel.
    The lens reports it — that is a true fact about the render — and names no
    stem, because no exclusion improves the fit."""
    stems = _three_stems()
    master = np.clip(_sum_of(stems), -0.3, 0.3).astype(np.float32)

    result = reconcile_stem_sum(stems, master, sample_rate=SR)

    assert result.skipped is None
    assert result.residual_db > FAITHFUL_RESIDUAL_DB
    assert result.correlation > 0.9, "the shape still tracks; the peaks do not"
    assert result.worst_offender is None


def test_a_polarity_inverted_sum_reads_as_negative_correlation():
    """Correlation carries polarity; the flat-gain fit does not, so it declines
    to report a negative gain as a dB number."""
    stems = _three_stems()
    master = (-_sum_of(stems)).astype(np.float32)

    result = reconcile_stem_sum(stems, master, sample_rate=SR)

    assert result.correlation < -0.99
    assert np.isnan(result.gain_offset_db)


# --------------------------------------------------------------------------- #
# Honest skips
# --------------------------------------------------------------------------- #

def test_empty_stem_list_is_skipped_with_a_reason():
    """No stems means no reconciliation — a structured reason, never a silent
    zero that reads as a clean render."""
    result = reconcile_stem_sum([], fixtures.sine(440.0, 1.0), sample_rate=SR)

    assert result.skipped is not None
    assert result.skipped.startswith("no_stems")
    assert np.isnan(result.residual_db)
    assert np.isnan(result.correlation)
    assert result.band_residuals == []
    assert result.worst_offender is None


def test_silent_master_is_skipped_with_a_reason():
    """Nothing to reconcile against, and a relative residual is undefined."""
    stems = _three_stems()

    result = reconcile_stem_sum(stems, fixtures.silence(2.0), sample_rate=SR)

    assert result.skipped is not None
    assert result.skipped.startswith("silent_master")


def test_silent_stem_sum_is_skipped_with_a_reason():
    """Every stem summed to silence while the master carries content — the
    strongest form of "we never saw this", and it must not divide by zero."""
    stems = [("a", fixtures.silence(2.0)), ("b", fixtures.silence(2.0))]

    result = reconcile_stem_sum(
        stems, fixtures.sine(440.0, 2.0), sample_rate=SR
    )

    assert result.skipped is not None
    assert result.skipped.startswith("silent_stem_sum")


def test_zero_length_audio_is_skipped_with_a_reason():
    stems = [("a", fixtures.silence(0.0))]

    result = reconcile_stem_sum(stems, fixtures.silence(0.0), sample_rate=SR)

    assert result.skipped is not None
    assert result.skipped.startswith("empty_audio")


def test_invalid_sample_rate_is_skipped_with_a_reason():
    stems = _three_stems()

    result = reconcile_stem_sum(stems, _sum_of(stems), sample_rate=0)

    assert result.skipped is not None
    assert result.skipped.startswith("invalid_sample_rate")


# --------------------------------------------------------------------------- #
# Shape invariants
# --------------------------------------------------------------------------- #

def test_unequal_surface_lengths_compare_over_the_common_samples():
    """The real capture path trims to a common length; a caller that hasn't
    must still get a reading rather than a broadcast error."""
    stems = _three_stems()
    master = _sum_of(stems)[: -SR // 2]

    result = reconcile_stem_sum(stems, master, sample_rate=SR)

    assert result.skipped is None
    assert result.residual_db < FAITHFUL_RESIDUAL_DB


def test_mono_surfaces_are_accepted():
    """Mono (n,) input is as valid as stereo (n, 2) — the lens mono-sums either
    way, because the pre-fader stems carry no pan to preserve."""
    stems = [("bass", fixtures.sine(80.0, 1.0, amplitude=0.5)[:, 0])]
    master = stems[0][1]

    result = reconcile_stem_sum(stems, master, sample_rate=SR)

    assert result.skipped is None
    assert result.residual_db < FAITHFUL_RESIDUAL_DB


def test_a_single_stem_names_no_offender():
    """Leave-one-out needs something to leave out; with one stem it declines
    rather than naming the only candidate by default."""
    stems = [("bass", fixtures.sine(80.0, 1.0, amplitude=0.5))]
    master = fixtures.sine(3000.0, 1.0, amplitude=0.5)

    result = reconcile_stem_sum(stems, master, sample_rate=SR)

    assert result.residual_db > FAITHFUL_RESIDUAL_DB
    assert result.worst_offender is None
