---
date: 2026-05-20
kind: decision
scope: song
tags: [meter, generator-constraint]
---

**Decided by:** inferred

# Time signature: 4/4

## Question
What meter does the song use?

## Answer
4/4 throughout. No meter changes between sections.

## Rationale
- **Genre fit.** Punk rock is overwhelmingly 4/4. Anything else would fight the idiom.
- **Source-material fit.** Beethoven's 5th Movement I is in 2/4 — which in punk-rock terms reads as straight 4/4 with the half-bar feel coming from the riff phrasing, not the meter itself.
- **Tooling constraint.** Hallucinote's pattern generators today assume 4/4 (Wave 0 finding H2; W14-B is the future meter-parametrized work). Picking 4/4 means we can use generators (`/pattern-compose` etc.) without hand-authoring around the constraint.

## What this binds
- Compose time can use `/pattern-compose` for drum patterns without meter-adapter work
- The fate motif (short-short-short-LONG) sits cleanly on beats 1-2-3-4 of a bar
