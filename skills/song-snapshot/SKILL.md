---
name: song-snapshot
description: Refresh a song's `captured_session.json` against the currently open Ableton set — the single DURABLE mix bake (what it writes survives a `build.py` rebuild, unlike a DB-only `/ableton-pull`). Re-runs the capture probes (`ableton_session(action='info')`, `ableton_return(action='list')`, per-track `ableton_track(action='info')` + `ableton_track(action='get_sends')`, per-device parameter + sidechain-source probes, nested rack-chain walks), writes a `captured_session.refresh.json` side-by-side, diffs against the existing snapshot, and asks the user to confirm before overwriting. Use when you've changed instrument params / sends / device chains / a device's sidechain source in Live and want the on-disk snapshot to reflect the new mix layout. Do NOT use to capture clips, notes, automation, arrangement, or cue points — those live in `build.py`, not the snapshot.
---

# /song-snapshot

> **Running engine commands.** The engine ships in the plugin's uv env. Resolve `$PY` once from `ableton://server/info`'s `python`; the `hallucinote …` commands below run as `"$PY" -m hallucinote.cli …`. See [`docs/running-the-engine.md`](../../docs/running-the-engine.md).

You refresh `songs/<slug>/captured_session.json` from the currently open Ableton set, with a diff confirmation before overwrite. The snapshot is the seed for `build.py`'s `replay_capture(...)` — it captures the **mix layout** (tracks, returns, sends, device chains, dialed instrument parameters, **device sidechain sources**, and nested rack chains to any depth). This is the **single durable mix bake**: what it captures lands in the git-tracked `captured_session.json` and reproduces on the next `build.py` — unlike `/ableton-pull`, which writes only the regenerable DB (a DB-only mix pull is not durable — the next `build.py` refuses with `StaleSnapshotError` rather than replaying over it, and on a legacy snapshot with no `captured_at` stamp it warns and reverts). Everything else (clips, notes, envelopes, arrangement, cues) is owned by `build.py` and is intentionally NOT touched.

## When to run this

Run after the user has manually edited the live Ableton set in ways that change what `replay_capture(...)` would produce: dialed an instrument param, added/removed a device, changed a send level, set a device's sidechain source ("Audio From" on a Compressor/Gate), renamed or reordered tracks, tweaked the master strip. **Don't** run this for clip edits (use `/ableton-pull` for those).

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

If the file doesn't exist, this is an initial capture, not a refresh — there's nothing to diff against. Capture straight to the canonical file (no `.refresh` / diff step), then use this skill for subsequent refreshes:

```bash
"$PY" -m hallucinote.cli capture execute --song <slug> \
  --output songs/<slug>/captured_session.json
```

Verify the bridge:

> *call `ableton_session` with action=info*

On connection errors: see `ableton://guides/error-recovery`.

## Step 1 — Capture (deterministic, in code)

Run the capture in one command — it walks the live set over the MCP bridge, reaching device parameters at **every nesting depth** (NodeAddr `path`), and writes the fresh snapshot to `songs/<slug>/captured_session.refresh.json` (NOT the canonical name — overwriting before the user has seen the diff is the bug this skill exists to prevent). It carries `browser_path` forward from the existing snapshot (capture probes don't surface it) and prints the refresh path to stdout:

```bash
"$PY" -m hallucinote.cli capture execute --song <slug>
```

This replaces the old by-hand "run each probe + assemble the dict" recipe — `assemble_snapshot_via_probes` (`src/hallucinote/capture.py`) does it deterministically: session globals, master chain, returns (+ mixer + devices), tracks (+ mixer + sends + devices), and the full recursive rack tree with dialed params filtered to non-defaults. A tool-side failure aborts loudly rather than writing a partial snapshot.

(`capture_cli plan` still prints the probe sequence if you ever need to capture by hand.)

## Step 2 — Diff

Run the diff CLI. It prints the structured diff as JSON to stdout and a one-screen human summary to stderr. Exit code is `0` when nothing changed and `1` when there are changes — branch on it.

```bash
"$PY" -m hallucinote.cli capture diff \
  songs/<slug>/captured_session.json \
  songs/<slug>/captured_session.refresh.json
```

**If exit 0 (no changes):** the snapshot content already matches Live. Normally: tell the user it's up to date and stop. Delete the `.refresh` file **last**, after the empty-diff question below is settled — the bake path needs it, so deleting on the way past leaves nothing to bake.

*Empty-diff bake (BAK-7D2V).* One corner needs more: if a prior **mix** `/ableton-pull` is still un-baked — e.g. you pulled a knob change, then hand-reverted it in Live, so the content matches again but `build.py` still **refuses** (`StaleSnapshotError`, because the guard is armed by the pull *events*, not by content) — the fresh refresh can be baked over the canonical snapshot so the guard disarms.

**Only offer this when a pull might be in play** (the user mentions a pull, or a build just refused). For a plain "did anything change?" check, just stop.

Ask first: *"No content changed in the diff, but a prior pull may still be blocking `build.py` — bake the fresh capture to disarm it? (yes / no)"*

**Write the refresh — never just move the timestamp.** An empty diff does NOT prove the on-disk snapshot carries everything replay will re-assert: the diff compares device identity, dialed parameters, and chain names, but the snapshot ALSO carries device sidechain sources, drum-pad mappings, and per-chain authored props (volume/pan/mute/solo/choke_group/out_note) that `replay_capture` re-asserts and the diff never looks at. A pull that touched only those fields produces an empty diff, so stamping the stale file forward would disarm the guard over old values and let the next build silently revert the by-ear work — exactly the failure this guard exists to prevent. The merge below takes the fresh capture as its base, so it carries those fields AND a fresh `captured_at`.

On **yes**:

```bash
"$PY" -m hallucinote.cli capture merge \
  songs/<slug>/captured_session.json \
  songs/<slug>/captured_session.refresh.json \
  -o songs/<slug>/captured_session.json
rm songs/<slug>/captured_session.refresh.json
```

On **no**: delete the `.refresh` file and stop.

**If exit 1 (changes present):** show the user the stderr summary (the human one-screen format). Don't dump the full JSON unless they ask — it can be thousands of lines for a complex song.

Then ask explicitly: *"overwrite `captured_session.json` with this refresh? (yes / no / show full diff)"*

- **yes** → merge first, then move. The merge preserves sticky device fields (`browser_path` — captured at load time, not surfaced by list-time probes) so a refresh doesn't wipe the cross-machine fallback identity:
  ```bash
  "$PY" -m hallucinote.cli capture merge \
    songs/<slug>/captured_session.json \
    songs/<slug>/captured_session.refresh.json \
    -o songs/<slug>/captured_session.json
  rm songs/<slug>/captured_session.refresh.json
  ```
  After the overwrite, tell the user the mix bake is **durable and the replay guard is now disarmed**: `captured_session.json` is stamped newer than any pulled edit, so the next `build.py` runs clean (no `StaleSnapshotError`, nothing reverted).
- **no** → delete the `.refresh` file and stop. Tell the user "no changes written."
- **show full diff** → cat the stdout JSON and re-ask.

## What the diff covers (and what it doesn't)

The diff helper (`hallucinote.capture.diff_snapshots`) matches tracks and returns by `index` and devices by their position within a chain. Name drift is reported as a field-change, not as add/remove (Live track names aren't unique enough to use as identity). Per-device dialed-parameter drift is diffed in full. The PREVIEW diff itemizes one level of nested rack chains and flags anything deeper as `nested_chains_subtree_changed: true` without descending — a preview simplification only. The full snapshot IS captured + replayed + pushed at any depth (DEEP-RACK-ADDR); the diff just doesn't spell out deep subtrees, so read the JSON if you need the detail.

What the diff does NOT see, because the snapshot doesn't carry it:

- Clip note edits (use `/ableton-pull`).
- Automation envelope changes.
- Arrangement edits (clip placement on the arrangement timeline).
- Cue points.

If the user expects these to surface, they're using the wrong tool — tell them.

What the diff does not see even though the snapshot DOES carry it — and replay
re-asserts it:

- A device's sidechain source (`sidechain_source` / `sidechain_source_channel`).
- Drum-pad mappings (`drum_pads`).
- Per-chain authored props (volume/pan/mute/solo/choke_group/out_note).

This category is the dangerous one: the diff summary you show at the confirm
prompt under-reports what the overwrite will actually change, and an empty diff
does not mean the on-disk snapshot is current. Never treat exit 0 as proof the
snapshot is fresh — that's why the empty-diff path above bakes the capture rather
than just moving the timestamp. When one of these fields is what changed, say so
plainly: the write is correct and desirable, the *summary* just can't itemize it.

## After overwrite

Note the timestamp / git status to the user. If the snapshot is tracked in git (`songs/<slug>/captured_session.json` typically is), suggest they review and commit it themselves — this skill never commits on its own.

If `build.py` hard-codes assumptions about the old snapshot (e.g., specific track indices, specific device classes), changing those in Live will silently break the next build until `build.py` catches up. The diff makes the structural changes visible; the user is responsible for updating `build.py` accordingly.
