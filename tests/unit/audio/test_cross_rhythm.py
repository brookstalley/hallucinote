"""Corpus tests for the per-part cross-rhythm analyzer.

There is no labelled polyrhythm ground truth for real audio, so — exactly like
``test_masking.py`` and ``test_timing.py`` — correctness is *defined* by
constructed fixtures: place onsets at known beat positions (the ground-truth
ratio), assert what ``analyze_cross_rhythm_window`` recovers. The corpus IS the
spec (``docs/polyrhythms.md`` §6); these cases are the ones the design was
validated against before it was built.

Fixtures use a sharp ``click`` transient so onset detection is sample-accurate;
onset-detection latency on slow-attack real instruments is a documented caveat
of the module (``docs/polyrhythms.md`` §5, limit #6), not something the corpus
bakes in.
"""
from __future__ import annotations

import pytest

from hallucinote.audio.cross_rhythm import analyze_cross_rhythm_window

from .fixtures import SAMPLE_RATE, onsets_at_beats, silence

BPM = 120.0


def _one(beats, *, total_beats=8.0, swing_ratio=None, window_start_beat=0.0):
    """Analyze a single part built from onsets at the given beat positions."""
    audio = onsets_at_beats(beats, bpm=BPM, total_beats=total_beats)
    swing = {"part": swing_ratio} if swing_ratio is not None else None
    res = analyze_cross_rhythm_window(
        [("part", audio)], SAMPLE_RATE,
        window_start_beat=window_start_beat, bpm=BPM, swing_ratios=swing,
    )
    assert len(res.parts) == 1
    return res.parts[0]


# --------------------------------------------------------------------------- #
# Plain binary subdivisions — on the grid, not against it
# --------------------------------------------------------------------------- #

def test_straight_eighths_read_subdivision_2_per_beat():
    p = _one([i * 0.5 for i in range(16)])
    assert p.pulse_ratio == "2/beat"
    assert p.verdict == "subdivision"
    assert not p.against_meter
    assert p.confidence > 0.9


def test_straight_sixteenths_read_subdivision_4_per_beat():
    p = _one([i * 0.25 for i in range(32)])
    assert p.pulse_ratio == "4/beat"
    assert p.verdict == "subdivision"
    assert not p.against_meter


# --------------------------------------------------------------------------- #
# Tuplet subdivisions — named, against the binary meter
# --------------------------------------------------------------------------- #

def test_triplets_read_3_per_beat_cross_rhythm():
    p = _one([i * (1.0 / 3.0) for i in range(24)])
    assert p.pulse_ratio == "3/beat"
    assert p.verdict == "cross-rhythm"
    assert p.against_meter
    assert p.confidence > 0.9


def test_quintuplets_read_5_per_beat():
    p = _one([i * 0.2 for i in range(40)])
    assert p.pulse_ratio == "5/beat"
    assert p.verdict == "cross-rhythm"
    assert p.against_meter


def test_septuplets_read_7_per_beat():
    """Septuplet P ≈ 0.143 beat sits just above the 1/8-beat density floor."""
    p = _one([i * (1.0 / 7.0) for i in range(56)])
    assert p.pulse_ratio == "7/beat"
    assert p.verdict == "cross-rhythm"


# --------------------------------------------------------------------------- #
# N-against-M cross-rhythms — the headline capability
# --------------------------------------------------------------------------- #

def test_hemiola_reads_3_against_2():
    """3 onsets span 2 beats → P = 2/3 → 3:2."""
    p = _one([i * (2.0 / 3.0) for i in range(12)])
    assert p.pulse_ratio == "3:2"
    assert p.verdict == "cross-rhythm"
    assert p.against_meter
    assert p.confidence > 0.95


def test_four_against_three():
    p = _one([i * 0.75 for i in range(11)])
    assert p.pulse_ratio == "4:3"
    assert p.verdict == "cross-rhythm"


def test_five_against_four():
    p = _one([i * 0.8 for i in range(10)])
    assert p.pulse_ratio == "5:4"
    assert p.verdict == "cross-rhythm"


def test_seven_against_four():
    p = _one([i * (4.0 / 7.0) for i in range(14)])
    assert p.pulse_ratio == "7:4"
    assert p.verdict == "cross-rhythm"


def test_five_against_three():
    p = _one([i * 0.6 for i in range(13)])
    assert p.pulse_ratio == "5:3"
    assert p.verdict == "cross-rhythm"


# --------------------------------------------------------------------------- #
# Rests / skips — ratio survives, occupancy flags the holes
# --------------------------------------------------------------------------- #

def test_hemiola_with_rests_still_named_but_lower_occupancy():
    """A 3:2 that rests one pulse per 2-beat cycle: the mode is rest-robust so
    the ratio survives, and occupancy drops to flag the holes (≈0.7 here)."""
    beats = []
    for c in range(4):
        base = c * 2.0
        beats += [base, base + 2.0 / 3.0]  # skip the third pulse (+1.333)
    p = _one(beats)
    assert p.pulse_ratio == "3:2"
    assert p.verdict == "cross-rhythm"
    assert p.occupancy < 0.85
    assert p.confidence > 0.9   # the ratio is not lost despite the holes


# --------------------------------------------------------------------------- #
# Confound rejection — the part most naive designs get wrong
# --------------------------------------------------------------------------- #

def test_displaced_sixteenths_stay_on_grid():
    """16ths shifted +0.1 beat: the constant offset is C7's drift, not a
    cross-rhythm. The free-offset grid-fit keeps it on-grid 16ths."""
    p = _one([i * 0.25 + 0.1 for i in range(31)])
    assert p.pulse_ratio == "4/beat"
    assert p.verdict == "subdivision"
    assert not p.against_meter


def test_swing_eighths_defer_to_c7_when_swing_ratio_supplied():
    """Swung 8ths look like a partially-filled triplet; with C7's swing_ratio in
    the swing band, defer to timing rather than mislabel as a 3/beat tuplet."""
    beats = [v for b in range(8) for v in (b, b + 0.6667)]
    p = _one(beats, swing_ratio=1.9)
    assert p.verdict == "swing(see-timing)"
    assert p.pulse_ratio is None


def test_swing_eighths_without_swing_ratio_are_not_deferred():
    """Without C7's swing input there's nothing to defer to — the read falls
    back to its own pulse estimate (a partial triplet), NOT a swing verdict.
    Documents that the deference is a cross-module composition, not magic."""
    beats = [v for b in range(8) for v in (b, b + 0.6667)]
    p = _one(beats)  # no swing_ratio
    assert p.verdict != "swing(see-timing)"


def test_rubato_accel_is_flagged_not_named():
    """Accelerando: IOIs trend monotonically and no single period fits →
    rubato, never a bizarre ratio."""
    beats = [0.0]
    t, ioi = 0.0, 0.6
    for _ in range(15):
        t += ioi
        beats.append(t)
        ioi *= 0.93
    p = _one(beats, total_beats=max(beats) + 1.0)
    assert p.verdict == "rubato"
    assert p.pulse_ratio is None


def test_buzz_roll_hits_density_floor():
    """A roll faster than 8 hits/beat is a roll/tremolo, not a nameable ratio."""
    p = _one([i * 0.04 for i in range(150)], total_beats=6.0)
    assert p.verdict == "roll"
    assert p.pulse_ratio is None
    assert p.confidence < 0.3


def test_additive_grouping_reads_low_confidence():
    """3+3+2 (units of a half-beat) has no single repeating IOI → low-confidence
    honestly, rather than a confident wrong ratio. Decoding grouping needs
    accent analysis (limit #1)."""
    beats = []
    for c in range(4):
        base = c * 4.0
        beats += [base, base + 1.5, base + 3.0]
    p = _one(sorted(set(beats)), total_beats=18.0)
    assert p.verdict == "low-confidence"
    assert p.pulse_ratio is None


# --------------------------------------------------------------------------- #
# Edge cases + invariants
# --------------------------------------------------------------------------- #

def test_sparse_part_is_low_confidence():
    """A one-drop kick (2 onsets) has too few intervals to assert a pulse."""
    p = _one([2.0, 6.0])
    assert p.verdict == "low-confidence"
    assert p.confidence < 0.3


def test_silent_stem_is_omitted():
    res = analyze_cross_rhythm_window(
        [("sil", silence(4.0))], SAMPLE_RATE, window_start_beat=0.0, bpm=BPM,
    )
    assert res.parts == []


def test_zero_bpm_returns_no_parts():
    audio = onsets_at_beats(list(range(8)), bpm=BPM, total_beats=8.0)
    res = analyze_cross_rhythm_window(
        [("p", audio)], SAMPLE_RATE, window_start_beat=0.0, bpm=0.0,
    )
    assert res.parts == []


def test_window_start_beat_offset_preserves_ratio():
    """Onsets local to a window slice still recover the same ratio regardless of
    the absolute beat the window starts at (the ratio is offset-invariant)."""
    p = _one([i * (2.0 / 3.0) for i in range(12)], window_start_beat=16.0)
    assert p.pulse_ratio == "3:2"


def test_mono_and_stereo_inputs_agree():
    stereo = onsets_at_beats([i * (2.0 / 3.0) for i in range(12)], bpm=BPM, total_beats=8.0)
    mono = stereo[:, 0]
    rs = analyze_cross_rhythm_window([("s", stereo)], SAMPLE_RATE, window_start_beat=0.0, bpm=BPM)
    rm = analyze_cross_rhythm_window([("m", mono)], SAMPLE_RATE, window_start_beat=0.0, bpm=BPM)
    assert rs.parts[0].pulse_ratio == rm.parts[0].pulse_ratio
    assert rs.parts[0].base_period_beats == pytest.approx(rm.parts[0].base_period_beats)


def test_deterministic():
    a = _one([i * (2.0 / 3.0) for i in range(12)])
    b = _one([i * (2.0 / 3.0) for i in range(12)])
    assert a == b


def test_parts_sorted_by_confidence_descending():
    clean = onsets_at_beats([i * (2.0 / 3.0) for i in range(12)], bpm=BPM, total_beats=8.0)
    sparse = onsets_at_beats([2.0, 6.0], bpm=BPM, total_beats=8.0)
    res = analyze_cross_rhythm_window(
        [("sparse", sparse), ("clean", clean)], SAMPLE_RATE,
        window_start_beat=0.0, bpm=BPM,
    )
    confs = [p.confidence for p in res.parts]
    assert confs == sorted(confs, reverse=True)
