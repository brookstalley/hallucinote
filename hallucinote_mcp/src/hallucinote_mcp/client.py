"""TCP client — talks from the MCP server side to the Remote Script side.

The MCP server runs as a separate process from Ableton Live. Each MCP tool
invocation translates to a ``wire.Request``, ships over a short-lived TCP
connection to the Remote Script's listening port, and reads back a
``wire.Response``.

Short-lived connections (per request) keep the model simple: no connection
state to manage, no reconnect logic, no head-of-line blocking across calls.
At single-user, single-Live latencies (sub-millisecond loopback) the cost
is negligible.
"""
from __future__ import annotations

import dataclasses
import socket
from typing import Any

from . import __version__, wire
from .wire import DEFAULT_HOST, DEFAULT_PORT, Request, Response


class LiveConnectionError(Exception):
    """Raised when the Remote Script side is unreachable."""


# Read-timeout policy per (tool, action) — THE single source of truth for both
# wire-recv paths (the server's agent-forward AND push_cli's direct dispatch),
# so a long-running handler can't outrun the socket on one route while being
# safe on the other (the ENV-9P4T blocker: perform_batch was safe on the
# server route but the push route hit the 15s default and severed verification).
# The default suits actions that return within Live's main-thread budget; a few
# break it by design and need a wider (or no) window:
#   - ableton_render(start): mints a job handle + spawns the detached render
#     worker, then returns immediately (< ~3s) → the default suits it; the
#     realtime full-arrangement playback runs on the worker, NOT on this
#     forwarded call. (The synchronous `render` action that DID block here for
#     minutes — needing an unbounded socket — was retired, MCP-9R3T.)
#   - ableton_automation(perform_batch): plays the union span of all changed
#     arcs in record (minutes at mix scale) → unbounded; the HANDLER owns the
#     timeout via its own ramp deadline + finally-restore, so a socket cutoff
#     here would discard the only verification this write-only surface has.
#   - ableton_render(ensure_loaded): loads the analyzer onto 25+ surfaces, each
#     a few seconds on the main thread → a generous BOUNDED ceiling so a stuck
#     load still surfaces as a timeout (MCP-4T6Y).
#   - ableton_render(status): long-polls the render job ~45s before returning, so
#     the socket read window must exceed that long-poll (else the socket severs
#     the poll mid-wait). Bounded just above the handler's long-poll; the
#     long-poll itself must stay under the Claude Code tool-call timeout (raise
#     .mcp.json `timeout` if you widen it). NOTE: start (not listed) returns
#     immediately, so the default suits it. (MCP-9R3T async render.)
#   - ableton_device(load): a browser load runs on Live's main thread and its
#     cost scales with the ITEM, not with our call. A Max for Live patch is the
#     worst case — HallucinoteAnalyzer.amxd is ~490 KB and Live blocks for tens
#     of seconds instantiating it, during which NO other request is answered
#     (measured: a single master-track analyzer load severed the socket twice at
#     the 15s default). Large sampled instrument racks behave the same way.
#     Bounded, not unbounded: a load that never returns is a real failure and
#     must still surface as a timeout rather than hanging the caller forever.
#   - ableton_device(get_parameters): `detail='full'` enumerates every parameter
#     on the addressed node. On a big sampled rack (a Brass Ensemble, a 16-pad
#     Drum Rack) that walk exceeds the default and aborts a whole capture —
#     which is how `capture execute` died mid-walk with a bare FrameError.
_DEFAULT_READ_TIMEOUT: float = 15.0
_ENSURE_LOADED_READ_TIMEOUT: float = 180.0
_STATUS_READ_TIMEOUT: float = 60.0
_DEVICE_LOAD_READ_TIMEOUT: float = 120.0
_GET_PARAMETERS_READ_TIMEOUT: float = 90.0
_READ_TIMEOUTS: dict[tuple[str, str], float | None] = {
    ("ableton_automation", "perform_batch"): None,
    ("ableton_render", "ensure_loaded"): _ENSURE_LOADED_READ_TIMEOUT,
    ("ableton_render", "status"): _STATUS_READ_TIMEOUT,
    ("ableton_device", "load"): _DEVICE_LOAD_READ_TIMEOUT,
    ("ableton_device", "get_parameters"): _GET_PARAMETERS_READ_TIMEOUT,
}


def read_timeout_for(tool: str, action: str) -> float | None:
    """Select the socket read timeout for a (tool, action). ``None`` =
    unbounded (block until the handler responds); a float = a bounded ceiling;
    the default for everything else."""
    return _READ_TIMEOUTS.get((tool, action), _DEFAULT_READ_TIMEOUT)


# Sentinel: caller did not specify read_timeout → resolve from the policy by
# (tool, action). Distinct from ``None``, which is an explicit "block forever".
_UNSET_READ_TIMEOUT: Any = object()


def send(
    request: Request,
    *,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    connect_timeout: float = 15.0,
    read_timeout: float | None = _UNSET_READ_TIMEOUT,
) -> Response:
    """Send a request to the Remote Script; return the parsed response.

    Stamps the request with this process's ``hallucinote_mcp.__version__``
    when the caller didn't set ``server_version`` explicitly. The Live side
    uses that field to detect a stale Remote Script and surface a clear
    recovery action. An explicit value is preserved as-is so tests can
    drive the mismatch path.

    Raises ``LiveConnectionError`` if the socket can't be opened. Wire-level
    framing errors (``wire.FrameError``) propagate — those are protocol bugs,
    not connection bugs, and should not be silently translated.

    Two timeouts because the failure modes are different:

      - ``connect_timeout`` bounds how long we wait for Live's TCP listener
        to accept. The Remote Script is either up or it isn't; if it can't
        accept within 15 s it's not coming back this call.
      - ``read_timeout`` bounds how long we wait for the response after the
        request lands on the wire. Long-running handlers (e.g.
        ``ableton_automation(perform_batch)`` records the union span in realtime
        — minutes) require a generous (or no) ceiling. (``ableton_render`` is no
        longer one of these on the forwarded call: its ``start`` returns a job
        handle in ~3s — the realtime playback runs on a detached worker — and
        ``status`` long-polls under a bounded ceiling.) **When the caller doesn't
        specify, it is
        resolved from the (tool, action) policy** (``read_timeout_for``) so
        BOTH wire-recv routes — the server's agent-forward and push_cli's
        direct dispatch — get the same window without each caller re-deriving
        it. An explicit value (incl. ``None`` = block forever) is honored as
        passed; default for most actions is 15s (Live's main-thread budget).
    """
    if read_timeout is _UNSET_READ_TIMEOUT:
        read_timeout = read_timeout_for(request.tool, request.action)
    if not request.server_version:
        request = dataclasses.replace(request, server_version=__version__)

    try:
        sock = socket.create_connection((host, port), timeout=connect_timeout)
    except OSError as exc:
        raise LiveConnectionError(
            f"could not reach Hallucinote Remote Script at {host}:{port}: {exc}. "
            f"Is Ableton Live running with Hallucinote selected as a Control Surface?"
        ) from exc

    try:
        wire.send_message(sock, request)
        reply = wire.recv_message(sock, timeout=read_timeout)
    finally:
        try:
            sock.close()
        except OSError:
            pass

    return _response_from_dict(reply)


def _response_from_dict(obj: dict[str, Any]) -> Response:
    """Translate a wire dict back to a typed Response.

    The Remote Script side serializes ``Response.to_dict()``; we round-trip
    back into the dataclass for type-safe access on the server side.
    """
    warnings = _maybe_tuple(obj.get("warnings"))
    is_ok = bool(obj.get("ok"))
    if is_ok:
        return Response(ok=True, result=obj.get("result"), warnings=warnings)
    return Response(
        ok=False,
        error=obj.get("error", ""),
        valid_actions=_maybe_tuple(obj.get("valid_actions")),
        required=_maybe_tuple(obj.get("required")),
        optional=_maybe_tuple(obj.get("optional")),
        example=obj.get("example"),
        hint=obj.get("hint"),
        warnings=warnings,
        code=obj.get("code"),
    )


def _maybe_tuple(value: Any) -> tuple[str, ...] | None:
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        return tuple(str(v) for v in value)
    return None


__all__ = ["LiveConnectionError", "send", "read_timeout_for"]
