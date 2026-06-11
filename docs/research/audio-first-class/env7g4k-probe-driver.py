"""ENV-7G4K chunk 01 step 0 — probe driver (re-record overwrite + group-host).

Scratch tooling per lom-probe-driver.py precedent; the verdicts in
lom-probe-results.md are the artifact. Wire calls carry
allow_version_mismatch=True: the running Remote Script (a5479db86125) predates
this branch but its ableton_probe surface is the one the original 195 probe
records were executed against.

Run from hallucinote_mcp/:
    uv run python /tmp/env7g4k_probes.py overwrite   # probe B: re-record overwrite (master volume)
    uv run python /tmp/env7g4k_probes.py group       # probe A: group-host recording (needs a group track)

Results: JSON lines appended to /tmp/env7g4k_probe_results.jsonl
"""
from __future__ import annotations

import json
import sys
import time

from hallucinote_mcp import client, wire

OUT = "/tmp/env7g4k_probe_results.jsonl"


def probe(name: str, action: str, quiet: bool = False, **params):
    resp = client.send(
        wire.Request(
            tool="ableton_probe",
            action=action,
            params=params,
            allow_version_mismatch=True,
        ),
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
    }
    with open(OUT, "a") as f:
        f.write(json.dumps(rec) + "\n")
    if not quiet:
        status = "OK " if resp.ok else "ERR"
        detail = json.dumps(resp.result)[:160] if resp.ok else (resp.error or "")[:160]
        print(f"[{status}] {name}: {detail}", flush=True)
    return rec


def get(path: str):
    return probe(f"get {path}", "get", quiet=True, path=path)


def gval(path: str):
    r = get(path)
    return r["result"]["value"] if r["ok"] else None


def setp(path: str, value, quiet: bool = True):
    return probe(f"set {path}={value!r}", "set", quiet=quiet, path=path, value=value)


def callp(path: str, method: str, name: str | None = None):
    return probe(name or f"call {path}.{method}()", "call", path=path, method=method)


def settle(path: str, want, timeout: float = 3.0):
    """Probe-10 discipline: transport-adjacent Song state applies async — poll."""
    t0 = time.time()
    while time.time() - t0 < timeout:
        if gval(path) == want:
            return time.time() - t0
        time.sleep(0.05)
    return None


def record_ramp(param: str, lo: float, hi: float, label: str,
                steps: int = 40, step_s: float = 0.1):
    """Probe-4 recipe: record a scripted lo->hi ramp into arrangement automation."""
    print(f"--- {label}: record ramp {lo} -> {hi} over {steps * step_s:.1f}s", flush=True)
    setp("song.current_song_time", 0.0)
    setp("song.session_automation_record", True)
    setp("song.record_mode", True)
    dt = settle("song.record_mode", True)
    if dt is None:
        raise SystemExit(f"{label}: record_mode never settled — aborting")
    print(f"    record_mode settled in {dt:.2f}s", flush=True)
    callp(param, "begin_gesture", name=f"{label} begin_gesture")
    callp("song", "start_playing", name=f"{label} start_playing")
    try:
        for i in range(steps + 1):
            v = lo + (hi - lo) * i / steps
            setp(param + ".value", v)
            time.sleep(step_s)
    finally:
        callp(param, "end_gesture", name=f"{label} end_gesture")
        callp("song", "stop_playing", name=f"{label} stop_playing")
        setp("song.record_mode", False)
        settle("song.record_mode", False)
        setp("song.session_automation_record", False)
    st = gval(param + ".automation_state")
    print(f"    automation_state after {label}: {st}", flush=True)
    return st


def playback_samples(param: str, label: str, secs: float = 4.4, every: float = 0.2):
    """Play from beat 0 with no writer attached; sample (song_time, value)."""
    setp("song.current_song_time", 0.0)
    callp("song", "start_playing", name=f"{label} playback start")
    out = []
    t0 = time.time()
    while time.time() - t0 < secs:
        st = gval("song.current_song_time")
        v = gval(param + ".value")
        out.append((st, v))
        time.sleep(every)
    callp("song", "stop_playing", name=f"{label} playback stop")
    setp("song.current_song_time", 0.0)
    print(f"    {label} samples (beat -> value):", flush=True)
    for st, v in out:
        print(f"      {st:6.2f} -> {v:.4f}", flush=True)
    probe(f"{label} samples", "get", quiet=True, path=param + ".value")
    with open(OUT, "a") as f:
        f.write(json.dumps({"probe": f"{label} sample-series", "samples": out}) + "\n")
    return out


def trend(samples):
    inc = sum(1 for a, b in zip(samples, samples[1:]) if b[1] > a[1] + 1e-4)
    dec = sum(1 for a, b in zip(samples, samples[1:]) if b[1] < a[1] - 1e-4)
    return inc, dec, len(samples) - 1


def phase_overwrite():
    param = "song.master_track.mixer_device.volume"
    print("== ENV-7G4K probe B: re-record overwrite (master volume) ==", flush=True)
    print(f"initial value={gval(param + '.value')} "
          f"automation_state={gval(param + '.automation_state')}", flush=True)

    st1 = record_ramp(param, 0.30, 0.90, "ramp1-up")
    s1 = playback_samples(param, "after-ramp1")
    st1_post = gval(param + ".automation_state")

    st2 = record_ramp(param, 0.90, 0.30, "ramp2-down")
    s2 = playback_samples(param, "after-ramp2")
    st2_post = gval(param + ".automation_state")

    inc1, dec1, n1 = trend(s1)
    inc2, dec2, n2 = trend(s2)
    print("== verdict inputs ==", flush=True)
    print(f"  ramp1: automation_state={st1} (post-playback {st1_post}); "
          f"{inc1}/{n1} steps ascending, {dec1} descending", flush=True)
    print(f"  ramp2: automation_state={st2} (post-playback {st2_post}); "
          f"{dec2}/{n2} steps descending, {inc2} ascending", flush=True)
    early1 = [v for t, v in s1 if t is not None and t < 3.0]
    early2 = [v for t, v in s2 if t is not None and t < 3.0]
    if early1 and early2:
        print(f"  early-span (beat<3) means: ramp1={sum(early1)/len(early1):.3f} "
              f"vs ramp2={sum(early2)/len(early2):.3f} "
              f"(up-ramp low / down-ramp high == overwrite)", flush=True)


def phase_group():
    r = get("song.tracks")
    v = r["result"]["value"]
    n = v["total"] if isinstance(v, dict) and "__truncated__" in v else len(v)
    gi = None
    for i in range(n):
        if gval(f"song.tracks[{i}].is_foldable"):
            gi = i
            break
    if gi is None:
        raise SystemExit("no group track in the set — group a track in Live (Cmd+G), then rerun")
    name = gval(f"song.tracks[{gi}].name")
    param = f"song.tracks[{gi}].mixer_device.volume"
    print(f"== ENV-7G4K probe A: group-host recording on tracks[{gi}] ({name!r}) ==", flush=True)
    print(f"initial automation_state={gval(param + '.automation_state')}", flush=True)
    st = record_ramp(param, 0.40, 0.85, "group-ramp")
    s = playback_samples(param, "group-playback")
    inc, dec, n2 = trend(s)
    print("== verdict inputs ==", flush=True)
    print(f"  automation_state={st}; {inc}/{n2} steps ascending, {dec} descending", flush=True)


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "overwrite"
    {"overwrite": phase_overwrite, "group": phase_group}[mode]()
