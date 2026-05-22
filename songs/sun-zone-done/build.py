"""Build Sun Zone / Stuff Done into a SQLite DB.

Reggae × speed-metal mashup. Alternating (not overlapping) sections at a
constant 180 BPM. Reggae sections feel half-time (effective 90 BPM);
metal sections inhabit 180 directly. Root: E throughout. Mode: Dorian
on reggae, Phrygian on metal — the F#→F + C#→C pivot is the joke.

The Amp Type envelope on Rhythm Gtr (Clean ↔ Heavy) is the song's most
audible genre-flip device. **Hosted by ONE long session clip** that
spans the whole song (256 beats / 64 bars) — Live 12.4 LOM requires
device_parameter envelopes to be hosted by a session clip covering
the envelope's beat range, and one envelope per (device, parameter) is
the data-model constraint. Other tracks (drums / bass / organ / lead)
use per-section session clips for compose-time convenience; only the
rhythm-gtr track is monolithic.

Section bar layout (1-based, 4/4 throughout):
    intro    bars  1– 8  ( 8 bars / 32 beats) — reggae, sun coming up
    verse1   bars  9–16  ( 8 bars / 32 beats) — reggae, "chillin in the sun zone"
    chorus1  bars 17–24  ( 8 bars / 32 beats) — metal, "NO TIME FOR THAT"
    verse2   bars 25–32  ( 8 bars / 32 beats) — reggae, back to chill
    chorus2  bars 33–40  ( 8 bars / 32 beats) — metal, escalating
    bridge   bars 41–56  (16 bars / 64 beats) — metal, sustained
    outro    bars 57–64  ( 8 bars / 32 beats) — reggae, exhausted

Run:
    python songs/sun-zone-done/build.py            # state-converger
    python songs/sun-zone-done/build.py --reset    # drop + rebuild
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from hallucinote.capture import replay_capture
from hallucinote.db import init_db, mutations as M, queries as Q, resolve_db_path

# W12-A: per-branch DB filename.
DB_PATH = resolve_db_path("sun-zone-done", root=Path(__file__).parent.parent)
SNAPSHOT_PATH = Path(__file__).parent / "captured_session.json"


# ---------------------------------------------------------------------------
# Section bar boundaries (1-based)
# ---------------------------------------------------------------------------
INTRO_BAR   = 1
VERSE1_BAR  = 9
CHORUS1_BAR = 17
VERSE2_BAR  = 25
CHORUS2_BAR = 33
BRIDGE_BAR  = 41
OUTRO_BAR   = 57
END_BAR     = 65  # one past the last bar (64 bars total)

SECTIONS = [
    # (name, start_bar, end_bar, genre)
    ("intro",   INTRO_BAR,   VERSE1_BAR,  "reggae"),
    ("verse1",  VERSE1_BAR,  CHORUS1_BAR, "reggae"),
    ("chorus1", CHORUS1_BAR, VERSE2_BAR,  "metal"),
    ("verse2",  VERSE2_BAR,  CHORUS2_BAR, "reggae"),
    ("chorus2", CHORUS2_BAR, BRIDGE_BAR,  "metal"),
    ("bridge",  BRIDGE_BAR,  OUTRO_BAR,   "metal"),
    ("outro",   OUTRO_BAR,   END_BAR,     "reggae"),
]

# Amp Type indices (Live exposes these in order):
# 0=Clean, 1=Boost, 2=Blues, 3=Rock, 4=Lead, 5=Heavy, 6=Bass
AMP_TYPE_VALUE_ITEMS = ["Clean", "Boost", "Blues", "Rock", "Lead", "Heavy", "Bass"]

# Drum Rack pad mapping (Hot Rod Kit — General-MIDI-style).
KICK   = 36
SNARE  = 38
HAT_C  = 42  # closed hat
HAT_O  = 46  # open hat
CRASH  = 49

# Pitch constants — only the notes we actually use.
E2  = 40   # bass root (reggae + metal)
B2  = 47   # bass fifth (reggae walking)
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _tracks_by_name(conn, song_id: str) -> dict[str, str]:
    """Map track name -> id for the song. Master included; returns are not."""
    return {row["name"]: row["id"] for row in Q.get_tracks_for_song(conn, song_id)}


def _clip_in_slot(conn, *, track_id: str, slot: int) -> dict | None:
    """Find a session clip by (track, slot). Returns None if absent."""
    for c in Q.get_clips_for_track(conn, track_id):
        if c["slot"] == slot:
            return c
    return None


def _note(pitch: int, start: float, dur: float, vel: int) -> dict:
    return {"pitch": pitch, "start_beats": start,
            "duration_beats": dur, "velocity": vel}


# ---------------------------------------------------------------------------
# Reggae patterns (per-section)
# ---------------------------------------------------------------------------


def _reggae_drums(start_beats: float, length_beats: float,
                  *, lazy: float = 0.04) -> list[dict]:
    """Reggae one-drop: snare on beat 3, sparse kick, closed hat on offbeats.
    Snare lays behind the click by `lazy` beats.
    """
    notes: list[dict] = []
    bars = int(length_beats // 4)
    for bar in range(bars):
        b0 = start_beats + bar * 4
        if bar % 2 == 0:
            notes.append(_note(KICK,  b0 + 0.00, 0.5, 95))
        notes.append(_note(SNARE, b0 + 2.0 + lazy, 0.5, 88))
        for off in (0.5, 1.5, 2.5, 3.5):
            notes.append(_note(HAT_C, b0 + off + lazy * 0.5,
                               0.25, 55 + (4 if off == 1.5 else 0)))
        if (bar + 1) % 4 == 0:
            notes.append(_note(HAT_O, b0 + 3.5 + lazy, 0.5, 65))
    return notes


def _reggae_bass(start_beats: float, length_beats: float,
                 *, root: int = E2, fifth_up: int = B2) -> list[dict]:
    """Reggae walking bass on the offbeats."""
    notes: list[dict] = []
    bars = int(length_beats // 4)
    octave = root + 12
    for bar in range(bars):
        b0 = start_beats + bar * 4
        notes.append(_note(root,      b0 + 0.00 + 0.02, 1.4, 80))
        notes.append(_note(fifth_up,  b0 + 1.50 + 0.02, 0.4, 72))
        notes.append(_note(octave,    b0 + 2.00 + 0.02, 1.4, 82))
        notes.append(_note(fifth_up,  b0 + 3.50 + 0.02, 0.4, 70))
    return notes


def _reggae_skank(start_beats: float, length_beats: float,
                  *, chord_pitches: list[int]) -> list[dict]:
    """Off-beat skanks on the 'and' of 2 and 4 — the iconic lazy chuck."""
    notes: list[dict] = []
    bars = int(length_beats // 4)
    for bar in range(bars):
        b0 = start_beats + bar * 4
        for off in (1.5, 3.5):
            for p in chord_pitches:
                notes.append(_note(p, b0 + off + 0.06, 0.30, 78))
    return notes


def _reggae_organ_bubble(start_beats: float, length_beats: float,
                          *, chord_pitches: list[int]) -> list[dict]:
    """Hammond bubble on every offbeat."""
    notes: list[dict] = []
    bars = int(length_beats // 4)
    for bar in range(bars):
        b0 = start_beats + bar * 4
        for off in (0.5, 1.5, 2.5, 3.5):
            for p in chord_pitches:
                notes.append(_note(p, b0 + off + 0.04, 0.20, 58))
    return notes


# ---------------------------------------------------------------------------
# Metal patterns (per-section)
# ---------------------------------------------------------------------------


def _metal_drums(start_beats: float, length_beats: float) -> list[dict]:
    """Metal: kick gallop on 16ths, snare on 2 and 4, hi-hat on 16ths."""
    notes: list[dict] = []
    bars = int(length_beats // 4)
    for bar in range(bars):
        b0 = start_beats + bar * 4
        for off in (0.0, 0.25, 0.5, 0.75, 1.5, 1.75, 2.5, 2.75, 3.0, 3.25, 3.75):
            notes.append(_note(KICK, b0 + off, 0.15, 108))
        notes.append(_note(SNARE, b0 + 1.0, 0.25, 115))
        notes.append(_note(SNARE, b0 + 3.0, 0.25, 115))
        for off in range(16):
            notes.append(_note(HAT_C, b0 + off * 0.25, 0.10,
                                70 + (15 if off % 4 == 0 else 0)))
        if bar == 0:
            notes.append(_note(CRASH, b0 + 0.0, 1.0, 118))
    return notes


def _metal_bass(start_beats: float, length_beats: float,
                *, root: int = E2) -> list[dict]:
    """Metal palm-mute root pedaling on 16ths."""
    notes: list[dict] = []
    bars = int(length_beats // 4)
    for bar in range(bars):
        b0 = start_beats + bar * 4
        for off in range(16):
            t = b0 + off * 0.25
            # Slight push (-0.01) on every 16th EXCEPT the very first note of
            # the clip — Live's MIDI clip has no negative-beat region.
            push = -0.01 if t > 0.0 else 0.0
            notes.append(_note(root, t + push, 0.18, 105))
    return notes


def _metal_gtr(start_beats: float, length_beats: float,
                *, power_chord_root: int = E3) -> list[dict]:
    """Metal palm-mute power chords on 16ths (root + 5th + octave)."""
    notes: list[dict] = []
    bars = int(length_beats // 4)
    fifth = power_chord_root + 7
    octave = power_chord_root + 12
    for bar in range(bars):
        b0 = start_beats + bar * 4
        for off in (0.0, 0.25, 0.5, 0.75, 1.5, 1.75, 2.5, 2.75, 3.0, 3.25, 3.75):
            notes.append(_note(power_chord_root, b0 + off, 0.18, 108))
            notes.append(_note(fifth,             b0 + off, 0.18, 100))
            notes.append(_note(octave,            b0 + off, 0.18, 95))
    return notes


# ---------------------------------------------------------------------------
# Lead (placeholder vocal melody)
# ---------------------------------------------------------------------------


def _reggae_lead_chillin(start_beats: float, length_beats: float) -> list[dict]:
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
        offset = start_beats + cycle * pattern_len
        for p, t, d, v in melody:
            notes.append(_note(p, offset + t, d, v))
    return notes


def _metal_lead_no_time(start_beats: float, length_beats: float) -> list[dict]:
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
        offset = start_beats + cycle * pattern_len
        for p, t, d, v in melody:
            notes.append(_note(p, offset + t, d, v))
    return notes


# ---------------------------------------------------------------------------
# Per-section composition (drums, bass, organ, lead — NOT rhythm gtr)
# ---------------------------------------------------------------------------


def _compose_sections(conn, song_id: str, tracks: dict[str, str]) -> None:
    """Author per-section session clips for drums / bass / organ / lead.
    Rhythm gtr is handled separately (one long clip — see _compose_rhythm_gtr)."""
    for section_idx, (name, start_bar, end_bar, genre) in enumerate(SECTIONS):
        length_beats = (end_bar - start_bar) * 4.0
        slot = section_idx + 1

        # --- Drums ---
        drum_notes = (_reggae_drums(0.0, length_beats) if genre == "reggae"
                       else _metal_drums(0.0, length_beats))
        drum_clip = M.create_clip(
            conn, track_id=tracks["01 Drums"], slot=slot,
            name=f"{name.capitalize()} Drums",
            length_beats=length_beats,
            section_role=name,
            actor="build", reason=f"{genre} drums",
        )
        M.replace_clip_notes(conn, clip_id=drum_clip, notes=drum_notes,
                              actor="build", reason="initial composition")

        # --- Bass ---
        bass_notes = (_reggae_bass(0.0, length_beats) if genre == "reggae"
                       else _metal_bass(0.0, length_beats))
        bass_clip = M.create_clip(
            conn, track_id=tracks["02 Bass"], slot=slot,
            name=f"{name.capitalize()} Bass",
            length_beats=length_beats,
            section_role=name,
            actor="build", reason=f"{genre} bass",
        )
        M.replace_clip_notes(conn, clip_id=bass_clip, notes=bass_notes,
                              actor="build", reason="initial composition")

        # --- Organ (reggae-only) ---
        if genre == "reggae":
            em_triad_upper = [G3, B3, E4]
            organ_notes = _reggae_organ_bubble(0.0, length_beats,
                                                chord_pitches=em_triad_upper)
            organ_clip = M.create_clip(
                conn, track_id=tracks["04 Organ"], slot=slot,
                name=f"{name.capitalize()} Organ",
                length_beats=length_beats,
                section_role=name,
                actor="build", reason="reggae organ bubbles",
            )
            M.replace_clip_notes(conn, clip_id=organ_clip, notes=organ_notes,
                                  actor="build", reason="initial composition")

        # --- Lead ---
        lead_notes = (_reggae_lead_chillin(0.0, length_beats) if genre == "reggae"
                       else _metal_lead_no_time(0.0, length_beats))
        lead_clip = M.create_clip(
            conn, track_id=tracks["05 Lead"], slot=slot,
            name=f"{name.capitalize()} Lead",
            length_beats=length_beats,
            section_role=name,
            actor="build", reason=f"{genre} lead (placeholder vocal)",
        )
        M.replace_clip_notes(conn, clip_id=lead_clip, notes=lead_notes,
                              actor="build", reason="initial composition")


# ---------------------------------------------------------------------------
# Rhythm gtr — ONE long session clip + ONE envelope across sections
# ---------------------------------------------------------------------------


def _compose_rhythm_gtr(conn, song_id: str, tracks: dict[str, str]) -> None:
    """Rhythm gtr is monolithic. One session clip spanning the whole song
    (256 beats / 64 bars), containing all per-section gtr notes concatenated.
    The Amp Type envelope sits on the track's Amp device with breakpoints
    at section boundaries — Live 12.4 LOM requires device_parameter envelopes
    to be hosted by a clip covering the envelope's full beat range; one
    envelope per (device, parameter) is the data-model constraint. ONE long
    clip is the structural fix.
    """
    gtr_track_id = tracks["03 Rhythm Gtr"]
    total_beats = (END_BAR - INTRO_BAR) * 4.0  # 256 beats

    # Build the concatenated note list — each section starts at its absolute
    # beat position within the song.
    em7 = [E3, G3, B3, D4]
    all_notes: list[dict] = []
    for name, start_bar, end_bar, genre in SECTIONS:
        section_start_beats = (start_bar - INTRO_BAR) * 4.0
        section_length_beats = (end_bar - start_bar) * 4.0
        if genre == "reggae":
            section_notes = _reggae_skank(section_start_beats,
                                           section_length_beats,
                                           chord_pitches=em7)
        else:
            section_notes = _metal_gtr(section_start_beats,
                                        section_length_beats,
                                        power_chord_root=E3)
        all_notes.extend(section_notes)

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

    # --- Amp Type envelope: section-boundary breakpoints ---
    gtr_devices = Q.get_devices_for_track(conn, gtr_track_id)
    amp_device = next((d for d in gtr_devices if d["kind"] == "Amp"), None)
    if amp_device is None:
        raise RuntimeError(
            f"Expected an 'Amp' device on track '03 Rhythm Gtr'; "
            f"found {[d['kind'] for d in gtr_devices]}"
        )

    # Build breakpoint at every genre change boundary.
    breakpoints: list[dict] = []
    last_genre: str | None = None
    for name, start_bar, end_bar, genre in SECTIONS:
        if genre != last_genre:
            amp_value = "Heavy" if genre == "metal" else "Clean"
            section_start_beats = (start_bar - INTRO_BAR) * 4.0
            breakpoints.append({
                "time_beats": section_start_beats,
                "value": amp_value,
                "curve_kind": "hold",
            })
            last_genre = genre

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
# Sections + Arrangement + Cues
# ---------------------------------------------------------------------------


def _author_sections(conn, song_id: str) -> None:
    for name, start_bar, end_bar, _genre in SECTIONS:
        M.create_section(
            conn, song_id=song_id, name=name,
            start_bar=float(start_bar), end_bar=float(end_bar),
            actor="build", reason="section boundary",
        )


def _author_arrangement(conn, song_id: str, tracks: dict[str, str]) -> None:
    """Place clips into the arrangement timeline.

    Drums / Bass / Organ / Lead: per-section clips placed at each section's
    bar range. Rhythm gtr: ONE clip placed at bar 1 spanning all 64 bars.
    """
    # Per-section tracks
    for section_idx, (name, start_bar, end_bar, genre) in enumerate(SECTIONS):
        slot = section_idx + 1
        per_section_tracks = ["01 Drums", "02 Bass", "05 Lead"]
        if genre == "reggae":
            per_section_tracks.append("04 Organ")
        for tname in per_section_tracks:
            tid = tracks[tname]
            clip = _clip_in_slot(conn, track_id=tid, slot=slot)
            if clip is None:
                continue
            M.add_arrangement_clip(
                conn, song_id=song_id,
                track_id=tid,
                clip_id=clip["id"],
                start_bar=float(start_bar),
                end_bar=float(end_bar),
                actor="build", reason=f"{name} placement",
            )

    # Rhythm gtr: one big placement spanning the whole song
    gtr_tid = tracks["03 Rhythm Gtr"]
    gtr_clip = _clip_in_slot(conn, track_id=gtr_tid, slot=1)
    if gtr_clip is not None:
        M.add_arrangement_clip(
            conn, song_id=song_id,
            track_id=gtr_tid,
            clip_id=gtr_clip["id"],
            start_bar=float(INTRO_BAR),
            end_bar=float(END_BAR),
            actor="build", reason="rhythm gtr full-song placement",
        )


def _author_cues(conn, song_id: str) -> None:
    for name, start_bar, _end, _genre in SECTIONS:
        M.add_cue_point(
            conn, song_id=song_id,
            position_bar=float(start_bar),
            name=name,
            actor="build", reason=f"{name} cue",
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

            # Compose-half.
            tracks = _tracks_by_name(conn, song_id)
            _author_sections(conn, song_id)
            _compose_sections(conn, song_id, tracks)
            _compose_rhythm_gtr(conn, song_id, tracks)
            _author_arrangement(conn, song_id, tracks)
            _author_cues(conn, song_id)

            # Report.
            print(f"song_id={song_id}, tempo=180, key=Em, sections={len(SECTIONS)}")
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
            arr = Q.get_arrangement_for_song(conn, song_id)
            print(f"  arrangement placements: {len(arr)}")
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
