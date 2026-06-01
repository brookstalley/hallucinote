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

DB-side audit linkage (``manifest.db_seq``) is deferred: the MVP
focuses on producing the captures + manifest end-to-end. Chunk 3 ties
the manifest to the song DB's event log when the analysis pipeline
needs cross-reference points.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from ..analyzer import (
    AnalyzerInstance,
    AnalyzerLayout,
    ensure_analyzers_loaded,
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
    """
    deadline = time.monotonic() + max_wait_s

    def _live_now() -> float:
        def _read() -> float:
            return float(getattr(context.song, "current_song_time", 0.0))
        return float(context.run_on_main(_read))

    now_fn = clock_source if clock_source is not None else _live_now

    while time.monotonic() < deadline:
        current = now_fn()
        if current >= target_beat:
            return "crossed"
        if (
            current >= no_frame_checkpoint_beat
            and frame_count() - frames_before <= 0
        ):
            return "no_frames"
        time.sleep(poll_interval_s)
    return "timeout"


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


def render_handler(
    context: LiveContext,
    *,
    song_slug: str,
    output_dir: str | None = None,
    post_roll_beats: float = _DEFAULT_POST_ROLL_BEATS,
    pre_roll_beats: float = _DEFAULT_PRE_ROLL_BEATS,
    start_at_beat: int = 0,
    stop_at_beat: int | None = None,
    _osc_factory: Callable[[int], AnalyzerOSC] | None = None,
    _sidecar: OSCSidecar | None = None,
    _clock_source: Callable[[], float] | None = None,
    _now_iso: Callable[[], str] | None = None,
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
      - ``post_roll_beats``: extra beats to let transport run past
        ``stop_at_beat`` before stopping. Default 4 (one bar in 4/4).
      - ``pre_roll_beats``: how many beats BEFORE ``start_at_beat`` to
        seek before pressing play. Required so the patch's transport-
        cross detector sees an actual edge (less-than-threshold then
        at-or-above) instead of starting at the threshold. Default 4
        (one bar in 4/4), symmetric to post_roll. The pre-roll audio
        is not part of the captured WAV — the patch's sfrecord~ only
        starts when transport crosses start_at_beat.
      - ``start_at_beat`` / ``stop_at_beat``: render window in beats.
        ``stop_at_beat=None`` (default) uses the arrangement's full
        length (``song.last_event_time``).

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

    # Compute window. `song.last_event_time` is Live's arrangement length;
    # an empty arrangement (last_event_time == 0) is the caller's bug, not
    # ours — surface it loud.
    end_beat = (
        int(stop_at_beat) if stop_at_beat is not None
        else int(_arrangement_length_beats(context))
    )
    if end_beat <= start_at_beat:
        raise ValueError(
            f"render: stop_at_beat ({end_beat}) must be > "
            f"start_at_beat ({start_at_beat}); the patch refuses to "
            "arm with a non-positive window. If you're rendering an "
            "empty arrangement, compose first or pass an explicit "
            "stop_at_beat."
        )

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
        client.set_stop_at_beat(end_beat)

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
    seek_to = max(0.0, float(start_at_beat) - float(pre_roll_beats))
    def _seek_on_main() -> None:
        context.song.current_song_time = seek_to
    context.run_on_main(_seek_on_main)
    time.sleep(_INTER_MUTATION_YIELD_S)
    def _play_on_main() -> None:
        context.song.start_playing()
    context.run_on_main(_play_on_main)

    # Wait for transport to cross stop+post_roll — or fail fast if the
    # recorder never starts capturing.
    target_beat = float(end_beat) + float(post_roll_beats)
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

    now_iso = (_now_iso() if _now_iso is not None else _utc_timestamp())
    manifest = {
        "schema_version": "1",
        "captured_at": now_iso,
        "song_slug": song_slug,
        "start_at_beat": start_at_beat,
        "stop_at_beat": end_beat,
        "post_roll_beats": post_roll_beats,
        "status": status,
        "frames_received": frames_after - frames_before,
        "analyzer_signature": "hallucinote-analyzer-v1",
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


# --- internals -------------------------------------------------------


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
        addr = _surface_address(inst)
        context.run_on_main(lambda inst=inst, addr=addr: device_handlers.set_parameter_handler(
            context,
            device_index=inst.device_index,
            parameter_name="Arm",
            value=value,
            value_type="continuous",
            **addr,
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
    }


__all__ = ["ensure_loaded_handler", "render_handler", "RenderResult"]
