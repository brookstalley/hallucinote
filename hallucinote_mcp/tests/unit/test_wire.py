"""Wire protocol — framing + Request/Response shapes."""
from __future__ import annotations

import io
import socket
import threading

import pytest

from hallucinote_mcp import wire
from hallucinote_mcp.wire import (
    FrameError,
    Request,
    Response,
    decode_messages,
    encode_message,
    error,
    ok,
    recv_message,
    send_message,
)


# ---------- Shape ----------


def test_request_round_trip():
    req = Request(tool="ableton_session", action="set_tempo", params={"bpm": 132})
    assert Request.from_dict(req.to_dict()) == req


@pytest.mark.parametrize(
    "obj, message",
    [
        ({"tool": 5, "action": "x", "params": {}}, "tool must be a string"),
        ({"tool": "x", "action": None, "params": {}}, "action must be a string"),
        ({"tool": "x", "action": "y", "params": []}, "params must be an object"),
    ],
)
def test_request_from_dict_validates(obj, message):
    with pytest.raises(ValueError, match=message):
        Request.from_dict(obj)


def test_ok_response_serializes_result():
    resp = ok({"tempo": 132})
    assert resp.to_dict() == {"ok": True, "result": {"tempo": 132}}


def test_error_response_emits_only_set_fields():
    resp = error("bad", valid_actions=["help", "info"], example="x(action='help')")
    d = resp.to_dict()
    assert d["ok"] is False
    assert d["error"] == "bad"
    assert d["valid_actions"] == ["help", "info"]
    assert d["example"] == "x(action='help')"
    # Unset hints should not appear in the serialized form
    assert "required" not in d
    assert "optional" not in d
    assert "hint" not in d


# ---------- Framing ----------


def test_encode_then_decode_round_trip():
    frames = encode_message({"a": 1}) + encode_message({"b": "two"})
    msgs, remainder = decode_messages(frames)
    assert msgs == [{"a": 1}, {"b": "two"}]
    assert remainder == b""


def test_decode_handles_partial_frame():
    full = encode_message({"hello": "world"})
    # Split mid-payload
    msgs, remainder = decode_messages(full[:6])
    assert msgs == []
    assert remainder == full[:6]

    # Now provide the rest, prepended with the remainder
    msgs2, remainder2 = decode_messages(full)
    assert msgs2 == [{"hello": "world"}]
    assert remainder2 == b""


def test_decode_rejects_oversized_length():
    bad = (16 * 1024 * 1024 + 1).to_bytes(4, "big") + b"junk"
    with pytest.raises(FrameError, match="exceeds wire cap"):
        decode_messages(bad)


def test_decode_rejects_malformed_json():
    payload = b"not-json"
    bad = len(payload).to_bytes(4, "big") + payload
    with pytest.raises(FrameError, match="malformed JSON"):
        decode_messages(bad)


def test_decode_rejects_non_object_top_level():
    payload = b"[1,2,3]"
    bad = len(payload).to_bytes(4, "big") + payload
    with pytest.raises(FrameError, match="must be a JSON object"):
        decode_messages(bad)


def test_encode_rejects_oversized_message():
    huge = {"x": "a" * (17 * 1024 * 1024)}
    with pytest.raises(ValueError, match="exceeds wire cap"):
        encode_message(huge)


# ---------- send_message / recv_message over a real socket pair ----------


def test_send_recv_round_trip_over_socket():
    server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_sock.bind(("127.0.0.1", 0))
    server_sock.listen(1)
    port = server_sock.getsockname()[1]

    received = {}

    def accept_once():
        conn, _ = server_sock.accept()
        try:
            received["msg"] = recv_message(conn, timeout=2.0)
            send_message(conn, ok({"reply": "yes"}))
        finally:
            conn.close()

    t = threading.Thread(target=accept_once, daemon=True)
    t.start()

    client = socket.create_connection(("127.0.0.1", port), timeout=2.0)
    try:
        send_message(client, Request(tool="ableton_session", action="info"))
        reply = recv_message(client, timeout=2.0)
    finally:
        client.close()
        server_sock.close()
        t.join(timeout=2.0)

    assert received["msg"] == {
        "tool": "ableton_session",
        "action": "info",
        "params": {},
    }
    assert reply == {"ok": True, "result": {"reply": "yes"}}


def test_recv_raises_on_closed_socket():
    a, b = socket.socketpair()
    b.close()
    with pytest.raises(FrameError, match="socket closed"):
        recv_message(a, timeout=1.0)
    a.close()
