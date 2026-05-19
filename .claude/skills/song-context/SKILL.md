---
description: Query a song's composer intent + decision rationale (decisions + annotations) before non-trivial composition work. Markdown-primary; FTS5-indexed.
argument-hint: "[topic] [--kind decision|annotation] [--scope song|time|track|track-time] [--track NAME] [--tags t1,t2] [--bars START:END]"
user-invocable: true
disable-model-invocation: false
context: fork
allowed-tools: Bash, Read
---

You are retrieving relevant composer intent + decision rationale for a song. This keeps the caller's context clean by returning only matching refs.

## When to invoke

**Run `/song-context` proactively before any non-trivial composition or arrangement work on a song.** Composition examples that warrant a pre-task retrieval:

- "Add a counter-melody to the bridge" → query `--bars 48:56` and topic 'bridge counter-melody'.
- "Adjust the chorus bass" → query `--track "03 Synth Bass" --kind decision` to surface prior bass decisions.
- "Make the chorus brighter" → query topic 'chorus brightness' or 'chorus pad' to surface tone-related prior choices.
- "Why is this passage like this?" → query `--bars <bar>:<bar+1>` to find decisions touching that range.

Skip retrieval only for purely mechanical edits (typos, renaming a clip, fixing a wrong note) where prior rationale won't change the answer. When in doubt, query — the cost is one Bash call returning markdown.

## How it works

Each song in `songs/<name>/` carries composer intent in two atomic-file directories:

- `songs/<name>/decisions/YYYY-MM-DD-slug.md` — deliberate choices with rationale (ADR-shaped, dated)
- `songs/<name>/annotations/slug.md` — timeless scoped intent (section feel, sound-design palette, don't-do warnings)

Both layers are indexed into the song's SQLite DB via `markdown_refs` + an FTS5 virtual table. The retrieval surface is `tools/song_context.py` — it runs a filtered query and prints markdown-formatted matches.

See `.prawduct/artifacts/song-conventions.md` for the full frontmatter schema and authoring conventions.

## Invocation

$ARGUMENTS

**Step 1 — Identify the active song.** Look at the caller's recent file activity / CWD. If a single song folder is in play (any file in `songs/<name>/` touched recently), use that song's DB: `songs/<name>/<name>.db`. If unclear, ask which song.

**Step 2 — Run the query.** Invoke `tools/song_context.py` via Bash with the appropriate filters. Examples:

```bash
# Fulltext search
python3 tools/song_context.py --db songs/falling-walking/falling-walking.db "dim7 bridge"

# Filter by kind
python3 tools/song_context.py --db songs/falling-walking/falling-walking.db --kind decision

# Filter by tags + bars
python3 tools/song_context.py --db songs/falling-walking/falling-walking.db --tags chorus --bars 33:40

# Combined
python3 tools/song_context.py --db songs/falling-walking/falling-walking.db --kind decision --tags pad
```

Translate the caller's topic + any natural-language filters into the appropriate flag combination:
- Bar ranges ("bars 33-40", "the bridge section") → `--bars START:END`. Use the overview doc for section→bar mapping if needed.
- Track names → `--track "NAME"` (resolves to track_id via `tracks.name` lookup). Use `--scope track` only when you want to filter further.
- Conceptual queries → use `topic` for fulltext + optional `--kind` / `--scope` filters.

**Step 3 — Display the result.** The script outputs markdown — show it to the caller as-is. Then, if a result looks load-bearing for the caller's work, **Read the file** so the full prose lands in the caller's context.

## Important

- This is a **read-only lookup**. Do not modify any files.
- If the query returns nothing, say so and suggest a broader query (e.g., drop tag filter, widen bar range).
- If the song's DB doesn't have `markdown_refs` populated yet, run `python3 tools/reindex_markdown.py <db>` first.
- The retrieval surface filters; the LLM does the synthesis. Don't try to summarize matches across files — return the matches, optionally Read the ones that matter, and let the caller integrate them.
