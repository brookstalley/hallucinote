"""Harmony / pad / pluck / bell generators.

Meter (W14-B). Most generators here take explicit ``start_beat`` +
``length_beats`` / ``section_length_beats``, so they're already
meter-agnostic. ``tresillo_pluck`` is the exception: it iterates bars
internally and uses the 4/4-shaped tresillo cell. ``beats_per_bar``
(default 4.0) controls bar iteration only; the within-bar pattern
stays 4/4-shaped.
"""
from __future__ import annotations

from typing import Any, Sequence

NoteDict = dict[str, Any]


def _note(pitch: int, start: float, dur: float, vel: int, tags: list[str]) -> NoteDict:
    return {
        "pitch": pitch,
        "start_beats": start,
        "duration_beats": dur,
        "velocity": vel,
        "tags": tags,
    }


def chord_pad(
    voicing: Sequence[int],
    *,
    start_beat: float,
    length_beats: float,
    velocity: int = 80,
) -> list[NoteDict]:
    """Sustained chord. Each pitch gets one long note."""
    return [
        _note(p, start_beat, length_beats, velocity, ["pad", "sustain"])
        for p in voicing
    ]


def chord_stab(
    voicing: Sequence[int],
    *,
    start_beat: float,
    duration: float = 0.5,
    velocity: int = 95,
) -> list[NoteDict]:
    """Short rhythmic chord hit."""
    return [
        _note(p, start_beat, duration, velocity, ["pad", "stab"])
        for p in voicing
    ]


def tresillo_pluck(
    voicing: Sequence[int],
    *,
    bars: int = 1,
    start_beat: float = 0.0,
    beats_per_bar: float = 4.0,
    duration: float = 0.2,
) -> list[NoteDict]:
    """Calypso-style pluck cycling through voicing on tresillo hits.
    4/4-shaped within a bar (see module docstring); ``beats_per_bar`` only
    scales the inter-bar step.
    """
    hits = [(0.0, 95), (0.75, 100), (1.5, 90), (2.0, 75), (2.75, 95), (3.5, 100)]
    out: list[NoteDict] = []
    for b in range(bars):
        bs = start_beat + b * beats_per_bar
        for i, (t, v) in enumerate(hits):
            p = voicing[i % len(voicing)]
            out.append(_note(p, bs + t, duration, v, ["pluck", "tresillo_hit"]))
    return out


def sparse_bell_top(
    voicing: Sequence[int],
    *,
    start_beat: float,
    section_length_beats: float = 8.0,
    octave_up: int = 12,
) -> list[NoteDict]:
    """Bell hits on the chord top: one long arrival + one mid-section answer.

    Lifted from falling-walking chorus_bell.
    """
    top = voicing[-1] + octave_up
    return [
        _note(top, start_beat, 1.0, 75, ["bell", "arrival"]),
        _note(top - 5, start_beat + section_length_beats - 2.5, 0.5, 65, ["bell", "answer"]),
    ]
