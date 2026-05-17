"""Wire protocol — canonical request/response shapes plus TCP framing.

The MCP server side and the Remote Script side exchange JSON messages over a
TCP socket. Framing is length-prefixed: each message is a 4-byte big-endian
unsigned-int length followed by exactly that many bytes of UTF-8 JSON.

TCP (not UDP, despite some early scratch notes saying otherwise):
  - Reliable, ordered, stream-based; the natural transport for a
    command-response loop where commands must succeed.
  - UDP's 64KB datagram cap is too small for browser tree / session
    snapshot reads.
  - Length-prefixed framing is the standard answer for "JSON over a TCP
    stream" — no JSON-decode-attempts-per-chunk pattern.
"""
from __future__ import annotations

import json
import socket as _socket  # noqa: F401  (used as a type hint target)
import struct
from dataclasses import dataclass, field
from typing import Any, Iterable


# Hallucinote-MCP listens on this port inside Live. Different from the legacy
# fork's 9877 so both can coexist while a user migrates.
DEFAULT_PORT: int = 9878
DEFAULT_HOST: str = "127.0.0.1"

_LENGTH_PREFIX_BYTES = 4
_MAX_MESSAGE_BYTES = 16 * 1024 * 1024  # 16 MiB — generous; guards runaway prefixes


@dataclass(frozen=True)
class Request:
    """Canonical request shape."""

    tool: str
    action: str
    params: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"tool": self.tool, "action": self.action, "params": dict(self.params)}

    @classmethod
    def from_dict(cls, obj: dict[str, Any]) -> "Request":
        if not isinstance(obj, dict):
            raise ValueError(f"request must be a dict, got {type(obj).__name__}")
        tool = obj.get("tool")
        action = obj.get("action")
        params = obj.get("params", {})
        if not isinstance(tool, str):
            raise ValueError("request.tool must be a string")
        if not isinstance(action, str):
            raise ValueError("request.action must be a string")
        if not isinstance(params, dict):
            raise ValueError("request.params must be an object")
        return cls(tool=tool, action=action, params=params)


@dataclass(frozen=True)
class Response:
    """Canonical response shape. ``ok=True`` carries a ``result``; ``ok=False``
    carries ``error`` plus optional teaching hints (``valid_actions``,
    ``required``, ``optional``, ``example``, ``hint``).

    ``needs_remote`` is an internal control-flow flag used between the
    server-side dispatcher and ``server.handle_tool_call``. When the
    server-side dispatch (context=None) determines that validation passed
    but execution requires Live, it sets this flag; the caller checks it
    and forwards the original request over TCP. The flag is intentionally
    not serialized to the wire — it would leak server-internal detail to
    the MCP client.
    """

    ok: bool
    result: Any = None
    error: str | None = None
    valid_actions: tuple[str, ...] | None = None
    required: tuple[str, ...] | None = None
    optional: tuple[str, ...] | None = None
    example: str | None = None
    hint: str | None = None
    needs_remote: bool = False

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"ok": self.ok}
        if self.ok:
            out["result"] = self.result
        else:
            out["error"] = self.error or ""
            if self.valid_actions is not None:
                out["valid_actions"] = list(self.valid_actions)
            if self.required is not None:
                out["required"] = list(self.required)
            if self.optional is not None:
                out["optional"] = list(self.optional)
            if self.example is not None:
                out["example"] = self.example
            if self.hint is not None:
                out["hint"] = self.hint
        return out


def ok(result: Any = None) -> Response:
    return Response(ok=True, result=result)


def error(
    message: str,
    *,
    valid_actions: Iterable[str] | None = None,
    required: Iterable[str] | None = None,
    optional: Iterable[str] | None = None,
    example: str | None = None,
    hint: str | None = None,
) -> Response:
    return Response(
        ok=False,
        error=message,
        valid_actions=tuple(valid_actions) if valid_actions is not None else None,
        required=tuple(required) if required is not None else None,
        optional=tuple(optional) if optional is not None else None,
        example=example,
        hint=hint,
    )


# ---------------------------------------------------------------------------
# Framing
# ---------------------------------------------------------------------------


class FrameError(Exception):
    """Raised when the wire bytes are malformed (bad length, truncated, etc.)."""


def encode_message(obj: dict[str, Any] | Request | Response) -> bytes:
    """Encode a dict / Request / Response as a length-prefixed frame."""
    if isinstance(obj, (Request, Response)):
        obj = obj.to_dict()
    payload = json.dumps(obj, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    if len(payload) > _MAX_MESSAGE_BYTES:
        raise ValueError(
            f"message of {len(payload)} bytes exceeds wire cap of "
            f"{_MAX_MESSAGE_BYTES} bytes"
        )
    return struct.pack(">I", len(payload)) + payload


def decode_messages(buffer: bytes) -> tuple[list[dict[str, Any]], bytes]:
    """Extract all complete messages from a buffer.

    Returns ``(messages, remaining_bytes)``. The caller is expected to
    accumulate the remaining bytes and call again when more data arrives.

    Raises ``FrameError`` if a length prefix exceeds the wire cap (indicates
    a corrupt stream).
    """
    messages: list[dict[str, Any]] = []
    pos = 0
    while pos + _LENGTH_PREFIX_BYTES <= len(buffer):
        (length,) = struct.unpack(">I", buffer[pos : pos + _LENGTH_PREFIX_BYTES])
        if length > _MAX_MESSAGE_BYTES:
            raise FrameError(
                f"declared message length {length} exceeds wire cap "
                f"{_MAX_MESSAGE_BYTES}; stream is likely corrupt"
            )
        msg_start = pos + _LENGTH_PREFIX_BYTES
        msg_end = msg_start + length
        if msg_end > len(buffer):
            break  # incomplete; wait for more bytes
        try:
            obj = json.loads(buffer[msg_start:msg_end].decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise FrameError(f"malformed JSON payload: {exc}") from exc
        if not isinstance(obj, dict):
            raise FrameError(
                f"top-level message must be a JSON object, got {type(obj).__name__}"
            )
        messages.append(obj)
        pos = msg_end
    return messages, buffer[pos:]


def recv_message(sock: _socket.socket, timeout: float | None = None) -> dict[str, Any]:
    """Blocking helper — read exactly one framed message from a socket.

    A ``socket.timeout`` during read is translated to ``FrameError`` so
    callers can handle "no message arrived" with the same exception class
    as other framing issues. Other ``OSError`` subclasses propagate.
    """
    if timeout is not None:
        sock.settimeout(timeout)
    try:
        header = _recv_exact(sock, _LENGTH_PREFIX_BYTES)
        (length,) = struct.unpack(">I", header)
        if length > _MAX_MESSAGE_BYTES:
            raise FrameError(
                f"declared message length {length} exceeds wire cap "
                f"{_MAX_MESSAGE_BYTES}"
            )
        payload = _recv_exact(sock, length)
    except _socket.timeout as exc:
        raise FrameError(f"socket read timed out after {timeout}s") from exc
    obj = json.loads(payload.decode("utf-8"))
    if not isinstance(obj, dict):
        raise FrameError(
            f"top-level message must be a JSON object, got {type(obj).__name__}"
        )
    return obj


def send_message(sock: _socket.socket, obj: dict[str, Any] | Request | Response) -> None:
    """Blocking helper — send a single framed message to a socket."""
    sock.sendall(encode_message(obj))


def _recv_exact(sock: _socket.socket, n: int) -> bytes:
    chunks: list[bytes] = []
    remaining = n
    while remaining > 0:
        chunk = sock.recv(remaining)
        if not chunk:
            raise FrameError(
                f"socket closed after {n - remaining} of {n} expected bytes"
            )
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


__all__ = [
    "DEFAULT_PORT",
    "DEFAULT_HOST",
    "Request",
    "Response",
    "ok",
    "error",
    "FrameError",
    "encode_message",
    "decode_messages",
    "recv_message",
    "send_message",
]
