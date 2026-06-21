"""W10-E2: bulk push dispatcher that bypasses the agent's tool-use channel.

The thirteen-phase push planner emits plans the agent has historically dispatched
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

    Raised by :func:`_filter_phases`; the CLI catches it and exits 2 with the
    teaching message (which lists the valid phases in order).
    """


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

    Raises :class:`PhaseTargetError` (teaching message + valid-phase list) on an
    unknown phase name, ``--only`` combined with a window flag, or a window whose
    stop precedes its start.
    """
    names = [p.name for p in phases]

    def _check(flag: str, value: str | None) -> None:
        if value is not None and value not in names:
            raise PhaseTargetError(
                f"unknown {flag} phase {value!r}. Valid phases (in order): "
                + ", ".join(names)
            )

    _check("--only", only)
    _check("--start-at", start_at)
    _check("--stop-after", stop_after)

    if only is not None:
        if start_at is not None or stop_after is not None:
            raise PhaseTargetError(
                "--only cannot be combined with --start-at/--stop-after"
            )
        return tuple(p for p in phases if p.name == only), {"only": only}

    lo = names.index(start_at) if start_at is not None else 0
    hi = names.index(stop_after) if stop_after is not None else len(names) - 1
    if hi < lo:
        raise PhaseTargetError(
            f"--stop-after {stop_after!r} precedes --start-at {start_at!r} "
            "in the phase order"
        )
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


@dataclass
class ExecuteResult:
    """Returned to the CLI for stdout summarization. Mirrors the on-disk state
    file contents minus the per-error detail (those go in errors_file)."""
    outcome: str  # "ok" | "partial" | "connection_lost"
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
) -> ExecuteResult:
    """Run the full thirteen-phase push, dispatching each call via ``send_fn``.

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
    state_file = state_dir / ".last-push-state.json"
    errors_file = state_dir / ".last-push-errors.json"

    # PSH-2R7K: plan + resolve phase-targeting BEFORE creating the request, so a
    # bad --only/--start-at/--stop-after fails fast (PhaseTargetError) without
    # leaving a dangling open audit row. plan_push_song is pure-data (no side
    # effects), so the reorder is safe.
    phases = push.plan_push_song(
        conn, song_id=song_id, session_id=session_id,
        perform_slowdown_factor=perform_slowdown_factor,
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
                       if p.status in {_STATUS_OK, _STATUS_HALTED}
                       else {}),
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

            if not ok:
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

    def _apply_results(batch: list[dict[str, Any]], phase_name: str) -> None:
        """Apply successes regardless of failure mix — push is idempotent and
        link rows must be live before the next phase (or the devices-phase
        convergence pass) plans."""
        apply_warnings = push.apply_push_results(
            conn,
            batch,
            session_id=session_id,
            actor=actor,
            request_id=request_id,
            reason=reason or f"push_cli execute phase={phase_name}",
        )
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

    def _drain_plan_warnings(plan_obj) -> None:
        """SYN-9F2L: a planner records an operator-actionable, non-fatal warning
        (e.g. a params_dialed write with no writable form) in ``plan.alerts``.
        ``execute`` is the only operator-visible surface on this path, so route
        alerts into the benign warnings channel — otherwise the warn is silently
        discarded, the exact silent-drop SYN-9F2L exists to prevent. Drains
        ``alerts`` (operator-facing), NOT ``notes`` (diagnostic "nothing to
        push" / "not linked yet" noise). Deduped by message so the devices-phase
        convergence re-plan (which regenerates the full plan, alerts included)
        doesn't double-report an already-surfaced warning."""
        for alert in plan_obj.alerts:
            if alert not in warning_messages:
                warning_messages.append(alert)

    def _halt(phase_name: str, idx: int, *, outcome_label: str,
              exit_code_val: int, calls_ok: int, calls_failed: int) -> None:
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
        ))
        halt_phase = phase_name
        outcome = outcome_label
        exit_code = exit_code_val
        for remaining in phases[idx + 1:]:
            phase_outcomes.append(PhaseOutcome(
                name=remaining.name, status=_STATUS_PENDING, calls_planned=0,
            ))
        _emit_progress(f"[{phase_name}] HALTED — {outcome_label}")

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
            )
            break

        if not plan.calls:
            pad_ok, pad_failed = _maybe_pad_probe(phase.name)
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
        if results:
            _apply_results(results, phase.name)

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
            and results
            and all(r.get("ok") for r in results)
        ):
            replan = phase.plan_fn()
            # SYN-9F2L: a device loaded THIS pass was unlinked when the primary
            # plan ran, so its params (and any unwritable-form warning) first
            # become visible in this re-plan — drain its new notes too, or the
            # same-pass case stays silent.
            _drain_plan_warnings(replan)
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
                        _apply_results(extra_results, phase.name)

        calls_ok = sum(1 for r in results if r.get("ok"))
        calls_failed = sum(1 for r in results if not r.get("ok"))

        if connection_lost:
            _halt(
                phase.name, idx, outcome_label="connection_lost",
                exit_code_val=EXIT_CONNECTION_LOST, calls_ok=calls_ok,
                calls_failed=calls_failed + 1,
            )
            break

        if calls_failed > 0:
            _halt(
                phase.name, idx, outcome_label="partial",
                exit_code_val=EXIT_PARTIAL, calls_ok=calls_ok,
                calls_failed=calls_failed,
            )
            break

        pad_ok, pad_failed = _maybe_pad_probe(phase.name)
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

    top_patterns: list[dict[str, Any]] = []
    if error_records:
        grouped = _group_errors(error_records)
        errors_payload = {
            "ts": _now_iso(),
            "phase": halt_phase,
            "errors": error_records,
            "grouped_by_error": grouped,
        }
        errors_file.write_text(json.dumps(errors_payload, indent=2) + "\n")
        # Keep top 3 patterns for the CLI summary.
        top_patterns = grouped[:3]
    else:
        # Make sure a stale errors file from a prior partial run doesn't
        # confuse the agent reading state after a clean re-push.
        if errors_file.exists():
            errors_file.unlink()

    # W23-C: close the request with the outcome the push reached.
    # request_outcome maps the push's tri-state (ok / partial / connection_lost)
    # onto REQUEST_OUTCOMES (ok / partial / failed). connection_lost lands as
    # 'failed' because nothing further could happen; partial keeps its name.
    request_outcome = {"ok": "ok", "partial": "partial",
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
            detail = "skipped (idempotent)"
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
