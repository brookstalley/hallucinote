"""End-to-end through the Remote Script TCP server using a fake LiveContext.

Proves the loop: client TCP connection → wire frame → dispatcher → response →
wire frame back. No Ableton Live required because the LiveContext is in-memory.
"""
from __future__ import annotations

import socket
import time

import pytest

from hallucinote_mcp import schema
from hallucinote_mcp.client import send as client_send
from hallucinote_mcp.remote_script.server import RemoteScriptServer
from hallucinote_mcp.schema import Action, LiveOp, ParamSpec
from hallucinote_mcp.wire import Request


class _FakeNode:
    def __init__(self, **attrs):
        for k, v in attrs.items():
            setattr(self, k, v)


class _FakeContext:
    """In-memory LiveContext for the integration loop test.

    Mirrors the production ``LiveLiveContext`` Protocol: ``song``,
    ``application``, and synchronous ``run_on_main`` (tests run on a
    single thread, so no marshaling needed).
    """

    def __init__(self, root, application=None):
        self._root = root
        self._application = application

    @property
    def song(self):
        return self._root

    @property
    def application(self):
        return self._application

    def run_on_main(self, fn):
        return fn()


def _free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture()
def running_server(isolated_registry):
    isolated_registry.register(
        Action(
            tool="ableton_session",
            name="get_tempo",
            description="",
            declarative_op=LiveOp(kind="property_read", target="song", property="tempo"),
        )
    )
    isolated_registry.register(
        Action(
            tool="ableton_session",
            name="set_tempo",
            description="",
            params=(ParamSpec(name="value", type="float"),),
            declarative_op=LiveOp(
                kind="property_write", target="song", property="tempo"
            ),
        )
    )
    isolated_registry.register_help_actions()

    root = _FakeNode(tempo=120.0)
    context = _FakeContext(root)
    port = _free_port()
    server = RemoteScriptServer(live_context=context, port=port)
    server.start()
    # Brief settle so the accept thread is in the loop before tests hit it.
    time.sleep(0.05)
    try:
        yield server, root, port
    finally:
        server.stop()


def test_end_to_end_property_read(running_server):
    _server, root, port = running_server
    response = client_send(Request(tool="ableton_session", action="get_tempo"), port=port)
    assert response.ok is True
    assert response.result == 120.0
    assert root.tempo == 120.0


def test_end_to_end_property_write(running_server):
    _server, root, port = running_server
    response = client_send(
        Request(tool="ableton_session", action="set_tempo", params={"value": 132.0}),
        port=port,
    )
    assert response.ok is True
    assert root.tempo == 132.0


def test_end_to_end_unknown_action(running_server):
    _server, _root, port = running_server
    response = client_send(
        Request(tool="ableton_session", action="bogus"), port=port
    )
    assert response.ok is False
    assert "bogus" in (response.error or "")
    assert response.valid_actions is not None
    assert "help" in response.valid_actions


def test_end_to_end_param_validation_error(running_server):
    _server, _root, port = running_server
    response = client_send(
        Request(tool="ableton_session", action="set_tempo", params={}),
        port=port,
    )
    assert response.ok is False
    assert response.required == ("value",)


def test_client_send_raises_when_no_server_listening():
    from hallucinote_mcp.client import LiveConnectionError

    port = _free_port()  # nothing listening
    with pytest.raises(LiveConnectionError, match="could not reach"):
        client_send(Request(tool="ableton_session", action="help"), port=port, timeout=1.0)


def test_end_to_end_version_mismatch_returns_structured_error(running_server):
    """When the MCP server side sends a version that differs from the
    Remote Script side's ``__version__``, the Live-side handler returns a
    structured error before dispatching. The agent sees one clear
    'version mismatch' response instead of decoding 'unknown action'
    cascades caused by drift.
    """
    _server, _root, port = running_server
    # Explicit non-empty value bypasses client.send's auto-inject.
    bad_request = Request(
        tool="ableton_session", action="get_tempo", server_version="9.9.9-WRONG"
    )
    response = client_send(bad_request, port=port)
    assert response.ok is False
    assert "version mismatch" in (response.error or "").lower()
    assert "9.9.9-WRONG" in (response.error or "")


def test_end_to_end_missing_server_version_returns_handshake_error(running_server):
    """A request that omits ``server_version`` should be rejected with the
    handshake-missing error. We can't drive this through ``client.send``
    (it auto-injects the current version), so we construct the wire frame
    by hand.
    """
    import socket as _socket

    from hallucinote_mcp import wire

    _server, _root, port = running_server
    with _socket.create_connection(("127.0.0.1", port), timeout=5.0) as sock:
        # Raw dict — no server_version key. Mirrors what a pre-handshake
        # MCP server would send.
        sock.sendall(
            wire.encode_message(
                {"tool": "ableton_session", "action": "get_tempo", "params": {}}
            )
        )
        reply = wire.recv_message(sock, timeout=5.0)
    assert reply["ok"] is False
    assert "handshake missing" in reply["error"].lower()


def test_client_send_injects_local_version(running_server, monkeypatch):
    """``client.send`` must stamp the request with this process's
    ``hallucinote_mcp.__version__`` when the caller didn't set one, so
    the Live-side handshake doesn't reject every legitimate call. We
    verify by patching ``__version__`` on the client side to a value the
    server side doesn't expect and asserting the resulting mismatch.
    """
    import hallucinote_mcp.client as client_mod

    _server, _root, port = running_server
    monkeypatch.setattr(client_mod, "__version__", "0.0.0-test-injection")
    response = client_send(
        Request(tool="ableton_session", action="get_tempo"), port=port
    )
    assert response.ok is False
    assert "0.0.0-test-injection" in (response.error or "")
    assert "version mismatch" in (response.error or "").lower()


def test_client_send_preserves_explicit_version(monkeypatch, running_server):
    """If the caller sets ``server_version`` explicitly, ``client.send``
    must NOT overwrite it — that's how the mismatch test above can drive
    the bad-version path even though the client-side ``__version__`` is
    the canonical correct value.
    """
    import hallucinote_mcp.client as client_mod

    _server, _root, port = running_server
    # Patch __version__ on the client side. If the explicit value isn't
    # preserved, this would inject the wrong value and the mismatch
    # message would name the patched version instead of the explicit one.
    monkeypatch.setattr(client_mod, "__version__", "0.0.0-should-not-leak")
    response = client_send(
        Request(
            tool="ableton_session",
            action="get_tempo",
            server_version="explicit-value",
        ),
        port=port,
    )
    assert response.ok is False
    assert "explicit-value" in (response.error or "")
    assert "0.0.0-should-not-leak" not in (response.error or "")
