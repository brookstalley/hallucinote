"""Worked example (MICROTUNE Chunk 2): authoring a phrase in a non-12 tuning.

This module IS the worked ``build.py`` the plan calls for — ``author_cadence`` is
the compose-step body a song's ``build.py`` would contain, and the tests run it
end-to-end with **no Live**. The whole point of MICROTUNE's "isolation over
integration" bet is proven here: the composer computes MIDI integers with the
tuning mapper, then hands plain ints to the **existing, unmodified** generators
(``chord_tones`` / ``chord_pad``) and the **existing** note-insertion mutator.
Nothing downstream of the mapper knows a tuning is in play — Live's loaded tuning
reinterprets the MIDI numbers at playback (a manual step outside this code).

Read ``author_cadence`` as the template; the tests below verify (1) the emitted
notes land on the expected MIDI step indices, (2) they flow through the real DB
pipeline unchanged, and (3) for 12-TET the mapper is a transparent pass-through —
a 12-TET build is byte-identical to feeding the generators raw MIDI ints.
"""
from __future__ import annotations

import pytest

from hallucinote.db import init_db
from hallucinote.db import mutations as M
from hallucinote.db import queries as Q
from hallucinote.generators.harmony import chord_pad
from hallucinote.generators.primitives import chord_tones
from hallucinote.tuning.mapper import degree_to_midi
from hallucinote.tuning.model import TuningData
from hallucinote.tuning.store import load_song_tuning, persist_tuning

from .fixtures import EDO_12, EDO_19


# ---------------------------------------------------------------------------
# The worked example — the body of a microtonal song's build.py compose step.
# ---------------------------------------------------------------------------
def author_cadence(
    tuning: TuningData,
    *,
    triad_steps: tuple[int, int, int],
    fifth_steps: int,
) -> list[dict]:
    """A short I–V–I cadence authored in scale-*degree* indices of ``tuning``.

    ``triad_steps`` are the chord's intervals **in scale steps of this tuning**
    (e.g. a 19-EDO "major" triad is roughly ``(0, 6, 11)``); ``fifth_steps`` is
    how many steps up the dominant root sits. Every pitch is a plain MIDI int
    produced by :func:`degree_to_midi` — the generators never see the tuning.
    """
    # Tonic chord on scale degree 0 (the reference note).
    tonic_root = degree_to_midi(tuning, 0)
    tonic = chord_pad(
        chord_tones(tonic_root, list(triad_steps)),
        start_beat=0.0, length_beats=2.0,
    )
    # Dominant chord rooted `fifth_steps` scale steps up.
    dom_root = degree_to_midi(tuning, fifth_steps)
    dominant = chord_pad(
        chord_tones(dom_root, list(triad_steps)),
        start_beat=2.0, length_beats=2.0,
    )
    # Return to tonic.
    resolution = chord_pad(
        chord_tones(tonic_root, list(triad_steps)),
        start_beat=4.0, length_beats=4.0,
    )
    return tonic + dominant + resolution


def _pitches(notes: list[dict]) -> list[int]:
    return [n["pitch"] for n in notes]


# 19-EDO "major"-ish triad + fifth, in scale steps.
_TRIAD_19 = (0, 6, 11)
_FIFTH_19 = 11
# 12-EDO major triad + perfect fifth, in scale steps (= semitones).
_TRIAD_12 = (0, 4, 7)
_FIFTH_12 = 7


@pytest.fixture
def conn(tmp_path):
    c = init_db(tmp_path / "song.db")
    yield c
    c.close()


# ---------------------------------------------------------------------------
# (1) the example emits the expected MIDI step indices
# ---------------------------------------------------------------------------
def test_19edo_cadence_lands_on_expected_midi_indices():
    notes = author_cadence(EDO_19, triad_steps=_TRIAD_19, fifth_steps=_FIFTH_19)
    # ref=60; tonic = 60 + (0,6,11); dominant rooted 11 steps up = 71 + (0,6,11).
    assert _pitches(notes) == [
        60, 66, 71,   # I
        71, 77, 82,   # V (a 19-EDO fifth, 11 steps, above the tonic)
        60, 66, 71,   # I
    ]


# ---------------------------------------------------------------------------
# (2) the notes flow through the real, unchanged DB pipeline
# ---------------------------------------------------------------------------
def test_phrase_inserts_through_unchanged_pipeline(conn, tmp_path):
    song = M.create_song(conn, name="microtune_demo", key="C")
    # Pull-from-Live is pre-seeded here: persist a 19-EDO tuning + its .ascl.
    persist_tuning(conn, song_id=song, song_dir=str(tmp_path), tuning=EDO_19)

    # The compose step reads the stored tuning and authors the phrase.
    tuning = load_song_tuning(conn, song)
    notes = author_cadence(tuning, triad_steps=_TRIAD_19, fifth_steps=_FIFTH_19)

    track = M.create_track(conn, song_id=song, track_index=1, name="Keys")
    clip = M.create_clip(conn, track_id=track, slot=1, length_beats=8.0, name="cadence")
    M.insert_notes(conn, clip_id=clip, notes=notes)

    stored = Q.get_notes_for_clip(conn, clip)
    assert sorted(n["pitch"] for n in stored) == sorted(_pitches(notes))
    # Every authored pitch is a valid MIDI note — the mapper's 0–127 clamp keeps
    # the notes table's CHECK(pitch BETWEEN 0 AND 127) satisfied.
    assert all(0 <= n["pitch"] <= 127 for n in stored)


# ---------------------------------------------------------------------------
# (3) for 12-TET the mapper is transparent — byte-identical to raw ints
# ---------------------------------------------------------------------------
def test_12tet_build_is_byte_identical_to_raw_ints():
    # Build via the tuning path (12-EDO, ref=60)...
    via_tuning = author_cadence(EDO_12, triad_steps=_TRIAD_12, fifth_steps=_FIFTH_12)

    # ...and build the SAME shape by calling the generators with literal MIDI
    # ints, no tuning layer at all (root 60, dominant a perfect fifth = 67).
    via_raw = (
        chord_pad(chord_tones(60, list(_TRIAD_12)), start_beat=0.0, length_beats=2.0)
        + chord_pad(chord_tones(67, list(_TRIAD_12)), start_beat=2.0, length_beats=2.0)
        + chord_pad(chord_tones(60, list(_TRIAD_12)), start_beat=4.0, length_beats=4.0)
    )
    # Identical NoteDicts → the generators are unchanged and the mapper adds
    # nothing for 12-TET (the 99.99% pay zero cost).
    assert via_tuning == via_raw


def test_generators_are_tuning_unaware():
    # chord_tones can't tell a tuning-mapped root from a literal int — it just
    # adds integers. This is the structural guarantee, restated at the unit.
    mapped_root = degree_to_midi(EDO_19, 0)
    assert chord_tones(mapped_root, [0, 6, 11]) == chord_tones(60, [0, 6, 11])
