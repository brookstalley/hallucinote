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

    def run_on_main(self, fn, **_kwargs):
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
    """W3-F: the seek-and-wait helper now runs on the WORKER thread and
    marshals each Live touch through ``context.run_on_main``. The
    synchronous test fake's setter is immediately visible via its
    getter, so the helper returns on the first poll iteration.
    """
    from hallucinote_mcp.handlers.arrangement import _seek_and_wait_on_worker
    ctx = FakeCtx()
    ctx.song.current_song_time = 0.0
    _seek_and_wait_on_worker(ctx, 12.0)
    assert ctx.song.current_song_time == 12.0
    # Each poll is its own main-thread bout: at minimum the seek-write
    # + one mirror-read = 2 bouts. The synchronous fake returns the
    # target on the first read so we expect exactly 2.
    assert ctx.run_on_main_calls == 2


def test_seek_then_settle_times_out_when_audio_thread_stuck():
    """If the audio thread never picks up the write, the mirror stays
    at the old value forever. The helper must surface a TimeoutError
    with actionable text instead of hanging — and crucially, it must do
    so WITHOUT blocking Live's main thread, which is the W3-F fix's
    central architectural goal. (The fake's ``run_on_main`` is identity;
    in real Live the main thread is free to pump events between our
    worker-thread polls.)
    """
    from hallucinote_mcp.handlers.arrangement import _seek_and_wait_on_worker
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

    ctx = FakeCtx(song=_StuckSong())
    with pytest.raises(TimeoutError) as exc_info:
        _seek_and_wait_on_worker(
            ctx, 8.0, max_wait_s=0.15, poll_interval_s=0.05,
        )
    msg = str(exc_info.value)
    assert "did not settle" in msg
    assert "8" in msg  # mentions the target beat


def test_seek_then_settle_polls_via_run_on_main_until_mirror_settles():
    """W3-F architectural contract: when the mirror LAGS the setter
    (the real-Live failure mode that broke W2-F), the helper polls
    via MULTIPLE ``run_on_main`` bouts — NOT a single bout containing
    a sleep loop, which would deadlock Live's main thread against the
    very event it needs to pump.

    The lagged-mirror fake refreshes its visible getter only on the
    Nth read, simulating Live's audio-thread → mirror propagation
    that happens between main-thread bouts (each ``run_on_main`` call
    in real Live yields back to the event loop for one tick). The
    worker-thread loop must observe the eventual settle.
    """
    from hallucinote_mcp.handlers.arrangement import _seek_and_wait_on_worker

    class _LaggedMirror:
        """Setter accepted immediately; getter returns the stale value
        for the first ``lag_reads`` reads, then catches up.

        This faithfully simulates Live's main-thread mirror being
        refreshed only when the main thread pumps an event between
        polls (which only happens in the W3-F architecture, where
        polls are separate main-thread bouts)."""

        def __init__(self, lag_reads: int = 3):
            self._set_value = 0.0
            self._visible = 0.0
            self._reads_since_set = 0
            self._lag_reads = lag_reads

        @property
        def current_song_time(self) -> float:
            self._reads_since_set += 1
            if self._reads_since_set > self._lag_reads:
                self._visible = self._set_value
            return self._visible

        @current_song_time.setter
        def current_song_time(self, v: float) -> None:
            self._set_value = float(v)
            self._reads_since_set = 0

    ctx = FakeCtx(song=_LaggedMirror(lag_reads=3))
    _seek_and_wait_on_worker(ctx, 12.0, poll_interval_s=0.001)
    # The fake required 4 reads to settle: 3 lagged + 1 actual. Plus
    # one setter bout. So we expect 5 run_on_main bouts.
    assert ctx.run_on_main_calls == 5, (
        f"expected 5 main-thread bouts (1 setter + 4 polls), got "
        f"{ctx.run_on_main_calls}. Counting matters: if this drops to 1, "
        f"the helper has regressed to a single-bout sleep loop that would "
        f"deadlock real Live (the W2-F failure mode W3-F was designed to fix)."
    )
    # And the final visible value matches the target.
    assert ctx.song.current_song_time == 12.0


def test_cue_create_action_runs_on_worker_thread():
    """W3-F: cue_create / cue_create_batch / cue_delete are registered
    with ``runs_on_worker=True``. The dispatcher must invoke them
    DIRECTLY rather than wrapping in ``run_on_main``. This test pins the
    contract: if a future commit forgets the flag (or a refactor of the
    dispatcher silently re-wraps), the structural property is lost and
    we deadlock real Live again.
    """
    from hallucinote_mcp import schema

    with isolated_actions():
        cue_create = schema.get("ableton_arrangement", "cue_create")
        cue_batch = schema.get("ableton_arrangement", "cue_create_batch")
        cue_delete = schema.get("ableton_arrangement", "cue_delete")
        assert cue_create is not None and cue_create.runs_on_worker, (
            "cue_create must be registered with runs_on_worker=True (W3-F)"
        )
        assert cue_batch is not None and cue_batch.runs_on_worker, (
            "cue_create_batch must be registered with runs_on_worker=True (W3-F)"
        )
        assert cue_delete is not None and cue_delete.runs_on_worker, (
            "cue_delete must be registered with runs_on_worker=True (W3-F)"
        )
        # And the non-cue actions stay on the default (main-thread-wrapped)
        # path — opting in is per-action and conservative.
        cue_list = schema.get("ableton_arrangement", "cue_list")
        info = schema.get("ableton_arrangement", "info")
        assert cue_list is not None and not cue_list.runs_on_worker
        assert info is not None and not info.runs_on_worker


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


# ---------- cue_jump async-readback regression (real-Live finding 2026-05-18) ----------

# Live's ``jump_to_*_cue`` and ``CuePoint.jump()`` schedule the playhead
# move for the audio thread and return immediately. Reading
# ``current_song_time`` in the same main-thread bout sees the PRE-jump
# value (the main-thread mirror hasn't yet been refreshed by the audio
# thread). The pre-fix handler returned that stale value as
# ``position_beats``. These tests pin the post-fix contract: the
# returned ``position_beats`` is the actual destination (resolved
# before the jump fires), and the handler waits for the mirror to
# catch up before returning.


class _AsyncCue:
    """Cue whose ``jump()`` schedules the playhead move to land on a
    later read, not synchronously. Used to expose the real-Live async-
    readback race that the unit FakeSong's synchronous behavior hides."""

    def __init__(self, song: "_AsyncJumpSong", time: float, name: str = ""):
        self.time = time
        self.name = name
        self._song = song

    def jump(self) -> None:
        self._song._schedule_jump(self.time)


class _AsyncJumpSong:
    """FakeSong whose cue jumps are async: ``jump()`` and
    ``jump_to_*_cue()`` set a pending target, and the next read of
    ``current_song_time`` advances toward it. Mirrors Live's actual
    behavior where the audio thread propagates the position to the
    main-thread mirror with a one-tick delay."""

    def __init__(
        self,
        cues: list[tuple[float, str]],
        *,
        ticks_to_settle: int = 2,
    ):
        self.signature_numerator = 4
        self.signature_denominator = 4
        self.last_event_time = 256.0
        self.loop = False
        self.loop_start = 0.0
        self.loop_length = 4.0
        self._cst = 0.0
        self._pending: float | None = None
        self._ticks_remaining = 0
        self._ticks_to_settle = ticks_to_settle
        self.cue_points: list[_AsyncCue] = [
            _AsyncCue(self, t, n) for t, n in cues
        ]

    @property
    def current_song_time(self) -> float:
        # Each read advances the propagation by one tick; once
        # ``_ticks_to_settle`` reads have happened, the pending target
        # becomes visible.
        if self._pending is not None:
            self._ticks_remaining -= 1
            if self._ticks_remaining <= 0:
                self._cst = self._pending
                self._pending = None
        return self._cst

    @current_song_time.setter
    def current_song_time(self, value: float) -> None:
        # Direct writes (the fallback path when CuePoint.jump is absent)
        # are synchronous in real Live too — only the `jump_to_*_cue` /
        # `CuePoint.jump()` paths are async.
        self._cst = float(value)
        self._pending = None
        self._ticks_remaining = 0

    def _schedule_jump(self, target: float) -> None:
        self._pending = float(target)
        self._ticks_remaining = self._ticks_to_settle

    def jump_to_next_cue(self) -> None:
        # Real-Live boundary semantics (Live 12.4 empirically): no cue
        # past current → wrap to ``last_event_time`` (arrangement end).
        cur = self._cst
        candidates = sorted(c.time for c in self.cue_points if c.time > cur)
        if candidates:
            self._schedule_jump(candidates[0])
        elif self.last_event_time > cur:
            self._schedule_jump(self.last_event_time)

    def jump_to_prev_cue(self) -> None:
        # Real-Live boundary semantics: no cue before current → wrap to
        # 0.0 (arrangement start).
        cur = self._cst
        candidates = sorted(
            (c.time for c in self.cue_points if c.time < cur), reverse=True,
        )
        if candidates:
            self._schedule_jump(candidates[0])
        elif cur > 0.0:
            self._schedule_jump(0.0)


def test_cue_jump_by_name_returns_destination_not_stale_readback(loaded_actions):
    """Real-Live 2026-05-18: ``CuePoint.jump()`` is async and
    ``current_song_time`` reads return the pre-jump value in the same
    main-thread bout. Pre-fix handler returned that stale value as
    ``position_beats``. Post-fix handler pre-resolves the target and
    polls the mirror until it settles, so ``position_beats`` is always
    the actual destination."""
    song = _AsyncJumpSong(cues=[(8.0, "Intro"), (16.0, "Verse"), (32.0, "Chorus")])
    ctx = FakeCtx(song=song)  # type: ignore[arg-type]
    resp = dispatch(
        Request(
            tool="ableton_arrangement", action="cue_jump",
            params={"name": "Verse"},
        ),
        context=ctx,
    )
    assert resp.ok, resp.error
    # Pre-fix this came back as 0.0 (the pre-jump current_song_time).
    # Post-fix it must report the actual destination.
    assert resp.result["position_beats"] == 16.0
    # And by the time the handler returned, the mirror should have
    # caught up (the settle loop blocked until propagation).
    assert song._cst == 16.0


def test_cue_jump_by_direction_returns_destination_not_stale_readback(loaded_actions):
    """Same race as the name path, but ``jump_to_next_cue`` rather than
    ``CuePoint.jump()``. Post-fix handler resolves the target from the
    sorted cue list before firing the jump, then settles on the worker
    thread."""
    song = _AsyncJumpSong(cues=[(8.0, "Intro"), (16.0, "Verse"), (32.0, "Chorus")])
    ctx = FakeCtx(song=song)  # type: ignore[arg-type]
    resp = dispatch(
        Request(
            tool="ableton_arrangement", action="cue_jump",
            params={"direction": "next"},
        ),
        context=ctx,
    )
    assert resp.ok, resp.error
    assert resp.result["position_beats"] == 8.0
    assert song._cst == 8.0


def test_cue_jump_by_direction_at_next_boundary_wraps_to_last_event_time(loaded_actions):
    """Real-Live 2026-05-18 (Live 12.4): ``jump_to_next_cue`` from
    past the latest cue wraps to ``last_event_time`` (arrangement
    end). Handler's pre-resolution must include the implicit
    end-boundary cue so the settle waits for the actual destination
    rather than mis-classifying the move as a no-op."""
    song = _AsyncJumpSong(cues=[(8.0, "Intro"), (16.0, "Verse")])
    song.last_event_time = 24.0
    song._cst = 20.0  # past the last cue
    ctx = FakeCtx(song=song)  # type: ignore[arg-type]
    resp = dispatch(
        Request(
            tool="ableton_arrangement", action="cue_jump",
            params={"direction": "next"},
        ),
        context=ctx,
    )
    assert resp.ok, resp.error
    assert resp.result["position_beats"] == 24.0
    assert song._cst == 24.0


def test_cue_jump_by_direction_at_prev_boundary_wraps_to_zero(loaded_actions):
    """Real-Live 2026-05-18 (Live 12.4): ``jump_to_prev_cue`` from
    before any cue wraps to 0.0 (arrangement start). Handler's
    pre-resolution must include the implicit start-boundary cue."""
    song = _AsyncJumpSong(cues=[(8.0, "Intro"), (16.0, "Verse")])
    song._cst = 8.0  # at the earliest cue — "previous" jumps to start
    ctx = FakeCtx(song=song)  # type: ignore[arg-type]
    resp = dispatch(
        Request(
            tool="ableton_arrangement", action="cue_jump",
            params={"direction": "previous"},
        ),
        context=ctx,
    )
    assert resp.ok, resp.error
    assert resp.result["position_beats"] == 0.0
    assert song._cst == 0.0


def test_cue_jump_true_noop_at_song_start(loaded_actions):
    """``jump_to_prev_cue`` from 0.0 is a true no-op (already at the
    implicit start-boundary cue). Handler must NOT timeout waiting
    for a settle that won't happen — pre-resolution returns None and
    the fallback reads back the current (unchanged) position."""
    song = _AsyncJumpSong(cues=[(8.0, "Intro"), (16.0, "Verse")])
    song._cst = 0.0  # already at start
    ctx = FakeCtx(song=song)  # type: ignore[arg-type]
    resp = dispatch(
        Request(
            tool="ableton_arrangement", action="cue_jump",
            params={"direction": "previous"},
        ),
        context=ctx,
    )
    assert resp.ok, resp.error
    assert resp.result["position_beats"] == 0.0
    assert song._cst == 0.0


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


def test_cue_create_batch_atomic_on_out_of_range_position(loaded_actions):
    """W5-C: a single position past last_event_time aborts the WHOLE
    batch — no cues persist. Without this, the W4-E real-Live smoke
    saw earlier cues persist while a later out-of-range cue raised."""
    ctx = FakeCtx()
    ctx.song.last_event_time = 32.0
    resp = dispatch(
        Request(
            tool="ableton_arrangement", action="cue_create_batch",
            params={"cues": [
                {"position_beats": 0.0, "name": "Intro"},
                {"position_beats": 16.0, "name": "Verse"},
                {"position_beats": 48.0, "name": "Past End"},
            ]},
        ),
        context=ctx,
    )
    assert resp.ok is False
    assert "last_event_time" in (resp.error or "")
    assert "48.0" in (resp.error or "")
    assert "No cues written" in (resp.error or "")
    # ATOMIC: the prior two in-range cues are NOT in Live's state.
    assert len(ctx.song.cue_points) == 0


def test_cue_create_batch_atomic_reports_all_out_of_range(loaded_actions):
    """When multiple positions are out of range, the error names every
    offending position so the user fixes them all in one round trip."""
    ctx = FakeCtx()
    ctx.song.last_event_time = 16.0
    resp = dispatch(
        Request(
            tool="ableton_arrangement", action="cue_create_batch",
            params={"cues": [
                {"position_beats": 8.0, "name": "OK"},
                {"position_beats": 24.0, "name": "Bad1"},
                {"position_beats": 32.0, "name": "Bad2"},
            ]},
        ),
        context=ctx,
    )
    assert resp.ok is False
    assert "24.0" in (resp.error or "")
    assert "32.0" in (resp.error or "")
    assert "2 cue(s)" in (resp.error or "")
    assert len(ctx.song.cue_points) == 0


def test_cue_create_batch_atomic_all_in_range_succeeds(loaded_actions):
    """Sanity check: with all positions inside last_event_time, the
    atomic precondition passes silently and the batch writes."""
    ctx = FakeCtx()
    ctx.song.last_event_time = 64.0
    resp = dispatch(
        Request(
            tool="ableton_arrangement", action="cue_create_batch",
            params={"cues": [
                {"position_beats": 0.0, "name": "A"},
                {"position_beats": 32.0, "name": "B"},
                {"position_beats": 64.0, "name": "C"},
            ]},
        ),
        context=ctx,
    )
    assert resp.ok is True, f"unexpected error: {resp.error!r}"
    assert resp.result["cue_count"] == 3
    assert len(ctx.song.cue_points) == 3


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
    aborts — no half-completed state pretending to be success.

    Uses ``if_exists='refuse'`` (legacy semantics) explicitly because
    the default flipped to ``'skip'`` in R-1.1.
    """
    ctx = FakeCtx(FakeSong(cues=[FakeCue(32.0, "Existing")]))
    resp = dispatch(
        Request(
            tool="ableton_arrangement", action="cue_create_batch",
            params={"cues": [
                {"position_beats": 16.0, "name": "Verse"},
                {"position_beats": 32.0, "name": "Clash"},
            ], "if_exists": "refuse"},
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


# ---------- R-1.1: cue if_exists semantics ----------


def test_cue_create_if_exists_skip_no_ops_when_name_matches(loaded_actions):
    """Idempotent re-push of the same cue is a no-op when names agree.

    The result carries ``skipped=True`` so the caller can distinguish
    "created" from "matched the existing cue." Live's cue_points list
    is unchanged.
    """
    ctx = FakeCtx(FakeSong(cues=[FakeCue(16.0, "Verse")]))
    resp = dispatch(
        Request(
            tool="ableton_arrangement", action="cue_create",
            params={
                "position_beats": 16.0, "name": "Verse",
                "if_exists": "skip",
            },
        ),
        context=ctx,
    )
    assert resp.ok is True, f"unexpected error: {resp.error!r}"
    assert resp.result["skipped"] is True
    assert resp.result["name"] == "Verse"
    assert resp.result["cue_index"] == 1
    # Nothing actually toggled — the existing cue is preserved without
    # any seek/toggle round-trip.
    assert len(ctx.song.cue_points) == 1
    assert ctx.song.set_or_delete_cue_calls == []


def test_cue_create_if_exists_skip_treats_missing_name_as_match(loaded_actions):
    """name=None means "I don't care about the name" — a same-position
    existing cue (of any name) is a match for skip purposes."""
    ctx = FakeCtx(FakeSong(cues=[FakeCue(16.0, "Verse")]))
    resp = dispatch(
        Request(
            tool="ableton_arrangement", action="cue_create",
            params={"position_beats": 16.0, "if_exists": "skip"},
        ),
        context=ctx,
    )
    assert resp.ok is True
    assert resp.result["skipped"] is True
    assert resp.result["name"] == "Verse"
    assert ctx.song.set_or_delete_cue_calls == []


def test_cue_create_if_exists_skip_raises_on_name_mismatch(loaded_actions):
    """A same-position cue with a DIFFERENT name signals real authoring
    drift (the user renamed in Live, or the DB now wants a different
    name there). ``if_exists='skip'`` does NOT silently rename — it
    raises so the caller resolves the discrepancy explicitly."""
    ctx = FakeCtx(FakeSong(cues=[FakeCue(16.0, "Verse")]))
    resp = dispatch(
        Request(
            tool="ableton_arrangement", action="cue_create",
            params={
                "position_beats": 16.0, "name": "Chorus",
                "if_exists": "skip",
            },
        ),
        context=ctx,
    )
    assert resp.ok is False
    err = resp.error or ""
    assert "already exists" in err
    assert "'Verse'" in err and "'Chorus'" in err
    # Existing cue is preserved, no rename happened.
    assert ctx.song.cue_points[0].name == "Verse"


def test_cue_create_if_exists_refuse_is_default(loaded_actions):
    """Single-cue ``cue_create`` defaults to ``if_exists='refuse'`` so
    one-shot callers see collisions instead of silent no-ops. Matches
    pre-R-1.1 behavior — the test_cue_create_refuses_to_clobber_*
    test above already pins this; this is the explicit parameter form.
    """
    ctx = FakeCtx(FakeSong(cues=[FakeCue(16.0, "Verse")]))
    resp = dispatch(
        Request(
            tool="ableton_arrangement", action="cue_create",
            params={"position_beats": 16.0, "name": "Verse"},
        ),
        context=ctx,
    )
    assert resp.ok is False
    assert "already exists" in (resp.error or "")


def test_cue_create_batch_default_if_exists_skip_makes_repush_idempotent(loaded_actions):
    """Replaying the same batch is a no-op — the planner can re-push
    after a tweak to other phases without manually deleting every cue
    in Live first.

    The batch's default is ``'skip'`` (the planner path); this test
    pins that default without passing the param explicitly.
    """
    ctx = FakeCtx(FakeSong(cues=[
        FakeCue(0.0, "Intro"),
        FakeCue(16.0, "Verse"),
        FakeCue(48.0, "Chorus"),
    ]))
    ctx.song.last_event_time = 64.0
    resp = dispatch(
        Request(
            tool="ableton_arrangement", action="cue_create_batch",
            params={"cues": [
                {"position_beats": 0.0, "name": "Intro"},
                {"position_beats": 16.0, "name": "Verse"},
                {"position_beats": 48.0, "name": "Chorus"},
            ]},
        ),
        context=ctx,
    )
    assert resp.ok is True, f"unexpected error: {resp.error!r}"
    assert resp.result["cue_count"] == 3
    assert all(c["skipped"] is True for c in resp.result["cues"])
    # No toggles fired — every cue was the existing one.
    assert ctx.song.set_or_delete_cue_calls == []
    # Live's cue list unchanged.
    assert [(c.time, c.name) for c in ctx.song.cue_points] == [
        (0.0, "Intro"), (16.0, "Verse"), (48.0, "Chorus"),
    ]


def test_cue_create_batch_skip_mixes_creates_and_skips(loaded_actions):
    """A batch with some cues already present + some new produces a
    mix of created and skipped per-cue results in submission order.
    """
    ctx = FakeCtx(FakeSong(cues=[FakeCue(16.0, "Verse")]))
    ctx.song.last_event_time = 64.0
    resp = dispatch(
        Request(
            tool="ableton_arrangement", action="cue_create_batch",
            params={"cues": [
                {"position_beats": 0.0, "name": "Intro"},      # new
                {"position_beats": 16.0, "name": "Verse"},     # skip
                {"position_beats": 32.0, "name": "Chorus"},    # new
            ]},
        ),
        context=ctx,
    )
    assert resp.ok is True
    per_cue = resp.result["cues"]
    assert per_cue[0].get("skipped") is not True
    assert per_cue[1]["skipped"] is True
    assert per_cue[2].get("skipped") is not True
    landed = {(c.time, c.name) for c in ctx.song.cue_points}
    assert landed == {(0.0, "Intro"), (16.0, "Verse"), (32.0, "Chorus")}


def test_cue_create_rejects_unknown_if_exists_value(loaded_actions):
    """The enum is pinned to {'refuse', 'skip'}. The dispatcher's
    ParamSpec.enum check rejects anything else with a teaching error
    before the handler runs."""
    ctx = FakeCtx()
    resp = dispatch(
        Request(
            tool="ableton_arrangement", action="cue_create",
            params={"position_beats": 16.0, "if_exists": "replace"},
        ),
        context=ctx,
    )
    assert resp.ok is False
    err = (resp.error or "").lower()
    # Either the dispatcher's enum guard or the handler's whitelist
    # fires; both forms surface the rejected value.
    assert "if_exists" in resp.error or "replace" in err


# ---------- SYN-6B4Q: cue_create_batch on_out_of_range ----------


def test_cue_create_batch_default_on_out_of_range_is_refuse_atomic(loaded_actions):
    """SYN-6B4Q: omitting ``on_out_of_range`` preserves the W5-C atomic
    contract — a single position past ``last_event_time`` aborts the whole
    batch and writes nothing. Direct/strict callers are unaffected by the
    new skip mode; only the planner opts into ``'skip'``."""
    ctx = FakeCtx()
    ctx.song.last_event_time = 32.0
    resp = dispatch(
        Request(
            tool="ableton_arrangement", action="cue_create_batch",
            params={"cues": [
                {"position_beats": 0.0, "name": "Intro"},
                {"position_beats": 48.0, "name": "Past End"},
            ]},
        ),
        context=ctx,
    )
    assert resp.ok is False
    assert "No cues written" in (resp.error or "")
    assert len(ctx.song.cue_points) == 0
    # The result shape must NOT grow skipped_out_of_range in refuse mode.
    assert resp.result is None or "skipped_out_of_range" not in (resp.result or {})


def test_cue_create_batch_skip_creates_in_range_defers_out_of_range(loaded_actions):
    """SYN-6B4Q: ``on_out_of_range='skip'`` creates the cues within
    ``last_event_time`` and returns the rest in ``skipped_out_of_range``
    rather than failing the batch. The push then continues (exit 0); the
    deferred cues land on the next push once arrangement content covers
    them."""
    ctx = FakeCtx()
    ctx.song.last_event_time = 32.0
    resp = dispatch(
        Request(
            tool="ableton_arrangement", action="cue_create_batch",
            params={
                "cues": [
                    {"position_beats": 0.0, "name": "Intro"},
                    {"position_beats": 16.0, "name": "Verse"},
                    {"position_beats": 48.0, "name": "Chorus"},  # past extent
                    {"position_beats": 64.0, "name": "Outro"},   # past extent
                ],
                "on_out_of_range": "skip",
            },
        ),
        context=ctx,
    )
    assert resp.ok is True, f"unexpected error: {resp.error!r}"
    # Only the two in-extent cues were created.
    assert resp.result["cue_count"] == 2
    landed = {(c.time, c.name) for c in ctx.song.cue_points}
    assert landed == {(0.0, "Intro"), (16.0, "Verse")}
    # The two past-extent cues are reported as deferred, not silently dropped.
    skipped = resp.result["skipped_out_of_range"]
    assert {(s["position_beats"], s["name"]) for s in skipped} == {
        (48.0, "Chorus"), (64.0, "Outro"),
    }
    # The result carries last_event_time so the caller can teach the gap.
    assert resp.result["last_event_time"] == 32.0


def test_cue_create_batch_skip_all_out_of_range_creates_nothing(loaded_actions):
    """SYN-6B4Q skeleton case: an empty arrangement (last_event_time=0)
    with authored cues defers EVERY cue — cue_count=0, all reported in
    skipped_out_of_range, and the call still succeeds (no PARTIAL)."""
    ctx = FakeCtx()
    ctx.song.last_event_time = 0.0
    resp = dispatch(
        Request(
            tool="ableton_arrangement", action="cue_create_batch",
            params={
                "cues": [
                    {"position_beats": 16.0, "name": "Verse"},
                    {"position_beats": 48.0, "name": "Chorus"},
                ],
                "on_out_of_range": "skip",
            },
        ),
        context=ctx,
    )
    assert resp.ok is True, f"unexpected error: {resp.error!r}"
    assert resp.result["cue_count"] == 0
    assert resp.result["cues"] == []
    assert len(ctx.song.cue_points) == 0
    assert len(resp.result["skipped_out_of_range"]) == 2


def test_cue_create_batch_skip_all_in_range_reports_empty_deferred(loaded_actions):
    """SYN-6B4Q: skip mode with every cue inside the extent behaves exactly
    like a normal create — nothing deferred, skipped_out_of_range empty."""
    ctx = FakeCtx()
    ctx.song.last_event_time = 64.0
    resp = dispatch(
        Request(
            tool="ableton_arrangement", action="cue_create_batch",
            params={
                "cues": [
                    {"position_beats": 0.0, "name": "A"},
                    {"position_beats": 32.0, "name": "B"},
                ],
                "on_out_of_range": "skip",
            },
        ),
        context=ctx,
    )
    assert resp.ok is True
    assert resp.result["cue_count"] == 2
    assert resp.result["skipped_out_of_range"] == []


def test_cue_create_batch_rejects_unknown_on_out_of_range_value(loaded_actions):
    """The enum is pinned to {'refuse', 'skip'}; anything else is rejected
    before the handler runs."""
    ctx = FakeCtx()
    resp = dispatch(
        Request(
            tool="ableton_arrangement", action="cue_create_batch",
            params={
                "cues": [{"position_beats": 0.0}],
                "on_out_of_range": "clamp",
            },
        ),
        context=ctx,
    )
    assert resp.ok is False
    err = (resp.error or "").lower()
    assert "on_out_of_range" in (resp.error or "") or "clamp" in err


def test_cue_create_batch_rejects_unknown_if_exists_value(loaded_actions):
    """Same enum guard at the batch entry."""
    ctx = FakeCtx()
    ctx.song.last_event_time = 64.0
    resp = dispatch(
        Request(
            tool="ableton_arrangement", action="cue_create_batch",
            params={
                "cues": [{"position_beats": 0.0}],
                "if_exists": "replace",
            },
        ),
        context=ctx,
    )
    assert resp.ok is False
    err = (resp.error or "").lower()
    assert "if_exists" in resp.error or "replace" in err


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
