"""Drum pattern generators. Output: list[NoteDict] with semantic tags.

Meter (W14-B). Every generator here was authored against 4/4 (kicks on the
downbeat, snares on 2 + 4, hats on 8ths, shaker on 16ths). The ``bars``
iteration uses ``beats_per_bar`` (default 4.0) so bar starts step correctly
through non-4/4 sections — e.g. ``trip_hop_hats(bars=4, beats_per_bar=3.5)``
lands bar 2's first hat at beat 3.5 not beat 4.0. The within-bar layout is
still 4/4-shaped and does NOT scale with the meter: patterns may overflow
a short bar (e.g. ``bossa_shaker`` fills 4 beats of 16ths regardless of
``beats_per_bar``) or under-fill a long one. For non-4/4 sections where
the within-bar shape matters, author by hand or compose a meter-specific
primitive.
"""
from __future__ import annotations

from typing import Any, Iterable

from hallucinote.generators.primitives import (
    HAT_CLOSED,
    HAT_OPEN,
    KICK,
    LAZY_SNARE,
    SNARE,
    TRESILLO_HITS,
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


def kick_stumble(
    bars: int,
    *,
    start_beat: float = 0.0,
    beats_per_bar: float = 4.0,
    strong_every: int = 4,
    accent_velocity: int = 118,
    base_velocity: int = 110,
    late_kick_velocity: int = 92,
    pitch: int = KICK,
    feel: Feel = None,
) -> list[NoteDict]:
    """Trip-hop kick: downbeat + alternating late-2.75 / early-2 kick.

    Tagged "kick" + "stumble". Within-bar layout is 4/4-shaped (see module
    docstring); ``beats_per_bar`` only scales the inter-bar step. ``feel``
    (W17-E) maps within-bar positions {0.0, 2.0, 2.75} to microtiming shifts.
    """
    out: list[NoteDict] = []
    for b in range(bars):
        bs = start_beat + b * beats_per_bar
        is_strong = b % strong_every == 0
        out.append(_note(pitch, bs + apply_feel(0.0, feel), 0.25,
                         accent_velocity if is_strong else base_velocity,
                         ["kick", "stumble", "downbeat"]))
        if b % 2 == 0:
            out.append(_note(pitch, bs + apply_feel(2.75, feel), 0.25, late_kick_velocity,
                             ["kick", "stumble", "late"]))
        else:
            out.append(_note(pitch, bs + apply_feel(2.0, feel), 0.25, late_kick_velocity + 3,
                             ["kick", "stumble", "early"]))
    return out


def lazy_snare(
    bars: int,
    *,
    start_beat: float = 0.0,
    beats_per_bar: float = 4.0,
    pitch: int = SNARE,
    backbeat_velocity: int = 100,
    accent_velocity: int = 112,
    lay_back: float = LAZY_SNARE,
    feel: Feel = None,
) -> list[NoteDict]:
    """Laid-back 2 & 4. Tagged "snare" + "backbeat". 4/4-shaped within a bar
    (see module docstring); ``beats_per_bar`` scales the inter-bar step.
    ``feel`` (W17-E) shifts the canonical 1.0 / 3.0 positions; ``lay_back``
    adds on top of the feel shift.
    """
    out: list[NoteDict] = []
    for b in range(bars):
        bs = start_beat + b * beats_per_bar
        out.append(_note(pitch, bs + apply_feel(1.0, feel) + lay_back, 0.25, backbeat_velocity,
                         ["snare", "backbeat"]))
        out.append(_note(pitch, bs + apply_feel(3.0, feel) + lay_back, 0.25, accent_velocity,
                         ["snare", "backbeat", "accent"]))
    return out


def trip_hop_hats(
    bars: int,
    *,
    start_beat: float = 0.0,
    beats_per_bar: float = 4.0,
    pitch: int = HAT_CLOSED,
    open_velocity: int = 80,
    ghost_velocity: int = 35,
    boost_bars: Iterable[int] = (),
    boost_ghost_velocity: int = 52,
    feel: Feel = None,
) -> list[NoteDict]:
    """8th-note closed hats with deep ghost on the off-beats.

    `boost_bars` indices get the louder ghost (used to build energy into fills).
    Tagged "hat" + "downbeat" or "ghost" + ("boost" if applicable).
    4/4-shaped within a bar (see module docstring); ``beats_per_bar`` only
    scales the inter-bar step. ``feel`` (W17-E) shifts any of the eighth-note
    positions {0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5} — a swing-8ths feel
    typically nudges the off-beats {0.5, 1.5, 2.5, 3.5} late.
    """
    boost = set(boost_bars)
    out: list[NoteDict] = []
    for b in range(bars):
        bs = start_beat + b * beats_per_bar
        boosted = b in boost
        for i, t in enumerate([0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5]):
            shifted = apply_feel(t, feel)
            if i % 2 == 0:
                out.append(_note(pitch, bs + shifted, 0.1, open_velocity, ["hat", "downbeat"]))
            else:
                v = boost_ghost_velocity if boosted else ghost_velocity
                tags = ["hat", "ghost"] + (["boost"] if boosted else [])
                out.append(_note(pitch, bs + shifted, 0.1, v, tags))
    return out


def tresillo_hats(
    bars: int,
    *,
    start_beat: float = 0.0,
    beats_per_bar: float = 4.0,
    pitch: int = HAT_CLOSED,
    feel: Feel = None,
) -> list[NoteDict]:
    """Tresillo cell on closed hats. Used in chorus / calypso-feel sections.
    4/4-shaped within a bar (see module docstring); ``beats_per_bar`` only
    scales the inter-bar step. ``feel`` (W17-E) shifts tresillo positions
    {0.0, 0.75, 1.5, 2.0, 2.75, 3.5}.
    """
    out: list[NoteDict] = []
    for b in range(bars):
        bs = start_beat + b * beats_per_bar
        for t, v in TRESILLO_HITS:
            # Translate the bass-side velocity profile to hat dynamics
            hat_vel = max(60, min(100, v - 5))
            out.append(_note(pitch, bs + apply_feel(t, feel), 0.1, hat_vel, ["hat", "tresillo"]))
    return out


def bossa_shaker(
    bars: int,
    *,
    start_beat: float = 0.0,
    beats_per_bar: float = 4.0,
    pitch: int = HAT_CLOSED,
    accent_velocity: int = 35,
    ghost_velocity: int = 24,
    fade_in_per_bar: int = 2,
    feel: Feel = None,
) -> list[NoteDict]:
    """16th-note shaker with accent on every 4th 16th. Bars fade in via velocity.
    4/4-shaped within a bar (see module docstring); ``beats_per_bar`` only
    scales the inter-bar step. ``feel`` (W17-E) shifts any of the sixteenth-note
    positions {0.0, 0.25, 0.5, ..., 3.75}.
    """
    out: list[NoteDict] = []
    for b in range(bars):
        bs = start_beat + b * beats_per_bar
        for sixteenth in range(16):
            t = sixteenth * 0.25
            base = accent_velocity if sixteenth % 4 == 0 else ghost_velocity
            v = base + b * fade_in_per_bar
            tags = ["hat", "shaker"] + (["accent"] if sixteenth % 4 == 0 else ["ghost"])
            out.append(_note(pitch, bs + apply_feel(t, feel), 0.08, v, tags))
    return out


def ghost_kicks(
    at_bars: Iterable[int],
    *,
    start_beat: float = 0.0,
    beats_per_bar: float = 4.0,
    offset_in_bar: float = 3.5,
    duration: float = 0.12,
    velocity: int = 50,
    pitch: int = KICK,
    feel: Feel = None,
) -> list[NoteDict]:
    """Sparse low-velocity kicks at specific bar indices. Use as garnish over kick_stumble.

    Bar indices are relative to `start_beat` — bar 0 lands at `start_beat`.
    4/4-shaped within a bar (see module docstring); ``beats_per_bar`` only
    scales the inter-bar step. ``feel`` (W17-E) shifts ``offset_in_bar``.
    """
    shifted = apply_feel(offset_in_bar, feel)
    return [
        _note(pitch, start_beat + b * beats_per_bar + shifted, duration, velocity,
              ["kick", "ghost"])
        for b in at_bars
    ]


def ghost_snares(
    at_bars: Iterable[int],
    *,
    start_beat: float = 0.0,
    beats_per_bar: float = 4.0,
    offset_in_bar: float = 3.75,
    duration: float = 0.1,
    velocity: int = 38,
    pitch: int = SNARE,
    feel: Feel = None,
) -> list[NoteDict]:
    """Sparse low-velocity snares for texture. Tagged "snare" + "ghost".

    Bar indices are relative to `start_beat` — bar 0 lands at `start_beat`.
    4/4-shaped within a bar (see module docstring); ``beats_per_bar`` only
    scales the inter-bar step. ``feel`` (W17-E) shifts ``offset_in_bar``.
    """
    shifted = apply_feel(offset_in_bar, feel)
    return [
        _note(pitch, start_beat + b * beats_per_bar + shifted, duration, velocity,
              ["snare", "ghost"])
        for b in at_bars
    ]


def open_hat_lifts(
    at_bars: Iterable[int],
    *,
    start_beat: float = 0.0,
    beats_per_bar: float = 4.0,
    offset_in_bar: float = 3.5,
    duration: float = 0.4,
    velocity: int = 70,
    pitch: int = HAT_OPEN,
    feel: Feel = None,
) -> list[NoteDict]:
    """Open-hat lifts as drummer flourishes (mini-fill marks).

    Bar indices are relative to `start_beat` — bar 0 lands at `start_beat`.
    4/4-shaped within a bar (see module docstring); ``beats_per_bar`` only
    scales the inter-bar step. ``feel`` (W17-E) shifts ``offset_in_bar``.
    """
    shifted = apply_feel(offset_in_bar, feel)
    return [
        _note(pitch, start_beat + b * beats_per_bar + shifted, duration, velocity,
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
    beats_per_bar: float = 4.0,
    fill_bars: Iterable[int] = (),
    feel: Feel = None,
) -> list[NoteDict]:
    """Standard verse-style trip-hop drums for `bars` bars.

    `fill_bars` get extra ghost garnish + boosted hat ghosts. 4/4-shaped
    within a bar (see module docstring); ``beats_per_bar`` only scales
    the inter-bar step and threads through to every sub-primitive.
    ``feel`` (W17-E) is forwarded uniformly to all sub-primitives — for
    differentiated feel per drum class (kick punch + snare drag), call the
    primitives directly with different feel dicts.
    """
    notes: list[NoteDict] = []
    notes.extend(kick_stumble(bars, start_beat=start_beat, beats_per_bar=beats_per_bar, feel=feel))
    notes.extend(lazy_snare(bars, start_beat=start_beat, beats_per_bar=beats_per_bar, feel=feel))
    notes.extend(trip_hop_hats(bars, start_beat=start_beat,
                               beats_per_bar=beats_per_bar, boost_bars=fill_bars, feel=feel))
    notes.extend(ghost_kicks(fill_bars, start_beat=start_beat,
                             beats_per_bar=beats_per_bar, feel=feel))
    notes.extend(ghost_snares(fill_bars, start_beat=start_beat,
                              beats_per_bar=beats_per_bar, feel=feel))
    notes.extend(open_hat_lifts(fill_bars, start_beat=start_beat,
                                beats_per_bar=beats_per_bar, feel=feel))
    return notes
