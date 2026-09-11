"""DEV-5R8Q — `chain_rebuild`: replace a device without destroying the chain below it.

Every test drives a FAKE Live (``FakeLive`` below) rather than a real one, so
what is proved here is the ORCHESTRATION: the order the calls go out in, what is
on disk when, what refuses before touching anything, and what the verify gate
catches. The fake validates every param against the real registered ``Action``
so the orchestration it proves is held to the wire's own contract, and it models
faithfully on purpose the failure the whole module exists to prevent — a
freshly loaded device comes back at its
CLASS DEFAULTS, so a rebuild that forgets to restore produces exactly the
audibly-wrong chain that a call-level "every call returned ok" would report as
success.

It also holds devices the DB does not author — see :func:`_analyzer_device`.
That is the second thing it has to model, and until #532 it did not: a chain
built only from the DB's own rows cannot express the device that survives the
delete, so the whole failure was unrepresentable here while being the first thing
a real `alien` hit.

What the fake cannot prove is named in the module docstring of each test that
depends on Live's own behaviour (browser resolution, real parameter curves,
whether Live actually silences a muted track mid-rebuild).
"""
from __future__ import annotations

import json

import pytest

import hallucinote_mcp.actions  # noqa: F401  — registers every Action
from hallucinote_mcp import schema as mcp_schema
from hallucinote_mcp.dispatcher import validate_params

from hallucinote.analyzer_identity import ANALYZER_DEVICE_NAME
from hallucinote.db import init_db, mutations as M, queries as Q
from hallucinote.sync import chain_rebuild, live_escalation
from hallucinote.sync.push import devices as push_devices


# ---------------------------------------------------------------------------
# The fake Live
# ---------------------------------------------------------------------------


class _Resp:
    def __init__(self, *, ok, result=None, error=None, code=None):
        self.ok = ok
        self.result = result
        self.error = error
        # The escalation discriminator. An escalated reply is ok=True, so
        # without this a fake cannot express the one case that distinguishes
        # "the call finished" from "we stopped waiting for it".
        self.code = code


class FakeDevice:
    def __init__(self, cls, params=None, *, class_name=None, name=None,
                 routing=None, chains=None):
        self.cls = cls
        self.class_name = class_name or cls
        self.name = name or cls
        # name -> {"value": float, "value_display": str, "is_enum": bool,
        #          "value_items": [...], "is_enabled": bool}
        self.params = {k: dict(v) for k, v in (params or {}).items()}
        self.routing = dict(routing) if routing else None
        self.chains = [dict(c) for c in (chains or [])]


class FakeLive:
    """A device-chain model just deep enough to drive a rebuild.

    ``defaults`` is the load-bearing part: ``load`` instantiates a device from
    the class's DEFAULT parameter values, never from whatever was there before.
    That is what makes "the rebuild forgot to restore" a detectable state rather
    than an invisible one.
    """

    def __init__(self):
        self.chains: dict[tuple[str, int], list[FakeDevice]] = {}
        self.defaults: dict[str, dict] = {}
        self.muted: dict[tuple[str, int], bool] = {}
        self.calls: list[tuple[str, str, dict]] = []
        # (tool, action) -> error string; that call then answers ok=False.
        self.fail: dict[tuple[str, str], str] = {}
        # (tool, action) -> callable(params) invoked BEFORE the call is served,
        # for probing what is true at that instant (e.g. "is the journal on
        # disk yet?").
        self.watch: dict[tuple[str, str], list] = {}
        # When set, `set_parameter` reports ok and writes NOTHING — the silent
        # regression R6's read-back exists to catch.
        self.swallow_set_parameter = False
        # class -> class the loader ACTUALLY instantiates; lets a test simulate
        # the browser resolving to something other than what was asked for.
        self.load_as: dict[str, str] = {}

    # -- helpers -----------------------------------------------------------
    def key(self, params):
        if params.get("master"):
            return ("master", 0)
        if "track_index" in params:
            return ("track", params["track_index"])
        return ("return", params["return_index"])

    def node_key(self, node):
        parent = node["parent"]
        if parent["kind"] == "master":
            return ("master", 0)
        return (parent["kind"], parent["index"])

    def chain(self, key):
        return self.chains.setdefault(key, [])

    def device_at(self, key, index):
        chain = self.chain(key)
        if 1 <= index <= len(chain):
            return chain[index - 1]
        return None

    def classes(self, key):
        return [d.cls for d in self.chain(key)]

    # -- dispatch ----------------------------------------------------------
    def send(self, req):
        # The wire validates every param against the action's ParamSpec before
        # a handler ever sees it. A fake that skips that lets a wrong-typed
        # param pass here and fail only against a real Live, so validate to
        # hold this fake to the same contract the wire enforces.
        #
        # FAIL CLOSED on an unregistered pair: `mcp_schema.get` returns None
        # for an action that was renamed or retired, and treating that as
        # "nothing to check" would silently switch validation off for exactly
        # the change most likely to break the wire contract.
        action = mcp_schema.get(req.tool, req.action)
        if action is None:
            raise AssertionError(
                f"{req.tool}({req.action!r}) is not a registered MCP action — "
                f"the fake cannot validate it, and passing it unchecked is how "
                f"a wire-contract break reaches Live with the suite green."
            )
        validate_params(action, dict(req.params))
        self.calls.append((req.tool, req.action, dict(req.params)))
        for hook in self.watch.get((req.tool, req.action), []):
            hook(dict(req.params))
        error = self.fail.get((req.tool, req.action))
        if error is not None:
            return _Resp(ok=False, error=error)
        handler = getattr(self, f"_{req.tool}__{req.action}", None)
        if handler is None:
            return _Resp(ok=False, error=f"unhandled {req.tool}/{req.action}")
        return handler(req.params)

    # -- ableton_device ----------------------------------------------------
    def _ableton_device__list(self, params):
        key = self.key(params)
        return _Resp(ok=True, result={"devices": [
            {
                "device_index": i,
                "name": d.name,
                "class_name": d.class_name,
                "class_display_name": d.cls,
            }
            for i, d in enumerate(self.chain(key), start=1)
        ]})

    def _ableton_device__get_parameters(self, params):
        key = self.node_key(params["node"])
        dev = self.device_at(key, params["node"]["device_index"])
        if dev is None:
            return _Resp(ok=False, error="no device there")
        return _Resp(ok=True, result={
            "device_index": params["node"]["device_index"],
            "parameters": [{"name": n, **v} for n, v in dev.params.items()],
        })

    def _ableton_device__get_input_routing(self, params):
        key = self.key(params)
        dev = self.device_at(key, params["device_index"])
        if dev is None or dev.routing is None:
            return _Resp(ok=True, result={"has_input_routing": False})
        return _Resp(ok=True, result={
            "has_input_routing": True, **dev.routing,
        })

    def _ableton_device__set_input_routing(self, params):
        key = self.key(params)
        dev = self.device_at(key, params["device_index"])
        if dev is None:
            return _Resp(ok=False, error="no device there")
        dev.routing = {
            "current_type": params.get("type_display_name"),
            "current_channel": params.get("channel_display_name"),
        }
        return _Resp(ok=True, result={"ok": True})

    def _ableton_device__get_device_chains(self, params):
        key = self.key(params)
        dev = self.device_at(key, params["device_index"])
        if dev is None or not dev.chains:
            return _Resp(ok=False, error="not a rack")
        return _Resp(ok=True, result={"chains": dev.chains})

    def _ableton_device__set_chain_property(self, params):
        node = params["node"]
        key = self.node_key(node)
        dev = self.device_at(key, node["device_index"])
        if dev is None:
            return _Resp(ok=False, error="no device there")
        for chain in dev.chains:
            if chain.get("chain_index") == node["chain_index"]:
                for k, v in params.items():
                    if k != "node":
                        chain[k] = v
        return _Resp(ok=True, result={"ok": True})

    def _ableton_device__pad_info(self, params):
        return _Resp(ok=False, error="not a drum rack")

    def _ableton_device__delete(self, params):
        key = self.key(params)
        chain = self.chain(key)
        idx = params["device_index"]
        if not (1 <= idx <= len(chain)):
            return _Resp(ok=False, error=f"no device at {idx}")
        chain.pop(idx - 1)
        return _Resp(ok=True, result={"deleted": True})

    def _ableton_device__load(self, params):
        key = self.node_key(params["node"])
        asked = params["kind"]
        cls = self.load_as.get(asked, asked)
        chain = self.chain(key)
        chain.append(FakeDevice(cls, self.defaults.get(cls, {})))
        return _Resp(ok=True, result={"device_index": len(chain)})

    def _ableton_device__set_parameter(self, params):
        node = params["node"]
        key = self.node_key(node)
        dev = self.device_at(key, node["device_index"])
        if dev is None:
            return _Resp(ok=False, error="no device there")
        name = params["parameter_name"]
        param = dev.params.get(name)
        if param is None:
            return _Resp(ok=False, error=f"no parameter {name!r}")
        if param.get("is_enabled") is False:
            return _Resp(
                ok=False,
                error="Value cannot be set, the parameter is disabled",
            )
        if self.swallow_set_parameter:
            return _Resp(ok=True, result={"value": param["value"]})
        if params.get("value_type") == "enum":
            items = param.get("value_items") or []
            display = params["value"]
            if display not in items:
                return _Resp(ok=False, error=f"{display!r} not in {items}")
            param["value"] = float(items.index(display))
            param["value_display"] = display
        else:
            param["value"] = float(params["value"])
        return _Resp(ok=True, result={"value": param["value"]})

    # -- ableton_track / ableton_return ------------------------------------
    def _ableton_track__info(self, params):
        return _Resp(ok=True, result={
            "mute": self.muted.get(("track", params["track_index"]), False),
        })

    def _ableton_track__set_property(self, params):
        if params["property"] != "mute":
            return _Resp(ok=False, error="only mute is modelled")
        self.muted[("track", params["track_index"])] = bool(params["value"])
        return _Resp(ok=True, result={"ok": True})

    def _ableton_return__info(self, params):
        return _Resp(ok=True, result={
            "mute": self.muted.get(("return", params["return_index"]), False),
        })

    def _ableton_return__set_property(self, params):
        if params["property"] != "mute":
            return _Resp(ok=False, error="only mute is modelled")
        self.muted[("return", params["return_index"])] = bool(params["value"])
        return _Resp(ok=True, result={"ok": True})


def _cont(value, display=None, *, enabled=None):
    entry = {"value": float(value), "value_display": display or f"{value}",
             "is_enum": False}
    if enabled is not None:
        entry["is_enabled"] = enabled
    return entry


def _analyzer_device():
    """The HallucinoteAnalyzer as Live reports it — an UNAUTHORED device the fake
    can now hold.

    Until this existed the fake's chains were built from the DB's own rows, so a
    live chain carrying a device the DB does not author was not merely untested
    but *unrepresentable* — which is why #532 survived the module's entire life
    and was found on first contact with a real `alien`.

    The identity is the render-stamped NAME; the class display name is the
    generic one every Max audio effect shares, so a fake that modelled only the
    class could not tell the tap from any other M4L device. That asymmetry is
    `analyzer_identity`'s, not this fake's, and the fake has to carry it to be
    worth anything here.
    """
    return FakeDevice("Max Audio Effect", name=ANALYZER_DEVICE_NAME)


# ---------------------------------------------------------------------------
# The song under test — the `alien` witness, in miniature
# ---------------------------------------------------------------------------


@pytest.fixture
def song_dir(tmp_path):
    d = tmp_path / "songs" / "alien"
    d.mkdir(parents=True)
    return d


@pytest.fixture
def conn(song_dir):
    c = init_db(song_dir / "alien.db")
    yield c
    c.close()


@pytest.fixture
def song(conn):
    return M.create_song(conn, name="alien", key="Cm")


@pytest.fixture
def session(conn, song):
    return M.create_ableton_session(conn, song_id=song, name="draft")


@pytest.fixture
def revoice(conn, song, session):
    """DB: track 'Alien Voice' at Live index 3, chain = Operator, EQ Eight,
    Erosion. Live still carries Analog in slot 1 — the re-voice case."""
    tid = M.create_track(
        conn, song_id=song, track_index=1, name="Alien Voice", kind="midi",
    )
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="track", db_id=tid, ableton_index=3,
    )
    chain_id = M.create_device_chain(conn, parent_track_id=tid, position=1)
    ids = {}
    for position, kind in ((1, "Operator"), (2, "EQ Eight"), (3, "Erosion")):
        ids[kind] = M.create_device(
            conn, chain_id=chain_id, position=position, kind=kind,
            display_name=kind,
        )
    conn.commit()
    return {"track_id": tid, "chain_id": chain_id, "device_ids": ids}


@pytest.fixture
def live(revoice):
    fake = FakeLive()
    fake.defaults = {
        "Operator": {"Volume": _cont(0.0, "-inf dB")},
        "EQ Eight": {"1 Frequency A": _cont(0.0, "20 Hz"),
                     "1 Gain A": _cont(0.5, "0.0 dB")},
        "Erosion": {"Amount": _cont(0.0, "0 %"),
                    "Mode": {"value": 0.0, "value_display": "Noise",
                             "is_enum": True,
                             "value_items": ["Noise", "Wide Noise", "Sine"]}},
        "Analog": {"Volume": _cont(0.0, "-inf dB")},
    }
    fake.chains[("track", 3)] = [
        FakeDevice("Analog", {"Volume": _cont(0.61, "-8.0 dB")}),
        FakeDevice("EQ Eight", {"1 Frequency A": _cont(0.42, "412 Hz"),
                                "1 Gain A": _cont(0.73, "+4.1 dB")}),
        FakeDevice("Erosion", {"Amount": _cont(0.77, "77 %"),
                               "Mode": {"value": 2.0,
                                        "value_display": "Sine",
                                        "is_enum": True,
                                        "value_items": ["Noise", "Wide Noise",
                                                        "Sine"]}}),
    ]
    return fake


def _rebuild(conn, song, session, live, song_dir, *, from_position=1, **kwargs):
    return chain_rebuild.rebuild_chain(
        conn, song_id=song, session_id=session, parent_kind="track",
        parent_index=3, from_position=from_position, send_fn=live.send,
        song_dir=song_dir, **kwargs,
    )


# ---------------------------------------------------------------------------
# R1 — the witness: the downstream chain survives the instrument swap
# ---------------------------------------------------------------------------


def test_the_downstream_chain_keeps_its_dialed_state_across_an_instrument_swap(
    conn, song, session, revoice, live, song_dir,
):
    """The `alien` witness (2026-06-22): swap position-1 Analog→Operator and
    keep EQ Eight + Erosion downstream with every non-default parameter intact.

    Every one of those parameters would read back at its class default if the
    rebuild had only deleted and reloaded — which is what the sanctioned manual
    dance produced, silently, on a heavily-tuned chain.
    """
    result = _rebuild(conn, song, session, live, song_dir)

    assert live.classes(("track", 3)) == ["Operator", "EQ Eight", "Erosion"]
    eq = live.device_at(("track", 3), 2)
    assert eq.params["1 Frequency A"]["value"] == pytest.approx(0.42)
    assert eq.params["1 Gain A"]["value"] == pytest.approx(0.73)
    erosion = live.device_at(("track", 3), 3)
    assert erosion.params["Amount"]["value"] == pytest.approx(0.77)
    # The enum rode its display string and came back as the same item.
    assert erosion.params["Mode"]["value_display"] == "Sine"
    assert result.ok
    assert result.restored_params == 4
    # Position 1's class changed, so the OLD instrument's dialed state was
    # deliberately not carried onto the new one — said out loud, not dropped.
    assert any(
        "changed class from 'Analog' to 'Operator'" in a for a in result.alerts
    )


def test_a_failed_rebuild_does_not_leave_the_parent_muted(
    conn, song, session, revoice, live, song_dir,
):
    """The mute is ours, so taking it off is ours on every path.

    A rebuild silences the parent for the transient-empty-chain window. If a
    failure exits before the unmute, the operator is left with a silent track
    and nothing saying why — hunting a mix problem the tool created, while the
    real message (the journal is on disk) is about something else entirely.
    """
    # A write Live accepts and does not apply: the read-back disagrees and
    # the verify gate raises, which is the failure path that matters here.
    live.swallow_set_parameter = True

    with pytest.raises(chain_rebuild.RebuildVerifyFailed):
        _rebuild(conn, song, session, live, song_dir)

    assert live.muted.get(("track", 3)) is not True, (
        "the rebuild exited leaving the parent silenced"
    )


def test_a_second_rebuild_refuses_rather_than_overwriting_the_journal(
    conn, song, session, revoice, live, song_dir,
):
    """The journal of an interrupted run is the ONLY record of what that chain
    held before it started deleting from it.

    Running the command again is the operator's most likely next action, and
    starting over would capture the chain THAT run left — half-demolished, or
    fully gutted — and write it over the record. The refusal has to name the
    resume path, or it just moves the operator's problem sideways.
    """
    live.fail[("ableton_device", "delete")] = "wedged"
    with pytest.raises(Exception):
        _rebuild(conn, song, session, live, song_dir)
    journals = chain_rebuild.stranded_journals(song_dir)
    assert journals, "fixture precondition: the interrupted run left a journal"
    before = journals[0].read_text()

    with pytest.raises(chain_rebuild.RebuildRefused) as caught:
        _rebuild(conn, song, session, live, song_dir)

    assert "--resume" in str(caught.value), "the refusal must name the way out"
    assert journals[0].read_text() == before, "the record was overwritten"


def test_resume_is_not_blocked_by_the_journal_it_exists_to_replay(
    conn, song, session, revoice, live, song_dir,
):
    """The guard is on STARTING OVER, not on finishing.

    `resume` reaches the destructive phases directly, so it bypasses the
    refusal by construction — correct today, and exactly the coupling a later
    refactor breaks silently. Pinning it means the guard cannot grow into the
    one path that must be allowed through.
    """
    live.fail[("ableton_device", "delete")] = "wedged"
    with pytest.raises(Exception):
        _rebuild(conn, song, session, live, song_dir)
    journal = chain_rebuild.stranded_journals(song_dir)[0]
    live.fail.clear()

    result = chain_rebuild.resume(journal, send_fn=live.send, conn=conn)

    assert result.ok, result.alerts
    assert not chain_rebuild.stranded_journals(song_dir), (
        "a passing resume clears the journal"
    )


# ---------------------------------------------------------------------------
# The escalation wire contract
# ---------------------------------------------------------------------------


def test_a_slow_load_is_polled_to_completion_not_booked_as_one(
    conn, song, session, revoice, live, song_dir, monkeypatch,
):
    """An escalated call is ok=True and the work is STILL RUNNING.

    A device load booked as landed while Live is still loading it makes the
    next call in the sequence hit the occupied bout and be refused — raising
    partway through the one operation that must not fail partway through, with
    the chain already gutted. Loading a large device is precisely the case the
    escalation exists for, so this module meets it on its most dangerous path.
    """
    monkeypatch.setattr(live_escalation, "ESCALATION_POLL_INTERVAL_S", 0.0)
    escalated: dict[str, int] = {"loads": 0}
    real_load = live._ableton_device__load

    def _slow_first_load(params):
        # Serve the load for real, then report it as escalated: the work IS
        # happening, the caller just was not told it finished.
        resp = real_load(params)
        escalated["loads"] += 1
        if escalated["loads"] == 1 and resp.ok:
            live._escalated_result = resp.result
            return _Resp(ok=True, result={
                "escalated": True, "job_id": "main_thread-abc123",
                "label": "ableton_device('load')",
            }, code="work_escalated")
        return resp

    def _bout_status(params):
        return _Resp(ok=True, result={"job": {
            "state": "done", "result": live._escalated_result,
        }})

    live._ableton_device__load = _slow_first_load
    live._ableton_session__bout_status = _bout_status

    result = _rebuild(conn, song, session, live, song_dir)

    # The rebuild completed, which it cannot do if the escalation was read as
    # a finished load: the poll is what supplies the device_index the restore
    # addresses.
    assert result.ok, result.alerts
    assert live.classes(("track", 3)) == ["Operator", "EQ Eight", "Erosion"]
    assert any(
        c[:2] == ("ableton_session", "bout_status") for c in live.calls
    ), "the handle was never polled"


# ---------------------------------------------------------------------------
# #532 — an unauthored device survives the rebuild, and must not move the
# restore with it
#
# The `alien` witness failed here on 2026-09-10 against a real Live: the
# HallucinoteAnalyzer the render had left at position 4 survived the delete
# (correctly — the render owns it), the reloads tail-appended behind it, and the
# tap that sat at the TAIL now sat at the HEAD. Every authored device had moved
# down one physical slot while the journal still named the old one, so EQ Eight
# was restored onto Operator and Erosion onto EQ Eight. Measured cost: EQ Eight
# lost 7 of 84 parameters, two of them real gain cuts (`3 Gain A` −1.99951 dB
# and `4 Gain A` −2.50488 dB, both to 0.0).
# ---------------------------------------------------------------------------


def test_a_surviving_analyzer_does_not_shift_the_restore_onto_the_next_device(
    conn, song, session, revoice, live, song_dir,
):
    """The witness, with the tap in the chain: every captured parameter still
    lands on the device it was read from.

    The analyzer is unauthored, so the demolish leaves it and the reloads arrive
    behind it — the one arrangement in which the pre-delete index and the
    post-rebuild index are guaranteed to differ. Addressing by the journal's
    index restores real dialed values onto whatever now occupies that slot, which
    is worse than restoring nothing: it is the same class of device often enough
    that the write succeeds.
    """
    live.chains[("track", 3)].append(_analyzer_device())

    result = _rebuild(conn, song, session, live, song_dir)

    # The render's tap survived, at the head, and the authored chain is in the
    # DB's order behind it.
    assert [d.name for d in live.chain(("track", 3))] == [
        ANALYZER_DEVICE_NAME, "Operator", "EQ Eight", "Erosion",
    ]
    eq = live.device_at(("track", 3), 3)
    assert eq.params["1 Frequency A"]["value"] == pytest.approx(0.42)
    assert eq.params["1 Gain A"]["value"] == pytest.approx(0.73)
    erosion = live.device_at(("track", 3), 4)
    assert erosion.params["Amount"]["value"] == pytest.approx(0.77)
    assert erosion.params["Mode"]["value_display"] == "Sine"
    assert result.ok, result.alerts
    assert result.restored_params == 4
    # Nothing was written onto the tap itself.
    assert not any(
        c[1] == "set_parameter" and c[2]["node"]["device_index"] == 1
        for c in live.calls
    )


def test_the_alerts_name_no_class_change_that_did_not_happen(
    conn, song, session, revoice, live, song_dir,
):
    """The one-slot shift did not only lose parameters — it reported the loss as
    three phantom class changes, which sent the operator looking at their own
    chain instead of at the intruder.

    An alert that names the wrong cause is worse than the silence it replaced,
    so the only class change reported is the one that really happened: the
    re-voice at position 1 the operator asked for.
    """
    live.chains[("track", 3)].append(_analyzer_device())

    result = _rebuild(conn, song, session, live, song_dir)

    changes = [a for a in result.alerts if "changed class" in a]
    assert len(changes) == 1, changes
    assert "changed class from 'Analog' to 'Operator'" in changes[0]
    assert not any("nothing sits at position" in a for a in result.alerts)


def test_an_analyzer_already_at_the_head_restores_every_captured_parameter(
    conn, song, session, revoice, live, song_dir,
):
    """The chain a SECOND rebuild meets, with the whole span in play.

    The first rebuild left the tap at the head, so every captured device answers
    to an index one above its position — the mirror of the tail case, and the one
    the pre-fix code happened to get right: the offset was constant across
    capture and re-read, so the two wrongs cancelled. Pinning it keeps the
    mapping honest rather than arithmetic, and stops a "subtract one" shortcut
    from passing for a fix.
    """
    live.chains[("track", 3)].insert(0, _analyzer_device())

    result = _rebuild(conn, song, session, live, song_dir)

    assert [d.name for d in live.chain(("track", 3))] == [
        ANALYZER_DEVICE_NAME, "Operator", "EQ Eight", "Erosion",
    ]
    assert live.device_at(("track", 3), 3).params["1 Gain A"]["value"] == (
        pytest.approx(0.73)
    )
    assert live.device_at(("track", 3), 4).params["Amount"]["value"] == (
        pytest.approx(0.77)
    )
    assert result.ok, result.alerts
    assert (result.restored_params, result.expected_params) == (4, 4)


def test_a_device_below_the_span_survives_an_analyzer_at_the_head(
    conn, song, session, revoice, live, song_dir,
):
    """A rebuild of part of a chain selects its span by DB POSITION, never by
    Live's index.

    This is the chain a second rebuild meets: the first one left the tap at the
    head, so every authored device answers to an index one higher than its
    position. Reading `--from-position 2` as "index 2 and down" takes out the
    instrument at position 1 — which the plan never reloads, because the DB does
    not author anything before position 2 — and the class order still verifies,
    so the loss reports as a success.
    """
    live.chains[("track", 3)].insert(0, _analyzer_device())

    result = _rebuild(conn, song, session, live, song_dir, from_position=2)

    assert [d.name for d in live.chain(("track", 3))] == [
        ANALYZER_DEVICE_NAME, "Analog", "EQ Eight", "Erosion",
    ], "the instrument below the span was deleted and never reloaded"
    # Untouched, dialed state and all.
    assert live.device_at(("track", 3), 2).params["Volume"]["value"] == (
        pytest.approx(0.61)
    )
    assert result.ok, result.alerts
    assert result.restored_params == 4
    assert result.deleted == ["EQ Eight", "Erosion"]


def test_a_device_the_rebuild_cannot_address_refuses_before_any_delete(
    conn, song, session, revoice, live, song_dir,
):
    """Only the analyzer earns the tolerance.

    Any other device the rebuild would skip survives the delete just the same and
    shifts every later slot, so the restore would write onto the device next
    door. There is no safe way to carry that, and the refusal is the same bright
    line as a device that cannot be reloaded: it names the intruder and runs
    before anything is deleted, while the operator still has the chain in front
    of them.
    """
    original = live._ableton_device__list

    def _with_an_unaddressable_device(params):
        resp = original(params)
        if resp.ok and live.key(params) == ("track", 3):
            resp.result["devices"].append({
                "device_index": None,
                "name": "Mystery",
                "class_name": "Compressor2",
                "class_display_name": "Compressor",
            })
        return resp

    live._ableton_device__list = _with_an_unaddressable_device

    with pytest.raises(chain_rebuild.RebuildRefused) as caught:
        _rebuild(conn, song, session, live, song_dir)

    message = str(caught.value)
    assert "'Mystery'" in message, message
    assert "HallucinoteAnalyzer" in message
    assert not any(c[1] == "delete" for c in live.calls)
    assert not chain_rebuild.stranded_journals(song_dir)
    assert live.classes(("track", 3)) == ["Analog", "EQ Eight", "Erosion"]


def test_a_shortfall_exit_is_non_zero_and_keeps_the_journal(
    conn, song, session, revoice, live, song_dir, monkeypatch, capsys,
):
    """#538's exit contract, through the entry point an operator actually runs.

    `main` returned 0 unconditionally, so re-running #291's witness box after a
    fix produced an exit code that meant nothing — which is why this ships with
    #532 rather than after it. The exit names what was captured, what was
    restored and where the journal still is; a bare 1 would send the operator
    back to the scrollback.
    """
    monkeypatch.setattr(chain_rebuild, "_cli_send_fn", lambda: live.send)
    original = live._ableton_device__set_parameter

    def _refuse_amount(params):
        if params["parameter_name"] == "Amount":
            return _Resp(ok=False, error="parameter is automated")
        return original(params)

    live._ableton_device__set_parameter = _refuse_amount

    rc = chain_rebuild.main([
        session, "--db", str(song_dir / "alien.db"), "--track", "3",
    ])

    captured = capsys.readouterr()
    out, err = captured.out, captured.err
    assert rc == 1
    assert "restored 3 of 4 writable parameter(s)" in err, err
    journal = chain_rebuild.journal_path_for(song_dir, "track", 3)
    assert str(journal) in err
    assert journal.exists()
    assert "SHORTFALL" in out


def test_a_restore_that_lands_nothing_exits_non_zero_from_the_cli(
    conn, song, session, revoice, live, song_dir, monkeypatch, capsys,
):
    """The wholly-failed restore, end to end: exit 1, the journal named, and the
    chain left for `--resume` rather than reported rebuilt."""
    monkeypatch.setattr(chain_rebuild, "_cli_send_fn", lambda: live.send)
    live.fail[("ableton_device", "set_parameter")] = "parameter is automated"

    rc = chain_rebuild.main([
        session, "--db", str(song_dir / "alien.db"), "--track", "3",
    ])

    assert rc == 1
    err = capsys.readouterr().err
    assert "VERIFY FAILED" in err
    assert "--resume auto" in err
    assert chain_rebuild.journal_path_for(song_dir, "track", 3).exists()


# ---------------------------------------------------------------------------
# R2 — the journal is durable and pre-delete
# ---------------------------------------------------------------------------


def test_the_journal_is_on_disk_before_the_first_delete_is_dispatched(
    conn, song, session, revoice, live, song_dir,
):
    """R2. A crash between demolish and rebuild is the failure that destroys mix
    work, and only something on disk survives it — so the assertion is about
    call ORDERING, not about the file existing at the end."""
    journal = chain_rebuild.journal_path_for(song_dir, "track", 3)
    seen: list[dict] = []

    def _on_delete(params):
        seen.append({
            "journal_exists": journal.exists(),
            "captured": (
                json.loads(journal.read_text())["captured"]
                if journal.exists() else None
            ),
        })

    live.watch[("ableton_device", "delete")] = [_on_delete]
    _rebuild(conn, song, session, live, song_dir)

    assert seen, "no delete was dispatched at all"
    assert seen[0]["journal_exists"], (
        "the first delete went out before the journal reached disk"
    )
    # And the journal held the whole chain, not just the device being deleted.
    assert [e["class"] for e in seen[0]["captured"]] == [
        "Analog", "EQ Eight", "Erosion",
    ]
    assert seen[0]["captured"][1]["parameters"][0]["value"] == pytest.approx(0.42)


def test_the_journal_is_removed_only_after_the_verify_pass(
    conn, song, session, revoice, live, song_dir,
):
    journal = chain_rebuild.journal_path_for(song_dir, "track", 3)
    at_verify: list[bool] = []

    def _on_get_parameters(params):
        at_verify.append(journal.exists())

    live.watch[("ableton_device", "get_parameters")] = [_on_get_parameters]
    result = _rebuild(conn, song, session, live, song_dir)

    # The last get_parameters is the verify read-back; the journal was still
    # there for it, and gone once the run reported success.
    assert at_verify[-1] is True
    assert not journal.exists()
    assert result.journal_path is None


def test_a_failure_between_demolish_and_rebuild_leaves_the_journal(
    conn, song, session, revoice, live, song_dir,
):
    """R2's recovery half: the run dies with the chain gutted, and the record of
    what was in it is on disk."""
    live.fail[("ableton_device", "load")] = "browser item not found"

    with pytest.raises(chain_rebuild.RebuildVerifyFailed) as exc:
        _rebuild(conn, song, session, live, song_dir)
    assert "part-way rebuilt" in str(exc.value)

    journal = chain_rebuild.journal_path_for(song_dir, "track", 3)
    assert journal.exists()
    payload = json.loads(journal.read_text())
    assert payload["phase"] == chain_rebuild.PHASE_DEMOLISHED
    assert [e["class"] for e in payload["captured"]] == [
        "Analog", "EQ Eight", "Erosion",
    ]
    # And Live really is gutted — this is the state the journal has to survive.
    assert live.classes(("track", 3)) == []


def test_resume_reconstructs_the_chain_from_the_journal_alone(
    conn, song, session, revoice, live, song_dir,
):
    """R2. ``resume`` is handed nothing but the journal path and a send_fn — no
    connection, no song id — because that is all an operator has after the
    process that started the rebuild is gone."""
    live.fail[("ableton_device", "load")] = "Live went away"
    with pytest.raises(chain_rebuild.RebuildVerifyFailed):
        _rebuild(conn, song, session, live, song_dir)
    journal = chain_rebuild.journal_path_for(song_dir, "track", 3)
    assert journal.exists()

    live.fail.pop(("ableton_device", "load"))
    result = chain_rebuild.resume(journal, send_fn=live.send)

    assert live.classes(("track", 3)) == ["Operator", "EQ Eight", "Erosion"]
    eq = live.device_at(("track", 3), 2)
    assert eq.params["1 Frequency A"]["value"] == pytest.approx(0.42)
    assert not journal.exists()
    assert result.ok
    # With no connection it says so rather than leaving stale links to be
    # discovered on the next push.
    assert any("probe-and-link" in a for a in result.alerts)


def test_resume_deletes_what_the_interrupted_run_left_not_what_it_captured(
    conn, song, session, revoice, live, song_dir,
):
    """The interrupted run may have got half-way through the deletes. Replaying
    the journal's ORIGINAL capture as the delete list would address indices that
    no longer exist; the resume re-probes instead."""
    live.fail[("ableton_device", "delete")] = "Live went away"
    with pytest.raises(chain_rebuild.RebuildVerifyFailed):
        _rebuild(conn, song, session, live, song_dir)
    # Nothing was deleted, so the whole chain is still there.
    assert live.classes(("track", 3)) == ["Analog", "EQ Eight", "Erosion"]
    live.fail.pop(("ableton_device", "delete"))

    # Simulate the operator having removed one device by hand before resuming.
    live.chains[("track", 3)].pop()
    journal = chain_rebuild.journal_path_for(song_dir, "track", 3)
    chain_rebuild.resume(journal, send_fn=live.send)

    assert live.classes(("track", 3)) == ["Operator", "EQ Eight", "Erosion"]


def test_a_journal_from_an_unknown_version_refuses_rather_than_replaying(
    song_dir, live,
):
    journal = chain_rebuild.journal_path_for(song_dir, "track", 3)
    chain_rebuild.write_journal(journal, {"version": 99, "parent_kind": "track"})
    with pytest.raises(chain_rebuild.RebuildRefused, match="version"):
        chain_rebuild.resume(journal, send_fn=live.send)


# ---------------------------------------------------------------------------
# R3 — a parameter that cannot be restored is an ALERT, never a silent skip
# ---------------------------------------------------------------------------


def test_a_locked_parameter_alerts_instead_of_being_dropped(
    conn, song, session, revoice, live, song_dir,
):
    """R3. ``is_enabled=False`` is a macro-mapped or locked parameter: Live
    reads it fine and refuses every write. Skipping it quietly would hand back a
    chain that is wrong in a way nothing announced.

    It is also NOT a shortfall (#538): it was never writable, so counting it
    against the restore would make every chain carrying one macro exit non-zero
    for ever, and an exit code that is always 1 says nothing.
    """
    live.chains[("track", 3)][1].params["1 Gain A"] = _cont(
        0.73, "+4.1 dB", enabled=False,
    )
    result = _rebuild(conn, song, session, live, song_dir)

    assert result.ok
    assert any(
        "'1 Gain A'" in a and "is_enabled=False" in a for a in result.alerts
    ), result.alerts
    # It was never written — the write would have failed anyway, and the point
    # is that the operator is told, not that the call was attempted.
    assert not any(
        c[1] == "set_parameter" and c[2].get("parameter_name") == "1 Gain A"
        for c in live.calls
    )
    assert (result.restored_params, result.expected_params) == (3, 3)
    assert not any("SHORTFALL" in a for a in result.alerts)
    assert not chain_rebuild.journal_path_for(song_dir, "track", 3).exists()


def test_a_parameter_whose_read_failed_is_alerted_and_not_invented(
    conn, song, session, revoice, live, song_dir,
):
    """A capture that could not read a device's parameters must not silently
    restore that device to defaults and call the run a success."""
    live.fail[("ableton_device", "get_parameters")] = "Live timed out"
    result = _rebuild(conn, song, session, live, song_dir)

    assert result.ok
    assert sum("could not read parameters" in a for a in result.alerts) == 3
    assert result.restored_params == 0


def test_a_refused_restore_write_alerts_and_finishes_but_is_not_success(
    conn, song, session, revoice, live, song_dir,
):
    """One parameter Live refuses to write does not HALT the run — R6 gates
    every parameter the restore RESTORED, and this one was not, so raising
    would abandon a chain that is as correct as Live let it be.

    It is not a success either (#538). The captured value is real mix work that
    is now only in the journal, so the run finishes, rebinds its links and
    reports — and then says SHORTFALL, keeps the journal and exits non-zero.
    Both halves matter: the chain is left usable, and nothing calls it done.
    """
    original = live._ableton_device__set_parameter

    def _refuse_amount(params):
        if params["parameter_name"] == "Amount":
            return _Resp(ok=False, error="parameter is automated")
        return original(params)

    live._ableton_device__set_parameter = _refuse_amount
    result = _rebuild(conn, song, session, live, song_dir)

    assert any("restoring 'Amount'" in a and "FAILED" in a
               for a in result.alerts), result.alerts
    # Everything else still landed — the run was not gutted.
    assert live.device_at(("track", 3), 2).params["1 Frequency A"]["value"] == (
        pytest.approx(0.42)
    )
    assert live.device_at(("track", 3), 3).params["Amount"]["value"] == 0.0
    assert live.classes(("track", 3)) == ["Operator", "EQ Eight", "Erosion"]
    # …and it is reported as the shortfall it is, with the record retained.
    assert not result.ok
    assert (result.restored_params, result.expected_params) == (3, 4)
    assert any("SHORTFALL" in a for a in result.alerts), result.alerts
    journal = chain_rebuild.journal_path_for(song_dir, "track", 3)
    assert journal.exists(), (
        "the values that did not land are only in the journal"
    )
    assert result.journal_path == journal


def test_a_restore_that_lands_nothing_fails_verify_instead_of_passing_on_zero(
    conn, song, session, revoice, live, song_dir,
):
    """#538. The read-back is scoped to what the restore WROTE, so a restore
    that wrote nothing compares nothing — and `continue`d past every device,
    reported ok and unlinked the journal.

    That is precisely the shape of the failure it exists to catch: a chain
    sitting at its class DEFAULTS passes a comparison over an empty set. So
    "landed none of them" is a verify failure, and the journal — which this
    module's own docstring calls the only way back — survives it.
    """
    live.fail[("ableton_device", "set_parameter")] = "parameter is automated"

    with pytest.raises(chain_rebuild.RebuildVerifyFailed) as caught:
        _rebuild(conn, song, session, live, song_dir)

    message = str(caught.value)
    assert "VERIFY FAILED" in message
    assert "landed NONE of the 4 writable parameter(s)" in message
    assert chain_rebuild.journal_path_for(song_dir, "track", 3).exists()
    # And the chain really is at its defaults — the state this used to call ok.
    assert live.device_at(("track", 3), 2).params["1 Frequency A"]["value"] == 0.0


# ---------------------------------------------------------------------------
# R4 — refuse BEFORE touching anything
# ---------------------------------------------------------------------------


def test_a_placeholder_in_the_span_refuses_before_any_delete(
    conn, song, session, revoice, live, song_dir,
):
    """R4. Live tail-appends, so a rebuild cannot reproduce an intentionally
    empty slot mid-chain — and deleting a chain it cannot put back is
    unrecoverable, so the refusal comes before the first delete."""
    M.create_device(
        conn, chain_id=revoice["chain_id"], position=4, kind="placeholder",
        display_name="reserved for a delay",
    )
    conn.commit()

    with pytest.raises(chain_rebuild.RebuildRefused) as exc:
        _rebuild(conn, song, session, live, song_dir)

    message = str(exc.value)
    assert "PLACEHOLDER" in message
    assert "reserved for a delay" in message, "the refusal must NAME the device"
    assert not any(c[1] == "delete" for c in live.calls)
    assert live.classes(("track", 3)) == ["Analog", "EQ Eight", "Erosion"]
    assert not chain_rebuild.journal_path_for(song_dir, "track", 3).exists()


def test_an_unlinked_parent_refuses(conn, song, session, revoice, live, song_dir):
    with pytest.raises(chain_rebuild.RebuildRefused, match="no link"):
        chain_rebuild.rebuild_chain(
            conn, song_id=song, session_id=session, parent_kind="track",
            parent_index=9, from_position=1, send_fn=live.send,
            song_dir=song_dir,
        )
    assert not any(c[1] == "delete" for c in live.calls)


def test_a_span_the_db_authors_nothing_in_refuses(
    conn, song, session, revoice, live, song_dir,
):
    with pytest.raises(chain_rebuild.RebuildRefused, match="authors no devices"):
        chain_rebuild.rebuild_chain(
            conn, song_id=song, session_id=session, parent_kind="track",
            parent_index=3, from_position=9, send_fn=live.send,
            song_dir=song_dir,
        )
    assert not any(c[1] == "delete" for c in live.calls)


def test_an_unreadable_chain_refuses_rather_than_deleting_blind(
    conn, song, session, revoice, live, song_dir,
):
    live.fail[("ableton_device", "list")] = "track not found"
    with pytest.raises(chain_rebuild.RebuildRefused, match="could not read"):
        _rebuild(conn, song, session, live, song_dir)
    assert not any(c[1] == "delete" for c in live.calls)


# ---------------------------------------------------------------------------
# R5 — the transient empty-chain window is silenced
# ---------------------------------------------------------------------------


def test_the_parent_is_muted_across_the_rebuild_and_restored_from_the_journal(
    conn, song, session, revoice, live, song_dir,
):
    """R5. The chain is briefly EMPTY, then briefly holds a raw un-processed
    instrument. A rebuild during playback must not blast that through the mix."""
    mute_at_delete: list[bool] = []
    live.watch[("ableton_device", "delete")] = [
        lambda p: mute_at_delete.append(live.muted.get(("track", 3), False))
    ]
    live.watch[("ableton_device", "load")] = [
        lambda p: mute_at_delete.append(live.muted.get(("track", 3), False))
    ]
    _rebuild(conn, song, session, live, song_dir)

    assert all(mute_at_delete), "the window was not silenced"
    assert live.muted[("track", 3)] is False


def test_a_parent_the_operator_had_muted_stays_muted(
    conn, song, session, revoice, live, song_dir,
):
    """The restore reads the pre-rebuild mute out of the journal rather than
    hardcoding 'unmuted' — un-silencing a track the operator muted is a mix
    change they did not ask for."""
    live.muted[("track", 3)] = True
    _rebuild(conn, song, session, live, song_dir)
    assert live.muted[("track", 3)] is True


def test_the_master_says_it_cannot_silence_the_window(
    conn, song, session, live, song_dir,
):
    """The master strip has no mute. R5 is unachievable there, so the rebuild
    says so instead of pretending it silenced anything."""
    tid = M.create_track(
        conn, song_id=song, track_index=2, name="Master", kind="master",
    )
    chain_id = M.create_device_chain(conn, parent_track_id=tid, position=1)
    M.create_device(conn, chain_id=chain_id, position=1, kind="Limiter",
                    display_name="Limiter")
    conn.commit()
    live.defaults["Limiter"] = {"Ceiling": _cont(0.9, "-0.3 dB")}
    live.chains[("master", 0)] = [
        FakeDevice("Utility", {"Gain": _cont(0.5, "0.0 dB")}),
    ]

    result = chain_rebuild.rebuild_chain(
        conn, song_id=song, session_id=session, parent_kind="master",
        parent_index=0, from_position=1, send_fn=live.send, song_dir=song_dir,
    )
    assert live.classes(("master", 0)) == ["Limiter"]
    assert any("has no mute" in a for a in result.alerts)


# ---------------------------------------------------------------------------
# R6 — the read-back is a gate, not a log line
# ---------------------------------------------------------------------------


def test_verify_fails_when_the_reprobed_order_disagrees_with_the_db(
    conn, song, session, revoice, live, song_dir,
):
    """R6. The browser resolved 'Erosion' to something else; every call still
    returned ok. Without the read-back this run reports success over a chain
    that is not the song."""
    live.load_as["Erosion"] = "Redux"

    with pytest.raises(chain_rebuild.RebuildVerifyFailed) as exc:
        _rebuild(conn, song, session, live, song_dir)
    message = str(exc.value)
    assert "VERIFY FAILED" in message
    assert "'Redux'" in message
    assert chain_rebuild.journal_path_for(song_dir, "track", 3).exists()


def test_verify_fails_when_a_restored_parameter_reads_back_at_its_default(
    conn, song, session, revoice, live, song_dir,
):
    """R6, and the regression the whole gate exists for: every `set_parameter`
    reports ok and writes nothing, so the chain is rebuilt at CLASS DEFAULTS —
    an audibly wrong track that a call-level check reports as ok."""
    live.swallow_set_parameter = True

    with pytest.raises(chain_rebuild.RebuildVerifyFailed) as exc:
        _rebuild(conn, song, session, live, song_dir)
    message = str(exc.value)
    assert "did not read back equal" in message
    assert "'1 Frequency A'" in message
    assert chain_rebuild.journal_path_for(song_dir, "track", 3).exists()


def test_verify_fails_when_the_read_back_probe_itself_fails(
    conn, song, session, revoice, live, song_dir,
):
    """"Could not verify" must never read as "verified clean"."""
    seen = {"loads": 0}

    original = live._ableton_device__list

    def _list(params):
        seen["loads"] += 1
        # Fail only the final verify probe, after everything is rebuilt.
        if seen["loads"] >= 3:
            return _Resp(ok=False, error="Live stopped answering")
        return original(params)

    live._ableton_device__list = _list
    with pytest.raises(chain_rebuild.RebuildVerifyFailed, match="UNVERIFIED"):
        _rebuild(conn, song, session, live, song_dir)


# ---------------------------------------------------------------------------
# R7 — one mechanism, two callers; the push caller is opt-in
# ---------------------------------------------------------------------------


def test_occupied_slots_names_the_shallowest_colliding_position(
    conn, song, session, revoice,
):
    """The reconcile fires on EXACTLY the condition the devices planner refuses
    on, and starts at the shallowest one — everything at or below it has to come
    out before the DB's order can be re-established."""
    live_map = {("track", 3): [
        {"device_index": 1, "class_display_name": "Analog", "name": "Analog"},
        {"device_index": 2, "class_display_name": "EQ Eight", "name": "EQ"},
    ]}
    slots = push_devices.occupied_slots(
        conn, song_id=song, session_id=session,
        live_devices_by_parent=live_map,
    )
    assert len(slots) == 1
    assert slots[0].parent_kind == "track"
    assert slots[0].parent_index == 3
    assert slots[0].from_position == 1
    assert slots[0].occupant_class == "Analog"


def test_occupied_slots_ignores_a_parent_whose_chain_could_not_be_read(
    conn, song, session, revoice,
):
    """An UNKNOWN verdict is a chain a rebuild must not touch — the capture it
    would journal is the same read that just failed."""
    assert push_devices.occupied_slots(
        conn, song_id=song, session_id=session, live_devices_by_parent={},
    ) == []


def test_occupied_slots_ignores_an_already_linked_device(
    conn, song, session, revoice,
):
    for kind, pos in (("Operator", 1), ("EQ Eight", 2), ("Erosion", 3)):
        M.link_db_to_ableton(
            conn, session_id=session, db_kind="device",
            db_id=revoice["device_ids"][kind], ableton_index=pos,
        )
    conn.commit()
    live_map = {("track", 3): [
        {"device_index": 1, "class_display_name": "Operator"},
    ]}
    assert push_devices.occupied_slots(
        conn, song_id=song, session_id=session,
        live_devices_by_parent=live_map,
    ) == []


def test_reconcile_chains_rebuilds_the_refused_parent(
    conn, song, session, revoice, live, song_dir,
):
    """R7's second caller. It reaches the same ``rebuild_chain``, which is the
    owner's 2026-08-07 ruling: one mechanism, two callers, not a push-local
    rebuild grown in isolation."""
    live_map = {("track", 3): [
        {"device_index": 1, "class_display_name": "Analog", "name": "Analog"},
        {"device_index": 2, "class_display_name": "EQ Eight", "name": "EQ"},
        {"device_index": 3, "class_display_name": "Erosion", "name": "Erosion"},
    ]}
    results = chain_rebuild.reconcile_chains(
        conn, song_id=song, session_id=session,
        live_devices_by_parent=live_map, send_fn=live.send, song_dir=song_dir,
    )
    assert len(results) == 1
    assert live.classes(("track", 3)) == ["Operator", "EQ Eight", "Erosion"]
    assert live.device_at(("track", 3), 2).params["1 Frequency A"]["value"] == (
        pytest.approx(0.42)
    )


def test_reconcile_chains_touches_nothing_when_no_slot_is_occupied(
    conn, song, session, revoice, live, song_dir,
):
    results = chain_rebuild.reconcile_chains(
        conn, song_id=song, session_id=session, live_devices_by_parent={},
        send_fn=live.send, song_dir=song_dir,
    )
    assert results == []
    assert live.calls == []


# ---------------------------------------------------------------------------
# #323 — after a reconcile, a SECOND push emits no drift note for that parent
# ---------------------------------------------------------------------------


def test_a_reconcile_rerecords_links_so_the_next_probe_emits_no_drift_note(
    conn, song, session, revoice, live, song_dir,
):
    """Folded in from #323. Before this, the drift note was re-emitted on every
    push forever because nothing ever changed what produced it. A rebuild makes
    the chain match the DB AND re-records the links from the new positions, so
    the next probe finds a class match at every position and says nothing."""
    from hallucinote.sync import push

    _rebuild(conn, song, session, live, song_dir)

    for kind, pos in (("Operator", 1), ("EQ Eight", 2), ("Erosion", 3)):
        assert Q.get_ableton_link(
            conn, session_id=session, db_kind="device",
            db_id=revoice["device_ids"][kind],
        ) == pos

    live_map = {("track", 3): [
        {"device_index": i, "class_display_name": cls, "name": cls}
        for i, cls in enumerate(live.classes(("track", 3)), start=1)
    ]}
    result = push.probe_and_link(
        conn, song_id=song, session_id=session,
        live_tracks=[{"track_index": 3, "name": "Alien Voice", "kind": "midi"}],
        live_returns=[],
        live_devices_by_parent=live_map,
    )
    assert not [n for n in result.notes if "device drift at" in n], result.notes


def test_the_drift_note_names_the_rebuild_as_a_remedy(
    conn, song, session, revoice,
):
    """The note used to describe a situation with no way out of it. Its two
    honest remedies are re-snapshotting (accept Live's order) and rebuilding
    (make the DB's order true) — it now names both."""
    from hallucinote.sync import push

    live_map = {("track", 3): [
        {"device_index": 1, "class_display_name": "Analog", "name": "Analog"},
    ]}
    result = push.probe_and_link(
        conn, song_id=song, session_id=session,
        live_tracks=[{"track_index": 3, "name": "Alien Voice", "kind": "midi"}],
        live_returns=[],
        live_devices_by_parent=live_map,
    )
    drift = [n for n in result.notes if "device drift at" in n]
    assert drift
    assert "chain-rebuild" in drift[0]


# ---------------------------------------------------------------------------
# The refusal message names the remedy either way
# ---------------------------------------------------------------------------


def test_the_occupied_slot_refusal_names_chain_rebuild(
    conn, song, session, revoice,
):
    """Without ``--reconcile-chains`` the halt stands — and its message must
    name the command that resolves it, which is the whole reason the halt was
    filed as unfinished (#323: 'the refusal offers no remedy')."""
    from hallucinote.sync import push

    live_map = {("track", 3): [
        {"device_index": 1, "class_display_name": "Analog", "name": "Analog"},
    ]}
    plan = push.plan_push_devices(
        conn, song_id=song, session_id=session,
        live_devices_by_parent=live_map,
    )
    assert plan.errors
    assert "chain-rebuild" in plan.errors[0]
    assert "--reconcile-chains" in plan.errors[0]
    assert "--from-position 1" in plan.errors[0]


# ---------------------------------------------------------------------------
# Journal shape + the rack limit
# ---------------------------------------------------------------------------


def test_a_racks_chain_properties_are_captured_and_restored(
    conn, song, session, song_dir, live,
):
    """A rack comes back via its PRESET, so its nested devices are out of reach —
    but the per-chain properties the operator authored on top of it are not, and
    are restored."""
    tid = M.create_track(
        conn, song_id=song, track_index=2, name="Drums", kind="midi",
    )
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="track", db_id=tid, ableton_index=2,
    )
    chain_id = M.create_device_chain(conn, parent_track_id=tid, position=1)
    M.create_device(conn, chain_id=chain_id, position=1, kind="Drum Rack",
                    display_name="Drum Rack")
    M.create_device(conn, chain_id=chain_id, position=2, kind="Saturator",
                    display_name="Saturator")
    conn.commit()
    live.defaults["Drum Rack"] = {"Macro 1": _cont(0.0, "0")}
    live.defaults["Saturator"] = {"Drive": _cont(0.0, "0.0 dB")}
    live.chains[("track", 2)] = [
        FakeDevice("Drum Rack", {"Macro 1": _cont(0.31, "31")},
                   chains=[{"chain_index": 1, "name": "Clap",
                            "choke_group": 2, "volume": 0.62}]),
        FakeDevice("Saturator", {"Drive": _cont(0.55, "11.0 dB")}),
    ]

    chain_rebuild.rebuild_chain(
        conn, song_id=song, session_id=session, parent_kind="track",
        parent_index=2, from_position=1, send_fn=live.send, song_dir=song_dir,
    )
    rack = live.device_at(("track", 2), 1)
    assert rack.params["Macro 1"]["value"] == pytest.approx(0.31)
    # The reloaded rack carries the preset's chains; the authored per-chain
    # properties were re-applied onto them.
    reapplied = [
        c for c in live.calls
        if c[1] == "set_chain_property"
    ]
    assert reapplied and reapplied[0][2]["choke_group"] == 2
    assert reapplied[0][2]["volume"] == pytest.approx(0.62)


def test_stranded_journals_lists_what_is_left_to_resume(song_dir, live):
    assert chain_rebuild.stranded_journals(song_dir) == []
    p = chain_rebuild.journal_path_for(song_dir, "track", 3)
    chain_rebuild.write_journal(p, {"version": chain_rebuild.JOURNAL_VERSION})
    assert chain_rebuild.stranded_journals(song_dir) == [p]


def test_a_rebuild_with_no_song_directory_refuses(live):
    """A rebuild without a durable journal is exactly the failure this command
    exists to remove, so an anchorless (in-memory) connection refuses rather
    than running the destructive part with an in-memory record."""
    mem = init_db(":memory:")
    try:
        song_id = M.create_song(mem, name="alien", key="Cm")
        session_id = M.create_ableton_session(
            mem, song_id=song_id, name="draft",
        )
        tid = M.create_track(
            mem, song_id=song_id, track_index=1, name="T", kind="midi",
        )
        M.link_db_to_ableton(
            mem, session_id=session_id, db_kind="track", db_id=tid,
            ableton_index=3,
        )
        chain_id = M.create_device_chain(mem, parent_track_id=tid, position=1)
        M.create_device(mem, chain_id=chain_id, position=1, kind="Operator",
                        display_name="Operator")
        mem.commit()
        with pytest.raises(chain_rebuild.RebuildRefused,
                           match="no song directory"):
            chain_rebuild.rebuild_chain(
                mem, song_id=song_id, session_id=session_id,
                parent_kind="track", parent_index=3, from_position=1,
                send_fn=live.send,
            )
    finally:
        mem.close()
    assert not any(c[1] == "delete" for c in live.calls)


def test_from_position_below_one_is_a_programming_error(
    conn, song, session, revoice, live, song_dir,
):
    with pytest.raises(ValueError, match="must be >= 1"):
        chain_rebuild.rebuild_chain(
            conn, song_id=song, session_id=session, parent_kind="track",
            parent_index=3, from_position=0, send_fn=live.send,
            song_dir=song_dir,
        )


# ---------------------------------------------------------------------------
# The `hallucinote chain-rebuild` entry point
#
# Exercised through `chain_rebuild.main(argv)` directly — the dispatcher in
# `cli.py` forwards argv verbatim and returns the exit code, so driving the
# module's own entry proves everything the subcommand does.
# ---------------------------------------------------------------------------


def test_cli_rebuilds_a_named_track_and_reports_what_it_carried(
    conn, song, session, revoice, live, song_dir, monkeypatch, capsys,
):
    monkeypatch.setattr(chain_rebuild, "_cli_send_fn", lambda: live.send)
    rc = chain_rebuild.main([
        session, "--db", str(song_dir / "alien.db"), "--track", "3",
        "--from-position", "1",
    ])
    assert rc == 0, capsys.readouterr().err
    out = capsys.readouterr().out
    assert "Alien Voice" in out
    assert "4 parameter(s) restored" in out
    assert live.classes(("track", 3)) == ["Operator", "EQ Eight", "Erosion"]


def test_cli_needs_a_parent(conn, song, session, revoice, live, song_dir,
                            monkeypatch, capsys):
    monkeypatch.setattr(chain_rebuild, "_cli_send_fn", lambda: live.send)
    with pytest.raises(SystemExit, match="name the parent"):
        chain_rebuild.main([session, "--db", str(song_dir / "alien.db")])


def test_cli_needs_a_song_or_db(capsys):
    assert chain_rebuild.main(["--track", "3"]) == 2
    assert "need --song" in capsys.readouterr().err


def test_cli_reports_a_refusal_on_stderr_with_exit_2(
    conn, song, session, revoice, live, song_dir, monkeypatch, capsys,
):
    """A refusal is not a crash and not a partial run — it is the command
    declining before touching anything, which deserves its own exit code."""
    monkeypatch.setattr(chain_rebuild, "_cli_send_fn", lambda: live.send)
    rc = chain_rebuild.main([
        session, "--db", str(song_dir / "alien.db"), "--track", "9",
    ])
    assert rc == 2
    assert "no link binding a track to Live index 9" in capsys.readouterr().err


def test_cli_resume_auto_finds_the_one_stranded_journal(
    conn, song, session, revoice, live, song_dir, monkeypatch, capsys,
):
    monkeypatch.setattr(chain_rebuild, "_cli_send_fn", lambda: live.send)
    live.fail[("ableton_device", "load")] = "Live went away"
    rc = chain_rebuild.main([
        session, "--db", str(song_dir / "alien.db"), "--track", "3",
    ])
    assert rc == 1
    err = capsys.readouterr().err
    assert "--resume auto" in err
    assert chain_rebuild.journal_path_for(song_dir, "track", 3).exists()

    live.fail.pop(("ableton_device", "load"))
    rc = chain_rebuild.main([
        session, "--db", str(song_dir / "alien.db"), "--resume", "auto",
    ])
    assert rc == 0, capsys.readouterr().err
    assert live.classes(("track", 3)) == ["Operator", "EQ Eight", "Erosion"]
    assert not chain_rebuild.journal_path_for(song_dir, "track", 3).exists()


def test_cli_resume_auto_refuses_to_choose_between_several_journals(
    conn, song, session, revoice, live, song_dir, monkeypatch, capsys,
):
    """Picking a chain to rebuild on the operator's behalf is not a default
    worth having."""
    monkeypatch.setattr(chain_rebuild, "_cli_send_fn", lambda: live.send)
    for index in (3, 4):
        chain_rebuild.write_journal(
            chain_rebuild.journal_path_for(song_dir, "track", index),
            {"version": chain_rebuild.JOURNAL_VERSION},
        )
    rc = chain_rebuild.main([
        session, "--db", str(song_dir / "alien.db"), "--resume", "auto",
    ])
    assert rc == 2
    assert "several stranded journals" in capsys.readouterr().err


def test_cli_resume_on_a_missing_journal_says_so(
    conn, song, session, revoice, live, song_dir, monkeypatch, capsys,
):
    monkeypatch.setattr(chain_rebuild, "_cli_send_fn", lambda: live.send)
    rc = chain_rebuild.main([
        session, "--db", str(song_dir / "alien.db"), "--resume", "auto",
    ])
    assert rc == 2
    assert "nothing to resume" in capsys.readouterr().err


def test_a_continuous_restore_value_reaches_the_wire_as_a_string():
    """``set_parameter`` declares ``ParamSpec(name="value", type="str")``, so a
    bare float is rejected by validation before it reaches Live.

    Asserted against the REAL action schema, not a copy of it, so the producer
    and the contract cannot drift apart.
    """
    kwargs = chain_rebuild._param_write_kwargs(
        {"name": "1 Gain A", "value": -1.99951171875}
    )
    assert kwargs is not None
    assert isinstance(kwargs["value"], str), (
        "a float here is refused by the wire and restores nothing"
    )
    # exact on the way back: repr is float's shortest round-trip form
    assert float(kwargs["value"]) == -1.99951171875

    action = mcp_schema.get("ableton_device", "set_parameter")
    assert action is not None
    validate_params(action, {
        "node": {"parent": {"kind": "track", "index": 4},
                 "terminal": "device", "device_index": 2},
        "parameter_name": "1 Gain A",
        **kwargs,
    })


def test_an_enum_restore_value_still_rides_its_display_string():
    """The enum branch rides its display string, the continuous branch a
    stringified float. Pinned so a fix to one does not regress the other."""
    kwargs = chain_rebuild._param_write_kwargs({
        "name": "Mode", "is_enum": True,
        "value_items": ["Standard", "Soft Clip"], "value_display": "Soft Clip",
    })
    assert kwargs == {"value": "Soft Clip", "value_type": "enum"}


def test_the_fake_refuses_an_action_the_wire_does_not_register():
    """The fixture's validation must FAIL CLOSED.

    ``mcp_schema.get`` returns ``None`` for a renamed or retired action, so a
    guard that treats a miss as "nothing to check" would switch validation off
    for precisely the change most likely to break the wire contract — the same
    shape as the defect this fixture was hardened to catch. Without this test
    that branch is unreachable from the suite and could rot silently.
    """
    live = FakeLive()

    class _Req:
        tool, action, params = "ableton_device", "no_such_action_here", {}

    assert mcp_schema.get(_Req.tool, _Req.action) is None, (
        "this test is only meaningful while the action is genuinely unregistered"
    )
    with pytest.raises(AssertionError, match="not a registered MCP action"):
        live.send(_Req())


# ---------- the journal's two meanings (#538 integration) ----------


def test_a_shortfall_stamps_its_journal_so_a_later_reader_can_tell(
    conn, song, session, revoice, live, song_dir,
):
    """The retained journal has to say WHICH kind of retention it is.

    A rebuild that finished and rebound its links, missing some values, is not a
    rebuild that stopped mid-demolition — and `push execute` must treat them
    differently, so the distinction has to survive on disk rather than living in
    the exit code of a process that already ended.
    """
    original = live._ableton_device__set_parameter

    def _refuse_amount(params):
        if params["parameter_name"] == "Amount":
            return _Resp(ok=False, error="parameter is automated")
        return original(params)

    live._ableton_device__set_parameter = _refuse_amount
    result = _rebuild(conn, song, session, live, song_dir)

    assert not result.ok
    journal = chain_rebuild.journal_path_for(song_dir, "track", 3)
    assert journal.exists()
    assert chain_rebuild.journal_phase(journal) == chain_rebuild.PHASE_SHORTFALL
    mid_flight, shortfall = chain_rebuild.partition_journals(song_dir)
    assert shortfall == [journal]
    assert mid_flight == [], (
        "a finished-but-short rebuild is not a chain anyone abandoned"
    )


def test_an_unreadable_journal_is_treated_as_mid_flight(song_dir):
    """Unknown degrades to dangerous. A journal this cannot parse might describe
    a half-demolished chain, so it must never be classified as the benign kind —
    that is the direction the failure has to fall."""
    d = chain_rebuild.journal_dir_for(song_dir)
    d.mkdir(parents=True, exist_ok=True)
    garbage = d / "track-9.json"
    garbage.write_text("{not json at all")

    assert chain_rebuild.journal_phase(garbage) == ""
    mid_flight, shortfall = chain_rebuild.partition_journals(song_dir)
    assert mid_flight == [garbage] and shortfall == []


def test_a_mid_flight_journal_classifies_as_mid_flight(song_dir):
    """Every phase that is not a shortfall, including the one that is a judgement
    rather than a leftover.

    ``verified`` is the interesting member: the verify is stamped BEFORE the final
    chain read and the link rebind, so a disconnect in that window leaves a chain
    that is correct while the DB's links still address the pre-rebuild one. The
    chain being right is what makes it dangerous — a push would plan against
    stale indices and report ok — so it groups here, with ``--resume`` as its
    remedy. The code says only ``else mid_flight``, so without this element the
    grouping is asserted by a docstring and pinned by nothing.
    """
    d = chain_rebuild.journal_dir_for(song_dir)
    d.mkdir(parents=True, exist_ok=True)
    for i, phase in enumerate((
        chain_rebuild.PHASE_JOURNALED,
        chain_rebuild.PHASE_DEMOLISHED,
        chain_rebuild.PHASE_REBUILT,
        chain_rebuild.PHASE_RESTORED,
        chain_rebuild.PHASE_VERIFIED,
    )):
        (d / f"track-{i}.json").write_text(
            json.dumps({"version": chain_rebuild.JOURNAL_VERSION, "phase": phase})
        )

    mid_flight, shortfall = chain_rebuild.partition_journals(song_dir)
    assert len(mid_flight) == 5 and shortfall == []


# ---------- the links are addresses, not positions (#532, one layer out) ----------


def test_the_links_address_the_post_rebuild_chain_when_the_tap_survives(
    conn, song, session, revoice, live, song_dir,
):
    """`ableton_links.ableton_index` is consumed as a PHYSICAL device index —
    `plan_push_devices` hands it straight to `set_parameter` as `device_index`.

    With the analyzer surviving at the head, DB position q answers to physical
    index q+1, so recording the position pointed every link one device short. The
    restore landed correctly and the next push then wrote authored values onto
    the neighbour — including `push execute --only devices`, which is the
    recovery the shortfall alert and the conventions guide both recommend. This
    is the same defect as #532 one layer out, and it survived the fix to the
    restore.
    """
    live.chains[("track", 3)].append(_analyzer_device())

    _rebuild(conn, song, session, live, song_dir)

    chain = live.chain(("track", 3))
    assert [d.name for d in chain][0] == ANALYZER_DEVICE_NAME, (
        "the tap must survive at the HEAD for this test to mean anything"
    )
    physical = {d.name: i for i, d in enumerate(chain, start=1)}
    assert physical["EQ Eight"] == 3 and physical["Erosion"] == 4

    for kind in ("Operator", "EQ Eight", "Erosion"):
        assert Q.get_ableton_link(
            conn, session_id=session, db_kind="device",
            db_id=revoice["device_ids"][kind],
        ) == physical[kind], (
            f"{kind}'s link must address the device Live answers to, not its "
            f"DB position"
        )


# ---------- a refused sidechain source is captured mix work too ----------


def test_a_refused_input_routing_restore_is_a_shortfall(
    conn, song, session, revoice, live, song_dir,
):
    """The sidechain SOURCE is the one value this module could still lose while
    exiting 0: it was alerted about but never counted, so the run reported
    success and then deleted the journal holding it.

    That is precisely what #536 exists to stop being silent and what #291's
    sidechain box is queued to witness, so it has to reach the shortfall.
    """
    # The capture only journals routing for a device that HAS a routing
    # surface, so the compressor has to carry one for this path to be reached.
    live.device_at(("track", 3), 2).routing = {
        "current_type": "Drums", "current_channel": "Post Mixer",
    }
    original = live._ableton_device__set_input_routing

    def _refuse(params):
        return _Resp(ok=False, error="no input routing on this device")

    live._ableton_device__set_input_routing = _refuse
    try:
        result = _rebuild(conn, song, session, live, song_dir)
    finally:
        live._ableton_device__set_input_routing = original

    assert any("input routing" in a and "FAILED" in a for a in result.alerts), (
        result.alerts
    )
    assert not result.ok, "a lost sidechain source is not a successful rebuild"
    journal = chain_rebuild.journal_path_for(song_dir, "track", 3)
    assert journal.exists(), "the captured routing is only in the journal now"
    assert chain_rebuild.journal_phase(journal) == chain_rebuild.PHASE_SHORTFALL


# ---------- a journal from before positions existed cannot be replayed ----------


def test_a_journal_without_positions_is_refused_rather_than_guessed(song_dir):
    """The old reader re-derived a missing `position` from entry ORDER, which is
    right only if the captured span held nothing but authored devices — and a
    journal written before `position` existed is by definition one written by the
    code that could not see a surviving analyzer. Replaying it onto a chain whose
    tap now sits at the head reproduces the off-by-one exactly.

    So it is refused, and JOURNAL_VERSION carries the requirement.
    """
    path = chain_rebuild.journal_path_for(song_dir, "track", 3)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "version": 1,
        "phase": chain_rebuild.PHASE_DEMOLISHED,
        "parent_kind": "track", "parent_index": 3, "from_position": 1,
        "captured": [], "plan_devices": [],
    }))

    with pytest.raises(chain_rebuild.RebuildRefused) as exc:
        chain_rebuild.read_journal(path)
    assert "version" in str(exc.value)


def test_an_entry_without_a_position_refuses_instead_of_inferring_one():
    """The guard below `read_journal`, for a version-2 journal whose entries are
    somehow short a position — refuse, never fall back to entry order."""
    with pytest.raises(chain_rebuild.RebuildRefused) as exc:
        chain_rebuild._entry_position({"class": "EQ Eight"})
    assert "one slot off" in str(exc.value)


# ---------- the two journal-phase branches, each pinned ----------


def _leave_a_shortfall(conn, song, session, revoice, live, song_dir):
    """Run a rebuild that finishes and comes up short, leaving its journal."""
    original = live._ableton_device__set_parameter

    def _refuse_amount(params):
        if params["parameter_name"] == "Amount":
            return _Resp(ok=False, error="parameter is automated")
        return original(params)

    live._ableton_device__set_parameter = _refuse_amount
    try:
        result = _rebuild(conn, song, session, live, song_dir)
    finally:
        live._ableton_device__set_parameter = original
    assert not result.ok
    journal = chain_rebuild.journal_path_for(song_dir, "track", 3)
    assert chain_rebuild.journal_phase(journal) == chain_rebuild.PHASE_SHORTFALL
    return journal


def test_a_second_rebuild_over_a_shortfall_journal_refuses_with_the_right_remedy(
    conn, song, session, revoice, live, song_dir,
):
    """Both journal states refuse a fresh rebuild, and they must refuse
    DIFFERENTLY, because the remedies are opposites: `--resume` recovers a gutted
    chain and DESTROYS a correct one.

    A shortfall chain is rebuilt, rebound and verified for everything that
    landed. Telling the operator it "did not finish" and handing them `--resume`
    as the fix sends them at a full demolish of work that is already right, so
    this branch names the cheap remedy first and prices the destructive one.
    """
    _leave_a_shortfall(conn, song, session, revoice, live, song_dir)

    with pytest.raises(chain_rebuild.RebuildRefused) as exc:
        _rebuild(conn, song, session, live, song_dir)

    message = str(exc.value)
    assert "SHORTFALL" in message
    assert "push execute --only devices" in message, (
        "the cheap remedy has to be the one named first"
    )
    assert "did not finish" not in message, (
        "that is the mid-flight story, and it is false here"
    )


def test_resume_auto_declines_a_shortfall_journal_and_says_what_to_do_instead(
    conn, song, session, revoice, live, song_dir, monkeypatch, capsys,
):
    """`auto` means "finish the rebuild that stopped". Before this, `auto` read an
    undifferentiated journal list and would select a shortfall journal — then
    demolish and rebuild a chain the module had just certified correct, silently,
    on an operator who asked it to recover something.

    It declines and names the file instead. Retrying the refused writes is still
    available, but only by naming the journal, so the destruction is always
    chosen rather than inferred.
    """
    journal = _leave_a_shortfall(conn, song, session, revoice, live, song_dir)
    monkeypatch.setattr(chain_rebuild, "_cli_send_fn", lambda: live.send)
    classes_before = live.classes(("track", 3))
    # The setup rebuild did its own deletes; only what happens AFTER this point
    # says anything about the decline.
    calls_before = len(live.calls)

    rc = chain_rebuild.main([
        session, "--db", str(song_dir / "alien.db"), "--resume", "auto",
    ])

    err = capsys.readouterr().err
    # 2 is this module's "declined before touching anything" code, asserted
    # exactly by its four sibling CLI tests — `!= 0` would accept a crash.
    assert rc == 2
    assert "no unfinished rebuild to resume" in err
    assert str(journal) in err
    assert "push execute --only devices" in err
    assert not any(c[1] == "delete" for c in live.calls[calls_before:]), (
        "auto must not demolish a chain it declined to resume"
    )
    assert live.classes(("track", 3)) == classes_before
    assert journal.exists(), "declining must not discard the captured values"


def test_resume_auto_still_finishes_a_mid_flight_journal_beside_a_shortfall(
    conn, song, session, revoice, live, song_dir, monkeypatch, capsys,
):
    """The classification is per file. A shortfall journal sitting next to a
    genuinely unfinished one must not make `auto` give up on the one it exists
    to finish."""
    _leave_a_shortfall(conn, song, session, revoice, live, song_dir)
    d = chain_rebuild.journal_dir_for(song_dir)
    (d / "track-7.json").write_text(json.dumps({
        "version": chain_rebuild.JOURNAL_VERSION,
        "phase": chain_rebuild.PHASE_DEMOLISHED,
        "parent_kind": "track", "parent_index": 7,
    }))

    target = chain_rebuild._cli_resume_target("auto", song_dir)

    assert target is not None and target.name == "track-7.json", (
        "auto must pick the unfinished rebuild, not refuse because a shortfall "
        "journal is also on disk"
    )



# ---------------------------------------------------------------------------
# #544 — an unreadable sidechain source is announced before it is destroyed
# ---------------------------------------------------------------------------


def test_an_unreadable_sidechain_source_warns_before_the_first_delete(
    conn, song, session, revoice, live, song_dir, capsys,
):
    """A source Live exposes no routing surface for is the one piece of mix work
    a rebuild can destroy while exiting 0.

    Every OTHER way this module loses a source ends in a write it attempted and
    Live refused, and that write raises its own alert. This one never reaches a
    write: the capture records nothing, so the restore has nothing to put back,
    and the demolish deletes the device that held it. Two surfaces already warn
    on this (`capture.py`, `push/plan.py`); this is the third and the only
    destructive one.

    The warning has to be on screen BEFORE the delete, not merely in the final
    report — the command is non-interactive, so the operator's own Ctrl-C is
    the only abort there is, and by the time the report prints the source is
    already gone.
    """
    armed = live.chains[("track", 3)][2]
    armed.params["S/C On"] = _cont(1.0, "On")
    assert armed.routing is None, (
        "the fixture must expose NO routing surface — that is the case"
    )

    result = _rebuild(conn, song, session, live, song_dir)

    assert any("sidechain source NOT machine-readable" in a
               for a in result.alerts), result.alerts
    assert any("'Erosion'" in a for a in result.alerts), result.alerts

    # On stderr while the chain was still intact, not only in the report.
    err = capsys.readouterr().err
    assert "sidechain source NOT machine-readable" in err


def test_a_readable_sidechain_source_adds_no_unreadable_warning(
    conn, song, session, revoice, live, song_dir,
):
    """The gate is `has_input_routing`, not "is a sidechain armed".

    A routing-capable device — the Compressor common case — is captured and
    restored through `set_input_routing` like any other value, so warning here
    would teach the operator to ignore the warning that matters.
    """
    armed = live.chains[("track", 3)][2]
    armed.params["S/C On"] = _cont(1.0, "On")
    armed.routing = {"current_type": "Audio", "current_channel": "1/2"}

    result = _rebuild(conn, song, session, live, song_dir)

    assert not any("sidechain source NOT machine-readable" in a
                   for a in result.alerts), result.alerts


def test_an_unarmed_device_with_no_routing_surface_stays_quiet(
    conn, song, session, revoice, live, song_dir,
):
    """Most of a chain has no input routing and no sidechain. Warning on every
    such device would make the warning worthless."""
    result = _rebuild(conn, song, session, live, song_dir)

    assert not any("sidechain source NOT machine-readable" in a
                   for a in result.alerts), result.alerts


# ---------------------------------------------------------------------------
# #534 — why the verify tolerance is safe, pinned
# ---------------------------------------------------------------------------


def test_the_verify_tolerance_is_never_consulted_in_anger(
    conn, song, session, revoice, live, song_dir,
):
    """`_PARAM_EPSILON` is an ABSOLUTE 1e-6, and a real-Live probe measured
    float32's round-trip error to be RELATIVE — so on a large-magnitude
    parameter (a 22 kHz frequency) an absolute epsilon would be breached by a
    perfectly correct write, and an integer-stepped parameter exposed as
    continuous would breach it outright.

    Neither reaches this module, and the reason is a property worth pinning
    rather than a coincidence worth trusting: the restore never INVENTS a
    value. `capture_chain` reads each parameter off Live, `_restore` writes
    that same value back, and the verify compares the two — so both ends are
    the same Live-sourced number and the delta is zero by construction, not by
    tolerance. The probe that produced those breaching deltas wrote deliberately
    off-grid values (41.424 into a stepped parameter), which is a thing
    chain-rebuild cannot do.

    This is the contract that keeps the epsilon honest. If a future change lets
    an AUTHORED value (from the DB, or computed) into the restore, the premise
    is gone and the tolerance has to be reconsidered — this test is what should
    fail and say so.
    """
    # The two shapes the probe found breaching, as Live would report them.
    eq = live.chains[("track", 3)][1]
    eq.params["1 Frequency A"] = _cont(22000.0, "22.0 kHz")
    eq.params["Note PB Range"] = _cont(41.0, "41 st")
    live.defaults["EQ Eight"]["1 Frequency A"] = _cont(0.0, "20 Hz")
    live.defaults["EQ Eight"]["Note PB Range"] = _cont(0.0, "0 st")

    result = _rebuild(conn, song, session, live, song_dir)

    assert result.ok, result.alerts
    assert not any("reads back" in a for a in result.alerts), (
        "a faithful round trip must not be reported as a mismatch"
    )
    # …and they really did land, rather than passing by never being written.
    assert eq.params["1 Frequency A"]["value"] == 22000.0
    assert eq.params["Note PB Range"]["value"] == 41.0


def test_a_parameter_left_at_its_default_is_still_caught(
    conn, song, session, revoice, live, song_dir,
):
    """The regression the tolerance exists for, and the other half of the test
    above: a tolerance that never fires is indistinguishable from one that
    cannot fire, and this is what tells them apart.

    A freshly loaded device comes back at class defaults. When the restore
    reports a write that Live silently did not apply, the read-back is the
    default and the verify has to say so — otherwise a chain rebuilt to
    defaults, which is audibly wrong, reports ok.
    """
    live.swallow_set_parameter = True

    with pytest.raises(chain_rebuild.RebuildVerifyFailed) as excinfo:
        _rebuild(conn, song, session, live, song_dir)

    # It names the values, so the journal is not the only way to learn them.
    msg = str(excinfo.value)
    assert "'1 Frequency A' was 0.42, reads back 0.0" in msg
    assert "The journal is intact." in msg
