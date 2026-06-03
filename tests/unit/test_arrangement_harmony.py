"""Chunk D — the harmony axis wired into the Arrangement.

Per-section key/mode/progression, the song-level harmonic_plan + "inherit"
slicing, the harmonic_curve read-side view, graceful degradation when a section
declares no harmony, and the PlacedSection -> SectionLint adapter feeding the
conformance lens end-to-end.
"""
from __future__ import annotations

import pytest

from hallucinote.arrangement import Arrangement
from hallucinote.generators import harmony
from hallucinote.theory import Progression, lint_harmony, mode

E = 4


def test_section_without_harmony_degrades_to_none():
    arr = Arrangement()
    arr.section("intro", function="intro", bars=4, layers={"drums": []})
    p = arr.plan()[0]
    assert p.key_pc is None and p.mode is None and p.progression is None


def test_per_section_progression_resolves_key_and_mode():
    prog = Progression.of("E", "Dorian", ["Em7", "A7"], beats_per_chord=4.0)
    arr = Arrangement()
    arr.section("verse", function="verse", bars=2, layers={}, progression=prog)
    p = arr.plan()[0]
    assert p.progression is prog
    assert p.key_pc == E
    assert p.mode is mode("Dorian")


def test_key_mode_independent_of_progression():
    # A modal drone: declare a mode with no chord changes — still linted as modal.
    arr = Arrangement()
    arr.section("drone", function="intro", bars=4, layers={}, key="E", mode="Phrygian")
    p = arr.plan()[0]
    assert p.key_pc == E
    assert p.mode is mode("Phrygian")
    assert p.progression is None


def test_explicit_key_mode_overrides_progression_defaults():
    prog = Progression.of("E", "Dorian", ["Em7"], beats_per_chord=4.0)
    arr = Arrangement()
    arr.section("v", function="verse", bars=2, layers={}, progression=prog,
                key="A", mode="Phrygian")
    p = arr.plan()[0]
    assert p.key_pc == 9          # A overrides the progression's E
    assert p.mode is mode("Phrygian")


def test_song_level_plan_inherit_slices_per_section():
    plan = Progression.of("E", "Dorian", ["Em7", "A7", "Cmaj7", "Bm7"],
                          beats_per_chord=4.0)  # 16 beats
    arr = Arrangement().harmonic_plan(plan)
    arr.section("v1", function="verse", bars=2, layers={}, progression="inherit")
    arr.section("v2", function="verse", bars=2, layers={}, progression="inherit")
    placed = arr.plan()
    assert placed[0].progression.changes[0].chord.symbol == "Em7"
    assert placed[1].progression.changes[0].chord.symbol == "Cmaj7"   # sliced + rebased
    assert placed[1].progression.changes[0].start_beat == 0.0


def test_inherit_without_plan_fails_loud():
    arr = Arrangement()
    arr.section("v", function="verse", bars=2, layers={}, progression="inherit")
    with pytest.raises(ValueError, match="no harmonic_plan"):
        arr.plan()


def test_bad_progression_string_rejected():
    arr = Arrangement()
    with pytest.raises(ValueError, match="must be 'inherit'"):
        arr.section("v", function="verse", bars=2, layers={}, progression="borrow")


def test_harmonic_curve_reports_key_area_and_distinct_chords():
    arr = Arrangement()
    arr.section("verse", function="verse", bars=2, layers={},
                progression=Progression.of("E", "Dorian", ["Em7", "A7"], beats_per_chord=4.0))
    arr.section("chorus", function="chorus", bars=2, layers={},
                progression=Progression.of("E", "Phrygian", ["Em", "F"], beats_per_chord=4.0))
    arr.section("drone", function="outro", bars=2, layers={})  # no harmony
    assert arr.harmonic_curve == [
        ("verse", E, "Dorian", 2),
        ("chorus", E, "Phrygian", 2),
        ("drone", None, None, 0),
    ]


# ---------------------------------------------------------------------------
# End-to-end: section_lints -> lint_harmony
# ---------------------------------------------------------------------------


def test_section_lints_feed_the_conformance_lens_clean():
    prog = Progression.of("E", "Dorian", ["Em7", "A7"], beats_per_chord=4.0)
    skank = harmony.reggae_skank(prog, bars=2, register=3)  # voices BOTH chords
    arr = Arrangement()
    arr.section("verse", function="verse", bars=2, layers={"03 Gtr": skank},
                progression=prog)
    report = lint_harmony(arr.section_lints(harmony_layers=["03 Gtr"]), song_slug="t")
    assert report.ok is True
    assert report.sections[0].sounded_distinct_chords == 2


def test_section_lints_name_a_frozen_part_as_stasis_without_blocking():
    # The adapter feeds a pedaled part to the lens. Per LNT-1V9K the lens NAMES it
    # in stasis_sections (the signal a song's test gates on) but never blocks —
    # a ruler, not a stamp.
    declared = Progression.of("E", "Dorian", ["Em7", "A7"], beats_per_chord=4.0)
    frozen = Progression.of("E", "Dorian", ["Em7"], beats_per_chord=4.0)
    skank = harmony.reggae_skank(frozen, bars=2, register=3)  # pedals Em7
    arr = Arrangement()
    arr.section("verse", function="verse", bars=2, layers={"03 Gtr": skank},
                progression=declared)
    report = lint_harmony(arr.section_lints(harmony_layers=["03 Gtr"]), song_slug="t")
    assert report.stasis_sections == ("verse",)   # named — a song's test can gate
    assert report.ok is True                        # but the lens never blocks
    assert report.blocking == ()
