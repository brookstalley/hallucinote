"""Tests for hallucinote.arrangement — the song-structure layer.

Two halves: the pure planning/vary rulers (no DB), and a materialize()
integration test proving the module emits correct DB rows through the mutators
(the Chunk-1 vertical slice — architecture end-to-end through the data layer).
"""
from __future__ import annotations

import sqlite3
import warnings
from pathlib import Path

import pytest

from hallucinote.arrangement import Arrangement, Motif, vary
from hallucinote.db import init_db, mutations as M, queries as Q
from hallucinote.generators import variations as V
from hallucinote.meter import BarGrid, MeterMap
from hallucinote.sync.geometry import _position_bar_to_beats
from hallucinote.theory.model import Progression


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


# ==========================================================================
# Bar-ruler provenance (#496)
# ==========================================================================


def test_materialize_stamps_every_row_it_writes_as_map(db_conn, song_and_tracks):
    """Every position this class writes is resolved through the song's meter
    map — the same walk push uses — so every row says ``map``. It used to say
    ``uniform`` because the positions really were uniform bar math; that is the
    ruler #566 retired."""
    song_id, tracks = song_and_tracks
    _two_section_arrangement().materialize(db_conn, song_id=song_id, tracks=tracks)

    placements = Q.get_arrangement_for_song(db_conn, song_id)
    assert placements, "fixture precondition"
    assert {p["bar_ruler"] for p in placements} == {"map"}

    cues = Q.get_cue_points(db_conn, song_id)
    assert cues, "fixture precondition"
    assert {c["bar_ruler"] for c in cues} == {"map"}

    sections = Q.get_sections_for_song(db_conn, song_id)
    assert sections, "fixture precondition"
    assert {sec["bar_ruler"] for sec in sections} == {"map"}


def test_no_module_in_the_tree_writes_a_uniform_row_any_more():
    """``uniform`` is provenance on rows already written, not a ruler anything
    still authors against (#566 R3). A writer reappearing here would be
    reintroducing the second ruler — which is unalertable once its rows are in,
    because the alert exists to find exactly these."""
    src = Path(__file__).resolve().parents[2] / "src" / "hallucinote"
    claimants = sorted(
        path.relative_to(src).as_posix()
        for path in src.rglob("*.py")
        if 'bar_ruler="uniform"' in path.read_text()
    )
    assert claimants == [], claimants


def test_the_mutators_default_to_map_so_an_unwitting_writer_is_correct(db_conn, song_and_tracks):
    """``map`` on the MUTATOR, not at the call sites: a writer that has never
    heard of this column authors a correct row. Since #566 that covers every
    writer in the tree, which is why the column now only ever distinguishes
    HISTORICAL rows."""
    song_id, tracks = song_and_tracks
    clip_id = M.create_clip(
        db_conn, track_id=tracks["Drums"], slot=9, length_beats=4.0, name="x",
    )
    M.add_arrangement_clip(
        db_conn, song_id=song_id, track_id=tracks["Drums"], clip_id=clip_id,
        start_bar=1.0, end_bar=5.0,
    )
    M.add_cue_point(db_conn, song_id=song_id, position_bar=1.0, name="top")
    assert Q.get_arrangement_for_song(db_conn, song_id)[0]["bar_ruler"] == "map"
    assert Q.get_cue_points(db_conn, song_id)[0]["bar_ruler"] == "map"


def test_an_unknown_bar_ruler_is_refused_by_the_mutator(db_conn, song_and_tracks):
    """The schema CHECK would also refuse it, in SQLite's words, naming neither
    the argument nor the two legal values."""
    song_id, tracks = song_and_tracks
    clip_id = M.create_clip(
        db_conn, track_id=tracks["Drums"], slot=9, length_beats=4.0, name="x",
    )
    with pytest.raises(ValueError, match="bar_ruler"):
        M.add_arrangement_clip(
            db_conn, song_id=song_id, track_id=tracks["Drums"], clip_id=clip_id,
            start_bar=1.0, end_bar=5.0, bar_ruler="uniformish",
        )
    with pytest.raises(ValueError, match="bar_ruler"):
        M.add_cue_point(
            db_conn, song_id=song_id, position_bar=1.0, bar_ruler="beats",
        )


def test_re_adding_a_row_with_a_different_ruler_restamps_it(db_conn, song_and_tracks):
    """A song repaired by re-authoring its positions against the meter map is
    re-run, not re-created. The existing-row UPDATE branch has to carry the new
    ruler, or the repaired song keeps raising the alert it just fixed."""
    song_id, tracks = song_and_tracks
    clip_id = M.create_clip(
        db_conn, track_id=tracks["Drums"], slot=9, length_beats=4.0, name="x",
    )
    for ruler in ("uniform", "map"):
        M.add_arrangement_clip(
            db_conn, song_id=song_id, track_id=tracks["Drums"], clip_id=clip_id,
            start_bar=1.0, end_bar=5.0, bar_ruler=ruler,
        )
        M.add_cue_point(
            db_conn, song_id=song_id, position_bar=1.0, name="top",
            bar_ruler=ruler,
        )
    placements = Q.get_arrangement_for_song(db_conn, song_id)
    cues = Q.get_cue_points(db_conn, song_id)
    assert len(placements) == 1 and placements[0]["bar_ruler"] == "map"
    assert len(cues) == 1 and cues[0]["bar_ruler"] == "map"


# ---------------------------------------------------------------------------
# Meter: the arrangement places against the song's map, not a uniform ruler
# (#566 R2/R6 — the two-ruler divergence this class used to document and cause)
# ---------------------------------------------------------------------------


def _ts_rows(meter_map):
    """The arrangement's map in the row shape `sync.geometry` reads."""
    return meter_map.as_rows()


def test_a_section_boundary_after_a_meter_change_lands_where_push_puts_it():
    """The exact case this class's docstring used to predict and could not fix:
    4/4 turning 7/4 at bar 9 put bar 13 at beat 48 here and at 60 in push."""
    arr = Arrangement()
    arr.meter_change(at_bar=9, meter="7/4")
    for name in ("a", "b", "c"):
        arr.section(name, function="verse", bars=4, layers={})

    placed = arr.plan()
    assert [p.start_bar for p in placed] == [1, 5, 9]
    assert placed[2].start_beat == pytest.approx(32.0)

    # ...and push's own ruler agrees, position for position.
    rows = _ts_rows(arr.meter_map)
    for p in placed:
        assert _position_bar_to_beats(float(p.start_bar), rows) == pytest.approx(
            p.start_beat
        )
        assert _position_bar_to_beats(float(p.end_bar), rows) == pytest.approx(
            p.start_beat + p.length_beats
        )
    # The boundary the old arithmetic got wrong.
    assert _position_bar_to_beats(13.0, rows) == pytest.approx(60.0)


def test_a_borrowed_bar_shortens_the_arrangement():
    """One 3/4 bar in a 4/4 song genuinely steals a beat — the literal steal
    ARR-4M3T wanted and the uniform ruler could not express."""
    def build(borrow: bool) -> Arrangement:
        arr = Arrangement()
        if borrow:
            arr.meter_change(at_bar=5, meter="3/4")
            arr.meter_change(at_bar=6, meter="4/4")
        for name in ("a", "b", "c"):
            arr.section(name, function="verse", bars=4, layers={})
        return arr

    plain, stolen = build(False).plan(), build(True).plan()
    assert plain[2].start_beat - stolen[2].start_beat == pytest.approx(1.0)
    assert stolen[0].length_beats == pytest.approx(plain[0].length_beats)
    assert stolen[1].length_beats == pytest.approx(plain[1].length_beats - 1.0)


def test_per_section_meter_is_sugar_for_a_map_point_and_does_not_revert():
    arr = Arrangement()
    arr.section("a", function="verse", bars=4, layers={})
    arr.section("hang", function="break", bars=1, layers={}, meter="7/4")
    arr.section("b", function="chorus", bars=4, layers={})

    assert arr.meter_map.describe() == "bar 1 -> 4/4 · bar 5 -> 7/4"
    placed = arr.plan()
    # The hang runs 7 beats...
    assert placed[1].length_beats == pytest.approx(7.0)
    # ...and so does every bar after it, because a meter persists.
    assert placed[2].length_beats == pytest.approx(28.0)


def test_a_section_that_should_return_to_four_four_says_so():
    arr = Arrangement()
    arr.section("a", function="verse", bars=4, layers={})
    arr.section("hang", function="break", bars=1, layers={}, meter="7/4")
    arr.section("b", function="chorus", bars=4, layers={}, meter="4/4")
    assert arr.plan()[2].length_beats == pytest.approx(16.0)


def test_the_sugar_follows_the_layout_start_bar():
    arr = Arrangement()
    arr.section("a", function="verse", bars=4, layers={})
    arr.section("hang", function="break", bars=1, layers={}, meter="7/4")
    assert arr.meter_map_at(17).describe() == "bar 1 -> 4/4 · bar 21 -> 7/4"
    assert arr.plan(start_bar=17)[1].length_beats == pytest.approx(7.0)


def test_two_declarations_of_one_bar_s_meter_raise():
    arr = Arrangement(meter="4/4")
    with pytest.raises(ValueError, match="already declared 4/4"):
        arr.meter_change(at_bar=1, meter="7/4")

    clash = Arrangement()
    clash.meter_change(at_bar=5, meter="5/4")
    clash.section("a", function="verse", bars=4, layers={})
    clash.section("hang", function="break", bars=1, layers={}, meter="7/4")
    with pytest.raises(ValueError, match="already declared 5/4"):
        clash.plan()


def test_the_bar_one_meter_is_declared_once():
    with pytest.raises(ValueError, match="not both"):
        Arrangement(meter="7/4", beats_per_bar=7.0)


def test_the_scalar_spelling_still_works():
    assert Arrangement(beats_per_bar=3.0).meter_map == Arrangement(meter="3/4").meter_map
    assert Arrangement(beats_per_bar=3.0).beats_per_bar == 3.0


def test_a_bad_meter_fails_at_the_call_site():
    with pytest.raises(ValueError, match="num/den"):
        Arrangement().section("a", function="verse", bars=4, layers={}, meter="7")


def test_an_all_four_four_arrangement_plans_as_it_always_did():
    """The regression floor: every single-meter song must place identically."""
    arr = Arrangement()
    for name, bars in (("intro", 8), ("verse", 16), ("chorus", 8)):
        arr.section(name, function=name, bars=bars, layers={})
    placed = arr.plan()
    assert [(p.start_bar, p.end_bar) for p in placed] == [(1, 9), (9, 25), (25, 33)]
    assert [p.start_beat for p in placed] == [0.0, 32.0, 96.0]
    assert [p.length_beats for p in placed] == [32.0, 64.0, 32.0]


def test_inherit_slices_the_song_plan_at_map_resolved_offsets():
    """`progression="inherit"` slices by BEATS, so a section after a meter
    change must slice from the beat the map puts it on."""
    plan_prog = Progression.of(
        "C", "Ionian", ["C", "F", "G", "Am"], beats_per_chord=4.0,
    )  # 16 beats: C@0, F@4, G@8, Am@12
    arr = Arrangement().harmonic_plan(plan_prog)
    arr.meter_change(at_bar=2, meter="7/4")
    arr.section("a", function="verse", bars=1, layers={}, progression="inherit")
    arr.section("b", function="chorus", bars=1, layers={}, progression="inherit")

    placed = arr.plan()
    assert placed[1].start_beat == pytest.approx(4.0)
    assert placed[1].length_beats == pytest.approx(7.0)
    # Sliced from beat 4 (where the map puts bar 2), so it opens on F — and it
    # runs 7 beats, so it reaches G at its own beat 4.
    assert placed[1].progression.changes[0].chord.symbol == "F"
    assert placed[1].progression.changes[1].chord.symbol == "G"


# ==========================================================================
# The declared meter is written, and the song may not hold a different one
# (#566 R3/R4)
# ==========================================================================


def test_materialize_writes_the_declared_meter_into_the_song(db_conn, song_and_tracks):
    song_id, tracks = song_and_tracks
    arr = Arrangement()
    arr.meter_change(at_bar=5, meter="7/4")
    arr.section("a", function="verse", bars=4, layers={"Drums": KICK})
    arr.section("b", function="chorus", bars=4, layers={"Drums": KICK})
    arr.materialize(db_conn, song_id=song_id, tracks=tracks)

    stored = MeterMap.from_rows(Q.get_time_signature_map(db_conn, song_id))
    assert stored == arr.meter_map
    assert stored.describe() == "bar 1 -> 4/4 · bar 5 -> 7/4"


def test_materialize_is_a_no_op_on_a_meter_the_song_already_holds(db_conn, song_and_tracks):
    """Every song's build.py authors its own bar-1 point. Re-authoring an
    identical point must not be an error, or this closes the door on all of
    them."""
    song_id, tracks = song_and_tracks
    M.add_time_signature_point(
        db_conn, song_id=song_id, start_bar=1.0, numerator=4, denominator=4,
    )
    _two_section_arrangement().materialize(db_conn, song_id=song_id, tracks=tracks)
    stored = MeterMap.from_rows(Q.get_time_signature_map(db_conn, song_id))
    assert stored == MeterMap.parse("4/4")


def test_a_song_that_declares_a_meter_the_arrangement_does_not_refuses(db_conn, song_and_tracks):
    """The author-time error R4 asks for: a second declaration of the song's
    meter would put every position after it on a different beat than plan()
    computed, which is the two-ruler divergence in its original form."""
    song_id, tracks = song_and_tracks
    M.add_time_signature_point(
        db_conn, song_id=song_id, start_bar=9.0, numerator=5, denominator=4,
    )
    arr = _two_section_arrangement()
    with pytest.raises(ValueError, match="declares a meter this arrangement does not"):
        arr.materialize(db_conn, song_id=song_id, tracks=tracks)


def test_the_refusal_names_both_maps(db_conn, song_and_tracks):
    song_id, tracks = song_and_tracks
    M.add_time_signature_point(
        db_conn, song_id=song_id, start_bar=9.0, numerator=5, denominator=4,
    )
    with pytest.raises(ValueError) as excinfo:
        _two_section_arrangement().materialize(
            db_conn, song_id=song_id, tracks=tracks,
        )
    message = str(excinfo.value)
    assert "bar 9 -> 5/4" in message
    assert "bar 1 -> 4/4" in message


def test_a_bar_one_meter_that_disagrees_refuses(db_conn, song_and_tracks):
    """add_time_signature_point UPDATES a row at the same bar, so the
    arrangement's own write would silently overwrite the song's declaration.
    The read-back is what makes that visible instead."""
    song_id, tracks = song_and_tracks
    M.add_time_signature_point(
        db_conn, song_id=song_id, start_bar=1.0, numerator=3, denominator=4,
    )
    arr = _two_section_arrangement()   # declares 4/4
    with pytest.raises(ValueError, match="declares a meter this arrangement does not"):
        arr.materialize(db_conn, song_id=song_id, tracks=tracks)


def test_placements_after_a_meter_change_land_on_the_beat_push_resolves(
    db_conn, song_and_tracks,
):
    """The end-to-end shape of #566 acceptance 1: what plan() computed and what
    push computes off the DB are the same number, at every boundary."""
    song_id, tracks = song_and_tracks
    arr = Arrangement()
    arr.meter_change(at_bar=9, meter="7/4")
    for name in ("a", "b", "c"):
        arr.section(name, function="verse", bars=4, layers={"Drums": KICK})
    arr.materialize(db_conn, song_id=song_id, tracks=tracks)

    rows = Q.get_time_signature_map(db_conn, song_id)
    for placed, row in zip(
        arr.plan(), sorted(Q.get_arrangement_for_song(db_conn, song_id),
                           key=lambda r: r["start_bar"]),
    ):
        assert _position_bar_to_beats(row["start_bar"], rows) == pytest.approx(
            placed.start_beat
        )


def test_clip_length_is_the_map_resolved_span(db_conn, song_and_tracks):
    """A clip covering a 7/4 bar is 7 beats long, not 4 — the length used to be
    bars x one beats_per_bar."""
    song_id, tracks = song_and_tracks
    arr = Arrangement()
    arr.section("a", function="verse", bars=1, layers={"Drums": KICK})
    arr.section("hang", function="break", bars=1, layers={"Drums": KICK}, meter="7/4")
    arr.materialize(db_conn, song_id=song_id, tracks=tracks)

    lengths = {
        c["name"]: c["length_beats"]
        for c in (Q.get_clip(db_conn, p["clip_id"])
                  for p in Q.get_arrangement_for_song(db_conn, song_id))
    }
    assert lengths["a · Drums"] == pytest.approx(4.0)
    assert lengths["hang · Drums"] == pytest.approx(7.0)


# ==========================================================================
# The read side reads the map too — BOTH SIDES (#566 R5)
# ==========================================================================


def _mixed_meter_arrangement() -> Arrangement:
    """4 bars of 4/4, then one 7/4 bar, then 4 bars of 4/4 — 16, 7, 16 beats."""
    arr = Arrangement()
    arr.section("a", function="verse", bars=4, layers={"lead": [_n(64, 0.0)]})
    arr.section("hang", function="break", bars=1, layers={"lead": [_n(64, 0.0)]},
                meter="7/4")
    arr.section("b", function="chorus", bars=4, layers={"lead": [_n(64, 0.0)]},
                meter="4/4")
    return arr


@pytest.mark.parametrize(
    "bridge",
    ["section_lints", "section_perf_inputs", "section_melody_inputs",
     "section_recurrence_inputs"],
)
def test_every_bridge_reports_map_resolved_lengths(bridge):
    """All four used to compute `bars * one beats_per_bar`, which is wrong for
    every section at or after a meter change."""
    arr = _mixed_meter_arrangement()
    inputs = getattr(arr, bridge)()
    assert [s.length_beats for s in inputs] == pytest.approx([16.0, 7.0, 16.0])


def test_the_recurrence_bridge_reports_map_resolved_starts():
    """A recall's absolute offset is how the lens reports where it recurred; on
    a uniform ruler every offset after the hang would be a beat early."""
    starts = [s.start_beat for s in _mixed_meter_arrangement().section_recurrence_inputs()]
    assert starts == pytest.approx([0.0, 16.0, 23.0])


def test_the_melody_bridge_carries_each_section_s_own_bar_grid():
    inputs = _mixed_meter_arrangement().section_melody_inputs()
    assert inputs[0].bars.bar_lengths == pytest.approx((4.0, 4.0, 4.0, 4.0))
    assert inputs[1].bars.bar_lengths == pytest.approx((7.0,))
    assert inputs[2].bars.bar_lengths == pytest.approx((4.0, 4.0, 4.0, 4.0))


def test_a_single_meter_song_reads_exactly_as_it_did():
    """The regression floor for a grading surface: a silent shift in a melody
    or performance report is worse than a loud break."""
    arr = Arrangement()
    for name, bars in (("intro", 8), ("verse", 16)):
        arr.section(name, function=name, bars=bars, layers={"lead": [_n(64, 0.0)]})
    assert [s.length_beats for s in arr.section_lints()] == [32.0, 64.0]
    assert [s.length_beats for s in arr.section_perf_inputs()] == [32.0, 64.0]
    assert [(s.start_beat, s.length_beats)
            for s in arr.section_recurrence_inputs()] == [(0.0, 32.0), (32.0, 64.0)]
    melody = arr.section_melody_inputs()
    assert melody[0].bars == BarGrid.uniform(4.0, 32.0)
    assert melody[1].bars == BarGrid.uniform(4.0, 64.0)


# ==========================================================================
# Meter written after positions exist — the order `materialize`'s guard
# cannot see, because its check has already run (#566 R4's blind side)
# ==========================================================================


def test_meter_written_after_placements_warns_that_they_are_retimed(
    db_conn, song_and_tracks,
):
    song_id, tracks = song_and_tracks
    _two_section_arrangement().materialize(db_conn, song_id=song_id, tracks=tracks)
    with pytest.warns(UserWarning, match="AFTER positions exist"):
        M.add_time_signature_point(
            db_conn, song_id=song_id, start_bar=2.0, numerator=7, denominator=4,
        )


def test_changing_an_existing_meter_point_warns_the_same_way(db_conn, song_and_tracks):
    song_id, tracks = song_and_tracks
    M.add_time_signature_point(
        db_conn, song_id=song_id, start_bar=2.0, numerator=7, denominator=4,
    )
    arr = Arrangement()
    arr.meter_change(at_bar=2, meter="7/4")
    arr.section("a", function="verse", bars=4, layers={"Drums": KICK})
    arr.materialize(db_conn, song_id=song_id, tracks=tracks)
    with pytest.warns(UserWarning, match="AFTER positions exist"):
        M.add_time_signature_point(
            db_conn, song_id=song_id, start_bar=2.0, numerator=5, denominator=4,
        )


def test_the_ordinary_order_is_silent(db_conn, song_and_tracks, recwarn):
    """A build.py authors its meter before it materializes anything, and a
    re-run re-authors identical points. Neither may warn, or the warning is one
    every build prints and nobody reads."""
    song_id, tracks = song_and_tracks
    M.add_time_signature_point(
        db_conn, song_id=song_id, start_bar=1.0, numerator=4, denominator=4,
    )
    M.add_time_signature_point(
        db_conn, song_id=song_id, start_bar=5.0, numerator=7, denominator=4,
    )
    arr = Arrangement()
    arr.meter_change(at_bar=5, meter="7/4")
    arr.section("a", function="verse", bars=4, layers={"Drums": KICK})
    arr.section("b", function="chorus", bars=4, layers={"Drums": KICK})
    arr.materialize(db_conn, song_id=song_id, tracks=tracks)
    # ...and the state-converger re-run, which re-authors the same points.
    arr.materialize(db_conn, song_id=song_id, tracks=tracks)
    assert [w for w in recwarn if "AFTER positions exist" in str(w.message)] == []


def test_a_point_before_every_position_does_not_warn(db_conn, song_and_tracks):
    """Changing the map at a bar nothing sits after re-times nothing."""
    song_id, tracks = song_and_tracks
    arr = Arrangement()
    arr.section("a", function="verse", bars=4, layers={"Drums": KICK})
    arr.materialize(db_conn, song_id=song_id, tracks=tracks, start_bar=9)
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        M.add_time_signature_point(
            db_conn, song_id=song_id, start_bar=20.0, numerator=7, denominator=4,
        )


def test_a_meter_that_moves_nothing_is_silent(db_conn, song_and_tracks):
    """Several songs' builds author the bar-1 row after creating content, and
    declaring 4/4 where 4/4 was already in force moves no position. A warning
    that fired on those would fire on almost every build, and a warning every
    build prints is one nobody reads."""
    song_id, tracks = song_and_tracks
    _two_section_arrangement().materialize(db_conn, song_id=song_id, tracks=tracks)
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        M.add_time_signature_point(
            db_conn, song_id=song_id, start_bar=1.0, numerator=4, denominator=4,
        )


def test_a_bar_one_meter_that_does_move_things_still_warns(db_conn, song_and_tracks):
    """The precision cuts one way only: 4/4 -> 7/4 at bar 1 re-times every
    position in the song, and that must still be said."""
    song_id, tracks = song_and_tracks
    _two_section_arrangement().materialize(db_conn, song_id=song_id, tracks=tracks)
    with pytest.warns(UserWarning, match="AFTER positions exist"):
        M.add_time_signature_point(
            db_conn, song_id=song_id, start_bar=1.0, numerator=7, denominator=4,
        )


def test_the_warning_names_the_bars_that_moved(db_conn, song_and_tracks):
    song_id, tracks = song_and_tracks
    _two_section_arrangement().materialize(db_conn, song_id=song_id, tracks=tracks)
    with pytest.warns(UserWarning) as caught:
        M.add_time_signature_point(
            db_conn, song_id=song_id, start_bar=2.0, numerator=7, denominator=4,
        )
    message = str(caught[0].message)
    assert "7/4 written at bar 2" in message
    assert "bars " in message
