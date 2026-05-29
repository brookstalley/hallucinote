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

from hallucinote.audio.cross_rhythm import (
    analyze_cross_rhythm_window,
    analyze_phasing_window,
    analyze_polymeter_window,
)

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


# --------------------------------------------------------------------------- #
# Additive grouping — decoded (C8c, was limit #1)
# --------------------------------------------------------------------------- #

def _additive(groups, *, n=4, unit=0.5, accent=False):
    """Build an additive part: onsets on each group start, ``unit``-beat cells.
    With ``accent`` the bar downbeat (each cycle's first group) is 2× louder."""
    beats, amps, pos = [], [], 0.0
    for _ in range(n):
        for k, g in enumerate(groups):
            beats.append(pos)
            amps.append(2.0 if (accent and k == 0) else 1.0)
            pos += g * unit
    return beats, amps


def _one_accented(beats, amps, *, total_beats, window_start_beat=0.0):
    """Analyze a single accented part (per-onset amplitudes)."""
    audio = onsets_at_beats(
        beats, bpm=BPM, total_beats=total_beats, amplitudes=amps
    )
    res = analyze_cross_rhythm_window(
        [("part", audio)], SAMPLE_RATE,
        window_start_beat=window_start_beat, bpm=BPM,
    )
    assert len(res.parts) == 1
    return res.parts[0]


def test_additive_3_3_2_decodes_grouping():
    """3+3+2 (half-beat units) — was low-confidence (limit #1), now decoded as
    an additive cell. Equal velocity → canonical (lex-max) rotation."""
    beats, _ = _additive([3, 3, 2])
    p = _one(beats, total_beats=18.0)
    assert p.verdict == "additive"
    assert p.grouping == (3, 3, 2)
    assert p.cycle_length_beats == pytest.approx(4.0)
    assert p.pulse_ratio is None
    assert p.against_meter
    assert p.confidence > 0.8


def test_additive_7_8_accent_anchors_rotation():
    """An accented 2+2+3 (7/8) reads (2,2,3) — the loud downbeat anchors the
    cell start, distinguishing it from 3+2+2 which equal-velocity cannot."""
    beats, amps = _additive([2, 2, 3], accent=True)
    p = _one_accented(beats, amps, total_beats=18.0)
    assert p.verdict == "additive"
    assert p.grouping == (2, 2, 3)
    assert p.cycle_length_beats == pytest.approx(3.5)


def test_additive_3_2_2_accent_distinct_from_7_8():
    """Accented 3+2+2 reads (3,2,2) — a different rotation than the 2+2+3 above,
    provable only because the accent locates the downbeat."""
    beats, amps = _additive([3, 2, 2], accent=True)
    p = _one_accented(beats, amps, total_beats=18.0)
    assert p.verdict == "additive"
    assert p.grouping == (3, 2, 2)


def test_uniform_subdivision_is_not_additive():
    """Steady 8ths have uniform IOIs → a plain subdivision, never an additive
    grouping (the decoder must not over-fire on an even pulse)."""
    p = _one([i * 0.5 for i in range(16)])
    assert p.verdict == "subdivision"
    assert p.grouping is None
    assert p.cycle_length_beats is None


def test_clean_cross_rhythm_carries_no_grouping():
    """A clean 3:2 names a ratio, not a grouping — additive fields stay None."""
    p = _one([i * (2.0 / 3.0) for i in range(13)])
    assert p.verdict == "cross-rhythm"
    assert p.grouping is None


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


# --------------------------------------------------------------------------- #
# Two-part phasing (Reich) — the C8b pass
# --------------------------------------------------------------------------- #

def _pulse_train(period_beats, total_beats):
    """A steady pulse at ``period_beats`` filling ``total_beats``."""
    beats = [i * period_beats for i in range(int(total_beats / period_beats) + 1)]
    return onsets_at_beats(
        [b for b in beats if b < total_beats], bpm=BPM, total_beats=total_beats,
    )


def _phasing(parts, *, total_beats):
    return analyze_phasing_window(
        parts, SAMPLE_RATE, window_start_beat=0.0, bpm=BPM,
    )


def test_reich_phasing_detected_as_monotonic_drift():
    """Two identical quarter-note pulses, B 3% faster: their relative offset
    marches monotonically → a clean phasing read (the Reich case). 3% over 16
    beats at a quarter pulse keeps the drift under half a pulse (no wrap)."""
    a = _pulse_train(1.0, 16.0)
    b = _pulse_train(1.0 / 1.03, 16.0)
    res = _phasing([("A", a), ("B", b)], total_beats=16.0)
    assert len(res.pairs) == 1
    ph = res.pairs[0]
    assert {ph.track_a, ph.track_b} == {"A", "B"}
    assert abs(ph.drift_beats_per_cycle) > 0.05   # a real march, not noise
    assert ph.confidence > 0.9                    # cleanly monotonic


def test_locked_parts_show_no_drift():
    """Two identical, locked pulses don't drift — confidence and drift both ≈ 0,
    so the integration layer floors them out (no false phasing)."""
    a = _pulse_train(1.0, 16.0)
    b = _pulse_train(1.0, 16.0)
    res = _phasing([("A", a), ("B", b)], total_beats=16.0)
    assert len(res.pairs) == 1   # the DSP reports the measured pair, neutrally
    ph = res.pairs[0]
    assert abs(ph.drift_beats_per_cycle) < 0.02   # below the integration floor


def test_constant_offset_is_not_phasing():
    """A constant phase offset (B always +0.06 beat) is a fixed relationship,
    not a drift — drift ≈ 0 even if detection jitter reads a trend, so the drift
    floor (not confidence) is what keeps it from being mislabeled phasing."""
    a = _pulse_train(1.0, 16.0)
    b = onsets_at_beats(
        [i + 0.06 for i in range(16)], bpm=BPM, total_beats=16.0,
    )
    res = _phasing([("A", a), ("B", b)], total_beats=16.0)
    assert res.pairs
    assert abs(res.pairs[0].drift_beats_per_cycle) < 0.02


def test_phasing_needs_two_parts():
    """A single part has no pair to phase against."""
    a = _pulse_train(1.0, 16.0)
    res = _phasing([("A", a)], total_beats=16.0)
    assert res.pairs == []


def test_phasing_zero_bpm_returns_no_pairs():
    a = _pulse_train(1.0, 16.0)
    b = _pulse_train(1.0 / 1.03, 16.0)
    res = analyze_phasing_window(
        [("A", a), ("B", b)], SAMPLE_RATE, window_start_beat=0.0, bpm=0.0,
    )
    assert res.pairs == []


# --------------------------------------------------------------------------- #
# Two-part polymeter (different cell lengths) — the C8c pass (was limit #2)
# --------------------------------------------------------------------------- #

def _accented_pulse(period_beats, *, cell_beats, total_beats):
    """A steady pulse whose every onset at a ``cell_beats`` boundary is 2× loud
    — a part looping a ``cell_beats``-long cell, marked only by its accent."""
    n = int(total_beats / period_beats)
    beats = [i * period_beats for i in range(n)]
    amps = [2.0 if abs((b % cell_beats)) < 1e-6 else 1.0 for b in beats]
    return onsets_at_beats(beats, bpm=BPM, total_beats=total_beats, amplitudes=amps)


def _poly(parts, *, total_beats):
    return analyze_polymeter_window(
        parts, SAMPLE_RATE, window_start_beat=0.0, bpm=BPM,
    )


def test_polymeter_four_cell_vs_three_cell():
    """A 4-beat cell against a 3-beat cell (both steady 8ths, distinguished only
    by accent) → distinct cells + a realign of lcm(4,3)=12 beats. The verifiable
    signal for limit #2."""
    a = _accented_pulse(0.5, cell_beats=4.0, total_beats=24.0)
    b = _accented_pulse(0.5, cell_beats=3.0, total_beats=24.0)
    res = _poly([("A", a), ("B", b)], total_beats=24.0)
    assert len(res.pairs) == 1
    pm = res.pairs[0]
    assert {pm.track_a, pm.track_b} == {"A", "B"}
    cells = sorted([pm.cycle_a_beats, pm.cycle_b_beats])
    assert cells[0] == pytest.approx(3.0, abs=0.1)
    assert cells[1] == pytest.approx(4.0, abs=0.1)
    assert pm.realign_beats == pytest.approx(12.0, abs=0.1)
    assert pm.confidence >= 0.5


def test_same_cell_is_not_polymeter():
    """Two parts on the same 4-beat cell share a meter — no polymeter pair."""
    a = _accented_pulse(0.5, cell_beats=4.0, total_beats=24.0)
    b = _accented_pulse(0.5, cell_beats=4.0, total_beats=24.0)
    res = _poly([("A", a), ("B", b)], total_beats=24.0)
    assert res.pairs == []


def test_equal_velocity_parts_surface_no_polymeter():
    """The deferral's core case: two equal-velocity steady streams have identical
    onset trains — no accent, no detectable cell, so honestly no polymeter (not a
    fabricated one)."""
    a = _pulse_train(0.5, 24.0)
    b = _pulse_train(0.5, 24.0)
    res = _poly([("A", a), ("B", b)], total_beats=24.0)
    assert res.pairs == []


def test_additive_part_does_not_pair_as_polymeter():
    """An additive part (irregular IOIs) is described by its `grouping`, not a
    cell — folding it onto a uniform pulse grid yields a spurious lcm-period
    cell. The uniformity guard keeps it out of the polymeter pass, so an
    additive part paired with a steady cell produces no polymeter pair. (This
    case was surfaced by the real-Live validation render — see build-plan C8c-4.)
    """
    beats, amps = _additive([3, 3, 2], accent=True, n=8)
    additive_part = onsets_at_beats(
        beats, bpm=BPM, total_beats=32.0, amplitudes=amps,
    )
    steady = _accented_pulse(0.5, cell_beats=4.0, total_beats=32.0)
    res = _poly([("add", additive_part), ("cell4", steady)], total_beats=32.0)
    assert res.pairs == []


def test_accent_cycle_picks_fundamental_not_harmonic():
    """An accent every 4 beats correlates at lag 4 AND at its 8/12-beat
    multiples (the harmonic trap §2 rejected onset-train autocorrelation for).
    The fundamental-lag selection (smallest near-maximal lag) must return the
    4-beat cell, NOT a 2×/3× harmonic — the load-bearing reason accent AC is
    safe where onset-train AC isn't."""
    from hallucinote.audio.cross_rhythm import _accent_cycle
    from hallucinote.audio.onsets import (
        DEFAULT_MIN_ONSET_SEPARATION_BEATS,
        dedup_onsets_with_strength,
        detect_onsets_with_strength,
        to_mono,
    )
    # 8 four-beat cells → harmonics at 8 and 12 beats are strongly present.
    audio = _accented_pulse(0.5, cell_beats=4.0, total_beats=32.0)
    s, st = detect_onsets_with_strength(to_mono(audio), SAMPLE_RATE)
    bps = BPM / 60.0 / SAMPLE_RATE
    beats, strengths = dedup_onsets_with_strength(
        s * bps, st, DEFAULT_MIN_ONSET_SEPARATION_BEATS
    )
    cell = _accent_cycle(beats, strengths)
    assert cell is not None
    assert cell[0] == pytest.approx(4.0, abs=0.1)  # fundamental, not 8 or 12


def test_polymeter_needs_two_parts():
    a = _accented_pulse(0.5, cell_beats=4.0, total_beats=24.0)
    res = _poly([("A", a)], total_beats=24.0)
    assert res.pairs == []


def test_polymeter_zero_bpm_returns_no_pairs():
    a = _accented_pulse(0.5, cell_beats=4.0, total_beats=24.0)
    b = _accented_pulse(0.5, cell_beats=3.0, total_beats=24.0)
    res = analyze_polymeter_window(
        [("A", a), ("B", b)], SAMPLE_RATE, window_start_beat=0.0, bpm=0.0,
    )
    assert res.pairs == []
