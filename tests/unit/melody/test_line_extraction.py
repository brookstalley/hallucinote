"""melody line extraction — the skyline-over-time top-voice reduction.

Regression coverage for the MEL-1A7K post-ship line-extraction fidelity bugfix. The
reducer must fold brief/incidental polyphony (octave doubles, backing vocals, a brief
higher harmony) into a single TOP-VOICE line by reading note DURATIONS — dropping a
note masked by a still-sounding higher note — instead of interleaving a staggered
second voice into the "monophonic" line (which inflated leaps / ballooned ambitus /
scrambled contour on sun-zone-done's back-half lead sections; see
.prawduct/artifacts/plans/MEL-1A7K/archive/extraction-fidelity-build-plan.md).
"""
from __future__ import annotations

from hallucinote.melody import SectionMelody, analyze_melody
from hallucinote.melody.lens import _extract_melodic_line, _melodic_sequence
from hallucinote.melody.segmentation import per_phrase_contours


def _n(pitch: int, start: float, dur: float = 0.5, vel: int = 80) -> dict:
    return {"pitch": pitch, "start_beats": start, "duration_beats": dur, "velocity": vel}


def _pitches(line):
    return [int(n["pitch"]) for n in line]


# ---------------------------------------------------------------------------
# Kept contracts — the skyline must preserve the prior exact-onset behavior.
# ---------------------------------------------------------------------------


def test_sequential_mono_line_unchanged():
    # Back-to-back notes: a note ending exactly as the next begins is no longer
    # SOUNDING, so nothing masks anything — every note is kept (faithful clean-mono).
    notes = [_n(64, 0.0, 1.0), _n(62, 1.0, 0.5), _n(59, 1.5, 0.5), _n(55, 2.0, 1.0)]
    assert _pitches(_extract_melodic_line(notes)) == [64, 62, 59, 55]
    assert _melodic_sequence(notes) == [(0.0, 64), (1.0, 62), (1.5, 59), (2.0, 55)]


def test_exact_onset_octave_double_keeps_top_voice():
    # The section-4 case: an octave-doubled hook struck TOGETHER -> top voice only.
    notes = [_n(48, 0.0, 1.0), _n(60, 0.0, 1.0), _n(50, 1.0, 1.0), _n(62, 1.0, 1.0)]
    assert _pitches(_extract_melodic_line(notes)) == [60, 62]


def test_zero_duration_simultaneous_keeps_top():
    notes = [_n(60, 0.0, 0.0), _n(67, 0.0, 0.0), _n(62, 1.0, 0.0)]
    assert _pitches(_extract_melodic_line(notes)) == [67, 62]


# ---------------------------------------------------------------------------
# The fix — staggered polyphony folded to the top line.
# ---------------------------------------------------------------------------


def test_staggered_lower_voice_under_held_note_is_masked():
    # A held melody note with a lower voice onsetting UNDER it (still sounding) ->
    # the lower notes are accompaniment, dropped; the line stays on the top voice.
    notes = [_n(72, 0.0, 4.0), _n(48, 1.0, 0.5), _n(50, 2.0, 0.5), _n(52, 3.0, 0.5)]
    assert _pitches(_extract_melodic_line(notes)) == [72]


def test_legato_descending_line_not_masked():
    # A descending LEGATO monophonic line: each note's tail laps the next (lower)
    # note's onset, but the higher note ENDS BEFORE the lower one does (no containment).
    # The lower notes ARE the melody and must be kept — masking them would gut a
    # legato descending line (sun-zone-done's reggae hook is exactly this).
    notes = [_n(64, 0.0, 1.2), _n(62, 1.0, 1.2), _n(60, 2.0, 1.2), _n(59, 3.0, 1.2)]
    assert _pitches(_extract_melodic_line(notes)) == [64, 62, 60, 59]


def test_brief_higher_harmony_folds_into_top_line():
    # DR-1: brief HIGHER polyphony (a high harmony / backing vocal above the lead) IS
    # included -> the line follows the top voice while the lower note still rings.
    notes = [_n(60, 0.0, 4.0), _n(79, 1.0, 0.5)]
    assert _pitches(_extract_melodic_line(notes)) == [60, 79]


def test_genuine_descent_lower_exposed_after_top_ends():
    # A real melodic descent: the high note ENDS before the low note starts -> the low
    # note is exposed and kept (we must not over-mask genuine downward motion).
    notes = [_n(72, 0.0, 1.0), _n(55, 1.0, 1.0)]
    assert _pitches(_extract_melodic_line(notes)) == [72, 55]


# ---------------------------------------------------------------------------
# Section-level faithfulness — ambitus reflects the top line, not the interleave.
# ---------------------------------------------------------------------------


def test_section_ambitus_reflects_top_voice_not_interleaved_pedal():
    # Held top-voice melody (true ambitus 5: 67..72) with a staggered octave-below
    # pedal. Without the fix the interleaved pedal balloons ambitus toward 2 octaves;
    # with it the line reads the melody's true ambitus.
    tops = [(67, 0.0), (72, 1.0), (69, 2.0), (71, 3.0),
            (67, 4.0), (72, 5.0), (69, 6.0), (71, 7.0)]
    melody = [_n(p, t, 1.0) for (p, t) in tops]
    pedal = [_n(p - 24, t + 0.5, 0.4) for (p, t) in tops]
    sec = SectionMelody(name="s", length_beats=8.0, layers={"lead": melody + pedal})
    line = analyze_melody([sec], song_slug="t").sections[0].lines[0]
    assert line.ambitus == 5          # 72 - 67, the melody's true range
    assert line.note_count == 16      # both voices present in the raw notes
    assert line.onset_count == 8      # the reduced line is the 8 top-voice notes


# ---------------------------------------------------------------------------
# Segmentation reads the SAME reduced line (no raw-notes bypass).
# ---------------------------------------------------------------------------


def test_per_phrase_contour_reads_reduced_line_not_raw_notes():
    # Two top-voice phrases split by a rest, each shadowed by a staggered low pedal.
    # Per-phrase contour must come from the REDUCED top line, not the raw interleave.
    tops = [(67, 0.0), (69, 0.5), (71, 1.0), (72, 1.5),          # phrase A (rising)
            (72, 4.0), (71, 4.5), (69, 5.0), (67, 5.5)]          # phrase B (falling)
    melody = [_n(p, t, 0.5) for (p, t) in tops]
    pedal = [_n(p - 24, t + 0.25, 0.2) for (p, t) in tops]
    notes = melody + pedal

    reduced_contours = per_phrase_contours(_extract_melodic_line(notes))
    raw_contours = per_phrase_contours(notes)
    # The input is crafted so the bypass actually MATTERS for this line.
    assert reduced_contours != raw_contours

    sec = SectionMelody(name="s", length_beats=8.0, layers={"lead": notes})
    line = analyze_melody([sec], song_slug="t").sections[0].lines[0]
    if line.phrase_contours:  # populated only when the reduced line is multi-phrase
        assert list(line.phrase_contours) == reduced_contours
        # no phrase apex comes from the dropped pedal voice
        for _shape, apex_pitch, _pos in line.phrase_contours:
            assert apex_pitch is None or apex_pitch >= 67
