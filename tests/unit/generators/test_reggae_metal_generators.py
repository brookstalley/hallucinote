"""Tests for the reggae / metal generator idioms.

Promoted from sun-zone-done (the flagship demo song) into the shared
`hallucinote.generators` package. These pin the genre semantics — the
*defining* moves of each idiom — independently of any one song. The
byte-level "this song still sounds identical" guard lives in
`songs/sun-zone-done/tests/test_sun_zone_done_build.py::test_notes_match_baseline`.
"""
from __future__ import annotations

import pytest

from hallucinote.generators import bass, drums, harmony
from hallucinote.generators.kit import Kit
from hallucinote.generators.primitives import METAL_GALLOP_OFFSETS

_KIT = Kit.gm_default()


def _well_formed(n):
    return (
        0 <= n["pitch"] <= 127
        and n["start_beats"] >= 0
        and n["duration_beats"] > 0
        and 0 <= n["velocity"] <= 127
        and isinstance(n["tags"], list)
    )


def _at(notes, pitch=None, tag=None):
    out = notes
    if pitch is not None:
        out = [n for n in out if n["pitch"] == pitch]
    if tag is not None:
        out = [n for n in out if tag in n["tags"]]
    return out


# --------------------------------------------------------------------------
# Reggae one-drop drums
# --------------------------------------------------------------------------


def test_one_drop_drops_the_downbeat_kick():
    """The defining reggae move: NO kick on beat 1. Kick only on even bars,
    and even then not on the downbeat-of-1 of odd bars."""
    notes = drums.reggae_one_drop(4, kit=_KIT)
    assert all(_well_formed(n) for n in notes)
    kicks = sorted(n["start_beats"] for n in _at(notes, pitch=_KIT.kick))
    # Even bars (0, 2) only -> kicks at 0.0 and 8.0, never on bars 1/3.
    assert kicks == [0.0, 8.0]


def test_one_drop_snare_on_three_laid_back():
    notes = drums.reggae_one_drop(1, kit=_KIT, lazy=0.04)
    snares = _at(notes, pitch=_KIT.snare)
    assert len(snares) == 1
    # Snare on beat 3, dragged 0.04 behind the click.
    assert snares[0]["start_beats"] == pytest.approx(2.0 + 0.04)


def test_one_drop_open_hat_every_fourth_bar():
    notes = drums.reggae_one_drop(8, kit=_KIT)
    open_hats = _at(notes, pitch=_KIT.hat_open)
    # Bars 3 and 7 (1-indexed 4th & 8th) get the lift.
    assert sorted(n["start_beats"] for n in open_hats) == \
        pytest.approx([12.0 + 3.5 + 0.04, 28.0 + 3.5 + 0.04])


# --------------------------------------------------------------------------
# Metal gallop drums
# --------------------------------------------------------------------------


def test_metal_gallop_uses_the_gallop_cell():
    notes = drums.metal_gallop(1, kit=_KIT, crash_bars=())
    kicks = sorted(n["start_beats"] for n in _at(notes, pitch=_KIT.kick))
    assert kicks == list(METAL_GALLOP_OFFSETS)


def test_metal_gallop_crash_only_on_named_bars():
    notes = drums.metal_gallop(4, kit=_KIT, crash_bars=(0,))
    crashes = _at(notes, tag="crash")
    assert len(crashes) == 1
    assert crashes[0]["start_beats"] == 0.0
    # Default is a section-entrance crash on the first bar.
    assert drums.metal_gallop(2, kit=_KIT) and \
        len(_at(drums.metal_gallop(2, kit=_KIT), tag="crash")) == 1


def test_metal_gallop_snare_on_two_and_four():
    notes = drums.metal_gallop(1, kit=_KIT, crash_bars=())
    snares = sorted(n["start_beats"] for n in _at(notes, pitch=_KIT.snare))
    assert snares == [1.0, 3.0]


# --------------------------------------------------------------------------
# Reggae bass
# --------------------------------------------------------------------------


def test_reggae_bass_long_root_short_offbeat_fifths():
    notes = bass.reggae_offbeat_bass(40, bars=1, push=0.02)
    assert all(_well_formed(n) for n in notes)
    # root(1.4) on 1, fifth(0.4) on 2&, octave(1.4) on 3, fifth(0.4) on 4&
    durs = [n["duration_beats"] for n in notes]
    assert durs == [1.4, 0.4, 1.4, 0.4]
    assert notes[0]["pitch"] == 40 and notes[2]["pitch"] == 52  # root, octave
    assert notes[1]["pitch"] == 47 and notes[3]["pitch"] == 47  # fifth both
    assert [n["start_beats"] for n in notes] == \
        pytest.approx([0.02, 1.52, 2.02, 3.52])


# --------------------------------------------------------------------------
# Metal pedal bass — the negative-beat guard
# --------------------------------------------------------------------------


def test_metal_pedal_first_note_not_pushed_negative():
    """The push is -0.01, but the very first 16th at absolute 0.0 must NOT be
    pushed negative (Live has no negative-beat region; the mutator refuses it)."""
    notes = bass.metal_pedal_16ths(40, bars=1, start_beat=0.0, push=-0.01)
    assert notes[0]["start_beats"] == 0.0
    assert notes[1]["start_beats"] == pytest.approx(0.25 - 0.01)
    assert all(n["start_beats"] >= 0.0 for n in notes)


def test_metal_pedal_pushed_when_section_starts_later():
    """A section that doesn't start at 0 pushes every 16th, including its first."""
    notes = bass.metal_pedal_16ths(40, bars=1, start_beat=64.0, push=-0.01)
    assert notes[0]["start_beats"] == pytest.approx(64.0 - 0.01)


def test_metal_pedal_count_and_pitch():
    notes = bass.metal_pedal_16ths(40, bars=2)
    assert len(notes) == 32
    assert {n["pitch"] for n in notes} == {40}


# --------------------------------------------------------------------------
# Reggae skank + organ bubble
# --------------------------------------------------------------------------


def test_skank_chucks_offbeats_only():
    voicing = [52, 55, 59, 62]
    notes = harmony.reggae_skank(voicing, bars=1, lazy=0.06)
    starts = sorted({n["start_beats"] for n in notes})
    # Only the "and" of 2 and the "and" of 4 — nothing on downbeats.
    assert starts == pytest.approx([1.5 + 0.06, 3.5 + 0.06])
    assert len(notes) == len(voicing) * 2
    assert all(n["duration_beats"] == 0.30 for n in notes)


def test_organ_bubble_on_every_offbeat_eighth():
    voicing = [55, 59, 64]
    notes = harmony.organ_bubble(voicing, bars=1, lag=0.04)
    starts = sorted({n["start_beats"] for n in notes})
    assert starts == pytest.approx([0.5 + 0.04, 1.5 + 0.04, 2.5 + 0.04, 3.5 + 0.04])


# --------------------------------------------------------------------------
# Palm-mute power chords — and the genre-coordination contract
# --------------------------------------------------------------------------


def test_power_chords_are_root_fifth_octave():
    notes = harmony.palm_mute_power_chords(52, bars=1)
    # Three voices per hit.
    first_hit = _at(notes)[:3]
    assert sorted(n["pitch"] for n in first_hit) == [52, 59, 64]
    assert all(n["duration_beats"] == 0.18 for n in notes)


def test_guitar_gallop_locks_with_drum_gallop():
    """The coordination IS the genre: the palm-muted guitar and the kick
    gallop must hit on the same rhythmic cell."""
    gtr = harmony.palm_mute_power_chords(52, bars=1)
    drm = drums.metal_gallop(1, kit=_KIT, crash_bars=())
    gtr_roots = sorted({n["start_beats"] for n in gtr})
    drm_kicks = sorted({n["start_beats"] for n in _at(drm, pitch=_KIT.kick)})
    assert gtr_roots == drm_kicks == list(METAL_GALLOP_OFFSETS)


# --------------------------------------------------------------------------
# feel parameter threads through every idiom
# --------------------------------------------------------------------------


@pytest.mark.parametrize("call", [
    lambda: drums.reggae_one_drop(2, kit=_KIT, feel={2.0: 0.1}),
    lambda: drums.metal_gallop(2, kit=_KIT, feel={0.0: 0.1}),
    lambda: bass.reggae_offbeat_bass(40, bars=2, feel={0.0: 0.1}),
    lambda: bass.metal_pedal_16ths(40, bars=2, start_beat=8.0, feel={0.5: 0.1}),
    lambda: harmony.reggae_skank([52, 59], bars=2, feel={1.5: 0.1}),
    lambda: harmony.organ_bubble([52, 59], bars=2, feel={0.5: 0.1}),
    lambda: harmony.palm_mute_power_chords(52, bars=2, feel={0.0: 0.1}),
])
def test_feel_is_accepted_and_shifts(call):
    """Every promoted idiom accepts a feel dict (microtiming is authorship)."""
    notes = call()
    assert notes and all(_well_formed(n) for n in notes)
