"""``ableton_render`` action handlers.

The render action orchestrates a single end-to-end capture pass:

  1. ensure analyzers are present on every audio track + return + master
  2. for each analyzer, deliver the WAV path via OSC `/path` and the
     identity via OSC `/track_id` (path / id can't be Live parameters —
     strings need an out-of-band channel; see analyzer spec)
  3. compute the (start_at_beat, stop_at_beat) window from the
     arrangement length, deliver via OSC
  4. arm all analyzers in one batch
  5. seek transport to start and play
  6. poll transport position until it crosses stop + post-roll
  7. stop transport and disarm
  8. write the captures manifest (JSON next to the WAVs)
  9. return the captures dir + manifest dict so the caller can hand
     it to ``ableton_analysis`` (Chunk 3) or another consumer

The transport observer inside the .amxd handles the actual sfrecord~
start/stop on its own; the handler just sets up the window and waits.
``Arm`` is a gate, not a boundary — see analyzer spec §"Transport-
position-driven timing" for why.

DB-side audit linkage: ``manifest.db_seq`` records the song's latest
audit-log seq at render-trigger time (AUD-4W7K). The MCP server reads
it (`server._attach_render_db_seq` — this handler runs in Live's
vendored env with no hallucinote package) and forwards it as the
``db_seq`` param; baseline diffs (``ableton_analysis`` ``compare_to``)
resolve previous reports by this key. Absent when the seq couldn't be
read — provenance is best-effort, never render-blocking.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .jobs import (
    DEFAULT_STATUS_LONG_POLL_S,
    JobRegistry,
    default_registry,
    spawn_daemon,
)

from ..analyzer import (
    AnalyzerInstance,
    AnalyzerLayout,
    StrippedAnalyzer,
    ensure_analyzers_loaded,
    strip_analyzers,
)
from ..analyzer.osc import AnalyzerOSC
from ..analyzer.sidecar import OSCSidecar, shared_sidecar
from ..dispatcher import LiveContext
from ..handlers import device as device_handlers


logger = logging.getLogger("hallucinote_mcp.render")

# How many extra beats to let transport run past `stop_at_beat` before we
# tell Live to stop. Gives the analyzer's beat-position observer (inside
# the patch) time to fire the stop+finalize on `sfrecord~` even if its
# scheduler tick lands just before the boundary. One bar at 4/4 is plenty.
_DEFAULT_POST_ROLL_BEATS = 4.0

# How many beats of pure reverb RING-OUT to record AFTER the arrangement ends.
# The dry arrangement plays through `stop_at_beat`; the render then keeps
# recording for `ring_out_beats` more while transport runs into the empty
# post-arrangement region — no MIDI, so instruments release and the reverb
# returns decay into silence. This captured decay is what reverb RT60
# verification measures (Schroeder backward integration of the tail; see
# `audio.reverb.measure_return_rt60`). WITHOUT it the recording finalizes at
# the arrangement end and RT60 is unverifiable (AUD-6R2M / AUD-4S8T).
#
# Beats, not seconds, because the analyzer's stop boundary is beat-based (the
# patch fires `sfrecord~` stop when transport crosses the stop-beat it was
# given). 8 beats covers a typical reverb at common tempos; scale it up for a
# long (e.g. 3 s+) hall when the session tempo is fast — the read side
# degrades to an honest "insufficient ring-out, re-render with more" skip
# rather than a wrong number if it's too short. Set 0 to skip the ring-out
# (e.g. a song with no reverb returns to verify).
_DEFAULT_RING_OUT_BEATS = 8.0

# How many beats before `start_at_beat` to seek BEFORE pressing play, so
# the patch's transport-cross detector sees a true less-than-threshold-
# then-at-or-above transition. The detector's expr is
# ``($f2 < $i3) && ($f1 >= $i3) && ($i4 == 1)`` where $f2 is the prior
# song-time (via [deferlow] → [f]) and $f1 is the current song-time. If
# we seek directly TO start_at_beat, the first observer fire lands at
# $f1 = start_at_beat AND deferlow has often already updated $f2 to that
# same value — the cross "edge" is missed and recording never starts.
# Seeking pre-roll-beats EARLIER guarantees a clean less-than initial
# state; transport then crosses the threshold during play. Symmetric to
# `_DEFAULT_POST_ROLL_BEATS` — one bar at 4/4 is plenty.
_DEFAULT_PRE_ROLL_BEATS = 4.0

# Worker-thread poll cadence for "has transport crossed stop_at_beat yet?".
# Matches the arrangement-cue-settle cadence already used elsewhere; fine
# for beat-granularity end detection.
_POLL_INTERVAL_S = 0.05

# Wall-clock pause between successive Live mutations (seek → play; arm
# writes across many surfaces). Lets Live's main thread drain the
# notification cascade triggered by each mutation before the next one
# enters Live's API; without it, the second mutation can land while
# Live is still inside the first's listener callbacks and Live raises
# "Changes cannot be triggered by notifications. You will need to defer
# your response." Same shape as the inter-surface yield in
# analyzer.setup.ensure_analyzers_loaded.
_INTER_MUTATION_YIELD_S = 0.05


# Worst-case wait. Equals (arrangement length in seconds) + a fat margin.
# At 60 BPM, 256 beats = 256 s; 5x margin = ~21 minutes. Live's transport
# can stall (audio driver hiccups, OS pressure) so don't be miserly. The
# render is bounded by song length × wall-clock-time-ratio anyway.
_MAX_WAIT_MULTIPLIER = 5.0
_MIN_WAIT_S = 30.0

# Fail-fast checkpoint: how many beats INTO the recording window transport must
# advance before a still-zero frame count is treated as "the recorder never
# armed" rather than "give it a moment". Measured from start_at_beat (not from
# the pre-roll seek), so a long pre-roll at slow tempo never trips it — by the
# time transport is this far past the recording start, a healthy analyzer has
# been emitting feature frames for a while. When the recorder is dead (stale
# Control-Surface subprocess, or an open analyzer M4L editor stealing
# udpreceive — both documented sharp edges) this bails in seconds instead of
# blocking the full ~minutes-long render window for frames that never come.
_NO_FRAME_CHECKPOINT_BEATS = 4.0

# Engine pre-flight. After ``start_playing`` the transport must actually advance.
# When Live's audio engine is OFF — the output device vanished (headphones
# unplugged, a device switch); Live shows "the audio engine is off" and refuses to
# play — the transport never moves: ``current_song_time`` stays frozen at the seek.
# The capture wait loop below polls ``current_song_time``, so WITHOUT this check an
# engine-off render blocks the ENTIRE ``max_wait_s`` window (minutes) before timing
# out to ``incomplete`` with no actionable cause. We sample ``current_song_time``
# across a short window right after play; a frozen transport fails fast and names
# the cause. The LOM exposes NO audio-engine-running flag (verified by introspecting
# ``song`` + ``application`` — neither carries one), so "does song-time move?" is the
# robust, property-independent detector.
_TRANSPORT_PROBE_S = 0.5
_TRANSPORT_ADVANCE_EPSILON_BEATS = 0.02


# --- public types ----------------------------------------------------


@dataclass(frozen=True)
class RenderResult:
    """One end-to-end render's deliverables.

    The captures dir holds N+R+1 WAVs (N audio tracks, R returns, 1
    master) plus `manifest.json`. The manifest dict here is the same
    payload that was written to disk.
    """

    captures_dir: Path
    manifest: dict[str, Any]
    layout: AnalyzerLayout
    status: str  # 'ok' | 'incomplete'


# --- helpers ---------------------------------------------------------


def _utc_timestamp() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


# The completion-heartbeat filename. The render writes this to <captures_dir>
# at start ({"state": "running"}), refreshes it inside the capture wait loop,
# and writes a terminal {"state": "done"} / {"state": "error"} at the end, so
# an agent can poll a stable file for completion (BUG3). The MCP wrapper times
# out at 60s with a red error long before a multi-minute render finishes;
# manifest.json is the only completion signal today, forcing fragile
# dir-watching. status.json is the robust signal — present-and-running the
# whole render, terminal at the end whether the render succeeded or raised.
STATUS_FILENAME = "status.json"


def _write_status_json(captures_dir: Path, status: dict[str, Any]) -> None:
    """Default disk status writer — atomically refresh <captures_dir>/status.json.

    Best-effort observability, never render-affecting: a write failure here
    must not break a render whose audio is otherwise fine, so the rare
    filesystem error (a transient lock, a vanished dir) is swallowed. This is
    NOT an error-hiding broad catch — there is no logic downstream of the
    write, and the render's real result is the manifest + WAVs; a missed
    heartbeat write only costs the poller one more poll.
    """
    try:
        (captures_dir / STATUS_FILENAME).write_text(
            json.dumps(status, indent=2, sort_keys=False),
            encoding="utf-8",
        )
    except OSError:
        pass


def _wav_filename(inst: AnalyzerInstance) -> str:
    """Filename derived from the analyzer's surface address. Stable
    enough that two consecutive renders on the same song produce the
    same names in different timestamp dirs (callers can diff)."""
    if inst.surface_kind == "master":
        return "master.wav"
    base = f"{inst.surface_kind}-{inst.surface_index:02d}-{_sanitize(inst.surface_name)}"
    return f"{base}.wav"


def _sanitize(name: str) -> str:
    """Filesystem-safe slug. Keeps alphanumeric + ._- ; replaces others."""
    out = []
    for ch in name:
        if ch.isalnum() or ch in (".", "_", "-"):
            out.append(ch)
        else:
            out.append("_")
    return "".join(out) or "unnamed"


def _arrangement_length_beats(context: LiveContext) -> float:
    """Live exposes arrangement length as `song.last_event_time` (the
    largest event time across all tracks/cue points; effectively the
    arrangement's authored length). Handlers elsewhere in this codebase
    use the same accessor; mirror their pattern."""
    return float(getattr(context.song, "last_event_time", 0.0))


def _content_end_beats(context: LiveContext) -> float:
    """Where the arrangement's *content* ends — the max clip ``end_time``
    across all tracks. This is the dry-stop anchor for the ring-out.

    NOT ``song.last_event_time``: Live extends last_event_time to the
    furthest playhead position, so a render that plays the transport into
    the post-content ring-out region inflates it past where the music
    actually ends — AND the inflation compounds across renders (each
    default-stop render anchors off the previous render's inflated value
    and pushes it further out). Once last_event_time has drifted past the
    real content, the dry "stop" lands in trailing dead-air where the
    reverb has already fully decayed, the ring-out window records pure
    silence, and the per-return RT60 measurement honestly skips with
    ``tail_span_db == 0`` — defeating the whole verification. Clip
    ``end_time`` is stable ground truth, immune to the drift.

    Falls back to ``last_event_time`` when no track carries arrangement
    clips (an empty or session-only set) so the downstream
    empty-arrangement guard still fires.
    """
    def _scan_max_clip_end() -> float:
        max_end = 0.0
        for track in context.song.tracks:
            for clip in getattr(track, "arrangement_clips", None) or ():
                end = float(getattr(clip, "end_time", 0.0))
                if end > max_end:
                    max_end = end
        return max_end

    content_end = float(context.run_on_main(_scan_max_clip_end))
    if content_end > 0.0:
        return content_end
    return _arrangement_length_beats(context)


def _wait_for_capture(
    context: LiveContext,
    target_beat: float,
    *,
    max_wait_s: float,
    frame_count: Callable[[], int],
    frames_before: int,
    no_frame_checkpoint_beat: float,
    poll_interval_s: float = _POLL_INTERVAL_S,
    clock_source: Callable[[], float] | None = None,
    status_writer: Callable[[dict[str, Any]], None] | None = None,
) -> str:
    """Poll transport + frame count; return the capture outcome.

    Returns one of:
      - ``"crossed"``   — transport reached ``target_beat`` (render complete).
      - ``"no_frames"`` — transport advanced past ``no_frame_checkpoint_beat``
        but the analyzer sidecar has received zero frames since
        ``frames_before``: the recorder isn't capturing, so fail fast instead
        of blocking the whole window.
      - ``"timeout"``   — the deadline elapsed without crossing (transport
        stalled while frames WERE flowing — a partial capture survives).

    The frame check is gated on transport progress (not wall-clock), so a long
    pre-roll at slow tempo can't false-trip it. ``clock_source`` is a test seam:
    when provided the loop reads the beat from it instead of from Live.

    ``status_writer``, when provided, is called once per poll with the live
    heartbeat (``state="running"`` + current beat / frame progress) so an agent
    polling ``status.json`` sees the render advancing (BUG3). It is the test
    seam too — a test passes a recording stand-in to assert the loop refreshes
    the heartbeat.
    """
    deadline = time.monotonic() + max_wait_s

    def _live_now() -> float:
        def _read() -> float:
            return float(getattr(context.song, "current_song_time", 0.0))
        return float(context.run_on_main(_read))

    now_fn = clock_source if clock_source is not None else _live_now

    while time.monotonic() < deadline:
        current = now_fn()
        if status_writer is not None:
            status_writer({
                "state": "running",
                "current_beat": current,
                "target_beat": target_beat,
                "frames_received": frame_count() - frames_before,
            })
        if current >= target_beat:
            return "crossed"
        if (
            current >= no_frame_checkpoint_beat
            and frame_count() - frames_before <= 0
        ):
            return "no_frames"
        time.sleep(poll_interval_s)
    return "timeout"


def _default_engine_preflight(context: LiveContext, *, probe_s: float) -> bool:
    """True iff the transport advances over ``probe_s`` seconds after play.

    Two samples of ``current_song_time`` on Live's main thread, ``probe_s`` apart.
    A frozen transport (delta within ``_TRANSPORT_ADVANCE_EPSILON_BEATS``) means
    Live's audio engine is off (or the transport stalled at the gate) — the caller
    fails fast instead of waiting out the whole render window. ``probe_s`` gives
    Live's transport time to spin up; even at 20 BPM (1 beat = 3 s) a 0.5 s window
    advances ~0.17 beat, far above the epsilon, so a healthy engine never
    false-trips."""
    def _read() -> float:
        def _r() -> float:
            return float(getattr(context.song, "current_song_time", 0.0))
        return float(context.run_on_main(_r))
    t0 = _read()
    time.sleep(probe_s)
    t1 = _read()
    return (t1 - t0) > _TRANSPORT_ADVANCE_EPSILON_BEATS


# --- the two action handlers -----------------------------------------


def ensure_loaded_handler(context: LiveContext) -> dict[str, Any]:
    """Silent sweep — just place analyzers where missing. No render.

    Wired into the `/song-new`, `/track-new-with-instrument`, and
    `/return-new` skill postludes so the analyzer placement keeps up
    with structural mutations without forcing the user to think about
    it. Returns the layout shape so the LLM can see what happened
    (loaded N, found M existing).
    """
    layout = ensure_analyzers_loaded(context)
    return {
        "loaded_count": layout.loaded_count,
        "existing_count": layout.existing_count,
        "instances": [_instance_to_dict(inst) for inst in layout.instances],
    }


def strip_handler(context: LiveContext) -> dict[str, Any]:
    """Bulk REMOVAL — delete the analyzer from every surface. No render.

    The inverse of ``ensure_loaded``: that places an analyzer on every audio
    track + return + master; this removes it from each. After a render the
    HallucinoteAnalyzer sits on ~N+R+1 surfaces; this gives a clean device set
    for a deterministic push or a clean save in one call instead of deleting
    each analyzer by hand. Idempotent — re-running once every surface is clear
    is a no-op (each surface short-circuits via the pure ``_strip_action``).

    Returns ``{"stripped_count": <int>, "instances": [...]}`` where each
    instance mirrors ``ensure_loaded``'s per-surface descriptor (surface_kind /
    surface_index / surface_name) plus the ``device_index`` the removed
    analyzer occupied.
    """
    result = strip_analyzers(context)
    return {
        "stripped_count": result.stripped_count,
        "instances": [_stripped_to_dict(s) for s in result.stripped],
    }


def render_handler(
    context: LiveContext,
    *,
    song_slug: str,
    output_dir: str | None = None,
    post_roll_beats: float = _DEFAULT_POST_ROLL_BEATS,
    pre_roll_beats: float = _DEFAULT_PRE_ROLL_BEATS,
    ring_out_beats: float = _DEFAULT_RING_OUT_BEATS,
    start_at_beat: int = 0,
    stop_at_beat: int | None = None,
    db_seq: int | None = None,
    _osc_factory: Callable[[int], AnalyzerOSC] | None = None,
    _sidecar: OSCSidecar | None = None,
    _clock_source: Callable[[], float] | None = None,
    _engine_check: Callable[[], bool] | None = None,
    _now_iso: Callable[[], str] | None = None,
    _status_writer: Callable[[Path, dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """End-to-end render: ensure analyzers, deliver paths, play, capture.

    Inputs:
      - ``song_slug``: the Hallucinote song slug. Drives the default
        ``output_dir`` (server-side ``_absolutize_render_output_dir``
        resolves it to ``<repo>/songs/<slug>/captures/<utc-ts>/``).
        Required.
      - ``output_dir`` (REQUIRED by this handler — the MCP server
        resolves it for forwarded calls): absolute path on disk.
        Live's process cwd is ``/`` on macOS (read-only), so the
        handler refuses missing/relative values; the server-side
        preprocessor owns default + absolutize logic.
      - ``post_roll_beats``: extra beats to let transport run past the
        recording stop before stopping transport. Default 4 (one bar in 4/4).
      - ``ring_out_beats``: beats of pure reverb ring-out to RECORD after
        ``stop_at_beat``. The dry arrangement stops at ``stop_at_beat``;
        recording continues for ``ring_out_beats`` more while the returns
        decay into silence, so reverb RT60 is measurable from the captured
        tail (see ``_DEFAULT_RING_OUT_BEATS``). 0 skips the ring-out. The
        manifest records ``stop_at_beat`` (the input-stop boundary) and
        ``ring_out_beats`` separately; the captured audio spans
        ``[start_at_beat, stop_at_beat + ring_out_beats]``.
      - ``pre_roll_beats``: how many beats BEFORE ``start_at_beat`` to
        seek before pressing play. Required so the patch's transport-
        cross detector sees an actual edge (less-than-threshold then
        at-or-above) instead of starting at the threshold. Default 4
        (one bar in 4/4), symmetric to post_roll. The pre-roll audio
        is not part of the captured WAV — the patch's sfrecord~ only
        starts when transport crosses start_at_beat.
      - ``start_at_beat`` / ``stop_at_beat``: render window in beats.
        ``stop_at_beat=None`` (default) uses where the arrangement's
        content ends (max clip ``end_time``; see ``_content_end_beats``),
        NOT ``song.last_event_time`` — that accessor drifts past the real
        content and compounds across renders.

    Returns a dict suitable for direct MCP response. Paths are
    absolute post-server-side absolutize::

        {
          "captures_dir": "/Users/.../songs/<slug>/captures/<ts>/",
          "manifest_path": "/Users/.../songs/<slug>/captures/<ts>/manifest.json",
          "manifest": {...},
          "status": "ok" | "incomplete",
        }
    """
    sidecar = _sidecar if _sidecar is not None else shared_sidecar()
    layout = ensure_analyzers_loaded(context, emit_port=sidecar.port)

    # Production path: ``server._absolutize_render_output_dir`` always
    # resolves ``output_dir`` to an absolute path before forwarding the
    # request to the Remote Script. Direct in-process callers (tests)
    # must supply ``output_dir`` explicitly — the handler refuses to
    # invent a relative default because Live's process cwd is ``/`` on
    # macOS (read-only) and the slug-derived path would never be
    # writable. The server side owns the default + absolutize logic.
    if not output_dir:
        raise ValueError(
            "render: output_dir is required. The MCP server's "
            "_absolutize_render_output_dir resolves it for forwarded "
            "calls; direct in-process callers must supply it explicitly."
        )
    captures_dir = Path(output_dir)
    captures_dir.mkdir(parents=True, exist_ok=True)

    # Completion heartbeat (BUG3). Write status.json=running the instant the
    # captures dir exists so a polling agent sees the render is alive long
    # before manifest.json appears (the MCP wrapper red-times-out at 60s; a
    # multi-minute render needs a robust mid-flight signal). The wait loop
    # refreshes it with live progress; the terminal done/error write lands in
    # the try/except below. ``_status_writer`` is the disk writer by default and
    # the test seam when overridden (it takes the captures_dir so the same
    # writer serves the running-write, the loop refresh, and the terminal
    # write).
    write_status = _status_writer if _status_writer is not None else _write_status_json
    write_status(captures_dir, {"state": "running"})

    try:
        # Compute window. The default dry-stop is where the arrangement's CONTENT
        # ends (max clip end_time), NOT `song.last_event_time` — the latter drifts
        # past the real content as the transport plays into the ring-out region and
        # compounds across renders, marching the ring-out into already-decayed
        # dead-air (see _content_end_beats). An empty arrangement (content end == 0
        # and no last_event_time fallback) is the caller's bug, not ours — surface
        # it loud below.
        end_beat = (
            int(stop_at_beat) if stop_at_beat is not None
            else int(_content_end_beats(context))
        )
        if end_beat <= start_at_beat:
            raise ValueError(
                f"render: stop_at_beat ({end_beat}) must be > "
                f"start_at_beat ({start_at_beat}); the patch refuses to "
                "arm with a non-positive window. If you're rendering an "
                "empty arrangement, compose first or pass an explicit "
                "stop_at_beat."
            )

        # Record past the content end so the reverb RING-OUT is captured: the dry
        # input stops at end_beat (where the last clip ends), then transport runs
        # into the empty post-content region for ring_out_beats while the returns
        # decay into silence (AUD-6R2M / AUD-4S8T). The analyzer's sfrecord~ finalizes when
        # transport crosses the stop-beat it is given, so we hand it this EXTENDED
        # stop; the manifest still records end_beat as stop_at_beat (the input-stop
        # boundary the read side measures the decay from) plus ring_out_beats.
        record_stop_beat = end_beat + max(0, int(round(ring_out_beats)))

        # Per-analyzer setup: deliver path, track_id, beat window via OSC.
        # Per-instance arrival is independent — each udpreceive owns its own
        # bound port and routes /path → prepend open → its sfrecord~ on
        # arrival. No inter-instance pacing required (the prior 50ms yield
        # was a misdirected timing hypothesis before the [value] global root
        # cause was identified).
        osc_factory = _osc_factory if _osc_factory is not None else (
            lambda port: AnalyzerOSC(port=port)
        )
        per_instance_paths: dict[str, Path] = {}
        for inst in layout.instances:
            wav_path = (captures_dir / _wav_filename(inst)).resolve()
            per_instance_paths[inst.track_id] = wav_path
            client = osc_factory(inst.osc_port)
            client.set_path(str(wav_path))
            client.set_track_id(inst.track_id)
            client.set_start_at_beat(start_at_beat)
            client.set_stop_at_beat(record_stop_beat)

        # Frame counts before this render — surfaces sidecar health in the
        # manifest (deltas show whether we got any frames during the
        # window).
        frames_before = sidecar.frames_received

        # Arm everyone. Each arm write is its own main-thread bout with a
        # wall-clock yield between (see _set_arm_on_all). Live's beat
        # observer (inside the patch) defines the recording boundary, not
        # the arm-write timing, so per-arm latency is irrelevant — the
        # iteration cost just buys notification-cascade safety.
        _set_arm_on_all(context, layout, arm=True)

        # Seek then play. SPLIT into two main-thread bouts with a worker-
        # thread yield between: setting current_song_time triggers Live's
        # transport-state notification cascade, and start_playing() called
        # synchronously from inside that same scope can land while Live is
        # still inside a listener callback — yielding Live's classic
        # "Changes cannot be triggered by notifications" error. One bout
        # per Live touch.
        #
        # The seek lands at start_at_beat - pre_roll_beats (clamped at 0)
        # so the patch's transport-cross detector sees a clean less-than-
        # then-at-or-above transition. See ``_DEFAULT_PRE_ROLL_BEATS`` for
        # the empirical motivation — without the pre-roll, seeking AT the
        # threshold lands the observer's first fire on the boundary and the
        # detector misses the edge.
        # Loop OFF for the capture: the ring-out needs transport to run into the
        # empty post-arrangement region and decay, not loop back and re-trigger.
        # Saved and restored after the capture stops (its own bout — like the
        # seek/play split, a transport-property write triggers a notification
        # cascade that must drain before the next Live touch).
        original_loop: "bool | None" = None
        def _loop_off_on_main() -> None:
            nonlocal original_loop
            original_loop = bool(context.song.loop)
            context.song.loop = False
        context.run_on_main(_loop_off_on_main)
        time.sleep(_INTER_MUTATION_YIELD_S)

        seek_to = max(0.0, float(start_at_beat) - float(pre_roll_beats))
        def _seek_on_main() -> None:
            context.song.current_song_time = seek_to
        context.run_on_main(_seek_on_main)
        time.sleep(_INTER_MUTATION_YIELD_S)
        def _play_on_main() -> None:
            context.song.start_playing()
        context.run_on_main(_play_on_main)

        # Engine pre-flight: the transport must advance now that we've pressed play.
        # A frozen transport means Live's audio engine is off — fail fast (in ~probe_s)
        # rather than blocking the full max_wait_s window for a capture that can't
        # happen. A provided ``_clock_source`` is a transport SIMULATION (tests own the
        # position), so trust it and skip the live probe; ``_engine_check`` is the
        # direct seam for exercising this branch. See ``_TRANSPORT_PROBE_S``.
        if _engine_check is not None:
            transport_advancing = _engine_check()
        elif _clock_source is None:
            transport_advancing = _default_engine_preflight(
                context, probe_s=_TRANSPORT_PROBE_S)
        else:
            transport_advancing = True
        if not transport_advancing:
            # Clean up Live's transport before raising (mirror the no_frames path).
            def _stop_engine_off() -> None:
                context.song.stop_playing()
            context.run_on_main(_stop_engine_off)
            time.sleep(_INTER_MUTATION_YIELD_S)
            _set_arm_on_all(context, layout, arm=False)
            _restore_loop(context, original_loop)
            raise ValueError(
                "render: transport did not advance after play — Live's audio engine is "
                "OFF (or the transport stalled at the gate). Nothing was captured. This "
                "usually means the audio output device went away (headphones unplugged / "
                "a device switch); Live then shows 'the audio engine is off' and refuses "
                "to play. Fix: re-select an output device (Preferences > Audio) or tick "
                "Options > 'Audio Engine On', then retry. (Failing fast after "
                f"~{_TRANSPORT_PROBE_S:.1f}s — the full render window would otherwise "
                "block for minutes waiting for a transport that never moves.)"
            )

        # Wait for transport to cross the recording stop + post_roll — or fail fast
        # if the recorder never starts capturing. The recording stop is the
        # arrangement end PLUS the ring-out, so transport must run far enough for
        # the analyzer to finalize the captured tail.
        target_beat = float(record_stop_beat) + float(post_roll_beats)
        max_wait_s = max(
            _MIN_WAIT_S,
            (target_beat - seek_to) * _MAX_WAIT_MULTIPLIER,
        )
        # Only arm the zero-frame check if the checkpoint lands inside the render
        # window; a sub-checkpoint-length render completes before it would fire.
        checkpoint = float(start_at_beat) + _NO_FRAME_CHECKPOINT_BEATS
        no_frame_checkpoint = checkpoint if checkpoint < target_beat else float("inf")
        outcome = _wait_for_capture(
            context, target_beat,
            max_wait_s=max_wait_s,
            frame_count=lambda: sidecar.frames_received,
            frames_before=frames_before,
            no_frame_checkpoint_beat=no_frame_checkpoint,
            clock_source=_clock_source,
            # Refresh status.json=running with live progress each poll so a
            # polling agent sees the render advancing (BUG3). Bind the
            # captures_dir so the loop's writer only needs the status dict.
            status_writer=lambda s: write_status(captures_dir, s),
        )

        # Stop transport, then disarm. Same split as seek+play: stop_playing
        # triggers its own notification cascade; the arm-writes that follow
        # must each be their own bout. Always clean up Live's transport, even on
        # the fail-fast path, before raising.
        def _stop_on_main() -> None:
            context.song.stop_playing()
        context.run_on_main(_stop_on_main)
        time.sleep(_INTER_MUTATION_YIELD_S)
        _set_arm_on_all(context, layout, arm=False)
        _restore_loop(context, original_loop)

        if outcome == "no_frames":
            raise ValueError(
                f"render: the HallucinoteAnalyzer received 0 frames after "
                f"transport reached beat {checkpoint:.0f} — the recorder isn't "
                f"capturing, so no WAVs will be written. This is almost always a "
                f"stale Control-Surface/server subprocess or an open analyzer M4L "
                f"device-editor window stealing udpreceive. Fix: (1) quit and "
                f"reopen Live, (2) close any open HallucinoteAnalyzer editor "
                f"window, (3) run /mcp to respawn the server, then retry. (Failing "
                f"fast — the full render window would otherwise block up to "
                f"{max_wait_s:.0f}s waiting for frames that never arrive.)"
            )

        status = "ok" if outcome == "crossed" else "incomplete"
        frames_after = sidecar.frames_received

        # SNP-8R4K Mechanism 2 (R9) — observability roll-up. Any surface whose
        # analyzer could NOT be made strictly terminal (present + last) at render
        # start is under-tapped: its WAV misses whatever device sits past the
        # analyzer. Surface the offending surfaces' track_ids at the top of the
        # manifest so a reading agent (ableton_analysis) never trusts an
        # under-measured stem as if it were faithful — never measure-and-lie.
        analyzer_not_terminal = [
            inst.track_id for inst in layout.instances if not inst.terminal
        ]

        now_iso = (_now_iso() if _now_iso is not None else _utc_timestamp())
        manifest = {
            "schema_version": "1",
            "captured_at": now_iso,
            "song_slug": song_slug,
            "start_at_beat": start_at_beat,
            "stop_at_beat": end_beat,
            # Per-render terminal-tap health (SNP-8R4K). Empty list = every tapped
            # surface had the analyzer strictly last (the healthy, common case).
            "analyzer_not_terminal": analyzer_not_terminal,
            # The ACTUAL ring-out recorded (record_stop_beat is integer-beat — the
            # analyzer's stop is `/stop_at_beat <int>`), not the requested float.
            # The read side trusts this to span [stop_at_beat, stop+ring_out] onto
            # the captured samples; recording a fractional request would skew that
            # beat↔sample map.
            "ring_out_beats": record_stop_beat - end_beat,
            "post_roll_beats": post_roll_beats,
            "status": status,
            "frames_received": frames_after - frames_before,
            "analyzer_signature": "hallucinote-analyzer-v1",
            # Audit-log seq the captured audio reflects (server-attached at
            # forward time; None when provenance couldn't be read). The
            # baseline-diff key for ableton_analysis compare_to (AUD-4W7K).
            "db_seq": db_seq,
            "tracks": [
                _track_manifest_entry(inst, per_instance_paths[inst.track_id])
                for inst in layout.instances if inst.surface_kind == "track"
            ],
            "returns": [
                _track_manifest_entry(inst, per_instance_paths[inst.track_id])
                for inst in layout.instances if inst.surface_kind == "return"
            ],
            "master": next(
                (
                    _track_manifest_entry(inst, per_instance_paths[inst.track_id])
                    for inst in layout.instances if inst.surface_kind == "master"
                ),
                None,
            ),
        }

        manifest_path = captures_dir / "manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=False),
            encoding="utf-8",
        )

        # Terminal heartbeat (BUG3): the render finished (the manifest + WAVs are
        # on disk). ``state="done"`` is the robust completion signal an agent
        # polls for; ``render_status`` carries "ok"/"incomplete" so the poller
        # also learns whether the transport reached the stop. A render that
        # RAISED instead lands in the except below with ``state="error"``.
        write_status(captures_dir, {
            "state": "done",
            "render_status": status,
            "manifest_path": str(manifest_path),
        })

        if outcome != "crossed":
            logger.warning(
                "render: transport did not cross beat %.2f within %.1fs; "
                "captures may be incomplete (status=incomplete in manifest)",
                target_beat, max_wait_s,
            )

        return {
            "captures_dir": str(captures_dir),
            "manifest_path": str(manifest_path),
            "manifest": manifest,
            "status": status,
        }
    except Exception as e:  # prawduct:allow prawduct/broad-except -- top-level render supervisor: write status.json=error then re-raise so a poller sees a terminal state for a render that raised (BUG3); the exception is NOT swallowed (re-raised, so the dispatcher still surfaces it)
        # Every catch logs context (project norm) before the terminal heartbeat —
        # the dispatcher surfaces the re-raised exception to the caller, but the
        # server log is where a stuck-render postmortem reads what actually blew up.
        logger.exception(
            "render: failed for song_slug=%s (captures_dir=%s) — wrote "
            "status.json=error and re-raising", song_slug, captures_dir,
        )
        write_status(captures_dir, {"state": "error", "error": str(e)})
        raise


# --- async start / status (MCP-9R3T) ---------------------------------

# A render runs for minutes; the Claude Code tool-call timeout is a
# transport-agnostic wall-clock limit, so the synchronous `render` action
# false-fails long before the audio is written. `start` backgrounds the render
# on a detached worker and returns a job handle immediately; `status`
# long-polls the job registry. The long-poll window + the daemon-worker spawn
# are shared with analyze's start/status, so they live in jobs.py
# (DEFAULT_STATUS_LONG_POLL_S, spawn_daemon) — one knob, not two that drift. See
# .prawduct/artifacts/plans/MCP-ASYNC-RENDER-ANALYZE/api-notes.md.

RENDER_POLL_INSTRUCTION = (
    "Render running in the background. Poll ableton_render(action='status', "
    "job_id='{job_id}'); each status call long-polls ~45s and returns "
    "{{state}} — repeat until state is 'done' or 'failed'. One render at a "
    "time: don't call start again while this is running."
)


def _estimate_render_eta_s(
    context: LiveContext,
    *,
    start_at_beat: int,
    stop_beat: int,
    ring_out_beats: float,
) -> int | None:
    """Rough wall-clock estimate for the handle: render is realtime, so the
    captured span in beats / tempo gives the bulk of the time. Returns None
    when tempo can't be read (the handle just omits the eta)."""
    def _read_tempo() -> float:
        return float(getattr(context.song, "tempo", 0.0))

    tempo = float(context.run_on_main(_read_tempo))
    if tempo <= 0.0:
        return None
    beats = max(0.0, float(stop_beat) - float(start_at_beat)) + max(
        0.0, float(ring_out_beats)
    )
    return int(round(beats / tempo * 60.0))


def render_start_handler(
    context: LiveContext,
    *,
    song_slug: str,
    output_dir: str | None = None,
    post_roll_beats: float = _DEFAULT_POST_ROLL_BEATS,
    pre_roll_beats: float = _DEFAULT_PRE_ROLL_BEATS,
    ring_out_beats: float = _DEFAULT_RING_OUT_BEATS,
    start_at_beat: int = 0,
    stop_at_beat: int | None = None,
    db_seq: int | None = None,
    _registry: JobRegistry | None = None,
    _render_fn: Callable[..., dict[str, Any]] | None = None,
    _spawn: Callable[[Callable[[], None]], None] | None = None,
) -> dict[str, Any]:
    """Background a render and return its job handle immediately.

    The handle (``job_id`` + ``captures_dir`` + ``eta_seconds`` +
    ``expected_stop_beat`` + a poll instruction) lets the agent poll
    ``status`` without holding the tool-call socket for the render's duration.
    One render at a time: a ``start`` while another render is running returns
    ``{busy: True, job_id}`` rather than launching a second transport pass.
    """
    registry = _registry if _registry is not None else default_registry()
    render_fn = _render_fn if _render_fn is not None else render_handler
    spawn = _spawn if _spawn is not None else (
        lambda worker: spawn_daemon(worker, name="hallucinote-render-worker")
    )

    # The MCP server's _absolutize_render_output_dir resolves output_dir before
    # forwarding (same as the synchronous render); direct callers must supply
    # it because Live's process cwd is read-only.
    if not output_dir:
        raise ValueError(
            "render start: output_dir is required. The MCP server's "
            "_absolutize_render_output_dir resolves it for forwarded calls; "
            "direct in-process callers must supply it explicitly."
        )

    expected_stop_beat = (
        int(stop_at_beat)
        if stop_at_beat is not None
        else int(_content_end_beats(context))
    )
    eta_seconds = _estimate_render_eta_s(
        context,
        start_at_beat=start_at_beat,
        stop_beat=expected_stop_beat,
        ring_out_beats=ring_out_beats,
    )
    # One render at a time — atomically claim the slot. The async dispatch
    # wrapper (server.py) lets two starts run on different threads, so the claim
    # must be atomic; create_if_idle closes the check-then-create TOCTOU. A
    # start while one runs returns a busy handle pointing at the live job.
    job, created = registry.create_if_idle(
        kind="render",
        dir=output_dir,
        eta_seconds=eta_seconds,
        expected_stop_beat=expected_stop_beat,
    )
    if not created:
        return {
            "busy": True,
            "job_id": job.job_id,
            "state": job.state,
            "captures_dir": job.dir,
            "message": (
                "A render is already running (one at a time). Poll it with "
                f"ableton_render(action='status', job_id='{job.job_id}'), "
                "or wait for it to finish before starting another."
            ),
        }

    def _status_writer(captures_dir: Path, status: dict[str, Any]) -> None:
        # Keep the on-disk heartbeat (crash-resilient / direct dir-watchers)
        # AND mirror live progress into the in-memory registry the status
        # action reads. Best-effort, never render-affecting (the disk writer
        # already swallows OSError; the registry update is a plain dict swap).
        # Only RUNNING heartbeats become job.progress — the terminal done/error
        # write is reflected via mark_done/mark_failed (state + result/error),
        # so it must not leak terminal metadata into the progress payload.
        _write_status_json(captures_dir, status)
        if status.get("state") == "running":
            registry.update_progress(job.job_id, status)

    def _worker() -> None:
        try:
            result = render_fn(
                context,
                song_slug=song_slug,
                output_dir=output_dir,
                post_roll_beats=post_roll_beats,
                pre_roll_beats=pre_roll_beats,
                ring_out_beats=ring_out_beats,
                start_at_beat=start_at_beat,
                stop_at_beat=stop_at_beat,
                db_seq=db_seq,
                _status_writer=_status_writer,
            )
            registry.mark_done(job.job_id, result)
        except Exception as e:  # prawduct:allow prawduct/broad-except -- detached render worker: any failure must land as job state=failed (else status long-polls forever); the render handler already logged + wrote status.json=error before re-raising
            logger.exception(
                "render worker failed for job %s (song_slug=%s)",
                job.job_id, song_slug,
            )
            registry.mark_failed(job.job_id, str(e))

    spawn(_worker)
    return job.start_result(RENDER_POLL_INSTRUCTION.format(job_id=job.job_id))


def render_status_handler(
    context: LiveContext,
    *,
    job_id: str,
    _registry: JobRegistry | None = None,
    _long_poll_s: float = DEFAULT_STATUS_LONG_POLL_S,
) -> dict[str, Any]:
    """Long-poll a render job: wait up to ``_long_poll_s`` for it to finish,
    then return its current state + progress (and manifest/error if terminal).

    Returns ``state='running'`` if still in flight after the wait — the agent
    simply calls again. ``context`` is unused (status reads in-process job
    state, no Live touch) but kept for the uniform handler signature.
    """
    registry = _registry if _registry is not None else default_registry()
    job = registry.get(job_id)
    if job is None:
        recent = registry.recent_ids(kind="render")
        hint = (
            f"recent render jobs: {', '.join(recent)}"
            if recent
            else "no render jobs have been started in this server process"
        )
        raise ValueError(f"render status: unknown job_id {job_id!r} ({hint})")
    job.wait_terminal(_long_poll_s)
    return job.status_result()


# --- internals -------------------------------------------------------


def _restore_loop(context: LiveContext, original_loop: "bool | None") -> None:
    """Restore the transport loop toggle the render disabled for capture.

    No-op when ``original_loop`` is None (loop-off bout never ran — e.g. an
    early raise before the seek). Its own main-thread bout + yield, like every
    other transport mutation, so Live's notification cascade drains."""
    if original_loop is None:
        return

    def _restore_on_main() -> None:
        context.song.loop = original_loop
    context.run_on_main(_restore_on_main)
    time.sleep(_INTER_MUTATION_YIELD_S)


def _set_arm_on_all(
    context: LiveContext,
    layout: AnalyzerLayout,
    *,
    arm: bool,
) -> None:
    """Write `Arm` Live param on every analyzer.

    Each write is its own ``context.run_on_main`` bout with a worker-
    thread yield between. Sequential because the patch's beat observer
    (not the Arm-write latency) defines the recording boundary — the
    per-Live-message latency between arms doesn't affect sample-accurate
    capture timing. The yield lets Live's parameter-listener cascade
    drain between writes; without it Live can reject the next write
    with "Changes cannot be triggered by notifications" when an
    analyzer's M4L Arm listener is still flushing.
    """
    value = "1.0" if arm else "0.0"
    for inst in layout.instances:
        node = device_handlers.build_node_addr(
            _surface_address(inst), device_index=inst.device_index,
        )
        context.run_on_main(lambda node=node: device_handlers.set_parameter_handler(  # type: ignore[misc]  # LOM-capturing lambda
            context,
            node=node,
            parameter_name="Arm",
            value=value,
            value_type="continuous",
        ))
        time.sleep(_INTER_MUTATION_YIELD_S)


def _surface_address(inst: AnalyzerInstance) -> dict[str, Any]:
    if inst.surface_kind == "master":
        return {"master": True}
    if inst.surface_kind == "track":
        return {"track_index": inst.surface_index}
    if inst.surface_kind == "return":
        return {"return_index": inst.surface_index}
    raise ValueError(f"unknown surface_kind: {inst.surface_kind!r}")


def _instance_to_dict(inst: AnalyzerInstance) -> dict[str, Any]:
    return {
        "surface_kind": inst.surface_kind,
        "surface_index": inst.surface_index,
        "surface_name": inst.surface_name,
        "device_index": inst.device_index,
        "track_id": inst.track_id,
        "osc_port": inst.osc_port,
        "osc_emit_port": inst.osc_emit_port,
        "was_loaded": inst.was_loaded,
        # SNP-8R4K Mechanism 2 (R9) — terminal-tap status surfaced through the
        # ensure_loaded action response too, so the LLM sees a repositioned or
        # under-tapped surface after a structural-mutation postlude sweep.
        "terminal": inst.terminal,
        "was_repositioned": inst.was_repositioned,
    }


def _stripped_to_dict(stripped: StrippedAnalyzer) -> dict[str, Any]:
    """Per-surface descriptor for the strip response. Mirrors the surface
    fields ``_instance_to_dict`` emits (so callers can match strip output
    against an ensure_loaded layout) plus the ``device_index`` the removed
    analyzer occupied."""
    return {
        "surface_kind": stripped.surface_kind,
        "surface_index": stripped.surface_index,
        "surface_name": stripped.surface_name,
        "device_index": stripped.device_index,
    }


def _track_manifest_entry(
    inst: AnalyzerInstance,
    wav_path: Path,
) -> dict[str, Any]:
    return {
        "track_id": inst.track_id,
        "surface_name": inst.surface_name,
        "surface_index": inst.surface_index,
        "device_index": inst.device_index,
        "osc_port": inst.osc_port,
        "filename": wav_path.name,
        "absolute_path": str(wav_path),
        # SNP-8R4K Mechanism 2 (R9) — per-surface terminal-tap status. The
        # analyzer must be the chain's LAST device for the WAV to reflect the
        # full authored chain; ``terminal=False`` flags an under-tapped stem so
        # a reading agent never trusts its numbers (see the top-level
        # ``analyzer_not_terminal`` flag, which lists every such surface).
        # ``was_repositioned`` records that this render had to move the analyzer
        # back to last on this surface (a device had landed past it).
        "terminal": inst.terminal,
        "was_repositioned": inst.was_repositioned,
    }


__all__ = ["ensure_loaded_handler", "strip_handler", "render_handler", "RenderResult"]
