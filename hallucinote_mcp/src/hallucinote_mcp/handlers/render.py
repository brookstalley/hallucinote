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

# Worker-thread poll cadence for "has transport crossed stop_at_beat yet?".
# Matches the arrangement-cue-settle cadence already used elsewhere; fine
# for beat-granularity end detection.
_POLL_INTERVAL_S = 0.05

# Worst-case wait. Equals (arrangement length in seconds) + a fat margin.
# At 60 BPM, 256 beats = 256 s; 5x margin = ~21 minutes. Live's transport
# can stall (audio driver hiccups, OS pressure) so don't be miserly. The
# render is bounded by song length × wall-clock-time-ratio anyway.
_MAX_WAIT_MULTIPLIER = 5.0
_MIN_WAIT_S = 30.0


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


def _default_captures_dir(song_slug: str | None) -> Path:
    """`songs/<slug>/captures/<iso-timestamp>/` per the agreed layout.

    Falls back to a `./captures/<timestamp>/` shape if no slug is
    provided — useful for one-off renders against an open Live set
    that isn't (yet) bound to a Hallucinote song.
    """
    ts = _utc_timestamp()
    if song_slug:
        return Path("songs") / song_slug / "captures" / ts
    return Path("captures") / ts


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


def _wait_for_beat_crossing(
    context: LiveContext,
    target_beat: float,
    *,
    max_wait_s: float,
    poll_interval_s: float = _POLL_INTERVAL_S,
    clock_source: Callable[[], float] | None = None,
) -> bool:
    """Poll until `current_song_time >= target_beat`.

    ``clock_source`` is a test seam: when provided, the loop reads from
    it instead of from Live. Production callers leave it ``None`` so
    polling goes through `context.run_on_main(read song.current_song_time)`.

    Returns True if crossed before the deadline; False on timeout.
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
            return True
        time.sleep(poll_interval_s)
    return False


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
    song_slug: str | None = None,
    output_dir: str | None = None,
    post_roll_beats: float = _DEFAULT_POST_ROLL_BEATS,
    start_at_beat: int = 0,
    stop_at_beat: int | None = None,
    _osc_factory: Callable[[int], AnalyzerOSC] | None = None,
    _sidecar: OSCSidecar | None = None,
    _clock_source: Callable[[], float] | None = None,
    _now_iso: Callable[[], str] | None = None,
) -> dict[str, Any]:
    """End-to-end render: ensure analyzers, deliver paths, play, capture.

    Inputs:
      - ``song_slug`` (optional): the Hallucinote song slug. Drives the
        default ``output_dir`` (``songs/<slug>/captures/<iso-ts>/``).
      - ``output_dir`` (optional): absolute or relative path. Created
        if missing. Overrides the slug-derived default.
      - ``post_roll_beats``: extra beats to let transport run past
        ``stop_at_beat`` before stopping. Default 4 (one bar in 4/4).
      - ``start_at_beat`` / ``stop_at_beat``: render window in beats.
        ``stop_at_beat=None`` (default) uses the arrangement's full
        length (``song.last_event_time``).

    Returns a dict suitable for direct MCP response::

        {
          "captures_dir": "songs/<slug>/captures/<ts>/",
          "manifest_path": "songs/<slug>/captures/<ts>/manifest.json",
          "manifest": {...},
          "status": "ok" | "incomplete",
        }
    """
    sidecar = _sidecar if _sidecar is not None else shared_sidecar()
    layout = ensure_analyzers_loaded(context, emit_port=sidecar.port)

    captures_dir = (
        Path(output_dir) if output_dir else _default_captures_dir(song_slug)
    )
    captures_dir.mkdir(parents=True, exist_ok=True)

    # Compute window.
    total_length_beats = _arrangement_length_beats(context)
    if stop_at_beat is None:
        # If the arrangement has zero length (a song scaffolded but not
        # composed yet), we still want a render harness to work for
        # smoke-testing — use a 4-bar minimum window.
        end_beat = int(max(total_length_beats, 16.0))
    else:
        end_beat = int(stop_at_beat)
    if end_beat <= start_at_beat:
        raise ValueError(
            f"render: stop_at_beat ({end_beat}) must be > "
            f"start_at_beat ({start_at_beat}); the patch refuses to "
            "arm with a non-positive window"
        )

    # Per-analyzer setup: deliver path, track_id, beat window via OSC.
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

    # Arm everyone in one pass. Live's set_parameter is synchronous so
    # the arms happen in handler call order; the patch's beat observer
    # waits for transport, not for arm-write timing, so per-Live-message
    # latency between arms doesn't matter (the architectural win — see
    # spec §"Why arm-as-gate").
    _set_arm_on_all(context, layout, arm=True)

    # Seek to start beat (1-based bar/beat addressing) then play.
    def _seek_and_play_on_main() -> None:
        context.song.current_song_time = float(start_at_beat)
        context.song.start_playing()
    context.run_on_main(_seek_and_play_on_main)

    # Wait for transport to cross stop+post_roll.
    target_beat = float(end_beat) + float(post_roll_beats)
    max_wait_s = max(
        _MIN_WAIT_S,
        (target_beat - start_at_beat) * _MAX_WAIT_MULTIPLIER,
    )
    crossed = _wait_for_beat_crossing(
        context, target_beat,
        max_wait_s=max_wait_s,
        clock_source=_clock_source,
    )

    # Stop transport, disarm.
    def _stop_on_main() -> None:
        context.song.stop_playing()
    context.run_on_main(_stop_on_main)
    _set_arm_on_all(context, layout, arm=False)

    status = "ok" if crossed else "incomplete"
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

    if not crossed:
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
    """Write `Arm` Live param on every analyzer. Sequential; the patch's
    beat observer (not the Arm-write latency) defines the recording
    boundary."""
    value = "1.0" if arm else "0.0"
    for inst in layout.instances:
        addr = _surface_address(inst)
        device_handlers.set_parameter_handler(
            context,
            device_index=inst.device_index,
            parameter_name="Arm",
            value=value,
            value_type="continuous",
            **addr,
        )


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
