"""client.send read-timeout auto-resolution (ENV-9P4T).

The read-timeout policy is the single source of truth shared by BOTH socket-recv
routes: the server's agent-forward (`server.handle_tool_call`) and push_cli's
direct dispatch (`send_fn = client.send`). The push route calls `client.send(req)`
with no `read_timeout`, so the value MUST auto-resolve from the (tool, action)
policy — otherwise a realtime action (perform_batch) hits the 15s default and a
`socket.timeout` severs the only verification a write-only surface has.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from hallucinote_mcp import client
from hallucinote_mcp.wire import Request


def _recv_timeout_for(req: Request, **send_kwargs):
    """Run client.send with the socket + wire framing mocked; return the
    timeout it actually passed to wire.recv_message."""
    captured: dict = {}

    def _fake_recv(sock, timeout=None):
        captured["timeout"] = timeout
        return {"ok": True, "result": {}}

    with patch("hallucinote_mcp.client.socket.create_connection",
               return_value=MagicMock()), \
         patch("hallucinote_mcp.client.wire.send_message"), \
         patch("hallucinote_mcp.client.wire.recv_message", side_effect=_fake_recv):
        client.send(req, **send_kwargs)
    return captured["timeout"]


# ---------------------------------------------------------------------------
# Policy resolution
# ---------------------------------------------------------------------------


def test_read_timeout_for_perform_batch_is_unbounded():
    assert client.read_timeout_for("ableton_automation", "perform_batch") is None


def test_read_timeout_for_render_start_is_default():
    # The synchronous `render` action (formerly unbounded — it held the socket
    # for the whole realtime pass) was retired (MCP-9R3T). `start` mints a job
    # handle and returns immediately, so the default read timeout suits it; the
    # realtime render runs on the detached worker, not this forwarded call.
    assert (
        client.read_timeout_for("ableton_render", "start")
        == client._DEFAULT_READ_TIMEOUT
    )


def test_read_timeout_for_ensure_loaded_is_generous_but_bounded():
    t = client.read_timeout_for("ableton_render", "ensure_loaded")
    assert t is not None and t > client._DEFAULT_READ_TIMEOUT


def test_read_timeout_for_default_action():
    # 20s = Live's 15s main-thread ceiling + the 5s reply margin. The caller
    # must outlast Live, or Live's "still running, do not retry" timeout
    # report is cut off by the socket and the agent sees a bare FrameError.
    assert client.read_timeout_for("ableton_track", "create") == 20.0


# ---------------------------------------------------------------------------
# Auto-resolution through send() — the PUSH route (no read_timeout passed)
# ---------------------------------------------------------------------------


def test_send_auto_resolves_perform_batch_unbounded():
    """The push route (`send_fn = client.send`, called with just the req) must
    get an UNBOUNDED read window for perform_batch — this is the route that
    bites at mix scale, where the server-table-only fix did nothing."""
    rt = _recv_timeout_for(
        Request(tool="ableton_automation", action="perform_batch", params={})
    )
    assert rt is None


def test_send_auto_resolves_normal_action_to_default():
    rt = _recv_timeout_for(
        Request(tool="ableton_track", action="create", params={})
    )
    assert rt == 20.0


def test_send_honors_explicit_read_timeout_over_policy():
    rt = _recv_timeout_for(
        Request(tool="ableton_automation", action="perform_batch", params={}),
        read_timeout=5.0,
    )
    assert rt == 5.0


def test_send_honors_explicit_none_as_block_forever():
    """Explicit None is 'block forever', NOT 'unset' — it must be honored, not
    re-resolved to the policy (which would give the 20s default here)."""
    rt = _recv_timeout_for(
        Request(tool="ableton_track", action="create", params={}),
        read_timeout=None,
    )
    assert rt is None
