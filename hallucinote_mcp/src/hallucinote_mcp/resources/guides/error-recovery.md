# Error recovery

The server returns structured errors with teaching hints. Read the message and
fix the input — retrying the same call with the same params will fail the same
way. The error fields (`valid_actions`, `required`, `optional`, `example`,
`hint`) tell you exactly what to change.

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

## Gap-blocked actions

See `ableton://guides/gaps` for the full list of API gaps and their
workarounds. The teaching errors will point you at that doc too.

## Schema-bug errors

- **`<tool>('<action>') executor referenced unknown param 'X'; this is a
  schema bug`** — server-side bug; report it.

## Don't retry silently

If a call fails with a teaching error, the structured response tells you
what to change. Same params → same failure.
