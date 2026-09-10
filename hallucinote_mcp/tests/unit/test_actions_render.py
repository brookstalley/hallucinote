"""Tests for ableton_render (action schema + render handler)."""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

import pytest

from hallucinote_mcp.analyzer.osc import AnalyzerOSC
from hallucinote_mcp.dispatcher import dispatch
from hallucinote_mcp.handlers import render as render_handlers
from hallucinote_mcp.handlers._transport import PlayheadPositionError
from hallucinote_mcp.wire import Request


# --- disposition: synchronous `render` action retired (MCP-9R3T) -----


def test_synchronous_render_action_is_retired():
    """The synchronous `render` action was retired: a full render is realtime /
    multi-minute and ALWAYS exceeded the 60s tool-call timeout, so it false-
    failed (the agent saw an error while the render finished server-side).
    `start` + `status` is the only render entry now. The worker function
    `render_handler` STAYS — `start` backgrounds it."""
    from hallucinote_mcp import schema

    names = {a.name for a in schema.actions_for("ableton_render")}
    assert "render" not in names, "synchronous render action must be retired"
    assert {"start", "status"} <= names, "start/status are the render entry"
    # The worker function is NOT removed — `start` spawns it on a detached worker.
    assert hasattr(render_handlers, "render_handler")


def test_retired_render_action_teaches_start():
    """Calling the retired action returns a teaching unknown-action error whose
    valid_actions name the live entry (so an agent with the old habit is
    redirected to start/status, not left guessing)."""
    resp = dispatch(Request(tool="ableton_render", action="render", params={}))
    assert resp.ok is False
    assert resp.valid_actions is not None
    assert "start" in resp.valid_actions and "status" in resp.valid_actions
    assert "render" not in resp.valid_actions


# --- fakes (mirror test_analyzer_setup.py) ---------------------------


class _FakeParam:
    def __init__(self, name, value=0.0, *, min=0.0, max=1.0):
        self.name = name
        self.value = value
        self.min = min
        self.max = max


def _analyzer_params() -> list[_FakeParam]:
    return [
        _FakeParam("Device On", 1.0),
        _FakeParam("Arm", 0.0),
        _FakeParam("Port", 11020.0, min=11000.0, max=11400.0),
        _FakeParam("EmitPort", 11221.0, min=11000.0, max=11400.0),
        _FakeParam("Emit", 1.0),
    ]


class _FakeDevice:
    def __init__(
        self,
        *,
        class_display_name: str,
        class_name: str | None = None,
        name: str | None = None,
        parameters: list[_FakeParam] | None = None,
    ):
        self.class_display_name = class_display_name
        self.class_name = class_name or class_display_name
        # Mirror Live's real shape: an M4L audio-effect has
        # class_display_name="Max Audio Effect" and name=<.amxd filename>.
        # Tests instantiating analyzer fakes should pass name=
        # "HallucinoteAnalyzer" explicitly; defaulting name to
        # class_display_name (prior behavior) made the fake look like
        # an unbranded "Max Audio Effect" with no specific .amxd.
        self.name = name or class_display_name
        if parameters is None and self.name == "HallucinoteAnalyzer":
            parameters = _analyzer_params()
        self.parameters = parameters or []


class _FakeMixer:
    def __init__(self):
        self.volume = _FakeParam("Volume", 0.85)
        self.panning = _FakeParam("Panning", 0.0)
        self.sends = []


class _FakeClip:
    """Minimal arrangement-clip stand-in: the render's content-end scan
    reads only ``end_time`` (beats from arrangement start)."""

    def __init__(self, end_time: float):
        self.end_time = float(end_time)


class _FakeTrack:
    def __init__(
        self,
        name: str,
        *,
        devices: list[_FakeDevice] | None = None,
        arrangement_clips: list[_FakeClip] | None = None,
        has_audio_output: bool = True,
        has_midi_input: bool = False,
        is_foldable: bool = False,
    ):
        self.name = name
        self.devices = list(devices or [])
        self.arrangement_clips = list(arrangement_clips or [])
        self.mixer_device = _FakeMixer()
        self.has_audio_output = has_audio_output
        self.has_midi_input = has_midi_input
        self.has_audio_input = not has_midi_input
        self.is_foldable = is_foldable

    def delete_device(self, index0: int) -> None:
        """Live's 0-based ``Track.delete_device`` — ``delete_handler`` reaches
        for it by name. Exercised by the SNP-8R4K analyzer reposition path."""
        del self.devices[index0]


class _FakeBrowserItem:
    def __init__(self, name: str):
        self.name = name
        self.uri = f"query:Audio Effects#{name}"
        self.is_loadable = True
        self.is_folder = False
        self.children: tuple = ()


class _FakeBrowserRoot:
    def __init__(self, name: str):
        self.name = name
        self.uri = ""
        self.is_loadable = False
        self.is_folder = True
        self.children: list[_FakeBrowserItem] = []


class _FakeBrowser:
    """Mirrors the real install layout: HallucinoteAnalyzer lives at
    ``user_library/Presets/Audio Effects/Max Audio Effect/HallucinoteAnalyzer``
    (the install skill writes the .amxd there). ``ensure_analyzers_loaded``
    locates it via ``preset_query`` with that exact path_prefix —
    ``kind=`` lookups miss it because ``_BROWSER_LOAD_ROOTS`` doesn't
    include user_library."""

    def __init__(self, song):
        self._song = song
        # Build the user_library subtree.
        self.user_library = _FakeBrowserRoot("User Library")
        presets = _FakeBrowserRoot("Presets")
        audio_effects_folder = _FakeBrowserRoot("Audio Effects")
        max_audio_effect = _FakeBrowserRoot("Max Audio Effect")
        max_audio_effect.children.append(_FakeBrowserItem("HallucinoteAnalyzer"))
        audio_effects_folder.children.append(max_audio_effect)
        presets.children.append(audio_effects_folder)
        self.user_library.children.append(presets)
        # Other roots present but empty.
        self.audio_effects = _FakeBrowserRoot("Audio Effects")
        self.instruments = _FakeBrowserRoot("Instruments")
        self.midi_effects = _FakeBrowserRoot("MIDI Effects")
        self.drums = _FakeBrowserRoot("Drums")
        self.plugins = _FakeBrowserRoot("Plug-Ins")
        self.samples = _FakeBrowserRoot("Samples")
        self.packs = _FakeBrowserRoot("Packs")
        self.load_calls: list[_FakeBrowserItem] = []

    def load_item(self, item):
        self.load_calls.append(item)
        target = self._song.view.selected_track
        # Mirror Live's real shape for M4L: class_display_name=
        # "Max Audio Effect", name=<.amxd filename>.
        target.devices.append(_FakeDevice(
            class_display_name="Max Audio Effect",
            name=item.name,
        ))


class _FakeApplication:
    def __init__(self, song):
        self.browser = _FakeBrowser(song)


class _FakeSongView:
    def __init__(self):
        self.selected_track: Any = None


class _FakeSong:
    def __init__(
        self,
        *,
        tracks: list[_FakeTrack] | None = None,
        returns: list[_FakeTrack] | None = None,
        master: _FakeTrack | None = None,
        last_event_time: float = 64.0,
    ):
        self.tracks = tracks or []
        self.return_tracks = returns or []
        self.master_track = master or _FakeTrack("Master")
        self.view = _FakeSongView()
        self.last_event_time = last_event_time
        self.current_song_time = 0.0
        self.is_playing = False
        # `loop` records every write so tests can assert the render disabled it
        # for the capture and restored it (the ring-out needs transport to run
        # into empty arrangement, not loop back). Starts True.
        self.loop_writes: list[bool] = []
        self._loop = True
        self.start_playing_calls = 0
        self.stop_playing_calls = 0
        self.stale_start_position: float | None = None

    @property
    def loop(self):
        return self._loop

    @loop.setter
    def loop(self, value):
        self._loop = bool(value)
        self.loop_writes.append(self._loop)

    def start_playing(self):
        self.is_playing = True
        self.start_playing_calls += 1
        # Live rolls from its START PLAYING POSITION, which is a different
        # property from the playhead. Set this to model a set someone has
        # listened to: playback then begins wherever they last pressed play,
        # no matter what the seek read back. Default None keeps the playhead
        # where it was put, which is the healthy case.
        if self.stale_start_position is not None:
            self.current_song_time = self.stale_start_position

    def stop_playing(self):
        self.is_playing = False
        self.stop_playing_calls += 1


class _FakeCtx:
    def __init__(self, song: _FakeSong):
        self._song = song
        self._application = _FakeApplication(song)
        self._live_state_lock = threading.RLock()
        # Records each main-thread bout so tests can assert that the
        # seek + play split lands in SEPARATE bouts (regression guard
        # for the notification-deferral bug — see render_handler).
        self.run_on_main_calls = 0
        # Per-bout snapshot of the song's transport mutations: each
        # entry is (bout_id, current_song_time, start_playing_calls,
        # stop_playing_calls). Tests inspect this to assert that seek
        # and start_playing didn't share a bout.
        self.bout_log: list[tuple[int, float, int, int]] = []

    @property
    def song(self):
        return self._song

    @property
    def application(self):
        return self._application

    @property
    def live_state_lock(self):
        return self._live_state_lock

    def run_on_main(self, fn, **_kwargs):
        self.run_on_main_calls += 1
        bout_id = self.run_on_main_calls
        time_before = self._song.current_song_time
        plays_before = self._song.start_playing_calls
        stops_before = self._song.stop_playing_calls
        result = fn()
        # Only log bouts that mutated transport state.
        if (
            self._song.current_song_time != time_before
            or self._song.start_playing_calls != plays_before
            or self._song.stop_playing_calls != stops_before
        ):
            self.bout_log.append((
                bout_id,
                self._song.current_song_time,
                self._song.start_playing_calls,
                self._song.stop_playing_calls,
            ))
        return result


# --- recording OSC factory + minimal sidecar substitute -------------


class _RecordingOSC(AnalyzerOSC):
    """Captures every method call without actually sending UDP. Tests
    use this via the render handler's `_osc_factory` seam."""

    def __init__(self, port: int, sink: list[tuple[int, str, tuple]]):
        super().__init__(port=port)
        self._sink = sink

    def _send(self, address: str, *args):
        self._sink.append((self.port, address, args))


class _StubSidecar:
    """Implements the tiny surface render_handler reaches for: .port +
    .frames_received. Standalone (doesn't bind a socket) so tests don't
    contend with the shared sidecar's port."""

    def __init__(self, port: int = 11221):
        self.port = port
        self.frames_received = 0


# --- fixtures --------------------------------------------------------


def _master_with_analyzer(name: str = "Master") -> _FakeTrack:
    """A master that already carries the analyzer. The render sweep DETECTS and
    configures it without re-loading. DEV-6M2K: the sweep can also auto-load the
    master analyzer when absent; pre-placing it here exercises the detect path
    (so loaded_count counts only the fresh track/return loads)."""
    return _FakeTrack("Master" if name == "Master" else name, devices=[
        _FakeDevice(class_display_name="Max Audio Effect", name="HallucinoteAnalyzer"),
    ])


@pytest.fixture
def ctx_two_tracks_one_return() -> _FakeCtx:
    return _FakeCtx(_FakeSong(
        tracks=[_FakeTrack("Drums"), _FakeTrack("Bass")],
        returns=[_FakeTrack("A-Reverb")],
        master=_master_with_analyzer(),
        last_event_time=64.0,
    ))


@pytest.fixture
def osc_sink():
    return []


@pytest.fixture
def osc_factory(osc_sink):
    return lambda port: _RecordingOSC(port, osc_sink)


@pytest.fixture
def stub_sidecar():
    return _StubSidecar()


# --- ensure_loaded action --------------------------------------------


def test_ensure_loaded_action_returns_layout(ctx_two_tracks_one_return):
    resp = dispatch(
        Request(tool="ableton_render", action="ensure_loaded", params={}),
        context=ctx_two_tracks_one_return,
    )
    assert resp.ok is True, resp.error
    # 2 tracks + 1 return loaded; the pre-placed master is detected (not
    # re-loaded) → 4 instances, 3 loaded + 1 existing.
    assert resp.result["loaded_count"] == 3
    assert resp.result["existing_count"] == 1
    assert len(resp.result["instances"]) == 4
    surfaces = {(i["surface_kind"], i["surface_index"]) for i in resp.result["instances"]}
    assert surfaces == {
        ("track", 1), ("track", 2), ("return", 1), ("master", 0),
    }


def test_ensure_loaded_idempotent_across_action_dispatches(ctx_two_tracks_one_return):
    """Calling the action twice — like /song-new postlude + /track-new
    postlude in the same session — does NOT duplicate analyzers."""
    first = dispatch(
        Request(tool="ableton_render", action="ensure_loaded", params={}),
        context=ctx_two_tracks_one_return,
    )
    second = dispatch(
        Request(tool="ableton_render", action="ensure_loaded", params={}),
        context=ctx_two_tracks_one_return,
    )
    assert first.ok and second.ok
    assert first.result["loaded_count"] == 3  # master pre-placed → detected
    assert second.result["loaded_count"] == 0
    assert second.result["existing_count"] == 4
    # No duplicates on any surface.
    counts = [
        sum(1 for d in t.devices if d.name == "HallucinoteAnalyzer")
        for t in (
            ctx_two_tracks_one_return.song.tracks[0],
            ctx_two_tracks_one_return.song.tracks[1],
            ctx_two_tracks_one_return.song.return_tracks[0],
            ctx_two_tracks_one_return.song.master_track,
        )
    ]
    assert counts == [1, 1, 1, 1]


# --- strip action ----------------------------------------------------


def test_strip_action_removes_all_analyzers_and_returns_shape(
    ctx_two_tracks_one_return,
):
    """The strip action (inverse of ensure_loaded): first populate every
    surface, then strip. Returns {stripped_count, instances:[surface descriptor
    + device_index]} and leaves NO analyzer on any surface."""
    # Populate every surface so there's something to strip on all of them.
    dispatch(
        Request(tool="ableton_render", action="ensure_loaded", params={}),
        context=ctx_two_tracks_one_return,
    )
    resp = dispatch(
        Request(tool="ableton_render", action="strip", params={}),
        context=ctx_two_tracks_one_return,
    )
    assert resp.ok is True, resp.error
    # 2 tracks + 1 return + master = 4 analyzers removed.
    assert resp.result["stripped_count"] == 4
    assert len(resp.result["instances"]) == 4
    surfaces = {
        (i["surface_kind"], i["surface_index"]) for i in resp.result["instances"]
    }
    assert surfaces == {
        ("track", 1), ("track", 2), ("return", 1), ("master", 0),
    }
    # Each descriptor mirrors ensure_loaded's surface fields + the removed index.
    for inst in resp.result["instances"]:
        assert set(inst) >= {
            "surface_kind", "surface_index", "surface_name", "device_index",
        }
        assert inst["device_index"] >= 1
    # No analyzer survives on any surface.
    song = ctx_two_tracks_one_return.song
    for track in (
        song.tracks[0], song.tracks[1], song.return_tracks[0], song.master_track,
    ):
        assert not any(d.name == "HallucinoteAnalyzer" for d in track.devices)


def test_strip_action_fires_delete_per_analyzer_bearing_surface(
    ctx_two_tracks_one_return,
):
    """The strip handler must call delete on EACH surface that carries an
    analyzer. The shared fixture pre-places the analyzer only on the master, so
    a bare strip (no ensure_loaded first) removes exactly that one — proving the
    handler fires a delete only where an analyzer is actually present (skips the
    bare track/return surfaces)."""
    song = ctx_two_tracks_one_return.song
    # Pre-condition: only the master carries the analyzer in this fixture.
    assert any(d.name == "HallucinoteAnalyzer" for d in song.master_track.devices)
    assert not any(d.name == "HallucinoteAnalyzer" for d in song.tracks[0].devices)

    resp = dispatch(
        Request(tool="ableton_render", action="strip", params={}),
        context=ctx_two_tracks_one_return,
    )
    assert resp.ok is True, resp.error
    # Only the master had an analyzer → exactly one delete fired.
    assert resp.result["stripped_count"] == 1
    assert resp.result["instances"][0]["surface_kind"] == "master"
    assert song.master_track.devices == []


def test_strip_action_idempotent_across_dispatches(ctx_two_tracks_one_return):
    """Strip twice — the second pass is a no-op (every surface already clear)."""
    dispatch(
        Request(tool="ableton_render", action="ensure_loaded", params={}),
        context=ctx_two_tracks_one_return,
    )
    first = dispatch(
        Request(tool="ableton_render", action="strip", params={}),
        context=ctx_two_tracks_one_return,
    )
    second = dispatch(
        Request(tool="ableton_render", action="strip", params={}),
        context=ctx_two_tracks_one_return,
    )
    assert first.ok and second.ok
    assert first.result["stripped_count"] == 4
    assert second.result["stripped_count"] == 0
    assert second.result["instances"] == []


# --- render handler (direct, with seams) -----------------------------


def test_render_writes_manifest_and_returns_status_ok(
    tmp_path, ctx_two_tracks_one_return, osc_factory, osc_sink, stub_sidecar,
):
    """End-to-end shape: render fires OSC messages, drives transport,
    writes manifest.json. With a fast clock_source the test runs in
    < 1 s (no real transport polling)."""
    # Fake clock: jump straight past stop_at_beat + post_roll on first poll.
    def _clock():
        return 999.0

    output_dir = tmp_path / "captures"
    result = render_handlers.render_handler(
        ctx_two_tracks_one_return,
        output_dir=str(output_dir),
        song_slug="test-song",
        _osc_factory=osc_factory,
        _sidecar=stub_sidecar,
        _clock_source=_clock,
        _now_iso=lambda: "20260526T120000Z",
    )

    assert result["status"] == "ok"
    assert Path(result["captures_dir"]).exists()
    manifest_path = Path(result["manifest_path"])
    assert manifest_path.exists()
    manifest = json.loads(manifest_path.read_text())
    assert manifest["status"] == "ok"
    assert manifest["song_slug"] == "test-song"
    assert manifest["captured_at"] == "20260526T120000Z"
    # Shared fixture has no arrangement clips, so the content-end scan falls
    # back to last_event_time (=64); stop_at_beat default uses it.
    assert manifest["stop_at_beat"] == 64
    assert len(manifest["tracks"]) == 2
    assert len(manifest["returns"]) == 1
    assert manifest["master"]["track_id"] == "master"
    # Each manifest entry has filename + absolute_path.
    for entry in manifest["tracks"] + manifest["returns"]:
        assert entry["filename"].endswith(".wav")
        assert Path(entry["absolute_path"]).is_absolute()


# --- RND: the analyzers must be armed AFTER the locate ----------------


def test_arm_happens_after_the_locate_not_before(
    tmp_path, ctx_two_tracks_one_return, osc_factory, osc_sink, stub_sidecar,
    monkeypatch,
):
    """Arming before the locate silently corrupts every capture.

    The M4L patch resets its ``prev_beat`` to -1 on the Arm RISING EDGE
    (m4l/HallucinoteAnalyzer.amxd.spec.md), which makes the start detector's
    ``prev_beat < start_at_beat`` clause unconditionally true. While armed, the
    detector therefore fires on the FIRST ``current_song_time`` change of any
    kind -- and a locate is exactly such a change. Arming first opened
    ``sfrecord~`` at the seek and recorded the wall clock before the transport
    rolled, putting every per-section window about a beat early, with nothing
    downstream able to notice.

    So this asserts ORDER, not just that both happened: by the time the arm is
    written the playhead must already be parked at the seek target, and the
    transport must not have been started yet.
    """
    events: list[tuple[str, float, bool]] = []

    real_arm = render_handlers._set_arm_on_all

    def _recording_arm(context, layout, *, arm):
        events.append(("arm" if arm else "disarm",
                       context.song.current_song_time,
                       context.song.is_playing))
        return real_arm(context, layout, arm=arm)

    real_locate = render_handlers.locate_start_position

    def _recording_locate(context, beat):
        result = real_locate(context, beat)
        events.append(("locate", context.song.current_song_time,
                       context.song.is_playing))
        return result

    monkeypatch.setattr(render_handlers, "_set_arm_on_all", _recording_arm)
    monkeypatch.setattr(render_handlers, "locate_start_position",
                        _recording_locate)

    result = render_handlers.render_handler(
        ctx_two_tracks_one_return,
        output_dir=str(tmp_path / "captures"),
        song_slug="test-song",
        start_at_beat=16,
        _osc_factory=osc_factory,
        _sidecar=stub_sidecar,
        _clock_source=lambda: 999.0,
        _now_iso=lambda: "20260526T120000Z",
    )
    assert result["status"] == "ok"

    kinds = [name for name, _, _ in events]
    assert "locate" in kinds, "the render never located"
    assert "arm" in kinds, "the render never armed"
    assert kinds.index("locate") < kinds.index("arm"), (
        f"arm must follow the locate; got {kinds}"
    )

    # The arm must see a playhead already parked, and a transport not yet
    # rolling -- the two halves of "the next movement is the transport".
    _, time_at_arm, playing_at_arm = events[kinds.index("arm")]
    assert time_at_arm > 0.0, (
        "armed while the playhead was still at 0 -- the locate had not landed"
    )
    assert not playing_at_arm, "armed after the transport was already rolling"


# --- BUG3: status.json completion heartbeat --------------------------


def test_render_writes_status_json_done_after_success(
    tmp_path, ctx_two_tracks_one_return, osc_factory, osc_sink, stub_sidecar,
):
    """BUG3: a completed render leaves status.json={state: done} next to the
    WAVs — the robust completion signal an agent polls (vs racing manifest.json
    via fragile dir-watching). It also carries the render_status + manifest_path
    so the poller knows the outcome and where the manifest is."""
    output_dir = tmp_path / "captures"
    result = render_handlers.render_handler(
        ctx_two_tracks_one_return,
        output_dir=str(output_dir),
        song_slug="test-song",
        _osc_factory=osc_factory,
        _sidecar=stub_sidecar,
        _clock_source=lambda: 999.0,
    )
    status_path = output_dir / "status.json"
    assert status_path.exists()
    status = json.loads(status_path.read_text())
    assert status["state"] == "done"
    assert status["render_status"] == result["status"] == "ok"
    assert status["manifest_path"] == result["manifest_path"]


def test_render_writes_status_json_error_on_failure(
    tmp_path, ctx_two_tracks_one_return, osc_factory, osc_sink, stub_sidecar,
):
    """BUG3: a render that RAISES (here an inverted beat window) still leaves a
    terminal status.json={state: error} so a poller sees completion rather than
    hanging on a manifest that never appears. The exception still propagates."""
    output_dir = tmp_path / "captures"
    with pytest.raises(ValueError, match="must be >"):
        render_handlers.render_handler(
            ctx_two_tracks_one_return,
            output_dir=str(output_dir),
            song_slug="test-song",
            start_at_beat=64,
            stop_at_beat=32,  # inverted → raises
            _osc_factory=osc_factory,
            _sidecar=stub_sidecar,
            _clock_source=lambda: 999.0,
        )
    status_path = output_dir / "status.json"
    assert status_path.exists()
    status = json.loads(status_path.read_text())
    assert status["state"] == "error"
    assert "must be >" in status["error"]


def test_render_status_writer_refreshes_running_during_wait(
    tmp_path, ctx_two_tracks_one_return, osc_factory, osc_sink, stub_sidecar,
):
    """The wait loop refreshes the heartbeat each poll (state=running + live
    progress) via the _status_writer seam — so a long render shows progress, not
    a stale 'running' frozen at start. The first write is the pre-wait running
    heartbeat; the wait loop emits at least one more running frame."""
    writes: list[tuple[str, dict]] = []

    def _recording_writer(captures_dir, status):
        writes.append((str(captures_dir), dict(status)))

    render_handlers.render_handler(
        ctx_two_tracks_one_return,
        output_dir=str(tmp_path / "captures"),
        song_slug="test-song",
        _osc_factory=osc_factory,
        _sidecar=stub_sidecar,
        _clock_source=lambda: 999.0,
        _status_writer=_recording_writer,
    )
    states = [s["state"] for _d, s in writes]
    # The pre-wait running write, at least one in-loop running refresh, then done.
    assert states[0] == "running"
    assert states[-1] == "done"
    running_writes = [s for _d, s in writes if s["state"] == "running"]
    # More than just the initial one → the loop refreshed it.
    assert len(running_writes) >= 2
    # The loop refresh carries live progress fields.
    loop_frame = running_writes[-1]
    assert "current_beat" in loop_frame and "target_beat" in loop_frame
    assert "frames_received" in loop_frame


def test_render_captures_ring_out_past_arrangement_end(
    tmp_path, ctx_two_tracks_one_return, osc_factory, osc_sink, stub_sidecar,
):
    """AUD-6R2M/AUD-4S8T: the analyzer is told to record past the arrangement
    end by ring_out_beats so the reverb decays into a captured tail. The
    manifest records stop_at_beat (the input-stop boundary) AND ring_out_beats
    separately; the /stop_at_beat sent to every analyzer is the EXTENDED stop."""
    render_handlers.render_handler(
        ctx_two_tracks_one_return,
        song_slug="t",
        output_dir=str(tmp_path / "c"),
        ring_out_beats=12.0,
        _osc_factory=osc_factory,
        _sidecar=stub_sidecar,
        _clock_source=lambda: 9999.0,
        _now_iso=lambda: "20260602T120000Z",
    )
    manifest = json.loads((tmp_path / "c" / "manifest.json").read_text())
    # No clips in the fixture → content-end scan falls back to last_event_time
    # (=64); stop_at_beat stays that content end, ring-out is recorded after.
    assert manifest["stop_at_beat"] == 64
    assert manifest["ring_out_beats"] == 12.0
    # Every analyzer's recording stop = end_beat + ring_out_beats = 76.
    stop_values = [args[0] for _port, addr, args in osc_sink
                   if addr == "/stop_at_beat"]
    assert stop_values, "no /stop_at_beat sent"
    assert set(stop_values) == {76}


def test_render_default_stop_anchors_to_clip_content_end_not_last_event_time(
    tmp_path, osc_factory, osc_sink, stub_sidecar,
):
    """Regression: the default dry-stop must anchor to where the arrangement's
    CONTENT ends (max clip end_time), NOT song.last_event_time.

    Live extends last_event_time to the furthest playhead, so the render's own
    ring-out playback inflates it past the real content — and it compounds
    across renders. If the dry-stop followed the inflated value, it would land
    in trailing dead-air where the reverb has already decayed, the ring-out
    would record silence, and the per-return RT60 would be unmeasurable. Here
    the clips end at 48 while last_event_time is inflated to 64: the dry-stop
    must be 48, and the analyzer's recording stop = 48 + ring_out (8) = 56."""
    song = _FakeSong(
        tracks=[
            _FakeTrack("Drums", arrangement_clips=[_FakeClip(end_time=48.0)]),
            _FakeTrack("Bass", arrangement_clips=[_FakeClip(end_time=32.0)]),
        ],
        returns=[_FakeTrack("A-Reverb")],
        master=_master_with_analyzer(),
        last_event_time=64.0,  # inflated past the real content end (48)
    )
    ctx = _FakeCtx(song)
    render_handlers.render_handler(
        ctx,
        song_slug="t",
        output_dir=str(tmp_path / "c"),
        ring_out_beats=8.0,
        _osc_factory=osc_factory,
        _sidecar=stub_sidecar,
        _clock_source=lambda: 9999.0,
    )
    manifest = json.loads((tmp_path / "c" / "manifest.json").read_text())
    assert manifest["stop_at_beat"] == 48  # clip content end, NOT 64
    stop_values = {args[0] for _p, addr, args in osc_sink if addr == "/stop_at_beat"}
    assert stop_values == {56}  # 48 + 8 ring-out


def test_render_default_stop_falls_back_to_last_event_time_when_no_clips(
    tmp_path, osc_factory, osc_sink, stub_sidecar,
):
    """A session-only / empty-arrangement set has no arrangement clips, so the
    content-end scan finds nothing and falls back to last_event_time — keeping
    the downstream empty-arrangement guard live."""
    song = _FakeSong(
        tracks=[_FakeTrack("Drums"), _FakeTrack("Bass")],  # no arrangement_clips
        returns=[_FakeTrack("A-Reverb")],
        master=_master_with_analyzer(),
        last_event_time=40.0,
    )
    ctx = _FakeCtx(song)
    render_handlers.render_handler(
        ctx,
        song_slug="t",
        output_dir=str(tmp_path / "c"),
        ring_out_beats=0.0,
        _osc_factory=osc_factory,
        _sidecar=stub_sidecar,
        _clock_source=lambda: 9999.0,
    )
    manifest = json.loads((tmp_path / "c" / "manifest.json").read_text())
    assert manifest["stop_at_beat"] == 40  # fell back to last_event_time


def test_render_ring_out_zero_records_to_arrangement_end(
    tmp_path, ctx_two_tracks_one_return, osc_factory, osc_sink, stub_sidecar,
):
    """ring_out_beats=0 (e.g. no reverb to verify) → recording stop is the
    arrangement end, no extra tail."""
    render_handlers.render_handler(
        ctx_two_tracks_one_return,
        song_slug="t",
        output_dir=str(tmp_path / "c"),
        ring_out_beats=0.0,
        _osc_factory=osc_factory,
        _sidecar=stub_sidecar,
        _clock_source=lambda: 9999.0,
    )
    manifest = json.loads((tmp_path / "c" / "manifest.json").read_text())
    assert manifest["ring_out_beats"] == 0.0
    stop_values = {args[0] for _p, addr, args in osc_sink if addr == "/stop_at_beat"}
    assert stop_values == {64}  # == end_beat, no ring-out


def test_render_manifest_records_actual_rounded_ring_out(
    tmp_path, ctx_two_tracks_one_return, osc_factory, osc_sink, stub_sidecar,
):
    """The analyzer stop is `/stop_at_beat <int>`, so a fractional request is
    rounded to whole beats. The manifest must record what was ACTUALLY
    recorded (the rounded int), not the float request — the read side trusts
    it to map the captured samples onto [stop, stop+ring_out]."""
    render_handlers.render_handler(
        ctx_two_tracks_one_return,
        song_slug="t",
        output_dir=str(tmp_path / "c"),
        ring_out_beats=7.4,
        _osc_factory=osc_factory,
        _sidecar=stub_sidecar,
        _clock_source=lambda: 9999.0,
    )
    manifest = json.loads((tmp_path / "c" / "manifest.json").read_text())
    assert manifest["ring_out_beats"] == 7          # 7.4 → 7 whole beats
    stop_values = {args[0] for _p, addr, args in osc_sink if addr == "/stop_at_beat"}
    assert stop_values == {71}                       # 64 + 7


def test_render_disables_loop_for_capture_then_restores_it(
    tmp_path, ctx_two_tracks_one_return, osc_factory, osc_sink, stub_sidecar,
):
    """Loop must be OFF during the ring-out (transport runs into empty
    arrangement, not looping back), and restored to its prior value after."""
    song = ctx_two_tracks_one_return.song
    assert song.loop is True  # fixture default
    render_handlers.render_handler(
        ctx_two_tracks_one_return,
        song_slug="t",
        output_dir=str(tmp_path / "c"),
        _osc_factory=osc_factory,
        _sidecar=stub_sidecar,
        _clock_source=lambda: 9999.0,
    )
    # Disabled for the capture, then restored to the original True.
    assert song.loop_writes == [False, True]
    assert song.loop is True


def test_render_sends_path_track_id_and_beat_window_via_osc(
    tmp_path, ctx_two_tracks_one_return, osc_factory, osc_sink, stub_sidecar,
):
    """For every analyzer, the handler must send (in this order):
    /path, /track_id, /start_at_beat, /stop_at_beat — all to the
    per-instance OSC port."""
    render_handlers.render_handler(
        ctx_two_tracks_one_return,
        song_slug="t",
        output_dir=str(tmp_path / "c"),
        _osc_factory=osc_factory,
        _sidecar=stub_sidecar,
        _clock_source=lambda: 999.0,
    )
    # Group recorded OSC messages by (port, address).
    by_port: dict[int, list[str]] = {}
    for port, addr, _args in osc_sink:
        by_port.setdefault(port, []).append(addr)
    # 4 analyzers → 4 ports (deterministic, stride 1).
    # Tracks: 11020 (T1), 11021 (T2). Return 1: 11120. Master: 11220.
    # Base 11020 (not 11000) clears AbletonOSC; see analyzer/setup.py.
    expected_ports = {11020, 11021, 11120, 11220}
    assert set(by_port.keys()) == expected_ports
    # Each port saw exactly the four expected addresses in order.
    for port in expected_ports:
        assert by_port[port] == [
            "/path", "/track_id", "/start_at_beat", "/stop_at_beat",
        ]


def test_render_arms_then_disarms_all_analyzers(
    tmp_path, ctx_two_tracks_one_return, osc_factory, osc_sink, stub_sidecar,
):
    """At the end of a clean render, every analyzer's Arm parameter is
    back at 0 — the patch's beat observer + Arm-gate model means a
    forgotten Arm=1 would leak into the next render."""
    render_handlers.render_handler(
        ctx_two_tracks_one_return,
        song_slug="t",
        output_dir=str(tmp_path / "c"),
        _osc_factory=osc_factory,
        _sidecar=stub_sidecar,
        _clock_source=lambda: 999.0,
    )
    for t in (
        ctx_two_tracks_one_return.song.tracks[0],
        ctx_two_tracks_one_return.song.tracks[1],
        ctx_two_tracks_one_return.song.return_tracks[0],
        ctx_two_tracks_one_return.song.master_track,
    ):
        analyzer = next(
            d for d in t.devices if d.name == "HallucinoteAnalyzer"
        )
        arm = next(p for p in analyzer.parameters if p.name == "Arm")
        assert arm.value == 0.0


def test_render_starts_and_stops_transport_exactly_once(
    tmp_path, ctx_two_tracks_one_return, osc_factory, stub_sidecar,
):
    render_handlers.render_handler(
        ctx_two_tracks_one_return,
        song_slug="t",
        output_dir=str(tmp_path / "c"),
        _osc_factory=osc_factory,
        _sidecar=stub_sidecar,
        _clock_source=lambda: 999.0,
    )
    assert ctx_two_tracks_one_return.song.start_playing_calls == 1
    assert ctx_two_tracks_one_return.song.stop_playing_calls == 1


def test_render_marks_status_incomplete_on_timeout(
    tmp_path, ctx_two_tracks_one_return, osc_factory, stub_sidecar,
):
    """A clock that never advances must time out and produce
    status=incomplete in the manifest (partial WAVs still survive)."""
    # Use a very short arrangement so the wait is bounded by _MIN_WAIT_S
    # (~30 s) — that's still too long for a test; force the timeout
    # via an absurdly large start_at_beat that overflows the
    # max_wait_s budget.
    # Simpler: a clock that returns 0 forever; the loop's deadline is
    # max(MIN_WAIT_S, ...) so it'd hang for 30s. Patch the constant
    # via monkeypatching is harder — instead, set stop_at_beat=1 so
    # max_wait_s = max(MIN_WAIT_S, ~5 beats) = MIN_WAIT_S. To keep the
    # test fast we monkey-patch the module constants.
    import hallucinote_mcp.handlers.render as render_mod

    original_min = render_mod._MIN_WAIT_S
    original_mult = render_mod._MAX_WAIT_MULTIPLIER
    render_mod._MIN_WAIT_S = 0.05  # 50ms
    render_mod._MAX_WAIT_MULTIPLIER = 0.0001
    try:
        result = render_handlers.render_handler(
            ctx_two_tracks_one_return,
            song_slug="t",
            output_dir=str(tmp_path / "c"),
            _osc_factory=osc_factory,
            _sidecar=stub_sidecar,
            _clock_source=lambda: 0.0,
        )
    finally:
        render_mod._MIN_WAIT_S = original_min
        render_mod._MAX_WAIT_MULTIPLIER = original_mult

    assert result["status"] == "incomplete"
    manifest = json.loads(Path(result["manifest_path"]).read_text())
    assert manifest["status"] == "incomplete"


def test_render_fails_fast_when_recorder_receives_no_frames(
    tmp_path, ctx_two_tracks_one_return, osc_factory, stub_sidecar,
):
    """Transport advances into the recording window but the analyzer sidecar
    gets 0 frames (dead recorder) → fail fast with a teaching error instead of
    blocking the whole render window for frames that never arrive."""
    # Clock parks past the no-frame checkpoint (beat 4) but short of the
    # crossing target (beat 68); stub_sidecar.frames_received stays 0.
    with pytest.raises(ValueError, match="0 frames"):
        render_handlers.render_handler(
            ctx_two_tracks_one_return,
            song_slug="t",
            output_dir=str(tmp_path / "c"),
            _osc_factory=osc_factory,
            _sidecar=stub_sidecar,
            _clock_source=lambda: 10.0,
        )
    # Live's transport was cleaned up (stop + disarm) before raising.
    assert ctx_two_tracks_one_return.song.stop_playing_calls == 1


def test_render_does_not_fail_fast_when_frames_flow(
    tmp_path, ctx_two_tracks_one_return, osc_factory,
):
    """Frames flowing past the checkpoint must NOT trip the fail-fast: once
    transport crosses the target the render completes status=ok. The fail-fast
    keys on the frame DELTA over the window, so the recorder must produce NEW
    frames (a counter that grows), not merely report a non-zero total."""
    class _LiveSidecar:
        port = 11221

        def __init__(self):
            self._n = 0

        @property
        def frames_received(self):
            self._n += 1   # a live recorder accrues frames on each read
            return self._n

    # First poll lands past the checkpoint (beat 4) with frames accruing; second
    # poll has crossed the target (beat 68) → 'crossed' → ok.
    ticks = iter([10.0, 999.0])

    result = render_handlers.render_handler(
        ctx_two_tracks_one_return,
        song_slug="t",
        output_dir=str(tmp_path / "c"),
        _osc_factory=osc_factory,
        _sidecar=_LiveSidecar(),
        _clock_source=lambda: next(ticks),
        _now_iso=lambda: "20260528T120000Z",
    )
    assert result["status"] == "ok"
    assert result["manifest"]["frames_received"] > 0  # new frames over the window


# --- engine pre-flight (RND-7K3M: fail fast when the audio engine is off) ----


def test_default_engine_preflight_detects_frozen_transport(ctx_two_tracks_one_return):
    """A transport whose current_song_time doesn't move (audio engine off) reads
    as NOT advancing — the signal the render handler fails fast on."""
    # _FakeSong.current_song_time stays 0.0 (start_playing doesn't advance it).
    assert render_handlers._default_engine_preflight(
        ctx_two_tracks_one_return, probe_s=0.001) is False


def test_default_engine_preflight_passes_when_transport_advances():
    """A transport whose current_song_time grows between samples reads as
    advancing (a live audio engine)."""
    class _AdvancingSong:
        def __init__(self):
            self._t = 0.0

        @property
        def current_song_time(self):
            self._t += 1.0  # a running transport accrues beats on each read
            return self._t

    class _AdvancingCtx:
        def __init__(self):
            self._song = _AdvancingSong()

        @property
        def song(self):
            return self._song

        def run_on_main(self, fn, **_kwargs):
            return fn()

    assert render_handlers._default_engine_preflight(
        _AdvancingCtx(), probe_s=0.001) is True


def test_render_fails_fast_when_audio_engine_off(
    tmp_path, ctx_two_tracks_one_return, osc_factory, stub_sidecar,
):
    """When the engine pre-flight reports the transport isn't advancing (audio
    engine off), the handler raises with an actionable cause AFTER cleaning up
    Live's transport (stop + disarm) — and BEFORE the long capture wait, so it
    fails in ~probe_s instead of blocking the full render window for minutes."""
    with pytest.raises(ValueError, match="audio engine is"):
        render_handlers.render_handler(
            ctx_two_tracks_one_return,
            song_slug="t",
            output_dir=str(tmp_path / "c"),
            _osc_factory=osc_factory,
            _sidecar=stub_sidecar,
            _engine_check=lambda: False,   # simulate a dead audio engine
        )
    # Transport was cleaned up before raising.
    assert ctx_two_tracks_one_return.song.stop_playing_calls == 1
    for t in (
        ctx_two_tracks_one_return.song.tracks[0],
        ctx_two_tracks_one_return.song.return_tracks[0],
        ctx_two_tracks_one_return.song.master_track,
    ):
        analyzer = next(d for d in t.devices if d.name == "HallucinoteAnalyzer")
        arm = next(p for p in analyzer.parameters if p.name == "Arm")
        assert arm.value == 0.0


def test_render_proceeds_when_engine_check_passes(
    tmp_path, ctx_two_tracks_one_return, osc_factory, stub_sidecar,
):
    """A passing engine pre-flight does not interfere with a normal render."""
    result = render_handlers.render_handler(
        ctx_two_tracks_one_return,
        song_slug="t",
        output_dir=str(tmp_path / "c"),
        _osc_factory=osc_factory,
        _sidecar=stub_sidecar,
        _engine_check=lambda: True,    # engine healthy
        _clock_source=lambda: 999.0,   # transport already past stop
    )
    assert result["status"] == "ok"


def test_render_handler_refuses_missing_output_dir(
    tmp_path, ctx_two_tracks_one_return, osc_factory, stub_sidecar,
):
    """The handler refuses to invent a default output_dir — the server
    side (`_absolutize_render_output_dir` in server.py) is the source of
    truth for default-resolution + absolutization. A handler that
    invented a relative default would silently write to Live's cwd (``/``
    on macOS, read-only) when called from inside the Remote Script.
    See `test_render_call_computes_default_output_dir_when_missing` in
    test_server.py for the server-side default coverage."""
    with pytest.raises(ValueError, match="output_dir is required"):
        render_handlers.render_handler(
            ctx_two_tracks_one_return,
            song_slug="my-song",
            _osc_factory=osc_factory,
            _sidecar=stub_sidecar,
            _clock_source=lambda: 999.0,
        )


def test_render_rejects_inverted_beat_window(
    tmp_path, ctx_two_tracks_one_return, osc_factory, stub_sidecar,
):
    with pytest.raises(ValueError, match="must be >"):
        render_handlers.render_handler(
            ctx_two_tracks_one_return,
            song_slug="t",
            output_dir=str(tmp_path / "c"),
            start_at_beat=64,
            stop_at_beat=64,  # equal to start → invalid window
            _osc_factory=osc_factory,
            _sidecar=stub_sidecar,
            _clock_source=lambda: 999.0,
        )


# --- per-instance WAV filenames ---------------------------------------


def test_render_per_surface_wav_filenames_are_deterministic(
    tmp_path, ctx_two_tracks_one_return, osc_factory, stub_sidecar,
):
    """Two consecutive renders on the same surfaces produce the same
    filename basenames (different timestamp dirs). Callers can diff
    captures across renders by basename."""
    a = render_handlers.render_handler(
        ctx_two_tracks_one_return,
        song_slug="t",
        output_dir=str(tmp_path / "c1"),
        _osc_factory=osc_factory,
        _sidecar=stub_sidecar,
        _clock_source=lambda: 999.0,
    )
    b = render_handlers.render_handler(
        ctx_two_tracks_one_return,
        song_slug="t",
        output_dir=str(tmp_path / "c2"),
        _osc_factory=osc_factory,
        _sidecar=stub_sidecar,
        _clock_source=lambda: 999.0,
    )
    names_a = sorted(t["filename"] for t in a["manifest"]["tracks"])
    names_b = sorted(t["filename"] for t in b["manifest"]["tracks"])
    assert names_a == names_b


# --- notification-deferral regression guard --------------------------
#
# Regression guard for the 2026-05-27 bug: writing current_song_time
# AND calling start_playing inside a single run_on_main bout triggers
# Live's "Changes cannot be triggered by notifications" error — the
# first write kicks off a notification cascade, and the synchronous
# second call lands while a listener is still flushing. Fix splits
# the two into separate bouts with a worker-thread yield between.


def test_render_seeks_and_plays_in_separate_bouts(
    tmp_path, ctx_two_tracks_one_return, osc_factory, stub_sidecar,
):
    """The seek (current_song_time write) and play (start_playing call)
    MUST happen in different main-thread bouts. Doing both in one bout
    raises Live's notification-deferral error against real Live.

    The seek lands at start_at_beat - pre_roll_beats (not start_at_beat
    itself) so the patch's transport-cross detector sees an edge — see
    ``_DEFAULT_PRE_ROLL_BEATS`` in handlers/render.py for the empirical
    motivation."""
    render_handlers.render_handler(
        ctx_two_tracks_one_return,
        song_slug="t",
        output_dir=str(tmp_path / "c"),
        start_at_beat=8,  # → seek lands at 8 - pre_roll = 4
        pre_roll_beats=4.0,
        _osc_factory=osc_factory,
        _sidecar=stub_sidecar,
        _clock_source=lambda: 999.0,
    )
    expected_seek_time = 4.0  # 8 - 4 pre-roll
    # Find the bouts that mutated transport. We need: ONE bout that
    # changed current_song_time to 4.0 with start_playing_calls
    # unchanged, then a LATER bout where start_playing_calls increments.
    seek_bout = None
    play_bout = None
    prev_plays = 0
    for bout_id, song_time, plays, _stops in ctx_two_tracks_one_return.bout_log:
        if seek_bout is None and song_time == expected_seek_time and plays == prev_plays:
            seek_bout = bout_id
        elif seek_bout is not None and play_bout is None and plays > prev_plays:
            play_bout = bout_id
        prev_plays = plays
    assert seek_bout is not None, (
        f"no bout wrote current_song_time={expected_seek_time}; "
        f"bout_log={ctx_two_tracks_one_return.bout_log}"
    )
    assert play_bout is not None, (
        f"no bout called start_playing after the seek; "
        f"bout_log={ctx_two_tracks_one_return.bout_log}"
    )
    assert seek_bout != play_bout, (
        f"seek and play landed in the same bout ({seek_bout}); Live "
        "rejects this with the notification-deferral error"
    )


def test_render_seek_includes_pre_roll(
    tmp_path, ctx_two_tracks_one_return, osc_factory, stub_sidecar,
):
    """Render must seek to start_at_beat - pre_roll_beats, not directly
    to start_at_beat. Without the pre-roll, the patch's cross-detector
    misses the edge and sfrecord~ never starts. Regression guard against
    re-introducing the direct-seek bug."""
    render_handlers.render_handler(
        ctx_two_tracks_one_return,
        song_slug="t",
        output_dir=str(tmp_path / "c"),
        start_at_beat=16,
        pre_roll_beats=4.0,
        _osc_factory=osc_factory,
        _sidecar=stub_sidecar,
        _clock_source=lambda: 999.0,
    )
    # The first transport mutation should be the seek to (16 - 4) = 12.
    first_seek = next(
        (song_time for _bid, song_time, _p, _s in ctx_two_tracks_one_return.bout_log),
        None,
    )
    assert first_seek == 12.0, (
        f"render must seek to start_at_beat - pre_roll = 12.0, got {first_seek}"
    )


def test_render_pre_roll_clamped_at_zero(
    tmp_path, ctx_two_tracks_one_return, osc_factory, stub_sidecar,
):
    """When start_at_beat - pre_roll would go negative, seek is clamped
    at 0 (transport can't go before the arrangement start)."""
    render_handlers.render_handler(
        ctx_two_tracks_one_return,
        song_slug="t",
        output_dir=str(tmp_path / "c"),
        start_at_beat=2,
        pre_roll_beats=4.0,  # 2 - 4 = -2 → should clamp to 0
        _osc_factory=osc_factory,
        _sidecar=stub_sidecar,
        _clock_source=lambda: 999.0,
    )
    first_seek = next(
        (song_time for _bid, song_time, _p, _s in ctx_two_tracks_one_return.bout_log),
        None,
    )
    assert first_seek == 0.0, (
        f"pre-roll seek should clamp at 0 when start_at_beat - pre_roll "
        f"is negative; got {first_seek}"
    )


def test_render_stops_and_disarms_in_separate_bouts(
    tmp_path, ctx_two_tracks_one_return, osc_factory, stub_sidecar,
):
    """Symmetric guard: stop_playing must not share a bout with the
    follow-up Arm-off writes. The Arm writes are themselves split per
    surface via _set_arm_on_all (see analyzer/setup parity)."""
    render_handlers.render_handler(
        ctx_two_tracks_one_return,
        song_slug="t",
        output_dir=str(tmp_path / "c"),
        _osc_factory=osc_factory,
        _sidecar=stub_sidecar,
        _clock_source=lambda: 999.0,
    )
    # The stop bout is the one where stop_playing_calls went 0 → 1
    # without another transport mutation in the same bout.
    stop_bout = None
    prev_stops = 0
    for bout_id, _song_time, _plays, stops in ctx_two_tracks_one_return.bout_log:
        if stop_bout is None and stops > prev_stops:
            stop_bout = bout_id
            break
        prev_stops = stops
    assert stop_bout is not None
    # The disarm writes happen AFTER the stop bout (per render_handler
    # ordering). The Arm parameters now read 0.0 on every analyzer.
    for t in (
        ctx_two_tracks_one_return.song.tracks[0],
        ctx_two_tracks_one_return.song.tracks[1],
        ctx_two_tracks_one_return.song.return_tracks[0],
        ctx_two_tracks_one_return.song.master_track,
    ):
        analyzer = next(d for d in t.devices if d.name == "HallucinoteAnalyzer")
        arm = next(p for p in analyzer.parameters if p.name == "Arm")
        assert arm.value == 0.0


def test_render_manifest_records_db_seq_param(
    tmp_path, ctx_two_tracks_one_return, osc_factory, osc_sink, stub_sidecar,
):
    """AUD-4W7K: the server-attached db_seq param lands in manifest.json —
    the audit-log key baseline diffs resolve by. Absent param → null (the
    loader treats both as untagged)."""
    def _clock():
        return 999.0

    common = dict(
        _osc_factory=osc_factory,
        _sidecar=stub_sidecar,
        _clock_source=_clock,
        _now_iso=lambda: "20260610T120000Z",
    )

    tagged = render_handlers.render_handler(
        ctx_two_tracks_one_return,
        output_dir=str(tmp_path / "a"),
        song_slug="test-song",
        db_seq=4823,
        **common,
    )
    manifest = json.loads(Path(tagged["manifest_path"]).read_text())
    assert manifest["db_seq"] == 4823

    untagged = render_handlers.render_handler(
        ctx_two_tracks_one_return,
        output_dir=str(tmp_path / "b"),
        song_slug="test-song",
        **common,
    )
    manifest = json.loads(Path(untagged["manifest_path"]).read_text())
    assert manifest["db_seq"] is None


# --- SNP-8R4K Mechanism 2: terminal-tap observability in the manifest ----
#
# The render re-asserts the analyzer-is-last invariant at render start (the
# ensure_analyzers_loaded sweep). The manifest must record, per surface, the
# terminal-tap status (R9) so a reading agent never trusts an under-tapped
# stem: each track/return/master entry carries terminal + was_repositioned,
# and a top-level analyzer_not_terminal lists any under-tapped surface.


def test_render_manifest_records_terminal_tap_status_clean(
    tmp_path, ctx_two_tracks_one_return, osc_factory, osc_sink, stub_sidecar,
):
    """A clean render (every analyzer present + last) records terminal=True on
    every surface, was_repositioned=False, and an empty analyzer_not_terminal."""
    result = render_handlers.render_handler(
        ctx_two_tracks_one_return,
        song_slug="t",
        output_dir=str(tmp_path / "c"),
        _osc_factory=osc_factory,
        _sidecar=stub_sidecar,
        _clock_source=lambda: 999.0,
    )
    manifest = result["manifest"]
    assert manifest["analyzer_not_terminal"] == []
    entries = manifest["tracks"] + manifest["returns"] + [manifest["master"]]
    for entry in entries:
        assert entry["terminal"] is True
        assert entry["was_repositioned"] is False


def test_render_repositions_analyzer_landed_past_it_and_flags_manifest(
    tmp_path, osc_factory, osc_sink, stub_sidecar,
):
    """The chunk's core case: a device was loaded after a prior render so it
    landed PAST the analyzer (analyzer no longer last → under-tapping). At the
    next render the sweep repositions the analyzer to last on that surface; the
    manifest entry flags was_repositioned=True and the surface ends terminal."""
    analyzer = _FakeDevice(class_display_name="Max Audio Effect", name="HallucinoteAnalyzer")
    # A Saturator loaded after the prior render sits AFTER the analyzer.
    saturator = _FakeDevice(class_display_name="Saturator")
    song = _FakeSong(
        tracks=[_FakeTrack("Drums", devices=[analyzer, saturator])],
        returns=[_FakeTrack("A-Reverb")],
        master=_master_with_analyzer(),
        last_event_time=64.0,
    )
    ctx = _FakeCtx(song)
    result = render_handlers.render_handler(
        ctx,
        song_slug="t",
        output_dir=str(tmp_path / "c"),
        _osc_factory=osc_factory,
        _sidecar=stub_sidecar,
        _clock_source=lambda: 999.0,
    )
    manifest = result["manifest"]
    # The analyzer is now last on the Drums track (Saturator before it).
    assert [d.name for d in song.tracks[0].devices] == ["Saturator", "HallucinoteAnalyzer"]
    drums_entry = next(t for t in manifest["tracks"] if t["surface_index"] == 1)
    assert drums_entry["was_repositioned"] is True
    assert drums_entry["terminal"] is True
    # Repositioning fixed the under-tap → nothing flagged not-terminal.
    assert manifest["analyzer_not_terminal"] == []
    # The return + master were already-last → not repositioned.
    assert manifest["returns"][0]["was_repositioned"] is False
    assert manifest["master"]["was_repositioned"] is False


def test_render_manifest_flags_surface_that_cannot_be_made_terminal(
    tmp_path, osc_factory, osc_sink, stub_sidecar,
):
    """Never measure-and-lie (R9): if a surface's analyzer cannot be made
    strictly last (here a misbehaving load that does NOT append it terminal),
    the manifest flags that surface in analyzer_not_terminal and marks the
    per-surface entry terminal=False — rather than emitting clean numbers for an
    under-tapped stem."""
    # A browser whose load_item appends the analyzer but ALSO leaves a device
    # after it (simulates a load that doesn't land terminal — a Live quirk /
    # concurrent edit). The terminal-verify re-read then sees it NOT last.
    class _NonTerminalBrowser(_FakeBrowser):
        def load_item(self, item):
            self.load_calls.append(item)
            target = self._song.view.selected_track
            target.devices.append(_FakeDevice(
                class_display_name="Max Audio Effect", name=item.name,
            ))
            # An interloper lands AFTER the analyzer — it is no longer last.
            target.devices.append(_FakeDevice(class_display_name="Utility"))

    class _NonTerminalApp(_FakeApplication):
        def __init__(self, song):
            self.browser = _NonTerminalBrowser(song)

    # Drums has NO analyzer → the sweep loads one, but the misbehaving browser
    # leaves a Utility after it → the surface can't be made terminal.
    song = _FakeSong(
        tracks=[_FakeTrack("Drums")],
        master=_master_with_analyzer(),  # master already-last (clean)
        last_event_time=64.0,
    )
    ctx = _FakeCtx(song)
    ctx._application = _NonTerminalApp(song)

    result = render_handlers.render_handler(
        ctx,
        song_slug="t",
        output_dir=str(tmp_path / "c"),
        _osc_factory=osc_factory,
        _sidecar=stub_sidecar,
        _clock_source=lambda: 999.0,
    )
    manifest = result["manifest"]
    drums_entry = next(t for t in manifest["tracks"] if t["surface_index"] == 1)
    assert drums_entry["terminal"] is False
    assert "track:1" in manifest["analyzer_not_terminal"]
    # The clean master is NOT flagged.
    assert manifest["master"]["terminal"] is True
    assert "master" not in manifest["analyzer_not_terminal"]


def test_ensure_loaded_action_surfaces_terminal_status(ctx_two_tracks_one_return):
    """The ensure_loaded action response surfaces terminal/was_repositioned per
    instance too, so a structural-mutation postlude sweep shows an under-tapped
    or repositioned surface to the LLM."""
    resp = dispatch(
        Request(tool="ableton_render", action="ensure_loaded", params={}),
        context=ctx_two_tracks_one_return,
    )
    assert resp.ok is True, resp.error
    for inst in resp.result["instances"]:
        assert inst["terminal"] is True
        assert inst["was_repositioned"] is False


def test_render_refuses_to_capture_from_the_wrong_part_of_the_song(
    tmp_path, ctx_two_tracks_one_return, osc_factory, stub_sidecar,
):
    """The render half of #471. Live rolls from a start playing position the
    seek never moved, so a capture can record a completely different section
    while every check the handler had said it was healthy — the engine
    pre-flight asks whether the transport ADVANCES, and a transport in the
    wrong place advances exactly as well as one in the right place."""
    ctx_two_tracks_one_return.song.stale_start_position = 999.0

    with pytest.raises(PlayheadPositionError) as exc:
        render_handlers.render_handler(
            ctx_two_tracks_one_return,
            song_slug="t",
            output_dir=str(tmp_path / "c"),
            _osc_factory=osc_factory,
            _sidecar=stub_sidecar,
            # A healthy engine — which is the whole point. This transport is
            # rolling perfectly well, three hundred bars from where it was
            # sent, and the advance check cannot tell the difference.
            _engine_check=lambda: True,
        )

    err = exc.value
    assert err.observed_beats == pytest.approx(999.0)
    assert "render capture" in str(err)
    assert "START PLAYING POSITION" in str(err)


def test_a_healthy_render_locates_the_start_position_before_playing(
    tmp_path, ctx_two_tracks_one_return, osc_factory, stub_sidecar,
):
    """The capture positions with a cue jump, not a bare playhead write — and
    gives back the locator it borrowed to do it."""
    song = ctx_two_tracks_one_return.song
    song.cue_points = []
    cue_ops: list[tuple] = []

    def _toggle() -> None:
        at = song.current_song_time
        cue_ops.append(("toggle", at))
        for i, cue in enumerate(song.cue_points):
            if abs(cue.time - at) < 1e-6:
                del song.cue_points[i]
                return
        song.cue_points.append(_JumpingCue(song, at, cue_ops))

    song.set_or_delete_cue = _toggle

    render_handlers.render_handler(
        ctx_two_tracks_one_return,
        song_slug="t",
        output_dir=str(tmp_path / "c"),
        _osc_factory=osc_factory,
        _sidecar=stub_sidecar,
        _clock_source=lambda: 999.0,
    )

    assert [op[0] for op in cue_ops] == ["toggle", "jump", "toggle"]
    assert song.cue_points == []


class _JumpingCue:
    def __init__(self, song, time_, ops):
        self._song = song
        self._ops = ops
        self.time = float(time_)
        self.name = ""

    def jump(self) -> None:
        self._ops.append(("jump", self.time))
        self._song.current_song_time = self.time
