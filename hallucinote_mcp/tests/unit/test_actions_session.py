"""ableton_session schema + handler behavior — drives M-1's actions through
the dispatcher against a fake Live API.

The actions package's import side-effects mean every test here must use the
isolated_registry fixture, then re-run the registration. The fixture clears
the registry on entry and restores it on exit — the test body imports the
actions module (or calls the targeted registration) inside that isolation.
"""
from __future__ import annotations

from typing import Any

import pytest

from hallucinote_mcp import schema
from hallucinote_mcp.dispatcher import dispatch
from hallucinote_mcp.testing import isolated_actions
from hallucinote_mcp.wire import Request


# ---------- Fake Live API objects ----------


class FakeParam:
    def __init__(self, value: float = 0.0):
        self.value = value


class FakeMixerDevice:
    def __init__(self, volume: float = 0.85, panning: float = 0.0):
        self.volume = FakeParam(volume)
        self.panning = FakeParam(panning)


class FakeMasterTrack:
    def __init__(self):
        self.mixer_device = FakeMixerDevice()
        self.mute = False


class FakeApplicationView:
    def __init__(self, visible: str = "Session"):
        self.shown_views: list[str] = []
        self._visible = visible

    def show_view(self, name: str) -> None:
        self.shown_views.append(name)
        self._visible = name

    def is_view_visible(self, name: str) -> bool:
        return name == self._visible


class FakeApplication:
    def __init__(self):
        self.view = FakeApplicationView()


class FakeSong:
    """Quacks like ``Live.Song.Song`` for the session-action surface."""

    def __init__(self):
        self.tempo = 120.0
        self.signature_numerator = 4
        self.signature_denominator = 4
        self.is_playing = False
        self.current_song_time = 0.0
        self.loop = False
        self.loop_start = 0.0
        self.loop_length = 4.0
        self.master_track = FakeMasterTrack()
        self.tracks: list[Any] = [object(), object(), object()]
        self.return_tracks: list[Any] = [object()]
        self.scenes: list[Any] = [object(), object()]
        self.view = None  # info_handler tolerates absent view

        self._application = FakeApplication()

        self.play_called = 0
        self.stop_called = 0

    def get_application(self):
        return self._application

    def start_playing(self):
        self.play_called += 1
        self.is_playing = True

    def stop_playing(self):
        self.stop_called += 1
        self.is_playing = False


class FakeLiveContext:
    """Synchronous LiveContext stub for tests."""

    def __init__(self, song: FakeSong | None = None):
        self._song = song if song is not None else FakeSong()
        self.run_on_main_calls = 0

    @property
    def song(self) -> FakeSong:
        return self._song

    def run_on_main(self, fn):
        self.run_on_main_calls += 1
        return fn()


@pytest.fixture()
def loaded_session_actions():
    """Yield a clean registry with the session actions freshly registered.

    Delegates to ``hallucinote_mcp.testing.isolated_actions`` so the
    save/clear/re-import pattern lives in one place (callable from the parent
    repo's cross-package tests too).
    """
    with isolated_actions():
        yield schema


# ---------- Schema sanity ----------


_EXPECTED_ACTIONS = {
    "help",
    "info",
    "set_master_property",
    "set_view",
    "set_tempo",
    "set_signature",
    "play",
    "stop",
    "seek",
    "set_arrangement_loop",
    "snapshot",
    "revert",
    "list_snapshots",
}


def test_session_registers_all_thirteen_actions(loaded_session_actions):
    names = {a.name for a in schema.actions_for("ableton_session")}
    assert names == _EXPECTED_ACTIONS


def test_help_action_lists_all_actions_except_itself(loaded_session_actions):
    resp = dispatch(Request(tool="ableton_session", action="help"))
    assert resp.ok is True
    names = {a["name"] for a in resp.result["actions"]}
    assert names == _EXPECTED_ACTIONS - {"help"}


# ---------- info ----------


def test_info_returns_structured_snapshot(loaded_session_actions):
    ctx = FakeLiveContext()
    resp = dispatch(Request(tool="ableton_session", action="info"), context=ctx)
    assert resp.ok is True
    r = resp.result
    assert r["tempo"] == 120.0
    assert r["signature"] == {"numerator": 4, "denominator": 4}
    assert r["is_playing"] is False
    assert r["master"]["volume"] == 0.85
    assert r["track_count"] == 3
    assert r["return_count"] == 1
    assert r["scene_count"] == 2
    # Reads via Application.View — defaults to "Session" in the fake.
    assert r["focused_view"] == "Session"


def test_info_focused_view_reports_unknown_when_application_unreachable(
    loaded_session_actions,
):
    """If ``song.get_application()`` raises, the field returns 'unknown' rather
    than leaking unrelated state (the bug the Critic caught in M-1 round-1)."""

    class _BadSong(FakeSong):
        def get_application(self):
            raise RuntimeError("no application")

    ctx = FakeLiveContext(song=_BadSong())
    resp = dispatch(Request(tool="ableton_session", action="info"), context=ctx)
    assert resp.ok is True
    assert resp.result["focused_view"] == "unknown"


def test_info_runs_executor_once_on_main(loaded_session_actions):
    ctx = FakeLiveContext()
    dispatch(Request(tool="ableton_session", action="info"), context=ctx)
    assert ctx.run_on_main_calls == 1


# ---------- set_tempo (declarative property_write via value_param) ----------


def test_set_tempo_writes_song_tempo(loaded_session_actions):
    ctx = FakeLiveContext()
    resp = dispatch(
        Request(tool="ableton_session", action="set_tempo", params={"bpm": 132.0}),
        context=ctx,
    )
    assert resp.ok is True
    assert ctx.song.tempo == 132.0


def test_set_tempo_validates_range(loaded_session_actions):
    resp = dispatch(
        Request(tool="ableton_session", action="set_tempo", params={"bpm": 5.0}),
    )
    assert resp.ok is False
    assert "below minimum" in (resp.error or "")
    assert resp.required == ("bpm",)


# ---------- set_signature ----------


def test_set_signature_writes_both_fields(loaded_session_actions):
    ctx = FakeLiveContext()
    resp = dispatch(
        Request(
            tool="ableton_session",
            action="set_signature",
            params={"numerator": 7, "denominator": 8},
        ),
        context=ctx,
    )
    assert resp.ok is True
    assert ctx.song.signature_numerator == 7
    assert ctx.song.signature_denominator == 8


def test_set_signature_rejects_non_power_of_two_denominator(loaded_session_actions):
    ctx = FakeLiveContext()
    resp = dispatch(
        Request(
            tool="ableton_session",
            action="set_signature",
            params={"numerator": 5, "denominator": 3},
        ),
        context=ctx,
    )
    assert resp.ok is False
    assert "power of two" in (resp.error or "")


# ---------- set_master_property ----------


@pytest.mark.parametrize(
    "property_name, value, attr_path",
    [
        ("volume", 0.55, ("mixer_device", "volume", "value")),
        ("panning", -0.3, ("mixer_device", "panning", "value")),
    ],
)
def test_set_master_property_writes_the_right_field(
    loaded_session_actions, property_name, value, attr_path
):
    ctx = FakeLiveContext()
    resp = dispatch(
        Request(
            tool="ableton_session",
            action="set_master_property",
            params={"property": property_name, "value": value},
        ),
        context=ctx,
    )
    assert resp.ok is True
    obj = ctx.song.master_track
    for attr in attr_path:
        obj = getattr(obj, attr)
    assert obj == pytest.approx(value)


def test_set_master_property_mute_branch(loaded_session_actions):
    ctx = FakeLiveContext()
    resp = dispatch(
        Request(
            tool="ableton_session",
            action="set_master_property",
            params={"property": "mute", "value": 1.0},
        ),
        context=ctx,
    )
    assert resp.ok is True
    assert ctx.song.master_track.mute is True


def test_set_master_property_rejects_unknown_property(loaded_session_actions):
    ctx = FakeLiveContext()
    resp = dispatch(
        Request(
            tool="ableton_session",
            action="set_master_property",
            params={"property": "saturation", "value": 0.5},
        ),
        context=ctx,
    )
    # Enum validation kicks in before the handler runs.
    assert resp.ok is False
    assert "not in enum" in (resp.error or "")


@pytest.mark.parametrize(
    "property_name, bad_value",
    [
        ("volume", -0.1),
        ("volume", 1.5),
        ("panning", -1.5),
        ("panning", 1.5),
    ],
)
def test_set_master_property_rejects_out_of_range_value(
    loaded_session_actions, property_name, bad_value
):
    """Per-property range validation in the handler (Critic finding from M-1).

    Without it, Live silently clamps; the agent thinks the write succeeded.
    A teaching error is better — surface the bound + value so the next
    attempt is informed.
    """
    ctx = FakeLiveContext()
    resp = dispatch(
        Request(
            tool="ableton_session",
            action="set_master_property",
            params={"property": property_name, "value": bad_value},
        ),
        context=ctx,
    )
    assert resp.ok is False
    assert "out of" in (resp.error or "")
    assert property_name in (resp.error or "")


# ---------- transport ----------


def test_play_invokes_song_start_playing(loaded_session_actions):
    ctx = FakeLiveContext()
    resp = dispatch(Request(tool="ableton_session", action="play"), context=ctx)
    assert resp.ok is True
    assert ctx.song.play_called == 1
    assert ctx.song.is_playing is True


def test_stop_invokes_song_stop_playing(loaded_session_actions):
    ctx = FakeLiveContext()
    ctx.song.is_playing = True
    resp = dispatch(Request(tool="ableton_session", action="stop"), context=ctx)
    assert resp.ok is True
    assert ctx.song.stop_called == 1
    assert ctx.song.is_playing is False


# ---------- seek ----------


def test_seek_converts_bar_beat_to_song_time(loaded_session_actions):
    ctx = FakeLiveContext()  # default 4/4
    resp = dispatch(
        Request(
            tool="ableton_session",
            action="seek",
            params={"bar": 5, "beat": 2.0},
        ),
        context=ctx,
    )
    assert resp.ok is True
    # bar 5 (1-based) means 4 bars elapsed; 4 bars * 4 beats = 16 beats; + 2 = 18
    assert ctx.song.current_song_time == pytest.approx(18.0)


def test_seek_respects_signature_for_bars_per_beat(loaded_session_actions):
    ctx = FakeLiveContext()
    ctx.song.signature_numerator = 6
    ctx.song.signature_denominator = 8
    resp = dispatch(
        Request(
            tool="ableton_session",
            action="seek",
            params={"bar": 3, "beat": 0.0},
        ),
        context=ctx,
    )
    assert resp.ok is True
    # 6/8 → 3 beats per bar (Live treats each beat as a quarter note);
    # bar 3 from bar 1 = 2 bars * 3 beats = 6 beats.
    assert ctx.song.current_song_time == pytest.approx(6.0)


def test_seek_with_implicit_beat_zero(loaded_session_actions):
    ctx = FakeLiveContext()
    resp = dispatch(
        Request(tool="ableton_session", action="seek", params={"bar": 9}),
        context=ctx,
    )
    assert resp.ok is True
    assert ctx.song.current_song_time == pytest.approx(32.0)


# ---------- set_arrangement_loop ----------


def test_set_arrangement_loop_toggles_enabled_only(loaded_session_actions):
    ctx = FakeLiveContext()
    resp = dispatch(
        Request(
            tool="ableton_session",
            action="set_arrangement_loop",
            params={"enabled": True},
        ),
        context=ctx,
    )
    assert resp.ok is True
    assert ctx.song.loop is True
    # No region given → start/length should retain their defaults
    assert ctx.song.loop_length == 4.0


def test_set_arrangement_loop_sets_region_with_signature(loaded_session_actions):
    ctx = FakeLiveContext()
    resp = dispatch(
        Request(
            tool="ableton_session",
            action="set_arrangement_loop",
            params={"enabled": True, "start_bar": 9, "end_bar": 17},
        ),
        context=ctx,
    )
    assert resp.ok is True
    # bar 9 → 8 bars elapsed → 32 beats at 4/4
    assert ctx.song.loop_start == pytest.approx(32.0)
    # 17 - 9 = 8 bars long → 32 beats
    assert ctx.song.loop_length == pytest.approx(32.0)


def test_set_arrangement_loop_rejects_one_sided_region(loaded_session_actions):
    ctx = FakeLiveContext()
    resp = dispatch(
        Request(
            tool="ableton_session",
            action="set_arrangement_loop",
            params={"enabled": True, "start_bar": 9},
        ),
        context=ctx,
    )
    assert resp.ok is False
    assert "must be provided together" in (resp.error or "")


def test_set_arrangement_loop_rejects_inverted_region(loaded_session_actions):
    ctx = FakeLiveContext()
    resp = dispatch(
        Request(
            tool="ableton_session",
            action="set_arrangement_loop",
            params={"enabled": True, "start_bar": 9, "end_bar": 9},
        ),
        context=ctx,
    )
    assert resp.ok is False
    assert "greater than start_bar" in (resp.error or "")


# ---------- set_view ----------


def test_set_view_maps_lowercase_to_live_names(loaded_session_actions):
    ctx = FakeLiveContext()
    resp = dispatch(
        Request(
            tool="ableton_session",
            action="set_view",
            params={"view": "arranger"},
        ),
        context=ctx,
    )
    assert resp.ok is True
    assert ctx.song.get_application().view.shown_views == ["Arranger"]


def test_set_view_rejects_unknown_view(loaded_session_actions):
    resp = dispatch(
        Request(
            tool="ableton_session",
            action="set_view",
            params={"view": "studio"},
        ),
    )
    # Enum validation kicks in before handler.
    assert resp.ok is False
    assert "not in enum" in (resp.error or "")


# ---------- snapshot trio — stubbed, returns the deferred-implementation error ----------


@pytest.mark.parametrize("action", ["snapshot", "revert"])
def test_snapshot_revert_return_deferred_error(loaded_session_actions, action):
    ctx = FakeLiveContext()
    resp = dispatch(
        Request(
            tool="ableton_session",
            action=action,
            params={"name": "verse-a"},
        ),
        context=ctx,
    )
    assert resp.ok is False
    assert "NotImplementedError" in (resp.error or "")
    assert "under design" in (resp.error or "") or "deferred" in (resp.error or "") or "design doc" in (resp.error or "")


def test_list_snapshots_returns_deferred_error(loaded_session_actions):
    ctx = FakeLiveContext()
    resp = dispatch(
        Request(tool="ableton_session", action="list_snapshots"),
        context=ctx,
    )
    assert resp.ok is False
    assert "NotImplementedError" in (resp.error or "")


# ---------- help payload sanity ----------


def test_help_payload_includes_param_metadata(loaded_session_actions):
    resp = dispatch(Request(tool="ableton_session", action="help"))
    actions = {a["name"]: a for a in resp.result["actions"]}
    set_tempo = actions["set_tempo"]
    assert set_tempo["required"] == ["bpm"]
    bpm_param = [p for p in set_tempo["params"] if p["name"] == "bpm"][0]
    assert bpm_param["minimum"] == 20.0
    assert bpm_param["maximum"] == 999.0


def test_help_payload_lists_set_master_property_enum(loaded_session_actions):
    resp = dispatch(Request(tool="ableton_session", action="help"))
    actions = {a["name"]: a for a in resp.result["actions"]}
    smp = actions["set_master_property"]
    property_param = [p for p in smp["params"] if p["name"] == "property"][0]
    assert property_param["enum"] == ["volume", "panning", "mute"]
