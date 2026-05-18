"""ableton_device schema + handler behavior."""
from __future__ import annotations

import threading
from typing import Any

import pytest

from hallucinote_mcp import schema
from hallucinote_mcp.dispatcher import dispatch
from hallucinote_mcp.testing import isolated_actions
from hallucinote_mcp.wire import Request


# ---------- Fakes ----------


class FakeParam:
    def __init__(
        self,
        name: str,
        value: float = 0.0,
        *,
        min: float = 0.0,
        max: float = 1.0,
        value_items: tuple[str, ...] | None = None,
    ):
        self.name = name
        self.value = value
        self.min = min
        self.max = max
        self.value_items = value_items
        self._str_for_value = lambda v: f"{v:.2f}"

    def str_for_value(self, v: float) -> str:
        if self.value_items:
            idx = int(v)
            if 0 <= idx < len(self.value_items):
                return self.value_items[idx]
        return self._str_for_value(v)


class FakeDevice:
    def __init__(
        self,
        name: str,
        class_name: str = "Operator",
        parameters: list[FakeParam] | None = None,
        *,
        is_drum_rack: bool = False,
    ):
        self.name = name
        self.class_name = class_name
        self.is_active = True
        self.parameters = tuple(parameters or [])
        self.can_have_chains = False
        self.sidechain_active = False
        self.input_routing_type = None
        self.selected_preset_index = 0
        self.selected_preset_name = "Default"
        if is_drum_rack:
            self.drum_pads = []


class FakeMixer:
    def __init__(self):
        self.volume = FakeParam("Volume", 0.85)
        self.panning = FakeParam("Panning", 0.0, min=-1.0, max=1.0)
        self.sends = []


class FakeTrack:
    def __init__(self, name: str = "T", devices: list[FakeDevice] | None = None):
        self.name = name
        self.devices = list(devices or [])
        self.mixer_device = FakeMixer()
        self._deleted: list[int] = []

    def delete_device(self, index_0based: int) -> None:
        self._deleted.append(index_0based)
        del self.devices[index_0based]


class FakeReturn(FakeTrack):
    pass


class FakeBrowserItem:
    """Mirrors Live's ``BrowserItem`` for tests.

    Live's real BrowserItem exposes ``name``, ``uri``, ``is_loadable``,
    ``is_folder``, ``children``. Browser walks recurse through children;
    ``application.browser.load_item(item)`` requires ``is_loadable`` and
    loads the item onto the track currently set as
    ``song.view.selected_track``.
    """

    def __init__(
        self,
        name: str,
        *,
        uri: str = "",
        is_loadable: bool = True,
        children: tuple["FakeBrowserItem", ...] = (),
    ):
        self.name = name
        self.uri = uri
        self.is_loadable = is_loadable
        self.is_folder = not is_loadable
        self.children = tuple(children)


class FakeBrowserRoot(FakeBrowserItem):
    """Browser root with a mutable children list — tests populate it."""

    def __init__(self, name: str):
        super().__init__(name, is_loadable=False, children=())
        self.children: list[FakeBrowserItem] = []


class FakeBrowser:
    """Mirrors Live 12.4 browser behavior for device-load tests.

    ``load_item(item)`` appends a fresh device to whatever track is
    currently set as ``song.view.selected_track``. Tests populate
    ``audio_effects.children``, ``drums.children``, etc. with
    ``FakeBrowserItem`` instances and then call the load action.
    """

    def __init__(self, song: "FakeSong"):
        self._song = song
        self.instruments = FakeBrowserRoot("Instruments")
        self.audio_effects = FakeBrowserRoot("Audio Effects")
        self.midi_effects = FakeBrowserRoot("MIDI Effects")
        self.drums = FakeBrowserRoot("Drums")
        self.plugins = FakeBrowserRoot("Plug-Ins")
        self.samples = FakeBrowserRoot("Samples")
        self.user_library = FakeBrowserRoot("User Library")
        self.packs = FakeBrowserRoot("Packs")
        self.load_calls: list[FakeBrowserItem] = []

    def load_item(self, item: FakeBrowserItem) -> None:
        self.load_calls.append(item)
        target = self._song.view.selected_track
        if target is None:
            raise RuntimeError(
                "FakeBrowser.load_item called with no selected_track set"
            )
        new_dev = FakeDevice(name=item.name, class_name=item.name)
        target.devices.append(new_dev)


class FakeApplication:
    def __init__(self, song: "FakeSong"):
        self.browser = FakeBrowser(song)


class FakeSongView:
    def __init__(self) -> None:
        self.selected_track: Any = None


class FakeSong:
    def __init__(
        self,
        tracks: list[FakeTrack] | None = None,
        returns: list[FakeReturn] | None = None,
    ):
        self.tracks = tracks or [FakeTrack("T1"), FakeTrack("T2")]
        self.return_tracks = returns or [FakeReturn("A-Rev")]
        self.view = FakeSongView()


class FakeCtx:
    def __init__(self, song: FakeSong | None = None):
        self._song = song or FakeSong()
        self._application = FakeApplication(self._song)
        self.run_on_main_calls = 0
        self._live_state_lock = threading.RLock()

    @property
    def song(self) -> FakeSong:
        return self._song

    @property
    def application(self) -> FakeApplication:
        return self._application

    @property
    def live_state_lock(self) -> threading.RLock:
        return self._live_state_lock

    def run_on_main(self, fn):
        self.run_on_main_calls += 1
        return fn()


def _add_browser_item(
    ctx: FakeCtx,
    root: str,
    name: str,
    *,
    uri: str = "",
    is_loadable: bool = True,
) -> FakeBrowserItem:
    """Helper: append a leaf BrowserItem under one of the browser roots."""
    item = FakeBrowserItem(name, uri=uri, is_loadable=is_loadable)
    getattr(ctx.application.browser, root).children.append(item)
    return item



@pytest.fixture()
def loaded_actions():
    with isolated_actions():
        yield schema


# ---------- Schema sanity ----------


_EXPECTED_DEVICE_ACTIONS = {
    "help", "list", "info", "load", "delete", "enable", "disable",
    "set_parameter", "get_parameters", "set_sidechain", "get_routing",
    "navigate_preset", "pad_info",
}


def test_device_registers_thirteen_actions(loaded_actions):
    names = {a.name for a in schema.actions_for("ableton_device")}
    assert names == _EXPECTED_DEVICE_ACTIONS


def test_device_help_lists_all_actions(loaded_actions):
    resp = dispatch(Request(tool="ableton_device", action="help"))
    assert resp.ok is True
    names = {a["name"] for a in resp.result["actions"]}
    assert names == _EXPECTED_DEVICE_ACTIONS - {"help"}


# ---------- list / info ----------


def _ctx_with_one_device() -> FakeCtx:
    dev = FakeDevice(
        name="Comp", class_name="Compressor2",
        parameters=[
            FakeParam("Threshold", -12.0, min=-60.0, max=0.0),
            FakeParam("Filter Type", 0.0, value_items=("Lowpass", "Highpass")),
        ],
    )
    return FakeCtx(FakeSong(tracks=[FakeTrack("Drums", devices=[dev])]))


def test_list_on_track(loaded_actions):
    ctx = _ctx_with_one_device()
    resp = dispatch(
        Request(
            tool="ableton_device", action="list",
            params={"track_index": 1},
        ),
        context=ctx,
    )
    assert resp.ok is True
    assert resp.result["parent_kind"] == "track"
    assert resp.result["track_index"] == 1
    assert [d["name"] for d in resp.result["devices"]] == ["Comp"]


def test_list_requires_exactly_one_of_track_or_return(loaded_actions):
    resp = dispatch(
        Request(tool="ableton_device", action="list", params={}),
        context=_ctx_with_one_device(),
    )
    assert resp.ok is False
    assert "track_index" in (resp.error or "")
    assert "return_index" in (resp.error or "")


def test_list_rejects_both_track_and_return(loaded_actions):
    resp = dispatch(
        Request(
            tool="ableton_device", action="list",
            params={"track_index": 1, "return_index": 1},
        ),
        context=_ctx_with_one_device(),
    )
    assert resp.ok is False
    assert "not both" in (resp.error or "")


def test_info_returns_parameter_count(loaded_actions):
    ctx = _ctx_with_one_device()
    resp = dispatch(
        Request(
            tool="ableton_device", action="info",
            params={"track_index": 1, "device_index": 1},
        ),
        context=ctx,
    )
    assert resp.ok is True
    assert resp.result["parameter_count"] == 2
    assert resp.result["class_name"] == "Compressor2"


def test_get_parameters_summary_vs_full(loaded_actions):
    ctx = _ctx_with_one_device()
    resp_s = dispatch(
        Request(
            tool="ableton_device", action="get_parameters",
            params={"track_index": 1, "device_index": 1, "detail": "summary"},
        ),
        context=ctx,
    )
    resp_f = dispatch(
        Request(
            tool="ableton_device", action="get_parameters",
            params={"track_index": 1, "device_index": 1, "detail": "full"},
        ),
        context=ctx,
    )
    assert resp_s.ok and resp_f.ok
    # Summary entries lack is_enum / value_items
    p0_summary = resp_s.result["parameters"][0]
    assert "is_enum" not in p0_summary
    assert "value_items" not in p0_summary
    # Full entries include them — and value_items appears only on enum params
    p_filter_full = resp_f.result["parameters"][1]
    assert p_filter_full["is_enum"] is True
    assert p_filter_full["value_items"] == ["Lowpass", "Highpass"]


# ---------- load / delete / enable / disable ----------


def test_load_appends_to_chain(loaded_actions):
    ctx = FakeCtx(FakeSong(tracks=[FakeTrack("T1")]))
    _add_browser_item(ctx, "audio_effects", "Compressor2",
                      uri="query:Compressor2")
    resp = dispatch(
        Request(
            tool="ableton_device", action="load",
            params={"track_index": 1, "kind": "Compressor2"},
        ),
        context=ctx,
    )
    assert resp.ok is True
    assert resp.result["device_index"] == 1
    assert resp.result["kind"] == "Compressor2"
    assert len(ctx.song.tracks[0].devices) == 1
    # Destination selection is how Live routes load_item.
    assert ctx.song.view.selected_track is ctx.song.tracks[0]
    # And the browser saw exactly one load_item call.
    assert len(ctx.application.browser.load_calls) == 1


def test_load_on_return(loaded_actions):
    ctx = FakeCtx(FakeSong(
        tracks=[FakeTrack("T1")],
        returns=[FakeReturn("Rev")],
    ))
    _add_browser_item(ctx, "audio_effects", "Reverb", uri="query:Reverb")
    resp = dispatch(
        Request(
            tool="ableton_device", action="load",
            params={"return_index": 1, "kind": "Reverb"},
        ),
        context=ctx,
    )
    assert resp.ok is True
    assert resp.result["parent_kind"] == "return"
    assert resp.result["return_index"] == 1
    assert len(ctx.song.return_tracks[0].devices) == 1
    assert ctx.song.view.selected_track is ctx.song.return_tracks[0]


def test_load_appends_to_existing_chain(loaded_actions):
    """Live appends to the END; existing devices stay in place."""
    track = FakeTrack("T1", devices=[FakeDevice("A"), FakeDevice("B")])
    ctx = FakeCtx(FakeSong(tracks=[track]))
    _add_browser_item(ctx, "audio_effects", "EQ8", uri="query:EQ8")
    resp = dispatch(
        Request(
            tool="ableton_device", action="load",
            params={"track_index": 1, "kind": "EQ8"},
        ),
        context=ctx,
    )
    assert resp.ok is True
    assert resp.result["device_index"] == 3
    assert [d.name for d in track.devices] == ["A", "B", "EQ8"]


def test_load_with_preset_uri_finds_by_uri_in_nested_folder(loaded_actions):
    """preset_uri match walks the full tree, including non-default roots."""
    ctx = FakeCtx(FakeSong(tracks=[FakeTrack("T1")]))
    # The falling-walking kit lives a few levels deep under Drums.
    kit_leaf = FakeBrowserItem(
        "My Kit", uri="query:Drums#FileId_5418", is_loadable=True,
    )
    kit_folder = FakeBrowserItem(
        "Kits", is_loadable=False, children=(kit_leaf,),
    )
    ctx.application.browser.drums.children.append(kit_folder)
    resp = dispatch(
        Request(
            tool="ableton_device", action="load",
            params={
                "track_index": 1, "kind": "DrumGroupDevice",
                "preset_uri": "query:Drums#FileId_5418",
            },
        ),
        context=ctx,
    )
    assert resp.ok is True
    assert resp.result["preset_uri"] == "query:Drums#FileId_5418"
    assert ctx.application.browser.load_calls[0].uri == \
        "query:Drums#FileId_5418"
    # The newly-appended device takes the BrowserItem's display name.
    assert ctx.song.tracks[0].devices[0].name == "My Kit"


def test_load_preset_uri_searches_plugins_root(loaded_actions):
    """preset_uri can resolve under plugins / user_library — kind-only cannot."""
    ctx = FakeCtx(FakeSong(tracks=[FakeTrack("T1")]))
    plugin = FakeBrowserItem(
        "Serum", uri="query:VST3#serum.vst3", is_loadable=True,
    )
    ctx.application.browser.plugins.children.append(plugin)
    resp = dispatch(
        Request(
            tool="ableton_device", action="load",
            params={
                "track_index": 1, "kind": "Serum",
                "preset_uri": "query:VST3#serum.vst3",
            },
        ),
        context=ctx,
    )
    assert resp.ok is True
    assert ctx.application.browser.load_calls[0].uri == \
        "query:VST3#serum.vst3"


def test_load_unknown_kind_errors_with_browser_hint(loaded_actions):
    ctx = FakeCtx(FakeSong(tracks=[FakeTrack("T1")]))
    resp = dispatch(
        Request(
            tool="ableton_device", action="load",
            params={"track_index": 1, "kind": "NoSuchDevice"},
        ),
        context=ctx,
    )
    assert resp.ok is False
    assert "no loadable browser item" in (resp.error or "")
    assert "NoSuchDevice" in (resp.error or "")
    assert "ableton_browser" in (resp.error or "")  # the recovery hint


def test_load_unknown_preset_uri_errors(loaded_actions):
    ctx = FakeCtx(FakeSong(tracks=[FakeTrack("T1")]))
    _add_browser_item(ctx, "audio_effects", "Compressor2",
                      uri="query:Compressor2")
    resp = dispatch(
        Request(
            tool="ableton_device", action="load",
            params={
                "track_index": 1, "kind": "Compressor2",
                "preset_uri": "query:Nonexistent",
            },
        ),
        context=ctx,
    )
    assert resp.ok is False
    assert "query:Nonexistent" in (resp.error or "")


def test_load_skips_non_loadable_folder_with_same_name(loaded_actions):
    """A folder named 'Compressor2' must NOT match — only is_loadable nodes."""
    ctx = FakeCtx(FakeSong(tracks=[FakeTrack("T1")]))
    decoy_folder = FakeBrowserItem(
        "Compressor2", is_loadable=False,
        children=(FakeBrowserItem(
            "Compressor2", uri="query:Compressor2", is_loadable=True,
        ),),
    )
    ctx.application.browser.audio_effects.children.append(decoy_folder)
    resp = dispatch(
        Request(
            tool="ableton_device", action="load",
            params={"track_index": 1, "kind": "Compressor2"},
        ),
        context=ctx,
    )
    assert resp.ok is True
    # The matched item is the loadable leaf, not the folder.
    assert ctx.application.browser.load_calls[0].is_loadable is True


def test_load_preset_uri_must_match_loadable_node(loaded_actions):
    """A non-loadable folder with a matching uri must NOT be picked —
    browser.load_item only accepts loadable BrowserItems. Without this
    gate, an empty preset_uri would resolve to a root and crash later
    with a misleading "did not append" error."""
    ctx = FakeCtx(FakeSong(tracks=[FakeTrack("T1")]))
    folder = FakeBrowserItem(
        "Vendor", uri="query:vendor", is_loadable=False,
        children=(FakeBrowserItem(
            "Synth", uri="query:vendor#synth", is_loadable=True,
        ),),
    )
    ctx.application.browser.plugins.children.append(folder)
    # preset_uri targets the FOLDER, not the leaf — should fail to resolve.
    resp = dispatch(
        Request(
            tool="ableton_device", action="load",
            params={
                "track_index": 1, "kind": "Synth",
                "preset_uri": "query:vendor",
            },
        ),
        context=ctx,
    )
    assert resp.ok is False
    assert "query:vendor" in (resp.error or "")
    # And no load_item was called.
    assert ctx.application.browser.load_calls == []


def test_load_position_param_is_unknown(loaded_actions):
    """Live 12.4 has no Track.move_device — position is not in V1 schema."""
    ctx = FakeCtx(FakeSong(tracks=[FakeTrack("T1")]))
    _add_browser_item(ctx, "audio_effects", "Compressor2",
                      uri="query:Compressor2")
    resp = dispatch(
        Request(
            tool="ableton_device", action="load",
            params={
                "track_index": 1, "kind": "Compressor2", "position": 1,
            },
        ),
        context=ctx,
    )
    assert resp.ok is False
    assert "position" in (resp.error or "")
    assert "unknown" in (resp.error or "").lower()


def test_load_without_application_errors(loaded_actions):
    """Missing application.browser surfaces a teaching error, not a crash."""
    ctx = FakeCtx(FakeSong(tracks=[FakeTrack("T1")]))
    ctx._application = None
    resp = dispatch(
        Request(
            tool="ableton_device", action="load",
            params={"track_index": 1, "kind": "Compressor2"},
        ),
        context=ctx,
    )
    assert resp.ok is False
    assert "application" in (resp.error or "").lower()


def test_load_no_chain_growth_is_runtime_error(loaded_actions):
    """If Live silently no-ops (e.g. instrument on master), we surface it."""
    ctx = FakeCtx(FakeSong(tracks=[FakeTrack("T1")]))
    _add_browser_item(ctx, "instruments", "Operator", uri="query:Operator")
    # Replace the browser's load_item with a no-op that doesn't grow the chain.
    ctx.application.browser.load_item = lambda item: \
        ctx.application.browser.load_calls.append(item)
    resp = dispatch(
        Request(
            tool="ableton_device", action="load",
            params={"track_index": 1, "kind": "Operator"},
        ),
        context=ctx,
    )
    assert resp.ok is False
    assert "did not append" in (resp.error or "")


def test_delete_removes_device(loaded_actions):
    track = FakeTrack("T1", devices=[FakeDevice("A"), FakeDevice("B")])
    ctx = FakeCtx(FakeSong(tracks=[track]))
    resp = dispatch(
        Request(
            tool="ableton_device", action="delete",
            params={"track_index": 1, "device_index": 1},
        ),
        context=ctx,
    )
    assert resp.ok is True
    assert [d.name for d in track.devices] == ["B"]


def test_enable_disable_toggle_is_active(loaded_actions):
    dev = FakeDevice("X")
    track = FakeTrack("T1", devices=[dev])
    ctx = FakeCtx(FakeSong(tracks=[track]))
    r1 = dispatch(
        Request(
            tool="ableton_device", action="disable",
            params={"track_index": 1, "device_index": 1},
        ),
        context=ctx,
    )
    assert r1.ok and dev.is_active is False
    r2 = dispatch(
        Request(
            tool="ableton_device", action="enable",
            params={"track_index": 1, "device_index": 1},
        ),
        context=ctx,
    )
    assert r2.ok and dev.is_active is True


# ---------- set_parameter ----------


def test_set_parameter_continuous_writes_value(loaded_actions):
    dev = FakeDevice("Comp", parameters=[
        FakeParam("Threshold", -12.0, min=-60.0, max=0.0),
    ])
    ctx = FakeCtx(FakeSong(tracks=[FakeTrack("T1", devices=[dev])]))
    resp = dispatch(
        Request(
            tool="ableton_device", action="set_parameter",
            params={
                "track_index": 1, "device_index": 1,
                "parameter_name": "Threshold", "value": "-24.0",
            },
        ),
        context=ctx,
    )
    assert resp.ok is True
    assert dev.parameters[0].value == -24.0


def test_set_parameter_continuous_out_of_range(loaded_actions):
    dev = FakeDevice("Comp", parameters=[
        FakeParam("Threshold", -12.0, min=-60.0, max=0.0),
    ])
    ctx = FakeCtx(FakeSong(tracks=[FakeTrack("T1", devices=[dev])]))
    resp = dispatch(
        Request(
            tool="ableton_device", action="set_parameter",
            params={
                "track_index": 1, "device_index": 1,
                "parameter_name": "Threshold", "value": "10.0",
            },
        ),
        context=ctx,
    )
    assert resp.ok is False
    assert "out of range" in (resp.error or "")


def test_set_parameter_enum_resolves_to_index(loaded_actions):
    dev = FakeDevice("Filter", parameters=[
        FakeParam("Filter Type", 0.0, value_items=("Lowpass", "Highpass", "Bandpass")),
    ])
    ctx = FakeCtx(FakeSong(tracks=[FakeTrack("T1", devices=[dev])]))
    resp = dispatch(
        Request(
            tool="ableton_device", action="set_parameter",
            params={
                "track_index": 1, "device_index": 1,
                "parameter_name": "Filter Type", "value": "Bandpass",
                "value_type": "enum",
            },
        ),
        context=ctx,
    )
    assert resp.ok is True
    assert dev.parameters[0].value == 2.0  # index of "Bandpass"


def test_set_parameter_enum_unknown_value_errors(loaded_actions):
    dev = FakeDevice("Filter", parameters=[
        FakeParam("Filter Type", 0.0, value_items=("Lowpass", "Highpass")),
    ])
    ctx = FakeCtx(FakeSong(tracks=[FakeTrack("T1", devices=[dev])]))
    resp = dispatch(
        Request(
            tool="ableton_device", action="set_parameter",
            params={
                "track_index": 1, "device_index": 1,
                "parameter_name": "Filter Type", "value": "Notch",
                "value_type": "enum",
            },
        ),
        context=ctx,
    )
    assert resp.ok is False
    assert "Notch" in (resp.error or "")
    # Lists what IS available
    assert "Lowpass" in (resp.error or "")


def test_set_parameter_enum_on_non_enum_errors(loaded_actions):
    dev = FakeDevice("Comp", parameters=[
        FakeParam("Threshold", -12.0, min=-60.0, max=0.0),
    ])
    ctx = FakeCtx(FakeSong(tracks=[FakeTrack("T1", devices=[dev])]))
    resp = dispatch(
        Request(
            tool="ableton_device", action="set_parameter",
            params={
                "track_index": 1, "device_index": 1,
                "parameter_name": "Threshold", "value": "Lowpass",
                "value_type": "enum",
            },
        ),
        context=ctx,
    )
    assert resp.ok is False
    assert "not an enum" in (resp.error or "")


def test_set_parameter_unknown_name(loaded_actions):
    dev = FakeDevice("Comp", parameters=[FakeParam("Threshold", -12.0)])
    ctx = FakeCtx(FakeSong(tracks=[FakeTrack("T1", devices=[dev])]))
    resp = dispatch(
        Request(
            tool="ableton_device", action="set_parameter",
            params={
                "track_index": 1, "device_index": 1,
                "parameter_name": "Bogus", "value": "0.5",
            },
        ),
        context=ctx,
    )
    assert resp.ok is False
    assert "Bogus" in (resp.error or "")
    assert "Threshold" in (resp.error or "")  # lists what's available


# ---------- set_sidechain ----------


def test_set_sidechain_enabled_with_source(loaded_actions):
    class _Routing:
        def __init__(self, name):
            self.display_name = name

    comp = FakeDevice("Comp", class_name="Compressor2",
                      parameters=[FakeParam("SC Gain", 0.0, min=-24.0, max=24.0)])
    comp.available_input_routing_types = [_Routing("Drums"), _Routing("Bass")]
    drums = FakeTrack("Drums", devices=[comp])
    bass = FakeTrack("Bass")
    ctx = FakeCtx(FakeSong(tracks=[drums, bass]))
    resp = dispatch(
        Request(
            tool="ableton_device", action="set_sidechain",
            params={
                "track_index": 1, "device_index": 1,
                "enabled": True, "source_track_index": 2, "gain_db": 3.0,
            },
        ),
        context=ctx,
    )
    assert resp.ok is True
    assert comp.sidechain_active is True
    assert comp.parameters[0].value == 3.0


def test_set_sidechain_disabled_clears_active(loaded_actions):
    comp = FakeDevice("Comp", class_name="Compressor2")
    comp.sidechain_active = True
    track = FakeTrack("T1", devices=[comp])
    ctx = FakeCtx(FakeSong(tracks=[track]))
    resp = dispatch(
        Request(
            tool="ableton_device", action="set_sidechain",
            params={"track_index": 1, "device_index": 1, "enabled": False},
        ),
        context=ctx,
    )
    assert resp.ok is True
    assert comp.sidechain_active is False


def test_set_sidechain_rejects_non_compressor(loaded_actions):
    eq = FakeDevice("EQ", class_name="EQ8")
    ctx = FakeCtx(FakeSong(tracks=[FakeTrack("T1", devices=[eq])]))
    resp = dispatch(
        Request(
            tool="ableton_device", action="set_sidechain",
            params={
                "track_index": 1, "device_index": 1, "enabled": True,
                "source_track_index": 1,
            },
        ),
        context=ctx,
    )
    assert resp.ok is False
    assert "Compressor" in (resp.error or "")


# ---------- navigate_preset / pad_info ----------


def test_navigate_preset_current_reads(loaded_actions):
    dev = FakeDevice("Op")
    dev.selected_preset_index = 5
    dev.selected_preset_name = "Pad"
    ctx = FakeCtx(FakeSong(tracks=[FakeTrack("T1", devices=[dev])]))
    resp = dispatch(
        Request(
            tool="ableton_device", action="navigate_preset",
            params={"track_index": 1, "device_index": 1, "direction": "current"},
        ),
        context=ctx,
    )
    assert resp.ok is True
    assert resp.result["preset_index"] == 5
    assert resp.result["preset_name"] == "Pad"


def test_pad_info_rejects_non_drum_rack(loaded_actions):
    op = FakeDevice("Op")  # not a drum rack
    ctx = FakeCtx(FakeSong(tracks=[FakeTrack("T1", devices=[op])]))
    resp = dispatch(
        Request(
            tool="ableton_device", action="pad_info",
            params={"track_index": 1, "device_index": 1},
        ),
        context=ctx,
    )
    assert resp.ok is False
    assert "drum rack" in (resp.error or "").lower()


# ---------- run_on_main discipline ----------


def test_device_execution_marshals_to_main_thread(loaded_actions):
    ctx = _ctx_with_one_device()
    dispatch(
        Request(
            tool="ableton_device", action="info",
            params={"track_index": 1, "device_index": 1},
        ),
        context=ctx,
    )
    assert ctx.run_on_main_calls == 1
