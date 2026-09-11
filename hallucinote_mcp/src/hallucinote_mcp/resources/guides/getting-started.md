# Getting started

## First moves
- For a quick exploration: `ableton_session(action='info')` reads tempo / track-count / master in one shot.
- For a new song from a prompt: `/song-brief "<prompt>"` **first** — a conversation
  that runs until the user hands off, resolving the tempo / meter / section values
  `/song-new` requires as arguments so they aren't invented at a command line.
  Then `/song-new` (see also `/song-pick-instruments`). Compose the first hearable
  unit and offer to play it before building the rest. `/song-workflow` is the whole
  lifecycle map.
- For pushing an existing song into Live: `/ableton-push <slug>` from its directory.

## Per-song composer intent
A song's declared intent + decision rationale live in git-tracked markdown, not
the DB — query them before non-trivial composition with `/song-context <slug>`
(intent + decisions) and `/song-attempts <slug>` (what was already tried on a
part, including reverted dead ends). Not derivable from the DB schema. A song
built on a sample reads the line first with `/sample-lens <slug> <source>`.

## Also read
- `ableton://guides/conventions` — indexing, time semantics, value-range gotchas.
- `ableton://guides/gaps` — what's still blocked at the API level + the canonical workaround.
- `ableton://guides/error-recovery` — structured-error recipes for the common stalls.
