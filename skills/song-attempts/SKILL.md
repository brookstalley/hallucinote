---
description: Query a song's attempt ledger — what was tried on a part/section and how it turned out (incl. reverted dead ends) — BEFORE re-trying something. The compositional/mix sibling of /song-context; pull-only, read-only. Use when about to change a part you've worked before ("we tried something on the bagpipes already, didn't we?"), or asked "what have we tried on X?", "did the notch work?", "why isn't there a filter here anymore?".
argument-hint: "[part-or-topic] [--outcome worked|partial|failed] [--track NAME] [--bars START:END]"
user-invocable: true
disable-model-invocation: false
context: fork
allowed-tools: Bash, Read
---

You are retrieving a song's **attempt ledger** — the chronological record of moves
*tried* on a part and how each turned out, including the ones that were reverted. The
point is to **read before you re-try**: don't re-propose a move the ledger already shows
failed. This keeps the caller's context clean by returning only matching attempt rows.

## When to invoke

**Before re-touching a part you (or a prior session) have worked before** — especially in
the mix and in iterative composition. Examples:

- "Let's tame the bagpipes" → query `--kind attempt "bagpipes"` first; if a notch already
  failed and a gate was kept, you start from the gate, not the notch.
- "Add more layers to lift the chorus" → query `"chorus"`; maybe layering was tried and
  muddied it, and subtraction was what worked.
- "Why is there no filter on the lead anymore?" → query `--track Lead` or `"lead filter"`;
  the ledger explains the revert.
- "What have we tried here that didn't work?" → `--outcome failed`.

This is the attempt-trail sibling of `/song-context` (intent + decisions). Reach for
`/song-attempts` when the question is *"what have we already tried, and how did it go?"*;
reach for `/song-context` when it's *"what did we decide / intend?"*.

## How it works

Attempts live as atomic files under `songs/<name>/attempts/<date>-slug.md`, each a
`kind: attempt` markdown ref with `outcome` (worked | partial | failed) and `resolution`
(kept | reverted | superseded). A correction reads as a chain: the failed attempt's
`related:` links forward to the entry that replaced it. The retrieval surface is the same
`hallucinote.tools.song_context` query layer, filtered to `--kind attempt`.

See `.prawduct/artifacts/song-conventions.md` ("The attempt ledger") for the full schema,
the worked example, and what does / doesn't belong here.

## Invocation

$ARGUMENTS

**Step 1 — Identify the active song.** From the caller's recent file activity / CWD. If a
single `songs/<name>/` is in play, use `songs/<name>/<name>.db`. If unclear, ask which song.

**Step 2 — Run the query.** Always pass `--kind attempt`. Prefer a **fulltext part name**
over `--track` for the "what have we tried on X" question — `--track` resolves the name to a
built track row, so it returns nothing for a part that hasn't been pushed yet; fulltext
matches the prose and tags regardless.

```bash
# What have we tried on the bagpipes, and how did it go?
python3 -m hallucinote.tools.song_context --db songs/highland/highland.db --kind attempt "bagpipes"

# Just the dead ends (read-before-you-retry)
python3 -m hallucinote.tools.song_context --db songs/highland/highland.db --kind attempt --outcome failed

# The whole ledger, most-recent first
python3 -m hallucinote.tools.song_context --db songs/highland/highland.db --kind attempt

# Scoped to a section's bars
python3 -m hallucinote.tools.song_context --db songs/highland/highland.db --kind attempt --bars 33:40
```

**Step 3 — Display + follow the chain.** Show the markdown output as-is. When a `failed` /
`reverted` row is load-bearing for the caller's plan, **Read the file** so the full story
lands in context, and follow its `related:` link to the entry that superseded it — that
forward link is *what worked instead*.

## Important

- **Read-only lookup.** Do not modify files. (Writing an attempt is the job of
  `/compose-review`, `/mix-review`, or a deliberate "log this" during iteration — they call
  `write_markdown_ref(kind='attempt', …)`.)
- **Inform, never verdict.** A `failed` row means "this move didn't achieve *its* goal *in
  this song*" — read it the way `--defensive` frames a constraint ("read before composing
  against it"), not as "never do this." Context differs across songs; the ledger is
  per-song memory, not a rule.
- If the query returns nothing, say so — there may simply be no recorded attempts yet on
  this part. Suggest a broader query (drop `--outcome`, widen to the whole ledger).
- If the DB has no `markdown_refs` rows yet, run
  `python3 -m hallucinote.tools.reindex_markdown <db>` first.
