"""W10-E2: bulk push dispatcher that bypasses the agent's tool-use channel.

The ten-phase push planner emits plans the agent has historically dispatched
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
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from hallucinote.db import mutations as M
from hallucinote.sync import push

# Imported lazily inside execute_push() to keep the unit-test import graph
# light. The MCP package is a sibling install; tests substitute send_fn
# directly and never touch it.


# Exit codes — documented in the design artifact.
EXIT_OK = 0
EXIT_PARTIAL = 1
EXIT_CONNECTION_LOST = 2


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


@dataclass
class PhaseOutcome:
    name: str
    status: str  # one of _STATUS_*
    calls_ok: int = 0
    calls_failed: int = 0
    calls_planned: int = 0  # for pending phases — how many they would have run


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


def _search_root_for_kind(kind: str) -> str:
    """Pick the canonical browser root for a fallback search by device kind.

    Plugin classes go to the ``plugins`` root (PluginDevice / AuPluginDevice /
    Vst3PluginDevice etc. — substring 'Plugin' matches the lot per
    ``sync/compat.py`` discriminator). Drum racks go to ``drums``. All
    others (instruments + unknown built-ins) default to ``instruments``,
    which is the broadest signal for missing-built-in cases.
    """
    if "Plugin" in kind:
        return "plugins"
    if kind == "DrumGroupDevice":
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
        "SELECT kind, display_name FROM devices WHERE id = ?",
        (device_id,),
    ).fetchone()
    if row is None:
        return None
    kind = row["kind"]
    display_name = (row["display_name"] or "").strip()
    if not display_name:
        return None

    root = _search_root_for_kind(kind)
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
    except Exception:  # prawduct:ok-broad-except — fallback must not crash the push loop; failure → no fallback
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
    except Exception:  # prawduct:ok-broad-except — fallback must not crash the push loop; failure → no fallback
        return None
    if not bool(getattr(retry_resp, "ok", False)):
        return None
    return retry_resp, fallback_uri


def _group_errors(errors: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group error records by message substring for pattern-spotting.

    The substring is the first 60 chars of the error message — long enough
    to disambiguate distinct failures, short enough that ``RuntimeError:
    Couldn't create clip — slot 3`` and ``... slot 7`` group together.
    """
    groups: dict[str, list[str]] = {}
    for e in errors:
        substr = (e.get("error") or "")[:60]
        groups.setdefault(substr, []).append(e["key"])
    return [
        {"error_substring": substr, "count": len(keys), "affected_keys": keys}
        for substr, keys in sorted(groups.items(), key=lambda kv: -len(kv[1]))
    ]


def execute_push(
    *,
    conn: sqlite3.Connection,
    song_id: str,
    session_id: str,
    state_dir: Path,
    send_fn: Callable[..., Any] | None = None,
    actor: str = "sync",
    reason: str | None = None,
) -> ExecuteResult:
    """Run the full ten-phase push, dispatching each call via ``send_fn``.

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
        payload={"session_id": session_id, "song_id": song_id},
        song_id=song_id,
        reason=reason,
    )

    phases = push.plan_push_song(conn, song_id=song_id, session_id=session_id)

    phase_outcomes: list[PhaseOutcome] = []
    halt_phase: str | None = None
    outcome = "ok"
    exit_code = EXIT_OK
    error_records: list[dict[str, Any]] = []
    error_phase: str | None = None

    for idx, phase in enumerate(phases):
        plan = phase.plan_fn()
        if not plan.calls:
            phase_outcomes.append(PhaseOutcome(name=phase.name, status=_STATUS_SKIPPED))
            continue

        results: list[dict[str, Any]] = []
        connection_lost = False

        for call in plan.calls:
            action = call.args.get("action")
            params = {k: v for k, v in call.args.items() if k != "action"}
            req = Request(tool=call.tool, action=action or "", params=params)
            try:
                resp = send_fn(req)
            except _CONNECTION_EXCS as exc:
                # Connection-class failure (Live unreachable, socket error).
                # Halt immediately — no point continuing without Live. Wire
                # protocol bugs (wire.FrameError) and other unexpected
                # exceptions propagate so they're not mislabeled here.
                connection_lost = True
                error_records.append({
                    "key": call.key,
                    "tool": call.tool,
                    "action": action,
                    "args_summary": _summarize_args(call.args),
                    "error": f"{type(exc).__name__}: {exc}",
                    "hint": None,
                })
                break

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

            result_payload = getattr(resp, "result", None) if ok else None
            hint = getattr(resp, "hint", None) if not ok else None

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

        # Apply successes regardless of failure mix — push is idempotent and
        # link rows must be live before the next phase plans. For
        # connection-lost the loop broke before any subsequent ok rows could
        # accumulate, so this is safe.
        if results:
            push.apply_push_results(
                conn,
                results,
                session_id=session_id,
                actor=actor,
                request_id=request_id,
                reason=reason or f"push_cli execute phase={phase.name}",
            )

        calls_ok = sum(1 for r in results if r.get("ok"))
        calls_failed = sum(1 for r in results if not r.get("ok"))

        if connection_lost:
            phase_outcomes.append(PhaseOutcome(
                name=phase.name, status=_STATUS_HALTED,
                calls_ok=calls_ok, calls_failed=calls_failed + 1,
            ))
            halt_phase = phase.name
            error_phase = phase.name
            outcome = "connection_lost"
            exit_code = EXIT_CONNECTION_LOST
            # Mark remaining phases as pending so the state file is uniform.
            for remaining in phases[idx + 1:]:
                phase_outcomes.append(PhaseOutcome(
                    name=remaining.name, status=_STATUS_PENDING,
                    calls_planned=0,
                ))
            break

        if calls_failed > 0:
            phase_outcomes.append(PhaseOutcome(
                name=phase.name, status=_STATUS_HALTED,
                calls_ok=calls_ok, calls_failed=calls_failed,
            ))
            halt_phase = phase.name
            error_phase = phase.name
            outcome = "partial"
            exit_code = EXIT_PARTIAL
            for remaining in phases[idx + 1:]:
                phase_outcomes.append(PhaseOutcome(
                    name=remaining.name, status=_STATUS_PENDING,
                    calls_planned=0,
                ))
            break

        phase_outcomes.append(PhaseOutcome(
            name=phase.name, status=_STATUS_OK,
            calls_ok=calls_ok, calls_failed=0,
        ))

    # Persist state + errors.
    state_payload = {
        "ts": _now_iso(),
        "song_id": song_id,
        "session_id": session_id,
        "outcome": outcome,
        "phase_halted": halt_phase,
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
            }
            for p in phase_outcomes
        ],
        "errors_file": errors_file.name if error_records else None,
    }
    state_file.write_text(json.dumps(state_payload, indent=2) + "\n")

    top_patterns: list[dict[str, Any]] = []
    if error_records:
        grouped = _group_errors(error_records)
        errors_payload = {
            "ts": _now_iso(),
            "phase": error_phase,
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
        lines.append("Top error patterns:")
        for pat in result.top_error_patterns:
            substr = pat["error_substring"]
            count = pat["count"]
            lines.append(f"  - {substr!r} ({count} occurrences)")
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
