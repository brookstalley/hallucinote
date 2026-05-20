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
            result_payload = getattr(resp, "result", None) if ok else None
            err_msg = getattr(resp, "error", None) if not ok else None
            hint = getattr(resp, "hint", None) if not ok else None

            results.append({
                "key": call.key,
                "tool": call.tool,
                "ok": ok,
                "result": result_payload,
                "error": err_msg,
            })

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
