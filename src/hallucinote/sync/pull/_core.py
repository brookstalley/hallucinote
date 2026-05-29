"""Shared core for the pull package: result dataclasses, float/diff helpers,
and bar/beat conversion utilities used by 2+ domain submodules.

Kept free of imports from the domain submodules (`mix`, `score`, `devices`,
`clips`, `notes`, `envelopes`, `plan`) so the package has no import cycle.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field, asdict
from typing import Any

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
    """
    mutations: int = 0
    no_ops: int = 0
    skipped_unlinked: int = 0
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


def _normalize_param_value(
    value: float, min_val: float, max_val: float, is_enum: bool,
) -> float | None:
    """Map Live's raw ``value`` into the DB's [0, 1] form.

    Returns ``None`` for enum/quantized params (schema CHECK allows
    NULL there — there's no continuous form). Also returns ``None``
    when ``min == max`` (constant-range params; the normalized form
    is undefined). Otherwise returns ``(value - min) / (max - min)``
    clamped into [0, 1] — Live's reported value can be marginally
    outside the documented range due to float, but the schema CHECK
    is strict on [0, 1] so we clamp at the boundary.
    """
    if is_enum:
        return None
    rng = max_val - min_val
    if abs(rng) < 1e-9:
        return None
    norm = (value - min_val) / rng
    return max(0.0, min(1.0, norm))


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


def _beats_per_bar(numerator: int, denominator: int) -> float:
    """Inverse helper to `push._beats_per_bar`: Live counts a beat as a quarter
    note regardless of meter, so beats-per-bar = numerator * (4 / denominator)."""
    return numerator * (4.0 / denominator)


def _join_bar_beat(
    bar: int,
    beat: float,
    ts_points: list[sqlite3.Row],
) -> float:
    """Inverse of `push._split_bar`: combine a 1-based bar int + 0-based beat
    float into a fractional `position_bar` using the song's time-signature
    map. Empty `ts_points` defaults to 4/4."""
    num, den = (4, 4)
    if ts_points:
        # Use the latest signature at-or-before this bar.
        chosen = ts_points[0]
        for p in ts_points:
            if p["start_bar"] <= bar:
                chosen = p
            else:
                break
        num, den = (chosen["numerator"], chosen["denominator"])
    return float(bar) + (float(beat) / _beats_per_bar(num, den))


def _is_numeric_id_name(s: Any) -> bool:
    """MCP gap #13 (legacy fork): `get_cue_points` returned numeric strings
    ('1', '2', ...) instead of the real names. The greenfield M-5 server's
    `ableton_arrangement(action='cue_list')` returns real names, but the
    detector stays as a defense against any agent-layer reformatting that
    might re-introduce numeric IDs.
    """
    return isinstance(s, str) and s.isdigit()


def _beats_to_position_bar(
    beats: float, ts_points: list[sqlite3.Row]
) -> float:
    """Walk the time-signature map to convert a beats-from-song-start
    position into a fractional bar position.

    Wave M-5: the wire format for cue positions is now `position_beats`
    (meter-agnostic, per principle 2). The DB stores `position_bar`. This
    helper bridges. For songs with no ts_points the assumption is 4/4
    throughout — same convention as the rest of the planner's bar math.
    """
    if not ts_points:
        # 4/4 fallback: 4 beats per bar, 1-based.
        return 1.0 + (float(beats) / 4.0)
    # Sort ts points by start_bar to walk forward.
    points = sorted(ts_points, key=lambda r: float(r["start_bar"]))
    # The first ts point should be at bar 1; if not, prepend a synthetic 4/4 at bar 1.
    if float(points[0]["start_bar"]) > 1.0 + 1e-9:
        first_bpb = 4.0  # 4/4 default for bars before the first explicit ts
    else:
        first_bpb = _beats_per_bar(
            int(points[0]["numerator"]), int(points[0]["denominator"])
        )

    cumulative_beats = 0.0
    current_bar = 1.0
    current_bpb = first_bpb

    for i, point in enumerate(points):
        point_bar = float(point["start_bar"])
        # Beats consumed up to this ts boundary (in the *previous* meter)
        bars_in_section = point_bar - current_bar
        beats_in_section = bars_in_section * current_bpb
        if cumulative_beats + beats_in_section > float(beats) - 1e-9:
            # Target beat is in this section.
            remaining = float(beats) - cumulative_beats
            return current_bar + (remaining / current_bpb)
        # Cross into the next section.
        cumulative_beats += beats_in_section
        current_bar = point_bar
        current_bpb = _beats_per_bar(
            int(point["numerator"]), int(point["denominator"])
        )

    # Beyond the last ts point — extrapolate in the current meter.
    remaining = float(beats) - cumulative_beats
    return current_bar + (remaining / current_bpb)


__all__ = [
    "_FLOAT_EPS",
    "PullCall",
    "PullPlan",
    "ApplyResult",
    "_floats_differ",
    "_normalize_param_value",
    "_normalized_values_match",
    "_bool_db",
    "_ints_differ",
    "_parse_signature",
    "_beats_per_bar",
    "_join_bar_beat",
    "_is_numeric_id_name",
    "_beats_to_position_bar",
]
