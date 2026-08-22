"""W10-E2: bulk push dispatcher that bypasses the agent's tool-use channel.

The fourteen-phase push planner emits plans the agent has historically dispatched
itself via MCP tool calls. For large songs that's the v1.0 ceiling: each call
ships its full args (notably ``notes=[…]``) as inline JSON inside the agent's
tool-use block, burning agent context budget per call. A 29-clip song measured
at ~500 KB carried across calls.

This module dispatches the same plan calls directly against Live's Remote
Script via :func:`hallucinote_mcp.client.send`. The agent invokes ``push_cli
execute`` once via Bash; bytes never enter its context.

Design lives at :file:`.prawduct/artifacts/push-execute-design.md`. The two
load-bearing decisions:

* **Phase-bounded error accumulation.** Within a phase, run every call and
  collect errors. At phase boundary, halt if any call failed — phases are
  real dependency boundaries (tracks before clips before notes), so plowing
  past a broken phase manufactures cascading failures.
* **No internal retry.** Re-running ``execute`` is the retry — push is
  idempotent (W10-A), so already-applied rows skip on re-run. Internal
  retry hides intermittent bugs.
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from hallucinote.db import mutations as M
from hallucinote.db import queries as Q
from hallucinote.paths import SONG_DIR_IGNORED_FILES, self_ignore_files
from hallucinote.sync import push
from hallucinote.sync.push.empty_rack_guard import (
    _parent_key,
    partition_doomed_nested_writes,
)

logger = logging.getLogger(__name__)

# Imported lazily inside execute_push() to keep the unit-test import graph
# light. The MCP package is a sibling install; tests substitute send_fn
# directly and never touch it.


# Exit codes — documented in the design artifact.
EXIT_OK = 0
EXIT_PARTIAL = 1
EXIT_CONNECTION_LOST = 2


# PSH-3K9D chunk 2: emit a mid-phase progress heartbeat every this-many dispatched
# calls — to stderr and into .last-push-state.json — so a phase issuing many calls
# is observable (a slow phase and a hung one stop looking identical to a poller).
_HEARTBEAT_EVERY = 25


# Phase status values written into .last-push-state.json. Mirrors the design
# doc's table.
_STATUS_OK = "ok"
_STATUS_SKIPPED = "skipped"
_STATUS_HALTED = "halted"
_STATUS_PENDING = "pending"
# PSH-ARRPROBE: the phase ran but could NOT determine part (or all) of what it
# was asked to do, so it deliberately did nothing there — distinct from
# _STATUS_SKIPPED ("nothing to do"), which is a clean, idempotent no-op. The
# reasons come from ``PushPlan.blocked_reasons``. An incomplete phase does NOT
# halt the run (the work that COULD be determined still lands, and later phases
# still run) but it DOES flip the terminal outcome off "ok" and the exit code
# off zero — a push that left the song un-materialized must never read clean.
_STATUS_INCOMPLETE = "incomplete"


# args_summary redaction: keys whose values are list-shaped and potentially
# large get collapsed to ``<key>_count``. Anything else (scalars, short
# strings, small dicts) passes through. Tuned for the calls actually emitted
# by push.py — extend if a new planner adds a new large-payload key.
_LARGE_LIST_KEYS = frozenset({
    "notes",         # ableton_clip(create), ableton_clip(replace_notes)
    "breakpoints",   # ableton_automation(write_envelope) — envelope curves
    "value_points",  # ableton_session(set_tempo_map) — tempo points
    "points",        # ableton_session(set_time_signature_map)
    "cues",          # ableton_arrangement(set_cues), if it lands
})


class PhaseTargetError(ValueError):
    """A phase-targeting flag named an unknown phase or an invalid combination.

    Raised by :func:`validate_phase_targets`; the CLI catches it and exits 2
    with the teaching message (which lists the valid phases in order).
    """


def validate_phase_targets(
    names: list[str],
    *,
    only: str | None = None,
    start_at: str | None = None,
    stop_after: str | None = None,
) -> None:
    """Validate the phase-targeting flags against the canonical phase NAME list.

    Pure (no Live, no slicing) so the CLI can call it BEFORE any Live probe
    (PSH-PHASEORDER): a typo'd ``--only``/``--start-at``/``--stop-after``
    shouldn't pay a coherence + arrangement round-trip — or be masked by a
    stale-link coherence refusal — before being rejected. :func:`_filter_phases`
    delegates here so the rule lives in one place.

    Raises :class:`PhaseTargetError` (teaching message + valid-phase list) on an
    unknown phase name, ``--only`` combined with a window flag, or a window whose
    stop precedes its start.
    """
    def _check(flag: str, value: str | None) -> None:
        if value is not None and value not in names:
            raise PhaseTargetError(
                f"unknown {flag} phase {value!r}. Valid phases (in order): "
                + ", ".join(names)
            )

    _check("--only", only)
    _check("--start-at", start_at)
    _check("--stop-after", stop_after)

    if only is not None and (start_at is not None or stop_after is not None):
        raise PhaseTargetError(
            "--only cannot be combined with --start-at/--stop-after"
        )

    if start_at is not None and stop_after is not None:
        if names.index(stop_after) < names.index(start_at):
            raise PhaseTargetError(
                f"--stop-after {stop_after!r} precedes --start-at {start_at!r} "
                "in the phase order"
            )


def _filter_phases(
    phases,
    *,
    only: str | None = None,
    start_at: str | None = None,
    stop_after: str | None = None,
):
    """Slice the planned phase list for PSH-2R7K phase-targeting.

    Order-agnostic: filters by phase NAME against the list it's handed, so it
    composes with any future reordering of the phase sequence (RTE-2P9X) without
    assuming indices. Returns ``(filtered_phases, scope)`` where ``scope`` is a
    JSON-friendly dict describing the filter (or ``None`` for a full run) recorded
    into ``.last-push-state.json`` so a scoped run is never mistaken for a full one.

    Validation (unknown name, ``--only`` + window, stop-before-start) is delegated
    to :func:`validate_phase_targets` — the same check the CLI runs up front before
    any Live probe (PSH-PHASEORDER), so a scoped execute and a pre-probe reject
    share one rule.
    """
    names = [p.name for p in phases]
    validate_phase_targets(
        names, only=only, start_at=start_at, stop_after=stop_after,
    )

    if only is not None:
        return tuple(p for p in phases if p.name == only), {"only": only}

    lo = names.index(start_at) if start_at is not None else 0
    hi = names.index(stop_after) if stop_after is not None else len(names) - 1
    sliced = tuple(phases[lo:hi + 1])
    scope: dict[str, str] | None = None
    if start_at is not None or stop_after is not None:
        scope = {}
        if start_at is not None:
            scope["start_at"] = start_at
        if stop_after is not None:
            scope["stop_after"] = stop_after
    return sliced, scope


@dataclass
class PhaseOutcome:
    name: str
    status: str  # one of _STATUS_*
    calls_ok: int = 0
    calls_failed: int = 0
    calls_planned: int = 0  # for pending phases — how many they would have run
    # A3: post-phase pad probing for the devices phase. Per-device best-effort —
    # failures do NOT halt the phase or affect the overall push outcome. Counts
    # are zero on phases where the probe doesn't run (every phase except the
    # devices phase, or a devices phase with no linked Drum Rack devices).
    pad_probes_ok: int = 0
    pad_probes_failed: int = 0
    # PSH-ARRPROBE: why this phase could not do (part of) its job — verbatim
    # from ``PushPlan.blocked_reasons``. Drives ``_STATUS_INCOMPLETE``, and is
    # carried on a HALTED phase too so a halt can't swallow the planner's
    # reason. Rides the state file + the summary so the operator reads WHY, not
    # just that something is missing.
    blocked_reasons: list[str] = field(default_factory=list)


@dataclass
class ExecuteResult:
    """Returned to the CLI for stdout summarization. Mirrors the on-disk state
    file contents minus the per-error detail (those go in errors_file)."""
    # "ok" | "incomplete" | "partial" | "connection_lost". "incomplete"
    # (PSH-ARRPROBE) means every phase RAN without failing a call, but at least
    # one could not determine part of its work and honestly skipped it — the
    # push did not halt, yet the song is not fully materialized.
    outcome: str
    exit_code: int
    phase_halted: str | None
    phases: list[PhaseOutcome] = field(default_factory=list)
    state_file: Path | None = None
    errors_file: Path | None = None
    top_error_patterns: list[dict[str, Any]] = field(default_factory=list)
    # SYN-6B4Q: benign warnings that did NOT fail the push (exit stays 0) —
    # e.g. cues deferred past Live's current arrangement extent, which land on
    # the next push. Kept distinct from errors so a deferral never reads as a
    # PARTIAL halt cause.
    warnings: list[str] = field(default_factory=list)


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _summarize_args(args: dict[str, Any]) -> dict[str, Any]:
    """Strip large list payloads to counts; keep scalars + short fields.

    The whole point of execute is that the agent doesn't see the bulk payload,
    so the error file (which the agent DOES read) must not reintroduce it.
    """
    out: dict[str, Any] = {}
    for k, v in args.items():
        if k in _LARGE_LIST_KEYS and isinstance(v, list):
            out[f"{k}_count"] = len(v)
        elif isinstance(v, list) and len(v) > 5:
            # Generic safety net for unexpected large arrays.
            out[f"{k}_count"] = len(v)
        else:
            out[k] = v
    return out


# ---------------------------------------------------------------------------
# M1-B: cross-machine device-load fallback
# ---------------------------------------------------------------------------
#
# When a `device.load` call carries a `preset_uri` captured on the author's
# machine and that URI is not resolvable on the consumer's machine (Live
# FileIds differ across installs), the executor falls back to an MCP
# `ableton_browser(action='search')` keyed on the device's `display_name`
# and retries the load with the first match's URI. The subsequent
# parameter-write phase fires unchanged against the fallback device, so
# the dialed parameter state still lands.
#
# This is NOT generic retry (the module docstring's "no internal retry"
# rule still holds) — it's a one-shot URI substitution that addresses a
# structural cross-machine mismatch, not a transient error.

# Error-message substrings that indicate a preset_uri resolution miss.
# When the original load fails with a message containing any of these,
# the fallback is attempted. Other failure modes (instrument-on-return
# preconditions, connection drops, etc.) skip the fallback unchanged.
_PRESET_URI_MISS_HINTS = (
    "preset_uri",
    "no loadable browser item",
)

# SYN-2D9K: substrings that mark a set_parameter failure as "this parameter is
# not on the device" (the orphan-from-class-change shape), distinct from a
# value-range refusal.
_PARAM_NOT_FOUND_HINTS = ("not found",)

# Live's refusal when a parameter exists and reads fine but cannot be written —
# macro-mapped, or otherwise locked. Matched on the message because the wire
# carries a RuntimeError string, not a typed code. Kept narrow on purpose: this
# tolerates ONLY the disabled case, never a value-range or missing-param
# refusal, both of which are real defects a push should still halt on.
_PARAM_DISABLED_HINT = "parameter is disabled"


def _is_tolerated_failure(
    *, tool: str, action: str | None, err_msg: str | None,
) -> bool:
    """Is this failure a no-op Live refused, rather than a real defect?

    Exactly one case qualifies: a chain-mixer write refused because the
    parameter is DISABLED (macro-mapped or otherwise locked). Such a parameter
    cannot be changed by us, by the user in Live's UI, or by anything else — so
    the DB's value can never audibly diverge, there is nothing a retry or a
    human could fix, and halting a fourteen-phase push over it is wrong.

    Everything else stays fatal. In particular a value-RANGE refusal and a
    missing-parameter refusal are real defects that must still halt: they mean
    the song is asking for something the device cannot do, which is exactly
    what a push is supposed to catch.
    """
    return (
        tool == "ableton_device"
        and action == "set_chain_property"
        and bool(err_msg)
        and _PARAM_DISABLED_HINT in (err_msg or "")
    )


def _orphan_param_hint(
    *, tool: str, action: str | None, err_msg: str | None,
    parameter_name: object,
) -> str | None:
    """SYN-2D9K: a ``set_parameter`` that 404s on a parameter the device does
    not have is almost always a STALE ORPHAN — a prior device class's param
    lingering in ``device_parameters`` after the instrument was swapped (e.g.
    Operator -> Analog). The MCP hint points at value-range debugging, which
    sends the operator hunting a phantom. Return a hint naming the real cause +
    the cure, or ``None`` when the failure is not that shape."""
    if tool != "ableton_device" or action != "set_parameter" or not err_msg:
        return None
    if not any(h in err_msg for h in _PARAM_NOT_FOUND_HINTS):
        return None
    pname = f"{parameter_name!r} " if parameter_name else ""
    return (
        f"parameter {pname}is not on this device — most likely a stale orphan "
        "from a device-class change (the DB still carries a prior class's "
        "params). Rebuild the song (a rebuild now prunes orphans, SYN-2D9K) to "
        "clear it; if it persists, the snapshot's device class may not match Live."
    )


def _search_root_for_kind(kind: str, class_name: str | None = None) -> str:
    """Pick the canonical browser root for a fallback search by device kind.

    Arc 4 / D4: ``kind`` is the browser display name (= Live's
    ``device.class_display_name``). The internal Live class lives in
    ``class_name`` (separate DB column). Plugin discrimination keys off
    ``class_name`` — Live wraps every plugin in one of three classes
    (``PluginDevice`` / ``AuPluginDevice`` / ``Vst3PluginDevice``);
    these never appear as ``kind`` under the post-D4 convention because
    ``kind`` is the plugin's browser display name (e.g. ``"Serum"``).
    The substring-'Plugin' check moves to ``class_name``. Drum racks
    still recognize via the rack display name; everything else
    defaults to ``instruments``.
    """
    if class_name and "Plugin" in class_name:
        return "plugins"
    if kind == "Drum Rack":
        return "drums"
    return "instruments"


def _attempt_load_fallback(
    *,
    failed_call: Any,
    conn: sqlite3.Connection,
    send_fn: Callable[..., Any],
    request_cls: type,
) -> tuple[Any, str] | None:
    """Try a cross-machine fallback for a failed ``device.load`` call.

    Returns ``(retry_response, fallback_uri)`` if the search-then-load
    fallback succeeded; ``None`` if no fallback was attempted (call shape
    didn't qualify) or the fallback didn't find a match.

    The fallback fires only when:
    1. The call is ``ableton_device(action='load')``.
    2. The call carried a ``preset_uri`` (kind-only loads have no
       per-machine URI to miss, so the original error already covers
       them).
    3. The call key identifies a device row in the DB (``device:<uuid>``).
    4. The device row has a non-empty ``display_name`` to search by.
    5. The search call itself succeeds and returns at least one match
       with a non-empty URI.
    6. The retry load with the fallback URI succeeds.
    """
    if failed_call.tool != "ableton_device":
        return None
    if failed_call.args.get("action") != "load":
        return None
    if not failed_call.args.get("preset_uri"):
        return None
    key = failed_call.key or ""
    if not key.startswith("device:"):
        return None
    device_id = key.split(":", 1)[1]
    row = conn.execute(
        "SELECT kind, display_name, class_name FROM devices WHERE id = ?",
        (device_id,),
    ).fetchone()
    if row is None:
        return None
    kind = row["kind"]
    class_name = row["class_name"] if "class_name" in row.keys() else None
    display_name = (row["display_name"] or "").strip()
    if not display_name:
        return None

    root = _search_root_for_kind(kind, class_name)
    search_req = request_cls(
        tool="ableton_browser",
        action="search",
        params={
            "pattern": display_name,
            "root": root,
            "loadable_only": True,
            "mode": "substring",
            "limit": 5,
        },
    )
    try:
        search_resp = send_fn(search_req)
    except Exception:  # prawduct:allow prawduct/broad-except -- fallback must not crash the push loop; failure → no fallback
        logger.debug(
            "load-fallback search failed for %r — no fallback",
            display_name, exc_info=True,
        )
        return None
    if not bool(getattr(search_resp, "ok", False)):
        return None
    matches = (getattr(search_resp, "result", None) or {}).get("matches") or []
    fallback_uri = ""
    for m in matches:
        uri = m.get("uri") if isinstance(m, dict) else None
        if uri:
            fallback_uri = uri
            break
    if not fallback_uri:
        return None

    retry_args = {k: v for k, v in failed_call.args.items() if k != "action"}
    retry_args["preset_uri"] = fallback_uri
    retry_req = request_cls(
        tool=failed_call.tool, action="load", params=retry_args,
    )
    try:
        retry_resp = send_fn(retry_req)
    except Exception:  # prawduct:allow prawduct/broad-except -- fallback must not crash the push loop; failure → no fallback
        logger.debug(
            "load-fallback retry (uri=%s) failed — no fallback",
            fallback_uri, exc_info=True,
        )
        return None
    if not bool(getattr(retry_resp, "ok", False)):
        return None
    return retry_resp, fallback_uri


# SYN-9F2L: the planner prefers the display form on the wire (exact via the
# param's own display curve), but several handler refusals have a known second
# form worth one retry each. Hint substrings match the handler's teaching
# errors (handlers/display_value.py resolve_continuous_write).
_SET_PARAM_ENUM_HINTS = ("is an enum", "is_quantized=True")
# Refusals whose remedy is "fall back to the stored normalized value": the param
# exposes no str_for_value curve to invert, OR its display can't address it —
# non-numeric (a pan's "50L".."50R" — SYN-RACK-PRESET-RELINK §3), non-monotonic,
# or constant. The display-can't-address family all end in "the normalized
# `value`"; matching that recovers them via the same normalized retry instead of
# 5 guaranteed pan failures on every push of a track with a dialed Analog pan.
_SET_PARAM_NO_CURVE_HINTS = ("str_for_value", "the normalized `value`")


def _attempt_set_parameter_fallback(
    *,
    failed_call: Any,
    conn: sqlite3.Connection,
    send_fn: Callable[..., Any],
    request_cls: type,
    err_msg: str,
) -> tuple[Any, str] | None:
    """One-shot retries for a refused ``value_display`` write (SYN-9F2L).

    Returns ``(retry_response, fallback_kind)`` on success, ``None`` when no
    fallback applies or the retry failed (original error stands). Two cases:

    * the handler refused because the parameter is actually an enum
      (hand-authored snapshots store enum choices as bare display strings,
      with no ``value_items`` captured) → retry as ``value_type='enum'``
      with the display string as the value;
    * the handler refused because the parameter exposes no ``str_for_value``
      curve to invert → retry with the DB's stored normalized value (the
      pre-SYN-9F2L wire form).
    """
    if failed_call.tool != "ableton_device":
        return None
    args = failed_call.args
    if args.get("action") != "set_parameter":
        return None
    if args.get("value_display") is None:
        return None
    base = {
        k: v for k, v in args.items()
        if k not in ("action", "value_display", "value", "value_type")
    }
    if any(h in err_msg for h in _SET_PARAM_ENUM_HINTS):
        retry_params = {
            **base, "value": args["value_display"], "value_type": "enum",
        }
        fallback_kind = "enum"
    elif any(h in err_msg for h in _SET_PARAM_NO_CURVE_HINTS):
        key = failed_call.key or ""
        parts = key.split(":", 2)
        if len(parts) != 3 or parts[0] != "device_parameter":
            return None
        _, device_id, param_name = parts
        row = next(
            (
                p for p in Q.get_device_parameters(conn, device_id)
                if p["name"] == param_name
            ),
            None,
        )
        if row is None or row["value_normalized"] is None:
            return None
        retry_params = {
            **base,
            "value": str(row["value_normalized"]),
            "value_type": "continuous",
        }
        fallback_kind = "normalized"
    else:
        return None
    retry_req = request_cls(
        tool=failed_call.tool, action="set_parameter", params=retry_params,
    )
    try:
        retry_resp = send_fn(retry_req)
    except Exception:  # prawduct:allow prawduct/broad-except -- fallback must not crash the push loop; failure → no fallback
        logger.debug(
            "set_parameter %s-fallback retry failed — no fallback",
            fallback_kind, exc_info=True,
        )
        return None
    if not bool(getattr(retry_resp, "ok", False)):
        return None
    return retry_resp, fallback_kind


def _probe_pad_mappings_for_session(
    *,
    conn: sqlite3.Connection,
    session_id: str,
    send_fn: Callable[..., Any],
    request_cls: Any,
    actor: str,
    request_id: str | None,
    reason: str | None,
) -> tuple[int, int]:
    """A3: walk every Drum Rack device fully linked in this session, probe
    its pad layout via ``ableton_device(action='pad_info', ...)``, and
    persist the result via :func:`M.replace_drum_pad_mappings`.

    Best-effort by design. The push's primary purpose — materializing the
    song's structural state in Live — already succeeded for this phase
    when this helper runs. Pad probing is auxiliary metadata for the
    composer (so ``Kit.from_device`` returns kit-specific notes instead of
    GM defaults next build cycle). A per-device failure (connection drop,
    handler error, mutator validation rejection) increments the failed
    counter and skips that device; the next push retries.

    The mutator ``M.replace_drum_pad_mappings`` is already idempotent — if
    the kit's pads haven't changed since the last probe, this is a no-op.
    That makes repeated invocations across re-pushes cheap.

    Returns ``(probes_ok, probes_failed)``. A row with missing addressing
    (parent or device index not yet linked for this session) is skipped
    silently — it counts as neither ok nor failed, just deferred to the
    next probe pass after the link lands.
    """
    probes_ok = 0
    probes_failed = 0
    for row in Q.get_linked_drum_racks_for_session(conn, session_id):
        device_id = row["device_id"]
        parent_kind = row["parent_kind"]
        parent_idx = row["parent_ableton_index"]
        device_idx = row["device_ableton_index"]
        if parent_idx is None or device_idx is None:
            # Drum Rack in DB but not yet bound in Live for this session
            # (devices phase didn't link it, or capture-only flow). The
            # probe needs a live address — skip silently; the next push
            # that links the device will probe it.
            continue
        params: dict[str, Any] = {"device_index": device_idx}
        if parent_kind == "track":
            params["track_index"] = parent_idx
        else:
            params["return_index"] = parent_idx
        try:
            resp = send_fn(request_cls(
                tool="ableton_device", action="pad_info", params=params,
            ))
        except Exception:  # prawduct:allow prawduct/broad-except -- best-effort post-phase probe; connection or wire errors must not derail an otherwise-successful push
            logger.debug(
                "pad-probe send failed for device %s on %s %s — counted, skipped",
                device_id, parent_kind, parent_idx, exc_info=True,
            )
            probes_failed += 1
            continue
        if not bool(getattr(resp, "ok", False)):
            logger.debug(
                "pad-probe refused for device %s on %s %s: %s",
                device_id, parent_kind, parent_idx,
                getattr(resp, "error", None),
            )
            probes_failed += 1
            continue
        payload = getattr(resp, "result", None) or {}
        pads = payload.get("pads") or []
        mappings = [
            {"chain_name": p["chain_name"], "midi_note": int(p["note"])}
            for p in pads
            if p.get("chain_name") and p.get("note") is not None
        ]
        try:
            M.replace_drum_pad_mappings(
                conn,
                device_id=device_id,
                mappings=mappings,
                actor=actor,
                request_id=request_id,
                reason=reason or f"push pad-probe (session={session_id})",
            )
        except Exception:  # prawduct:allow prawduct/broad-except -- mutator validation (e.g. midi_note out of range from a malformed handler response) shouldn't halt the post-phase probe
            logger.debug(
                "pad-probe mapping write failed for device %s — counted, skipped",
                device_id, exc_info=True,
            )
            probes_failed += 1
            continue
        probes_ok += 1
    return probes_ok, probes_failed


def _group_errors(errors: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group error records by message substring for pattern-spotting.

    The substring is the first 60 chars of the error message — long enough
    to disambiguate distinct failures, short enough that ``RuntimeError:
    Couldn't create clip — slot 3`` and ``... slot 7`` group together.

    Each group also carries a representative ``tool``/``action`` (the first
    record's) and the first non-null ``hint`` in the group, so the CLI
    summary can name the halt cause without the agent opening the errors
    file (PSH-4E2W).
    """
    groups: dict[str, list[dict[str, Any]]] = {}
    for e in errors:
        substr = (e.get("error") or "")[:60]
        groups.setdefault(substr, []).append(e)
    return [
        {
            "error_substring": substr,
            "count": len(recs),
            "affected_keys": [r["key"] for r in recs],
            "tool": recs[0].get("tool"),
            "action": recs[0].get("action"),
            "hint": next((r.get("hint") for r in recs if r.get("hint")), None),
        }
        for substr, recs in sorted(groups.items(), key=lambda kv: -len(kv[1]))
    ]


def _suggest_next_step(pattern: dict[str, Any], *, outcome: str) -> str:
    """One actionable line per halt cause (PSH-4E2W).

    Prefer the responder's own hint — it knows the cause better than any
    heuristic here. Fall back to a per-class suggestion so the summary
    always says what to do next, not just what broke.
    """
    if pattern.get("hint"):
        return str(pattern["hint"])
    if outcome == "connection_lost":
        return (
            "check Live is running with the Hallucinote control surface "
            "loaded, then re-run execute (idempotent)"
        )
    if pattern.get("tool") == "ableton_device" and pattern.get("action") == "load":
        return (
            "device failed to load — likely not installed on this machine; "
            "see REQUIREMENTS.md"
        )
    return (
        "fix the cause in build.py / the snapshot, rebuild, then re-run "
        "execute (idempotent — applied rows skip)"
    )


def execute_push(
    *,
    conn: sqlite3.Connection,
    song_id: str,
    session_id: str,
    state_dir: Path,
    send_fn: Callable[..., Any] | None = None,
    actor: str = "sync",
    reason: str | None = None,
    perform_slowdown_factor: float = 1.0,
    only: str | None = None,
    start_at: str | None = None,
    stop_after: str | None = None,
    progress_fn: Callable[[str], None] | None = None,
    live_arrangement_clips_by_track: push.LiveArrangementProbe = None,
) -> ExecuteResult:
    """Run the full fourteen-phase push, dispatching each call via ``send_fn``.

    ``send_fn`` defaults to :func:`hallucinote_mcp.client.send`. Tests pass
    their own to avoid touching the MCP package or Live.

    State + errors files are written into ``state_dir``. Caller (CLI) chooses
    the directory — defaults to the song's DB directory when invoked via
    ``--song <slug>``.

    Returns an :class:`ExecuteResult`. Side effects:

    * Successful results in each phase are applied to the DB via
      :func:`push.apply_push_results` (so later phases see updated
      ``ableton_links`` rows).
    * Writes ``<state_dir>/.last-push-state.json`` always.
    * Writes ``<state_dir>/.last-push-errors.json`` only when there's at
      least one per-call error or a connection drop.

    ``live_arrangement_clips_by_track`` accepts a dict OR a zero-arg thunk
    (:data:`push.LiveArrangementProbe`). Callers that probe Live should pass the
    THUNK: it is resolved inside the arrangement phase's planner, i.e. AFTER the
    `tracks` phase has created the song's Live tracks. See
    :func:`push.plan_push_song` for why an eagerly-probed map is wrong on a
    first push.

    Outcome (PSH-ARRPROBE): "ok" only when every phase either did its work or
    had none to do. A phase that could not DETERMINE its work (a failed probe,
    a missing link — ``PushPlan.blocked_reasons``) is recorded ``incomplete``,
    which flips the run's outcome to ``"incomplete"`` and its exit to
    ``EXIT_PARTIAL`` WITHOUT halting. A silent no-op that leaves the song
    un-materialized must never exit 0.
    """
    if send_fn is None:
        from hallucinote_mcp import client as _client  # type: ignore[import-not-found]
        send_fn = _client.send

    # Resolve the Request type lazily — same reason as send_fn. Tests that
    # inject send_fn directly may pass anything that round-trips; the dispatch
    # loop builds plain Request objects unconditionally for the real path.
    from hallucinote_mcp.wire import Request  # type: ignore[import-not-found]
    # Connection-class exceptions we treat as halt-immediate. Anything else
    # (e.g. wire.FrameError — protocol bugs, not network issues; programming
    # errors from planner contract drift) propagates so the failure mode
    # surfaces honestly instead of mislabeling as 'connection lost'.
    try:
        from hallucinote_mcp.client import LiveConnectionError as _LiveConnectionError  # type: ignore[import-not-found]
        _CONNECTION_EXCS: tuple[type[BaseException], ...] = (_LiveConnectionError, OSError)
    except ImportError:
        _CONNECTION_EXCS = (OSError,)

    state_dir.mkdir(parents=True, exist_ok=True)
    # WSP-3R7K: the push's own bookkeeping self-ignores where it is written, so
    # a workspace that predates `init-workspace`'s managed root block doesn't
    # keep offering these as committable. By NAME, not a blanket ignore — this
    # dir is the song dir, which also holds build.py and the snapshot.
    self_ignore_files(state_dir, SONG_DIR_IGNORED_FILES)
    state_file = state_dir / ".last-push-state.json"
    errors_file = state_dir / ".last-push-errors.json"

    # PSH-2R7K: plan + resolve phase-targeting BEFORE creating the request, so a
    # bad --only/--start-at/--stop-after fails fast (PhaseTargetError) without
    # leaving a dangling open audit row. plan_push_song is pure-data (no side
    # effects), so the reorder is safe.
    # PSH-DEVDUP: the devices phase needs Live's CURRENT device chains to tell
    # "this device is missing" from "this device is present but unlinked" —
    # answering `load` to both is what doubled every FX chain on `the-argument`
    # (2026-08-08). The probe is a THUNK resolved inside the devices plan_fn, so
    # it runs AFTER `tracks`/`returns` have created + linked the parents it keys
    # by (an eagerly-probed map on a first push describes different indices).
    # Resolving it also RECONCILES the device links, which is the actual repair:
    # a chain loaded into Live by /song-pick-instruments reaches the DB only via
    # the capture snapshot, so it never had an `ableton_links` row, and
    # `push_cli execute` — unlike `push_cli probe-and-link` — never bound one.
    device_probe_state: dict[str, Any] = {"done": False, "map": None}

    def _device_chain_probe() -> dict[tuple[str, int], list[dict]] | None:
        if device_probe_state["done"]:
            return device_probe_state["map"]
        device_probe_state["done"] = True
        probed, parent_count = _probe_live_device_chains()
        if probed:
            push.reconcile_device_links(
                conn,
                song_id=song_id,
                session_id=session_id,
                live_devices_by_parent=probed,
                actor=actor,
                reason=(
                    reason
                    or f"push_cli execute device reconcile (session={session_id})"
                ),
            )
        # No PARENTS to probe (a song with no linked tracks/returns yet, or a
        # scoped run before `tracks`) yields an empty map that says nothing —
        # hand the planner ``None`` so it keeps its pure-planner contract. But
        # an empty map when there WERE parents means every read failed, and
        # that is real ignorance: keep the empty map so the planner refuses
        # per-parent rather than appending on faith.
        device_probe_state["map"] = probed if parent_count else None
        return device_probe_state["map"]

    phases = push.plan_push_song(
        conn, song_id=song_id, session_id=session_id,
        perform_slowdown_factor=perform_slowdown_factor,
        live_arrangement_clips_by_track=live_arrangement_clips_by_track,
        live_device_chains=_device_chain_probe,
    )
    phases, scope = _filter_phases(
        phases, only=only, start_at=start_at, stop_after=stop_after,
    )

    # W23-C: every full-song push is one attributed request. Threading the
    # request_id through `apply_push_results`'s actor/request kwargs tags
    # every link-binding event the apply layer emits, so the provenance
    # read surface (`Q.list_requests_for_song(..., kind='push')` +
    # `Q.get_events_for_request(rid)`) gives a complete cycle view.
    # Outcome flips below if a phase halts; close_request writes 'partial' /
    # 'failed' instead of 'ok'.
    request_id = M.create_request(
        conn,
        actor=actor,
        intent=f"push_cli execute (session={session_id})",
        kind="push",
        payload={"session_id": session_id, "song_id": song_id, "scope": scope},
        song_id=song_id,
        reason=reason,
        metadata=M.provenance_metadata(
            extra={"driver": "push_cli", "session_id": session_id},
        ),
    )

    phase_outcomes: list[PhaseOutcome] = []
    halt_phase: str | None = None  # also the errors-file "phase" — one source
    outcome = "ok"
    exit_code = EXIT_OK
    error_records: list[dict[str, Any]] = []
    # SYN-6B4Q: benign warnings (deferred cues) — do not flip outcome/exit.
    warning_messages: list[str] = []
    # PSH-3K9D chunk 2: mid-phase heartbeat — {phase, done, total}. None except
    # DURING a dispatch that crosses _HEARTBEAT_EVERY; _flush_state surfaces it so
    # a poller sees forward motion inside a long phase. Reset per phase + cleared
    # at the terminal flush so a finished push never shows stale progress.
    phase_progress: dict[str, Any] | None = None

    def _flush_state(current_phase: str | None = None) -> None:
        """Write ``.last-push-state.json`` reflecting progress SO FAR (PSH-5T9D).

        Called at the top of every phase (with the phase as ``current_phase``)
        and at the terminal state, so the file is **pollable mid-run** for
        phase-level progress + the current phase — instead of only materializing
        at exit (the opacity PSH-5T9D fixes). Reads the live accumulators by
        closure, so each call snapshots the current state.
        """
        state_payload = {
            "ts": _now_iso(),
            "song_id": song_id,
            "session_id": session_id,
            "outcome": outcome,
            "phase_halted": halt_phase,
            # PSH-5T9D: the phase currently executing (None at the terminal
            # flush) — lets a poller see "where are we right now".
            "current_phase": current_phase,
            # PSH-2R7K: the phase-targeting filter (None for a full run) so a
            # scoped run's state file is never mistaken for a full push.
            "scope": scope,
            # PSH-3K9D chunk 2: mid-phase progress for the currently-dispatching
            # phase (omitted at phase boundaries + terminal — only present while a
            # long phase is mid-flight). Distinguishes slow from hung.
            **({"phase_progress": phase_progress} if phase_progress else {}),
            "phases": [
                {
                    "name": p.name,
                    "status": p.status,
                    **({"calls_ok": p.calls_ok, "calls_failed": p.calls_failed}
                       if p.status in {_STATUS_OK, _STATUS_HALTED,
                                       _STATUS_INCOMPLETE}
                       else {}),
                    # PSH-ARRPROBE: WHY the phase couldn't finish. Emitted
                    # only when there IS a reason, so a reader can branch on
                    # the key's presence alone.
                    **({"blocked_reasons": p.blocked_reasons}
                       if p.blocked_reasons else {}),
                    **({"calls_planned": p.calls_planned}
                       if p.status == _STATUS_PENDING
                       else {}),
                    # A3: only emit pad-probe counts when probes actually ran.
                    **({"pad_probes_ok": p.pad_probes_ok,
                        "pad_probes_failed": p.pad_probes_failed}
                       if (p.pad_probes_ok or p.pad_probes_failed)
                       else {}),
                }
                for p in phase_outcomes
            ],
            "errors_file": errors_file.name if error_records else None,
            # SYN-6B4Q: benign warnings (deferred cues) — additive field; an OK
            # push can carry warnings without an errors file.
            "warnings": warning_messages,
        }
        # Atomic write (temp sibling + os.replace): PSH-5T9D made this file a
        # mid-run READ contract (pollers + --resume), and it's now rewritten
        # N+1× per push — a bare write_text would expose a torn file to a
        # concurrent reader between truncate and flush (learnings.md: state
        # writes must be atomic). os.replace is atomic on POSIX + Windows.
        tmp = state_file.with_name(f".{state_file.name}.tmp-{os.getpid()}")
        tmp.write_text(json.dumps(state_payload, indent=2) + "\n")
        os.replace(tmp, state_file)

    def _emit_progress(line: str) -> None:
        """Forward a one-line progress message to the caller's sink (PSH-5T9D)."""
        if progress_fn is not None:
            progress_fn(line)

    def _maybe_pad_probe(phase_name: str) -> tuple[int, int]:
        """A3: best-effort pad-mapping probe for the devices phase.

        Fires after a structurally successful devices phase (whether the
        phase had work to do OR was skipped because every device was
        already linked via W20-A — both cases want pad_info captured for
        the linked Drum Racks). Does not fire on halt/connection_lost:
        the connection may be broken, and the push is going to be re-run
        after the user fixes the underlying problem.

        Returns ``(0, 0)`` for non-devices phases.
        """
        if phase_name != "devices":
            return 0, 0
        return _probe_pad_mappings_for_session(
            conn=conn,
            session_id=session_id,
            send_fn=send_fn,
            request_cls=Request,
            actor=actor,
            request_id=request_id,
            reason=reason or f"push_cli execute pad-probe (session={session_id})",
        )

    def _probe_one_device_chain(
        parent_kind: str, parent_index: int,
    ) -> list[dict[str, Any]] | None:
        """PSH-DEVDUP: read one parent's top-level Live device chain.

        Returns the ``ableton_device(action='list')`` device list, or ``None``
        on ANY failure. ``None`` is load-bearing and must never be softened to
        ``[]``: the devices planner reads "no data for this parent" as REFUSE,
        while ``[]`` means "Live's chain is genuinely empty, appending is safe".
        Collapsing the two is precisely the guess that doubles a chain."""
        if parent_kind == "master":
            params: dict[str, Any] = {"master": True}
        elif parent_kind == "track":
            params = {"track_index": parent_index}
        elif parent_kind == "return":
            params = {"return_index": parent_index}
        else:
            return None
        try:
            resp = send_fn(Request(
                tool="ableton_device", action="list", params=params,
            ))
        except Exception:  # prawduct:allow prawduct/broad-except -- a probe hiccup must surface as "unknown" (which REFUSES the load), never as a traceback or a false "chain is empty"
            logger.debug(
                "device-chain probe failed for %s#%s", parent_kind, parent_index,
                exc_info=True,
            )
            return None
        if not bool(getattr(resp, "ok", False)):
            return None
        payload = getattr(resp, "result", None) or {}
        # An OK response with no `devices` key is read as an EMPTY chain, not as
        # a failure — same convention as `push_cli._probe_live_devices_via_mcp`
        # (the handler omits the key for an empty chain). Only a refused call or
        # a raised transport error is "unknown"; that is the distinction the
        # planner's refuse-vs-load fork rests on.
        return list(payload.get("devices") or [])

    def _probe_live_device_chains() -> tuple[dict[tuple[str, int], list[dict]], int]:
        """PSH-DEVDUP: probe every addressable parent's device chain, keyed
        ``(parent_kind, parent_index)`` — the same shape ``probe_and_link``
        consumes. Parents come from ``ableton_links`` (plus the master
        singleton), so this issues exactly as many reads as the devices phase
        has parents to address, and a per-parent failure simply leaves that key
        ABSENT (which the planner reads as "unknown → refuse").

        Returns ``(map, parent_count)``; the count lets the caller tell "there
        was nothing to probe" from "nothing answered"."""
        tracks, returns, master = push.linked_device_parents(
            conn, song_id=song_id, session_id=session_id,
        )
        by_parent: dict[tuple[str, int], list[dict]] = {}
        parent_count = 0
        for parents, parent_kind in (
            (tracks, "track"), (returns, "return"), (master, "master"),
        ):
            for parent in parents:
                parent_count += 1
                idx = parent["ableton_index"]
                probed = _probe_one_device_chain(parent_kind, idx)
                if probed is not None:
                    by_parent[(parent_kind, idx)] = probed
        return by_parent, parent_count

    def _read_device_params(node: dict[str, Any]) -> dict[str, Any] | None:
        """PSH-3K9D: read one device's current Live parameters for the
        devices-phase diff-reconcile. Returns the ``get_parameters`` result
        payload, or ``None`` on ANY failure — the diff then keeps that device's
        writes (skip-on-confident-equal). Auxiliary like the pad-probe: a read
        hiccup must never derail an otherwise-fine push, only forgo the skip."""
        try:
            resp = send_fn(Request(
                tool="ableton_device",
                action="get_parameters",
                params={"node": node, "detail": "full"},
            ))
        except Exception:  # prawduct:allow prawduct/broad-except -- best-effort pre-dispatch read; any failure just forgoes the skip (keeps the write), never halts the push
            logger.debug("devices-diff get_parameters read failed — keeping writes", exc_info=True)
            return None
        if not bool(getattr(resp, "ok", False)):
            return None
        return getattr(resp, "result", None)

    def _probe_rack_chain_count(rack: dict[str, Any]) -> int | None:
        """SYN-9F4K: read a freshly-loaded rack's live chain count via the
        existing ``get_device_chains`` handler (engine-only — reuses the
        read-only handler, no MCP wire change). Returns the ``chain_count`` int,
        or ``None`` on ANY failure — the guard then keeps the rack's writes
        (keep-on-doubt: a probe hiccup must never fabricate an empty-rack halt)."""
        parent = rack["parent"]
        kind = parent.get("kind") if isinstance(parent, dict) else None
        params: dict[str, Any] = {"device_index": rack["live_index"]}
        if kind == "track":
            params["track_index"] = parent.get("index")
        elif kind == "return":
            params["return_index"] = parent.get("index")
        elif kind == "master":
            params["master"] = True
        else:
            return None
        try:
            resp = send_fn(Request(
                tool="ableton_device", action="get_device_chains", params=params,
            ))
        except Exception:  # prawduct:allow prawduct/broad-except -- best-effort runtime probe; any failure forgoes the empty-rack guard (keeps writes), never halts
            logger.debug("empty-rack chain probe failed — keeping writes", exc_info=True)
            return None
        if not bool(getattr(resp, "ok", False)):
            return None
        result = getattr(resp, "result", None) or {}
        chain_count = result.get("chain_count")
        return chain_count if isinstance(chain_count, int) else None

    def _loaded_rack_name_fn(main_calls):
        """SYN-9F4K: build a best-effort ``name_fn`` for the empty-rack guard from
        THIS pass's load calls — ``(parent, device_index) -> display_name`` for
        each rack loaded this pass, resolved via its now-live link. The guard uses
        it to name an empty rack in the failure message; a rack with no load this
        pass (e.g. an already-linked rack on a re-push) isn't in the map, so the
        guard falls back to the rack's live address. Cheap per-load DB reads."""
        name_map: dict[tuple[Any, Any], str] = {}
        for call in main_calls:
            if call.tool != "ableton_device" or call.args.get("action") != "load":
                continue
            key = call.key or ""
            if not key.startswith("device:"):
                continue
            device_id = key.split(":", 1)[1]
            live_index = Q.get_ableton_link(
                conn, session_id=session_id, db_kind="device", db_id=device_id,
            )
            if live_index is None:
                continue
            parent = (call.args.get("node") or {}).get("parent")
            if not parent:
                continue
            row = Q.get_device(conn, device_id)
            display_name = (row["display_name"] if row is not None else None)
            if display_name:
                name_map[(_parent_key(parent), live_index)] = display_name

        def name_fn(parent, device_index):
            return name_map.get((_parent_key(parent), device_index))

        return name_fn

    def _empty_rack_result_entries(failures) -> list[dict[str, Any]]:
        """SYN-9F4K: turn empty-rack guard failures into synthetic failed-result
        entries (returned, for the caller to extend ``results``) + error records
        (appended here). One per empty rack, so the boundary halt fires on a single
        clear "preset content did not load" error instead of the chain-index
        cascade. NOT routed through ``_apply_results`` — these are diagnosis, not
        wire results."""
        entries: list[dict[str, Any]] = []
        for fail in failures:
            kind, index = _parent_key(fail["parent"])
            base = {
                "key": f"empty_rack:{kind}:{index}/{fail['device_index']}",
                "tool": "ableton_device",
                "error": fail["message"],
            }
            entries.append({**base, "ok": False, "result": None})
            error_records.append({
                **base,
                "action": "load",
                "args_summary": {
                    "empty_rack_suppressed_writes": fail["suppressed_count"],
                },
                "hint": fail["hint"],
            })
        return entries

    def _dispatch_calls(
        calls, *, phase_name: str | None = None,
    ) -> tuple[list[dict[str, Any]], bool]:
        """Dispatch ToolCalls via ``send_fn`` → (results, connection_lost).

        Per-call failures append to ``error_records``; a connection-class
        exception stops the batch immediately (no point continuing without
        Live). Shared by the main per-phase pass and the devices-phase
        convergence pass (SYN-9F2L).

        PSH-3K9D chunk 2: when ``phase_name`` is set, emit a mid-phase heartbeat
        every ``_HEARTBEAT_EVERY`` processed calls — to stderr (``progress_fn``)
        AND into ``.last-push-state.json`` (``phase_progress``) — so a phase
        issuing many calls is observable. ``len(results)`` is the processed count
        (one result per call); the connection-loss early-return appends none, so
        no heartbeat fires on the failed call.
        """
        nonlocal phase_progress
        results: list[dict[str, Any]] = []
        total = len(calls)
        for call in calls:
            action = call.args.get("action")
            params = {k: v for k, v in call.args.items() if k != "action"}
            req = Request(tool=call.tool, action=action or "", params=params)
            # ENV-8K2R #5: a planner-derived read ceiling (perform_batch) is
            # forwarded only when set; every other call keeps the client's
            # (tool, action) policy, so 1-arg ``send_fn`` test doubles are
            # untouched by the non-perform path.
            send_kwargs: dict[str, Any] = {}
            if call.read_timeout is not None:
                send_kwargs["read_timeout"] = call.read_timeout
            try:
                resp = send_fn(req, **send_kwargs)
            except _CONNECTION_EXCS as exc:
                # Connection-class failure (Live unreachable, socket error).
                # Halt immediately — no point continuing without Live. Wire
                # protocol bugs (wire.FrameError) and other unexpected
                # exceptions propagate so they're not mislabeled here.
                error_records.append({
                    "key": call.key,
                    "tool": call.tool,
                    "action": action,
                    "args_summary": _summarize_args(call.args),
                    "error": f"{type(exc).__name__}: {exc}",
                    "hint": None,
                })
                return results, True

            ok = bool(getattr(resp, "ok", False))
            err_msg = getattr(resp, "error", None) if not ok else None

            # M1-B: cross-machine device-load fallback. When a `device.load`
            # with a captured-on-the-author's-machine `preset_uri` fails
            # because the URI is unresolvable on this machine, try a search
            # by display_name and retry with the discovered URI.
            fallback_uri: str | None = None
            if (
                not ok
                and call.tool == "ableton_device"
                and action == "load"
                and call.args.get("preset_uri")
                and err_msg
                and any(hint in err_msg for hint in _PRESET_URI_MISS_HINTS)
            ):
                fb = _attempt_load_fallback(
                    failed_call=call, conn=conn, send_fn=send_fn,
                    request_cls=Request,
                )
                if fb is not None:
                    resp, fallback_uri = fb
                    ok = True
                    err_msg = None

            # SYN-9F2L: a refused value_display write has two known second
            # forms (actual-enum, no-display-curve) worth one retry each.
            set_param_fallback: str | None = None
            if (
                not ok
                and call.tool == "ableton_device"
                and action == "set_parameter"
                and err_msg
            ):
                fb2 = _attempt_set_parameter_fallback(
                    failed_call=call, conn=conn, send_fn=send_fn,
                    request_cls=Request, err_msg=err_msg,
                )
                if fb2 is not None:
                    resp, set_param_fallback = fb2
                    ok = True
                    err_msg = None

            result_payload = getattr(resp, "result", None) if ok else None
            hint = getattr(resp, "hint", None) if not ok else None
            # SYN-2D9K: replace the MCP's value-range hint with the orphan-cause
            # hint when a set_parameter fails on a param the device doesn't have.
            if not ok:
                orphan_hint = _orphan_param_hint(
                    tool=call.tool, action=action, err_msg=err_msg,
                    parameter_name=call.args.get("parameter_name"),
                )
                if orphan_hint is not None:
                    hint = orphan_hint

            # SYN-6B4Q: a cue_create_batch dispatched in skip mode reports the
            # cues it DEFERRED (ahead of Live's current extent). The call itself
            # succeeded — surface the deferral as a benign warning, not a
            # failure. The deferred cues land on the next push once arrangement
            # content covers them (the planner already refused any cue past the
            # composed song length, so these WILL become placeable).
            if (
                ok
                and call.tool == "ableton_arrangement"
                and action == "cue_create_batch"
            ):
                deferred = (result_payload or {}).get("skipped_out_of_range") or []
                if deferred:
                    let = (result_payload or {}).get("last_event_time")
                    preview = ", ".join(
                        f"{d.get('name') or '(unnamed)'}@beat"
                        f"{float(d['position_beats']):.2f}"
                        for d in deferred[:5]
                    )
                    ellipsis = " ..." if len(deferred) > 5 else ""
                    warning_messages.append(
                        f"cues: {len(deferred)} cue(s) deferred past Live's "
                        f"current arrangement extent (last_event_time={let}) — "
                        "they land on the next push once arrangement content "
                        f"covers them: [{preview}{ellipsis}]"
                    )

            result_entry: dict[str, Any] = {
                "key": call.key,
                "tool": call.tool,
                "ok": ok,
                "result": result_payload,
                "error": err_msg,
            }
            if fallback_uri is not None:
                # Surface in the state file so the agent can see that the
                # fallback fired (and which URI was substituted). The DB's
                # preset_uri stays untouched — the song remains portable.
                result_entry["fallback_preset_uri"] = fallback_uri
            if set_param_fallback is not None:
                result_entry["set_parameter_fallback"] = set_param_fallback
            results.append(result_entry)

            # A chain-mixer write Live refuses BECAUSE THE PARAMETER IS DISABLED
            # is a no-op, and halting fourteen phases over it is wrong. A
            # macro-mapped or locked chain mixer cannot be changed by us, by the
            # user in the UI, or by anything else — so the DB's value can never
            # audibly diverge from Live, and there is nothing for a retry or a
            # human to fix. (Live's own 606 Core Kit hi-hat pads do this.) The
            # capture side now declines to record such params at all
            # (`_chain_mixer_nondefault`), so this is the belt to that braces:
            # snapshots authored before the capture fix, or a param that becomes
            # macro-mapped after capture, still must not take down a push.
            #
            # Deliberately NOT converted to ok=True: nothing succeeded, so the
            # result must not be applied as though the value had been written.
            # It is recorded as a warning and skipped.
            tolerated = not ok and _is_tolerated_failure(
                tool=call.tool, action=action, err_msg=err_msg,
            )
            if tolerated:
                result_entry["skipped_param_disabled"] = True
                warning_messages.append(
                    f"devices: chain property skipped — Live reports the "
                    f"parameter is disabled (macro-mapped or locked), so the "
                    f"write is a no-op ({call.key})"
                )

            if not ok and not tolerated:
                error_records.append({
                    "key": call.key,
                    "tool": call.tool,
                    "action": action,
                    "args_summary": _summarize_args(call.args),
                    "error": err_msg,
                    "hint": hint,
                })

            # PSH-3K9D chunk 2: mid-phase heartbeat. `len(results)` is the
            # processed count (one result appended per call above). Fires every
            # _HEARTBEAT_EVERY calls, never on the last (the phase's own "[x] ok"
            # line covers completion). Throttled, so the per-call state write
            # stays cheap even on a 1000+ call phase.
            done = len(results)
            if phase_name and done % _HEARTBEAT_EVERY == 0 and done < total:
                phase_progress = {"phase": phase_name, "done": done, "total": total}
                _flush_state(current_phase=phase_name)
                _emit_progress(f"[{phase_name}] {done}/{total} call(s)…")
        return results, False

    def _apply_results(batch: list[dict[str, Any]], phase_name: str) -> bool:
        """Apply successes regardless of failure mix — push is idempotent and
        link rows must be live before the next phase (or the devices-phase
        convergence pass) plans.

        Returns ``True`` when apply recorded cleanly. SYN-8Q3F (c): a
        ``ValueError`` from the apply layer is planner↔apply CONTRACT DRIFT —
        an unknown result key kind (the twice-shipped device_param_override /
        device_chain_props class), a malformed key, or a perform arc missing
        its arc_id. The apply transaction has already rolled the whole batch
        back, so nothing from this phase is recorded. Historically this raise
        escaped ``execute_push`` as a raw traceback — no terminal state file,
        request row left open (contract artifact, violation V4). Now it is the
        deliberate fail-loud-WITH-CONTEXT path: record the teaching message +
        hint and return ``False`` so the caller halts the phase through the
        normal ``_halt`` machinery (state file written, later phases PENDING,
        request closed ``partial``, exit ``EXIT_PARTIAL``)."""
        try:
            apply_warnings = push.apply_push_results(
                conn,
                batch,
                session_id=session_id,
                actor=actor,
                request_id=request_id,
                reason=reason or f"push_cli execute phase={phase_name}",
            )
        except ValueError as exc:
            error_records.append({
                "key": None,
                "tool": "apply_push_results",
                "action": "apply",
                "args_summary": {"phase": phase_name, "results": len(batch)},
                "error": f"{type(exc).__name__}: {exc}",
                "hint": (
                    "apply-layer failure — usually planner↔apply contract "
                    "drift (an undeclared result key kind; the error names "
                    "the cause). NOTHING from this batch was recorded (it "
                    "rolled back). For an undeclared kind, declare it in "
                    "_LINK_KINDS / _ACK_ONLY_KINDS (see "
                    "KNOWN_RESULT_KEY_KINDS in sync/push/plan.py), then re-run "
                    "execute (idempotent — Live-side writes already landed and "
                    "re-link on the next pass)."
                ),
            })
            return False
        # Apply-layer warnings (e.g. a perform whose write Live could
        # not verify — nothing recorded, next push retries) ride the
        # errors file so the agent sees them. They don't flip the
        # phase status: the wire call succeeded; what failed is the
        # verification-gated DB record.
        for w in apply_warnings:
            error_records.append({
                "key": None,
                "tool": "apply_push_results",
                "action": "apply",
                "args_summary": {"phase": phase_name},
                "error": w,
                "hint": None,
            })
        return True

    def _drain_plan_warnings(plan_obj) -> None:
        """SYN-9F2L: a planner records an operator-actionable, non-fatal warning
        (e.g. a params_dialed write with no writable form) in ``plan.alerts``.
        ``execute`` is the only operator-visible surface on this path, so route
        alerts into the benign warnings channel — otherwise the warn is silently
        discarded, the exact silent-drop SYN-9F2L exists to prevent. Drains
        ``alerts`` (operator-facing), NOT ``notes`` (diagnostic "nothing to
        push" / "not linked yet" noise). Deduped by message so the devices-phase
        convergence re-plan (which regenerates the full plan, alerts included)
        doesn't double-report an already-surfaced warning.

        PSH-ARRPROBE: alerts that are ALSO ``blocked_reasons`` are excluded —
        they are not benign (they make the push INCOMPLETE), and the phase
        outcome carries them into their own summary section. Routing them here
        too would both double-print them and label them "push still OK"."""
        blocked = set(getattr(plan_obj, "blocked_reasons", ()))
        for alert in plan_obj.alerts:
            if alert in blocked:
                continue
            if alert not in warning_messages:
                warning_messages.append(alert)

    def _note_blocked() -> None:
        """PSH-ARRPROBE: flip the run off "clean" because a phase reported work
        it could NOT determine and honestly skipped.

        Does not halt (the determinable work still landed, and later phases
        still run) and never downgrades a stronger terminal state — a later
        halt overwrites ``incomplete`` with ``partial`` /
        ``connection_lost``. Reuses ``EXIT_PARTIAL`` rather than minting a
        fourth exit code: every caller's contract is "0 means the push did
        everything", and an incomplete push did not."""
        nonlocal outcome, exit_code
        if outcome == "ok":
            outcome = "incomplete"
            exit_code = EXIT_PARTIAL

    def _halt(phase_name: str, idx: int, *, outcome_label: str,
              exit_code_val: int, calls_ok: int, calls_failed: int,
              blocked_reasons: list[str] | None = None) -> None:
        """Record a phase halt: mark the phase HALTED, set the terminal
        outcome/exit, and fill every later phase as PENDING so the state file is
        uniform. The three halt causes (plan-error, connection-lost, call-fail)
        differ only in their counts + labels — this is the one place that
        bookkeeping lives. The caller still issues ``break`` (loop control can't
        cross the call boundary).

        PSH-3K9D chunk 2: intentionally does NOT call ``_flush_state`` — the
        terminal flush after the loop clears ``phase_progress`` first (the only
        post-loop write). Adding a flush here would persist a stale mid-phase
        ``phase_progress`` from the just-halted phase; if you add one, reset
        ``phase_progress = None`` before it."""
        nonlocal halt_phase, outcome, exit_code
        phase_outcomes.append(PhaseOutcome(
            name=phase_name, status=_STATUS_HALTED,
            calls_ok=calls_ok, calls_failed=calls_failed,
            # A halted phase can ALSO have skipped undeterminable work; carry
            # the reasons so the halt doesn't swallow them.
            blocked_reasons=list(blocked_reasons or ()),
        ))
        halt_phase = phase_name
        outcome = outcome_label
        exit_code = exit_code_val
        for remaining in phases[idx + 1:]:
            phase_outcomes.append(PhaseOutcome(
                name=remaining.name, status=_STATUS_PENDING, calls_planned=0,
            ))
        _emit_progress(f"[{phase_name}] HALTED — {outcome_label}")

    def _device_chains_verified(phase_name: str, idx: int, calls_ok: int) -> bool:
        """PSH-DEVDUP PREVENTION assert — the devices-phase sibling of the
        arrangement integrity check, and the same contract: a materialize step
        that can corrupt state silently proves it didn't, or the push HALTs.

        Re-probes every addressable parent's chain in a FRESH read (never the
        pre-phase map — that one predates the loads) and compares Live's
        authored device classes against the DB's. Live carrying MORE of a class
        the DB authors on that parent than the DB authors is the duplication
        signature; anything else (a factory device, a hand-dropped utility, a
        short chain, an unreadable parent) is surfaced as a warning and does not
        halt. Returns True when the phase may be recorded OK."""
        if phase_name != "devices":
            return True
        from hallucinote.sync.device_chain_verify import (
            DeviceChainIntegrityError,
            assert_device_chains_materialized,
            CHAIN_PROBE_FAILED,
        )
        try:
            report = assert_device_chains_materialized(
                conn, song_id=song_id, session_id=session_id,
                probe_fn=_probe_one_device_chain,
            )
        except DeviceChainIntegrityError as exc:
            error_records.append({
                "key": None,
                "tool": phase_name,
                "action": "integrity_assert",
                "args_summary": {"phase": phase_name},
                "error": str(exc),
                "hint": (
                    "Live's device chain carries a duplicate of a device the DB "
                    "already authors there. Live has no reorder API, so a "
                    "re-push cannot undo it: delete the duplicates in Live (or "
                    "push into a fresh set), then re-run `push_cli "
                    "probe-and-link <session> --song <slug> --probe`."
                ),
            })
            _halt(
                phase_name, idx, outcome_label="partial",
                exit_code_val=EXIT_PARTIAL, calls_ok=calls_ok,
                calls_failed=1,
            )
            return False
        except _CONNECTION_EXCS as exc:
            error_records.append({
                "key": None,
                "tool": phase_name,
                "action": "integrity_assert",
                "args_summary": {"phase": phase_name},
                "error": (
                    "connection lost during the device-chain integrity "
                    f"re-probe: {exc}"
                ),
                "hint": "see ableton://guides/error-recovery; re-execute (idempotent).",
            })
            _halt(
                phase_name, idx, outcome_label="connection_lost",
                exit_code_val=EXIT_CONNECTION_LOST, calls_ok=calls_ok,
                calls_failed=1,
            )
            return False
        # Non-fatal disagreements: say them, don't swallow them. "Couldn't
        # verify" must read differently from "verified clean" — that gap is the
        # whole reason the assert exists.
        for anomaly in report.anomalies():
            msg = f"devices integrity: {anomaly.describe()}"
            if msg not in warning_messages:
                warning_messages.append(msg)
        unverified = [
            r for r in report.results if r.status == CHAIN_PROBE_FAILED
        ]
        if unverified:
            msg = (
                f"devices integrity: {len(unverified)} device chain(s) could "
                f"NOT be verified (Live re-probe failed) — a duplicated chain "
                f"on those would NOT have been caught: "
                + ", ".join(
                    f"{r.parent_kind} {r.parent_name!r}" for r in unverified[:5]
                )
                + (" ..." if len(unverified) > 5 else "")
            )
            if msg not in warning_messages:
                warning_messages.append(msg)
        return True

    # MICROTUNE Chunk 3: before the phase loop, emit the gated tuning notices —
    # the re-load instruction + a non-blocking drift warning — for an alt-tuned
    # song. Inert (returns []) for the 99.99% with tuning_ref NULL, with NO extra
    # Live round-trip. Routed through the benign warnings channel so they ride
    # the summary + state file; emitted early so the operator sees them up front.
    from hallucinote.sync.push.tuning_notice import collect_tuning_notices
    for notice in collect_tuning_notices(
        conn, song_id=song_id, send_fn=send_fn, request_cls=Request,
    ):
        if notice not in warning_messages:
            warning_messages.append(notice)
        _emit_progress(notice)

    for idx, phase in enumerate(phases):
        # PSH-3K9D chunk 2: clear any prior phase's mid-flight progress before
        # the phase-start flush, so a poller never sees stale done/total.
        phase_progress = None
        # PSH-5T9D: flush at the START of each phase so a poller of
        # .last-push-state.json sees the current phase before it runs (the
        # per-phase progress the opacity bug asked for). The stderr heartbeat
        # below fires only for phases that actually dispatch.
        _flush_state(current_phase=phase.name)
        plan = phase.plan_fn()
        _drain_plan_warnings(plan)
        # PSH-ARRPROBE: work this planner refused to guess at (a failed probe,
        # a missing link). Collected BEFORE the halt branches so every exit path
        # from this iteration can carry it.
        blocked_reasons: list[str] = list(getattr(plan, "blocked_reasons", []))

        # SYN-6B4Q: a planner can flag a hard authoring error (e.g. a cue past
        # the composed song length). Halt the phase WITHOUT dispatching — the
        # DB describes something that can't be materialized, so nothing should
        # half-apply in Live. The clear DB-grounded message rides the errors
        # file; the operator fixes the authoring and re-pushes (idempotent).
        if plan.errors:
            for msg in plan.errors:
                error_records.append({
                    "key": None,
                    "tool": phase.name,
                    "action": "plan",
                    "args_summary": {"phase": phase.name},
                    "error": msg,
                    "hint": (
                        "fix the authoring in build.py (the message names the "
                        "offending row[s]), rebuild, then re-run execute "
                        "(idempotent — applied rows skip)"
                    ),
                })
            _halt(
                phase.name, idx, outcome_label="partial",
                exit_code_val=EXIT_PARTIAL, calls_ok=0,
                calls_failed=len(plan.errors),
                blocked_reasons=blocked_reasons,
            )
            break

        if not plan.calls:
            # PSH-DEVDUP: an empty devices plan is the fully-idempotent
            # re-push — every device already linked. That is exactly the state
            # a doubled chain hides in (the second copy IS linked), so verify
            # here too rather than trusting "nothing to do".
            if not _device_chains_verified(phase.name, idx, 0):
                break
            pad_ok, pad_failed = _maybe_pad_probe(phase.name)
            # PSH-ARRPROBE: an empty plan has two very different causes, and
            # collapsing them is the silent-failure bug this split closes.
            # "Nothing to push" is idempotent and clean; "couldn't determine
            # the state, so pushed nothing" left the song un-materialized and
            # must NOT read as a clean skip in the summary or the exit code.
            if blocked_reasons:
                _note_blocked()
                phase_outcomes.append(PhaseOutcome(
                    name=phase.name, status=_STATUS_INCOMPLETE,
                    pad_probes_ok=pad_ok, pad_probes_failed=pad_failed,
                    blocked_reasons=blocked_reasons,
                ))
                _emit_progress(
                    f"[{phase.name}] INCOMPLETE — nothing pushed; "
                    f"{len(blocked_reasons)} precondition(s) could not be "
                    "determined"
                )
                continue
            phase_outcomes.append(PhaseOutcome(
                name=phase.name, status=_STATUS_SKIPPED,
                pad_probes_ok=pad_ok, pad_probes_failed=pad_failed,
            ))
            _emit_progress(f"[{phase.name}] skipped (nothing to push)")
            continue

        # PSH-3K9D: make the devices phase a true diff-reconcile. Read each
        # device's current Live params once and drop the set_parameter calls
        # already equal to Live — the just-captured set used to re-apply ~1200
        # redundant params and stall for minutes. Skip-on-confident-equal: any
        # doubt keeps the write, so this can only ever degrade to today's
        # re-write-everything behavior, never to a wrong mix. Loaded-this-pass
        # devices land their params via the convergence re-plan below (NOT
        # diffed — a fresh device is at factory defaults, so every param
        # genuinely differs); on a fresh-set push the main plan has only loads,
        # so this fires no reads at all.
        calls_to_dispatch = plan.calls
        main_rack_failures: list[dict[str, Any]] = []
        if phase.name == "devices":
            from hallucinote.sync.push.device_param_diff import (
                partition_unchanged_device_params,
            )
            calls_to_dispatch, skipped_params = partition_unchanged_device_params(
                plan.calls, conn=conn, read_fn=_read_device_params,
            )
            if skipped_params:
                msg = (
                    f"devices: {len(skipped_params)} param(s) already current in "
                    f"Live — skipped; dispatching {len(calls_to_dispatch)} call(s)"
                )
                _emit_progress(f"[{phase.name}] {msg}")
                if msg not in warning_messages:
                    warning_messages.append(msg)
            # SYN-9F4K: an already-linked rack that still loads empty (a re-push
            # against an unresolved preset) re-emits its nested writes HERE, in
            # the main dispatch — not the convergence pass (which only sees a
            # device loaded THIS pass). Probe + drop them too, or the
            # chain-index-out-of-range cascade returns on every push after the
            # first. On a fresh push the rack is unlinked, so the main plan has
            # only the load (no nested writes) and this is a no-op — the
            # convergence guard below handles that case (with the loaded rack's
            # name). name_fn=None here: a re-push emits no load, so no name is
            # available — the message falls back to the rack's live address.
            calls_to_dispatch, main_rack_failures = partition_doomed_nested_writes(
                calls_to_dispatch, probe_fn=_probe_rack_chain_count,
            )

        # PSH-5T9D: announce a phase that actually dispatches. The realtime
        # perform gets a distinctive heads-up + ETA framing so a multi-minute
        # phase isn't mistaken for a hang (the worst-case the bug named).
        if phase.name == "performed_automation":
            _emit_progress(
                f"[{phase.name}] realtime perform — plays the arrangement; "
                "this can take several minutes…"
            )
        else:
            _emit_progress(f"[{phase.name}] running ({len(calls_to_dispatch)} call(s))…")

        results, connection_lost = _dispatch_calls(
            calls_to_dispatch, phase_name=phase.name,
        )

        # For connection-lost the dispatch stopped before any subsequent ok
        # rows could accumulate, so applying what we have is safe.
        # SYN-8Q3F (c): apply_ok=False means the apply layer hit contract
        # drift (unknown/malformed result key kind) — the batch rolled back
        # and the phase must halt below (after the connection-lost check,
        # which is the more actionable outcome when both fire).
        apply_ok = True
        if results:
            apply_ok = _apply_results(results, phase.name)

        # SYN-9F4K: record any main-dispatch empty-rack failures AFTER apply
        # (they're diagnosis, not wire results). Their ok=False entries make
        # `all(r.get("ok"))` False below, so the convergence pass is correctly
        # skipped — the phase halts on the single clear error.
        if main_rack_failures:
            results.extend(_empty_rack_result_entries(main_rack_failures))

        # SYN-9F2L convergence: a device loaded THIS pass gets its link at
        # apply-time, after parameter planning — so its dialed parameters
        # were unplannable above. Re-plan once now that links are live and
        # dispatch only the NEW calls (loads already dispatched keep their
        # keys, so nothing re-sends). Without this pass the params silently
        # never land: the next push's planner sees no DB change and skips.
        if (
            phase.name == "devices"
            and not connection_lost
            and apply_ok
            and results
            and all(r.get("ok") for r in results)
        ):
            replan = phase.plan_fn()
            # SYN-9F2L: a device loaded THIS pass was unlinked when the primary
            # plan ran, so its params (and any unwritable-form warning) first
            # become visible in this re-plan — drain its new notes too, or the
            # same-pass case stays silent.
            _drain_plan_warnings(replan)
            # PSH-ARRPROBE: the re-plan can surface blocked work the first plan
            # couldn't see (links only exist post-apply) — merge, don't drop.
            for reason in getattr(replan, "blocked_reasons", ()):
                if reason not in blocked_reasons:
                    blocked_reasons.append(reason)
            dispatched_keys = {c.key for c in plan.calls}
            extra_calls = [
                c for c in replan.calls
                if c.key not in dispatched_keys
            ]
            if extra_calls:
                # SYN-9F4K: a rack that loaded this pass with 0 chains cannot
                # accept its dependent nested writes — each would fail
                # chain-index-out-of-range, burying the real cause (the empty
                # load) under hundreds of errors. Probe each rack a nested write
                # addresses; drop the doomed writes and record ONE "preset content
                # did not load" failure per empty rack so the phase halts on a
                # single clear error instead of the cascade. The loaded rack's
                # name is available this pass (name_fn from the loads). Engine-only
                # (reuses get_device_chains, no MCP change).
                extra_calls, empty_rack_failures = partition_doomed_nested_writes(
                    extra_calls,
                    probe_fn=_probe_rack_chain_count,
                    name_fn=_loaded_rack_name_fn(plan.calls),
                )
                if empty_rack_failures:
                    results.extend(
                        _empty_rack_result_entries(empty_rack_failures)
                    )
                if extra_calls:
                    extra_results, connection_lost = _dispatch_calls(
                        extra_calls, phase_name=phase.name,
                    )
                    results.extend(extra_results)
                    if extra_results:
                        apply_ok = _apply_results(extra_results, phase.name)

        calls_ok = sum(1 for r in results if r.get("ok"))
        calls_failed = sum(1 for r in results if not r.get("ok"))

        if connection_lost:
            _halt(
                phase.name, idx, outcome_label="connection_lost",
                exit_code_val=EXIT_CONNECTION_LOST, calls_ok=calls_ok,
                calls_failed=calls_failed + 1,
                blocked_reasons=blocked_reasons,
            )
            break

        if not apply_ok:
            # SYN-8Q3F (c): apply-layer contract drift. The wire calls may all
            # have succeeded (calls_failed can be 0), but NOTHING from this
            # phase was recorded — halting is mandatory or later phases would
            # plan against links that were never written. The +1 counts the
            # apply failure itself (mirrors the connection-lost convention).
            _halt(
                phase.name, idx, outcome_label="partial",
                exit_code_val=EXIT_PARTIAL, calls_ok=calls_ok,
                calls_failed=calls_failed + 1,
                blocked_reasons=blocked_reasons,
            )
            break

        if calls_failed > 0:
            _halt(
                phase.name, idx, outcome_label="partial",
                exit_code_val=EXIT_PARTIAL, calls_ok=calls_ok,
                calls_failed=calls_failed,
                blocked_reasons=blocked_reasons,
            )
            break

        # ARR-PROJ Chunk 3: PREVENTION assert. The arrangement phase just
        # materialized; re-probe Live in a FRESH callback (never inline after the
        # write, §6a) and verify every clip's audible set equals the DB collapsed
        # set. HALT on silent corruption (drop / orphan / stack / drift) instead
        # of reporting OK — the structural backstop for the 2026-06-21 stacking +
        # bulk-drop and 2026-06-22 orphan bugs.
        if phase.name == "arrangement":
            from hallucinote.sync.arrangement_verify import (
                ArrangementIntegrityError,
                assert_arrangement_materialized,
            )
            try:
                integrity_report = assert_arrangement_materialized(
                    conn, song_id=song_id, session_id=session_id, send_fn=send_fn,
                )
                # The assert HALTs only on SILENT corruption; a per-clip NOTE
                # re-probe failure is not corruption (the clip is demonstrably at
                # the right position — only its contents could not be read), so the
                # assert returns normally — but those placements went UNVERIFIED, so
                # "OK" would overstate the guarantee (the exact gap the assert
                # exists to close). Surface the unverified count as a benign warning
                # (does not flip the exit) so "couldn't verify N clips" reads
                # distinctly from "verified all N".
                #
                # ARR-ORPHAN2: a whole-LANE probe failure is deliberately NOT in
                # this benign channel — it now raises above (`lane_probe_failed` is
                # corruption), because the pusher plans its clear from that same
                # probe, so an unreadable lane was never cleared and never rebuilt.
                unverified = [
                    r for r in integrity_report.results
                    if r.status == "probe_failed"
                ]
                if unverified:
                    verified_n = sum(
                        1 for r in integrity_report.results
                        if r.status in ("faithful", "diverged", "missing_clip")
                    )
                    affected = ", ".join(
                        f"{r.track_name}/{r.section}" for r in unverified[:5]
                    ) + (" ..." if len(unverified) > 5 else "")
                    msg = (
                        f"arrangement integrity: {len(unverified)} placement(s) "
                        f"could NOT be verified (Live note/clip re-probe failed); "
                        f"the assert covered only {verified_n} placement(s), so a "
                        f"silent drop/stack on the unverified ones would NOT have "
                        f"been caught. Re-run `execute --only arrangement` once Live "
                        f"is reachable to re-materialize + re-verify. Affected: "
                        f"{affected}"
                    )
                    if msg not in warning_messages:
                        warning_messages.append(msg)
            except ArrangementIntegrityError as exc:
                error_records.append({
                    "key": None,
                    "tool": phase.name,
                    "action": "integrity_assert",
                    "args_summary": {"phase": phase.name},
                    "error": str(exc),
                    "hint": (
                        "the materialized arrangement does not match the DB "
                        "(drop / orphan / stack / drift), or a track's arrangement "
                        "lane could not be read at all — an unreadable lane was "
                        "never cleared and never rebuilt, so its content is "
                        "unproven. Re-run `execute --only arrangement --probe` "
                        "(idempotent clear+rebuild); if it persists, run "
                        "`hallucinote verify-arrangement` and inspect the named "
                        "track/section."
                    ),
                })
                _halt(
                    phase.name, idx, outcome_label="partial",
                    exit_code_val=EXIT_PARTIAL, calls_ok=calls_ok,
                    calls_failed=1,
                    blocked_reasons=blocked_reasons,
                )
                break
            except _CONNECTION_EXCS as exc:
                # The assert's fresh re-probe lost Live mid-check. Treat exactly
                # like a dispatch-time connection loss so the terminal state file
                # is still written (the executor's always-write-state contract)
                # and the operator gets a re-execute instruction, not a traceback.
                error_records.append({
                    "key": None,
                    "tool": phase.name,
                    "action": "integrity_assert",
                    "args_summary": {"phase": phase.name},
                    "error": f"connection lost during the arrangement integrity re-probe: {exc}",
                    "hint": "see ableton://guides/error-recovery; re-execute (idempotent).",
                })
                _halt(
                    phase.name, idx, outcome_label="connection_lost",
                    exit_code_val=EXIT_CONNECTION_LOST, calls_ok=calls_ok,
                    calls_failed=calls_failed + 1,
                    blocked_reasons=blocked_reasons,
                )
                break

        # PSH-DEVDUP: the devices phase just dispatched loads/params. Prove Live
        # doesn't now carry a doubled chain before recording OK — the exact
        # claim the 2026-08-08 `23/23 ok` made falsely.
        if not _device_chains_verified(phase.name, idx, calls_ok):
            break

        pad_ok, pad_failed = _maybe_pad_probe(phase.name)
        # PSH-ARRPROBE: every dispatched call succeeded, but the planner may
        # still have refused to guess at part of the phase (e.g. 8 of 9 tracks
        # materialized, one lane unprobed). "ok" would overstate that.
        if blocked_reasons:
            _note_blocked()
            phase_outcomes.append(PhaseOutcome(
                name=phase.name, status=_STATUS_INCOMPLETE,
                calls_ok=calls_ok, calls_failed=0,
                pad_probes_ok=pad_ok, pad_probes_failed=pad_failed,
                blocked_reasons=blocked_reasons,
            ))
            _emit_progress(
                f"[{phase.name}] INCOMPLETE — {calls_ok} call(s) ok, "
                f"{len(blocked_reasons)} precondition(s) could not be determined"
            )
            continue
        phase_outcomes.append(PhaseOutcome(
            name=phase.name, status=_STATUS_OK,
            calls_ok=calls_ok, calls_failed=0,
            pad_probes_ok=pad_ok, pad_probes_failed=pad_failed,
        ))
        _emit_progress(f"[{phase.name}] ok ({calls_ok} call(s))")

    # Persist the terminal state (PSH-5T9D: the per-phase flushes above already
    # made it pollable mid-run; this is the final, current_phase=None write).
    # PSH-3K9D chunk 2: clear mid-phase progress so the terminal file is clean.
    phase_progress = None
    _flush_state(current_phase=None)

    # SYN-8Q3F review W1: the errors-file write must never leave the request
    # row open. Before this, a write failure here (disk full / permissions)
    # raised BEFORE close_request — reproducing the V4 symptom (open request +
    # escaping exception) one step after the class was closed. try/finally
    # guarantees close_request runs (the exception still propagates — a broken
    # state_dir is operator-actionable); the write itself gets the same atomic
    # temp + os.replace treatment as the state file, so a concurrent reader
    # never sees a torn errors file.
    top_patterns: list[dict[str, Any]] = []
    try:
        if error_records:
            grouped = _group_errors(error_records)
            errors_payload = {
                "ts": _now_iso(),
                "phase": halt_phase,
                "errors": error_records,
                "grouped_by_error": grouped,
            }
            tmp = errors_file.with_name(f".{errors_file.name}.tmp-{os.getpid()}")
            tmp.write_text(json.dumps(errors_payload, indent=2) + "\n")
            os.replace(tmp, errors_file)
            # Keep top 3 patterns for the CLI summary.
            top_patterns = grouped[:3]
        else:
            # Make sure a stale errors file from a prior partial run doesn't
            # confuse the agent reading state after a clean re-push.
            if errors_file.exists():
                errors_file.unlink()
    finally:
        # W23-C: close the request with the outcome the push reached.
        # request_outcome maps the push's tri-state (ok / partial /
        # connection_lost) onto REQUEST_OUTCOMES (ok / partial / failed).
        # connection_lost lands as 'failed' because nothing further could
        # happen; partial keeps its name.
        # PSH-ARRPROBE: 'incomplete' maps to 'partial' — the request DID land
        # work, just not all of it. Same bucket a halt uses; the state file's
        # per-phase blocked_reasons carry the distinction.
        request_outcome = {"ok": "ok", "incomplete": "partial",
                           "partial": "partial",
                           "connection_lost": "failed"}[outcome]
        M.close_request(
            conn,
            request_id=request_id,
            outcome=request_outcome,
            actor=actor,
            reason=reason,
        )

    return ExecuteResult(
        outcome=outcome,
        exit_code=exit_code,
        phase_halted=halt_phase,
        phases=phase_outcomes,
        state_file=state_file,
        errors_file=errors_file if error_records else None,
        top_error_patterns=top_patterns,
        warnings=warning_messages,
    )


def format_summary(result: ExecuteResult) -> str:
    """One-page text summary for stdout. Small by design — full detail lives
    in the JSON files."""
    if result.outcome == "ok":
        header = (
            f"push_cli execute: OK — all {len(result.phases)} phases completed"
        )
    elif result.outcome == "incomplete":
        # PSH-ARRPROBE: nothing failed and nothing halted, but a phase could not
        # determine part of its work and skipped it. Saying OK here is what let
        # a first push report success over an empty arrangement.
        stuck = [p for p in result.phases if p.status == _STATUS_INCOMPLETE]
        header = (
            f"push_cli execute: INCOMPLETE — "
            f"{len(stuck)} of {len(result.phases)} phase(s) could not determine "
            f"part of their work and pushed nothing for it "
            f"({', '.join(p.name for p in stuck)}). No call failed; the song "
            f"is NOT fully materialized."
        )
    elif result.outcome == "partial":
        ok_count = sum(1 for p in result.phases if p.status in {_STATUS_OK, _STATUS_SKIPPED})
        header = (
            f"push_cli execute: PARTIAL — halted at phase "
            f"{result.phase_halted!r} ({ok_count}/{len(result.phases)} phases ok)"
        )
    else:  # connection_lost
        ok_count = sum(1 for p in result.phases if p.status in {_STATUS_OK, _STATUS_SKIPPED})
        header = (
            f"push_cli execute: CONNECTION LOST — halted at phase "
            f"{result.phase_halted!r} ({ok_count}/{len(result.phases)} phases ok)"
        )

    lines: list[str] = [header, ""]
    for p in result.phases:
        if p.status == _STATUS_OK:
            mark = "[ok]  "
            detail = f"{p.calls_ok}/{p.calls_ok} ok"
        elif p.status == _STATUS_SKIPPED:
            mark = "[ok]  "
            detail = "skipped (nothing to push)"
        elif p.status == _STATUS_INCOMPLETE:
            # Never "skipped (idempotent)": nothing here was idempotent.
            mark = "[GAP] "
            n = len(p.blocked_reasons)
            if p.calls_ok:
                detail = (
                    f"{p.calls_ok}/{p.calls_ok} ok, INCOMPLETE — "
                    f"{n} could not be determined"
                )
            else:
                detail = (
                    f"NOT PUSHED — could not determine state "
                    f"({n} reason{'s' if n != 1 else ''})"
                )
        elif p.status == _STATUS_HALTED:
            mark = "[FAIL]"
            total = p.calls_ok + p.calls_failed
            detail = f"{p.calls_ok}/{total} ok, {p.calls_failed} failed -> halted"
        else:  # pending
            mark = "[--]  "
            detail = "pending"
        lines.append(f"  {mark} {p.name:<18} {detail}")
    lines.append("")
    if result.state_file:
        lines.append(f"state:  {result.state_file}")
    if result.errors_file:
        lines.append(f"errors: {result.errors_file}")
    if result.top_error_patterns:
        lines.append("")
        lines.append(f"Halt cause (phase {result.phase_halted!r}):")
        for pat in result.top_error_patterns:
            substr = pat["error_substring"]
            count = pat["count"]
            tool = pat.get("tool")
            action = pat.get("action")
            target = f"{tool}.{action}" if tool and action else (tool or "call")
            plural = "s" if count != 1 else ""
            lines.append(f"  - {target}: {substr!r} ({count} call{plural})")
            lines.append(f"    next: {_suggest_next_step(pat, outcome=result.outcome)}")
    # PSH-ARRPROBE: the un-determinable work, verbatim, in its own section —
    # above the benign warnings so it can't be read as one. This is the "what
    # is my song missing, and why" surface.
    # Keyed on blocked_reasons rather than the status, so reasons carried by a
    # phase that ALSO halted (a partial materialization caught downstream) still
    # print instead of being swallowed by the halt.
    incomplete_phases = [p for p in result.phases if p.blocked_reasons]
    if incomplete_phases:
        lines.append("")
        lines.append(
            "INCOMPLETE — pushed nothing for this, and did not guess "
            "(exit is non-zero):"
        )
        for p in incomplete_phases:
            for reason in p.blocked_reasons:
                lines.append(f"  - [{p.name}] {reason}")
        lines.append(
            "  next: fix the named precondition (a failed probe usually means "
            "Live was unreachable for that track — re-run `execute --probe`, "
            "which re-probes and is idempotent)."
        )
    # SYN-6B4Q: deferred-cue warnings are benign (the push is still OK) — show
    # them in their own section so they never read as a halt cause.
    if result.warnings:
        lines.append("")
        lines.append("Warnings (push still OK):")
        for w in result.warnings:
            lines.append(f"  - {w}")
    return "\n".join(lines) + "\n"


__all__ = [
    "EXIT_CONNECTION_LOST",
    "EXIT_OK",
    "EXIT_PARTIAL",
    "ExecuteResult",
    "PhaseOutcome",
    "execute_push",
    "format_summary",
]
