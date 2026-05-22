"""Low-level musical building blocks shared across drum / bass / harmony generators."""
from __future__ import annotations

from typing import Mapping, Sequence

# Per-part microtiming feel (W17-E). `feel` maps within-bar beat positions to
# shifts in beats. {0.0: -0.01, 2.0: -0.015} = downbeat 10 ticks early, beat 3
# 15 ticks early. Generators apply the lookup at each note's within-bar
# position via `apply_feel`. None preserves the canonical pattern timing.
#
# Per-part, per-helper-call. Granularity is the call, not the song or
# section — so verse drums and chorus drums can have different feels (two
# calls, two feel dicts), and so can two parts in the same clip (kick +
# guitar with opposite microtiming intents). No song-level or section-level
# shared groove instance (see docs/song-authoring-conventions.md "Per-part
# feel"). For string feels ("push hard", "drag eighths", "swing-8ths heavy")
# the LLM resolves the string to a structured dict at compose time; the
# generator API is dict-only.
Feel = Mapping[float, float] | None


def apply_feel(within_bar_position: float, feel: Feel) -> float:
    """Return the within-bar position with the feel shift applied, or unchanged when feel is None.

    Negative results are mathematically valid here — a `feel={0.0: -0.02}`
    shifting bar-1's downbeat by -0.02 returns -0.02. The function is a
    pure within-bar math primitive that doesn't know about absolute
    timeline starts. The mutator boundary (`_normalize_note` in
    `db/mutations.py`) refuses notes whose ABSOLUTE `start_beats` ends
    up negative — that's the layer where reality (Live's MIDI clip has
    no negative-beat region) intrudes. Authors who want to shift bar-1's
    downbeat earlier need to either drop that shift on bar 1 or author
    a pickup/anacrusis pattern explicitly.
    """
    if feel is None:
        return within_bar_position
    return within_bar_position + feel.get(within_bar_position, 0.0)

# Standard GM-ish drum pitches (MIDI). Match the kit used in falling-walking;
# override at the kit level when other songs use different mappings.
KICK = 36
SNARE = 38
HAT_CLOSED = 42
HAT_OPEN = 46
TOM_LO = 47
TOM_HI = 50
RIDE_BELL = 53
CRASH_1 = 49
CRASH_2 = 57
SPLASH = 55
CHINA = 52

# Tresillo (3-3-2) hit offsets within a 4-beat bar, with characteristic
# velocity emphasis on the dotted-eighth pattern.
TRESILLO_HITS: tuple[tuple[float, int], ...] = (
    (0.0, 102),
    (0.75, 90),
    (1.5, 88),
    (2.0, 95),
    (2.75, 85),
    (3.5, 88),
)

# Trip-hop swing: snare laid back this many beats. Empirical from falling-walking.
LAZY_SNARE = 0.04


def chord_tones(root_pitch: int, intervals: Sequence[int]) -> list[int]:
    """Build a chord from root + interval list (semitones).

    >>> chord_tones(38, [0, 3, 7])  # Dm
    [38, 41, 45]
    """
    return [root_pitch + i for i in intervals]
