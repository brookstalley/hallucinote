"""Drum pattern generators. Output: list[NoteDict] with semantic tags."""
from __future__ import annotations

from typing import Any, Iterable

from hallucinote.generators.primitives import (
    HAT_CLOSED,
    HAT_OPEN,
    KICK,
    LAZY_SNARE,
    SNARE,
    TRESILLO_HITS,
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


def kick_stumble(
    bars: int,
    *,
    start_beat: float = 0.0,
    strong_every: int = 4,
    accent_velocity: int = 118,
    base_velocity: int = 110,
    late_kick_velocity: int = 92,
    pitch: int = KICK,
) -> list[NoteDict]:
    """Trip-hop kick: downbeat + alternating late-2.75 / early-2 kick.

    Tagged "kick" + "stumble".
    """
    out: list[NoteDict] = []
    for b in range(bars):
        bs = start_beat + b * 4.0
        is_strong = b % strong_every == 0
        out.append(_note(pitch, bs, 0.25,
                         accent_velocity if is_strong else base_velocity,
                         ["kick", "stumble", "downbeat"]))
        if b % 2 == 0:
            out.append(_note(pitch, bs + 2.75, 0.25, late_kick_velocity,
                             ["kick", "stumble", "late"]))
        else:
            out.append(_note(pitch, bs + 2.0, 0.25, late_kick_velocity + 3,
                             ["kick", "stumble", "early"]))
    return out


def lazy_snare(
    bars: int,
    *,
    start_beat: float = 0.0,
    pitch: int = SNARE,
    backbeat_velocity: int = 100,
    accent_velocity: int = 112,
    lay_back: float = LAZY_SNARE,
) -> list[NoteDict]:
    """Laid-back 2 & 4. Tagged "snare" + "backbeat"."""
    out: list[NoteDict] = []
    for b in range(bars):
        bs = start_beat + b * 4.0
        out.append(_note(pitch, bs + 1.0 + lay_back, 0.25, backbeat_velocity,
                         ["snare", "backbeat"]))
        out.append(_note(pitch, bs + 3.0 + lay_back, 0.25, accent_velocity,
                         ["snare", "backbeat", "accent"]))
    return out


def trip_hop_hats(
    bars: int,
    *,
    start_beat: float = 0.0,
    pitch: int = HAT_CLOSED,
    open_velocity: int = 80,
    ghost_velocity: int = 35,
    boost_bars: Iterable[int] = (),
    boost_ghost_velocity: int = 52,
) -> list[NoteDict]:
    """8th-note closed hats with deep ghost on the off-beats.

    `boost_bars` indices get the louder ghost (used to build energy into fills).
    Tagged "hat" + "downbeat" or "ghost" + ("boost" if applicable).
    """
    boost = set(boost_bars)
    out: list[NoteDict] = []
    for b in range(bars):
        bs = start_beat + b * 4.0
        boosted = b in boost
        for i, t in enumerate([0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5]):
            if i % 2 == 0:
                out.append(_note(pitch, bs + t, 0.1, open_velocity, ["hat", "downbeat"]))
            else:
                v = boost_ghost_velocity if boosted else ghost_velocity
                tags = ["hat", "ghost"] + (["boost"] if boosted else [])
                out.append(_note(pitch, bs + t, 0.1, v, tags))
    return out


def tresillo_hats(
    bars: int,
    *,
    start_beat: float = 0.0,
    pitch: int = HAT_CLOSED,
) -> list[NoteDict]:
    """Tresillo cell on closed hats. Used in chorus / calypso-feel sections."""
    out: list[NoteDict] = []
    for b in range(bars):
        bs = start_beat + b * 4.0
        for t, v in TRESILLO_HITS:
            # Translate the bass-side velocity profile to hat dynamics
            hat_vel = max(60, min(100, v - 5))
            out.append(_note(pitch, bs + t, 0.1, hat_vel, ["hat", "tresillo"]))
    return out


def bossa_shaker(
    bars: int,
    *,
    start_beat: float = 0.0,
    pitch: int = HAT_CLOSED,
    accent_velocity: int = 35,
    ghost_velocity: int = 24,
    fade_in_per_bar: int = 2,
) -> list[NoteDict]:
    """16th-note shaker with accent on every 4th 16th. Bars fade in via velocity."""
    out: list[NoteDict] = []
    for b in range(bars):
        bs = start_beat + b * 4.0
        for sixteenth in range(16):
            t = sixteenth * 0.25
            base = accent_velocity if sixteenth % 4 == 0 else ghost_velocity
            v = base + b * fade_in_per_bar
            tags = ["hat", "shaker"] + (["accent"] if sixteenth % 4 == 0 else ["ghost"])
            out.append(_note(pitch, bs + t, 0.08, v, tags))
    return out


def ghost_kicks(
    at_bars: Iterable[int],
    *,
    start_beat: float = 0.0,
    offset_in_bar: float = 3.5,
    duration: float = 0.12,
    velocity: int = 50,
    pitch: int = KICK,
) -> list[NoteDict]:
    """Sparse low-velocity kicks at specific bar indices. Use as garnish over kick_stumble.

    Bar indices are relative to `start_beat` — bar 0 lands at `start_beat`.
    """
    return [
        _note(pitch, start_beat + b * 4.0 + offset_in_bar, duration, velocity,
              ["kick", "ghost"])
        for b in at_bars
    ]


def ghost_snares(
    at_bars: Iterable[int],
    *,
    start_beat: float = 0.0,
    offset_in_bar: float = 3.75,
    duration: float = 0.1,
    velocity: int = 38,
    pitch: int = SNARE,
) -> list[NoteDict]:
    """Sparse low-velocity snares for texture. Tagged "snare" + "ghost".

    Bar indices are relative to `start_beat` — bar 0 lands at `start_beat`.
    """
    return [
        _note(pitch, start_beat + b * 4.0 + offset_in_bar, duration, velocity,
              ["snare", "ghost"])
        for b in at_bars
    ]


def open_hat_lifts(
    at_bars: Iterable[int],
    *,
    start_beat: float = 0.0,
    offset_in_bar: float = 3.5,
    duration: float = 0.4,
    velocity: int = 70,
    pitch: int = HAT_OPEN,
) -> list[NoteDict]:
    """Open-hat lifts as drummer flourishes (mini-fill marks).

    Bar indices are relative to `start_beat` — bar 0 lands at `start_beat`.
    """
    return [
        _note(pitch, start_beat + b * 4.0 + offset_in_bar, duration, velocity,
              ["hat", "open", "lift"])
        for b in at_bars
    ]


# ---------------------------------------------------------------------------
# Composers — build up complete patterns from primitives
# ---------------------------------------------------------------------------


def trip_hop_drum_pattern(
    bars: int,
    *,
    start_beat: float = 0.0,
    fill_bars: Iterable[int] = (),
) -> list[NoteDict]:
    """Standard verse-style trip-hop drums for `bars` bars.

    `fill_bars` get extra ghost garnish + boosted hat ghosts.
    """
    notes: list[NoteDict] = []
    notes.extend(kick_stumble(bars, start_beat=start_beat))
    notes.extend(lazy_snare(bars, start_beat=start_beat))
    notes.extend(trip_hop_hats(bars, start_beat=start_beat, boost_bars=fill_bars))
    notes.extend(ghost_kicks(fill_bars, start_beat=start_beat))
    notes.extend(ghost_snares(fill_bars, start_beat=start_beat))
    notes.extend(open_hat_lifts(fill_bars, start_beat=start_beat))
    return notes
