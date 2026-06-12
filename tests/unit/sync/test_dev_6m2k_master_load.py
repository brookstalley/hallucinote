"""Regression tests for DEV-6M2K — master-strip device LOAD works like any track.

Background (DEV-2M9K → SYN-2M9P → DEV-6M2K). DEV-2M9K shipped a verdict that
Ableton Live 12.4 has no LOM path to load a device onto the master strip, and
SYN-2M9P then made ``plan_push_devices`` SKIP master loads to avoid a
guaranteed execute-time halt (an emitted ``device.load(master=True)`` would
fail and turn the devices phase PARTIAL). Both rested on a premise REFUTED on
Live 12.4.2: ``song.view.selected_track = master_track`` STICKS (read-back
confirms — not the claimed silent no-op), so ``select master ->
browser.load_item`` lands a device on the master chain exactly like any track
(live-proven; see ``.prawduct/artifacts/research-spike-automation-ingest.md``).

DEV-6M2K re-enables the load across the stack. The planner now emits
``device.load(master=True)`` for an UNLINKED master device, it executes, links
via the standard ``device:<id>`` key path, and the devices-phase convergence
re-plan (SYN-9F2L) writes its parameters once the link is live — no
PARTIAL-by-master halt, no hand-placement step.

This file (formerly ``test_syn_2m9p_master_load.py``) keeps the dedicated plan
+ execute-path coverage, flipped from SYN-2M9P's "must NOT emit a master load"
to the parity contract DEV-6M2K establishes. It is self-contained (does not
share ``test_push_devices.py`` fixtures).
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
    c = init_db(tmp_path / "dev6m2k.db")
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
# Plan-level: a master LOAD is emitted, master-addressed (the core signal)
# ---------------------------------------------------------------------------


def test_unlinked_master_chain_emits_master_load(
    conn, song, session, master_track,
):
    """DEV-6M2K core signal: an *unlinked* master device chain emits exactly
    one ``device.load(master=True)`` — the same emission a track/return device
    gets. (Under SYN-2M9P this asserted zero loads; that contract is retired.)"""
    cid = M.create_device_chain(conn, parent_track_id=master_track)
    M.create_device(
        conn, chain_id=cid, position=1,
        kind="Limiter", display_name="Master Limiter",
    )

    plan = push.plan_push_devices(conn, song_id=song, session_id=session)

    loads = _master_loads(plan)
    assert len(loads) == 1, [c.args for c in plan.calls]
    args = loads[0].args
    assert args["kind"] == "Limiter"
    assert args.get("master") is True
    assert "track_index" not in args and "return_index" not in args
    # The load is keyed like every other device load so apply_push_results
    # links it on the same path.
    assert loads[0].key.startswith("device:")


def test_unlinked_master_chain_emits_not_linked_yet_note(
    conn, song, session, master_track,
):
    """The unlinked master device gets the STANDARD device-level "not linked
    yet" note (rerun after apply_push_results) — never the retired SYN-2M9P
    "place by hand" / "not loadable via LOM" note."""
    cid = M.create_device_chain(conn, parent_track_id=master_track)
    M.create_device(
        conn, chain_id=cid, position=1,
        kind="Limiter", display_name="Master Limiter",
    )

    plan = push.plan_push_devices(conn, song_id=song, session_id=session)

    assert any(
        "Master Limiter" in n and "not linked yet" in n for n in plan.notes
    ), plan.notes
    assert not any(
        "by hand" in n or "not loadable via LOM" in n for n in plan.notes
    ), plan.notes


def test_unlinked_master_chain_defers_params_until_linked(
    conn, song, session, master_track,
):
    """An unlinked master device has no device_index yet, so set_parameter
    can't be addressed — the plan carries the LOAD but no param calls. The
    params land on the convergence re-plan once the load links (see the
    execute-path test below)."""
    cid = M.create_device_chain(conn, parent_track_id=master_track)
    did = M.create_device(
        conn, chain_id=cid, position=1,
        kind="Limiter", display_name="Master Limiter",
    )
    # Author dialed a ceiling, but the device isn't linked — the param waits.
    M.set_device_parameter(
        conn, device_id=did, name="Ceiling",
        value_display="-0.3 dB", value_normalized=0.9,
    )

    plan = push.plan_push_devices(conn, song_id=song, session_id=session)

    assert len(_master_loads(plan)) == 1
    set_calls = [c for c in plan.calls if c.args.get("action") == "set_parameter"]
    assert set_calls == [], [c.args for c in set_calls]


def test_linked_master_device_emits_set_parameter_no_load(
    conn, song, session, master_track,
):
    """Once the master device is linked, parameter writes fire master-addressed
    and NO load is re-emitted (the device already exists)."""
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

    # Already linked → no load...
    assert _master_loads(plan) == []
    # ...and the parameter write is emitted, master-addressed.
    set_calls = [c for c in plan.calls if c.args.get("action") == "set_parameter"]
    assert len(set_calls) == 1
    args = set_calls[0].args
    assert args.get("master") is True
    assert "track_index" not in args and "return_index" not in args
    assert args["parameter_name"] == "Ceiling"


# ---------------------------------------------------------------------------
# Execute-path: the master load dispatches, links, and the phase completes
# ---------------------------------------------------------------------------


@dataclass
class _FakeResponse:
    """Shape-compatible with hallucinote_mcp.wire.Response (ok/result/error/hint)."""
    ok: bool
    result: dict | None = None
    error: str | None = None
    hint: str | None = None


def _succeeding_send_fn():
    """A fake send_fn that mirrors Live 12.4.2: a ``device.load`` (master or
    not) SUCCEEDS and returns a synthetic device_index so apply_push_results
    can link it; every other call succeeds trivially. (Under SYN-2M9P this was
    a *refusing* send_fn that rejected master loads — DEV-6M2K removes the
    refusal, so the master load is now a real, succeeding dispatch.)"""
    counters: dict[str, int] = {}
    log: list[dict] = []

    def send(req):
        log.append({"tool": req.tool, "action": req.action, "params": req.params})
        if req.tool == "ableton_device" and req.action == "load":
            counters["device"] = counters.get("device", 0) + 1
            return _FakeResponse(ok=True, result={"device_index": counters["device"]})
        return _FakeResponse(ok=True, result={})

    send.log = log  # type: ignore[attr-defined]
    return send


def _master_load_dispatches(log) -> list:
    return [
        c for c in log
        if c["tool"] == "ableton_device"
        and c["action"] == "load"
        and c["params"].get("master") is True
    ]


def test_execute_unlinked_master_loads_and_completes(
    conn, song, session, master_track, state_dir,
):
    """DEV-6M2K end-to-end: drive an unlinked master device chain through
    execute_push. The master load IS dispatched (master-addressed), succeeds,
    and the devices phase completes cleanly — the master chain is no longer a
    reliable PARTIAL trap."""
    cid = M.create_device_chain(conn, parent_track_id=master_track)
    M.create_device(
        conn, chain_id=cid, position=1,
        kind="Limiter", display_name="Master Limiter",
    )

    send = _succeeding_send_fn()
    result = push_execute.execute_push(
        conn=conn, song_id=song, session_id=session,
        state_dir=state_dir, send_fn=send,
    )

    # The master load went out, master-addressed.
    assert len(_master_load_dispatches(send.log)) == 1, send.log

    by_name = {p.name: p for p in result.phases}
    assert "devices" in by_name
    assert by_name["devices"].status != "halted", by_name["devices"]
    assert result.phase_halted != "devices"
    assert result.outcome != "partial"
    assert result.exit_code != push_execute.EXIT_PARTIAL


def test_execute_unlinked_master_load_then_param_converges(
    conn, song, session, master_track, state_dir,
):
    """Multi-hop: an unlinked master device with a dialed parameter. The
    devices phase loads it (master-addressed), the load links via the
    ``device:<id>`` key, and the SYN-9F2L convergence re-plan — within the same
    execute_push — dispatches the now-plannable set_parameter. Both the load
    and the master-addressed parameter write appear in the dispatch log."""
    cid = M.create_device_chain(conn, parent_track_id=master_track)
    did = M.create_device(
        conn, chain_id=cid, position=1,
        kind="Limiter", display_name="Master Limiter",
    )
    M.set_device_parameter(
        conn, device_id=did, name="Ceiling",
        value_display="-0.3 dB", value_normalized=0.9,
    )

    send = _succeeding_send_fn()
    result = push_execute.execute_push(
        conn=conn, song_id=song, session_id=session,
        state_dir=state_dir, send_fn=send,
    )

    # Load dispatched (master-addressed)...
    assert len(_master_load_dispatches(send.log)) == 1, send.log
    # ...and the convergence re-plan dispatched the master set_parameter.
    master_param_calls = [
        c for c in send.log
        if c["tool"] == "ableton_device"
        and c["action"] == "set_parameter"
        and c["params"].get("master") is True
        and c["params"].get("parameter_name") == "Ceiling"
    ]
    assert len(master_param_calls) == 1, send.log

    by_name = {p.name: p for p in result.phases}
    assert by_name["devices"].status != "halted", by_name["devices"]
    assert result.outcome != "partial"


def test_execute_linked_master_param_writes_through(
    conn, song, session, master_track, state_dir,
):
    """A *linked* master device's parameter write dispatches (master-addressed)
    and the devices phase succeeds — no load is re-emitted for an existing
    device."""
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

    send = _succeeding_send_fn()
    result = push_execute.execute_push(
        conn=conn, song_id=song, session_id=session,
        state_dir=state_dir, send_fn=send,
    )

    # No load for the already-linked device.
    assert _master_load_dispatches(send.log) == [], send.log
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
