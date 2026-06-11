"""AUD-1M4V chunk 02 — LOM probe driver (scratch tooling; results are the artifact).

Drives the ableton_probe bridge tool over TCP per the build-plan probe list.
Run from hallucinote_mcp/: uv run python /tmp/aud1m4v_probes.py [static|record|autorec]

Results: JSON lines appended to /tmp/aud1m4v_probe_results.jsonl
"""
from __future__ import annotations

import json
import sys
import time

from hallucinote_mcp import client, wire

WAV = "/tmp/aud1m4v_probe.wav"
OUT = "/tmp/aud1m4v_probe_results.jsonl"


def probe(name: str, action: str, quiet: bool = False, **params):
    resp = client.send(
        wire.Request(tool="ableton_probe", action=action, params=params),
        connect_timeout=5,
        read_timeout=30,
    )
    rec = {
        "probe": name,
        "action": action,
        "params": params,
        "ok": resp.ok,
        "result": resp.result,
        "error": resp.error,
        "warnings": resp.warnings,
    }
    with open(OUT, "a") as f:
        f.write(json.dumps(rec) + "\n")
    if not quiet:
        status = "OK " if resp.ok else "ERR"
        detail = (
            json.dumps(resp.result)[:200] if resp.ok else (resp.error or "")[:200]
        )
        print(f"[{status}] {name}: {detail}")
    return rec


def get(path, **kw):
    return probe(f"get {path}", "get", path=path, **kw)


def setp(path, value, name=None):
    return probe(name or f"set {path}={value!r}", "set", path=path, value=value)


def callp(name, path, method, args=None, kwargs=None, then=None):
    params = {"path": path, "method": method}
    if args is not None:
        params["args"] = args
    if kwargs is not None:
        params["kwargs"] = kwargs
    if then is not None:
        params["then"] = then
    return probe(name, "call", **params)


def track_count():
    r = get("song.tracks", quiet=True)
    v = r["result"]["value"]
    return v["total"] if isinstance(v, dict) and "__truncated__" in v else len(v)


def find_or_make_probe_track():
    n = track_count()
    for i in range(n):
        r = get(f"song.tracks[{i}].name", quiet=True)
        if r["ok"] and r["result"]["value"] == "PROBE-AUDIO":
            return i
    callp("create audio track", "song", "create_audio_track", args=[-1])
    idx = track_count() - 1
    setp(f"song.tracks[{idx}].name", "PROBE-AUDIO", name="name probe track")
    return idx


def phase_static():
    get("application.major_version")
    get("application.minor_version")
    get("song.tempo")
    ti = find_or_make_probe_track()
    base = f"song.tracks[{ti}]"
    print(f"-- probe track at index {ti} --")

    # Inventory snapshots (dir-diff source material; full payload in JSONL)
    probe("describe Song", "describe", quiet=True, path="song")
    probe("describe Track", "describe", quiet=True, path=base)
    probe("describe ClipSlot", "describe", quiet=True, path=f"{base}.clip_slots[0]")
    probe("describe MasterTrack", "describe", quiet=True, path="song.master_track")
    print("[OK ] inventory describes captured (quiet)")

    # P1a session audio clip
    callp("P1a session create_audio_clip", f"{base}.clip_slots[0]",
          "create_audio_clip", args=[WAV])
    get(f"{base}.clip_slots[0].clip.file_path")
    get(f"{base}.clip_slots[0].clip.warping")
    get(f"{base}.clip_slots[0].clip.length")

    # P1b arrangement audio clip
    callp("P1b arrangement create_audio_clip", base,
          "create_audio_clip", args=[WAV, 16.0])

    # P1c error shapes
    callp("P1c create on MIDI track (expect err)", "song.tracks[0].clip_slots[0]",
          "create_audio_clip", args=[WAV])
    callp("P1c bad path (expect err)", f"{base}.clip_slots[1]",
          "create_audio_clip", args=["/tmp/does-not-exist.wav"])

    # P2 arrangement envelope gate
    callp("P2 automation_envelope on arrangement clip",
          f"{base}.arrangement_clips[0]", "automation_envelope",
          args=[{"$path": f"{base}.mixer_device.volume"}])
    callp("P2 create_automation_envelope on arrangement clip",
          f"{base}.arrangement_clips[0]", "create_automation_envelope",
          args=[{"$path": f"{base}.mixer_device.volume"}])

    # P3 session AUDIO clip mixer envelope end-to-end (ENV-8H1T melt test)
    callp("P3 create env + insert_step", f"{base}.clip_slots[0].clip",
          "create_automation_envelope",
          args=[{"$path": f"{base}.mixer_device.volume"}],
          then=[{"method": "insert_step", "args": [0.0, 4.0, 0.5]}])
    callp("P3 value_at_time readback", f"{base}.clip_slots[0].clip",
          "automation_envelope",
          args=[{"$path": f"{base}.mixer_device.volume"}],
          then=[{"method": "value_at_time", "args": [2.0]}])

    # P6 undocumented envelope-event API (session clip)
    callp("P6 events_in_range", f"{base}.clip_slots[0].clip",
          "automation_envelope",
          args=[{"$path": f"{base}.mixer_device.volume"}],
          then=[{"method": "events_in_range", "args": [0.0, 4.0]}])

    # P6b warp markers
    get(f"{base}.clip_slots[0].clip.warp_markers")
    callp("P6b add_warp_marker dict", f"{base}.clip_slots[0].clip",
          "add_warp_marker", args=[{"beat_time": 1.0}])
    get(f"{base}.clip_slots[0].clip.warp_markers")

    # count-in settability (a probe finding either way)
    get("song.count_in_duration")
    setp("song.count_in_duration", 2, name="count_in_duration settable?")


def phase_record():
    ti = find_or_make_probe_track()
    base = f"song.tracks[{ti}]"
    get(f"{base}.available_input_routing_types")
    get(f"{base}.current_monitoring_state")
    setp(f"{base}.current_monitoring_state", 2, name="monitoring OFF")
    setp(f"{base}.arm", True, name="arm probe track")
    callp("P5 fire(record_length=8.0)", f"{base}.clip_slots[2]", "fire",
          kwargs={"record_length": 8.0})
    time.sleep(1.0)
    get(f"{base}.clip_slots[2].is_recording")
    r = get(f"{base}.clip_slots[2].has_clip")
    if r["ok"] and r["result"]["value"]:
        get(f"{base}.clip_slots[2].clip.is_recording")
        get(f"{base}.clip_slots[2].clip.file_path")
    deadline = time.time() + 25
    while time.time() < deadline:
        r = get(f"{base}.clip_slots[2].is_recording", quiet=True)
        if r["ok"] and not r["result"]["value"]:
            break
        time.sleep(2)
    callp("stop transport", "song", "stop_playing")
    get(f"{base}.clip_slots[2].clip.file_path")
    get(f"{base}.clip_slots[2].clip.is_audio_clip")
    get(f"{base}.clip_slots[2].clip.length")
    setp(f"{base}.arm", False, name="disarm")


def phase_autorec():
    """B-critical: scripted master/group automation write via record_mode."""
    vol = "song.master_track.mixer_device.volume"
    get(f"{vol}.automation_state")
    before = get(f"{vol}.value")
    v0 = before["result"]["value"] if before["ok"] else 0.85

    setp("song.session_automation_record", True, name="automation arm ON")
    setp("song.record_mode", True, name="arrangement record ON")
    callp("begin_gesture", vol, "begin_gesture")
    callp("start_playing", "song", "start_playing")
    t0 = time.time()
    steps = 40  # ~4s ramp at 100ms
    for i in range(steps):
        target = v0 - 0.25 + 0.5 * (i / (steps - 1))
        target = max(0.0, min(1.0, target))
        setp(f"{vol}.value", target, name=f"ramp[{i}]") if i % 10 == 0 else probe(
            f"ramp[{i}]", "set", quiet=True, path=f"{vol}.value", value=target)
        time.sleep(max(0.0, (t0 + 0.1 * (i + 1)) - time.time()))
    callp("end_gesture", vol, "end_gesture")
    callp("stop_playing", "song", "stop_playing")
    setp("song.record_mode", False, name="arrangement record OFF")
    get(f"{vol}.automation_state")
    setp(f"{vol}.value", v0, name="restore master volume")
    get(f"{vol}.automation_state")
    # group-track repeat is run manually after reviewing master results


if __name__ == "__main__":
    phase = sys.argv[1] if len(sys.argv) > 1 else "static"
    {"static": phase_static, "record": phase_record, "autorec": phase_autorec}[phase]()
    print("results appended to", OUT)
