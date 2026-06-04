"""Regression tests for SYN-2M9P — push planner must NOT emit impossible
master-strip device LOADs.

Background (DEV-2M9K → SYN-2M9P): Ableton Live 12.4 has no LOM path to load a
device onto the master strip. DEV-2M9K made the MCP load_handler + render
setup refuse master loads ("place by hand once" / configure-only contract).
But ``plan_push_devices`` still walked the master strip and emitted a
``ableton_device(action='load', master=True)`` for every *unbound* master
device. At execute time that call FAILS, and ``push_execute`` halts the
devices phase (outcome='partial'), leaving envelopes / arrangement / cues
PENDING — so any song authoring a master-strip device chain gets a reliably
PARTIAL push, re-planned every run.

The fix makes the planner mirror the rest of the stack: ZERO master loads,
a place-by-hand note instead, while STILL emitting master device PARAMETER
writes (``set_parameter`` works on a hand-placed master device).

These tests are intentionally dedicated to SYN-2M9P (collision discipline) —
they do not touch the shared ``test_push_devices.py`` fixtures.
"""
from __future__ import annotations

from dataclasses import dataclass

import pytest

from hallucinote.db import init_db, mutations as M
from hallucinote.sync import push, push_execute


# ---------------------------------------------------------------------------
# Fixtures (self-contained — do not depend on test_push_devices.py)
# ---------------------------------------------------------------------------


@pytest.fixture
def conn(tmp_path):
    c = init_db(tmp_path / "syn2m9p.db")
    yield c
    c.close()


@pytest.fixture
def song(conn):
    return M.create_song(conn, name="t", key="Dm")


@pytest.fixture
def session(conn, song):
    return M.create_ableton_session(conn, song_id=song, name="draft")


@pytest.fixture
def master_track(conn, song):
    """A master-strip track in the DB (kind='master', track_index=0)."""
    return M.create_track(
        conn, song_id=song, track_index=0, name="Master", kind="master",
    )


@pytest.fixture
def state_dir(tmp_path):
    d = tmp_path / "state"
    d.mkdir()
    return d


def _master_loads(plan) -> list:
    """Every load ToolCall addressed at the master strip."""
    return [
        c for c in plan.calls
        if c.args.get("action") == "load" and c.args.get("master") is True
    ]


# ---------------------------------------------------------------------------
# Plan-level: zero master LOADs (the core verifiable signal)
# ---------------------------------------------------------------------------


def test_unlinked_master_chain_emits_zero_master_loads(
    conn, song, session, master_track,
):
    """SYN-2M9P core signal: an *unlinked* master device chain produces NO
    ``device.load(master=True)`` call — that call is impossible in Live 12.4
    and would halt the devices phase at execute time."""
    cid = M.create_device_chain(conn, parent_track_id=master_track)
    M.create_device(
        conn, chain_id=cid, position=1,
        kind="Limiter", display_name="Master Limiter",
    )

    plan = push.plan_push_devices(conn, song_id=song, session_id=session)

    assert _master_loads(plan) == []
    # No load addressed master=True anywhere in the plan.
    assert not any(
        c.args.get("action") == "load" and c.args.get("master") is True
        for c in plan.calls
    )


def test_unlinked_master_chain_emits_place_by_hand_note(
    conn, song, session, master_track,
):
    """When the master load is skipped, the user must learn to place the
    device by hand — surfaced as a push-state note."""
    cid = M.create_device_chain(conn, parent_track_id=master_track)
    M.create_device(
        conn, chain_id=cid, position=1,
        kind="Limiter", display_name="Master Limiter",
    )

    plan = push.plan_push_devices(conn, song_id=song, session_id=session)

    assert any(
        "Master Limiter" in n and "by hand" in n for n in plan.notes
    ), plan.notes


def test_unlinked_master_chain_emits_no_param_calls_either(
    conn, song, session, master_track,
):
    """An unlinked master device has no device_index, so set_parameter can't
    be addressed yet — the chain is fully deferred to hand-placement. No load,
    no params, just the place-by-hand note."""
    cid = M.create_device_chain(conn, parent_track_id=master_track)
    did = M.create_device(
        conn, chain_id=cid, position=1,
        kind="Limiter", display_name="Master Limiter",
    )
    # Author dialed a ceiling, but the device isn't linked — nothing to push
    # until it's hand-placed and linked.
    M.set_device_parameter(
        conn, device_id=did, name="Ceiling",
        value_display="-0.3 dB", value_normalized=0.9,
    )

    plan = push.plan_push_devices(conn, song_id=song, session_id=session)

    assert plan.calls == [], [c.args for c in plan.calls]


def test_linked_master_device_still_emits_set_parameter(
    conn, song, session, master_track,
):
    """Configure-only contract: once the master device is hand-placed and
    linked, parameter writes MUST still fire (set_parameter works on a
    hand-placed master device), addressed master=True — never via a load."""
    cid = M.create_device_chain(conn, parent_track_id=master_track)
    dev = M.create_device(
        conn, chain_id=cid, position=1,
        kind="Limiter", display_name="Master Limiter",
    )
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="device", db_id=dev, ableton_index=1,
    )
    M.set_device_parameter(
        conn, device_id=dev, name="Ceiling",
        value_display="-0.3 dB", value_normalized=0.9,
    )

    plan = push.plan_push_devices(conn, song_id=song, session_id=session)

    # Zero loads...
    assert _master_loads(plan) == []
    # ...but the parameter write is emitted, master-addressed.
    set_calls = [c for c in plan.calls if c.args.get("action") == "set_parameter"]
    assert len(set_calls) == 1
    args = set_calls[0].args
    assert args.get("master") is True
    assert "track_index" not in args
    assert "return_index" not in args
    assert args["parameter_name"] == "Ceiling"


# ---------------------------------------------------------------------------
# Execute-path: a refused master load must NOT halt the devices phase
# ---------------------------------------------------------------------------


@dataclass
class _FakeResponse:
    """Shape-compatible with hallucinote_mcp.wire.Response (ok/result/error/hint)."""
    ok: bool
    result: dict | None = None
    error: str | None = None
    hint: str | None = None


def _refusing_send_fn():
    """A fake send_fn that mirrors DEV-2M9K's load_handler: it REFUSES any
    ``ableton_device(action='load', master=True)`` (Live 12.4 cannot load a
    device onto the master). Every other call succeeds with a synthetic link
    index. If a regression reintroduces the master load, this refusal makes
    the devices phase go partial — which the test asserts against."""
    counters: dict[str, int] = {}
    log: list[dict] = []

    def send(req):
        log.append({"tool": req.tool, "action": req.action, "params": req.params})
        if (
            req.tool == "ableton_device"
            and req.action == "load"
            and req.params.get("master") is True
        ):
            return _FakeResponse(
                ok=False,
                error="cannot load a device onto the master strip in Live 12.4",
            )
        if req.tool == "ableton_device" and req.action == "load":
            counters["device"] = counters.get("device", 0) + 1
            return _FakeResponse(ok=True, result={"device_index": counters["device"]})
        return _FakeResponse(ok=True, result={})

    send.log = log  # type: ignore[attr-defined]
    return send


def test_execute_master_chain_does_not_halt_devices_phase(
    conn, song, session, master_track, state_dir,
):
    """The full verifiable signal: drive a refused-master scenario through
    execute_push and assert the devices phase is NOT halted by it. With the
    SYN-2M9P fix the planner emits no master load, so the refusing send_fn is
    never asked to load the master — the devices phase has no failing call and
    completes cleanly (skipped: nothing addressable until hand-placement)."""
    cid = M.create_device_chain(conn, parent_track_id=master_track)
    M.create_device(
        conn, chain_id=cid, position=1,
        kind="Limiter", display_name="Master Limiter",
    )

    send = _refusing_send_fn()
    result = push_execute.execute_push(
        conn=conn, song_id=song, session_id=session,
        state_dir=state_dir, send_fn=send,
    )

    # The refusing send_fn was never asked to load the master.
    assert not any(
        c["tool"] == "ableton_device"
        and c["action"] == "load"
        and c["params"].get("master") is True
        for c in send.log
    ), send.log

    # Devices phase is not halted; the overall push is not partial-by-master.
    by_name = {p.name: p for p in result.phases}
    assert "devices" in by_name
    assert by_name["devices"].status != "halted", by_name["devices"]
    assert result.phase_halted != "devices"
    assert result.outcome != "partial"
    assert result.exit_code != push_execute.EXIT_PARTIAL


def test_execute_master_param_writes_through_after_hand_placement(
    conn, song, session, master_track, state_dir,
):
    """Configure-only end-to-end: a *linked* (hand-placed) master device's
    parameter write dispatches and the devices phase succeeds — the master
    chain is no longer a reliable PARTIAL trap."""
    cid = M.create_device_chain(conn, parent_track_id=master_track)
    dev = M.create_device(
        conn, chain_id=cid, position=1,
        kind="Limiter", display_name="Master Limiter",
    )
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="device", db_id=dev, ableton_index=1,
    )
    M.set_device_parameter(
        conn, device_id=dev, name="Ceiling",
        value_display="-0.3 dB", value_normalized=0.9,
    )

    send = _refusing_send_fn()
    result = push_execute.execute_push(
        conn=conn, song_id=song, session_id=session,
        state_dir=state_dir, send_fn=send,
    )

    # The master set_parameter went out (master-addressed), and succeeded.
    master_param_calls = [
        c for c in send.log
        if c["tool"] == "ableton_device"
        and c["action"] == "set_parameter"
        and c["params"].get("master") is True
    ]
    assert len(master_param_calls) == 1, send.log

    by_name = {p.name: p for p in result.phases}
    assert by_name["devices"].status != "halted", by_name["devices"]
    assert result.outcome != "partial"
