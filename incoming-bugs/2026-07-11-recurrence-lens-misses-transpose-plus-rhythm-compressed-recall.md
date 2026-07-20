# Recurrence lens: blind to a transpose ∘ rhythm-compressed recall (the payoff recall, in practice)

**Type:** lens capability gap.
**Severity:** M. The lens's variation vocabulary covers single transforms
(`transpose` / `augment` / `diminish` / …) and *bounded compositions like
`diminish∘fragment`*, but in the wild the most dramatically important recall of a
song combined transpose with a rhythm compression whose onsets halved but whose
durations didn't — and the lens reported **no recall at all** (not even `derived`).

**Engine / server:** current main-era. Surfaced on song `missing` (branch
`compose/missing`), `/compose-review` pass 2026-07-11.

## The gap

`missing`'s whole recurrence architecture converges on one moment: the coda restates
the registered `reach` motif (B → D# → F#, home in verse1) and it finally **ends on
E** — the question the song asks, answered. Authored form vs home form:

- home (verse1): pitches 59/63/66, onsets 0.0/4.0/8.0, durations 1.5/2.0/1.5
- coda recall: pitches 71/75/78 (+12), onsets 32.0/34.0/36.0 (spacing exactly
  halved), durations 1.5/1.5/1.0 (NOT halved), followed by an added landed E5

So the true variation is `transpose(+12) ∘ onset-diminish(0.5)` with free durations,
plus a coda-only extension note. `hallucinote.cli recurrence missing` reports recalls
in chorus1/verse2/chorus2/break/finalchorus but **nothing in the coda** — the one
recall the composer would most want confirmed ("does the outro recall land?" is the
skill's own canonical example question).

By ear the recall is unmistakable (identical interval cell, same contour). The miss
seems to be that (a) composed transforms beyond the bounded set aren't searched, and
(b) the duration channel is treated as part of the rhythm-transform match, so
onset-only compression with sung/held durations falls through entirely instead of
degrading to `derived`.

## Why it matters

The skill doc positions `derived` as "a partial recall I can't fully name" — that
grade existing implies near-misses should degrade gracefully, not vanish. A recall
that returns transposed *and* rhythmically tightened is one of the most common
expressive recapitulation shapes (arrival statements compress). If the lens goes
silent exactly there, /compose-review reads "no recall in the coda" as a form fact
and may flag a recap that IS authored.

Secondary, same pass: `verse3`'s two deliberately *abandoned* reach attempts
(2–3 notes each, the abandonment is the point) are also invisible — arguably correct
(coverage below any fragment threshold), but a `fragment` reading with low coverage
would have let the review say "the lens sees the attempts break off," which is the
authored narrative. Worth considering a floor-coverage `derived`/`fragment` tier.

## Repro

```
git worktree add /tmp/wt-missing compose/missing
cd /tmp/wt-missing
uv run --project ~/source/hallucinote python -m hallucinote.cli recurrence missing
# → 6 recalls, none in [coda]; _lead_coda() in songs/missing/build.py:956 plainly
#   restates the reach motif at beats 32–38 transposed +12 with halved onset spacing
```
