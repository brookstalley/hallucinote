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

from hallucinote.generators.primitives import (
    METAL_GALLOP_OFFSETS,
    REGGAE_LAZY,
    Feel,
    apply_feel,
)

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
    feel: Feel = None,
) -> list[NoteDict]:
    """Calypso-style pluck cycling through voicing on tresillo hits.
    4/4-shaped within a bar (see module docstring); ``beats_per_bar`` only
    scales the inter-bar step. ``feel`` (W17-E) shifts pluck positions
    {0.0, 0.75, 1.5, 2.0, 2.75, 3.5}.
    """
    hits = [(0.0, 95), (0.75, 100), (1.5, 90), (2.0, 75), (2.75, 95), (3.5, 100)]
    out: list[NoteDict] = []
    for b in range(bars):
        bs = start_beat + b * beats_per_bar
        for i, (t, v) in enumerate(hits):
            p = voicing[i % len(voicing)]
            out.append(_note(p, bs + apply_feel(t, feel), duration, v, ["pluck", "tresillo_hit"]))
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


# ---------------------------------------------------------------------------
# Reggae / metal idioms (promoted from sun-zone-done — the flagship demo song)
# ---------------------------------------------------------------------------


def reggae_skank(
    voicing: Sequence[int],
    *,
    bars: int = 1,
    start_beat: float = 0.0,
    beats_per_bar: float = 4.0,
    duration: float = 0.30,
    velocity: int = 78,
    lazy: float = 0.06,
    feel: Feel = None,
) -> list[NoteDict]:
    """The iconic reggae skank: a clipped chord "chuck" on the "and" of 2 and
    the "and" of 4 — nothing on the downbeats, which is what makes it lift.

    Each chuck lands ``lazy`` beats behind the click (the unhurried chop) and
    is short (``duration``) — staccato, not sustained. 4/4-shaped within a bar
    (see module docstring); ``beats_per_bar`` only scales the inter-bar step.
    ``feel`` (W17-E) shifts the {1.5, 3.5} positions on top of ``lazy``.
    Tagged "skank" + "offbeat".
    """
    out: list[NoteDict] = []
    for b in range(bars):
        bs = start_beat + b * beats_per_bar
        for off in (1.5, 3.5):
            for p in voicing:
                out.append(_note(p, bs + apply_feel(off, feel) + lazy, duration, velocity,
                                 ["skank", "offbeat", "chuck"]))
    return out


def organ_bubble(
    voicing: Sequence[int],
    *,
    bars: int = 1,
    start_beat: float = 0.0,
    beats_per_bar: float = 4.0,
    duration: float = 0.20,
    velocity: int = 58,
    lag: float = REGGAE_LAZY,
    feel: Feel = None,
) -> list[NoteDict]:
    """Hammond "bubble": short organ chord stabs on every off-beat eighth
    (the "and" of every beat), the percolating reggae keyboard texture that
    sits under the skank.

    Each stab lands ``lag`` beats behind the click. 4/4-shaped within a bar
    (see module docstring); ``beats_per_bar`` only scales the inter-bar step.
    ``feel`` (W17-E) shifts the {0.5, 1.5, 2.5, 3.5} positions on top of
    ``lag``. Tagged "organ" + "bubble".
    """
    out: list[NoteDict] = []
    for b in range(bars):
        bs = start_beat + b * beats_per_bar
        for off in (0.5, 1.5, 2.5, 3.5):
            for p in voicing:
                out.append(_note(p, bs + apply_feel(off, feel) + lag, duration, velocity,
                                 ["organ", "bubble", "offbeat"]))
    return out


def palm_mute_power_chords(
    root_pitch: int,
    *,
    bars: int = 1,
    fifth_offset: int = 7,
    octave_offset: int = 12,
    start_beat: float = 0.0,
    beats_per_bar: float = 4.0,
    root_velocity: int = 108,
    fifth_velocity: int = 100,
    octave_velocity: int = 95,
    note_duration: float = 0.18,
    feel: Feel = None,
) -> list[NoteDict]:
    """Palm-muted power chords (root + 5th + octave) chugging the
    :data:`METAL_GALLOP_OFFSETS` cell — the metal rhythm-guitar engine.

    Locks rhythmically with :func:`hallucinote.generators.drums.metal_gallop`
    (same offset cell): the chunked guitar and the kick gallop hit together,
    which is the genre's wall of attack. Short notes (``note_duration``) =
    palm-muted chug. 4/4-shaped within a bar (see module docstring);
    ``beats_per_bar`` scales the inter-bar step. ``feel`` (W17-E) shifts each
    chug. Tagged "power_chord" + "palm_mute" + "gallop".
    """
    fifth = root_pitch + fifth_offset
    octave = root_pitch + octave_offset
    out: list[NoteDict] = []
    for b in range(bars):
        bs = start_beat + b * beats_per_bar
        for off in METAL_GALLOP_OFFSETS:
            t = bs + apply_feel(off, feel)
            out.append(_note(root_pitch, t, note_duration, root_velocity,
                             ["power_chord", "palm_mute", "gallop"]))
            out.append(_note(fifth, t, note_duration, fifth_velocity,
                             ["power_chord", "palm_mute", "gallop"]))
            out.append(_note(octave, t, note_duration, octave_velocity,
                             ["power_chord", "palm_mute", "gallop"]))
    return out
