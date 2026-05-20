"""Build Punk Fate into a SQLite DB using the hallucinote layer.

Condense the chord progressions of Beethoven's 5th into a 2-minute punk-rock arc. Verses pull from Mvt. I's i-iv-V and III-VI-iio6-V in C minor (the fate motif); choruses lift to C major mirroring Mvt. IV's triumph; bridge nods to the Eb-major second theme. Four parts: drums, bass, lead guitar, and a staccato synth carrying the vocal line. Real punk energy — fast, raw, driving, no precious moments.

Section bar layout (1-based, 4/4 throughout — 88 bars ≈ 1:57 at 180 BPM):
    intro        bars  1-8    (8 bars)   — motif establishment
    verse        bars  9-24   (16 bars)  — Cm: i-iv-V
    chorus       bars 25-40   (16 bars)  — C major: IV-V-I
    verse2       bars 41-56   (16 bars)  — Cm reprise, synth octave-up
    chorus2      bars 57-72   (16 bars)  — C major restated, bigger
    bridge       bars 73-80   (8 bars)   — Eb major, drums drop for 4 then return
    outro        bars 81-88   (8 bars)   — Cm motif recap, abrupt cut

Run:
    python songs/punk-fate/build.py            # state-converger: re-run is no-op if nothing changed
    python songs/punk-fate/build.py --reset    # drop + rebuild from scratch
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from hallucinote.capture import replay_capture
from hallucinote.db import init_db, mutations as M, queries as Q, resolve_db_path

# Per-branch DB filename (W12-A): branch switches pick up the right DB
# silently; outside a repo / detached HEAD falls back to punk-fate.db.
DB_PATH = resolve_db_path("punk-fate", root=Path(__file__).parent.parent)
SNAPSHOT_PATH = Path(__file__).parent / "captured_session.json"


# ---------------------------------------------------------------------------
# Section bar boundaries (1-based) — adjust as the song grows
# ---------------------------------------------------------------------------
INTRO_BAR = 1
VERSE_BAR = 9
CHORUS_BAR = 25
VERSE2_BAR = 41
CHORUS2_BAR = 57
BRIDGE_BAR = 73
OUTRO_BAR = 81
END_BAR = 89


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _tracks_by_name(conn, song_id: str) -> dict[str, str]:
    """Map track name -> id for the song. Master included; returns are not."""
    return {row["name"]: row["id"] for row in Q.get_tracks_for_song(conn, song_id)}


def _note(pitch: int, start: float, dur: float, vel: int) -> dict:
    return {"pitch": pitch, "start_beats": start,
            "duration_beats": dur, "velocity": vel}


# Drum Rack GM-derived mapping (Hot Rod Kit). User can remap visually in Live
# if any pad lands on a different sound than expected.
KICK, SNARE = 36, 38
HAT_CLOSED, HAT_OPEN = 42, 46
CRASH = 49
TOM_LO, TOM_MID, TOM_HI = 43, 47, 50

# Bass roots (octave 2 — sub region of an electric bass)
BASS_C, BASS_F, BASS_G, BASS_EB, BASS_AB, BASS_BB, BASS_D = 36, 41, 43, 39, 44, 46, 38

# Guitar power-chord roots (Operator's "Power Chords Guitar" preset produces
# the chord stack from a single MIDI note via its FM algorithm — write
# single notes on each chord root).
GTR_C, GTR_F, GTR_G, GTR_EB, GTR_AB, GTR_BB, GTR_D = 48, 53, 55, 51, 56, 58, 50

# Synth-vox motif pitches. The fate motif's three repeated notes sit on
# scale degree 5 (G); the long note drops to degree 3 (Eb in Cm, E♮ in C major).
VOX_G, VOX_EB, VOX_E, VOX_C, VOX_F, VOX_AB, VOX_BB = 67, 63, 64, 60, 65, 68, 70
VOX_G5, VOX_EB5, VOX_E5 = 79, 75, 76  # octave-up for chorus2 lift


# ---------------------------------------------------------------------------
# Pattern helpers — punk-energy heuristics from decisions/07-energy-aesthetic.md
# ---------------------------------------------------------------------------


def _punk_drum_bar(start: float, *, crash: bool = False, fill: bool = False) -> list[dict]:
    """One bar: driving 8th hats, kick on 1+3, snare on 2+4. `fill` swaps beats 3-4
    for a tom roll into the next section. `crash` adds an open crash on beat 1."""
    n: list[dict] = []
    for i in range(8):
        n.append(_note(HAT_CLOSED, start + i * 0.5, 0.2, 88 + (i % 2) * 10))
    if crash:
        n.append(_note(CRASH, start + 0.0, 1.5, 120))
    n.append(_note(KICK, start + 0.0, 0.25, 116))
    n.append(_note(KICK, start + 2.0, 0.25, 112))
    if fill:
        # Beats 3-4: tom-roll fill replacing the second half of the bar
        n = [x for x in n if x["start_beats"] < start + 2.0 or x["pitch"] == HAT_CLOSED]
        n.append(_note(SNARE, start + 1.0, 0.2, 110))
        for i, p in enumerate([TOM_HI, TOM_HI, TOM_MID, TOM_MID, TOM_LO, TOM_LO, SNARE, SNARE]):
            n.append(_note(p, start + 2.0 + i * 0.25, 0.18, 108 + i * 2))
    else:
        n.append(_note(SNARE, start + 1.0, 0.2, 108))
        n.append(_note(SNARE, start + 3.0, 0.2, 112))
    return n


def _bass_eighths(pitch: int, start: float, bars: int) -> list[dict]:
    """Pumping eighth-note root for `bars` bars."""
    n: list[dict] = []
    for b in range(bars):
        for i in range(8):
            n.append(_note(pitch, start + b * 4 + i * 0.5, 0.42, 100 + (i % 2) * 6))
    return n


def _bass_quarters(pitch: int, start: float, bars: int) -> list[dict]:
    """Quarter-note thumps — the chorus 'felt contrast' from the energy decision."""
    n: list[dict] = []
    for b in range(bars):
        for i in range(4):
            n.append(_note(pitch, start + b * 4 + i, 0.9, 108 + (i % 2) * 6))
    return n


def _power_chord_held(root: int, start: float, bars: int) -> list[dict]:
    """Held power chord for `bars` bars."""
    return [_note(root, start, bars * 4.0, 108)]


def _motif_at(pitch_repeat: int, pitch_long: int, start: float,
              vel_base: int = 108) -> list[dict]:
    """The Beethoven fate motif: 3 eighths at `pitch_repeat`, half note at `pitch_long`.
    Fits in 1 bar of 4/4 (3.5 beats + 0.5 of rest before the next bar)."""
    return [
        _note(pitch_repeat, start + 0.0, 0.4, vel_base),
        _note(pitch_repeat, start + 0.5, 0.4, vel_base + 4),
        _note(pitch_repeat, start + 1.0, 0.4, vel_base + 7),
        _note(pitch_long,   start + 1.5, 2.0, vel_base + 12),
    ]


# ---------------------------------------------------------------------------
# Composition
# ---------------------------------------------------------------------------


def _compose(conn, song_id: str, tracks: dict[str, str]) -> None:
    """Build all clips + arrange them. Each section is one clip per track.

    Beats are clip-local (each clip starts at beat 0); the arrangement
    places them at the section's start_bar. Per-section length_beats =
    bars * 4 (4/4 throughout).
    """
    drums_t = tracks["01 Drums"]
    bass_t  = tracks["02 Bass"]
    gtr_t   = tracks["03 Lead Guitar"]
    vox_t   = tracks["04 Synth Vox"]

    section_specs = [
        ("intro",   1, INTRO_BAR,   VERSE_BAR,   8),
        ("verse",   2, VERSE_BAR,   CHORUS_BAR,  16),
        ("chorus",  3, CHORUS_BAR,  VERSE2_BAR,  16),
        ("verse2",  4, VERSE2_BAR,  CHORUS2_BAR, 16),
        ("chorus2", 5, CHORUS2_BAR, BRIDGE_BAR,  16),
        ("bridge",  6, BRIDGE_BAR,  OUTRO_BAR,   8),
        ("outro",   7, OUTRO_BAR,   END_BAR,     8),
    ]

    for role, slot, start_bar, end_bar, bars in section_specs:
        length = bars * 4.0
        d_notes, b_notes, g_notes, v_notes = _notes_for_section(role, bars)

        for track_id, role_short, notes in [
            (drums_t, "Drums",  d_notes),
            (bass_t,  "Bass",   b_notes),
            (gtr_t,   "Gtr",    g_notes),
            (vox_t,   "Vox",    v_notes),
        ]:
            cid = M.create_clip(
                conn, track_id=track_id, slot=slot, length_beats=length,
                name=f"{role.capitalize()} {role_short}", section_role=role,
            )
            M.replace_clip_notes(conn, clip_id=cid, notes=notes)
            M.add_arrangement_clip(
                conn, song_id=song_id,
                track_id=track_id, clip_id=cid,
                start_bar=float(start_bar), end_bar=float(end_bar),
            )


def _notes_for_section(role: str, bars: int) -> tuple[list, list, list, list]:
    """Return (drums, bass, gtr, vox) notes for one section, beats clip-local."""
    if role == "intro":
        return _intro()
    if role == "verse":
        return _verse()
    if role == "chorus":
        return _chorus(octave_up=False)
    if role == "verse2":
        return _verse()  # same harmony as verse; chorus2 carries the lift
    if role == "chorus2":
        return _chorus(octave_up=True)
    if role == "bridge":
        return _bridge()
    if role == "outro":
        return _outro(bars)
    raise ValueError(f"unknown section role: {role}")


def _intro() -> tuple[list, list, list, list]:
    """Bars 1-2: motif alone (gtr + vox). Bar 3-4: kick joins. Bars 5-8: full band on motif."""
    d, b, g, v = [], [], [], []
    # Bars 1-2: silent drums + bass; motif on gtr + vox
    for bar in range(2):
        g.extend(_motif_at(GTR_C, GTR_C, bar * 4.0))  # power chord stays on root
        v.extend(_motif_at(VOX_G, VOX_EB, bar * 4.0, vel_base=100))
    # Bars 3-4: kick on 1+3, motif continues
    for bar in range(2, 4):
        d.append(_note(KICK, bar * 4.0 + 0.0, 0.25, 110))
        d.append(_note(KICK, bar * 4.0 + 2.0, 0.25, 108))
        d.append(_note(HAT_CLOSED, bar * 4.0 + 2.0, 0.2, 80))
        g.extend(_motif_at(GTR_C, GTR_C, bar * 4.0))
        v.extend(_motif_at(VOX_G, VOX_EB, bar * 4.0))
    # Bars 5-8: full punk drums + bass entering, motif rolling
    for bar in range(4, 8):
        is_last = bar == 7
        d.extend(_punk_drum_bar(bar * 4.0, fill=is_last))
        b.extend(_bass_eighths(BASS_C, bar * 4.0, 1))
        g.extend(_motif_at(GTR_C, GTR_C, bar * 4.0, vel_base=112))
        v.extend(_motif_at(VOX_G, VOX_EB, bar * 4.0, vel_base=112))
    return d, b, g, v


def _verse() -> tuple[list, list, list, list]:
    """16 bars in Cm: 4 Cm | 2 Fm | 2 G | 4 Cm | 2 Fm | 2 G (V transitions to chorus).
    Bass on 8th-note roots, guitar with motif rhythm on chord roots, vox melody."""
    d, b, g, v = [], [], [], []
    # Chord layout per bar (16 bars)
    plan = [
        ("Cm", BASS_C, GTR_C, VOX_G, VOX_EB),  # bar 1
        ("Cm", BASS_C, GTR_C, VOX_G, VOX_EB),
        ("Cm", BASS_C, GTR_C, VOX_G, VOX_EB),
        ("Cm", BASS_C, GTR_C, VOX_G, VOX_EB),
        ("Fm", BASS_F, GTR_F, VOX_AB, VOX_C),  # bar 5 — iv reveal
        ("Fm", BASS_F, GTR_F, VOX_AB, VOX_C),
        ("G",  BASS_G, GTR_G, VOX_BB, VOX_G),  # bar 7 — V tension
        ("G",  BASS_G, GTR_G, VOX_BB, VOX_G),
        ("Cm", BASS_C, GTR_C, VOX_G, VOX_EB),  # bar 9 — return
        ("Cm", BASS_C, GTR_C, VOX_G, VOX_EB),
        ("Cm", BASS_C, GTR_C, VOX_G, VOX_EB),
        ("Cm", BASS_C, GTR_C, VOX_G, VOX_EB),
        ("Fm", BASS_F, GTR_F, VOX_AB, VOX_C),
        ("Fm", BASS_F, GTR_F, VOX_AB, VOX_C),
        ("G",  BASS_G, GTR_G, VOX_BB, VOX_G),
        ("G",  BASS_G, GTR_G, VOX_BB, VOX_G),  # bar 16 — fill into chorus
    ]
    for bar_idx, (_label, bass_p, gtr_p, vox_hi, vox_lo) in enumerate(plan):
        bar_start = bar_idx * 4.0
        is_last = bar_idx == len(plan) - 1
        d.extend(_punk_drum_bar(bar_start, fill=is_last))
        b.extend(_bass_eighths(bass_p, bar_start, 1))
        g.extend(_motif_at(gtr_p, gtr_p, bar_start, vel_base=110))
        v.extend(_motif_at(vox_hi, vox_lo, bar_start, vel_base=108))
    return d, b, g, v


def _chorus(*, octave_up: bool) -> tuple[list, list, list, list]:
    """16 bars in C major: IV-V-I cycles. Quarter-note bass (felt contrast),
    held power chords with stabs on beat 4, vocal melody in C major (E natural)."""
    d, b, g, v = [], [], [], []
    # Chord layout (16 bars)
    plan = [
        ("F", BASS_F, GTR_F),  # IV
        ("F", BASS_F, GTR_F),
        ("G", BASS_G, GTR_G),  # V
        ("G", BASS_G, GTR_G),
        ("C", BASS_C, GTR_C),  # I — arrival
        ("C", BASS_C, GTR_C),
        ("C", BASS_C, GTR_C),
        ("C", BASS_C, GTR_C),
        ("F", BASS_F, GTR_F),
        ("F", BASS_F, GTR_F),
        ("G", BASS_G, GTR_G),
        ("G", BASS_G, GTR_G),
        ("C", BASS_C, GTR_C),
        ("C", BASS_C, GTR_C),
        ("C", BASS_C, GTR_C),
        ("C", BASS_C, GTR_C),
    ]
    # Vocal hook: G G G E (C major motif), one bar per phrase, walking through chords
    vox_g = VOX_G5 if octave_up else VOX_G
    vox_e = VOX_E5 if octave_up else VOX_E
    vox_high_chord = {"F": vox_g, "G": vox_g, "C": vox_g}
    vox_low_chord  = {"F": vox_e, "G": vox_e, "C": vox_e}

    for bar_idx, (label, bass_p, gtr_p) in enumerate(plan):
        bar_start = bar_idx * 4.0
        is_first = bar_idx == 0
        is_last = bar_idx == len(plan) - 1
        d.extend(_punk_drum_bar(bar_start, crash=is_first, fill=is_last))
        b.extend(_bass_quarters(bass_p, bar_start, 1))
        # Guitar: held chord all bar + stab on beat 4 for punctuation
        g.extend(_power_chord_held(gtr_p, bar_start, 1))
        g.append(_note(gtr_p, bar_start + 3.5, 0.4, 115))
        # Vocal: motif-shaped hook
        v.extend(_motif_at(vox_high_chord[label], vox_low_chord[label], bar_start,
                           vel_base=112))
    return d, b, g, v


def _bridge() -> tuple[list, list, list, list]:
    """8 bars in Eb major. Bars 1-4: drums OUT, bass + gtr + vox in Eb-Ab.
    Bars 5-8: drums return, build into the chorus2 reprise. Bb (V of Eb) on bar 8."""
    d, b, g, v = [], [], [], []
    plan = [
        ("Eb", BASS_EB, GTR_EB, VOX_BB, VOX_G),
        ("Eb", BASS_EB, GTR_EB, VOX_BB, VOX_G),
        ("Ab", BASS_AB, GTR_AB, VOX_EB5, VOX_C),
        ("Ab", BASS_AB, GTR_AB, VOX_EB5, VOX_C),
        ("Eb", BASS_EB, GTR_EB, VOX_BB, VOX_G),
        ("Eb", BASS_EB, GTR_EB, VOX_BB, VOX_G),
        ("Bb", BASS_BB, GTR_BB, VOX_F,   VOX_BB),  # V of Eb
        ("Bb", BASS_BB, GTR_BB, VOX_F,   VOX_BB),  # huge fill bar
    ]
    for bar_idx, (_label, bass_p, gtr_p, vox_hi, vox_lo) in enumerate(plan):
        bar_start = bar_idx * 4.0
        if bar_idx >= 4:
            is_last = bar_idx == len(plan) - 1
            d.extend(_punk_drum_bar(bar_start, crash=(bar_idx == 4), fill=is_last))
        b.extend(_bass_quarters(bass_p, bar_start, 1))  # quarter notes throughout bridge
        g.extend(_power_chord_held(gtr_p, bar_start, 1))
        v.extend(_motif_at(vox_hi, vox_lo, bar_start, vel_base=104))
    return d, b, g, v


def _outro(bars: int) -> tuple[list, list, list, list]:
    """8 bars in Cm — fate motif returns, then abrupt cut on the downbeat of bar 8.
    No fade, no ritard, no goodbye (per decisions/07-energy-aesthetic.md)."""
    d, b, g, v = [], [], [], []
    plan = [
        ("Cm", BASS_C, GTR_C, VOX_G, VOX_EB),
        ("Cm", BASS_C, GTR_C, VOX_G, VOX_EB),
        ("G",  BASS_G, GTR_G, VOX_BB, VOX_G),
        ("G",  BASS_G, GTR_G, VOX_BB, VOX_G),
        ("Cm", BASS_C, GTR_C, VOX_G, VOX_EB),
        ("Cm", BASS_C, GTR_C, VOX_G, VOX_EB),
        ("G",  BASS_G, GTR_G, VOX_BB, VOX_G),  # last motif phrase
    ]
    for bar_idx, (_label, bass_p, gtr_p, vox_hi, vox_lo) in enumerate(plan):
        bar_start = bar_idx * 4.0
        d.extend(_punk_drum_bar(bar_start))
        b.extend(_bass_eighths(bass_p, bar_start, 1))
        g.extend(_motif_at(gtr_p, gtr_p, bar_start, vel_base=110))
        v.extend(_motif_at(vox_hi, vox_lo, bar_start, vel_base=110))
    # Bar 8: one hit on beat 1 from every voice, then silence
    final = (bars - 1) * 4.0
    d.append(_note(KICK,  final + 0.0, 0.3, 122))
    d.append(_note(SNARE, final + 0.0, 0.3, 122))
    d.append(_note(CRASH, final + 0.0, 2.0, 124))
    b.append(_note(BASS_C, final + 0.0, 0.5, 122))
    g.append(_note(GTR_C,  final + 0.0, 0.5, 122))
    v.append(_note(VOX_C,  final + 0.0, 0.5, 122))
    return d, b, g, v


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------


def build(reset: bool = False) -> str:
    """Build the song. Returns the song_id (UUID hex).

    W12-A: this is a state-converger. Re-running with no source changes is
    a no-op (zero net events). Mutators inside `build_session` are
    idempotent — second call with identical args returns kind='unchanged'.
    Build-owned rows from a prior build that aren't touched this run get
    tombstoned automatically at session exit. Pulled rows (actor='sync')
    and LLM-authored edits survive.

    `--reset` remains an escape hatch for "wipe the DB and start fresh"
    but is no longer required in the normal flow.
    """
    if reset and DB_PATH.exists():
        DB_PATH.unlink()

    conn = init_db(DB_PATH)
    try:
        with M.build_session(conn, song_name="punk-fate", owner="build.py"):
            # Mix-half: replay the captured (or synthetic) Ableton session.
            snapshot = json.loads(SNAPSHOT_PATH.read_text())
            song_id = replay_capture(
                conn, snapshot,
                song_name="punk-fate",
                song_title="Punk Fate",
                song_key='Cm',
                actor="sync", reason="initial capture replay",
            )

            # Score-half: tempo, meter, sections, cue points.
            M.set_song_timing_mode(conn, song_id=song_id, timing_mode="native")
            M.add_tempo_point(
                conn, song_id=song_id, start_bar=1.0, tempo_bpm=180.0,
            )
            M.add_time_signature_point(
                conn, song_id=song_id, start_bar=1.0,
                numerator=4, denominator=4,
            )

            # Section markers.
            M.create_section(
                conn, song_id=song_id, name='intro',
                start_bar=float(INTRO_BAR),
                end_bar=float(VERSE_BAR),
            )
            M.create_section(
                conn, song_id=song_id, name='verse',
                start_bar=float(VERSE_BAR),
                end_bar=float(CHORUS_BAR),
            )
            M.create_section(
                conn, song_id=song_id, name='chorus',
                start_bar=float(CHORUS_BAR),
                end_bar=float(VERSE2_BAR),
            )
            M.create_section(
                conn, song_id=song_id, name='verse2',
                start_bar=float(VERSE2_BAR),
                end_bar=float(CHORUS2_BAR),
            )
            M.create_section(
                conn, song_id=song_id, name='chorus2',
                start_bar=float(CHORUS2_BAR),
                end_bar=float(BRIDGE_BAR),
            )
            M.create_section(
                conn, song_id=song_id, name='bridge',
                start_bar=float(BRIDGE_BAR),
                end_bar=float(OUTRO_BAR),
            )
            M.create_section(
                conn, song_id=song_id, name='outro',
                start_bar=float(OUTRO_BAR),
                end_bar=float(END_BAR),
            )

            # Cue points at every section boundary.
            for bar, name in [(INTRO_BAR, 'intro'), (VERSE_BAR, 'verse'), (CHORUS_BAR, 'chorus'), (VERSE2_BAR, 'verse2'), (CHORUS2_BAR, 'chorus2'), (BRIDGE_BAR, 'bridge'), (OUTRO_BAR, 'outro')]:
                M.add_cue_point(
                    conn, song_id=song_id,
                    position_bar=float(bar), name=name,
                )

            tracks = _tracks_by_name(conn, song_id)

            # === Compose-half ===
            _compose(conn, song_id, tracks)

        return song_id
    finally:
        conn.close()


def report(song_id: str) -> None:
    """Print a summary of what got built."""
    conn = init_db(DB_PATH)
    try:
        song_row = Q.get_song(conn, song_id)
        tracks = Q.get_tracks_for_song(conn, song_id)
        print(f"song_id={song_id}, timing_mode={song_row['timing_mode']}, "
              f"tracks={len(tracks)}")
        total_notes = 0
        for t in tracks:
            clips = Q.get_clips_for_track(conn, t["id"])
            notes_in_track = sum(len(Q.get_notes_for_clip(conn, c["id"])) for c in clips)
            total_notes += notes_in_track
            print(f"  track {t['track_index']:>2}  {t['name']:<24} "
                  f"({t['kind']}, {len(clips)} clips, {notes_in_track} notes)")
        sections = [s["name"] for s in Q.get_sections_for_song(conn, song_id)]
        print(f"total notes: {total_notes}")
        print(f"sections: {sections}")
    finally:
        conn.close()


if __name__ == "__main__":
    reset = "--reset" in sys.argv
    song_id = build(reset=reset)
    report(song_id)
