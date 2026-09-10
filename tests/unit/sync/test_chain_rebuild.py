"""DEV-5R8Q — `chain_rebuild`: replace a device without destroying the chain below it.

Every test drives a FAKE Live (``FakeLive`` below) rather than a real one, so
what is proved here is the ORCHESTRATION: the order the calls go out in, what is
on disk when, what refuses before touching anything, and what the verify gate
catches. The one thing the fake models faithfully on purpose is the failure the
whole module exists to prevent — a freshly loaded device comes back at its
CLASS DEFAULTS, so a rebuild that forgets to restore produces exactly the
audibly-wrong chain that a call-level "every call returned ok" would report as
success.

What the fake cannot prove is named in the module docstring of each test that
depends on Live's own behaviour (browser resolution, real parameter curves,
whether Live actually silences a muted track mid-rebuild).
"""
from __future__ import annotations

import json

import pytest

from hallucinote.db import init_db, mutations as M, queries as Q
from hallucinote.sync import chain_rebuild
from hallucinote.sync.push import devices as push_devices


# ---------------------------------------------------------------------------
# The fake Live
# ---------------------------------------------------------------------------


class _Resp:
    def __init__(self, *, ok, result=None, error=None):
        self.ok = ok
        self.result = result
        self.error = error


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


def _rebuild(conn, song, session, live, song_dir, **kwargs):
    return chain_rebuild.rebuild_chain(
        conn, song_id=song, session_id=session, parent_kind="track",
        parent_index=3, from_position=1, send_fn=live.send,
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
    chain that is wrong in a way nothing announced."""
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


def test_a_refused_restore_write_alerts_without_gutting_the_run(
    conn, song, session, revoice, live, song_dir,
):
    """One parameter Live refuses to write is an ALERT (R3), not a verify
    failure: R6 gates every parameter the restore RESTORED, and this one was
    not. Halting here would strand the journal over a chain that is as correct
    as Live let it be — while saying nothing would hide a real loss."""
    original = live._ableton_device__set_parameter

    def _refuse_amount(params):
        if params["parameter_name"] == "Amount":
            return _Resp(ok=False, error="parameter is automated")
        return original(params)

    live._ableton_device__set_parameter = _refuse_amount
    result = _rebuild(conn, song, session, live, song_dir)

    assert result.ok
    assert any("restoring 'Amount'" in a and "FAILED" in a
               for a in result.alerts), result.alerts
    # Everything else still landed.
    assert live.device_at(("track", 3), 2).params["1 Frequency A"]["value"] == (
        pytest.approx(0.42)
    )
    assert live.device_at(("track", 3), 3).params["Amount"]["value"] == 0.0


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
