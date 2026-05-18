"""ableton_arrangement schema + handler behavior."""
from __future__ import annotations

import threading

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
    def __init__(self, name: str = "T", *, is_foldable: bool = False):
        self.name = name
        self.fold_state = 0
        # Live 12.4: only group tracks (and rack-typed tracks) accept
        # collapse/expand. Writing fold_state on a regular track raises
        # ``RuntimeError: This Track can not be collapsed``. Mirror that
        # by defaulting is_foldable=False (Wave-2 W2-C / B-13 root cause).
        self.is_foldable = is_foldable


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
    matching the real LiveContext Protocol. ``live_state_lock`` is a
    real ``threading.RLock`` so concurrent-caller tests exercise the
    same mutual-exclusion semantics as real Live."""

    def __init__(
        self,
        song: FakeSong | None = None,
        application: FakeApplication | None = None,
    ):
        self._song = song or FakeSong()
        self._application = application or FakeApplication()
        self.run_on_main_calls = 0
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
        self.run_on_main_calls += 1
        return fn()



@pytest.fixture()
def loaded_actions():
    with isolated_actions():
        yield schema


# ---------- Schema sanity ----------


_EXPECTED_ARRANGEMENT_ACTIONS = {
    "help", "info", "set_loop", "control_view",
    "cue_list", "cue_create", "cue_create_batch",
    "cue_delete", "cue_rename", "cue_jump",
}


def test_arrangement_registers_expected_actions(loaded_actions):
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
    """collapse_track works on FOLDABLE tracks (group/rack)."""
    foldable_track = FakeTrack(name="Group A", is_foldable=True)
    ctx = FakeCtx(FakeSong(tracks=[foldable_track]))
    resp = dispatch(
        Request(
            tool="ableton_arrangement", action="control_view",
            params={"action_kind": "collapse_track", "track_index": 1},
        ),
        context=ctx,
    )
    assert resp.ok is True
    assert ctx.song.tracks[0].fold_state == 1


def test_control_view_collapse_non_foldable_track_teaches(loaded_actions):
    """Wave-2 W2-C / B-13: collapse_track on a non-foldable track must
    surface a teaching error pointing at the group-track workaround,
    not Live's raw RuntimeError.
    """
    ctx = FakeCtx()  # default tracks have is_foldable=False
    resp = dispatch(
        Request(
            tool="ableton_arrangement", action="control_view",
            params={"action_kind": "collapse_track", "track_index": 1},
        ),
        context=ctx,
    )
    assert resp.ok is False
    assert "not a foldable track" in (resp.error or "")
    assert "group" in (resp.error or "").lower()


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


def test_seek_then_settle_returns_when_playhead_confirms_target():
    """Wave-2 W2-F: the new poll-confirmed settle helper waits for the
    audio thread to acknowledge the seek (via the current_song_time
    getter) instead of trusting a fixed sleep. The synchronous fake's
    setter is immediately visible, so this returns on the first poll.
    """
    from hallucinote_mcp.handlers.arrangement import _seek_then_settle
    song = FakeSong()
    song.current_song_time = 0.0
    _seek_then_settle(song, 12.0)
    assert song.current_song_time == 12.0


def test_seek_then_settle_times_out_when_audio_thread_stuck():
    """If the audio thread never picks up the write, the getter stays at
    the old value forever. The helper must surface a TimeoutError with
    actionable text instead of hanging.
    """
    from hallucinote_mcp.handlers.arrangement import _seek_then_settle
    import pytest

    class _StuckSong:
        """Setter accepted but never acknowledged by the getter."""
        _stored = 0.0

        @property
        def current_song_time(self) -> float:
            return 0.0  # always lies — getter never reflects the write

        @current_song_time.setter
        def current_song_time(self, v: float) -> None:
            self._stored = v

    with pytest.raises(TimeoutError) as exc_info:
        _seek_then_settle(_StuckSong(), 8.0, max_wait_s=0.15, poll_interval_s=0.05)
    msg = str(exc_info.value)
    assert "did not settle" in msg
    assert "8" in msg  # mentions the target beat


def test_cue_delete_verifies_via_cue_points_side_effect(loaded_actions):
    """Wave-2 W2-6: cue_delete used to return ok:true after the toggle
    even when the cue was still present (the toggle fired at the wrong
    position due to the W2-4 settle race). Verify-via-side-effect:
    after the toggle, scan cue_points and raise if the targeted cue
    persists.
    """
    # Build a fake that toggles ONLY if current_song_time matches the cue.
    # Then override set_or_delete_cue to "miss" — simulating the W2-4 race
    # by leaving the cue intact regardless of toggle.
    song = FakeSong(cues=[FakeCue(16.0, "Verse"), FakeCue(32.0, "Chorus")])

    def _bad_toggle() -> None:  # simulates W2-4: toggle fired at wrong pos
        pass  # no state change at all

    song.set_or_delete_cue = _bad_toggle
    ctx = FakeCtx(song)
    resp = dispatch(
        Request(
            tool="ableton_arrangement", action="cue_delete",
            params={"cue_index": 1},
        ),
        context=ctx,
    )
    assert resp.ok is False
    err = (resp.error or "")
    assert "did not remove" in err
    assert "still present" in err
    # The cue is still there (no spurious removal).
    assert any(c.time == 16.0 for c in song.cue_points)
    # Playhead restored despite the verify-failure raise (try/finally
    # symmetric with cue_create).
    assert song.current_song_time == 0.0


def test_cue_delete_succeeds_when_toggle_works(loaded_actions):
    """Happy-path symmetric with the verify regression: when the toggle
    actually removes the cue, cue_delete returns ok:true.
    """
    song = FakeSong(cues=[FakeCue(16.0, "Verse")])
    ctx = FakeCtx(song)
    resp = dispatch(
        Request(
            tool="ableton_arrangement", action="cue_delete",
            params={"cue_index": 1},
        ),
        context=ctx,
    )
    assert resp.ok is True
    assert resp.result["deleted_cue_index"] == 1
    assert len(song.cue_points) == 0


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


# ---------- cue_create_batch ----------


def test_cue_create_batch_creates_all_in_order(loaded_actions):
    """Happy path: a 4-element batch produces 4 cues at the requested
    positions with the requested names."""
    ctx = FakeCtx()
    ctx.song.last_event_time = 64.0
    resp = dispatch(
        Request(
            tool="ableton_arrangement", action="cue_create_batch",
            params={"cues": [
                {"position_beats": 0.0, "name": "Intro"},
                {"position_beats": 16.0, "name": "Verse"},
                {"position_beats": 32.0, "name": "Chorus"},
                {"position_beats": 48.0, "name": "Bridge"},
            ]},
        ),
        context=ctx,
    )
    assert resp.ok is True, f"unexpected error: {resp.error!r}"
    assert resp.result["cue_count"] == 4
    assert len(resp.result["cues"]) == 4
    # All four landed at requested positions with requested names.
    landed = {(c.time, c.name) for c in ctx.song.cue_points}
    assert landed == {
        (0.0, "Intro"), (16.0, "Verse"),
        (32.0, "Chorus"), (48.0, "Bridge"),
    }


def test_cue_create_batch_omitted_name_is_blank(loaded_actions):
    """Entries without ``name`` create a cue with Live's auto-name
    (empty string in the fake — real Live's "1", "2", etc.)."""
    ctx = FakeCtx()
    resp = dispatch(
        Request(
            tool="ableton_arrangement", action="cue_create_batch",
            params={"cues": [{"position_beats": 8.0}]},
        ),
        context=ctx,
    )
    assert resp.ok is True
    assert ctx.song.cue_points[0].name == ""


def test_cue_create_batch_rejects_empty_list(loaded_actions):
    ctx = FakeCtx()
    resp = dispatch(
        Request(
            tool="ableton_arrangement", action="cue_create_batch",
            params={"cues": []},
        ),
        context=ctx,
    )
    assert resp.ok is False
    assert "empty" in (resp.error or "")


def test_cue_create_batch_rejects_non_list(loaded_actions):
    ctx = FakeCtx()
    resp = dispatch(
        Request(
            tool="ableton_arrangement", action="cue_create_batch",
            params={"cues": {"position_beats": 0.0}},
        ),
        context=ctx,
    )
    # Dispatcher's param validation rejects dict-where-list-expected before
    # the handler even runs.
    assert resp.ok is False


def test_cue_create_batch_rejects_non_dict_entry(loaded_actions):
    ctx = FakeCtx()
    resp = dispatch(
        Request(
            tool="ableton_arrangement", action="cue_create_batch",
            params={"cues": [16.0]},
        ),
        context=ctx,
    )
    assert resp.ok is False
    assert "must be a dict" in (resp.error or "")


def test_cue_create_batch_rejects_missing_position(loaded_actions):
    ctx = FakeCtx()
    resp = dispatch(
        Request(
            tool="ableton_arrangement", action="cue_create_batch",
            params={"cues": [{"name": "Intro"}]},
        ),
        context=ctx,
    )
    assert resp.ok is False
    assert "position_beats" in (resp.error or "")


def test_cue_create_batch_rejects_duplicate_position(loaded_actions):
    """Live's cue list rejects two cues at the same position. Pre-flight
    duplicate detection beats a partial batch + opaque mid-loop error."""
    ctx = FakeCtx()
    resp = dispatch(
        Request(
            tool="ableton_arrangement", action="cue_create_batch",
            params={"cues": [
                {"position_beats": 16.0, "name": "A"},
                {"position_beats": 16.0, "name": "B"},
            ]},
        ),
        context=ctx,
    )
    assert resp.ok is False
    assert "duplicate" in (resp.error or "")
    # Pre-validation fired before any cue was created.
    assert len(ctx.song.cue_points) == 0


def test_cue_create_batch_rejects_invalid_name_type(loaded_actions):
    ctx = FakeCtx()
    resp = dispatch(
        Request(
            tool="ableton_arrangement", action="cue_create_batch",
            params={"cues": [{"position_beats": 16.0, "name": 123}]},
        ),
        context=ctx,
    )
    assert resp.ok is False
    assert "name" in (resp.error or "") and "string" in (resp.error or "")


def test_cue_create_batch_rejects_invalid_position_type(loaded_actions):
    ctx = FakeCtx()
    resp = dispatch(
        Request(
            tool="ableton_arrangement", action="cue_create_batch",
            params={"cues": [{"position_beats": "16.0"}]},
        ),
        context=ctx,
    )
    assert resp.ok is False
    assert "must be a number" in (resp.error or "")


def test_cue_create_batch_propagates_per_cue_error(loaded_actions):
    """Once pre-validation passes, an in-loop failure (e.g. clash with
    an existing cue) surfaces with the cue_create error and the batch
    aborts — no half-completed state pretending to be success."""
    ctx = FakeCtx(FakeSong(cues=[FakeCue(32.0, "Existing")]))
    resp = dispatch(
        Request(
            tool="ableton_arrangement", action="cue_create_batch",
            params={"cues": [
                {"position_beats": 16.0, "name": "Verse"},
                {"position_beats": 32.0, "name": "Clash"},
            ]},
        ),
        context=ctx,
    )
    assert resp.ok is False
    assert "already exists" in (resp.error or "")
    # The first cue DID land before the second one failed — surfacing the
    # error mid-batch is better than silent rollback we can't actually do
    # against Live (the toggle is destructive).
    landed_names = sorted(c.name for c in ctx.song.cue_points)
    assert "Verse" in landed_names
    assert "Existing" in landed_names


# ---------- live_state_lock acquisition ----------


class _InstrumentedRLock:
    """Re-entrant lock that records every acquire / release event.

    Used to assert handlers actually take the lock — a regression where
    a future refactor forgets to `with context.live_state_lock:` would
    let the parallel-call race re-appear silently. The instrumentation
    pins the contract.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self.events: list[str] = []

    def __enter__(self):
        self._lock.acquire()
        self.events.append("acquire")
        return self

    def __exit__(self, *args):
        self.events.append("release")
        self._lock.release()
        return False


class _InstrumentedCtx(FakeCtx):
    """FakeCtx with an instrumented live_state_lock."""

    def __init__(self, song: FakeSong | None = None):
        super().__init__(song=song)
        self._live_state_lock = _InstrumentedRLock()


def test_cue_create_acquires_live_state_lock(loaded_actions):
    ctx = _InstrumentedCtx()
    dispatch(
        Request(
            tool="ableton_arrangement", action="cue_create",
            params={"position_beats": 16.0, "name": "Verse"},
        ),
        context=ctx,
    )
    assert ctx.live_state_lock.events == ["acquire", "release"]


def test_cue_create_batch_acquires_lock_once_for_whole_batch(loaded_actions):
    """A 3-cue batch should acquire+release the lock exactly once, not
    three times. That's the latency win over three separate cue_create
    calls — pay the lock+settle window once."""
    ctx = _InstrumentedCtx()
    ctx.song.last_event_time = 64.0
    dispatch(
        Request(
            tool="ableton_arrangement", action="cue_create_batch",
            params={"cues": [
                {"position_beats": 0.0},
                {"position_beats": 16.0},
                {"position_beats": 32.0},
            ]},
        ),
        context=ctx,
    )
    assert ctx.live_state_lock.events == ["acquire", "release"]


def test_cue_delete_acquires_live_state_lock(loaded_actions):
    """cue_delete's fallback path (seek + toggle) holds the lock so it
    serializes against concurrent cue_create / seek operations."""
    song = FakeSong(cues=[FakeCue(16.0, "Verse")])
    ctx = _InstrumentedCtx(song)
    dispatch(
        Request(
            tool="ableton_arrangement", action="cue_delete",
            params={"cue_index": 1},
        ),
        context=ctx,
    )
    # cue_delete's primary path uses per-cue `delete()` if exposed (no lock
    # needed); FakeCue here doesn't define it, so we hit the fallback.
    assert ctx.live_state_lock.events == ["acquire", "release"]


def test_cue_jump_by_direction_acquires_live_state_lock(loaded_actions):
    """cue_jump's direction path calls Live's jump_to_{next,prev}_cue
    which mutates current_song_time. Same B-21 race surface as
    cue_create/seek — handler must hold live_state_lock."""
    ctx = _InstrumentedCtx(
        FakeSong(cues=[FakeCue(16.0, "Verse"), FakeCue(32.0, "Chorus")])
    )
    dispatch(
        Request(
            tool="ableton_arrangement", action="cue_jump",
            params={"direction": "next"},
        ),
        context=ctx,
    )
    assert ctx.live_state_lock.events == ["acquire", "release"]


def test_cue_jump_by_name_acquires_live_state_lock(loaded_actions):
    """cue_jump's name path writes current_song_time directly (when the
    target CuePoint doesn't expose .jump()). Same lock requirement."""
    song = FakeSong(cues=[FakeCue(16.0, "Verse")])
    ctx = _InstrumentedCtx(song)
    dispatch(
        Request(
            tool="ableton_arrangement", action="cue_jump",
            params={"name": "Verse"},
        ),
        context=ctx,
    )
    assert ctx.live_state_lock.events == ["acquire", "release"]


# ---------- Parallel-call regression (B-21) ----------


def test_concurrent_cue_creates_all_land_at_requested_positions(
    loaded_actions, monkeypatch,
):
    """B-21 regression. Multiple worker threads calling cue_create in
    parallel must each produce a cue at its requested position, with no
    "previous handler's target" cross-contamination.

    The race exists because Live's audio thread picks up
    ``current_song_time`` writes on its own schedule (the handler sleeps
    to give it wall-clock time). Without serialization, thread A writes
    cst=X, sleeps, thread B writes cst=Y during A's sleep, A wakes and
    toggles at cst=Y. The live_state_lock makes the per-handler window
    atomic.

    The fake here mimics the audio-thread settle by reading
    ``current_song_time`` at toggle time (which under a real race would
    return another thread's value). Sleep is monkey-patched to a small
    value so the test stays under a second.
    """
    import hallucinote_mcp.handlers.arrangement as arr_module
    monkeypatch.setattr(arr_module, "_CUE_SETTLE_POLL_S", 0.005)

    song = FakeSong()
    song.last_event_time = 1000.0
    ctx = FakeCtx(song)

    positions = [16.0, 32.0, 48.0, 64.0, 80.0, 96.0, 112.0]
    errors: list[str] = []

    def worker(pos: float) -> None:
        resp = dispatch(
            Request(
                tool="ableton_arrangement", action="cue_create",
                params={"position_beats": pos, "name": f"Cue@{pos}"},
            ),
            context=ctx,
        )
        if not resp.ok:
            errors.append(f"pos={pos}: {resp.error}")

    threads = [
        threading.Thread(target=worker, args=(pos,)) for pos in positions
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10.0)

    assert not errors, f"worker errors: {errors}"
    # Every requested position has a cue, with the matching name.
    landed = {(c.time, c.name) for c in song.cue_points}
    expected = {(p, f"Cue@{p}") for p in positions}
    assert landed == expected, (
        f"missing cues — expected={expected}, got={landed}; "
        f"indicates the parallel-call race re-surfaced"
    )


def test_concurrent_cue_creates_restore_playhead_to_initial(
    loaded_actions, monkeypatch,
):
    """Each handler restores ``current_song_time`` to the value it
    observed on entry. With the lock, the LAST handler's restore is the
    one that wins (whichever ran last), and it should be the value that
    was current BEFORE that handler started — which under serialization
    equals the initial play position before any handler ran. (No handler
    sees an intermediate target because they're mutually exclusive.)
    """
    import hallucinote_mcp.handlers.arrangement as arr_module
    monkeypatch.setattr(arr_module, "_CUE_SETTLE_POLL_S", 0.005)

    song = FakeSong()
    song.last_event_time = 1000.0
    song.current_song_time = 4.0
    ctx = FakeCtx(song)

    def worker(pos: float) -> None:
        dispatch(
            Request(
                tool="ableton_arrangement", action="cue_create",
                params={"position_beats": pos},
            ),
            context=ctx,
        )

    threads = [
        threading.Thread(target=worker, args=(pos,))
        for pos in (16.0, 32.0, 48.0)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5.0)

    assert song.current_song_time == 4.0
