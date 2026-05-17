"""Bass pattern generators."""
from __future__ import annotations

from typing import Any

from hallucinote.generators.primitives import TRESILLO_HITS

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
    note_duration: float = 0.5,
) -> list[NoteDict]:
    """Plain tresillo on the chord root. Tagged "bass" + "tresillo_hit"."""
    out: list[NoteDict] = []
    for b in range(bars):
        bs = start_beat + b * 4.0
        for t, v in TRESILLO_HITS:
            out.append(_note(root_pitch, bs + t, note_duration, v,
                             ["bass", "tresillo_hit"]))
    return out


def walking_bass_to_next_chord(
    *,
    walk: list[int],
    start_beat: float,
    bar_count: int = 1,
    accent_velocity: int = 100,
    walk_velocity: int = 88,
    note_duration: float = 1.0,
) -> list[NoteDict]:
    """Walk through `walk` pitches across `bar_count` bars at beats [0, 1.5, 2, 3.5].

    Convention: walk[0] = chord root, walk[1:] = passing tones leading to next chord.
    Tagged "bass" + "walk" with first note also "downbeat".
    """
    out: list[NoteDict] = []
    for bar in range(bar_count):
        bs = start_beat + bar * 4.0
        for i, beat in enumerate([0.0, 1.5, 2.0, 3.5]):
            p = walk[i % len(walk)]
            tags = ["bass", "walk"]
            if i == 0:
                tags.append("downbeat")
                vel = accent_velocity
            else:
                vel = walk_velocity
            out.append(_note(p, bs + beat, note_duration, vel, tags))
    return out


def chord_tone_embellishment(
    root_pitch: int,
    *,
    third_offset: int,
    fifth_offset: int,
    octave_offset: int = 12,
    start_beat: float = 0.0,
    walk_to_next: int | None = None,
) -> list[NoteDict]:
    """One bar of bass-player embellishment: root + 3rd + octave + walk note.

    Pattern lifted from falling-walking chorus bass bar 2 / bar 4 / bar 6 / bar 8.
    `walk_to_next`, when given, plays a final passing tone leading into the next bar.
    """
    notes = [
        _note(root_pitch, start_beat + 0.0, 0.5, 100, ["bass", "downbeat"]),
        _note(root_pitch + third_offset, start_beat + 0.75, 0.4, 88, ["bass", "third"]),
        _note(root_pitch, start_beat + 1.5, 0.4, 85, ["bass"]),
        _note(root_pitch + octave_offset, start_beat + 2.0, 0.5, 95, ["bass", "octave"]),
        _note(root_pitch, start_beat + 2.75, 0.4, 82, ["bass"]),
    ]
    if walk_to_next is not None:
        notes.append(_note(walk_to_next, start_beat + 3.5, 0.5, 88, ["bass", "walk_in"]))
    return notes
