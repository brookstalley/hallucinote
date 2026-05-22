"""Tests for the chunk-3 push planner: plan_push_mix and return-link apply."""
from __future__ import annotations

import pytest

from hallucinote.db import init_db, mutations as M
from hallucinote.sync import push


@pytest.fixture
def conn(tmp_path):
    c = init_db(tmp_path / "pmix.db")
    yield c
    c.close()


@pytest.fixture
def song(conn):
    return M.create_song(conn, name="t", key="Dm")


@pytest.fixture
def session(conn, song):
    return M.create_ableton_session(conn, song_id=song, name="draft")


def _calls_by_tool(plan) -> dict[str, list]:
    out: dict[str, list] = {}
    for c in plan.calls:
        out.setdefault(c.tool, []).append(c)
    return out


def test_plan_push_mix_skips_unlinked_tracks(conn, song, session):
    tid = M.create_track(conn, song_id=song, track_index=1, name="Drums")
    M.set_track_mixer(conn, track_id=tid, volume=0.6, pan=-0.25)
    plan = push.plan_push_mix(conn, song_id=song, session_id=session)
    assert _calls_by_tool(plan) == {}
    assert any("not linked" in n for n in plan.notes)


def _set_property_calls(plan, expected_property):
    """Helper — returns track set_property calls matching a given property name."""
    return [
        c for c in plan.calls
        if c.tool == "ableton_track"
        and c.args.get("action") == "set_property"
        and c.args.get("property") == expected_property
    ]


def test_plan_push_mix_emits_volume_and_pan_for_linked_tracks(conn, song, session):
    """Wave M-2: all mixer fields go through one unified
    ableton_track(action='set_property', ...) emitter."""
    tid = M.create_track(conn, song_id=song, track_index=1, name="Drums")
    M.set_track_mixer(conn, track_id=tid, volume=0.6, pan=-0.25)
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="track", db_id=tid, ableton_index=5
    )
    plan = push.plan_push_mix(conn, song_id=song, session_id=session)
    vol_calls = _set_property_calls(plan, "volume")
    pan_calls = _set_property_calls(plan, "panning")
    assert len(vol_calls) == 1
    assert len(pan_calls) == 1
    assert vol_calls[0].args == {
        "action": "set_property",
        "track_index": 5,
        "property": "volume",
        "value": 0.6,
    }
    assert pan_calls[0].args == {
        "action": "set_property",
        "track_index": 5,
        "property": "panning",
        "value": -0.25,
    }


def test_plan_push_mix_skips_volume_when_none(conn, song, session):
    tid = M.create_track(conn, song_id=song, track_index=1, name="Drums")
    M.set_track_mixer(conn, track_id=tid, pan=0.0)  # volume left null
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="track", db_id=tid, ableton_index=5
    )
    plan = push.plan_push_mix(conn, song_id=song, session_id=session)
    assert _set_property_calls(plan, "volume") == []
    assert len(_set_property_calls(plan, "panning")) == 1


def test_plan_push_mix_emits_all_mixer_properties_via_unified_tool(conn, song, session):
    """M-2 closed the mute/solo/arm/color MCP gap — they're now direct, not aliased."""
    tid = M.create_track(conn, song_id=song, track_index=1, name="Drums")
    M.set_track_mixer(conn, track_id=tid, mute=1, solo=0, arm=1, color=0xFF00FF)
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="track", db_id=tid, ableton_index=5
    )
    plan = push.plan_push_mix(conn, song_id=song, session_id=session)
    for prop in ("mute", "solo", "arm", "color"):
        calls = _set_property_calls(plan, prop)
        assert len(calls) == 1, f"missing unified set_property call for {prop!r}"
        # Every call uses the same shape — that's the consolidation win.
        assert calls[0].tool == "ableton_track"
        assert calls[0].args["action"] == "set_property"


def test_plan_push_mix_master_uses_master_strip_tools(conn, song, session):
    mid = M.create_track(
        conn, song_id=song, track_index=0, name="Master", kind="master"
    )
    M.set_track_mixer(conn, track_id=mid, volume=0.85, pan=0.0)
    plan = push.plan_push_mix(conn, song_id=song, session_id=session)
    # Master is reached via the unified ableton_session tool (M-1 retarget):
    # ableton_session(action='set_master_property', property=..., value=...).
    # No track_index — master is implicit.
    session_calls = [c for c in plan.calls if c.tool == "ableton_session"]
    master_props = [
        c for c in session_calls
        if c.args.get("action") == "set_master_property"
    ]
    assert {c.args["property"] for c in master_props} == {"volume", "panning"}
    vol_call = next(c for c in master_props if c.args["property"] == "volume")
    assert vol_call.args["value"] == 0.85
    assert "track_index" not in vol_call.args


def test_plan_push_mix_emits_create_return_track_when_unlinked(conn, song, session):
    """Wave M-2: return creation is now ableton_return(action='create', name=...)."""
    M.create_return(conn, song_id=song, name="A-Reverb", position=1)
    plan = push.plan_push_mix(conn, song_id=song, session_id=session)
    create_calls = [
        c for c in plan.calls
        if c.tool == "ableton_return" and c.args.get("action") == "create"
    ]
    assert len(create_calls) == 1
    # Arc 7 / P7: M.create_return strips the slot prefix, so DB stores
    # "Reverb"; push re-emits the stripped form and Live re-adds "A-"
    # (W4-C cross-layer contract).
    assert create_calls[0].args == {"action": "create", "name": "Reverb"}


def test_plan_push_mix_emits_return_set_property_for_linked_returns(conn, song, session):
    """Wave M-2: when a return is already linked, the planner emits
    ableton_return(action='set_property', ...) per non-null mixer field
    (not create + property — we don't recreate the return on every push).
    """
    rid = M.create_return(conn, song_id=song, name="A-Reverb", position=1)
    M.update_return(conn, return_id=rid, volume=0.6, pan=0.0)
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="return", db_id=rid, ableton_index=1
    )
    plan = push.plan_push_mix(conn, song_id=song, session_id=session)
    return_calls = [c for c in plan.calls if c.tool == "ableton_return"]
    # No create call — return is already linked.
    assert all(c.args.get("action") != "create" for c in return_calls)
    # One set_property per non-null mixer field on the return.
    set_props = [c for c in return_calls if c.args.get("action") == "set_property"]
    # mute/solo were not set on this return -> nullable schema -> not emitted.
    assert {c.args["property"] for c in set_props} == {"volume", "panning"}
    vol = next(c for c in set_props if c.args["property"] == "volume")
    assert vol.args == {
        "action": "set_property",
        "return_index": 1,
        "property": "volume",
        "value": 0.6,
    }


def test_plan_push_mix_emits_return_mute_solo_when_set(conn, song, session):
    """M+1-4: once mute/solo are set on a return, the planner emits a
    set_property call per field with the canonical `return_mute:<id>` /
    `return_solo:<id>` key (matches the `track_*` parity surfaced in
    `_ACK_ONLY_KINDS`)."""
    rid = M.create_return(conn, song_id=song, name="A-Reverb", position=1)
    M.update_return(conn, return_id=rid, mute=1, solo=0)
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="return", db_id=rid, ableton_index=1
    )
    plan = push.plan_push_mix(conn, song_id=song, session_id=session)
    set_props = [
        c for c in plan.calls
        if c.tool == "ableton_return"
        and c.args.get("action") == "set_property"
    ]
    by_prop = {c.args["property"]: c for c in set_props}
    assert "mute" in by_prop and by_prop["mute"].args["value"] == 1
    assert "solo" in by_prop and by_prop["solo"].args["value"] == 0
    assert by_prop["mute"].key == f"return_mute:{rid}"
    assert by_prop["solo"].key == f"return_solo:{rid}"


def test_apply_push_results_accepts_return_mute_and_solo_acks(
    conn, song, session
):
    """M+1-4: `return_mute` and `return_solo` are ack-only kinds —
    `apply_push_results` accepts them without raising
    (no `ableton_links` binding to record; DB-side state is already
    correct as the push originated from DB)."""
    rid = M.create_return(conn, song_id=song, name="A-Reverb", position=1)
    M.update_return(conn, return_id=rid, mute=1, solo=0)
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="return", db_id=rid, ableton_index=1
    )
    # Should not raise — verifies `return_mute` / `return_solo` membership
    # in `_ACK_ONLY_KINDS`.
    push.apply_push_results(
        conn,
        [
            {"key": f"return_mute:{rid}", "ok": True,
             "tool": "ableton_return", "result": {"value": 1}},
            {"key": f"return_solo:{rid}", "ok": True,
             "tool": "ableton_return", "result": {"value": 0}},
        ],
        session_id=session,
    )
    # DB state unchanged (ack-only does not re-write).
    from hallucinote.db import queries as Q
    row = Q.get_return(conn, rid)
    assert row["mute"] == 1
    assert row["solo"] == 0


def test_plan_push_mix_sends_require_both_links(conn, song, session):
    """Wave M-2: send writes are ableton_track(action='set_send', ...)."""
    tid = M.create_track(conn, song_id=song, track_index=1, name="Drums")
    rid = M.create_return(conn, song_id=song, name="A-Reverb", position=1)
    M.set_send_level(conn, from_track_id=tid, to_return_id=rid, level=0.4)

    def _send_calls(plan):
        return [
            c for c in plan.calls
            if c.tool == "ableton_track" and c.args.get("action") == "set_send"
        ]

    # Neither linked — skipped with warning.
    plan = push.plan_push_mix(conn, song_id=song, session_id=session)
    assert _send_calls(plan) == []
    assert any("missing link" in n for n in plan.notes)

    # Link both — call emitted.
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="track", db_id=tid, ableton_index=5
    )
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="return", db_id=rid, ableton_index=1
    )
    plan = push.plan_push_mix(conn, song_id=song, session_id=session)
    calls = _send_calls(plan)
    assert len(calls) == 1
    assert calls[0].args == {
        "action": "set_send",
        "track_index": 5,
        "return_index": 1,
        "value": 0.4,
    }


def test_apply_push_results_links_returns(conn, song, session):
    rid = M.create_return(conn, song_id=song, name="A-Reverb", position=1)
    push.apply_push_results(
        conn,
        [
            {"key": f"return:{rid}", "ok": True, "tool": "create_return_track",
             "result": {"return_index": 1}},
        ],
        session_id=session,
    )
    from hallucinote.db import queries as Q
    linked = Q.get_ableton_link(
        conn, session_id=session, db_kind="return", db_id=rid
    )
    assert linked == 1


def test_apply_push_results_accepts_chunk3_keys_as_acks(conn, song, session):
    """Chunk-3 mixer/send keys are recognized acks: no raise, no link written.

    `plan_push_mix` emits keys like `track_volume:`, `track_pan:`, `send:`,
    `master_volume:` — none of these record an `ableton_links` binding (the
    bindings come from the prior `track:` / `return:` creates). The dispatch
    table in `apply_push_results` declares them as ack-only; this test pins
    that contract.
    """
    tid = M.create_track(conn, song_id=song, track_index=1, name="Drums")
    M.set_track_mixer(conn, track_id=tid, volume=0.5)
    M.link_db_to_ableton(
        conn, session_id=session, db_kind="track", db_id=tid, ableton_index=5
    )
    push.apply_push_results(
        conn,
        [
            {"key": f"track_volume:{tid}", "ok": True, "tool": "set_track_volume",
             "result": {}},
            {"key": f"track_pan:{tid}", "ok": True, "tool": "set_track_panning",
             "result": {}},
            {"key": f"track_mute:{tid}", "ok": True, "tool": "set_track_mute",
             "result": {}},
            {"key": f"track_solo:{tid}", "ok": True, "tool": "set_track_solo",
             "result": {}},
            {"key": f"track_arm:{tid}", "ok": True, "tool": "set_track_arm",
             "result": {}},
            {"key": f"track_color:{tid}", "ok": True, "tool": "set_track_color",
             "result": {}},
            {"key": f"send:{tid}:fake_return_uuid_for_test", "ok": True,
             "tool": "set_track_send", "result": {}},
            {"key": f"master_volume:{tid}", "ok": True, "tool": "ableton_session",
             "result": {}},
            {"key": f"master_pan:{tid}", "ok": True, "tool": "ableton_session",
             "result": {}},
            # Wave M-2: return mixer ack-only keys. Only volume / pan / color
            # are live today — the DB's returns table has no mute / solo
            # columns yet (backlog item: "Return-track mute/solo round-trip").
            {"key": f"return_volume:fake_rid", "ok": True, "tool": "ableton_return",
             "result": {}},
            {"key": f"return_pan:fake_rid", "ok": True, "tool": "ableton_return",
             "result": {}},
            {"key": f"return_color:fake_rid", "ok": True, "tool": "ableton_return",
             "result": {}},
        ],
        session_id=session,
    )
    # No new links materialized — only the original track link survives.
    from hallucinote.db import queries as Q
    links = Q.get_ableton_links_for_session(conn, session)
    assert len(links) == 1
    assert links[0]["db_kind"] == "track"


def test_apply_push_results_raises_on_unknown_kind(conn, song, session):
    """Dispatch contract: a key kind not in `_LINK_KINDS` or `_ACK_ONLY_KINDS`
    must raise rather than silently no-op. This forces a future planner that
    grows a new key kind to declare its resolution at the apply layer.
    """
    tid = M.create_track(conn, song_id=song, track_index=1, name="Drums")
    with pytest.raises(ValueError, match="unknown push result key kind"):
        push.apply_push_results(
            conn,
            [
                {"key": f"device_param:{tid}", "ok": True,
                 "tool": "set_device_parameter", "result": {}},
            ],
            session_id=session,
        )


def test_apply_push_results_raises_on_missing_key(conn, session):
    with pytest.raises(ValueError, match="missing 'key'"):
        push.apply_push_results(
            conn,
            [{"ok": True, "tool": "set_track_volume", "result": {}}],
            session_id=session,
        )


def test_plan_push_mix_empty_song_warns(conn, song, session):
    plan = push.plan_push_mix(conn, song_id=song, session_id=session)
    assert plan.calls == []
    assert any("no mix state" in n for n in plan.notes)


# Song-specific shape tests (falling-walking snapshot end-to-end) live at
# `songs/falling-walking/tests/test_push_mix_snapshot.py`. This file holds only
# platform-level planner tests that use synthetic fixtures.
