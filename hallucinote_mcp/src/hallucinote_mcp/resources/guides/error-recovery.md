# hallucinote-mcp — Error Recovery

This server returns structured error responses with teaching hints. The
patterns below cover the most common errors and the right fix for each.

## Validation errors (param-level)

### `param 'X' must be int, got bool` / `must be str, got int` / etc.
Type mismatch on a parameter. Check the action's `params_schema` via
`ableton_<tool>(action='help')` — every action's help entry includes the
param type for each name.

### `param 'X'=Y not in enum [...]`
You passed a value outside the enum's allowed set. The error message
lists the valid values. Common one: `target_kind` on
`ableton_automation(action='write_envelope')` must be one of the seven
envelope target families.

### `missing required param(s) for <tool>('<action>'): X, Y, Z`
The action requires these params; you omitted them. The schema's
`required` list is in `action='help'` output for that action.

### `unknown param(s) for <tool>('<action>'): foo`
You passed a param the action doesn't accept. Likely a typo. Check the
action's help for the canonical names.

## Range errors (handler-level)

### `value X out of range [min, max]`
The schema accepted the type but the handler caught a value-bound
violation. Common cases: track volume must be 0.0–1.0 (NOT dB), pan
must be -1.0 to 1.0, MIDI velocity 1–127.

### `value X is out of range — pass -1 OR a value in [20, 999]`
Scene `set_tempo` accepts -1 (clear override) OR [20, 999] for an
explicit scene tempo. The gap (-1, 0] and (0, 20) is rejected.

## Address errors (runtime)

### `track_index X out of range [1, N]`
You addressed a track that doesn't exist. Call `ableton_track(action='list')`
to see what's available and the current index range.

### `session slot X on track Y is empty; create a clip first`
You tried to operate on an empty session slot. Either:
- `ableton_clip(action='create', location='session', track_index=Y,
  clip_index=X, kind='midi', length=N)` first, then your operation, OR
- pass `replace=True` to create when you want delete-and-create atomic.

### `cue_create: a cue already exists at position_beats=X`
Live's `set_or_delete_cue` is a TOGGLE that would silently DELETE the
existing cue. The handler refuses to "create" at an occupied position.
Use `cue_delete` first if you want to replace.

### `cue_create: position_beats=X is past the song's last_event_time=Y`
Live's `current_song_time` setter is clamped to the arrangement's
extent. Place arrangement content covering this position first
(`ableton_clip(action='create', location='arrangement', ...)`), then
add the cue.

## Cue creation — latency model

Each `cue_create` takes **~400ms** end-to-end (200ms pre-toggle settle
+ 200ms post-toggle settle). Live's `Song.current_song_time` setter is
asynchronous — the audio thread picks up the write on its own
buffer-aligned schedule, so the handler sleeps to give it wall-clock
time before firing the toggle. There is no faster reliable path on
Live 12.x; `schedule_message` bounces don't yield wall-clock time and
read-after-write checks return stale cached values.

**For multi-cue pushes, use `cue_create_batch`** — one round trip,
N × 400ms (a 7-cue song is ~3s). It holds the parallel-safety lock
once for the whole batch instead of once per cue, so it's not faster
than serial single calls but it's one TCP round trip instead of N.

**Parallel `cue_create` calls effectively serialize.** The bridge
holds a per-Live mutex (`live_state_lock`) around the cue
seek+settle+toggle window so concurrent callers don't observe each
other's playhead writes. Firing 7 parallel `cue_create` calls
completes in ~7×400ms wall-clock, not 400ms — they wait their turn
on the lock. Prefer `cue_create_batch` to be explicit about it.

`seek` and `cue_delete` take the same lock; they don't race against
in-flight cue creates either.

## "Needs Live" errors

### `<tool>('<action>') requires the Remote Script side to execute (no Live context available)`
The MCP server validated your call but Live isn't reachable. Open Ableton
Live, then in Preferences → Link, Tempo & MIDI select 'Hallucinote' as a
Control Surface. Re-run the call.

### `live connection failed for <tool>(<action>): ...`
The server tried to forward but the TCP connection to the Remote Script
failed. Live may not be running, or the Remote Script may not be installed.
The `/ableton-install-mcp` Claude Code skill walks through fresh install.

## Version-handshake errors

The MCP bridge has two halves running in different Python processes: the
**MCP server** (the `hallucinote-mcp` pip package, spawned by Claude Code
when you connect) and the **Remote Script** (the vendored copy in Live's
User Library, loaded by Live when it boots). They must agree on
`hallucinote_mcp.__version__`. On every call, the server side stamps its
version into the request; the Live side checks before dispatch.

Two failure modes — recovery differs:

### `Hallucinote MCP version handshake missing: ...`
The MCP server side didn't send a `server_version` field at all. It's old
enough to predate the handshake — i.e., the pip-installed `hallucinote-mcp`
is older than what's currently in Live's Remote Scripts folder.

**Fix:** upgrade the pip package, then respawn the MCP server.
1. `pip install -U hallucinote-mcp` (in the environment Claude Code uses)
2. In Claude Code: `/mcp` — this respawns the server process, which now
   ships the version on every request.

A full Claude Code restart works too, but `/mcp` alone is sufficient
because it relaunches the MCP server subprocess.

### `Hallucinote MCP version mismatch: MCP server side reports X, Remote Script side is Y`
Both halves are speaking the handshake, but they disagree. Whichever side
is older is the one to refresh.

**If the Remote Script side is older (`Remote Script side is Y` where
`Y < X`)** — the common case, because the pip side updates more freely:
1. `/ableton-install-mcp` — re-runs the install, refreshing the vendored
   copy in Live's User Library.
2. Fully quit Live (⌘Q / Alt+F4) and reopen it. **Live caches Control
   Surface modules at startup**, so a restart is required — `/mcp` alone
   does nothing for this branch, because the staleness is inside Live.

**If the MCP server side is older (`MCP server side reports X` where
`X < Y`)** — less common, but happens if you reinstall the Remote Script
without upgrading the pip package:
1. `pip install -U hallucinote-mcp`
2. `/mcp` in Claude Code to respawn the server.

The error message names both versions so you can tell which side is the
stale one without guessing.

## Gap-blocked actions (intentional)

### `ableton_note operations are blocked by MCP gap #4 — ...`
Per-note operations (list, add, update, delete) require stable note IDs
that Live's API doesn't yet expose. To REPLACE all notes on a clip,
use `ableton_clip(action='replace_notes', ...)` — that's the working
path today. See `ableton://guides/gaps`.

### `ableton_automation read operations (list, get_envelope) are blocked...`
The MCP envelope read surface isn't yet implemented. Use
`action='write_envelope'` to push; envelope reads come in a future
chunk.

### `target_kind=... requires clip_index + location on Live 12.4...`
Live 12.4's LOM only addresses envelopes through a containing clip —
there's no `Track.create_automation_envelope`. Pass `location`
(`'arrangement'` or `'session'`) and `clip_index` pointing at the
clip that should hold the envelope. Same applies to `action='clear'`
on the mixer / pan / send / device_parameter target_kinds. See
`ableton://guides/gaps` for the "track-level / clip-less" entry.

### `clear with target_kind='note_expression' is not exposed by Live 12.4's LOM...`
Live exposes `Clip.envelope_for_note(pitch, start, axis)` to fetch /
create the per-axis envelope but no symmetric `clear_note_envelope`.
Use `action='clear_all'` on the containing clip to wipe every
envelope (including note expression), then re-write what you want to
keep.

## Schema-bug errors

### `<tool>('<action>') executor referenced unknown param 'X'; this is a schema bug`
The action's executor (handler or declarative_op) tried to read a param
that isn't in the schema. This is a server-side bug — report it.

## Don't retry silently

If a call fails with a teaching error, READ the message and fix the
input. Retrying the same call with the same params will fail the same
way. The structured error fields (`valid_actions`, `required`, `optional`,
`example`, `hint`) tell you exactly what to change.
