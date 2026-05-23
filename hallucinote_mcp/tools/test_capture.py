"""Throwaway capture harness — Chunk 1 proof-of-life for HallucinoteAnalyzer.amxd.

This script drives one round of the GO/NO-GO gate described in
``.prawduct/artifacts/build-plan.md`` (Chunk 1). It is intentionally
minimal — Chunk 2 replaces it with the ``ableton_render`` MCP action.
May or may not survive the next chunk; do not build on it.

What it does
============

1. Connects to the Hallucinote Remote Script (Live must be running with the
   control surface enabled).
2. Reads the session tempo so it can compute how long 4 bars of recording
   takes at the current BPM.
3. Sets ``output_path`` on the analyzer device sitting on the target track,
   then writes ``record_arm = 1``.
4. Seeks transport to bar 1, presses play, sleeps for the recording window,
   presses stop, sets ``record_arm = 0``.
5. Reports the WAV path the user should now inspect.

Master-track analyzer is **NOT driven by this script in Chunk 1.**
``ableton_device.set_parameter`` does not yet have a master-strip path
(Chunk 2 backlog dependency). For the GO/NO-GO test, manually arm the
master analyzer via its device UI toggle in Live (set ``output_path`` in
the device's text field too) before running this harness, and disarm it
manually after. Chunk 2 collapses both into one ``ableton_render`` call.

Usage
=====

    .venv/bin/python hallucinote_mcp/tools/test_capture.py \\
        --track-index 1 \\
        --device-index 1 \\
        --output-dir /tmp/hallucinote-chunk1 \\
        --bars 4

(Run as a plain script — this file lives outside the installed package so
``python -m`` won't resolve it. The editable install puts ``hallucinote_mcp``
on ``sys.path``, so the imports below resolve from anywhere.)

Defaults are tuned for "one audio track with the analyzer as the only
device, captured into /tmp." Override as needed.

What 'GO' looks like
====================

- ``track.wav`` exists in ``--output-dir`` (and ``master.wav``, if you
  manually pre-armed the master analyzer to the same directory).
- Both files are 32-bit float, stereo, Live's session sample rate.
- Duration matches ``--bars`` × (60 / bpm) × beats-per-bar within ± one
  buffer period.
- Cross-correlating the two via
  ``tests.unit.audio.test_pdc_alignment.cross_correlation_peak_lag``
  yields a lag within ± 64 samples of zero at 48 kHz.

What 'NO-GO' looks like
=======================

Read the build plan's NO-GO criteria. Fall back to the spike's
Resampling-tracks alternative and re-plan before Chunk 2.
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
import time
from pathlib import Path

from hallucinote_mcp.client import LiveConnectionError, send
from hallucinote_mcp.wire import Request, Response


def _send(tool: str, action: str, **params) -> Response:
    """Thin wrapper that fails loudly on protocol errors."""
    response = send(Request(tool=tool, action=action, params=params))
    if not response.ok:
        raise RuntimeError(
            f"{tool}({action}) failed: {response.error} "
            f"(hint: {response.hint or '—'})"
        )
    return response


def _seconds_for_bars(bars: int, bpm: float, beats_per_bar: int = 4) -> float:
    """How long ``bars`` arrangement bars take at ``bpm``.

    Assumes 4/4. Chunk 1 explicitly uses a simple test arrangement; meter
    awareness is Chunk 2's problem.
    """
    return bars * beats_per_bar * (60.0 / bpm)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Drive HallucinoteAnalyzer.amxd for the Chunk 1 GO/NO-GO test."
    )
    parser.add_argument(
        "--track-index",
        type=int,
        required=True,
        help="1-based track index of the test track carrying the analyzer.",
    )
    parser.add_argument(
        "--device-index",
        type=int,
        default=1,
        help=(
            "1-based device index of the analyzer within the track's "
            "device chain. Default 1 (analyzer is the only device)."
        ),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help=(
            "Directory to write WAVs into. Default: "
            "/tmp/hallucinote-chunk1-<iso-timestamp>."
        ),
    )
    parser.add_argument(
        "--bars",
        type=int,
        default=4,
        help="Number of bars to record (default 4).",
    )
    parser.add_argument(
        "--pre-roll-s",
        type=float,
        default=0.25,
        help=(
            "Seconds to wait between arming the recorder and starting "
            "transport. Gives sfrecord~ time to open the file. Bump if "
            "captures show truncated heads."
        ),
    )
    parser.add_argument(
        "--post-roll-s",
        type=float,
        default=0.25,
        help=(
            "Seconds to wait between stopping transport and disarming. "
            "Lets the audio buffer flush. Bump if captures show "
            "truncated tails."
        ),
    )
    args = parser.parse_args(argv)

    output_dir: Path = args.output_dir or Path(
        f"/tmp/hallucinote-chunk1-{dt.datetime.now().strftime('%Y%m%dT%H%M%S')}"
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    track_wav = output_dir / "track.wav"

    print(f"[harness] output dir: {output_dir}")
    print(
        f"[harness] driving track_index={args.track_index} "
        f"device_index={args.device_index}"
    )
    print(
        "[harness] NOTE: master-strip analyzer is NOT driven by this script "
        "in Chunk 1. Pre-arm it manually in Live (see spec) if you want a "
        "master WAV for PDC alignment."
    )

    try:
        info = _send("ableton_session", "info")
        bpm = float(info.result["tempo"])  # type: ignore[index]
        print(f"[harness] session tempo: {bpm:.3f} BPM")

        record_window_s = _seconds_for_bars(args.bars, bpm)
        print(
            f"[harness] {args.bars} bars @ {bpm:.2f} BPM = "
            f"{record_window_s:.3f} s of audio"
        )

        # 1) Point the analyzer at the WAV path.
        _send(
            "ableton_device",
            "set_parameter",
            track_index=args.track_index,
            device_index=args.device_index,
            parameter_name="Output Path",
            value=str(track_wav.resolve()),
        )

        # 2) Arm the recorder.
        _send(
            "ableton_device",
            "set_parameter",
            track_index=args.track_index,
            device_index=args.device_index,
            parameter_name="Record Arm",
            value="1.0",
        )

        # 3) Pre-roll so sfrecord~ has the file open before t=0.
        time.sleep(args.pre_roll_s)

        # 4) Seek to bar 1, beat 0; start transport.
        _send("ableton_session", "seek", bar=1, beat=0.0)
        _send("ableton_session", "play")
        print(f"[harness] transport started; recording {record_window_s:.3f} s")

        # 5) Sleep the recording window.
        time.sleep(record_window_s)

        # 6) Stop transport, post-roll, disarm.
        _send("ableton_session", "stop")
        time.sleep(args.post_roll_s)
        _send(
            "ableton_device",
            "set_parameter",
            track_index=args.track_index,
            device_index=args.device_index,
            parameter_name="Record Arm",
            value="0.0",
        )

    except LiveConnectionError as exc:
        print(f"[harness] could not reach Live: {exc}", file=sys.stderr)
        return 2
    except RuntimeError as exc:
        print(f"[harness] protocol error: {exc}", file=sys.stderr)
        return 3

    print(f"[harness] done. inspect: {track_wav}")
    if not track_wav.exists():
        print(
            "[harness] WARNING: expected WAV not found on disk. NO-GO — "
            "check the .amxd's record_arm handling and the Output Path "
            "parameter wiring.",
            file=sys.stderr,
        )
        return 4
    print(f"[harness] file size: {track_wav.stat().st_size} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
