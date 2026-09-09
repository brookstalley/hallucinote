"""Shared core for the push package — types, constants, bar/beat helpers.

No imports from domain submodules (tempo / tracks / clips / mix / devices /
envelopes / arrangement / probe / plan) — keeps the package's import graph
acyclic. Domain submodules import from here, never the reverse.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field, asdict
from typing import Any

# Re-exported (redundant aliases): the geometry helpers lived in the original
# push.py, and the package __init__ + domain submodules still import them from
# here — part of the preserved public surface of the push.py split.
from ..geometry import (
    _DEFAULT_NUMERATOR as _DEFAULT_NUMERATOR,
    _DEFAULT_DENOMINATOR as _DEFAULT_DENOMINATOR,
    _beats_per_bar as _beats_per_bar,
    _meter_at_bar as _meter_at_bar,
    _split_bar as _split_bar,
    _position_bar_to_beats as _position_bar_to_beats,
    uniform_bar_math_divergences as uniform_bar_math_divergences,
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
    # Per-call socket read ceiling, in seconds (ENV-8K2R #5). ``None`` =
    # defer to the client's (tool, action) read-timeout policy (the default
    # for every call). A planner sets an explicit value only when it can
    # derive a *better* bound than the static policy — e.g. perform_batch,
    # whose policy is intentionally UNBOUNDED (a fixed timeout would sever its
    # verification) but which the planner caps at a union-span-derived ceiling
    # so a dead worker can't block the push forever. The executor forwards it
    # to ``client.send(read_timeout=...)`` only when set.
    read_timeout: float | None = None


@dataclass
class PushPlan:
    calls: list[ToolCall] = field(default_factory=list)
    # Internal/benign planner notes (e.g. "no tempo_map rows; nothing to push",
    # "not linked yet; rerun after apply"). Diagnostic only — NOT surfaced to
    # the operator. Use `alert()` for anything the operator must see.
    notes: list[str] = field(default_factory=list)
    # Hard authoring errors (SYN-6B4Q): a planner sets these when the DB
    # describes something that can never be materialized in Live (e.g. a cue
    # past the composed song length), as opposed to a `note` ("skipped a row,
    # the agent decides"). The executor HALTS a phase whose plan carries
    # errors — without dispatching any of its calls — so the operator gets a
    # clear, DB-grounded message instead of an opaque runtime failure.
    errors: list[str] = field(default_factory=list)
    # Operator-actionable, NON-fatal warnings (SYN-9F2L): a planner sets these
    # when it had to skip something the operator authored and would want to
    # know about — e.g. a params_dialed write with no writable form ("the
    # dialed intent was NOT pushed"). Distinct from `notes` (diagnostic noise
    # the operator shouldn't see) and from `errors` (which halt). The executor
    # drains alerts into the push report's benign warnings channel; the push
    # still completes (exit 0). Severity-, not phase-, scoped: any planner can
    # raise one and it surfaces.
    alerts: list[str] = field(default_factory=list)
    # PSH-ARRPROBE: work the planner did NOT plan because it could not
    # DETERMINE the state it needed (a failed probe, a missing link) — as
    # opposed to work there was genuinely none of. The distinction is the whole
    # point: "nothing to do" is a clean skip; "could not determine, so did
    # nothing" is an INCOMPLETE push that must not report OK. The executor marks
    # any phase whose plan carries these `incomplete` and flips the run's
    # outcome + exit code; nothing halts (sibling tracks and later phases still
    # run — the work that COULD be determined still lands).
    #
    # Every blocked reason is ALSO an alert (it is operator-actionable by
    # definition — :meth:`blocked` appends to both), so alert-shaped consumers
    # keep seeing it; `blocked_reasons` is the strictly-stronger subset. The
    # executor drains alerts MINUS blocked reasons into the benign
    # "push still OK" channel, so a blocked reason is never labeled benign.
    blocked_reasons: list[str] = field(default_factory=list)

    def add(self, call: ToolCall) -> None:
        self.calls.append(call)

    def warn(self, msg: str) -> None:
        self.notes.append(msg)

    def error(self, msg: str) -> None:
        self.errors.append(msg)

    def alert(self, msg: str) -> None:
        self.alerts.append(msg)

    def blocked(self, msg: str) -> None:
        """Record work skipped because its precondition could not be DETERMINED.

        Strictly stronger than :meth:`alert` (which it also records): a blocked
        reason makes the push report INCOMPLETE with a non-zero exit, because
        the song did not get something it asked for. Use :meth:`warn` for a
        deliberate, known-scope no-op (e.g. audio tracks, CLP-AUD2) and
        :meth:`error` for authoring Live can NEVER materialize (that halts the
        phase before dispatch).
        """
        self.blocked_reasons.append(msg)
        self.alerts.append(msg)

    def to_dict(self) -> dict[str, Any]:
        return {
            "calls": [asdict(c) for c in self.calls],
            "notes": self.notes,
            "errors": self.errors,
            "alerts": self.alerts,
            "blocked_reasons": self.blocked_reasons,
        }


# ---------------------------------------------------------------------------
# Note conversion: DB -> MCP
# ---------------------------------------------------------------------------


def build_node_addr(
    parent_kv: dict[str, Any],
    *,
    device_index: int | None = None,
    device_path: list[dict[str, int]] | None = None,
    terminal: str = "device",
    chain_index: int | None = None,
) -> dict[str, Any]:
    """Build the NODE-ADDR ``node`` wire object (the single addressing unit)
    from the planner's flat ``parent_kv`` (``{"track_index": n}`` /
    ``{"return_index": n}`` / ``{"master": True}``) + the device address.

    The DB→wire translation point for the migrated actions (set_parameter /
    load / set_sidechain / write_envelope+perform device_parameter). Songs'
    build.py never sees this — they author the DB; push translates DB→wire here.
    The shape matches ``handlers.device.validate_node_addr``: ``terminal``
    defaults to ``"device"`` (and is then omitted from the wire); a
    track/return/master terminal is a node-itself address (no device_index); a
    ``chain`` terminal carries device_index + chain_index.
    """
    if parent_kv.get("master"):
        parent: dict[str, Any] = {"kind": "master"}
    elif "track_index" in parent_kv:
        parent = {"kind": "track", "index": parent_kv["track_index"]}
    elif "return_index" in parent_kv:
        parent = {"kind": "return", "index": parent_kv["return_index"]}
    else:
        raise ValueError(
            f"build_node_addr: parent_kv must carry master / track_index / "
            f"return_index, got {parent_kv!r}"
        )
    node: dict[str, Any] = {"parent": parent}
    if terminal != "device":
        node["terminal"] = terminal
    if terminal in ("device", "chain"):
        node["device_index"] = device_index
        if device_path:
            node["path"] = device_path
    if terminal == "chain":
        node["chain_index"] = chain_index
    return node


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
