"""Corpus tests for the per-part timing-deviation analyzer.

There is no labelled groove ground truth for real audio, so — exactly like
``test_masking.py`` — correctness is *defined* by constructed fixtures: place
onsets at known beat positions, assert what ``analyze_timing_window`` recovers.

The fixtures use a sharp ``click`` transient so onset detection is sample-
accurate; the analyzer's onset-detection latency on slow-attack real
instruments (kicks, pads) is a documented caveat of the module, not something
the corpus bakes in. Absolute drift carries a small detection offset, so the
push/drag tests assert SIGN + ORDERING (robust) rather than exact magnitude.

The "real groove" tests at the end are the design's answer to "can we hear
Marley / the Dead / Phish?" — they pin the character the analyzer recovers for
those feels (off-beat skank, loose ensemble, cross-rhythm) and double as
executable documentation of what it can and can't do.
"""
from __future__ import annotations

import numpy as np
import pytest

from hallucinote.audio.timing import analyze_timing_window

from .fixtures import SAMPLE_RATE, onsets_at_beats, silence

BPM = 120.0


def _one(beats, *, bpm=BPM, total_beats=8.0, window_start_beat=0.0, **kw):
    """Analyze a single part built from onsets at the given beat positions."""
    audio = onsets_at_beats(beats, bpm=bpm, total_beats=total_beats)
    res = analyze_timing_window(
        [("part", audio)], SAMPLE_RATE,
        window_start_beat=window_start_beat, bpm=bpm, **kw,
    )
    assert len(res.parts) == 1
    return res.parts[0]


# --------------------------------------------------------------------------- #
# Drift: push / drag / on-grid
# --------------------------------------------------------------------------- #

def test_on_grid_reads_near_zero_drift():
    p = _one(list(range(8)))
    assert abs(p.mean_drift_beats) < 0.02
    assert p.confidence > 0.9


def test_pushed_part_reads_ahead_of_grid():
    """Onsets placed early → negative (ahead/pushed) mean drift."""
    p = _one([b - 0.03 for b in range(8)])
    assert p.mean_drift_beats < -0.015


def test_dragged_part_reads_behind_grid():
    """Onsets placed late → positive (behind/dragged) mean drift."""
    p = _one([b + 0.05 for b in range(8)])
    assert p.mean_drift_beats > 0.015


def test_push_drag_ordering_is_monotone():
    """The cross-fixture invariant that survives any constant detection
    latency: pushed sits ahead of on-grid sits ahead of dragged."""
    pushed = _one([b - 0.03 for b in range(8)]).mean_drift_beats
    on_grid = _one(list(range(8))).mean_drift_beats
    dragged = _one([b + 0.05 for b in range(8)]).mean_drift_beats
    assert pushed < on_grid < dragged


def test_drift_is_bounded_to_half_a_subdivision():
    """Snapping to the nearest subdivision means drift measures micro-timing
    WITHIN the grid — it can never exceed half a subdivision (0.125 for 16ths)."""
    p = _one([b + 0.05 for b in range(8)])
    assert abs(p.mean_drift_beats) <= 0.125 + 1e-9


# --------------------------------------------------------------------------- #
# Tightness → confidence
# --------------------------------------------------------------------------- #

def test_tight_part_is_tight_and_confident():
    p = _one([i * 0.5 for i in range(16)])
    assert p.drift_stdev_beats < 0.01
    assert p.confidence > 0.9


def test_loose_ensemble_reads_higher_stdev_and_lower_confidence():
    """A loosely-played part (jittered onsets) is looser and less trusted than
    a machine-tight one — the 'human feel' signal."""
    rng = np.random.default_rng(3)
    loose = _one([b + float(rng.normal(0, 0.04)) for b in range(8)])
    tight = _one(list(range(8)))
    assert loose.drift_stdev_beats > tight.drift_stdev_beats
    assert loose.confidence < tight.confidence


# --------------------------------------------------------------------------- #
# Swing
# --------------------------------------------------------------------------- #

def test_straight_eighths_read_no_swing():
    p = _one([i * 0.5 for i in range(16)])
    assert p.swing_ratio is not None
    assert 0.85 < p.swing_ratio < 1.15


def test_triplet_swing_reads_near_two():
    """Off-beat 8ths at the triplet position (0.667) → swing ratio ≈ 2."""
    beats = [v for b in range(8) for v in (b, b + 0.6667)]
    p = _one(beats)
    assert p.swing_ratio is not None
    assert p.swing_ratio > 1.7


def test_light_swing_reads_between_straight_and_triplet():
    beats = [v for b in range(8) for v in (b, b + 0.583)]
    p = _one(beats)
    assert p.swing_ratio is not None
    assert 1.2 < p.swing_ratio < 1.6


def test_swing_is_none_without_enough_offbeat_onsets():
    """On-beat-only material has no off-beat 8ths to measure swing from."""
    p = _one(list(range(8)))
    assert p.swing_ratio is None


def test_swing_median_is_robust_to_a_stray_onset():
    """One off-grid stray onset must not drag the swing reading off a groove
    that otherwise swings consistently (median, not mean)."""
    beats = [v for b in range(8) for v in (b, b + 0.6667)]
    beats.append(3.2)  # a stray off-beat onset nowhere near the swung position
    p = _one(beats)
    assert p.swing_ratio is not None
    assert p.swing_ratio > 1.7


# --------------------------------------------------------------------------- #
# Edge cases + invariants
# --------------------------------------------------------------------------- #

def test_silent_stem_is_omitted():
    res = analyze_timing_window(
        [("sil", silence(4.0))], SAMPLE_RATE, window_start_beat=0.0, bpm=BPM,
    )
    assert res.parts == []


def test_sparse_onsets_lower_confidence_than_dense():
    """Few onsets → lower count factor → lower confidence, even when tight."""
    sparse = _one([0.0, 2.0])           # 2 onsets
    dense = _one(list(range(8)))        # 8 onsets
    assert sparse.confidence < dense.confidence
    assert sparse.onset_count < dense.onset_count


def test_window_start_beat_offset_preserves_absolute_grid():
    """Onsets local to the window slice map to absolute beats via
    window_start_beat; an integer offset keeps a grid-aligned part on grid."""
    p = _one(list(range(8)), window_start_beat=16.0)
    assert abs(p.mean_drift_beats) < 0.02


def test_mono_and_stereo_inputs_agree():
    stereo = onsets_at_beats(list(range(8)), bpm=BPM, total_beats=8.0)
    mono = stereo[:, 0]
    rs = analyze_timing_window([("s", stereo)], SAMPLE_RATE, window_start_beat=0.0, bpm=BPM)
    rm = analyze_timing_window([("m", mono)], SAMPLE_RATE, window_start_beat=0.0, bpm=BPM)
    assert rs.parts[0].onset_count == rm.parts[0].onset_count
    assert rs.parts[0].mean_drift_beats == pytest.approx(rm.parts[0].mean_drift_beats)


def test_deterministic():
    a = _one(list(range(8)))
    b = _one(list(range(8)))
    assert a == b


def test_zero_bpm_returns_no_parts():
    audio = onsets_at_beats(list(range(8)), bpm=BPM, total_beats=8.0)
    res = analyze_timing_window([("p", audio)], SAMPLE_RATE, window_start_beat=0.0, bpm=0.0)
    assert res.parts == []


def test_parts_sorted_by_confidence_descending():
    tight = onsets_at_beats(list(range(8)), bpm=BPM, total_beats=8.0)
    rng = np.random.default_rng(11)
    loose = onsets_at_beats(
        [b + float(rng.normal(0, 0.05)) for b in range(8)], bpm=BPM, total_beats=8.0,
    )
    res = analyze_timing_window(
        [("loose", loose), ("tight", tight)], SAMPLE_RATE,
        window_start_beat=0.0, bpm=BPM,
    )
    confs = [p.confidence for p in res.parts]
    assert confs == sorted(confs, reverse=True)


# --------------------------------------------------------------------------- #
# "Can we hear ...?" — real-groove character (executable documentation)
# --------------------------------------------------------------------------- #

def test_reggae_one_drop_is_sparse_low_confidence():
    """One-drop: kick+snare on beat 3 only. Few onsets → low confidence;
    the analyzer reports the sparse pulse honestly rather than inventing feel."""
    p = _one([2.0, 6.0])               # beat 3 of two 4/4 bars (0-indexed 2.0, 6.0)
    assert p.onset_count <= 3
    assert p.confidence < 0.7          # sparse → not a confident feel reading


def test_reggae_skank_reads_offbeat_and_laid_back():
    """The skank plays straight off-beats, pushed slightly late (the lazy
    feel). Swing stays near-straight (it's not a swing groove); drift is
    positive (behind the beat)."""
    p = _one([i * 0.5 + 0.5 + 0.03 for i in range(8)])
    assert p.swing_ratio is not None and p.swing_ratio < 1.3   # not swung
    assert p.mean_drift_beats > 0.0                            # laid back


def test_grateful_dead_loose_ensemble_reads_loose():
    """Loose, elastic ensemble timing → high stdev (the 'human' spread), but
    still a real, reportable feel (confidence above the analyzer's floor)."""
    rng = np.random.default_rng(1969)
    p = _one([b + float(rng.normal(0, 0.035)) for b in range(8)])
    assert p.drift_stdev_beats > 0.02
    assert p.confidence > 0.25


def test_phish_cross_rhythm_reads_low_confidence_not_false_grid():
    """A 3:2 cross-rhythm against the straight grid doesn't align to any
    subdivision → high stdev, low confidence. The HONEST limit: the analyzer
    flags 'this isn't on the grid' rather than fabricating a tidy drift. (It
    measures deviation-from-grid, not the alternative grid the part is on.)"""
    p = _one([i * (2.0 / 3.0) for i in range(12)])
    assert p.drift_stdev_beats > 0.04
    assert p.confidence < 0.25
