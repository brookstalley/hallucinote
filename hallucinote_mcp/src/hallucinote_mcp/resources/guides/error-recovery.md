# Error recovery

The server returns structured errors with teaching hints. Read the message and
fix the input — for the errors on this page, retrying the same call with the
same params will fail the same way. The error fields (`valid_actions`,
`required`, `optional`, `example`, `hint`) tell you exactly what to change.

**Two replies are exceptions to that rule, and both are about Live being busy
rather than about your call.** Read *Live is busy* below before you treat
either as something to fix.

## Validation errors (param-level)

- **`param 'X' must be int, got bool`** (or similar type mismatches) — check
  the action's `params_schema` via `ableton_<tool>(action='help')`.
- **`param 'X'=Y not in enum [...]`** — the error lists valid values.
- **`missing required param(s) for <tool>('<action>'): X, Y`** — the
  `required` list is in `action='help'`.
- **`unknown param(s) for <tool>('<action>'): foo`** — likely a typo.

## Range errors

- **`value X out of range [min, max]`** — common cases: volume must be 0.0–1.0
  (NOT dB), pan -1.0 to 1.0, MIDI velocity 1–127.
- **`value X is out of range — pass -1 OR a value in [20, 999]`** — scene
  `set_tempo` accepts -1 (clear override) OR a valid BPM; the gap is rejected.

## Address errors

- **`track_index X out of range [1, N]`** — call `ableton_track(action='list')`
  to see what exists.
- **`session slot X on track Y is empty; create a clip first`** — either
  `ableton_clip(action='create', ...)` first, then your op, or pass
  `replace=True` to create.
- **`cue_create: a cue already exists at position_beats=X`** — Live's
  `set_or_delete_cue` is a TOGGLE that would silently DELETE; use `cue_delete`
  first if you want to replace.
- **`cue_create: position_beats=X is past the song's last_event_time=Y`** —
  place arrangement content covering this position first, then add the cue.

## Cue creation latency

Each `cue_create` takes ~150-400ms (Live's playhead-write + settle window).
For multi-cue pushes, use `cue_create_batch` — one TCP round-trip, same
per-cue cost. Concurrent `cue_create` / `seek` / `cue_delete` calls serialize
on a per-Live lock.

## Needs-Live errors

- **`<tool>('<action>') requires the Remote Script side to execute (no Live
  context available)`** — open Live and select 'Hallucinote' as a Control
  Surface (Preferences → Link, Tempo & MIDI).
- **`live connection failed for <tool>(<action>): ...`** — Live not running,
  or Remote Script not installed. Run `/ableton-mcp-install`.

## Version-handshake errors

If you see `Hallucinote MCP version handshake missing` or `version mismatch`,
the pip package and the vendored Remote Script disagree. Run
`/ableton-mcp-install`, then fully quit + reopen Live (Live caches Control
Surface modules at startup; `/mcp` alone is not enough). `hallucinote-mcp
preflight` reports both versions without restarting.

### Engine version drift during a live compose session

If you're **developing the engine in parallel** (editable install) while a song
session is mid-flight, this mismatch is common and the reinstall path above is
the wrong move — quitting Live to re-vendor the Remote Script throws away the
running set. The engine repo advanced (new commits, maybe a dirty tree) so every
fresh `push_cli` process now reports a newer version than the Remote Script Live
loaded at startup; the handshake refuses correctly, but the song work is blocked
through no fault of its own.

Recovery that keeps the live session: **pin the CLI to the Remote Script's own
content** instead of upgrading Live. The `+<suffix>` in a version string is a
content fingerprint of the vendored package (`_compute_content_fingerprint`),
**not a git commit** — `git cat-file -t` rejects it and no worktree, ref or tag
resolves it. The only tree that reproduces that fingerprint is the package Live
loaded, so the pin copies *that directory* and puts it first on `PYTHONPATH`.

The install strips `cli/` and `server.py` from what it vendors, and neither is
in `_FINGERPRINT_PATHS`, so copy them back from your checkout — `preflight`
works again and the pin still fingerprints as the Remote Script does. Run from
your checkout root (the path below is macOS's default User Library; `preflight`
prints yours as `user_library.default`):

```
PIN=/tmp/hallucinote-pin; rm -rf "$PIN"; mkdir -p "$PIN"
cp -R "$HOME/Music/Ableton/User Library/Remote Scripts/Hallucinote/hallucinote_mcp" "$PIN/"
cp -R hallucinote_mcp/src/hallucinote_mcp/cli "$PIN/hallucinote_mcp/cli"
cp hallucinote_mcp/src/hallucinote_mcp/server.py "$PIN/hallucinote_mcp/"
export PYTHONPATH="$PIN:$PWD/src"
python3 -m hallucinote_mcp.cli preflight   # remote_script.candidates[].matches_mcp_server must read true
python3 -m hallucinote.sync.push_cli execute ...   # now handshakes clean
```

When the session is done, drop the pin (`rm -rf /tmp/hallucinote-pin`, unset
`PYTHONPATH`) and reinstall normally to bring Live up to date. There is no
`--pin` flag: a process that mutates `sys.path` after import has already
imported the wrong package, so pinning has to happen in the environment before
Python starts. `push_cli execute` prints this same recipe — with your detected
User Library path already filled in — in its recovery footer when it detects
the handshake refusal.

## Render capture errors (recorder won't arm)

A render can fail with **`render: the HallucinoteAnalyzer received 0
frames after transport reached beat N`** — surfaced through
`ableton_render(action='status', job_id=…)` as `state='failed'` (render is a
start+poll action now; the synchronous `render` was retired). The transport
played but the M4L analyzer's `sfrecord~` never captured, so no WAVs were
written. This is almost
always a stale Control-Surface/server subprocess or an **open analyzer M4L
device-editor window** — either one steals the `udpreceive` port the analyzer
listens on for its OSC path/arm messages.

**Preconditions — set these up BEFORE a render so the fix is never needed:**

1. **No analyzer device-editor window open in Live.** If you've been editing
   the HallucinoteAnalyzer `.amxd`, close its editor — the patcher editor and
   the Live runtime fight over `udpreceive`.
2. **A fresh server subprocess.** After any pip/Remote-Script change, run
   `/mcp` to respawn the server. (Live caches Control Surface modules at
   startup, so Live-side changes additionally need a full quit + reopen — same
   as the version-handshake fix above.)

**Recovery when the 0-frame error fires:** (1) quit and reopen Live, (2) close
any open HallucinoteAnalyzer editor window, (3) run `/mcp` to respawn the
server, then retry. The render **fails fast** (seconds, once transport passes
the checkpoint) rather than blocking the full render window waiting for frames
that never arrive — so a retry is cheap.

## Gap-blocked actions

See `ableton://guides/gaps` for the full list of API gaps and their
workarounds. The teaching errors will point you at that doc too.

## Schema-bug errors

- **`<tool>('<action>') executor referenced unknown param 'X'; this is a
  schema bug`** — server-side bug; report it.

## Live is busy — the two replies that are NOT about your call

Everything else on this page is a defect in the request. These two are not, and
the fix for each is to wait rather than to change anything.

### `ok=false` — the request was refused, not attempted

The message names an operation already running on Live's main thread and how
long it has been going. Live's main thread serves one caller at a time, and
this refusal is deliberate: queueing you behind it is what turns one slow
operation into an unresponsive DAW.

**Your call never ran.** Nothing partial happened, so there is nothing to undo.
Poll `ableton_session(action='bout_status')` until it is clear, then send the
same call unchanged — same params, and this time it succeeds. This is the one
place on this page where an identical retry is the correct move; do not "fix"
the request, because nothing was wrong with it.

### `ok=true` with `code='work_escalated'` — a handle, not a result

The call outran Live's main-thread ceiling. **It did not fail and it is still
running** — Python cannot interrupt a Live API call, so the reply reports that
the server stopped waiting, not that the work stopped. The `result` carries
`job_id`, `label` and `elapsed_s` instead of the call's own return value.

Treating this as success is the mistake it exists to prevent: it books a write
that has not landed, and your next call queues behind the one still executing.

Poll `ableton_session(action='bout_status', job_id=...)` to a terminal state —
`done` carries the call's real result, `failed` carries Live's own error. If it
never terminates, `ableton_session(action='abandon_bout', job_id=...)` clears
the occupancy; the work may still be running in Live, and abandoning does not
stop it.

## Don't retry silently

If a call fails with a teaching error, the structured response tells you
what to change. Same params → same failure. The busy refusal above is the
stated exception: there, same params → success once the main thread is free.
