"""Build Sun Zone / Stuff Done into a SQLite DB.

Reggae × speed-metal mashup, authored on the `hallucinote.arrangement` +
`hallucinote.theory` capabilities. A 9-section / 184-bar THROUGH-COMPOSED arc at
a constant 180 BPM (~4:05). Reggae sections feel half-time (effective 90 BPM);
metal sections inhabit 180 directly. Root: E throughout — the song's thesis is "I
remain E while my character (Dorian ↔ Phrygian) evolves", so the climax fuses the
two modes over an E pedal rather than modulating away.

Harmony is FIRST-CLASS here (the arrangement-model harmony axis): every section
declares a real, genre-authentic, MOVING progression — the parts compose against
it via the chord-aware generators, and a build-time conformance lens
(`theory.lint`) fails the build if any section's bass doesn't realize the declared
harmony (the structural fix for the old one-E-chord drone).

The arc tells a story of adapting → accepting both worlds at once:

    intro        16b  reggae  E Dorian     0.25  sun rising: Em7 dawn drone + 3:4:5:7 polyrhythm
    verse1       24b  reggae  E Dorian     0.40  "chillin": i–IV–♭VI–ii, a B7 secondary-dominant push
    chorus1      16b  metal   E Phrygian   0.80  "NO TIME": i–♭II Neapolitan + ♭VI–♭VII descent
    verse2       24b  reggae  E Dorian     0.45  richer (Em9, C#m7♭5 passing); steel pans ENTER
    chorus2      16b  metal   E Phrygian   0.90  darker, more harmonic motion; lead octave-down
    development  24b  morphing E Dorian↔Phr 0.70  the worlds trade bars; harmonic rhythm accelerates
    break        16b  break   (the hinge)  0.72  Em/C# ↔ Em/C slash vote; Amp inverted to HEAVY
    integration  32b  metal   polymodal    1.00  metal engine + polyrhythm recap + the both-at-once split
    outro        16b  reggae  E Dorian     0.35  enlightenment: re-brighten to Dorian, land Em9, calm

Every genre flip is a deliberate ENERGY DISCONTINUITY — never smoothed. The
convention-break decouples Amp TIMBRE from groove TIME-FEEL (a reggae groove
through a HEAVY amp). The integration QUOTES the registered polyrhythm motif
(recapitulation) and resolves it into a `Chord.split` "both-at-once" sonority
(both F#/F and C#/C); the outro fragments + double-times the no-time hook into the
reggae groove (the stress, at peace).

The Rhythm Gtr is the deliberate exception to the per-section clips: it stays
MONOLITHIC — one session clip spanning the whole song (736 beats / 184 bars) —
because the Amp Type envelope (Clean ↔ Heavy, the most audible genre-flip device)
must be hosted by one clip covering its full beat range (Live 12.4 LOM). It voices
the SAME per-section progressions as `arr.plan()`, so boundaries stay in sync.

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
from hallucinote.melody import analyze_arrangement
from hallucinote.theory import Chord, Progression, lint_harmony

# The monophonic melodic line to read with the melody lens (exclude drums + the
# chordal pads/organ). sun-zone-done's two hand-authored hooks live on "05 Lead":
# the reggae "chillin in the sun zone" and the metal "NO TIME FOR THAT" — the
# both-sides acceptance test (melody-model.md §9).
MELODY_LAYERS = ("05 Lead",)

# W12-A: per-branch DB filename.
DB_PATH = resolve_db_path("sun-zone-done", root=Path(__file__).parent.parent)
SNAPSHOT_PATH = Path(__file__).parent / "captured_session.json"

BEATS_PER_BAR = 4.0

# ---------------------------------------------------------------------------
# The narrative arc — the authored section map. Each tuple:
# (name, function, genre, bars, energy). Bar ranges are assigned sequentially by
# Arrangement.plan(); energy is the authored intensity (the curve's direction is
# the SEQUENCE, never smoothed — genre flips are deliberate discontinuities).
# ---------------------------------------------------------------------------
ARC = [
    # name           function   genre     bars  energy
    ("intro",       "intro",   "reggae",   16,   0.25),
    ("verse1",      "verse",   "reggae",   24,   0.40),
    ("chorus1",     "chorus",  "metal",    16,   0.80),
    ("verse2",      "verse",   "reggae",   24,   0.45),
    ("chorus2",     "chorus",  "metal",    16,   0.90),
    ("development", "develop", "reggae",   24,   0.70),
    ("break",       "break",   "reggae",   16,   0.72),
    ("integration", "chorus",  "metal",    32,   1.00),
    ("outro",       "outro",   "reggae",   16,   0.50),   # synthesis: lifted, joyful — NOT sleepy (decisions/07)
]

# Amp Type indices (Live exposes these in order):
# 0=Clean, 1=Boost, 2=Blues, 3=Rock, 4=Lead, 5=Heavy, 6=Bass
AMP_TYPE_VALUE_ITEMS = ["Clean", "Boost", "Blues", "Rock", "Lead", "Heavy", "Bass"]

# Drum pads come from the loaded kit (Kit.from_device), NOT hardcoded MIDI notes.
# With the synthetic snapshot the kit falls through to GM defaults
# (kick 36 / snare 38 / hat 42·46 / crash 49); a real snapshot picks up the kit's
# actual pads (see generators/kit.py — Hot Rod Kit's pad 51 is cowbell, not ride).

# Pitch constants — only the notes the hand-authored melodies use.
E2  = 40   # bass root reference
E3  = 52   # organ bottom + lead floor
G3  = 55
B3  = 59
D4  = 62
E4  = 64   # lead top of reggae range
F4  = 65   # phrygian b2 (metal lead)
FS4 = 66   # E-Dorian 2nd (steel)
G4  = 67
A4  = 69
B4  = 71   # lead climax
C5  = 72   # phrygian b6 (metal lead)
CS5 = 73   # E-Dorian natural 6th — the bright island note (steel)
D5  = 74
E5  = 76   # lead top of metal range

# ---------------------------------------------------------------------------
# THE HARMONIC MAP — per-section progressions (the authored harmony).
# Root E throughout; reggae = E Dorian (the bright natural-6 C#), metal =
# E Phrygian (the dark ♭2 F). Sophisticated by default: extended chords, a
# borrowed ♭VI, a secondary-dominant push, a half-diminished passing chord, the
# i–♭II Neapolitan + ♭VI–♭VII descent, the slash-bass hinge, and the polymodal
# fusion. The chord-aware generators voice these; the conformance lens verifies
# the parts realize them (no stasis).
# ---------------------------------------------------------------------------

# Reggae — E Dorian. The bass is the harmonic agent (it walks the changes).
DRONE = Progression.of("E", "Dorian", ["Em7"], beats_per_chord=8.0)            # intro dawn drone
VERSE1 = Progression.of(                                                       # i–IV–♭VI–ii … V7/i push
    "E", "Dorian", ["Em7", "A7", "Cmaj7", "Bm7", "Em7", "A7", "Bm7", "B7"],
    beats_per_chord=4.0)
VERSE2 = Progression.of(                                                       # richer: Em9, C#m7♭5 passing
    "E", "Dorian", ["Em9", "A7", "C#m7b5", "Bm7", "Em9", "A7", "F#m7", "B7"],
    beats_per_chord=4.0)
OUTRO_H = Progression.of("E", "Dorian", ["Em9", "A7", "Cmaj7", "Em9"], beats_per_chord=4.0)

# Metal — E Phrygian, pedal-point power chords that WALK (root reads the chord).
CHORUS1 = Progression.of(                                                      # i–♭II Neapolitan + ♭VI–♭VII
    "E", "Phrygian", ["E5", "F5", "E5", "F5", "E5", "C5", "D5", "C5"],
    beats_per_chord=4.0)
CHORUS2 = Progression.of(                                                      # darker, more motion
    "E", "Phrygian", ["E5", "F5", "G5", "F5", "E5", "D5", "C5", "F5"],
    beats_per_chord=4.0)

# Development — the morph: Dorian cells answered by Phrygian, harmonic rhythm
# ACCELERATING (4,4 → 2,2,2,2). Declared E Dorian; the Phrygian F is intended
# chromaticism (the lens flags it as a question, not an error).
DEV = Progression.of("E", "Dorian", [
    ("Em7", 4.0), ("A7", 4.0), ("Em", 2.0), ("F", 2.0),
    ("Em7", 2.0), ("A7", 2.0), ("Em", 2.0), ("F", 2.0),
])

# Break — the harmonic HINGE: the bass votes the mode by sliding one semitone,
# C# (Dorian 6) ↔ C (Phrygian ♭6), under an unchanging Em. Amp inverted to HEAVY.
BREAK_H = Progression.of("E", "Dorian", ["Em/C#", "Em/C", "Em/C#", "Em/C"], beats_per_chord=4.0)

# Integration — the fusion: a Phrygian metal riff with the Dorian IV (A5) injected,
# the harmonic "both worlds" gesture under the polyrhythm recap.
INTEG = Progression.of(
    "E", "Phrygian", ["E5", "F5", "E5", "A5", "E5", "F5", "G5", "A5"],
    beats_per_chord=4.0)

# Per-section declared harmony (drives the generators AND the conformance lens).
SECTION_HARMONY: dict[str, Progression] = {
    "intro": DRONE, "verse1": VERSE1, "chorus1": CHORUS1, "verse2": VERSE2,
    "chorus2": CHORUS2, "development": DEV, "break": BREAK_H,
    "integration": INTEG, "outro": OUTRO_H,
}

# The polymodal "both-at-once" sonority — an Em7 carrying BOTH the Dorian F#/C#
# AND the Phrygian F/C. Resolves the intro's polyrhythm cloud at the climax peak.
FUSION_CHORD = Chord.of(4, "m7", split=[6, 5, 1, 0], label="both-at-once")  # Em7 + F#/F + C#/C


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

    With the synthetic snapshot (no probed pad mappings) this falls through to GM
    defaults; once snapshotted from a real Live set the same call picks up that
    kit's actual pad layout. Never hardcode pads."""
    devices = Q.get_devices_for_track(conn, drum_track_id)
    rack = next((d for d in devices if d["kind"] == "Drum Rack"), None)
    if rack is None:
        raise RuntimeError(
            f"Expected a 'Drum Rack' on the drums track; "
            f"found {[d['kind'] for d in devices]}"
        )
    return Kit.from_device(conn, rack["id"], name="Hot Rod Kit")


# ---------------------------------------------------------------------------
# Lead (placeholder vocal melody) — song-specific hooks, stay local.
# The actual vocal hooks ("chillin in the sun zone" / "NO TIME FOR THAT"), not
# reusable idioms. Authored 0-based within a section.
# ---------------------------------------------------------------------------


def _reggae_lead_chillin(length_beats: float) -> list[dict]:
    """'Chillin in the sun zone' — E Dorian melody, mid-register. Loops every 16
    beats (4 bars)."""
    melody = [
        (E4, 0.0, 1.0, 85), (D4, 1.0, 0.5, 80), (B3, 1.5, 0.5, 75),
        (B3, 2.0, 0.5, 72), (G3, 2.5, 0.5, 75), (E3, 3.0, 1.0, 80),
        (B3,  8.0, 0.5, 80), (A4,  8.5, 0.5, 78), (G3,  9.0, 1.0, 82),
        (E3, 10.0, 0.5, 75), (G3, 10.5, 0.5, 76), (B3, 11.0, 0.5, 78),
        (D4, 11.5, 0.5, 80), (E4, 12.0, 3.0, 70),
    ]
    notes: list[dict] = []
    pattern_len = 16.0
    for cycle in range(int(length_beats // pattern_len)):
        offset = cycle * pattern_len
        for p, t, d, v in melody:
            notes.append(_note(p, offset + t, d, v))
    return notes


# The 'NO TIME FOR THAT' hook — one canonical 8-beat (2-bar) cycle, E Phrygian
# stabs (the ♭2 F is the trademark), upper register. Registered as a motif.
_NO_TIME_CYCLE = [
    (E5, 0.0, 0.5, 110), (D5, 1.0, 0.5, 108),
    (C5, 2.0, 0.5, 110), (E5, 3.0, 0.5, 108),
    (E4, 4.0, 0.3, 105), (F4, 4.5, 0.3, 108),
    (G4, 5.0, 0.5, 110), (B4, 6.0, 0.5, 112),
    (E5, 7.0, 1.0, 115),
]


def _no_time_motif() -> list[dict]:
    """The 'NO TIME' hook as a single 0-based cycle — the referenceable motif."""
    return [_note(p, t, d, v) for p, t, d, v in _NO_TIME_CYCLE]


def _metal_lead_no_time(length_beats: float) -> list[dict]:
    """'NO TIME FOR THAT' tiled across the section (loops every 8 beats)."""
    notes: list[dict] = []
    for cycle in range(int(length_beats // 8.0)):
        offset = cycle * 8.0
        for p, t, d, v in _NO_TIME_CYCLE:
            notes.append(_note(p, offset + t, d, v))
    return notes


# ---------------------------------------------------------------------------
# The polyrhythm intro — HAND-AUTHORED, no generator. The gesture IS the art
# (feedback_great_art_not_software): the sun coming up as a 3:4:5:7 cross-rhythm
# shimmer that thickens until it's unbearable, then drops into the verse. Every
# voice is an Em7 chord tone, so the RHYTHM is chaos but the HARMONY stays pure.
# The dense cell is registered as a motif so the integration can call it back.
# ---------------------------------------------------------------------------

_POLY_VOICES = [
    (E3, 1.00),   # the steady pulse (the "4")
    (B3, 0.75),   # the "3"  — first cross-rhythm
    (G3, 1.25),   # the "5"  — wider cross-rhythm
    (D4, 1.75),   # the "7"  — the outer, "unbearable" layer
]
_POLY_DUR = 0.20  # short organ stabs — percolating, not sustained


def _poly_voice(pitch: int, interval: float, start_beat: float, end_beat: float,
                *, vel_at) -> list[dict]:
    """Place ``pitch`` every ``interval`` beats across [start, end). Pure
    note-arithmetic; ``vel_at(t)`` shapes the crescendo."""
    notes: list[dict] = []
    t = start_beat
    while t < end_beat - 1e-9:
        notes.append(_note(pitch, round(t, 6), _POLY_DUR, vel_at(t)))
        t += interval
    return notes


def _polyrhythm_intro(bars: int) -> list[dict]:
    """The additive build: each cross-rhythm voice enters two bars after the last,
    and a velocity ramp drives the whole thing from a quiet dawn to the peak."""
    total = bars * BEATS_PER_BAR

    def ramp(t: float) -> int:
        return int(round(52 + (86 - 52) * (t / total)))  # ~52 (dawn) -> ~86 (peak)

    notes: list[dict] = []
    for idx, (pitch, interval) in enumerate(_POLY_VOICES):
        entry = idx * 2 * BEATS_PER_BAR  # voices enter at bars 1, 3, 5, 7
        notes.extend(_poly_voice(pitch, interval, entry, total, vel_at=ramp))
    return notes


def _polyrhythm_cell(bars: int = 2) -> list[dict]:
    """The full 4-voice polyrhythm at steady intensity — the referenceable motif
    the integration calls back."""
    total = bars * BEATS_PER_BAR
    notes: list[dict] = []
    for pitch, interval in _POLY_VOICES:
        notes.extend(_poly_voice(pitch, interval, 0.0, total, vel_at=lambda _t: 74))
    return notes


# ---------------------------------------------------------------------------
# Per-section layer blueprints (drums / bass / organ / lead — NOT rhythm gtr).
# Each returns a {track name -> notes} map, 0-based within the section. The
# bass / organ are CHORD-AWARE — they voice the section's declared progression,
# so the harmony moves. A track absent from the map doesn't play that section.
# ---------------------------------------------------------------------------


def _reggae_layers(kit: Kit, bars: int, prog: Progression, *,
                   sparse: bool = False) -> dict[str, list[dict]]:
    """A full reggae section: one-drop drums + off-beat bass (walking the chords)
    + organ bubble (voicing the chords) + vocal hook. ``sparse=True`` (the intro)
    drops organ + lead — the sun is just coming up."""
    layers: dict[str, list[dict]] = {
        "01 Drums": DG.reggae_one_drop(bars, kit=kit),
        "02 Bass":  BG.reggae_offbeat_bass(prog, bars=bars),
    }
    if not sparse:
        layers["04 Organ"] = HG.organ_bubble(prog, bars=bars)
        layers["05 Lead"] = _reggae_lead_chillin(bars * BEATS_PER_BAR)
    return layers


# ---------------------------------------------------------------------------
# Metal energy — how great metal SUSTAINS a long section: crash accents at phrase
# tops, fills leading out of phrases, so a long stretch breathes. The musical
# decisions (where crashes/fills land) stay here; the gallop idiom is furniture.
# ---------------------------------------------------------------------------


def _metal_fill(kit: Kit, bar_start_beat: float) -> list[dict]:
    """A 16th-note snare roll across the last three 16ths of the bar, rising in
    velocity — the lead-out that keeps a long metal stretch from going static.
    Starts at 3.25 (AFTER the gallop's beat-3 snare). Kit-safe: snare always
    present; a low-tom accent only if the kit has one."""
    snare = kit.snare
    notes = [
        _note(snare, bar_start_beat + 3.25 + i * 0.25, 0.12, 105 + i * 5)
        for i in range(3)
    ]
    tom = kit.try_pitch_of("tom_lo")
    if tom is not None:
        notes.append(_note(tom, bar_start_beat + 3.75, 0.18, 115))
    return notes


def _metal_drums(kit: Kit, bars: int) -> list[dict]:
    """Gallop drums with sustained energy: a crash on every 4-bar phrase START and
    a snare fill leading OUT of each 4-bar phrase."""
    crash_bars = tuple(range(0, bars, 4))
    notes = DG.metal_gallop(bars, kit=kit, crash_bars=crash_bars)
    for phrase_end in range(3, bars, 4):
        notes.extend(_metal_fill(kit, phrase_end * BEATS_PER_BAR))
    return notes


def _metal_layers(kit: Kit, bars: int, prog: Progression) -> dict[str, list[dict]]:
    """A metal section: gallop drums (crashes + fills) + 16th pedal bass (walking
    the riff) + cutting Phrygian lead. Organ is tacet (it returns only in reggae
    + the integration callback)."""
    return {
        "01 Drums": _metal_drums(kit, bars),
        "02 Bass":  BG.metal_pedal_16ths(prog, bars=bars),
        "05 Lead":  _metal_lead_no_time(bars * BEATS_PER_BAR),
    }


# ---------------------------------------------------------------------------
# Development — the worlds COLLIDE rhythmically, not just harmonically
# (decisions/07). The rhythmic trade is DERIVED FROM THE SAME HARMONIC MAP that
# drives the pitches: walk the progression bar-by-bar; a bar where the Phrygian
# ♭II (F) intrudes goes METAL (gallop + entrance crash, on the grid), a Dorian bar
# stays REGGAE (one-drop, lay-back). The organ bubble + chillin lead persist — the
# reggae voice the metal keeps interrupting. Feel is the genre generators' baked
# default; the COLLISION is which world plays each bar.
# ---------------------------------------------------------------------------


def _dev_collision(kit: Kit, prog: Progression, bars: int) -> dict[str, list[dict]]:
    drums: list[dict] = []
    bass: list[dict] = []
    for b in range(bars):
        bs = b * BEATS_PER_BAR
        bar_prog = prog.slice(bs, BEATS_PER_BAR)
        # The F (♭II, pitch-class 5) is the Phrygian/metal intrusion → this bar trades to metal.
        metal_bar = any(ch.chord.root_pc == 5 for ch in bar_prog.changes)
        if metal_bar:
            drums.extend(DG.metal_gallop(1, kit=kit, start_beat=bs, crash_bars=(0,)))
            bass.extend(BG.metal_pedal_16ths(bar_prog, bars=1, start_beat=bs))
        else:
            drums.extend(DG.reggae_one_drop(1, kit=kit, start_beat=bs))
            bass.extend(BG.reggae_offbeat_bass(bar_prog, bars=1, start_beat=bs))
    return {
        "01 Drums": drums,
        "02 Bass":  bass,
        "04 Organ": HG.organ_bubble(prog, bars=bars),              # reggae bed persists
        "05 Lead":  _reggae_lead_chillin(bars * BEATS_PER_BAR),    # the chill voice the metal interrupts
    }


# ---------------------------------------------------------------------------
# Steel pans — a bright E-Dorian calypso counter-melody entering in the LATER
# reggae sections (verse2 + outro). The natural-6th C# is the Dorian "happy" note
# — the island paradise the protagonist sinks back into.
# ---------------------------------------------------------------------------

_STEEL_FIGURE = [  # a 2-bar offbeat island figure (onset within the 8-beat loop)
    (B4,  0.5, 0.40, 78), (E5,  1.5, 0.40, 82), (CS5, 2.5, 0.40, 75),
    (A4,  3.5, 0.40, 76), (G4,  4.5, 0.40, 78), (B4,  5.5, 0.40, 80),
    (E5,  6.5, 0.50, 84), (FS4, 7.5, 0.40, 74),
]


def _steel_island(bars: int) -> list[dict]:
    """Bright E-Dorian steel-pan counter-melody — calypso offbeats lifting the
    later reggae sections. Loops every 2 bars, up in the pan register."""
    notes: list[dict] = []
    cycle = 2 * BEATS_PER_BAR
    for c in range(int(bars * BEATS_PER_BAR // cycle)):
        base = c * cycle
        for p, t, d, v in _STEEL_FIGURE:
            notes.append(_note(p, base + t, d, v))
    return notes


# ---------------------------------------------------------------------------
# Convention-break + integration + outro.
#
# Convention-break: the Amp TIMBRE is decoupled from the groove's TIME-FEEL. The
# single break is a reggae groove (one-drop + skank + the Em/C#↔Em/C bass vote)
# through a HEAVY amp — metal timbre on reggae time, the "playing with conventions".
#
# Integration: the registered polyrhythm cloud is QUOTED on the organ (the
# recapitulation — the intro's chaos returning inside the metal climax) and
# RESOLVED into the polymodal `FUSION_CHORD` at the peak (both worlds at once).
#
# Outro: the RESOLUTION into a NEW joyful synthesis (decisions/07) — not a retreat
# to sleepy reggae. The no-time hook is AUGMENTED (slowed) and softened — the
# anxiety melody now at peace — and a diatonic LIFT rises the chill into something
# new. The bed is lifted (drag halved). Feel/energy = first-pass, tune by ear.
# ---------------------------------------------------------------------------

_AMP_OVERRIDE = {"break": "Heavy"}  # the convention inversion (reggae groove, metal timbre)


def _amp_for(name: str, genre: str | None) -> str:
    """The Amp Type for a section: genre by default (Heavy=metal, Clean=reggae),
    inverted for the convention-break."""
    if name in _AMP_OVERRIDE:
        return _AMP_OVERRIDE[name]
    return "Heavy" if genre == "metal" else "Clean"


def _polyrhythm_callback(motif_notes: list[dict], bars: int) -> list[dict]:
    """Tile the registered polyrhythm cloud — the intro's chaos returning inside
    the metal climax (the fusion recapitulation)."""
    notes: list[dict] = []
    cell = 2 * BEATS_PER_BAR
    for c in range(int(bars * BEATS_PER_BAR // cell)):
        notes.extend(V.shift(motif_notes, c * cell))
    return notes


def _integration_organ(motif_notes: list[dict], bars: int) -> list[dict]:
    """The integration organ: the polyrhythm recap across the section, RESOLVING
    into the polymodal both-at-once `FUSION_CHORD` over the final 8 bars — the
    intro's pure Em7 cloud blooming into the fused Dorian+Phrygian sonority."""
    notes = _polyrhythm_callback(motif_notes, bars)
    peak_start = (bars - 8) * BEATS_PER_BAR
    for strike in range(2):  # two sustained hits across the last 8 bars
        at = peak_start + strike * 16.0
        for p in FUSION_CHORD.voicing(register=4):
            notes.append(_note(p, at, 16.0, 58))
    return notes


def _augmented_no_time(no_time_motif: list[dict], at_beat: float) -> list[dict]:
    """The 'NO TIME' hook AUGMENTED (slowed 2×) and softened — the same anxiety
    melody, now at peace (decisions/07: the outro RESOLVES, it doesn't retreat).
    ``augment`` keeps the contour and stretches it in time; the velocity drop eases
    the urgency. Its Phrygian color (F / C) sitting calmly over the Dorian bed is
    the fusion, reconciled."""
    slowed = V.augment(no_time_motif, 2.0)                 # 8-beat cycle -> 16 beats, serene
    calm = [{**n, "velocity": max(48, n["velocity"] - 45)} for n in slowed]
    return V.shift(calm, at_beat)


def _outro_lead(bars: int, no_time_motif: list[dict], mode, key_pc: int) -> list[dict]:
    """The outro lead as a RESOLUTION arc (decisions/07): the chillin hook settles
    (0–32), the 'NO TIME' anxiety returns AUGMENTED and at peace (32–48), then a
    diatonic LIFT rises the chill up a third IN KEY — joyful, rising into something
    new (48–64). Not a retreat to sleepy reggae: a synthesis."""
    notes = _reggae_lead_chillin(32.0)                                  # settle (2 cycles)
    notes.extend(_augmented_no_time(no_time_motif, 32.0))               # the anxiety, slowed to peace
    lift = V.transpose_diatonic(_reggae_lead_chillin(16.0),             # the joyful lift (in-key, +a third)
                                mode=mode, key_pc=key_pc, steps=2)
    notes.extend(V.shift(lift, 48.0))
    return notes


def _octave_down(notes: list[dict]) -> list[dict]:
    """Recurrence delta: double a layer an octave lower (heavier / escalating)."""
    return notes + V.transpose(notes, -12)


def _build_arrangement(kit: Kit) -> Arrangement:
    """Author the full through-composed arc on the arrangement + harmony modules.

    Each section declares its real progression (the harmony axis); the chord-aware
    generators voice it so the harmony MOVES. Recurring sections evolve their
    first instance via a harmonic development (a richer/darker progression) PLUS a
    `vary()` layer-delta (steel entering at verse2, the lead octave-doubled at
    chorus2) — multi-axis recurrence, not an independent copy.
    """
    arr = Arrangement(beats_per_bar=BEATS_PER_BAR)
    specs = {name: (function, genre, bars, energy)
             for name, function, genre, bars, energy in ARC}

    poly = arr.motif("polyrhythm-cloud", _polyrhythm_cell())
    no_time = arr.motif("no-time-stab", _no_time_motif())

    def reg(name: str, *, sparse: bool = False) -> dict:
        return _reggae_layers(kit, specs[name][2], SECTION_HARMONY[name], sparse=sparse)

    def met(name: str) -> dict:
        return _metal_layers(kit, specs[name][2], SECTION_HARMONY[name])

    # Intro: sparse rhythm section under the hand-authored polyrhythm build.
    intro = reg("intro", sparse=True)
    intro["04 Organ"] = _polyrhythm_intro(specs["intro"][2])

    verse1 = reg("verse1")
    chorus1 = met("chorus1")

    # verse2: richer harmony (its own progression) + steel ENTERING (add-delta).
    verse2 = vary(reg("verse2"), add={"06 Steel": _steel_island(specs["verse2"][2])})
    # chorus2: darker harmony (own progression) + lead octave-doubled-down (escalation).
    chorus2 = vary(met("chorus2"), transform={"05 Lead": _octave_down})

    # development: the worlds collide rhythmically (feel trades bar-by-bar, derived
    # from the DEV harmonic map — see _dev_collision), not just harmonically.
    development = _dev_collision(kit, SECTION_HARMONY["development"], specs["development"][2])

    # break: the hinge — reggae groove over the Em/C#↔Em/C slash vote (the bass
    # votes the mode), Amp inverted to HEAVY (metal timbre on reggae time).
    break_ = reg("break")

    # integration: metal engine + the polyrhythm recap resolving into the fusion split.
    integration = met("integration")
    integration["04 Organ"] = _integration_organ(poly.notes, specs["integration"][2])

    # outro: the RESOLUTION into a NEW joyful synthesis (decisions/07) — not a
    # retreat to sleepy reggae. The bed is LIFTED (drag halved toward the grid —
    # neither sleepy reggae nor metal-tight), steel pans bring the joy, and the
    # lead resolves the anxiety (augmented no-time hook + a diatonic lift).
    ob = specs["outro"][2]
    outro = {
        "01 Drums": DG.reggae_one_drop(ob, kit=kit, lazy=0.02),
        "02 Bass":  BG.reggae_offbeat_bass(OUTRO_H, bars=ob, push=0.01),
        "04 Organ": HG.organ_bubble(OUTRO_H, bars=ob, lag=0.02),
        "06 Steel": _steel_island(ob),
        "05 Lead":  _outro_lead(ob, no_time.notes, OUTRO_H.mode, OUTRO_H.key_pc),
    }

    layers_by_name = {
        "intro": intro, "verse1": verse1, "chorus1": chorus1, "verse2": verse2,
        "chorus2": chorus2, "development": development, "break": break_,
        "integration": integration, "outro": outro,
    }

    for name, function, genre, bars, energy in ARC:
        arr.section(
            name, function=function, bars=bars, genre=genre, energy=energy,
            progression=SECTION_HARMONY[name], layers=layers_by_name[name],
        )
    return arr


# ---------------------------------------------------------------------------
# Rhythm gtr — ONE long session clip + ONE Amp envelope across sections.
# The deliberate note-floor exception to the arrangement module: a monolithic
# clip hosts the Amp Type device_parameter envelope. It voices the SAME
# per-section progressions as the arrangement, so its seams line up bar-for-bar.
# ---------------------------------------------------------------------------


def _compose_rhythm_gtr(conn, song_id, tracks, placed) -> None:
    """Author the monolithic rhythm-gtr clip + the Amp Type envelope. Reggae
    sections voice the section's progression as a skank; metal sections as
    walking power chords — the gtr now MOVES with the harmony."""
    gtr_track_id = tracks["03 Rhythm Gtr"]
    first_bar = placed[0].start_bar
    total_beats = (placed[-1].end_bar - first_bar) * BEATS_PER_BAR

    all_notes: list[dict] = []
    for sec in placed:
        section_start_beats = (sec.start_bar - first_bar) * BEATS_PER_BAR
        section_bars = sec.end_bar - sec.start_bar
        prog = sec.progression  # resolved per section by plan()
        if sec.genre == "reggae":
            all_notes.extend(HG.reggae_skank(
                prog, bars=section_bars, start_beat=section_start_beats, register=3))
        else:
            all_notes.extend(HG.palm_mute_power_chords(
                prog, bars=section_bars, start_beat=section_start_beats, register=3))

    gtr_clip = M.create_clip(
        conn, track_id=gtr_track_id, slot=1, name="Rhythm Gtr (full song)",
        length_beats=total_beats, section_role=None, actor="build",
        reason="monolithic rhythm gtr clip for Amp envelope hosting",
    )
    M.replace_clip_notes(conn, clip_id=gtr_clip, notes=all_notes,
                         actor="build", reason="initial composition")
    M.add_arrangement_clip(
        conn, song_id=song_id, track_id=gtr_track_id, clip_id=gtr_clip,
        start_bar=float(first_bar), end_bar=float(placed[-1].end_bar),
        actor="build", reason="rhythm gtr full-song placement",
    )

    # --- Amp Type envelope: one breakpoint at every amp change ---
    gtr_devices = Q.get_devices_for_track(conn, gtr_track_id)
    amp_device = next((d for d in gtr_devices if d["kind"] == "Amp"), None)
    if amp_device is None:
        raise RuntimeError(
            f"Expected an 'Amp' device on track '03 Rhythm Gtr'; "
            f"found {[d['kind'] for d in gtr_devices]}"
        )

    breakpoints: list[dict] = []
    last_amp: str | None = None
    for sec in placed:
        amp_value = _amp_for(sec.name, sec.genre)
        if amp_value != last_amp:
            section_start_beats = (sec.start_bar - first_bar) * BEATS_PER_BAR
            breakpoints.append({
                "time_beats": section_start_beats, "value": amp_value,
                "curve_kind": "hold",
            })
            last_amp = amp_value

    M.create_enum_envelope(
        conn, device_id=amp_device["id"], parameter_name="Amp Type",
        breakpoints=breakpoints, value_items=AMP_TYPE_VALUE_ITEMS,
        actor="build", reason="genre-flip amp character at section boundaries",
    )


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------


def melody_report():
    """The per-song convention `tools/melody_lens.py` (and `/compose-review`) calls
    to read the line-level melodic facts (contour, intervals, harmony-fit) of the
    "05 Lead" hooks against their sections' progressions.

    DB-free: the melodic lines and the per-section progressions are authored in
    `build.py`, so the report builds the arrangement with a GM-default kit (drums
    don't affect the line reading) and runs the lens over the in-memory arrangement
    — no Live, no built DB needed. See melody-model.md §7 *Read-side surface*."""
    arr = _build_arrangement(Kit.gm_default())
    return analyze_arrangement(
        arr, song_slug="sun-zone-done", melody_layers=MELODY_LAYERS)


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
                conn, snapshot, song_name="sun-zone-done",
                song_title="Sun Zone / Stuff Done", song_key="Em",
                actor="sync", reason="initial capture replay",
            )

            # Score-half: tempo + meter (constant across the song).
            M.set_song_timing_mode(conn, song_id=song_id, timing_mode="native")
            M.add_tempo_point(conn, song_id=song_id, start_bar=1.0, tempo_bpm=180.0)
            M.add_time_signature_point(
                conn, song_id=song_id, start_bar=1.0, numerator=4, denominator=4)

            # Compose-half: author the arc on the arrangement + harmony modules.
            tracks = _tracks_by_name(conn, song_id)
            kit = _kit_for_drums(conn, tracks["01 Drums"])
            arr = _build_arrangement(kit)
            placed = arr.plan()
            created = arr.materialize(
                conn, song_id=song_id, tracks=tracks,
                author_sections=True, author_cues=True, actor="build")
            _compose_rhythm_gtr(conn, song_id, tracks, placed)

            # Harmony conformance — the structural gate. The bass must realize the
            # declared harmony in every section (no one-chord drone).
            report = lint_harmony(
                arr.section_lints(harmony_layers=["02 Bass"]),
                song_slug="sun-zone-done")

            # Report.
            print(f"song_id={song_id}, tempo=180, key=Em, "
                  f"sections={len(ARC)}, total_bars={arr.total_bars}")
            print(f"  arrangement-module created: {created}")
            print(f"  energy curve:   {[(n, e) for n, e in arr.energy_curve]}")
            print(f"  harmonic curve: {arr.harmonic_curve}")
            print(f"  harmony lint: ok={report.ok}  stasis={report.stasis_sections}")
            for f in report.findings:
                print(f"    [{f.severity}] {f.section}: {f.detail}")

            # Melody lens — the line-level read-side reading (info-only, never a
            # gate; the line is authored, not computed). Same `arr`, so the "05
            # Lead" hooks read identically to `melody_report()`.
            mel = analyze_arrangement(
                arr, song_slug="sun-zone-done", melody_layers=MELODY_LAYERS)
            active = sum(1 for s in mel.sections for ln in s.lines
                         if ln.classification == "active")
            print(f"  melody lens: lines={sum(len(s.lines) for s in mel.sections)} "
                  f"active={active} findings={len(mel.findings)}")
            for f in mel.findings:
                print(f"    [{f.severity}] {f.section}: {f.detail}")

            for tname in ("01 Drums", "02 Bass", "03 Rhythm Gtr",
                          "04 Organ", "05 Lead", "06 Steel"):
                tid = tracks[tname]
                clips = Q.get_clips_for_track(conn, tid)
                total_notes = sum(len(Q.get_notes_for_clip(conn, c["id"]))
                                  for c in clips)
                print(f"  {tname:20s} clips={len(clips)} notes={total_notes}")
            envs = Q.get_envelopes_for_song(conn, song_id)
            print(f"  envelopes: {len(envs)}")
            arrangement = Q.get_arrangement_for_song(conn, song_id)
            print(f"  arrangement placements: {len(arrangement)}")
            cues = Q.get_cue_points(conn, song_id)
            print(f"  cue points: {len(cues)}")

            if not report.ok:
                raise RuntimeError(
                    f"HARMONIC STASIS in {report.stasis_sections}: the parts do "
                    f"not realize the declared harmony. Fix the composition, not "
                    f"the lens.")
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
