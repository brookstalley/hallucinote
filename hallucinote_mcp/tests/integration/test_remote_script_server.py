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

    Mirrors the production ``LiveLiveContext`` Protocol: ``song`` plus
    synchronous ``run_on_main`` (tests run on a single thread, so no
    marshaling needed).
    """

    def __init__(self, root):
        self._root = root

    @property
    def song(self):
        return self._root

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
