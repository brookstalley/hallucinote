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
    break        16b  reggae  E (suspended) 0.72  EUREKA: drums+bass OUT, ethereal FUSION pad + half↔double call-response, riser → bass drop
    integration  32b  metal   polymodal    1.00  PLAYGROUND: 4-bar combine-cells (groove+lead, gallop+float, trade, interlock) → earned fusion
    outro        16b  reggae  E Dorian     0.50  enlightenment: re-brighten to Dorian, land Em9, lifted joy

Every genre flip is a deliberate ENERGY DISCONTINUITY — never smoothed. The
break (decisions/08) is the EUREKA suspension: drums + bass drop OUT, an ethereal
polymodal FUSION pad + thinned shimmer hold the breath while a half↔double-time
call-response lets the two worlds finally answer (not interrupt) each other; a
riser launches the bass DROP. The integration (decisions/08) is the PLAYGROUND:
the worlds genuinely COMBINED cell-by-cell, building to the EARNED climax that
QUOTES the registered polyrhythm motif (recapitulation) and resolves it into the
`Chord.split` "both-at-once" sonority (both F#/F and C#/C). The outro AUGMENTS
(slows) the no-time hook and lifts it in-key into the reggae groove (stress, at peace).

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
from hallucinote.performance.realization import (
    BREATH, HUMAN, PerformanceProfile, apply_profile)
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

# Development — the morph: harmonic rhythm ACCELERATES across the WHOLE section
# (decisions/08 v3), not a looped 5-bar cell. The collision the intent claims is
# now realized harmonically: phase 1 (bars 0–8) settles on slow 8-beat Dorian
# changes; phase 2 (8–16) tightens to 4-beat changes as the Phrygian F intrudes
# (the worlds begin to trade); phase 3 (16–24) is the 2-beat WHIPLASH — chords
# colliding twice as fast, accelerating into the break drop. Declared E Dorian;
# the Phrygian F is intended chromaticism (the lens flags it as a question, not an
# error). Exactly 24 bars (96 beats) — no tiling, so the acceleration is global.
DEV = Progression.of("E", "Dorian", [
    # phase 1 — settled, slow (8-beat Dorian), bars 0–8
    ("Em7", 8.0), ("A7", 8.0), ("Cmaj7", 8.0), ("Bm7", 8.0),
    # phase 2 — the morph, medium (4-beat); F = the Phrygian intrusion, bars 8–16
    ("Em7", 4.0), ("A7", 4.0), ("Em", 4.0), ("F", 4.0),
    ("Em7", 4.0), ("A7", 4.0), ("Bm7", 4.0), ("B7", 4.0),
    # phase 3 — the WHIPLASH, fast (2-beat), bars 16–24: collision at double the rate
    ("Em", 2.0), ("F", 2.0), ("Em", 2.0), ("A7", 2.0),
    ("Em", 2.0), ("F", 2.0), ("G", 2.0), ("F", 2.0),
    ("Em", 2.0), ("F", 2.0), ("Em", 2.0), ("A7", 2.0),
    ("Em", 2.0), ("Bm7", 2.0), ("F", 2.0), ("D", 2.0),
])

# Break — the EUREKA suspension (reinvented): a single sustained polymodal field.
# Bass AND drums drop OUT; the harmony is carried by a sustained FUSION pad on the
# organ, not a walking bass. So the break declares ONE chord (the E tonic the
# insight hovers on) and names no bass — the conformance lens honors a single
# declared chord as a deliberate field (never stasis), and with no bass layer there
# is nothing to flag. The pad voices a richer polymodal colour on top (a texture, not
# a lint target). See decisions/07 + decisions/08 for the reinvention rationale.
BREAK_H = Progression.of("E", "Dorian", ["Em"], beats_per_chord=64.0)

# Integration — the fusion ARC (decisions/08 v3). The old version looped one
# Phrygian power-chord riff ×4, so the "both worlds" only sounded in 2 organ hits at
# the very end — the fusion was cosmetic. Now the HARMONY itself enacts the
# combining, cell by cell (aligned to INTEG_CELLS): the reggae cell is Dorian
# (Em7→A7, the bright C# 6th); the metal cell is Phrygian (Em→F, the dark ♭2); the
# trade cell ALTERNATES them bar-by-bar (A7 Dorian ↔ F Phrygian); the "both" cell
# rubs the two colors at 2-beat rate; the climax pedals E while holding BOTH the
# Phrygian F and the Dorian A7/C# under the polyrhythm recap → the earned both-at-
# once. The bass plays the chord roots (its reggae/metal generators conform either
# way); the organ_bubble voices the full colour. Declared E Phrygian (the metal
# home); the Dorian A7/C# is intended chromaticism (lens flags it as a question).
# 128 beats = exactly the 32-bar section. RENDER-GATED: confirm the fusion reads as
# richness, not mud (the integration is the song's #1 masking-risk section).
INTEG = Progression.of("E", "Phrygian", [
    ("Em7", 8.0), ("A7", 8.0),                              # reggae cell (0–4): Dorian
    ("Em", 8.0), ("F", 8.0),                                # metal cell (4–8): Phrygian
    ("A7", 4.0), ("F", 4.0), ("A7", 4.0), ("F", 4.0),       # trade cell (8–12): alternate
    ("A7", 2.0), ("F", 2.0), ("A7", 2.0), ("F", 2.0),       # both cell (12–16): rub, fast
    ("Em", 2.0), ("F", 2.0), ("A7", 2.0), ("F", 2.0),
    ("Em", 4.0), ("A7", 4.0), ("F", 4.0), ("A7", 4.0),      # climax (16–32): E-centred but
    ("Em", 4.0), ("A7", 4.0), ("F", 4.0), ("A7", 4.0),      #   BRIGHTENING — the Dorian A7 (C#)
    ("Em", 4.0), ("A7", 4.0), ("F", 4.0), ("A7", 4.0),      #   anchors the hybrid hook + foreshadows
    ("Em", 4.0), ("A7", 4.0), ("F", 4.0), ("A7", 4.0),      #   the outro synthesis; F keeps the dark
])

# The integration "playground" cell map — ONE source of truth for the per-cell world
# structure, consumed by BOTH the layer builder (_integration_play) and the rhythm-
# gtr/amp authoring (_compose_rhythm_gtr), so the guitar + amp stay aligned with the
# groove. (start_bar within the 32-bar section, length_bars, world). The worlds:
#   reggae — one-drop groove + offbeat bass + organ, metal lead ANSWERING (active-
#            while-relaxing); the guitar plays a CLEAN skank here.
#   metal  — gallop engine + pedal bass, reggae organ + steel FLOATING over it
#            (chill-while-working).
#   trade  — call & response bar-by-bar (reggae one-drop ↔ metal gallop), the worlds
#            in dialogue, half-time ↔ double-time.
#   both   — both engines interlocking, rising into the climax.
#   climax — both worlds full + the polyrhythm recap + the both-at-once FUSION chord
#            (the EARNED payoff — the culmination of the play, not a cold smash).
INTEG_CELLS = [
    # start_bar  length  world
    (0,  4,  "reggae"),
    (4,  4,  "metal"),
    (8,  4,  "trade"),
    (12, 4,  "both"),
    (16, 16, "climax"),
]

# Per-section declared harmony (drives the generators AND the conformance lens).
SECTION_HARMONY: dict[str, Progression] = {
    "intro": DRONE, "verse1": VERSE1, "chorus1": CHORUS1, "verse2": VERSE2,
    "chorus2": CHORUS2, "development": DEV, "break": BREAK_H,
    "integration": INTEG, "outro": OUTRO_H,
}

# The polymodal "both-at-once" sonority, built as the UNION of the two worlds via
# `Chord.split_chord`: an Em coloured Dorian (the F# 9th + C# 13th) fused with the
# same Em coloured Phrygian (the F ♭9 + C ♭13). split_chord keeps the Dorian Em as
# primary and folds Phrygian's extra pitch-classes (F, C) in as `split`, so the lens
# accepts notes from EITHER world as in-chord. Resolves the intro's polyrhythm cloud
# at the climax peak. (Same pitch-set as the old literal Em7+[F#,F,C#,C], but now
# self-documenting as Dorian ⊕ Phrygian rather than a flat pitch-class list.)
_EM_DORIAN = Chord.of(4, (0, 3, 7, 10, 2, 9), label="Em(Dorian)")      # E G B D + F#(9) + C#(13)
_EM_PHRYGIAN = Chord.of(4, (0, 3, 7, 10, 1, 8), label="Em(Phrygian)")  # E G B D + F(♭9) + C(♭13)
FUSION_CHORD = Chord.split_chord(_EM_DORIAN, _EM_PHRYGIAN, label="both-at-once")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _tracks_by_name(conn, song_id: str) -> dict[str, str]:
    """Map track name -> id for the song. Master included; returns are not."""
    return {row["name"]: row["id"] for row in Q.get_tracks_for_song(conn, song_id)}


# Composer-declared reverb decay intent (decisions/05 + captured_session.json: the
# Plate is a long dub tail, the Room a tight metal punch). Quantifying the snapshot's
# qualitative reverb _notes lets the audio analyzer VERIFY the realized RT60 against
# intent — without it, reverb verification is SKIPPED. DubDelay is an Echo (a delay),
# not a reverb, so it carries no RT60 intent.
_INTENDED_RT60_S = {"Plate": 3.0, "Room": 0.8}


def _declare_reverb_intent(conn, song_id: str) -> None:
    """Declare intended RT60 on every audible send into the reverb returns."""
    for s in Q.get_sends_for_song(conn, song_id):
        rt60 = _INTENDED_RT60_S.get(s["return_name"])
        if rt60 is not None and s["level"] > 0.0:
            M.set_send_intended_rt60(
                conn, from_track_id=s["from_track_id"],
                to_return_id=s["to_return_id"], intended_rt60_s=rt60,
                actor="build",
                reason="composer-declared reverb decay intent (decisions/05)")


def _note(pitch: int, start: float, dur: float, vel: int,
          tags: list[str] | None = None) -> dict:
    # Hand-authored content carries semantic tags too (matching the generators'
    # convention) so the song's signature lines stay addressable by tag-based ops.
    return {"pitch": pitch, "start_beats": start,
            "duration_beats": dur, "velocity": vel, "tags": tags or []}


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
            notes.append(_note(p, offset + t, d, v, tags=["lead", "reggae"]))
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
    return [_note(p, t, d, v, tags=["lead", "metal", "no-time"])
            for p, t, d, v in _NO_TIME_CYCLE]


def _metal_lead_no_time(length_beats: float) -> list[dict]:
    """'NO TIME FOR THAT' tiled across the section (loops every 8 beats)."""
    notes: list[dict] = []
    for cycle in range(int(length_beats // 8.0)):
        offset = cycle * 8.0
        for p, t, d, v in _NO_TIME_CYCLE:
            notes.append(_note(p, offset + t, d, v, tags=["lead", "metal", "no-time"]))
    return notes


# The HYBRID hook (decisions/08 v3) — the NEW idea the playground BIRTHS, the
# missing "something generated by the fusion". It is the NO-TIME hook's rhythm +
# contour with every DARK Phrygian degree flipped to its BRIGHT Dorian neighbour
# (F→F#, C→C#) and landing on the natural-6 C# (the "sun zone" note) instead of the
# tense E: the rhythm still says "NO TIME", the pitches now say "sun zone". It is
# "I don't have to choose" as a single line — neither pure reggae nor pure metal,
# built from BOTH hooks' own DNA so it sounds inevitable, not bolted on. Debuts in
# the integration "both" cell (the play discovering it), is crowned octave-doubled
# in the climax (its melodic identity), and returns AUGMENTED in the outro as the
# synthesis. RENDER-GATED: confirm it reads as a hook, not a contrivance.
_HYBRID_CYCLE = [
    (E5,  0.0, 0.5, 100), (D5,  1.0, 0.5,  96),
    (CS5, 2.0, 0.5, 100), (E5,  3.0, 0.5,  96),   # C# (bright 6) where NO-TIME had C (♭6)
    (E4,  4.0, 0.3,  92), (FS4, 4.5, 0.3,  96),   # F# (bright 2) where NO-TIME had F (♭2)
    (A4,  5.0, 0.5, 100), (B4,  6.0, 0.5, 102),
    (CS5, 7.0, 1.0, 104),                          # lands bright (the 6th), the urgency turned joyful
]


def _hybrid_hook() -> list[dict]:
    """The hybrid hook as a single 0-based 8-beat cycle (the referenceable idea)."""
    return [_note(p, t, d, v, tags=["lead", "hybrid", "fusion"])
            for p, t, d, v in _HYBRID_CYCLE]


def _hybrid_lead(length_beats: float) -> list[dict]:
    """The hybrid hook tiled across a section (loops every 8 beats)."""
    notes: list[dict] = []
    for cycle in range(int(length_beats // 8.0)):
        offset = cycle * 8.0
        for p, t, d, v in _HYBRID_CYCLE:
            notes.append(_note(p, offset + t, d, v, tags=["lead", "hybrid", "fusion"]))
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
        notes.append(_note(pitch, round(t, 6), _POLY_DUR, vel_at(t),
                           tags=["polyrhythm", "organ"]))
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
        _note(snare, bar_start_beat + 3.25 + i * 0.25, 0.12, 105 + i * 5,
              tags=["drums", "metal", "fill"])
        for i in range(3)
    ]
    tom = kit.try_pitch_of("tom_lo")
    if tom is not None:
        notes.append(_note(tom, bar_start_beat + 3.75, 0.18, 115,
                           tags=["drums", "metal", "fill"]))
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


def _verse1_metal_punctuation(layers: dict[str, list[dict]], kit: Kit, *,
                              at_beat: float = 44.0) -> dict[str, list[dict]]:
    """A subtle 1-bar Phrygian metal punctuation ~halfway through verse1 (bar 12) —
    the metal side poking through the long chill BEFORE chorus1's full interruption.
    For one bar the reggae one-drop yields to a softened gallop burst and the chillin
    lead cuts out for the 'NO TIME' head; then the groove resumes. Low velocity — a
    shadow, not the flip. Merged AFTER breathing, so the metal hint stays machine-
    tight while the reggae bed breathes (decisions/06: metal is on-grid)."""
    lo, hi = at_beat, at_beat + BEATS_PER_BAR

    def _outside(n: dict) -> bool:
        return not (lo - 1e-9 <= n["start_beats"] < hi - 1e-9)

    out = {k: list(v) for k, v in layers.items()}
    # Drums: the one-drop yields to a softened gallop burst (entrance crash) for one bar.
    drums = [n for n in out.get("01 Drums", []) if _outside(n)]
    burst = DG.metal_gallop(1, kit=kit, start_beat=at_beat, crash_bars=(0,))
    drums.extend({**n, "velocity": max(62, n["velocity"] - 26)} for n in burst)
    out["01 Drums"] = drums
    # Lead: the chill cuts out; the 'NO TIME' head pokes through, softened.
    lead = [n for n in out.get("05 Lead", []) if _outside(n)]
    frag = V.fragment(_no_time_motif(), 0.0, 3.0)
    lead.extend(V.shift([{**n, "velocity": max(74, n["velocity"] - 22)} for n in frag], at_beat))
    out["05 Lead"] = lead
    return out


# ---------------------------------------------------------------------------
# Development — the worlds COLLIDE rhythmically, not just harmonically
# (decisions/07). The rhythmic trade is DERIVED FROM THE SAME HARMONIC MAP that
# drives the pitches: walk the progression bar-by-bar; a bar where the Phrygian
# ♭II (F) intrudes goes METAL (gallop + entrance crash, on the grid), a Dorian bar
# stays REGGAE (one-drop, lay-back). The organ bubble + chillin lead persist — the
# reggae voice the metal keeps interrupting. Feel is the genre generators' baked
# default; the COLLISION is which world plays each bar.
# ---------------------------------------------------------------------------


def _dev_polyrhythm_creep(start_beat: float, end_beat: float, *,
                          hot: bool = False) -> list[dict]:
    """The intro's 3:4:5:7 cloud CREEPING back into the development organ — two high
    cross-rhythm voices (a third when ``hot``), velocity ramping up across the window,
    foreshadowing the integration's polyrhythm recap. The dawn cloud the protagonist
    can't escape, quietly reforming under the collision."""
    voices = [(B3, 0.75), (D4, 1.25)] + ([(G3, 1.0)] if hot else [])
    lo, hi = (40, 66) if hot else (26, 46)
    span = max(1.0, end_beat - start_beat)

    def vel_at(t: float) -> int:
        return int(round(lo + (hi - lo) * ((t - start_beat) / span)))

    notes: list[dict] = []
    for pitch, interval in voices:
        notes.extend(_poly_voice(pitch, interval, start_beat, end_beat, vel_at=vel_at))
    return notes


def _dev_fill(kit: Kit, start_beat: float) -> list[dict]:
    """A 1-bar snare fill closing the development — a crescendo of 16ths at the tension
    peak, launching the DROP into the eureka break (where everything cuts to silence)."""
    snare = kit.snare
    notes: list[dict] = []
    t, vel = start_beat, 84.0
    while t < start_beat + BEATS_PER_BAR - 1e-9:
        notes.append(_note(snare, round(t, 6), 0.12, min(122, int(vel)),
                           tags=["drums", "fill", "development"]))
        vel += 5
        t += 0.25
    return notes


def _dev_collision(kit: Kit, prog: Progression, bars: int) -> dict[str, list[dict]]:
    """The development: the worlds COLLIDE with accelerating whiplash — THROUGH-COMPOSED
    as a 3-phase arc, not the old tiled loop (which repeated one ~5-bar collision cell
    until it read as 'parts just glued together differently'). Authored for the 24-bar
    development (the ARC fixes its length):

      Phase 1 (bars 0–8):  a settled reggae groove with brief metal POKES (the shout
                           poking through the long chill).
      Phase 2 (8–16):      2-bar reggae↔metal TRADES, the intro polyrhythm cloud
                           CREEPING back into the organ, the steel island entering.
      Phase 3 (16–24):     rapid bar-by-bar WHIPLASH accelerating, velocities rising,
                           the chillin lead FRAGMENTING under NO-TIME stabs, a gallop
                           crescendo + snare fill launching the break's drop-out.

    The contrast intensifies toward the eureka; nothing just loops. Bass reads each
    bar's chord (harmony-lint motion preserved); the persistent reggae bed + the
    polyrhythm creep + the lead get breathed (see _build_arrangement)."""
    drums: list[dict] = []
    bass:  list[dict] = []
    organ: list[dict] = []
    lead:  list[dict] = []
    steel: list[dict] = []
    no_time_head = V.fragment(_no_time_motif(), 0.0, 4.0)   # the 'NO TIME' shout (first half)

    def _bp(b: int) -> Progression:   # the bar's chord slice (bass/organ realize it → lint motion)
        return prog.slice(b * BEATS_PER_BAR, BEATS_PER_BAR)

    def reggae_bar(b: int) -> None:
        bs = b * BEATS_PER_BAR
        drums.extend(DG.reggae_one_drop(1, kit=kit, start_beat=bs))
        bass.extend(BG.reggae_offbeat_bass(_bp(b), bars=1, start_beat=bs))

    def metal_bar(b: int, *, crash: bool = False, kv: int = 108, sv: int = 115) -> None:
        bs = b * BEATS_PER_BAR
        drums.extend(DG.metal_gallop(1, kit=kit, start_beat=bs,
                                     crash_bars=(0,) if crash else (),
                                     kick_velocity=kv, snare_velocity=sv))
        bass.extend(BG.metal_pedal_16ths(_bp(b), bars=1, start_beat=bs))

    # --- Phase 1 (bars 0–8): settled reggae + brief metal pokes ---
    for b in range(0, 8):
        if b in (4, 7):
            metal_bar(b, crash=(b == 4))
            lead.extend(V.shift(no_time_head, b * BEATS_PER_BAR))   # the shout pokes through
        else:
            reggae_bar(b)
    organ.extend(HG.organ_bubble(prog.slice(0.0, 8 * BEATS_PER_BAR), bars=8))
    lead.extend(_reggae_lead_chillin(8 * BEATS_PER_BAR))            # the chill through-line (2 cycles)

    # --- Phase 2 (bars 8–16): 2-bar trades + polyrhythm creep + steel ---
    for b in range(8, 16):
        block_metal = ((b - 8) // 2) % 2 == 1
        if block_metal:
            metal_bar(b, crash=((b - 8) % 2 == 0))
            if (b - 8) % 2 == 0:                                    # shout on each metal block downbeat
                lead.extend(V.shift(_no_time_motif(), b * BEATS_PER_BAR))
        else:
            reggae_bar(b)
            if (b - 8) % 2 == 0:                                    # a chill fragment answers on reggae blocks
                lead.extend(V.shift(V.fragment(_reggae_lead_chillin(16.0), 0.0, 4.0),
                                    b * BEATS_PER_BAR))
    organ.extend(HG.organ_bubble(prog.slice(8 * BEATS_PER_BAR, 8 * BEATS_PER_BAR),
                                 bars=8, start_beat=8 * BEATS_PER_BAR, velocity=46))
    organ.extend(_dev_polyrhythm_creep(8 * BEATS_PER_BAR, 16 * BEATS_PER_BAR))
    steel.extend(V.shift(_steel_island(8), 8 * BEATS_PER_BAR))     # the island enters, lifting

    # --- Phase 3 (bars 16–24): rapid whiplash accelerating into the break drop ---
    for b in range(16, 22):                                        # bar-by-bar collision
        if b % 2 == 0:
            reggae_bar(b)
            lead.extend(V.shift(V.fragment(_reggae_lead_chillin(16.0), 0.0, 2.0),
                                b * BEATS_PER_BAR))                 # chill, fragmenting
        else:
            metal_bar(b, crash=False, kv=110, sv=118)
            lead.extend(V.shift(no_time_head, b * BEATS_PER_BAR))
    metal_bar(22, crash=True, kv=114, sv=120)                      # the gallop crescendo
    lead.extend(V.shift(_no_time_motif(), 22 * BEATS_PER_BAR))
    bass.extend(BG.metal_pedal_16ths(_bp(23), bars=1, start_beat=23 * BEATS_PER_BAR))
    drums.extend(_dev_fill(kit, 23 * BEATS_PER_BAR))               # the fill → the eureka drop-out
    lead.extend(V.shift(no_time_head, 23 * BEATS_PER_BAR))
    organ.extend(_dev_polyrhythm_creep(16 * BEATS_PER_BAR, 24 * BEATS_PER_BAR, hot=True))
    steel.extend(V.shift(_steel_island(8), 16 * BEATS_PER_BAR))

    return {"01 Drums": drums, "02 Bass": bass, "04 Organ": organ,
            "05 Lead": lead, "06 Steel": steel}


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
            notes.append(_note(p, base + t, d, v, tags=["steel", "reggae"]))
    return notes


# ---------------------------------------------------------------------------
# Break (REINVENTED) + integration (REINVENTED) + outro.
#
# Break — the EUREKA (decisions/08): drums AND bass drop OUT. A suspended, ethereal
# field — a sustained polymodal FUSION pad (pp), the intro polyrhythm thinned to a
# slow distant shimmer, and a CALL-AND-RESPONSE between a half-time reggae lead
# fragment and a double-time metal fragment (the two worlds finally LISTENING to
# each other, not interrupting). The last two bars rebuild tension (a snare-roll
# RISER); the bass DROPS IN at the integration downbeat (the insight crystallising).
#
# Integration — the PLAYGROUND (decisions/08): the realization in action. Not metal
# layers with an organ bolted on (the old smash), but the two worlds genuinely
# COMBINED — a sequence of 4-bar "experiment" cells (reggae groove + metal lead
# answering; metal gallop + floating reggae organ/steel; call-response trade; both
# engines interlocking) building to the EARNED climax: both worlds full + the
# polyrhythm recap RESOLVING into the polymodal both-at-once FUSION_CHORD.
#
# Outro: the RESOLUTION into a NEW joyful synthesis (decisions/07) — not a retreat
# to sleepy reggae. The no-time hook is AUGMENTED (slowed) and softened — the
# anxiety melody now at peace — and a diatonic LIFT rises the chill into something
# new. The bed is lifted (drag halved). Feel/energy = first-pass, tune by ear.
# ---------------------------------------------------------------------------


def _amp_for(genre: str | None) -> str:
    """The Amp Type for a section by genre: Heavy=metal, Clean=reggae. (The
    integration's internal Clean→Heavy guitar trade is in _amp_segments; the break
    holds whatever preceded it — its guitar is tacet.)"""
    return "Heavy" if genre == "metal" else "Clean"


def _amp_segments(sec_name: str, genre: str | None) -> list[tuple[float, str]]:
    """(local_start_beat, amp_value) segments within a section. Most sections are a
    single segment; the integration's guitar amp follows INTEG_CELLS cell-by-cell —
    CLEAN in the reggae cell, HEAVY in the metal/both/climax engine, and in the TRADE
    cell it FLIPS BAR-BY-BAR (Clean reggae bar ↔ Heavy metal bar) so the genre-flip
    device itself plays the call-and-response. The break runs HEAVY for the ghosted
    metal guitar DRIFT that haunts the suspension (decisions/08 v2). One source of
    truth = INTEG_CELLS, so the amp lines up with the groove + the guitar part."""
    if sec_name == "integration":
        segs: list[tuple[float, str]] = []
        for start_bar, length, world in INTEG_CELLS:
            cb = start_bar * BEATS_PER_BAR
            if world == "reggae":
                segs.append((cb, "Clean"))
            elif world == "trade":   # the amp trades bar-by-bar with the groove
                for bb in range(length):
                    segs.append((cb + bb * BEATS_PER_BAR,
                                 "Clean" if bb % 2 == 0 else "Heavy"))
            else:                    # metal / both / climax — the Heavy engine
                segs.append((cb, "Heavy"))
        return segs
    if sec_name == "break":
        return [(0.0, "Heavy")]   # the metal-guitar DRIFT through the suspension
    return [(0.0, _amp_for(genre))]


def _polyrhythm_callback(motif_notes: list[dict], bars: int) -> list[dict]:
    """Tile the registered polyrhythm cloud — the intro's chaos returning inside
    the metal climax (the fusion recapitulation)."""
    notes: list[dict] = []
    cell = 2 * BEATS_PER_BAR
    for c in range(int(bars * BEATS_PER_BAR // cell)):
        notes.extend(V.shift(motif_notes, c * cell))
    return notes


# ---------------------------------------------------------------------------
# The break — the eureka suspension. Hand-authored (the gesture IS the art): no
# generator builds "an ethereal field", so this is composed from primitives +
# variation ops. Drums + bass are absent (the drop-out); the pad/shimmer/dialogue
# carry the held breath, and a riser launches the bass drop into the integration.
# ---------------------------------------------------------------------------


def _break_shimmer(total_beats: float) -> list[dict]:
    """The intro polyrhythm THINNED to a slow, distant shimmer — two high voices
    on a slow cross-rhythm, pp, a wash of the dawn cloud heard from far away."""
    notes: list[dict] = []
    for pitch, interval in ((B4, 1.5), (E5, 2.5)):
        t = 0.5  # off the downbeat — floating, not pulsed
        while t < total_beats - 1e-9:
            notes.append(_note(pitch, round(t, 6), 0.6, 36,
                               tags=["organ", "shimmer", "break"]))
            t += interval
    return notes


def _break_call_response(total_beats: float) -> list[dict]:
    """The two worlds in a DIALOGUE THAT DAWNS (decisions/08 v3): a half-time
    (augmented, slowed) reggae 'chillin' CALL, answered by a double-time (diminished,
    fast) 'NO TIME' RESPONSE. The old version repeated the same exchange 4× — static,
    for the song's emotional pivot. Now the realization UNFOLDS across the four
    cycles: the response starts far off (a 2-beat gap) and urgent, then each cycle it
    draws CLOSER to the call and SOFTENS, until the last cycle it OVERLAPS the call's
    tail and is gentle — the worlds stop interrupting and start speaking TOGETHER.
    'They finally listen' is enacted, not labelled. (The v1 static exchange is in git
    history; this evolves the same materials, so the blessed feel is recoverable.)"""
    base_call = V.augment(V.fragment(_reggae_lead_chillin(16.0), 0.0, 4.0), 2.0)
    base_resp = V.diminish(V.fragment(_no_time_motif(), 0.0, 4.0), 2.0)
    # per-cycle (gap-after-call-start, extra response velocity-drop): the response
    # draws IN (10→6 beats) and YIELDS (softens) as the eureka settles.
    arc = [(10.0, 30), (9.0, 38), (8.0, 46), (6.0, 54)]
    notes: list[dict] = []
    cycle = 16.0
    for c in range(int(total_beats // cycle)):
        base = c * cycle
        gap, soften = arc[min(c, len(arc) - 1)]
        call = [{**n, "velocity": max(46, n["velocity"] - 28)} for n in base_call]
        resp = [{**n, "velocity": max(58, n["velocity"] - soften)} for n in base_resp]
        notes.extend(V.shift(call, base))           # call: the slow chill, beats 0–8
        notes.extend(V.shift(resp, base + gap))      # response: drawing in + softening each cycle
    return notes


def _break_sparkle(total_beats: float) -> list[dict]:
    """Sparse high steel sparkle — the ethereal top, one soft wet bell per 4 bars."""
    pitches = (CS5, E5, B4, D5)
    return [_note(pitches[i % len(pitches)], at, 1.5, 34, tags=["steel", "sparkle", "break"])
            for i, at in enumerate((6.0, 22.0, 38.0, 54.0)) if at < total_beats]


def _break_riser(kit: Kit, total_beats: float) -> list[dict]:
    """The RISER: a snare roll across the last two bars, accelerating 8ths→16ths and
    crescendoing — rebuilds the tension the suspension released, launching the bass
    drop at the integration downbeat."""
    snare = kit.snare
    notes: list[dict] = []
    start = total_beats - 8.0  # last two bars
    t, vel = start, 60.0
    while t < total_beats - 1e-9:
        notes.append(_note(snare, round(t, 6), 0.12, min(120, int(vel)),
                           tags=["drums", "riser", "break"]))
        vel += 4
        step = 0.25 if t >= total_beats - 4.0 else 0.5  # last bar tightens to 16ths
        t += step
    return notes


def _break_suspension(kit: Kit, bars: int) -> dict[str, list[dict]]:
    """The whole eureka break: an ethereal suspended field. Drums + bass absent
    (the drop-out); a sustained polymodal FUSION pad + thinned shimmer on the organ,
    a half↔double-time call-response on the lead, sparse steel sparkle, and a riser
    in the last two bars launching the bass drop."""
    total = bars * BEATS_PER_BAR
    pad_voicing = FUSION_CHORD.voicing(register=4)
    organ: list[dict] = []
    for half in range(2):  # two long pad swells across the field, pp
        at = half * (total / 2.0)
        for p in pad_voicing:
            organ.append(_note(p, at, total / 2.0, 40, tags=["organ", "pad", "fusion", "break"]))
    organ.extend(_break_shimmer(total))
    return {
        "04 Organ": organ,
        "05 Lead":  _break_call_response(total),
        "06 Steel": _break_sparkle(total),
        "01 Drums": _break_riser(kit, total),  # the riser only — no groove
    }


# ---------------------------------------------------------------------------
# The integration — the playground. Hand-authored cell-by-cell (per INTEG_CELLS,
# the shared world map) because the *combination* is the musical decision, not a
# generator's: the helpers only place the genre furniture the composer chose for
# each cell (ruler, not stamp). This is the worked example for GEN-1S4K — the
# section-archetype builders (reg/met) could only superpose whole worlds; the
# playground needs interplay, so it is authored at the bar/cell grain here.
# ---------------------------------------------------------------------------


def _integration_climax_organ(motif_notes: list[dict], start_beat: float,
                              bars: int) -> list[dict]:
    """The climax organ: the polyrhythm recap across the climax, RESOLVING into the
    polymodal both-at-once FUSION_CHORD over its final 8 bars — the intro's pure Em7
    cloud blooming into the fused Dorian+Phrygian sonority, now EARNED by the play.
    The recap is the POINT of the climax (the intro returning), so it is voiced FORWARD
    (vel boosted) and the guitar is thinned beneath it (see _integration_climax_gtr_
    swells) — it must stay audible inside the wall, not be buried (mix-intent)."""
    recap = V.shift(_polyrhythm_callback(motif_notes, bars), start_beat)
    # +12 (was +20): the recap now wins primarily by SPACE — steel + the doubled lead are
    # held out of its first 8 bars (see _integration_play climax) — so it needs only a
    # modest lift to cut, not a brute boost. Arrangement subtraction over fader-by-velocity.
    recap = [{**n, "velocity": min(112, n["velocity"] + 12)} for n in recap]
    notes = list(recap)
    peak = start_beat + (bars - 8) * BEATS_PER_BAR
    for strike in range(2):  # two sustained hits across the last 8 bars
        at = peak + strike * 16.0
        for p in FUSION_CHORD.voicing(register=4):
            notes.append(_note(p, at, 16.0, 70, tags=["organ", "fusion"]))
    return notes


def _integration_climax_gtr_swells(prog: Progression, start_beat: float) -> list[dict]:
    """The climax guitar OPENS over the last 8 bars: sustained low power-chord swells
    (root + 5th, following the riff harmony) instead of a chugging wall, at a pulled-
    back velocity — so the polyrhythm organ recap and the both-at-once FUSION chord
    ring THROUGH the climax (the wall resolving into the fused sonority, the earned
    payoff) rather than smearing the low-mids the recap lives in. The arrange/thin fix
    (fix-order #1) for the integration burying its own recapitulation."""
    notes: list[dict] = []
    step = 2 * BEATS_PER_BAR  # one swell per 2 bars
    for i in range(int(8 * BEATS_PER_BAR // step)):
        t = i * step
        for p in prog.chord_at(t).voicing(register=3)[:2]:   # root + 5th = power chord
            notes.append(_note(p, start_beat + t, step * 0.92, 60,
                               tags=["power_chord", "fusion", "climax", "swell"]))
    return notes


def _integration_play(kit: Kit, prog: Progression, poly_notes: list[dict],
                      no_time_notes: list[dict]) -> dict[str, list[dict]]:
    """The 32-bar playground, authored cell-by-cell from INTEG_CELLS. Bass voices
    INTEG in every cell (the harmonic through-line the lens checks); the worlds
    combine differently in each cell, building to the earned fusion climax."""
    drums: list[dict] = []
    bass:  list[dict] = []
    organ: list[dict] = []
    lead:  list[dict] = []
    steel: list[dict] = []

    # A short metal "answer" — the back half of the NO TIME hook, the urgency
    # poking through, placed on the off-bars of a reggae cell.
    answer = V.fragment(no_time_notes, 4.0, 8.0)

    for start_bar, length, world in INTEG_CELLS:
        bs = start_bar * BEATS_PER_BAR
        clen = length * BEATS_PER_BAR
        cell_prog = prog.slice(bs, clen)

        if world == "reggae":
            # Active-while-relaxing: reggae groove + metal lead ANSWERING. THE DROP
            # lands on beat 0 — a low sub slam + kick after the suspended break.
            drums.append(_note(kit.kick, 0.0, 0.20, 122, tags=["drums", "drop"]))
            drums.extend(DG.reggae_one_drop(length, kit=kit, start_beat=bs))
            bass.append(_note(E2 - 12, 0.0, 1.0, 122, tags=["bass", "drop"]))   # the bass DROP
            bass.extend(BG.reggae_offbeat_bass(cell_prog, bars=length, start_beat=bs))
            organ.extend(HG.organ_bubble(cell_prog, bars=length, start_beat=bs))
            lead.extend(V.shift(answer, bs + 6.0))    # urgency answers the chill
            lead.extend(V.shift(answer, bs + 14.0))

        elif world == "metal":
            # Chill-while-working: metal gallop engine, reggae organ + steel FLOATING.
            drums.extend(DG.metal_gallop(length, kit=kit, start_beat=bs, crash_bars=(0,)))
            bass.extend(BG.metal_pedal_16ths(cell_prog, bars=length, start_beat=bs))
            organ.extend(HG.organ_bubble(cell_prog, bars=length, start_beat=bs))  # reggae bed floats over
            steel.extend(V.shift(_steel_island(length), bs))

        elif world == "trade":
            # Call & response bar-by-bar: reggae one-drop (half-time chill) ↔ metal
            # gallop (double-time urgency), the worlds in dialogue, accelerating.
            for b in range(length):
                bbs = bs + b * BEATS_PER_BAR
                bprog = prog.slice(bbs, BEATS_PER_BAR)
                if b % 2 == 0:  # reggae call
                    drums.extend(DG.reggae_one_drop(1, kit=kit, start_beat=bbs))
                    bass.extend(BG.reggae_offbeat_bass(bprog, bars=1, start_beat=bbs))
                    organ.extend(HG.organ_bubble(bprog, bars=1, start_beat=bbs))
                else:           # metal response
                    drums.extend(DG.metal_gallop(1, kit=kit, start_beat=bbs, crash_bars=(0,)))
                    bass.extend(BG.metal_pedal_16ths(bprog, bars=1, start_beat=bbs))
                    lead.extend(V.shift(V.diminish(V.fragment(no_time_notes, 0.0, 4.0), 2.0), bbs))

        elif world == "both":
            # Both engines interlock, rising: the metal drive + reggae organ/steel
            # floating + the NO TIME lead, leaning into the climax.
            drums.extend(DG.metal_gallop(length, kit=kit, start_beat=bs, crash_bars=(0, 2)))
            bass.extend(BG.metal_pedal_16ths(cell_prog, bars=length, start_beat=bs))
            organ.extend(HG.organ_bubble(cell_prog, bars=length, start_beat=bs))
            steel.extend(V.shift(_steel_island(length), bs))
            lead.extend(V.shift(_hybrid_lead(clen), bs))   # the play BIRTHS the hybrid idea

        else:  # "climax" — recap WINS BY SPACE (16–24), then the full PEAK (24–32)
            half = (length // 2) * BEATS_PER_BAR   # 8 bars
            drums.extend(V.shift(_metal_drums(kit, length), bs))   # metal floor + phrase crashes throughout
            bass.extend(BG.metal_pedal_16ths(cell_prog, bars=length, start_beat=bs))
            organ.extend(_integration_climax_organ(poly_notes, bs, length))
            # SUBTRACTION (decisions/08 v3): the first 8 bars EXPOSE the polyrhythm recap —
            # steel out, the hybrid lead single (not doubled) — so the recap wins by SPACE,
            # not the old +20 boost. The last 8 bars bring the full PEAK: steel returns + the
            # hybrid octave-doubled + the gtr swells + the FUSION bloom. The climax now PEAKS
            # at bar 24 instead of running flat-full from its downbeat (16).
            lead.extend(V.shift(_hybrid_lead(half), bs))                       # 16–24: exposed, single
            lead.extend(V.shift(_octave_down(_hybrid_lead(half)), bs + half))  # 24–32: crowned, doubled
            steel.extend(V.shift(_steel_island(length // 2), bs + half))       # steel only in the peak

    return {"01 Drums": drums, "02 Bass": bass, "04 Organ": organ,
            "05 Lead": lead, "06 Steel": steel}


def _augmented_no_time(no_time_motif: list[dict], at_beat: float) -> list[dict]:
    """The 'NO TIME' hook AUGMENTED (slowed 2×) and softened — the same anxiety
    melody, now at peace (decisions/07: the outro RESOLVES, it doesn't retreat).
    ``augment`` keeps the contour and stretches it in time; the velocity drop eases
    the urgency. Its Phrygian color (F / C) sitting calmly over the Dorian bed is
    the fusion, reconciled."""
    slowed = V.augment(no_time_motif, 2.0)                 # 8-beat cycle -> 16 beats, serene
    calm = [{**n, "velocity": max(48, n["velocity"] - 45)} for n in slowed]
    return V.shift(calm, at_beat)


def _augmented_hybrid(at_beat: float) -> list[dict]:
    """The HYBRID hook (the playground's new idea) AUGMENTED (slowed 2×) and softened
    — the synthesis returning at peace (decisions/08 v3). The fused 'I don't have to
    choose' line, reconciled into the outro's Dorian bed: the genuinely NEW idea the
    back half generated, now the resolution. 8-beat cycle -> 16 beats."""
    slowed = V.augment(_hybrid_hook(), 2.0)
    calm = [{**n, "velocity": max(50, n["velocity"] - 40)} for n in slowed]
    return V.shift(calm, at_beat)


def _outro_lead(bars: int, no_time_motif: list[dict]) -> list[dict]:
    """The outro lead as a RESOLUTION arc (decisions/07 + 08): the chillin hook
    settles (0–32), the 'NO TIME' anxiety returns AUGMENTED and at peace (32–48),
    then the HYBRID hook the playground birthed returns AUGMENTED (48–64) — the
    synthesis. Not a retreat to sleepy reggae, and not a mechanical transposition of
    the chill: the genuinely NEW idea the fusion generated, now reconciled."""
    notes = _reggae_lead_chillin(32.0)                                  # settle (2 cycles)
    notes.extend(_augmented_no_time(no_time_motif, 32.0))               # the anxiety, slowed to peace
    notes.extend(_augmented_hybrid(48.0))                               # the synthesis: the new idea, at peace
    return notes


def _octave_down(notes: list[dict]) -> list[dict]:
    """Recurrence delta: double a layer an octave lower (heavier / escalating)."""
    return notes + V.transpose(notes, -12)


# ---------------------------------------------------------------------------
# 1/f breathing (apply_profile) — the performance-authoring layer. Reggae + the
# blend pockets BREATHE: correlated 1/f timing+velocity laid over the generators'
# baked feel, so the perf lens reads them HUMAN (a constant offset reads mechanical;
# white jitter reads sloppy — only 1/f structure reads human). Metal stays machine-
# tight: its parts are never passed to `_breathe` (decisions/07 — tight is correct).
# Each (section, part) draws its own seed so parts breathe independently — a band,
# not one locked performer. k=1.0 = the presets as-authored; tune by ear post-render.
# ---------------------------------------------------------------------------

# Per-part base seed; the section's index is added so each section is a fresh "take".
_PART_SEED = {"01 Drums": 1000, "02 Bass": 2000, "03 Rhythm Gtr": 3000,
              "04 Organ": 4000, "05 Lead": 5000, "06 Steel": 6000}
_SECTION_INDEX = {name: i for i, (name, *_rest) in enumerate(ARC)}

# The reggae rhythm-section + hook pocket: drums/bass/organ on HUMAN, the signature
# lead on BREATH (subtle — humanize the delivery, don't wobble the hook itself).
_REGGAE_BREATH = {"01 Drums": HUMAN, "02 Bass": HUMAN, "04 Organ": HUMAN, "05 Lead": BREATH}


def _seed_for(section: str, track: str) -> int:
    return _PART_SEED[track] + _SECTION_INDEX[section]


def _breathe(layers: dict[str, list[dict]], *, section: str,
             plan: dict[str, PerformanceProfile]) -> dict[str, list[dict]]:
    """Apply 1/f breathing to the named tracks of a section's layer map, each with a
    deterministic per-(section, track) seed. Tracks absent from ``plan`` stay tight
    (metal parts are never passed). Pure: returns a new dict, inputs untouched."""
    out = dict(layers)
    for name, profile in plan.items():
        if name in out:
            out[name] = apply_profile(out[name], profile, seed=_seed_for(section, name))
    return out


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
    # The dawn cloud breathes subtly (organic sunrise); the integration recap of
    # this same motif stays TIGHT (the mechanical climax). Sparse intro = no lead.
    intro = _breathe(intro, section="intro",
                     plan={"01 Drums": HUMAN, "02 Bass": HUMAN, "04 Organ": BREATH})

    # verse1: a subtle metal punctuation pokes through ~halfway (bar 12) — hinting
    # the metal side before chorus1's full interruption. Merged AFTER breathing so
    # the hint stays metal-tight while the reggae bed breathes.
    verse1 = _breathe(reg("verse1"), section="verse1", plan=_REGGAE_BREATH)
    verse1 = _verse1_metal_punctuation(verse1, kit)
    chorus1 = met("chorus1")  # metal — stays machine-tight (never breathed)

    # verse2: richer harmony (its own progression) + steel ENTERING (add-delta).
    verse2 = vary(reg("verse2"), add={"06 Steel": _steel_island(specs["verse2"][2])})
    verse2 = _breathe(verse2, section="verse2",
                      plan={**_REGGAE_BREATH, "06 Steel": HUMAN})
    # chorus2: darker harmony (own progression) + lead octave-doubled-down (escalation).
    chorus2 = vary(met("chorus2"), transform={"05 Lead": _octave_down})  # metal — tight

    # development: the worlds collide rhythmically (feel trades bar-by-bar, derived
    # from the DEV harmonic map — see _dev_collision), not just harmonically.
    development = _dev_collision(kit, SECTION_HARMONY["development"], specs["development"][2])
    # The persistent reggae BED breathes (organ bubble + polyrhythm creep + chillin
    # lead + the entering steel); the bar-by-bar collision drums/bass stay as authored
    # — the contrast IS the point.
    development = _breathe(development, section="development",
                           plan={"04 Organ": HUMAN, "05 Lead": BREATH, "06 Steel": HUMAN})

    # break (REINVENTED — decisions/08): the EUREKA suspension. Drums + bass drop
    # OUT; a sustained polymodal FUSION pad + thinned shimmer carry the held breath,
    # a half↔double-time call-response dialogue plays over it, sparse steel sparkle
    # is the ethereal top, and a snare-roll riser in the last two bars launches the
    # bass DROP into the integration. Only the call-response lead breathes (BREATH) —
    # the pad must not wobble and the riser is a deliberate mechanical build.
    break_ = _breathe(_break_suspension(kit, specs["break"][2]), section="break",
                      plan={"05 Lead": BREATH})

    # integration (REINVENTED — decisions/08): the PLAYGROUND. Not metal layers with
    # an organ bolted on (the old smash) — the two worlds genuinely COMBINED, cell by
    # cell (INTEG_CELLS), building to the EARNED fusion climax (recap + both-at-once
    # chord). Stays machine-tight (engine + climax precision); per-cell breathing is
    # a render-gated dial, not v1.
    integration = _integration_play(kit, SECTION_HARMONY["integration"],
                                    poly.notes, no_time.notes)

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
        "05 Lead":  _outro_lead(ob, no_time.notes),
    }
    # The synthesis pocket — the whole reggae bed breathes together (distinct seeds):
    # a band arriving somewhere new, not a grid with the drag merely halved.
    outro = _breathe(outro, section="outro",
                     plan={"01 Drums": HUMAN, "02 Bass": HUMAN, "04 Organ": HUMAN,
                           "06 Steel": HUMAN, "05 Lead": BREATH})

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


def _strum(notes: list[dict], *, spread: float = 0.012) -> list[dict]:
    """Make a block chord read as a STRUMMED electric guitar, not a keyboard stab:
    rake the notes that share an onset low→high by ``spread`` beats (a pick stroke),
    nudging the top strings a hair louder. A dead-synchronous voicing is exactly what
    made the reggae skank sound 'not quite' like a strum; the rake is the fix. Pure
    note-arithmetic — the composer chose to strum, this only places the rake (ruler,
    not stamp). Song-local for now (candidate promotion once GEN-1S4K resolves the
    generator-altitude question). spread=0.012 beat ≈ 4 ms/string at 180 BPM — a tight
    reggae chop, not a folk sweep; tune by ear at the render."""
    by_onset: dict[float, list[dict]] = {}
    for n in notes:
        by_onset.setdefault(round(n["start_beats"], 4), []).append(n)
    out: list[dict] = []
    for grp in by_onset.values():
        for i, n in enumerate(sorted(grp, key=lambda m: m["pitch"])):
            out.append({**n, "start_beats": n["start_beats"] + i * spread,
                        "velocity": min(127, n["velocity"] + i)})
    return out


def _break_drift() -> list[dict]:
    """The metal guitar DRIFTING through the eureka suspension (decisions/08 v2): sparse,
    SUSTAINED low power-chord swells at a GHOST velocity — the anxiety of the metal world
    still echoing in the moment of peace, distant and (via the clip-local pan sweep)
    panned hard across the field. Voiced as E power chords (root + 5th, no third) so the
    metal timbre stays consonant with the suspension's E-tonic fusion pad, and placed in
    the GAPS around the call-response, not on top of it. Played through the Heavy amp
    (_amp_segments break = Heavy); 'much lower volume than usual' is the velocity floor."""
    voicings = ((E2, E2 + 7), (E3, E3 + 7))   # low + slightly higher E5 power chord
    # (onset_beat, length_beats, voicing_idx) — four long swells drifting in/out over 16 bars
    swells = [(3.0, 9.0, 0), (19.0, 7.0, 1), (35.0, 11.0, 0), (51.0, 9.0, 1)]
    notes: list[dict] = []
    for at, ln, vi in swells:
        for p in voicings[vi]:
            notes.append(_note(p, at, ln, 30, tags=["power_chord", "metal", "drift", "break"]))
    return notes


def _compose_rhythm_gtr(conn, song_id, tracks, placed) -> None:
    """Author the monolithic rhythm-gtr clip + the Amp Type envelope. Reggae
    sections voice the section's progression as a strummed skank; metal sections as
    walking power chords — the gtr now MOVES with the harmony."""
    gtr_track_id = tracks["03 Rhythm Gtr"]
    first_bar = placed[0].start_bar
    total_beats = (placed[-1].end_bar - first_bar) * BEATS_PER_BAR

    def _skank(prog, *, bars, start_beat, section):
        """A breathing, STRUMMED reggae skank — the hand-on-strings chuck raked into a
        pick stroke (_strum), then humanized (HUMAN). Metal power-chord chunks stay
        tight, un-raked (decisions/06)."""
        notes = HG.reggae_skank(prog, bars=bars, start_beat=start_beat, register=3)
        notes = _strum(notes)  # rake the chuck so it reads as a strummed electric, not a stab
        return apply_profile(notes, HUMAN, seed=_seed_for(section, "03 Rhythm Gtr"))

    all_notes: list[dict] = []
    for sec in placed:
        section_start_beats = (sec.start_bar - first_bar) * BEATS_PER_BAR
        section_bars = sec.end_bar - sec.start_bar
        prog = sec.progression  # resolved per section by plan()
        if sec.name == "break":
            # No longer tacet: a ghosted metal-guitar DRIFT haunts the suspension
            # (decisions/08 v2), through the Heavy amp + the clip-local pan sweep.
            all_notes.extend(V.shift(_break_drift(), section_start_beats))
            continue
        if sec.name == "integration":
            # The guitar PLAYS the playground cell-by-cell (one source of truth =
            # INTEG_CELLS): a Clean strummed skank in the reggae cell, the Heavy
            # palm-muted engine in metal/both, a bar-by-bar Clean↔Heavy trade, and in
            # the climax a Heavy gallop that OPENS into sustained power-chord swells so
            # the polyrhythm organ recap + the fusion chord ring through. Velocities are
            # pulled well under the chorus engine (root 84–92 vs 108): the integration
            # must MIX, not dominate — it was burying the organ callback 0.50 in the lows.
            def _engine(p, *, bars, sb, root):
                return HG.palm_mute_power_chords(
                    p, bars=bars, start_beat=sb, register=3, root_velocity=root,
                    fifth_velocity=root - 14, octave_velocity=root - 20)
            for cell_start, cell_len, world in INTEG_CELLS:
                cbeat = section_start_beats + cell_start * BEATS_PER_BAR
                cloc = cell_start * BEATS_PER_BAR
                cprog = prog.slice(cloc, cell_len * BEATS_PER_BAR)
                if world == "reggae":
                    all_notes.extend(_skank(cprog, bars=cell_len, start_beat=cbeat,
                                            section="integration"))
                elif world == "metal":
                    all_notes.extend(_engine(cprog, bars=cell_len, sb=cbeat, root=88))
                elif world == "trade":   # the guitar trades bar-by-bar with the groove
                    for bb in range(cell_len):
                        bbeat = cbeat + bb * BEATS_PER_BAR
                        bprog = prog.slice(cloc + bb * BEATS_PER_BAR, BEATS_PER_BAR)
                        if bb % 2 == 0:
                            all_notes.extend(_skank(bprog, bars=1, start_beat=bbeat,
                                                    section="integration"))
                        else:
                            all_notes.extend(_engine(bprog, bars=1, sb=bbeat, root=88))
                elif world == "both":
                    all_notes.extend(_engine(cprog, bars=cell_len, sb=cbeat, root=92))
                else:  # climax — a driving wall that OPENS into ringing fusion swells
                    drive = cell_len - 8
                    all_notes.extend(_engine(prog.slice(cloc, drive * BEATS_PER_BAR),
                                             bars=drive, sb=cbeat, root=84))
                    all_notes.extend(_integration_climax_gtr_swells(
                        prog.slice(cloc + drive * BEATS_PER_BAR, 8 * BEATS_PER_BAR),
                        cbeat + drive * BEATS_PER_BAR))
            continue
        if sec.genre == "reggae":
            all_notes.extend(_skank(prog, bars=section_bars,
                                    start_beat=section_start_beats, section=sec.name))
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
        section_start_beats = (sec.start_bar - first_bar) * BEATS_PER_BAR
        for local_start, amp_value in _amp_segments(sec.name, sec.genre):
            if amp_value != last_amp:
                breakpoints.append({
                    "time_beats": section_start_beats + local_start, "value": amp_value,
                    "curve_kind": "hold",
                })
                last_amp = amp_value

    M.create_enum_envelope(
        conn, device_id=amp_device["id"], parameter_name="Amp Type",
        breakpoints=breakpoints, value_items=AMP_TYPE_VALUE_ITEMS,
        actor="build", reason="genre-flip amp character at section boundaries",
    )


# ---------------------------------------------------------------------------
# Per-section "space" — the clip-hosted pan/reverb route (MIX-3S7P). The
# atmospheric sections (intro dawn cloud + break suspension) get a wetter Plate tail
# + a gently wider image; the rest of the song keeps the static baseline. The trick
# (the user's): each section's organ/lead/steel CLIP exists ONLY in that section, so
# a clip-local mixer/send envelope inside its beat range is hosted by that clip and
# the mix SNAPS BACK to baseline at verse/chorus automatically — no monolithic host
# clip needed (the push resolves the host clip by beat range; a miss warn+skips,
# non-fatal). Amounts are conservative — render-gated to tune by ear.
# (section, track, plate_send, pan-or-None) — ranges derived from the plan, not
# hardcoded. Envelope identity is (track, target_kind, return, parameter), so each
# (track, param) can carry only ONE clip-local timeline — i.e. ONE atmospheric
# section. The organ is the INTRO's voice; the LEAD + STEEL are the BREAK's floating
# voices (the break's sustained pad rides its 0.20 baseline, already wet, wrapped in
# the wetter lead/steel) — so no track is claimed by both sections (no collision).
_ATMOSPHERE = [
    ("intro", "04 Organ", 0.35, -0.30),   # the dawn cloud — wider + wetter
    ("break", "05 Lead",  0.42, None),     # the call-response floats (wet)
    ("break", "06 Steel", 0.40, 0.34),    # the sparkle — wide right + wet
]


def _author_atmosphere_envelopes(conn, song_id, tracks, placed) -> int:
    """Author the clip-local pan/send 'space' envelopes for intro + break (MIX-3S7P).
    Beat ranges come from the plan so they always sit inside the hosting clip; a hold
    across [start, end-4] keeps the resolver inside the section clip. Returns the count."""
    first_bar = placed[0].start_bar
    bounds = {p.name: ((p.start_bar - first_bar) * BEATS_PER_BAR,
                       (p.end_bar - first_bar) * BEATS_PER_BAR) for p in placed}
    plate = next((r for r in Q.get_returns_for_song(conn, song_id)
                  if r["name"] == "Plate"), None)
    if plate is None:
        raise RuntimeError("expected a 'Plate' return for the atmosphere sends")

    def _hold(env_id: str, start: float, end: float, value: float, what: str) -> None:
        M.replace_breakpoints(conn, envelope_id=env_id, breakpoints=[
            {"time_beats": start, "value": value, "curve_kind": "hold"},
            {"time_beats": max(start, end - 4.0), "value": value, "curve_kind": "hold"},
        ], actor="build", reason=f"hold the {what} across the section (clip-local)")

    n = 0
    for section, track, send, pan in _ATMOSPHERE:
        start, end = bounds[section]
        tid = tracks[track]
        send_env = M.create_envelope(
            conn, song_id=song_id, target_kind="send_level", target_track_id=tid,
            target_send_return_id=plate["id"], actor="build",
            reason=f"{section} atmosphere: wetter Plate (MIX-3S7P, clip-local)")
        _hold(send_env, start, end, send, "elevated Plate send")
        n += 1
        if pan is not None:
            pan_env = M.create_envelope(
                conn, song_id=song_id, target_kind="mixer_pan", target_track_id=tid,
                actor="build",
                reason=f"{section} atmosphere: wider image (MIX-3S7P, clip-local)")
            _hold(pan_env, start, end, pan, "widened pan")
            n += 1
    return n


def _author_break_drift_pan(conn, song_id, tracks, placed) -> int:
    """The EXTREME pan SWEEP on the break's metal-guitar drift (decisions/08 v2): the
    ghosted power chords drift slowly L→R→L across the suspension, dead-center
    everywhere else. The rhythm gtr is a MONOLITHIC clip (it hosts the Amp envelope),
    so unlike the clip-local atmosphere route this is one continuous automation lane
    bookended at center — the guitar in every other section stays centered; only the
    break drift wanders the field. Linear curves = a smooth drift, not a jump."""
    first_bar = placed[0].start_bar
    bounds = {p.name: ((p.start_bar - first_bar) * BEATS_PER_BAR,
                       (p.end_bar - first_bar) * BEATS_PER_BAR) for p in placed}
    bstart, bend = bounds["break"]
    L, R = -0.95, 0.95
    env = M.create_envelope(
        conn, song_id=song_id, target_kind="mixer_pan",
        target_track_id=tracks["03 Rhythm Gtr"], actor="build",
        reason="break drift: extreme L↔R pan sweep (decisions/08 v2)")
    M.replace_breakpoints(conn, envelope_id=env, breakpoints=[
        {"time_beats": 0.0,          "value": 0.0,     "curve_kind": "linear"},
        {"time_beats": bstart,       "value": 0.0,     "curve_kind": "linear"},
        {"time_beats": bstart + 3.0, "value": L,       "curve_kind": "linear"},
        {"time_beats": bstart + 22.0,"value": R,       "curve_kind": "linear"},
        {"time_beats": bstart + 40.0,"value": L,       "curve_kind": "linear"},
        {"time_beats": bend - 4.0,   "value": R * 0.6, "curve_kind": "linear"},
        {"time_beats": bend,         "value": 0.0,     "curve_kind": "linear"},
    ], actor="build", reason="break drift pan sweep (extreme, decisions/08 v2)")
    return 1


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

            # Reverb intent: declare the Plate (long dub) / Room (tight metal)
            # decay times so the audio analyzer can verify them (decisions/05).
            _declare_reverb_intent(conn, song_id)

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
            atmos = _author_atmosphere_envelopes(conn, song_id, tracks, placed)
            atmos += _author_break_drift_pan(conn, song_id, tracks, placed)

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
            print(f"  envelopes: {len(envs)} (1 Amp Type + {atmos} atmosphere pan/send)")
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
