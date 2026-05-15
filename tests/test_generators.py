"""Smoke + tag-correctness tests for generators."""
from __future__ import annotations

from songwright.generators import drums, bass, harmony


def _has_tag(notes, tag):
    return [n for n in notes if tag in n.get("tags", [])]


def _well_formed(n):
    return (
        0 <= n["pitch"] <= 127
        and n["start_beats"] >= 0
        and n["duration_beats"] > 0
        and 0 <= n["velocity"] <= 127
    )


def test_kick_stumble_shape():
    notes = drums.kick_stumble(4)
    assert all(_well_formed(n) for n in notes)
    # Two kicks per bar (downbeat + late/early)
    assert len(notes) == 8
    # Strong every 4 -> first bar has the heaviest kick
    first = next(n for n in notes if n["start_beats"] == 0.0)
    assert first["velocity"] == 118
    assert "stumble" in first["tags"]


def test_lazy_snare_lay_back():
    notes = drums.lazy_snare(2)
    backbeats = sorted(n["start_beats"] for n in notes)
    # Each bar has snares at beat 1 + LAZY and beat 3 + LAZY
    assert backbeats == [1.04, 3.04, 5.04, 7.04]


def test_trip_hop_hats_alternation_and_boost():
    notes = drums.trip_hop_hats(4, boost_bars=[3])
    assert all(_well_formed(n) for n in notes)
    boost_ghosts = [n for n in notes if "boost" in n["tags"]]
    # Bar 3 has 4 ghost-offbeats
    assert len(boost_ghosts) == 4
    # All ghost notes are velocity 35 in non-boost bars
    plain_ghosts = [n for n in notes if "ghost" in n["tags"] and "boost" not in n["tags"]]
    assert all(n["velocity"] == 35 for n in plain_ghosts)


def test_trip_hop_pattern_composes():
    notes = drums.trip_hop_drum_pattern(4, fill_bars=[3])
    assert any("kick" in n["tags"] for n in notes)
    assert any("snare" in n["tags"] for n in notes)
    assert any("hat" in n["tags"] for n in notes)
    # Fill bar 3 brings ghost kicks + snares + open-hat lift
    assert _has_tag(notes, "ghost")
    assert _has_tag(notes, "lift")


def test_tresillo_bass_uses_root():
    notes = bass.tresillo_bass(38, bars=2)
    assert len(notes) == 12  # 6 hits per bar
    assert all(n["pitch"] == 38 for n in notes)
    assert all("tresillo_hit" in n["tags"] for n in notes)


def test_walking_bass_first_note_accents():
    notes = bass.walking_bass_to_next_chord(walk=[34, 36, 38, 41], start_beat=0.0)
    assert notes[0]["velocity"] == 100
    assert "downbeat" in notes[0]["tags"]
    assert all("walk" in n["tags"] for n in notes)


def test_chord_pad_stab():
    pad = harmony.chord_pad([53, 57, 62], start_beat=0.0, length_beats=8.0)
    assert len(pad) == 3
    assert all(n["duration_beats"] == 8.0 for n in pad)

    stab = harmony.chord_stab([53, 57, 62], start_beat=14.0)
    assert all(s["start_beats"] == 14.0 for s in stab)
    assert all("stab" in s["tags"] for s in stab)


def test_tresillo_pluck_cycles():
    notes = harmony.tresillo_pluck([62, 65, 69], bars=2)
    assert len(notes) == 12
    # Check pitches cycle through voicing
    pitches_first_bar = [n["pitch"] for n in notes[:6]]
    assert pitches_first_bar[0] == 62 and pitches_first_bar[3] == 62  # i % 3
