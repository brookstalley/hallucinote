"""Build Sun Zone / Stuff Done into a SQLite DB.

Reggae × speed-metal mashup, authored on the `hallucinote.arrangement`
capability. A 9-section / 80-bar narrative arc at a constant 180 BPM. Reggae
sections feel half-time (effective 90 BPM); metal sections inhabit 180 directly.
Root: E throughout. Mode: Dorian on reggae, Phrygian on metal — the F#→F + C#→C
pivot is the joke.

The arc tells a story of adapting:

    intro    bars  1– 8  reggae  energy 0.25  sun coming up (sparse; C3 polyrhythm)
    verse1   bars  9–16  reggae  energy 0.40  "chillin in the sun zone"
    chorus1  bars 17–24  metal   energy 0.80  "NO TIME FOR THAT" — first interruption
    verse2   bars 25–32  reggae  energy 0.45  back to chill, hasn't given up (recurrence+delta)
    chorus2  bars 33–40  metal   energy 0.90  second interruption, escalating (recurrence+delta)
    break1   bars 41–48  break   energy 0.70  convention-break: reggae-time, metal timbre (C5)
    break2   bars 49–56  break   energy 0.68  convention-break: metal-time, reggae timbre (C5)
    integ.   bars 57–72  metal   energy 1.00  integrating final chorus — fuse both + polyrhythm (C5)
    outro    bars 73–80  reggae  energy 0.35  enlightenment: reggae beat + metal bursts (C5)

Every genre flip is a deliberate ENERGY DISCONTINUITY — never smoothed (see
`.prawduct/artifacts/arrangement-model.md`). The break / integration / outro
sections are authored here with restructured EXISTING material (Chunk 2 of the
build plan); their genre-bending content lands as deltas/layers in later chunks.

The per-section drums / bass / organ / lead are authored on
`Arrangement` — one clip per (section, layer), placed automatically. Recurring
sections (verse2, chorus2) are derived from their first instance via `vary()` +
a `variations` op, so "same section, evolved" is one identity + a delta, never
an independent copy.

The Rhythm Gtr is the deliberate exception: it stays MONOLITHIC — one session
clip spanning the whole song (320 beats / 80 bars) — because the Amp Type
envelope (Clean ↔ Heavy, the song's most audible genre-flip device) must be
hosted by one clip covering its full beat range (Live 12.4 LOM; one envelope per
(device, parameter)). It is driven by the SAME `arr.plan()` output as the
arrangement, so section boundaries stay in sync — single source of truth.

Run:
    python songs/sun-zone-done/build.py            # state-converger
    python songs/sun-zone-done/build.py --reset    # drop + rebuild
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from hallucinote.arrangement import Arrangement, vary
from hallucinote.capture import replay_capture
from hallucinote.db import init_db, mutations as M, queries as Q, resolve_db_path
from hallucinote.generators import bass as BG, drums as DG, harmony as HG
from hallucinote.generators import variations as V
from hallucinote.generators.kit import Kit

# W12-A: per-branch DB filename.
DB_PATH = resolve_db_path("sun-zone-done", root=Path(__file__).parent.parent)
SNAPSHOT_PATH = Path(__file__).parent / "captured_session.json"

BEATS_PER_BAR = 4.0

# ---------------------------------------------------------------------------
# The narrative arc — the authored section map (build-plan Chunk 2).
# Each tuple: (name, function, genre, bars, energy). Bar ranges are assigned
# sequentially by Arrangement.plan(); energy is the authored intensity intent
# (direction across a transition is the *sequence* of energies, never smoothed —
# the genre flips are deliberate discontinuities).
# ---------------------------------------------------------------------------
ARC = [
    # name           function  genre     bars  energy
    ("intro",       "intro",  "reggae",   8,   0.25),
    ("verse1",      "verse",  "reggae",   8,   0.40),
    ("chorus1",     "chorus", "metal",    8,   0.80),
    ("verse2",      "verse",  "reggae",   8,   0.45),
    ("chorus2",     "chorus", "metal",    8,   0.90),
    ("break1",      "break",  "reggae",   8,   0.70),
    ("break2",      "break",  "metal",    8,   0.68),
    ("integration", "chorus", "metal",   16,   1.00),
    ("outro",       "outro",  "reggae",   8,   0.35),
]

# Amp Type indices (Live exposes these in order):
# 0=Clean, 1=Boost, 2=Blues, 3=Rock, 4=Lead, 5=Heavy, 6=Bass
AMP_TYPE_VALUE_ITEMS = ["Clean", "Boost", "Blues", "Rock", "Lead", "Heavy", "Bass"]

# Drum pads come from the loaded kit (Kit.from_device), NOT hardcoded MIDI
# notes — Hot Rod Kit's pad 51 is cowbell, not ride, the cautionary tale that
# motivated kit-probing (see generators/kit.py). With the current synthetic
# snapshot the kit has no probed pads and falls through to GM defaults
# (kick 36 / snare 38 / hat 42·46 / crash 49); once the song is snapshotted
# from a real Live set, the same call picks up that kit's actual pads.

# Pitch constants — only the notes we actually use.
E2  = 40   # bass root (reggae + metal)
E3  = 52   # guitar power-chord root + organ bottom + lead floor
G3  = 55   # gtr Em7 chord tone + organ
B3  = 59   # gtr Em7 chord tone + organ
D4  = 62   # gtr Em7 chord tone + lead
E4  = 64   # lead top of reggae range
F4  = 65   # phrygian b2 (metal lead)
G4  = 67   # lead motion
A4  = 69   # lead motion
B4  = 71   # lead climax
C5  = 72   # phrygian b6 (metal lead)
D5  = 74   # lead high
E5  = 76   # lead top of metal range

EM7 = [E3, G3, B3, D4]                 # rhythm-gtr reggae skank voicing
EM_TRIAD_UPPER = [G3, B3, E4]          # organ bubble voicing


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _tracks_by_name(conn, song_id: str) -> dict[str, str]:
    """Map track name -> id for the song. Master included; returns are not."""
    return {row["name"]: row["id"] for row in Q.get_tracks_for_song(conn, song_id)}


def _note(pitch: int, start: float, dur: float, vel: int) -> dict:
    return {"pitch": pitch, "start_beats": start,
            "duration_beats": dur, "velocity": vel}


def _kit_for_drums(conn, drum_track_id: str) -> Kit:
    """Load the Drum Rack's kit so generators author the RIGHT pad per kit.

    With the synthetic snapshot (no probed pad mappings) this falls through
    to GM defaults; once the song is snapshotted from a real Live set the
    same call picks up that kit's actual pad layout. Never hardcode pads."""
    devices = Q.get_devices_for_track(conn, drum_track_id)
    rack = next((d for d in devices if d["kind"] == "Drum Rack"), None)
    if rack is None:
        raise RuntimeError(
            f"Expected a 'Drum Rack' on the drums track; "
            f"found {[d['kind'] for d in devices]}"
        )
    return Kit.from_device(conn, rack["id"], name="Hot Rod Kit")


# ---------------------------------------------------------------------------
# Lead (placeholder vocal melody) — song-specific content, stays local.
# These are the actual vocal hooks ("chillin in the sun zone" / "NO TIME FOR
# THAT"), not reusable genre idioms, so they belong to the song, not the
# shared generators package. Authored 0-based within a section; the
# Arrangement places the clip at the section's bar range.
# ---------------------------------------------------------------------------


def _reggae_lead_chillin(length_beats: float) -> list[dict]:
    """'Chillin in the sun zone' — E Dorian melody, mid-register.
    Loops every 16 beats (4 bars)."""
    melody = [
        (E4, 0.0, 1.0, 85), (D4, 1.0, 0.5, 80), (B3, 1.5, 0.5, 75),
        (B3, 2.0, 0.5, 72), (G3, 2.5, 0.5, 75), (E3, 3.0, 1.0, 80),
        (B3,  8.0, 0.5, 80), (A4,  8.5, 0.5, 78), (G3,  9.0, 1.0, 82),
        (E3, 10.0, 0.5, 75), (G3, 10.5, 0.5, 76), (B3, 11.0, 0.5, 78),
        (D4, 11.5, 0.5, 80), (E4, 12.0, 3.0, 70),
    ]
    notes: list[dict] = []
    pattern_len = 16.0
    cycles = int(length_beats // pattern_len)
    for cycle in range(cycles):
        offset = cycle * pattern_len
        for p, t, d, v in melody:
            notes.append(_note(p, offset + t, d, v))
    return notes


def _metal_lead_no_time(length_beats: float) -> list[dict]:
    """'NO TIME FOR THAT' — E Phrygian stabs, upper register.
    Loops every 8 beats (2 bars)."""
    melody = [
        (E5, 0.0, 0.5, 110), (D5, 1.0, 0.5, 108),
        (C5, 2.0, 0.5, 110), (E5, 3.0, 0.5, 108),
        (E4, 4.0, 0.3, 105), (F4, 4.5, 0.3, 108),
        (G4, 5.0, 0.5, 110), (B4, 6.0, 0.5, 112),
        (E5, 7.0, 1.0, 115),
    ]
    notes: list[dict] = []
    pattern_len = 8.0
    cycles = int(length_beats // pattern_len)
    for cycle in range(cycles):
        offset = cycle * pattern_len
        for p, t, d, v in melody:
            notes.append(_note(p, offset + t, d, v))
    return notes


# ---------------------------------------------------------------------------
# Per-section layer blueprints (drums / bass / organ / lead — NOT rhythm gtr).
# Each returns a {track name -> notes} map, 0-based within the section. A track
# absent from the map simply doesn't play that section (organ tacet in metal;
# intro deliberately sparse). The Arrangement assigns bars + emits the clips.
# ---------------------------------------------------------------------------


def _reggae_layers(kit: Kit, bars: int, *, sparse: bool = False) -> dict[str, list[dict]]:
    """A full reggae section: one-drop drums + off-beat bass + organ bubble +
    vocal hook. ``sparse=True`` (the intro) drops organ + lead — the sun is
    just coming up; the hook hasn't arrived yet."""
    layers: dict[str, list[dict]] = {
        "01 Drums": DG.reggae_one_drop(bars, kit=kit),
        "02 Bass":  BG.reggae_offbeat_bass(E2, bars=bars),
    }
    if not sparse:
        layers["04 Organ"] = HG.organ_bubble(EM_TRIAD_UPPER, bars=bars)
        layers["05 Lead"] = _reggae_lead_chillin(bars * BEATS_PER_BAR)
    return layers


def _metal_layers(kit: Kit, bars: int) -> dict[str, list[dict]]:
    """A metal section: gallop drums + 16th pedal bass + cutting Phrygian lead.
    Organ is tacet (it returns only in the reggae world)."""
    return {
        "01 Drums": DG.metal_gallop(bars, kit=kit),
        "02 Bass":  BG.metal_pedal_16ths(E2, bars=bars),
        "05 Lead":  _metal_lead_no_time(bars * BEATS_PER_BAR),
    }


def _octave_up(notes: list[dict]) -> list[dict]:
    """Recurrence delta: double a layer an octave higher (brighter / fuller)."""
    return notes + V.transpose(notes, 12)


def _octave_down(notes: list[dict]) -> list[dict]:
    """Recurrence delta: double a layer an octave lower (heavier / escalating)."""
    return notes + V.transpose(notes, -12)


def _build_arrangement(kit: Kit) -> Arrangement:
    """Author the full narrative arc on the arrangement module.

    Recurring sections are derived from their first instance via ``vary`` — the
    cumulative-development primitive. verse2 / chorus2 are NOT independent
    copies; they are verse1 / chorus1 + a single delta, so "same section,
    evolved" reads as one identity plus a change.
    """
    arr = Arrangement(beats_per_bar=BEATS_PER_BAR)
    specs = {name: (function, genre, bars, energy)
             for name, function, genre, bars, energy in ARC}

    # First instances (blueprints the recurrences derive from).
    verse1 = _reggae_layers(kit, specs["verse1"][2])
    chorus1 = _metal_layers(kit, specs["chorus1"][2])

    # Recurrence deltas (the heart of the model — multi-axis, bidirectional):
    #   verse2  = verse1  + organ octave-doubled  ("more layered, hasn't given up")
    #   chorus2 = chorus1 + lead  octave-doubled down ("escalating, heavier")
    verse2 = vary(verse1, transform={"04 Organ": _octave_up})
    chorus2 = vary(chorus1, transform={"05 Lead": _octave_down})

    layers_by_name = {
        "intro":       _reggae_layers(kit, specs["intro"][2], sparse=True),
        "verse1":      verse1,
        "chorus1":     chorus1,
        "verse2":      verse2,
        "chorus2":     chorus2,
        # break / integration / outro: Chunk 2 restructures EXISTING material;
        # the timbre/time swaps, fusion, and bursts are authored in Chunk 5.
        "break1":      _reggae_layers(kit, specs["break1"][2]),
        "break2":      _metal_layers(kit, specs["break2"][2]),
        "integration": _metal_layers(kit, specs["integration"][2]),
        "outro":       _reggae_layers(kit, specs["outro"][2]),
    }

    for name, function, genre, bars, energy in ARC:
        arr.section(
            name, function=function, bars=bars, genre=genre,
            energy=energy, layers=layers_by_name[name],
        )
    return arr


# ---------------------------------------------------------------------------
# Rhythm gtr — ONE long session clip + ONE envelope across sections.
# The deliberate note-floor exception to the arrangement module: a monolithic
# clip is required to host the Amp Type device_parameter envelope. Driven by
# the SAME planned sections so its boundaries match the arrangement exactly.
# ---------------------------------------------------------------------------


def _compose_rhythm_gtr(conn, song_id, tracks, placed) -> None:
    """Author the monolithic rhythm-gtr clip + the Amp Type envelope.

    ``placed`` is ``Arrangement.plan()`` output — the single source of truth for
    section bar ranges and genre, so the gtr's section-boundary note seams and
    the Amp breakpoints line up with the per-section clips bar-for-bar.
    """
    gtr_track_id = tracks["03 Rhythm Gtr"]
    first_bar = placed[0].start_bar
    total_beats = (placed[-1].end_bar - first_bar) * BEATS_PER_BAR

    all_notes: list[dict] = []
    for sec in placed:
        section_start_beats = (sec.start_bar - first_bar) * BEATS_PER_BAR
        section_bars = sec.end_bar - sec.start_bar
        if sec.genre == "reggae":
            all_notes.extend(HG.reggae_skank(
                EM7, bars=section_bars, start_beat=section_start_beats))
        else:
            all_notes.extend(HG.palm_mute_power_chords(
                E3, bars=section_bars, start_beat=section_start_beats))

    gtr_clip = M.create_clip(
        conn, track_id=gtr_track_id, slot=1,
        name="Rhythm Gtr (full song)",
        length_beats=total_beats,
        section_role=None,
        actor="build",
        reason="monolithic rhythm gtr clip for Amp envelope hosting",
    )
    M.replace_clip_notes(conn, clip_id=gtr_clip, notes=all_notes,
                         actor="build", reason="initial composition")
    M.add_arrangement_clip(
        conn, song_id=song_id,
        track_id=gtr_track_id, clip_id=gtr_clip,
        start_bar=float(first_bar), end_bar=float(placed[-1].end_bar),
        actor="build", reason="rhythm gtr full-song placement",
    )

    # --- Amp Type envelope: one breakpoint at every genre change ---
    gtr_devices = Q.get_devices_for_track(conn, gtr_track_id)
    amp_device = next((d for d in gtr_devices if d["kind"] == "Amp"), None)
    if amp_device is None:
        raise RuntimeError(
            f"Expected an 'Amp' device on track '03 Rhythm Gtr'; "
            f"found {[d['kind'] for d in gtr_devices]}"
        )

    breakpoints: list[dict] = []
    last_genre: str | None = None
    for sec in placed:
        if sec.genre != last_genre:
            amp_value = "Heavy" if sec.genre == "metal" else "Clean"
            section_start_beats = (sec.start_bar - first_bar) * BEATS_PER_BAR
            breakpoints.append({
                "time_beats": section_start_beats,
                "value": amp_value,
                "curve_kind": "hold",
            })
            last_genre = sec.genre

    M.create_enum_envelope(
        conn,
        device_id=amp_device["id"],
        parameter_name="Amp Type",
        breakpoints=breakpoints,
        value_items=AMP_TYPE_VALUE_ITEMS,
        actor="build",
        reason="genre-flip amp character at section boundaries",
    )


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------


def build(reset: bool = False) -> str:
    conn = init_db(DB_PATH)
    try:
        if reset:
            song = Q.get_song_by_name(conn, "sun-zone-done")
            if song is not None:
                M.reset_song_content(conn, song_id=song["id"])
        with M.build_session(conn, song_name="sun-zone-done", owner="build.py"):
            # Mix-half: replay the synthetic Ableton session.
            snapshot = json.loads(SNAPSHOT_PATH.read_text())
            song_id = replay_capture(
                conn, snapshot,
                song_name="sun-zone-done",
                song_title="Sun Zone / Stuff Done",
                song_key="Em",
                actor="sync", reason="initial capture replay",
            )

            # Score-half: tempo + meter (constant across the song).
            M.set_song_timing_mode(conn, song_id=song_id, timing_mode="native")
            M.add_tempo_point(conn, song_id=song_id, start_bar=1.0, tempo_bpm=180.0)
            M.add_time_signature_point(
                conn, song_id=song_id, start_bar=1.0, numerator=4, denominator=4,
            )

            # Compose-half: author the arc on the arrangement module.
            tracks = _tracks_by_name(conn, song_id)
            kit = _kit_for_drums(conn, tracks["01 Drums"])
            arr = _build_arrangement(kit)
            placed = arr.plan()
            created = arr.materialize(
                conn, song_id=song_id, tracks=tracks,
                author_sections=True, author_cues=True, actor="build",
            )
            _compose_rhythm_gtr(conn, song_id, tracks, placed)

            # Report.
            print(f"song_id={song_id}, tempo=180, key=Em, "
                  f"sections={len(ARC)}, total_bars={arr.total_bars}")
            print(f"  arrangement-module created: {created}")
            print(f"  energy curve: "
                  f"{[(n, e) for n, e in arr.energy_curve]}")
            for tname in ("01 Drums", "02 Bass", "03 Rhythm Gtr",
                          "04 Organ", "05 Lead"):
                tid = tracks[tname]
                clips = Q.get_clips_for_track(conn, tid)
                total_notes = sum(len(Q.get_notes_for_clip(conn, c["id"]))
                                  for c in clips)
                print(f"  {tname:20s} clips={len(clips)} notes={total_notes}")
            envs = Q.get_envelopes_for_song(conn, song_id)
            print(f"  envelopes: {len(envs)}")
            for env in envs:
                bps = Q.get_breakpoints(conn, env["id"])
                print(f"    target_kind={env['target_kind']:18s} "
                      f"param={env['parameter_path'] or '-':12s} "
                      f"breakpoints={len(bps)}")
            arrangement = Q.get_arrangement_for_song(conn, song_id)
            print(f"  arrangement placements: {len(arrangement)}")
            cues = Q.get_cue_points(conn, song_id)
            print(f"  cue points: {len(cues)}")
        return song_id
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Build sun-zone-done.")
    parser.add_argument("--reset", action="store_true",
                        help="Soft reset: wipe rebuild-by-build.py content first.")
    args = parser.parse_args()
    build(reset=args.reset)


if __name__ == "__main__":
    main()
