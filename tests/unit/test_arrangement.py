"""Tests for hallucinote.arrangement — the song-structure layer.

Two halves: the pure planning/vary rulers (no DB), and a materialize()
integration test proving the module emits correct DB rows through the mutators
(the Chunk-1 vertical slice — architecture end-to-end through the data layer).
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from hallucinote.arrangement import Arrangement, Motif, vary
from hallucinote.db import init_db, mutations as M, queries as Q
from hallucinote.generators import variations as V


def _n(pitch, start, dur=1.0, vel=90, tags=None):
    return {
        "pitch": pitch,
        "start_beats": start,
        "duration_beats": dur,
        "velocity": vel,
        "tags": tags if tags is not None else [],
    }


KICK = [_n(36, 0.0), _n(36, 2.0)]
BASS = [_n(40, 0.0, 2.0), _n(40, 2.0, 2.0)]
ORGAN = [_n(55, 1.5), _n(59, 3.5)]


# ==========================================================================
# Pure planning
# ==========================================================================


def test_plan_assigns_sequential_bar_ranges():
    arr = (
        Arrangement()
        .section("intro", function="intro", bars=8, layers={"Drums": KICK})
        .section("verse", function="verse", bars=16, layers={"Drums": KICK})
        .section("chorus", function="chorus", bars=8, layers={"Drums": KICK})
    )
    placed = arr.plan()
    assert [(p.name, p.start_bar, p.end_bar) for p in placed] == [
        ("intro", 1, 9),
        ("verse", 9, 25),
        ("chorus", 25, 33),
    ]
    assert arr.total_bars == 32


def test_plan_respects_custom_start_bar():
    arr = Arrangement().section("a", function="verse", bars=4, layers={"Drums": KICK})
    assert arr.plan(start_bar=17)[0].start_bar == 17


def test_section_rejects_nonpositive_bars():
    with pytest.raises(ValueError, match="bars must be > 0"):
        Arrangement().section("x", function="verse", bars=0, layers={})


def test_energy_curve_reports_authored_intensities():
    arr = (
        Arrangement()
        .section("verse", function="verse", bars=8, layers={}, energy=0.3)
        .section("chorus", function="chorus", bars=8, layers={}, energy=0.9)
    )
    assert arr.energy_curve == [("verse", 0.3), ("chorus", 0.9)]


def test_section_does_not_alias_caller_layers():
    caller_kick = [_n(36, 0.0), _n(36, 2.0)]  # local — must not touch shared constants
    arr = Arrangement().section("a", function="verse", bars=4, layers={"Drums": caller_kick})
    caller_kick.append(_n(38, 1.0))  # mutate caller's list after the fact
    assert len(arr.plan()[0].layers["Drums"]) == 2  # section took a copy


# ==========================================================================
# Motifs
# ==========================================================================


def test_motif_registration_and_lookup():
    arr = Arrangement()
    m = arr.motif("hook", KICK)
    assert isinstance(m, Motif)
    assert arr.get_motif("hook").notes == KICK


def test_motif_is_defensively_copied():
    arr = Arrangement()
    src = [_n(36, 0.0)]
    arr.motif("hook", src)
    src[0]["pitch"] = 99
    assert arr.get_motif("hook").notes[0]["pitch"] == 36


def test_duplicate_motif_raises():
    arr = Arrangement()
    arr.motif("hook", KICK)
    with pytest.raises(ValueError, match="already registered"):
        arr.motif("hook", BASS)


def test_get_unknown_motif_raises():
    with pytest.raises(KeyError, match="not registered"):
        Arrangement().get_motif("nope")


# ==========================================================================
# vary() — cumulative-development deltas
# ==========================================================================

BASE = {"Drums": KICK, "Bass": BASS, "Organ": ORGAN}


def test_vary_strip_removes_layers():
    out = vary(BASE, strip=["Organ"])
    assert set(out) == {"Drums", "Bass"}


def test_vary_add_introduces_or_replaces_layer():
    steel = [_n(72, 0.5)]
    out = vary(BASE, add={"Steel": steel})
    assert out["Steel"] == steel
    # replace existing
    out2 = vary(BASE, add={"Organ": steel})
    assert out2["Organ"] == steel


def test_vary_transform_applies_to_existing_layer():
    out = vary(BASE, transform={"Drums": lambda ns: V.transpose(ns, 0)})
    assert out["Drums"] == KICK  # transpose 0 is identity but proves the wiring
    out2 = vary(BASE, transform={"Bass": lambda ns: V.augment(ns, 2.0)})
    assert [n["start_beats"] for n in out2["Bass"]] == [0.0, 4.0]


def test_vary_application_order_is_strip_transform_add():
    # transform names a stripped layer -> no-op (already gone); add can re-create it.
    out = vary(
        BASE,
        strip=["Organ"],
        transform={"Organ": lambda ns: V.transpose(ns, 12)},  # Organ already stripped
        add={"Organ": [_n(60, 0.0)]},
    )
    assert out["Organ"] == [_n(60, 0.0)]  # the add wins; transform saw nothing


def test_vary_is_pure():
    out = vary(BASE, strip=["Organ"], add={"Drums": [_n(40, 0.0)]})
    assert set(BASE) == {"Drums", "Bass", "Organ"}  # base untouched
    assert BASE["Drums"] == KICK
    out["Bass"].append(_n(99, 0.0))
    assert len(BASE["Bass"]) == 2  # nested lists copied


# ---- deep-copy depth: in-place note-dict + tags mutation must not leak --------
# (Critic Chunk-1 WARNING: copy depth must match variations._copy.)


def test_motif_deep_copies_note_dicts_and_tags():
    arr = Arrangement()
    src = [_n(36, 0.0, tags=["kick"])]
    arr.motif("hook", src)
    src[0]["pitch"] = 99           # in-place scalar mutation
    src[0]["tags"].append("muted")  # in-place nested-list mutation
    stored = arr.get_motif("hook").notes[0]
    assert stored["pitch"] == 36
    assert stored["tags"] == ["kick"]


def test_section_deep_copies_note_dicts_and_tags():
    caller = [_n(36, 0.0, tags=["kick"])]
    arr = Arrangement().section("a", function="verse", bars=4, layers={"Drums": caller})
    caller[0]["pitch"] = 99
    caller[0]["tags"].append("muted")
    stored = arr.plan()[0].layers["Drums"][0]
    assert stored["pitch"] == 36
    assert stored["tags"] == ["kick"]


def test_vary_deep_copies_note_dicts_and_tags():
    base = {"Drums": [_n(36, 0.0, tags=["kick"])]}
    out = vary(base, add={"Bass": [_n(40, 0.0, tags=["root"])]})
    # mutate both the base note and the added note in place
    base["Drums"][0]["tags"].append("x")
    out_bass_src_unaffected = out["Bass"][0]["tags"] == ["root"]
    assert out["Drums"][0]["tags"] == ["kick"]  # base mutation didn't leak into out
    assert out_bass_src_unaffected


# ==========================================================================
# materialize() — integration through the mutators
# ==========================================================================


@pytest.fixture
def db_conn(tmp_path: Path) -> sqlite3.Connection:
    conn = init_db(tmp_path / "arr.db")
    yield conn
    conn.close()


@pytest.fixture
def song_and_tracks(db_conn):
    song_id = M.create_song(db_conn, name="t", title="T", key="Em")
    tracks = {}
    for i, name in enumerate(["Drums", "Bass", "Organ"], start=1):
        tracks[name] = M.create_track(db_conn, song_id=song_id, track_index=i, name=name)
    return song_id, tracks


def _two_section_arrangement():
    return (
        Arrangement()
        .section("verse", function="verse", bars=4, energy=0.4, genre="reggae",
                 layers={"Drums": KICK, "Bass": BASS, "Organ": ORGAN})
        # chorus: Organ tacet (absent from the layer map)
        .section("chorus", function="chorus", bars=4, energy=0.9, genre="metal",
                 layers={"Drums": KICK, "Bass": BASS})
    )


def test_materialize_creates_expected_rows(db_conn, song_and_tracks):
    song_id, tracks = song_and_tracks
    created = _two_section_arrangement().materialize(
        db_conn, song_id=song_id, tracks=tracks
    )
    assert created == {
        "clips": 5,       # verse 3 + chorus 2
        "notes": 2 + 2 + 2 + 2 + 2,
        "placements": 5,
        "sections": 2,
        "cues": 2,
    }


def test_materialize_section_and_cue_bar_ranges(db_conn, song_and_tracks):
    song_id, tracks = song_and_tracks
    _two_section_arrangement().materialize(db_conn, song_id=song_id, tracks=tracks)

    sections = {s["name"]: (s["start_bar"], s["end_bar"]) for s in Q.get_sections_for_song(db_conn, song_id)}
    assert sections == {"verse": (1.0, 5.0), "chorus": (5.0, 9.0)}

    cues = {c["name"]: c["position_bar"] for c in Q.get_cue_points(db_conn, song_id)}
    assert cues == {"verse": 1.0, "chorus": 5.0}


def test_materialize_layer_presence_and_notes(db_conn, song_and_tracks):
    song_id, tracks = song_and_tracks
    _two_section_arrangement().materialize(db_conn, song_id=song_id, tracks=tracks)

    # Organ plays only in the verse (tacet in chorus) -> exactly one clip.
    organ_clips = Q.get_clips_for_track(db_conn, tracks["Organ"])
    assert len(organ_clips) == 1
    assert organ_clips[0]["section_role"] == "verse"

    # Drums play both sections -> two clips at slots 1 and 2.
    drum_clips = sorted(Q.get_clips_for_track(db_conn, tracks["Drums"]), key=lambda c: c["slot"])
    assert [c["slot"] for c in drum_clips] == [1, 2]

    # Notes round-tripped: the verse kick clip has KICK's two notes.
    verse_kick = next(c for c in drum_clips if c["section_role"] == "verse")
    pitches = sorted(n["pitch"] for n in Q.get_notes_for_clip(db_conn, verse_kick["id"]))
    assert pitches == [36, 36]


def test_materialize_places_clips_at_section_bars(db_conn, song_and_tracks):
    song_id, tracks = song_and_tracks
    _two_section_arrangement().materialize(db_conn, song_id=song_id, tracks=tracks)
    placements = Q.get_arrangement_for_song(db_conn, song_id)
    drum_spans = sorted(
        (p["start_bar"], p["end_bar"]) for p in placements if p["track_id"] == tracks["Drums"]
    )
    assert drum_spans == [(1.0, 5.0), (5.0, 9.0)]


def test_materialize_can_skip_sections_and_cues(db_conn, song_and_tracks):
    song_id, tracks = song_and_tracks
    created = _two_section_arrangement().materialize(
        db_conn, song_id=song_id, tracks=tracks,
        author_sections=False, author_cues=False,
    )
    assert created["sections"] == 0 and created["cues"] == 0
    assert Q.get_sections_for_song(db_conn, song_id) == []


def test_materialize_unknown_track_raises_loud(db_conn, song_and_tracks):
    song_id, tracks = song_and_tracks
    arr = Arrangement().section(
        "verse", function="verse", bars=4, layers={"Theremin": KICK}
    )
    with pytest.raises(KeyError, match="unknown track 'Theremin'"):
        arr.materialize(db_conn, song_id=song_id, tracks=tracks)
