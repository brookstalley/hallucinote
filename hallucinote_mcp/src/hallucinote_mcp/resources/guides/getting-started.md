# Getting started

## First moves
- For a quick exploration: `ableton_session(action='info')` reads tempo / track-count / master in one shot.
- For new song scaffolding: `/song-new <prompt>` (see also `/song-pick-instruments`).
- For pushing an existing song into Live: `/ableton-push <slug>` from its directory.

## Per-song composer intent
A song's declared intent + decision rationale live in git-tracked markdown, not
the DB — query them before non-trivial composition with `/song-context <slug>`
(intent + decisions) and `/song-attempts <slug>` (what was already tried on a
part, including reverted dead ends). Not derivable from the DB schema.

## Also read
- `ableton://guides/conventions` — indexing, time semantics, value-range gotchas.
- `ableton://guides/gaps` — what's still blocked at the API level + the canonical workaround.
- `ableton://guides/error-recovery` — structured-error recipes for the common stalls.
