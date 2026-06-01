"""Chunk A — the theory core (Chord / Mode / Progression).

Pure harmonic arithmetic, so these are exhaustive example tests plus a few
Hypothesis property tests on the invariants (parse round-trips, cyclic
chord_at, tiling coverage, voicing stays in MIDI range).
"""
from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from hallucinote.theory.model import (
    MODES,
    QUALITIES,
    Change,
    Chord,
    Mode,
    Progression,
    mode,
    pc_name,
    pitch_class,
)

# Pitch classes used a lot below.
E, F, FS, G, B, C, CS, D, A = 4, 5, 6, 7, 11, 0, 1, 2, 9


# ---------------------------------------------------------------------------
# Pitch-class names
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name,pc",
    [("C", 0), ("c", 0), ("C#", 1), ("Db", 1), ("E", 4), ("F#", 6),
     ("Gb", 6), ("Bb", 10), ("A#", 10), ("B", 11)],
)
def test_pitch_class_parses(name, pc):
    assert pitch_class(name) == pc


def test_pitch_class_rejects_garbage():
    with pytest.raises(ValueError, match="unknown note name"):
        pitch_class("H")


def test_pc_name_is_sharp_spelling():
    assert pc_name(1) == "C#"
    assert pc_name(6) == "F#"
    assert pc_name(13) == "C#"  # wraps


# ---------------------------------------------------------------------------
# Modes
# ---------------------------------------------------------------------------


def test_e_dorian_vs_e_phrygian_pitch_classes():
    # The two worlds share root E and four degrees; they differ only at the
    # 2nd (F# vs F) and the 6th (C# vs C). That two-semitone hinge is the song.
    dorian = mode("Dorian").pitch_classes(E)
    phrygian = mode("Phrygian").pitch_classes(E)
    assert dorian == {E, FS, G, A, B, CS, D}
    assert phrygian == {E, F, G, A, B, C, D}
    # The pivot notes: F# only in Dorian, F only in Phrygian; C# only Dorian, C only Phrygian.
    assert dorian - phrygian == {FS, CS}
    assert phrygian - dorian == {F, C}
    assert dorian & phrygian == {E, G, A, B, D}


def test_mode_lookup_case_insensitive_and_aliases():
    assert mode("dorian") is mode("Dorian")
    assert mode("Ionian").intervals == mode("Major").intervals
    assert mode("Aeolian").intervals == mode("Minor").intervals


def test_mode_unknown_raises():
    with pytest.raises(ValueError, match="unknown mode"):
        mode("Bebop Hyperlydian")


# ---------------------------------------------------------------------------
# Chord.parse / of / split
# ---------------------------------------------------------------------------


def test_parse_minor_seventh():
    c = Chord.parse("Em7")
    assert c.root_pc == E
    assert c.intervals == (0, 3, 7, 10)
    assert c.bass_pc is None
    assert c.symbol == "Em7"
    assert c.pitch_classes() == {E, G, B, D}


def test_parse_bare_symbol_is_major():
    c = Chord.parse("F")
    assert c.root_pc == F
    assert c.intervals == (0, 4, 7)
    assert c.pitch_classes() == {F, 9, 0}  # F A C


def test_power_chord_has_no_third():
    c = Chord.parse("E5")
    assert c.intervals == (0, 7)
    assert c.tones() == (E, B)
    # No major or minor third present — the lens must never flag this.
    assert G not in c.pitch_classes()  # G would be the m3
    assert (E + 4) % 12 not in c.pitch_classes()  # G# the M3


def test_slash_bass_is_the_dorian_phrygian_pivot():
    # Em/C# (bright 6th — Dorian) vs Em/C (dark b6 — Phrygian): one semitone.
    dorian_voiced = Chord.parse("Em/C#")
    phrygian_voiced = Chord.parse("Em/C")
    assert dorian_voiced.bass_pc == CS
    assert phrygian_voiced.bass_pc == C
    # Same chord up top, the bass is the only difference.
    assert dorian_voiced.tones() == phrygian_voiced.tones() == (E, G, B)
    assert CS in dorian_voiced.pitch_classes()
    assert C in phrygian_voiced.pitch_classes()


def test_parse_unknown_quality_fails_loud():
    with pytest.raises(ValueError, match="unknown chord quality"):
        Chord.parse("Ezz9")


def test_of_named_and_raw_quality_agree():
    named = Chord.of(E, "m7")
    raw = Chord.of(E, (0, 3, 7, 10))
    assert named.pitch_classes() == raw.pitch_classes()


def test_split_chord_is_both_worlds_at_once():
    # The fusion-climax sonority: an Em carrying BOTH the Dorian C# and the
    # Phrygian C — both-at-once. Built from the two slash-voiced chords.
    dorian = Chord.parse("Em/C#")
    phrygian = Chord.parse("Em/C")
    fused = Chord.split_chord(dorian, phrygian)
    assert {C, CS} <= fused.pitch_classes()  # both worlds present
    assert fused.pitch_classes() == dorian.pitch_classes() | phrygian.pitch_classes()


def test_chord_rejects_bad_pitch_classes():
    with pytest.raises(ValueError, match="root_pc must be 0..11"):
        Chord(root_pc=12, intervals=(0, 4, 7))
    with pytest.raises(ValueError, match="at least one interval"):
        Chord(root_pc=0, intervals=())


# ---------------------------------------------------------------------------
# Voicing (the dumb close-position fallback)
# ---------------------------------------------------------------------------


def test_voicing_em7_matches_legacy_hardcoded_voicing():
    # The old sun-zone-done hardcoded EM7 = [E3, G3, B3, D4] = [52, 55, 59, 62].
    # The chord-aware path must reproduce it from Chord + register.
    assert Chord.parse("Em7").voicing(register=3) == [52, 55, 59, 62]


def test_voicing_power_chord_root_and_fifth():
    assert Chord.parse("E5").voicing(register=3) == [52, 59]  # E3, B3


def test_voicing_excludes_slash_bass_but_includes_split():
    # Slash bass is the bass part's job — a chordal voicing of Em/C# plays Em up
    # top (no C# folded in). The polymodal split, however, IS part of the sound.
    assert Chord.parse("Em/C#").voicing(register=3) == [52, 55, 59]  # E G B, no C#
    fused = Chord.split_chord(Chord.parse("Em/C#"), Chord.parse("Em/C"))
    # the split C (pc 0) voices as C4 = 60, a minor 6th above E3
    assert 60 in fused.voicing(register=3)


# ---------------------------------------------------------------------------
# Progression
# ---------------------------------------------------------------------------


def test_progression_even_rhythm():
    p = Progression.of("E", "Dorian", ["Em7", "A7", "Em7", "Bm7"], beats_per_chord=4.0)
    assert p.key_pc == E
    assert p.mode is mode("Dorian")
    assert p.cycle_beats == 16.0
    assert p.harmonic_rhythm == (4.0, 4.0, 4.0, 4.0)
    assert p.distinct_chords == 3  # Em7 appears twice


def test_progression_explicit_rhythm_accelerates():
    # Accelerating harmonic rhythm into a cadence — the expressive case.
    p = Progression.of("E", "Phrygian", [("F", 8.0), ("Em", 4.0), ("Bb", 2.0), ("Em", 2.0)])
    assert p.harmonic_rhythm == (8.0, 4.0, 2.0, 2.0)
    assert p.cycle_beats == 16.0


def test_progression_mixed_spec_rejected():
    with pytest.raises(ValueError, match="mixes bare symbols"):
        Progression.of("E", "Dorian", ["Em7", ("A7", 4.0)], beats_per_chord=4.0)


def test_progression_bare_without_rhythm_rejected():
    with pytest.raises(ValueError, match="needs beats_per_chord"):
        Progression.of("E", "Dorian", ["Em7", "A7"])


def test_chord_at_is_cyclic():
    p = Progression.of("E", "Dorian", ["Em7", "A7"], beats_per_chord=4.0)
    assert p.chord_at(0.0).symbol == "Em7"
    assert p.chord_at(2.0).symbol == "Em7"
    assert p.chord_at(4.0).symbol == "A7"
    assert p.chord_at(7.9).symbol == "A7"
    assert p.chord_at(8.0).symbol == "Em7"   # wraps
    assert p.chord_at(12.0).symbol == "A7"   # wraps again


def test_tiled_covers_exactly():
    p = Progression.of("E", "Dorian", ["Em7", "A7"], beats_per_chord=4.0)
    t = p.tiled(16.0)
    assert t.changes[0].start_beat == 0.0
    assert t.changes[-1].start_beat + t.changes[-1].duration_beats == pytest.approx(16.0)
    # every change lies within [0, 16)
    assert all(0.0 <= c.start_beat < 16.0 for c in t.changes)
    assert len(t.changes) == 4  # Em7 A7 Em7 A7


def test_slice_rebases_to_zero():
    p = Progression.of("E", "Dorian", ["Em7", "A7", "Cmaj7", "Bm7"], beats_per_chord=4.0)
    s = p.slice(8.0, 8.0)  # bars covering Cmaj7, Bm7
    assert s.changes[0].start_beat == 0.0
    assert s.changes[0].chord.symbol == "Cmaj7"
    assert s.changes[-1].chord.symbol == "Bm7"
    assert s.cycle_beats == 8.0


def test_distinct_chords_counts_pitch_identity_not_symbol():
    # Same chord twice -> 1 distinct.
    p = Progression.of("E", "Phrygian", ["Em", "Em"], beats_per_chord=4.0)
    assert p.distinct_chords == 1


# ---------------------------------------------------------------------------
# Property tests — the invariants
# ---------------------------------------------------------------------------

_NAMES = ["C", "C#", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"]
_QUALS = sorted(q for q in QUALITIES if q)


@given(root=st.sampled_from(_NAMES), qual=st.sampled_from(_QUALS))
def test_parse_roundtrips_root_and_quality(root, qual):
    c = Chord.parse(f"{root}{qual}")
    assert c.root_pc == pitch_class(root)
    assert c.intervals == QUALITIES[qual]


@given(
    syms=st.lists(st.sampled_from(["Em7", "A7", "F", "Cmaj7", "Bm7", "Em"]),
                  min_size=1, max_size=6),
    beat=st.floats(min_value=0.0, max_value=200.0, allow_nan=False),
)
def test_chord_at_always_returns_a_declared_chord(syms, beat):
    p = Progression.of("E", "Dorian", syms, beats_per_chord=4.0)
    got = p.chord_at(beat)
    assert got.symbol in syms
    # cyclic identity: chord_at(beat) == chord_at(beat % cycle)
    assert p.chord_at(beat).symbol == p.chord_at(beat % p.cycle_beats).symbol


@given(length=st.floats(min_value=1.0, max_value=120.0, allow_nan=False))
def test_tiled_changes_are_within_window_and_contiguous(length):
    p = Progression.of("E", "Phrygian", ["Em", "F", "Em", "D"], beats_per_chord=4.0)
    t = p.tiled(length)
    prev_end = 0.0
    for c in t.changes:
        assert 0.0 <= c.start_beat < length + 1e-9
        assert c.start_beat == pytest.approx(prev_end)  # contiguous, no gaps
        prev_end = c.start_beat + c.duration_beats
    assert prev_end == pytest.approx(length)


@given(reg=st.integers(min_value=0, max_value=7),
       sym=st.sampled_from(["Em7", "A7", "F", "Cmaj7", "E5", "Bm7"]))
def test_voicing_stays_in_midi_range(reg, sym):
    for pitch in Chord.parse(sym).voicing(register=reg):
        assert 0 <= pitch <= 127
