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
        # Live 12.4 raises ``RuntimeError: Only quantized parameters have
        # value items`` when ``value_items`` is read on a continuous
        # parameter. Mirror that strictly so handlers that read it
        # unguarded fail at test time (Wave-2 W2-9 root cause).
        self.is_quantized = value_items is not None
        self._value_items = value_items
        self._str_for_value = lambda v: f"{v:.2f}"

    @property
    def value_items(self) -> tuple[str, ...]:
        if not self.is_quantized:
            raise RuntimeError("Only quantized parameters have value items")
        return self._value_items or ()

    def str_for_value(self, v: float) -> str:
        if self.is_quantized and self._value_items:
            idx = int(v)
            if 0 <= idx < len(self._value_items):
                return self._value_items[idx]
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
        self.class_display_name = class_name
        self.is_active = True
        self.parameters = tuple(parameters or [])
        self.can_have_chains = False
        self.can_have_drum_pads = False
        # input_routing_type / available_input_routing_types intentionally
        # absent — devices opt in by setting these on the instance. Mirrors
        # the W6-E-1 real-Live finding that Glue / Gate / Multiband Dynamics
        # don't expose the API at all on their Device class.
        self.selected_preset_index = 0
        self.selected_preset_name = "Default"
        if is_drum_rack:
            self.drum_pads = []
            self.can_have_drum_pads = True


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
    "set_parameter", "get_parameters",
    # W6-E-2 capability-probing primitives + retained legacy-named actions:
    "capabilities", "set_input_routing", "get_input_routing",
    "set_sidechain", "get_routing",
    "navigate_preset", "pad_info",
}


def test_device_registers_expected_actions(loaded_actions):
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


def test_load_translates_class_name_to_display_name(loaded_actions):
    """Wave-2 W2-7: real Live exposes ``device.class_name='Compressor2'`` but
    the browser indexes it as ``'Compressor'``. Capture → push reaches the
    handler with the class name; the handler falls back to the
    device_names translation table when the direct name match misses.
    """
    ctx = FakeCtx(FakeSong(tracks=[FakeTrack("T1")]))
    # Browser exposes ONLY the display name "Compressor" — no node named
    # "Compressor2" exists. Without translation, this load would fail.
    _add_browser_item(ctx, "audio_effects", "Compressor", uri="query:Compressor")
    resp = dispatch(
        Request(
            tool="ableton_device", action="load",
            params={"track_index": 1, "kind": "Compressor2"},
        ),
        context=ctx,
    )
    assert resp.ok is True, (
        f"Expected translation 'Compressor2' → 'Compressor' to succeed. "
        f"Response: {resp.to_dict()}"
    )
    # The result preserves the requested kind (caller's identity).
    assert resp.result["kind"] == "Compressor2"
    # And the device IS loaded.
    assert len(ctx.song.tracks[0].devices) == 1


def test_load_translates_drum_group_device_to_drum_rack(loaded_actions):
    """Sample table coverage: DrumGroupDevice → Drum Rack — exercised by
    every drum kit push (falling-walking has one).
    """
    ctx = FakeCtx(FakeSong(tracks=[FakeTrack("T1")]))
    _add_browser_item(ctx, "drums", "Drum Rack", uri="query:DrumRack")
    resp = dispatch(
        Request(
            tool="ableton_device", action="load",
            params={"track_index": 1, "kind": "DrumGroupDevice"},
        ),
        context=ctx,
    )
    assert resp.ok is True
    assert resp.result["kind"] == "DrumGroupDevice"


def test_load_passes_through_unmapped_class_name(loaded_actions):
    """For names not in the translation table (third-party plugins,
    Live built-ins that match in both name spaces), the original behavior
    is preserved — direct display-name match.
    """
    ctx = FakeCtx(FakeSong(tracks=[FakeTrack("T1")]))
    _add_browser_item(ctx, "audio_effects", "Reverb", uri="query:Reverb")
    resp = dispatch(
        Request(
            tool="ableton_device", action="load",
            params={"track_index": 1, "kind": "Reverb"},
        ),
        context=ctx,
    )
    assert resp.ok is True
    assert resp.result["kind"] == "Reverb"


def test_load_unknown_kind_error_mentions_translation(loaded_actions):
    """When the translation table has a mapping but the browser still lacks
    the translated node, the error reports BOTH the original kind and the
    translated display name so the user knows we tried both paths.
    """
    ctx = FakeCtx(FakeSong(tracks=[FakeTrack("T1")]))
    # No "Compressor" or "Compressor2" node in the browser.
    resp = dispatch(
        Request(
            tool="ableton_device", action="load",
            params={"track_index": 1, "kind": "Compressor2"},
        ),
        context=ctx,
    )
    assert resp.ok is False
    assert "Compressor2" in (resp.error or "")
    assert "Compressor" in (resp.error or "")  # translated form mentioned
    assert "device_names" in (resp.error or "")  # hint at the table


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
    """Fallback path: device without a 'Device On' parameter falls through
    to the direct is_active attribute write. Preserves the prior contract.
    """
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


def test_enable_disable_uses_device_on_parameter(loaded_actions):
    """Wave-2 W2-C / B-12: Live 12.4 exposes ``is_active`` as read-only on
    at least CompressorDevice. The writable surface is the 'Device On'
    parameter at parameters[0]. The handler must write there, not to the
    raw attribute. Verified by asserting the parameter's value changed
    AND the (deliberately untouched) is_active mock stayed at its
    initial state to prove the param path won.
    """
    device_on = FakeParam("Device On", value=1.0, value_items=("Off", "On"))
    dev = FakeDevice(
        "Comp", parameters=[device_on, FakeParam("Threshold", 0.5)],
    )
    track = FakeTrack("T1", devices=[dev])
    ctx = FakeCtx(FakeSong(tracks=[track]))
    initial_is_active = dev.is_active

    r1 = dispatch(
        Request(
            tool="ableton_device", action="disable",
            params={"track_index": 1, "device_index": 1},
        ),
        context=ctx,
    )
    assert r1.ok
    assert device_on.value == 0.0, (
        f"disable should have written 0.0 to the 'Device On' parameter "
        f"(got {device_on.value})"
    )
    # is_active stayed at its mock-initial value — the handler did NOT
    # fall back to the read-only attribute.
    assert dev.is_active == initial_is_active

    r2 = dispatch(
        Request(
            tool="ableton_device", action="enable",
            params={"track_index": 1, "device_index": 1},
        ),
        context=ctx,
    )
    assert r2.ok
    assert device_on.value == 1.0


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


# ---------- capability-probing primitives (W6-E-2) ----------
#
# The previous tests pinned a Compressor-class whitelist + a fictional
# sidechain_active attribute. W6-E-1 empirical probing (real-Live, 2026-
# 05-19) found that (a) sidechain enable is the 'S/C On' parameter, not
# any device attribute; (b) source routing uses Live's unified
# input_routing_* API, which Glue / Gate / Multiband Dynamics don't
# expose; (c) third-party plugins follow the same patterns when they
# declare sidechain inputs. The new primitives probe capabilities
# instead of registering classes.


class _Routing:
    """Mirrors Live's RoutingType / RoutingChannel — display_name +
    category + attached_object. Tests only need display_name."""

    def __init__(self, name: str, category: int = 0):
        self.display_name = name
        self.category = category
        self.attached_object = None


def _compressor_with_routing() -> FakeDevice:
    """A faked Compressor2 with the full sidechain surface: S/C params
    plus the input_routing_* API."""
    comp = FakeDevice(
        "Comp",
        class_name="Compressor2",
        parameters=[
            FakeParam("Device On", 1.0),
            FakeParam("Threshold", 0.85),
            FakeParam("S/C On", 0.0),
            FakeParam("S/C Gain", 0.4, min=-24.0, max=24.0),
            FakeParam("S/C Mix", 1.0),
        ],
    )
    comp.input_routing_type = _Routing("No Input")
    comp.input_routing_channel = _Routing("Post FX")
    comp.available_input_routing_types = [
        _Routing("1-Drums"), _Routing("2-Bass"), _Routing("Main"), _Routing("No Input"),
    ]
    comp.available_input_routing_channels = [
        _Routing("Pre FX"), _Routing("Post FX"), _Routing("Post Mixer"),
    ]
    return comp


def _glue_compressor_without_routing() -> FakeDevice:
    """A faked Glue Compressor: has S/C params, NO input_routing_*."""
    return FakeDevice(
        "Glue",
        class_name="GlueCompressor",
        parameters=[
            FakeParam("Device On", 1.0),
            FakeParam("Threshold", 0.0),
            FakeParam("S/C On", 0.0),
            FakeParam("S/C Gain", 0.4),
            FakeParam("S/C Mix", 1.0),
        ],
    )


# ---------- capabilities ----------


def test_capabilities_compressor_reports_full_surface(loaded_actions):
    comp = _compressor_with_routing()
    ctx = FakeCtx(FakeSong(tracks=[FakeTrack("T1", devices=[comp])]))
    resp = dispatch(
        Request(
            tool="ableton_device", action="capabilities",
            params={"track_index": 1, "device_index": 1},
        ),
        context=ctx,
    )
    assert resp.ok is True, resp.error
    r = resp.result
    assert r["class_name"] == "Compressor2"
    assert r["has_input_routing"] is True
    assert r["is_third_party_plugin"] is False
    # Sidechain-shaped params surfaced by substring match.
    assert "S/C On" in r["sidechain_param_names"]
    assert "S/C Gain" in r["sidechain_param_names"]
    assert "S/C Mix" in r["sidechain_param_names"]
    # Non-sidechain params don't sneak in.
    assert "Threshold" not in r["sidechain_param_names"]


def test_capabilities_glue_reports_no_input_routing(loaded_actions):
    """Glue Compressor exposes S/C params but no input_routing_* API —
    capabilities snapshot reflects that asymmetry honestly."""
    glue = _glue_compressor_without_routing()
    ctx = FakeCtx(FakeSong(tracks=[FakeTrack("T1", devices=[glue])]))
    resp = dispatch(
        Request(
            tool="ableton_device", action="capabilities",
            params={"track_index": 1, "device_index": 1},
        ),
        context=ctx,
    )
    assert resp.ok is True
    assert resp.result["has_input_routing"] is False
    assert "S/C On" in resp.result["sidechain_param_names"]


def test_capabilities_third_party_plugin_flag(loaded_actions):
    plugin = FakeDevice("My Plugin", class_name="PluginDevice")
    ctx = FakeCtx(FakeSong(tracks=[FakeTrack("T1", devices=[plugin])]))
    resp = dispatch(
        Request(
            tool="ableton_device", action="capabilities",
            params={"track_index": 1, "device_index": 1},
        ),
        context=ctx,
    )
    assert resp.ok is True
    assert resp.result["is_third_party_plugin"] is True


# ---------- set_input_routing ----------


def test_set_input_routing_finds_by_display_name(loaded_actions):
    comp = _compressor_with_routing()
    ctx = FakeCtx(FakeSong(tracks=[FakeTrack("T1", devices=[comp])]))
    resp = dispatch(
        Request(
            tool="ableton_device", action="set_input_routing",
            params={
                "track_index": 1, "device_index": 1,
                "type_display_name": "1-Drums",
            },
        ),
        context=ctx,
    )
    assert resp.ok is True, resp.error
    assert comp.input_routing_type.display_name == "1-Drums"
    assert resp.result["input_routing_type"] == "1-Drums"


def test_set_input_routing_with_channel(loaded_actions):
    comp = _compressor_with_routing()
    ctx = FakeCtx(FakeSong(tracks=[FakeTrack("T1", devices=[comp])]))
    resp = dispatch(
        Request(
            tool="ableton_device", action="set_input_routing",
            params={
                "track_index": 1, "device_index": 1,
                "type_display_name": "2-Bass",
                "channel_display_name": "Pre FX",
            },
        ),
        context=ctx,
    )
    assert resp.ok is True
    assert comp.input_routing_type.display_name == "2-Bass"
    assert comp.input_routing_channel.display_name == "Pre FX"


def test_set_input_routing_unknown_type_lists_available(loaded_actions):
    comp = _compressor_with_routing()
    ctx = FakeCtx(FakeSong(tracks=[FakeTrack("T1", devices=[comp])]))
    resp = dispatch(
        Request(
            tool="ableton_device", action="set_input_routing",
            params={
                "track_index": 1, "device_index": 1,
                "type_display_name": "Nonexistent",
            },
        ),
        context=ctx,
    )
    assert resp.ok is False
    err = resp.error or ""
    assert "1-Drums" in err and "2-Bass" in err  # available list surfaced


def test_set_input_routing_missing_api_raises_teaching_error(loaded_actions):
    """Glue Compressor (and the other older natives, and older plugins)
    don't expose input_routing_* — the call must fail loudly with a
    workaround pointer, not silently no-op."""
    glue = _glue_compressor_without_routing()
    ctx = FakeCtx(FakeSong(tracks=[FakeTrack("T1", devices=[glue])]))
    resp = dispatch(
        Request(
            tool="ableton_device", action="set_input_routing",
            params={
                "track_index": 1, "device_index": 1,
                "type_display_name": "1-Drums",
            },
        ),
        context=ctx,
    )
    assert resp.ok is False
    err = resp.error or ""
    assert "GlueCompressor" in err
    assert "UI configuration" in err or "set the sidechain source manually" in err.lower()


# ---------- get_input_routing ----------


def test_get_input_routing_returns_current_and_available(loaded_actions):
    comp = _compressor_with_routing()
    ctx = FakeCtx(FakeSong(tracks=[FakeTrack("T1", devices=[comp])]))
    resp = dispatch(
        Request(
            tool="ableton_device", action="get_input_routing",
            params={"track_index": 1, "device_index": 1},
        ),
        context=ctx,
    )
    assert resp.ok is True
    r = resp.result
    assert r["has_input_routing"] is True
    assert r["current_type"] == "No Input"
    assert "1-Drums" in r["available_types"]
    assert "Post FX" in r["available_channels"]


def test_get_input_routing_no_api_returns_false_no_raise(loaded_actions):
    """Symmetric with capabilities — get_ should not raise on devices
    without the API; it returns has_input_routing=False so the agent
    knows the surface is absent without a try/except."""
    glue = _glue_compressor_without_routing()
    ctx = FakeCtx(FakeSong(tracks=[FakeTrack("T1", devices=[glue])]))
    resp = dispatch(
        Request(
            tool="ableton_device", action="get_input_routing",
            params={"track_index": 1, "device_index": 1},
        ),
        context=ctx,
    )
    assert resp.ok is True
    assert resp.result["has_input_routing"] is False
    assert "current_type" not in resp.result


# ---------- set_sidechain (post-W6-E-2: no class whitelist) ----------


def test_set_sidechain_enables_via_canonical_param(loaded_actions):
    """No more class whitelist — set_sidechain works on ANY device that
    exposes the canonical S/C On parameter (Compressor, Compressor2,
    Glue, Gate, Multiband Dynamics, third-party plugins matching the
    naming hints)."""
    comp = _compressor_with_routing()
    ctx = FakeCtx(FakeSong(tracks=[FakeTrack("T1", devices=[comp])]))
    resp = dispatch(
        Request(
            tool="ableton_device", action="set_sidechain",
            params={
                "track_index": 1, "device_index": 1, "enabled": True,
                "source_display_name": "1-Drums", "gain_db": 3.0,
            },
        ),
        context=ctx,
    )
    assert resp.ok is True, resp.error
    sc_on = next(p for p in comp.parameters if p.name == "S/C On")
    sc_gain = next(p for p in comp.parameters if p.name == "S/C Gain")
    assert sc_on.value == 1.0
    assert sc_gain.value == 3.0
    assert comp.input_routing_type.display_name == "1-Drums"


def test_set_sidechain_works_on_glue_for_enable_only(loaded_actions):
    """Glue Compressor has S/C params but no input_routing_* — enable
    succeeds; source routing without a source_display_name doesn't
    attempt the routing primitive."""
    glue = _glue_compressor_without_routing()
    ctx = FakeCtx(FakeSong(tracks=[FakeTrack("T1", devices=[glue])]))
    resp = dispatch(
        Request(
            tool="ableton_device", action="set_sidechain",
            params={"track_index": 1, "device_index": 1, "enabled": True},
        ),
        context=ctx,
    )
    assert resp.ok is True, resp.error
    sc_on = next(p for p in glue.parameters if p.name == "S/C On")
    assert sc_on.value == 1.0


def test_set_sidechain_glue_with_source_falls_through_to_routing_error(loaded_actions):
    """Requesting source routing on a device without input_routing_*
    raises the teaching error from set_input_routing — but enable has
    ALREADY toggled (the call partially succeeds before the failure
    point). Documented behavior: the agent gets a precise error
    location, not a silent no-op."""
    glue = _glue_compressor_without_routing()
    ctx = FakeCtx(FakeSong(tracks=[FakeTrack("T1", devices=[glue])]))
    resp = dispatch(
        Request(
            tool="ableton_device", action="set_sidechain",
            params={
                "track_index": 1, "device_index": 1, "enabled": True,
                "source_display_name": "1-Drums",
            },
        ),
        context=ctx,
    )
    assert resp.ok is False
    assert "GlueCompressor" in (resp.error or "")
    # Enable still toggled before the routing failure.
    sc_on = next(p for p in glue.parameters if p.name == "S/C On")
    assert sc_on.value == 1.0


def test_set_sidechain_disable_via_canonical_param(loaded_actions):
    comp = _compressor_with_routing()
    sc_on = next(p for p in comp.parameters if p.name == "S/C On")
    sc_on.value = 1.0  # start enabled
    ctx = FakeCtx(FakeSong(tracks=[FakeTrack("T1", devices=[comp])]))
    resp = dispatch(
        Request(
            tool="ableton_device", action="set_sidechain",
            params={"track_index": 1, "device_index": 1, "enabled": False},
        ),
        context=ctx,
    )
    assert resp.ok is True
    assert sc_on.value == 0.0


def test_set_sidechain_no_canonical_enable_param_raises(loaded_actions):
    """Device with no S/C On (or naming variants) gets a teaching error
    pointing at set_parameter — the structural fallback for third-party
    plugins with non-canonical naming."""
    eq = FakeDevice("EQ", class_name="EQ8",
                    parameters=[FakeParam("Frequency", 0.5)])
    ctx = FakeCtx(FakeSong(tracks=[FakeTrack("T1", devices=[eq])]))
    resp = dispatch(
        Request(
            tool="ableton_device", action="set_sidechain",
            params={"track_index": 1, "device_index": 1, "enabled": True},
        ),
        context=ctx,
    )
    assert resp.ok is False
    err = resp.error or ""
    assert "set_parameter" in err  # points at the workaround
    assert "get_parameters" in err  # and at the discovery primitive


# ---------- get_routing (legacy-named, retained) ----------


def test_get_routing_reports_current_input_routing(loaded_actions):
    comp = _compressor_with_routing()
    ctx = FakeCtx(FakeSong(tracks=[FakeTrack("T1", devices=[comp])]))
    resp = dispatch(
        Request(
            tool="ableton_device", action="get_routing",
            params={"track_index": 1, "device_index": 1},
        ),
        context=ctx,
    )
    assert resp.ok is True
    assert resp.result["input_routing"] == "No Input"
    assert resp.result["has_input_routing"] is True
    # Fictional sidechain_active retired — must NOT appear.
    assert "sidechain_active" not in resp.result


def test_get_routing_no_api_reports_none(loaded_actions):
    glue = _glue_compressor_without_routing()
    ctx = FakeCtx(FakeSong(tracks=[FakeTrack("T1", devices=[glue])]))
    resp = dispatch(
        Request(
            tool="ableton_device", action="get_routing",
            params={"track_index": 1, "device_index": 1},
        ),
        context=ctx,
    )
    assert resp.ok is True
    assert resp.result["input_routing"] is None
    assert resp.result["has_input_routing"] is False


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
