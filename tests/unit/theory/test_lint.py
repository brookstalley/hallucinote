"""Chunk B / LNT-1V9K — chord-aware reggae_skank + the conformance lens.

The headline regression: feed the SAME declared 2-chord progression two ways —
once through the chord-aware skank (which voices both) and once through a frozen
single-chord progression (which pedals one) — and assert the lens NAMES the
second as harmonic stasis (``stasis_sections``, the signal a song's test gates
on) and not the first. Per LNT-1V9K the lens is a ruler, not a stamp: stasis is a
loud WARNING, never a build block — a deliberate field (or 4'33") must ship.
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


def test_frozen_skank_under_a_moving_progression_warns_but_never_blocks():
    # Pedal one chord under a declared Em7->A7 change — the realization bug-shape.
    # A build-time lens is a ruler, not a stamp (LNT-1V9K): it surfaces a LOUD
    # WARNING and names the section in stasis_sections (the regression signal a
    # song asserts on), but it NEVER blocks the build.
    notes = harmony.reggae_skank(_FROZEN, bars=2, register=3)
    section = SectionLint("verse", 8.0, _DECLARED, {"03 Gtr": notes},
                          harmony_layers=("03 Gtr",))
    report = lint_harmony([section], song_slug="toy")
    sec = report.sections[0]
    assert sec.declared_distinct_chords == 2
    assert sec.sounded_distinct_chords == 1   # it pedalled
    assert sec.harmonic_stasis is True        # the bug-shape is still NAMED...
    assert report.stasis_sections == ("verse",)  # ...so a song's test can gate
    assert report.ok is True                  # ...but the lens never blocks
    assert report.blocking == ()
    assert any(f.kind == "harmonic-stasis" and f.severity == "warning"
               for f in report.findings)


# ---------------------------------------------------------------------------
# Graceful degradation + intentional stasis
# ---------------------------------------------------------------------------


def test_bassless_section_with_declared_movement_is_absence_not_a_block():
    # The LNT-1V9K trigger: a deliberately bare section (drums + bass drop out)
    # under a declared multi-chord progression. The harmony layer is present but
    # TACET — sounded == 0. Absence is NOT stasis (nothing can realize movement
    # with no harmonic agent present), so it is an INFO coaching question, never a
    # block, and is NOT counted in stasis_sections.
    section = SectionLint("break", 8.0, _DECLARED, {"03 Gtr": []},
                          harmony_layers=("03 Gtr",))
    report = lint_harmony([section], song_slug="toy")
    sec = report.sections[0]
    assert sec.sounded_distinct_chords == 0
    assert sec.harmonic_stasis is False          # absence != the pedal bug
    assert report.stasis_sections == ()
    assert report.ok is True
    assert any(f.kind == "harmonic-absence" and f.severity == "info"
               for f in sec.findings)


def test_no_harmony_finding_ever_blocks_the_build():
    # The LNT-1V9K verifiable signal: ship a pedaled, a bass-less, and a long
    # static section together — the lens reports loudly but NOTHING blocks.
    pedaled = SectionLint("pedaled", 8.0, _DECLARED,
                          {"g": harmony.reggae_skank(_FROZEN, bars=2, register=3)},
                          harmony_layers=("g",))
    bare = SectionLint("bare", 8.0, _DECLARED, {"g": []}, harmony_layers=("g",))
    drone = SectionLint("drone", 32.0, _FROZEN,
                        {"g": harmony.reggae_skank(_FROZEN, bars=8, register=3)},
                        harmony_layers=("g",))
    report = lint_harmony([pedaled, bare, drone], song_slug="toy")
    assert report.ok is True
    assert report.blocking == ()
    # ...and it still SURFACES everything (a ruler measures loudly).
    kinds = {f.kind for f in report.findings}
    assert {"harmonic-stasis", "harmonic-absence", "ambition"} <= kinds


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
