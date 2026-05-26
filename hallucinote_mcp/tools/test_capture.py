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
3. Sends ``/path <abs-path>`` to the analyzer's ``[udpreceive]`` via OSC
   (default 127.0.0.1:11000 — matches the patch's default ``OSC Port``).
   Path delivery is out-of-band because Live parameters are float / int /
   enum only — strings need a side channel.
4. Writes ``record_arm = 1`` via ``ableton_device.set_parameter``.
5. Seeks transport to bar 1, presses play, sleeps for the recording window,
   presses stop, sets ``record_arm = 0``.
6. Reports the WAV path the user should now inspect.

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
import math
import socket
import sys
import time
from pathlib import Path

import numpy as np
import soundfile as sf

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


def _osc_string(s: str) -> bytes:
    """OSC 1.0 null-terminated, 4-byte-aligned string."""
    raw = s.encode("utf-8") + b"\x00"
    pad = (-len(raw)) % 4
    return raw + (b"\x00" * pad)


def _osc_send(host: str, port: int, address: str, *args: str) -> None:
    """Minimal OSC sender. Only handles string args; that's all the patch needs."""
    type_tag = "," + ("s" * len(args))
    packet = _osc_string(address) + _osc_string(type_tag)
    for a in args:
        packet += _osc_string(a)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.sendto(packet, (host, port))
    finally:
        sock.close()


def _probe_device(track_index: int, device_index: int) -> dict[str, dict]:
    """Return {param_short_name: {value, min, max, ...}} for the device.

    Surfaces the Remote Script's short-name view, which is what
    set_parameter must address. If the device isn't the analyzer (or
    isn't loaded), the caller should bail before driving transport.
    """
    response = _send(
        "ableton_device",
        "get_parameters",
        track_index=track_index,
        device_index=device_index,
    )
    params = response.result.get("parameters", [])  # type: ignore[union-attr]
    return {p["name"]: p for p in params}


def _audio_activity(data: np.ndarray, sr: int, threshold_dbfs: float = -50.0) -> dict[str, float]:
    """Locate where audio is actually present in the recording.

    Slides a 50 ms RMS window across the file. Reports the first and last
    window above ``threshold_dbfs`` so we can see whether the overshoot
    duration is at the head (pre-arm leakage), the tail (post-stop
    leakage), or both. Threshold of -50 dBFS catches even quiet sustain
    while ignoring float-zero noise floor.
    """
    win_s = 0.05
    win = max(1, int(win_s * sr))
    n = len(data)
    if n < win:
        return {"audio_start_s": 0.0, "audio_end_s": 0.0, "active_duration_s": 0.0}
    # Mono-sum for envelope detection.
    mono = data.mean(axis=1) if data.ndim == 2 else data
    threshold_lin = 10.0 ** (threshold_dbfs / 20.0)
    # Vectorized window RMS via cumulative sum of squares.
    sq = mono.astype(np.float64) ** 2
    cumsum = np.concatenate(([0.0], np.cumsum(sq)))
    window_sums = cumsum[win:] - cumsum[:-win]
    window_rms = np.sqrt(window_sums / win)
    active = window_rms >= threshold_lin
    if not active.any():
        return {"audio_start_s": float("nan"), "audio_end_s": float("nan"), "active_duration_s": 0.0}
    first = int(np.argmax(active))
    last = int(len(active) - 1 - np.argmax(active[::-1]))
    return {
        "audio_start_s": first / float(sr),
        "audio_end_s": (last + win) / float(sr),
        "active_duration_s": ((last + win) - first) / float(sr),
    }


def _inspect_wav(path: Path) -> dict[str, object]:
    """Open a WAV; return shape + peak/mean dBFS, or {error: ...} on failure.

    Distinguishes the failure modes that all look like 'file exists' to
    a stat() check:
      - missing       → file isn't on disk
      - empty         → zero audio frames (header only)
      - silent        → frames present, peak < -60 dBFS (audio not reaching sfrecord~)
      - clipped       → peak ≥ 0 dBFS (signal too hot)
      - clean         → peak in [-60, 0) dBFS
    """
    if not path.exists():
        return {"status": "missing"}
    size = path.stat().st_size
    try:
        with sf.SoundFile(str(path)) as f:
            sr = f.samplerate
            channels = f.channels
            frames = len(f)
            subtype = f.subtype
            data = f.read(always_2d=True)
    except (sf.LibsndfileError, RuntimeError) as exc:
        return {"status": "unreadable", "size_bytes": size, "error": str(exc)}

    if frames == 0:
        return {
            "status": "empty",
            "size_bytes": size,
            "sample_rate": sr,
            "channels": channels,
            "subtype": subtype,
        }
    abs_data = np.abs(data)
    peak = float(abs_data.max())
    rms = float(np.sqrt(np.mean(data.astype(np.float64) ** 2)))
    peak_dbfs = 20.0 * math.log10(peak) if peak > 0 else float("-inf")
    rms_dbfs = 20.0 * math.log10(rms) if rms > 0 else float("-inf")
    duration_s = frames / float(sr)
    if peak == 0:
        status = "silent"
    elif peak >= 1.0:
        status = "clipped"
    elif peak_dbfs < -60:
        status = "silent"
    else:
        status = "clean"
    activity = _audio_activity(data, sr)
    return {
        "status": status,
        "size_bytes": size,
        "sample_rate": sr,
        "channels": channels,
        "subtype": subtype,
        "frames": frames,
        "duration_s": duration_s,
        "peak_dbfs": peak_dbfs,
        "rms_dbfs": rms_dbfs,
        **activity,
    }


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
        "--osc-host",
        type=str,
        default="127.0.0.1",
        help="Host for OSC /path delivery to the analyzer (default 127.0.0.1).",
    )
    parser.add_argument(
        "--osc-port",
        type=int,
        default=11000,
        help=(
            "UDP port the analyzer's [udpreceive] is bound to (default 11000, "
            "matches the .amxd's default OSC Port parameter). Must match the "
            "device instance's OSC Port value in Live."
        ),
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

    # Phase timing — track wall-clock at every transition so we can attribute
    # any duration overshoot in the WAV to a specific MCP / patch step.
    timeline: list[tuple[str, float]] = []
    t0 = time.monotonic()

    def mark(label: str) -> None:
        timeline.append((label, time.monotonic() - t0))

    try:
        mark("start")
        info = _send("ableton_session", "info")
        bpm = float(info.result["tempo"])  # type: ignore[index]
        print(f"[harness] session tempo: {bpm:.3f} BPM")

        record_window_s = _seconds_for_bars(args.bars, bpm)
        print(
            f"[harness] {args.bars} bars @ {bpm:.2f} BPM = "
            f"{record_window_s:.3f} s of audio"
        )

        # Pre-flight: probe the device. Confirms we have the analyzer (not
        # some other device at that slot), reads its actual OSC Port value
        # so we send /path to the right UDP socket, and surfaces parameter
        # short names so a mismatch with the harness's expectations fails
        # loud here, not silently mid-capture.
        params = _probe_device(args.track_index, args.device_index)
        print(
            f"[harness] device at track {args.track_index} / device "
            f"{args.device_index} exposes {len(params)} parameters: "
            f"{sorted(params.keys())}"
        )
        missing = [name for name in ("Arm", "Port") if name not in params]
        if missing:
            print(
                f"[harness] ABORT: expected analyzer short-name parameters "
                f"missing: {missing}. Either this slot doesn't hold "
                f"HallucinoteAnalyzer.amxd, or its parameters aren't set to "
                f"'Automated and Stored' (Stored-Only hides them from the "
                f"Remote Script API).",
                file=sys.stderr,
            )
            return 5

        device_port = int(float(params["Port"]["value"]))
        if "--osc-port" in (argv or sys.argv[1:]):
            osc_port = args.osc_port
            print(
                f"[harness] OSC port override: using --osc-port={osc_port} "
                f"(device's OSC Port parameter = {device_port})"
            )
        else:
            osc_port = device_port
            print(f"[harness] OSC port from device: {osc_port}")

        arm_value = float(params["Arm"]["value"])
        if arm_value != 0:
            print(
                f"[harness] WARNING: Arm starts at {arm_value} (expected 0). "
                f"Pre-existing recording in progress? Will force disarm before run."
            )
            _send(
                "ableton_device",
                "set_parameter",
                track_index=args.track_index,
                device_index=args.device_index,
                parameter_name="Arm",
                value="0.0",
            )
            time.sleep(0.1)

        # 1) Point the analyzer at the WAV path via OSC. Live parameters are
        # float / int / enum only — the path can't be a Live parameter, so the
        # patch listens on UDP for `/path <symbol>`. Must arrive BEFORE the
        # rising edge of record_arm (the patch's no-path guard refuses to arm
        # otherwise).
        resolved = str(track_wav.resolve())
        _osc_send(args.osc_host, osc_port, "/path", resolved)
        mark("osc-path-sent")
        print(
            f"[harness] OSC /path → {args.osc_host}:{osc_port} "
            f"= {resolved}"
        )

        # Small settle so the patch retains /path before the param write.
        time.sleep(0.05)

        # 2) Arm the recorder. The .amxd's live.toggle exposes short name "Arm"
        # (long name is "Record Arm"; Live's Remote Script API surfaces parameters
        # by short name, which is what set_parameter must address).
        mark("arm-1-sent-before")
        _send(
            "ableton_device",
            "set_parameter",
            track_index=args.track_index,
            device_index=args.device_index,
            parameter_name="Arm",
            value="1.0",
        )
        mark("arm-1-sent-after")

        # 3) Pre-roll so sfrecord~ has the file open before t=0.
        time.sleep(args.pre_roll_s)

        # 4) Seek to bar 1, beat 0; start transport.
        mark("play-sent-before")
        _send("ableton_session", "seek", bar=1, beat=0.0)
        _send("ableton_session", "play")
        mark("play-sent-after")
        print(f"[harness] transport started; recording {record_window_s:.3f} s")

        # 5) Sleep the recording window.
        time.sleep(record_window_s)

        # 6) Stop transport, post-roll, disarm.
        mark("stop-sent-before")
        _send("ableton_session", "stop")
        mark("stop-sent-after")
        time.sleep(args.post_roll_s)
        mark("arm-0-sent-before")
        _send(
            "ableton_device",
            "set_parameter",
            track_index=args.track_index,
            device_index=args.device_index,
            parameter_name="Arm",
            value="0.0",
        )
        mark("arm-0-sent-after")

    except LiveConnectionError as exc:
        print(f"[harness] could not reach Live: {exc}", file=sys.stderr)
        return 2
    except RuntimeError as exc:
        print(f"[harness] protocol error: {exc}", file=sys.stderr)
        return 3

    mark("done")
    print("[harness] timeline (seconds from start):")
    for label, t in timeline:
        print(f"  {t:7.3f}s  {label}")

    print(f"[harness] done. inspecting: {track_wav}")
    report = _inspect_wav(track_wav)
    print(f"[harness] WAV report: {report}")

    # Attribute the WAV's actual recording window to the phase timeline.
    # arm-1-sent-after → arm-0-sent-before is the harness's expected
    # arm-high window. The WAV's audio_start_s/audio_end_s shows where
    # audible content actually sits in the file.
    by_label = {label: t for label, t in timeline}
    arm_high_window = by_label.get("arm-0-sent-before", 0.0) - by_label.get("arm-1-sent-after", 0.0)
    play_window = by_label.get("stop-sent-before", 0.0) - by_label.get("play-sent-after", 0.0)
    print(
        f"[harness] expected arm-high (harness wall-clock): {arm_high_window:.3f} s; "
        f"transport-play window: {play_window:.3f} s; "
        f"WAV duration: {report.get('duration_s', 0.0):.3f} s; "
        f"audio active: [{report.get('audio_start_s')!r}, {report.get('audio_end_s')!r}] s"
    )

    status = report["status"]
    if status == "missing":
        print(
            "[harness] NO-GO: expected WAV not found on disk. Likely causes: "
            "(a) /path OSC never reached udpreceive (wrong port, firewall, "
            "OSC-route mismatch), (b) record_arm rising-edge guard fired "
            "(no-path or no-parent-dir), (c) sfrecord~'s `open` never "
            "received the path. Check Max console for [print "
            "HallucinoteAnalyzer] lines.",
            file=sys.stderr,
        )
        return 4
    if status == "empty":
        print(
            "[harness] NO-GO: WAV header exists but no audio frames. "
            "Likely: sfrecord~ opened the file but `record 1` never fired, "
            "or fired and immediately got `record 0`. Check the patch's "
            "record_arm change handler.",
            file=sys.stderr,
        )
        return 6
    if status == "silent":
        print(
            "[harness] NO-GO: WAV has audio frames but is silent "
            f"(peak {report.get('peak_dbfs')!r} dBFS). Likely: the audio "
            "inlet isn't reaching sfrecord~. Check the patch's signal "
            "flow — `plugin~` → `sfrecord~` connection, or whether the "
            "device is post-fader / pre-fader vs where the audio "
            "actually lives on this track.",
            file=sys.stderr,
        )
        return 7
    if status == "clipped":
        print(
            "[harness] WARNING: peak ≥ 0 dBFS — signal too hot. PDC math "
            "will still work but consider attenuating the source.",
            file=sys.stderr,
        )
    if status == "unreadable":
        print(
            f"[harness] NO-GO: file exists but soundfile can't parse it: "
            f"{report.get('error')!r}. Likely: sfrecord~ wrote a corrupt "
            f"header (didn't get `close`?), or wrong `samptype`.",
            file=sys.stderr,
        )
        return 8
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
