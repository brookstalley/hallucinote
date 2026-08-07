"""Build The Angle of the Light into a SQLite DB using the hallucinote layer.

Doubt, transfigured, and then revealed as doubt again. The intro layers to D-F-Ab-C-Eb (half-diminished with a b9). The chorus re-roots those same five pitches on Ab -- Ab6/9#11, Lydian, radiant. Nothing changes but the bass, which moves by tritone. At the crescendo the bass slides back to D and the triumph is not destroyed but revealed: it was the doubt chord all along. We never escape doubt because we were never outside it.

The meter is 1/4 — one "bar" is one quarter-note beat, so the ruler counts
rather than claims. The FELT meter (4/4, 3/4, 5/8) lives in accent and note
placement, because Live's MCP has no `song_signature` automation target and a
within-song meter ratchet cannot reach it. The section table and the reasoning
are on the section-boundary constants below; do not duplicate them here.

This song lives in `examples/`, not `songs/` — it is the worked example the
repo's tour documents, and it is built by CI as an integration test. Marker
discovery finds `examples/hallucinote.toml` only when the start directory is
inside `examples/`, so run it from there:

    cd examples && python angle-of-the-light/build.py            # converger; re-run is a no-op
    cd examples && python angle-of-the-light/build.py --reset    # drop + rebuild
    cd examples && python angle-of-the-light/build.py --force-replay
        # consciously revert live edits pulled via /ableton-pull that are newer
        # than captured_session.json (replay otherwise refuses; the durable fix
        # is a re-capture via /song-snapshot — see StaleSnapshotError)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from hallucinote.authoring import arrange_section, run_build
from hallucinote.capture import replay_capture
from hallucinote.db import init_db, mutations as M, queries as Q, resolve_db_path
from hallucinote.melody import MelodyReport
from hallucinote.theory.model import Change, Chord, Progression, mode

# Per-branch DB filename (W12-A): branch switches pick up the right DB
# silently; outside a repo / detached HEAD falls back to angle-of-the-light.db.
DB_PATH = resolve_db_path("angle-of-the-light", root=Path(__file__).parent.parent)
SNAPSHOT_PATH = Path(__file__).parent / "captured_session.json"


# ---------------------------------------------------------------------------
# Section bar boundaries (1-based) — adjust as the song grows
# ---------------------------------------------------------------------------
# The meter is 1/4, so one "bar" is one quarter-note beat and these constants
# ARE the beat budget. Live's MCP has no `song_signature` automation target, so
# a within-song meter ratchet cannot reach Live at all (the mutator refuses it
# at start_bar > 1.0). A 1/4 ruler is the answer: it never contradicts the
# music, it just counts. The felt meter lives in accent and note placement.
#
#   section          felt meter              beats   bars      seconds @144
#   intro            4/4 x 6                    24   1 - 25           10.00
#   verse            (4/4 + 3/4) x 4            28   25 - 53          11.67
#   riser            4/4 x 2                     8   53 - 61           3.33
#   bridge           5/8 x 4  (2.5 beats ea)    10   61 - 71           4.17
#   chorus           4/4 x 4                    16   71 - 87           6.67
#   chorus-reprise   4/4 x 4                    16   87 - 103          6.67
#   outro            4/4 x 2                     8   103 - 111         3.33
#                                              ---                    -----
#                                              110                    45.83
#
# 45.83 s sits inside the brief's 45-60 s window. Three sections are longer
# than the brief specified (bridge 2->4 measures, outro 1->2, riser ~1->2);
# the brief's own structure totalled ~41 s, under its own floor, so the time
# was already there. See decisions/02-the-time-budget.md.
INTRO_BAR = 1
VERSE_BAR = 25
RISER_BAR = 53
BRIDGE_BAR = 61
CHORUS_BAR = 71
CHORUS_REPRISE_BAR = 87
OUTRO_BAR = 103
END_BAR = 111


# ---------------------------------------------------------------------------
# The harmonic spine
#
# THE ONE OBJECT. The whole song is transformations of a single five-pitch
# collection: {D, F, Ab, C, Eb}. Rooted on D it is a half-diminished chord with
# a flat ninth — a tritone (D-Ab) and a minor ninth (D-Eb) in one sonority,
# about as anxious as five notes get. Rooted on Ab, the SAME five pitches are
# Ab major 6 add #11: Lydian, radiant, the sound of a sunrise.
#
# Nothing is transposed between them. Only the bass moves, by a tritone. That
# is the answer to the brief's one unanswered word ("the ominous notes are
# suddenly major SOMEHOW"), and it is why the ending needs no new material: at
# the crescendo the bass slides back to D and the triumph is not destroyed but
# REVEALED as the chord it always was.
#
# `tests/` asserts the two chords are the same pitch-class set. That assertion
# is the song's thesis in executable form — if a later edit breaks it, the
# piece has stopped meaning what it means, and prose in a comment would not
# have noticed.
# ---------------------------------------------------------------------------
D, F, Ab, C, Eb, G, Bb, A, B = 2, 5, 8, 0, 3, 7, 10, 9, 11

#: Doubt. D-F-Ab-C-Eb read from D: root, m3, tritone, m7, b9.
DOUBT = Chord(root_pc=D, intervals=(0, 3, 6, 10, 13),
              label="i-halfdim-b9", symbol="Dm7b5(b9)")

#: Triumph. The SAME five pitches read from Ab: root, M3, 5, 6, #11-an-octave-up.
TRIUMPH = Chord(root_pc=Ab, intervals=(0, 4, 7, 9, 18),
                label="bV-lydian", symbol="Ab6/9(#11)")

#: The collapse. Doubt with C lowered to Cb — D fully diminished.
COLLAPSE = Chord(root_pc=D, intervals=(0, 3, 6, 9),
                 label="i-dim7", symbol="Ddim7")


# ---------------------------------------------------------------------------
# Note-authoring primitives
# ---------------------------------------------------------------------------

#: Beats per millisecond at 144 BPM. Microtiming is authored in ms because that
#: is the unit the feel is *heard* in; converting once here keeps every pattern
#: readable as "18 ms ahead" rather than as an opaque fraction of a beat.
MS = 144 / 60000.0

# General-MIDI-ish drum-rack map. Live's factory racks follow this layout.
KICK, RIM, SNARE, CLAP = 36, 37, 38, 39
TOM_LO, HAT, TOM_MID, HAT_OPEN = 45, 42, 47, 46
CRASH, TOM_HI, RIDE = 49, 50, 51

# Pitches used by name, so the harmony reads as music rather than as integers.
D1, Ab1, A1 = 26, 32, 33
Bb1, D2, Eb2, F2, G2, A2 = 34, 38, 39, 41, 43, 45
C3, D3, Eb3, F3, G3, Ab3, A3, Bb3, B3 = 48, 50, 51, 53, 55, 56, 57, 58, 59
C4, Db4, D4, Eb4, F4, Gb4, G4, Ab4, A4, Bb4, B4 = 60, 61, 62, 63, 65, 66, 67, 68, 69, 70, 71
C5, D5, Eb5, F5, Ab5, Bb5 = 72, 74, 75, 77, 80, 82
D6, F6, Eb6 = 86, 89, 87

#: The motif: up a minor third, down a major second. D-F-Eb.
#:
#: Eb is not decoration — it IS the b9 of the doubt chord, so the sigh lands on
#: the single most dissonant note in the collection. Over Ab in the chorus the
#: identical three pitches read #11 -> 6 -> 5, descending onto the fifth. The
#: motif is never transposed; only the ground under it moves.
MOTIF = (0, 3, 1)

#: Its inversion — down a minor third, up a major second, kept diatonic to D
#: Aeolian (D-Bb-C). The 3/4 answer contradicts the 4/4 call in contour as well
#: as in meter, instrumentation and feel.
MOTIF_INV = (0, -3, -2)


def note(pitch: int, start: float, dur: float, vel: int) -> dict:
    """One NoteDict. `start` is clamped at 0 — a push at beat 0 of a clip would
    otherwise go negative, which the mutator rejects outright."""
    return {"pitch": int(pitch), "start_beats": round(max(0.0, start), 5),
            "duration_beats": round(dur, 5), "velocity": int(vel)}


def push(beats: float, ms: float) -> float:
    """Move a note EARLIER by `ms` — ahead of the beat, the rushing feel.

    Positive `ms` pushes; negative drags. Kept as one function so the whole
    song's feel arc reads in one unit (see decisions/03-the-microtiming-arc).
    """
    return beats - ms * MS


def progression() -> Progression:
    """The song's harmonic timeline, in beats (the ruler is 1/4, so bar == beat).

    In-memory only — a `Progression` is never persisted (the melody lens reads it
    at build time for harmony-fit). Beats are 0-based; the section constants above
    are 1-based bars, hence the -1.
    """
    def at(bar: int) -> float:
        return float(bar - 1)

    changes: list[Change] = [
        # Intro — one chord, arrived at by layering one pitch per bar (see the
        # intro voicing plan in the compose half). Held so the arrival lands.
        Change(DOUBT, at(INTRO_BAR), at(VERSE_BAR) - at(INTRO_BAR)),
    ]

    # Verse — four cycles of (4/4 call + 3/4 response) = 7 beats each. Little
    # harmonic movement by the brief's instruction, but the Ebmaj7 in cycle 3 is
    # doing real work: it is the seed of the chorus's key, audible inside the
    # doubt long before the transfiguration. Cycle 4's A7 is the dominant that
    # the bridge then refuses to resolve.
    verse_cycle = [
        (Chord(root_pc=D, intervals=(0, 3, 7), label="i", symbol="Dm"),
         Chord(root_pc=D, intervals=(0, 3, 7), bass_pc=F, label="i6", symbol="Dm/F")),
        (Chord(root_pc=D, intervals=(0, 3, 7), label="i", symbol="Dm"),
         Chord(root_pc=Bb, intervals=(0, 4, 7, 11), label="VI7", symbol="Bbmaj7")),
        (Chord(root_pc=G, intervals=(0, 3, 7), label="iv", symbol="Gm"),
         Chord(root_pc=Eb, intervals=(0, 4, 7, 11), label="bII7", symbol="Ebmaj7")),
        (Chord(root_pc=A, intervals=(0, 4, 7, 10, 15), label="V7#9", symbol="A7#9"),
         Chord(root_pc=A, intervals=(0, 4, 7, 10, 13), label="V7b9", symbol="A7b9")),
    ]
    beat = at(VERSE_BAR)
    for call, response in verse_cycle:
        changes.append(Change(call, beat, 4.0))          # the 4/4 rock bar
        changes.append(Change(response, beat + 4.0, 3.0))  # the 3/4 waltz answer
        beat += 7.0

    # Riser — holds the unresolved A7b9. The tension is the point; the riser
    # promises a euphoric drop and delivers the bridge instead.
    changes.append(Change(verse_cycle[-1][1], at(RISER_BAR),
                          at(BRIDGE_BAR) - at(RISER_BAR)))

    # Bridge — four bars of 5/8 (2.5 beats each), the lament tetrachord D-C-Bb-A
    # descending. Mechanical, quantized, grim. Bar 4 lands on A, the dominant,
    # which by every expectation resolves to D minor. It does not.
    for i, root in enumerate((D, C, Bb, A)):
        changes.append(Change(
            Chord(root_pc=root, intervals=(0, 7), label="lament", symbol="power"),
            at(BRIDGE_BAR) + i * 2.5, 2.5))

    # Chorus — the transfiguration. A -> Ab is a semitone slip where a resolution
    # to D minor was owed: the surprise the brief asks for, and the same five
    # pitches the intro spent six bars assembling.
    changes.append(Change(TRIUMPH, at(CHORUS_BAR), 8.0))
    changes.append(Change(
        Chord(root_pc=Bb, intervals=(0, 4, 7), bass_pc=Ab, label="II/bVII", symbol="Bb/Ab"),
        at(CHORUS_BAR) + 8.0, 4.0))
    changes.append(Change(
        Chord(root_pc=Eb, intervals=(0, 5, 7), label="V-sus", symbol="Ebsus4"),
        at(CHORUS_BAR) + 12.0, 4.0))

    # Chorus reprise — doubling down, with the verse's material pulled into the
    # major world. Ebmaj7 was cycle 3's chord; here it is the dominant. The seed
    # was always there.
    changes.append(Change(TRIUMPH, at(CHORUS_REPRISE_BAR), 4.0))
    changes.append(Change(
        Chord(root_pc=Eb, intervals=(0, 4, 7, 11), label="V7", symbol="Ebmaj7"),
        at(CHORUS_REPRISE_BAR) + 4.0, 4.0))
    changes.append(Change(
        Chord(root_pc=Bb, intervals=(0, 3, 7, 10), label="ii7", symbol="Bbm7"),
        at(CHORUS_REPRISE_BAR) + 8.0, 4.0))
    changes.append(Change(
        Chord(root_pc=Eb, intervals=(0, 4, 7, 10, 15), label="V7#9", symbol="Eb7#9"),
        at(CHORUS_REPRISE_BAR) + 12.0, 4.0))

    # Outro — bar 1: the bass slides Ab -> D under an unchanged chord. Bar 2:
    # C drops to Cb and the whole thing bends down an octave.
    changes.append(Change(
        Chord(root_pc=D, intervals=(0, 3, 6, 10, 13), label="reveal", symbol="Dm7b5(b9)"),
        at(OUTRO_BAR), 4.0))
    changes.append(Change(COLLAPSE, at(OUTRO_BAR) + 4.0, 4.0))

    return Progression(key_pc=D, mode=mode("Aeolian"), changes=tuple(changes))


# ---------------------------------------------------------------------------
# Section composers
#
# One function per section, each returning {track_name: clip_id}. Sections are
# composed independently because that is how the song is *heard* — as eight
# worlds in forty-six seconds — and keeping them separate means a change to the
# bridge cannot silently perturb the verse.
# ---------------------------------------------------------------------------


def _clip(conn, tracks, track, name, length, slot, notes):
    """Create one clip and fill it. Returns the clip_id."""
    cid = M.create_clip(conn, track_id=tracks[track], slot=slot,
                        length_beats=float(length), name=name)
    M.replace_clip_notes(conn, clip_id=cid, notes=notes)
    return cid


def _intro(conn, tracks, length):
    """Six bars, one new pitch per bar, arriving at D-F-Ab-C-Eb.

    The layering is the tension: each entry is consonant with what preceded it
    until Eb and Ab arrive and retroactively make the whole stack a
    half-diminished b9. Nothing 'goes wrong' — the meaning of the earlier notes
    changes, which is the song's whole method stated once, quietly, up front.
    """
    slot = 1
    pad = []
    for i, p in enumerate((D3, A3, F3, C4, Eb4, Ab4)):
        onset = i * 4.0
        pad.append(note(p, onset, length - onset, 44 + i * 6))
    return {
        "Sub": _clip(conn, tracks, "Sub", "intro drone", length, slot,
                     [note(D1, 0, length, 60)]),
        "Pad": _clip(conn, tracks, "Pad", "intro layers", length, slot, pad),
        # Deliberately off any grid — the intro is the one section with no pulse
        # to be early or late against, so the bells are placed by hand.
        "Bells": _clip(conn, tracks, "Bells", "intro motif", length, slot, [
            note(D5, 2.3, 1.6, 76), note(F5, 7.1, 1.5, 69),
            note(Eb5, 12.6, 1.9, 73), note(D6, 18.4, 1.1, 57),
            note(Ab5, 22.15, 1.85, 84),
        ]),
    }


#: Per verse cycle: (call bass, response bass, response brass voicing, push ms).
#: Little harmonic movement by the brief's instruction — but Ebmaj7 in cycle 3
#: is the chorus's dominant, planted inside the doubt long before it means
#: anything, and cycle 4's A7 is the dominant the bridge then refuses to resolve.
_VERSE_CYCLES = (
    (D2, F2,  (F3, A3, D4),        10),
    (D2, Bb1, (Bb3, D4, F4, A4),   17),
    (G2, Eb2, (Eb4, G3, Bb3, D5),  24),
    (A2, A2,  (A3, Db4, G4, Bb4),  30),
)
_VERSE_KEYS = ((D4, F4, A4), (D4, F4, A4), (G3, Bb3, D4), (A3, Db4, G4, C5))


def _verse(conn, tracks, length):
    """Four cycles of 7 beats: a 4/4 rock bar CALLS, a 3/4 bar ANSWERS.

    The answer is a different ensemble in a different meter with a different
    feel — orchestral brass and percussion, irritated, playing a rock 3/4 rather
    than a polite waltz. And it rushes HARDER than the rock does (+8 ms on top
    of the cycle's push), which is what makes a genre that should be poised
    sound like it is losing its temper.
    """
    slot = 2
    kit, bass, keys, perc, brass = [], [], [], [], []
    for i, (call_bass, resp_bass, resp_voicing, ms) in enumerate(_VERSE_CYCLES):
        c = i * 7.0
        wms = ms + 8  # the waltz out-pushes the rock

        # --- the 4/4 call: pushing rock and roll -------------------------
        kit.append(note(KICK, push(c + 0.0, ms), 0.5, 118))
        kit.append(note(KICK, push(c + 2.5, ms), 0.5, 104))
        kit.append(note(SNARE, push(c + 1.0, ms), 0.5, 112))
        kit.append(note(SNARE, push(c + 3.0, ms), 0.5, 116))
        for h in range(8):
            kit.append(note(HAT, push(c + h * 0.5, ms), 0.25,
                            96 if h % 2 == 0 else 74))
        if i == 0:
            kit.append(note(CRASH, push(c, ms), 2.0, 120))
        bass.append(note(call_bass, push(c + 0.0, ms), 2.25, 110))
        bass.append(note(call_bass + 12, push(c + 2.5, ms), 1.25, 96))
        for p in _VERSE_KEYS[i]:
            keys.append(note(p, push(c + 0.75, ms), 0.4, 92))
            keys.append(note(p, push(c + 2.25, ms), 0.35, 80))

        # --- the 3/4 answer: the orchestra, annoyed ----------------------
        perc.append(note(TOM_LO, push(c + 4.0, wms), 0.6, 122))
        perc.append(note(SNARE, push(c + 5.0, wms), 0.4, 104))
        perc.append(note(SNARE, push(c + 6.0, wms), 0.4, 110))
        if i == 3:  # the fill that hands over to the riser
            for k, p in enumerate((TOM_HI, TOM_MID, TOM_LO)):
                perc.append(note(p, push(c + 6.25 + k * 0.25, wms), 0.25, 100 + k * 8))
        else:
            perc.append(note(HAT_OPEN, push(c + 6.5, wms), 0.3, 84))
        bass.append(note(resp_bass, push(c + 4.0, wms), 2.6, 104))
        for p in resp_voicing:
            brass.append(note(p, push(c + 4.0, wms), 0.85, 121))       # sforzando
            brass.append(note(p + 12, push(c + 6.0, wms), 0.75, 108))  # the flourish
    return {
        "Kit Rock": _clip(conn, tracks, "Kit Rock", "verse rock", length, slot, kit),
        "Bass": _clip(conn, tracks, "Bass", "verse bass", length, slot, bass),
        "Keys": _clip(conn, tracks, "Keys", "verse stabs", length, slot, keys),
        "Perc": _clip(conn, tracks, "Perc", "verse orch perc", length, slot, perc),
        "Brass Stab": _clip(conn, tracks, "Brass Stab", "verse answer", length,
                            slot, brass),
    }


def _riser(conn, tracks, length):
    """Two bars that promise a euphoric drop and deliver the machine.

    The lie is the point (see the brief's 'anything could happen, and it does').
    Everything here accelerates and rises; what follows is rigid and descends.
    """
    slot = 3
    fx = []
    for k in range(32):                       # a chromatic climb in 32nds
        t = k * (length / 32.0)
        fx.append(note(D4 + k // 2, t, length / 32.0, 40 + k * 2))
    roll, t, step = [], 0.0, 0.5
    while t < length:                          # a snare roll that tightens
        roll.append(note(SNARE, t, step, min(127, 58 + int(t * 9))))
        t += step
        step = max(0.125, step * 0.86)
    return {
        "FX": _clip(conn, tracks, "FX", "riser", length, slot, fx),
        "Kit Rock": _clip(conn, tracks, "Kit Rock", "riser roll", length, slot, roll),
        "Sub": _clip(conn, tracks, "Sub", "riser dominant", length, slot,
                     [note(A1, 0, length, 78)]),
    }


def _bridge(conn, tracks, length):
    """Four bars of 5/8, grouped 3+2, descending D-C-Bb-A. EXACTLY quantized.

    Every other section in this song has a human hand in its timing. This one
    has none, and the absence is the grimness — more than the descending
    harmony or the bit-crushed production, both of which are decoration on the
    same idea. It only reads as absence because there is an arc to be absent from.
    """
    slot = 4
    machine, lead, bass = [], [], []
    for i, root in enumerate((D4, C4, Bb3, A3)):
        b = i * 2.5                                    # 5/8 == 2.5 quarter notes
        machine.append(note(KICK, b, 0.4, 116))        # no push. none anywhere.
        machine.append(note(SNARE, b + 1.5, 0.4, 112))  # the 3+2 seam
        for h in range(5):
            machine.append(note(HAT, b + h * 0.5, 0.2, 88))
        # The motif, mechanised: equal eighths, no phrasing, repeating to fill.
        for k, iv in enumerate(MOTIF + MOTIF[:2]):
            lead.append(note(root + iv, b + k * 0.5, 0.45, 100))
        bass.append(note(root - 24, b, 2.5, 108))
    return {
        "Machine": _clip(conn, tracks, "Machine", "bridge machine", length, slot,
                         machine),
        "Lead": _clip(conn, tracks, "Lead", "bridge lead", length, slot, lead),
        "Bass": _clip(conn, tracks, "Bass", "bridge bass", length, slot, bass),
    }


#: The transfiguration voicing — the intro's five pitches, re-rooted on Ab.
_TRIUMPH_VOICING = (Ab3, C4, Eb4, F4, D5)


def _chorus(conn, tracks, length):
    """The sun rises, and not one pitch has changed.

    A -> Ab is a semitone slip where a resolution to D minor was owed. The
    listener hears a surprise; what actually happened is that the ground moved
    a tritone and left the chord alone.
    """
    slot = 5
    sustain = [note(p, 0, 8, 104) for p in _TRIUMPH_VOICING]
    sustain += [note(p, 8, 4, 98) for p in (Bb3, D4, F4)]
    sustain += [note(p, 12, 4, 100) for p in (Eb4, Ab4, Bb4)]
    stab, perc = [], []
    for bar in range(4):
        b = bar * 4.0
        for off, vel in ((0.0, 122), (1.5, 96), (2.0, 108), (3.5, 92)):
            stab.append(note(_TRIUMPH_VOICING[bar % len(_TRIUMPH_VOICING)] + 12,
                             push(b + off, 5), 0.4, vel))
        perc.append(note(TOM_LO, push(b + 0.0, 5), 0.5, 120))
        perc.append(note(TOM_LO, push(b + 2.0, 5), 0.5, 106))
        for k in range(4):
            perc.append(note(SNARE, push(b + k, 5), 0.3, 100 if k == 0 else 84))
        if bar == 3:
            perc.append(note(CRASH, push(b + 3.0, 5), 1.0, 118))
    return {
        "Brass Sustain": _clip(conn, tracks, "Brass Sustain", "chorus radiance",
                               length, slot, sustain),
        "Brass Stab": _clip(conn, tracks, "Brass Stab", "chorus fanfare", length,
                            slot, stab),
        "Perc": _clip(conn, tracks, "Perc", "chorus march", length, slot, perc),
        "Sub": _clip(conn, tracks, "Sub", "chorus sub", length, slot, [
            note(Ab1, 0, 12, 96), note(Eb2, 12, 4, 90)]),
        "Pad": _clip(conn, tracks, "Pad", "chorus pad", length, slot,
                     [note(p + 12, 0, length, 62) for p in _TRIUMPH_VOICING]),
        "Bells": _clip(conn, tracks, "Bells", "chorus motif", length, slot, [
            note(D6, 0.0, 1.4, 92), note(F6, 2.0, 1.2, 84),
            note(Eb6, 5.0, 2.0, 88)]),
    }


def _reprise(conn, tracks, length):
    """Doubling down — and the rock band rejoins the orchestra.

    The verse's kit and push return inside the major world, and the brass groups
    in threes across 4/4 (a 3-against-4 hemiola) so the waltz is present as a
    rhythmic ghost without a meter change. Ebmaj7 was cycle 3 of the verse; here
    it is the dominant. The seed was always in the doubt.
    """
    slot = 6
    sustain = [note(p, 0, 4, 104) for p in _TRIUMPH_VOICING]
    sustain += [note(p, 4, 4, 100) for p in (Eb4, G3, Bb3, D5)]      # Ebmaj7
    sustain += [note(p, 8, 4, 98) for p in (Bb3, Db4, F4, Ab4)]      # Bbm7
    sustain += [note(p, 12, 4, 108) for p in (Eb4, G3, Db4, Gb4)]    # Eb7#9
    stab, kit, perc = [], [], []
    t = 0.0
    while t < 12.0:                       # hemiola: the waltz, without the meter
        stab.append(note(D5, push(t, 8), 0.4, 112))
        stab.append(note(Ab5, push(t, 8), 0.4, 96))
        t += 1.5
    for bar in range(4):
        b = bar * 4.0
        kit.append(note(KICK, push(b + 0.0, 22), 0.5, 118))
        kit.append(note(KICK, push(b + 2.5, 22), 0.5, 102))
        kit.append(note(SNARE, push(b + 1.0, 22), 0.5, 114))
        kit.append(note(SNARE, push(b + 3.0, 22), 0.5, 118))
        for h in range(8):
            kit.append(note(HAT, push(b + h * 0.5, 22), 0.25,
                            94 if h % 2 == 0 else 72))
        perc.append(note(TOM_LO, push(b, 5), 0.5, 118))
        for k in range(4):
            perc.append(note(SNARE, push(b + k, 5), 0.3, 96 if k == 0 else 80))
    return {
        "Brass Sustain": _clip(conn, tracks, "Brass Sustain", "reprise", length,
                               slot, sustain),
        "Brass Stab": _clip(conn, tracks, "Brass Stab", "reprise hemiola", length,
                            slot, stab),
        "Kit Rock": _clip(conn, tracks, "Kit Rock", "reprise rock", length, slot, kit),
        "Perc": _clip(conn, tracks, "Perc", "reprise march", length, slot, perc),
        "Sub": _clip(conn, tracks, "Sub", "reprise sub", length, slot, [
            note(Ab1, 0, 4, 96), note(Eb2, 4, 4, 92),
            note(Bb1, 8, 4, 94), note(Eb2, 12, 4, 100)]),
        "Bass": _clip(conn, tracks, "Bass", "reprise bass", length, slot, [
            note(Ab1 + 12, push(0, 22), 3.5, 100),
            note(Eb2 + 12, push(4, 22), 3.5, 98),
            note(Bb1 + 12, push(8, 22), 3.5, 96),
            note(Eb2 + 12, push(12, 22), 3.5, 104)]),
    }


def _outro(conn, tracks, length):
    """The reveal, then the collapse.

    Bar 1: the brass holds the chorus voicing UNCHANGED while the bass slides
    Ab -> D. Nothing is transposed; the triumph is not destroyed, it is
    identified. Bar 2: C drops to Cb and the chord is D fully diminished.

    The octave drop that follows is NOT authored here as notes — clip_pitch_bend
    cannot be pushed to Live (no auto-encode path; see the mix pass), so it rides
    a Shifter device-parameter envelope instead. That envelope is authored in
    :func:`_author_octave_drop`, which runs after the sections are laid out
    because it has to look the Shifter up by class on the master strip.
    """
    slot = 7
    return {
        # The same five pitches the chorus was radiant on, held straight through
        # the bass move. If this voicing ever changes, the song stops arguing.
        "Brass Sustain": _clip(conn, tracks, "Brass Sustain", "outro reveal",
                               length, slot,
                               [note(p, 0, 4, 100) for p in _TRIUMPH_VOICING]
                               + [note(p, 4, 4, 92)
                                  for p in (D4, F4, Ab4, B3 + 12)]),
        "Sub": _clip(conn, tracks, "Sub", "outro slide", length, slot, [
            note(Ab1, 0, 1.0, 96), note(D1, 1.0, 3.0, 104),
            note(D1, 4.0, 4.0, 88)]),
        "Pad": _clip(conn, tracks, "Pad", "outro pad", length, slot,
                     [note(p + 12, 0, 4, 58) for p in _TRIUMPH_VOICING]
                     + [note(p + 12, 4, 4, 54) for p in (D4, F4, Ab4, B3 + 12)]),
        "Perc": _clip(conn, tracks, "Perc", "outro impact", length, slot, [
            note(CRASH, 0, 3.0, 120), note(TOM_LO, 0, 1.5, 116),
            note(CRASH, 4, 4.0, 104)]),
    }


#: The outro's octave drop — the brief's closing gesture, and the only moment in
#: the piece that cannot be written as notes.
#:
#: The brief asks that "everything pitch bends down a whole octave while it fades
#: out over one 4/4 measure". *Everything* is the operative word: this is not a
#: part bending, it is the whole record being dragged under, so it belongs on the
#: master strip rather than on any instrument. A Shifter in Pitch mode sits ahead
#: of the master Limiter (chain order matters — pitching down AFTER limiting
#: would re-introduce the peaks the ceiling just removed), and its `Pitch Coarse`
#: parameter is automated in raw semitones from 0 to -12.
#:
#: The meter here is a global 1/4 ruler that counts rather than claims (see the
#: time-signature note above), so one bar is one beat and the outro's two
#: notional 4/4 measures are beats 102-106 and 106-110. The drop rides the
#: SECOND measure only: bar 1 is the reveal (the bass slides Ab -> D under an
#: unchanged voicing) and it has to be heard at pitch to land, because the whole
#: argument is that the triumph was the doubt chord all along. Only once that is
#: audible does the floor go.
OCTAVE_DROP_HOLD_BEAT = float(OUTRO_BAR - 1)          # outro starts, still at pitch
OCTAVE_DROP_START_BEAT = float(OUTRO_BAR - 1) + 4.0   # the reveal has landed
OCTAVE_DROP_END_BEAT = float(END_BAR - 1)             # an octave down
OCTAVE_DROP_SEMITONES = -12.0


def _author_octave_drop(conn, song_id, tracks):
    """Automate the master Shifter down an octave across the outro's last bar.

    Looked up by CLASS on the master strip rather than by a hard-coded index:
    the device chain is materialized from `captured_session.json`, so its
    position is snapshot state this file does not own. Raising when it is absent
    is deliberate — a silently-missing Shifter is exactly how this gesture went
    unbuilt once already, documented in prose while no envelope existed.
    """
    master_id = tracks["Master"]
    shifter = next(
        (d for d in Q.get_devices_for_track(conn, master_id)
         if d["class_name"] == "Shifter"),
        None,
    )
    if shifter is None:
        raise RuntimeError(
            "no Shifter on the master strip — the outro's octave drop has "
            "nothing to ride. It lives in captured_session.json under "
            "song.master.devices, ahead of the Limiter; re-capture the set "
            "with `hallucinote capture execute` if it has been lost."
        )
    # build.py is a state CONVERGER: re-running it with no source change must
    # produce no net state change. `create_envelope` inserts unconditionally, so
    # reuse an existing arc when there is one and rewrite its points — otherwise
    # every rebuild stacks another envelope on the same parameter.
    existing = [
        e for e in Q.get_envelopes_for_device(conn, shifter["id"])
        if e["parameter_path"] == "Pitch Coarse"
    ]
    want = [
        {"time_beats": OCTAVE_DROP_HOLD_BEAT, "value": 0.0,
         "curve_kind": "linear"},
        {"time_beats": OCTAVE_DROP_START_BEAT, "value": 0.0,
         "curve_kind": "linear"},
        {"time_beats": OCTAVE_DROP_END_BEAT, "value": OCTAVE_DROP_SEMITONES,
         "curve_kind": "linear"},
    ]
    # Reuse an existing arc rather than stacking a second one: `create_envelope`
    # inserts unconditionally. `replace_breakpoints` is a true converger — it
    # emits nothing when the points are already identical — so it is safe to
    # call every build, and calling it is also what marks the envelope as
    # TOUCHED. That matters: `build_session` is mark-and-sweep, and a row the
    # build never touches is deleted as orphaned build content. Returning early
    # on "nothing changed" therefore deletes the very envelope it was trying to
    # preserve.
    if existing:
        envelope_id = existing[0]["id"]
    else:
        envelope_id = M.create_envelope(
            conn, song_id=song_id,
            target_kind="device_parameter",
            target_device_id=shifter["id"],
            parameter_path="Pitch Coarse",
            actor="build",
            reason="outro octave drop — the brief's closing gesture",
        )
    M.replace_breakpoints(
        conn, envelope_id=envelope_id,
        breakpoints=want,
        actor="build",
        reason="outro octave drop — the brief's closing gesture",
    )
    return envelope_id


SECTION_SPANS = (
    ("intro", INTRO_BAR, VERSE_BAR),
    ("verse", VERSE_BAR, RISER_BAR),
    ("riser", RISER_BAR, BRIDGE_BAR),
    ("bridge", BRIDGE_BAR, CHORUS_BAR),
    ("chorus", CHORUS_BAR, CHORUS_REPRISE_BAR),
    ("chorus-reprise", CHORUS_REPRISE_BAR, OUTRO_BAR),
    ("outro", OUTRO_BAR, END_BAR),
)

SECTION_COMPOSERS = {
    "intro": _intro,
    "verse": _verse,
    "riser": _riser,
    "bridge": _bridge,
    "chorus": _chorus,
    "chorus-reprise": _reprise,
    "outro": _outro,
}


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------


def build(reset: bool = False, force_replay: bool = False) -> str:
    """Build the song. Returns the song_id (UUID hex).

    State-converger (W12-A): re-running with no source change is a no-op (zero net
    events). `--reset` is a soft reset (W18-C) — wipes build.py-authored content
    (clips, notes, arrangement, sections, tempo/meter maps, cue points, envelopes)
    but preserves the mix layout (tracks, returns, devices, sends) AND the Ableton
    projection (`ableton_sessions` + `ableton_links`); delete the DB file for a full
    clean slate. The lifecycle (open DB → optional reset → build_session → close)
    lives in `hallucinote.authoring.run_build`; this function holds only the
    composition (the `compose` closure below).
    """
    def compose(conn):
        # Mix-half: replay the captured (or synthetic) Ableton session.
        snapshot = json.loads(SNAPSHOT_PATH.read_text())
        song_id = replay_capture(
            conn, snapshot,
            song_name="angle-of-the-light",
            song_title="The Angle of the Light",
            song_key='Dm',
            actor="sync", reason="initial capture replay",
            # BAK-7D2V: replay refuses (StaleSnapshotError) when the DB holds
            # /ableton-pull edits newer than the snapshot; --force-replay is
            # the conscious revert, /song-snapshot the durable fix.
            allow_stale_snapshot=force_replay,
        )

        # Score-half: tempo, meter, sections, cue points.
        M.set_song_timing_mode(conn, song_id=song_id, timing_mode="native")
        M.add_tempo_point(
            conn, song_id=song_id, start_bar=1.0, tempo_bpm=144.0,
        )
        M.add_time_signature_point(
            conn, song_id=song_id, start_bar=1.0,
            numerator=1, denominator=4,
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
            end_bar=float(RISER_BAR),
        )
        M.create_section(
            conn, song_id=song_id, name='riser',
            start_bar=float(RISER_BAR),
            end_bar=float(BRIDGE_BAR),
        )
        M.create_section(
            conn, song_id=song_id, name='bridge',
            start_bar=float(BRIDGE_BAR),
            end_bar=float(CHORUS_BAR),
        )
        M.create_section(
            conn, song_id=song_id, name='chorus',
            start_bar=float(CHORUS_BAR),
            end_bar=float(CHORUS_REPRISE_BAR),
        )
        M.create_section(
            conn, song_id=song_id, name='chorus-reprise',
            start_bar=float(CHORUS_REPRISE_BAR),
            end_bar=float(OUTRO_BAR),
        )
        M.create_section(
            conn, song_id=song_id, name='outro',
            start_bar=float(OUTRO_BAR),
            end_bar=float(END_BAR),
        )

        # Cue points at every section boundary.
        for bar, name in [(INTRO_BAR, 'intro'), (VERSE_BAR, 'verse'), (RISER_BAR, 'riser'), (BRIDGE_BAR, 'bridge'), (CHORUS_BAR, 'chorus'), (CHORUS_REPRISE_BAR, 'chorus-reprise'), (OUTRO_BAR, 'outro')]:
            M.add_cue_point(
                conn, song_id=song_id,
                position_bar=float(bar), name=name,
            )

        tracks = Q.tracks_by_name(conn, song_id)

        # === Compose-half ===
        #
        # Hand-authored throughout rather than generator-driven. The meter is
        # the content here — 4/4 alternating with 3/4, then 5/8 — and the
        # generators lay out within a 4/4 bar shape, so every pattern that
        # matters would have needed hand-authoring anyway. Notes are just
        # NoteDict lists (docs/song-authoring-conventions.md, "The toolkit
        # reduces work — it never limits what you can author").
        for section_name, start, end in SECTION_SPANS:
            clips = SECTION_COMPOSERS[section_name](conn, tracks, end - start)
            arrange_section(conn, song_id, tracks, clips,
                            start_bar=float(start), end_bar=float(end))

        # The one gesture that isn't notes. Runs last because it resolves the
        # Shifter off the master chain the snapshot replayed above.
        _author_octave_drop(conn, song_id, tracks)

        return song_id

    return run_build(DB_PATH, "angle-of-the-light", compose, reset=reset)


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


def melody_report() -> MelodyReport:
    """The melody-lens convention `hallucinote.tools.melody_lens` + `/compose-review` call to
    read this song's line-level melodic facts (contour, intervals, harmony-fit).

    Build the in-memory arrangement (or `SectionMelody` inputs) for this song's
    monophonic melodic line(s) and run the lens. Full harmony-fit needs the
    in-memory `Progression` (NOT persisted to the DB) — so this runs build-time over
    the arrangement, not over a DB read. See melody-model.md §7 *Read-side surface*
    and songs/sun-zone-done/build.py for the worked pattern:

        from hallucinote.melody import analyze_arrangement
        arr = _build_arrangement(...)          # your in-memory Arrangement
        return analyze_arrangement(
            arr, song_slug="angle-of-the-light", melody_layers=("Lead",))

    To GRADE a line against what it is *trying to be* (profile-relative, still a
    coaching question — never a verdict), declare a `MelodicProfile` per line and
    pass it as `profiles={layer_name: profile}`. The declaration IS the learn-back
    (melody-model.md §4): once declared, a deliberate genre choice never re-flags.

        from hallucinote.melody import MelodicProfile, analyze_arrangement
        return analyze_arrangement(
            arr, song_slug="angle-of-the-light", melody_layers=("Lead",),
            profiles={
                "Lead": MelodicProfile(
                    name="singable-hook",      # a reusable declared-intent label
                    contour_intent="arch",     # arch/ascending/descending/valley/level/free
                    step_appetite="high",      # low | moderate | high (proximity vs leap)
                    harmonic_freedom="low",    # low (chord-tone-locked) .. high (chromatic)
                    repetition_appetite="high",# low (through-composed) .. high (cell hook)
                ),
            })

    Per-SECTION path (when you don't have, or don't want, a full `Arrangement` —
    a single section, a subset of lines, or a synthetic read): call `analyze_melody`
    over `SectionMelody` inputs directly. `analyze_arrangement` is sugar over this
    (it calls `arr.section_melody_inputs()` for you); reach for `analyze_melody`
    when you're constructing sections by hand. Same `profiles=` grading applies.

        from hallucinote.melody import analyze_melody, SectionMelody
        return analyze_melody(
            [SectionMelody(name="Chorus", length_beats=32.0,
                           layers={"Lead": chorus_lead_notes})],
            song_slug="angle-of-the-light")

    Until this song has a composed melodic line wired here, it returns an empty
    report (the CLI then shows "0 lines" rather than failing).
    """
    # TODO: wire to this song's melodic line(s) — see the docstring above.
    return MelodyReport(song_slug="angle-of-the-light", sections=(), findings=())


if __name__ == "__main__":
    reset = "--reset" in sys.argv
    force_replay = "--force-replay" in sys.argv
    song_id = build(reset=reset, force_replay=force_replay)
    report(song_id)
