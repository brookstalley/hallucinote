"""ableton_device schema + handler behavior."""
from __future__ import annotations

import threading
from typing import Any

import pytest

from hallucinote_mcp import schema
from hallucinote_mcp.dispatcher import dispatch
from hallucinote_mcp.handlers.device import _resolve_device_path
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
        display_fn=None,
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
        # ``display_fn`` lets a test inject a realistic (e.g. nonlinear, dB)
        # str_for_value curve; default mirrors Live's bare numeric render.
        self._str_for_value = display_fn or (lambda v: f"{v:.2f}")

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


class FakeApplicationView:
    """Models Live's ``Application.View`` for device-load tests.

    Live's view state has two INDEPENDENT axes and the loader touches both:

    * the main document view — ``"Session"`` / ``"Arranger"``. ``load_item``
      is view-sensitive here: it silently no-ops when Arranger is focused
      (MCP-1V8K), so the loader must focus Session first. ``current`` records
      it, defaulting to Session so pre-existing load tests keep exercising the
      happy path.
    * the Detail pane's sub-view — ``"Detail/Clip"`` / ``"Detail/DeviceChain"``.
      Showing one of these does NOT change the main document view (that is why
      it is a separate field, not a second write to ``current``). It decides
      which chain the Detail pane is BOUND to, and that binding is the second
      half of what aims a browser load (MST-LEAK). Defaults to ``Detail/Clip``
      — the state ``ableton_session(action='set_view', view='detail')`` leaves
      behind, and the state the master-load leak was observed in.
    """

    _DETAIL_PREFIX = "Detail/"

    def __init__(
        self,
        current: str = "Session",
        detail_view: str = "Detail/Clip",
        detail_open: bool = True,
    ) -> None:
        self.current = current
        self.detail_view = detail_view
        # Live lets the composer collapse the Detail pane entirely; `show_view`
        # on a sub-view re-opens it, so the loader has to be able to put that
        # back too.
        self.detail_open = detail_open
        self.show_view_calls: list[str] = []
        self.hide_view_calls: list[str] = []

    def show_view(self, name: str) -> None:
        self.show_view_calls.append(name)
        if name == "Detail":
            self.detail_open = True
        elif name.startswith(self._DETAIL_PREFIX):
            self.detail_view = name
            self.detail_open = True
        else:
            self.current = name

    def hide_view(self, name: str) -> None:
        self.hide_view_calls.append(name)
        if name == "Detail" or name.startswith(self._DETAIL_PREFIX):
            self.detail_open = False

    def is_view_visible(self, name: str) -> bool:
        if name == "Detail":
            return self.detail_open
        if name.startswith(self._DETAIL_PREFIX):
            return self.detail_open and name == self.detail_view
        return name == self.current


class FakeBrowser:
    """Mirrors Live 12.4 browser behavior for device-load tests.

    ``load_item(item)`` appends a fresh device to whatever track is
    currently set as ``song.view.selected_track`` — UNLESS Live's focused
    view is Arranger, in which case the load silently no-ops (MCP-1V8K:
    the state a render leaves behind). Tests populate
    ``audio_effects.children``, ``drums.children``, etc. with
    ``FakeBrowserItem`` instances and then call the load action.
    """

    def __init__(self, song: "FakeSong", view: "FakeApplicationView"):
        self._song = song
        self._view = view
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
        if self._view.current == "Arranger":
            # Live silently no-ops a browser load when Arranger is focused.
            return
        target = self._song.view.selected_track
        if target is None:
            raise RuntimeError(
                "FakeBrowser.load_item called with no selected_track set"
            )
        new_dev = FakeDevice(name=item.name, class_name=item.name)
        target.devices.append(new_dev)


class FakeApplication:
    def __init__(self, song: "FakeSong"):
        self.view = FakeApplicationView()
        self.browser = FakeBrowser(song, self.view)


class FakeSongView:
    """Models Live 12.4.2: ``selected_track`` accepts regular tracks, return
    tracks, AND the master — the assignment STICKS for all three. DEV-6M2K:
    the master selection is no longer a silent no-op (DEV-2M9K's premise,
    live-refuted on Live 12.4.2 — read-back confirms the master sticks), so
    a load that selects the master correctly targets the master chain. A
    faithful fake reproduces THAT: ``load_handler``'s generic select-then-load
    path lands the device on the master, exactly as on any other track."""

    def __init__(self, song: "FakeSong") -> None:
        self._song = song
        self._selected: Any = None

    @property
    def selected_track(self) -> Any:
        return self._selected

    @selected_track.setter
    def selected_track(self, track: Any) -> None:
        self._selected = track


class FakeSong:
    def __init__(
        self,
        tracks: list[FakeTrack] | None = None,
        returns: list[FakeReturn] | None = None,
        master: FakeTrack | None = None,
    ):
        self.tracks = tracks or [FakeTrack("T1"), FakeTrack("T2")]
        self.return_tracks = returns or [FakeReturn("A-Rev")]
        self.master_track = master or FakeTrack("Master")
        self.view = FakeSongView(self)


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

    def run_on_main(self, fn, **_kwargs):
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
    # A sampler's sample is assigned by its own re-callable action, not by load.
    "assign_sample",
    # W6-E-2 capability-probing primitives + retained legacy-named actions:
    "capabilities", "set_input_routing", "get_input_routing",
    "set_sidechain", "get_routing",
    "navigate_preset", "pad_info",
    # Nested rack chains: recursive probe. DEEP-RACK-ADDR retired the one-level
    # load_in_rack / set_parameter_in_rack — folded into load (device_path +
    # chain_index) and set_parameter (device_path).
    "get_device_chains",
    # NODE-ADDR Chunk C: per-DrumChain choke_group / out_note via the `chain`
    # terminal.
    "set_chain_property",
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
    assert "not more than one" in (resp.error or "")


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
            params={"node": {"parent": {"kind": "track", "index": 1}, "device_index": 1}, "detail": "summary"},
        ),
        context=ctx,
    )
    resp_f = dispatch(
        Request(
            tool="ableton_device", action="get_parameters",
            params={"node": {"parent": {"kind": "track", "index": 1}, "device_index": 1}, "detail": "full"},
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
            params={"node": {"parent": {"kind": "track", "index": 1}, "terminal": "track"}, "kind": "Compressor2"},
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


def test_load_focuses_session_view_when_arranger(loaded_actions):
    """MCP-1V8K: a render leaves Live focused on Arranger, where
    ``browser.load_item`` silently no-ops. The loader must focus Session
    before loading so the post-render "load a device" sequence works on the
    first try. Without the focus-Session step the FakeBrowser no-ops in
    Arranger and the device never lands (the regression this guards)."""
    ctx = FakeCtx(FakeSong(tracks=[FakeTrack("T1")]))
    # Simulate the post-render state: focus is on Arranger.
    ctx.application.view.current = "Arranger"
    _add_browser_item(ctx, "audio_effects", "Operator", uri="query:Operator")
    resp = dispatch(
        Request(
            tool="ableton_device", action="load",
            params={"node": {"parent": {"kind": "track", "index": 1}, "terminal": "track"}, "kind": "Operator"},
        ),
        context=ctx,
    )
    assert resp.ok is True
    # The loader focused Session before loading...
    assert "Session" in ctx.application.view.show_view_calls
    assert ctx.application.view.current == "Session"
    # ...so the load actually landed (no silent Arranger no-op).
    assert len(ctx.song.tracks[0].devices) == 1
    assert resp.result["kind"] == "Operator"


def test_load_response_carries_loaded_class_name(loaded_actions):
    """Arc 7 / P5: the load response includes `loaded_class_name`
    (the device's resolved class_display_name) so callers can detect a
    kind / preset_uri mismatch without a follow-up
    ``ableton_device(action='list')`` probe. Falls back to class_name
    when class_display_name isn't exposed (older Live wrappers); empty
    string when neither is present."""
    ctx = FakeCtx(FakeSong(tracks=[FakeTrack("T1")]))
    _add_browser_item(ctx, "audio_effects", "Compressor", uri="query:Comp")
    resp = dispatch(
        Request(
            tool="ableton_device", action="load",
            params={"node": {"parent": {"kind": "track", "index": 1}, "terminal": "track"}, "kind": "Compressor"},
        ),
        context=ctx,
    )
    assert resp.ok is True
    # FakeBrowser.load_item creates a FakeDevice that sets both
    # class_name and class_display_name to the item's name. Caller can
    # detect mismatches via this field.
    assert resp.result["loaded_class_name"] == "Compressor"


def test_load_on_return(loaded_actions):
    ctx = FakeCtx(FakeSong(
        tracks=[FakeTrack("T1")],
        returns=[FakeReturn("Rev")],
    ))
    _add_browser_item(ctx, "audio_effects", "Reverb", uri="query:Reverb")
    resp = dispatch(
        Request(
            tool="ableton_device", action="load",
            params={"node": {"parent": {"kind": "return", "index": 1}, "terminal": "return"}, "kind": "Reverb"},
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
            params={"node": {"parent": {"kind": "track", "index": 1}, "terminal": "track"}, "kind": "EQ8"},
        ),
        context=ctx,
    )
    assert resp.ok is True
    assert resp.result["device_index"] == 3
    assert [d.name for d in track.devices] == ["A", "B", "EQ8"]


def test_load_reports_the_device_loaded_not_the_one_it_displaced(loaded_actions):
    """Live keeps a chain in MIDI-effects / instrument / audio-effects order,
    so loading a MIDI effect onto a track that already holds an instrument
    inserts at the HEAD and pushes the instrument down. The response must name
    the device just loaded at its real position — naming the displaced device
    is the worst failure shape available here, because it names a REAL device
    and nothing downstream (push's device linking reads `device_index`) can
    tell it is wrong."""
    track = FakeTrack("T1", devices=[
        FakeDevice("Operator", class_name="Operator"),
    ])
    ctx = FakeCtx(FakeSong(tracks=[track]))
    _add_browser_item(ctx, "midi_effects", "Pitch", uri="query:Pitch")

    def fake_load(item):
        ctx.application.browser.load_calls.append(item)
        track.devices.insert(
            0, FakeDevice(name=item.name, class_name="MidiPitcher")
        )
    ctx.application.browser.load_item = fake_load

    resp = dispatch(
        Request(
            tool="ableton_device", action="load",
            params={"node": {"parent": {"kind": "track", "index": 1}, "terminal": "track"}, "kind": "Pitch"},
        ),
        context=ctx,
    )
    assert resp.ok is True, resp.to_dict()
    assert [d.class_name for d in track.devices] == ["MidiPitcher", "Operator"]
    assert resp.result["device_index"] == 1
    assert resp.result["loaded_class_name"] == "MidiPitcher"
    assert resp.result["name"] == "Pitch"


def test_load_into_the_middle_of_a_chain_reports_that_position(loaded_actions):
    """The MIDI-effect-at-the-head case is one instance, not the boundary: any
    load Live does not append lands somewhere the tail does not name. An
    instrument dropped between a MIDI effect and the audio effects reports its
    own position."""
    track = FakeTrack("T1", devices=[
        FakeDevice("Pitch", class_name="MidiPitcher"),
        FakeDevice("Reverb", class_name="Reverb"),
    ])
    ctx = FakeCtx(FakeSong(tracks=[track]))
    _add_browser_item(ctx, "instruments", "Operator", uri="query:Operator")

    def fake_load(item):
        ctx.application.browser.load_calls.append(item)
        track.devices.insert(
            1, FakeDevice(name=item.name, class_name="Operator")
        )
    ctx.application.browser.load_item = fake_load

    resp = dispatch(
        Request(
            tool="ableton_device", action="load",
            params={"node": {"parent": {"kind": "track", "index": 1}, "terminal": "track"}, "kind": "Operator"},
        ),
        context=ctx,
    )
    assert resp.ok is True, resp.to_dict()
    assert resp.result["device_index"] == 2
    assert resp.result["loaded_class_name"] == "Operator"


def test_load_of_a_second_same_class_device_still_reports_the_tail(loaded_actions):
    """Positional diff boundary: when the loaded device's class already sits in
    the chain, the first diverging position is where the chain grew — for a
    plain append that is still the tail, so the common shape is unchanged."""
    track = FakeTrack("T1", devices=[
        FakeDevice("EQ8", class_name="Eq8"),
    ])
    ctx = FakeCtx(FakeSong(tracks=[track]))
    _add_browser_item(ctx, "audio_effects", "EQ Eight", uri="query:Eq8")

    def fake_load(item):
        ctx.application.browser.load_calls.append(item)
        track.devices.append(FakeDevice(name=item.name, class_name="Eq8"))
    ctx.application.browser.load_item = fake_load

    resp = dispatch(
        Request(
            tool="ableton_device", action="load",
            params={"node": {"parent": {"kind": "track", "index": 1}, "terminal": "track"}, "kind": "EQ Eight"},
        ),
        context=ctx,
    )
    assert resp.ok is True, resp.to_dict()
    assert resp.result["device_index"] == 2
    assert resp.result["name"] == "EQ Eight"


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
                "node": {"parent": {"kind": "track", "index": 1}, "terminal": "track"}, "kind": "DrumGroupDevice",
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
                "node": {"parent": {"kind": "track", "index": 1}, "terminal": "track"}, "kind": "Serum",
                "preset_uri": "query:VST3#serum.vst3",
            },
        ),
        context=ctx,
    )
    assert resp.ok is True
    assert ctx.application.browser.load_calls[0].uri == \
        "query:VST3#serum.vst3"


def test_load_kind_matches_browser_display_directly(loaded_actions):
    """Arc 4 / D4: the loader is now kind-as-given against the browser.
    Push sends ``kind="Compressor"`` (the browser display name, written
    into ``devices.kind`` by pull from ``device.class_display_name``);
    no static translation table interposes.
    """
    ctx = FakeCtx(FakeSong(tracks=[FakeTrack("T1")]))
    _add_browser_item(ctx, "audio_effects", "Compressor", uri="query:Compressor")
    resp = dispatch(
        Request(
            tool="ableton_device", action="load",
            params={"node": {"parent": {"kind": "track", "index": 1}, "terminal": "track"}, "kind": "Compressor"},
        ),
        context=ctx,
    )
    assert resp.ok is True, resp.to_dict()
    assert resp.result["kind"] == "Compressor"
    assert len(ctx.song.tracks[0].devices) == 1


def test_load_internal_class_name_fails_under_new_convention(loaded_actions):
    """Arc 4 / D4: passing the internal Live class name (e.g.
    ``Compressor2`` or ``DrumGroupDevice``) no longer resolves. The
    DB-level convention shift means push sends the browser display name
    (``Compressor`` / ``Drum Rack``); a caller that sends the internal
    class hits a loud "no loadable browser item" failure. Pinned here
    so the deletion of the _CLASS_TO_DISPLAY table stays semantic, not
    accidental.
    """
    ctx = FakeCtx(FakeSong(tracks=[FakeTrack("T1")]))
    # Browser exposes only the display-name node.
    _add_browser_item(ctx, "audio_effects", "Compressor", uri="query:Compressor")
    resp = dispatch(
        Request(
            tool="ableton_device", action="load",
            params={"node": {"parent": {"kind": "track", "index": 1}, "terminal": "track"}, "kind": "Compressor2"},
        ),
        context=ctx,
    )
    assert resp.ok is False
    assert "no loadable browser item" in (resp.error or "")


def test_load_rack_display_name_resolves_in_canonical_root(loaded_actions):
    """Rack kinds (``Drum Rack``, ``Instrument Rack``, ...) get the
    canonical-root restriction even under the simplified loader (W7-0
    cross-category disambiguation, preserved post-D4). Browser exposes
    ``Drum Rack`` under the drums root only — the loader walks just
    there for rack kinds.
    """
    ctx = FakeCtx(FakeSong(tracks=[FakeTrack("T1")]))
    _add_browser_item(ctx, "drums", "Drum Rack", uri="query:DrumRack")
    resp = dispatch(
        Request(
            tool="ableton_device", action="load",
            params={"node": {"parent": {"kind": "track", "index": 1}, "terminal": "track"}, "kind": "Drum Rack"},
        ),
        context=ctx,
    )
    assert resp.ok is True
    assert resp.result["kind"] == "Drum Rack"


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
            params={"node": {"parent": {"kind": "track", "index": 1}, "terminal": "track"}, "kind": "Reverb"},
        ),
        context=ctx,
    )
    assert resp.ok is True
    assert resp.result["kind"] == "Reverb"


def test_load_unknown_kind_error_names_the_kind(loaded_actions):
    """Arc 4 / D4: with the translation table gone, the error simply
    names the unresolvable kind and points at the browser-probe
    recovery path. No more "(also tried X via device_names translation
    / *Device suffix strip)" trailer — that mechanism doesn't exist.
    """
    ctx = FakeCtx(FakeSong(tracks=[FakeTrack("T1")]))
    resp = dispatch(
        Request(
            tool="ableton_device", action="load",
            params={"node": {"parent": {"kind": "track", "index": 1}, "terminal": "track"}, "kind": "WhateverNew"},
        ),
        context=ctx,
    )
    assert resp.ok is False
    assert "WhateverNew" in (resp.error or "")
    assert "ableton_browser" in (resp.error or "")  # recovery hint


def test_load_unknown_kind_errors_with_browser_hint(loaded_actions):
    ctx = FakeCtx(FakeSong(tracks=[FakeTrack("T1")]))
    resp = dispatch(
        Request(
            tool="ableton_device", action="load",
            params={"node": {"parent": {"kind": "track", "index": 1}, "terminal": "track"}, "kind": "NoSuchDevice"},
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
                "node": {"parent": {"kind": "track", "index": 1}, "terminal": "track"}, "kind": "Compressor2",
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
            params={"node": {"parent": {"kind": "track", "index": 1}, "terminal": "track"}, "kind": "Compressor2"},
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
                "node": {"parent": {"kind": "track", "index": 1}, "terminal": "track"}, "kind": "Synth",
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
                "node": {"parent": {"kind": "track", "index": 1}, "terminal": "track"}, "kind": "Compressor2", "position": 1,
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
            params={"node": {"parent": {"kind": "track", "index": 1}, "terminal": "track"}, "kind": "Compressor2"},
        ),
        context=ctx,
    )
    assert resp.ok is False
    assert "application" in (resp.error or "").lower()


def test_load_no_chain_growth_is_runtime_error(loaded_actions):
    """If Live silently no-ops a load on a track (a device it won't append to
    this chain), we surface it. (DEV-6M2K: the master reaches this same path
    now — if a master selection ever failed to stick, the post-load chain-grew
    check here is exactly what would catch the mis-load instead of corrupting a
    regular track.)"""
    ctx = FakeCtx(FakeSong(tracks=[FakeTrack("T1")]))
    _add_browser_item(ctx, "instruments", "Operator", uri="query:Operator")
    # Replace the browser's load_item with a no-op that doesn't grow the chain.
    ctx.application.browser.load_item = lambda item: \
        ctx.application.browser.load_calls.append(item)
    resp = dispatch(
        Request(
            tool="ableton_device", action="load",
            params={"node": {"parent": {"kind": "track", "index": 1}, "terminal": "track"}, "kind": "Operator"},
        ),
        context=ctx,
    )
    assert resp.ok is False
    assert "did not append" in (resp.error or "")


def test_load_no_chain_growth_surfaces_existing_chain_class_names(loaded_actions):
    """A2-resid: when the load no-ops because a matching device is already
    present (punk-fate --reset-then-repush repro), the error must list
    the existing chain so the caller can diagnose without a separate
    ableton_device(action='list') probe. The pre-A2-resid error only
    named the misleading 'instrument on a return' hint."""
    track = FakeTrack("T1", devices=[
        FakeDevice("Existing Compressor", class_name="Compressor2"),
        FakeDevice("Existing Reverb", class_name="Reverb"),
    ])
    ctx = FakeCtx(FakeSong(tracks=[track]))
    _add_browser_item(ctx, "instruments", "Operator", uri="query:Operator")
    # Browser silently no-ops — same shape Live exhibits when a matching
    # device is already at the expected chain position.
    ctx.application.browser.load_item = lambda item: \
        ctx.application.browser.load_calls.append(item)
    resp = dispatch(
        Request(
            tool="ableton_device", action="load",
            params={"node": {"parent": {"kind": "track", "index": 1}, "terminal": "track"}, "kind": "Operator"},
        ),
        context=ctx,
    )
    assert resp.ok is False
    err = resp.error or ""
    assert "did not append" in err
    # The two existing class names appear in the surfaced chain list.
    assert "Compressor2" in err
    assert "Reverb" in err
    # The misleading "instrument on a return" hint is suppressed for
    # track parents — it only applies to return parents.
    assert "instrument on a return" not in err


def test_load_no_chain_growth_on_return_keeps_instrument_hint(loaded_actions):
    """A2-resid: 'instrument on a return' hint is real for return parents
    (Live actually rejects instrument loads on returns) — keep it for
    that case so the loader still names the structural mismatch."""
    ret = FakeReturn("Rev")  # empty chain
    ctx = FakeCtx(FakeSong(tracks=[FakeTrack("T1")], returns=[ret]))
    _add_browser_item(ctx, "instruments", "Operator", uri="query:Operator")
    ctx.application.browser.load_item = lambda item: \
        ctx.application.browser.load_calls.append(item)
    resp = dispatch(
        Request(
            tool="ableton_device", action="load",
            params={"node": {"parent": {"kind": "return", "index": 1}, "terminal": "return"}, "kind": "Operator"},
        ),
        context=ctx,
    )
    assert resp.ok is False
    err = resp.error or ""
    assert "did not append" in err
    assert "instrument on a return" in err


def test_load_resolved_path_present_on_kind_only(loaded_actions):
    """E3 (W13-A v1.0): the load response carries the resolved browser path
    (segments from the root key to the leaf's name) — captured into
    `devices.browser_path_json` at snapshot ingest time."""
    ctx = FakeCtx(FakeSong(tracks=[FakeTrack("T1")]))
    _add_browser_item(ctx, "instruments", "Operator", uri="query:Operator")
    resp = dispatch(
        Request(
            tool="ableton_device", action="load",
            params={"node": {"parent": {"kind": "track", "index": 1}, "terminal": "track"}, "kind": "Operator"},
        ),
        context=ctx,
    )
    assert resp.ok is True, resp.to_dict()
    assert resp.result["resolved_path"] == ["instruments", "Operator"]


def test_load_resolved_path_present_on_preset_uri(loaded_actions):
    """preset_uri lookups also surface the resolved path so the snapshot
    can capture the vendor / pack scope for future cross-machine push."""
    ctx = FakeCtx(FakeSong(tracks=[FakeTrack("T1")]))
    plugin = FakeBrowserItem(
        "FatBass", uri="query:Plugin#FileId_9999", is_loadable=True,
    )
    massive = FakeBrowserItem("Massive X", is_loadable=False, children=(plugin,))
    ni = FakeBrowserItem(
        "Native Instruments", is_loadable=False, children=(massive,),
    )
    ctx.application.browser.plugins.children.append(ni)
    resp = dispatch(
        Request(
            tool="ableton_device", action="load",
            params={
                "node": {"parent": {"kind": "track", "index": 1}, "terminal": "track"}, "kind": "Massive X",
                "preset_uri": "query:Plugin#FileId_9999",
            },
        ),
        context=ctx,
    )
    assert resp.ok is True, resp.to_dict()
    assert resp.result["resolved_path"] == [
        "plugins", "Native Instruments", "Massive X", "FatBass",
    ]


def test_load_browser_path_fallback_resolves_when_preset_uri_misses(loaded_actions):
    """E3 (W13-A v1.0): preset_uri is per-machine. On a target machine
    where the FileId differs, the URI walk returns nothing; the handler
    then falls back to a path-scoped browser search using browser_path.
    The leaf name (browser_path[-1]) is the exact-match pattern; the
    middle segments scope the walk via path_prefix; the first segment is
    the root. Same-display-name plugins from different vendors are
    discriminated by the path scope."""
    ctx = FakeCtx(FakeSong(tracks=[FakeTrack("T1")]))
    # Two FatBass leaves under different vendors — display-name-only would
    # be ambiguous. The captured browser_path scopes the search.
    fatbass_ni = FakeBrowserItem(
        "FatBass", uri="query:Plugin#FileId_THIS_MACHINE", is_loadable=True,
    )
    massive = FakeBrowserItem(
        "Massive X", is_loadable=False, children=(fatbass_ni,),
    )
    ni = FakeBrowserItem(
        "Native Instruments", is_loadable=False, children=(massive,),
    )
    fatbass_other = FakeBrowserItem(
        "FatBass", uri="query:Plugin#FileId_OTHER", is_loadable=True,
    )
    diva = FakeBrowserItem("Diva", is_loadable=False, children=(fatbass_other,))
    uhe = FakeBrowserItem("u-he", is_loadable=False, children=(diva,))
    ctx.application.browser.plugins.children.extend([ni, uhe])
    resp = dispatch(
        Request(
            tool="ableton_device", action="load",
            params={
                "node": {"parent": {"kind": "track", "index": 1}, "terminal": "track"}, "kind": "Massive X",
                # The snapshot's URI is stale on this machine.
                "preset_uri": "query:Plugin#STALE_FILE_ID",
                "browser_path": [
                    "plugins", "Native Instruments", "Massive X", "FatBass",
                ],
            },
        ),
        context=ctx,
    )
    assert resp.ok is True, resp.to_dict()
    # The fallback resolves to the NI/Massive X branch — not the u-he one.
    assert ctx.application.browser.load_calls[0].uri == \
        "query:Plugin#FileId_THIS_MACHINE"
    assert resp.result["resolved_path"] == [
        "plugins", "Native Instruments", "Massive X", "FatBass",
    ]


def test_load_browser_path_leaf_anchors_against_longer_sibling(loaded_actions):
    """A captured leaf must not be beaten by a sibling that merely CONTAINS it.

    Live ships kit presets in pairs — ``Kit-BritishVintage.adg`` and its MPE
    twin ``MPE Kit-BritishVintage.adg`` — side by side under the same Drums
    folder. The captured leaf is the browser item's own display name, so it
    matches its own node exactly; matching it as a substring made the MPE twin
    a second hit and the strict loader refused the pair as ambiguous, which
    halted a from-scratch push of a song that had captured the plain kit. No
    ``path_prefix`` can separate the two (same folder), so the leaf itself is
    the only thing that can be anchored.
    """
    ctx = FakeCtx(FakeSong(tracks=[FakeTrack("T1")]))
    plain = FakeBrowserItem(
        "Kit-BritishVintage.adg", uri="query:Drums#FileId_PLAIN",
        is_loadable=True,
    )
    mpe = FakeBrowserItem(
        "MPE Kit-BritishVintage.adg", uri="query:Drums#FileId_MPE",
        is_loadable=True,
    )
    ctx.application.browser.drums.children.extend([plain, mpe])
    resp = dispatch(
        Request(
            tool="ableton_device", action="load",
            params={
                "node": {
                    "parent": {"kind": "track", "index": 1},
                    "terminal": "track",
                },
                "kind": "Drum Rack",
                "browser_path": ["drums", "Kit-BritishVintage.adg"],
            },
        ),
        context=ctx,
    )
    assert resp.ok is True, resp.to_dict()
    # The captured kit loaded — not the MPE twin, and not a refusal.
    assert ctx.application.browser.load_calls[0].uri == "query:Drums#FileId_PLAIN"

    # The anchoring is symmetric: capturing the MPE twin must load the twin,
    # which a "longest match wins" shortcut would also satisfy but a
    # "prefer the shorter name" one would not.
    ctx2 = FakeCtx(FakeSong(tracks=[FakeTrack("T1")]))
    ctx2.application.browser.drums.children.extend([
        FakeBrowserItem(
            "Kit-BritishVintage.adg", uri="query:Drums#FileId_PLAIN",
            is_loadable=True,
        ),
        FakeBrowserItem(
            "MPE Kit-BritishVintage.adg", uri="query:Drums#FileId_MPE",
            is_loadable=True,
        ),
    ])
    resp2 = dispatch(
        Request(
            tool="ableton_device", action="load",
            params={
                "node": {
                    "parent": {"kind": "track", "index": 1},
                    "terminal": "track",
                },
                "kind": "Drum Rack",
                "browser_path": ["drums", "MPE Kit-BritishVintage.adg"],
            },
        ),
        context=ctx2,
    )
    assert resp2.ok is True, resp2.to_dict()
    assert ctx2.application.browser.load_calls[0].uri == "query:Drums#FileId_MPE"


def test_load_browser_path_fallback_refuses_on_zero_match(loaded_actions):
    """E3 (W13-A v1.0): plugin not installed at the captured path on this
    machine — fallback refuses with a teaching error that names the
    captured path so the agent can decide whether to surface the gap to
    the user."""
    ctx = FakeCtx(FakeSong(tracks=[FakeTrack("T1")]))
    # Browser has no plugins at all.
    resp = dispatch(
        Request(
            tool="ableton_device", action="load",
            params={
                "node": {"parent": {"kind": "track", "index": 1}, "terminal": "track"}, "kind": "Massive X",
                "preset_uri": "query:Plugin#STALE",
                "browser_path": [
                    "plugins", "Native Instruments", "Massive X", "FatBass",
                ],
            },
        ),
        context=ctx,
    )
    assert resp.ok is False
    err = resp.error or ""
    assert "fallback identity" in err
    # Failure mode: either the path_prefix isn't navigable (vendor folder
    # missing entirely) OR the walk found 0 loadable leaves at the
    # captured scope. Both refuse cleanly with the captured segments
    # named in the teaching error.
    assert "Native Instruments" in err


def test_load_browser_path_fallback_refuses_on_multi_match(loaded_actions):
    """E3 (W13-A v1.0): on a target machine where the captured path scope
    matches more than one loadable (e.g. multiple presets share the same
    leaf name within the same vendor folder), the fallback refuses with
    the ambiguity teaching error so the agent doesn't silently pick the
    wrong one."""
    ctx = FakeCtx(FakeSong(tracks=[FakeTrack("T1")]))
    # Two FatBass leaves under the SAME vendor — captured path scope can't
    # disambiguate; multi-match must refuse rather than guess.
    fatbass_a = FakeBrowserItem(
        "FatBass", uri="query:Plugin#FileId_A", is_loadable=True,
    )
    fatbass_b = FakeBrowserItem(
        "FatBass", uri="query:Plugin#FileId_B", is_loadable=True,
    )
    massive = FakeBrowserItem(
        "Massive X", is_loadable=False, children=(fatbass_a, fatbass_b),
    )
    ni = FakeBrowserItem(
        "Native Instruments", is_loadable=False, children=(massive,),
    )
    ctx.application.browser.plugins.children.append(ni)
    resp = dispatch(
        Request(
            tool="ableton_device", action="load",
            params={
                "node": {"parent": {"kind": "track", "index": 1}, "terminal": "track"}, "kind": "Massive X",
                "preset_uri": "query:Plugin#STALE",
                "browser_path": [
                    "plugins", "Native Instruments", "Massive X", "FatBass",
                ],
            },
        ),
        context=ctx,
    )
    assert resp.ok is False
    err = resp.error or ""
    assert "fallback identity" in err
    assert "ambiguous" in err


def test_load_browser_path_requires_preset_uri(loaded_actions):
    """browser_path is the fallback FOR preset_uri — passing it alone is
    a teaching error (composers wanting standalone path-scoped search
    should use preset_query, which carries the same shape)."""
    ctx = FakeCtx(FakeSong(tracks=[FakeTrack("T1")]))
    resp = dispatch(
        Request(
            tool="ableton_device", action="load",
            params={
                "node": {"parent": {"kind": "track", "index": 1}, "terminal": "track"}, "kind": "Operator",
                "browser_path": ["instruments", "Operator", "Bass", "Sub Bass"],
            },
        ),
        context=ctx,
    )
    assert resp.ok is False
    err = resp.error or ""
    assert "fallback" in err
    assert "preset_query" in err  # teaches the alternative


def test_load_browser_path_rejects_bad_shape(loaded_actions):
    """Empty list / non-string elements are rejected with a teaching
    error before any browser walk happens."""
    ctx = FakeCtx(FakeSong(tracks=[FakeTrack("T1")]))
    _add_browser_item(ctx, "instruments", "Operator", uri="query:Operator")
    resp = dispatch(
        Request(
            tool="ableton_device", action="load",
            params={
                "node": {"parent": {"kind": "track", "index": 1}, "terminal": "track"}, "kind": "Operator",
                "preset_uri": "query:Operator",
                "browser_path": [],
            },
        ),
        context=ctx,
    )
    assert resp.ok is False
    assert "browser_path" in (resp.error or "")


def test_load_browser_path_fallback_not_used_when_preset_uri_resolves(loaded_actions):
    """When preset_uri DOES resolve, the fallback is not consulted —
    keeps the deterministic fast path as the dominant case. Lock-test:
    we don't want surprise fallback behavior on the happy path."""
    ctx = FakeCtx(FakeSong(tracks=[FakeTrack("T1")]))
    leaf = FakeBrowserItem(
        "Sub Bass", uri="query:Operator#FileId_HERE", is_loadable=True,
    )
    bass = FakeBrowserItem("Bass", is_loadable=False, children=(leaf,))
    op = FakeBrowserItem("Operator", is_loadable=False, children=(bass,))
    ctx.application.browser.instruments.children.append(op)
    resp = dispatch(
        Request(
            tool="ableton_device", action="load",
            params={
                "node": {"parent": {"kind": "track", "index": 1}, "terminal": "track"}, "kind": "Operator",
                "preset_uri": "query:Operator#FileId_HERE",
                # The browser_path is provided but the URI already resolves,
                # so the response path should reflect the URI walk's result.
                "browser_path": ["instruments", "Operator", "Bass", "Sub Bass"],
            },
        ),
        context=ctx,
    )
    assert resp.ok is True, resp.to_dict()
    assert ctx.application.browser.load_calls[0].uri == \
        "query:Operator#FileId_HERE"
    assert resp.result["resolved_path"] == [
        "instruments", "Operator", "Bass", "Sub Bass",
    ]


def test_load_browser_path_preset_file_loads_standalone(loaded_actions):
    """SYN-RACK-PRESET-RELINK: a browser_path whose leaf is a preset FILE
    (.adg/.adv) loads STANDALONE — no preset_uri / preset_query needed. The
    common /song-snapshot case: capture can't probe preset_uri, so a rack
    preset's only identity is its browser_path. Before this it loaded the bare
    CLASS node (empty Drum Rack, 0 chains). The standalone path must resolve the
    PRESET, not the class node — even with both present in the browser."""
    ctx = FakeCtx(FakeSong(tracks=[FakeTrack("Drums")]))
    empty_rack = FakeBrowserItem(
        "Drum Rack", uri="query:Drums#Empty", is_loadable=True,
    )
    kit = FakeBrowserItem(
        "AG Techno Kit.adg", uri="query:Drums#FileId_KIT", is_loadable=True,
    )
    ctx.application.browser.drums.children.extend([empty_rack, kit])
    resp = dispatch(
        Request(
            tool="ableton_device", action="load",
            params={
                "node": {"parent": {"kind": "track", "index": 1}, "terminal": "track"},
                "kind": "Drum Rack",
                # No preset_uri / preset_query — browser_path is the only identity.
                "browser_path": ["drums", "AG Techno Kit.adg"],
            },
        ),
        context=ctx,
    )
    assert resp.ok is True, resp.to_dict()
    # Resolves the PRESET, not the empty "Drum Rack" class node.
    assert ctx.application.browser.load_calls[0].name == "AG Techno Kit.adg"
    assert ctx.application.browser.load_calls[0].uri == "query:Drums#FileId_KIT"
    assert resp.result["resolved_path"] == ["drums", "AG Techno Kit.adg"]


def test_load_browser_path_preset_file_standalone_refuses_when_not_installed(
    loaded_actions,
):
    """A standalone preset-file browser_path that resolves to nothing on this
    machine (preset not installed at that path) refuses with a teaching error
    naming the path — not a silent empty-rack load."""
    ctx = FakeCtx(FakeSong(tracks=[FakeTrack("Drums")]))
    # drums root has no matching preset.
    resp = dispatch(
        Request(
            tool="ableton_device", action="load",
            params={
                "node": {"parent": {"kind": "track", "index": 1}, "terminal": "track"},
                "kind": "Drum Rack",
                "browser_path": ["drums", "AG Techno Kit.adg"],
            },
        ),
        context=ctx,
    )
    assert resp.ok is False
    err = resp.error or ""
    assert "AG Techno Kit.adg" in err
    assert "not be installed" in err


def test_load_replace_in_place_succeeds(loaded_actions):
    """E2: Live's browser sometimes REPLACES the existing device in place
    instead of appending — empirically observed when loading a Drum Rack
    onto a track that already has an Instrument Rack. Chain length stays
    the same but the class at the affected position changes. The
    post-condition must accept this shape and the response's
    `device_index` must point at the replaced position so the caller can
    follow up correctly (e.g. set_parameter on the freshly-loaded
    device). Before this fix the handler raised
    `RuntimeError: load: Live did not append ...` even though the load
    succeeded semantically — masking the real shape and forcing callers
    to retry / probe."""
    track = FakeTrack("T1", devices=[
        FakeDevice("Existing Rack", class_name="InstrumentGroupDevice"),
    ])
    ctx = FakeCtx(FakeSong(tracks=[track]))
    _add_browser_item(ctx, "drums", "Drum Rack", uri="query:DrumRack")
    # Replace-in-place: load_item swaps the device at position 1 rather
    # than appending. Mirrors the empirical Drum-Rack-onto-Instrument-Rack
    # finding (2026-05-22 probing session).
    def fake_load(item):
        ctx.application.browser.load_calls.append(item)
        new = FakeDevice(name=item.name, class_name="DrumGroupDevice")
        track.devices[0] = new
    ctx.application.browser.load_item = fake_load
    resp = dispatch(
        Request(
            tool="ableton_device", action="load",
            params={"node": {"parent": {"kind": "track", "index": 1}, "terminal": "track"}, "kind": "Drum Rack"},
        ),
        context=ctx,
    )
    assert resp.ok is True, resp.to_dict()
    # device_index points at the replaced position (not the tail), and
    # loaded_class_name reflects the actual class Live ended up with.
    assert resp.result["device_index"] == 1
    assert resp.result["loaded_class_name"] == "DrumGroupDevice"
    assert resp.result["kind"] == "Drum Rack"
    assert len(track.devices) == 1


def test_load_no_chain_growth_same_class_still_fails(loaded_actions):
    """E2 boundary: the silent-no-op error path is unchanged for the case
    where chain length is the same AND no class changed (a same-class
    device already at the expected position, Live no-ops the load).
    Pre-A2-resid behavior preserved: surface the existing chain so the
    caller can diagnose without a separate `list` probe."""
    track = FakeTrack("T1", devices=[
        FakeDevice("Existing", class_name="Compressor2"),
    ])
    ctx = FakeCtx(FakeSong(tracks=[track]))
    _add_browser_item(ctx, "audio_effects", "Compressor", uri="query:Comp")
    ctx.application.browser.load_item = lambda item: \
        ctx.application.browser.load_calls.append(item)
    resp = dispatch(
        Request(
            tool="ableton_device", action="load",
            params={"node": {"parent": {"kind": "track", "index": 1}, "terminal": "track"}, "kind": "Compressor"},
        ),
        context=ctx,
    )
    assert resp.ok is False
    err = resp.error or ""
    assert "did not append" in err
    assert "Compressor2" in err


def test_load_multi_position_change_raises(loaded_actions):
    """E2 defensive branch: if Live somehow returned a same-length chain
    where MORE THAN one position's class changed, the post-condition
    must surface that — we have no model for it and don't want to
    silently pick a 'new device'. The empirical replace-in-place case
    affects exactly one position; this guards against future Live
    behavior changes that would otherwise pass through unnoticed."""
    track = FakeTrack("T1", devices=[
        FakeDevice("A", class_name="ClassA"),
        FakeDevice("B", class_name="ClassB"),
    ])
    ctx = FakeCtx(FakeSong(tracks=[track]))
    _add_browser_item(ctx, "audio_effects", "ClassZ", uri="query:ClassZ")
    # Same length, two positions changed class — defensive shape.
    def fake_load(item):
        ctx.application.browser.load_calls.append(item)
        track.devices[0] = FakeDevice("X", class_name="ClassX")
        track.devices[1] = FakeDevice("Z", class_name="ClassZ")
    ctx.application.browser.load_item = fake_load
    resp = dispatch(
        Request(
            tool="ableton_device", action="load",
            params={"node": {"parent": {"kind": "track", "index": 1}, "terminal": "track"}, "kind": "ClassZ"},
        ),
        context=ctx,
    )
    assert resp.ok is False
    err = resp.error or ""
    assert "multiple devices" in err
    # The diagnostic chain includes the post-load classes so the caller
    # can see what happened.
    assert "ClassX" in err
    assert "ClassZ" in err


def test_load_chain_shrink_raises(loaded_actions):
    """E2 defensive branch: a load should never shrink the chain.
    Surface what we observed so we don't pretend a tail-pick succeeded."""
    track = FakeTrack("T1", devices=[
        FakeDevice("A", class_name="ClassA"),
        FakeDevice("B", class_name="ClassB"),
    ])
    ctx = FakeCtx(FakeSong(tracks=[track]))
    _add_browser_item(ctx, "audio_effects", "ClassZ", uri="query:ClassZ")
    def fake_load(item):
        ctx.application.browser.load_calls.append(item)
        track.devices.pop()  # shrank
    ctx.application.browser.load_item = fake_load
    resp = dispatch(
        Request(
            tool="ableton_device", action="load",
            params={"node": {"parent": {"kind": "track", "index": 1}, "terminal": "track"}, "kind": "ClassZ"},
        ),
        context=ctx,
    )
    assert resp.ok is False
    err = resp.error or ""
    assert "shrank" in err
    assert "pre=2" in err
    assert "post=1" in err


def test_load_no_chain_growth_on_empty_track_shows_empty_chain(loaded_actions):
    """A2-resid: empty chain renders as `(empty)` so the message is
    unambiguous about the parent's actual state."""
    ctx = FakeCtx(FakeSong(tracks=[FakeTrack("T1")]))  # empty chain
    _add_browser_item(ctx, "instruments", "Operator", uri="query:Operator")
    ctx.application.browser.load_item = lambda item: \
        ctx.application.browser.load_calls.append(item)
    resp = dispatch(
        Request(
            tool="ableton_device", action="load",
            params={"node": {"parent": {"kind": "track", "index": 1}, "terminal": "track"}, "kind": "Operator"},
        ),
        context=ctx,
    )
    assert resp.ok is False
    assert "(empty)" in (resp.error or "")


# ---------- M1-A: device-load forgiveness (suffix strip + rack disambiguation) ----------


def test_load_analog_kind_matches_browser_directly_post_d4(loaded_actions):
    """Arc 4 / D4: previously ``kind='AnalogDevice'`` resolved via the
    deleted ``strip_device_suffix`` fallback (``AnalogDevice → Analog``).
    Under the post-D4 convention, push sends ``kind='Analog'`` (the
    browser display name, written by pull from
    ``device.class_display_name``); the kind-as-given walk matches
    directly. No suffix-strip needed.
    """
    ctx = FakeCtx(FakeSong(tracks=[FakeTrack("T1")]))
    _add_browser_item(ctx, "instruments", "Analog", uri="query:Analog")
    resp = dispatch(
        Request(
            tool="ableton_device", action="load",
            params={"node": {"parent": {"kind": "track", "index": 1}, "terminal": "track"}, "kind": "Analog"},
        ),
        context=ctx,
    )
    assert resp.ok is True, resp.error
    assert resp.result["kind"] == "Analog"
    assert len(ctx.song.tracks[0].devices) == 1
    assert ctx.application.browser.load_calls[0].name == "Analog"


def test_load_drum_rack_ignores_cross_category_namesake(loaded_actions):
    """W7-0: user has an Instrument Rack preset named ``Drum Rack`` in the
    instruments root. The canonical empty Drum Rack lives under drums.
    Restricted-root walk MUST pick the drums-root node, never the
    instruments imposter.
    """
    ctx = FakeCtx(FakeSong(tracks=[FakeTrack("T1")]))
    imposter = FakeBrowserItem(
        "Drum Rack", uri="query:Instruments#Imposter", is_loadable=True,
    )
    canonical = FakeBrowserItem(
        "Drum Rack", uri="query:Drums#Empty", is_loadable=True,
    )
    ctx.application.browser.instruments.children.append(imposter)
    ctx.application.browser.drums.children.append(canonical)
    resp = dispatch(
        Request(
            tool="ableton_device", action="load",
            params={"node": {"parent": {"kind": "track", "index": 1}, "terminal": "track"}, "kind": "Drum Rack"},
        ),
        context=ctx,
    )
    assert resp.ok is True, resp.error
    assert ctx.application.browser.load_calls[0].uri == "query:Drums#Empty"


def test_load_drum_rack_kind_restricted_to_drums_post_d4(loaded_actions):
    """Arc 4 / D4: pre-D4 this test called the loader with
    ``kind='DrumGroupDevice'`` (internal class) and relied on the
    translation table + rack-root restriction applying to the
    translated candidate. Under the new convention push sends
    ``kind='Drum Rack'`` directly (browser display name, populated by
    pull from ``device.class_display_name``); the rack-root
    restriction applies to the display name itself. An instruments-
    root imposter named ``Drum Rack`` still must NOT match.
    """
    ctx = FakeCtx(FakeSong(tracks=[FakeTrack("T1")]))
    ctx.application.browser.instruments.children.append(
        FakeBrowserItem("Drum Rack", uri="query:Instruments#Imposter"),
    )
    ctx.application.browser.drums.children.append(
        FakeBrowserItem("Drum Rack", uri="query:Drums#Empty"),
    )
    resp = dispatch(
        Request(
            tool="ableton_device", action="load",
            params={"node": {"parent": {"kind": "track", "index": 1}, "terminal": "track"}, "kind": "Drum Rack"},
        ),
        context=ctx,
    )
    assert resp.ok is True, resp.error
    assert ctx.application.browser.load_calls[0].uri == "query:Drums#Empty"


def test_load_audio_effect_rack_restricted_to_audio_effects_root(loaded_actions):
    """Parallel to the Drum Rack case for Audio Effect Rack."""
    ctx = FakeCtx(FakeSong(tracks=[FakeTrack("T1")]))
    ctx.application.browser.instruments.children.append(
        FakeBrowserItem("Audio Effect Rack", uri="query:Instruments#Wrong"),
    )
    ctx.application.browser.audio_effects.children.append(
        FakeBrowserItem("Audio Effect Rack", uri="query:AudioEffects#Right"),
    )
    resp = dispatch(
        Request(
            tool="ableton_device", action="load",
            params={"node": {"parent": {"kind": "track", "index": 1}, "terminal": "track"}, "kind": "Audio Effect Rack"},
        ),
        context=ctx,
    )
    assert resp.ok is True, resp.error
    assert ctx.application.browser.load_calls[0].uri == "query:AudioEffects#Right"


def test_load_instrument_rack_finds_canonical_under_instruments(loaded_actions):
    """When an empty Instrument Rack node IS exposed under the
    instruments root, the rack-kind walk finds it.
    """
    ctx = FakeCtx(FakeSong(tracks=[FakeTrack("T1")]))
    ctx.application.browser.instruments.children.append(
        FakeBrowserItem("Instrument Rack", uri="query:Instruments#Empty"),
    )
    resp = dispatch(
        Request(
            tool="ableton_device", action="load",
            params={"node": {"parent": {"kind": "track", "index": 1}, "terminal": "track"}, "kind": "Instrument Rack"},
        ),
        context=ctx,
    )
    assert resp.ok is True, resp.error
    assert ctx.application.browser.load_calls[0].uri == "query:Instruments#Empty"


def test_load_instrument_rack_missing_node_teaches_workaround(loaded_actions):
    """Backlog #35: bare ``kind='Instrument Rack'`` with no loadable node
    surfaces a teaching error pointing at the Cmd+G workaround instead of
    Live's bare ``did not append`` runtime error.
    """
    ctx = FakeCtx(FakeSong(tracks=[FakeTrack("T1")]))
    # No nodes added — restricted walk on instruments finds nothing.
    resp = dispatch(
        Request(
            tool="ableton_device", action="load",
            params={"node": {"parent": {"kind": "track", "index": 1}, "terminal": "track"}, "kind": "Instrument Rack"},
        ),
        context=ctx,
    )
    assert resp.ok is False
    err = resp.error or ""
    assert "Instrument Rack" in err
    assert "instruments" in err  # canonical-root mention
    assert "Cmd+G" in err or "preset_uri" in err  # workaround pointer


# ---------- preset_query (Sweep B — compose-time portable selection) ----------


def _load_with_query(ctx, **query_fields):
    """Helper — invoke load with a preset_query dict."""
    return dispatch(
        Request(
            tool="ableton_device", action="load",
            params={
                "node": {"parent": {"kind": "track", "index": 1}, "terminal": "track"}, "kind": "DrumGroupDevice",
                "preset_query": query_fields,
            },
        ),
        context=ctx,
    )


def test_load_preset_query_unique_match_loads_that_item(loaded_actions):
    """preset_query resolves to exactly one loadable node; load picks it."""
    ctx = FakeCtx(FakeSong(tracks=[FakeTrack("T1")]))
    # Only one '909' kit in the browser → unambiguous.
    ctx.application.browser.drums.children.append(
        FakeBrowserItem("Late Nite Kit", uri="query:Drums#FileId_5500",
                        is_loadable=True),
    )
    ctx.application.browser.drums.children.append(
        FakeBrowserItem("Vintage Funk", uri="query:Drums#FileId_5600",
                        is_loadable=True),
    )
    resp = _load_with_query(ctx, root="drums", pattern="Late Nite")
    assert resp.ok is True, resp.error
    assert ctx.application.browser.load_calls[0].uri == \
        "query:Drums#FileId_5500"


def test_load_preset_query_no_match_refuses_with_teaching_error(loaded_actions):
    ctx = FakeCtx(FakeSong(tracks=[FakeTrack("T1")]))
    ctx.application.browser.drums.children.append(
        FakeBrowserItem("Late Nite Kit", uri="query:Drums#FileId_5500"),
    )
    resp = _load_with_query(ctx, root="drums", pattern="Nonexistent")
    assert resp.ok is False
    assert "no loadable matches" in (resp.error or "")
    assert "Tighten the scope" in (resp.error or "") or \
        "ableton_browser" in (resp.error or "")


def test_load_preset_query_ambiguous_match_refuses(loaded_actions):
    """Strict mode — two matches must refuse, not silently pick first."""
    ctx = FakeCtx(FakeSong(tracks=[FakeTrack("T1")]))
    ctx.application.browser.drums.children.append(
        FakeBrowserItem("Kit-Core 909", uri="query:Drums#FileId_5418"),
    )
    ctx.application.browser.drums.children.append(
        FakeBrowserItem("Kit-Vintage 909", uri="query:Drums#FileId_5419"),
    )
    resp = _load_with_query(ctx, root="drums", pattern="909")
    assert resp.ok is False
    assert "ambiguous" in (resp.error or "")
    assert "Kit-Core 909" in (resp.error or "")
    assert "Kit-Vintage 909" in (resp.error or "")
    # Refusal must mean no load was issued.
    assert ctx.application.browser.load_calls == []


def test_load_preset_query_path_prefix_disambiguates(loaded_actions):
    """Same pattern, two parent folders — path_prefix narrows to one."""
    ctx = FakeCtx(FakeSong(tracks=[FakeTrack("T1")]))
    impulse_folder = FakeBrowserItem(
        "Impulse", is_loadable=False, children=(
            FakeBrowserItem("Kit-909", uri="query:Impulse#909",
                            is_loadable=True),
        ),
    )
    drumrack_folder = FakeBrowserItem(
        "Drum Rack", is_loadable=False, children=(
            FakeBrowserItem("Kit-909", uri="query:DrumRack#909",
                            is_loadable=True),
        ),
    )
    ctx.application.browser.drums.children.extend([impulse_folder, drumrack_folder])
    resp = _load_with_query(
        ctx, root="drums", pattern="909", path_prefix=["Impulse"],
    )
    assert resp.ok is True, resp.error
    assert ctx.application.browser.load_calls[0].uri == "query:Impulse#909"


def test_load_preset_query_glob_mode(loaded_actions):
    ctx = FakeCtx(FakeSong(tracks=[FakeTrack("T1")]))
    ctx.application.browser.drums.children.append(
        FakeBrowserItem("Kit-Core 909", uri="query:Drums#5418"),
    )
    # Other entries don't match the pattern Kit-Core* → unambiguous.
    ctx.application.browser.drums.children.append(
        FakeBrowserItem("Vintage Funk", uri="query:Drums#5500"),
    )
    resp = _load_with_query(
        ctx, root="drums", pattern="Kit-Core*", mode="glob",
    )
    assert resp.ok is True, resp.error
    assert ctx.application.browser.load_calls[0].uri == "query:Drums#5418"


def test_load_preset_query_invalid_mode_rejected(loaded_actions):
    ctx = FakeCtx(FakeSong(tracks=[FakeTrack("T1")]))
    ctx.application.browser.drums.children.append(
        FakeBrowserItem("X", uri="q:x"),
    )
    resp = _load_with_query(ctx, root="drums", pattern="X", mode="fuzzy")
    assert resp.ok is False
    assert "mode" in (resp.error or "")


def test_load_preset_query_unknown_root_errors(loaded_actions):
    ctx = FakeCtx(FakeSong(tracks=[FakeTrack("T1")]))
    resp = _load_with_query(ctx, root="bogus", pattern="x")
    assert resp.ok is False
    assert "root" in (resp.error or "")


def test_load_preset_query_path_prefix_unknown_segment_lists_available(loaded_actions):
    ctx = FakeCtx(FakeSong(tracks=[FakeTrack("T1")]))
    ctx.application.browser.drums.children.append(
        FakeBrowserItem("Impulse", is_loadable=False, children=()),
    )
    resp = _load_with_query(
        ctx, root="drums", pattern="x", path_prefix=["NoSuchFolder"],
    )
    assert resp.ok is False
    assert "NoSuchFolder" in (resp.error or "")
    assert "available" in (resp.error or "")


def test_load_preset_query_exact_mode_resolves_substring_collision(loaded_actions):
    """A precise preset name that is a substring of another resolves uniquely
    in exact mode. substring would match both → ambiguous; exact anchors to the
    whole leaf name. (The 'Saturated Bass' vs 'Basic Saturated Bass' friction.)"""
    ctx = FakeCtx(FakeSong(tracks=[FakeTrack("T1")]))
    ctx.application.browser.drums.children.append(
        FakeBrowserItem("Saturated Bass", uri="query:Drums#exact"),
    )
    ctx.application.browser.drums.children.append(
        FakeBrowserItem("Basic Saturated Bass", uri="query:Drums#super"),
    )
    # substring matches BOTH → strict mode refuses.
    sub = _load_with_query(ctx, root="drums", pattern="Saturated Bass")
    assert sub.ok is False
    assert "ambiguous" in (sub.error or "")
    # exact matches only the whole-name node → unambiguous load.
    ex = _load_with_query(
        ctx, root="drums", pattern="Saturated Bass", mode="exact",
    )
    assert ex.ok is True, ex.error
    assert ctx.application.browser.load_calls[-1].uri == "query:Drums#exact"


def test_load_rack_kind_class_mismatch_emits_warning(loaded_actions):
    """kind='Drum Rack' resolving to an Instrument Rack (a user preset shadowed
    the canonical rack in the browser walk) returns a `warning` naming the
    mismatch — instead of silently succeeding until a Drum-Rack-only op fails."""
    track = FakeTrack("T1")
    ctx = FakeCtx(FakeSong(tracks=[track]))
    _add_browser_item(ctx, "drums", "Drum Rack", uri="query:DrumRack")
    # Shadow trap: the walk matched a 'Drum Rack' node but Live instantiated an
    # Instrument Rack (class_display_name = "Instrument Rack").
    def fake_load(item):
        ctx.application.browser.load_calls.append(item)
        track.devices.append(
            FakeDevice(name="Acuff Kit", class_name="Instrument Rack"),
        )
    ctx.application.browser.load_item = fake_load
    resp = dispatch(
        Request(
            tool="ableton_device", action="load",
            params={"node": {"parent": {"kind": "track", "index": 1}, "terminal": "track"}, "kind": "Drum Rack"},
        ),
        context=ctx,
    )
    assert resp.ok is True, resp.error
    assert resp.result["loaded_class_name"] == "Instrument Rack"
    assert "warning" in resp.result
    assert "Drum Rack" in resp.result["warning"]
    assert "Instrument Rack" in resp.result["warning"]


def test_load_rack_kind_class_match_has_no_warning(loaded_actions):
    """A correctly-resolved rack (loaded class == requested rack kind) carries
    no warning — the mismatch field only appears on a real divergence."""
    track = FakeTrack("T1")
    ctx = FakeCtx(FakeSong(tracks=[track]))
    _add_browser_item(ctx, "drums", "Drum Rack", uri="query:DrumRack")
    # Default load_item appends a device named like the matched item ("Drum
    # Rack"), so class_display_name == kind.
    resp = dispatch(
        Request(
            tool="ableton_device", action="load",
            params={"node": {"parent": {"kind": "track", "index": 1}, "terminal": "track"}, "kind": "Drum Rack"},
        ),
        context=ctx,
    )
    assert resp.ok is True, resp.error
    assert resp.result["loaded_class_name"] == "Drum Rack"
    assert "warning" not in resp.result


def test_load_non_rack_kind_class_difference_does_not_warn(loaded_actions):
    """A non-rack kind whose loaded class differs (e.g. a preset whose device
    class isn't the kind label) must NOT warn — only the four rack display
    names are a reliable kind==class identity, so the warning is scoped to them
    to avoid false positives on built-in classes / preset loads."""
    track = FakeTrack("T1")
    ctx = FakeCtx(FakeSong(tracks=[track]))
    _add_browser_item(ctx, "instruments", "Sub Bass", uri="query:SubBass")

    def fake_load(item):
        ctx.application.browser.load_calls.append(item)
        track.devices.append(
            FakeDevice(name="Sub Bass", class_name="Instrument Rack"),
        )
    ctx.application.browser.load_item = fake_load
    resp = dispatch(
        Request(
            tool="ableton_device", action="load",
            params={"node": {"parent": {"kind": "track", "index": 1}, "terminal": "track"}, "kind": "Sub Bass"},
        ),
        context=ctx,
    )
    assert resp.ok is True, resp.error
    assert "warning" not in resp.result


def test_load_preset_query_and_preset_uri_mutually_exclusive(loaded_actions):
    ctx = FakeCtx(FakeSong(tracks=[FakeTrack("T1")]))
    resp = dispatch(
        Request(
            tool="ableton_device", action="load",
            params={
                "node": {"parent": {"kind": "track", "index": 1}, "terminal": "track"}, "kind": "DrumGroupDevice",
                "preset_uri": "query:Drums#1",
                "preset_query": {"root": "drums", "pattern": "x"},
            },
        ),
        context=ctx,
    )
    assert resp.ok is False
    assert "mutually exclusive" in (resp.error or "")


def test_load_preset_query_skips_non_loadable_match(loaded_actions):
    """A folder named 'Kit-909' that ISN'T loadable + a leaf named '909 Kit'
    that IS loadable: the resolver returns the loadable one (no double-match
    because the folder is filtered)."""
    ctx = FakeCtx(FakeSong(tracks=[FakeTrack("T1")]))
    ctx.application.browser.drums.children.append(
        FakeBrowserItem("909-Folder", is_loadable=False, children=(
            FakeBrowserItem("Leaf inside", uri="q:1"),
        )),
    )
    ctx.application.browser.drums.children.append(
        FakeBrowserItem("909 Kit", uri="query:909-leaf", is_loadable=True),
    )
    resp = _load_with_query(ctx, root="drums", pattern="909")
    # Only the loadable leaf matches; folder is filtered.
    assert resp.ok is True, resp.error
    assert ctx.application.browser.load_calls[0].uri == "query:909-leaf"


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
                "node": {"parent": {"kind": "track", "index": 1}, "device_index": 1},
                "parameter_name": "Threshold", "value": "-24.0",
            },
        ),
        context=ctx,
    )
    assert resp.ok is True
    assert dev.parameters[0].value == -24.0


def _freq_hz_khz(raw: float) -> str:
    """20 Hz .. 22 kHz across [0,1], rendered Hz below 1 kHz then kHz — the
    real EQ-freq shape whose leading number reverses at the unit switch."""
    hz = 20.0 * (1100.0 ** raw)
    return f"{hz / 1000.0:.2f} kHz" if hz >= 1000.0 else f"{hz:.1f} Hz"


def test_set_parameter_non_monotonic_unit_display_resolves_and_echoes_value_real(
    loaded_actions,
):
    """DPP-7H2K(a)+(b): a Hz/kHz freq param is settable by an explicit-unit
    display string (no reverse-engineering the raw curve), AND the response
    echoes value_real/value_real_unit at full precision so a phase-critical
    rate is verifiable beyond the device's rounded value_display."""
    dev = FakeDevice("EQ", parameters=[
        FakeParam("Freq", 0.5, min=0.0, max=1.0, display_fn=_freq_hz_khz),
    ])
    ctx = FakeCtx(FakeSong(tracks=[FakeTrack("T1", devices=[dev])]))
    resp = dispatch(
        Request(
            tool="ableton_device", action="set_parameter",
            params={
                "node": {"parent": {"kind": "track", "index": 1}, "device_index": 1},
                "parameter_name": "Freq", "value_display": "2 kHz",
            },
        ),
        context=ctx,
    )
    assert resp.ok is True
    # (a) the param actually moved to ~2 kHz — canonical inversion worked.
    assert _freq_hz_khz(dev.parameters[0].value) == "2.00 kHz"
    # (b) the response carries the achieved magnitude in its base unit.
    assert resp.result["value_real"] == pytest.approx(2000.0)
    assert resp.result["value_real_unit"] == "Hz"


def test_set_parameter_raw_value_omits_value_real(loaded_actions):
    """value_real is only attached for a recognised-unit value_display write;
    a raw `value` write carries the exact `value` already (no value_real)."""
    dev = FakeDevice("Comp", parameters=[
        FakeParam("Threshold", -12.0, min=-60.0, max=0.0),
    ])
    ctx = FakeCtx(FakeSong(tracks=[FakeTrack("T1", devices=[dev])]))
    resp = dispatch(
        Request(
            tool="ableton_device", action="set_parameter",
            params={
                "node": {"parent": {"kind": "track", "index": 1}, "device_index": 1},
                "parameter_name": "Threshold", "value": "-24.0",
            },
        ),
        context=ctx,
    )
    assert resp.ok is True
    assert "value_real" not in resp.result


def test_set_parameter_continuous_out_of_range(loaded_actions):
    dev = FakeDevice("Comp", parameters=[
        FakeParam("Threshold", -12.0, min=-60.0, max=0.0),
    ])
    ctx = FakeCtx(FakeSong(tracks=[FakeTrack("T1", devices=[dev])]))
    resp = dispatch(
        Request(
            tool="ableton_device", action="set_parameter",
            params={
                "node": {"parent": {"kind": "track", "index": 1}, "device_index": 1},
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
                "node": {"parent": {"kind": "track", "index": 1}, "device_index": 1},
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
                "node": {"parent": {"kind": "track", "index": 1}, "device_index": 1},
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
                "node": {"parent": {"kind": "track", "index": 1}, "device_index": 1},
                "parameter_name": "Threshold", "value": "Lowpass",
                "value_type": "enum",
            },
        ),
        context=ctx,
    )
    assert resp.ok is False
    assert "not an enum" in (resp.error or "")


def _db_param(name: str = "Threshold") -> FakeParam:
    """A normalized [0,1] param whose display renders dB, like a real Compressor
    Threshold: raw 0 -> -70 dB, raw 1 -> 0 dB. str_for_value is the only inverse
    Live exposes, so value_display must bisect it."""
    return FakeParam(
        name, 0.5, min=0.0, max=1.0,
        display_fn=lambda v: f"{-70.0 + v * 70.0:.2f} dB",
    )


def test_set_parameter_value_display_resolves_to_raw(loaded_actions):
    threshold = _db_param()
    dev = FakeDevice("Comp", parameters=[threshold])
    ctx = FakeCtx(FakeSong(tracks=[FakeTrack("T1", devices=[dev])]))
    resp = dispatch(
        Request(
            tool="ableton_device", action="set_parameter",
            params={
                "node": {"parent": {"kind": "track", "index": 1}, "device_index": 1},
                "parameter_name": "Threshold", "value_display": "-18 dB",
            },
        ),
        context=ctx,
    )
    assert resp.ok is True, resp.error
    # -18 dB on the -70..0 curve is raw (-18+70)/70.
    assert threshold.value == pytest.approx((-18.0 + 70.0) / 70.0, abs=1e-3)
    # The response echoes the achieved display so the caller can confirm.
    assert resp.result["value_display"] == "-18.00 dB"


def test_set_parameter_value_and_display_mutually_exclusive(loaded_actions):
    dev = FakeDevice("Comp", parameters=[_db_param()])
    ctx = FakeCtx(FakeSong(tracks=[FakeTrack("T1", devices=[dev])]))
    resp = dispatch(
        Request(
            tool="ableton_device", action="set_parameter",
            params={
                "node": {"parent": {"kind": "track", "index": 1}, "device_index": 1},
                "parameter_name": "Threshold",
                "value": "0.5", "value_display": "-18 dB",
            },
        ),
        context=ctx,
    )
    assert resp.ok is False
    assert "exactly one" in (resp.error or "")


def test_set_parameter_continuous_requires_value_or_display(loaded_actions):
    dev = FakeDevice("Comp", parameters=[_db_param()])
    ctx = FakeCtx(FakeSong(tracks=[FakeTrack("T1", devices=[dev])]))
    resp = dispatch(
        Request(
            tool="ableton_device", action="set_parameter",
            params={
                "node": {"parent": {"kind": "track", "index": 1}, "device_index": 1},
                "parameter_name": "Threshold",
            },
        ),
        context=ctx,
    )
    assert resp.ok is False
    assert "exactly one" in (resp.error or "")


def test_set_parameter_value_display_rejected_on_enum(loaded_actions):
    dev = FakeDevice("Filter", parameters=[
        FakeParam("Filter Type", 0.0, value_items=("Lowpass", "Highpass")),
    ])
    ctx = FakeCtx(FakeSong(tracks=[FakeTrack("T1", devices=[dev])]))
    resp = dispatch(
        Request(
            tool="ableton_device", action="set_parameter",
            params={
                "node": {"parent": {"kind": "track", "index": 1}, "device_index": 1},
                "parameter_name": "Filter Type", "value_display": "Highpass",
            },
        ),
        context=ctx,
    )
    assert resp.ok is False
    assert "enum" in (resp.error or "")


def test_set_parameter_device_path_value_display_parity(loaded_actions):
    """value_display resolves identically through device_path — the shared
    resolve_continuous_write keeps the contract in lock-step (B4 lesson).
    Migrated from set_parameter_in_rack (DEEP-RACK-ADDR)."""
    threshold = _db_param()
    nested = FakeDevice("Comp", class_name="Compressor2", parameters=[threshold])
    chain = _FakeChain("Lead", devices=[nested])
    rack = _FakeRackDevice("Rack", chains=[chain])
    ctx = FakeCtx(FakeSong(tracks=[FakeTrack("T1", devices=[rack])]))
    resp = dispatch(
        Request(
            tool="ableton_device", action="set_parameter",
            params={
                "node": {"parent": {"kind": "track", "index": 1}, "device_index": 1, "path": [{"chain_index": 1, "device_position": 1}]},
                "parameter_name": "Threshold", "value_display": "-18 dB",
            },
        ),
        context=ctx,
    )
    assert resp.ok is True, resp.error
    assert threshold.value == pytest.approx((-18.0 + 70.0) / 70.0, abs=1e-3)
    assert resp.result["value_display"] == "-18.00 dB"
    assert resp.result["device_path"] == [
        {"chain_index": 1, "device_position": 1}
    ]


def test_set_parameter_device_path_unit_display_attaches_value_real(loaded_actions):
    """device_path writes share _attach_real_unit_echo: a recognised-unit
    value_display write echoes value_real/value_real_unit identically to the
    top-level set_parameter (DPP-7H2K(b) parity across both write sites)."""
    freq = FakeParam("Freq", 0.5, min=0.0, max=1.0, display_fn=_freq_hz_khz)
    nested = FakeDevice("EQ", class_name="Eq8", parameters=[freq])
    chain = _FakeChain("Lead", devices=[nested])
    rack = _FakeRackDevice("Rack", chains=[chain])
    ctx = FakeCtx(FakeSong(tracks=[FakeTrack("T1", devices=[rack])]))
    resp = dispatch(
        Request(
            tool="ableton_device", action="set_parameter",
            params={
                "node": {"parent": {"kind": "track", "index": 1}, "device_index": 1, "path": [{"chain_index": 1, "device_position": 1}]},
                "parameter_name": "Freq", "value_display": "2 kHz",
            },
        ),
        context=ctx,
    )
    assert resp.ok is True, resp.error
    assert _freq_hz_khz(freq.value) == "2.00 kHz"
    assert resp.result["value_real"] == pytest.approx(2000.0)
    assert resp.result["value_real_unit"] == "Hz"


def test_set_parameter_unknown_name(loaded_actions):
    dev = FakeDevice("Comp", parameters=[FakeParam("Threshold", -12.0)])
    ctx = FakeCtx(FakeSong(tracks=[FakeTrack("T1", devices=[dev])]))
    resp = dispatch(
        Request(
            tool="ableton_device", action="set_parameter",
            params={
                "node": {"parent": {"kind": "track", "index": 1}, "device_index": 1},
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
    plus the input_routing_* API. W6-K real-Live 2026-05-22:
    Compressor's S/C Gain has internal range 0.0..1.0 (normalized) —
    fake mirrors that so the dB-rejection path is exercised."""
    comp = FakeDevice(
        "Comp",
        class_name="Compressor2",
        parameters=[
            FakeParam("Device On", 1.0),
            FakeParam("Threshold", 0.85),
            FakeParam("S/C On", 0.0),
            FakeParam("S/C Gain", 0.4, min=0.0, max=1.0),
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
    naming hints). gain_db is covered by separate dB-native /
    normalized-refuse tests below."""
    comp = _compressor_with_routing()
    ctx = FakeCtx(FakeSong(tracks=[
        FakeTrack("T1", devices=[comp]), FakeTrack("1-Drums"),
    ]))
    resp = dispatch(
        Request(
            tool="ableton_device", action="set_sidechain",
            params={
                "node": {"parent": {"kind": "track", "index": 1}, "device_index": 1},
                "enabled": True,
                "source": {"parent": {"kind": "track", "index": 2}, "terminal": "track"},
            },
        ),
        context=ctx,
    )
    assert resp.ok is True, resp.error
    sc_on = next(p for p in comp.parameters if p.name == "S/C On")
    assert sc_on.value == 1.0
    assert comp.input_routing_type.display_name == "1-Drums"


def _compressor_with_db_native_gain() -> FakeDevice:
    """A hypothetical compressor whose S/C Gain IS dB-native (range
    -24..24). Used to validate that the gain_db path still works for
    devices that don't follow Live's normalized-0..1 convention."""
    comp = FakeDevice(
        "Comp-dB",
        class_name="ThirdPartyComp",
        parameters=[
            FakeParam("Device On", 1.0),
            FakeParam("Threshold", 0.85),
            FakeParam("S/C On", 0.0),
            FakeParam("S/C Gain", 0.0, min=-24.0, max=24.0),
            FakeParam("S/C Mix", 1.0),
        ],
    )
    comp.input_routing_type = _Routing("No Input")
    comp.input_routing_channel = _Routing("Post FX")
    comp.available_input_routing_types = [
        _Routing("1-Drums"), _Routing("No Input"),
    ]
    comp.available_input_routing_channels = [
        _Routing("Pre FX"), _Routing("Post FX"), _Routing("Post Mixer"),
    ]
    return comp


def test_set_sidechain_gain_db_succeeds_on_db_native_param(loaded_actions):
    """When the gain param's range is NOT normalized 0..1, gain_db
    writes through directly — preserving the convenience wrapper for
    plugins that expose a true dB-native gain."""
    comp = _compressor_with_db_native_gain()
    ctx = FakeCtx(FakeSong(tracks=[
        FakeTrack("T1", devices=[comp]), FakeTrack("1-Drums"),
    ]))
    resp = dispatch(
        Request(
            tool="ableton_device", action="set_sidechain",
            params={
                "node": {"parent": {"kind": "track", "index": 1}, "device_index": 1},
                "enabled": True,
                "source": {"parent": {"kind": "track", "index": 2}, "terminal": "track"},
                "gain_db": 3.0,
            },
        ),
        context=ctx,
    )
    assert resp.ok is True, resp.error
    sc_gain = next(p for p in comp.parameters if p.name == "S/C Gain")
    assert sc_gain.value == 3.0
    assert comp.input_routing_type.display_name == "1-Drums"


def test_set_sidechain_gain_db_refuses_on_normalized_param(loaded_actions):
    """W6-K real-Live finding (2026-05-22): Live's Compressor S/C Gain
    has internal range 0..1 despite displaying in dB. Writing gain_db
    directly trips Live's range check. Handler refuses with a teaching
    error pointing at set_parameter."""
    comp = _compressor_with_routing()
    ctx = FakeCtx(FakeSong(tracks=[
        FakeTrack("T1", devices=[comp]), FakeTrack("1-Drums"),
    ]))
    resp = dispatch(
        Request(
            tool="ableton_device", action="set_sidechain",
            params={
                "node": {"parent": {"kind": "track", "index": 1}, "device_index": 1},
                "enabled": True,
                "source": {"parent": {"kind": "track", "index": 2}, "terminal": "track"},
                "gain_db": 3.0,
            },
        ),
        context=ctx,
    )
    assert resp.ok is False
    err = resp.error or ""
    assert "normalized" in err
    assert "set_parameter" in err
    assert "S/C Gain" in err


def test_set_sidechain_normalized_gain_refusal_does_not_touch_state(loaded_actions):
    """The gain_db pre-validation refusal happens BEFORE enable/routing
    side effects — partial-application would leave the user with a
    half-configured sidechain that's hard to reason about."""
    comp = _compressor_with_routing()
    sc_on_before = next(p for p in comp.parameters if p.name == "S/C On").value
    routing_before = comp.input_routing_type.display_name
    ctx = FakeCtx(FakeSong(tracks=[
        FakeTrack("T1", devices=[comp]), FakeTrack("1-Drums"),
    ]))
    resp = dispatch(
        Request(
            tool="ableton_device", action="set_sidechain",
            params={
                "node": {"parent": {"kind": "track", "index": 1}, "device_index": 1},
                "enabled": True,
                "source": {"parent": {"kind": "track", "index": 2}, "terminal": "track"},
                "gain_db": 3.0,
            },
        ),
        context=ctx,
    )
    assert resp.ok is False
    # Neither side effect applied.
    sc_on = next(p for p in comp.parameters if p.name == "S/C On")
    assert sc_on.value == sc_on_before
    assert comp.input_routing_type.display_name == routing_before


def test_set_sidechain_works_on_glue_for_enable_only(loaded_actions):
    """Glue Compressor has S/C params but no input_routing_* — enable
    succeeds; source routing without a source_display_name doesn't
    attempt the routing primitive."""
    glue = _glue_compressor_without_routing()
    ctx = FakeCtx(FakeSong(tracks=[FakeTrack("T1", devices=[glue])]))
    resp = dispatch(
        Request(
            tool="ableton_device", action="set_sidechain",
            params={"node": {"parent": {"kind": "track", "index": 1}, "device_index": 1}, "enabled": True},
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
    ctx = FakeCtx(FakeSong(tracks=[
        FakeTrack("T1", devices=[glue]), FakeTrack("1-Drums"),
    ]))
    resp = dispatch(
        Request(
            tool="ableton_device", action="set_sidechain",
            params={
                "node": {"parent": {"kind": "track", "index": 1}, "device_index": 1},
                "enabled": True,
                "source": {"parent": {"kind": "track", "index": 2}, "terminal": "track"},
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
            params={"node": {"parent": {"kind": "track", "index": 1}, "device_index": 1}, "enabled": False},
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
            params={"node": {"parent": {"kind": "track", "index": 1}, "device_index": 1}, "enabled": True},
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


# ---------- nested rack chains (W6-I / W6-J) ----------


class _FakeChainMixer:
    def __init__(self, volume: float = 0.85, panning: float = 0.0):
        self.volume = FakeParam("Volume", volume, min=0.0, max=1.0)
        self.panning = FakeParam("Panning", panning, min=-1.0, max=1.0)


class _FakeChain:
    def __init__(self, name: str, devices: list[FakeDevice] | None = None,
                 *, mute: bool = False, solo: bool = False):
        self.name = name
        self.devices = list(devices or [])
        self.mixer_device = _FakeChainMixer()
        self.mute = mute
        self.solo = solo

    def insert_device(self, name: str, index: int = -1) -> FakeDevice:
        # Models Live's Chain.insert_device(DeviceName, DeviceIndex=-1): adds a
        # device by browser display name (at end when index=-1) and returns it.
        dev = FakeDevice(name, class_name=name)
        if index == -1:
            self.devices.append(dev)
        else:
            self.devices.insert(index, dev)
        return dev


class _FakeRackView:
    def __init__(self):
        self.selected_chain = None


class _FakeRackDevice(FakeDevice):
    """Mirrors InstrumentGroupDevice / AudioEffectGroupDevice — has
    `chains` + a view with selected_chain."""
    def __init__(self, name: str = "Rack", chains: list[_FakeChain] | None = None):
        super().__init__(name, class_name="InstrumentGroupDevice")
        self.chains = chains or []
        self.view = _FakeRackView()
        self.can_have_chains = True


def test_get_device_chains_summary(loaded_actions):
    nested_a = FakeDevice("Sub-A", class_name="Operator")
    nested_b = FakeDevice("Sub-B", class_name="Compressor2")
    chain = _FakeChain("Lead", devices=[nested_a, nested_b])
    rack = _FakeRackDevice("Rack", chains=[chain])
    ctx = FakeCtx(FakeSong(tracks=[FakeTrack("T1", devices=[rack])]))
    resp = dispatch(
        Request(
            tool="ableton_device", action="get_device_chains",
            params={"track_index": 1, "device_index": 1},
        ),
        context=ctx,
    )
    assert resp.ok is True, resp.error
    r = resp.result
    assert r["chain_count"] == 1
    assert r["chains"][0]["name"] == "Lead"
    assert r["chains"][0]["device_count"] == 2
    names = [d["name"] for d in r["chains"][0]["devices"]]
    assert names == ["Sub-A", "Sub-B"]


def test_get_device_chains_full_includes_mixer(loaded_actions):
    nested = FakeDevice("Sub", class_name="Operator")
    chain = _FakeChain("Lead", devices=[nested])
    rack = _FakeRackDevice("Rack", chains=[chain])
    ctx = FakeCtx(FakeSong(tracks=[FakeTrack("T1", devices=[rack])]))
    resp = dispatch(
        Request(
            tool="ableton_device", action="get_device_chains",
            params={"track_index": 1, "device_index": 1, "detail": "full"},
        ),
        context=ctx,
    )
    assert resp.ok is True
    assert "mixer" in resp.result["chains"][0]
    assert resp.result["chains"][0]["mixer"]["volume"] == 0.85


def test_get_device_chains_non_rack_raises_teaching_error(loaded_actions):
    eq = FakeDevice("EQ", class_name="EQ8")
    ctx = FakeCtx(FakeSong(tracks=[FakeTrack("T1", devices=[eq])]))
    resp = dispatch(
        Request(
            tool="ableton_device", action="get_device_chains",
            params={"track_index": 1, "device_index": 1},
        ),
        context=ctx,
    )
    assert resp.ok is False
    err = resp.error or ""
    assert "EQ8" in err
    assert "rack" in err.lower()


def test_set_parameter_device_path_writes_continuous_value(loaded_actions):
    threshold = FakeParam("Threshold", 0.5, min=0.0, max=1.0)
    nested = FakeDevice("Comp", class_name="Compressor2",
                        parameters=[threshold])
    chain = _FakeChain("Lead", devices=[nested])
    rack = _FakeRackDevice("Rack", chains=[chain])
    ctx = FakeCtx(FakeSong(tracks=[FakeTrack("T1", devices=[rack])]))
    resp = dispatch(
        Request(
            tool="ableton_device", action="set_parameter",
            params={
                "node": {"parent": {"kind": "track", "index": 1}, "device_index": 1, "path": [{"chain_index": 1, "device_position": 1}]},
                "parameter_name": "Threshold", "value": "0.75",
            },
        ),
        context=ctx,
    )
    assert resp.ok is True, resp.error
    assert threshold.value == 0.75


def test_set_parameter_device_path_writes_enum_value(loaded_actions):
    filter_type = FakeParam(
        "Filter Type", 0.0, value_items=("Lowpass", "Highpass", "Bandpass"),
    )
    nested = FakeDevice("Op", class_name="Operator", parameters=[filter_type])
    chain = _FakeChain("Lead", devices=[nested])
    rack = _FakeRackDevice("Rack", chains=[chain])
    ctx = FakeCtx(FakeSong(tracks=[FakeTrack("T1", devices=[rack])]))
    resp = dispatch(
        Request(
            tool="ableton_device", action="set_parameter",
            params={
                "node": {"parent": {"kind": "track", "index": 1}, "device_index": 1, "path": [{"chain_index": 1, "device_position": 1}]},
                "parameter_name": "Filter Type", "value": "Highpass",
                "value_type": "enum",
            },
        ),
        context=ctx,
    )
    assert resp.ok is True, resp.error
    assert filter_type.value == 1.0  # index of 'Highpass'
    # Response `value` is the resolved float index, matching set_parameter's
    # top-level enum response shape.
    assert resp.result["value"] == 1.0


def test_set_parameter_device_path_invalid_chain_raises(loaded_actions):
    rack = _FakeRackDevice("Rack", chains=[_FakeChain("Only", devices=[
        FakeDevice("X", parameters=[FakeParam("Y", 0.0)]),
    ])])
    ctx = FakeCtx(FakeSong(tracks=[FakeTrack("T1", devices=[rack])]))
    resp = dispatch(
        Request(
            tool="ableton_device", action="set_parameter",
            params={
                "node": {"parent": {"kind": "track", "index": 1}, "device_index": 1, "path": [{"chain_index": 99, "device_position": 1}]},
                "parameter_name": "Y", "value": "0.5",
            },
        ),
        context=ctx,
    )
    assert resp.ok is False
    assert "chain_index" in (resp.error or "")


# load into a rack chain (load + device_index + chain_index, the DEEP-RACK-ADDR
# replacement for load_in_rack). Models Live 12.4.2: a device is inserted INTO a
# nested chain via Chain.insert_device(name). browser.load_item ONLY ever targets
# the track's MAIN chain (earlier fakes asserted rack.view.selected_chain, then an
# appointed device — both mechanisms real Live ignores; the NODE-ADDR Chunk-A Live
# pass on 2026-06-15 caught the device landing at the track top level, twice). The
# _FakeChain.insert_device fake reproduces the real append-into-chain behavior;
# load_item is never called on the chain path.
def _chain_load_ctx(chain):
    """rack(chain) on track 1 + a browser with 'Compressor2' loadable (for the
    handler's kind-validation walk). The insert itself goes through
    _FakeChain.insert_device."""
    rack = _FakeRackDevice("Rack", chains=[chain])
    track = FakeTrack("T1", devices=[rack])
    ctx = FakeCtx(FakeSong(tracks=[track]))

    class _FakeItem:
        def __init__(self, name):
            self.name = name
            self.is_loadable = True
            self.is_folder = False
            self.uri = ""
            self.children = ()

    class _FakeBrowser:
        def __init__(self, item):
            for root in (
                "audio_effects", "instruments", "midi_effects", "drums",
                "plugins", "user_library", "samples", "sounds",
            ):
                node = _FakeItem(root)
                node.is_loadable = False
                node.is_folder = True
                node.children = (item,) if root == "audio_effects" else ()
                setattr(self, root, node)

    ctx.application.browser = _FakeBrowser(_FakeItem("Compressor2"))
    return ctx


def test_load_into_chain_inserts_device(loaded_actions):
    """A 'chain' terminal load inserts the device INTO the nested chain (not the
    track top level) via Chain.insert_device. Non-empty chain → appended at end."""
    chain = _FakeChain("Lead", devices=[FakeDevice("Seed", class_name="Operator")])
    ctx = _chain_load_ctx(chain)
    resp = dispatch(
        Request(
            tool="ableton_device", action="load",
            params={
                "node": {"parent": {"kind": "track", "index": 1}, "terminal": "chain", "device_index": 1, "chain_index": 1},
                "kind": "Compressor2",
            },
        ),
        context=ctx,
    )
    assert resp.ok is True, resp.error
    assert [d.name for d in chain.devices] == ["Seed", "Compressor2"]
    assert resp.result["nested_device_position"] == 2
    assert resp.result["chain_index"] == 1
    assert resp.result["name"] == "Compressor2"
    # No stray on the track's top-level chain — the bug this fix closes.
    assert [d.name for d in ctx.song.tracks[0].devices] == ["Rack"]


def test_load_into_empty_chain_inserts_device(loaded_actions):
    """insert_device handles an EMPTY chain too — the device lands at position 1
    with no appointed-device dance and no stray on the track's top-level chain."""
    chain = _FakeChain("Empty", devices=[])
    ctx = _chain_load_ctx(chain)
    resp = dispatch(
        Request(
            tool="ableton_device", action="load",
            params={
                "node": {"parent": {"kind": "track", "index": 1}, "terminal": "chain", "device_index": 1, "chain_index": 1},
                "kind": "Compressor2",
            },
        ),
        context=ctx,
    )
    assert resp.ok is True, resp.error
    assert len(chain.devices) == 1
    assert resp.result["nested_device_position"] == 1
    assert [d.name for d in ctx.song.tracks[0].devices] == ["Rack"]


def test_load_into_chain_insert_noop_raises(loaded_actions):
    """Fail-loud backstop: if Chain.insert_device doesn't actually add a device,
    the handler raises rather than reporting a phantom load."""
    class _NoOpChain(_FakeChain):
        def insert_device(self, name, index=-1):
            return None  # broken/no-op insert — chain unchanged

    chain = _NoOpChain("Lead", devices=[FakeDevice("Existing", class_name="Compressor2")])
    ctx = _chain_load_ctx(chain)
    resp = dispatch(
        Request(
            tool="ableton_device", action="load",
            params={
                "node": {"parent": {"kind": "track", "index": 1}, "terminal": "chain", "device_index": 1, "chain_index": 1},
                "kind": "Compressor2",
            },
        ),
        context=ctx,
    )
    assert resp.ok is False
    err = resp.error or ""
    assert "did not add exactly one device" in err
    assert "insert_device" in err
    assert "1:Compressor2" in err


def test_load_preset_into_chain_refused(loaded_actions):
    """Chain.insert_device is built-in-name-only — a preset/plugin selector on a
    chain load is refused (not silently inserting the base device), chain untouched."""
    chain = _FakeChain("Lead", devices=[FakeDevice("Seed", class_name="Operator")])
    ctx = _chain_load_ctx(chain)
    resp = dispatch(
        Request(
            tool="ableton_device", action="load",
            params={
                "node": {"parent": {"kind": "track", "index": 1}, "terminal": "chain", "device_index": 1, "chain_index": 1},
                "kind": "Compressor2",
                "preset_uri": "query:AudioFx#Compressor:FileId_1",
            },
        ),
        context=ctx,
    )
    assert resp.ok is False
    err = resp.error or ""
    assert "preset" in err.lower()
    assert "Chain.insert_device" in err
    assert [d.name for d in chain.devices] == ["Seed"]


# ---------- DEEP-RACK-ADDR: canonical device_path at arbitrary depth ----------


def _deep_rack_ctx():
    """A 3-level-deep rack tree on track 1, device 1:

      device 1            = Outer Rack
        chain 1 'Outer'   -> device 1 = Mid Rack
          chain 1 'Mid'   -> device 1 = Inner Rack
            chain 1 'Inner' -> device 1 = MultiSampler 'Deep Synth' (param 'Macro')

    Returns (ctx, leaf_param, leaf_device). Positional addresses:
      depth 0: device_index=1                                  -> Outer Rack
      depth 1: + [{1,1}]                                       -> Mid Rack
      depth 2: + [{1,1},{1,1}]                                 -> Inner Rack
      depth 3: + [{1,1},{1,1},{1,1}]                           -> Deep Synth
    """
    leaf_param = FakeParam("Macro", 0.5, min=0.0, max=1.0)
    leaf = FakeDevice("Deep Synth", class_name="MultiSampler",
                      parameters=[leaf_param])
    inner = _FakeRackDevice("Inner Rack",
                            chains=[_FakeChain("Inner", devices=[leaf])])
    mid = _FakeRackDevice("Mid Rack",
                          chains=[_FakeChain("Mid", devices=[inner])])
    outer = _FakeRackDevice("Outer Rack",
                            chains=[_FakeChain("Outer", devices=[mid])])
    ctx = FakeCtx(FakeSong(tracks=[FakeTrack("T1", devices=[outer])]))
    return ctx, leaf_param, leaf


_STEP = {"chain_index": 1, "device_position": 1}


def test_resolve_device_path_depth0_is_toplevel():
    ctx, _, _ = _deep_rack_ctx()
    track = ctx.song.tracks[0]
    assert _resolve_device_path(track, 1, None).name == "Outer Rack"
    # Empty list is equivalent to None — the depth-0 behavior.
    assert _resolve_device_path(track, 1, []).name == "Outer Rack"


def test_resolve_device_path_depths_1_2_3():
    ctx, _, leaf = _deep_rack_ctx()
    track = ctx.song.tracks[0]
    assert _resolve_device_path(track, 1, [_STEP]).name == "Mid Rack"
    assert _resolve_device_path(track, 1, [_STEP, _STEP]).name == "Inner Rack"
    assert _resolve_device_path(track, 1, [_STEP, _STEP, _STEP]) is leaf


def test_resolve_device_path_out_of_range_chain():
    ctx, _, _ = _deep_rack_ctx()
    track = ctx.song.tracks[0]
    with pytest.raises(IndexError) as exc:
        _resolve_device_path(track, 1, [{"chain_index": 9, "device_position": 1}])
    assert "chain_index" in str(exc.value)


def test_resolve_device_path_out_of_range_position():
    ctx, _, _ = _deep_rack_ctx()
    track = ctx.song.tracks[0]
    with pytest.raises(IndexError) as exc:
        _resolve_device_path(track, 1, [{"chain_index": 1, "device_position": 9}])
    assert "device_position" in str(exc.value)


def test_resolve_device_path_non_rack_descent_raises_teaching_error():
    ctx, _, _ = _deep_rack_ctx()
    track = ctx.song.tracks[0]
    # Step 4 would descend into the leaf MultiSampler, which is not a rack.
    with pytest.raises(ValueError) as exc:
        _resolve_device_path(track, 1, [_STEP, _STEP, _STEP, _STEP])
    msg = str(exc.value)
    assert "step 4" in msg
    assert "not a rack" in msg


def test_resolve_device_path_depth_cap_rejects_pathological_input():
    ctx, _, _ = _deep_rack_ctx()
    track = ctx.song.tracks[0]
    with pytest.raises(ValueError) as exc:
        _resolve_device_path(track, 1, [_STEP] * 17)
    assert "exceeds the cap" in str(exc.value)


def test_resolve_device_path_malformed_step_raises_teaching_error():
    ctx, _, _ = _deep_rack_ctx()
    track = ctx.song.tracks[0]
    with pytest.raises(ValueError) as exc:
        _resolve_device_path(track, 1, [{"chain_index": 1}])  # missing position
    assert "device_position" in str(exc.value)


def test_get_parameters_at_depth3_via_device_path(loaded_actions):
    ctx, _, _ = _deep_rack_ctx()
    resp = dispatch(
        Request(
            tool="ableton_device", action="get_parameters",
            params={
                "node": {"parent": {"kind": "track", "index": 1}, "device_index": 1, "path": [_STEP, _STEP, _STEP]}, "detail": "full",
            },
        ),
        context=ctx,
    )
    assert resp.ok is True, resp.error
    assert [p["name"] for p in resp.result["parameters"]] == ["Macro"]
    assert resp.result["device_path"] == [_STEP, _STEP, _STEP]


def test_set_parameter_at_depth3_via_device_path(loaded_actions):
    ctx, leaf_param, _ = _deep_rack_ctx()
    resp = dispatch(
        Request(
            tool="ableton_device", action="set_parameter",
            params={
                "node": {"parent": {"kind": "track", "index": 1}, "device_index": 1, "path": [_STEP, _STEP, _STEP]},
                "parameter_name": "Macro", "value": "0.8",
            },
        ),
        context=ctx,
    )
    assert resp.ok is True, resp.error
    assert leaf_param.value == 0.8
    assert resp.result["device_path"] == [_STEP, _STEP, _STEP]


def test_get_device_chains_recurses_reporting_device_path(loaded_actions):
    ctx, _, _ = _deep_rack_ctx()
    resp = dispatch(
        Request(
            tool="ableton_device", action="get_device_chains",
            params={"track_index": 1, "device_index": 1},
        ),
        context=ctx,
    )
    assert resp.ok is True, resp.error
    # Top-level Outer Rack -> chain 'Outer' -> Mid Rack (is_rack, depth-1 path).
    mid = resp.result["chains"][0]["devices"][0]
    assert mid["name"] == "Mid Rack"
    assert mid["is_rack"] is True
    assert mid["device_path"] == [_STEP]
    # Recurses: Mid Rack -> 'Mid' -> Inner Rack (depth-2 path).
    inner = mid["chains"][0]["devices"][0]
    assert inner["name"] == "Inner Rack"
    assert inner["is_rack"] is True
    assert inner["device_path"] == [_STEP, _STEP]
    # Leaf: Inner Rack -> 'Inner' -> Deep Synth (non-rack, depth-3 path).
    leaf = inner["chains"][0]["devices"][0]
    assert leaf["name"] == "Deep Synth"
    assert leaf["is_rack"] is False
    assert leaf["device_path"] == [_STEP, _STEP, _STEP]


def test_device_path_from_get_device_chains_feeds_set_parameter(loaded_actions):
    """Read-by-name, address-by-path: the device_path get_device_chains reports
    for a nested device is exactly what set_parameter accepts — the agent never
    hand-counts indices. Multi-hop: enumerate, then write via the reported path."""
    ctx, leaf_param, _ = _deep_rack_ctx()
    chains = dispatch(
        Request(
            tool="ableton_device", action="get_device_chains",
            params={"track_index": 1, "device_index": 1},
        ),
        context=ctx,
    ).result
    leaf = (
        chains["chains"][0]["devices"][0]      # Mid Rack
        ["chains"][0]["devices"][0]            # Inner Rack
        ["chains"][0]["devices"][0]            # Deep Synth
    )
    resp = dispatch(
        Request(
            tool="ableton_device", action="set_parameter",
            params={
                "node": {"parent": {"kind": "track", "index": 1}, "device_index": 1, "path": leaf["device_path"]},
                "parameter_name": "Macro", "value": "0.9",
            },
        ),
        context=ctx,
    )
    assert resp.ok is True, resp.error
    assert leaf_param.value == 0.9


def test_load_into_nested_chain_via_device_path(loaded_actions):
    """load with device_path + chain_index inserts into a chain of a DEEPLY
    nested rack (depth-2 destination) via Chain.insert_device — proves the
    nested-load path threads the canonical device_path past the depth-1 case."""
    inner_chain = _FakeChain(
        "Inner", devices=[FakeDevice("Inner Seed", class_name="Operator")]
    )
    inner_rack = _FakeRackDevice("Inner Rack", chains=[inner_chain])
    outer_rack = _FakeRackDevice(
        "Outer Rack", chains=[_FakeChain("Outer", devices=[inner_rack])],
    )
    track = FakeTrack("T1", devices=[outer_rack])
    ctx = FakeCtx(FakeSong(tracks=[track]))

    class _FakeItem:
        def __init__(self, name):
            self.name = name
            self.is_loadable = True
            self.is_folder = False
            self.uri = ""
            self.children = ()

    class _FakeBrowser:
        # Only needs to make 'Compressor2' resolvable for the handler's
        # kind-validation walk; the insert goes through _FakeChain.insert_device
        # (load_item is never called on the chain path).
        def __init__(self, item):
            for root in (
                "audio_effects", "instruments", "midi_effects", "drums",
                "plugins", "user_library", "samples", "sounds",
            ):
                node = _FakeItem(root)
                node.is_loadable = False
                node.is_folder = True
                node.children = (item,) if root == "audio_effects" else ()
                setattr(self, root, node)

    ctx.application.browser = _FakeBrowser(_FakeItem("Compressor2"))
    resp = dispatch(
        Request(
            tool="ableton_device", action="load",
            params={
                "node": {"parent": {"kind": "track", "index": 1}, "terminal": "chain", "device_index": 1, "path": [_STEP], "chain_index": 1},
                "kind": "Compressor2",
            },
        ),
        context=ctx,
    )
    assert resp.ok is True, resp.error
    assert resp.result["nested_device_position"] == 2
    assert resp.result["device_path"] == [_STEP]
    assert [d.name for d in inner_chain.devices] == ["Inner Seed", "Compressor2"]


def test_load_chain_index_without_device_index_is_teaching_error(loaded_actions):
    ctx, _, _ = _deep_rack_ctx()
    resp = dispatch(
        Request(
            tool="ableton_device", action="load",
            params={"node": {"parent": {"kind": "track", "index": 1}, "terminal": "chain", "chain_index": 1}, "kind": "Compressor2"},
        ),
        context=ctx,
    )
    assert resp.ok is False
    assert "device_index" in (resp.error or "")


def test_load_device_path_without_chain_index_is_teaching_error(loaded_actions):
    ctx, _, _ = _deep_rack_ctx()
    resp = dispatch(
        Request(
            tool="ableton_device", action="load",
            params={
                "node": {"parent": {"kind": "track", "index": 1}, "terminal": "chain", "device_index": 1, "path": [_STEP]},
                "kind": "Compressor2",
            },
        ),
        context=ctx,
    )
    assert resp.ok is False
    assert "chain_index" in (resp.error or "")


def test_voices_param_on_nested_multisampler_is_covered(loaded_actions):
    """DEEP-RACK-ADDR ask #4, the 'Voices IS a DeviceParameter' branch: when a
    sampler exposes its voice count as a DeviceParameter, the depth-N
    device_path path READS and SETS it with no new mechanism (and Chunk 2's
    push makes it durable like any nested param — see the capture->push
    round-trip). This is the swell case: track 4 -> 'Guitar-Dual Amped Heavy'
    -> nested 'Guitar' rack -> 'Guitar Dead Notes' MultiSampler.

    The 'Voices is a non-parameter LOM property' branch is decided by a LIVE
    probe (get_parameters on the real pack sampler) — tracked as an
    operator-verification step + a conditional follow-up, NOT built speculatively
    here (it would be a durability-incomplete half-feature against an unverified
    requirement)."""
    voices = FakeParam("Voices", 1.0, min=1.0, max=32.0)
    sampler = FakeDevice(
        "Guitar Dead Notes", class_name="MultiSampler", parameters=[voices],
    )
    rack = _FakeRackDevice(
        "Guitar", chains=[_FakeChain("Guitar", devices=[sampler])],
    )
    ctx = FakeCtx(FakeSong(tracks=[FakeTrack("Gtr", devices=[rack])]))
    path = [{"chain_index": 1, "device_position": 1}]
    read = dispatch(
        Request(
            tool="ableton_device", action="get_parameters",
            params={
                "node": {"parent": {"kind": "track", "index": 1}, "device_index": 1, "path": path},
                "detail": "full",
            },
        ),
        context=ctx,
    )
    assert read.ok is True, read.error
    assert "Voices" in [p["name"] for p in read.result["parameters"]]
    wrote = dispatch(
        Request(
            tool="ableton_device", action="set_parameter",
            params={
                "node": {"parent": {"kind": "track", "index": 1}, "device_index": 1, "path": path},
                "parameter_name": "Voices", "value": "8",
            },
        ),
        context=ctx,
    )
    assert wrote.ok is True, wrote.error
    assert voices.value == 8.0


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


# ---------------------------------------------------------------------------
# Master-strip device chains (Chunk 2)
# ---------------------------------------------------------------------------


def _ctx_with_master_device() -> FakeCtx:
    """Song with one device on the master strip (a master limiter shape)."""
    limiter = FakeDevice(
        name="Limiter", class_name="Limiter",
        parameters=[FakeParam("Ceiling", -0.3, min=-12.0, max=0.0)],
    )
    return FakeCtx(
        FakeSong(
            tracks=[FakeTrack("Drums")],
            returns=[FakeReturn("A-Rev")],
            master=FakeTrack("Master", devices=[limiter]),
        )
    )


def test_list_on_master(loaded_actions):
    ctx = _ctx_with_master_device()
    resp = dispatch(
        Request(
            tool="ableton_device", action="list",
            params={"master": True},
        ),
        context=ctx,
    )
    assert resp.ok is True, resp.error
    assert resp.result["parent_kind"] == "master"
    # Master is a singleton — response carries `master: True`, no index field.
    assert resp.result["master"] is True
    assert "track_index" not in resp.result
    assert "return_index" not in resp.result
    assert [d["name"] for d in resp.result["devices"]] == ["Limiter"]


def test_list_rejects_master_with_track_index(loaded_actions):
    resp = dispatch(
        Request(
            tool="ableton_device", action="list",
            params={"master": True, "track_index": 1},
        ),
        context=_ctx_with_master_device(),
    )
    assert resp.ok is False
    assert "not more than one" in (resp.error or "")


def test_list_rejects_master_with_return_index(loaded_actions):
    resp = dispatch(
        Request(
            tool="ableton_device", action="list",
            params={"master": True, "return_index": 1},
        ),
        context=_ctx_with_master_device(),
    )
    assert resp.ok is False
    assert "not more than one" in (resp.error or "")


def test_master_false_is_not_addressing(loaded_actions):
    """`master: false` must not count as an addressing — the schema still
    requires exactly one of {track_index, return_index, master=true}."""
    resp = dispatch(
        Request(
            tool="ableton_device", action="list",
            params={"master": False},
        ),
        context=_ctx_with_master_device(),
    )
    assert resp.ok is False
    assert ("track_index" in (resp.error or "")
            or "exactly one" in (resp.error or ""))


def test_info_on_master(loaded_actions):
    ctx = _ctx_with_master_device()
    resp = dispatch(
        Request(
            tool="ableton_device", action="info",
            params={"master": True, "device_index": 1},
        ),
        context=ctx,
    )
    assert resp.ok is True, resp.error
    assert resp.result["parent_kind"] == "master"
    assert resp.result["master"] is True
    assert resp.result["parameter_count"] == 1


def test_get_parameters_on_master(loaded_actions):
    ctx = _ctx_with_master_device()
    resp = dispatch(
        Request(
            tool="ableton_device", action="get_parameters",
            params={"node": {"parent": {"kind": "master"}, "device_index": 1}, "detail": "summary"},
        ),
        context=ctx,
    )
    assert resp.ok is True, resp.error
    names = [p["name"] for p in resp.result["parameters"]]
    assert "Ceiling" in names


def test_set_parameter_on_master(loaded_actions):
    ctx = _ctx_with_master_device()
    resp = dispatch(
        Request(
            tool="ableton_device", action="set_parameter",
            params={
                "node": {"parent": {"kind": "master"}, "device_index": 1},
                "parameter_name": "Ceiling", "value": "-1.0",
                "value_type": "continuous",
            },
        ),
        context=ctx,
    )
    assert resp.ok is True, resp.error
    assert resp.result["parent_kind"] == "master"
    assert ctx.song.master_track.devices[0].parameters[0].value == -1.0


def test_load_on_master_appends_to_master_chain(loaded_actions):
    """DEV-6M2K: `load` onto the master goes through the same select-then-load
    path as any track. Live 12.4.2 lets `selected_track = master_track` stick,
    so `browser.load_item` lands the device on the master chain. The response
    is master-addressed (`parent_kind='master'`, `master: True`, no index)."""
    ctx = _ctx_with_master_device()  # master already holds a "Limiter"
    item = FakeBrowserItem(
        name="EQ Eight", uri="query:Audio Effects#EQ Eight", is_loadable=True,
    )
    ctx.application.browser.audio_effects.children.append(item)

    resp = dispatch(
        Request(
            tool="ableton_device", action="load",
            params={"node": {"parent": {"kind": "master"}, "terminal": "master"}, "kind": "EQ Eight"},
        ),
        context=ctx,
    )
    assert resp.ok is True, resp.error
    assert resp.result["parent_kind"] == "master"
    assert resp.result["master"] is True
    assert "track_index" not in resp.result
    assert "return_index" not in resp.result
    assert resp.result["name"] == "EQ Eight"
    # The load landed on the MASTER chain (appended after the pre-existing
    # Limiter), not mis-targeted onto a regular track.
    assert ctx.application.browser.load_calls == [item]
    master_devices = [d.name for d in ctx.song.master_track.devices]
    assert master_devices == ["Limiter", "EQ Eight"]
    assert resp.result["device_index"] == 2
    # No regular track was touched.
    assert all(t.devices == [] for t in ctx.song.tracks)


# ---------------------------------------------------------------------------
# MST-LEAK: a browser load must change exactly ONE chain
# ---------------------------------------------------------------------------
#
# Field report, Ableton Live 12.4 Suite, 2026-08-07. Live's view was on
# `Detail/Clip` with track 3 selected. Two `ableton_device(action='load')` calls
# addressed the MASTER (`Shifter`, then `Limiter`). The master chain came out
# right — `[1:Shifter, 2:Limiter]` — and both calls returned `ok` with
# `parent_kind: "master"`. But track 3 ALSO grew both devices, at positions 6
# and 7, which nobody had asked for. No other track was affected.
#
# `browser.load_item` takes no destination argument: Live aims it from VIEW
# state, and that state has two halves — the Session selection and the Detail
# pane's device-chain binding. The loader moved only the first. Selecting the
# master moves the Session selection off the track list entirely (the master is
# the one destination that is not a member of `song.tracks`), so the Detail pane
# stayed bound to track 3 and the load materialized in both chains. The old
# post-condition re-read only `parent.devices`, so "the chain I aimed at grew"
# was reported as success while a stray sat on the composer's track.
#
# `_LeakyBrowser` models exactly that mechanism; `_AlwaysLeakyBrowser` models a
# Live where retargeting the Detail pane is NOT enough, so the census backstop
# is exercised on its own.


class _LeakyBrowser(FakeBrowser):
    """Live 12.4's two-halves load aiming (MST-LEAK).

    The load lands on ``song.view.selected_track`` (as always) AND on whatever
    chain the Detail pane is bound to, when the two disagree. The Detail pane
    re-binds to the current selection only while it is actually SHOWING the
    device chain — which is the behaviour the loader has to establish before
    calling ``load_item``.
    """

    def __init__(self, song, view, *, detail_bound_track):
        super().__init__(song, view)
        self.detail_bound_track = detail_bound_track

    def load_item(self, item: FakeBrowserItem) -> None:
        if self._view.detail_view == "Detail/DeviceChain":
            self.detail_bound_track = self._song.view.selected_track
        selected = self._song.view.selected_track
        super().load_item(item)
        bound = self.detail_bound_track
        if bound is not None and bound is not selected:
            bound.devices.append(
                FakeDevice(name=item.name, class_name=item.name)
            )


class _AlwaysLeakyBrowser(FakeBrowser):
    """A load that ALWAYS also appends to ``leak_into``, whatever the view says.

    Stands in for a Live/plugin combination where retargeting the Detail pane
    doesn't prevent the second insertion. Keeps the census backstop honest
    independently of the prevention step.
    """

    def __init__(self, song, view, *, leak_into, leak_class=None):
        super().__init__(song, view)
        self.leak_into = leak_into
        self.leak_class = leak_class

    def load_item(self, item: FakeBrowserItem) -> None:
        super().load_item(item)
        name = self.leak_class or item.name
        self.leak_into.devices.append(FakeDevice(name=name, class_name=name))


def _ctx_focused_on_track_three(browser_factory) -> FakeCtx:
    """The field-report session: three tracks, track 3 authored + focused, the
    Detail pane on Clip, an empty master. ``browser_factory(song, view, track3)``
    builds the browser under test."""
    track3 = FakeTrack("Gtr", devices=[
        FakeDevice(name=n, class_name=n)
        for n in ("StringStudio", "Overdrive", "Amp", "Cabinet", "Saturator")
    ])
    song = FakeSong(
        tracks=[FakeTrack("Drums"), FakeTrack("Bass"), track3],
        returns=[FakeReturn("A-Rev")],
        master=FakeTrack("Master"),
    )
    ctx = FakeCtx(song)
    ctx.application.view.detail_view = "Detail/Clip"
    song.view.selected_track = track3
    ctx.application.browser = browser_factory(
        song, ctx.application.view, track3,
    )
    return ctx


def test_load_on_master_does_not_leak_into_the_focused_track(loaded_actions):
    """MST-LEAK, prevention half: retarget BOTH halves of Live's load-aiming
    state before ``load_item``, so the device is never created on the
    previously focused track in the first place.

    Without the Detail-pane retarget the leaky browser appends the device to
    track 3 as well — the reported field bug."""
    ctx = _ctx_focused_on_track_three(
        lambda song, view, t3: _LeakyBrowser(song, view, detail_bound_track=t3)
    )
    item = FakeBrowserItem(
        name="Shifter", uri="query:Audio Effects#Shifter", is_loadable=True,
    )
    ctx.application.browser.audio_effects.children.append(item)

    resp = dispatch(
        Request(
            tool="ableton_device", action="load",
            params={
                "node": {"parent": {"kind": "master"}, "terminal": "master"},
                "kind": "Shifter",
            },
        ),
        context=ctx,
    )
    assert resp.ok is True, resp.error
    assert resp.result["parent_kind"] == "master"
    assert resp.result["device_index"] == 1
    assert [d.name for d in ctx.song.master_track.devices] == ["Shifter"]
    # The composer's track is byte-for-byte what it was.
    assert [d.name for d in ctx.song.tracks[2].devices] == [
        "StringStudio", "Overdrive", "Amp", "Cabinet", "Saturator",
    ]
    # Prevented, not repaired — nothing had to be cleaned up.
    assert "collateral_removed" not in resp.result
    # The loader pointed the Detail pane at the destination's device chain.
    assert "Detail/DeviceChain" in ctx.application.view.show_view_calls


def test_load_restores_the_callers_selection_and_detail_pane(loaded_actions):
    """A load is a chain mutation, not a navigation command: the composer's
    selected track and Detail pane come back exactly as they were.

    Without the restore the loader leaves the master selected and the Detail
    pane on the device chain — the user's screen silently rearranged, and the
    next load inherits a target they never chose."""
    ctx = _ctx_focused_on_track_three(
        lambda song, view, t3: _LeakyBrowser(song, view, detail_bound_track=t3)
    )
    track3 = ctx.song.tracks[2]
    item = FakeBrowserItem(name="Limiter", uri="query:Limiter", is_loadable=True)
    ctx.application.browser.audio_effects.children.append(item)

    resp = dispatch(
        Request(
            tool="ableton_device", action="load",
            params={
                "node": {"parent": {"kind": "master"}, "terminal": "master"},
                "kind": "Limiter",
            },
        ),
        context=ctx,
    )
    assert resp.ok is True, resp.error
    assert ctx.song.view.selected_track is track3
    assert ctx.application.view.detail_view == "Detail/Clip"
    assert ctx.application.view.detail_open is True


def test_load_leaves_a_collapsed_detail_pane_collapsed(loaded_actions):
    """Retargeting the Detail pane RE-OPENS it. A composer who had it collapsed
    gets it back collapsed — the load must not rearrange their screen at all."""
    ctx = _ctx_focused_on_track_three(
        lambda song, view, t3: _LeakyBrowser(song, view, detail_bound_track=t3)
    )
    ctx.application.view.detail_open = False
    item = FakeBrowserItem(name="Shifter", uri="query:Shifter", is_loadable=True)
    ctx.application.browser.audio_effects.children.append(item)

    resp = dispatch(
        Request(
            tool="ableton_device", action="load",
            params={
                "node": {"parent": {"kind": "master"}, "terminal": "master"},
                "kind": "Shifter",
            },
        ),
        context=ctx,
    )
    assert resp.ok is True, resp.error
    assert [d.name for d in ctx.song.master_track.devices] == ["Shifter"]
    assert ctx.application.view.detail_open is False


def test_load_removes_and_reports_a_collateral_device(loaded_actions):
    """MST-LEAK, detection half: the destination chain growing is NOT proof the
    load behaved. A device that appears in a chain nobody addressed is removed
    and named on the response — never reported as a clean ``ok``.

    Without the full-session census the old post-condition (re-read
    ``parent.devices``, see it grew) returns ``ok`` and the stray survives into
    the next ``/song-snapshot``."""
    ctx = _ctx_focused_on_track_three(
        lambda song, view, t3: _AlwaysLeakyBrowser(song, view, leak_into=t3)
    )
    item = FakeBrowserItem(name="Shifter", uri="query:Shifter", is_loadable=True)
    ctx.application.browser.audio_effects.children.append(item)

    resp = dispatch(
        Request(
            tool="ableton_device", action="load",
            params={
                "node": {"parent": {"kind": "master"}, "terminal": "master"},
                "kind": "Shifter",
            },
        ),
        context=ctx,
    )
    assert resp.ok is True, resp.error
    assert [d.name for d in ctx.song.master_track.devices] == ["Shifter"]
    # The stray was undone.
    assert [d.name for d in ctx.song.tracks[2].devices] == [
        "StringStudio", "Overdrive", "Amp", "Cabinet", "Saturator",
    ]
    assert resp.result["collateral_removed"] == [{
        "parent_kind": "track",
        "index": 3,
        "device_index": 6,
        "class_name": "Shifter",
    }]
    assert "track 3" in resp.result["warning"]


def test_load_raises_when_a_collateral_change_cannot_be_undone(loaded_actions):
    """A chain we did not address changed in a way this load cannot be blamed
    for — so we must not touch it, and we must not claim success. Removing a
    device we can't prove we created would be a worse bug than the leak."""
    ctx = _ctx_focused_on_track_three(
        lambda song, view, t3: _AlwaysLeakyBrowser(
            song, view, leak_into=t3, leak_class="Utility",
        )
    )
    item = FakeBrowserItem(name="Shifter", uri="query:Shifter", is_loadable=True)
    ctx.application.browser.audio_effects.children.append(item)

    resp = dispatch(
        Request(
            tool="ableton_device", action="load",
            params={
                "node": {"parent": {"kind": "master"}, "terminal": "master"},
                "kind": "Shifter",
            },
        ),
        context=ctx,
    )
    assert resp.ok is False
    assert "not aimed at" in resp.error
    assert "track 3" in resp.error
    # Left in place — an unattributable device is the operator's call.
    assert [d.name for d in ctx.song.tracks[2].devices][-1] == "Utility"


def test_load_on_return_does_not_leak_into_the_focused_track(loaded_actions):
    """The same aiming defect is latent on RETURN loads — a return is also not a
    member of ``song.tracks``, so selecting one moves the Session selection off
    the focused track exactly like the master does. The fix is destination-kind
    agnostic, so this passes for the same reason the master case does."""
    ctx = _ctx_focused_on_track_three(
        lambda song, view, t3: _LeakyBrowser(song, view, detail_bound_track=t3)
    )
    item = FakeBrowserItem(name="Reverb", uri="query:Reverb", is_loadable=True)
    ctx.application.browser.audio_effects.children.append(item)

    resp = dispatch(
        Request(
            tool="ableton_device", action="load",
            params={
                "node": {"parent": {"kind": "return", "index": 1},
                         "terminal": "return"},
                "kind": "Reverb",
            },
        ),
        context=ctx,
    )
    assert resp.ok is True, resp.error
    assert [d.name for d in ctx.song.return_tracks[0].devices] == ["Reverb"]
    assert [d.name for d in ctx.song.tracks[2].devices] == [
        "StringStudio", "Overdrive", "Amp", "Cabinet", "Saturator",
    ]
    assert "collateral_removed" not in resp.result


# `plan_push_devices` master-strip walk lives in tests/unit/sync/test_push_devices.py
# next to the other planner-shape tests.
