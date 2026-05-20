"""Build Neon Feedback into a SQLite DB using the hallucinote layer.

Disco + prog-metal fusion. Subdivision-halving intro simulates 'too fast to hear' settling to verse tempo. Jazzy disco voicings (Am9, D9, Gmaj7, Cmaj7) in verses, Phrygian power chords (F5, G5, Am) in pre-chorus, modal interchange (Am to A to F#m to D) in the bridge, with a 5/8 bridge-twist section testing section-boundary meter changes. Danceable rhythm with chromatic walk fills, polymetric hat layer in bridge, double-time hat in chorus-2 tag. Designed to exercise chord voicing ergonomics, per-note micro-timing offsets, and refusal paths (tempo automation, meter ratchet).

Section bar layout (1-based, 4/4 throughout — adjust if non-4/4):
    intro        bars  1-8    (8 bars)
    verse-1      bars  9-16   (8 bars)
    pre-chorus-1 bars 17-24   (8 bars)
    chorus-1     bars 25-32   (8 bars)
    verse-2      bars 33-40   (8 bars)
    pre-chorus-2 bars 41-48   (8 bars)
    bridge       bars 49-56   (8 bars)
    bridge-twist bars 57-64   (8 bars)
    bridge-return bars 65-72   (8 bars)
    chorus-2     bars 73-80   (8 bars)
    outro        bars 81-88   (8 bars)

Run:
    python songs/neon-feedback/build.py            # state-converger: re-run is no-op if nothing changed
    python songs/neon-feedback/build.py --reset    # drop + rebuild from scratch
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from hallucinote.capture import replay_capture
from hallucinote.db import init_db, mutations as M, queries as Q, resolve_db_path
from hallucinote.generators.primitives import (
    KICK, SNARE, HAT_CLOSED, HAT_OPEN, CRASH_1, TOM_LO, TOM_HI, RIDE_BELL,
)

# Per-branch DB filename (W12-A): branch switches pick up the right DB
# silently; outside a repo / detached HEAD falls back to neon-feedback.db.
DB_PATH = resolve_db_path("neon-feedback", root=Path(__file__).parent.parent)
SNAPSHOT_PATH = Path(__file__).parent / "captured_session.json"

# Captures the H1 meter-ratchet refusal teaching message so report() can show
# whether the gap fired as expected. None == ratchet did not refuse.
RATCHET_REFUSED: str | None = None


# ---------------------------------------------------------------------------
# Section bar boundaries (1-based) — adjust as the song grows
# ---------------------------------------------------------------------------
# Reshaped from the scaffold's uniform-8-bar grid:
#   intro 8 / verse-1 16 / pre-chorus-1 4 / chorus-1 16 / verse-2 12 /
#   pre-chorus-2 4 / bridge 8 / bridge-twist 1 (5/8) / bridge-return 4 /
#   chorus-2 16 / outro 4  =>  93 bars total (about 3:06 at 120 BPM)
# bridge-twist is one 5/8 bar at a section boundary, testing whether
# meter-ratchet refuses-and-teaches per known limitation (CHANGELOG: H1).
INTRO_BAR = 1
VERSE_1_BAR = 9
PRE_CHORUS_1_BAR = 25
CHORUS_1_BAR = 29
VERSE_2_BAR = 45
PRE_CHORUS_2_BAR = 57
BRIDGE_BAR = 61
BRIDGE_TWIST_BAR = 69
BRIDGE_RETURN_BAR = 70   # bridge-twist is exactly one bar (5/8)
CHORUS_2_BAR = 74
OUTRO_BAR = 90
END_BAR = 94


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _tracks_by_name(conn, song_id: str) -> dict[str, str]:
    """Map track name -> id for the song. Master included; returns are not."""
    return {row["name"]: row["id"] for row in Q.get_tracks_for_song(conn, song_id)}


# ---------------------------------------------------------------------------
# Music theory — chord voicings as MIDI pitch lists
# ---------------------------------------------------------------------------
# No chord-name helper exists in hallucinote.generators (gap). Hand-build
# voicings as sorted MIDI pitches. Octave numbers are scientific (C4 = 60).

A2, B2 = 45, 47
C3, D3, E3, F3, G3, A3, B3 = 48, 50, 52, 53, 55, 57, 59
C4, D4, E4, F4, Fs4, G4, A4, B4 = 60, 62, 64, 65, 66, 67, 69, 71
C5, D5, E5, F5, Fs5, G5, A5, B5 = 72, 74, 76, 77, 78, 79, 81, 83
C6, D6, E6 = 84, 86, 88

# Verse-1 / verse-2: jazzy disco voicings (rootless / 9-chord shells).
# Played on Lead synth comp + arpeggiated outline on Guitar.
AM9   = [A3, C4, E4, G4, B4]            # i9 in Am
D9    = [D3, Fs4, A4, C5, E5]           # IV9 (functions as ii→V to G area)
GMAJ7 = [G3, B3, D4, Fs4, A4]           # bVII Maj7 (modal interchange)
CMAJ7 = [C3, E3, G3, B3, D4]            # bIII Maj7

VERSE_CYCLE = [AM9, D9, GMAJ7, CMAJ7]   # one chord per 2 bars

# Pre-chorus: Phrygian power chords (root + 5th, no 3rd).
F_POW  = [F3, C4]    # bVI
G_POW  = [G3, D4]    # bVII
AM_POW = [A3, E4]    # i

# Chorus: Am – F – C – G (the disco/metal common ground).
AM_TRIAD = [A3, C4, E4]
F_TRIAD  = [F3, A3, C4]
C_TRIAD  = [C4, E4, G4]
G_TRIAD  = [G3, B3, D4]
CHORUS_CYCLE = [AM_TRIAD, F_TRIAD, C_TRIAD, G_TRIAD]   # one chord per bar

# Bridge: modal interchange Am → A → F#m → D (parallel major + relative minor).
Cs3, Cs4 = 49, 61
Fs3 = 54
A_TRIAD   = [A3, Cs4, E4]            # A major
FSM_TRIAD = [Fs3, A3, Cs4]           # F# minor
D_TRIAD   = [D3, Fs3, A3]            # D major
BRIDGE_CYCLE = [AM_TRIAD, A_TRIAD, FSM_TRIAD, D_TRIAD]


def _note(pitch: int, start: float, dur: float, vel: int, tags: list[str]) -> dict:
    return {
        "pitch": pitch, "start_beats": start, "duration_beats": dur,
        "velocity": vel, "tags": list(tags),
    }


# ---------------------------------------------------------------------------
# Swing: 16th-note triplet shuffle. Late 16ths get nudged later.
# ---------------------------------------------------------------------------
# `swing=0.0` -> straight; `swing=1.0` -> triplet (16th lands at 2/3 of beat).
# Disco hi-hat conventionally sits around 0.55-0.65; ~0.6 is a fat groove.

def _swing_16(beat_pos: float, swing: float) -> float:
    """Apply 16th-note swing to a beat position. Late 16ths (the .25 + .75 of
    a beat) get pushed back proportional to `swing` (0.0..1.0)."""
    whole = int(beat_pos)
    frac = beat_pos - whole
    # 16th slots within a beat: 0.00, 0.25, 0.50, 0.75
    slot = round(frac * 4) / 4
    residue = frac - slot
    if slot in (0.25, 0.75):
        # push the off-16ths back; 0.0 -> 0.25; 1.0 -> 0.333 (triplet).
        nudge = (0.333 - 0.25) * swing
        slot = slot + nudge
    return whole + slot + residue


# ---------------------------------------------------------------------------
# Drum patterns — disco, metal, and the intro halving
# ---------------------------------------------------------------------------


def _disco_drums(bars: int, *, start_beat: float = 0.0, swing: float = 0.6,
                 fill_at: int | None = None) -> list[dict]:
    """Four-on-floor kick + 2/4 snare + swung 16th closed hats + offbeat open hat.

    Tags carry intent ('downbeat', 'backbeat', 'hat-offbeat', 'swing').
    """
    out: list[dict] = []
    for b in range(bars):
        bs = start_beat + b * 4.0
        # Kick on every beat (four-on-floor)
        for beat in range(4):
            out.append(_note(KICK, bs + beat, 0.18, 112 if beat == 0 else 100,
                             ["kick", "four-on-floor", "downbeat" if beat == 0 else "beat"]))
        # Snare on 2 and 4
        for beat in (1, 3):
            out.append(_note(SNARE, bs + beat, 0.2, 105, ["snare", "backbeat"]))
        # Closed hats on every 16th, swung
        for sixteenth in range(16):
            t = sixteenth * 0.25
            pos = _swing_16(t, swing)
            vel = 60 if sixteenth % 4 == 0 else 42  # accent on the beat
            tags = ["hat", "16th", "swing" if swing > 0 else "straight"]
            if sixteenth % 4 == 0:
                tags.append("accent")
            out.append(_note(HAT_CLOSED, bs + pos, 0.08, vel, tags))
        # Open hat on the "and" of 2 and 4 (the disco lift)
        for off in (1.5, 3.5):
            out.append(_note(HAT_OPEN, bs + _swing_16(off, swing), 0.25, 75,
                             ["hat", "open", "lift"]))
        # Fill on the last bar if requested
        if fill_at is not None and b == fill_at:
            out.append(_note(TOM_HI, bs + 3.5, 0.12, 92, ["tom", "fill"]))
            out.append(_note(TOM_LO, bs + 3.75, 0.12, 96, ["tom", "fill"]))
    return out


def _metal_drums(bars: int, *, start_beat: float = 0.0,
                 push_snare_ms: float = 0.0, bpm: float = 120.0) -> list[dict]:
    """Double-bass kick on every 8th + snare on 2/4 + ride bell on quarter notes.

    `push_snare_ms` nudges the snare ahead of the beat (negative beats).
    """
    push = -(push_snare_ms / 1000.0) * (bpm / 60.0)  # convert ms -> beats
    out: list[dict] = []
    for b in range(bars):
        bs = start_beat + b * 4.0
        # Double-bass: 8th note kicks
        for eighth in range(8):
            t = eighth * 0.5
            vel = 118 if eighth % 2 == 0 else 105
            out.append(_note(KICK, bs + t, 0.1, vel,
                             ["kick", "double-bass", "metal"]))
        # Snare on 2 and 4, pushed
        for beat in (1, 3):
            out.append(_note(SNARE, bs + beat + push, 0.18, 115,
                             ["snare", "backbeat", "push"]))
        # Ride bell on quarters
        for beat in range(4):
            out.append(_note(RIDE_BELL, bs + beat, 0.18, 88, ["ride", "bell"]))
        # Crash at bar start of every 4
        if b % 4 == 0:
            out.append(_note(CRASH_1, bs, 1.0, 110, ["crash", "downbeat"]))
    return out


def _intro_halving(bars: int = 8, *, start_beat: float = 0.0) -> list[dict]:
    """Subdivision halving 'too fast to hear -> settling' effect at constant BPM.

    Bar 1-2: 32nd hi-hats (16/bar) — blur
    Bar 3-4: 16th hi-hats (4/beat) — distinguishable
    Bar 5-6: 8th hi-hats — rhythmic
    Bar 7-8: quarter kicks + 2/4 snare — resolved to disco pulse
    Style cuts every bar between disco hat layer and metal palm-mute stab.
    """
    out: list[dict] = []
    subdivisions = [32, 32, 16, 16, 8, 8, 4, 4]
    for b in range(bars):
        bs = start_beat + b * 4.0
        n = subdivisions[b]
        step = 4.0 / n
        is_metal = b % 2 == 1  # alternate disco/metal bars
        for i in range(n):
            t = i * step
            if is_metal:
                # Palm-mute stab via low-tom on every other step + ghosts
                if i % 2 == 0:
                    out.append(_note(TOM_LO, bs + t, step * 0.6, 92,
                                     ["tom", "metal-stab", "intro"]))
            else:
                # Disco hat blur — accent every 4th
                vel = 80 if i % 4 == 0 else 50
                out.append(_note(HAT_CLOSED, bs + t, step * 0.4, vel,
                                 ["hat", "intro", "halving"]))
        # Anchor downbeat kick from bar 5 onward (rhythmic settling)
        if b >= 4:
            out.append(_note(KICK, bs, 0.2, 108, ["kick", "anchor", "intro"]))
            if b >= 6:
                out.append(_note(SNARE, bs + 1.0, 0.2, 100, ["snare", "intro"]))
                out.append(_note(SNARE, bs + 3.0, 0.2, 100, ["snare", "intro"]))
    return out


# ---------------------------------------------------------------------------
# Bass: disco octave pumps + metal palm-mute roots
# ---------------------------------------------------------------------------


def _disco_bass(bars: int, chord_cycle: list[list[int]], *,
                start_beat: float = 0.0, beats_per_chord: float = 8.0,
                swing: float = 0.5) -> list[dict]:
    """Octave-jumping 16th bass — classic disco engine. Cycles chord roots."""
    out: list[dict] = []
    chord_idx = 0
    chord_start = 0.0
    for b in range(bars):
        bs = start_beat + b * 4.0
        if (b * 4.0 - chord_start) >= beats_per_chord:
            chord_idx = (chord_idx + 1) % len(chord_cycle)
            chord_start = b * 4.0
        root = chord_cycle[chord_idx][0] - 12   # drop the bass an octave
        octave_up = root + 12
        # 16th-note octave pump pattern: low-high-low-high...
        for sixteenth in range(16):
            t = sixteenth * 0.25
            pos = _swing_16(t, swing)
            pitch = root if sixteenth % 2 == 0 else octave_up
            vel = 100 if sixteenth % 4 == 0 else 78
            out.append(_note(pitch, bs + pos, 0.12, vel,
                             ["bass", "octave-pump", "disco"]))
    return out


def _metal_bass(bars: int, *, start_beat: float = 0.0,
                 root_pitch: int = A2) -> list[dict]:
    """Palm-mute 8th roots — locks with double-bass kick."""
    out: list[dict] = []
    for b in range(bars):
        bs = start_beat + b * 4.0
        for eighth in range(8):
            t = eighth * 0.5
            out.append(_note(root_pitch, bs + t, 0.18, 112,
                             ["bass", "palm-mute", "metal"]))
    return out


# ---------------------------------------------------------------------------
# Guitar / lead / harmony
# ---------------------------------------------------------------------------


def _verse_guitar_arp(bars: int, chord_cycle: list[list[int]], *,
                      start_beat: float = 0.0, beats_per_chord: float = 2.0
                      ) -> list[dict]:
    """16th-note arpeggio outlining each chord — disco rhythm guitar."""
    out: list[dict] = []
    for b in range(bars):
        bs = start_beat + b * 4.0
        # Each chord covers `beats_per_chord` beats; cycle the chord list.
        # For our verse: 2 chords per 4-bar phrase -> beats_per_chord = 8.0 / 4 = 2
        chord_idx_in_bar = ((b * 4) // beats_per_chord) % len(chord_cycle)
        # Two arpeggios in a 4-beat bar at beats_per_chord=2
        for half in range(2):
            chord = chord_cycle[int((b * 4 / beats_per_chord + half) %
                                    len(chord_cycle))]
            half_start = bs + half * 2.0
            for i, p in enumerate(chord[:4]):
                t = half_start + i * 0.25
                out.append(_note(p, t, 0.22, 78,
                                 ["guitar", "arp", "disco-chord"]))
            # Walk back down the upper voices on beats 3-4
            for i, p in enumerate(reversed(chord[1:4])):
                t = half_start + 1.0 + i * 0.25
                out.append(_note(p, t, 0.2, 72, ["guitar", "arp", "descend"]))
    return out


def _pre_chorus_metal_stabs(bars: int, *, start_beat: float = 0.0) -> list[dict]:
    """4 bars: F5 / G5 / Am5 / G5 -- syncopated power-chord stabs.

    Hits on 1, the 'and' of 2, and 4. Pure metal pre-chorus.
    """
    cycle = [F_POW, G_POW, AM_POW, G_POW]
    out: list[dict] = []
    for b in range(bars):
        bs = start_beat + b * 4.0
        chord = cycle[b % len(cycle)]
        for hit, vel in ((0.0, 115), (2.5, 110), (3.0, 118)):
            for p in chord:
                out.append(_note(p, bs + hit, 0.25, vel,
                                 ["guitar", "power-chord", "stab"]))
    return out


def _chorus_lead(bars: int, *, start_beat: float = 0.0,
                 lay_back_beats: float = 0.02) -> list[dict]:
    """Lead-synth hook over Am-F-C-G. Singable, with a chromatic-walk fill at
    bar 8 (or every 8th bar). Snare-pocket placement: notes laid back slightly.
    """
    # Phrase melody (in beats from chord start, pitch, duration):
    #   bar 0 (Am): A4 G4 E4 ...
    #   bar 1 (F):  F4 G4 A4 G4
    #   bar 2 (C):  E4 G4 C5 B4
    #   bar 3 (G):  D5 B4 G4 A4 (lift back to verse)
    bar_melodies = [
        [(0.0, A4, 0.75), (0.75, G4, 0.5), (1.5, E4, 0.5),
         (2.5, A4, 0.5), (3.0, C5, 0.75)],
        [(0.0, F4, 0.5), (0.5, G4, 0.5), (1.5, A4, 0.75),
         (2.5, G4, 0.5), (3.25, F4, 0.5)],
        [(0.0, E4, 0.5), (0.75, G4, 0.5), (1.5, C5, 0.75),
         (2.5, B4, 0.5), (3.0, G4, 0.5)],
        [(0.0, D5, 0.5), (0.5, B4, 0.5), (1.5, G4, 0.5),
         (2.5, A4, 0.5), (3.0, B4, 0.75)],
    ]
    chromatic_walk = [
        (0.0, A4, 0.25), (0.25, As := A4 + 1, 0.25), (0.5, B4, 0.25),
        (0.75, C5, 0.25), (1.0, Cs := C5 + 1, 0.25), (1.25, D5, 0.25),
        (1.5, E5, 1.5), (3.0, C5, 1.0),
    ]
    out: list[dict] = []
    for b in range(bars):
        bs = start_beat + b * 4.0
        in_phrase = b % 4
        notes = chromatic_walk if (b % 8) == 7 else bar_melodies[in_phrase]
        for t, p, dur in notes:
            out.append(_note(p, bs + t + lay_back_beats, dur, 92,
                             ["lead", "hook", "laid-back" if lay_back_beats > 0 else "straight"]))
    return out


def _bridge_pad(bars: int, *, start_beat: float = 0.0) -> list[dict]:
    """Modal-interchange pad: 2 bars per chord, sustained voicings."""
    out: list[dict] = []
    chord_idx = 0
    for b in range(bars):
        if b > 0 and b % 2 == 0:
            chord_idx = (chord_idx + 1) % len(BRIDGE_CYCLE)
        if b % 2 == 0:
            chord = BRIDGE_CYCLE[chord_idx]
            bs = start_beat + b * 4.0
            for p in chord:
                out.append(_note(p, bs, 8.0, 70, ["pad", "modal-interchange"]))
    return out


def _bridge_polyhat(bars: int, *, start_beat: float = 0.0) -> list[dict]:
    """Hat layer in 3-over-4 polymeter: dotted-eighth hits across straight 4/4.

    Tests whether straightforward polymetric layering survives push/pull.
    """
    out: list[dict] = []
    total_beats = bars * 4.0
    step = 0.75  # dotted-eighth = 3 sixteenths
    t = 0.0
    while t < total_beats:
        vel = 75 if abs(t - round(t)) < 0.01 else 55
        out.append(_note(HAT_CLOSED, start_beat + t, 0.1, vel,
                         ["hat", "polymeter", "3-over-4"]))
        t += step
    return out


def _outro_motif(bars: int, *, start_beat: float = 0.0) -> list[dict]:
    """Half-time outro: kick on 1, snare on 3, intro hat motif fades out."""
    out: list[dict] = []
    for b in range(bars):
        bs = start_beat + b * 4.0
        out.append(_note(KICK, bs, 0.3, 100, ["kick", "outro", "half-time"]))
        out.append(_note(SNARE, bs + 2.0, 0.3, 95, ["snare", "outro", "half-time"]))
        # Decaying intro hat motif — quarters at decreasing velocity
        fade = max(20, 70 - b * 15)
        for beat in range(4):
            out.append(_note(HAT_CLOSED, bs + beat, 0.1, fade,
                             ["hat", "outro", "fade"]))
    return out


# ---------------------------------------------------------------------------
# Top-level compose
# ---------------------------------------------------------------------------


def _compose(conn, song_id: str, tracks: dict[str, str]) -> None:
    """Create per-section clips for every track, then place them in the arrangement.

    Each section gets one clip per track. Empty section/track combos are skipped.
    """
    # Map: (section_name, track_name) -> notes
    sections: list[tuple[str, int, int, dict[str, list[dict]]]] = []

    # intro -- 8 bars, 32 beats
    sections.append(("intro", INTRO_BAR, VERSE_1_BAR, {
        "Drums": _intro_halving(8),
    }))

    # verse-1 -- 16 bars
    sections.append(("verse-1", VERSE_1_BAR, PRE_CHORUS_1_BAR, {
        "Drums": _disco_drums(16, swing=0.55),
        "Bass":  _disco_bass(16, VERSE_CYCLE, beats_per_chord=8.0, swing=0.55),
        "Guitar": _verse_guitar_arp(16, VERSE_CYCLE, beats_per_chord=2.0),
    }))

    # pre-chorus-1 -- 4 bars metal stabs
    sections.append(("pre-chorus-1", PRE_CHORUS_1_BAR, CHORUS_1_BAR, {
        "Drums":  _metal_drums(4, push_snare_ms=10.0),
        "Bass":   _metal_bass(4),
        "Guitar": _pre_chorus_metal_stabs(4),
    }))

    # chorus-1 -- 16 bars hybrid; chromatic walk at internal bar 7
    sections.append(("chorus-1", CHORUS_1_BAR, VERSE_2_BAR, {
        "Drums": _disco_drums(16, swing=0.5, fill_at=15),
        "Bass":  _disco_bass(16, CHORUS_CYCLE, beats_per_chord=4.0, swing=0.5),
        "Guitar": _verse_guitar_arp(16, CHORUS_CYCLE, beats_per_chord=1.0),
        "Lead":  _chorus_lead(16, lay_back_beats=0.025),
    }))

    # verse-2 -- 12 bars, more swing
    sections.append(("verse-2", VERSE_2_BAR, PRE_CHORUS_2_BAR, {
        "Drums": _disco_drums(12, swing=0.62),
        "Bass":  _disco_bass(12, VERSE_CYCLE, beats_per_chord=8.0, swing=0.62),
        "Guitar": _verse_guitar_arp(12, VERSE_CYCLE, beats_per_chord=2.0),
    }))

    # pre-chorus-2 -- 4 bars metal stabs (same)
    sections.append(("pre-chorus-2", PRE_CHORUS_2_BAR, BRIDGE_BAR, {
        "Drums":  _metal_drums(4, push_snare_ms=10.0),
        "Bass":   _metal_bass(4),
        "Guitar": _pre_chorus_metal_stabs(4),
    }))

    # bridge -- 8 bars modal-interchange pad + polymetric hat
    sections.append(("bridge", BRIDGE_BAR, BRIDGE_TWIST_BAR, {
        "Drums": _bridge_polyhat(8),
        "Guitar": _bridge_pad(8),
    }))

    # bridge-twist -- 1 bar of 5/8 (push-time meter will refuse)
    # We still author this bar's clip with 5 beats of content so it sounds
    # right if a future push handles the meter ratchet.
    twist_notes_drums = [
        _note(KICK, 0.0, 0.2, 110, ["kick", "twist", "5-8"]),
        _note(KICK, 1.5, 0.2, 108, ["kick", "twist", "5-8"]),
        _note(SNARE, 1.0, 0.18, 105, ["snare", "twist"]),
        _note(SNARE, 3.0, 0.18, 105, ["snare", "twist"]),
        _note(CRASH_1, 0.0, 1.0, 115, ["crash", "twist"]),
    ]
    twist_notes_guitar = [
        _note(p, 0.0, 2.5, 115, ["guitar", "power-chord", "twist"])
        for p in AM_POW
    ]
    sections.append(("bridge-twist", BRIDGE_TWIST_BAR, BRIDGE_RETURN_BAR, {
        "Drums":  twist_notes_drums,
        "Guitar": twist_notes_guitar,
    }))

    # bridge-return -- 4 bars metal stabs feeding back into chorus-2
    sections.append(("bridge-return", BRIDGE_RETURN_BAR, CHORUS_2_BAR, {
        "Drums":  _metal_drums(4, push_snare_ms=15.0),
        "Bass":   _metal_bass(4),
        "Guitar": _pre_chorus_metal_stabs(4),
    }))

    # chorus-2 -- 16 bars with double-time hi-hat tag in last 4 bars
    chorus2_drums = _disco_drums(12, swing=0.5, fill_at=11)
    # Double-time hat for bars 12-15 (last 4 bars of chorus-2)
    for bar_idx in range(12, 16):
        bs = bar_idx * 4.0
        for i in range(32):  # 32nd-note hat
            t = bs + i * 0.125
            chorus2_drums.append(_note(HAT_CLOSED, t, 0.05,
                                       55 if i % 4 == 0 else 35,
                                       ["hat", "double-time", "tag"]))
        # Keep the four-on-floor kick + 2/4 snare under the hat
        for beat in range(4):
            chorus2_drums.append(_note(KICK, bs + beat, 0.18, 110,
                                       ["kick", "four-on-floor", "tag"]))
        for beat in (1, 3):
            chorus2_drums.append(_note(SNARE, bs + beat, 0.2, 108,
                                       ["snare", "backbeat", "tag"]))
    sections.append(("chorus-2", CHORUS_2_BAR, OUTRO_BAR, {
        "Drums": chorus2_drums,
        "Bass":  _disco_bass(16, CHORUS_CYCLE, beats_per_chord=4.0, swing=0.5),
        "Guitar": _verse_guitar_arp(16, CHORUS_CYCLE, beats_per_chord=1.0),
        "Lead":  _chorus_lead(16, lay_back_beats=0.025),
    }))

    # outro -- 4 bars half-time
    sections.append(("outro", OUTRO_BAR, END_BAR, {
        "Drums": _outro_motif(4),
    }))

    # Materialize: one clip per (section, track) with notes.
    slot_counter: dict[str, int] = {name: 0 for name in tracks}
    for section_name, start_bar, end_bar, track_notes in sections:
        length_beats = float((end_bar - start_bar) * 4)
        # bridge-twist was designed as 5/8 (2.5 beats) but H1 refused the
        # meter ratchet, so the bar plays as 4/4. Authored notes sit in beats
        # 0-3, leaving beat 3-4 as a deliberate hesitation.
        for track_name, notes in track_notes.items():
            track_id = tracks.get(track_name)
            if not track_id or not notes:
                continue
            clip_name = f"{section_name}-{track_name.lower()}"
            slot = slot_counter[track_name]
            slot_counter[track_name] += 1
            clip_id = M.create_clip(
                conn, track_id=track_id, slot=slot,
                length_beats=length_beats, name=clip_name,
                section_role=section_name,
            )
            M.replace_clip_notes(conn, clip_id=clip_id, notes=notes)
            M.add_arrangement_clip(
                conn, song_id=song_id, track_id=track_id, clip_id=clip_id,
                start_bar=float(start_bar), end_bar=float(end_bar),
            )


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
        with M.build_session(conn, song_name="neon-feedback", owner="build.py"):
            # Mix-half: replay the captured (or synthetic) Ableton session.
            snapshot = json.loads(SNAPSHOT_PATH.read_text())
            song_id = replay_capture(
                conn, snapshot,
                song_name="neon-feedback",
                song_title="Neon Feedback",
                song_key='Am',
                actor="sync", reason="initial capture replay",
            )

            # Score-half: tempo, meter, sections, cue points.
            M.set_song_timing_mode(conn, song_id=song_id, timing_mode="native")
            M.add_tempo_point(
                conn, song_id=song_id, start_bar=1.0, tempo_bpm=120.0,
            )
            M.add_time_signature_point(
                conn, song_id=song_id, start_bar=1.0,
                numerator=4, denominator=4,
            )

            # Section markers.
            M.create_section(
                conn, song_id=song_id, name='intro',
                start_bar=float(INTRO_BAR),
                end_bar=float(VERSE_1_BAR),
            )
            M.create_section(
                conn, song_id=song_id, name='verse-1',
                start_bar=float(VERSE_1_BAR),
                end_bar=float(PRE_CHORUS_1_BAR),
            )
            M.create_section(
                conn, song_id=song_id, name='pre-chorus-1',
                start_bar=float(PRE_CHORUS_1_BAR),
                end_bar=float(CHORUS_1_BAR),
            )
            M.create_section(
                conn, song_id=song_id, name='chorus-1',
                start_bar=float(CHORUS_1_BAR),
                end_bar=float(VERSE_2_BAR),
            )
            M.create_section(
                conn, song_id=song_id, name='verse-2',
                start_bar=float(VERSE_2_BAR),
                end_bar=float(PRE_CHORUS_2_BAR),
            )
            M.create_section(
                conn, song_id=song_id, name='pre-chorus-2',
                start_bar=float(PRE_CHORUS_2_BAR),
                end_bar=float(BRIDGE_BAR),
            )
            M.create_section(
                conn, song_id=song_id, name='bridge',
                start_bar=float(BRIDGE_BAR),
                end_bar=float(BRIDGE_TWIST_BAR),
            )
            M.create_section(
                conn, song_id=song_id, name='bridge-twist',
                start_bar=float(BRIDGE_TWIST_BAR),
                end_bar=float(BRIDGE_RETURN_BAR),
            )
            M.create_section(
                conn, song_id=song_id, name='bridge-return',
                start_bar=float(BRIDGE_RETURN_BAR),
                end_bar=float(CHORUS_2_BAR),
            )
            M.create_section(
                conn, song_id=song_id, name='chorus-2',
                start_bar=float(CHORUS_2_BAR),
                end_bar=float(OUTRO_BAR),
            )
            M.create_section(
                conn, song_id=song_id, name='outro',
                start_bar=float(OUTRO_BAR),
                end_bar=float(END_BAR),
            )

            # Cue points at every section boundary.
            for bar, name in [(INTRO_BAR, 'intro'), (VERSE_1_BAR, 'verse-1'), (PRE_CHORUS_1_BAR, 'pre-chorus-1'), (CHORUS_1_BAR, 'chorus-1'), (VERSE_2_BAR, 'verse-2'), (PRE_CHORUS_2_BAR, 'pre-chorus-2'), (BRIDGE_BAR, 'bridge'), (BRIDGE_TWIST_BAR, 'bridge-twist'), (BRIDGE_RETURN_BAR, 'bridge-return'), (CHORUS_2_BAR, 'chorus-2'), (OUTRO_BAR, 'outro')]:
                M.add_cue_point(
                    conn, song_id=song_id,
                    position_bar=float(bar), name=name,
                )

            # bridge-twist: section-boundary meter-ratchet probe.
            # Per CHANGELOG known-limitation H1, post-bar-1 signature
            # changes refuse-and-teach. We TRY anyway and catch the error
            # so the rest of the build proceeds — that lets us verify the
            # refusal fires cleanly without aborting the test song.
            global RATCHET_REFUSED
            RATCHET_REFUSED = None
            try:
                M.add_time_signature_point(
                    conn, song_id=song_id,
                    start_bar=float(BRIDGE_TWIST_BAR),
                    numerator=5, denominator=8,
                )
                M.add_time_signature_point(
                    conn, song_id=song_id,
                    start_bar=float(BRIDGE_RETURN_BAR),
                    numerator=4, denominator=4,
                )
            except Exception as exc:
                RATCHET_REFUSED = f"{type(exc).__name__}: {exc}"

            tracks = _tracks_by_name(conn, song_id)
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
        if RATCHET_REFUSED:
            print(f"meter-ratchet refusal (expected per H1): {RATCHET_REFUSED}")
    finally:
        conn.close()


if __name__ == "__main__":
    reset = "--reset" in sys.argv
    song_id = build(reset=reset)
    report(song_id)
