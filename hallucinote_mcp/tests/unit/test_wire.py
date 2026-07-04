"""Wire protocol — framing + Request/Response shapes."""
from __future__ import annotations

import socket
import threading

import pytest

from hallucinote_mcp.wire import (
    FrameError,
    Request,
    Response,
    check_version_compat,
    check_version_compat_with_override,
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


def test_request_round_trips_server_version():
    req = Request(
        tool="ableton_session", action="info", params={}, server_version="1.2.3"
    )
    serialized = req.to_dict()
    assert serialized["server_version"] == "1.2.3"
    assert Request.from_dict(serialized) == req


def test_request_to_dict_omits_empty_server_version():
    # Keep the wire small for the legacy/no-handshake path. The Live side
    # treats missing-or-empty identically; we don't need to ship "".
    req = Request(tool="ableton_session", action="help")
    assert "server_version" not in req.to_dict()


def test_request_from_dict_defaults_missing_server_version():
    obj = {"tool": "ableton_session", "action": "help", "params": {}}
    assert Request.from_dict(obj).server_version == ""


@pytest.mark.parametrize(
    "obj, message",
    [
        ({"tool": 5, "action": "x", "params": {}}, "tool must be a string"),
        ({"tool": "x", "action": None, "params": {}}, "action must be a string"),
        ({"tool": "x", "action": "y", "params": []}, "params must be an object"),
        (
            {"tool": "x", "action": "y", "params": {}, "server_version": 42},
            "server_version must be a string",
        ),
        (
            {
                "tool": "x",
                "action": "y",
                "params": {},
                "allow_version_mismatch": "yes",
            },
            "allow_version_mismatch must be a boolean",
        ),
    ],
)
def test_request_from_dict_validates(obj, message):
    with pytest.raises(ValueError, match=message):
        Request.from_dict(obj)


def test_request_round_trips_allow_version_mismatch():
    req = Request(
        tool="ableton_session",
        action="info",
        params={},
        allow_version_mismatch=True,
    )
    serialized = req.to_dict()
    assert serialized["allow_version_mismatch"] is True
    assert Request.from_dict(serialized) == req


def test_request_to_dict_omits_default_allow_version_mismatch():
    # Default is False; don't ship it on the wire — keeps the request
    # small and signals "no opt-in needed" to the Live side.
    req = Request(tool="ableton_session", action="help")
    assert "allow_version_mismatch" not in req.to_dict()


def test_request_from_dict_defaults_missing_allow_version_mismatch():
    obj = {"tool": "ableton_session", "action": "help", "params": {}}
    assert Request.from_dict(obj).allow_version_mismatch is False


# ---------- Version handshake ----------


def test_check_version_compat_match_returns_none():
    assert check_version_compat("0.2.0", "0.2.0") is None


def test_check_version_compat_empty_returns_stale_server_error():
    resp = check_version_compat("", "0.2.0")
    assert resp is not None
    assert resp.ok is False
    assert "0.2.0" in (resp.error or "")
    # The hint must name both the pip upgrade AND the `/mcp` reconnect —
    # those are the two-step recovery for this branch.
    assert "pip install" in (resp.hint or "").lower()
    assert "/mcp" in (resp.hint or "")


def test_check_version_compat_mismatch_names_both_versions():
    resp = check_version_compat("0.1.0", "0.2.0")
    assert resp is not None
    assert resp.ok is False
    # The agent reading this needs to see both versions to know which side
    # is stale and which install step to take.
    assert "0.1.0" in (resp.error or "")
    assert "0.2.0" in (resp.error or "")
    # The hint must cover both recovery branches — Remote Script stale
    # (re-install + full Live restart) and MCP server stale (pip + /mcp).
    assert "ableton-mcp-install" in (resp.hint or "")
    assert "/mcp" in (resp.hint or "")


def test_version_mismatch_hint_mentions_allow_version_mismatch_escape_hatch():
    # The error path is the natural discovery surface for the bypass —
    # agents hit it once, see the hint, use the flag next call. If this
    # affordance disappears from the hint, the bypass becomes invisible.
    resp = check_version_compat("0.1.0", "0.2.0")
    assert resp is not None
    assert "allow_version_mismatch" in (resp.hint or "")

    empty_resp = check_version_compat("", "0.2.0")
    assert empty_resp is not None
    assert "allow_version_mismatch" in (empty_resp.hint or "")


# ---------- Version handshake bypass (allow_version_mismatch) ----------


def test_check_version_compat_with_override_match_returns_clean():
    refusal, warning = check_version_compat_with_override(
        "0.2.0", "0.2.0", allow_mismatch=False
    )
    assert refusal is None
    assert warning is None
    # allow_mismatch has no effect when versions agree.
    refusal2, warning2 = check_version_compat_with_override(
        "0.2.0", "0.2.0", allow_mismatch=True
    )
    assert refusal2 is None
    assert warning2 is None


def test_check_version_compat_with_override_drift_no_allow_refuses():
    refusal, warning = check_version_compat_with_override(
        "0.1.0", "0.2.0", allow_mismatch=False
    )
    assert refusal is not None
    assert refusal.ok is False
    assert warning is None


def test_check_version_compat_with_override_drift_with_allow_proceeds_with_warning():
    refusal, warning = check_version_compat_with_override(
        "0.1.0", "0.2.0", allow_mismatch=True
    )
    assert refusal is None
    assert warning is not None
    # Warning must surface the actual versions, the development-only intent,
    # and the data-corruption risk — these are load-bearing for caller
    # awareness; the only governance on the bypass is that the caller
    # sees what they opted into.
    lower = warning.lower()
    assert "0.1.0" in warning
    assert "0.2.0" in warning
    assert "data corruption" in lower
    assert "development" in lower


def test_check_version_compat_with_override_empty_with_allow_proceeds_with_warning():
    # The empty-version branch (no handshake field at all) is also bypassable.
    # The warning should report "<unset>" so the caller can see WHICH branch.
    refusal, warning = check_version_compat_with_override(
        "", "0.2.0", allow_mismatch=True
    )
    assert refusal is None
    assert warning is not None
    assert "<unset>" in warning
    assert "0.2.0" in warning


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
    assert "warnings" not in d


def test_response_with_warnings_serializes_them():
    # warnings ride alongside ok=True or ok=False — they don't change ok.
    resp_ok = Response(ok=True, result={"x": 1}, warnings=("be careful",))
    assert resp_ok.to_dict() == {
        "ok": True,
        "result": {"x": 1},
        "warnings": ["be careful"],
    }
    resp_err = Response(ok=False, error="bad", warnings=("also be careful",))
    d = resp_err.to_dict()
    assert d["ok"] is False
    assert d["error"] == "bad"
    assert d["warnings"] == ["also be careful"]


def test_response_empty_warnings_omitted_from_dict():
    # None or empty tuple → no `warnings` key on the wire.
    assert "warnings" not in Response(ok=True, result=1, warnings=None).to_dict()
    assert "warnings" not in Response(ok=True, result=1, warnings=()).to_dict()


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
