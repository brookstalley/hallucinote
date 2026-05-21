# hallucinote-mcp — Getting Started

Welcome. This MCP server exposes Ableton Live as a unified 11-tool surface
designed for low-context-cost agent interaction.

## The shape

11 tools, each with an `action` parameter:

```
ableton_session     — global state, master, transport, view, tempo, signature, snapshot
ableton_track       — tracks: lifecycle, mixer state, sends
ableton_return      — return tracks
ableton_clip        — session + arrangement clips (lifecycle, set_property, replace_notes)
ableton_note        — within-clip note operations (gap #4 blocked)
ableton_device      — devices on tracks/returns
ableton_automation  — envelopes across seven target families
ableton_arrangement — arrangement layout + cue points
ableton_scene       — session-view scenes (rows of clip slots + tempo + signature)
ableton_browser     — instruments, effects, plugins
ableton_annotation  — composer-intent annotations on a song's DB (W8-C surface)
```

**Discoverability**: every tool has `action='help'` that returns the full
action menu with required/optional params, examples, and tips. Call it
when you're unsure.

## First moves for any task

1. `ableton_session(action='info')` to see global state (tempo, signature,
   transport, master mixer, track/return/scene counts).
2. `ableton_track(action='list')` to see what tracks exist.
3. `ableton_<tool>(action='help')` if the action you want isn't obvious.

## Resources vs tools

This server also exposes **resources** (URIs read via `resources/read`)
for slow-changing reads:

- `ableton://session/snapshot` — current session state in one read
- `ableton://browser/{instruments,effects,drums}` — content library trees
- `ableton://plugins/installed` — VST/AU list
- `ableton://reference/{scales,device-params}` — static lookups
- `ableton://guides/{getting-started,conventions,error-recovery,gaps}` —
  this file and three others

Prefer resources over tool calls when the data is slow-changing — they
load implicitly without consuming a turn.

## Read these next

- `ableton://guides/conventions` — addressing, value ranges, beats vs bars
- `ableton://guides/error-recovery` — common errors and the right fix
- `ableton://guides/gaps` — what NOT to attempt (gap-#4 note operations,
  arrangement-level tempo automation, envelope reads)
