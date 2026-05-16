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

import socket
from typing import Any

from . import wire
from .wire import DEFAULT_HOST, DEFAULT_PORT, Request, Response


class LiveConnectionError(Exception):
    """Raised when the Remote Script side is unreachable."""


def send(
    request: Request,
    *,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    timeout: float = 15.0,
) -> Response:
    """Send a request to the Remote Script; return the parsed response.

    Raises ``LiveConnectionError`` if the socket can't be opened. Wire-level
    framing errors (``wire.FrameError``) propagate — those are protocol bugs,
    not connection bugs, and should not be silently translated.
    """
    try:
        sock = socket.create_connection((host, port), timeout=timeout)
    except OSError as exc:
        raise LiveConnectionError(
            f"could not reach Hallucinote Remote Script at {host}:{port}: {exc}. "
            f"Is Ableton Live running with Hallucinote selected as a Control Surface?"
        ) from exc

    try:
        wire.send_message(sock, request)
        reply = wire.recv_message(sock, timeout=timeout)
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
    is_ok = bool(obj.get("ok"))
    if is_ok:
        return Response(ok=True, result=obj.get("result"))
    return Response(
        ok=False,
        error=obj.get("error", ""),
        valid_actions=_maybe_tuple(obj.get("valid_actions")),
        required=_maybe_tuple(obj.get("required")),
        optional=_maybe_tuple(obj.get("optional")),
        example=obj.get("example"),
        hint=obj.get("hint"),
    )


def _maybe_tuple(value: Any) -> tuple[str, ...] | None:
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        return tuple(str(v) for v in value)
    return None


__all__ = ["LiveConnectionError", "send"]
