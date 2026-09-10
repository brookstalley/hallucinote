"""Resolving a Live call that outran its main-thread ceiling.

A `run_on_main` bout that exceeds Live's ceiling does NOT come back as a
failure. It comes back as an ESCALATION — `ok=True`, `code='work_escalated'`,
carrying a job handle — because Python cannot interrupt a Live API call, so
neither "done" nor "failed" is true yet. The work is still executing.

**Any engine module that dispatches MCP calls has to know this**, and the
shape of the mistake is specific: an unwrapper that reads `ok` and returns the
result books an escalation as a completed call. A device load recorded as
landed while Live is still loading it makes the next call in the sequence hit
an occupied bout and be refused — which, inside a destructive sequence like a
chain rebuild, raises partway through the one operation that must not fail
partway through.

That is why this lives here rather than inside one caller: the wire contract
has more than one consumer, and a second one learning it by being broken is
how the first one found out.

The `hallucinote_mcp` import stays lazy in the callers — this module takes
`request_cls` and `send_fn` and never imports the MCP package itself, so it is
importable in a checkout that has no MCP install.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable


# Python cannot interrupt a Live API call, so neither "done" nor "failed" is
# true yet. The executor must not read that as success (the write has not
# landed) nor as failure (it may still land): it polls the handle to a terminal
# state and reports what actually happened.
ESCALATION_CODE = "work_escalated"
# How long to wait between polls, and how long to keep polling before giving
# up. The ceiling is generous because the escalated operation is uncancellable
# — a device load of a large Max device is the witnessed case — and because
# giving up does not stop it. When it expires the step FAILS honestly, naming
# the job so an operator can keep watching it.
ESCALATION_POLL_INTERVAL_S = 2.0
ESCALATION_POLL_CEILING_S = 600.0


@dataclass
class PolledResponse:
    """Response-shaped stand-in for the terminal outcome of an escalated call.

    The dispatch loop duck-types responses (``ok`` / ``result`` / ``error`` /
    ``hint``), so the polled outcome substitutes for the escalation reply and
    every downstream branch — fallbacks, apply, error records — reads the real
    answer instead of a handle.
    """

    ok: bool
    result: Any = None
    error: str | None = None
    hint: str | None = None
    code: str | None = None


def escalated_job_id(resp: Any) -> str | None:
    """The job id of an escalation reply, or ``None`` for an ordinary one.

    Reads BOTH the ``code`` discriminator and the ``escalated`` flag in the
    result: the code is the contract, and the payload flag is what survives a
    client that does not carry ``code`` through on the ok path.
    """
    if not bool(getattr(resp, "ok", False)):
        return None
    payload = getattr(resp, "result", None)
    flagged = (
        isinstance(payload, dict) and payload.get("escalated") is True
    )
    if getattr(resp, "code", None) != ESCALATION_CODE and not flagged:
        return None
    job_id = payload.get("job_id") if isinstance(payload, dict) else None
    return str(job_id) if job_id else None


def await_escalated(
    *,
    job_id: str,
    label: str,
    send_fn: Callable[..., Any],
    request_cls: type,
    progress_fn: Callable[[str], None],
    warnings_sink: Callable[[str], None],
) -> PolledResponse:
    """Poll an escalated main-thread call to a terminal state.

    Live is still executing the work; ``ableton_session(action='bout_status')``
    runs on the worker thread precisely so it can answer while the main thread
    is fenced. Returns the call's real outcome — its own result on ``done``, an
    error on ``failed``, and an error naming the job if the ceiling passes with
    the work still running (which is the honest report: we stopped watching,
    the work did not stop).
    """
    deadline = time.monotonic() + ESCALATION_POLL_CEILING_S
    progress_fn(
        f"[escalated] {label} outran Live's ceiling and is still running — "
        f"polling job {job_id}"
    )
    while True:
        poll = send_fn(request_cls(
            tool="ableton_session",
            action="bout_status",
            params={"job_id": job_id},
        ))
        if not bool(getattr(poll, "ok", False)):
            return PolledResponse(
                ok=False,
                error=(
                    f"{label} was escalated to job {job_id} and the poll for "
                    f"it failed: {getattr(poll, 'error', None)}"
                ),
                hint=(
                    "The original call may still be running on Live's main "
                    "thread. Check ableton_session(action='bout_status') "
                    "before re-pushing — a retry queues behind work Live "
                    "cannot cancel."
                ),
            )
        job = (getattr(poll, "result", None) or {}).get("job") or {}
        state = job.get("state")
        if state == "done":
            warnings_sink(
                f"{label}: outran Live's main-thread ceiling and was polled "
                f"to completion via job {job_id} — the call succeeded, it was "
                f"just slower than the ceiling allows"
            )
            return PolledResponse(ok=True, result=job.get("result"))
        if state == "failed":
            return PolledResponse(
                ok=False,
                error=(
                    f"{label} (escalated to job {job_id}) failed in Live: "
                    f"{job.get('error')}"
                ),
                hint=(
                    "The call outran Live's main-thread ceiling and then "
                    "failed. The error above is Live's own; the escalation "
                    "only changed how it was reported."
                ),
            )
        if time.monotonic() >= deadline:
            return PolledResponse(
                ok=False,
                error=(
                    f"{label} (escalated to job {job_id}) was STILL RUNNING "
                    f"after {ESCALATION_POLL_CEILING_S:.0f}s of polling. It "
                    f"has not failed — Live cannot be made to abandon it — "
                    f"but this push stopped waiting for it."
                ),
                hint=(
                    f"Poll it yourself with ableton_session("
                    f"action='bout_status', job_id='{job_id}'). Do NOT "
                    f"re-push until it reaches a terminal state: every call "
                    f"you send now queues behind it, which is how a slow "
                    f"operation becomes an unresponsive Live."
                ),
            )
        time.sleep(ESCALATION_POLL_INTERVAL_S)


__all__ = [
    "ESCALATION_CODE",
    "ESCALATION_POLL_CEILING_S",
    "ESCALATION_POLL_INTERVAL_S",
    "PolledResponse",
    "await_escalated",
    "escalated_job_id",
]
