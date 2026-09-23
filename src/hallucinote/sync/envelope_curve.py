"""The authored envelope curve, and the staircase that carries it to Live.

The MCP handler writes a session-clip envelope with ``Envelope.insert_step``,
which draws a flat step held until the next one. An authored two-point
``linear`` ramp sent as-is therefore reaches Live as ONE flat step at the first
value: the ramp the author wrote is not the ramp that plays.

The fix is a materialization, the same way the arrangement is a projection of
the DB: the DB keeps the AUTHORED breakpoints, and the session-clip push renders
them into a staircase that samples the authored curve finely enough to be heard
as the curve. Pull then asks whether what Live holds is a sampling OF the
authored curve. Comparing against the stored breakpoints would see 64 steps
where the DB holds 2 and overwrite the author's intent with the projection.

**The alternative not taken: a curved write (#298).** Live 12.4's envelope also
has ``create_event`` / ``events_in_range``, which carry real curved segments on
this same session-clip route (probed 2026-06-12,
``.prawduct/artifacts/research-spike-automation-ingest.md``). A curved write
would make the staircase unnecessary. It is not the route here because its write
round trip is still unproven. When #298 lands a curved writer, it replaces
:func:`render_staircase` for the envelopes it can write, and pull's
:func:`holds_authored_curve` is what it must keep passing.

This is a leaf module: both ``sync.push`` and ``sync.pull`` import it, and it
imports neither, so the one rendering both halves agree on has one home.

Curve semantics match the perform route's ``_interp_performed_value`` in
``hallucinote_mcp.handlers.automation`` exactly (a parity test holds them
together): ``breakpoints[i]['curve']`` shapes the segment FROM breakpoint ``i``
TO ``i + 1`` — ``linear`` (the DB default) lerps, ``hold`` freezes, ``fast`` is
``1 - (1 - t)**2``, ``slow`` is ``t**2``.
"""
from __future__ import annotations

import bisect
import math
from collections.abc import Sequence
from typing import Any

# The staircase's step width, in beats. A resolution CHOICE bounded by wire
# payload, not a measured Live limit: 1/16 beat is finer than the perform
# recorder's ~0.21 beat per tick at `--perform-slowdown 4`, so the session-clip
# route is never the coarser of the two. Whether Live coalesces steps this dense
# has not been measured — one push-and-read-back in a Live session settles it.
STAIRCASE_STEP_BEATS = 0.0625

# The most breakpoints one staircase may put on the wire. Past it the step is
# WIDENED until the whole ramp fits, rather than truncating the ramp — a coarser
# ramp still arrives at its authored end value, a truncated one does not. The
# count includes the end point, so this is a 64-beat (16-bar 4/4) ramp at full
# resolution: 64 * 16 steps plus the point it lands on.
MAX_STAIRCASE_STEPS = 64 * 16 + 1

# How far a value may sit from the target's static value and still count as
# "the same": Live discards an envelope every one of whose steps equals the
# parameter's static value. Tight on purpose — a ride a hair off static is a
# real ride Live keeps, and skipping it would be the silent loss this guards.
STATIC_MATCH_REL_TOL = 1e-6
STATIC_MATCH_ABS_TOL = 1e-6

# Growth factor when a staircase overflows MAX_STAIRCASE_STEPS. Per-segment
# ceil() rounding means one exact division can still overflow by up to one step
# per segment, so the width grows until the count fits.
_STEP_GROWTH = 1.25

# Consecutive staircase values closer than this are one step, the same collapse
# Live's read-back applies (`_sample_envelope_to_breakpoints`).
_SAME_STEP_EPS = 1e-9


def wire_breakpoints(rows: Sequence[Any]) -> list[dict[str, Any]]:
    """DB ``automation_breakpoints`` rows in the wire shape the MCP handler
    and every function here read: ``curve_kind`` becomes ``curve`` at this
    boundary, the one place push and pull both convert through."""
    return [
        {
            "time_beats": float(bp["time_beats"]),
            "value": float(bp["value"]),
            "curve": bp["curve_kind"],
        }
        for bp in rows
    ]


def _curve_of(bp: dict[str, Any]) -> str:
    return bp.get("curve") or "linear"


def segment_ramps(bps: Sequence[dict[str, Any]], i: int) -> bool:
    """Does the segment from ``bps[i]`` to ``bps[i + 1]`` move its value across
    time rather than step it? ``hold``, a zero-length segment and a segment
    with no value change all step; every other curve ramps."""
    if _curve_of(bps[i]) == "hold":
        return False
    if float(bps[i + 1]["time_beats"]) <= float(bps[i]["time_beats"]):
        return False
    return float(bps[i + 1]["value"]) != float(bps[i]["value"])


def has_ramp(bps: Sequence[dict[str, Any]]) -> bool:
    """True when any segment of the envelope ramps — the envelopes a flat-step
    write would misrepresent, and the only ones the staircase touches."""
    return any(segment_ramps(bps, i) for i in range(len(bps) - 1))


def sample_authored_curve(bps: Sequence[dict[str, Any]], t: float) -> float:
    """The authored curve's value at beat ``t``.

    ``bps`` is time-sorted wire-shape breakpoints (``time_beats``, ``value``,
    ``curve``). Before the first breakpoint the first value holds; from the
    last one on, the last value holds.
    """
    if not bps:
        raise ValueError("sample_authored_curve: no breakpoints")
    if t <= float(bps[0]["time_beats"]):
        return float(bps[0]["value"])
    if t >= float(bps[-1]["time_beats"]):
        return float(bps[-1]["value"])
    for i in range(len(bps) - 1):
        t0 = float(bps[i]["time_beats"])
        t1 = float(bps[i + 1]["time_beats"])
        if t0 <= t < t1:
            return _segment_value(bps[i], bps[i + 1], (t - t0) / (t1 - t0))
    return float(bps[-1]["value"])


def _segment_value(
    bp: dict[str, Any], nxt: dict[str, Any], x: float,
) -> float:
    """The value a fraction ``x`` (0..1) of the way through the segment from
    ``bp`` to ``nxt``, shaped by ``bp``'s curve."""
    v0 = float(bp["value"])
    v1 = float(nxt["value"])
    curve = _curve_of(bp)
    if curve == "hold":
        return v0
    if curve == "fast":
        shaped = 1.0 - (1.0 - x) ** 2
    elif curve == "slow":
        shaped = x**2
    else:
        shaped = x
    return v0 + (v1 - v0) * shaped


def _segment_step_count(duration: float, step_beats: float) -> int:
    return max(1, math.ceil(duration / step_beats - 1e-9))


def _count_steps(bps: Sequence[dict[str, Any]], step_beats: float) -> int:
    n = 1  # the final breakpoint
    for i in range(len(bps) - 1):
        if segment_ramps(bps, i):
            dur = float(bps[i + 1]["time_beats"]) - float(bps[i]["time_beats"])
            n += _segment_step_count(dur, step_beats)
        else:
            n += 1
    return n


def render_staircase(
    bps: Sequence[dict[str, Any]],
    *,
    step_beats: float | None = None,
    max_steps: int | None = None,
) -> tuple[list[dict[str, Any]], float]:
    """Render authored breakpoints as the stepped breakpoint list to send Live.

    Returns ``(breakpoints, step_used)``. Every ramping segment is cut into
    equal steps no wider than ``step_used``, each holding the authored curve's
    value at its start, so every authored breakpoint appears on the wire at its
    exact time and value and the ramp arrives at its authored end. Stepping
    segments pass through as one point. Every emitted point is ``hold`` — the
    list IS the step shape, and the handler writes it as such.

    An envelope with no ramping segment is returned unchanged (same objects,
    same curves), so a ``hold``-only push is byte-identical to one that never
    passed through here.

    ``step_used`` is ``step_beats`` unless the staircase would exceed
    ``max_steps`` breakpoints, in which case it is the widened step that fits.
    Both default to the module constants, read at call time.
    """
    if step_beats is None:
        step_beats = STAIRCASE_STEP_BEATS
    if max_steps is None:
        max_steps = MAX_STAIRCASE_STEPS
    if not bps or not has_ramp(bps):
        return list(bps), step_beats
    # One point per authored breakpoint is the floor no widening can go under,
    # so an envelope already that dense is sent at one step per segment.
    budget = max(max_steps, len(bps))
    step = step_beats
    while _count_steps(bps, step) > budget:
        step *= _STEP_GROWTH
    out: list[dict[str, Any]] = []
    for i in range(len(bps) - 1):
        t0 = float(bps[i]["time_beats"])
        if not segment_ramps(bps, i):
            out.append({**bps[i], "time_beats": t0,
                        "value": float(bps[i]["value"]), "curve": "hold"})
            continue
        t1 = float(bps[i + 1]["time_beats"])
        n = _segment_step_count(t1 - t0, step)
        width = (t1 - t0) / n
        for k in range(n):
            out.append({**bps[i], "time_beats": t0 + k * width,
                        "value": _segment_value(bps[i], bps[i + 1], k / n),
                        "curve": "hold"})
    last = bps[-1]
    out.append({**last, "time_beats": float(last["time_beats"]),
                "value": float(last["value"]), "curve": "hold"})
    return out, step


def _step_changes(
    bps: Sequence[dict[str, Any]],
) -> list[tuple[float, float]]:
    """Collapse a step list to its value CHANGES, the way Live's read-back
    reports one: a run of equal values is one breakpoint."""
    changes: list[tuple[float, float]] = []
    for bp in bps:
        v = float(bp["value"])
        if changes and abs(v - changes[-1][1]) <= _SAME_STEP_EPS:
            continue
        changes.append((float(bp["time_beats"]), v))
    return changes


def _curve_range(
    bps: Sequence[dict[str, Any]], a: float, b: float,
) -> tuple[float, float]:
    """The lowest and highest value the authored curve takes on ``[a, b]``.

    Every segment is monotone between its ends, so the extremes lie at the
    window's ends or at a breakpoint inside it — counting both the value a
    breakpoint lands on and the value the segment before it ended at (they
    differ across a ``hold``).
    """
    values = [sample_authored_curve(bps, a), sample_authored_curve(bps, b)]
    for i in range(len(bps) - 1):
        t1 = float(bps[i + 1]["time_beats"])
        if a < t1 <= b:
            values.append(float(bps[i + 1]["value"]))
            values.append(_segment_value(bps[i], bps[i + 1], 1.0))
    return min(values), max(values)


def holds_authored_curve(
    authored: Sequence[dict[str, Any]],
    live: Sequence[dict[str, Any]],
    *,
    time_eps: float,
    value_eps: float,
) -> bool:
    """Is what Live holds a step-sampling of the authored curve?

    Push sends a ramp as steps whose values sit ON the authored curve, and
    Live reads back one point per value change. So Live holds what push sent
    when:

    - before the envelope's first authored point, Live has at most ONE
      constant value. The read-back always starts at clip-local 0, and a ride
      authored mid-clip leaves that stretch at whatever Live holds unset.
      Two or more changes there is a ride someone added;
    - every value Live changes to after that sits on the authored curve at a
      beat within ``time_eps`` before the change was reported, because Live
      localizes a step up to one sampling interval late; and
    - every authored breakpoint is held just after its own beat.

    The step WIDTH is deliberately not part of the test. A staircase pushed
    at any resolution, or the bare authored points an older push wrote,
    passes; a step moved off the curve, a value added before the envelope, or
    a missing breakpoint fails.
    """
    lv = _step_changes(live)
    if not authored or not lv:
        return False
    first_t = float(authored[0]["time_beats"])
    pre = [c for c in lv if c[0] < first_t - time_eps]
    if len(pre) > 1:
        return False
    for t, v in lv[len(pre):]:
        lo, hi = _curve_range(authored, t - time_eps, t)
        if not (lo - value_eps <= v <= hi + value_eps):
            return False
    times = [t for t, _ in lv]
    for i, bp in enumerate(authored):
        t_b = float(bp["time_beats"])
        if i + 1 < len(authored) and float(authored[i + 1]["time_beats"]) == t_b:
            continue  # an instant jump: only the value it lands on is held
        k = bisect.bisect_right(times, t_b + time_eps) - 1
        if k < 0 or abs(lv[k][1] - float(bp["value"])) > value_eps:
            return False
    return True


def is_flat_at(values: Sequence[float], static_value: float | None) -> bool:
    """True when every value equals ``static_value`` — an envelope Live would
    discard on write, leaving a push that reported ok over nothing.

    Checked on the AUTHORED values: every curve here is monotone between its
    endpoints, so a staircase sampled from them is flat at ``static_value``
    exactly when the authored values are. ``None`` (the DB records no static
    value for the target) is never flat — nothing is known to compare with.
    """
    if static_value is None or not values:
        return False
    return all(
        math.isclose(float(v), float(static_value),
                     rel_tol=STATIC_MATCH_REL_TOL, abs_tol=STATIC_MATCH_ABS_TOL)
        for v in values
    )


__all__ = [
    "STAIRCASE_STEP_BEATS",
    "MAX_STAIRCASE_STEPS",
    "STATIC_MATCH_REL_TOL",
    "STATIC_MATCH_ABS_TOL",
    "segment_ramps",
    "has_ramp",
    "sample_authored_curve",
    "render_staircase",
    "holds_authored_curve",
    "wire_breakpoints",
    "is_flat_at",
]
