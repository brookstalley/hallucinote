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

NoteDict = dict[str, Any]


def _note(pitch: int, start: float, dur: float, vel: int, tags: list[str]) -> NoteDict:
    return {
        "pitch": pitch,
        "start_beats": start,
        "duration_beats": dur,
        "velocity": vel,
        "tags": tags,
    }


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
