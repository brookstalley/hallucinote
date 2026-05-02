#!/usr/bin/env python3
"""
Generate MIDI note arrays for falling-walking song clips. v2 - liveliness pass.

Changes vs v1:
- Bass: rhythmic motion (verse follows kick stumble; chorus tresillo; bridge walking)
- Pad: re-articulation stabs + inner-voice walk in long Dm
- Drums: 16th snare rolls every 4 bars in verse, real fill bar 14, ghost kicks/snares
- Intro: progressive hat journey (silence -> bossa shaker -> tresillo -> trip-hop)
- Intro arp (chorus pluck): foreshadows verse 8/4/2/1 chord progression
- Intro bell: sparse high arpeggio bars 5-8
- Intro lead: hook fragment bars 9-12, full hook bars 13-16
- C3' drums (NEW): chorus pattern + multi-flavor crashes (49/55/57/52)
"""
import json
import sys

LAZY = 0.04


def add_chord(notes, pitches, start, dur, vel=85):
    for p in pitches:
        notes.append({"pitch": p, "start_time": start, "duration": dur, "velocity": vel})


def stab(notes, pitches, start, vel=95, dur=0.5):
    add_chord(notes, pitches, start, dur, vel)


# =====================================================================
# VERSE (15 bars = 60 beats)
# =====================================================================

verse_drums = []
for b in range(14):  # bars 1..14 musically
    bs = b * 4.0
    is_strong_bar = (b % 4 == 0)

    # KICK: stumble (1 + late 2.75 alt bars)
    verse_drums.append({"pitch": 36, "start_time": bs + 0.0, "duration": 0.25,
                        "velocity": 118 if is_strong_bar else 110})
    if b % 2 == 0:
        verse_drums.append({"pitch": 36, "start_time": bs + 2.75, "duration": 0.25, "velocity": 92})
    else:
        verse_drums.append({"pitch": 36, "start_time": bs + 2.0, "duration": 0.25, "velocity": 95})
    # ghost kick offbeat 3.5 every 4 bars
    if b in [3, 7, 11]:
        verse_drums.append({"pitch": 36, "start_time": bs + 3.5, "duration": 0.12, "velocity": 50})

    # SNARE: 2 + 4 laid-back, ghost on 3.75 alt bars, 16th roll on beat 4 every 4 bars
    verse_drums.append({"pitch": 38, "start_time": bs + 1.0 + LAZY, "duration": 0.25, "velocity": 100})
    verse_drums.append({"pitch": 38, "start_time": bs + 3.0 + LAZY, "duration": 0.25, "velocity": 112})
    if b % 2 == 1:
        verse_drums.append({"pitch": 38, "start_time": bs + 3.75, "duration": 0.1, "velocity": 38})
    if b in [3, 7, 11]:  # mini-fill on bar 4/8/12 beat 4
        verse_drums.append({"pitch": 38, "start_time": bs + 3.5, "duration": 0.1, "velocity": 78})
        verse_drums.append({"pitch": 38, "start_time": bs + 3.625, "duration": 0.08, "velocity": 82})
        verse_drums.append({"pitch": 38, "start_time": bs + 3.875, "duration": 0.08, "velocity": 90})

    # HATS 8ths with deep ghosts; ghosts louder on bars 4/8/12 (build)
    for i, t in enumerate([0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5]):
        v = 80 if i % 2 == 0 else 35
        if b in [3, 7, 11] and i % 2 == 1:
            v = 52
        verse_drums.append({"pitch": 42, "start_time": bs + t, "duration": 0.1, "velocity": v})

# Bar 15 (b=14): real drum fill (toms + snare roll + crash)
bs = 14 * 4.0
verse_drums.append({"pitch": 36, "start_time": bs + 0.0, "duration": 0.25, "velocity": 115})
verse_drums.append({"pitch": 38, "start_time": bs + 1.0, "duration": 0.15, "velocity": 100})
# tom fill
verse_drums.append({"pitch": 47, "start_time": bs + 1.5, "duration": 0.15, "velocity": 92})
verse_drums.append({"pitch": 47, "start_time": bs + 1.75, "duration": 0.15, "velocity": 96})
verse_drums.append({"pitch": 50, "start_time": bs + 2.0, "duration": 0.15, "velocity": 102})
verse_drums.append({"pitch": 50, "start_time": bs + 2.25, "duration": 0.15, "velocity": 108})
# 32nd snare roll into beat 4
for i in range(8):
    t = 2.5 + i * 0.125
    v = 90 + i * 4
    verse_drums.append({"pitch": 38, "start_time": bs + t, "duration": 0.08, "velocity": min(v, 122)})
# Crash on beat 4
verse_drums.append({"pitch": 49, "start_time": bs + 3.5, "duration": 1.0, "velocity": 110})
# Hat ticks first half
verse_drums.append({"pitch": 42, "start_time": bs + 0.0, "duration": 0.1, "velocity": 80})
verse_drums.append({"pitch": 42, "start_time": bs + 0.5, "duration": 0.1, "velocity": 45})

# Drummer flourishes — open-hat lifts on mini-fill bars 4/8/12 beat 3.5
for _b in [3, 7, 11]:
    verse_drums.append({"pitch": 46, "start_time": _b * 4.0 + 3.5, "duration": 0.4, "velocity": 70})
# Soft chord-change crashes (drummer marks the form, not bombast)
verse_drums.append({"pitch": 49, "start_time": 32.0, "duration": 1.5, "velocity": 75})  # bar 9 Gm arrival
verse_drums.append({"pitch": 55, "start_time": 48.0, "duration": 1.0, "velocity": 70})  # bar 13 Bb (splash)
# Ride bell ghost notes in bar 7 — texture variation deep in the long Dm
for _t, _v in [(0.0, 45), (1.0, 38), (2.0, 42), (3.0, 36)]:
    verse_drums.append({"pitch": 53, "start_time": 24.0 + _t, "duration": 0.15, "velocity": _v})

# BASS — bass-player thinking: chord tones, ghosts, chromatic walks into chord changes
verse_bass = []
def _vb(p, t, dur, v):
    verse_bass.append({"pitch": p, "start_time": t, "duration": dur, "velocity": v})

# Bars 1-8 Dm (D2=38)
# Bar 1: establish — pure root + stumble
_vb(38, 0.0, 1.5, 105)
_vb(38, 2.75, 0.75, 88)
# Bar 2: octave answer
_vb(38, 4.0, 0.5, 100)
_vb(33, 4.5, 0.3, 70)            # A1 grace (5th below)
_vb(38, 6.0, 1.5, 92)
_vb(50, 7.5, 0.4, 80)            # D3 octave answer
# Bar 3: 3rd embellishment
_vb(38, 8.0, 1.5, 102)
_vb(38, 10.75, 0.4, 88)
_vb(41, 11.25, 0.5, 78)          # F2 (3rd of Dm)
_vb(38, 11.75, 0.25, 70)
# Bar 4: turnaround mini-walk
_vb(38, 12.0, 1.5, 100)
_vb(38, 14.0, 0.75, 90)
_vb(33, 14.875, 0.125, 50)       # A1 ghost
_vb(36, 15.5, 0.25, 78)          # C2 walk
_vb(38, 15.75, 0.25, 85)         # back to D
# Bar 5: octave figure restart
_vb(38, 16.0, 1.0, 105)
_vb(50, 17.0, 0.5, 78)            # D3 octave accent
_vb(38, 18.75, 0.75, 88)
# Bar 6: ghost-heavy
_vb(38, 20.0, 0.4, 98)
_vb(38, 20.5, 0.125, 45)         # ghost
_vb(38, 22.0, 1.0, 92)
_vb(45, 23.5, 0.4, 80)           # A2 (5th up)
# Bar 7: chord-tone climb
_vb(38, 24.0, 1.0, 102)
_vb(41, 25.0, 0.5, 80)           # F2
_vb(38, 26.75, 0.5, 88)
_vb(40, 27.5, 0.5, 75)           # E2 chromatic passing
# Bar 8: walk into Gm
_vb(38, 28.0, 1.5, 100)
_vb(38, 30.0, 0.5, 92)
_vb(41, 30.5, 0.5, 90)           # F2
_vb(42, 31.5, 0.5, 95)           # F#2 chromatic leading tone

# Bars 9-12 Gm (G2=43)
# Bar 9: strong arrival
_vb(43, 32.0, 1.5, 110)
_vb(43, 34.75, 0.75, 90)
# Bar 10: 3rd embellishment + ghost
_vb(43, 36.0, 0.5, 100)
_vb(38, 36.875, 0.125, 55)       # D2 ghost (5th below)
_vb(43, 38.0, 1.0, 92)
_vb(46, 39.5, 0.4, 82)           # Bb2 (3rd of Gm)
# Bar 11: chord tone climb
_vb(43, 40.0, 1.0, 102)
_vb(46, 41.0, 0.5, 82)           # Bb2
_vb(43, 42.75, 0.5, 88)
_vb(50, 43.5, 0.4, 80)           # D3 (5th)
# Bar 12: walk into Bb
_vb(43, 44.0, 1.0, 100)
_vb(43, 46.0, 0.5, 90)
_vb(44, 46.5, 0.5, 78)           # G#2 chromatic
_vb(45, 47.0, 0.5, 88)           # A2
_vb(34, 47.5, 0.5, 95)           # Bb1 (low octave land)

# Bars 13-14 Bb (Bb1=34)
# Bar 13: strong, low octave
_vb(34, 48.0, 1.5, 105)
_vb(34, 50.75, 0.75, 88)
_vb(41, 51.5, 0.5, 80)           # F2 (5th)
# Bar 14: walk into A
_vb(34, 52.0, 1.0, 102)
_vb(38, 53.0, 0.5, 88)           # D2 (3rd of Bb)
_vb(41, 54.0, 0.5, 92)           # F2 (5th of Bb)
_vb(38, 54.5, 0.5, 85)
_vb(34, 55.0, 0.5, 88)
_vb(34, 55.5, 0.25, 92)
_vb(33, 55.75, 0.25, 100)        # A1 pickup to bar 15

# Bar 15 A — 8th-note drive with octave punctuation + chromatic neighbor
for i, t in enumerate([0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0]):
    p = 45 if i in (3, 6) else 33  # A2 octave on beats 2.5 and 4.0; A1 elsewhere
    v = 95 + i * 2
    _vb(p, 56.0 + t, 0.4, v)
_vb(34, 59.5, 0.25, 92)           # Bb1 chromatic upper
_vb(33, 59.75, 0.25, 110)         # A1 resolve into bar 16/chorus

# SUB — octave below synth bass
verse_sub = [{"pitch": max(n["pitch"] - 12, 0),
              "start_time": n["start_time"],
              "duration": n["duration"],
              "velocity": int(n["velocity"] * 0.85)}
             for n in verse_bass]

# PAD — chord with inner-voice walk + stabs on bar 4/8/12 beat 4
verse_pad = []
# Bars 1-8 Dm: F3, A3 sustained 32 beats; top voice walks D4 -> E4 -> F4 -> E4
verse_pad.append({"pitch": 53, "start_time": 0.0, "duration": 32.0, "velocity": 80})
verse_pad.append({"pitch": 57, "start_time": 0.0, "duration": 32.0, "velocity": 80})
verse_pad.append({"pitch": 62, "start_time": 0.0, "duration": 16.0, "velocity": 82})  # D4 bars 1-4
verse_pad.append({"pitch": 64, "start_time": 16.0, "duration": 8.0, "velocity": 85})  # E4 bars 5-6
verse_pad.append({"pitch": 65, "start_time": 24.0, "duration": 4.0, "velocity": 88})  # F4 bar 7
verse_pad.append({"pitch": 64, "start_time": 28.0, "duration": 4.0, "velocity": 85})  # E4 bar 8
# Stabs on bar 4 / bar 8 beat 4
stab(verse_pad, [53, 57, 62], 14.0, 95, 0.5)
stab(verse_pad, [53, 57, 64], 30.0, 98, 0.5)
# Bars 9-12 Gm
verse_pad.append({"pitch": 55, "start_time": 32.0, "duration": 16.0, "velocity": 84})
verse_pad.append({"pitch": 58, "start_time": 32.0, "duration": 16.0, "velocity": 84})
verse_pad.append({"pitch": 62, "start_time": 32.0, "duration": 16.0, "velocity": 84})
stab(verse_pad, [55, 58, 62], 46.0, 100, 0.5)
# Bars 13-14 Bb
verse_pad.append({"pitch": 53, "start_time": 48.0, "duration": 8.0, "velocity": 88})
verse_pad.append({"pitch": 58, "start_time": 48.0, "duration": 8.0, "velocity": 88})
verse_pad.append({"pitch": 62, "start_time": 48.0, "duration": 8.0, "velocity": 88})
# Bar 15 A: stabs on beats 1, 2, 3, 4
for t in [0.0, 1.0, 2.0, 3.0]:
    stab(verse_pad, [57, 61, 64], 56.0 + t, 95, 0.6)


# =====================================================================
# CHORUS (8 bars = 32 beats) — half-time + calypso
# =====================================================================

chorus_drums = []
for b in range(8):
    bs = b * 4.0
    chorus_drums.append({"pitch": 36, "start_time": bs + 0.0, "duration": 0.3, "velocity": 118})
    if b % 2 == 1:
        chorus_drums.append({"pitch": 36, "start_time": bs + 3.5, "duration": 0.2, "velocity": 70})
    if b % 4 == 2:
        chorus_drums.append({"pitch": 36, "start_time": bs + 1.5, "duration": 0.15, "velocity": 55})
    chorus_drums.append({"pitch": 38, "start_time": bs + 2.0, "duration": 0.35, "velocity": 115})
    # ghost snare on 2.75 (after the half-time hit)
    chorus_drums.append({"pitch": 38, "start_time": bs + 2.75, "duration": 0.1, "velocity": 42})
    if b % 2 == 1:
        chorus_drums.append({"pitch": 38, "start_time": bs + 2.875, "duration": 0.08, "velocity": 38})
    for t, v in [(0.0, 75), (0.75, 95), (1.5, 95), (2.0, 75), (2.75, 95), (3.5, 90)]:
        chorus_drums.append({"pitch": 42, "start_time": bs + t, "duration": 0.1, "velocity": v})
    if b % 2 == 1:
        chorus_drums.append({"pitch": 46, "start_time": bs + 3.75, "duration": 0.25, "velocity": 80})

# Soft crash on chorus arrival (subtle entry accent)
chorus_drums.append({"pitch": 49, "start_time": 0.0, "duration": 1.5, "velocity": 88})
# Snare flick on bar 8 final 16ths — pushes into next section
chorus_drums.append({"pitch": 38, "start_time": 31.5, "duration": 0.1, "velocity": 70})
chorus_drums.append({"pitch": 38, "start_time": 31.75, "duration": 0.1, "velocity": 88})

# BASS — tresillo with bass-player embellishments. Plain bar establishes; embellished bar
# adds chord tones, octave jumps, and walks into the next chord change.
TRESILLO = [(0.0, 102), (0.75, 90), (1.5, 88), (2.0, 95), (2.75, 85), (3.5, 88)]

def _build_chorus_bass(walk_in_pitches):
    """walk_in_pitches: 4-tuple of pitches to use on bar 8 last 3.5 beat (walk back to next loop)."""
    notes = []
    def add(p, t, dur, v):
        notes.append({"pitch": p, "start_time": t, "duration": dur, "velocity": v})

    # Bars 1-2 Dm (D2=38)
    # Bar 1: plain tresillo on D2
    for t, v in TRESILLO: add(38, t, 0.5, v)
    # Bar 2: embellished — chord tones + octave answer
    add(38, 4.0, 0.5, 100)
    add(41, 4.75, 0.4, 88)        # F2 (3rd)
    add(38, 5.5, 0.4, 85)
    add(50, 6.0, 0.5, 95)         # D3 octave up
    add(38, 6.75, 0.4, 82)
    add(40, 7.5, 0.5, 88)         # E2 chromatic walk to F at bar 3

    # Bars 3-4 F (F2=41)
    # Bar 3: plain tresillo on F2
    for t, v in TRESILLO: add(41, 8.0 + t, 0.5, v)
    # Bar 4: embellished — chord tones + walk to C
    add(41, 12.0, 0.5, 100)
    add(45, 12.75, 0.4, 88)       # A2 (3rd of F)
    add(41, 13.5, 0.4, 85)
    add(48, 14.0, 0.5, 95)        # C3 (5th up octave)
    add(41, 14.75, 0.4, 82)
    add(38, 15.5, 0.5, 88)        # D2 upper neighbor leading to C

    # Bars 5-6 C (C2=36)
    # Bar 5: plain tresillo on C2
    for t, v in TRESILLO: add(36, 16.0 + t, 0.5, v)
    # Bar 6: embellished — chord tones + walk to G
    add(36, 20.0, 0.5, 100)
    add(40, 20.75, 0.4, 88)       # E2 (3rd of C)
    add(36, 21.5, 0.4, 85)
    add(43, 22.0, 0.5, 95)        # G2 (5th)
    add(36, 22.75, 0.4, 82)
    add(41, 23.5, 0.5, 90)        # F2 passing to G

    # Bars 7-8 — caller-supplied (G or Bb)
    # Bar 7: plain tresillo on first walk_in pitch
    p7 = walk_in_pitches[0]
    for t, v in TRESILLO: add(p7, 24.0 + t, 0.5, v)
    # Bar 8: embellished walk back to Dm for next chorus loop
    add(walk_in_pitches[0], 28.0, 0.5, 100)
    add(walk_in_pitches[1], 28.75, 0.4, 88)
    add(walk_in_pitches[0], 29.5, 0.4, 85)
    add(walk_in_pitches[2], 30.0, 0.5, 95)
    add(walk_in_pitches[0], 30.75, 0.4, 82)
    add(walk_in_pitches[3], 31.5, 0.5, 92)
    return notes

# walk_in_pitches: [root, 3rd, 5th-up, walk-to-next-chord]
# Regular chorus bars 7-8 = G2: G2, B2, D3, A2 (A2 = 5th of Dm, primes loop-back)
chorus_bass = _build_chorus_bass([43, 47, 50, 45])
# C3' twist bars 7-8 = Bb: Bb1, D2, F2, A1 (A1 half-step below Dm root)
chorus_bass_twist = _build_chorus_bass([34, 38, 41, 33])

# SUB — root on beat 1 of each bar, sustained
chorus_sub = []
for chord_start, p in [(0.0, 38), (8.0, 41), (16.0, 36), (24.0, 43)]:
    for bar_offset in [0.0, 4.0]:
        bs = chord_start + bar_offset
        chorus_sub.append({"pitch": p - 12, "start_time": bs + 0.0, "duration": 3.5, "velocity": 88})

# C3' twist sub — last 2 bars Bb-1 octave instead of G-1 octave
chorus_sub_twist = []
for chord_start, p in [(0.0, 38), (8.0, 41), (16.0, 36), (24.0, 34)]:  # last chord is Bb1=34
    for bar_offset in [0.0, 4.0]:
        bs = chord_start + bar_offset
        chorus_sub_twist.append({"pitch": p - 12, "start_time": bs + 0.0, "duration": 3.5, "velocity": 88})

# PAD with 7ths — long sustains let the slow-evolving patch bloom; tiny gap at chord change
chorus_pad = []
chord_voicings_pad = [
    (0.0,  [53, 57, 60, 62]),
    (8.0,  [53, 57, 60, 64]),
    (16.0, [52, 55, 59, 60]),
    (24.0, [55, 59, 62])
]
for start, voicing in chord_voicings_pad:
    add_chord(chorus_pad, voicing, start, 7.5, 78)

# C3' TWIST PAD — last 2 bars Bbmaj7 instead of G
chorus_pad_twist = []
chord_voicings_twist = [
    (0.0,  [53, 57, 60, 62]),
    (8.0,  [53, 57, 60, 64]),
    (16.0, [52, 55, 59, 60]),
    (24.0, [53, 57, 58, 62])
]
for start, voicing in chord_voicings_twist:
    add_chord(chorus_pad_twist, voicing, start, 7.5, 78)

# PLUCK — calypso tresillo
chord_voicings_pluck = {
    "Dm": [62, 65, 69], "F": [65, 69, 72], "C": [60, 64, 67],
    "G": [62, 67, 71], "Bb": [65, 70, 74],
}
chorus_pluck = []
for sect_start, chord in [(0, "Dm"), (8, "F"), (16, "C"), (24, "G")]:
    voices = chord_voicings_pluck[chord]
    for bar_in_sect in range(2):
        bs = sect_start + bar_in_sect * 4.0
        for i, (t, v) in enumerate([(0.0, 95), (0.75, 100), (1.5, 90), (2.0, 75), (2.75, 95), (3.5, 100)]):
            chorus_pluck.append({"pitch": voices[i % 3], "start_time": bs + t, "duration": 0.2, "velocity": v})

chorus_pluck_twist = []
for sect_start, chord in [(0, "Dm"), (8, "F"), (16, "C"), (24, "Bb")]:
    voices = chord_voicings_pluck[chord]
    for bar_in_sect in range(2):
        bs = sect_start + bar_in_sect * 4.0
        for i, (t, v) in enumerate([(0.0, 95), (0.75, 100), (1.5, 90), (2.0, 75), (2.75, 95), (3.5, 100)]):
            chorus_pluck_twist.append({"pitch": voices[i % 3], "start_time": bs + t, "duration": 0.2, "velocity": v})

# BELL
chorus_bell = []
for sect_start, chord in [(0, "Dm"), (8, "F"), (16, "C"), (24, "G")]:
    top = chord_voicings_pluck[chord][2] + 12
    chorus_bell.append({"pitch": top, "start_time": sect_start + 0.0, "duration": 1.0, "velocity": 75})
    chorus_bell.append({"pitch": top - 5, "start_time": sect_start + 5.5, "duration": 0.5, "velocity": 65})

chorus_bell_twist = []
for sect_start, chord in [(0, "Dm"), (8, "F"), (16, "C"), (24, "Bb")]:
    top = chord_voicings_pluck[chord][2] + 12
    chorus_bell_twist.append({"pitch": top, "start_time": sect_start + 0.0, "duration": 1.0, "velocity": 75})
    chorus_bell_twist.append({"pitch": top - 5, "start_time": sect_start + 5.5, "duration": 0.5, "velocity": 65})


# =====================================================================
# C3' DRUMS (NEW) — chorus pattern + multi-flavor crashes
# =====================================================================
c3prime_drums = list(chorus_drums)
c3prime_drums.append({"pitch": 49, "start_time": 0.0, "duration": 1.0, "velocity": 115})   # Crash 1 — arrival
c3prime_drums.append({"pitch": 55, "start_time": 8.0, "duration": 0.5, "velocity": 90})    # Splash — Fmaj7 lift
c3prime_drums.append({"pitch": 57, "start_time": 16.0, "duration": 1.0, "velocity": 100})  # Crash 2 — Cmaj7 darker
c3prime_drums.append({"pitch": 52, "start_time": 24.0, "duration": 1.0, "velocity": 110})  # China — Bbmaj7 TWIST
c3prime_drums.append({"pitch": 49, "start_time": 31.5, "duration": 1.0, "velocity": 115})  # Crash 1 — push to outro


# =====================================================================
# BRIDGE (8 bars Bb major)
# =====================================================================

bridge_drums = []
for b in range(8):
    bs = b * 4.0
    for t, v in [(0.0, 95), (1.5, 78), (2.0, 88), (3.5, 75)]:
        bridge_drums.append({"pitch": 36, "start_time": bs + t, "duration": 0.2, "velocity": v})
    if b % 2 == 0:
        for t, v in [(0.0, 78), (1.5, 72), (2.5, 78)]:
            bridge_drums.append({"pitch": 37, "start_time": bs + t, "duration": 0.12, "velocity": v})
    else:
        for t, v in [(1.0, 75), (2.0, 80)]:
            bridge_drums.append({"pitch": 37, "start_time": bs + t, "duration": 0.12, "velocity": v})
    for sixteenth in range(16):
        t = sixteenth * 0.25
        v = 42 if sixteenth % 4 == 0 else 30
        bridge_drums.append({"pitch": 42, "start_time": bs + t, "duration": 0.08, "velocity": v})

# BASS — walking bossa with passing tones
# Each chord 8 beats. Walks: Bbmaj7 -> Gm7 -> Cm7 -> F7
bridge_bass = []
walks = [
    (0.0,  [34, 36, 38, 41]),  # Bb chord: Bb-C-D-F (root, 9, 3, 5)
    (8.0,  [31, 34, 36, 38]),  # G chord:  G-Bb-C-D
    (16.0, [36, 39, 41, 43]),  # C chord:  C-Eb-F-G
    (24.0, [41, 45, 48, 50]),  # F chord:  F-A-C-D
]
for start, walk in walks:
    for bar in range(2):
        bs = start + bar * 4.0
        for i, beat in enumerate([0.0, 1.5, 2.0, 3.5]):
            p = walk[i % len(walk)]
            v = 100 if i == 0 else 88
            bridge_bass.append({"pitch": p, "start_time": bs + beat, "duration": 1.0, "velocity": v})

bridge_sub = []
for start, walk in walks:
    bridge_sub.append({"pitch": walk[0] - 12, "start_time": start, "duration": 8.0, "velocity": 82})

bridge_ep = []
add_chord(bridge_ep, [58, 62, 65, 69], 0.0, 8.0, 80)
add_chord(bridge_ep, [55, 58, 62, 65], 8.0, 8.0, 80)
add_chord(bridge_ep, [60, 63, 67, 70], 16.0, 8.0, 80)
add_chord(bridge_ep, [53, 57, 60, 63], 24.0, 8.0, 80)


# =====================================================================
# TAG (4 bars) — unchanged
# =====================================================================
tag_drums = []
for b in range(4):
    bs = b * 4.0
    if b < 2:
        tag_drums.append({"pitch": 36, "start_time": bs + 0.0, "duration": 0.3, "velocity": 110})
        tag_drums.append({"pitch": 38, "start_time": bs + 2.0, "duration": 0.35, "velocity": 105})
        for t, v in [(0.0, 70), (0.75, 85), (1.5, 85), (2.0, 70), (2.75, 85), (3.5, 80)]:
            tag_drums.append({"pitch": 42, "start_time": bs + t, "duration": 0.1, "velocity": v})
    else:
        tag_drums.append({"pitch": 36, "start_time": bs + 0.0, "duration": 0.25, "velocity": 80})
        for sixteenth in range(16):
            t = sixteenth * 0.25
            v = 35 if sixteenth % 4 == 0 else 25
            tag_drums.append({"pitch": 42, "start_time": bs + t, "duration": 0.08, "velocity": v})

tag_pad = []
add_chord(tag_pad, [53, 57, 60, 62], 0.0, 12.0, 75)
add_chord(tag_pad, [53, 57, 58, 62], 12.0, 4.0, 80)


# =====================================================================
# INTRO (16 bars = 64 beats)
# =====================================================================

# DRUMS — progressive hat journey + kick from bar 13 + snare from bar 15
intro_drums = []
# Bars 1-4: hat tick on beat 1 only
for b in range(4):
    bs = b * 4.0
    intro_drums.append({"pitch": 42, "start_time": bs + 0.0, "duration": 0.1, "velocity": 50 + b*3})
# Bars 5-8: bossa 16th shaker
for b in range(4, 8):
    bs = b * 4.0
    for sixteenth in range(16):
        t = sixteenth * 0.25
        v = 35 if sixteenth % 4 == 0 else 24
        v += (b - 4) * 2
        intro_drums.append({"pitch": 42, "start_time": bs + t, "duration": 0.08, "velocity": v})
# Bars 9-12: tresillo
for b in range(8, 12):
    bs = b * 4.0
    for t, v_base in [(0.0, 60), (0.75, 78), (1.5, 78), (2.0, 60), (2.75, 78), (3.5, 75)]:
        v = v_base + (b - 8) * 3
        intro_drums.append({"pitch": 42, "start_time": bs + t, "duration": 0.1, "velocity": v})
# Bars 13-16: trip-hop 8ths with ghosts
for b in range(12, 16):
    bs = b * 4.0
    for i, t in enumerate([0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5]):
        v = 80 if i % 2 == 0 else 35
        intro_drums.append({"pitch": 42, "start_time": bs + t, "duration": 0.1, "velocity": v})
intro_drums.append({"pitch": 46, "start_time": 63.5, "duration": 0.5, "velocity": 95})  # open hat lift

# Kick: enters bar 13 with stumble pattern
for b in range(12, 16):
    bs = b * 4.0
    intro_drums.append({"pitch": 36, "start_time": bs + 0.0, "duration": 0.25, "velocity": 95 + (b - 12) * 5})
    if b % 2 == 0:
        intro_drums.append({"pitch": 36, "start_time": bs + 2.75, "duration": 0.25, "velocity": 80})
    else:
        intro_drums.append({"pitch": 36, "start_time": bs + 2.0, "duration": 0.25, "velocity": 85})

# Snare: enters bar 15
for b in range(14, 16):
    bs = b * 4.0
    intro_drums.append({"pitch": 38, "start_time": bs + 1.0 + LAZY, "duration": 0.25, "velocity": 90})
    intro_drums.append({"pitch": 38, "start_time": bs + 3.0 + LAZY, "duration": 0.25, "velocity": 100})

# PAD
intro_pad = []
add_chord(intro_pad, [53, 57, 62], 0.0,  16.0, 60)
add_chord(intro_pad, [53, 57, 62], 16.0, 16.0, 70)
add_chord(intro_pad, [53, 57, 62], 32.0, 16.0, 80)
add_chord(intro_pad, [53, 57, 62], 48.0, 16.0, 88)

intro_sub = [{"pitch": 26, "start_time": 0.0, "duration": 64.0, "velocity": 75}]

# ARP (foreshadows verse 8/4/2/1) — chorus pluck track
intro_arp = []
# Bars 1-4 (Dm sparse): D4 + A3 alternating beats 1 and 3
for b in range(4):
    bs = b * 4.0
    intro_arp.append({"pitch": 62, "start_time": bs + 0.0, "duration": 1.0, "velocity": 65})
    intro_arp.append({"pitch": 57, "start_time": bs + 2.0, "duration": 1.0, "velocity": 60})
# Bars 5-8 (Dm 8ths)
for b in range(4, 8):
    bs = b * 4.0
    for t, p, v in [(0.0, 62, 75), (0.5, 65, 70), (1.0, 69, 78), (1.5, 65, 70),
                    (2.0, 62, 75), (2.5, 65, 70), (3.0, 69, 78), (3.5, 65, 70)]:
        intro_arp.append({"pitch": p, "start_time": bs + t, "duration": 0.4, "velocity": v + (b-4)*2})
# Bars 9-12 (Gm 8ths — iv reveal)
for b in range(8, 12):
    bs = b * 4.0
    for t, p, v in [(0.0, 67, 80), (0.5, 70, 75), (1.0, 74, 82), (1.5, 70, 75),
                    (2.0, 67, 80), (2.5, 70, 75), (3.0, 74, 82), (3.5, 70, 75)]:
        intro_arp.append({"pitch": p, "start_time": bs + t, "duration": 0.4, "velocity": v})
# Bars 13-14 (Bb 16ths)
for b in range(12, 14):
    bs = b * 4.0
    pitches = [70, 74, 77, 74]
    for sixteenth in range(16):
        t = sixteenth * 0.25
        p = pitches[sixteenth % 4]
        v = 78 + (sixteenth % 4) * 3
        intro_arp.append({"pitch": p, "start_time": bs + t, "duration": 0.2, "velocity": v})
# Bar 15 (A held)
intro_arp.append({"pitch": 69, "start_time": 56.0, "duration": 4.0, "velocity": 88})
# Bar 16: silence (breath)

# BELL — sparse high arpeggio bars 5-8
intro_bell = []
intro_bell.append({"pitch": 74, "start_time": 16.0, "duration": 2.0, "velocity": 70})  # bar 5 D5
intro_bell.append({"pitch": 77, "start_time": 22.0, "duration": 2.0, "velocity": 65})  # bar 6.5 F5
intro_bell.append({"pitch": 81, "start_time": 26.0, "duration": 2.0, "velocity": 75})  # bar 7.5 A5
intro_bell.append({"pitch": 74, "start_time": 30.0, "duration": 2.0, "velocity": 60})  # bar 8.5 D5

# CHIPTUNE LEAD — fragment bars 9-12, full hook bars 13-16
intro_lead = []
# Fragment (bars 9-12, beats 32-47): just first 4 notes, softer
for start, pitch, dur in [(32.0, 69, 1.0), (33.0, 65, 0.5), (33.5, 62, 1.0), (35.0, 67, 1.0)]:
    intro_lead.append({"pitch": pitch, "start_time": start, "duration": dur, "velocity": 70})
# Full hook (bars 13-16, beats 48-63)
for start, pitch, dur in [
    (48.0, 69, 1.0), (49.0, 65, 0.5), (49.5, 62, 1.0), (51.0, 67, 1.0),
    (52.0, 65, 0.75), (53.0, 64, 0.75), (54.0, 62, 2.0),
    (57.0, 69, 0.5), (57.75, 65, 0.75), (58.5, 62, 1.5),
    (60.0, 70, 1.0), (61.0, 69, 1.0), (62.0, 65, 1.0), (63.0, 64, 1.0),
]:
    intro_lead.append({"pitch": pitch, "start_time": start, "duration": dur, "velocity": 90})


# =====================================================================
# OUTRO (8 bars)
# =====================================================================
outro_drums = []
for b in range(8):
    bs = b * 4.0
    if b < 4:
        outro_drums.append({"pitch": 36, "start_time": bs + 0.0, "duration": 0.25, "velocity": max(95 - b*15, 50)})
        if b < 2 and b % 2 == 0:
            outro_drums.append({"pitch": 36, "start_time": bs + 2.75, "duration": 0.25, "velocity": 75})
    if b < 2:
        outro_drums.append({"pitch": 38, "start_time": bs + 1.0 + LAZY, "duration": 0.25, "velocity": 90 - b*15})
        outro_drums.append({"pitch": 38, "start_time": bs + 3.0 + LAZY, "duration": 0.25, "velocity": 95 - b*15})
    for t in [0.0, 1.0, 2.0, 3.0]:
        v = max(75 - b*8, 22)
        outro_drums.append({"pitch": 42, "start_time": bs + t, "duration": 0.1, "velocity": v})

outro_pad = []
outro_pad.append({"pitch": 53, "start_time": 0.0, "duration": 32.0, "velocity": 70})
outro_pad.append({"pitch": 57, "start_time": 0.0, "duration": 32.0, "velocity": 70})
outro_pad.append({"pitch": 62, "start_time": 0.0, "duration": 32.0, "velocity": 70})
stab(outro_pad, [53, 57, 62], 16.0, 80, 0.5)

outro_sub = [{"pitch": 26, "start_time": 0.0, "duration": 32.0, "velocity": 65}]

outro_lead = []
for start, pitch, dur in [
    (0.0, 69, 1.0), (1.0, 65, 0.5), (1.5, 62, 1.0), (3.0, 67, 1.0),
    (4.0, 65, 0.75), (5.0, 64, 0.75), (6.0, 62, 4.0),
    (12.0, 69, 0.5), (12.75, 65, 0.75), (13.5, 62, 6.0),
]:
    outro_lead.append({"pitch": pitch, "start_time": start, "duration": dur, "velocity": 75})


# =====================================================================
output = {
    "verse_drums": verse_drums, "verse_bass": verse_bass, "verse_sub": verse_sub, "verse_pad": verse_pad,
    "chorus_drums": chorus_drums, "chorus_bass": chorus_bass, "chorus_sub": chorus_sub,
    "chorus_bass_twist": chorus_bass_twist, "chorus_sub_twist": chorus_sub_twist,
    "chorus_pad": chorus_pad, "chorus_pad_twist": chorus_pad_twist,
    "chorus_pluck": chorus_pluck, "chorus_pluck_twist": chorus_pluck_twist,
    "chorus_bell": chorus_bell, "chorus_bell_twist": chorus_bell_twist,
    "c3prime_drums": c3prime_drums,
    "bridge_drums": bridge_drums, "bridge_bass": bridge_bass, "bridge_sub": bridge_sub, "bridge_ep": bridge_ep,
    "tag_drums": tag_drums, "tag_pad": tag_pad,
    "intro_drums": intro_drums, "intro_pad": intro_pad, "intro_sub": intro_sub,
    "intro_arp": intro_arp, "intro_bell": intro_bell, "intro_lead": intro_lead,
    "outro_drums": outro_drums, "outro_pad": outro_pad, "outro_sub": outro_sub, "outro_lead": outro_lead,
}

if len(sys.argv) > 1:
    print(json.dumps(output[sys.argv[1]], separators=(",", ":")))
else:
    for key, notes in output.items():
        print(f"{key}: {len(notes)} notes")
