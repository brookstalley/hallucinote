"""hallucinote.performance.ensemble — inter-part phase / ensemble lock (symbolic).

The §7 inter-part half of the lens: do two parts LOCK (move together — a stable
relative timing, the pocket) or sit independently? Measured at the grid positions
BOTH parts hit, as the relative offset of one part to the other:

  * a **stable** relative offset (low stdev) = locked — they breathe together,
    even when each deviates from the grid;
  * a **constant nonzero** offset is a deliberate POCKET (the bass sitting behind
    the kick), NOT sloppiness — captured as ``offset_mean``, separate from tightness;
  * a **high** relative stdev = they don't lock.

REPORTED, not flagged. Whether non-locking is "loose" or deliberate independence
(a cross-rhythm, punk drums under lazy bluegrass in one section — valid
authorship) is an INTENT question, interpreted downstream (e.g. /mix-review)
against the song's declared intent. The lens measures; it never flags inter-part
independence as error (feedback_microtiming_is_authorship). Pure stdlib.
"""
from __future__ import annotations

import statistics
from typing import Sequence

# Minimum grid positions two parts must BOTH hit before their ensemble
# relationship is measurable — too few shared onsets = no ensemble to speak of.
MIN_SHARED_ONSETS = 6


def _grid_dev_map(events: Sequence[tuple[float, float]], grid: float) -> dict[float, float]:
    """grid-position → signed deviation, for each onset (snapped to nearest grid).
    First onset wins if two somehow snap to the same grid line (post-dedup, rare)."""
    out: dict[float, float] = {}
    for onset, _dur in events:
        g = round(onset / grid) * grid
        out.setdefault(g, onset - g)
    return out


def pairwise_offsets(
    events_a: Sequence[tuple[float, float]],
    events_b: Sequence[tuple[float, float]],
    *,
    grid: float,
) -> tuple[float, float, int] | None:
    """``(offset_mean, offset_stdev, shared)`` of B relative to A at the grid
    positions both hit. ``offset_mean`` < 0 = B ahead of A, > 0 = B behind;
    ``offset_stdev`` is the ensemble tightness (low = locked). ``None`` when the
    pair shares fewer than ``MIN_SHARED_ONSETS`` grid positions."""
    a = _grid_dev_map(events_a, grid)
    b = _grid_dev_map(events_b, grid)
    shared = sorted(set(a) & set(b))
    if len(shared) < MIN_SHARED_ONSETS:
        return None
    rel = [b[g] - a[g] for g in shared]
    return statistics.fmean(rel), statistics.pstdev(rel), len(shared)
