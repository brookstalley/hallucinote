"""End-to-end through the Remote Script TCP server using a fake LiveContext.

Proves the loop: client TCP connection → wire frame → dispatcher → response →
wire frame back. No Ableton Live required because the LiveContext is in-memory.
"""
from __future__ import annotations

import socket
import threading
import time

import pytest

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
    ``application``, ``live_state_lock``, and synchronous
    ``run_on_main``. The lock is a real ``threading.RLock`` so the
    parallel-call test exercises the same mutual-exclusion semantics
    as production.
    """

    def __init__(self, root, application=None):
        self._root = root
        self._application = application
        self._live_state_lock = threading.RLock()

    @property
    def song(self):
        return self._root

    @property
    def application(self):
        return self._application

    @property
    def live_state_lock(self):
        return self._live_state_lock

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
        client_send(Request(tool="ableton_session", action="help"), port=port, connect_timeout=1.0)


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


def test_end_to_end_allow_version_mismatch_bypasses_drift(running_server):
    """When the caller opts into the bypass AND drift exists, the dispatch
    proceeds and the response carries a `warnings` advisory naming the
    data-corruption risk. This is the load-bearing end-to-end test for Q1
    — without it, a Remote Script regression that ignored the field would
    pass unit tests but fail at runtime.
    """
    _server, root, port = running_server
    bypassed = Request(
        tool="ableton_session",
        action="get_tempo",
        server_version="9.9.9-WRONG",
        allow_version_mismatch=True,
    )
    response = client_send(bypassed, port=port)
    # Dispatch proceeded — version error was bypassed.
    assert response.ok is True
    assert response.result == root.tempo
    # Warning rode along in the response so the bypass is visible.
    assert response.warnings is not None
    assert len(response.warnings) == 1
    warning = response.warnings[0]
    assert "9.9.9-WRONG" in warning
    assert "data corruption" in warning.lower()
    assert "development" in warning.lower()


def test_end_to_end_allow_version_mismatch_false_still_refuses(running_server):
    """Default behavior (no opt-in) MUST refuse on drift — strict-by-default
    is the chunk's load-bearing safety property."""
    _server, _root, port = running_server
    request = Request(
        tool="ableton_session",
        action="get_tempo",
        server_version="9.9.9-WRONG",
        allow_version_mismatch=False,
    )
    response = client_send(request, port=port)
    assert response.ok is False
    assert "version mismatch" in (response.error or "").lower()


def test_end_to_end_allow_version_mismatch_no_drift_no_warning(running_server):
    """allow_version_mismatch is a no-op when versions agree — no warning
    attached, behavior identical to default."""
    from hallucinote_mcp import __version__ as local_version

    _server, root, port = running_server
    request = Request(
        tool="ableton_session",
        action="get_tempo",
        server_version=local_version,
        allow_version_mismatch=True,
    )
    response = client_send(request, port=port)
    assert response.ok is True
    assert response.result == root.tempo
    assert response.warnings is None


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


# ---------- Parallel-call regression for cue_create (B-21) ----------


class _CueFakeCue:
    def __init__(self, time: float, name: str = ""):
        self.time = time
        self.name = name


class _CueFakeSong:
    """Minimal Song double for the parallel cue_create end-to-end test.

    Implements just enough surface (cue_points, current_song_time,
    set_or_delete_cue, last_event_time) to drive the cue_create handler
    end-to-end through the TCP server. ``set_or_delete_cue`` is a NO-ARG
    toggle (matching Live 12.x) — it appends a cue at whatever
    current_song_time happens to hold at toggle time, which is the
    surface the B-21 race exploits when concurrent callers interleave.
    """

    def __init__(self) -> None:
        self.current_song_time = 0.0
        self.last_event_time = 1000.0
        self.cue_points: list[_CueFakeCue] = []

    def set_or_delete_cue(self) -> None:
        t = float(self.current_song_time)
        for i, c in enumerate(self.cue_points):
            if abs(c.time - t) < 1e-6:
                del self.cue_points[i]
                return
        self.cue_points.append(_CueFakeCue(t, ""))


@pytest.fixture()
def cue_server(monkeypatch):
    """Server fixture wired with the real arrangement actions + a fast
    settle so the threading test completes in well under a second."""
    # Speed up cue_create's settle sleep so the test stays fast — the
    # serialization guarantee is independent of sleep duration.
    import hallucinote_mcp.handlers.arrangement as arr_module
    from hallucinote_mcp.testing import isolated_actions
    monkeypatch.setattr(arr_module, "_CUE_SETTLE_POLL_S", 0.005)

    with isolated_actions():
        song = _CueFakeSong()
        context = _FakeContext(song)
        port = _free_port()
        server = RemoteScriptServer(live_context=context, port=port)
        server.start()
        time.sleep(0.05)
        try:
            yield server, song, port
        finally:
            server.stop()


def test_concurrent_cue_creates_through_tcp_all_land(cue_server):
    """B-21 end-to-end. Multiple TCP clients firing cue_create in
    parallel must each produce a cue at its requested position. The
    Remote Script's per-client threads + the live_state_lock together
    serialize the playhead-write windows so the audio-thread-settle
    race can't observe another caller's target.
    """
    _server, song, port = cue_server
    positions = [16.0, 32.0, 48.0, 64.0, 80.0, 96.0, 112.0]
    errors: list[str] = []

    def worker(pos: float) -> None:
        resp = client_send(
            Request(
                tool="ableton_arrangement", action="cue_create",
                params={"position_beats": pos, "name": f"Cue@{pos}"},
            ),
            port=port,
        )
        if not resp.ok:
            errors.append(f"pos={pos}: {resp.error}")

    threads = [
        threading.Thread(target=worker, args=(pos,)) for pos in positions
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=15.0)

    assert not errors, f"worker errors: {errors}"
    landed = {(c.time, c.name) for c in song.cue_points}
    expected = {(p, f"Cue@{p}") for p in positions}
    assert landed == expected, (
        f"missing or misplaced cues — expected={expected}, got={landed}; "
        f"the parallel-call race re-surfaced"
    )


def test_cue_create_batch_through_tcp(cue_server):
    """End-to-end shape check on the batch action: one TCP round-trip
    creates N cues."""
    _server, song, port = cue_server
    resp = client_send(
        Request(
            tool="ableton_arrangement", action="cue_create_batch",
            params={"cues": [
                {"position_beats": 0.0, "name": "Intro"},
                {"position_beats": 16.0, "name": "Verse"},
                {"position_beats": 48.0, "name": "Chorus"},
            ]},
        ),
        port=port,
    )
    assert resp.ok is True, f"unexpected error: {resp.error!r}"
    assert resp.result["cue_count"] == 3
    landed = {(c.time, c.name) for c in song.cue_points}
    assert landed == {(0.0, "Intro"), (16.0, "Verse"), (48.0, "Chorus")}


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
