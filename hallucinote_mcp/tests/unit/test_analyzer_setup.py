"""Tests for hallucinote_mcp.analyzer.setup — silent analyzer sweep."""
from __future__ import annotations

import threading
from typing import Any

import pytest

from hallucinote_mcp.analyzer import setup as analyzer_setup
from hallucinote_mcp.analyzer.setup import (
    ANALYZER_DEVICE_NAME,
    ensure_analyzers_loaded,
    track_id_for_surface,
)


# --- minimal Live fakes (mirrors test_actions_device.py's surface) ---


class _FakeParam:
    def __init__(
        self,
        name: str,
        value: float = 0.0,
        *,
        min: float = 0.0,
        max: float = 1.0,
    ):
        self.name = name
        self.value = value
        self.min = min
        self.max = max


def _analyzer_params() -> list[_FakeParam]:
    """The HallucinoteAnalyzer surfaces these Live params (see spec)."""
    return [
        _FakeParam("Device On", 1.0),
        _FakeParam("Arm", 0.0),
        _FakeParam("Port", 11000.0, min=11000.0, max=11400.0),
        _FakeParam("EmitPort", 11201.0, min=11000.0, max=11400.0),
        _FakeParam("Emit", 1.0),
    ]


class _FakeDevice:
    """A Live device. ``class_display_name`` is what M4L surfaces as the
    .amxd filename; a HallucinoteAnalyzer instance has class_display_name
    equal to ``HallucinoteAnalyzer``. Other devices set it to their
    actual Live class display (Compressor, Reverb, etc.)."""

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
    """Tracks each load_item call and appends a fresh device to whatever
    track is selected. The selected track is the parent surface
    that ``load_handler`` is targeting (which calls
    ``song.view.selected_track = parent`` before ``browser.load_item``)."""

    def __init__(self, song: "_FakeSong", *, item_name: str = ANALYZER_DEVICE_NAME):
        self._song = song
        self.audio_effects = _FakeBrowserRoot("Audio Effects")
        # Pre-populate with the analyzer item so load_handler's name-walk
        # finds it.
        self._item = _FakeBrowserItem(item_name)
        self.audio_effects.children.append(self._item)
        # Other roots load_handler walks in `_BROWSER_URI_ROOTS`.
        self.instruments = _FakeBrowserRoot("Instruments")
        self.midi_effects = _FakeBrowserRoot("MIDI Effects")
        self.drums = _FakeBrowserRoot("Drums")
        self.plugins = _FakeBrowserRoot("Plug-Ins")
        self.samples = _FakeBrowserRoot("Samples")
        self.user_library = _FakeBrowserRoot("User Library")
        self.packs = _FakeBrowserRoot("Packs")
        self.load_calls: list[_FakeBrowserItem] = []

    def load_item(self, item: _FakeBrowserItem) -> None:
        self.load_calls.append(item)
        target = self._song.view.selected_track
        new_dev = _FakeDevice(class_display_name=item.name)
        target.devices.append(new_dev)


class _FakeApplication:
    def __init__(self, song: "_FakeSong"):
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
    ):
        self.tracks = tracks or []
        self.return_tracks = returns or []
        self.master_track = master or _FakeTrack("Master")
        self.view = _FakeSongView()


class _FakeCtx:
    def __init__(self, song: _FakeSong):
        self._song = song
        self._application = _FakeApplication(song)
        self._live_state_lock = threading.RLock()

    @property
    def song(self) -> _FakeSong:
        return self._song

    @property
    def application(self) -> _FakeApplication:
        return self._application

    @property
    def live_state_lock(self) -> Any:
        return self._live_state_lock

    def run_on_main(self, fn):
        return fn()


# --- track_id derivation ---------------------------------------------


def test_track_id_for_surface_is_structurally_stable():
    assert track_id_for_surface("track", 1) == "track:1"
    assert track_id_for_surface("track", 7) == "track:7"
    assert track_id_for_surface("return", 2) == "return:2"
    assert track_id_for_surface("master", 0) == "master"


def test_track_id_for_surface_rejects_unknown_kind():
    with pytest.raises(ValueError, match="unknown surface_kind"):
        track_id_for_surface("group", 1)


# --- empty sweep on bare song ----------------------------------------


def test_sweep_loads_analyzer_on_master_only_when_no_other_surfaces():
    """A song with no tracks + no returns + just master still gets one
    analyzer on master."""
    ctx = _FakeCtx(_FakeSong())
    layout = ensure_analyzers_loaded(ctx)
    assert len(layout.instances) == 1
    inst = layout.instances[0]
    assert inst.surface_kind == "master"
    assert inst.track_id == "master"
    assert inst.was_loaded is True
    # Loaded into a fresh chain at position 1.
    assert inst.device_index == 1
    assert len(ctx.song.master_track.devices) == 1


# --- idempotency: the most load-bearing property ---------------------


def test_sweep_is_idempotent_no_duplicates():
    """Two consecutive sweeps must produce identical layouts and not
    add a second analyzer to any surface."""
    ctx = _FakeCtx(_FakeSong(
        tracks=[_FakeTrack("Drums"), _FakeTrack("Bass")],
        returns=[_FakeTrack("A-Reverb")],
    ))

    first = ensure_analyzers_loaded(ctx)
    assert first.loaded_count == 4  # 2 tracks + 1 return + master
    assert first.existing_count == 0

    # All four surfaces should now have exactly one analyzer each.
    chain_counts_after_first = [
        len([d for d in t.devices if d.class_display_name == ANALYZER_DEVICE_NAME])
        for t in (
            ctx.song.tracks[0], ctx.song.tracks[1],
            ctx.song.return_tracks[0], ctx.song.master_track,
        )
    ]
    assert chain_counts_after_first == [1, 1, 1, 1]

    second = ensure_analyzers_loaded(ctx)
    assert second.loaded_count == 0
    assert second.existing_count == 4

    chain_counts_after_second = [
        len([d for d in t.devices if d.class_display_name == ANALYZER_DEVICE_NAME])
        for t in (
            ctx.song.tracks[0], ctx.song.tracks[1],
            ctx.song.return_tracks[0], ctx.song.master_track,
        )
    ]
    # Still exactly one each — no duplicates from the second sweep.
    assert chain_counts_after_second == [1, 1, 1, 1]

    # Port assignment is the same across sweeps.
    assert first.by_track_id().keys() == second.by_track_id().keys()
    for tid, first_inst in first.by_track_id().items():
        assert second.by_track_id()[tid].osc_port == first_inst.osc_port


def test_sweep_detects_existing_analyzer_does_not_reload():
    """If the analyzer is already present on a surface, the sweep
    records its existing index and does NOT re-load."""
    existing = _FakeDevice(class_display_name=ANALYZER_DEVICE_NAME)
    eq = _FakeDevice(class_display_name="EQ Eight")
    ctx = _FakeCtx(_FakeSong(
        tracks=[_FakeTrack("Drums", devices=[eq, existing])],
    ))

    layout = ensure_analyzers_loaded(ctx)
    by_surface = layout.by_surface()
    track_inst = by_surface[("track", 1)]
    assert track_inst.was_loaded is False
    # Found at position 2 (1-based), not 1 — order in the chain matters.
    assert track_inst.device_index == 2
    # Master still got a fresh load.
    master_inst = by_surface[("master", 0)]
    assert master_inst.was_loaded is True
    # Track chain unchanged.
    assert len(ctx.song.tracks[0].devices) == 2


# --- port + track_id assignment -------------------------------------


def test_port_assignment_is_deterministic_per_surface():
    """Port numbers must be a pure function of surface address —
    repeating the sweep recovers the same ports without needing prior
    state."""
    ctx = _FakeCtx(_FakeSong(
        tracks=[_FakeTrack("T1"), _FakeTrack("T2"), _FakeTrack("T3")],
        returns=[_FakeTrack("A-Rev"), _FakeTrack("B-Del")],
    ))
    layout = ensure_analyzers_loaded(ctx)
    by_tid = layout.by_track_id()
    # Tracks: 11000, 11001, 11002 (stride 1).
    assert by_tid["track:1"].osc_port == 11000
    assert by_tid["track:2"].osc_port == 11001
    assert by_tid["track:3"].osc_port == 11002
    # Returns: 11100, 11101.
    assert by_tid["return:1"].osc_port == 11100
    assert by_tid["return:2"].osc_port == 11101
    # Master: 11200.
    assert by_tid["master"].osc_port == 11200
    # All share the same emit port by default (11201 — past master).
    emit_ports = {inst.osc_emit_port for inst in layout.instances}
    assert emit_ports == {11201}


def test_sweep_writes_per_instance_port_via_live_param():
    """The deterministic per-instance port is only effective if it's
    written to the analyzer's `Port` Live parameter. Two analyzers
    listening on the same port would both receive every `/path` —
    which would cross-contaminate render targets."""
    ctx = _FakeCtx(_FakeSong(
        tracks=[_FakeTrack("T1"), _FakeTrack("T2")],
    ))
    ensure_analyzers_loaded(ctx)

    def _param_value(track, pname):
        analyzer = next(
            d for d in track.devices
            if d.class_display_name == ANALYZER_DEVICE_NAME
        )
        return next(p for p in analyzer.parameters if p.name == pname).value

    # Track 1 → 11000, Track 2 → 11001 (stride 1).
    assert _param_value(ctx.song.tracks[0], "Port") == 11000.0
    assert _param_value(ctx.song.tracks[1], "Port") == 11001.0
    # Both share the default emit port.
    assert _param_value(ctx.song.tracks[0], "EmitPort") == 11201.0
    assert _param_value(ctx.song.tracks[1], "EmitPort") == 11201.0
    # Master at 11200.
    assert _param_value(ctx.song.master_track, "Port") == 11200.0


def test_sweep_custom_emit_port_propagates():
    ctx = _FakeCtx(_FakeSong(tracks=[_FakeTrack("T1")]))
    # Stay within the patch's documented Port range (11000-11400 in the
    # test fake; the real spec uses 11000-11100, but that's a config
    # decision per Live install — see HallucinoteAnalyzer.amxd.spec.md).
    layout = ensure_analyzers_loaded(ctx, emit_port=11250)
    for inst in layout.instances:
        assert inst.osc_emit_port == 11250


# --- surface filtering ------------------------------------------------


def test_sweep_skips_group_tracks():
    """Group tracks (is_foldable=True) are routing aggregations of their
    members. Skipping them avoids double-counting audio at render time."""
    group = _FakeTrack("Drums Group", is_foldable=True)
    leaf = _FakeTrack("Kick")
    ctx = _FakeCtx(_FakeSong(tracks=[group, leaf]))
    layout = ensure_analyzers_loaded(ctx)
    surfaces = {(i.surface_kind, i.surface_index) for i in layout.instances}
    # Track index 2 (the leaf) is captured; track index 1 (the group) is not.
    assert ("track", 2) in surfaces
    assert ("track", 1) not in surfaces


def test_sweep_skips_tracks_with_no_audio_output():
    ctx = _FakeCtx(_FakeSong(tracks=[
        _FakeTrack("Mute Stub", has_audio_output=False),
        _FakeTrack("Audio Track"),
    ]))
    layout = ensure_analyzers_loaded(ctx)
    surfaces = {(i.surface_kind, i.surface_index) for i in layout.instances}
    assert ("track", 2) in surfaces
    assert ("track", 1) not in surfaces


# --- layout helpers ---------------------------------------------------


def test_layout_helpers_round_trip_instances():
    ctx = _FakeCtx(_FakeSong(
        tracks=[_FakeTrack("T")],
        returns=[_FakeTrack("R")],
    ))
    layout = ensure_analyzers_loaded(ctx)
    by_tid = layout.by_track_id()
    by_surface = layout.by_surface()
    assert by_tid["track:1"] is by_surface[("track", 1)]
    assert by_tid["return:1"] is by_surface[("return", 1)]
    assert by_tid["master"] is by_surface[("master", 0)]
    assert layout.loaded_count + layout.existing_count == len(layout.instances)
