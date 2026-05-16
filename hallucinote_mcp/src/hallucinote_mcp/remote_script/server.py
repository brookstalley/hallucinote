"""TCP server inside the Remote Script. Listens for wire requests, dispatches
each through ``hallucinote_mcp.dispatcher.dispatch``, sends the wire response
back.

Threading discipline:
  - Accept loop runs on a daemon thread (``_accept_loop``).
  - Each accepted client is handled on its own daemon thread (``_handle_client``).
  - Inside the handler, decoding the wire request, validating params, and
    encoding the response are pure operations — safe on any thread.
  - The actual Live API access (declarative ops, handlers) happens in
    ``LiveLiveContext.resolve`` / handler bodies, which marshal onto Live's
    main thread via ``schedule_on_main`` (see ``dispatch.LiveLiveContext``).
"""
from __future__ import annotations

import socket
import threading
from typing import Any, Callable

from .. import wire
from ..dispatcher import LiveContext, dispatch
from ..wire import DEFAULT_HOST, DEFAULT_PORT, FrameError, Request


LogFn = Callable[[str], None]


class RemoteScriptServer:
    """TCP server with the canonical hallucinote-mcp wire protocol."""

    def __init__(
        self,
        live_context: LiveContext,
        log: LogFn = lambda _: None,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
    ) -> None:
        self._live_context = live_context
        self._log = log
        self.host = host
        self.port = port

        self._sock: socket.socket | None = None
        self._accept_thread: threading.Thread | None = None
        self._running = False
        self._client_threads: list[threading.Thread] = []

    def start(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((self.host, self.port))
        sock.listen(8)
        sock.settimeout(1.0)
        self._sock = sock
        self._running = True
        self._accept_thread = threading.Thread(
            target=self._accept_loop, name="hallucinote-mcp-accept", daemon=True
        )
        self._accept_thread.start()
        self._log(f"Hallucinote MCP server listening on {self.host}:{self.port}")

    def stop(self) -> None:
        self._running = False
        sock = self._sock
        self._sock = None
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass
        if self._accept_thread is not None:
            self._accept_thread.join(timeout=2.0)
            self._accept_thread = None
        # Don't join client threads — they may be blocked on Live's main
        # thread and joining would risk a deadlock. They're daemons and
        # will be reaped when Live exits.

    def _accept_loop(self) -> None:
        while self._running and self._sock is not None:
            try:
                client, addr = self._sock.accept()
            except socket.timeout:
                continue
            except OSError:
                # Socket closed under us during shutdown.
                return
            client.settimeout(None)
            thread = threading.Thread(
                target=self._handle_client,
                args=(client, addr),
                name=f"hallucinote-mcp-client-{addr[1]}",
                daemon=True,
            )
            thread.start()
            self._client_threads.append(thread)
            # Reap finished threads occasionally to keep the list bounded.
            self._client_threads = [t for t in self._client_threads if t.is_alive()]

    def _handle_client(self, client: socket.socket, addr: tuple[str, int]) -> None:
        try:
            while self._running:
                try:
                    request_obj = wire.recv_message(client)
                except FrameError as exc:
                    self._log(f"Hallucinote MCP framing error from {addr}: {exc}")
                    return
                except OSError:
                    return
                try:
                    request = Request.from_dict(request_obj)
                except ValueError as exc:
                    response = wire.error(str(exc))
                else:
                    response = dispatch(request, context=self._live_context)
                try:
                    wire.send_message(client, response)
                except OSError as exc:
                    self._log(f"Hallucinote MCP send error to {addr}: {exc}")
                    return
        finally:
            try:
                client.close()
            except OSError:
                pass


__all__ = ["RemoteScriptServer"]
