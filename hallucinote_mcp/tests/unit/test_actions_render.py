"""Tests for ableton_render (action schema + render handler)."""
from __future__ import annotations

import json
import socket
import struct
import threading
from pathlib import Path
from typing import Any

import pytest

from hallucinote_mcp.analyzer.osc import AnalyzerOSC
from hallucinote_mcp.analyzer.sidecar import (
    OSCSidecar,
    reset_shared_sidecar_for_tests,
)
from hallucinote_mcp.dispatcher import dispatch
from hallucinote_mcp.handlers import render as render_handlers
from hallucinote_mcp.wire import Request


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
        _FakeParam("Port", 11000.0, min=11000.0, max=11400.0),
        _FakeParam("EmitPort", 11001.0, min=11000.0, max=11400.0),
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
        self.name = name or class_display_name
        if parameters is None and class_display_name == "HallucinoteAnalyzer":
            parameters = _analyzer_params()
        self.parameters = parameters or []


class _FakeMixer:
    def __init__(self):
        self.volume = _FakeParam("Volume", 0.85)
        self.panning = _FakeParam("Panning", 0.0)
        self.sends = []


class _FakeTrack:
    def __init__(
        self,
        name: str,
        *,
        devices: list[_FakeDevice] | None = None,
        has_audio_output: bool = True,
        has_midi_input: bool = False,
        is_foldable: bool = False,
    ):
        self.name = name
        self.devices = list(devices or [])
        self.mixer_device = _FakeMixer()
        self.has_audio_output = has_audio_output
        self.has_midi_input = has_midi_input
        self.has_audio_input = not has_midi_input
        self.is_foldable = is_foldable


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
    def __init__(self, song):
        self._song = song
        self.audio_effects = _FakeBrowserRoot("Audio Effects")
        self.audio_effects.children.append(_FakeBrowserItem("HallucinoteAnalyzer"))
        self.instruments = _FakeBrowserRoot("Instruments")
        self.midi_effects = _FakeBrowserRoot("MIDI Effects")
        self.drums = _FakeBrowserRoot("Drums")
        self.plugins = _FakeBrowserRoot("Plug-Ins")
        self.samples = _FakeBrowserRoot("Samples")
        self.user_library = _FakeBrowserRoot("User Library")
        self.packs = _FakeBrowserRoot("Packs")
        self.load_calls: list[_FakeBrowserItem] = []

    def load_item(self, item):
        self.load_calls.append(item)
        target = self._song.view.selected_track
        target.devices.append(_FakeDevice(class_display_name=item.name))


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
        self.start_playing_calls = 0
        self.stop_playing_calls = 0

    def start_playing(self):
        self.is_playing = True
        self.start_playing_calls += 1

    def stop_playing(self):
        self.is_playing = False
        self.stop_playing_calls += 1


class _FakeCtx:
    def __init__(self, song: _FakeSong):
        self._song = song
        self._application = _FakeApplication(song)
        self._live_state_lock = threading.RLock()

    @property
    def song(self):
        return self._song

    @property
    def application(self):
        return self._application

    @property
    def live_state_lock(self):
        return self._live_state_lock

    def run_on_main(self, fn):
        return fn()


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

    def __init__(self, port: int = 11001):
        self.port = port
        self.frames_received = 0


# --- fixtures --------------------------------------------------------


@pytest.fixture
def ctx_two_tracks_one_return() -> _FakeCtx:
    return _FakeCtx(_FakeSong(
        tracks=[_FakeTrack("Drums"), _FakeTrack("Bass")],
        returns=[_FakeTrack("A-Reverb")],
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
    # 2 tracks + 1 return + master = 4 instances; all loaded this sweep.
    assert resp.result["loaded_count"] == 4
    assert resp.result["existing_count"] == 0
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
    assert first.result["loaded_count"] == 4
    assert second.result["loaded_count"] == 0
    assert second.result["existing_count"] == 4
    # No duplicates on any surface.
    counts = [
        sum(1 for d in t.devices if d.class_display_name == "HallucinoteAnalyzer")
        for t in (
            ctx_two_tracks_one_return.song.tracks[0],
            ctx_two_tracks_one_return.song.tracks[1],
            ctx_two_tracks_one_return.song.return_tracks[0],
            ctx_two_tracks_one_return.song.master_track,
        )
    ]
    assert counts == [1, 1, 1, 1]


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
    # last_event_time fixture = 64 beats; stop_at_beat default uses it.
    assert manifest["stop_at_beat"] == 64
    assert len(manifest["tracks"]) == 2
    assert len(manifest["returns"]) == 1
    assert manifest["master"]["track_id"] == "master"
    # Each manifest entry has filename + absolute_path.
    for entry in manifest["tracks"] + manifest["returns"]:
        assert entry["filename"].endswith(".wav")
        assert Path(entry["absolute_path"]).is_absolute()


def test_render_sends_path_track_id_and_beat_window_via_osc(
    tmp_path, ctx_two_tracks_one_return, osc_factory, osc_sink, stub_sidecar,
):
    """For every analyzer, the handler must send (in this order):
    /path, /track_id, /start_at_beat, /stop_at_beat — all to the
    per-instance OSC port."""
    render_handlers.render_handler(
        ctx_two_tracks_one_return,
        output_dir=str(tmp_path / "c"),
        _osc_factory=osc_factory,
        _sidecar=stub_sidecar,
        _clock_source=lambda: 999.0,
    )
    # Group recorded OSC messages by (port, address).
    by_port: dict[int, list[str]] = {}
    for port, addr, _args in osc_sink:
        by_port.setdefault(port, []).append(addr)
    # 4 analyzers → 4 ports (deterministic).
    # Tracks: 11000 (T1), 11002 (T2). Return 1: 11100. Master: 11200.
    expected_ports = {11000, 11002, 11100, 11200}
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
            d for d in t.devices if d.class_display_name == "HallucinoteAnalyzer"
        )
        arm = next(p for p in analyzer.parameters if p.name == "Arm")
        assert arm.value == 0.0


def test_render_starts_and_stops_transport_exactly_once(
    tmp_path, ctx_two_tracks_one_return, osc_factory, stub_sidecar,
):
    render_handlers.render_handler(
        ctx_two_tracks_one_return,
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


def test_render_default_output_dir_uses_song_slug(
    tmp_path, monkeypatch, ctx_two_tracks_one_return, osc_factory, stub_sidecar,
):
    """No explicit output_dir → write under songs/<slug>/captures/<ts>/."""
    monkeypatch.chdir(tmp_path)
    result = render_handlers.render_handler(
        ctx_two_tracks_one_return,
        song_slug="my-song",
        _osc_factory=osc_factory,
        _sidecar=stub_sidecar,
        _clock_source=lambda: 999.0,
    )
    captures_dir = Path(result["captures_dir"])
    # Path is relative, resolves under tmp_path.
    assert captures_dir.parts[:3] == ("songs", "my-song", "captures")


def test_render_rejects_inverted_beat_window(
    tmp_path, ctx_two_tracks_one_return, osc_factory, stub_sidecar,
):
    with pytest.raises(ValueError, match="must be >"):
        render_handlers.render_handler(
            ctx_two_tracks_one_return,
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
        output_dir=str(tmp_path / "c1"),
        _osc_factory=osc_factory,
        _sidecar=stub_sidecar,
        _clock_source=lambda: 999.0,
    )
    b = render_handlers.render_handler(
        ctx_two_tracks_one_return,
        output_dir=str(tmp_path / "c2"),
        _osc_factory=osc_factory,
        _sidecar=stub_sidecar,
        _clock_source=lambda: 999.0,
    )
    names_a = sorted(t["filename"] for t in a["manifest"]["tracks"])
    names_b = sorted(t["filename"] for t in b["manifest"]["tracks"])
    assert names_a == names_b
