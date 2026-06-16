"""Shared core for the pull package: result dataclasses, float/diff helpers,
and bar/beat conversion utilities used by 2+ domain submodules.

Kept free of imports from the domain submodules (`mix`, `score`, `devices`,
`clips`, `notes`, `envelopes`, `plan`) so the package has no import cycle.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any

from ..geometry import (
    _beats_per_bar,
    _beats_to_position_bar,
    _join_bar_beat,
)

# Float tolerance for diff detection. 1e-3 means anything within ~0.1% of full
# scale is a no-op — covers Live's display-rounding (e.g. 0.6249 vs 0.6250)
# without papering over real moves.
_FLOAT_EPS = 1e-3


@dataclass
class PullCall:
    """One MCP *read* probe. `key` identifies what it pulls back; the apply
    layer dispatches on the `<kind>` prefix of `key`.

    Names are *canonical* (post-Wave-1 MCP). Agent uses `mcp_names.resolve` to
    map onto today's surface if needed.

    Expected `result` shape per key kind:
      - `session_info`           -> {master: {volume, panning}, tempo, signature, ...}
      - `returns_list`           -> [{index, name, volume, panning, ...}, ...]
      - `track_info:<track_id>`  -> {name, type, volume, panning, mute?, solo?,
                                     arm?, color?, ...}  (mixer fields)
      - `track_sends:<track_id>` -> {<return_name>: level, ...}
      - `track_output_routing:<track_id>` / `track_input_routing:<track_id>`
                                 -> {has_<dir>_routing, current_type,
                                     current_channel, available_types,
                                     available_channels}  (RTE-1K9T — the Live
                                     display_name is mapped back to a DB routing
                                     reference; see sync/routing_names.py)
      - `track_monitor:<track_id>`
                                 -> {has_monitoring_state,
                                     monitoring_state: 'In'|'Auto'|'Off'}
      - `device_sidechain_source:<device_id>`
                                 -> {has_input_routing, current_type,
                                     current_channel, available_types,
                                     available_channels}  (SDC-7K3M — the device
                                     input-routing display_name is resolved to a
                                     song-track FK and written via
                                     set_device_sidechain; same get_input_routing
                                     shape as track_input_routing)
      - `track_arrangement_clips:<track_id>`
                                 -> {track_index, location: 'arrangement',
                                     clips: [{arrangement_clip_index, name,
                                              start_beats, length}, ...]}
                                    (W3-4 / M+1-3b — per-track placements)
    """
    tool: str
    args: dict[str, Any]
    key: str
    purpose: str = ""


@dataclass
class PullPlan:
    calls: list[PullCall] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def add(self, call: PullCall) -> None:
        self.calls.append(call)

    def warn(self, msg: str) -> None:
        self.notes.append(msg)

    def to_dict(self) -> dict[str, Any]:
        return {
            "calls": [asdict(c) for c in self.calls],
            "notes": self.notes,
        }


@dataclass
class ApplyResult:
    """Summary of an `apply_pull_results` run.

    `details` carries one human-readable line per applied diff so the skill
    can show the user exactly what changed. `warnings` carries non-fatal
    things the user should know (unlinked Ableton rows, missing results, etc.).

    `unreadable` (PULL-DRIFT-DETECT) counts probes that FAILED or returned no
    payload — i.e. state the pull could not read. It is load-bearing: a run with
    `unreadable > 0` could NOT determine drift, so "couldn't read" must never be
    mistaken for "no drift" (the dangerous-twin: a version-skewed probe that
    silently degrades to `mutations: 0`). `pull_cli execute` exits non-zero when
    it is > 0.
    """
    mutations: int = 0
    no_ops: int = 0
    skipped_unlinked: int = 0
    unreadable: int = 0
    warnings: list[str] = field(default_factory=list)
    details: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _floats_differ(new: Any, existing: Any) -> bool:
    """Tolerant float compare.

    If `new` is None, the probe didn't report a value — no diff (caller should
    skip rather than write null). If `existing` is None and `new` is a value,
    that IS a real change (DB had no setting; Ableton has one). Otherwise
    diff iff the magnitude exceeds `_FLOAT_EPS`.
    """
    if new is None:
        return False
    if existing is None:
        return True
    return abs(float(new) - float(existing)) > _FLOAT_EPS


def _normalized_values_match(
    new: float | None, existing: Any,
) -> bool:
    """True iff ``new`` and ``existing`` represent the same
    normalized parameter value (both None, or floats within
    ``_FLOAT_EPS``). Mirrors :func:`_floats_differ`'s tolerance but
    treats both-None as equal (the enum-param case)."""
    if new is None and existing is None:
        return True
    if new is None or existing is None:
        return False
    return abs(float(new) - float(existing)) <= _FLOAT_EPS


def _bool_db(v: Any) -> int | None:
    """Normalize an MCP boolean into the DB's 0/1 int convention."""
    if v is None:
        return None
    return 1 if v else 0


def _ints_differ(new: Any, existing: Any) -> bool:
    """Same DB-None-vs-new-value asymmetry as `_floats_differ`."""
    if new is None:
        return False
    if existing is None:
        return True
    return int(new) != int(existing)


def _parse_signature(s: Any) -> tuple[int, int]:
    """Parse a `"N/D"` signature string. Raises ValueError on malformed input."""
    parts = str(s).split("/")
    if len(parts) != 2:
        raise ValueError(f"expected 'N/D', got {s!r}")
    num, den = int(parts[0]), int(parts[1])
    if num <= 0 or den <= 0:
        raise ValueError(f"signature {s!r}: numerator/denominator must be positive")
    return num, den


def _is_numeric_id_name(s: Any) -> bool:
    """MCP gap #13 (legacy fork): `get_cue_points` returned numeric strings
    ('1', '2', ...) instead of the real names. The greenfield M-5 server's
    `ableton_arrangement(action='cue_list')` returns real names, but the
    detector stays as a defense against any agent-layer reformatting that
    might re-introduce numeric IDs.
    """
    return isinstance(s, str) and s.isdigit()


__all__ = [
    "_FLOAT_EPS",
    "PullCall",
    "PullPlan",
    "ApplyResult",
    "_floats_differ",
    "_normalized_values_match",
    "_bool_db",
    "_ints_differ",
    "_parse_signature",
    "_beats_per_bar",
    "_join_bar_beat",
    "_is_numeric_id_name",
    "_beats_to_position_bar",
]
