"""The escalation wrapper — the seam that makes the wire contract hold for a
module nobody has written yet.

A call that outruns Live's main-thread ceiling comes back `ok=True` carrying a
job handle, and the work is still running. An unwrapper that reads `ok` and
returns `result` books a write that has not landed — and the mistake is
invisible, because the reply is a success. Teaching each caller individually is
how the second caller finds out by being broken; wrapping where the client send
is RESOLVED is what closes it by construction.
"""
from __future__ import annotations

import pytest

from hallucinote.sync import live_escalation


class _Resp:
    def __init__(self, *, ok, result=None, error=None, code=None):
        self.ok = ok
        self.result = result
        self.error = error
        self.code = code


class _Req:
    def __init__(self, tool, action, params):
        self.tool = tool
        self.action = action
        self.params = params


@pytest.fixture(autouse=True)
def _no_poll_delay(monkeypatch):
    monkeypatch.setattr(live_escalation, "ESCALATION_POLL_INTERVAL_S", 0.0)


def _escalation(job_id="main_thread-abc"):
    return _Resp(ok=True, code="work_escalated", result={
        "escalated": True, "job_id": job_id, "label": "ableton_device('load')",
    })


def test_an_ordinary_reply_passes_straight_through():
    """The wrapper must be invisible on the path it is not for."""
    sent = []

    def raw(req, **kw):
        sent.append(req)
        return _Resp(ok=True, result={"device_index": 2})

    send = live_escalation.escalation_aware(raw)
    resp = send(_Req("ableton_device", "load", {}))

    assert resp.ok and resp.result == {"device_index": 2}
    assert len(sent) == 1, "an ordinary call must not be polled"


def test_an_escalated_reply_is_polled_to_its_real_result():
    """The caller sees what the call returned, never the handle."""
    calls = []

    def raw(req, **kw):
        calls.append((req.tool, req.action))
        if req.action == "bout_status":
            return _Resp(ok=True, result={"job": {
                "state": "done", "result": {"loaded_class_name": "Operator"},
            }})
        return _escalation()

    send = live_escalation.escalation_aware(raw)
    resp = send(_Req("ableton_device", "load", {}))

    assert resp.ok
    assert resp.result == {"loaded_class_name": "Operator"}
    assert ("ableton_session", "bout_status") in calls


def test_an_escalated_call_that_fails_in_live_is_reported_as_failed():
    """`done` and `failed` are both terminal; only one of them is success."""
    def raw(req, **kw):
        if req.action == "bout_status":
            return _Resp(ok=True, result={"job": {
                "state": "failed", "error": "Live said no",
            }})
        return _escalation()

    resp = live_escalation.escalation_aware(raw)(_Req("ableton_device", "load", {}))

    assert resp.ok is False
    assert "Live said no" in (resp.error or "")


def test_the_payload_flag_alone_is_enough():
    """`code` is the contract and the payload flag is what survives a transport
    that drops `code` on the ok path. Either alone has to be enough — the cost
    of missing it is applying a write that never landed."""
    def raw(req, **kw):
        if req.action == "bout_status":
            return _Resp(ok=True, result={"job": {"state": "done", "result": {"ok": 1}}})
        # No `code` — only the flag in the payload.
        return _Resp(ok=True, result={"escalated": True, "job_id": "j1"})

    resp = live_escalation.escalation_aware(raw)(_Req("ableton_device", "load", {}))
    assert resp.result == {"ok": 1}


def test_a_refused_call_is_not_mistaken_for_an_escalation():
    """A busy REFUSAL is ok=False and never ran. Polling it would invent a job."""
    def raw(req, **kw):
        return _Resp(ok=False, error="Live is busy with ableton_device('load')")

    resp = live_escalation.escalation_aware(raw)(_Req("ableton_track", "list", {}))
    assert resp.ok is False
    assert "busy" in resp.error


def test_read_timeout_kwargs_reach_the_raw_send():
    """The wrapper sits in front of a send whose per-action read timeout is
    load-bearing — a realtime action that lost it would sever the only
    verification a write-only surface has."""
    seen = {}

    def raw(req, **kw):
        seen.update(kw)
        return _Resp(ok=True, result={})

    live_escalation.escalation_aware(raw)(_Req("t", "a", {}), read_timeout=None)
    assert "read_timeout" in seen and seen["read_timeout"] is None


def test_resolve_client_send_composes_the_wrapper_over_the_real_client(
    monkeypatch,
):
    """The two-line composition, pinned.

    Every other test here drives `escalation_aware` directly, and every CLI
    test monkeypatches its module's own resolver — so a wrong lazy import or a
    dropped argument in this function would ship without a single test
    noticing. It is two lines, and it is the two lines every wrapped caller
    depends on.
    """
    import sys as _sys
    import types

    seen = {}

    def _client_send(req, **kw):
        seen["req"] = req
        if getattr(req, "action", None) == "bout_status":
            return _Resp(ok=True, result={"job": {"state": "done", "result": {"v": 7}}})
        return _escalation()

    fake_client = types.SimpleNamespace(send=_client_send)
    fake_wire = types.SimpleNamespace(Request=_Req)
    monkeypatch.setitem(_sys.modules, "hallucinote_mcp",
                        types.SimpleNamespace(client=fake_client, wire=fake_wire))
    monkeypatch.setitem(_sys.modules, "hallucinote_mcp.client", fake_client)
    monkeypatch.setitem(_sys.modules, "hallucinote_mcp.wire", fake_wire)

    notes = []
    send = live_escalation.resolve_client_send(progress_fn=notes.append)
    resp = send(_Req("ableton_device", "load", {}))

    assert resp.result == {"v": 7}, "the composition did not resolve the handle"
    assert notes, "the progress sink was not carried through"
