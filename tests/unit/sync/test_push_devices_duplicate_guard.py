"""PSH-DEVDUP — the devices phase must never append a chain Live already has.

The bug, observed on `the-argument` (2026-08-08, Live 12.4 Suite): the chain was
loaded into Live by ``/song-pick-instruments`` (direct MCP ``ableton_device
load``), captured into ``captured_session.json``, and only then entered the DB —
via ``replay_capture`` during ``build.py --reset``. So the DB's device rows had
NO ``ableton_links`` binding, because nothing in the ``push_cli execute`` path
ever wrote one (``probe_and_link``, which does, runs only in its own
subcommand). ``plan_push_devices`` read "unlinked" as "absent" and emitted a
``load`` for all eighteen post-instrument effects across nine tracks. Live 12.4
has no reorder API, so each load TAIL-APPENDED: every FX chain was doubled, and
the phase reported ``23/23 ok``.

Three layers of coverage, matching the three layers of the fix:

  * ``classify_load_target`` / ``compare_chain`` — the pure decisions.
  * ``reconcile_device_links`` — binding the DB to a chain Live already carries.
  * ``execute_push`` end-to-end — an idempotent re-push appends nothing, a
    rebuilt DB appends nothing, an unmatchable chain REFUSES, a trailing
    HallucinoteAnalyzer doesn't disturb any of it, and a set that IS doubled
    fails the post-phase integrity assert instead of reporting OK.
"""
from __future__ import annotations

from dataclasses import dataclass

import pytest

from hallucinote.db import init_db, mutations as M, queries as Q
from hallucinote.sync import push, push_execute
from hallucinote.sync.device_chain_verify import (
    CHAIN_DUPLICATED,
    CHAIN_EXTRA,
    CHAIN_FAITHFUL,
    CHAIN_PROBE_FAILED,
    CHAIN_SHORT,
    DeviceChainIntegrityError,
    assert_device_chains_materialized,
    compare_chain,
    verify_device_chains,
)
from hallucinote.sync.push.devices import (
    _LOAD_TARGET_ABSENT,
    _LOAD_TARGET_PRESENT,
    _LOAD_TARGET_UNKNOWN,
    classify_load_target,
)


ANALYZER = {
    "device_index": 99,
    "name": "HallucinoteAnalyzer",
    "class_display_name": "Max Audio Effect",
}


@dataclass
class FakeResponse:
    ok: bool
    result: dict | None = None
    error: str | None = None
    hint: str | None = None


@pytest.fixture
def conn(tmp_path):
    c = init_db(tmp_path / "devdup.db")
    yield c
    c.close()


@pytest.fixture
def state_dir(tmp_path):
    d = tmp_path / "state"
    d.mkdir()
    return d


def _guitar_song(conn, *, link_devices=False):
    """One track carrying the exact shape that got doubled: an instrument plus
    a four-deep post-instrument FX chain."""
    song = M.create_song(conn, name="the-argument", key="Em")
    session = M.create_ableton_session(conn, song_id=song, name="draft")
    track = M.create_track(conn, song_id=song, track_index=1, name="Rhythm Gtr")
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="track", db_id=track, ableton_index=3,
    )
    chain = M.create_device_chain(conn, parent_track_id=track)
    device_ids = []
    for pos, (kind, name) in enumerate(
        [("Tension", "Steel Picked Guitar"), ("Overdrive", "Overdrive"),
         ("Amp", "Heavy"), ("Cabinet", "Cabinet"), ("Saturator", "Saturator")],
        start=1,
    ):
        did = M.create_device(
            conn, chain_id=chain, position=pos, kind=kind, display_name=name,
        )
        device_ids.append(did)
        if link_devices:
            M.link_db_to_ableton(
                conn, session_id=session, db_kind="device", db_id=did,
                ableton_index=pos,
            )
    return {
        "song": song, "session": session, "track": track,
        "devices": device_ids,
    }


_LIVE_GUITAR_CHAIN = [
    {"device_index": 1, "name": "Steel Picked Guitar",
     "class_display_name": "Tension"},
    {"device_index": 2, "name": "Overdrive", "class_display_name": "Overdrive"},
    {"device_index": 3, "name": "Heavy", "class_display_name": "Amp"},
    {"device_index": 4, "name": "Cabinet", "class_display_name": "Cabinet"},
    {"device_index": 5, "name": "Saturator", "class_display_name": "Saturator"},
]


def _send_fn(chains_by_parent, *, load_index_start=6):
    """Fake send_fn that MODELS a Live set's device chains.

    ``chains_by_parent`` maps ``("track", idx)`` / ``("return", idx)`` /
    ``("master", 0)`` to the device list ``ableton_device(action='list')``
    returns; a key mapped to ``None`` answers not-ok (an unreadable parent).
    ``load`` appends, exactly like Live 12.4 (no reorder API) — which is what
    makes an unnecessary load a duplication rather than a no-op.
    """
    call_log: list = []
    next_index = {"n": load_index_start}

    def _parent_key(params):
        node = params.get("node") or {}
        parent = node.get("parent") or {}
        if params.get("master") or parent.get("kind") == "master":
            return ("master", 0)
        if "track_index" in params:
            return ("track", params["track_index"])
        if "return_index" in params:
            return ("return", params["return_index"])
        if parent.get("kind") in ("track", "return"):
            return (parent["kind"], parent.get("index"))
        return None

    def send(req, *, read_timeout=None):
        call_log.append({
            "tool": req.tool, "action": req.action, "params": dict(req.params),
        })
        if req.tool == "ableton_device" and req.action == "list":
            key = _parent_key(req.params)
            chain = chains_by_parent.get(key, [])
            if chain is None:
                return FakeResponse(ok=False, error="probe refused")
            return FakeResponse(ok=True, result={"devices": list(chain)})
        if req.tool == "ableton_device" and req.action == "load":
            key = _parent_key(req.params)
            idx = next_index["n"]
            next_index["n"] += 1
            chains_by_parent.setdefault(key, []).append({
                "device_index": idx,
                "name": req.params.get("kind"),
                "class_display_name": req.params.get("kind"),
            })
            return FakeResponse(ok=True, result={"device_index": idx})
        return FakeResponse(ok=True, result={})

    send.call_log = call_log
    send.chains = chains_by_parent
    return send


def _loads(send_fn):
    return [c for c in send_fn.call_log if c["action"] == "load"]


# ---------------------------------------------------------------------------
# classify_load_target — the pure "is this slot already occupied?" decision
# ---------------------------------------------------------------------------


def test_classify_no_probe_map_stays_permissive():
    """A caller with no Live truth (``push_cli plan``, the unit suite) keeps the
    pre-fix contract — the guard binds where the corruption happened, the
    execute path, not on planners that never had a probe to begin with."""
    assert classify_load_target(
        None, parent_kind="track", parent_index=3, position=2,
    ) == (_LOAD_TARGET_ABSENT, None)


def test_classify_absent_when_live_chain_is_shorter():
    verdict, occupant = classify_load_target(
        {("track", 3): _LIVE_GUITAR_CHAIN[:1]},
        parent_kind="track", parent_index=3, position=2,
    )
    assert verdict == _LOAD_TARGET_ABSENT
    assert occupant is None


def test_classify_present_when_slot_is_occupied():
    verdict, occupant = classify_load_target(
        {("track", 3): _LIVE_GUITAR_CHAIN},
        parent_kind="track", parent_index=3, position=2,
    )
    assert verdict == _LOAD_TARGET_PRESENT
    assert occupant["name"] == "Overdrive"


def test_classify_unknown_when_parent_was_not_probed():
    """Absent from a map that exists = the read failed. "Can't determine" must
    not collapse into "absent" — that collapse is the bug."""
    assert classify_load_target(
        {("track", 9): []}, parent_kind="track", parent_index=3, position=1,
    ) == (_LOAD_TARGET_UNKNOWN, None)


def test_classify_ignores_trailing_analyzer():
    """The render leaves a HallucinoteAnalyzer trailing every measured chain. It
    is measurement infrastructure, never an authored slot, so it must not make
    a genuinely-absent position read as occupied."""
    verdict, _ = classify_load_target(
        {("track", 3): _LIVE_GUITAR_CHAIN[:2] + [dict(ANALYZER, device_index=3)]},
        parent_kind="track", parent_index=3, position=3,
    )
    assert verdict == _LOAD_TARGET_ABSENT


# ---------------------------------------------------------------------------
# compare_chain — the integrity comparator
# ---------------------------------------------------------------------------


def test_compare_chain_faithful():
    assert compare_chain(["Tension", "Overdrive"], ["Tension", "Overdrive"]) == (
        CHAIN_FAITHFUL, []
    )


def test_compare_chain_flags_the_doubling_signature():
    status, dupes = compare_chain(
        ["Tension", "Overdrive", "Amp"],
        ["Tension", "Overdrive", "Amp", "Overdrive", "Amp"],
    )
    assert status == CHAIN_DUPLICATED
    assert dupes == ["Amp", "Overdrive"]


def test_compare_chain_tolerates_a_device_the_db_never_authored():
    """A stock/hand-placed device is the composer's, not corruption — halting on
    it would break working sets for no safety gain."""
    assert compare_chain(["Reverb"], ["Reverb", "Utility"]) == (CHAIN_EXTRA, [])


def test_compare_chain_reports_a_short_chain():
    assert compare_chain(["Reverb", "Delay"], ["Reverb"]) == (CHAIN_SHORT, [])


# ---------------------------------------------------------------------------
# plan_push_devices — the probe map is what changes the answer
# ---------------------------------------------------------------------------


def test_planner_without_a_probe_map_still_loads_a_present_chain(conn):
    """Pins the delta the fix turns on. With no Live truth the planner CANNOT
    tell present-but-unlinked from missing, and emits five loads — the pre-fix
    behavior, preserved for callers that never had a probe (``push_cli plan``).
    This is the failure mode; the guard below is what the execute path gains."""
    s = _guitar_song(conn, link_devices=False)
    plan = push.plan_push_devices(
        conn, song_id=s["song"], session_id=s["session"],
    )
    assert len([c for c in plan.calls if c.args.get("action") == "load"]) == 5
    assert plan.errors == []


def test_planner_with_a_probe_map_refuses_instead_of_loading(conn):
    """Same DB, same Live set, one extra input: the probe map. Now the planner
    emits ZERO loads and five refusals — it will not append onto a chain it can
    see is already there."""
    s = _guitar_song(conn, link_devices=False)
    plan = push.plan_push_devices(
        conn, song_id=s["song"], session_id=s["session"],
        live_devices_by_parent={("track", 3): _LIVE_GUITAR_CHAIN},
    )
    assert [c for c in plan.calls if c.args.get("action") == "load"] == []
    assert len(plan.errors) == 5
    assert all("REFUSING to load" in e for e in plan.errors)


# ---------------------------------------------------------------------------
# reconcile_device_links — binding to a chain Live already carries
# ---------------------------------------------------------------------------


def test_reconcile_binds_an_unlinked_chain_that_live_already_has(conn):
    """The exact repro: DB devices from a snapshot replay, zero device links,
    Live already holding the chain."""
    s = _guitar_song(conn, link_devices=False)
    result = push.reconcile_device_links(
        conn, song_id=s["song"], session_id=s["session"],
        live_devices_by_parent={("track", 3): _LIVE_GUITAR_CHAIN},
    )
    assert len(result.matched) == 5
    for pos, did in enumerate(s["devices"], start=1):
        assert Q.get_ableton_link(
            conn, session_id=s["session"], db_kind="device", db_id=did,
        ) == pos


def test_reconcile_ignores_a_trailing_analyzer(conn):
    s = _guitar_song(conn, link_devices=False)
    result = push.reconcile_device_links(
        conn, song_id=s["song"], session_id=s["session"],
        live_devices_by_parent={
            ("track", 3): _LIVE_GUITAR_CHAIN + [dict(ANALYZER, device_index=6)],
        },
    )
    assert len(result.matched) == 5


def test_reconcile_refuses_to_bind_across_a_class_mismatch(conn):
    s = _guitar_song(conn, link_devices=False)
    drifted = [dict(d) for d in _LIVE_GUITAR_CHAIN]
    drifted[1]["class_display_name"] = "Phaser"
    result = push.reconcile_device_links(
        conn, song_id=s["song"], session_id=s["session"],
        live_devices_by_parent={("track", 3): drifted},
    )
    assert Q.get_ableton_link(
        conn, session_id=s["session"], db_kind="device", db_id=s["devices"][1],
    ) is None
    assert any("device drift" in n for n in result.notes)


def test_reconcile_drops_a_link_to_a_vanished_index(conn):
    s = _guitar_song(conn, link_devices=True)
    # Live now holds only the first three devices; positions 4-5 are gone.
    result = push.reconcile_device_links(
        conn, song_id=s["song"], session_id=s["session"],
        live_devices_by_parent={("track", 3): _LIVE_GUITAR_CHAIN[:3]},
    )
    assert {r["db_id"] for r in result.unlinked_stale} == set(s["devices"][3:])
    assert Q.get_ableton_link(
        conn, session_id=s["session"], db_kind="device", db_id=s["devices"][4],
    ) is None


def test_reconcile_leaves_an_unprobed_parent_alone(conn):
    s = _guitar_song(conn, link_devices=True)
    result = push.reconcile_device_links(
        conn, song_id=s["song"], session_id=s["session"],
        live_devices_by_parent={},
    )
    assert result.unlinked_stale == []
    assert Q.get_ableton_link(
        conn, session_id=s["session"], db_kind="device", db_id=s["devices"][0],
    ) == 1


# ---------------------------------------------------------------------------
# execute_push — the end-to-end contract
# ---------------------------------------------------------------------------


def test_push_onto_a_set_that_already_has_the_chain_appends_nothing(
    conn, state_dir,
):
    """THE regression. DB devices carry no links (snapshot-replay origin); Live
    already holds the exact chain. Before the fix this dispatched five loads and
    reported ok, doubling the FX chain."""
    s = _guitar_song(conn, link_devices=False)
    send = _send_fn({("track", 3): [dict(d) for d in _LIVE_GUITAR_CHAIN]})
    result = push_execute.execute_push(
        conn=conn, song_id=s["song"], session_id=s["session"],
        state_dir=state_dir, send_fn=send, only="devices",
    )
    assert result.outcome == "ok"
    assert _loads(send) == []
    assert len(send.chains[("track", 3)]) == 5  # nothing appended
    # ... and the DB now knows what Live has, so the NEXT push is a no-op too.
    for pos, did in enumerate(s["devices"], start=1):
        assert Q.get_ableton_link(
            conn, session_id=s["session"], db_kind="device", db_id=did,
        ) == pos


def test_push_after_a_soft_reset_rebuild_appends_nothing(conn, state_dir):
    """``build.py --reset`` is a SOFT reset: it preserves tracks / devices /
    ``ableton_links``, and ``replay_capture`` re-creates device rows under the
    same upsert-stable UUIDs. A push straight after it must still be a no-op
    against a set that already carries the chain."""
    s = _guitar_song(conn, link_devices=False)
    push.reconcile_device_links(
        conn, song_id=s["song"], session_id=s["session"],
        live_devices_by_parent={("track", 3): _LIVE_GUITAR_CHAIN},
    )
    M.reset_song_content(conn, song_id=s["song"])
    # Devices + their links survived the soft reset — that is the documented
    # contract, and it is what makes the re-push idempotent.
    assert len(Q.get_devices_for_track(conn, s["track"])) == 5
    send = _send_fn({("track", 3): [dict(d) for d in _LIVE_GUITAR_CHAIN]})
    result = push_execute.execute_push(
        conn=conn, song_id=s["song"], session_id=s["session"],
        state_dir=state_dir, send_fn=send, only="devices",
    )
    assert result.outcome == "ok"
    assert _loads(send) == []
    assert len(send.chains[("track", 3)]) == 5


def test_push_with_a_trailing_analyzer_appends_nothing(conn, state_dir):
    """A rendered set carries the HallucinoteAnalyzer at the END of every chain.
    It must not shift the authored positions out of alignment and trigger
    re-loads."""
    s = _guitar_song(conn, link_devices=False)
    live = [dict(d) for d in _LIVE_GUITAR_CHAIN] + [dict(ANALYZER, device_index=6)]
    send = _send_fn({("track", 3): live})
    result = push_execute.execute_push(
        conn=conn, song_id=s["song"], session_id=s["session"],
        state_dir=state_dir, send_fn=send, only="devices",
    )
    assert result.outcome == "ok"
    assert _loads(send) == []
    assert len(send.chains[("track", 3)]) == 6  # the analyzer, untouched


def test_push_still_loads_a_genuinely_missing_device(conn, state_dir):
    """The guard must not turn into a refusal to ever load: a position Live's
    chain does not reach is genuinely absent, and appending there is correct."""
    s = _guitar_song(conn, link_devices=False)
    send = _send_fn({("track", 3): [dict(d) for d in _LIVE_GUITAR_CHAIN[:3]]})
    result = push_execute.execute_push(
        conn=conn, song_id=s["song"], session_id=s["session"],
        state_dir=state_dir, send_fn=send, only="devices",
    )
    assert result.outcome == "ok"
    loaded = [c["params"]["kind"] for c in _loads(send)]
    assert loaded == ["Cabinet", "Saturator"]


def test_push_refuses_rather_than_doubling_an_unmatchable_chain(
    conn, state_dir,
):
    """Live's slot 2 holds a device the DB can't match. Loading would append a
    second Overdrive AND leave the mismatch in place; refusing names the track
    and what was seen."""
    s = _guitar_song(conn, link_devices=False)
    drifted = [dict(d) for d in _LIVE_GUITAR_CHAIN]
    drifted[1]["class_display_name"] = "Phaser"
    drifted[1]["name"] = "Phaser"
    send = _send_fn({("track", 3): drifted})
    result = push_execute.execute_push(
        conn=conn, song_id=s["song"], session_id=s["session"],
        state_dir=state_dir, send_fn=send, only="devices",
    )
    assert result.outcome == "partial"
    assert result.phase_halted == "devices"
    assert _loads(send) == []          # refused BEFORE dispatch
    assert len(send.chains[("track", 3)]) == 5
    errors = (state_dir / ".last-push-errors.json").read_text()
    assert "REFUSING to load" in errors
    assert "Rhythm Gtr" in errors      # names the track ...
    assert "Phaser" in errors          # ... and what it saw


def test_push_refuses_when_a_parents_chain_cannot_be_read(conn, state_dir):
    """A failed probe is ignorance, not absence. Appending on a guess would
    double the chain if the guess is wrong."""
    s = _guitar_song(conn, link_devices=False)
    send = _send_fn({("track", 3): None})
    result = push_execute.execute_push(
        conn=conn, song_id=s["song"], session_id=s["session"],
        state_dir=state_dir, send_fn=send, only="devices",
    )
    assert result.outcome == "partial"
    assert result.phase_halted == "devices"
    assert _loads(send) == []
    errors = (state_dir / ".last-push-errors.json").read_text()
    assert "could not be read" in errors


def test_integrity_assert_halts_on_an_already_doubled_set(conn, state_dir):
    """The backstop. Every device is linked (so the phase has nothing to do),
    but Live carries a doubled chain — the state the 2026-08-08 push left
    behind. "Skipped (nothing to push)" must not read as OK over that."""
    s = _guitar_song(conn, link_devices=True)
    doubled = [dict(d) for d in _LIVE_GUITAR_CHAIN] + [
        {"device_index": 6, "name": "Overdrive",
         "class_display_name": "Overdrive"},
        {"device_index": 7, "name": "Heavy", "class_display_name": "Amp"},
    ]
    send = _send_fn({("track", 3): doubled})
    result = push_execute.execute_push(
        conn=conn, song_id=s["song"], session_id=s["session"],
        state_dir=state_dir, send_fn=send, only="devices",
    )
    assert result.outcome == "partial"
    assert result.phase_halted == "devices"
    errors = (state_dir / ".last-push-errors.json").read_text()
    assert "DUPLICATE" in errors
    assert "Rhythm Gtr" in errors


def test_integrity_assert_tolerates_an_unauthored_extra_device(
    conn, state_dir,
):
    """A device the DB never authored is the composer's; it surfaces as a
    warning, and the push still completes."""
    s = _guitar_song(conn, link_devices=True)
    live = [dict(d) for d in _LIVE_GUITAR_CHAIN] + [
        {"device_index": 6, "name": "Utility", "class_display_name": "Utility"},
    ]
    send = _send_fn({("track", 3): live})
    result = push_execute.execute_push(
        conn=conn, song_id=s["song"], session_id=s["session"],
        state_dir=state_dir, send_fn=send, only="devices",
    )
    assert result.outcome == "ok"
    assert any("devices integrity" in w for w in result.warnings)


# ---------------------------------------------------------------------------
# verify_device_chains — the report's own contract
# ---------------------------------------------------------------------------


def test_verify_reports_probe_failure_without_claiming_anything(conn):
    s = _guitar_song(conn, link_devices=True)
    report = verify_device_chains(
        conn, song_id=s["song"], session_id=s["session"],
        probe_fn=lambda kind, idx: None,
    )
    assert [r.status for r in report.results] == [CHAIN_PROBE_FAILED]
    assert report.has_corruption() is False


def test_assert_raises_and_carries_the_report(conn):
    s = _guitar_song(conn, link_devices=True)
    doubled = [d["class_display_name"] for d in _LIVE_GUITAR_CHAIN]

    def probe_fn(kind, idx):
        return [
            {"device_index": i + 1, "name": c, "class_display_name": c}
            for i, c in enumerate(doubled + doubled[1:])
        ]

    with pytest.raises(DeviceChainIntegrityError) as exc:
        assert_device_chains_materialized(
            conn, song_id=s["song"], session_id=s["session"], probe_fn=probe_fn,
        )
    assert exc.value.report.duplicated()
    assert "Rhythm Gtr" in str(exc.value)
