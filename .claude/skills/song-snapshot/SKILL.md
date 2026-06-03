---
name: song-snapshot
description: Refresh a song's `captured_session.json` against the currently open Ableton set. Re-runs the capture probes (`ableton_session(action='info')`, `ableton_return(action='list')`, per-track `ableton_track(action='info')` + `ableton_track(action='get_sends')`, per-device parameter probes, nested rack-chain walks), writes a `captured_session.refresh.json` side-by-side, diffs against the existing snapshot, and asks the user to confirm before overwriting. Use when you've changed instrument params / sends / device chains in Live and want the on-disk snapshot to reflect the new mix layout. Do NOT use to capture clips, notes, automation, arrangement, or cue points — those live in `build.py`, not the snapshot.
---

# /song-snapshot

You refresh `songs/<slug>/captured_session.json` from the currently open Ableton set, with a diff confirmation before overwrite. The snapshot is the seed for `build.py`'s `replay_capture(...)` — it captures the **mix layout** (tracks, returns, sends, top-level device chains, dialed instrument parameters, one level of nested rack chains). Everything else (clips, notes, envelopes, arrangement, cues) is owned by `build.py` and is intentionally NOT touched.

## When to run this

Run after the user has manually edited the live Ableton set in ways that change what `replay_capture(...)` would produce: dialed an instrument param, added/removed a device, changed a send level, renamed or reordered tracks, tweaked the master strip. **Don't** run this for clip edits (use `/ableton-pull` for those).

## When NOT to run this

- Just changed automation / envelopes → no-op (snapshot doesn't carry envelopes).
- Just added/edited clip notes → use `/ableton-pull`.
- Cue points / arrangement layout changed → owned by `build.py`, not captured.
- Live isn't running, or you haven't loaded the song's set → refuse; ask user to open Live with the right set loaded.

## Preflight

The user must give you a song slug. If they don't, ask: "which song? It needs to match a `songs/<slug>/` directory."

Then verify:

```bash
ls songs/<slug>/captured_session.json
```

If the file doesn't exist, this isn't a refresh — it's an initial capture. Tell the user; they probably want `hallucinote.tools.capture_cli --plan` walked by hand for the first capture, then this skill for subsequent refreshes.

Verify the bridge:

> *call `ableton_session` with action=info*

On connection errors: see `ableton://guides/error-recovery`.

## Step 1 — Run the capture probes

Get the probe list from the canonical source so you don't drift from what `compile_snapshot` expects:

```bash
python -m hallucinote.tools.capture_cli plan
```

Execute each probe in order. The output is the same as the procedure documented in `src/hallucinote/capture.py` (capture_plan docstring) — global session info, return tracks, per-track info, per-track sends, per-device parameters, per-rack-device nested chains. Loop over every track and every device.

Assemble the results into the three buckets `compile_snapshot` wants:

- `session_info` — `{tempo, signature, master: {volume, panning}}` from `ableton_session(action='info')`
- `returns` — list of return-track dicts (each with `index`, `name`, `volume`, `panning`, optionally `devices`)
- `tracks` — list of track dicts (each with `index`, `name`, `type`, `volume`, `panning`, optional `mute`/`solo`/`arm`/`color`, optional `sends` map, optional `devices`)

For rack devices (`Drum Rack`, `Instrument Rack`, `Audio Effect Rack` — browser display names; see `ableton://guides/conventions`), attach the nested `chains` array as the device's `chains` field. Walk one level only.

## Step 2 — Write the fresh capture to a side-by-side file

Compile the dict and write it to `songs/<slug>/captured_session.refresh.json` (NOT the canonical name — overwriting before the user has seen the diff is the bug this skill exists to prevent). Capture probes don't expose `browser_path`, so `preserve_browser_paths` carries the old paths forward where device identity (parent index + position + class) still matches:

```python
from hallucinote.capture import compile_snapshot, preserve_browser_paths
import json, pathlib

old_path = pathlib.Path("songs/<slug>/captured_session.json")
old = json.loads(old_path.read_text())

new = compile_snapshot(
    session_info=<dict you assembled>,
    returns=<list>,
    tracks=<list>,
)
preserve_browser_paths(old, new)

pathlib.Path("songs/<slug>/captured_session.refresh.json").write_text(
    json.dumps(new, indent=2)
)
```

## Step 3 — Diff

Run the diff CLI. It prints the structured diff as JSON to stdout and a one-screen human summary to stderr. Exit code is `0` when nothing changed and `1` when there are changes — branch on it.

```bash
python -m hallucinote.tools.capture_cli diff \
  songs/<slug>/captured_session.json \
  songs/<slug>/captured_session.refresh.json
```

**If exit 0 (no changes):** tell the user the snapshot is already up to date, delete the `.refresh` file, and stop.

**If exit 1 (changes present):** show the user the stderr summary (the human one-screen format). Don't dump the full JSON unless they ask — it can be thousands of lines for a complex song.

Then ask explicitly: *"overwrite `captured_session.json` with this refresh? (yes / no / show full diff)"*

- **yes** → merge first, then move. The merge preserves sticky device fields (`browser_path` — captured at load time, not surfaced by list-time probes) so a refresh doesn't wipe the cross-machine fallback identity:
  ```bash
  python -m hallucinote.tools.capture_cli merge \
    songs/<slug>/captured_session.json \
    songs/<slug>/captured_session.refresh.json \
    -o songs/<slug>/captured_session.json
  rm songs/<slug>/captured_session.refresh.json
  ```
- **no** → delete the `.refresh` file and stop. Tell the user "no changes written."
- **show full diff** → cat the stdout JSON and re-ask.

## What the diff covers (and what it doesn't)

The diff helper (`hallucinote.capture.diff_snapshots`) matches tracks and returns by `index` and devices by their position within a chain. Name drift is reported as a field-change, not as add/remove (Live track names aren't unique enough to use as identity). Per-device dialed-parameter drift is diffed in full; nested rack chains walk one level (matching what `replay_capture` supports). Recursively nested racks (rack-in-rack) are flagged as `nested_chains_subtree_changed: true` without descending — the user can read the JSON if they need more detail.

What the diff does NOT see, because the snapshot doesn't carry it:

- Clip note edits (use `/ableton-pull`).
- Automation envelope changes.
- Arrangement edits (clip placement on the arrangement timeline).
- Cue points.

If the user expects these to surface, they're using the wrong tool — tell them.

## After overwrite

Note the timestamp / git status to the user. If the snapshot is tracked in git (`songs/<slug>/captured_session.json` typically is), suggest they review and commit it themselves — this skill never commits on its own.

If `build.py` hard-codes assumptions about the old snapshot (e.g., specific track indices, specific device classes), changing those in Live will silently break the next build until `build.py` catches up. The diff makes the structural changes visible; the user is responsible for updating `build.py` accordingly.
