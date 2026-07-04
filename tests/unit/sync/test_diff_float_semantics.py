"""SYN-8Q3F (e): pin the TWO diff engines' float-equality semantics together.

Push side (``push/device_param_diff._floats_equal``, rel+abs 1e-6) answers "is
Live already at the DB value?" — a false EQUAL silently skips a dialed write (a
wrong mix), so it is deliberately TIGHT and only skips on proven equality.

Pull side (``pull/_core``: ``_FLOAT_EPS = 1e-3`` via ``_floats_differ`` /
``_normalized_values_match`` / ``_raw_values_match``) answers "did Live move
away from the DB value?" — a false DIFFER churns a DB row + event on every
drift pull (Live display-rounding noise), so it is deliberately LOOSE.

The two are INTENTIONALLY different (documented at both definition sites and in
.prawduct/artifacts/sync-boundary-contract.md §Diff engines). What must never
drift is the DIRECTED relationship between them:

    push-equal  ⟹  pull-no-drift        (push epsilon ≤ pull epsilon)

If that inverts, a captured set oscillates: push skips a write it deems equal,
the next pull "detects" drift and mutates the DB, the next push then differs
again — churn with no fixed point. The reverse gap (pull-same but push-differ)
is safe: one redundant write, then a fixed point — and it is pinned here as an
EXPECTED asymmetry so a future "unify the tolerances" refactor has to meet this
test consciously.

These tests fail if either side's tolerance semantics change — that is the
point. Changing a tolerance is allowed, but only with this invariant re-proven.
"""
from __future__ import annotations

import inspect

from hallucinote.sync.pull._core import (
    _FLOAT_EPS,
    _floats_differ,
    _normalized_values_match,
    _raw_values_match,
)
from hallucinote.sync.push.device_param_diff import _floats_equal


# Representative magnitudes by CHANNEL. The invariant must be checked matcher-
# by-matcher against the value domain that matcher actually sees:
#
#   * RAW channel (any magnitude — a step index, a dB, an 18 kHz cutoff):
#     push compares value_raw via _floats_equal (rel 1e-6); pull compares via
#     _raw_values_match (rel 1e-3, DEV-4P7R). Both RELATIVE → invariant holds
#     across the whole range.
#   * NORMALIZED / MIXER channel ([0,1]-scale — normalized params, volumes,
#     pans, send levels): push compares the normalized→raw projection via
#     _floats_equal; pull uses the ABSOLUTE matchers (_floats_differ /
#     _normalized_values_match, 1e-3). Absolute is only sound because the
#     domain is bounded ~[−1, 1] — at |x| ≤ 1 push's relative term (≤ 1e-6)
#     stays under pull's 1e-3 floor.
#
# The near-miss this split documents: pairing push's RELATIVE 1e-6 against
# pull's ABSOLUTE _floats_differ at a large magnitude (18000.0 vs 18000.016 —
# push-equal, "pull-drift") WOULD violate the invariant. It doesn't in the
# shipped code because pull never applies _floats_differ to the raw channel —
# DEV-4P7R exists precisely because it once did, and the churn was real. Any
# new pull comparison of raw-magnitude values MUST use _raw_values_match.
_RAW_MAGNITUDES = (0.0, 0.001, 0.5, 1.0, -0.37, 8.0, -12.5, 440.0, 18000.0)
_UNIT_MAGNITUDES = (0.0, 0.001, 0.25, 0.5, -0.5, 0.85, 1.0, -1.0)


# ---------------------------------------------------------------------------
# Push side: tight, rel+abs 1e-6, skip-on-confident-equal
# ---------------------------------------------------------------------------


def test_push_floats_equal_absolute_floor_small_values():
    assert _floats_equal(0.5, 0.5 + 9e-7)          # inside 1e-6 abs
    assert _floats_equal(0.0, 9.9e-7)
    assert not _floats_equal(0.5, 0.5 + 2e-6)      # outside
    assert not _floats_equal(0.0, 2e-6)


def test_push_floats_equal_relative_for_large_values():
    # rel term: 1e-6 * 18000 = 0.018
    assert _floats_equal(18000.0, 18000.0 + 0.017)
    assert not _floats_equal(18000.0, 18000.0 + 0.02)


def test_push_default_tolerances_are_1e6():
    sig = inspect.signature(_floats_equal)
    assert sig.parameters["rel"].default == 1e-6
    assert sig.parameters["abs_"].default == 1e-6


# ---------------------------------------------------------------------------
# Pull side: loose, 1e-3, churn-avoidance (+ None asymmetries)
# ---------------------------------------------------------------------------


def test_pull_float_eps_is_1e3():
    assert _FLOAT_EPS == 1e-3


def test_pull_floats_differ_absorbs_display_rounding():
    # The documented case: Live display-rounds 0.6249 vs 0.6250.
    assert not _floats_differ(0.6250, 0.6249)
    assert _floats_differ(0.6273, 0.6250)  # a real (if small) move
    # None semantics: probe-silent is never a diff; DB-None + probed value is.
    assert not _floats_differ(None, 0.5)
    assert _floats_differ(0.5, None)


def test_pull_normalized_match_is_absolute_1e3_with_both_none_equal():
    assert _normalized_values_match(None, None)
    assert not _normalized_values_match(None, 0.5)
    assert not _normalized_values_match(0.5, None)
    assert _normalized_values_match(0.5, 0.5 + 9e-4)
    assert not _normalized_values_match(0.5, 0.5 + 2e-3)


def test_pull_raw_match_is_relative_floored():
    # DEV-4P7R: 4th-significant-digit jitter on a large raw must NOT churn…
    assert _raw_values_match(18000.0012, 18000.0)
    # …while adjacent quantized steps still differ (0.1% of 8 << the 1.0 gap).
    assert not _raw_values_match(7.0, 8.0)
    # Small values keep the absolute floor.
    assert _raw_values_match(0.0005, 0.0)
    assert not _raw_values_match(0.002, 0.0)


# ---------------------------------------------------------------------------
# The cross-engine invariant: push-equal ⟹ pull-no-drift
# ---------------------------------------------------------------------------


def _push_equal_pairs(magnitudes):
    """Pairs the PUSH diff deems equal, across ``magnitudes``: at the absolute
    floor and at the relative bound (just inside each)."""
    for base in magnitudes:
        for delta in (0.0, 9e-7, -9e-7, 0.9e-6 * abs(base), -0.9e-6 * abs(base)):
            a, b = base, base + delta
            if _floats_equal(a, b):
                yield a, b


def test_push_skip_implies_pull_no_drift_raw_channel():
    """RAW channel: any pair the push devices diff would SKIP the write for
    (proven equal) must read as un-drifted to pull's raw matcher — otherwise
    push-skip → pull-mutate churn. Full magnitude range: both sides are
    relative here."""
    checked = 0
    for a, b in _push_equal_pairs(_RAW_MAGNITUDES):
        assert _raw_values_match(a, b), (a, b)
        checked += 1
    assert checked >= len(_RAW_MAGNITUDES)


def test_push_skip_implies_pull_no_drift_unit_channel():
    """NORMALIZED / MIXER channel ([0,1]-scale): push-equal pairs must satisfy
    pull's ABSOLUTE matchers too. Sound only on the bounded domain — see the
    module-level channel note for why 18 kHz-magnitude values must never reach
    _floats_differ / _normalized_values_match."""
    checked = 0
    for a, b in _push_equal_pairs(_UNIT_MAGNITUDES):
        assert not _floats_differ(a, b), (a, b)
        assert _normalized_values_match(a, b), (a, b)
        assert _raw_values_match(a, b), (a, b)
        checked += 1
    assert checked >= len(_UNIT_MAGNITUDES)


def test_absolute_pull_matchers_are_domain_bounded():
    """The documented boundary of the invariant: at raw magnitudes the
    absolute matchers DO disagree with push (push-equal yet 'drift'). This is
    exactly why pull's raw channel uses _raw_values_match (DEV-4P7R) — pin the
    disagreement so it stays a known boundary, not a latent surprise."""
    a, b = 18000.0, 18000.016  # inside push rel-1e-6 (0.018), outside abs 1e-3
    assert _floats_equal(a, b)
    assert _floats_differ(a, b)            # absolute matcher: wrong tool here
    assert not _normalized_values_match(a, b)
    assert _raw_values_match(a, b)         # the raw-channel matcher agrees


def test_push_tolerance_is_not_looser_than_pull_tolerance():
    """The constants themselves: push (1e-6 rel+abs) ≤ pull (1e-3). Loosening
    push past pull breaks test_push_skip_implies_pull_no_drift's premise even
    where that sweep doesn't sample — pin the scalar relation too."""
    sig = inspect.signature(_floats_equal)
    assert sig.parameters["rel"].default <= _FLOAT_EPS
    assert sig.parameters["abs_"].default <= _FLOAT_EPS


def test_reverse_gap_is_expected_asymmetry():
    """Pull-same but push-differ is the INTENDED gap (loose read-side, tight
    write-side): a value within Live's display-rounding noise (5e-4) is not
    drift on pull, but push still rewrites it — one redundant write, then a
    fixed point. Pinned so a future tolerance unification must be conscious."""
    a, b = 0.5, 0.5005
    assert not _floats_differ(a, b)        # pull: no drift
    assert not _floats_equal(a, b)         # push: not provably equal → rewrite
