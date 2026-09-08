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

import threading
from typing import Any

import pytest

from hallucinote_mcp.handlers import _transport
from hallucinote_mcp.handlers._transport import (
    LOCATE_EXISTING_CUE,
    LOCATE_PLAYHEAD_ONLY,
    LOCATE_TEMPORARY_CUE,
    PlayheadPositionError,
    assert_playhead_within,
    locate_start_position,
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


def test_a_caller_that_forbids_writing_to_the_set_gets_a_playhead_only_locate():
    song = FakeTransportSong()
    ctx = FakeCtx(song)

    result = locate_start_position(ctx, 8.0, allow_temporary_cue=False)

    assert result.method == LOCATE_PLAYHEAD_ONLY
    assert "forbids creating a temporary one" in (result.detail or "")
    assert song.cue_points == []


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
# assert_playhead_within
# ---------------------------------------------------------------------------


def test_a_playhead_inside_the_window_is_returned():
    song = FakeTransportSong()
    song._playhead = 9.5
    ctx = FakeCtx(song)

    assert assert_playhead_within(
        ctx, low=8.0, high=24.0, target_beats=8.0, what="perform pass",
    ) == 9.5


def test_a_playhead_past_the_window_fails_immediately_and_names_the_beat():
    """The #471 signature: a span at 8..24 and a transport at 351. It can
    never arrive, so waiting for it only delays the report."""
    song = FakeTransportSong()
    song._playhead = 351.3
    ctx = FakeCtx(song)

    with pytest.raises(PlayheadPositionError) as excinfo:
        assert_playhead_within(
            ctx, low=8.0, high=24.0, target_beats=8.0, what="perform pass",
            timeout_s=60.0,
        )

    err = excinfo.value
    assert err.observed_beats == pytest.approx(351.3)
    assert err.target_beats == 8.0
    assert "351.3" in str(err)
    assert "START PLAYING POSITION" in str(err)


def test_a_playhead_short_of_the_window_is_given_time_to_travel_in():
    """A render deliberately starts before its capture window (the pre-roll),
    so short-of-the-window is a wait, not a failure."""
    song = FakeTransportSong()
    song._playhead = 4.0
    song.is_playing = True
    song.beats_per_read = 1.0
    ctx = FakeCtx(song)

    landed = assert_playhead_within(
        ctx, low=8.0, high=24.0, target_beats=8.0, what="render capture",
        timeout_s=60.0,
    )

    assert 8.0 <= landed <= 24.0


def test_a_transport_that_never_reaches_the_window_times_out_with_the_beat():
    song = FakeTransportSong()
    song._playhead = 4.0
    ctx = FakeCtx(song)

    with pytest.raises(PlayheadPositionError) as excinfo:
        assert_playhead_within(
            ctx, low=8.0, high=24.0, target_beats=8.0, what="render capture",
            timeout_s=0.0,
        )

    assert excinfo.value.observed_beats == pytest.approx(4.0)
    assert "still short of the expected window" in str(excinfo.value)


def test_an_inverted_window_is_a_caller_bug_and_says_so():
    ctx = FakeCtx(FakeTransportSong())
    with pytest.raises(ValueError, match="is below low"):
        assert_playhead_within(
            ctx, low=24.0, high=8.0, target_beats=8.0, what="perform pass",
        )
