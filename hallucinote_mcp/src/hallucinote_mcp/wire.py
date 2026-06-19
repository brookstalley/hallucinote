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
    """Canonical request shape.

    ``server_version`` carries the MCP server's ``hallucinote_mcp.__version__``
    so the Live-side handler can detect a stale Remote Script and surface a
    clear recovery action instead of the agent decoding "unknown action"
    errors caused by version drift. Empty means the sender didn't populate
    it; the Live side treats that as "MCP server too old to handshake".

    ``allow_version_mismatch`` is a per-call escape hatch from the strict
    handshake — when ``True`` and version drift exists, the Remote Script
    dispatches the action anyway and attaches a warning to the response.
    Intended for the development loop where every server-side Python edit
    invalidates the source fingerprint and otherwise blocks introspection
    until reinstall + Live restart. **Bypass can result in data corruption**
    on mutating calls — see the warning text the helper attaches.
    """

    tool: str
    action: str
    params: dict[str, Any] = field(default_factory=dict)
    server_version: str = ""
    allow_version_mismatch: bool = False

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "tool": self.tool,
            "action": self.action,
            "params": dict(self.params),
        }
        if self.server_version:
            out["server_version"] = self.server_version
        if self.allow_version_mismatch:
            out["allow_version_mismatch"] = True
        return out

    @classmethod
    def from_dict(cls, obj: dict[str, Any]) -> "Request":
        if not isinstance(obj, dict):
            raise ValueError(f"request must be a dict, got {type(obj).__name__}")
        tool = obj.get("tool")
        action = obj.get("action")
        params = obj.get("params", {})
        server_version = obj.get("server_version", "")
        allow_version_mismatch = obj.get("allow_version_mismatch", False)
        if not isinstance(tool, str):
            raise ValueError("request.tool must be a string")
        if not isinstance(action, str):
            raise ValueError("request.action must be a string")
        if not isinstance(params, dict):
            raise ValueError("request.params must be an object")
        if not isinstance(server_version, str):
            raise ValueError("request.server_version must be a string")
        if not isinstance(allow_version_mismatch, bool):
            raise ValueError("request.allow_version_mismatch must be a boolean")
        return cls(
            tool=tool,
            action=action,
            params=params,
            server_version=server_version,
            allow_version_mismatch=allow_version_mismatch,
        )


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

    ``warnings`` carries advisory messages that ride alongside the response
    without changing ``ok``. The only producer today is the
    ``allow_version_mismatch`` bypass — when a caller opts into dispatching
    across version drift, the Remote Script attaches a "can result in data
    corruption" advisory so the bypass remains visible end-to-end. Use the
    same shape for any future advisory that shouldn't fail the call but
    must reach the caller.
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
    warnings: tuple[str, ...] | None = None
    # Stable machine-readable discriminator for errors the MCP server side
    # post-processes. Today the only producer is the version handshake
    # (``VERSION_MISMATCH_CODE``), which the server uses to refine the
    # remediation hint (re-vendor vs. respawn the server process). Optional
    # and serialized only when set, so it is backward-compatible with a
    # vendored Remote Script that predates it.
    code: str | None = None

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
            if self.code is not None:
                out["code"] = self.code
        if self.warnings:
            out["warnings"] = list(self.warnings)
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
    code: str | None = None,
) -> Response:
    return Response(
        ok=False,
        error=message,
        valid_actions=tuple(valid_actions) if valid_actions is not None else None,
        required=tuple(required) if required is not None else None,
        optional=tuple(optional) if optional is not None else None,
        example=example,
        hint=hint,
        code=code,
    )


# ---------------------------------------------------------------------------
# Version handshake
# ---------------------------------------------------------------------------

#: Discriminator the Remote Script side stamps onto a version-mismatch
#: refusal so the MCP server side can refine the remediation (the
#: Remote-Script-side hint can only guess "re-vendor"; the server side
#: knows whether its own *process* is the stale half — see
#: ``hallucinote_mcp.stale_server_process_hint``).
VERSION_MISMATCH_CODE = "version_mismatch"


def check_version_compat(
    request_version: str, local_version: str
) -> Response | None:
    """Compare the version reported by the MCP server side to the local
    ``hallucinote_mcp.__version__`` on the Remote Script side.

    Returns ``None`` when the versions match (caller proceeds to dispatch).
    Returns a structured ``Response`` error when they don't — naming both
    versions and pointing to the recovery action. Strict equality on
    purpose: any version drift can change the wire shape, action surface,
    or handler logic, and the cost of a false positive (re-run install) is
    tiny compared to the cost of a false negative (silent "unknown action"
    errors that take minutes to diagnose — the exact failure mode that
    motivated this check).

    Three branches:

    * **match**: ``request_version == local_version`` → ``None``.
    * **missing**: ``request_version`` is empty → the MCP server didn't
      send the field at all, so it predates this handshake. The user
      should upgrade the pip package.
    * **mismatch**: both set but different → typically the Remote Script
      is stale (the MCP server side updates more freely; the Remote Script
      requires a re-copy plus Live restart). The user should re-run
      ``/ableton-mcp-install`` and restart Live.
    """
    if not request_version:
        return error(
            "Hallucinote MCP version handshake missing: the installed "
            f"hallucinote-mcp package didn't send its version. "
            f"Remote Script side is running {local_version}. The MCP server "
            f"side is likely older than {local_version} and predates the "
            f"version handshake.",
            hint=(
                "Upgrade the MCP server side — `pip install -U "
                "hallucinote-mcp` — then run `/mcp` in Claude Code to "
                "respawn the server (a full Claude Code restart works too "
                "but isn't necessary). To inspect which versions are on "
                "disk before reinstalling, run "
                "`python -m hallucinote_mcp.cli preflight` and check the "
                "`package.version` and `remote_script.candidates[*].version` "
                "fields. If this is an introspection call during development "
                "and you accept the risk, pass `allow_version_mismatch=true` "
                "on the tool call to bypass this check — see the warning "
                "text the bypass attaches for the data-corruption caveat."
            ),
        )
    if request_version != local_version:
        return error(
            f"Hallucinote MCP version mismatch: MCP server side reports "
            f"{request_version}, Remote Script side is {local_version}. "
            f"These two halves run in different Python processes and must "
            f"match — drift means the action surface or wire shape may "
            f"differ.",
            hint=(
                "If the Remote Script side is stale (the common case): "
                "run `/ableton-mcp-install` to refresh the vendored copy "
                "in Live's User Library, then fully quit and reopen Live "
                "(Live caches Control Surface modules at startup, so a "
                "restart is required — `/mcp` alone won't help). If the "
                "MCP server side is stale: `pip install -U hallucinote-mcp` "
                "then run `/mcp` in Claude Code to respawn it. To confirm "
                "which side is which BEFORE reinstalling, run "
                "`python -m hallucinote_mcp.cli preflight` and compare "
                "`package.version` (server) against "
                "`remote_script.candidates[*].version` (vendored copy). "
                "If this is an introspection call during development and "
                "you accept the risk, pass `allow_version_mismatch=true` "
                "on the tool call to bypass — see the warning the bypass "
                "attaches for the data-corruption caveat."
            ),
            code=VERSION_MISMATCH_CODE,
        )
    return None


def check_version_compat_with_override(
    request_version: str,
    local_version: str,
    allow_mismatch: bool,
) -> tuple[Response | None, str | None]:
    """Version handshake with a per-call bypass.

    Returns a 2-tuple ``(refusal, warning)`` where exactly one of the
    following holds:

    * **match** → ``(None, None)``: versions agree; proceed clean.
    * **drift + ``allow_mismatch=True``** → ``(None, warning_text)``:
      caller has opted into the bypass; dispatch proceeds and the caller
      should attach ``warning_text`` to the response so the bypass is
      visible end-to-end.
    * **drift + ``allow_mismatch=False``** → ``(refusal_response, None)``:
      strict default; the caller short-circuits with ``refusal_response``
      and does not dispatch.

    The "drift" branch covers both empty-version (no handshake) and
    actual-mismatch outcomes from :func:`check_version_compat`. The
    bypass is uniform — agents asking for it know they want
    "dispatch anyway." We don't pretend introspection-vs-mutation can be
    safely distinguished at the dispatcher layer; the warning text is
    explicit about the data-corruption risk and the dev-only intent.
    """
    refusal = check_version_compat(request_version, local_version)
    if refusal is None:
        return (None, None)
    if not allow_mismatch:
        return (refusal, None)
    warning = (
        "WARNING: dispatched despite version mismatch "
        "(allow_version_mismatch=true). MCP server reports "
        f"{request_version or '<unset>'!r}; Remote Script is "
        f"{local_version!r}. This bypass CAN RESULT IN DATA CORRUPTION on "
        "mutating calls — the action surface or wire shape may differ "
        "between the two halves. Use only during development. To clear "
        "the drift, run `/ableton-mcp-install` and restart Live, or "
        "`pip install -U hallucinote-mcp` + `/mcp` depending on which "
        "side is stale."
    )
    return (None, warning)


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

    ``timeout`` semantics:
      - A float — bound the read; ``socket.timeout`` translates to
        ``FrameError`` with the elapsed budget.
      - ``None`` — explicitly clear any prior socket timeout and block
        indefinitely. The caller is asserting "this read may take as
        long as the handler needs" (e.g. ``ableton_render(render)``
        plays the full arrangement before responding — minutes for a
        long song). Without the explicit clear, ``socket.create_connection``'s
        connect timeout would carry over and bound the read at 15 s
        even when the caller intends to wait.
    """
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
    "check_version_compat",
    "check_version_compat_with_override",
    "FrameError",
    "encode_message",
    "decode_messages",
    "recv_message",
    "send_message",
]
