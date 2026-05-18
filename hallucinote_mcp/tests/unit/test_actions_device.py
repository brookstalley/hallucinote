"""ableton_device schema + handler behavior."""
from __future__ import annotations

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
        self._loaded: list[tuple[str, str | None]] = []
        self._deleted: list[int] = []
        self._moved: list[tuple[FakeDevice, int]] = []

    def load_device(self, *args, **kwargs):
        """Modern-ish API: accept kind + preset_uri kwargs."""
        kind = kwargs.get("kind", args[0] if args else None)
        preset = kwargs.get("preset_uri")
        new_dev = FakeDevice(name=kind or "Loaded", class_name=kind or "Loaded")
        self.devices.append(new_dev)
        self._loaded.append((kind or "", preset))

    def delete_device(self, index_0based: int) -> None:
        self._deleted.append(index_0based)
        del self.devices[index_0based]

    def move_device(self, device: FakeDevice, new_index_0based: int) -> None:
        self._moved.append((device, new_index_0based))
        self.devices.remove(device)
        self.devices.insert(new_index_0based, device)


class FakeReturn(FakeTrack):
    pass


class FakeSong:
    def __init__(
        self,
        tracks: list[FakeTrack] | None = None,
        returns: list[FakeReturn] | None = None,
    ):
        self.tracks = tracks or [FakeTrack("T1"), FakeTrack("T2")]
        self.return_tracks = returns or [FakeReturn("A-Rev")]


class FakeCtx:
    def __init__(self, song: FakeSong | None = None):
        self._song = song or FakeSong()
        self.run_on_main_calls = 0

    @property
    def song(self) -> FakeSong:
        return self._song

    def run_on_main(self, fn):
        self.run_on_main_calls += 1
        return fn()



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


def test_load_at_position_moves_device(loaded_actions):
    track = FakeTrack("T1", devices=[
        FakeDevice("A"), FakeDevice("B"), FakeDevice("C"),
    ])
    ctx = FakeCtx(FakeSong(tracks=[track]))
    resp = dispatch(
        Request(
            tool="ableton_device", action="load",
            params={"track_index": 1, "kind": "EQ8", "position": 2},
        ),
        context=ctx,
    )
    assert resp.ok is True
    assert resp.result["device_index"] == 2
    # New device sits at slot 2 (between A and B)
    assert [d.name for d in track.devices] == ["A", "EQ8", "B", "C"]


def test_load_on_return(loaded_actions):
    ctx = FakeCtx(FakeSong(
        tracks=[FakeTrack("T1")],
        returns=[FakeReturn("Rev")],
    ))
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
