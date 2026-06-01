"""Chunk B — the vertical slice: chord-aware reggae_skank + the conformance lens.

The headline is the regression test that makes "a whole song pedalling one
chord" a BLOCKING test failure: feed the SAME declared 2-chord progression two
ways — once through the chord-aware skank (which voices both) and once through a
frozen single-chord progression (which pedals one) — and assert the lens flags
the second as harmonic stasis and not the first.
"""
from __future__ import annotations

from hallucinote.generators import harmony
from hallucinote.theory import Progression, lint_harmony
from hallucinote.theory.lint import SectionLint
from hallucinote.theory.model import Change, Chord, mode

# A declared progression that MOVES (the verse intent): Em7 -> A7.
_DECLARED = Progression.of("E", "Dorian", ["Em7", "A7"], beats_per_chord=4.0)
# A frozen single chord (the bug): everything pedals Em7.
_FROZEN = Progression.of("E", "Dorian", ["Em7"], beats_per_chord=4.0)


def _note(pitch, start, dur=0.5, vel=80):
    return {"pitch": pitch, "start_beats": start, "duration_beats": dur,
            "velocity": vel, "tags": []}


# ---------------------------------------------------------------------------
# THE regression — the structural fix for the one-chord bug
# ---------------------------------------------------------------------------


def test_chord_aware_skank_voices_both_chords_and_passes():
    notes = harmony.reggae_skank(_DECLARED, bars=2, register=3)
    section = SectionLint("verse", 8.0, _DECLARED, {"03 Gtr": notes},
                          harmony_layers=("03 Gtr",))
    report = lint_harmony([section], song_slug="toy")
    sec = report.sections[0]
    assert sec.declared is True
    assert sec.declared_distinct_chords == 2
    assert sec.sounded_distinct_chords == 2   # the skank actually MOVED
    assert sec.harmonic_stasis is False
    assert report.ok is True
    assert report.stasis_sections == ()


def test_frozen_skank_under_a_moving_progression_is_flagged_blocking():
    # The OLD behavior: declare Em7->A7 but pedal one chord. This is the bug.
    notes = harmony.reggae_skank(_FROZEN, bars=2, register=3)
    section = SectionLint("verse", 8.0, _DECLARED, {"03 Gtr": notes},
                          harmony_layers=("03 Gtr",))
    report = lint_harmony([section], song_slug="toy")
    sec = report.sections[0]
    assert sec.declared_distinct_chords == 2
    assert sec.sounded_distinct_chords == 1   # it pedalled
    assert sec.harmonic_stasis is True
    assert report.ok is False
    assert report.stasis_sections == ("verse",)
    assert any(f.kind == "harmonic-stasis" and f.severity == "blocking"
               for f in report.blocking)


# ---------------------------------------------------------------------------
# Graceful degradation + intentional stasis
# ---------------------------------------------------------------------------


def test_no_declared_harmony_is_skipped_not_failed():
    section = SectionLint("intro", 8.0, None, {"03 Gtr": [_note(52, 0.0)]})
    report = lint_harmony([section], song_slug="toy")
    sec = report.sections[0]
    assert sec.declared is False
    assert sec.harmonic_stasis is False
    assert report.ok is True
    assert sec.findings == ()


def test_declared_single_chord_is_not_stasis_but_coaches_when_long():
    # A modal drone / minimalist field: ONE declared chord is legitimate, never
    # flagged as the bug. A long static stretch earns an INFO coaching question.
    notes = harmony.reggae_skank(_FROZEN, bars=8, register=3)  # 32 beats of Em7
    section = SectionLint("drone", 32.0, _FROZEN, {"03 Gtr": notes},
                          harmony_layers=("03 Gtr",))
    report = lint_harmony([section], song_slug="toy")
    sec = report.sections[0]
    assert sec.harmonic_stasis is False        # declared==1 -> not the bug
    assert report.ok is True                    # info never gates
    assert any(f.kind == "ambition" and f.severity == "info" for f in sec.findings)


# ---------------------------------------------------------------------------
# Conformance metrics: out-of-chord (warning) and out-of-mode (warning)
# ---------------------------------------------------------------------------


def test_out_of_chord_passing_tones_warn_but_dont_gate():
    # Half the notes are F# (pc 6): in E Dorian, but NOT in the Em7 chord.
    em7 = Progression.of("E", "Dorian", ["Em7"], beats_per_chord=4.0)
    notes = [_note(52, 0.0), _note(54, 1.0)]  # E (in chord), F# (in mode, not chord)
    section = SectionLint("v", 4.0, em7, {"lead": notes}, harmony_layers=("lead",))
    report = lint_harmony([section], song_slug="toy")
    lh = report.sections[0].layers[0]
    assert lh.out_of_chord_fraction == 0.5
    assert lh.out_of_mode_fraction == 0.0      # F# is diatonic to E Dorian
    assert report.ok is True                    # warnings don't gate
    assert any(f.kind == "out-of-chord" and f.severity == "warning"
               for f in report.findings)


def test_out_of_mode_chromaticism_warns():
    em7 = Progression.of("E", "Dorian", ["Em7"], beats_per_chord=4.0)
    notes = [_note(52, 0.0), _note(56, 1.0)]  # E (diatonic), G# (pc 8, NOT in E Dorian)
    section = SectionLint("v", 4.0, em7, {"lead": notes}, harmony_layers=("lead",))
    report = lint_harmony([section], song_slug="toy")
    lh = report.sections[0].layers[0]
    assert lh.out_of_mode_fraction == 0.5
    assert any(f.kind == "out-of-mode" for f in report.findings)


# ---------------------------------------------------------------------------
# The slash-bass pivot and the polymodal split are in-chord (not false-flagged)
# ---------------------------------------------------------------------------


def test_slash_bass_note_counts_as_in_chord():
    # Bass plays C# (pc 1) under Em/C# — that IS the chord's bass, in-chord.
    prog = Progression(key_pc=4, mode=mode("Dorian"),
                       changes=(Change(Chord.parse("Em/C#"), 0.0, 4.0),))
    notes = [_note(49, 0.0)]  # C#3 = pc 1
    section = SectionLint("hinge", 4.0, prog, {"bass": notes}, harmony_layers=("bass",))
    lh = lint_harmony([section], song_slug="toy").sections[0].layers[0]
    assert lh.out_of_chord_fraction == 0.0


def test_split_chord_accepts_both_worlds():
    # The fusion sonority: an Em carrying both C# (Dorian) and C (Phrygian).
    fused = Chord.split_chord(Chord.parse("Em/C#"), Chord.parse("Em/C"))
    prog = Progression(key_pc=4, mode=mode("Dorian"),
                       changes=(Change(fused, 0.0, 4.0),))
    notes = [_note(48, 0.0), _note(49, 1.0)]  # C (pc 0) and C# (pc 1) — both worlds
    section = SectionLint("climax", 4.0, prog, {"organ": notes}, harmony_layers=("organ",))
    lh = lint_harmony([section], song_slug="toy").sections[0].layers[0]
    assert lh.out_of_chord_fraction == 0.0    # both accepted at once
