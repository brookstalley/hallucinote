"""Tests for ``handlers/_transport.py`` — locating Live's START PLAYING
POSITION, and proving where the transport actually rolled from.

The fake here is the whole point. ``FakeTransportSong`` keeps two fields where
the previous perform fakes kept one: ``_playhead`` (what ``current_song_time``
reads and writes) and ``_start_position`` (what ``start_playing()`` rolls
from). Only ``CuePoint.jump()`` moves the second. That is Live's actual shape,
and it is what makes these tests fail convincingly against a bare
``current_song_time`` write — the write lands, the read-back agrees, and
playback still begins somewhere else.
"""
from __future__ import annotations

import ast
import pathlib
import threading
from typing import Any

import pytest

from hallucinote_mcp.handlers import _transport
from hallucinote_mcp.handlers._transport import (
    LOCATE_EXISTING_CUE,
    LOCATE_PLAYHEAD_ONLY,
    LOCATE_TEMPORARY_CUE,
    PlayheadPositionError,
    locate_start_position,
    require_playhead_within,
)


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeCue:
    def __init__(self, song: "FakeTransportSong", time_: float, name: str = ""):
        self._song = song
        self.time = float(time_)
        self.name = name

    def jump(self) -> None:
        self._song.events.append(("cue_jump", round(self.time, 6)))
        # Live: "when not playing, simply move the start playing position".
        # The displayed playhead follows it.
        self._song._start_position = self.time
        self._song._playhead = self.time


class FakeTransportSong:
    """A Song whose playhead and start playing position are DIFFERENT fields.

    ``current_song_time`` reads and writes the playhead only. ``start_playing``
    rolls from the start position — which is how a perform pass came to record
    nothing while every read-back agreed it was in the right place.
    """

    def __init__(
        self,
        *,
        cues: "list[float] | None" = None,
        start_position: float = 0.0,
        last_event_time: float = 512.0,
        has_toggle: bool = True,
    ):
        self.events: list[tuple] = []
        self._playhead = 0.0
        self._start_position = float(start_position)
        self.last_event_time = float(last_event_time)
        self.is_playing = False
        self.beats_per_read = 0.0
        self.cue_points: list[Any] = [
            self._make_cue(t) for t in (cues or [])
        ]
        # A Live with no cue-toggle API. The handler probes by ``getattr(...,
        # None)``, so shadowing the method with None is exactly what absence
        # looks like from where it stands.
        if not has_toggle:
            self.set_or_delete_cue = None  # type: ignore[assignment]
        # A toggle Live accepts and silently does nothing with.
        self.toggle_is_noop = False

    def _make_cue(self, t: float) -> Any:
        return FakeCue(self, t)

    # -- transport ---------------------------------------------------
    @property
    def current_song_time(self) -> float:
        t = self._playhead
        if self.is_playing:
            self._playhead += self.beats_per_read
        return t

    @current_song_time.setter
    def current_song_time(self, v: float) -> None:
        self.events.append(("seek", float(v)))
        # Live clamps the playhead to the arrangement's extent.
        self._playhead = min(float(v), self.last_event_time)

    def start_playing(self) -> None:
        self.events.append(("play",))
        self._playhead = self._start_position
        self.is_playing = True

    def stop_playing(self) -> None:
        self.is_playing = False

    # -- cues --------------------------------------------------------
    def set_or_delete_cue(self) -> None:
        """Live's no-arg toggle: acts at the CURRENT playhead."""
        self.events.append(("toggle", round(self._playhead, 6)))
        if self.toggle_is_noop:
            return
        at = self._playhead
        for i, cue in enumerate(self.cue_points):
            if abs(cue.time - at) < 1e-6:
                del self.cue_points[i]
                return
        self.cue_points.append(self._make_cue(at))
        self.cue_points.sort(key=lambda c: c.time)


class FakeCueNoJump(FakeCue):
    """A cue on a Live that predates ``CuePoint.jump``."""

    jump = None  # type: ignore[assignment]


class FakeCtx:
    def __init__(self, song: FakeTransportSong):
        self._song = song
        self._lock = threading.RLock()
        self._depth = 0
        self.max_depth = 0

    @property
    def song(self) -> FakeTransportSong:
        return self._song

    @property
    def application(self) -> Any:
        return None

    @property
    def live_state_lock(self) -> threading.RLock:
        return self._lock

    def run_on_main(self, fn, **_kwargs):
        self._depth += 1
        self.max_depth = max(self.max_depth, self._depth)
        try:
            return fn()
        finally:
            self._depth -= 1


@pytest.fixture(autouse=True)
def _no_real_sleeping(monkeypatch):
    """The module's settle yields are correctness-bearing, not timing-bearing —
    every wait is between bouts. Strip the wall clock so the suite stays fast
    without changing a single ordering the code depends on."""
    monkeypatch.setattr(_transport.time, "sleep", lambda _s: None)


# ---------------------------------------------------------------------------
# The defect, stated as a test
# ---------------------------------------------------------------------------


def test_a_bare_seek_leaves_playback_starting_somewhere_else():
    """The failure this module exists to remove, with no fix applied.

    Seek to 8, read it back as 8 — an honest read — then play, and the
    transport rolls from 351. If this test ever goes green on its own, the
    fake has stopped modelling Live and every test below it is worthless.
    """
    song = FakeTransportSong(start_position=351.3)
    song.current_song_time = 8.0
    assert song.current_song_time == 8.0

    song.start_playing()

    assert song.current_song_time == 351.3


def test_locate_moves_the_start_position_so_playback_begins_there():
    song = FakeTransportSong(start_position=351.3)
    ctx = FakeCtx(song)

    result = locate_start_position(ctx, 8.0)

    assert result.start_position_moved
    song.start_playing()
    assert song.current_song_time == 8.0


# ---------------------------------------------------------------------------
# locate_start_position — the three paths
# ---------------------------------------------------------------------------


def test_an_existing_cue_is_jumped_never_toggled():
    """A toggle at a beat that already has a cue DELETES it. The operator's
    locators must survive a locate untouched."""
    song = FakeTransportSong(cues=[8.0, 64.0], start_position=351.3)
    ctx = FakeCtx(song)

    result = locate_start_position(ctx, 8.0)

    assert result.method == LOCATE_EXISTING_CUE
    assert [c.time for c in song.cue_points] == [8.0, 64.0]
    assert ("toggle", 8.0) not in song.events
    assert song._start_position == 8.0


def test_with_no_cue_one_is_borrowed_and_given_back():
    song = FakeTransportSong(cues=[64.0], start_position=351.3)
    ctx = FakeCtx(song)

    result = locate_start_position(ctx, 8.0)

    assert result.method == LOCATE_TEMPORARY_CUE
    assert result.start_position_moved
    assert song._start_position == 8.0
    # The set is left exactly as it was found.
    assert [c.time for c in song.cue_points] == [64.0]


def test_a_target_past_the_arrangement_is_refused_not_attempted():
    """Live clamps both the playhead and the toggle to ``last_event_time``. A
    toggle fired after a clamped seek lands at the WRONG beat — creating or
    deleting a cue nobody asked about — and playback can never start at the
    requested position anyway. Refuse, and say what to do about it."""
    song = FakeTransportSong(cues=[64.0], last_event_time=100.0)
    ctx = FakeCtx(song)

    with pytest.raises(ValueError, match="past the arrangement's extent"):
        locate_start_position(ctx, 200.0)

    assert [c.time for c in song.cue_points] == [64.0]
    assert ("seek", 200.0) not in song.events


def test_a_live_without_the_cue_toggle_degrades_and_names_the_reason():
    song = FakeTransportSong(has_toggle=False)
    ctx = FakeCtx(song)

    result = locate_start_position(ctx, 8.0)

    assert result.method == LOCATE_PLAYHEAD_ONLY
    assert "set_or_delete_cue" in (result.detail or "")
    # Degraded, but the playhead still went where it was asked.
    assert song._playhead == 8.0


def test_an_unjumpable_existing_cue_never_falls_through_to_the_toggle():
    """The destructive path: a cue is at the target but cannot be jumped. The
    borrow path's toggle fires at that same beat, so falling through would
    delete the operator's locator to work around a missing API."""
    song = FakeTransportSong(start_position=351.3)
    song.cue_points = [FakeCueNoJump(song, 8.0, name="drop")]
    ctx = FakeCtx(song)

    result = locate_start_position(ctx, 8.0)

    assert result.method == LOCATE_PLAYHEAD_ONLY
    assert "would delete that one" in (result.detail or "")
    assert [c.time for c in song.cue_points] == [8.0]


def test_a_toggle_that_creates_nothing_is_reported_not_assumed():
    song = FakeTransportSong()
    song.toggle_is_noop = True
    ctx = FakeCtx(song)

    result = locate_start_position(ctx, 8.0)

    assert result.method == LOCATE_PLAYHEAD_ONLY
    assert "no jumpable cue" in (result.detail or "")


def test_a_negative_target_is_refused():
    ctx = FakeCtx(FakeTransportSong())
    with pytest.raises(ValueError, match="must be >= 0"):
        locate_start_position(ctx, -1.0)


def test_a_playhead_that_never_settles_raises_with_all_three_numbers():
    class StuckSong(FakeTransportSong):
        @property
        def current_song_time(self) -> float:
            return 351.3

        @current_song_time.setter
        def current_song_time(self, v: float) -> None:
            self.events.append(("seek", float(v)))

    song = StuckSong(has_toggle=False)
    ctx = FakeCtx(song)

    with pytest.raises(TimeoutError) as excinfo:
        locate_start_position(ctx, 8.0, settle_timeout_s=0.0)

    message = str(excinfo.value)
    assert "beat 8" in message           # target
    assert "351.3" in message            # last observed
    assert "prior position 351.3" in message


def test_no_live_touch_ever_nests_a_main_thread_bout():
    """A nested ``run_on_main`` deadlocks in real Live. Every wait here must
    happen BETWEEN bouts, on the worker thread."""
    song = FakeTransportSong(start_position=351.3)
    ctx = FakeCtx(song)

    locate_start_position(ctx, 8.0)

    assert ctx.max_depth == 1


# ---------------------------------------------------------------------------
# require_playhead_within
# ---------------------------------------------------------------------------


def test_a_playhead_inside_the_window_is_accepted():
    require_playhead_within(
        9.5, low=8.0, high=24.0, target_beats=8.0, what="perform pass",
    )


def test_a_playhead_short_of_the_window_is_left_to_the_callers_own_budget():
    """A render deliberately starts before its capture window (the pre-roll),
    and a perform pass has a wall-clock ceiling that already answers "rolling,
    but from too far back". Neither wants this to raise."""
    require_playhead_within(
        4.0, low=8.0, high=24.0, target_beats=8.0, what="render capture",
    )


def test_a_playhead_past_the_window_raises_and_names_the_beat():
    """The #471 signature: a span at 8..24 and a transport at 351. It can
    never arrive, so there is nothing to wait for."""
    with pytest.raises(PlayheadPositionError) as excinfo:
        require_playhead_within(
            351.3, low=8.0, high=24.0, target_beats=8.0, what="perform pass",
        )

    err = excinfo.value
    assert err.observed_beats == pytest.approx(351.3)
    assert err.target_beats == 8.0
    assert "351.3" in str(err)
    assert "START PLAYING POSITION" in str(err)
    # The window the reader was owed, not half of it.
    assert "[8, 24]" in str(err)


def test_an_inverted_window_is_a_caller_bug_and_says_so():
    with pytest.raises(ValueError, match="is below low"):
        require_playhead_within(
            9.0, low=24.0, high=8.0, target_beats=8.0, what="perform pass",
        )


# ---------------------------------------------------------------------------
# The invariant, checked over the source rather than trusted
# ---------------------------------------------------------------------------


_HANDLERS_DIR = (
    pathlib.Path(__file__).resolve().parents[2]
    / "src" / "hallucinote_mcp" / "handlers"
)

# Handlers that press play WITHOUT positioning first, and why that is correct.
# Each is a bare transport verb the operator asked for by name — "press play
# where you are" — so there is no target beat to locate to. Anything that plays
# in order to reach a POSITION belongs on the other side of this line.
UNPOSITIONED_PLAY = {
    "play_handler": "Live's *Start* verb, invoked as-is; no target position",
    "continue_playing_handler": "Live's *Continue* verb; resumes, by design",
}


def _module_level_functions():
    for py_file in sorted(_HANDLERS_DIR.glob("*.py")):
        tree = ast.parse(py_file.read_text(encoding="utf-8"))
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                yield py_file.name, node


def _calls_method(node, name: str) -> bool:
    return any(
        isinstance(sub, ast.Call)
        and isinstance(sub.func, ast.Attribute)
        and sub.func.attr == name
        for sub in ast.walk(node)
    )


def _calls_function(node, name: str) -> bool:
    return any(
        isinstance(sub, ast.Call)
        and isinstance(sub.func, ast.Name)
        and sub.func.id == name
        for sub in ast.walk(node)
    )


def test_nothing_plays_toward_a_position_without_locating_the_start_position():
    """The defect was one line in one handler, and the same line was in three.

    A seek-then-play reads back perfectly and still begins somewhere else, so
    the mistake leaves no trace in the code that made it — which is why this is
    checked over the source instead of left to reviewers. Add a fourth site
    that plays toward a beat and this fails until it locates first, or until
    someone writes down why it does not have to.
    """
    offenders = []
    for filename, fn in _module_level_functions():
        if fn.name in UNPOSITIONED_PLAY:
            continue
        if not _calls_method(fn, "start_playing"):
            continue
        if not _calls_function(fn, "locate_start_position"):
            offenders.append(f"{filename}::{fn.name}")

    assert not offenders, (
        f"{offenders} call start_playing() without locate_start_position(). "
        "Writing current_song_time moves the playhead, not the START PLAYING "
        "POSITION that start_playing() rolls from, so the transport will "
        "begin wherever play was last pressed. Locate first — or, if this "
        "really is a bare transport verb with no target beat, add it to "
        "UNPOSITIONED_PLAY with the reason."
    )


def test_the_unpositioned_play_exemptions_still_exist():
    """A stale exemption silently re-opens the hole it was written to keep
    narrow."""
    present = {fn.name for _, fn in _module_level_functions()}
    stale = sorted(set(UNPOSITIONED_PLAY) - present)
    assert not stale, (
        f"UNPOSITIONED_PLAY names handler(s) that no longer exist: {stale}. "
        "Remove the entries."
    )


def test_a_cue_added_between_bouts_does_not_redirect_the_jump():
    """The survey and the jump are separate main-thread bouts, and Live's
    locator strip is clickable in between. Resolving by the surveyed INDEX
    would jump to whatever slid into that slot — the exact "transport in the
    wrong place" this module exists to end."""
    song = FakeTransportSong(cues=[8.0, 64.0], start_position=351.3)
    ctx = FakeCtx(song)
    real_run = ctx.run_on_main
    inserted = [False]

    def _run(fn, **kw):
        result = real_run(fn, **kw)
        if not inserted[0]:
            inserted[0] = True
            # A locator appears BEFORE the target, shifting every later index.
            song.cue_points.insert(0, FakeCue(song, 2.0))
        return result

    ctx.run_on_main = _run  # type: ignore[method-assign]

    result = locate_start_position(ctx, 8.0)

    assert result.method == LOCATE_EXISTING_CUE
    assert song._start_position == 8.0


def test_the_borrowed_cue_is_not_toggled_away_from_the_wrong_beat():
    """``set_or_delete_cue`` acts wherever the playhead is, so the give-back is
    only safe while the playhead is still ON the borrowed cue. A caller with a
    loose arrival tolerance accepts a playhead half a beat off — fine to play
    from, and NOT fine to toggle at, because the toggle would leave a stray
    locator there while the borrowed one stayed. Skip it and say so."""
    song = FakeTransportSong(start_position=351.3)
    ctx = FakeCtx(song)
    real_run = ctx.run_on_main

    def _run(fn, **kw):
        result = real_run(fn, **kw)
        # Live nudges the playhead a half-beat off once the jump has landed.
        if ("cue_jump", 8.0) in song.events and song._playhead == 8.0:
            song._playhead = 8.5
        return result

    ctx.run_on_main = _run  # type: ignore[method-assign]

    result = locate_start_position(ctx, 8.0, arrival_tolerance_beats=1.0)

    # The start position still moved — that is what the caller asked for.
    assert result.start_position_moved
    # And the set carries exactly one locator, the borrowed one, rather than a
    # stray at 8.5 alongside it.
    assert [c.time for c in song.cue_points] == [8.0]
    assert ("toggle", 8.5) not in song.events


def test_a_raise_mid_borrow_still_gives_the_cue_back():
    """Between the toggle and the give-back, a locator exists in the set that
    the operator did not make. `run_on_main` refuses outright when Live's main
    thread is busy, so that window is not a forward path — and a locator left
    behind by an unrelated-looking failure is the silent leak this module says
    must never happen."""
    song = FakeTransportSong(start_position=351.3)
    ctx = FakeCtx(song)
    real_run = ctx.run_on_main

    def _run(fn, **kw):
        # Fail the jump bout, once the borrowed cue exists.
        if song.cue_points and fn.__name__ == "_jump_to_cue_at_target":
            raise RuntimeError("Live's main thread is occupied")
        return real_run(fn, **kw)

    ctx.run_on_main = _run  # type: ignore[method-assign]

    with pytest.raises(RuntimeError, match="main thread is occupied"):
        locate_start_position(ctx, 8.0)

    assert song.cue_points == []


def test_a_raise_mid_borrow_is_the_error_that_propagates():
    """The give-back is best-effort cleanup. If IT fails too, the original
    failure is what the operator needs — a cleanup error replacing it would
    describe the tidying rather than the fault."""
    song = FakeTransportSong(start_position=351.3)
    ctx = FakeCtx(song)
    real_run = ctx.run_on_main

    def _run(fn, **kw):
        if song.cue_points:
            raise RuntimeError("Live's main thread is occupied")
        return real_run(fn, **kw)

    ctx.run_on_main = _run  # type: ignore[method-assign]

    with pytest.raises(RuntimeError, match="main thread is occupied"):
        locate_start_position(ctx, 8.0)

    # The cue could not be removed — but that is reported, not raised over the
    # cause, and the locator is named in the log rather than lost.
    assert [c.time for c in song.cue_points] == [8.0]

# The false claim this bundle removed had four copies across three surfaces —
# a handler note, a tool description, an action description and a guide — and
# fixing one is what let the other three survive a whole chunk. Anything an
# agent or operator READS is in scope.
_AGENT_FACING = (
    "handlers/session.py",
    "handlers/automation.py",
    "handlers/render.py",
    "actions/session.py",
    "actions/render.py",
    "resources/guides",
)

# Phrases that assert the disproved behaviour. Each is a claim that writing
# the playhead positions playback.
_DISPROVED_CLAIMS = (
    "locates-and-plays",
    "locates and plays",
    "seek then play locates",
)


def _agent_facing_files():
    pkg = _HANDLERS_DIR.parent
    for rel in _AGENT_FACING:
        target = pkg / rel
        if target.is_dir():
            yield from sorted(target.rglob("*.md"))
            yield from sorted(target.rglob("*.py"))
        elif target.is_file():
            yield target


def test_no_shipped_surface_still_promises_that_seeking_positions_playback():
    """`current_song_time` is the playhead; `start_playing()` rolls from the
    start playing position. Any surface that tells a reader otherwise teaches
    them to reproduce #471 — and does it at the moment they are debugging it,
    which is when they are most likely to believe it."""
    offenders = []
    for path in _agent_facing_files():
        text = path.read_text(encoding="utf-8", errors="ignore").lower()
        for claim in _DISPROVED_CLAIMS:
            if claim in text:
                offenders.append(f"{path.name}: {claim!r}")

    assert not offenders, (
        f"{offenders} still assert that a seek positions playback. Live rolls "
        "from its START PLAYING POSITION, which current_song_time does not "
        "move. Say what seek actually does, and point at "
        "start_position_moved."
    )
