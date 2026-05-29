"""Shared core for the push package — types, constants, bar/beat helpers.

No imports from domain submodules (tempo / tracks / clips / mix / devices /
envelopes / arrangement / probe / plan) — keeps the package's import graph
acyclic. Domain submodules import from here, never the reverse.
"""
from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, field, asdict
from typing import Any

from hallucinote.return_naming import strip_return_slot_prefix
from hallucinote.db import mutations as M, queries as Q
from hallucinote.db.connection import transaction

# Live's default meter when a song has no `time_signature_map` rows.
_DEFAULT_NUMERATOR = 4
_DEFAULT_DENOMINATOR = 4


@dataclass
class ToolCall:
    """One MCP tool invocation. `key` lets results be matched back to ops.

    Names are *canonical* (post-Wave-1). Agent uses `mcp_names.resolve` to
    map onto today's surface.
    """
    tool: str
    args: dict[str, Any]
    key: str  # caller-chosen identifier; used in apply_push_results
    purpose: str = ""  # human-readable hint for the agent


@dataclass
class PushPlan:
    calls: list[ToolCall] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)  # human notes / warnings

    def add(self, call: ToolCall) -> None:
        self.calls.append(call)

    def warn(self, msg: str) -> None:
        self.notes.append(msg)

    def to_dict(self) -> dict[str, Any]:
        return {
            "calls": [asdict(c) for c in self.calls],
            "notes": self.notes,
        }


# ---------------------------------------------------------------------------
# Note conversion: DB -> MCP
# ---------------------------------------------------------------------------


def _beats_per_bar(numerator: int, denominator: int) -> float:
    """Live counts a beat as a quarter note regardless of meter, so the beat
    count per bar is `numerator * (4 / denominator)` (e.g., 6/8 -> 3 beats,
    7/4 -> 7 beats, 4/4 -> 4 beats)."""
    return numerator * (4.0 / denominator)


def _meter_at_bar(
    bar: float,
    ts_points: list[sqlite3.Row],
) -> tuple[int, int]:
    """Return (numerator, denominator) effective at a 1-based bar position.

    Empty ts_points fall back to 4/4. Bars before the first map point use the
    first point's meter — matches Live's behavior for unmarked regions.
    """
    if not ts_points:
        return (_DEFAULT_NUMERATOR, _DEFAULT_DENOMINATOR)
    chosen = ts_points[0]
    for p in ts_points:
        if p["start_bar"] <= bar:
            chosen = p
        else:
            break
    return (chosen["numerator"], chosen["denominator"])


def _split_bar(
    bar_pos: float,
    ts_points: list[sqlite3.Row],
) -> tuple[int, float]:
    """Split a 1-based fractional bar position into (bar_int, beat_within_bar).

    Matches the `(bar: int 1-based, beat: float 0-based-within-bar)` shape that
    Live's MCP tools use throughout. `bar_pos=4.5` in 4/4 -> (4, 2.0).
    """
    if bar_pos < 1.0:
        raise ValueError(
            f"bar_pos must be >= 1.0 per 1-based bar convention (got {bar_pos!r})"
        )
    bar_int = int(bar_pos)
    frac = bar_pos - bar_int
    num, den = _meter_at_bar(bar_pos, ts_points)
    return bar_int, frac * _beats_per_bar(num, den)


def _position_bar_to_beats(
    bar_pos: float,
    ts_points: list[sqlite3.Row],
) -> float:
    """Convert a 1-based fractional bar position to cumulative beats from song start.

    Live's arrangement time is measured in BEATS (quarter notes) regardless of
    meter — `position_beats` on every ableton_arrangement / ableton_clip
    arrangement-side action. Inverse-ish of :func:`_split_bar`: that returns
    ``(bar_int, beat_within_bar)``; this returns the total beats from bar 1's
    downbeat to the requested fractional bar.

    Walks the time_signature_map so meter changes accumulate correctly. Bars
    before ``ts_points[0].start_bar`` use ``ts_points[0]``'s meter (matches
    :func:`_meter_at_bar`'s fallback). Empty map → 4/4 throughout.

    Examples (in 4/4):
      - ``bar_pos=1.0`` -> 0.0
      - ``bar_pos=17.0`` -> 64.0    (16 bars × 4 beats)
      - ``bar_pos=17.5`` -> 66.0    (16 bars × 4 + half-bar = 2 beats)
    """
    if bar_pos < 1.0:
        raise ValueError(
            f"bar_pos must be >= 1.0 per 1-based bar convention (got {bar_pos!r})"
        )
    if not ts_points:
        return (bar_pos - 1.0) * _beats_per_bar(
            _DEFAULT_NUMERATOR, _DEFAULT_DENOMINATOR,
        )

    beats = 0.0
    current_bar = 1.0
    current_bpb = _beats_per_bar(
        ts_points[0]["numerator"], ts_points[0]["denominator"],
    )

    for p in ts_points:
        change_at = float(p["start_bar"])
        if change_at <= current_bar:
            # Already at or past this point's bar (the canonical case for
            # ts_points[0] when its start_bar == 1.0). Adopt this point's
            # meter; nothing to accumulate.
            current_bpb = _beats_per_bar(p["numerator"], p["denominator"])
            continue
        if bar_pos < change_at:
            return beats + (bar_pos - current_bar) * current_bpb
        beats += (change_at - current_bar) * current_bpb
        current_bar = change_at
        current_bpb = _beats_per_bar(p["numerator"], p["denominator"])

    return beats + (bar_pos - current_bar) * current_bpb


def _notes_for_mcp(notes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """DB notes carry tags + extra fields; MCP wants the bare quartet."""
    return [
        {
            "pitch": n["pitch"],
            "start_time": n["start_beats"],
            "duration": n["duration_beats"],
            "velocity": n["velocity"],
            "mute": bool(n["mute"]),
        }
        for n in notes
    ]


def _breakpoints_for_mcp(bps: list[sqlite3.Row]) -> list[dict[str, Any]]:
    """Convert DB breakpoint rows to the wire shape that
    ``ableton_automation(action='write_envelope')`` expects.

    Field renames: ``curve_kind`` → ``curve`` (the MCP-side handler uses
    ``curve`` to match its enum naming). DB-side keeps ``curve_kind`` since
    it disambiguates from other "kind" columns; the rename happens at the
    wire boundary.
    """
    return [
        {
            "time_beats": float(bp["time_beats"]),
            "value": float(bp["value"]),
            "curve": bp["curve_kind"],
        }
        for bp in bps
    ]
