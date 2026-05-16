"""Low-level musical building blocks shared across drum / bass / harmony generators."""
from __future__ import annotations

from typing import Sequence

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
