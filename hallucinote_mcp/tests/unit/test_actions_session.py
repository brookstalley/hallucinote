"""ableton_session schema + handler behavior — drives M-1's actions through
the dispatcher against a fake Live API.

The actions package's import side-effects mean every test here must use the
isolated_registry fixture, then re-run the registration. The fixture clears
the registry on entry and restores it on exit — the test body imports the
actions module (or calls the targeted registration) inside that isolation.
"""
from __future__ import annotations

import threading
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
    """Quacks like ``Live.Song.Song`` for the session-action surface.

    Note: Live's actual ``Song`` does NOT expose ``get_application`` — the
    Application is reached via ``Live.Application.get_application()``
    (module-level) and surfaced to handlers via ``LiveContext.application``.
    This fake mirrors the real Song surface and intentionally does NOT
    define ``get_application``; tests that need the Application reach it
    via ``ctx.application``.
    """

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

        # Arrangement-override latch (back_to_arranger). Default: not engaged.
        self.back_to_arranger = 0
        self.re_enable_automation_called = 0

        self.play_called = 0
        self.continue_called = 0
        self.stop_called = 0

    def start_playing(self):
        self.play_called += 1
        self.is_playing = True

    def continue_playing(self):
        self.continue_called += 1
        self.is_playing = True

    def stop_playing(self):
        self.stop_called += 1
        self.is_playing = False

    def re_enable_automation(self):
        self.re_enable_automation_called += 1


class LatchStuckSong(FakeSong):
    """A Song whose ``back_to_arranger`` latch ignores API writes — mirrors the
    Live 12.x LOM quirk where ``setattr(song, 'back_to_arranger', 0)`` is
    accepted without error but does not clear the override.
    """

    def __init__(self):
        super().__init__()
        self._latched = True

    @property
    def back_to_arranger(self):
        return self._latched

    @back_to_arranger.setter
    def back_to_arranger(self, value):
        # Live silently drops the write; the latch survives.
        pass


class HonoredLatchNoReEnableSong(FakeSong):
    """A latched Song that HONORS the API clear but exposes no callable
    ``re_enable_automation`` — mirrors an older Live build / minimal surface.
    Exercises the handler's ``callable()`` guard so a missing method does not
    crash the recovery.
    """

    def __init__(self):
        super().__init__()
        self.back_to_arranger = 1  # latched; plain attr setter honors the clear
        self.re_enable_automation = None  # not callable → guard must skip it


class FakeLiveContext:
    """Synchronous LiveContext stub for tests.

    Owns the FakeApplication (the Application object lives on the context,
    not the Song — symmetric to the real LiveContext Protocol). Tests that
    want to drive a missing-Application scenario can construct
    ``FakeLiveContext(application=None)`` or pass an object whose
    ``view`` access raises.
    """

    _MISSING = object()  # sentinel — distinguishes "not given" from "None"

    def __init__(
        self,
        song: FakeSong | None = None,
        application: Any = _MISSING,
    ):
        self._song = song if song is not None else FakeSong()
        self._application = (
            FakeApplication() if application is FakeLiveContext._MISSING else application
        )
        self.run_on_main_calls = 0
        self._live_state_lock = threading.RLock()

    @property
    def song(self) -> FakeSong:
        return self._song

    @property
    def application(self) -> Any:
        return self._application

    @property
    def live_state_lock(self):
        return self._live_state_lock

    def run_on_main(self, fn, **_kwargs):
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
    "continue_playing",
    "stop",
    "seek",
    "back_to_arrangement",
    "bout_status",
    "abandon_bout",
    "snapshot",
    "revert",
    "list_snapshots",
    "introspect",
}
# Wave M-5: set_arrangement_loop dropped from ableton_session; the canonical
# home is ableton_arrangement(action='set_loop') — see test_actions_arrangement.


def test_session_registers_expected_actions(loaded_session_actions):
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
    # Arrangement-override latch is always reported; not engaged by default,
    # and no teaching block is attached when nothing is overridden.
    assert r["back_to_arranger"] is False
    assert "arrangement_override" not in r


def test_info_surfaces_latched_arrangement_override(loaded_session_actions):
    """When back_to_arranger is engaged, info names the state + the GUI
    recovery instead of leaving the agent to read a bare bool (MCP-7P3R)."""
    song = FakeSong()
    song.back_to_arranger = 1
    ctx = FakeLiveContext(song=song)
    resp = dispatch(Request(tool="ableton_session", action="info"), context=ctx)
    assert resp.ok is True
    r = resp.result
    assert r["back_to_arranger"] is True
    assert r["arrangement_override"]["latched"] is True
    note = r["arrangement_override"]["note"]
    assert "Back to Arrangement" in note
    assert "back_to_arrangement" in note  # points at the recovery action


def test_info_focused_view_reports_unknown_when_application_unreachable(
    loaded_session_actions,
):
    """If ``context.application`` raises, the field returns 'unknown' rather
    than leaking unrelated state (the bug the Critic caught in M-1 round-1)."""

    class _RaisingApp:
        @property
        def view(self):
            raise RuntimeError("no application")

    ctx = FakeLiveContext(application=_RaisingApp())
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
    # Wave-2 W2-D / B-15: result_template echoes the input bpm so callers
    # get a confirming response shape instead of result=None.
    assert resp.result == {"tempo": 132.0}, (
        f"set_tempo should return {{tempo: bpm}} via result_template; "
        f"got {resp.result!r}"
    )


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
    # play = Live's *Start* verb; we report the verb invoked, not a claimed
    # start position (the realized position isn't reliably read back).
    assert resp.result["is_playing"] is True
    assert resp.result["verb"] == "start"
    assert "started_from" not in resp.result  # no fabricated position field
    # the note teaches the override latch as the real cause of "no audio".
    assert "back_to_arrangement" in resp.result["note"]


def test_continue_playing_reports_continue_verb(loaded_session_actions):
    ctx = FakeLiveContext()
    resp = dispatch(
        Request(tool="ableton_session", action="continue_playing"), context=ctx
    )
    assert resp.ok is True
    # *Continue*: resume from the last-stopped position.
    assert ctx.song.continue_called == 1
    assert ctx.song.play_called == 0
    assert ctx.song.is_playing is True
    assert resp.result["is_playing"] is True
    assert resp.result["verb"] == "continue"
    assert "started_from" not in resp.result
    assert "seek" in resp.result["note"]


def test_stop_invokes_song_stop_playing(loaded_session_actions):
    ctx = FakeLiveContext()
    ctx.song.is_playing = True
    resp = dispatch(Request(tool="ableton_session", action="stop"), context=ctx)
    assert resp.ok is True
    assert ctx.song.stop_called == 1
    assert ctx.song.is_playing is False
    # Wave-2 W2-D / B-15: structured result instead of None.
    assert resp.result == {"is_playing": False}


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


def test_seek_acquires_live_state_lock(loaded_session_actions):
    """B-21 regression. ``seek`` writes ``current_song_time``, which
    races against concurrent ``cue_create`` / ``cue_delete`` callers.
    The handler must take ``live_state_lock`` around the write so the
    operations serialize.
    """
    class _RecordingLock:
        def __init__(self) -> None:
            self.events: list[str] = []
            self._inner = threading.RLock()

        def __enter__(self):
            self._inner.acquire()
            self.events.append("acquire")
            return self

        def __exit__(self, *args):
            self.events.append("release")
            self._inner.release()
            return False

    ctx = FakeLiveContext()
    recording = _RecordingLock()
    ctx._live_state_lock = recording
    resp = dispatch(
        Request(
            tool="ableton_session", action="seek",
            params={"bar": 3, "beat": 0.0},
        ),
        context=ctx,
    )
    assert resp.ok is True
    # The handler takes the lock, and gives back every acquire it made. There
    # is more than one because the shared locate primitive takes it too (the
    # RLock is re-entrant on purpose); what must never drift is the balance —
    # an unbalanced seek would strand the lock against every cue caller.
    assert recording.events[0] == "acquire"
    assert recording.events[-1] == "release"
    assert recording.events.count("acquire") == recording.events.count("release")


# ---------- back_to_arrangement ----------


def test_back_to_arrangement_noop_when_not_overridden(loaded_session_actions):
    """Nothing latched → cleared:true, was_latched:false, and no write is
    attempted on the latch."""
    ctx = FakeLiveContext()
    resp = dispatch(
        Request(tool="ableton_session", action="back_to_arrangement"),
        context=ctx,
    )
    assert resp.ok is True
    assert resp.result["cleared"] is True
    assert resp.result["was_latched"] is False
    # No best-effort recovery attempted when there was nothing to recover.
    assert ctx.song.re_enable_automation_called == 0


def test_back_to_arrangement_clears_a_honored_latch(loaded_session_actions):
    """When Live honors the API clear (the FakeSong latch is a plain settable
    attribute), the latch drops and we report cleared:true."""
    song = FakeSong()
    song.back_to_arranger = 1
    ctx = FakeLiveContext(song=song)
    resp = dispatch(
        Request(tool="ableton_session", action="back_to_arrangement"),
        context=ctx,
    )
    assert resp.ok is True
    assert resp.result["cleared"] is True
    assert resp.result["was_latched"] is True
    assert song.back_to_arranger == 0
    # Mirrors the GUI button: it also re-enables overridden automation.
    assert song.re_enable_automation_called == 1
    assert "warning" not in resp.result


def test_back_to_arrangement_teaches_when_live_ignores_the_clear(
    loaded_session_actions,
):
    """The Live 12.x quirk: setattr is accepted but the latch survives. The
    action must report cleared:false with a teaching warning naming the GUI
    button — never a misleading ok (MCP-7P3R direction 1)."""
    song = LatchStuckSong()
    ctx = FakeLiveContext(song=song)
    resp = dispatch(
        Request(tool="ableton_session", action="back_to_arrangement"),
        context=ctx,
    )
    assert resp.ok is True
    assert resp.result["cleared"] is False
    assert resp.result["was_latched"] is True
    # It still tried (re_enable_automation is the GUI button's other half).
    assert song.re_enable_automation_called == 1
    assert "Back to Arrangement" in resp.result["warning"]


def test_back_to_arrangement_tolerates_missing_re_enable_automation(
    loaded_session_actions,
):
    """The callable() guard skips a non-callable/absent re_enable_automation
    (older Live build) without crashing — the latch still clears."""
    song = HonoredLatchNoReEnableSong()
    ctx = FakeLiveContext(song=song)
    resp = dispatch(
        Request(tool="ableton_session", action="back_to_arrangement"), context=ctx
    )
    assert resp.ok is True
    assert resp.result["cleared"] is True
    assert resp.result["was_latched"] is True
    assert song.back_to_arranger == 0  # the plain setter honored the clear


def test_back_to_arrangement_runs_once_on_main(loaded_session_actions):
    """Atomic: the whole read-clear-readback happens in one main-thread bounce
    (the handler is not runs_on_worker)."""
    song = FakeSong()
    song.back_to_arranger = 1
    ctx = FakeLiveContext(song=song)
    dispatch(
        Request(tool="ableton_session", action="back_to_arrangement"),
        context=ctx,
    )
    assert ctx.run_on_main_calls == 1


# set_arrangement_loop: deprecated in Wave M-5 — see
# test_actions_arrangement.py::set_loop tests for the canonical home.


def test_session_no_longer_exposes_set_arrangement_loop(loaded_session_actions):
    """Wave M-5: ableton_session(action='set_arrangement_loop') was dropped;
    the canonical home is ableton_arrangement(action='set_loop'). Lock the
    absence so a well-meaning future PR doesn't silently re-register it.
    """
    assert schema.get("ableton_session", "set_arrangement_loop") is None, (
        "set_arrangement_loop must NOT be on ableton_session — see Wave M-5 "
        "decision. Use ableton_arrangement(action='set_loop', enabled=...) "
        "with beats (not bars) per the meter-agnostic-wire principle."
    )


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
    # Application lives on the context (not the song) — same surface the
    # handler reaches through.
    assert ctx.application.view.shown_views == ["Arranger"]


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


# ---------- W6-Probe: introspect ----------
#
# Read-only LOM probing. The action surfaces dir/type/value/repr for any
# dotted path rooted at song/application/view. Used in subsequent Wave 6
# chunks (E/F/G/I/J) for empirical confirmation of Live's API surface
# when third-party LOM dumps are stale or ambiguous.


def test_introspect_dir_on_song_lists_public_members(loaded_session_actions):
    ctx = FakeLiveContext()
    resp = dispatch(
        Request(
            tool="ableton_session", action="introspect",
            params={"target": "song", "what": "dir"},
        ),
        context=ctx,
    )
    assert resp.ok is True, resp.error
    members = resp.result["members"]
    assert "tempo" in members
    assert "tracks" in members
    assert "master_track" in members
    # Private filtered by default.
    assert not any(m.startswith("_") for m in members)


def test_introspect_dir_include_private_shows_underscore_names(loaded_session_actions):
    ctx = FakeLiveContext()
    resp = dispatch(
        Request(
            tool="ableton_session", action="introspect",
            params={"target": "song", "what": "dir", "include_private": True},
        ),
        context=ctx,
    )
    assert resp.ok is True
    # FakeSong has no private attrs of its own, but Python objects have
    # ``__class__``, ``__init__``, etc. — those must surface.
    assert any(m.startswith("_") for m in resp.result["members"])


def test_introspect_type_on_song_tempo_returns_float(loaded_session_actions):
    ctx = FakeLiveContext()
    resp = dispatch(
        Request(
            tool="ableton_session", action="introspect",
            params={"target": "song.tempo", "what": "type"},
        ),
        context=ctx,
    )
    assert resp.ok is True
    assert resp.result["type"] == "float"


def test_introspect_value_on_primitive_returns_value(loaded_session_actions):
    ctx = FakeLiveContext()
    resp = dispatch(
        Request(
            tool="ableton_session", action="introspect",
            params={"target": "song.tempo", "what": "value"},
        ),
        context=ctx,
    )
    assert resp.ok is True
    assert resp.result["value"] == 120.0
    assert "note" not in resp.result


def test_introspect_value_on_non_primitive_returns_repr_with_note(loaded_session_actions):
    ctx = FakeLiveContext()
    resp = dispatch(
        Request(
            tool="ableton_session", action="introspect",
            params={"target": "song.master_track", "what": "value"},
        ),
        context=ctx,
    )
    assert resp.ok is True
    assert isinstance(resp.result["value"], str)
    assert "note" in resp.result


def test_introspect_repr_always_stringifies(loaded_session_actions):
    ctx = FakeLiveContext()
    resp = dispatch(
        Request(
            tool="ableton_session", action="introspect",
            params={"target": "song.tempo", "what": "repr"},
        ),
        context=ctx,
    )
    assert resp.ok is True
    assert resp.result["repr"] == "120.0"


def test_introspect_walks_nested_dotted_path(loaded_session_actions):
    ctx = FakeLiveContext()
    resp = dispatch(
        Request(
            tool="ableton_session", action="introspect",
            params={
                "target": "song.master_track.mixer_device.volume.value",
                "what": "value",
            },
        ),
        context=ctx,
    )
    assert resp.ok is True
    assert resp.result["value"] == 0.85


def test_introspect_supports_zero_based_index(loaded_session_actions):
    ctx = FakeLiveContext()
    resp = dispatch(
        Request(
            tool="ableton_session", action="introspect",
            params={"target": "song.tracks[0]", "what": "repr"},
        ),
        context=ctx,
    )
    assert resp.ok is True
    # FakeSong.tracks[0] is `object()` — repr starts with '<object object'.
    assert "object object" in resp.result["repr"]


def test_introspect_index_out_of_range_raises_teaching_error(loaded_session_actions):
    ctx = FakeLiveContext()
    resp = dispatch(
        Request(
            tool="ableton_session", action="introspect",
            params={"target": "song.tracks[99]", "what": "type"},
        ),
        context=ctx,
    )
    assert resp.ok is False
    assert "index 99" in (resp.error or "")


def test_introspect_invalid_root_raises_teaching_error(loaded_session_actions):
    ctx = FakeLiveContext()
    resp = dispatch(
        Request(
            tool="ableton_session", action="introspect",
            params={"target": "context.foo", "what": "dir"},
        ),
        context=ctx,
    )
    assert resp.ok is False
    assert "root" in (resp.error or "")
    assert "context" in (resp.error or "")


def test_introspect_missing_attribute_raises_teaching_error(loaded_session_actions):
    ctx = FakeLiveContext()
    resp = dispatch(
        Request(
            tool="ableton_session", action="introspect",
            params={"target": "song.nonexistent_attribute", "what": "dir"},
        ),
        context=ctx,
    )
    assert resp.ok is False
    err = resp.error or ""
    assert "song" in err and "nonexistent_attribute" in err


def test_introspect_invalid_what_raises_teaching_error(loaded_session_actions):
    ctx = FakeLiveContext()
    resp = dispatch(
        Request(
            tool="ableton_session", action="introspect",
            params={"target": "song", "what": "eval"},
        ),
        context=ctx,
    )
    assert resp.ok is False
    assert "what" in (resp.error or "")


def test_introspect_view_root_aliases_application_view(loaded_session_actions):
    ctx = FakeLiveContext()
    # Both paths must resolve to the same object.
    via_view = dispatch(
        Request(
            tool="ableton_session", action="introspect",
            params={"target": "view", "what": "repr"},
        ),
        context=ctx,
    )
    via_application = dispatch(
        Request(
            tool="ableton_session", action="introspect",
            params={"target": "application.view", "what": "repr"},
        ),
        context=ctx,
    )
    assert via_view.ok is True
    assert via_application.ok is True
    assert via_view.result["repr"] == via_application.result["repr"]


def test_introspect_empty_target_raises_teaching_error(loaded_session_actions):
    ctx = FakeLiveContext()
    resp = dispatch(
        Request(
            tool="ableton_session", action="introspect",
            params={"target": "", "what": "dir"},
        ),
        context=ctx,
    )
    assert resp.ok is False
    assert "non-empty" in (resp.error or "")


# ---------------------------------------------------------------------------
# #471 — seek moves the START PLAYING POSITION, not only the playhead
# ---------------------------------------------------------------------------


class _StartPositionSong(FakeSong):
    """A Song shaped like Live's: the playhead and the start playing position
    are separate, and only ``CuePoint.jump()`` moves the second."""

    def __init__(self, *, start_position: float = 351.3, has_cue_api: bool = True):
        super().__init__()
        self.start_position = float(start_position)
        self.cue_points: list[Any] = []
        self.last_event_time = 4096.0
        if not has_cue_api:
            self.set_or_delete_cue = None

    def set_or_delete_cue(self) -> None:
        at = self.current_song_time
        for i, cue in enumerate(self.cue_points):
            if abs(cue.time - at) < 1e-6:
                del self.cue_points[i]
                return
        self.cue_points.append(_SessionCue(self, at))

    def start_playing(self) -> None:
        self.current_song_time = self.start_position
        super().start_playing()


class _SessionCue:
    def __init__(self, song: _StartPositionSong, time_: float):
        self._song = song
        self.time = float(time_)
        self.name = ""

    def jump(self) -> None:
        self._song.start_position = self.time
        self._song.current_song_time = self.time


def test_seek_then_play_actually_begins_where_it_was_told(loaded_session_actions):
    """The read-back workflow that diagnosed #471 depends on this. A seek that
    moved only the playhead read back perfectly and then played from wherever
    play was last pressed, so every parameter sampled after it described the
    wrong beat."""
    ctx = FakeLiveContext(song=_StartPositionSong(start_position=351.3))

    resp = dispatch(
        Request(tool="ableton_session", action="seek", params={"bar": 3}),
        context=ctx,
    )

    assert resp.ok is True
    assert resp.result["start_position_moved"] is True
    ctx.song.start_playing()
    assert ctx.song.current_song_time == pytest.approx(8.0)


def test_seek_reports_a_degraded_locate_rather_than_claiming_one(
    loaded_session_actions,
):
    """A Live with no cue-toggle surface cannot have its start position moved.
    The playhead still lands, and the caller is told which of the two it got —
    a silent downgrade is what made this class of bug invisible."""
    ctx = FakeLiveContext(
        song=_StartPositionSong(start_position=351.3, has_cue_api=False)
    )

    resp = dispatch(
        Request(tool="ableton_session", action="seek", params={"bar": 3}),
        context=ctx,
    )

    assert resp.ok is True
    assert resp.result["start_position_moved"] is False
    assert resp.result["locate_method"] == "playhead_only"
    assert "set_or_delete_cue" in resp.result["locate_detail"]
    assert ctx.song.current_song_time == pytest.approx(8.0)


def test_the_play_note_no_longer_promises_seek_then_play_locates(
    loaded_session_actions,
):
    """The note used to tell operators that seek-then-play locates-and-plays,
    and cited the render capture as relying on it. Both halves were false, and
    the note is read at exactly the moment someone is debugging this."""
    from hallucinote_mcp.handlers.session import _PLAY_SEMANTICS_NOTE

    assert "START PLAYING POSITION" in _PLAY_SEMANTICS_NOTE
    assert "locates-and-plays" not in _PLAY_SEMANTICS_NOTE
