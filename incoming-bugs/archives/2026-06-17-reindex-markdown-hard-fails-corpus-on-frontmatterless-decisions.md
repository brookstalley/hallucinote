# `reindex_markdown` hard-fails the WHOLE corpus on a frontmatter-less `decisions/*.md` (so `/song-context` FTS over decisions is silently broken)

**Date:** 2026-06-17
**Severity:** low-medium — silent search degradation. The FTS5 index that
`/song-context` searches is never refreshed for a song whose decisions lack
frontmatter; the failure only surfaces if you run the reindexer by hand.

## Repro (swell, real)

```
python3 -m hallucinote.tools.reindex_markdown songs/swell/swell-compose--swell.db \
  --songs-root songs --repo-root .
```
→
```
ValueError: failed to parse …/songs/swell/decisions/01-intent-and-theme.md:
            missing frontmatter delimiter on line 1
```

`load_markdown_doc` (`src/hallucinote/markdown_refs.py:343`) raises on the first
file with no `---` frontmatter, and `reindex_corpus` (`:464`,
`docs = [load_markdown_doc(p, …) for p in corpus]`) is a list comprehension — so
**one malformed file aborts the entire corpus**, indexing nothing.

## Scope — it's not one file

In swell, **all 23** `decisions/*.md` start with `# NN — Title`, NO frontmatter;
all 7 `annotations/*.md` DO have frontmatter. The reindexer globs BOTH
(`decisions/*.md` + `annotations/*.md` per its own docstring) and dies on
`decisions/01`. So swell's decisions corpus has likely NEVER been FTS-indexed, and
`/song-context` (which advertises "decisions + annotations … FTS5-indexed") silently
returns nothing from decisions for this song. Any song scaffolded the same way is
affected.

Mismatch: the decisions-authoring convention (and/or the scaffold) emits
frontmatter-less `# heading` decisions, but the indexer REQUIRES frontmatter.

## Proposed fix (two independent, both cheap)

1. **Resilience:** `reindex_corpus` should skip-and-warn per file, not abort the
   corpus — wrap the comprehension so one unparseable doc is counted/reported and
   the rest still index. A broken doc shouldn't blind search to all the good ones.
2. **Tolerance:** `load_markdown_doc` should treat a missing-frontmatter file as
   empty metadata + index the body (title from the first `# ` heading), rather than
   raising — decisions are legitimately frontmatter-optional. OR: make the decisions
   scaffold/CLI emit a minimal frontmatter block so the corpus is uniform.

Pick (1) regardless — it's the difference between "this song's search is degraded"
and "this song's search is dead."

## Discovered while

Baking the swell voice-LFO `param_overrides` (separate report
`2026-06-17-param-overrides-cannot-carry-quantized-nonunit-range-param.md`); ran
the reindexer to refresh after editing an annotation and hit this.
