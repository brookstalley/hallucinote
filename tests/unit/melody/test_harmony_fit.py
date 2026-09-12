"""melody.harmony_fit — the line's pitch read against the declared harmony.

Reuses ``theory.model``. Tests pin: the chord-tone > scale-tone > chromatic
classification, the strong-beat predicate, the Bharucha NCT-resolves-by-step read
(incl. the metal ♭2 -> chord-tone resolution that proves a modal color is honored,
not flagged), the chord-tone-on-strong-beat coupling, and the ``None``-safe cases.
"""
from __future__ import annotations

from hallucinote.melody.harmony_fit import (
    HarmonyFit,
    _is_strong_beat,
    analyze_harmony_fit,
    classify_tone,
)
from hallucinote.meter import BarGrid, MeterMap, MeterPoint
from hallucinote.theory.model import Progression, mode

# Em chord pcs {E,G,B} = {4,7,11}; E Dorian pcs {E,F#,G,A,B,C#,D} = {4,6,7,9,11,1,2}
_EM = frozenset({4, 7, 11})
_DORIAN = mode("Dorian").pitch_classes(4)


def test_classify_tone_stability_ranking():
    assert classify_tone(4, _EM, _DORIAN) == "chord-tone"     # E
    assert classify_tone(2, _EM, _DORIAN) == "scale-tone"     # D (in mode, not chord)
    assert classify_tone(3, _EM, _DORIAN) == "chromatic"      # D#/Eb (outside mode)
    assert classify_tone(4 + 12, _EM, _DORIAN) == "chord-tone"  # register-blind


_FOUR_FOUR = BarGrid.uniform(4.0, 16.0)


def test_is_strong_beat_downbeat_and_mid_bar():
    assert _is_strong_beat(0.0, _FOUR_FOUR) is True       # downbeat
    assert _is_strong_beat(2.0, _FOUR_FOUR) is True        # mid-bar
    assert _is_strong_beat(4.0, _FOUR_FOUR) is True        # next downbeat
    assert _is_strong_beat(1.0, _FOUR_FOUR) is False       # weak beat
    assert _is_strong_beat(3.0, _FOUR_FOUR) is False       # weak beat


def test_strong_beats_are_the_bar_s_own_not_the_song_s():
    """A 7/4 bar's strong beats are its 1 and its 4.5. The scalar read this
    replaced called beat 4 of it strong — 4 divides the SONG's bar length, but
    in a 7/4 bar it is an off-beat (#566 R5)."""
    seven = MeterMap([MeterPoint(1.0, 7, 4)]).grid_for(1.0, 3.0)
    assert _is_strong_beat(0.0, seven) is True
    assert _is_strong_beat(3.5, seven) is True
    assert _is_strong_beat(7.0, seven) is True     # the next bar's downbeat
    assert _is_strong_beat(4.0, seven) is False    # what the scalar got wrong
    assert _is_strong_beat(2.0, seven) is False


def test_a_grid_spanning_a_change_grades_each_bar_on_its_own_meter():
    mixed = MeterMap(
        [MeterPoint(1.0, 4, 4), MeterPoint(2.0, 7, 4), MeterPoint(3.0, 4, 4)]
    ).grid_for(1.0, 4.0)          # 4/4 | 7/4 | 4/4 == beats 0-4, 4-11, 11-15
    assert _is_strong_beat(2.0, mixed) is True     # mid of the 4/4 bar
    assert _is_strong_beat(7.5, mixed) is True     # mid of the 7/4 bar
    assert _is_strong_beat(6.0, mixed) is False    # would be mid on a 4/4 ruler
    assert _is_strong_beat(13.0, mixed) is True    # mid of the closing 4/4 bar


def test_analyze_harmony_fit_exact():
    prog = Progression.of("E", "Dorian", ["Em"], beats_per_chord=4.0)
    # E@0 (ct, strong), F#@1 (scale, weak), G@2 (ct, strong), D@3 (scale, weak)
    seq = [(0.0, 64), (1.0, 66), (2.0, 67), (3.0, 62)]
    fit = analyze_harmony_fit(seq, prog, bars=_FOUR_FOUR)
    assert fit.note_count == 4
    assert fit.chord_tone_fraction == 0.5
    assert fit.scale_tone_fraction == 0.5
    assert fit.chromatic_fraction == 0.0
    assert fit.non_chord_tone_fraction == 0.5
    # F# (nct) -> G (chord tone) by step (+1) = resolved; D is last, not eligible
    assert fit.nct_resolves_by_step == 1.0
    # both strong-beat notes (E, G) are chord tones
    assert fit.chord_tone_on_strong_beat == 1.0


def test_phrygian_flat_two_resolves_not_flagged():
    # the metal hook's signature ♭2 (F) over Em: F (scale-tone) -> G (chord tone)
    # by step is a textbook anchoring resolution, NOT a defect.
    prog = Progression.of("E", "Phrygian", ["Em"], beats_per_chord=8.0)
    seq = [(4.0, 64), (4.5, 65), (5.0, 67)]  # E (ct), F=♭2 (nct), G (ct)
    fit = analyze_harmony_fit(seq, prog, bars=_FOUR_FOUR)
    assert fit.nct_resolves_by_step == 1.0


def test_none_safe_cases():
    prog = Progression.of("E", "Dorian", ["Em"], beats_per_chord=4.0)
    # empty line
    empty = analyze_harmony_fit([], prog, bars=_FOUR_FOUR)
    assert empty == HarmonyFit(0, 0.0, 0.0, 0.0, None, None)
    # all chord tones -> no NCT to resolve
    all_ct = analyze_harmony_fit([(0.0, 64), (1.0, 67), (2.0, 71)], prog, bars=_FOUR_FOUR)
    assert all_ct.nct_resolves_by_step is None
    # all onsets off the beat -> no strong-beat coupling to report
    off = analyze_harmony_fit([(0.5, 64), (1.5, 62)], prog, bars=_FOUR_FOUR)
    assert off.chord_tone_on_strong_beat is None
