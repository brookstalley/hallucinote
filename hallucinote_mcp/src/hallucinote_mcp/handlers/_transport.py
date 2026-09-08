"""Transport POSITIONING primitives, shared by every handler that positions
Live and then presses play.

Why this module exists
----------------------

``song.current_song_time`` is the PLAYHEAD. Live keeps a second, separate
**start playing position**, and that — not the playhead — is where
``start_playing()`` and ``continue_playing()`` begin from. Writing
``current_song_time`` does not move it.

The two agree often enough to hide the difference: on a set nobody has
listened to, the start position sits at 0 and a locate to 0 "works". They part
company the moment a human presses play anywhere in the arrangement. After
that, a handler can seek to beat 8, read ``current_song_time`` back as 8.0 —
an honest read, the locate really did land — call ``start_playing()``, and
have the transport roll from beat 351.

That is not a hypothetical. It is the mechanism behind a perform pass that
recorded nothing across three sessions in one day while reporting success at
every step: the ramp loop's first tick read a beat already past the span's
end, closed every gesture, and returned a clean result. The playhead settle
this module's callers already had was never wrong — it was answering a
question about the wrong property.

So: never position Live for playback by writing ``current_song_time`` alone.
Use :func:`locate_start_position`, and prove where the transport ACTUALLY
started with :func:`assert_playhead_within`. The second is the one that holds
when the first is defeated by something nobody has seen yet — it reads the
realized position instead of trusting any mechanism, which is why it is worth
having even where the locate is believed to work.

Moving the start position
-------------------------

The LOM exposes no writable start-position property. The one surface that
moves it is ``CuePoint.jump()``, whose own docstring is explicit: *"When the
Song is playing, set the playing-position quantized to this Cuepoint's time.
When not playing, simply move the start playing position."* So a locate is a
jump to a cue at the target beat — using the operator's cue when one is
already there, and otherwise borrowing one: create, jump, delete.

Threading
---------

Every function here MUST be called on the WORKER (TCP-listener) thread. Each
Live touch is its own ``context.run_on_main`` bout and every wall-clock wait
happens between bouts, so Live's main thread stays free to pump the
audio-thread → mirror propagation these settles are waiting for. A
main-thread caller starves the very event pump it polls (the W3-F lesson in
``handlers/arrangement.py``) and a nested bout deadlocks.

``context.live_state_lock`` is acquired here, around the whole
seek/settle/toggle window. It is re-entrant, so a caller that already holds it
(``perform_batch``, ``seek``) nests without deadlocking.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

from ..dispatcher import LiveContext


logger = logging.getLogger(__name__)


# Settle budget for one positioning operation. Matches the cue handlers'
# ``_CUE_SETTLE_TIMEOUT_S``: the propagation being waited on is the same
# audio-thread → main-thread mirror refresh, so the same wall-clock covers it.
_LOCATE_SETTLE_TIMEOUT_S = 3.0
_LOCATE_POLL_S = 0.05

# The playhead has ARRIVED when it reads within this of the target. Live
# quantizes a locate, so this is a quantization tolerance (~1 ms in beats),
# not a slop allowance — same value the cue handlers settle against.
_LOCATE_TOLERANCE_BEATS = 0.001

# Two cue times are the same cue when they agree to this. Cue times come back
# as floats Live computed; an exact == would miss the operator's own locator
# and toggle a duplicate on top of it.
_CUE_MATCH_EPSILON_BEATS = 1e-6

# How long :func:`assert_playhead_within` gives a transport that is SHORT of
# its window to travel into it (a render's pre-roll is the ordinary case).
# A playhead PAST the window fails immediately regardless — see the function.
_PLAYHEAD_ARRIVAL_TIMEOUT_S = 2.0
_PLAYHEAD_POLL_S = 0.05


#: The start playing position really was moved.
LOCATE_EXISTING_CUE = "existing_cue"
LOCATE_TEMPORARY_CUE = "temporary_cue"
#: The playhead was moved but the start position was NOT — degraded, and the
#: caller must treat a pass positioned this way as unverified until
#: :func:`assert_playhead_within` says otherwise.
LOCATE_PLAYHEAD_ONLY = "playhead_only"

_START_POSITION_METHODS = frozenset({LOCATE_EXISTING_CUE, LOCATE_TEMPORARY_CUE})


@dataclass(frozen=True)
class LocateResult:
    """What :func:`locate_start_position` actually managed to do.

    ``start_position_moved`` is the field callers branch on. It is False for
    :data:`LOCATE_PLAYHEAD_ONLY`, which is a DEGRADED success: the playhead is
    at the target and playback may well begin there, but nothing proved it
    will. ``detail`` then names why the strong path was unavailable, so the
    reason reaches the operator instead of dying in a log line.
    """

    target_beats: float
    settled_beats: float
    method: str
    detail: str | None = None

    @property
    def start_position_moved(self) -> bool:
        return self.method in _START_POSITION_METHODS


class PlayheadPositionError(RuntimeError):
    """The transport is rolling from somewhere it was not sent.

    Carries the numbers a reader needs to act — where it was asked to start,
    where it actually is, and the window that was expected — because a bare
    "wrong position" is exactly the message that sent an operator looking at
    punch-in and clip envelopes for six hours.
    """

    def __init__(
        self,
        message: str,
        *,
        target_beats: float,
        observed_beats: float,
        low: float,
        high: float,
    ) -> None:
        super().__init__(message)
        self.target_beats = target_beats
        self.observed_beats = observed_beats
        self.low = low
        self.high = high


def _read_song_time(context: LiveContext) -> float:
    return context.run_on_main(
        lambda: float(getattr(context.song, "current_song_time", 0.0))
    )


def _wait_for_playhead(
    context: LiveContext,
    target_beats: float,
    *,
    timeout_s: float,
    tolerance_beats: float = _LOCATE_TOLERANCE_BEATS,
    poll_s: float = _LOCATE_POLL_S,
    prior_beats: float | None = None,
) -> float:
    """Poll the playhead on the worker thread until it reads ``target_beats``.

    Returns the beat finally observed; raises ``TimeoutError`` naming target,
    last observed and prior position — the three numbers without which a
    transport race is invisible from a log.
    """
    deadline = time.monotonic() + timeout_s
    prior_text = "unknown" if prior_beats is None else f"{prior_beats:.3f}"
    observed = _read_song_time(context)
    while abs(observed - target_beats) > tolerance_beats:
        if time.monotonic() >= deadline:
            raise TimeoutError(
                f"could not locate the playhead to beat {target_beats:g} "
                f"within {timeout_s:.1f}s — it still reads {observed:.3f} "
                f"({abs(observed - target_beats):.3f} beats away; prior "
                f"position {prior_text}). "
                "Live applies a locate asynchronously through the audio "
                "thread; it may be busy or showing a modal dialog. Retry, or "
                "raise the settle timeout."
            )
        time.sleep(poll_s)
        observed = _read_song_time(context)
    return observed


def _cue_toggle(song: Any) -> Any | None:
    """Live's no-arg cue toggle, under either of the two names it has shipped
    under. Returns None when this Live exposes neither."""
    return getattr(song, "set_or_delete_cue", None) or getattr(
        song, "set_or_delete_cue_point", None,
    )


def _jump_cue_at(song: Any, target_beats: float) -> bool:
    """Jump to the cue sitting at ``target_beats``. False when there is none,
    or when this Live's ``CuePoint`` has no ``jump``.

    Resolves the cue inside the caller's main-thread bout every time. Live
    re-wraps API objects on every property access, so a cue object held across
    bouts is a different Python object next time — and an INDEX held across
    bouts can point at a different cue entirely once one is added or removed.
    """
    index = _cue_index_at(song, target_beats)
    if index is None:
        return False
    cues = list(getattr(song, "cue_points", ()))
    if index >= len(cues):  # pragma: no cover - resolved in the same bout
        return False
    jumper = getattr(cues[index], "jump", None)
    if jumper is None:
        return False
    jumper()
    return True


def _cue_index_at(song: Any, target_beats: float) -> int | None:
    """Index into ``song.cue_points`` of a cue sitting at ``target_beats``.

    Returns an INDEX, never the cue object: Live re-wraps API objects on every
    property access, so a cue held across bouts is a different Python object
    next time and identity comparisons against it are meaningless.
    """
    for i, cue in enumerate(getattr(song, "cue_points", ())):
        if abs(float(getattr(cue, "time", -1.0)) - target_beats) < _CUE_MATCH_EPSILON_BEATS:
            return i
    return None


def locate_start_position(
    context: LiveContext,
    target_beats: float,
    *,
    settle_timeout_s: float = _LOCATE_SETTLE_TIMEOUT_S,
    arrival_tolerance_beats: float = _LOCATE_TOLERANCE_BEATS,
    allow_temporary_cue: bool = True,
) -> LocateResult:
    """Move Live's START PLAYING POSITION to ``target_beats`` and settle.

    Three paths, strongest first:

    1. A cue already sits at the target — jump to it. Costs nothing and
       touches nothing the operator owns.
    2. No cue there — seek, toggle one into existence, jump to it, toggle it
       away. Two Undo entries; the operator's cue list is left as it was, and
       a temporary cue that survives is reported rather than swallowed.
    3. Neither is possible — seek the playhead and say so
       (:data:`LOCATE_PLAYHEAD_ONLY`). The caller is responsible for treating
       what follows as unproven; :func:`assert_playhead_within` is how it
       finds out.

    ``allow_temporary_cue=False`` skips path 2 for a caller that must not
    write to the set at all.

    ``arrival_tolerance_beats`` is how close the playhead must read to count as
    ARRIVED. It defaults to a quantization epsilon, which is what a caller that
    then acts at the position needs. A caller that only needs the transport
    roughly there — a perform pass interpolates its ramp off the ACTUAL playhead
    beat, so a fraction off is self-correcting — should widen it, because Live
    does not promise to park on the exact float it was handed. Borrowing a cue
    still requires the tight epsilon regardless: the toggle fires at wherever
    the playhead really is, so an imprecise position would place the locator at
    the wrong beat. That case degrades instead.

    Raises ``TimeoutError`` if the playhead never settles — a locate that
    never lands is a failure whichever property was being aimed at.
    """
    target = float(target_beats)
    if target < 0:
        raise ValueError(
            f"locate_start_position: target_beats {target} must be >= 0"
        )

    with context.live_state_lock:
        def _survey() -> dict[str, Any]:
            song = context.song
            return {
                "prior": float(getattr(song, "current_song_time", 0.0)),
                "cue_index": _cue_index_at(song, target),
                "has_toggle": _cue_toggle(song) is not None,
                "last_event_time": float(getattr(song, "last_event_time", 0.0)),
            }

        survey = context.run_on_main(_survey)
        prior: float = survey["prior"]
        degraded_detail: str | None = None

        # ---- path 1: the operator already has a locator here ----
        if survey["cue_index"] is not None:
            # Re-find by TIME, not by the surveyed index. Indices shift when a
            # locator is added or removed between bouts, and jumping to the
            # wrong cue puts the transport somewhere nobody asked for — which
            # is the whole failure this module exists to end.
            if context.run_on_main(lambda: _jump_cue_at(context.song, target)):
                settled = _wait_for_playhead(
                    context, target, timeout_s=settle_timeout_s,
                    tolerance_beats=arrival_tolerance_beats,
                    prior_beats=prior,
                )
                return LocateResult(
                    target_beats=target,
                    settled_beats=settled,
                    method=LOCATE_EXISTING_CUE,
                )
            # A cue IS here and could not be jumped (no CuePoint.jump on this
            # Live, or it vanished between bouts). Do NOT fall through to the
            # borrow path: its toggle fires at this same beat, and with a cue
            # already there a toggle DELETES — it would take the operator's
            # locator with it. Degrade instead.
            degraded_detail = (
                "a cue exists at the target but could not be jumped (this "
                "Live exposes no CuePoint.jump); borrowing a cue here would "
                "delete that one, so the start position was left unmoved"
            )

        # ---- path 3 preconditions: is path 2 even available? ----
        if degraded_detail is not None:
            pass  # path 1 already ruled the borrow out; keep its reason.
        elif not allow_temporary_cue:
            degraded_detail = (
                "no cue at the target and this caller forbids creating a "
                "temporary one"
            )
        elif not survey["has_toggle"]:
            degraded_detail = (
                "this Live version exposes no cue-toggle API "
                "(set_or_delete_cue), so no cue can be borrowed to jump to"
            )
        elif target > survey["last_event_time"] + _CUE_MATCH_EPSILON_BEATS:
            # Not a degradation — a refusal. Live clamps BOTH the playhead and
            # the cue toggle to the arrangement's extent, so a seek here lands
            # somewhere else and a toggle fired after it creates or deletes a
            # cue at that other beat. Degrading would hand the caller a
            # playhead it does not have; the cue handlers refuse the same
            # condition for the same reason.
            raise ValueError(
                f"locate_start_position: beat {target:g} is past the "
                f"arrangement's extent (last_event_time="
                f"{survey['last_event_time']:g}). Live clamps the playhead to "
                "that extent, so playback can never start here. Place "
                "arrangement content covering this position first."
            )

        if degraded_detail is not None:
            settled = _seek_playhead(
                context, target, settle_timeout_s=settle_timeout_s, prior=prior,
                tolerance_beats=arrival_tolerance_beats,
            )
            logger.warning(
                "locate_start_position fell back to a playhead-only locate at "
                "beat %g: %s", target, degraded_detail,
            )
            return LocateResult(
                target_beats=target,
                settled_beats=settled,
                method=LOCATE_PLAYHEAD_ONLY,
                detail=degraded_detail,
            )

        # ---- path 2: borrow a cue ----
        settled = _seek_playhead(
            context, target, settle_timeout_s=settle_timeout_s, prior=prior,
            tolerance_beats=arrival_tolerance_beats,
        )
        if abs(settled - target) > _LOCATE_TOLERANCE_BEATS:
            # Close enough to play from, not close enough to toggle at: the
            # cue would be created at wherever the playhead really is. Take the
            # degraded locate rather than leave a locator at a beat nobody named.
            detail = (
                f"Live parked the playhead at beat {settled:.3f} rather than "
                f"{target:g}; a cue toggle fires at the real position, so "
                "borrowing one here would place it at the wrong beat"
            )
            logger.warning(
                "locate_start_position fell back to a playhead-only locate at "
                "beat %g: %s", target, detail,
            )
            return LocateResult(
                target_beats=target,
                settled_beats=settled,
                method=LOCATE_PLAYHEAD_ONLY,
                detail=detail,
            )

        def _toggle_one_in() -> bool:
            """Create the cue. Returns False — WITHOUT toggling — if a cue has
            appeared at the target since the survey (the operator clicking in
            Live is outside ``live_state_lock``'s reach). The toggle is a
            toggle: firing it there would delete their locator."""
            song = context.song
            if _cue_index_at(song, target) is not None:
                return False
            toggle = _cue_toggle(song)
            if toggle is None:  # pragma: no cover - surveyed above
                raise NotImplementedError(
                    "Live stopped exposing a cue-toggle API mid-locate"
                )
            toggle()
            return True

        toggled = context.run_on_main(_toggle_one_in)
        # The toggle reads the same audio-thread-mediated position the seek
        # wrote, so the new cue is not visible in the same bout. Yield on the
        # worker thread and look again.
        time.sleep(_LOCATE_POLL_S)

        def _jump_to_cue_at_target() -> tuple[bool, bool]:
            """(is a cue at the target, did we jump to it)"""
            song = context.song
            if _cue_index_at(song, target) is None:
                return False, False
            return True, _jump_cue_at(song, target)

        cue_present, jumped = context.run_on_main(_jump_to_cue_at_target)

        # Give the cue back only if we can see the one we made. A toggle that
        # produced nothing at the target either did nothing or landed
        # elsewhere; toggling again on that guess is how a stray locator ends
        # up in the operator's set at a beat nobody named.
        borrowed = toggled and cue_present
        if borrowed:
            _delete_borrowed_cue(context, target)
        elif toggled and not cue_present:
            logger.warning(
                "locate_start_position toggled a cue for beat %g but none "
                "appeared there — Live may have clamped it elsewhere. Not "
                "toggling again; check the set's locators.", target,
            )

        if not jumped:
            # The toggle did not produce a jumpable cue. The playhead is still
            # at the target from the seek above, so report the degraded locate
            # honestly rather than claiming a start-position move.
            detail = (
                "no jumpable cue could be put at the target (no CuePoint.jump "
                "on this Live, or Live clamped the toggle to another position)"
            )
            logger.warning(
                "locate_start_position fell back to a playhead-only locate at "
                "beat %g: %s", target, detail,
            )
            return LocateResult(
                target_beats=target,
                settled_beats=settled,
                method=LOCATE_PLAYHEAD_ONLY,
                detail=detail,
            )

        settled = _wait_for_playhead(
            context, target, timeout_s=settle_timeout_s,
            tolerance_beats=arrival_tolerance_beats, prior_beats=prior,
        )
        return LocateResult(
            target_beats=target,
            settled_beats=settled,
            method=LOCATE_TEMPORARY_CUE if borrowed else LOCATE_EXISTING_CUE,
        )


def _seek_playhead(
    context: LiveContext,
    target: float,
    *,
    settle_timeout_s: float,
    prior: float,
    tolerance_beats: float = _LOCATE_TOLERANCE_BEATS,
) -> float:
    """Write the playhead and settle-poll it. The weak half of a locate — on
    its own it moves nothing that ``start_playing()`` reads."""
    context.run_on_main(
        lambda: setattr(context.song, "current_song_time", target)
    )
    return _wait_for_playhead(
        context, target, timeout_s=settle_timeout_s,
        tolerance_beats=tolerance_beats, prior_beats=prior,
    )


def _delete_borrowed_cue(context: LiveContext, target: float) -> None:
    """Toggle away the cue this module created, and say so loudly if it stays.

    A locator left behind is a visible edit to the operator's set that they
    did not make. It is not worth failing the pass over — the pass is the
    thing they asked for — but it must never be silent.
    """
    def _toggle_off() -> bool:
        song = context.song
        # The toggle fires at wherever the playhead REALLY is. If it has
        # drifted off the target, toggling would delete or create a locator at
        # some other beat — worse than leaving ours behind, which at least the
        # warning below names.
        at = float(getattr(song, "current_song_time", 0.0))
        if abs(at - target) > _LOCATE_TOLERANCE_BEATS:
            return False
        toggle = _cue_toggle(song)
        if toggle is not None:
            toggle()
        return True

    try:
        if not context.run_on_main(_toggle_off):
            logger.warning(
                "locate_start_position did not remove the temporary cue at "
                "beat %g — the playhead had moved off it, and the toggle acts "
                "wherever the playhead is. A locator may be left in the set "
                "at that position.", target,
            )
            return
    except Exception as exc:  # prawduct:allow prawduct/broad-except -- Live wrappers raise arbitrary types; a failed cleanup must not mask the locate
        logger.warning(
            "locate_start_position could not remove the temporary cue at beat "
            "%g (%s: %s) — a locator may be left in the set at that position.",
            target, type(exc).__name__, exc,
        )
        return

    time.sleep(_LOCATE_POLL_S)
    still_there = context.run_on_main(
        lambda: _cue_index_at(context.song, target) is not None
    )
    if still_there:
        logger.warning(
            "locate_start_position left a temporary cue at beat %g — the "
            "delete toggle did not take. Remove the locator in Live if you "
            "did not put it there.", target,
        )


def require_playhead_within(
    observed: float,
    *,
    low: float,
    high: float,
    target_beats: float,
    what: str,
) -> None:
    """Judge an ALREADY-READ playhead beat. Raises
    :class:`PlayheadPositionError` when it is past ``high``.

    Split out from :func:`assert_playhead_within` so a caller that is already
    reading the playhead every tick — a perform pass's ramp loop — can check
    the beat it has rather than pay a second Live touch to fetch the same
    number. Being short of ``low`` is not judged here: a caller with its own
    travel budget (that ramp loop, a render's pre-roll) owns that direction.
    """
    if high < low:
        raise ValueError(
            f"require_playhead_within: high {high} is below low {low}"
        )
    if observed <= high:
        return
    raise PlayheadPositionError(
        f"{what} was positioned at beat {target_beats:g} but the transport is "
        f"playing from beat {observed:.3f} — past the expected window "
        f"[{low:g}, {high:g}], so it can never arrive. Live keeps a START "
        "PLAYING POSITION separate from the playhead, and start_playing() "
        "rolls from that; writing current_song_time does not move it. Nothing "
        "was recorded or captured. Retry — the locate borrows a cue point to "
        "move the start position, and this means the borrow did not take.",
        target_beats=target_beats,
        observed_beats=observed,
        low=low,
        high=high,
    )


def assert_playhead_within(
    context: LiveContext,
    *,
    low: float,
    high: float,
    target_beats: float,
    what: str,
    timeout_s: float = _PLAYHEAD_ARRIVAL_TIMEOUT_S,
    poll_s: float = _PLAYHEAD_POLL_S,
) -> float:
    """After ``start_playing()``, prove the transport is rolling where it was
    sent. Returns the beat observed inside ``[low, high]``.

    The two directions are not symmetric, and the asymmetry is the point:

    * **Past ``high``** — fail at once. A transport already beyond the window
      cannot travel back into it, so waiting only delays the report. This is
      the shape of the failure this function exists for: a span at beats 8-24
      and a playhead at 351.
    * **Short of ``low``** — wait. A caller may deliberately start early (a
      render's pre-roll), and the first read after ``start_playing()`` can
      still show the pre-play mirror. Give it ``timeout_s`` to travel in.

    ``what`` names the operation in the message ("perform pass", "render
    capture") so the reader knows what was abandoned.
    """
    deadline = time.monotonic() + timeout_s
    observed = _read_song_time(context)
    while True:
        require_playhead_within(
            observed, low=low, high=high, target_beats=target_beats, what=what,
        )
        if observed >= low:
            return observed
        if time.monotonic() >= deadline:
            raise PlayheadPositionError(
                f"{what} was positioned at beat {target_beats:g} but after "
                f"{timeout_s:.1f}s the transport reads beat {observed:.3f} — "
                f"still short of the expected window [{low:g}, {high:g}]. "
                "Either the transport is not rolling (Live's audio engine off, "
                "a modal dialog) or it started far earlier than it was sent.",
                target_beats=target_beats,
                observed_beats=observed,
                low=low,
                high=high,
            )
        time.sleep(poll_s)
        observed = _read_song_time(context)


__all__ = [
    "LOCATE_EXISTING_CUE",
    "LOCATE_PLAYHEAD_ONLY",
    "LOCATE_TEMPORARY_CUE",
    "LocateResult",
    "PlayheadPositionError",
    "assert_playhead_within",
    "locate_start_position",
    "require_playhead_within",
]
