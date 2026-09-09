"""The pitch follower: an F0 contour in beats becomes tagged notes and bends.

Every stream here is synthesized from MIDI numbers through the inverse of
the Hz→MIDI mapping, so the expected pitches are exact and no audio is
involved.
"""
from __future__ import annotations

import numpy as np
import pytest

from hallucinote.features.types import BeatStream
from hallucinote.generators.follow import FOLLOW_TAG, follow_pitch
from hallucinote.generators.output import GeneratorOutput

HOP = 0.05  # beats per frame — twenty frames a beat


def midi_to_hz(midi: float) -> float:
    return 440.0 * 2.0 ** ((midi - 69.0) / 12.0)


def contour(
    segments: list[tuple[float | None, float]],
    *,
    confidence: list[float] | None = None,
    units: str = "Hz",
) -> BeatStream:
    """A stream from ``(midi_or_None, beats)`` segments; ``None`` is unvoiced.

    A float ``midi`` holds; a segment may instead give a ``(from, to)`` pair
    to glide linearly across its span.
    """
    beats: list[float] = []
    values: list[float] = []
    conf: list[float] = []
    t = 0.0
    for i, (pitch, span) in enumerate(segments):
        n = int(round(span / HOP))
        for k in range(n):
            beats.append(t + k * HOP)
            if pitch is None:
                values.append(np.nan)
            elif isinstance(pitch, tuple):
                lo, hi = pitch
                values.append(midi_to_hz(lo + (hi - lo) * k / n))
            else:
                values.append(midi_to_hz(pitch))
            conf.append(1.0 if confidence is None else confidence[i])
        t += n * HOP
    return BeatStream(
        name="f0",
        beats=np.array(beats),
        values=np.array(values),
        units=units,
        confidence=None if confidence is None else np.array(conf),
    )


def pitches(out: GeneratorOutput) -> list[int]:
    return [n["pitch"] for n in out.notes]


# ---------------------------------------------------------------------------
# Segmentation
# ---------------------------------------------------------------------------


def test_stepped_contour_yields_exactly_its_steps():
    stream = contour([(60, 1.0), (64, 1.0), (67, 1.0)])
    out = follow_pitch(stream, key=None, register=(48, 84))
    assert pitches(out) == [60, 64, 67]
    assert [n["start_beats"] for n in out.notes] == pytest.approx([0.0, 1.0, 2.0])
    assert [n["duration_beats"] for n in out.notes] == pytest.approx([1.0, 1.0, 1.0])
    assert all(n["tags"] == [FOLLOW_TAG] for n in out.notes)
    assert all(n["velocity"] == 100 for n in out.notes)
    assert out.envelopes == []


def test_stepped_contour_carries_no_bend_because_nothing_moves():
    stream = contour([(60, 1.0), (64, 1.0)])
    out = follow_pitch(stream, key=None, register=(48, 84), bend="note_expression")
    assert pitches(out) == [60, 64]
    assert out.envelopes == []


def test_glide_yields_one_note_with_a_bend():
    # Two semitones over one beat: no half-semitone dwell lasts 0.75 beats,
    # so the gesture is one note centred on its median with the motion as
    # a bend around it.
    stream = contour([((60.0, 62.0), 1.0)])
    out = follow_pitch(
        stream, key=None, register=(48, 84), min_note_beats=0.75,
        bend="note_expression",
    )
    assert pitches(out) == [61]
    assert len(out.envelopes) == 1
    env = out.envelopes[0]
    assert env["target_kind"] == "note_expression"
    assert env["parameter_path"] == "pitch"
    assert env["note_pitch"] == 61
    assert env["note_start_beats"] == pytest.approx(0.0)
    assert env["note_duration"] == pytest.approx(1.0)
    times = [bp["time_beats"] for bp in env["breakpoints"]]
    values = [bp["value"] for bp in env["breakpoints"]]
    assert times[0] == pytest.approx(0.0)
    assert times[-1] < env["note_duration"]
    assert values[0] == pytest.approx(-1.0, abs=0.06)
    assert values[-1] == pytest.approx(0.9, abs=0.06)
    assert all(b > a for a, b in zip(values, values[1:]))
    assert all(bp["curve_kind"] == "linear" for bp in env["breakpoints"])


def test_glide_with_bend_none_yields_the_note_and_no_envelope():
    stream = contour([((60.0, 62.0), 1.0)])
    out = follow_pitch(stream, key=None, register=(48, 84), min_note_beats=0.75)
    assert pitches(out) == [61]
    assert out.envelopes == []


def test_scoop_into_a_held_tone_belongs_to_that_note():
    # A quarter-beat rise into a beat of held pitch: one note starting at
    # the scoop, pitched by the dwell, whose bend records the rise.
    stream = contour([((58.0, 60.0), 0.25), (60, 1.0)])
    out = follow_pitch(
        stream, key=None, register=(48, 84), min_note_beats=0.5,
        bend="note_expression",
    )
    assert pitches(out) == [60]
    assert out.notes[0]["start_beats"] == pytest.approx(0.0)
    assert out.notes[0]["duration_beats"] == pytest.approx(1.25)
    env = out.envelopes[0]
    assert env["breakpoints"][0]["value"] == pytest.approx(-2.0)
    assert env["breakpoints"][-1]["value"] == pytest.approx(0.0)


def test_unvoiced_gaps_yield_rests_not_zero_pitch_notes():
    stream = contour([(60, 1.0), (None, 1.0), (60, 1.0)])
    out = follow_pitch(stream, key=None, register=(48, 84))
    assert pitches(out) == [60, 60]
    assert [n["start_beats"] for n in out.notes] == pytest.approx([0.0, 2.0])
    assert [n["duration_beats"] for n in out.notes] == pytest.approx([1.0, 1.0])
    assert all(n["pitch"] > 0 for n in out.notes)


def test_frames_below_the_confidence_floor_are_unvoiced():
    stream = contour(
        [(60, 1.0), (64, 1.0), (60, 1.0)], confidence=[0.9, 0.2, 0.9]
    )
    out = follow_pitch(stream, key=None, register=(48, 84), confidence_floor=0.5)
    assert pitches(out) == [60, 60]
    assert [n["start_beats"] for n in out.notes] == pytest.approx([0.0, 2.0])


def test_a_blip_shorter_than_min_note_beats_is_a_rest():
    stream = contour([(60, 1.0), (None, 0.5), (72, 0.1), (None, 0.4), (64, 1.0)])
    out = follow_pitch(stream, key=None, register=(48, 84), min_note_beats=0.25)
    assert pitches(out) == [60, 64]


def test_vibrato_stays_inside_one_note():
    beats = np.arange(0.0, 2.0, HOP)
    midi = 60.0 + 0.3 * np.sin(2 * np.pi * 6.0 * beats)
    stream = BeatStream(name="f0", beats=beats, values=midi_to_hz(midi), units="Hz")
    out = follow_pitch(stream, key=None, register=(48, 84), bend="note_expression")
    assert pitches(out) == [60]
    assert out.notes[0]["duration_beats"] == pytest.approx(2.0)
    values = [bp["value"] for bp in out.envelopes[0]["breakpoints"]]
    assert max(abs(v) for v in values) == pytest.approx(np.max(np.abs(midi - 60.0)))


def test_empty_stream_yields_nothing():
    stream = BeatStream(name="f0", beats=np.array([]), values=np.array([]), units="Hz")
    out = follow_pitch(stream, key=None, register=(48, 84))
    assert out.notes == [] and out.envelopes == []


# ---------------------------------------------------------------------------
# Key: a parameter, never a default
# ---------------------------------------------------------------------------


def test_key_none_preserves_a_pitch_that_c_major_would_move():
    stream = contour([(61.2, 1.0)])
    kept = follow_pitch(stream, key=None, register=(48, 84))
    moved = follow_pitch(stream, key=(0, "Major"), register=(48, 84))
    assert pitches(kept) == [61]
    assert pitches(moved) == [62]


def test_key_accepts_a_note_name_for_the_tonic():
    stream = contour([(61.2, 1.0)])
    out = follow_pitch(stream, key=("C", "Major"), register=(48, 84))
    assert pitches(out) == [62]


def test_key_quantization_uses_the_mode_not_just_the_tonic():
    stream = contour([(63.0, 1.0)])  # Eb — in C minor, not in C major
    minor = follow_pitch(stream, key=(0, "Minor"), register=(48, 84))
    major = follow_pitch(stream, key=(0, "Major"), register=(48, 84))
    assert pitches(minor) == [63]
    assert pitches(major)[0] in (62, 64)


def test_key_must_be_named_explicitly():
    stream = contour([(60, 1.0)])
    with pytest.raises(TypeError):
        follow_pitch(stream, register=(48, 84))  # type: ignore[call-arg]


def test_unknown_mode_teaches_the_known_set():
    stream = contour([(60, 1.0)])
    with pytest.raises(ValueError, match="unknown mode"):
        follow_pitch(stream, key=(0, "Mixolydic"), register=(48, 84))


def test_bend_is_the_residual_around_the_centre_so_the_key_holds():
    beats = np.arange(0.0, 2.0, HOP)
    midi = 61.2 + 0.3 * np.sin(2 * np.pi * 6.0 * beats)
    stream = BeatStream(name="f0", beats=beats, values=midi_to_hz(midi), units="Hz")
    out = follow_pitch(
        stream, key=(0, "Major"), register=(48, 84), bend="note_expression"
    )
    assert pitches(out) == [62]
    values = [bp["value"] for bp in out.envelopes[0]["breakpoints"]]
    # The vibrato rides around zero; the 0.8-semitone key correction is
    # not smuggled back in through the envelope.
    assert max(abs(v) for v in values) < 0.35


# ---------------------------------------------------------------------------
# Register: transposed in, never dropped
# ---------------------------------------------------------------------------


def test_register_transposes_by_octave_never_drops():
    low_line = contour([(36, 1.0), (43, 1.0)])
    out = follow_pitch(low_line, key=None, register=(60, 71))
    assert pitches(out) == [60, 67]
    high_line = contour([(82, 1.0)])
    out = follow_pitch(high_line, key=None, register=(48, 59))
    assert pitches(out) == [58]


def test_register_applies_after_key_so_both_hold():
    # 71.2 is a B the register (60, 71) holds; Db major has no B, so the key
    # moves it to C (72), past the register, and the octave transposition
    # brings that C back down — the key's pitch class survives the register.
    stream = contour([(71.2, 1.0)])
    assert pitches(follow_pitch(stream, key=None, register=(60, 71))) == [71]
    out = follow_pitch(stream, key=(1, "Major"), register=(60, 71))
    assert pitches(out) == [60]


def test_register_too_narrow_for_every_pitch_class_is_refused():
    stream = contour([(60, 1.0)])
    with pytest.raises(ValueError, match="at least 11"):
        follow_pitch(stream, key=None, register=(60, 64))


# ---------------------------------------------------------------------------
# Refusals that teach
# ---------------------------------------------------------------------------


def test_zero_hz_on_a_voiced_frame_is_refused():
    stream = BeatStream(
        name="f0", beats=np.array([0.0, HOP]), values=np.array([261.6, 0.0]), units="Hz"
    )
    with pytest.raises(ValueError, match="never zero"):
        follow_pitch(stream, key=None, register=(48, 84))


def test_non_hz_stream_is_refused():
    stream = contour([(60, 1.0)], units="midi")
    with pytest.raises(ValueError, match="Hz"):
        follow_pitch(stream, key=None, register=(48, 84))


def test_vector_stream_is_refused():
    stream = BeatStream(
        name="bark", beats=np.array([0.0, HOP]), values=np.ones((2, 3)), units="Hz"
    )
    with pytest.raises(ValueError, match="scalar"):
        follow_pitch(stream, key=None, register=(48, 84))


@pytest.mark.parametrize(
    "kwargs, match",
    [
        ({"min_note_beats": 0.0}, "min_note_beats"),
        ({"confidence_floor": 1.5}, "confidence_floor"),
        ({"bend": "clip_pitch_bend"}, "bend"),
        ({"velocity": 200}, "velocity"),
    ],
)
def test_out_of_range_parameters_are_refused(kwargs, match):
    stream = contour([(60, 1.0)])
    with pytest.raises(ValueError, match=match):
        follow_pitch(stream, key=None, register=(48, 84), **kwargs)
