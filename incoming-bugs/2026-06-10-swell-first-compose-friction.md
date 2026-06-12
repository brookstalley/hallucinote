# Friction log — swell first compose session (2026-06-10)

Context: full song bootstrap (scaffold → picks → skeleton push → first compose
pass) for `swell` in hallucinote-songs. Engine + plugin 0.9.0, hallucinote-mcp
`0.1.0+a5479db86125`, Live 12.4.1 Suite. Five items, roughly by severity.

## 1. `preset_query` authoring has two silent foot-guns (inventory.find / resolve_query)

Hit both while authoring the 20-pack-pick snapshot:

- **Pattern matches the entry NAME, not the path.** A natural first attempt —
  `pattern='Instrument Rack/Strings/Ac Strings Orch'` — returns the
  0-match error "verify the preset is installed, or refresh the cache",
  which sent me toward a (pointless) cache refresh before realizing patterns
  are name-only and scoping belongs in `path_prefix`. Suggest: when a pattern
  contains `/`, the error should teach "patterns match entry names; use
  path_prefix for path scoping (or the path-shape sugar)".
- **`path_prefix` must exclude the root segment.** Passing
  `path_prefix=['packs', 'Orchestral Strings']` under `root='packs'` errors
  with "path_prefix=… not found under root 'packs'" — true but unhelpful,
  since the actual fix is dropping `'packs'` from the list. Suggest: detect
  `path_prefix[0] == root` and say so.

Both have good strict-mode behavior (no silent wrong loads) — the friction is
purely that the teaching errors point away from the actual fix.

## 2. Skeleton push always goes PARTIAL at the `cues` phase

First push of a freshly-scaffolded song (tracks + returns + devices, no clips
yet) halts at `cues`: `cue_create_batch: N cue(s) past last_event_time=24.0` —
Live's locator setter is clamped to the arrangement extent and the arrangement
is empty. Everything else is fine, but the operator sees "PARTIAL — halted" +
an errors file for what is really "cues wait for content". Suggest: the cues
planner should skip-with-warning cues beyond the current arrangement extent
(they're idempotently picked up by the next push — which is exactly what
happened once clips existed), reserving the hard error for cue positions
beyond the *composed* song length. Workaround used meanwhile: build.py only
emits cue points for composed sections.

## 3. No "replace instrument, keep FX chain" path (device load is append-only)

The Glitch track needed its empty Simpler replaced by a Simpler carrying a
sample (`Vocal Choir Pure C4.wav`) *ahead of* its Redux → Erosion → Saturator
chain. `ableton_device(action='load')` appends at chain end and Live 12.4 has
no reorder API, so the only path is: delete all 4 devices (descending), reload
all 4 in order — 8 MCP calls for a 1-device swap, with a window where the
chain is gone. It worked (and links survived re-probe; next `execute` showed
`devices: skipped (idempotent)`), but it's fragile by hand. Suggest either a
`rebuild_chain` convenience (delete+reload from a devices[] spec) or at least
documenting the delete-descending/reload-in-order pattern in
`ableton://guides/conventions`.

## 4. `/ableton-mcp-install` rsync example breaks under zsh

The skill doc's expanded rsync example has `--exclude=*.pyc` unquoted. Under
zsh (macOS default), the glob fails with "no matches found: --exclude=*.pyc"
and aborts the whole compound command *before rsync runs* — the install
appears to have copied nothing. Fix: quote it (`--exclude='*.pyc'`) in the
skill doc (the other excludes are glob-free and safe).

## 5. `/song-new` postlude vs `ableton_render(action='ensure_loaded')` params

The song-new skill's postlude says to call `ensure_loaded` silently after
scaffolding; calling it with `song_slug` (natural, since every other render
action wants it) errors with "unknown param(s)". Trivial, but the skill text
could say "call with no params".

## Positive notes (so the signal isn't all negative)

- `compat check --probe` → `probe-and-link --auto-session` → `execute` is a
  genuinely great pipeline: 21 tracks / 4 returns / 52 devices materialized
  with zero manual fixes, and the default-scaffold cleanup gate did the right
  thing.
- The inventory cache made offline pick-verification (same matcher as push)
  possible and fast; the refresh-when-Live-up loop took ~15 s.
- Deterministic seeded generation + the converger idempotency test caught
  nothing because nothing needed catching — the whole first compose pass
  (2,785 notes, 22 clips) pushed clean on the first execute.

## 6. (added later same session) `params_dialed` on a snapshot-authored device didn't apply at push

Added a Saturator to a track via the snapshot with
`params_dialed: {"Drive": {"value": "14 dB", "normalized": 0.389}}`. The
devices phase loaded it (1/1 ok) but Drive stayed at the default (raw 0.5 =
0.0 dB) — the dial never landed; set it via
`ableton_device(set_parameter, value_display='14 dB')` instead (raw 0.6875).
Two sub-issues: (a) params_dialed from a hand-authored snapshot appears not to
be applied on device load (or fails silently — no error surfaced); (b) the
`normalized` field is ambiguous for center-zero params — Saturator Drive's raw
range maps 0.5→0 dB, so a naive "fraction of max" normalized (0.389) would
have dialed NEGATIVE drive. Suggest the push planner prefer the display
`value` string (inverted via the param's display curve, like set_parameter's
value_display) over `normalized`, and warn when a params_dialed write is
skipped.

## 7. (overnight session) Long-running `ensure_loaded` vs the 15s socket window

`ableton_render(action='ensure_loaded')` on a 21-track + 4-return set loads
the M4L analyzer onto ~25 surfaces; the MCP bridge's 15s read timeout fires
long before that finishes (two timeouts in a row), while the work continues
server-side. Recovered by driving `hallucinote_mcp.client.send(...,
read_timeout=300)` in-process. Suggest: a progress/async pattern for
known-long actions (ensure_loaded, render), or chunked per-track ensure.

## 8. (overnight session) Master-analyzer gap blocks fully-unattended mix passes

Documented gap (DEV-2M9K) confirmed end-to-end: `ensure_loaded` hard-errors
without a master HallucinoteAnalyzer, and `ableton_device(load, master=true)`
correctly refuses (no Live API). Consequence worth naming: a render →
MixReport → /mix-review cycle can never run unattended on a fresh set — it
always waits on one human drag. If any path exists (template set with the
analyzer pre-placed on master? default-set template?), documenting it would
unlock overnight mix iteration.

## 9. (overnight session) Engine source moved mid-session → version-pin recovery

The hallucinote repo advanced (v0.9.4 + commits + dirty working tree) while a
song session was mid-flight; every fresh CLI process (push_cli) then refused
with a version mismatch against the still-running Remote Script — correctly,
but the song work was blocked through no fault of its own. Recovery that
worked cleanly: `git worktree add /tmp/hallucinote-pin <old-commit>` +
`PYTHONPATH` pinning push_cli to the fingerprint matching the Remote Script
(verified via preflight: pinned == installed). Suggest: a first-class
`--pin <version>` or env knob on push_cli for exactly this, and a note in
error-recovery that the *editable-install + parallel engine dev* combo makes
this likely for anyone composing while developing.
