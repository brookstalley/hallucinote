"""Cross-cut test: planner-emitted session-domain shape passes dispatcher validation.

Wave M-1 retargeted `set_master_volume` / `set_master_panning` from narrow tool
names to `ableton_session(action='set_master_property', ...)`. This test
verifies the contract: the planner's ToolCall args, fed verbatim into the
hallucinote-mcp dispatcher's request shape, validate cleanly. Catches drift
between the Hallucinote-side emitter and the MCP-side action schema.
"""
from __future__ import annotations

import pytest

from hallucinote.db import mutations as M
from hallucinote.db.connection import init_db
from hallucinote.sync import push


@pytest.fixture()
def conn(tmp_path):
    db = tmp_path / "shape.db"
    c = init_db(db)
    yield c
    c.close()


@pytest.fixture()
def setup_master(conn):
    sid = M.create_song(conn, name="m1-shape-test", title="M-1 shape test")
    mid = M.create_track(conn, song_id=sid, track_index=0, name="Master", kind="master")
    M.set_track_mixer(conn, track_id=mid, volume=0.72, pan=-0.3)
    sess = M.create_ableton_session(conn, song_id=sid, name="test")
    return sid, mid, sess


def test_planner_master_emit_validates_against_dispatcher(setup_master, conn):
    """Planner-emitted args, fed to the dispatcher as a Request, must validate.

    Imports the hallucinote_mcp dispatcher and exercises it with a real fake
    LiveContext. If a future schema change rejects the planner's shape, this
    test fails immediately — catching cross-package drift at the planner
    boundary.
    """
    from hallucinote_mcp.dispatcher import dispatch
    from hallucinote_mcp.testing import isolated_actions
    from hallucinote_mcp.wire import Request

    class _FakeMaster:
        def __init__(self):
            self.mixer_device = type(
                "M", (), {
                    "volume": type("P", (), {"value": 0.0})(),
                    "panning": type("P", (), {"value": 0.0})(),
                }
            )()
            self.mute = False

    class _FakeSong:
        def __init__(self):
            self.master_track = _FakeMaster()

    class _FakeCtx:
        def __init__(self):
            self._song = _FakeSong()
        @property
        def song(self): return self._song
        def run_on_main(self, fn): return fn()

    with isolated_actions():
        sid, _mid, sess = setup_master
        plan = push.plan_push_mix(conn, song_id=sid, session_id=sess)
        master_calls = [
            c for c in plan.calls
            if c.tool == "ableton_session"
            and c.args.get("action") == "set_master_property"
        ]
        assert master_calls, "planner did not emit ableton_session(set_master_property)"

        ctx = _FakeCtx()
        for call in master_calls:
            args = dict(call.args)
            action_name = args.pop("action")
            resp = dispatch(
                Request(tool=call.tool, action=action_name, params=args),
                context=ctx,
            )
            assert resp.ok, (
                f"planner-emitted call rejected by dispatcher: {resp.error!r}"
            )
        assert ctx.song.master_track.mixer_device.volume.value == pytest.approx(0.72)
        assert ctx.song.master_track.mixer_device.panning.value == pytest.approx(-0.3)
