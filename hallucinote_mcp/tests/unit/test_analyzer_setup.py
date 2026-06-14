"""Tests for hallucinote_mcp.analyzer.setup — silent analyzer sweep."""
from __future__ import annotations

import threading
from typing import Any

import pytest

from hallucinote_mcp.analyzer import setup as analyzer_setup
from hallucinote_mcp.analyzer.setup import (
    ANALYZER_DEVICE_NAME,
    _reposition_action,
    _strip_action,
    ensure_analyzers_loaded,
    strip_analyzers,
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
        _FakeParam("Port", 11020.0, min=11000.0, max=11400.0),
        _FakeParam("EmitPort", 11221.0, min=11000.0, max=11400.0),
        _FakeParam("Emit", 1.0),
    ]


class _FakeDevice:
    """A Live device.

    Mirrors Live's actual attribute shape:
      - ``class_display_name`` is the device CLASS as Live exposes it.
        For M4L audio-effect devices this is ALWAYS ``"Max Audio Effect"``
        (every .amxd of type audioeffect shares this class). For built-in
        Live devices it's the device's display name (``"Compressor"``,
        ``"Reverb"``, etc.).
      - ``name`` is the user-visible label. For freshly-loaded M4L
        devices Live initializes ``name`` to the .amxd filename without
        extension (e.g. ``"HallucinoteAnalyzer"``), though the user can
        rename it in the session.

    Earlier versions of this fake set ``class_display_name`` to the
    .amxd filename, which never happens in real Live — caused
    `_find_analyzer_index` (which compared on class_display_name) to
    return True in tests but always False against real M4L devices.
    """

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
        # Auto-detect: an M4L audio-effect device loaded by the analyzer
        # setup will have class_display_name="Max Audio Effect" and name
        # defaulting to "HallucinoteAnalyzer". Tests that construct a
        # _FakeDevice for the analyzer chain MUST set name accordingly
        # — defaulting name to class_display_name (the prior behavior)
        # would produce a device that looks like a non-M4L "Max Audio
        # Effect" device with no specific .amxd identity.
        self.name = name or class_display_name
        if parameters is None and self.name == "HallucinoteAnalyzer":
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

    def delete_device(self, index0: int) -> None:
        """Live's 0-based ``Track.delete_device``. ``delete_handler`` reaches
        for it by name; the analyzer reposition path (SNP-8R4K) deletes the
        mid-chain analyzer here before re-adding it last."""
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
    """Tracks each load_item call and appends a fresh device to whatever
    track is selected. The selected track is the parent surface
    that ``load_handler`` is targeting (which calls
    ``song.view.selected_track = parent`` before ``browser.load_item``).

    Mirrors the real install layout: the analyzer .amxd lives at
    ``user_library/Presets/Audio Effects/Max Audio Effect/HallucinoteAnalyzer``
    (where the install skill writes it). ``ensure_analyzers_loaded``
    locates it via ``preset_query`` with that exact path_prefix — a
    ``kind=`` lookup would miss it because the built-in
    ``_BROWSER_LOAD_ROOTS`` (instruments / audio_effects / midi_effects /
    drums) doesn't include ``user_library``.
    """

    def __init__(self, song: "_FakeSong", *, item_name: str = ANALYZER_DEVICE_NAME):
        self._song = song
        # Build the user_library subtree that mirrors the install layout.
        self.user_library = _FakeBrowserRoot("User Library")
        presets = _FakeBrowserRoot("Presets")
        audio_effects_folder = _FakeBrowserRoot("Audio Effects")
        max_audio_effect = _FakeBrowserRoot("Max Audio Effect")
        self._item = _FakeBrowserItem(item_name)
        max_audio_effect.children.append(self._item)
        audio_effects_folder.children.append(max_audio_effect)
        presets.children.append(audio_effects_folder)
        self.user_library.children.append(presets)
        # Other roots are present but empty — the load_handler walks
        # them for kind / preset_uri lookups, but the analyzer
        # specifically lives under user_library.
        self.audio_effects = _FakeBrowserRoot("Audio Effects")
        self.instruments = _FakeBrowserRoot("Instruments")
        self.midi_effects = _FakeBrowserRoot("MIDI Effects")
        self.drums = _FakeBrowserRoot("Drums")
        self.plugins = _FakeBrowserRoot("Plug-Ins")
        self.samples = _FakeBrowserRoot("Samples")
        self.packs = _FakeBrowserRoot("Packs")
        self.load_calls: list[_FakeBrowserItem] = []

    def load_item(self, item: _FakeBrowserItem) -> None:
        self.load_calls.append(item)
        target = self._song.view.selected_track
        # Mirror Live's actual attribute shape: a freshly-loaded M4L
        # audio effect has class_display_name="Max Audio Effect" (the
        # device class) and name=<.amxd filename>. The browser item's
        # name in this fake is the .amxd filename.
        new_dev = _FakeDevice(
            class_display_name="Max Audio Effect",
            name=item.name,
        )
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
        # Counts each run_on_main bout. Tests assert that each Live touch
        # gets its own bout — the deadlock fix's load-bearing invariant.
        self.run_on_main_calls = 0

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
        self.run_on_main_calls += 1
        return fn()


def _master_with_analyzer(name: str = "Master") -> _FakeTrack:
    """A master that already carries the analyzer. The sweep DETECTS it and
    configures its ports without re-loading (idempotency). DEV-6M2K: the sweep
    can also auto-load the master analyzer when absent (see
    ``test_sweep_auto_loads_master_analyzer_when_absent``); pre-placing it here
    exercises the detect-and-configure branch specifically."""
    return _FakeTrack(name, devices=[
        _FakeDevice(class_display_name="Max Audio Effect", name=ANALYZER_DEVICE_NAME),
    ])


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


def test_sweep_configures_preplaced_master_analyzer():
    """A song whose master already carries the analyzer: the sweep DETECTS and
    configures it — never loaded/duplicated (idempotency holds whether or not
    the master can auto-load)."""
    ctx = _FakeCtx(_FakeSong(master=_master_with_analyzer()))
    layout = ensure_analyzers_loaded(ctx)
    assert len(layout.instances) == 1
    inst = layout.instances[0]
    assert inst.surface_kind == "master"
    assert inst.track_id == "master"
    assert inst.was_loaded is False  # detected, not loaded
    assert inst.device_index == 1
    # Detected, not duplicated.
    assert len(ctx.song.master_track.devices) == 1


def test_sweep_auto_loads_master_analyzer_when_absent():
    """DEV-6M2K: a bare master (no pre-placed analyzer) is AUTO-LOADED like any
    track/return — no loud "add it by hand" failure. The earlier DEV-2M9K
    fail-loud rested on the refuted premise that Live can't load onto the
    master; live-proven on Live 12.4.2 that it can."""
    ctx = _FakeCtx(_FakeSong(tracks=[_FakeTrack("Drums")]))  # default empty master
    layout = ensure_analyzers_loaded(ctx)
    by_surface = layout.by_surface()
    master_inst = by_surface[("master", 0)]
    assert master_inst.was_loaded is True  # auto-loaded, not hand-placed
    assert master_inst.osc_port == 11220  # the master's deterministic port
    # The analyzer landed on the master chain.
    master_analyzers = [
        d for d in ctx.song.master_track.devices
        if d.name == ANALYZER_DEVICE_NAME
    ]
    assert len(master_analyzers) == 1


# --- idempotency: the most load-bearing property ---------------------


def test_sweep_is_idempotent_no_duplicates():
    """Two consecutive sweeps must produce identical layouts and not
    add a second analyzer to any surface."""
    ctx = _FakeCtx(_FakeSong(
        tracks=[_FakeTrack("Drums"), _FakeTrack("Bass")],
        returns=[_FakeTrack("A-Reverb")],
        master=_master_with_analyzer(),
    ))

    first = ensure_analyzers_loaded(ctx)
    assert first.loaded_count == 3  # 2 tracks + 1 return (master is pre-placed)
    assert first.existing_count == 1  # master pre-placed → detected, not loaded

    # All four surfaces should now have exactly one analyzer each.
    chain_counts_after_first = [
        len([d for d in t.devices if d.name == ANALYZER_DEVICE_NAME])
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
        len([d for d in t.devices if d.name == ANALYZER_DEVICE_NAME])
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
    # Mirror real Live: M4L analyzer has class_display_name="Max Audio Effect",
    # name=<.amxd filename>. EQ Eight has class_display_name="EQ Eight",
    # name="EQ Eight" (Live's built-in devices have name==class_display_name).
    existing = _FakeDevice(class_display_name="Max Audio Effect", name=ANALYZER_DEVICE_NAME)
    eq = _FakeDevice(class_display_name="EQ Eight")
    ctx = _FakeCtx(_FakeSong(
        tracks=[_FakeTrack("Drums", devices=[eq, existing])],
        master=_master_with_analyzer(),
    ))

    layout = ensure_analyzers_loaded(ctx)
    by_surface = layout.by_surface()
    track_inst = by_surface[("track", 1)]
    assert track_inst.was_loaded is False
    # Found at position 2 (1-based), not 1 — order in the chain matters.
    assert track_inst.device_index == 2
    # Master pre-placed here — the analyzer is detected, not re-loaded.
    master_inst = by_surface[("master", 0)]
    assert master_inst.was_loaded is False
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
        master=_master_with_analyzer(),
    ))
    layout = ensure_analyzers_loaded(ctx)
    by_tid = layout.by_track_id()
    # Tracks: 11020, 11021, 11022 (stride 1, base 11020 clears AbletonOSC).
    assert by_tid["track:1"].osc_port == 11020
    assert by_tid["track:2"].osc_port == 11021
    assert by_tid["track:3"].osc_port == 11022
    # Returns: 11120, 11121.
    assert by_tid["return:1"].osc_port == 11120
    assert by_tid["return:2"].osc_port == 11121
    # Master: 11220.
    assert by_tid["master"].osc_port == 11220
    # All share the same emit port by default (11221 — past master).
    emit_ports = {inst.osc_emit_port for inst in layout.instances}
    assert emit_ports == {11221}


def test_sweep_writes_per_instance_port_via_live_param():
    """The deterministic per-instance port is only effective if it's
    written to the analyzer's `Port` Live parameter. Two analyzers
    listening on the same port would both receive every `/path` —
    which would cross-contaminate render targets."""
    ctx = _FakeCtx(_FakeSong(
        tracks=[_FakeTrack("T1"), _FakeTrack("T2")],
        master=_master_with_analyzer(),
    ))
    ensure_analyzers_loaded(ctx)

    def _param_value(track, pname):
        analyzer = next(
            d for d in track.devices
            if d.name == ANALYZER_DEVICE_NAME
        )
        return next(p for p in analyzer.parameters if p.name == pname).value

    # Track 1 → 11020, Track 2 → 11021 (stride 1; base 11020 clears AbletonOSC).
    assert _param_value(ctx.song.tracks[0], "Port") == 11020.0
    assert _param_value(ctx.song.tracks[1], "Port") == 11021.0
    # Both share the default emit port.
    assert _param_value(ctx.song.tracks[0], "EmitPort") == 11221.0
    assert _param_value(ctx.song.tracks[1], "EmitPort") == 11221.0
    # Master at 11220.
    assert _param_value(ctx.song.master_track, "Port") == 11220.0


def test_sweep_custom_emit_port_propagates():
    ctx = _FakeCtx(_FakeSong(
        tracks=[_FakeTrack("T1")], master=_master_with_analyzer(),
    ))
    # Stay within the patch's documented Port range (11000-11400 — see
    # HallucinoteAnalyzer.amxd.spec.md). The active band is 11020-11221.
    layout = ensure_analyzers_loaded(ctx, emit_port=11250)
    for inst in layout.instances:
        assert inst.osc_emit_port == 11250


# --- surface filtering ------------------------------------------------


def test_sweep_skips_group_tracks():
    """Group tracks (is_foldable=True) are routing aggregations of their
    members. Skipping them avoids double-counting audio at render time."""
    group = _FakeTrack("Drums Group", is_foldable=True)
    leaf = _FakeTrack("Kick")
    ctx = _FakeCtx(_FakeSong(tracks=[group, leaf], master=_master_with_analyzer()))
    layout = ensure_analyzers_loaded(ctx)
    surfaces = {(i.surface_kind, i.surface_index) for i in layout.instances}
    # Track index 2 (the leaf) is captured; track index 1 (the group) is not.
    assert ("track", 2) in surfaces
    assert ("track", 1) not in surfaces


def test_sweep_skips_tracks_with_no_audio_output():
    ctx = _FakeCtx(_FakeSong(
        tracks=[
            _FakeTrack("Mute Stub", has_audio_output=False),
            _FakeTrack("Audio Track"),
        ],
        master=_master_with_analyzer(),
    ))
    layout = ensure_analyzers_loaded(ctx)
    surfaces = {(i.surface_kind, i.surface_index) for i in layout.instances}
    assert ("track", 2) in surfaces
    assert ("track", 1) not in surfaces


# --- layout helpers ---------------------------------------------------


def test_layout_helpers_round_trip_instances():
    ctx = _FakeCtx(_FakeSong(
        tracks=[_FakeTrack("T")],
        returns=[_FakeTrack("R")],
        master=_master_with_analyzer(),
    ))
    layout = ensure_analyzers_loaded(ctx)
    by_tid = layout.by_track_id()
    by_surface = layout.by_surface()
    assert by_tid["track:1"] is by_surface[("track", 1)]
    assert by_tid["return:1"] is by_surface[("return", 1)]
    assert by_tid["master"] is by_surface[("master", 0)]
    assert layout.loaded_count + layout.existing_count == len(layout.instances)


# --- worker-thread marshaling discipline -----------------------------
#
# Regression guard for the 2026-05-27 deadlock: ``ensure_analyzers_loaded``
# is invoked from a runs_on_worker action, so each Live touch must
# marshal through ``context.run_on_main`` individually. Calling the
# device handlers synchronously from the worker thread (the pre-fix
# shape) packed N surfaces × 3 ops into one Remote-Script request-
# thread call → Live's main thread deadlocked on the M4L runtime. The
# fix is structural: every load + every set_parameter is its own
# main-thread bout. This test asserts that structure so regression
# can't reintroduce the worker-side bundling.


def test_sweep_marshals_each_live_touch_through_run_on_main():
    """A loaded surface = 1 detect + 1 load + 2 set_param = 4 bouts; a
    pre-placed (detected) surface = 1 detect + 2 set_param = 3 bouts. Here the
    master is pre-placed (3 bouts). Plus one initial run_on_main for the
    surface-list snapshot. With 2 tracks + 1 return loaded fresh + a pre-placed
    master:
        1 (plan) + 3 loaded * 4 + 1 master * 3 = 16 run_on_main bouts.

    The exact count matters less than the discipline: more than one bout
    per Live touch means the worker thread is yielding control between
    touches, which is what frees Live's main thread to pump the
    notification cascade from the previous touch.
    """
    ctx = _FakeCtx(_FakeSong(
        tracks=[_FakeTrack("Drums"), _FakeTrack("Bass")],
        returns=[_FakeTrack("A-Reverb")],
        master=_master_with_analyzer(),
    ))
    ensure_analyzers_loaded(ctx)
    # 3 loaded surfaces * (detect + load + 2 set_param) + detect-only master
    # (detect + 2 set_param) + 1 surface-list snapshot. The lower bound guards
    # against re-introducing the worker-side bundling — if the regression
    # collapses everything into one run_on_main, the count drops to 1.
    assert ctx.run_on_main_calls >= 3 * 4 + 3 + 1


def test_sweep_when_analyzer_already_present_still_bounces_per_touch():
    """Existing-analyzer path still uses run_on_main for: surface plan +
    per-surface detect + 2 set_param writes. Even with nothing to load,
    each Live access is its own bout."""
    existing = _FakeDevice(class_display_name="Max Audio Effect", name=ANALYZER_DEVICE_NAME)
    ctx = _FakeCtx(_FakeSong(
        tracks=[_FakeTrack("T1", devices=[existing])],
        master=_master_with_analyzer(),
    ))
    before = ctx.run_on_main_calls
    ensure_analyzers_loaded(ctx)
    # 1 plan + (1 detect + 2 set_param) per surface × 2 surfaces (T1 + master)
    # = 1 + 6 = 7. Both skip the load bout because both analyzers are already
    # present (T1's and the pre-placed master's).
    delta = ctx.run_on_main_calls - before
    assert delta >= 7


# --- SNP-8R4K Mechanism 2: terminal-tap reposition --------------------
#
# The analyzer must be the chain's strictly-LAST device at capture time so the
# per-stem WAV reflects the full authored chain. ``ensure_analyzers_loaded``
# now RE-ASSERTS that invariant on every surface at render start: no-op if the
# analyzer is already last, delete+re-add (the only way — Live has no reorder
# API) if a device landed past it, load if absent. The pure ``_reposition_action``
# helper encodes the decision; ``_ensure_on_surface`` carries it out and records
# ``terminal`` / ``was_repositioned`` on the instance for the render manifest.


# --- pure decision helper (Live-free) --------------------------------


def test_reposition_action_absent():
    """No analyzer in the chain → load (which appends, landing it last)."""
    assert _reposition_action(None, 0) == "absent"
    assert _reposition_action(None, 3) == "absent"


def test_reposition_action_already_last():
    """Analyzer present AND last → no-op (the common case; no M4L reload)."""
    assert _reposition_action(1, 1) == "already_last"
    assert _reposition_action(4, 4) == "already_last"


def test_reposition_action_reposition_when_interleaved():
    """Analyzer present but NOT last (a device landed past it) → reposition."""
    # analyzer at index 1 of 2 (an authored device sits after it).
    assert _reposition_action(1, 2) == "reposition"
    # analyzer at index 2 of 4 (interleaved among authored devices).
    assert _reposition_action(2, 4) == "reposition"


# --- _ensure_on_surface terminal-tap behavior (mocked Live) ----------


def test_sweep_repositions_analyzer_when_not_last():
    """A surface where a device landed AFTER the analyzer: the sweep deletes the
    mid-chain analyzer and re-adds it (appends → now last). Ends terminal,
    flagged was_repositioned. The interleaving device survives, now BEFORE the
    analyzer."""
    analyzer = _FakeDevice(class_display_name="Max Audio Effect", name=ANALYZER_DEVICE_NAME)
    # A Saturator loaded after a prior render → analyzer is no longer last.
    saturator = _FakeDevice(class_display_name="Saturator")
    track = _FakeTrack("Drums", devices=[analyzer, saturator])  # analyzer at idx 1 of 2
    ctx = _FakeCtx(_FakeSong(tracks=[track], master=_master_with_analyzer()))

    layout = ensure_analyzers_loaded(ctx)
    inst = layout.by_surface()[("track", 1)]

    # Exactly one analyzer survives (delete + re-add, no duplicate).
    analyzers = [d for d in track.devices if d.name == ANALYZER_DEVICE_NAME]
    assert len(analyzers) == 1
    # The analyzer is now the LAST device in the chain.
    assert track.devices[-1].name == ANALYZER_DEVICE_NAME
    # The interleaving Saturator survived, now before the analyzer.
    assert [d.name for d in track.devices] == ["Saturator", ANALYZER_DEVICE_NAME]
    # Observability: terminal + flagged as repositioned. was_loaded stays False —
    # the analyzer pre-existed in the song; it was MOVED, not newly added.
    assert inst.terminal is True
    assert inst.was_repositioned is True
    assert inst.was_loaded is False
    assert inst.device_index == 2  # 1-based, now last


def test_sweep_no_reposition_when_analyzer_already_last():
    """A surface where the analyzer is ALREADY last: the sweep must NOT delete +
    re-add (that pays the expensive M4L reload on an unchanged surface — R12).
    The chain is untouched and the same analyzer object stays in place."""
    eq = _FakeDevice(class_display_name="EQ Eight")
    analyzer = _FakeDevice(class_display_name="Max Audio Effect", name=ANALYZER_DEVICE_NAME)
    track = _FakeTrack("Drums", devices=[eq, analyzer])  # analyzer at idx 2 of 2 (last)
    ctx = _FakeCtx(_FakeSong(tracks=[track], master=_master_with_analyzer()))

    browser = ctx.application.browser
    loads_before = len(browser.load_calls)
    layout = ensure_analyzers_loaded(ctx)
    inst = layout.by_surface()[("track", 1)]

    # No load happened on this track surface (the already-last analyzer).
    # The only load_calls come from surfaces that needed one — this surface and
    # the pre-placed master are both already-last, so NO loads at all here.
    assert len(browser.load_calls) == loads_before
    # The very same analyzer object is still last — no delete + re-add churn.
    assert track.devices[-1] is analyzer
    assert [d.name for d in track.devices] == ["EQ Eight", ANALYZER_DEVICE_NAME]
    # Observability: terminal, not repositioned, not (re)loaded.
    assert inst.terminal is True
    assert inst.was_repositioned is False
    assert inst.was_loaded is False
    assert inst.device_index == 2


def test_sweep_loads_analyzer_when_absent_and_marks_terminal():
    """A surface with NO analyzer: the sweep loads one (appends → last). Ends
    terminal, flagged was_loaded, NOT was_repositioned."""
    eq = _FakeDevice(class_display_name="EQ Eight")
    track = _FakeTrack("Drums", devices=[eq])  # no analyzer
    ctx = _FakeCtx(_FakeSong(tracks=[track], master=_master_with_analyzer()))

    layout = ensure_analyzers_loaded(ctx)
    inst = layout.by_surface()[("track", 1)]

    # One analyzer loaded, landing last after the EQ.
    assert [d.name for d in track.devices] == ["EQ Eight", ANALYZER_DEVICE_NAME]
    assert inst.terminal is True
    assert inst.was_loaded is True
    assert inst.was_repositioned is False
    assert inst.device_index == 2


def test_sweep_reposition_deletes_via_delete_handler_then_reloads():
    """The reposition path must use delete_handler (delete_device) to remove the
    mid-chain analyzer, then the load path to re-add it. Asserts the delete
    actually fired by observing the chain shrink-then-grow back to a single
    analyzer at the end (Live has no reorder API → delete + re-add is the only
    'make last')."""
    analyzer = _FakeDevice(class_display_name="Max Audio Effect", name=ANALYZER_DEVICE_NAME)
    dev_after_1 = _FakeDevice(class_display_name="Reverb")
    dev_after_2 = _FakeDevice(class_display_name="Saturator")
    # analyzer at idx 1 of 3 — two authored devices landed after it.
    track = _FakeTrack("Drums", devices=[analyzer, dev_after_1, dev_after_2])
    ctx = _FakeCtx(_FakeSong(tracks=[track], master=_master_with_analyzer()))

    browser = ctx.application.browser
    loads_before = len(browser.load_calls)
    layout = ensure_analyzers_loaded(ctx)
    inst = layout.by_surface()[("track", 1)]

    # A re-load fired on this surface (delete + re-add).
    assert len(browser.load_calls) == loads_before + 1
    # Final chain: the two authored devices, then the single re-added analyzer.
    assert [d.name for d in track.devices] == ["Reverb", "Saturator", ANALYZER_DEVICE_NAME]
    assert inst.was_repositioned is True
    assert inst.terminal is True
    assert inst.device_index == 3


def test_sweep_idempotent_after_reposition():
    """Multi-hop: after one render repositions the analyzer to last, the NEXT
    render sees it already-last → no-op (no churn, no second reposition). Guards
    against a reposition that doesn't actually settle the invariant."""
    analyzer = _FakeDevice(class_display_name="Max Audio Effect", name=ANALYZER_DEVICE_NAME)
    saturator = _FakeDevice(class_display_name="Saturator")
    track = _FakeTrack("Drums", devices=[analyzer, saturator])
    ctx = _FakeCtx(_FakeSong(tracks=[track], master=_master_with_analyzer()))

    first = ensure_analyzers_loaded(ctx)
    assert first.by_surface()[("track", 1)].was_repositioned is True

    browser = ctx.application.browser
    loads_after_first = len(browser.load_calls)
    second = ensure_analyzers_loaded(ctx)
    inst = second.by_surface()[("track", 1)]
    # Second sweep: analyzer already last → no-op, no further load/reposition.
    assert inst.was_repositioned is False
    assert inst.terminal is True
    assert len(browser.load_calls) == loads_after_first
    # Still exactly one analyzer, still last.
    assert [d.name for d in track.devices] == ["Saturator", ANALYZER_DEVICE_NAME]


# --- strip sweep (bulk removal — the inverse of ensure_analyzers_loaded) ----
#
# ``strip_analyzers`` walks the SAME _plan_surfaces snapshot, finds the analyzer
# per surface via _find_analyzer_index, and deletes it via delete_handler. The
# pure ``_strip_action`` helper encodes the per-surface decision (delete vs
# already-clean), mirroring _reposition_action's pure style.


# --- pure decision helper (Live-free) --------------------------------


def test_strip_action_absent():
    """No analyzer in the chain → no-op (already clean; keeps re-runs idempotent)."""
    assert _strip_action(None) == "absent"


def test_strip_action_delete_when_present():
    """Analyzer present (at any 1-based index) → delete it."""
    assert _strip_action(1) == "delete"
    assert _strip_action(3) == "delete"


# --- strip_analyzers behavior (mocked Live) --------------------------


def test_strip_removes_analyzer_from_every_surface():
    """Bulk strip: a song with the analyzer on every surface ends with NONE.
    The result names each surface a deletion fired on, with the device_index
    the analyzer occupied; interleaving authored devices survive."""
    eq = _FakeDevice(class_display_name="EQ Eight")
    drums = _FakeTrack("Drums", devices=[
        eq,
        _FakeDevice(class_display_name="Max Audio Effect", name=ANALYZER_DEVICE_NAME),
    ])  # analyzer at idx 2 of 2
    bass = _FakeTrack("Bass", devices=[
        _FakeDevice(class_display_name="Max Audio Effect", name=ANALYZER_DEVICE_NAME),
    ])  # analyzer at idx 1 of 1
    reverb = _FakeTrack("A-Reverb", devices=[
        _FakeDevice(class_display_name="Max Audio Effect", name=ANALYZER_DEVICE_NAME),
    ])
    ctx = _FakeCtx(_FakeSong(
        tracks=[drums, bass], returns=[reverb], master=_master_with_analyzer(),
    ))

    result = strip_analyzers(ctx)

    # Every surface had its analyzer removed (2 tracks + 1 return + master = 4).
    assert result.stripped_count == 4
    # The authored EQ survives on Drums; no analyzer left anywhere.
    assert [d.name for d in drums.devices] == ["EQ Eight"]
    assert bass.devices == []
    assert reverb.devices == []
    assert [d.name for d in ctx.song.master_track.devices] == []
    # Result records the surface + the device_index the analyzer occupied.
    by_surface = {(s.surface_kind, s.surface_index): s for s in result.stripped}
    assert by_surface[("track", 1)].device_index == 2  # last on Drums
    assert by_surface[("track", 2)].device_index == 1
    assert by_surface[("return", 1)].device_index == 1
    assert by_surface[("master", 0)].device_index == 1
    assert by_surface[("track", 1)].surface_name == "Drums"


def test_strip_skips_surfaces_without_analyzer():
    """A surface with no analyzer is skipped (no delete fired) — only
    analyzer-bearing surfaces appear in the result."""
    plain = _FakeTrack("Drums", devices=[_FakeDevice(class_display_name="EQ Eight")])
    tapped = _FakeTrack("Bass", devices=[
        _FakeDevice(class_display_name="Max Audio Effect", name=ANALYZER_DEVICE_NAME),
    ])
    # Master with NO analyzer so its surface is also skipped.
    ctx = _FakeCtx(_FakeSong(
        tracks=[plain, tapped], master=_FakeTrack("Master"),
    ))

    result = strip_analyzers(ctx)

    # Only the Bass track had an analyzer.
    assert result.stripped_count == 1
    assert [(s.surface_kind, s.surface_index) for s in result.stripped] == [("track", 2)]
    # The plain track's EQ is untouched.
    assert [d.name for d in plain.devices] == ["EQ Eight"]
    assert tapped.devices == []


def test_strip_is_idempotent():
    """Multi-hop: after one strip clears every surface, the next strip sees no
    analyzers → no-op (stripped_count 0, no further deletes)."""
    ctx = _FakeCtx(_FakeSong(
        tracks=[_FakeTrack("Drums", devices=[
            _FakeDevice(class_display_name="Max Audio Effect", name=ANALYZER_DEVICE_NAME),
        ])],
        master=_master_with_analyzer(),
    ))

    first = strip_analyzers(ctx)
    assert first.stripped_count == 2  # Drums + master

    second = strip_analyzers(ctx)
    assert second.stripped_count == 0
    assert ctx.song.tracks[0].devices == []
    assert ctx.song.master_track.devices == []
