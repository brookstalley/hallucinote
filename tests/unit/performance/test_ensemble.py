"""P4 — inter-part phase / ensemble lock.

Distinguishes parts that LOCK (stable relative timing — the pocket) from parts
that sit independently, and a deliberate constant offset (a pocket) from drift.
Covers the pure pairwise metric and the lens integration (SectionPerformance.
ensemble). No findings: non-locking is interpreted against intent downstream.
"""
from __future__ import annotations

import random

from hallucinote.performance import SectionPerf, analyze_performance
from hallucinote.performance.ensemble import MIN_SHARED_ONSETS, pairwise_offsets
from hallucinote.performance.lens import LOCKED_ENSEMBLE_STDEV_MAX


def _voss(n, seed, octaves=5):
    rng = random.Random(seed)
    rows = [rng.gauss(0, 1) for _ in range(octaves)]
    out = []
    for i in range(n):
        for b in range(octaves):
            if i % (1 << b) == 0:
                rows[b] = rng.gauss(0, 1)
        out.append(sum(rows))
    return out


def _events(devs):
    """(onset, dur) events on the 0.5-beat grid, nudged by small deviations."""
    return [(i * 0.5 + max(-0.1, min(0.1, d * 0.02)), 0.25) for i, d in enumerate(devs)]


def _notes(devs, *, vel_seed=None):
    """Notes on the 0.5 grid; varied velocities (seeded) so dynamics don't read
    flat and distract — this suite is about ensemble timing."""
    rng = random.Random(vel_seed if vel_seed is not None else 0)
    return [{"pitch": 60, "start_beats": o, "duration_beats": d,
             "velocity": int(70 + rng.uniform(-12, 12)), "tags": []}
            for o, d in _events(devs)]


# ---------------------------------------------------------------------------
# pairwise_offsets — the metric
# ---------------------------------------------------------------------------


def test_identical_timing_is_perfectly_locked():
    base = _events(_voss(32, 1))
    mean, stdev, n = pairwise_offsets(base, base, grid=0.25)
    assert stdev == 0.0 and mean == 0.0 and n == 32


def test_constant_offset_is_a_locked_pocket_not_drift():
    a = _voss(32, 1)
    ev_a = _events(a)
    ev_b = _events([d + 2.5 for d in a])   # +0.05 beat behind, same shape
    mean, stdev, _ = pairwise_offsets(ev_a, ev_b, grid=0.25)
    assert mean > 0.04                      # B sits behind A (a pocket)
    assert stdev <= LOCKED_ENSEMBLE_STDEV_MAX   # but the offset is STABLE -> locked


def test_independent_parts_do_not_lock():
    a = _events(_voss(32, 7))
    b = _events(_voss(32, 107))
    _, stdev, _ = pairwise_offsets(a, b, grid=0.25)
    assert stdev > LOCKED_ENSEMBLE_STDEV_MAX


def test_none_when_too_few_shared_onsets():
    a = [(i * 1.0, 0.25) for i in range(4)]        # beats 0,1,2,3,...
    b = [(i * 1.0 + 0.5, 0.25) for i in range(4)]  # beats 0.5,1.5,... (disjoint grid)
    assert pairwise_offsets(a, b, grid=0.25) is None
    assert MIN_SHARED_ONSETS > 0


# ---------------------------------------------------------------------------
# Lens integration — SectionPerformance.ensemble
# ---------------------------------------------------------------------------


def _ensemble_of(layers):
    return analyze_performance(
        [SectionPerf(name="verse", length_beats=24.0, layers=layers)],
        song_slug="t").sections[0].ensemble


def test_section_reports_a_locked_pair():
    devs = _voss(32, 2)
    pairs = _ensemble_of({"kick": _notes(devs, vel_seed=1),
                          "snare": _notes(devs, vel_seed=2)})   # same timing
    assert len(pairs) == 1
    assert {pairs[0].track_a, pairs[0].track_b} == {"kick", "snare"}
    assert pairs[0].locked is True
    assert pairs[0].offset_stdev <= LOCKED_ENSEMBLE_STDEV_MAX


def test_section_reports_an_unlocked_independent_pair():
    pairs = _ensemble_of({"gtr": _notes(_voss(32, 7), vel_seed=1),
                          "keys": _notes(_voss(32, 107), vel_seed=2)})
    assert len(pairs) == 1
    assert pairs[0].locked is False


def test_three_parts_produce_three_pairs_and_serialize():
    devs = _voss(32, 3)
    sec = analyze_performance(
        [SectionPerf(name="v", length_beats=24.0,
                     layers={"a": _notes(devs, vel_seed=1),
                             "b": _notes(devs, vel_seed=2),
                             "c": _notes(_voss(32, 203), vel_seed=3)})],
        song_slug="t").sections[0]
    assert len(sec.ensemble) == 3                       # a-b, a-c, b-c
    d = sec.to_dict()
    assert len(d["ensemble"]) == 3
    assert all("locked" in e for e in d["ensemble"])
