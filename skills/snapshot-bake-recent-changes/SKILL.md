---
name: snapshot-bake-recent-changes
description: Bake mid-session device-parameter tweaks from the open Ableton set back into the song's DB so they survive the next push. Wraps `pull_cli execute device-parameters` with a `--dry-run` preview + confirm step. Use after manually tweaking knobs in Live (Amp Type, sidechain threshold, instrument macros, etc.) and BEFORE re-running a full push that might overwrite them. Lightweight alternative to `/song-snapshot` (which captures the full mix layout). Do NOT use for clip notes, automation, or arrangement edits — those have their own paths.
---

# /snapshot-bake-recent-changes

You bake **mid-session device-parameter changes** from the open Ableton set back into the song's SQLite DB. The motivating use case: during composition iteration the user tweaks `Amp.Type`, sidechain threshold, Wavetable macros, etc. via direct MCP `set_parameter` calls (or by twisting knobs in Live's UI). Those changes live in Live's memory but not on disk — the next full re-push reloads the devices from the DB's `params_dialed` and the tweaks are silently lost.

This skill closes that loop. It diffs Live's current parameter state against the DB's, shows the user what would change, and on confirmation writes the new values through the standard pull pipeline (mutators + events, audit-logged as `actor='sync'`, `kind='pull'`).

## When to run this

- User said something like "bake my tweaks" / "save these mix changes" / "preserve this before the next push" / "make sure I don't lose the amp setting."
- The user has been iterating on device parameters in Live (manually or via MCP) and wants those changes to survive the next `/ableton-push`.
- You're about to invoke a full re-push (e.g. `push_cli execute`) and the user has been tweaking — offer this first.

## When NOT to run this

- **Note / clip edits** → use `/ableton-pull` with the `clip-notes` domain. Notes don't ride on device parameters.
- **Track names / send levels / new devices** → those are the *mix layout*, not parameter dial-ins. Use `/song-snapshot` for those; it captures the full layout and updates `captured_session.json`.
- **Automation / envelope edits** → not yet round-tripped; surface the limitation.
- **Live isn't running** or the song's set isn't loaded → refuse; ask the user to open Live first.
- **No `ableton_sessions` row exists for this DB** → run `push_cli probe-and-link --auto-session` first so the binding exists; this skill needs a `session_id`.

## Preflight

The user must give you a song slug. If they don't, ask: *"which song?"* — needs to match a `songs/<slug>/` directory.

Then verify the bridge is live:

> *call `ableton_session` with action=info*

On connection errors: see `ableton://guides/error-recovery`.

Resolve the song's session_id: if the user gave one, use it; otherwise just omit it — the pull/push CLIs auto-select the only / most-recent session and echo the choice on stderr (WFL-7Q2N). No manual `sqlite3` listing needed. If no sessions exist, the CLI refuses with bootstrap guidance (`push_cli probe-and-link --auto-session` first).

## Step 1 — Preview the diff (`--dry-run`)

Run the dry-run against the `device-parameters` domain. The SAVEPOINT inside `pull_cli execute --dry-run` makes this safe — every write is rolled back; the output JSON's `applied.mutations` counter and `applied.details` block show what WOULD change:

```bash
python -m hallucinote.sync.pull_cli execute device-parameters <session_id> \
  --song <slug> --dry-run
```

The output is a JSON object on stdout. Pluck three things from it for the human display:

- `dry_run: true` — confirms preview-only.
- `applied.mutations` — count of DB rows that would change.
- `applied.details` — per-row before/after surface (look for entries like `{"action": "update", "table": "device_parameters", "before": ..., "after": ...}`).

If `applied.mutations == 0`: tell the user the DB already matches Live; nothing to bake. Stop.

If `applied.mutations >= 1`: continue to Step 2.

## Step 2 — Show the diff and confirm

Show the user a compact summary — don't dump the whole `applied.details` JSON unless they ask. Format like:

> *"Live has 3 device-parameter changes that aren't in the DB:*
>  *- Drums / Compressor / Threshold: -12.0 dB → -6.0 dB*
>  *- Bass / Wavetable / Sub Decay: 0.50 → 0.72*
>  *- Master / Glue Compressor / Makeup: 0.0 dB → 2.0 dB*
> *Bake these into the song DB (`$DB_PATH` from Step 0)? (yes / no / show full diff)"*

Branch:

- **yes** → Step 3.
- **no** → confirm "no changes written; Live's tweaks stay in memory only" and stop.
- **show full diff** → emit the raw `applied.details` JSON and re-ask.

## Step 3 — Real apply (no `--dry-run`)

Re-run without the flag. The SAVEPOINT discipline no longer fires; mutations commit and a `kind='pull'` request is recorded for audit:

```bash
python -m hallucinote.sync.pull_cli execute device-parameters <session_id> \
  --song <slug> \
  --reason "snapshot-bake-recent-changes: user-confirmed device-parameter diff"
```

Confirm `applied.mutations` in the response matches the dry-run count. If it diverges (Live changed something between Step 1 and Step 3), surface that to the user — the bake still happened, but the count drift is worth noting.

## After bake

- The DB now reflects Live's current device-parameter state. The next `push_cli execute` won't overwrite the tweaks.
- The `captured_session.json` snapshot is **not** updated by this skill. If the user wants the snapshot to match too (e.g. for fresh `--reset` rebuilds), point them at `/song-snapshot`.
- If the change spanned mix-state, sends, or new devices, those weren't baked here — they need `/song-snapshot` or `/ableton-pull` against a wider domain.
- **Sidechain SOURCE** (the device input routing — not the `S/C On`/`S/C Gain` params, which ARE captured above) rides a separate domain. If the user added/changed sidechains in Live, run a second dry-run/apply pass against `device-sidechain` (same `pull_cli execute` flow) so `devices.sidechain_source_track_id` is baked too (SDC-7K3M).

## What this skill does NOT do

- Capture clip note edits (use `/ableton-pull` with `--domain clip-notes`).
- Capture envelope / automation changes (no round-trip path today).
- Update `captured_session.json` (use `/song-snapshot`).
- Recurse into nested rack chains' parameters (separate `nested-rack-chains` domain).
- Commit anything to git — the user reviews the DB diff and decides.

## Relationship to other tools

- **`/song-snapshot`** — heavier; recaptures the full mix layout into `captured_session.json`. Use when the layout (tracks, sends, device chain shape) changed.
- **`/ableton-pull`** — domain-scoped; lets the user pick what to pull (notes, mix-state, arrangement-clips, etc.). This skill is a UX-tuned wrapper around the `device-parameters` slice of that, with the dry-run preview baked in.
- **`/ableton-push`** — the inverse direction. Always offer this skill *before* a push if the user has been tweaking, so the push doesn't overwrite their work.
