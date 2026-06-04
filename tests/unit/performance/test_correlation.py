"""P2 — the structured-vs-white discriminator (the human/sloppy split).

Two layers of test, matching the calibration finding:
  * the metric functions on GENUINE pink (1/f) vs white vs flat vs brown series
    (lag-1 acf is the robust primary; DFA α is the long-series-only readout), and
  * the lens classification end-to-end — onsets carrying a pink deviation read
    ``human``, white reads ``sloppy``, on-grid reads ``mechanical``.

Pink is generated with the Voss-McCartney algorithm (pure stdlib), seeded for
determinism. Invariants (boundedness, the None conditions) are property-tested
with Hypothesis.
"""
from __future__ import annotations

import math
import random

from hypothesis import given, settings, strategies as st

from hallucinote.performance import SectionPerf, analyze_performance, pink_noise
from hallucinote.performance.correlation import (
    DFA_MIN_POINTS,
    STRUCTURED_ACF_MIN,
    dfa_alpha,
    lag1_autocorr,
)

# The Voss-McCartney pink (1/f) generator now lives in production
# (performance.realization.pink_noise) — it IS the series the authoring layer
# emits. Measuring the real generator here keeps the calibration constants
# (STRUCTURED_ACF_MIN etc.) honest: they describe what apply_profile actually
# produces, not a test-only twin that could silently drift.
_voss_pink = pink_noise


def _white(n, *, seed):
    rng = random.Random(seed)
    return [rng.gauss(0, 1) for _ in range(n)]


# ---------------------------------------------------------------------------
# lag-1 autocorrelation — the robust primary discriminator
# ---------------------------------------------------------------------------


def test_white_noise_reads_uncorrelated():
    # Averaged over seeds so the assertion is about the process, not one draw.
    accs = [lag1_autocorr(_white(64, seed=s)) for s in range(20)]
    assert sum(accs) / len(accs) < STRUCTURED_ACF_MIN


def test_pink_noise_reads_correlated():
    accs = [lag1_autocorr(_voss_pink(64, seed=s)) for s in range(20)]
    assert sum(accs) / len(accs) >= STRUCTURED_ACF_MIN


def test_lag1_separates_pink_from_white_even_on_short_series():
    # The whole reason lag-1 acf is primary: it works where DFA does not (N=16).
    white = sum(lag1_autocorr(_white(16, seed=s)) for s in range(20)) / 20
    pink = sum(lag1_autocorr(_voss_pink(16, seed=s)) for s in range(20)) / 20
    assert white < STRUCTURED_ACF_MIN <= pink


def test_lag1_is_none_for_too_short_or_constant_series():
    assert lag1_autocorr([1.0, 2.0]) is None          # < 3 points
    assert lag1_autocorr([0.3, 0.3, 0.3, 0.3]) is None  # zero variance


# ---------------------------------------------------------------------------
# DFA α — the long-series-only 1/f exponent
# ---------------------------------------------------------------------------


def test_dfa_is_none_below_the_trust_threshold():
    assert dfa_alpha(_white(DFA_MIN_POINTS - 1, seed=1)) is None


def test_dfa_alpha_orders_white_below_pink_on_long_series():
    # On a long series DFA is reliable: white ~0.5, pink ~1.0. Assert the
    # ORDERING (white clearly below pink) rather than brittle absolute bands.
    white = sum(dfa_alpha(_white(256, seed=s)) for s in range(12)) / 12
    pink = sum(dfa_alpha(_voss_pink(256, seed=s)) for s in range(12)) / 12
    assert white < 0.7 < pink


# ---------------------------------------------------------------------------
# Lens classification end-to-end — structure drives human vs sloppy
# ---------------------------------------------------------------------------


def _notes_from_deviations(devs):
    """Onsets on the 0.5-beat grid, each nudged by a (small) deviation so the
    grid-deviation the lens recovers IS that deviation. Scaled to sit clear of
    the mechanical floor but well inside the 16th grid (no snap to a neighbour)."""
    return [{"pitch": 60, "start_beats": i * 0.5 + max(-0.1, min(0.1, d * 0.02)),
             "duration_beats": 0.25, "velocity": 80, "tags": []}
            for i, d in enumerate(devs)]


def _section_from_deviations(devs):
    sec = SectionPerf(name="s", length_beats=len(devs) * 0.5,
                      layers={"part": _notes_from_deviations(devs)})
    return analyze_performance([sec], song_slug="t").sections[0].parts[0]


def test_pink_deviation_part_reads_human():
    part = _section_from_deviations(_voss_pink(96, seed=3))
    assert part.classification == "human"
    assert part.timing_acf >= STRUCTURED_ACF_MIN


def test_white_deviation_part_reads_sloppy():
    part = _section_from_deviations(_white(96, seed=3))
    assert part.classification == "sloppy"
    assert part.timing_acf < STRUCTURED_ACF_MIN


def test_on_grid_part_reads_mechanical_regardless_of_correlation():
    notes = [{"pitch": 60, "start_beats": i * 0.5, "duration_beats": 0.25,
              "velocity": 80, "tags": []} for i in range(16)]
    sec = SectionPerf(name="s", length_beats=8.0, layers={"part": notes})
    part = analyze_performance([sec], song_slug="t").sections[0].parts[0]
    assert part.classification == "mechanical"


def test_sloppy_part_emits_an_info_finding_never_blocking():
    report = analyze_performance(
        [SectionPerf(name="verse", length_beats=48.0,
                     layers={"shaker": _notes_from_deviations(_white(96, seed=5))})],
        song_slug="t")
    findings = report.sections[0].findings
    assert any(f.kind == "sloppy-timing" and f.severity == "info" for f in findings)
    assert report.ok is True            # a coaching question, never a gate
    assert report.blocking == ()


# ---------------------------------------------------------------------------
# Invariants (Hypothesis)
# ---------------------------------------------------------------------------

_floats = st.floats(min_value=-1e3, max_value=1e3, allow_nan=False, allow_infinity=False)


# deadline=None: each example runs the lag-1 correlation math over up to 200
# floats; that O(n) compute is steady serially but spikes past hypothesis's
# default 200ms per-example deadline under `-n auto` CPU contention. The
# deadline measures machine load, not the bounded-in-[-1,1] property — the
# assertion below is unchanged.
@settings(deadline=None)
@given(st.lists(_floats, min_size=3, max_size=200))
def test_lag1_is_bounded_in_unit_interval(series):
    acf = lag1_autocorr(series)
    assert acf is None or (-1.0 - 1e-9 <= acf <= 1.0 + 1e-9)


@given(st.lists(_floats, max_size=DFA_MIN_POINTS - 1))
def test_dfa_is_none_below_min_points_for_any_series(series):
    assert dfa_alpha(series) is None


# deadline=None: each example runs the full DFA exponent fit (nested
# scale/segment loops) over up to 200 floats — the heaviest per-example
# compute in this file, and the observed parallel-only flaker during
# MEL-1A7K verification. The default 200ms deadline measures `-n auto`
# CPU contention, not the finiteness property; the assertion is unchanged.
@settings(deadline=None)
@given(st.lists(_floats, min_size=DFA_MIN_POINTS, max_size=200))
def test_dfa_when_present_is_a_finite_number(series):
    alpha = dfa_alpha(series)
    assert alpha is None or math.isfinite(alpha)
