"""hallucinote.performance.dynamics — the velocity + articulation read side.

The §4.2 dynamics + articulation half of the symbolic performance lens. Its
headline is the FLAT-DYNAMICS case — the documented sun-zone-done organ: many
rhythmic notes at essentially one velocity, a mechanically flat dynamic (the lens
asks "intended drone, or missing dynamic shaping?" — never a verdict). It also
reports an articulation character (staccato↔legato) from each note's duration
against the gap to the next onset. Pure stdlib — no numpy.

Dynamics is per-NOTE (every note carries a velocity; a block chord's three notes
are three velocities). Articulation is per-ONSET (the rhythmic event), using the
sustaining voice's duration against the inter-onset interval — so it is computed
from the de-duplicated onset-event list the lens already builds, not raw notes.
"""
from __future__ import annotations

import statistics
from typing import Any, Sequence

NoteDict = dict[str, Any]  # same shape the lens/realization modules use

# Velocity stdev (MIDI units) at/below which a part's dynamics read FLAT — many
# notes at essentially one level. ~2 units is dynamically imperceptible; human
# (or humanized) dynamic shaping runs ~8–20. The tests import this constant.
FLAT_VELOCITY_STDEV_MAX = 2.0

# Minimum NOTES before the flat-dynamics flag is meaningful (a 2-note part being
# "one velocity" says nothing).
FLAT_DYNAMICS_MIN_NOTES = 8


def velocity_stats(notes: Sequence[NoteDict]) -> tuple[float | None, float | None, int]:
    """``(mean, population-stdev, n)`` of the part's note velocities. ``(None,
    None, 0)`` for an empty part."""
    vels = [float(n["velocity"]) for n in notes]
    n = len(vels)
    if n == 0:
        return None, None, 0
    return statistics.fmean(vels), statistics.pstdev(vels), n


def is_flat_dynamics(velocity_stdev: float | None, note_count: int) -> bool:
    """A part reads dynamically flat when it has enough notes and their velocities
    cluster within ``FLAT_VELOCITY_STDEV_MAX`` of one level. This is a fact about
    the part; whether it's worth a coaching finding (rhythmic activity) is the
    lens's call."""
    return (
        velocity_stdev is not None
        and note_count >= FLAT_DYNAMICS_MIN_NOTES
        and velocity_stdev <= FLAT_VELOCITY_STDEV_MAX
    )


def articulation_stats(
    onset_events: Sequence[tuple[float, float]],
) -> tuple[float | None, float | None]:
    """``(median, stdev)`` of duration/IOI across distinct onsets — the
    articulation character (≈1 legato/sustained, <≈0.5 staccato/detached) and its
    consistency (low stdev = uniform articulation). ``onset_events`` is the lens's
    sorted ``(onset, sustaining-duration)`` list. ``(None, None)`` when fewer than
    two onsets carry a positive inter-onset interval.

    Reported, not yet a finding source: an all-uniform articulation is usually
    rhythmic intent (every note a clean 8th), not an error — flagging it would
    false-positive constantly. A future refinement can coach on it against intent.
    """
    ratios: list[float] = []
    for i in range(len(onset_events) - 1):
        ioi = onset_events[i + 1][0] - onset_events[i][0]
        if ioi > 0:
            ratios.append(onset_events[i][1] / ioi)
    if not ratios:
        return None, None
    if len(ratios) == 1:
        return ratios[0], 0.0
    return statistics.median(ratios), statistics.pstdev(ratios)
