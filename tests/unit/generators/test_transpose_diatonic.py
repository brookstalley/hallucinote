"""Chunk E — transpose_diatonic: the key-aware variation op.

The chromatic `transpose` shifts semitones (key-blind); `transpose_diatonic`
shifts scale DEGREES within a declared (key, mode), preserving harmonic function.
"""
from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from hallucinote.generators.variations import transpose, transpose_diatonic
from hallucinote.theory.model import mode

E_DORIAN = mode("Dorian")
E_PC = 4  # E

# E Dorian ascending from E3 crosses the octave at C: E3 F#3 G3 A3 B3 C#4 D4 E4.
E3, FS3, G3, A3, B3 = 52, 54, 55, 57, 59
CS4, D4, E4 = 61, 62, 64
D3 = 50  # the D a step BELOW E3 (the mode's 7th degree, one octave down)


def _n(pitch, start=0.0, dur=1.0, vel=80, tags=None):
    return {"pitch": pitch, "start_beats": start, "duration_beats": dur,
            "velocity": vel, "tags": tags or []}


def _pitches(notes):
    return [n["pitch"] for n in notes]


def test_diatonic_third_differs_from_chromatic_third():
    # Up a "third" (2 scale degrees) in E Dorian: E -> G (a MINOR third here),
    # NOT E -> G# (the chromatic +4). This is the whole point of the op.
    src = [_n(E3)]
    assert _pitches(transpose_diatonic(src, mode=E_DORIAN, key_pc=E_PC, steps=2)) == [G3]
    assert _pitches(transpose(src, 4)) == [56]  # chromatic would land on G#


def test_one_octave_is_n_degrees():
    assert _pitches(transpose_diatonic([_n(E3)], mode=E_DORIAN, key_pc=E_PC, steps=7)) == [E4]


def test_step_down():
    assert _pitches(transpose_diatonic([_n(E3)], mode=E_DORIAN, key_pc=E_PC, steps=-1)) == [D3]


def test_melody_contour_preserved_diatonically():
    melody = [_n(E3), _n(G3), _n(B3), _n(D4)]  # an Em7 arpeggio (scale tones)
    up2 = transpose_diatonic(melody, mode=E_DORIAN, key_pc=E_PC, steps=2)
    # each tone moves up two scale degrees, staying in E Dorian
    assert _pitches(up2) == [G3, B3, D4, FS3 + 12]  # E->G, G->B, B->D, D->F#(next oct)


def test_roundtrip_up_then_down_is_identity():
    melody = [_n(E3), _n(A3), _n(CS4)]
    for k in (1, 2, 3, 5, 7, -4):
        there = transpose_diatonic(melody, mode=E_DORIAN, key_pc=E_PC, steps=k)
        back = transpose_diatonic(there, mode=E_DORIAN, key_pc=E_PC, steps=-k)
        assert _pitches(back) == _pitches(melody)


def test_preserves_rhythm_and_tags():
    src = [_n(E3, start=2.5, dur=0.75, vel=99, tags=["lead", "hook"])]
    out = transpose_diatonic(src, mode=E_DORIAN, key_pc=E_PC, steps=2)
    assert out[0]["start_beats"] == 2.5
    assert out[0]["duration_beats"] == 0.75
    assert out[0]["velocity"] == 99
    assert out[0]["tags"] == ["lead", "hook"]
    assert out[0]["tags"] is not src[0]["tags"]  # defensive copy


# ---------------------------------------------------------------------------
# Non-scale policy
# ---------------------------------------------------------------------------

GS3 = 56  # G#3 — NOT in E Dorian


def test_nonscale_raises_by_default():
    with pytest.raises(ValueError, match="not in E Dorian"):
        transpose_diatonic([_n(GS3)], mode=E_DORIAN, key_pc=E_PC, steps=1)


def test_nonscale_snap_lands_on_a_scale_tone():
    # G# snaps to the nearest scale tone (G3, ties resolve down), then +1 -> A3.
    out = transpose_diatonic([_n(GS3)], mode=E_DORIAN, key_pc=E_PC, steps=1,
                             on_nonscale="snap")
    assert _pitches(out) == [A3]


def test_nonscale_pass_leaves_chromatic_note_untouched():
    src = [_n(E3), _n(GS3)]  # scale tone + chromatic
    out = transpose_diatonic(src, mode=E_DORIAN, key_pc=E_PC, steps=2,
                             on_nonscale="pass")
    assert _pitches(out) == [G3, GS3]  # E->G, the G# passes through


def test_bad_policy_rejected():
    with pytest.raises(ValueError, match="on_nonscale"):
        transpose_diatonic([_n(E3)], mode=E_DORIAN, key_pc=E_PC, steps=1,
                           on_nonscale="wobble")


def test_out_of_midi_range_fails_loud():
    # E (pc 4) high up is a scale tone; +70 degrees blows past MIDI 127.
    with pytest.raises(ValueError, match="MIDI range"):
        transpose_diatonic([_n(100)], mode=E_DORIAN, key_pc=E_PC, steps=70)


# ---------------------------------------------------------------------------
# Property: a scale tone stays in the scale, for any mode / steps
# ---------------------------------------------------------------------------


@given(
    mode_name=st.sampled_from(["Dorian", "Phrygian", "Major", "Minor", "Lydian"]),
    key=st.integers(min_value=0, max_value=11),
    steps=st.integers(min_value=-14, max_value=14),
    degree=st.integers(min_value=0, max_value=6),
)
def test_scale_tone_stays_in_scale(mode_name, key, steps, degree):
    m = mode(mode_name)
    start_pitch = 60 + key + m.intervals[degree]  # a known scale tone near middle C
    out = transpose_diatonic([_n(start_pitch)], mode=m, key_pc=key, steps=steps)
    assert (out[0]["pitch"] % 12) in m.pitch_classes(key)
