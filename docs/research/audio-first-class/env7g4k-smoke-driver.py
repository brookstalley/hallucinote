"""ENV-7G4K S-7 / ENV-9P4T smoke driver — performed automation end-to-end.

Run from the repo root: uv run python /tmp/env7g4k_smoke.py
Live must be open on a set with: tracks[0] = a group track, >=1 return,
an Auto Filter on the master chain. Versions must match (no bypass).

Drives the REAL surfaces: plan_push_performed_automation → wire-execute the
ONE batched ``perform_batch`` ToolCall (ENV-9P4T: all changed arcs recorded
in a single transport pass with per-parameter windowing) → apply_push_results
→ re-plan (all-skip) → edit one arc → re-plan (only it, still batched) →
execute → final all-skip. This doubles as the ENV-9P4T batched-perform live
smoke (the two-overlapping-window probe in
.prawduct/artifacts/plans/ENV-9P4T/archive/api-notes.md is the focused complement).
"""
from __future__ import annotations


from hallucinote.db import init_db, mutations as M
from hallucinote.sync import push
from hallucinote_mcp import client, wire

DB = "/tmp/env7g4k_smoke.db"


def send(tool, action, **params):
    # No read_timeout override — let client.send auto-resolve from the
    # (tool, action) policy (perform_batch → unbounded). A hard-coded
    # override here would mask a wrong default on the real push path, the
    # exact trap the read-timeout learning was written about.
    return client.send(
        wire.Request(tool=tool, action=action, params=params),
        connect_timeout=5,
    )


def probe_get(path):
    r = send("ableton_probe", "get", path=path)
    if not r.ok:
        raise SystemExit(f"probe get {path} failed: {r.error}")
    return r.result["value"]


def find_master_device_param(name_exact):
    n = len(probe_get("song.master_track.devices[0].parameters"))
    for i in range(n):
        if probe_get(f"song.master_track.devices[0].parameters[{i}].name") == name_exact:
            lo = probe_get(f"song.master_track.devices[0].parameters[{i}].min")
            hi = probe_get(f"song.master_track.devices[0].parameters[{i}].max")
            return name_exact, float(lo), float(hi)
    raise SystemExit(f"master device has no parameter named {name_exact!r}")


def show_plan(tag, plan):
    print(f"--- {tag}: {len(plan.calls)} call(s)")
    for c in plan.calls:
        print(f"    CALL {c.key}: {c.purpose}")
    for n in plan.notes:
        print(f"    NOTE {n}")


def execute(plan):
    results = []
    for c in plan.calls:
        params = {k: v for k, v in c.args.items() if k != "action"}
        resp = send(c.tool, c.args["action"], **params)
        res = resp.result or {}
        if "arcs" in res:  # perform_batch fan-out
            states = {a.get("arc_id"): a.get("automation_state")
                      for a in res["arcs"]}
            print(f"    EXEC {c.key}: ok={resp.ok} arc_states={states}"
                  + (f" error={resp.error}" if resp.error else ""))
        else:
            print(f"    EXEC {c.key}: ok={resp.ok} "
                  f"automation_state={res.get('automation_state')}"
                  + (f" error={resp.error}" if resp.error else ""))
        results.append({
            "key": c.key, "ok": resp.ok, "tool": c.tool,
            "result": resp.result, "error": resp.error,
        })
    return results


def main():
    conn = init_db(DB)
    song = M.create_song(conn, name="s7-smoke", key="Am")
    session = M.create_ableton_session(conn, song_id=song, name="s7")

    master = M.create_track(conn, song_id=song, track_index=0, name="Master",
                            kind="master")
    group = M.create_track(conn, song_id=song, track_index=1, name="Bus",
                           kind="group")
    M.link_db_to_ableton(conn, session_id=session, db_kind="track",
                         db_id=group, ableton_index=1)
    ret = M.create_return(conn, song_id=song, name="A-Reverb", position=1)
    M.link_db_to_ableton(conn, session_id=session, db_kind="return",
                         db_id=ret, ableton_index=1)
    chain = M.create_device_chain(conn, parent_track_id=master, position=0)
    dev = M.create_device(conn, chain_id=chain, position=1,
                          kind="AutoFilter2", display_name="Auto Filter")
    M.link_db_to_ableton(conn, session_id=session, db_kind="device",
                         db_id=dev, ableton_index=1)

    pname, plo, phi = find_master_device_param("Frequency")
    sweep_lo = plo + 0.3 * (phi - plo)
    sweep_hi = plo + 0.9 * (phi - plo)
    print(f"master device param {pname!r}: raw range [{plo:g}, {phi:g}], "
          f"sweeping {sweep_lo:g} -> {sweep_hi:g}")

    arcs = {}

    arcs["master_vol"] = M.create_envelope(
        conn, song_id=song, target_kind="mixer_volume", target_track_id=master)
    M.replace_breakpoints(conn, envelope_id=arcs["master_vol"], breakpoints=[
        {"time_beats": 0.0, "value": 0.85},
        {"time_beats": 8.0, "value": 0.5, "curve_kind": "slow"},
        {"time_beats": 16.0, "value": 0.85},
    ])

    arcs["group_vol"] = M.create_envelope(
        conn, song_id=song, target_kind="mixer_volume", target_track_id=group)
    M.replace_breakpoints(conn, envelope_id=arcs["group_vol"], breakpoints=[
        {"time_beats": 0.0, "value": 0.5},
        {"time_beats": 8.0, "value": 0.85},
    ])

    arcs["group_send"] = M.create_envelope(
        conn, song_id=song, target_kind="send_level",
        target_track_id=group, target_send_return_id=ret)
    M.replace_breakpoints(conn, envelope_id=arcs["group_send"], breakpoints=[
        {"time_beats": 0.0, "value": 0.0},
        {"time_beats": 8.0, "value": 0.6},
    ])

    arcs["return_vol"] = M.create_envelope(
        conn, song_id=song, target_kind="return_mixer_volume",
        target_send_return_id=ret)
    M.replace_breakpoints(conn, envelope_id=arcs["return_vol"], breakpoints=[
        {"time_beats": 0.0, "value": 0.85},
        {"time_beats": 8.0, "value": 0.6},
    ])

    arcs["master_filter"] = M.create_envelope(
        conn, song_id=song, target_kind="device_parameter",
        target_device_id=dev, parameter_path=pname)
    M.replace_breakpoints(conn, envelope_id=arcs["master_filter"], breakpoints=[
        {"time_beats": 0.0, "value": sweep_hi},
        {"time_beats": 8.0, "value": sweep_lo, "curve_kind": "slow"},
        {"time_beats": 16.0, "value": sweep_hi, "curve_kind": "fast"},
    ])

    def plan():
        return push.plan_push_performed_automation(
            conn, song_id=song, session_id=session)

    print("== PASS 1: initial perform (5 arcs in ONE batched pass, "
          "transport will play) ==")
    p1 = plan()
    show_plan("plan-1", p1)
    if len(p1.calls) != 1:
        raise SystemExit(f"FAIL: expected 1 batched call, got {len(p1.calls)}")
    batch_arcs = p1.calls[0].args["arcs"]
    if len(batch_arcs) != 5:
        raise SystemExit(f"FAIL: expected 5 arcs in the batch, "
                         f"got {len(batch_arcs)}")
    r1 = execute(p1)
    push.apply_push_results(conn, r1, session_id=session)
    arc_states = {a["arc_id"]: a.get("automation_state")
                  for a in (r1[0]["result"] or {}).get("arcs", [])}
    bad = {k: v for k, v in arc_states.items() if v != 1}
    print(f"    pass-1 arc automation_states: {arc_states}")
    if bad:
        raise SystemExit(f"FAIL: non-1 automation_state: {bad}")

    print("== PASS 2: idempotent re-push (must skip all 5) ==")
    p2 = plan()
    show_plan("plan-2", p2)
    if p2.calls:
        raise SystemExit(f"FAIL: pass 2 emitted {len(p2.calls)} call(s)")
    if sum("skipped (unchanged)" in n for n in p2.notes) != 5:
        raise SystemExit("FAIL: pass 2 did not report all 5 skips")

    print("== PASS 3: edit master_vol arc -> only it re-performs ==")
    M.replace_breakpoints(conn, envelope_id=arcs["master_vol"], breakpoints=[
        {"time_beats": 0.0, "value": 0.85},
        {"time_beats": 8.0, "value": 0.3, "curve_kind": "slow"},  # deeper duck
        {"time_beats": 16.0, "value": 0.85},
    ])
    p3 = plan()
    show_plan("plan-3", p3)
    if len(p3.calls) != 1:
        raise SystemExit("FAIL: pass 3 should emit exactly one batched call")
    p3_arcs = p3.calls[0].args["arcs"]
    if [a["arc_id"] for a in p3_arcs] != [arcs["master_vol"]]:
        raise SystemExit("FAIL: pass 3 should re-perform exactly master_vol")
    r3 = execute(p3)
    push.apply_push_results(conn, r3, session_id=session)
    r3_arcs = (r3[0]["result"] or {}).get("arcs", [])
    if not r3_arcs or r3_arcs[0].get("automation_state") != 1:
        raise SystemExit("FAIL: re-perform automation_state != 1")

    print("== PASS 4: final no-op ==")
    p4 = plan()
    show_plan("plan-4", p4)
    if p4.calls:
        raise SystemExit("FAIL: pass 4 emitted calls")

    n_events = conn.execute(
        "SELECT COUNT(*) c FROM events WHERE kind='automation_performed'",
    ).fetchone()["c"]
    print(f"== S-7 PASS == performed-state events: {n_events} (expect 6: 5 + 1 re-perform)")


if __name__ == "__main__":
    main()
