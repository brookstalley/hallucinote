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
from hallucinote.theory.model import Progression, mode

# Em chord pcs {E,G,B} = {4,7,11}; E Dorian pcs {E,F#,G,A,B,C#,D} = {4,6,7,9,11,1,2}
_EM = frozenset({4, 7, 11})
_DORIAN = mode("Dorian").pitch_classes(4)


def test_classify_tone_stability_ranking():
    assert classify_tone(4, _EM, _DORIAN) == "chord-tone"     # E
    assert classify_tone(2, _EM, _DORIAN) == "scale-tone"     # D (in mode, not chord)
    assert classify_tone(3, _EM, _DORIAN) == "chromatic"      # D#/Eb (outside mode)
    assert classify_tone(4 + 12, _EM, _DORIAN) == "chord-tone"  # register-blind


def test_is_strong_beat_downbeat_and_mid_bar():
    assert _is_strong_beat(0.0, 4.0) is True       # downbeat
    assert _is_strong_beat(2.0, 4.0) is True        # mid-bar
    assert _is_strong_beat(4.0, 4.0) is True        # next downbeat
    assert _is_strong_beat(1.0, 4.0) is False       # weak beat
    assert _is_strong_beat(3.0, 4.0) is False       # weak beat


def test_analyze_harmony_fit_exact():
    prog = Progression.of("E", "Dorian", ["Em"], beats_per_chord=4.0)
    # E@0 (ct, strong), F#@1 (scale, weak), G@2 (ct, strong), D@3 (scale, weak)
    seq = [(0.0, 64), (1.0, 66), (2.0, 67), (3.0, 62)]
    fit = analyze_harmony_fit(seq, prog, beats_per_bar=4.0)
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
    fit = analyze_harmony_fit(seq, prog, beats_per_bar=4.0)
    assert fit.nct_resolves_by_step == 1.0


def test_none_safe_cases():
    prog = Progression.of("E", "Dorian", ["Em"], beats_per_chord=4.0)
    # empty line
    empty = analyze_harmony_fit([], prog, beats_per_bar=4.0)
    assert empty == HarmonyFit(0, 0.0, 0.0, 0.0, None, None)
    # all chord tones -> no NCT to resolve
    all_ct = analyze_harmony_fit([(0.0, 64), (1.0, 67), (2.0, 71)], prog, beats_per_bar=4.0)
    assert all_ct.nct_resolves_by_step is None
    # all onsets off the beat -> no strong-beat coupling to report
    off = analyze_harmony_fit([(0.5, 64), (1.5, 62)], prog, beats_per_bar=4.0)
    assert off.chord_tone_on_strong_beat is None
