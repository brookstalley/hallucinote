"""ableton_arrangement schema + handler behavior."""
from __future__ import annotations

import pytest

from hallucinote_mcp import schema
from hallucinote_mcp.dispatcher import dispatch
from hallucinote_mcp.testing import isolated_actions
from hallucinote_mcp.wire import Request


# ---------- Fakes ----------


class FakeCue:
    def __init__(self, time: float, name: str = ""):
        self.time = time
        self.name = name


class FakeView:
    def __init__(self):
        self.follow_song = False


class FakeAppView:
    def __init__(self):
        self.zoom_calls: list[tuple[int, str, bool]] = []
        self.scroll_calls: list[tuple[int, str, bool]] = []

    def zoom_view(self, direction, view_name, ext):
        self.zoom_calls.append((direction, view_name, ext))

    def scroll_view(self, direction, view_name, ext):
        self.scroll_calls.append((direction, view_name, ext))


class FakeApplication:
    def __init__(self):
        self.view = FakeAppView()


class FakeTrack:
    def __init__(self, name: str = "T"):
        self.name = name
        self.fold_state = 0


class FakeSong:
    def __init__(
        self,
        *,
        tempo: float = 120.0,
        sig_num: int = 4,
        sig_den: int = 4,
        cues: list[FakeCue] | None = None,
        tracks: list[FakeTrack] | None = None,
    ):
        self.tempo = tempo
        self.signature_numerator = sig_num
        self.signature_denominator = sig_den
        self.last_event_time = 32.0
        self.loop = False
        self.loop_start = 0.0
        self.loop_length = 4.0
        self.cue_points = cues if cues is not None else []
        self.current_song_time = 0.0
        self.view = FakeView()
        self.tracks = tracks if tracks is not None else [FakeTrack("Drums")]
        self.set_or_delete_cue_calls: list[float] = []

    def set_or_delete_cue(self) -> None:
        """Toggle cue at the current play position (`current_song_time`).
        Append if no cue exists at that position, else remove. Mirrors
        Live's actual C++ signature: NO arguments, operates on the
        current play head."""
        time = float(self.current_song_time)
        self.set_or_delete_cue_calls.append(time)
        for i, c in enumerate(self.cue_points):
            if abs(c.time - time) < 1e-6:
                del self.cue_points[i]
                return
        self.cue_points.append(FakeCue(time, ""))

    def jump_to_next_cue(self) -> None:
        future = sorted(
            (c for c in self.cue_points if c.time > self.current_song_time + 1e-9),
            key=lambda c: c.time,
        )
        if future:
            self.current_song_time = future[0].time

    def jump_to_prev_cue(self) -> None:
        past = sorted(
            (c for c in self.cue_points if c.time < self.current_song_time - 1e-9),
            key=lambda c: -c.time,
        )
        if past:
            self.current_song_time = past[0].time


class FakeCtx:
    """LiveContext stub. Application lives on the ctx (not the song),
    matching the real LiveContext Protocol."""

    def __init__(
        self,
        song: FakeSong | None = None,
        application: FakeApplication | None = None,
    ):
        self._song = song or FakeSong()
        self._application = application or FakeApplication()
        self.run_on_main_calls = 0

    @property
    def song(self):
        return self._song

    @property
    def application(self):
        return self._application

    def run_on_main(self, fn):
        self.run_on_main_calls += 1
        return fn()



@pytest.fixture()
def loaded_actions():
    with isolated_actions():
        yield schema


# ---------- Schema sanity ----------


_EXPECTED_ARRANGEMENT_ACTIONS = {
    "help", "info", "set_loop", "control_view",
    "cue_list", "cue_create", "cue_delete", "cue_rename", "cue_jump",
}


def test_arrangement_registers_nine_actions(loaded_actions):
    names = {a.name for a in schema.actions_for("ableton_arrangement")}
    assert names == _EXPECTED_ARRANGEMENT_ACTIONS


def test_arrangement_help_lists_all_actions(loaded_actions):
    resp = dispatch(Request(tool="ableton_arrangement", action="help"))
    assert resp.ok is True
    names = {a["name"] for a in resp.result["actions"]}
    assert names == _EXPECTED_ARRANGEMENT_ACTIONS - {"help"}


# ---------- info ----------


def test_info_returns_arrangement_snapshot(loaded_actions):
    ctx = FakeCtx()
    resp = dispatch(
        Request(tool="ableton_arrangement", action="info"),
        context=ctx,
    )
    assert resp.ok is True
    assert resp.result["tempo"] == 120.0
    assert resp.result["signature"] == {"numerator": 4, "denominator": 4}
    assert resp.result["loop_enabled"] is False
    assert resp.result["cue_count"] == 0


# ---------- set_loop ----------


def test_set_loop_toggles_enabled_only(loaded_actions):
    ctx = FakeCtx()
    resp = dispatch(
        Request(
            tool="ableton_arrangement", action="set_loop",
            params={"enabled": True},
        ),
        context=ctx,
    )
    assert resp.ok is True
    assert ctx.song.loop is True
    # Region unchanged
    assert ctx.song.loop_start == 0.0
    assert ctx.song.loop_length == 4.0


def test_set_loop_sets_region(loaded_actions):
    ctx = FakeCtx()
    resp = dispatch(
        Request(
            tool="ableton_arrangement", action="set_loop",
            params={"enabled": True, "start_beats": 32.0, "end_beats": 64.0},
        ),
        context=ctx,
    )
    assert resp.ok is True
    assert ctx.song.loop_start == 32.0
    assert ctx.song.loop_length == 32.0


def test_set_loop_rejects_one_sided_region(loaded_actions):
    ctx = FakeCtx()
    resp = dispatch(
        Request(
            tool="ableton_arrangement", action="set_loop",
            params={"enabled": True, "start_beats": 32.0},
        ),
        context=ctx,
    )
    assert resp.ok is False
    assert "together" in (resp.error or "")


def test_set_loop_rejects_inverted_region(loaded_actions):
    ctx = FakeCtx()
    resp = dispatch(
        Request(
            tool="ableton_arrangement", action="set_loop",
            params={"enabled": True, "start_beats": 32.0, "end_beats": 32.0},
        ),
        context=ctx,
    )
    assert resp.ok is False
    assert "must be >" in (resp.error or "")


# ---------- control_view ----------


def test_control_view_follow_on(loaded_actions):
    ctx = FakeCtx()
    resp = dispatch(
        Request(
            tool="ableton_arrangement", action="control_view",
            params={"action_kind": "follow_on"},
        ),
        context=ctx,
    )
    assert resp.ok is True
    assert ctx.song.view.follow_song is True


def test_control_view_zoom_in(loaded_actions):
    ctx = FakeCtx()
    resp = dispatch(
        Request(
            tool="ableton_arrangement", action="control_view",
            params={"action_kind": "zoom_in"},
        ),
        context=ctx,
    )
    assert resp.ok is True
    app_view = ctx.application.view
    assert len(app_view.zoom_calls) == 1
    assert app_view.zoom_calls[0] == (0, "Arranger", False)


def test_control_view_collapse_requires_track_index(loaded_actions):
    ctx = FakeCtx()
    resp = dispatch(
        Request(
            tool="ableton_arrangement", action="control_view",
            params={"action_kind": "collapse_track"},
        ),
        context=ctx,
    )
    assert resp.ok is False
    assert "track_index" in (resp.error or "")


def test_control_view_collapse_track(loaded_actions):
    ctx = FakeCtx()
    resp = dispatch(
        Request(
            tool="ableton_arrangement", action="control_view",
            params={"action_kind": "collapse_track", "track_index": 1},
        ),
        context=ctx,
    )
    assert resp.ok is True
    assert ctx.song.tracks[0].fold_state == 1


# ---------- cue_list / cue_create / cue_delete / cue_jump ----------


def test_cue_list_returns_named_positions(loaded_actions):
    ctx = FakeCtx(FakeSong(cues=[FakeCue(16.0, "Verse"), FakeCue(32.0, "Chorus")]))
    resp = dispatch(
        Request(tool="ableton_arrangement", action="cue_list"),
        context=ctx,
    )
    assert resp.ok is True
    cues = resp.result["cue_points"]
    assert len(cues) == 2
    assert cues[0] == {"cue_index": 1, "position_beats": 16.0, "name": "Verse"}
    assert cues[1] == {"cue_index": 2, "position_beats": 32.0, "name": "Chorus"}


def test_cue_create_adds_named(loaded_actions):
    ctx = FakeCtx()
    resp = dispatch(
        Request(
            tool="ableton_arrangement", action="cue_create",
            params={"position_beats": 16.0, "name": "Verse"},
        ),
        context=ctx,
    )
    assert resp.ok is True
    assert resp.result["cue_index"] == 1
    assert resp.result["position_beats"] == 16.0
    assert resp.result["name"] == "Verse"
    assert len(ctx.song.cue_points) == 1
    assert ctx.song.cue_points[0].name == "Verse"


def test_cue_create_refuses_to_clobber_existing_cue(loaded_actions):
    """Live's set_or_delete_cue is a TOGGLE — calling it at an occupied
    position silently deletes the existing cue. cue_create's contract is to
    create, so the handler must refuse with a teaching error instead.
    """
    ctx = FakeCtx(FakeSong(cues=[FakeCue(16.0, "Verse")]))
    resp = dispatch(
        Request(
            tool="ableton_arrangement", action="cue_create",
            params={"position_beats": 16.0, "name": "AnotherName"},
        ),
        context=ctx,
    )
    assert resp.ok is False
    assert "already exists" in (resp.error or "")
    # Existing cue NOT clobbered.
    assert len(ctx.song.cue_points) == 1
    assert ctx.song.cue_points[0].name == "Verse"


def test_cue_create_rejects_negative_position(loaded_actions):
    ctx = FakeCtx()
    resp = dispatch(
        Request(
            tool="ableton_arrangement", action="cue_create",
            params={"position_beats": -1.0},
        ),
        context=ctx,
    )
    assert resp.ok is False
    assert "below minimum" in (resp.error or "")


# Regression: Live's `Song.set_or_delete_cue` is a NO-ARG toggle that
# operates on the current play position. The handler previously tried to
# call it with a positional time argument first, and only fell back to
# the seek-then-toggle pattern when the method was missing. That fast
# path crashed in real Live 12.x with ArgumentError before any cue was
# created. The fix: always seek + toggle. These tests guard the contract.


def test_cue_create_seeks_then_toggles_then_restores_play_head(loaded_actions):
    """The handler must move `current_song_time` to the target position,
    call the no-arg toggle, then restore the prior play position. The
    fake records the time the toggle saw — that's the load-bearing check
    that the handler actually seeked first."""
    song = FakeSong()
    song.current_song_time = 7.5  # arbitrary non-zero starting position
    ctx = FakeCtx(song)
    resp = dispatch(
        Request(
            tool="ableton_arrangement", action="cue_create",
            params={"position_beats": 32.0, "name": "Verse"},
        ),
        context=ctx,
    )
    assert resp.ok is True, f"unexpected error: {resp.error!r}"
    # Toggle was called exactly once, and at the target position.
    assert song.set_or_delete_cue_calls == [32.0]
    # Play head is back where it started — cue_create shouldn't move the transport.
    assert song.current_song_time == 7.5
    # Cue landed with the right name.
    assert len(song.cue_points) == 1
    assert song.cue_points[0].time == 32.0
    assert song.cue_points[0].name == "Verse"


def test_cue_create_handler_refuses_position_past_arrangement_end(loaded_actions):
    """Architectural contract: Live's ``current_song_time`` setter is
    clamped to the arrangement's extent (``last_event_time``). Writing
    past that silently fails and the cue would land at the clamped
    position, corrupting unrelated state. The handler must detect this
    BEFORE the seek and raise a teaching error pointing the user at
    the arrangement-clips-first workflow.
    """
    from hallucinote_mcp.handlers.arrangement import cue_create_handler

    # Default FakeSong has last_event_time = 32.0 (set in __init__).
    ctx = FakeCtx()
    assert ctx.song.last_event_time == 32.0
    try:
        cue_create_handler(ctx, position_beats=64.0, name="OutOfBounds")
    except ValueError as exc:
        assert "last_event_time" in str(exc)
        assert "arrangement content" in str(exc)
    else:
        raise AssertionError(
            "expected ValueError because position_beats > last_event_time"
        )


def test_cue_create_does_not_pass_position_to_toggle(loaded_actions):
    """Stronger guard: a fake whose toggle REJECTS any positional argument
    (mirroring Live 12.x's C++ signature) must still let cue_create
    succeed. If the handler ever regresses to calling `set_or_delete_cue(pos)`,
    this test fails loudly with a TypeError-shaped trail."""

    class _StrictToggleSong(FakeSong):
        def set_or_delete_cue(self, *args, **kwargs):  # type: ignore[override]
            if args or kwargs:
                raise TypeError(
                    "set_or_delete_cue takes no positional arguments "
                    f"(got args={args!r}, kwargs={kwargs!r}) — this is "
                    "Live 12.x's actual signature"
                )
            return super().set_or_delete_cue()

    song = _StrictToggleSong()
    ctx = FakeCtx(song)
    resp = dispatch(
        Request(
            tool="ableton_arrangement", action="cue_create",
            params={"position_beats": 16.0, "name": "Intro"},
        ),
        context=ctx,
    )
    assert resp.ok is True, f"unexpected error: {resp.error!r}"
    assert len(song.cue_points) == 1
    assert song.cue_points[0].name == "Intro"


def test_cue_delete_removes(loaded_actions):
    song = FakeSong(cues=[FakeCue(16.0, "Verse"), FakeCue(32.0, "Chorus")])
    # Add a delete method to FakeCue for the per-cue delete path
    for c in song.cue_points:
        c.delete = lambda c=c: song.cue_points.remove(c)
    ctx = FakeCtx(song)
    resp = dispatch(
        Request(
            tool="ableton_arrangement", action="cue_delete",
            params={"cue_index": 1},
        ),
        context=ctx,
    )
    assert resp.ok is True
    assert len(ctx.song.cue_points) == 1
    assert ctx.song.cue_points[0].name == "Chorus"


def test_cue_delete_out_of_range(loaded_actions):
    ctx = FakeCtx()
    resp = dispatch(
        Request(
            tool="ableton_arrangement", action="cue_delete",
            params={"cue_index": 99},
        ),
        context=ctx,
    )
    assert resp.ok is False
    assert "out of range" in (resp.error or "")


def test_cue_rename_sets_name(loaded_actions):
    """cue_rename writes the name directly on the CuePoint — no
    seek/toggle dance — so it's synchronous and reliable. Mainly used
    as a recovery path when cue_create completed but the inline rename
    couldn't apply due to Live's audio-thread settle timing.
    """
    song = FakeSong(cues=[FakeCue(16.0, "Verse"), FakeCue(32.0, "Chorus")])
    ctx = FakeCtx(song)
    resp = dispatch(
        Request(
            tool="ableton_arrangement", action="cue_rename",
            params={"cue_index": 2, "name": "Refrain"},
        ),
        context=ctx,
    )
    assert resp.ok is True, f"unexpected error: {resp.error!r}"
    assert resp.result == {
        "cue_index": 2,
        "position_beats": 32.0,
        "name": "Refrain",
    }
    assert song.cue_points[1].name == "Refrain"
    # The cue at index 1 is untouched.
    assert song.cue_points[0].name == "Verse"


def test_cue_rename_out_of_range(loaded_actions):
    ctx = FakeCtx()
    resp = dispatch(
        Request(
            tool="ableton_arrangement", action="cue_rename",
            params={"cue_index": 99, "name": "x"},
        ),
        context=ctx,
    )
    assert resp.ok is False
    assert "out of range" in (resp.error or "")


def test_cue_jump_by_direction(loaded_actions):
    ctx = FakeCtx(FakeSong(cues=[FakeCue(16.0, "Verse"), FakeCue(32.0, "Chorus")]))
    resp = dispatch(
        Request(
            tool="ableton_arrangement", action="cue_jump",
            params={"direction": "next"},
        ),
        context=ctx,
    )
    assert resp.ok is True
    assert ctx.song.current_song_time == 16.0


def test_cue_jump_by_name(loaded_actions):
    cues = [FakeCue(16.0, "Verse"), FakeCue(32.0, "Chorus")]
    for c in cues:
        c.jump = lambda c=c: setattr(ctx.song, "current_song_time", c.time)
    ctx = FakeCtx(FakeSong(cues=cues))
    # Re-bind jump to actual ctx.song now that ctx exists
    for c in ctx.song.cue_points:
        c.jump = lambda c=c, _s=ctx.song: setattr(_s, "current_song_time", c.time)
    resp = dispatch(
        Request(
            tool="ableton_arrangement", action="cue_jump",
            params={"name": "Chorus"},
        ),
        context=ctx,
    )
    assert resp.ok is True
    assert ctx.song.current_song_time == 32.0


def test_cue_jump_requires_exactly_one(loaded_actions):
    ctx = FakeCtx()
    # Neither
    r1 = dispatch(
        Request(tool="ableton_arrangement", action="cue_jump", params={}),
        context=ctx,
    )
    assert r1.ok is False
    assert "exactly one" in (r1.error or "")
    # Both
    r2 = dispatch(
        Request(
            tool="ableton_arrangement", action="cue_jump",
            params={"direction": "next", "name": "Verse"},
        ),
        context=ctx,
    )
    assert r2.ok is False
    assert "exactly one" in (r2.error or "")


def test_cue_jump_unknown_name_lists_available(loaded_actions):
    ctx = FakeCtx(FakeSong(cues=[FakeCue(16.0, "Verse")]))
    resp = dispatch(
        Request(
            tool="ableton_arrangement", action="cue_jump",
            params={"name": "Bridge"},
        ),
        context=ctx,
    )
    assert resp.ok is False
    assert "Bridge" in (resp.error or "")
    assert "Verse" in (resp.error or "")


# ---------- run_on_main discipline ----------


def test_arrangement_execution_marshals_to_main_thread(loaded_actions):
    ctx = FakeCtx()
    dispatch(
        Request(tool="ableton_arrangement", action="info"),
        context=ctx,
    )
    assert ctx.run_on_main_calls == 1
