"""Bass pattern generators.

Meter (W14-B). The bar iteration here uses ``beats_per_bar`` (default 4.0)
so bar starts step correctly through non-4/4 sections. The within-bar
layout is 4/4-shaped (tresillo cell over 4 beats; walking-bass beats at
[0.0, 1.5, 2.0, 3.5]) and does NOT scale with ``beats_per_bar``. For
non-4/4 sections where the within-bar shape matters, author by hand.
"""
from __future__ import annotations

from typing import Any

from hallucinote.generators.primitives import TRESILLO_HITS, Feel, apply_feel
from hallucinote.theory.model import Progression

NoteDict = dict[str, Any]


def _note(pitch: int, start: float, dur: float, vel: int, tags: list[str]) -> NoteDict:
    return {
        "pitch": pitch,
        "start_beats": start,
        "duration_beats": dur,
        "velocity": vel,
        "tags": tags,
    }


def _bass_root(chords: Progression, local_beat: float, register: int) -> int:
    """The bass MIDI pitch at ``local_beat``: the chord's SLASH bass if present
    (so ``Em/C#`` puts C# in the bass — the Dorian/Phrygian pivot becomes audible
    automatically), else the chord root, voiced in ``register``
    (MIDI = 12*(register+1)+pc, so register 2 -> E2 = 40)."""
    ch = chords.chord_at(local_beat)
    pc = ch.bass_pc if ch.bass_pc is not None else ch.root_pc
    return 12 * (register + 1) + pc


def tresillo_bass(
    root_pitch: int,
    *,
    bars: int = 1,
    start_beat: float = 0.0,
    beats_per_bar: float = 4.0,
    note_duration: float = 0.5,
    feel: Feel = None,
) -> list[NoteDict]:
    """Plain tresillo on the chord root. Tagged "bass" + "tresillo_hit".
    4/4-shaped within a bar (see module docstring); ``beats_per_bar``
    only scales the inter-bar step. ``feel`` (W17-E) shifts tresillo
    positions {0.0, 0.75, 1.5, 2.0, 2.75, 3.5}.
    """
    out: list[NoteDict] = []
    for b in range(bars):
        bs = start_beat + b * beats_per_bar
        for t, v in TRESILLO_HITS:
            out.append(_note(root_pitch, bs + apply_feel(t, feel), note_duration, v,
                             ["bass", "tresillo_hit"]))
    return out


def walking_bass_to_next_chord(
    *,
    walk: list[int],
    start_beat: float,
    bar_count: int = 1,
    beats_per_bar: float = 4.0,
    accent_velocity: int = 100,
    walk_velocity: int = 88,
    note_duration: float = 1.0,
    feel: Feel = None,
) -> list[NoteDict]:
    """Walk through `walk` pitches across `bar_count` bars at beats [0, 1.5, 2, 3.5].

    Convention: walk[0] = chord root, walk[1:] = passing tones leading to next chord.
    Tagged "bass" + "walk" with first note also "downbeat". 4/4-shaped
    within a bar (see module docstring); ``beats_per_bar`` only scales
    the inter-bar step. ``feel`` (W17-E) shifts the walking positions
    {0.0, 1.5, 2.0, 3.5}.
    """
    out: list[NoteDict] = []
    for bar in range(bar_count):
        bs = start_beat + bar * beats_per_bar
        for i, beat in enumerate([0.0, 1.5, 2.0, 3.5]):
            p = walk[i % len(walk)]
            tags = ["bass", "walk"]
            if i == 0:
                tags.append("downbeat")
                vel = accent_velocity
            else:
                vel = walk_velocity
            out.append(_note(p, bs + apply_feel(beat, feel), note_duration, vel, tags))
    return out


def reggae_offbeat_bass(
    chords: Progression,
    *,
    bars: int = 1,
    register: int = 2,
    fifth_offset: int = 7,
    octave_offset: int = 12,
    start_beat: float = 0.0,
    beats_per_bar: float = 4.0,
    root_velocity: int = 80,
    octave_velocity: int = 82,
    fifth_down_velocity: int = 72,
    fifth_up_velocity: int = 70,
    push: float = 0.02,
    feel: Feel = None,
) -> list[NoteDict]:
    """Reggae bass: root on 1, fifth on the "and" of 2, octave on 3, fifth on
    the "and" of 4 — the long-short rocking motion that walks the off-beats.

    Chord-aware (the harmony substrate): the bass is reggae's harmonic AGENT, so
    it reads the chord at each step and roots its rocking figure on that chord's
    SLASH bass (or root) — an authored ``Em7→A7`` now walks instead of pedalling
    E, and an ``Em/C#``→``Em/C`` hinge puts the pivot semitone in the bass
    automatically. ``register`` 2 reproduces the old E2 root. Roots/octaves are
    long (1.4 beats), the off-beat fifths short (0.4) — the bounce. Everything
    sits ``push`` beats behind the click. 4/4-shaped within a bar (see module
    docstring); ``beats_per_bar`` only scales the inter-bar step. ``feel``
    (W17-E) shifts {0.0, 1.5, 2.0, 3.5} on top of ``push``. Tagged "bass"+"reggae".
    """
    out: list[NoteDict] = []
    for b in range(bars):
        bs = start_beat + b * beats_per_bar
        bb = b * beats_per_bar  # section-relative bar start, for the chord lookup
        root = _bass_root(chords, bb + 0.0, register)
        out.append(_note(root, bs + apply_feel(0.0, feel) + push, 1.4, root_velocity,
                         ["bass", "reggae", "root"]))
        out.append(_note(_bass_root(chords, bb + 1.5, register) + fifth_offset,
                         bs + apply_feel(1.5, feel) + push, 0.4, fifth_down_velocity,
                         ["bass", "reggae", "offbeat"]))
        out.append(_note(_bass_root(chords, bb + 2.0, register) + octave_offset,
                         bs + apply_feel(2.0, feel) + push, 1.4, octave_velocity,
                         ["bass", "reggae", "octave"]))
        out.append(_note(_bass_root(chords, bb + 3.5, register) + fifth_offset,
                         bs + apply_feel(3.5, feel) + push, 0.4, fifth_up_velocity,
                         ["bass", "reggae", "offbeat"]))
    return out


def metal_pedal_16ths(
    chords: Progression,
    *,
    bars: int = 1,
    register: int = 2,
    start_beat: float = 0.0,
    beats_per_bar: float = 4.0,
    velocity: int = 105,
    note_duration: float = 0.18,
    push: float = -0.01,
    feel: Feel = None,
) -> list[NoteDict]:
    """Metal palm-mute root pedaling: the chord root machine-gunned on straight
    16ths, the foundation under the gallop guitar.

    Chord-aware: each 16th pedals the chord SOUNDING at that 16th (slash bass or
    root), so a moving Phrygian riff (E pedal → ♭II F → …) pedals the riff
    instead of a frozen E. ``register`` 2 reproduces the old E2 pedal. Every 16th
    gets a slight ``push`` (ahead of the click) for aggression — EXCEPT any note
    whose absolute onset would land at or before 0.0 (Live's MIDI clip has no
    negative-beat region; the mutator boundary refuses it). 4/4-shaped within a
    bar; ``beats_per_bar`` scales the inter-bar step. ``feel`` (W17-E) shifts each
    16th on top of ``push``. Tagged "bass" + "metal" + "pedal".
    """
    out: list[NoteDict] = []
    for b in range(bars):
        bs = start_beat + b * beats_per_bar
        bb = b * beats_per_bar
        for sixteenth in range(16):
            local = bb + sixteenth * 0.25
            pitch = _bass_root(chords, local, register)
            t = bs + apply_feel(sixteenth * 0.25, feel)
            applied_push = push if t > 0.0 else 0.0
            out.append(_note(pitch, t + applied_push, note_duration, velocity,
                             ["bass", "metal", "pedal"]))
    return out


def chord_tone_embellishment(
    root_pitch: int,
    *,
    third_offset: int,
    fifth_offset: int,
    octave_offset: int = 12,
    start_beat: float = 0.0,
    walk_to_next: int | None = None,
    feel: Feel = None,
) -> list[NoteDict]:
    """One bar of bass-player embellishment: root + 3rd + octave + walk note.

    Pattern lifted from falling-walking chorus bass bar 2 / bar 4 / bar 6 / bar 8.
    `walk_to_next`, when given, plays a final passing tone leading into the next bar.

    Note: this is a SINGLE-BAR generator and is 4/4-shaped (positions at
    0.0 / 0.75 / 1.5 / 2.0 / 2.75 / 3.5 within the bar). It takes no
    ``beats_per_bar`` because there's no inter-bar iteration; caller controls
    placement via ``start_beat``. ``feel`` (W17-E) shifts the within-bar
    positions.
    """
    notes = [
        _note(root_pitch, start_beat + apply_feel(0.0, feel), 0.5, 100, ["bass", "downbeat"]),
        _note(root_pitch + third_offset, start_beat + apply_feel(0.75, feel), 0.4, 88, ["bass", "third"]),
        _note(root_pitch, start_beat + apply_feel(1.5, feel), 0.4, 85, ["bass"]),
        _note(root_pitch + octave_offset, start_beat + apply_feel(2.0, feel), 0.5, 95, ["bass", "octave"]),
        _note(root_pitch, start_beat + apply_feel(2.75, feel), 0.4, 82, ["bass"]),
    ]
    if walk_to_next is not None:
        notes.append(_note(walk_to_next, start_beat + apply_feel(3.5, feel), 0.5, 88, ["bass", "walk_in"]))
    return notes
