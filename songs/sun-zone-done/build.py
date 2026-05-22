"""Build Sun Zone / Stuff Done — reggae × speed-metal mashup in E.

Alternating (not overlapping) sections express the tension between wanting to
relax and having too much to do. Reggae sections in E Dorian (half-time felt
at 90 BPM); metal sections in E Phrygian (felt straight at 180). Tempo
constant; the genre flip is articulation, not a tempo cut. Modal pivots on
F# <-> F-natural and C# <-> C-natural — same E tonic, modes flip.

Section bar layout (1-based, 4/4 throughout):
    intro    bars  1-8    (8 bars / 32 beats) — drifting reggae → drums in → WHACK → reggae pickup
    verse1   bars  9-16   (8 bars / 32 beats) — alternating 2-bar reggae / 2-bar metal × 2
    chorus1  bars 17-24   (8 bars / 32 beats) — faster alternation, counter-melody hook enters
    verse2   bars 25-32   (same shape, ratcheted up)
    chorus2  bars 33-40   (same, with C-melody variation)
    bridge   bars 41-48   (genre bleed — the alternation rule breaks)
    chorus3  bars 49-56   (final chorus, payoff)
    outro    bars 57-64   (reverse of intro — drifts out)

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

# Per-branch DB filename.
DB_PATH = resolve_db_path("sun-zone-done", root=Path(__file__).parent.parent)
SNAPSHOT_PATH = Path(__file__).parent / "captured_session.json"


# ---------------------------------------------------------------------------
# Pitch reference (MIDI). Live conventions: C3 = 60.
# ---------------------------------------------------------------------------
# Bass roots (low octave)
E2, F2, A2, B2, C2, D2 = 40, 41, 45, 47, 36, 38
E1 = 28

# Reggae skank voicings (E Dorian — bright)
EM9_SKANK   = [55, 59, 62, 66]   # G3 B3 D4 F#4 — Em9 upper structure (F# = Dorian color)
A13_SKANK   = [61, 64, 67, 66]   # C#4 E4 G4 F#4 — A13 (C# = Dorian color)
DMAJ7_SKANK = [54, 57, 61]       # F#3 A3 C#4 — Dmaj7 upper
BM7_SKANK   = [50, 54, 57]       # D3 F#3 A3 — Bm7 upper

# Organ voicings (wider, sustained pads — higher register, above the vocal hole)
EM9_ORGAN   = [64, 67, 71, 74, 78]  # E4 G4 B4 D5 F#5
A13_ORGAN   = [64, 69, 73, 76, 78]  # E4 A4 C#5 E5 F#5
DMAJ7_ORGAN = [62, 66, 69, 73]      # D4 F#4 A4 C#5
BM7_ORGAN   = [59, 62, 66, 69]      # B3 D4 F#4 A4

# Metal power chord voicings (E Phrygian — power chords, no third)
# Voiced low for chug character; bass plays root separately.
E5_POWER = [40, 47]   # E2 + B2
F5_POWER = [41, 48]   # F2 + C3 — bII, the Phrygian punch
D5_POWER = [38, 45]   # D2 + A2 — bvii
C5_POWER = [36, 43]   # C2 + G2 — bVI

# Section bar boundaries (1-based)
INTRO_BAR   = 1
VERSE1_BAR  = 9
CHORUS1_BAR = 17
VERSE2_BAR  = 25
CHORUS2_BAR = 33
BRIDGE_BAR  = 41
CHORUS3_BAR = 49
OUTRO_BAR   = 57
END_BAR     = 65


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _tracks_by_name(conn, song_id):
    return {row["name"]: row["id"] for row in Q.get_tracks_for_song(conn, song_id)}


def _note(pitch, start, dur, vel, *tags):
    n = {"pitch": int(pitch), "start_beats": float(start),
         "duration_beats": float(dur), "velocity": int(vel)}
    if tags:
        n["tags"] = list(tags)
    return n


# ---------------------------------------------------------------------------
# Genre pattern generators
# ---------------------------------------------------------------------------


def reggae_one_drop(bars, start_beat, *, vel_base=85, with_kick_on_1=False):
    """Reggae one-drop drums (1 song-bar = 1 reggae bar at felt half-time).

    Beat 1: silent (one-drop) OR kick (rockers variant).
    Beat 3: kick + rim/snare (the drop).
    Hi-hat: light 8ths throughout.
    """
    notes = []
    for b in range(bars):
        bs = start_beat + b * 4.0
        # The drop: kick + rim on beat 3
        notes.append(_note(36, bs + 2.0, 0.25, vel_base + 5, "kick", "drop"))
        notes.append(_note(37, bs + 2.0, 0.25, vel_base + 3, "rim", "drop"))
        if with_kick_on_1:
            notes.append(_note(36, bs + 0.0, 0.2, vel_base - 5, "kick", "downbeat"))
        # Hat 8ths, alternating accent
        for i in range(8):
            t = i * 0.5
            vel = (vel_base - 25) if (i % 2 == 0) else (vel_base - 30)
            notes.append(_note(42, bs + t, 0.18, vel, "hat", "8ths"))
    return notes


def reggae_skank(voicing, bars, start_beat, *, vel=82, accent_strong=True):
    """Skank chord stabs on off-beats (1.5, 2.5, 3.5, 4.5 — i.e., 'ands').
    Short attack and duration — characteristic reggae 'chuck'.
    """
    notes = []
    for b in range(bars):
        bs = start_beat + b * 4.0
        for off in (0.5, 1.5, 2.5, 3.5):
            v = vel + (5 if accent_strong and off in (1.5, 3.5) else 0)
            for p in voicing:
                notes.append(_note(p, bs + off, 0.22, v, "skank"))
    return notes


def reggae_bass(roots_with_bars, start_beat):
    """Reggae bass walking line.

    roots_with_bars: list of (root_midi, bars_for_this_chord).
    Authoring per chord: root on 1 held to 2.5; fifth stab on 2.5; octave on 4.
    Last bar adds a chromatic walk-up on the 'and' of 4 leading to the next chord.
    """
    notes = []
    beat = start_beat
    for ci, (root, bars) in enumerate(roots_with_bars):
        for b in range(bars):
            local = beat + b * 4.0
            # Root note 1.5 beats
            notes.append(_note(root, local, 1.5, 92, "bass", "root"))
            # Fifth stab on beat 2.5
            notes.append(_note(root + 7, local + 2.0, 0.5, 78, "bass", "fifth"))
            # Octave on beat 4
            notes.append(_note(root + 12, local + 3.0, 0.4, 75, "bass", "oct"))
            # Walk-up to next chord on the very last beat (and)
            if b == bars - 1 and ci < len(roots_with_bars) - 1:
                next_root = roots_with_bars[ci + 1][0]
                # Step-wise approach: from current root toward next
                approach = next_root - 1 if next_root > root else next_root + 1
                notes.append(_note(approach, local + 3.5, 0.4, 80, "bass", "walk"))
        beat += bars * 4.0
    return notes


def metal_gallop_drums(bars, start_beat, *, vel_base=110, with_china=False):
    """Speed-metal drums.

    Kick on every beat + 16th gallop fills on beats 3 and 4.
    Snare on 2 and 4.
    Closed hat (Hot Rod Kit's bigger "Buttery" pad) 8ths driving the tempo —
    Hot Rod Kit has no ride / china / open hat, so we use closed hats
    differentially (42 Easy = reggae bright tick; 46 Buttery = metal big-stick).
    """
    notes = []
    for b in range(bars):
        bs = start_beat + b * 4.0
        # Kick on every beat
        for beat in (0.0, 1.0, 2.0, 3.0):
            notes.append(_note(36, bs + beat, 0.15, vel_base, "kick", "drive"))
        # Double-kick gallop on the 'and-a' of 3 and 4
        notes.append(_note(36, bs + 2.5, 0.1, vel_base - 8, "kick", "gallop"))
        notes.append(_note(36, bs + 2.75, 0.1, vel_base - 8, "kick", "gallop"))
        notes.append(_note(36, bs + 3.5, 0.1, vel_base - 8, "kick", "gallop"))
        notes.append(_note(36, bs + 3.75, 0.1, vel_base - 8, "kick", "gallop"))
        # Snare on 2 and 4 (hard)
        notes.append(_note(38, bs + 1.0, 0.2, vel_base + 5, "snare", "backbeat"))
        notes.append(_note(38, bs + 3.0, 0.2, vel_base + 5, "snare", "backbeat"))
        # Driving 8ths — Hot Rod's Closed Hat Buttery (46) for "ride-like" weight;
        # when with_china=True alternate with Polo (44) for slight variation.
        for i in range(8):
            t = i * 0.5
            on_beat = (i % 2 == 0)
            pitch = 46
            if with_china and on_beat:
                pitch = 44  # alternate accent
            vel = (vel_base - 30) if on_beat else (vel_base - 35)
            notes.append(_note(pitch, bs + t, 0.15, vel, "drive-8ths"))
    return notes


def metal_chug(power_chord, bars, start_beat, *, pattern="gallop", vel_base=110):
    """Palm-mute power-chord chug.

    pattern:
      - 'gallop': 16th-note chug, accents on downbeats (8th-and-two-16ths feel)
      - 'stab':   downbeat-only quarter-note stabs (good for transitions)
      - 'whack':  single screaming chord on beat 1, sustain the whole bar
    """
    notes = []
    for b in range(bars):
        bs = start_beat + b * 4.0
        if pattern == "gallop":
            # 8th + two-16ths gallop pattern over each beat
            # Pattern within one beat: 0.0 (long), 0.5 (short), 0.75 (short)
            for beat in (0.0, 1.0, 2.0, 3.0):
                base = bs + beat
                for p in power_chord:
                    notes.append(_note(p, base + 0.0, 0.4, vel_base, "chug", "long"))
                    notes.append(_note(p, base + 0.5, 0.2, vel_base - 10, "chug", "short"))
                    notes.append(_note(p, base + 0.75, 0.2, vel_base - 10, "chug", "short"))
        elif pattern == "stab":
            for beat in (0.0, 1.0, 2.0, 3.0):
                for p in power_chord:
                    notes.append(_note(p, bs + beat, 0.45, vel_base + 5, "stab"))
        elif pattern == "whack":
            for p in power_chord:
                notes.append(_note(p, bs, 3.8, vel_base + 10, "whack"))
        else:
            raise ValueError(f"unknown pattern {pattern!r}")
    return notes


def metal_bass(power_chord_roots, start_beat, *, bars=1, vel_base=105):
    """Metal bass — palm-muted root pumping, locked to kick.

    power_chord_roots: list of (root_midi, beat_position_within_section).
    For typical use, pass a list of (root, beat_offset) pairs matching guitar stabs.
    Or use the convenience form: pass list of (root, bars_for_this_root) and a start_beat.
    Here: roots get pumped on every kick (every beat + gallop 16ths) for the chord's duration.
    """
    notes = []
    for root, bars_for_root in power_chord_roots:
        for b in range(bars_for_root):
            bs = start_beat + b * 4.0
            for beat in (0.0, 1.0, 2.0, 3.0):
                notes.append(_note(root, bs + beat, 0.18, vel_base, "bass", "pump"))
            # Gallop 16ths matching kick
            notes.append(_note(root, bs + 2.5, 0.1, vel_base - 5, "bass", "gallop"))
            notes.append(_note(root, bs + 2.75, 0.1, vel_base - 5, "bass", "gallop"))
            notes.append(_note(root, bs + 3.5, 0.1, vel_base - 5, "bass", "gallop"))
            notes.append(_note(root, bs + 3.75, 0.1, vel_base - 5, "bass", "gallop"))
        start_beat += bars_for_root * 4.0
    return notes


# ---------------------------------------------------------------------------
# SECTION BUILDERS
# ---------------------------------------------------------------------------


def _build_intro(conn, song_id, tracks):
    """Intro — 8 bars / 32 beats.

    bars 1-2 (b 0-8):   drifting organ pad (Em9), no drums, no bass
    bars 3-4 (b 8-16):  organ adds skank pattern, lead voice enters with sustained F#
    bars 5-6 (b 16-24): one-drop drums + bass + clean guitar skank (full reggae)
    bar  7  (b 24-28):  METAL WHACK — F5 power chord + double-kick burst + F♮ vocal shout
    bar  8  (b 28-32):  reggae groove resumes, settling into Verse 1
    """
    clips = {}

    # --- Drums: silent bars 1-4, reggae bars 5-6, metal whack bar 7, reggae bar 8 ---
    drum_notes = []
    drum_notes += reggae_one_drop(2, start_beat=16.0)  # bars 5-6
    # Metal whack bar 7 (beats 24-28): full bar of gallop + double-kick + crash
    drum_notes += metal_gallop_drums(1, start_beat=24.0, with_china=True)
    drum_notes.append(_note(49, 24.0, 1.0, 118, "crash", "whack"))
    # Bar 8 (beats 28-32): reggae one-drop resumes — softer, building back
    drum_notes += reggae_one_drop(1, start_beat=28.0, vel_base=78)

    cid = M.create_clip(
        conn, track_id=tracks["01 Drums"], slot=1, length_beats=32.0,
        name="Intro Drums", section_role="intro",
        generator_call={"fn": "intro composed", "kwargs": {"bars": 8}},
    )
    M.replace_clip_notes(conn, clip_id=cid, notes=drum_notes)
    clips["01 Drums"] = cid

    # --- Bass: silent bars 1-4, reggae bass bars 5-6, F♮ metal stab bar 7, reggae bass bar 8 ---
    bass_notes = []
    # Bars 5-6: walk Em9 → A13 (Em9 1 bar, A13 1 bar)
    bass_notes += reggae_bass([(E2, 1), (A2, 1)], start_beat=16.0)
    # Bar 7 WHACK: low F♮ pumping on every beat (matches metal F5 power chord)
    bass_notes += metal_bass([(F2, 1)], start_beat=24.0, vel_base=110)
    # Bar 8: walk Em9 leading into verse
    bass_notes += reggae_bass([(E2, 1)], start_beat=28.0)
    cid = M.create_clip(
        conn, track_id=tracks["02 Bass"], slot=1, length_beats=32.0,
        name="Intro Bass", section_role="intro",
    )
    M.replace_clip_notes(conn, clip_id=cid, notes=bass_notes)
    clips["02 Bass"] = cid

    # --- Rhythm Gtr: silent bars 1-2, sparse clean skank bars 3-4, full skank bars 5-6,
    #                 dirty F5 chug bar 7, clean skank bar 8 ---
    gtr_notes = []
    # Bars 3-4 (beats 8-16): sparse Em9 skank — only on beat 4.5 of each bar
    for b in range(2):
        bs = 8.0 + b * 4.0
        for p in EM9_SKANK:
            gtr_notes.append(_note(p, bs + 3.5, 0.22, 75, "skank", "sparse"))
    # Bars 5-6 (beats 16-24): full reggae skank Em9, A13
    gtr_notes += reggae_skank(EM9_SKANK, 1, start_beat=16.0)
    gtr_notes += reggae_skank(A13_SKANK, 1, start_beat=20.0)
    # Bar 7 (beats 24-28): METAL CHUG on F5 (the Phrygian punch)
    gtr_notes += metal_chug(F5_POWER, 1, start_beat=24.0, pattern="gallop")
    # Bar 8 (beats 28-32): clean Em9 skank resuming
    gtr_notes += reggae_skank(EM9_SKANK, 1, start_beat=28.0)

    cid = M.create_clip(
        conn, track_id=tracks["03 Rhythm Gtr"], slot=1, length_beats=32.0,
        name="Intro Rhythm Gtr", section_role="intro",
    )
    M.replace_clip_notes(conn, clip_id=cid, notes=gtr_notes)
    clips["03 Rhythm Gtr"] = cid

    # --- Organ: sustained Em9 pad bars 1-2, skank-bubble bars 3-6, silent bar 7, skank bar 8 ---
    organ_notes = []
    # Bars 1-2 (beats 0-8): sustained Em9 voicing (warm pad, low velocity)
    for p in EM9_ORGAN:
        organ_notes.append(_note(p, 0.0, 8.0, 55, "pad", "drift"))
    # Bars 3-4 (beats 8-16): organ bubble — Em9 on offbeats but high register
    organ_notes += reggae_skank(EM9_ORGAN[:3], 2, start_beat=8.0, vel=58, accent_strong=False)
    # Bars 5-6 (beats 16-24): full skank Em9, A13
    organ_notes += reggae_skank(EM9_ORGAN[:4], 1, start_beat=16.0, vel=68)
    organ_notes += reggae_skank(A13_ORGAN[:4], 1, start_beat=20.0, vel=68)
    # Bar 7: SILENT (organ drops out for metal — characteristic genre absence)
    # Bar 8 (beats 28-32): organ returns softly with Em9
    organ_notes += reggae_skank(EM9_ORGAN[:3], 1, start_beat=28.0, vel=60)
    cid = M.create_clip(
        conn, track_id=tracks["04 Organ"], slot=1, length_beats=32.0,
        name="Intro Organ", section_role="intro",
    )
    M.replace_clip_notes(conn, clip_id=cid, notes=organ_notes)
    clips["04 Organ"] = cid

    # --- Lead Voice: silent bars 1-4, sustained F#4 ("vibes flowing") bars 5-6,
    #                 sharp F♮4 shout bar 7, silent bar 8 ---
    lead_notes = []
    # Bars 5-6: sustained F#4 (the Dorian 9th of Em — "rasta vibes flowing in the —")
    # Phrasing: enter on beat 1 of bar 5, hold through bar 6's beat 3, taper out
    lead_notes.append(_note(66, 16.0, 6.0, 78, "lead", "sustain", "vibes"))
    # Bar 7 beat 1: F♮4 SHOUT ("NO TIME FOR THAT") — short, hard, with octave-up emphasis
    lead_notes.append(_note(65, 24.0, 0.5, 115, "lead", "shout", "whack"))
    lead_notes.append(_note(77, 24.0, 0.5, 110, "lead", "shout", "octave"))  # F5 doubled for impact
    # Optional pickup phrase later in bar 7 — sustained F♮ leading into the resolution
    lead_notes.append(_note(65, 25.0, 2.0, 95, "lead", "metal"))
    # Bar 8: silent (let the rhythm section resolve back into reggae)
    cid = M.create_clip(
        conn, track_id=tracks["05 Lead Voice"], slot=1, length_beats=32.0,
        name="Intro Lead Voice", section_role="intro",
    )
    M.replace_clip_notes(conn, clip_id=cid, notes=lead_notes)
    clips["05 Lead Voice"] = cid

    # Counter-melody and Vocal Bus: silent in intro (intentional)
    return clips


def _build_verse(conn, song_id, tracks, *, slot, name_suffix, intensity=1.0):
    """Verse — 8 bars / 32 beats. Two 4-bar cycles of [2 bars reggae + 2 bars metal].

    Bars 1-2 reggae (Em9), Bars 3-4 metal (E5/F5), Bars 5-6 reggae (Em9 → A13), Bars 7-8 metal (E5/D5/C5/F5).
    intensity scales velocities for Verse 2 (more aggressive).
    """
    clips = {}
    vel_scale = lambda v: int(v * intensity)

    # === Drums ===
    drum_notes = []
    # Bars 1-2 (beats 0-8): reggae one-drop
    drum_notes += reggae_one_drop(2, start_beat=0.0, vel_base=vel_scale(85))
    # Bars 3-4 (beats 8-16): metal gallop
    drum_notes += metal_gallop_drums(2, start_beat=8.0, vel_base=vel_scale(108))
    # Bars 5-6 (beats 16-24): reggae one-drop
    drum_notes += reggae_one_drop(2, start_beat=16.0, vel_base=vel_scale(85))
    # Bars 7-8 (beats 24-32): metal gallop with china for variety
    drum_notes += metal_gallop_drums(2, start_beat=24.0, vel_base=vel_scale(110), with_china=True)
    # End-of-section crash on the very last 'and' to push into chorus
    drum_notes.append(_note(49, 31.5, 0.5, vel_scale(115), "crash", "push"))

    cid = M.create_clip(
        conn, track_id=tracks["01 Drums"], slot=slot, length_beats=32.0,
        name=f"Verse Drums {name_suffix}", section_role="verse",
    )
    M.replace_clip_notes(conn, clip_id=cid, notes=drum_notes)
    clips["01 Drums"] = cid

    # === Bass ===
    bass_notes = []
    # Bars 1-2 reggae Em9 → walking
    bass_notes += reggae_bass([(E2, 2)], start_beat=0.0)
    # Bars 3-4 metal: pump E2 for 1 bar, F2 for 1 bar (the bII move)
    bass_notes += metal_bass([(E2, 1), (F2, 1)], start_beat=8.0, vel_base=vel_scale(108))
    # Bars 5-6 reggae walking: Em9 1 bar, A13 1 bar
    bass_notes += reggae_bass([(E2, 1), (A2, 1)], start_beat=16.0)
    # Bars 7-8 metal: E2, D2, C2, F2 (the full Phrygian descent then resolution)
    bass_notes += metal_bass([(E2, 1)], start_beat=24.0, vel_base=vel_scale(108))
    bass_notes += metal_bass([(D2, 1)], start_beat=26.0 if False else 26.0, vel_base=vel_scale(108))
    # Actually let me redo: each E_POWER is 1 bar. 4 chords across 2 bars = each chord = 0.5 bars
    # Rewrite bars 7-8 as 4 half-bar metal stabs
    cid = M.create_clip(
        conn, track_id=tracks["02 Bass"], slot=slot, length_beats=32.0,
        name=f"Verse Bass {name_suffix}", section_role="verse",
    )
    M.replace_clip_notes(conn, clip_id=cid, notes=bass_notes)
    clips["02 Bass"] = cid

    # === Rhythm Gtr ===
    gtr_notes = []
    # Bars 1-2 reggae skank Em9
    gtr_notes += reggae_skank(EM9_SKANK, 2, start_beat=0.0, vel=vel_scale(82))
    # Bars 3-4 metal gallop chug: E5 1 bar, F5 1 bar (i-bII alternation)
    gtr_notes += metal_chug(E5_POWER, 1, start_beat=8.0, pattern="gallop", vel_base=vel_scale(108))
    gtr_notes += metal_chug(F5_POWER, 1, start_beat=12.0, pattern="gallop", vel_base=vel_scale(110))
    # Bars 5-6 reggae skank Em9, A13
    gtr_notes += reggae_skank(EM9_SKANK, 1, start_beat=16.0, vel=vel_scale(84))
    gtr_notes += reggae_skank(A13_SKANK, 1, start_beat=20.0, vel=vel_scale(84))
    # Bars 7-8 metal: E5, D5, C5, F5 (Phrygian descent, two beats each = 8 beats / 4 chords)
    gtr_notes += metal_chug(E5_POWER, 0, start_beat=24.0)  # 0 bars = no-op skip
    # Half-bar metal stabs (2 beats per chord) for bars 7-8
    half_bar_chord_seq = [E5_POWER, D5_POWER, C5_POWER, F5_POWER]
    for i, chord in enumerate(half_bar_chord_seq):
        beat_offset = 24.0 + i * 2.0
        # 2 beats of gallop chug per chord
        for sixteenth in range(8):
            t = sixteenth * 0.25
            v = vel_scale(112) if sixteenth % 4 == 0 else vel_scale(98)
            for p in chord:
                gtr_notes.append(_note(p, beat_offset + t, 0.2, v, "chug", "descent"))

    cid = M.create_clip(
        conn, track_id=tracks["03 Rhythm Gtr"], slot=slot, length_beats=32.0,
        name=f"Verse Rhythm Gtr {name_suffix}", section_role="verse",
    )
    M.replace_clip_notes(conn, clip_id=cid, notes=gtr_notes)
    clips["03 Rhythm Gtr"] = cid

    # === Organ ===
    # Reggae sections only — metal sections SILENT.
    organ_notes = []
    # Bars 1-2 Em9
    organ_notes += reggae_skank(EM9_ORGAN[:4], 2, start_beat=0.0, vel=vel_scale(72))
    # Bars 3-4 SILENT (metal)
    # Bars 5-6 Em9 / A13
    organ_notes += reggae_skank(EM9_ORGAN[:4], 1, start_beat=16.0, vel=vel_scale(72))
    organ_notes += reggae_skank(A13_ORGAN[:4], 1, start_beat=20.0, vel=vel_scale(74))
    # Bars 7-8 SILENT
    cid = M.create_clip(
        conn, track_id=tracks["04 Organ"], slot=slot, length_beats=32.0,
        name=f"Verse Organ {name_suffix}", section_role="verse",
    )
    M.replace_clip_notes(conn, clip_id=cid, notes=organ_notes)
    clips["04 Organ"] = cid

    # === Lead Voice (placeholder vocal) ===
    # Reggae phrases: lyrical melodic line in E3-E4 (Dorian — uses F# = 66)
    # Metal phrases: rhythmic shouts in E4-G4 (Phrygian — uses F♮ = 65)
    lead_notes = []
    # Bars 1-2 reggae melody ("chillin in the sun zone")
    # E4(64) D4(62) F#4(66) E4(64)  — Dorian melody, syncopated
    lead_notes += [
        _note(64, 0.5, 0.5, 72, "lead", "reggae", "chillin"),
        _note(62, 1.0, 0.5, 70, "lead", "reggae", "in"),
        _note(64, 1.5, 1.0, 78, "lead", "reggae", "the"),
        _note(66, 2.5, 1.5, 82, "lead", "reggae", "sun"),     # F#4 — the Dorian color
        _note(64, 5.0, 0.5, 72, "lead", "reggae", "zone"),
        _note(62, 5.5, 0.5, 70, "lead", "reggae"),
        _note(66, 6.0, 1.5, 80, "lead", "reggae"),
    ]
    # Bars 3-4 metal shouts ("NO TIME FOR THAT")
    # Hits on every beat: E4(64), F♮4(65), E4(64), F♮4(65)... rhythm locked to gallop
    metal_word_beats = [8.0, 9.0, 10.0, 11.0, 12.0, 13.0, 14.0, 15.0]
    metal_word_pitches = [65, 64, 65, 64, 65, 64, 67, 65]  # F-E-F-E-F-E-G-F (Phrygian)
    for beat, pitch in zip(metal_word_beats, metal_word_pitches):
        lead_notes.append(_note(pitch, beat, 0.5, vel_scale(108), "lead", "metal", "shout"))
    # Bars 5-6 reggae melody ("rasta vibes flowing in the —")
    lead_notes += [
        _note(64, 16.5, 0.5, 72, "lead", "reggae"),
        _note(62, 17.0, 0.5, 70, "lead", "reggae"),
        _note(60, 17.5, 0.5, 72, "lead", "reggae"),
        _note(62, 18.0, 1.0, 75, "lead", "reggae"),
        _note(66, 19.0, 0.5, 78, "lead", "reggae"),
        _note(64, 19.5, 0.5, 75, "lead", "reggae"),
        _note(61, 20.5, 1.0, 78, "lead", "reggae", "Cs"),    # C#4 — the A13 color tone
        _note(64, 21.5, 0.5, 75, "lead", "reggae"),
        _note(66, 22.0, 2.0, 80, "lead", "reggae", "hold"),  # held F#4 — leads into the WHACK
    ]
    # Bars 7-8 metal shouts ("GOTTA GET STUFF DONE")
    metal2_word_beats = [24.0, 24.75, 25.5, 26.0, 26.75, 27.5, 28.0, 29.0, 30.0, 31.0]
    metal2_word_pitches = [65, 65, 64, 65, 65, 64, 67, 65, 64, 65]
    for beat, pitch in zip(metal2_word_beats, metal2_word_pitches):
        lead_notes.append(_note(pitch, beat, 0.4, vel_scale(110), "lead", "metal", "shout"))

    cid = M.create_clip(
        conn, track_id=tracks["05 Lead Voice"], slot=slot, length_beats=32.0,
        name=f"Verse Lead {name_suffix}", section_role="verse",
    )
    M.replace_clip_notes(conn, clip_id=cid, notes=lead_notes)
    clips["05 Lead Voice"] = cid

    # Counter-melody silent in verse; vocal bus empty
    return clips


def _build_chorus(conn, song_id, tracks, *, slot, name_suffix, variation=1):
    """Chorus — 8 bars / 32 beats. Faster alternation [2 bars reggae / 2 bars metal] x 2.

    Counter-melody lead enters with the hook line above the placeholder vocal.
    variation: 1 = standard, 2 = with C-melody twist, 3 = final payoff (more dense).
    """
    clips = {}

    # === Drums ===
    drum_notes = []
    drum_notes += reggae_one_drop(2, start_beat=0.0, vel_base=88, with_kick_on_1=True)  # rockers — more energy than verse one-drop
    drum_notes += metal_gallop_drums(2, start_beat=8.0, vel_base=110, with_china=True)
    drum_notes += reggae_one_drop(2, start_beat=16.0, vel_base=90, with_kick_on_1=True)
    drum_notes += metal_gallop_drums(2, start_beat=24.0, vel_base=112, with_china=True)
    # Crashes at every genre boundary
    for beat in (8.0, 16.0, 24.0):
        drum_notes.append(_note(49, beat, 1.0, 110, "crash", "boundary"))
    if variation == 3:
        # Final chorus: bigger crash arrival on beat 1 + outro-push crash
        # (Hot Rod Kit has no ride bell; use crash + tom flam instead)
        drum_notes.append(_note(49, 0.0, 1.5, 100, "crash", "payoff"))
        drum_notes.append(_note(47, 0.25, 0.2, 95, "tom-hi", "payoff-flam"))
        drum_notes.append(_note(49, 31.0, 1.0, 120, "crash", "outro-push"))

    cid = M.create_clip(
        conn, track_id=tracks["01 Drums"], slot=slot, length_beats=32.0,
        name=f"Chorus Drums {name_suffix}", section_role="chorus",
    )
    M.replace_clip_notes(conn, clip_id=cid, notes=drum_notes)
    clips["01 Drums"] = cid

    # === Bass ===
    bass_notes = []
    bass_notes += reggae_bass([(E2, 1), (A2, 1)], start_beat=0.0)
    bass_notes += metal_bass([(E2, 1), (F2, 1)], start_beat=8.0)
    bass_notes += reggae_bass([(E2, 1), (D2 + 12, 1)], start_beat=16.0)  # Em → Dmaj (Dorian VII)
    # Metal: E5 - C5 - D5 - F5 over bars 7-8 (the descent into the chorus repeat)
    for i, root in enumerate([E2, C2, D2, F2]):
        bass_notes += metal_bass([(root, 1)], start_beat=24.0 + i * 0.5 * 4.0)
    cid = M.create_clip(
        conn, track_id=tracks["02 Bass"], slot=slot, length_beats=32.0,
        name=f"Chorus Bass {name_suffix}", section_role="chorus",
    )
    # Trim bass to clip length (the half-bar pattern produced overflow)
    bass_notes = [n for n in bass_notes if n["start_beats"] + n["duration_beats"] <= 32.0]
    M.replace_clip_notes(conn, clip_id=cid, notes=bass_notes)
    clips["02 Bass"] = cid

    # === Rhythm Gtr ===
    gtr_notes = []
    # Bars 1-2 reggae Em9 → A13
    gtr_notes += reggae_skank(EM9_SKANK, 1, start_beat=0.0, vel=85)
    gtr_notes += reggae_skank(A13_SKANK, 1, start_beat=4.0, vel=85)
    # Bars 3-4 metal E5 → F5
    gtr_notes += metal_chug(E5_POWER, 1, start_beat=8.0, pattern="gallop")
    gtr_notes += metal_chug(F5_POWER, 1, start_beat=12.0, pattern="gallop")
    # Bars 5-6 reggae Em9 → Dmaj7
    gtr_notes += reggae_skank(EM9_SKANK, 1, start_beat=16.0, vel=87)
    gtr_notes += reggae_skank(DMAJ7_SKANK, 1, start_beat=20.0, vel=87)
    # Bars 7-8 metal descent E5 - C5 - D5 - F5 (half-bar each)
    half_bar_chord_seq = [E5_POWER, C5_POWER, D5_POWER, F5_POWER]
    for i, chord in enumerate(half_bar_chord_seq):
        beat_offset = 24.0 + i * 2.0
        for sixteenth in range(8):
            t = sixteenth * 0.25
            v = 112 if sixteenth % 4 == 0 else 98
            for p in chord:
                gtr_notes.append(_note(p, beat_offset + t, 0.2, v, "chug"))

    cid = M.create_clip(
        conn, track_id=tracks["03 Rhythm Gtr"], slot=slot, length_beats=32.0,
        name=f"Chorus Rhythm Gtr {name_suffix}", section_role="chorus",
    )
    M.replace_clip_notes(conn, clip_id=cid, notes=gtr_notes)
    clips["03 Rhythm Gtr"] = cid

    # === Organ (reggae only) ===
    organ_notes = []
    organ_notes += reggae_skank(EM9_ORGAN[:4], 1, start_beat=0.0, vel=72)
    organ_notes += reggae_skank(A13_ORGAN[:4], 1, start_beat=4.0, vel=72)
    # Bars 3-4 silent
    organ_notes += reggae_skank(EM9_ORGAN[:4], 1, start_beat=16.0, vel=74)
    organ_notes += reggae_skank(DMAJ7_ORGAN[:4], 1, start_beat=20.0, vel=74)
    # Bars 7-8 silent
    cid = M.create_clip(
        conn, track_id=tracks["04 Organ"], slot=slot, length_beats=32.0,
        name=f"Chorus Organ {name_suffix}", section_role="chorus",
    )
    M.replace_clip_notes(conn, clip_id=cid, notes=organ_notes)
    clips["04 Organ"] = cid

    # === Lead Voice (placeholder vocals) ===
    # Chorus has a meta-commentary lyric — alternating sides commenting on each other
    lead_notes = []
    # Bars 1-2 reggae: "Can't relax 'cause I'm behind"
    lead_notes += [
        _note(64, 0.5, 0.4, 80, "lead", "reggae"),  # Can't
        _note(64, 1.0, 0.4, 78, "lead", "reggae"),  # re-
        _note(66, 1.5, 0.4, 80, "lead", "reggae"),  # lax
        _note(64, 2.5, 0.5, 78, "lead", "reggae"),  # 'cause
        _note(62, 3.0, 0.5, 76, "lead", "reggae"),  # I'm
        _note(60, 3.5, 0.5, 78, "lead", "reggae"),  # be-
        _note(62, 4.5, 2.0, 82, "lead", "reggae"),  # hind (held into bar 2)
    ]
    # Bars 3-4 metal: "BE-HIND BE-CAUSE I TRIED" — shouted
    metal_chorus_beats = [8.0, 9.0, 10.0, 11.0, 12.0, 13.0, 14.0, 15.0]
    metal_chorus_pitches = [65, 65, 64, 67, 65, 65, 64, 67]  # F-F-E-G-F-F-E-G
    for beat, pitch in zip(metal_chorus_beats, metal_chorus_pitches):
        lead_notes.append(_note(pitch, beat, 0.45, 110, "lead", "metal", "shout"))
    # Bars 5-6 reggae: "to un-wind"
    lead_notes += [
        _note(64, 16.5, 0.5, 80, "lead", "reggae"),
        _note(64, 17.0, 0.5, 78, "lead", "reggae"),
        _note(66, 17.5, 1.0, 82, "lead", "reggae"),
        _note(62, 19.0, 0.5, 78, "lead", "reggae"),
        _note(64, 19.5, 1.5, 80, "lead", "reggae"),
        _note(66, 21.0, 0.5, 82, "lead", "reggae"),
        _note(67, 21.5, 2.0, 85, "lead", "reggae", "G"),  # G4 — the climax tone
    ]
    # Bars 7-8 metal: "AL-WAYS DO-ING NEV-ER DONE"
    metal_chorus2_beats = [24.0, 24.5, 25.0, 26.0, 26.5, 27.0, 28.0, 28.5, 29.0, 30.0, 30.5, 31.0]
    metal_chorus2_pitches = [65, 67, 65, 64, 65, 64, 65, 65, 64, 67, 65, 65]
    for beat, pitch in zip(metal_chorus2_beats, metal_chorus2_pitches):
        lead_notes.append(_note(pitch, beat, 0.4, 112, "lead", "metal", "shout"))

    cid = M.create_clip(
        conn, track_id=tracks["05 Lead Voice"], slot=slot, length_beats=32.0,
        name=f"Chorus Lead {name_suffix}", section_role="chorus",
    )
    M.replace_clip_notes(conn, clip_id=cid, notes=lead_notes)
    clips["05 Lead Voice"] = cid

    # === Counter-Melody Lead ===
    # Hook above the vocal register (B4-E5). Used in choruses only (and bridge).
    # In reggae bars: lyrical 8th-note line E5-D5-B4-G4 type figures
    # In metal bars: rhythmic stabs locked to the shout cadence
    cm_notes = []
    # Bars 1-2 (reggae): lyrical melody above the vocal hook
    # E5(76) D5(74) B4(71) E5(76)
    cm_notes += [
        _note(76, 1.0, 1.0, 75, "cmelody", "reggae"),  # E5
        _note(78, 2.0, 0.5, 72, "cmelody", "reggae"),  # F#5 (Dorian color)
        _note(76, 2.5, 0.5, 70, "cmelody", "reggae"),
        _note(74, 3.5, 0.5, 72, "cmelody", "reggae"),  # D5
        _note(71, 5.0, 1.0, 75, "cmelody", "reggae"),  # B4
        _note(74, 6.0, 0.5, 72, "cmelody", "reggae"),
        _note(76, 6.5, 1.5, 78, "cmelody", "reggae"),
    ]
    # Bars 3-4 (metal): rhythmic stabs on F5 (the bII anchor)
    for beat in [8.0, 9.0, 10.0, 11.0, 12.5, 13.0, 14.0, 15.0]:
        cm_notes.append(_note(77, beat, 0.4, 90, "cmelody", "metal", "stab"))  # F5
    # Bars 5-6 (reggae): melody developing
    cm_notes += [
        _note(76, 17.0, 0.5, 75, "cmelody", "reggae"),
        _note(78, 17.5, 0.5, 72, "cmelody", "reggae"),
        _note(81, 18.0, 1.0, 80, "cmelody", "reggae", "high"),  # A5 — climbs higher
        _note(78, 19.5, 0.5, 75, "cmelody", "reggae"),
        _note(76, 20.0, 1.0, 73, "cmelody", "reggae"),
        _note(74, 21.5, 0.5, 72, "cmelody", "reggae"),
        _note(78, 22.0, 1.5, 78, "cmelody", "reggae"),
    ]
    # Bars 7-8 (metal): descending stabs matching the chord descent E-C-D-F
    metal_cm_beats_pitches = [(24.0, 76), (25.0, 76), (26.0, 72), (27.0, 72),  # E5, E5, C5, C5
                              (28.0, 74), (29.0, 74), (30.0, 77), (31.0, 77)]  # D5, D5, F5, F5
    for beat, pitch in metal_cm_beats_pitches:
        cm_notes.append(_note(pitch, beat, 0.5, 95, "cmelody", "metal", "descent"))

    cid = M.create_clip(
        conn, track_id=tracks["06 Counter-Melody"], slot=slot, length_beats=32.0,
        name=f"Chorus C-Melody {name_suffix}", section_role="chorus",
    )
    M.replace_clip_notes(conn, clip_id=cid, notes=cm_notes)
    clips["06 Counter-Melody"] = cid

    return clips


def _build_bridge(conn, song_id, tracks):
    """Bridge — 8 bars / 32 beats. The alternation rule breaks: GENRE BLEED.

    Bars 1-4 (b 0-16):  metal vocal cadence + power-chord stabs OVER reggae bass + organ
                        — "the answer the song's been asking"
    Bars 5-6 (b 16-24): everything stops except sustained organ pad + sparse lead vocal —
                        the realization moment
    Bars 7-8 (b 24-32): builds back: reggae groove + metal chug *simultaneously* —
                        the loop made musical
    """
    clips = {}

    # === Drums: reggae beat under metal stabs bars 1-4, sparse bars 5-6, full bleed 7-8 ===
    drum_notes = []
    # Bars 1-4: reggae one-drop drives, but with metal-velocity closed-hat-buttery
    # 8ths (genre confused). Hot Rod Kit has no ride; use 46 Closed Hat Buttery
    # for the big-stick ride substitute, 42 for ghost ticks.
    for b in range(4):
        bs = b * 4.0
        # One-drop rim + kick on beat 3
        drum_notes.append(_note(36, bs + 2.0, 0.25, 92, "kick", "drop"))
        drum_notes.append(_note(37, bs + 2.0, 0.25, 88, "rim", "drop"))
        # Big-stick 8ths (METAL-velocity over reggae kick pattern)
        for i in range(8):
            t = i * 0.5
            vel = 85 if (i % 2 == 0) else 70
            drum_notes.append(_note(46, bs + t, 0.15, vel, "drive-8ths", "bleed"))
        # Hat ghosts on the offbeats too
        for off in (0.5, 1.5, 2.5, 3.5):
            drum_notes.append(_note(42, bs + off, 0.12, 55, "hat", "ghost"))
    # Bars 5-6 (b 16-24): SPARSE — only a single rim on beat 3 of bar 5 and an open hat on bar 6 beat 1
    drum_notes.append(_note(37, 18.0, 0.4, 70, "rim", "sparse", "realization"))
    drum_notes.append(_note(46, 20.0, 1.5, 65, "open-hat", "sparse"))
    # Bars 7-8: BOTH genres fully — reggae one-drop pattern + metal kick gallop layered
    drum_notes += reggae_one_drop(2, start_beat=24.0, vel_base=88)
    # Add metal-style kick gallop on top
    for b in range(2):
        bs = 24.0 + b * 4.0
        for beat in (0.0, 1.0):  # gallop on beats 1 and 2 only (not all 4 to avoid stepping on one-drop kick at 3)
            drum_notes.append(_note(36, bs + beat, 0.12, 100, "kick", "bleed-gallop"))
            drum_notes.append(_note(36, bs + beat + 0.5, 0.08, 90, "kick", "bleed-gallop"))
        # Crash on beat 1 of bar 8 to climax
    drum_notes.append(_note(49, 28.0, 1.5, 115, "crash", "bridge-climax"))

    cid = M.create_clip(
        conn, track_id=tracks["01 Drums"], slot=6, length_beats=32.0,
        name="Bridge Drums", section_role="bridge",
    )
    M.replace_clip_notes(conn, clip_id=cid, notes=drum_notes)
    clips["01 Drums"] = cid

    # === Bass: reggae walking under metal stabs bars 1-4, drop bars 5-6, full pump bars 7-8 ===
    bass_notes = []
    # Bars 1-4: reggae bass through chord changes Em9 → Cmaj7 (the C natural appearing — bridge harmony pivot)
    # Use the Phrygian bVI (C natural) under reggae bass articulation — modal bleed in harmony itself
    bass_notes += reggae_bass([(E2, 2), (C2 + 12, 2)], start_beat=0.0)
    # Bars 5-6: silent (the realization moment)
    # Bars 7-8: full metal pump on E + F
    bass_notes += metal_bass([(E2, 1), (F2, 1)], start_beat=24.0, vel_base=110)
    cid = M.create_clip(
        conn, track_id=tracks["02 Bass"], slot=6, length_beats=32.0,
        name="Bridge Bass", section_role="bridge",
    )
    M.replace_clip_notes(conn, clip_id=cid, notes=bass_notes)
    clips["02 Bass"] = cid

    # === Rhythm Gtr: METAL POWER-CHORD STABS over reggae beat bars 1-4,
    #                 silent 5-6, both bars 7-8 ===
    gtr_notes = []
    # Bars 1-4: power chord stab on beat 1 of each bar — answering the reggae bass with metal interruption
    chord_seq_bridge = [E5_POWER, C5_POWER, F5_POWER, E5_POWER]
    for b, chord in enumerate(chord_seq_bridge):
        bs = b * 4.0
        for p in chord:
            gtr_notes.append(_note(p, bs, 1.5, 105, "stab", "bleed"))
        # Light skank-style chuck on the 'and' of 2 — the reggae beat trying to assert itself
        for p in [55, 59, 62]:  # Em skank voicing
            gtr_notes.append(_note(p, bs + 1.5, 0.2, 72, "skank", "bleed"))
    # Bars 5-6: silent
    # Bars 7-8: full metal gallop chug (the metal side wins this bar) — E5 → F5
    gtr_notes += metal_chug(E5_POWER, 1, start_beat=24.0, pattern="gallop", vel_base=112)
    gtr_notes += metal_chug(F5_POWER, 1, start_beat=28.0, pattern="gallop", vel_base=115)
    cid = M.create_clip(
        conn, track_id=tracks["03 Rhythm Gtr"], slot=6, length_beats=32.0,
        name="Bridge Rhythm Gtr", section_role="bridge",
    )
    M.replace_clip_notes(conn, clip_id=cid, notes=gtr_notes)
    clips["03 Rhythm Gtr"] = cid

    # === Organ: sustained pad through bars 1-6 (defies the "drops out in metal" rule),
    #            silent bars 7-8 ===
    organ_notes = []
    # Bars 1-2 Em9 sustained
    for p in EM9_ORGAN:
        organ_notes.append(_note(p, 0.0, 8.0, 60, "pad", "bleed"))
    # Bars 3-4 Cmaj7 sustained (modal pivot — C natural sustains over the metal stabs)
    cmaj7_organ = [60, 64, 67, 71]  # C4 E4 G4 B4
    for p in cmaj7_organ:
        organ_notes.append(_note(p, 8.0, 8.0, 60, "pad", "bleed", "modal-pivot"))
    # Bars 5-6 sparse — just a single sustained Em chord, very soft (the realization)
    for p in [52, 55, 59]:  # E3 G3 B3
        organ_notes.append(_note(p, 16.0, 7.5, 45, "pad", "realization"))
    # Bars 7-8 silent (metal owns this)
    cid = M.create_clip(
        conn, track_id=tracks["04 Organ"], slot=6, length_beats=32.0,
        name="Bridge Organ", section_role="bridge",
    )
    M.replace_clip_notes(conn, clip_id=cid, notes=organ_notes)
    clips["04 Organ"] = cid

    # === Lead Voice: the realization lyric ===
    # "I have a lot to do / because I was lazy / I want to be lazy / because I'm tired"
    lead_notes = []
    # Bars 1-2 reggae phrasing: "I have a lot to do"
    lead_notes += [
        _note(64, 0.5, 0.5, 75, "lead", "bridge"),    # I
        _note(64, 1.0, 0.5, 73, "lead", "bridge"),    # have
        _note(62, 1.5, 0.5, 72, "lead", "bridge"),    # a
        _note(60, 2.5, 0.5, 75, "lead", "bridge"),    # lot
        _note(62, 3.0, 0.5, 73, "lead", "bridge"),    # to
        _note(64, 4.0, 1.5, 80, "lead", "bridge"),    # do
        _note(66, 5.5, 0.5, 78, "lead", "bridge"),
        _note(64, 6.0, 2.0, 80, "lead", "bridge"),
    ]
    # Bars 3-4 metal: "BE-CAUSE I WAS LA-ZY" (shouted, on the C natural pivot)
    metal_bridge_words = [(8.0, 65), (8.5, 65), (9.0, 64), (10.0, 65), (10.5, 64), (11.0, 60),  # be-cause I was la-zy (drops to C4 = the pivot)
                          (12.0, 65), (13.0, 64), (14.0, 65), (15.0, 64)]
    for beat, pitch in metal_bridge_words:
        lead_notes.append(_note(pitch, beat, 0.45, 108, "lead", "metal", "bridge"))
    # Bars 5-6: SUSTAINED HELD NOTE — "wait" / the realization
    lead_notes.append(_note(64, 16.0, 3.0, 70, "lead", "realization", "hold"))  # E4 held
    lead_notes.append(_note(66, 19.0, 1.5, 75, "lead", "realization", "hold"))  # F#4 sustained
    lead_notes.append(_note(64, 20.5, 3.0, 73, "lead", "realization", "hold"))
    # Bars 7-8: full metal scream — the loop made explicit
    metal_climax_beats = [24.0, 24.5, 25.0, 26.0, 26.5, 27.5, 28.0, 28.5, 29.0, 30.0, 30.5, 31.0]
    metal_climax_pitches = [65, 65, 67, 65, 67, 64, 65, 65, 67, 65, 67, 65]
    for beat, pitch in zip(metal_climax_beats, metal_climax_pitches):
        lead_notes.append(_note(pitch, beat, 0.4, 115, "lead", "metal", "climax"))

    cid = M.create_clip(
        conn, track_id=tracks["05 Lead Voice"], slot=6, length_beats=32.0,
        name="Bridge Lead", section_role="bridge",
    )
    M.replace_clip_notes(conn, clip_id=cid, notes=lead_notes)
    clips["05 Lead Voice"] = cid

    # === Counter-Melody: sparse high commentary ===
    cm_notes = []
    # Bars 1-4: sparse high-register answer phrases
    cm_notes.append(_note(76, 2.0, 1.0, 70, "cmelody", "bridge"))  # E5 answer
    cm_notes.append(_note(78, 6.0, 1.0, 72, "cmelody", "bridge"))  # F#5
    cm_notes.append(_note(72, 10.0, 1.0, 75, "cmelody", "bridge", "C-natural-pivot"))  # C5 — the modal shift announced
    cm_notes.append(_note(77, 14.0, 1.0, 78, "cmelody", "bridge", "F-natural"))  # F5
    # Bars 5-6: held high note as the realization sustains
    cm_notes.append(_note(83, 16.0, 8.0, 65, "cmelody", "realization", "hold"))  # B5 — high held tone
    # Bars 7-8: rapid descending climax
    for i, p in enumerate([83, 81, 79, 77, 76, 74, 72, 71]):
        cm_notes.append(_note(p, 24.0 + i * 1.0, 0.5, 90 + i * 2, "cmelody", "descent"))

    cid = M.create_clip(
        conn, track_id=tracks["06 Counter-Melody"], slot=6, length_beats=32.0,
        name="Bridge C-Melody", section_role="bridge",
    )
    M.replace_clip_notes(conn, clip_id=cid, notes=cm_notes)
    clips["06 Counter-Melody"] = cid

    return clips


def _build_outro(conn, song_id, tracks):
    """Outro — 8 bars / 32 beats. Reverse of intro.

    bars 1-2 (b 0-8):   metal fading — chugs softer, less frequent
    bar  3  (b 8-12):   metal whack one last time (mirroring intro)
    bars 4-5 (b 12-20): reggae groove takes over
    bars 6-7 (b 20-28): reggae thins out — just organ + sparse skank
    bar  8  (b 28-32):  sustained Em9 organ pad, unresolved F# hangs in the air
    """
    clips = {}

    # === Drums ===
    drum_notes = []
    # Bars 1-2: fading metal gallop
    drum_notes += metal_gallop_drums(2, start_beat=0.0, vel_base=98, with_china=True)
    # Bar 3: one final metal whack (mirror intro bar 7)
    drum_notes += metal_gallop_drums(1, start_beat=8.0, vel_base=108)
    drum_notes.append(_note(49, 8.0, 1.5, 115, "crash", "final-whack"))
    # Bars 4-5: reggae one-drop emerges
    drum_notes += reggae_one_drop(2, start_beat=12.0, vel_base=82)
    # Bars 6-7: sparse reggae — only rim on beat 3 (no kick), no hat
    drum_notes.append(_note(37, 22.0, 0.4, 70, "rim", "outro-sparse"))
    drum_notes.append(_note(37, 26.0, 0.4, 65, "rim", "outro-sparse"))
    # Bar 8: silent (let the organ hang)
    cid = M.create_clip(
        conn, track_id=tracks["01 Drums"], slot=8, length_beats=32.0,
        name="Outro Drums", section_role="outro",
    )
    M.replace_clip_notes(conn, clip_id=cid, notes=drum_notes)
    clips["01 Drums"] = cid

    # === Bass ===
    bass_notes = []
    bass_notes += metal_bass([(E2, 2)], start_beat=0.0, vel_base=98)
    bass_notes += metal_bass([(F2, 1)], start_beat=8.0, vel_base=108)
    bass_notes += reggae_bass([(E2, 2)], start_beat=12.0)
    # Bars 6-7: just root notes on beat 1, fading
    bass_notes.append(_note(E2, 20.0, 3.5, 70, "bass", "fading"))
    bass_notes.append(_note(E2, 24.0, 3.5, 60, "bass", "fading"))
    # Bar 8: silent — let the organ pad close
    cid = M.create_clip(
        conn, track_id=tracks["02 Bass"], slot=8, length_beats=32.0,
        name="Outro Bass", section_role="outro",
    )
    M.replace_clip_notes(conn, clip_id=cid, notes=bass_notes)
    clips["02 Bass"] = cid

    # === Rhythm Gtr ===
    gtr_notes = []
    gtr_notes += metal_chug(E5_POWER, 2, start_beat=0.0, pattern="gallop", vel_base=100)
    gtr_notes += metal_chug(F5_POWER, 1, start_beat=8.0, pattern="gallop", vel_base=110)
    gtr_notes += reggae_skank(EM9_SKANK, 2, start_beat=12.0, vel=80)
    # Bars 6-7: sparser skank — only on offbeats 1.5 and 3.5
    for b in range(2):
        bs = 20.0 + b * 4.0
        for p in EM9_SKANK:
            gtr_notes.append(_note(p, bs + 1.5, 0.2, 72, "skank", "fading"))
            gtr_notes.append(_note(p, bs + 3.5, 0.2, 68, "skank", "fading"))
    # Bar 8: silent
    cid = M.create_clip(
        conn, track_id=tracks["03 Rhythm Gtr"], slot=8, length_beats=32.0,
        name="Outro Rhythm Gtr", section_role="outro",
    )
    M.replace_clip_notes(conn, clip_id=cid, notes=gtr_notes)
    clips["03 Rhythm Gtr"] = cid

    # === Organ ===
    organ_notes = []
    # Bars 1-2 SILENT (metal)
    # Bar 3 SILENT (metal whack)
    # Bars 4-5: skank pattern returns
    organ_notes += reggae_skank(EM9_ORGAN[:4], 2, start_beat=12.0, vel=68)
    # Bars 6-7: sustained pad starting to emerge
    for p in EM9_ORGAN:
        organ_notes.append(_note(p, 20.0, 7.5, 55, "pad", "settling"))
    # Bar 8: SUSTAINED Em9 with held F#5 (the unresolved Dorian color tone)
    for p in EM9_ORGAN:
        organ_notes.append(_note(p, 28.0, 4.0, 50, "pad", "final"))
    # Final unresolved F#5 hangs — the Dorian/Phrygian conflict never resolves
    organ_notes.append(_note(78, 30.0, 2.0, 60, "pad", "unresolved-Fs"))
    cid = M.create_clip(
        conn, track_id=tracks["04 Organ"], slot=8, length_beats=32.0,
        name="Outro Organ", section_role="outro",
    )
    M.replace_clip_notes(conn, clip_id=cid, notes=organ_notes)
    clips["04 Organ"] = cid

    # === Lead Voice ===
    lead_notes = []
    # Bars 1-2 metal: "Still not done" — shouted, fading
    for beat, pitch in [(0.5, 65), (1.0, 65), (2.0, 64), (4.5, 65), (5.0, 65), (6.0, 64)]:
        lead_notes.append(_note(pitch, beat, 0.4, 100, "lead", "metal", "fading"))
    # Bar 3 metal whack: "NO MORE"
    lead_notes.append(_note(65, 8.0, 0.5, 115, "lead", "metal", "final-whack"))
    lead_notes.append(_note(67, 9.0, 0.5, 110, "lead", "metal", "final-whack"))
    # Bars 4-5 reggae: "back to the sun..."
    lead_notes += [
        _note(64, 13.0, 0.5, 75, "lead", "reggae"),
        _note(62, 13.5, 0.5, 72, "lead", "reggae"),
        _note(60, 14.0, 1.0, 73, "lead", "reggae"),
        _note(62, 16.0, 0.5, 75, "lead", "reggae"),
        _note(64, 17.0, 0.5, 75, "lead", "reggae"),
        _note(66, 17.5, 2.0, 78, "lead", "reggae", "hold"),  # F#4 held
    ]
    # Bars 6-7: very sparse — just the F# breath
    lead_notes.append(_note(66, 22.0, 3.0, 65, "lead", "fading", "Fs"))
    # Bar 8: SILENT — let organ hold the final note
    cid = M.create_clip(
        conn, track_id=tracks["05 Lead Voice"], slot=8, length_beats=32.0,
        name="Outro Lead", section_role="outro",
    )
    M.replace_clip_notes(conn, clip_id=cid, notes=lead_notes)
    clips["05 Lead Voice"] = cid

    # Counter-melody silent in outro
    return clips


# ---------------------------------------------------------------------------
# Channel-switch envelope: Rhythm Gtr Amp Device On per section
# ---------------------------------------------------------------------------
#
# Tension instrument has no genre-specific character on its own; the Amp is
# what makes metal sections sound metal. But the same Amp on reggae sections
# turns the skanks into rock chords. Per-section channel switching is the
# song's authorship — author it via clip-envelope automation on the Amp's
# 'Device On' parameter:
#
#   Off (Device On=0) during reggae bars → signal bypasses amp distortion;
#     Cabinet + EQ + Comp still shape the tone but no overdrive.
#   On  (Device On=1) during metal bars → full Heavy amp character.
#
# Breakpoints land at song-bar boundaries (1-based bars converted to 0-based
# beats — bar 1 starts at beat 0). The value alternates per the section's
# internal genre layout.


# Amp's "Amp Type" is a 7-value enum: Clean / Boost / Blues / Heavy / Smith /
# Lead / Bass (Live's value_items order; index = numeric value stored). The
# build authors enum-name breakpoints; M.create_enum_envelope resolves the
# names to numeric indices at compose time, falling back to this list when
# the snapshot hasn't yet captured the param's value_items_json.
_AMP_TYPE_VALUE_ITEMS = (
    "Clean", "Boost", "Blues", "Heavy", "Smith", "Lead", "Bass",
)


def _amp_type_breakpoints() -> list[dict]:
    """Build the Amp Type breakpoint list for the rhythm-gtr Amp.

    Returns list of {time_beats, value} dicts. value is 'Clean' (reggae
    sections — bright skanks) or 'Heavy' (metal sections — palm-muted
    chugs). M.create_enum_envelope resolves the enum-name strings to
    Amp's numeric indices (Clean=0, Heavy=3) at compose time. Live
    treats enum params as step changes — curve defaults to 'hold' via
    the helper.
    """
    # (start_beat, amp_type) tuples — bars in song-space, 1-based bars start at b 0.
    # Each section (8 bars = 32 beats) maps to 4 quadrants × 2 bars = 8 beats each.
    segments: list[tuple[float, str]] = [
        # intro (b 0-32)
        (0.0,   "Clean"),  # bars 1-4 silent guitar → clean (the default)
        (24.0,  "Heavy"),  # bar 7 metal WHACK
        (28.0,  "Clean"),  # bar 8 reggae resume
        # verse1 (b 32-64) — Clean-Heavy-Clean-Heavy 8-beat quadrants
        (32.0,  "Clean"),
        (40.0,  "Heavy"),
        (48.0,  "Clean"),
        (56.0,  "Heavy"),
        # chorus1 (b 64-96)
        (64.0,  "Clean"),
        (72.0,  "Heavy"),
        (80.0,  "Clean"),
        (88.0,  "Heavy"),
        # verse2 (b 96-128)
        (96.0,  "Clean"),
        (104.0, "Heavy"),
        (112.0, "Clean"),
        (120.0, "Heavy"),
        # chorus2 (b 128-160)
        (128.0, "Clean"),
        (136.0, "Heavy"),
        (144.0, "Clean"),
        (152.0, "Heavy"),
        # bridge (b 160-192) — metal stabs throughout the bleed; sparse middle off
        (160.0, "Heavy"),
        (176.0, "Clean"),
        (184.0, "Heavy"),
        # chorus3 (b 192-224)
        (192.0, "Clean"),
        (200.0, "Heavy"),
        (208.0, "Clean"),
        (216.0, "Heavy"),
        # outro (b 224-256) — metal fades, then reggae back
        (224.0, "Heavy"),
        (236.0, "Clean"),
    ]
    return [{"time_beats": float(t), "value": v} for t, v in segments]


def _author_amp_envelope(conn, song_id: str, tracks: dict[str, str]) -> None:
    """Author the Rhythm Gtr Amp Type envelope (E1 empirical driver).

    Targets the Amp at chain position 2 on track '03 Rhythm Gtr'. Uses
    M.create_enum_envelope's value_items escape hatch — the snapshot
    only captures value_items after the first round-trip pull through
    Live, and this build runs offline (no Live required).
    """
    rg_track_id = tracks["03 Rhythm Gtr"]
    devices = Q.get_devices_for_track(conn, rg_track_id)
    amp_device = None
    for d in devices:
        if d["kind"] == "Amp":
            amp_device = d
            break
    if amp_device is None:
        raise RuntimeError(
            f"Expected an 'Amp' device on track '03 Rhythm Gtr'; "
            f"found {[d['kind'] for d in devices]}"
        )
    M.create_enum_envelope(
        conn,
        device_id=amp_device["id"],
        parameter_name="Amp Type",
        breakpoints=_amp_type_breakpoints(),
        value_items=_AMP_TYPE_VALUE_ITEMS,
        actor="build",
        reason="per-section amp character: Clean for reggae skanks, Heavy for metal gallops",
    )


# ---------------------------------------------------------------------------
# Arrangement
# ---------------------------------------------------------------------------


def _arrange_section(conn, song_id, tracks, clips, *, start_bar, end_bar):
    """Place every clip in `clips` on its track between start_bar and end_bar."""
    for track_name, clip_id in clips.items():
        M.add_arrangement_clip(
            conn, song_id=song_id,
            track_id=tracks[track_name], clip_id=clip_id,
            start_bar=start_bar, end_bar=end_bar,
        )


# ---------------------------------------------------------------------------
# Top-level build
# ---------------------------------------------------------------------------


def build(reset=False):
    conn = init_db(DB_PATH)
    try:
        if reset:
            song = Q.get_song_by_name(conn, "sun-zone-done")
            if song is not None:
                M.reset_song_content(conn, song_id=song["id"])
        with M.build_session(conn, song_name="sun-zone-done", owner="build.py"):
            # Mix-half
            snapshot = json.loads(SNAPSHOT_PATH.read_text())
            song_id = replay_capture(
                conn, snapshot,
                song_name="sun-zone-done",
                song_title="Sun Zone / Stuff Done",
                song_key='Em',
                actor="sync", reason="initial capture replay",
            )

            # Score-half
            M.set_song_timing_mode(conn, song_id=song_id, timing_mode="native")
            M.add_tempo_point(conn, song_id=song_id, start_bar=1.0, tempo_bpm=180.0)
            M.add_time_signature_point(
                conn, song_id=song_id, start_bar=1.0, numerator=4, denominator=4,
            )

            # Sections
            section_specs = [
                ("intro",   INTRO_BAR,   VERSE1_BAR,  "drift → reggae groove → metal WHACK → reggae"),
                ("verse1",  VERSE1_BAR,  CHORUS1_BAR, "alternating 2-bar reggae / 2-bar metal × 2"),
                ("chorus1", CHORUS1_BAR, VERSE2_BAR,  "faster alternation; counter-melody hook enters"),
                ("verse2",  VERSE2_BAR,  CHORUS2_BAR, "ratcheted intensity, same alternation shape"),
                ("chorus2", CHORUS2_BAR, BRIDGE_BAR,  "twist variation"),
                ("bridge",  BRIDGE_BAR,  CHORUS3_BAR, "genre bleed — alternation rule breaks"),
                ("chorus3", CHORUS3_BAR, OUTRO_BAR,   "final payoff chorus"),
                ("outro",   OUTRO_BAR,   END_BAR,     "reverse of intro — drifts out, unresolved F#"),
            ]
            for name, sb, eb, notes in section_specs:
                M.create_section(conn, song_id=song_id, name=name,
                                 start_bar=float(sb), end_bar=float(eb),
                                 notes_md=notes)
            for sb, name in [(INTRO_BAR, "intro"), (VERSE1_BAR, "verse1"),
                             (CHORUS1_BAR, "chorus1"), (VERSE2_BAR, "verse2"),
                             (CHORUS2_BAR, "chorus2"), (BRIDGE_BAR, "bridge"),
                             (CHORUS3_BAR, "chorus3"), (OUTRO_BAR, "outro")]:
                M.add_cue_point(conn, song_id=song_id, position_bar=float(sb), name=name)

            tracks = _tracks_by_name(conn, song_id)

            # Compose-half: build each section's clips
            intro   = _build_intro(conn, song_id, tracks)
            verse1  = _build_verse(conn, song_id, tracks, slot=2, name_suffix="V1", intensity=1.0)
            chorus1 = _build_chorus(conn, song_id, tracks, slot=3, name_suffix="C1", variation=1)
            verse2  = _build_verse(conn, song_id, tracks, slot=4, name_suffix="V2", intensity=1.1)
            chorus2 = _build_chorus(conn, song_id, tracks, slot=5, name_suffix="C2", variation=2)
            bridge_ = _build_bridge(conn, song_id, tracks)
            chorus3 = _build_chorus(conn, song_id, tracks, slot=7, name_suffix="C3", variation=3)
            outro   = _build_outro(conn, song_id, tracks)

            # Arrangement
            _arrange_section(conn, song_id, tracks, intro,   start_bar=float(INTRO_BAR),   end_bar=float(VERSE1_BAR))
            _arrange_section(conn, song_id, tracks, verse1,  start_bar=float(VERSE1_BAR),  end_bar=float(CHORUS1_BAR))
            _arrange_section(conn, song_id, tracks, chorus1, start_bar=float(CHORUS1_BAR), end_bar=float(VERSE2_BAR))
            _arrange_section(conn, song_id, tracks, verse2,  start_bar=float(VERSE2_BAR),  end_bar=float(CHORUS2_BAR))
            _arrange_section(conn, song_id, tracks, chorus2, start_bar=float(CHORUS2_BAR), end_bar=float(BRIDGE_BAR))
            _arrange_section(conn, song_id, tracks, bridge_, start_bar=float(BRIDGE_BAR),  end_bar=float(CHORUS3_BAR))
            _arrange_section(conn, song_id, tracks, chorus3, start_bar=float(CHORUS3_BAR), end_bar=float(OUTRO_BAR))
            _arrange_section(conn, song_id, tracks, outro,   start_bar=float(OUTRO_BAR),   end_bar=float(END_BAR))

            # Channel-switch automation: Amp Device On per section.
            _author_amp_envelope(conn, song_id, tracks)

        return song_id
    finally:
        conn.close()


def report(song_id):
    conn = init_db(DB_PATH)
    try:
        song_row = Q.get_song(conn, song_id)
        tracks = Q.get_tracks_for_song(conn, song_id)
        print(f"song_id={song_id}, timing_mode={song_row['timing_mode']}, tracks={len(tracks)}")
        total_notes = 0
        for t in tracks:
            clips = Q.get_clips_for_track(conn, t["id"])
            notes_in_track = sum(len(Q.get_notes_for_clip(conn, c["id"])) for c in clips)
            total_notes += notes_in_track
            print(f"  track {t['track_index']:>2}  {t['name']:<24} ({t['kind']}, {len(clips)} clips, {notes_in_track} notes)")
        sections = [s["name"] for s in Q.get_sections_for_song(conn, song_id)]
        print(f"total notes: {total_notes}")
        print(f"sections: {sections}")
        arr = Q.get_arrangement_for_song(conn, song_id) if hasattr(Q, "get_arrangement_for_song") else []
        print(f"arrangement entries: {len(arr)}")
    finally:
        conn.close()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--reset", action="store_true", help="drop + rebuild")
    args = p.parse_args()
    sid = build(reset=args.reset)
    report(sid)
