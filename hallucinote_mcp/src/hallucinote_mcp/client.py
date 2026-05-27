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


def send(
    request: Request,
    *,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    connect_timeout: float = 15.0,
    read_timeout: float | None = 15.0,
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
        request lands on the wire. Long-running handlers (``ableton_render``
        plays the entire arrangement before responding — minutes for a full
        song) require a generous ceiling. ``None`` means "block forever";
        the server-side dispatcher (``server.handle_tool_call``) passes
        ``None`` for ``ableton_render(render)`` since the handler is
        synchronous-on-completion. Default 15s matches every other action's
        contract — those that don't block on transport should respond
        within Live's main-thread budget.
    """
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
    )


def _maybe_tuple(value: Any) -> tuple[str, ...] | None:
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        return tuple(str(v) for v in value)
    return None


__all__ = ["LiveConnectionError", "send"]
