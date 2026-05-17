"""Cross-cut test: planner-emitted shape passes dispatcher validation.

Wave M-1 retargeted master mixer state to `ableton_session(action='set_master_property', ...)`.
Wave M-2 added per-track mixer state via `ableton_track(action='set_property', ...)`,
return mixer state via `ableton_return(action='set_property', ...)`, sends via
`ableton_track(action='set_send', ...)`, and return creation via
`ableton_return(action='create', ...)`.

This test verifies the contract: the planner's ToolCall args, fed verbatim into
the hallucinote-mcp dispatcher's request shape, validate cleanly. Catches
drift between the Hallucinote-side emitter and the MCP-side action schema.
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


def test_planner_track_and_return_emits_validate_against_dispatcher(conn):
    """Wave M-2: track mixer properties, return create, return mixer, and sends
    all flow through ableton_track / ableton_return action schemas.
    """
    from hallucinote_mcp.dispatcher import dispatch
    from hallucinote_mcp.testing import isolated_actions
    from hallucinote_mcp.wire import Request

    # Set up a song with a linked track + an unlinked return that should
    # trigger the create-return emit + a linked return for the property writes.
    sid = M.create_song(conn, name="m2-shape-test", title="M-2 shape test")
    sess = M.create_ableton_session(conn, song_id=sid, name="test")
    tid = M.create_track(conn, song_id=sid, track_index=1, name="Drums")
    M.set_track_mixer(
        conn, track_id=tid, volume=0.6, pan=-0.2,
        mute=0, solo=0, arm=0, color=12,
    )
    M.link_db_to_ableton(
        conn, session_id=sess, db_kind="track", db_id=tid, ableton_index=1
    )
    rid = M.create_return(conn, song_id=sid, name="A-Reverb", position=1)
    # First pass: return is unlinked → planner emits create.
    plan = push.plan_push_mix(conn, song_id=sid, session_id=sess)
    track_property_calls = [
        c for c in plan.calls
        if c.tool == "ableton_track"
        and c.args.get("action") == "set_property"
    ]
    create_return_calls = [
        c for c in plan.calls
        if c.tool == "ableton_return"
        and c.args.get("action") == "create"
    ]
    # All 6 properties (volume, panning, mute, solo, arm, color) emitted.
    assert {c.args["property"] for c in track_property_calls} == {
        "volume", "panning", "mute", "solo", "arm", "color"
    }
    assert len(create_return_calls) == 1
    assert create_return_calls[0].args == {"action": "create", "name": "A-Reverb"}

    # Build a fake song with one track + one return slot so the dispatcher
    # can actually execute the planner's calls.
    class _Param:
        def __init__(self, value=0.0): self.value = value

    class _Send:
        def __init__(self, value=0.0): self.value = value

    class _Mixer:
        def __init__(self):
            self.volume = _Param()
            self.panning = _Param()
            self.sends = [_Send()]

    class _Track:
        def __init__(self, name="Drums"):
            self.name = name
            self.mixer_device = _Mixer()
            self.mute = False
            self.solo = False
            self.arm = False
            self.color = 0
            self.has_midi_input = True
            self.has_audio_input = False
            self.is_foldable = False
            self.is_grouped = False

    class _Return:
        def __init__(self, name="A-Reverb"):
            self.name = name
            self.mixer_device = _Mixer()
            self.mute = False
            self.solo = False
            self.color = 0

    class _Song:
        def __init__(self):
            self.tracks = [_Track()]
            self.return_tracks = [_Return()]

        def create_return_track(self):
            new = _Return(name="New")
            self.return_tracks.append(new)
            return new

    class _Ctx:
        def __init__(self):
            self._song = _Song()
        @property
        def song(self): return self._song
        def run_on_main(self, fn): return fn()

    with isolated_actions():
        ctx = _Ctx()
        for call in plan.calls:
            args = dict(call.args)
            action_name = args.pop("action")
            resp = dispatch(
                Request(tool=call.tool, action=action_name, params=args),
                context=ctx,
            )
            assert resp.ok, (
                f"planner-emitted call rejected by dispatcher: "
                f"tool={call.tool}, action={action_name}, args={args}, err={resp.error!r}"
            )
        # Round-trip values landed on the fake.
        track = ctx.song.tracks[0]
        assert track.mixer_device.volume.value == pytest.approx(0.6)
        assert track.mixer_device.panning.value == pytest.approx(-0.2)
        assert track.color == 12


def test_planner_replace_notes_emit_validates_against_dispatcher(conn):
    """Wave M-3: in-place clip note replace flows through
    ableton_clip(action='replace_notes', ...). Verifies the planner's shape
    is what the unified dispatcher accepts.
    """
    from hallucinote_mcp.dispatcher import dispatch
    from hallucinote_mcp.testing import isolated_actions
    from hallucinote_mcp.wire import Request

    sid = M.create_song(conn, name="m3-shape-test", title="M-3 shape test")
    sess = M.create_ableton_session(conn, song_id=sid, name="test")
    tid = M.create_track(conn, song_id=sid, track_index=1, name="Drums")
    cid = M.create_clip(conn, track_id=tid, slot=1, name="Pattern", length_beats=16.0)
    M.replace_clip_notes(
        conn, clip_id=cid,
        notes=[{
            "pitch": 60, "start_beats": 0.0, "duration_beats": 1.0,
            "velocity": 100,
        }],
    )
    M.link_db_to_ableton(
        conn, session_id=sess, db_kind="track", db_id=tid, ableton_index=2
    )
    M.link_db_to_ableton(
        conn, session_id=sess, db_kind="clip", db_id=cid, ableton_index=1
    )
    plan = push.plan_push_clip(conn, clip_id=cid, session_id=sess)
    replace_calls = [
        c for c in plan.calls
        if c.tool == "ableton_clip" and c.args.get("action") == "replace_notes"
    ]
    assert len(replace_calls) == 1, (
        f"planner did not emit ableton_clip(replace_notes): {plan.calls!r}"
    )

    # Build a fake song with a single MIDI clip on track 2, slot 1.
    class _Clip:
        def __init__(self):
            self.notes: tuple = ()
            self.name = "Pattern"
            self.length = 16.0
            self.loop_start = 0.0
            self.loop_end = 16.0
            self.muted = False
            self.color = 0
        def set_notes(self, n): self.notes = tuple(n)

    class _Slot:
        def __init__(self, clip=None): self.clip = clip

    class _Track:
        def __init__(self):
            self.clip_slots = [_Slot(_Clip())]
            self.arrangement_clips = []

    class _Song:
        def __init__(self):
            self.tracks = [_Track(), _Track()]  # index 2 = second track

    class _Ctx:
        def __init__(self): self._song = _Song()
        @property
        def song(self): return self._song
        def run_on_main(self, fn): return fn()

    with isolated_actions():
        ctx = _Ctx()
        for call in replace_calls:
            args = dict(call.args)
            action_name = args.pop("action")
            resp = dispatch(
                Request(tool=call.tool, action=action_name, params=args),
                context=ctx,
            )
            assert resp.ok, (
                f"planner-emitted call rejected by dispatcher: "
                f"action={action_name}, args={args}, err={resp.error!r}"
            )
        # The notes round-tripped.
        clip = ctx.song.tracks[1].clip_slots[0].clip
        assert len(clip.notes) == 1
        assert clip.notes[0][0] == 60  # pitch
