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
    M.create_return(conn, song_id=sid, name="A-Reverb", position=1)
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
    # Arc 7 / P7: M.create_return strips the slot prefix → DB stores
    # "Reverb"; push re-emits it stripped, Live re-adds "A-".
    assert create_return_calls[0].args == {"action": "create", "name": "Reverb"}

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


def test_planner_track_create_emit_validates_against_dispatcher(conn):
    """W3-C: track creation moved out of plan_push_clip into the
    song-level pre-pass plan_push_song_tracks. Pipe its emit through the
    actual dispatcher against a fake context to lock the cross-package
    wire contract for the new pre-pass shape.
    """
    from hallucinote_mcp.dispatcher import dispatch
    from hallucinote_mcp.testing import isolated_actions
    from hallucinote_mcp.wire import Request

    sid = M.create_song(conn, name="m5-track-create-shape", title="M-5 track create")
    sess = M.create_ableton_session(conn, song_id=sid, name="test")
    M.create_track(
        conn, song_id=sid, track_index=1, name="Lead",
        instrument_uri="query:Operator#FileId_99",
    )
    # The track is intentionally NOT linked — plan_push_song_tracks should
    # emit the create call.
    plan = push.plan_push_song_tracks(conn, song_id=sid, session_id=sess)
    create_calls = [
        c for c in plan.calls
        if c.tool == "ableton_track" and c.args.get("action") == "create"
    ]
    assert len(create_calls) == 1, (
        f"plan_push_song_tracks did not emit ableton_track(create): {plan.calls!r}"
    )
    call = create_calls[0]
    assert call.args["kind"] == "midi"
    assert call.args["name"] == "Lead"
    assert call.args["instrument_uri"] == "query:Operator#FileId_99"

    # Fake song with no tracks yet.
    class _NewTrack:
        def __init__(self):
            self.name = ""
            self.mixer_device = type("M", (), {
                "volume": type("P", (), {"value": 0.85})(),
                "panning": type("P", (), {"value": 0.0})(),
                "sends": [],
            })()
            self.mute = False
            self.solo = False
            self.arm = False
            self.color = None
            self.has_midi_input = True
            self.has_audio_input = False
            self.is_foldable = False
            self.is_grouped = False

    class _Song:
        def __init__(self):
            self.tracks: list = []
            self.return_tracks: list = []
        def create_midi_track(self, insert_at: int) -> _NewTrack:
            t = _NewTrack()
            if insert_at == -1:
                self.tracks.append(t)
            else:
                self.tracks.insert(insert_at, t)
            return t
        def create_audio_track(self, insert_at: int) -> _NewTrack:
            t = _NewTrack()
            t.has_midi_input = False
            t.has_audio_input = True
            if insert_at == -1:
                self.tracks.append(t)
            else:
                self.tracks.insert(insert_at, t)
            return t

    class _Ctx:
        def __init__(self): self._song = _Song()
        @property
        def song(self): return self._song
        def run_on_main(self, fn): return fn()

    with isolated_actions():
        ctx = _Ctx()
        args = dict(call.args)
        action_name = args.pop("action")
        resp = dispatch(
            Request(tool=call.tool, action=action_name, params=args),
            context=ctx,
        )
        assert resp.ok, (
            f"track create call rejected by dispatcher: "
            f"args={args}, err={resp.error!r}"
        )
        assert resp.result["track_index"] == 1
        assert resp.result["kind"] == "midi"
        assert resp.result["name"] == "Lead"
        # instrument_uri round-trips as deferred (M-2 behavior preserved).
        assert resp.result.get("instrument_uri_deferred") == "query:Operator#FileId_99"


def test_planner_cue_list_pull_validates_against_dispatcher(conn):
    """Wave M-5: cue-points pull flows through ableton_arrangement(action='cue_list').
    Pipe the pull plan through the actual dispatcher against a fake context
    and confirm the shape is accepted end-to-end.
    """
    from hallucinote_mcp.dispatcher import dispatch
    from hallucinote_mcp.testing import isolated_actions
    from hallucinote_mcp.wire import Request
    from hallucinote.sync import pull

    sid = M.create_song(conn, name="m5-cue-shape", title="M-5 cue shape")
    sess = M.create_ableton_session(conn, song_id=sid, name="test")
    plan = pull.plan_pull_cue_points(conn, song_id=sid, session_id=sess)
    assert len(plan.calls) == 1
    call = plan.calls[0]
    assert call.tool == "ableton_arrangement"
    assert call.args == {"action": "cue_list"}

    # Fake context that returns a cue list shape matching the handler.
    class _Cue:
        def __init__(self, time, name):
            self.time = time
            self.name = name

    class _Song:
        def __init__(self):
            self.cue_points = (
                _Cue(0.0, "Intro"),
                _Cue(16.0, "Verse"),
                _Cue(32.0, "Chorus"),
            )

    class _Ctx:
        def __init__(self): self._song = _Song()
        @property
        def song(self): return self._song
        def run_on_main(self, fn): return fn()

    with isolated_actions():
        ctx = _Ctx()
        action_name = call.args["action"]
        resp = dispatch(
            Request(tool=call.tool, action=action_name),
            context=ctx,
        )
        assert resp.ok, resp.error
        cues = resp.result["cue_points"]
        assert len(cues) == 3
        # Names round-trip cleanly (legacy gap #13 doesn't apply in M-5+).
        names = [c["name"] for c in cues]
        assert names == ["Intro", "Verse", "Chorus"]


def test_planner_device_load_emit_validates_against_dispatcher(conn):
    """Wave M-4: device load flows through ableton_device(action='load')."""
    from hallucinote_mcp.dispatcher import dispatch
    from hallucinote_mcp.testing import isolated_actions
    from hallucinote_mcp.wire import Request

    sid = M.create_song(conn, name="m4-dev-shape", title="M-4 device shape")
    sess = M.create_ableton_session(conn, song_id=sid, name="test")
    tid = M.create_track(conn, song_id=sid, track_index=1, name="Drums")
    M.link_db_to_ableton(
        conn, session_id=sess, db_kind="track", db_id=tid, ableton_index=1
    )
    cid = M.create_device_chain(conn, parent_track_id=tid)
    M.create_device(conn, chain_id=cid, position=1, kind="Compressor", display_name="Comp")
    plan = push.plan_push_devices(conn, song_id=sid, session_id=sess)
    load_calls = [
        c for c in plan.calls
        if c.tool == "ableton_device" and c.args.get("action") == "load"
    ]
    assert len(load_calls) == 1

    class _Track:
        def __init__(self):
            self.devices = []
            self.mixer_device = type("M", (), {
                "volume": type("P", (), {"value": 0.5})(),
                "panning": type("P", (), {"value": 0.0})(),
                "sends": [],
            })()

    class _View:
        def __init__(self): self.selected_track = None

    class _Item:
        def __init__(self, name, uri):
            self.name = name
            self.uri = uri
            self.is_loadable = True
            self.is_folder = False
            self.children = ()

    class _Root:
        def __init__(self, name):
            self.name = name
            self.children = []
        is_loadable = False
        is_folder = True
        uri = ""

    class _Browser:
        def __init__(self, song):
            self._song = song
            self.instruments = _Root("Instruments")
            self.audio_effects = _Root("Audio Effects")
            self.midi_effects = _Root("MIDI Effects")
            self.drums = _Root("Drums")
            self.plugins = _Root("Plug-Ins")
            self.samples = _Root("Samples")
            self.user_library = _Root("User Library")
            self.packs = _Root("Packs")
            # Pre-populate with the Compressor browser node the planner is
            # about to load. Post-D4: kind sent by push is the browser display
            # name ('Compressor'), not the internal class ('Compressor2').
            self.audio_effects.children.append(
                _Item("Compressor", "query:Compressor")
            )

        def load_item(self, item):
            target = self._song.view.selected_track
            new_dev = type("D", (), {
                "name": item.name,
                "class_name": item.name,
                "is_active": True,
                "parameters": (),
                "can_have_chains": False,
            })()
            target.devices.append(new_dev)

    class _Application:
        def __init__(self, song): self.browser = _Browser(song)

    class _Song:
        def __init__(self):
            self.tracks = [_Track()]
            self.return_tracks = []
            self.view = _View()

    class _Ctx:
        def __init__(self):
            self._song = _Song()
            self._application = _Application(self._song)
        @property
        def song(self): return self._song
        @property
        def application(self): return self._application
        def run_on_main(self, fn): return fn()

    with isolated_actions():
        ctx = _Ctx()
        for call in load_calls:
            args = dict(call.args)
            action_name = args.pop("action")
            resp = dispatch(
                Request(tool=call.tool, action=action_name, params=args),
                context=ctx,
            )
            assert resp.ok, (
                f"device load call rejected: action={action_name}, "
                f"args={args}, err={resp.error!r}"
            )
        # The device landed on the (only) track.
        assert len(ctx.song.tracks[0].devices) == 1


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
            self.is_midi_clip = True
        def set_notes(self, n): self.notes = tuple(n)
        def get_notes_extended(self, fp, ps, ft, ts): return list(self.notes)
        def remove_notes_extended(self, fp, ps, ft, ts):
            # replace_notes now full-extent-clears before set_notes (ARR-ORPHAN).
            self.notes = tuple(
                x for x in self.notes
                if not (fp <= x[0] < fp + ps and ft <= x[1] < ft + ts)
            )

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
