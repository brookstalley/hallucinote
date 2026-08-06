#!/usr/bin/env python3
"""ARR-PROJ Chunk-1 Live spike — arrangement-as-projection proof on ONE track.

Throwaway / recorded probe sequence (build-plan Chunk-1 deliverable). Drives the
REAL alien set's Drums track through the projection model:

    clear (existing per-clip delete wire) -> create_midi_clip + set_notes (create
    handler, atomic create+fill) -> fresh read-back -> compare to DB collapsed set
    -> repeat (idempotence).

It deliberately keeps every note PAYLOAD out of the agent's context: only counts
and per-clip OK/MISMATCH rows are printed. Notes never leave this process.

Run from the PRIMARY checkout with Ableton open on the alien set and the
hallucinote-mcp server respawned (version-matched). Non-destructive in the sense
that a CORRECT idempotent rebuild of a faithful arrangement returns Drums to the
identical state it started in.

    .venv/bin/python .prawduct/artifacts/plans/ARR-PROJ/chunk1-spike.py
"""
from __future__ import annotations

import os
import sys
import time

ROOT = "<repo-root>"
# Belt-and-suspenders against the worktree import gotcha (we are in primary, but
# force this checkout's src dirs to the front regardless).
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "hallucinote_mcp/src"))

from hallucinote_mcp import client                       # noqa: E402
from hallucinote_mcp.wire import Request                 # noqa: E402
from hallucinote.db.connection import init_db            # noqa: E402
from hallucinote.db import queries as Q                  # noqa: E402
from hallucinote.sync.geometry import _position_bar_to_beats  # noqa: E402
from hallucinote.sync.push._core import _notes_for_mcp   # noqa: E402

DB = "<songs-workspace>/songs/alien/alien-compose--alien.db"
TRACK_INDEX = 1          # Drums (1-based MCP index)
TRACK_NAME = "Drums"
EPS = 1e-6


def mcp(tool: str, action: str, **params):
    resp = client.send(Request(tool=tool, action=action, params=params))
    if not resp.ok:
        raise RuntimeError(f"{tool}.{action} failed: {resp.error}")
    return resp.result


def list_arr(ti: int):
    return mcp("ableton_clip", "list", track_index=ti, location="arrangement")["clips"]


def note_api_count(ti: int, ci: int) -> int:
    res = mcp("ableton_note", "list", track_index=ti, location="arrangement", clip_index=ci)
    return len(res["notes"])


def collapsed(mcp_notes) -> int:
    return len({(n["pitch"], round(n["start_time"], 6)) for n in mcp_notes})


def build_spec(conn, song_id):
    ts = Q.get_time_signature_map(conn, song_id)
    rows = [r for r in Q.get_arrangement_for_song(conn, song_id)
            if r["track_name"] == TRACK_NAME]
    spec = []
    for r in rows:
        start_beats = _position_bar_to_beats(r["start_bar"], ts)
        clip = Q.get_clip(conn, r["clip_id"])
        length = float(clip["length_beats"])
        notes = _notes_for_mcp(Q.get_notes_for_clip(conn, r["clip_id"]))
        spec.append({
            "name": r["clip_name"],
            "start": start_beats,
            "length": length,
            "notes": notes,
            "raw": len(notes),
            "collapsed": collapsed(notes),
        })
    spec.sort(key=lambda s: s["start"])
    return spec


def rebuild_and_verify(spec, label):
    t0 = time.time()
    # CLEAR — delete descending (indices renumber down after each delete).
    clips = list_arr(TRACK_INDEX)
    n_before = len(clips)
    for ci in range(len(clips), 0, -1):
        mcp("ableton_clip", "delete", track_index=TRACK_INDEX,
            location="arrangement", clip_index=ci)
    after_clear = list_arr(TRACK_INDEX)
    if len(after_clear) != 0:
        print(f"  !! CLEAR INCOMPLETE: {len(after_clear)} clip(s) survived")
    t_clear = time.time() - t0

    # CREATE + FILL — atomic create_midi_clip + set_notes per placement.
    for s in spec:
        mcp("ableton_clip", "create", track_index=TRACK_INDEX, location="arrangement",
            kind="midi", start_beats=s["start"], length=s["length"],
            name=s["name"], notes=s["notes"])
    t_build = time.time() - t0 - t_clear

    # VERIFY — fresh read-back (a NEW list call, not inline after the writes).
    live = list_arr(TRACK_INDEX)
    by_start = {round(float(c["start_beats"]), 3): c for c in live}
    all_ok = True
    rows = []
    for s in spec:
        c = by_start.get(round(s["start"], 3))
        if c is None:
            rows.append((s["name"], s["raw"], s["collapsed"], "MISSING", "FAIL"))
            all_ok = False
            continue
        nc = c["note_count"]
        match = (nc == s["collapsed"]) and (abs(c["start_beats"] - s["start"]) < EPS)
        all_ok = all_ok and match
        rows.append((s["name"], s["raw"], s["collapsed"], nc, "OK" if match else "MISMATCH"))

    print(f"=== {label}  (cleared {n_before}, built {len(spec)}; "
          f"clear={t_clear:.1f}s build={t_build:.1f}s) ===")
    print(f"  {'section':<18}{'db_raw':>7}{'db_coll':>8}{'live_nc':>8}  result")
    for name, raw, coll, nc, res in rows:
        print(f"  {name:<18}{raw:>7}{coll:>8}{str(nc):>8}  {res}")
    print(f"  ALL_MATCH={all_ok}")
    return all_ok, rows


def main():
    conn = init_db(DB)
    song_id = conn.execute("SELECT id FROM songs LIMIT 1").fetchone()["id"]
    spec = build_spec(conn, song_id)

    base = list_arr(TRACK_INDEX)
    print(f"BASELINE: {len(base)} Drums arrangement clips; "
          f"note_counts={[c['note_count'] for c in base]}")
    print(f"DB spec : {len(spec)} placements; "
          f"raw={[s['raw'] for s in spec]}")
    print(f"          collapsed={[s['collapsed'] for s in spec]}")
    print()

    ok1, rows1 = rebuild_and_verify(spec, "PASS 1 (clear + create+fill)")
    print()
    ok2, rows2 = rebuild_and_verify(spec, "PASS 2 (idempotence rebuild)")
    print()

    # §6 q2 cross-check: ableton_note(list) count == ableton_clip(list) note_count
    # on a clip with raw != collapsed (stacked notes), read via a fresh call.
    live = list_arr(TRACK_INDEX)
    stacked = next((s for s in spec if s["raw"] != s["collapsed"]), spec[0])
    ci = next(i for i, c in enumerate(live, start=1)
              if abs(c["start_beats"] - stacked["start"]) < EPS)
    note_api = note_api_count(TRACK_INDEX, ci)
    clip_nc = live[ci - 1]["note_count"]
    print(f"§6q2 CROSS-CHECK on '{stacked['name']}' (raw={stacked['raw']}, "
          f"collapsed={stacked['collapsed']}): "
          f"clip.list note_count={clip_nc}, note.list count={note_api}, "
          f"agree={clip_nc == note_api == stacked['collapsed']}")
    print(f"  (this clip was created source-less via create_midi_clip — a "
          f"note_count of {clip_nc} can only be the clip's OWN notes, not a "
          f"mirrored session source.)")
    print()

    idempotent = (rows1 == rows2)
    net_noop = ([c["note_count"] for c in live] == [c["note_count"] for c in base])
    print(f"SUMMARY: pass1={ok1} pass2={ok2} idempotent(pass1==pass2)={idempotent} "
          f"net_noop_vs_baseline={net_noop}")


if __name__ == "__main__":
    main()
