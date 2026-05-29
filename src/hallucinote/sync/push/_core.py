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
from ..geometry import (
    _DEFAULT_NUMERATOR,
    _DEFAULT_DENOMINATOR,
    _beats_per_bar,
    _meter_at_bar,
    _split_bar,
    _position_bar_to_beats,
)


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
