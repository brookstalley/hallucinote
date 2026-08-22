---
date: 2026-08-10
kind: attempt
scope: section
section: chorus-eb
tags: [arrangement, energy-arc, chorus, subtraction, compose-review]
outcome: kept
resolution: kept
---

`/compose-review` read the first pass and found the chorus at **49.0 notes/bar**
against a verse at **49.2** — the relative-major lift the brief declared existed
only in articulation (guitar 0.45 vs 0.22 beat hits) and in the vocal apex.

**Tried three things; kept two.**

1. **Verse bars 1–8 guitar → quarters** (bass keeps 8ths). *Kept.* Verse becomes
   37 → 49 internally; the chorus finally has something to arrive against. The
   cheapest fix in the fix order and the one that did the most work.
2. **Chorus vocal doubled at the octave.** *Kept.* Widens register, not just
   count. Chorus → 53.0. The melody lens still reads the top voice, so the line's
   measured shape is unchanged — confirmed by re-running it.
3. **Chorus drums `kick_pickup=True`.** *Reverted.* It got the chorus to 54.0 —
   *above* the finale's 49.5, which makes the chorus the song's peak and the
   C-major payoff an anticlimax. Removed, and the finale got the gang-vocal
   doubling instead, landing at 53.5 just above the chorus's 53.0.

**The lesson worth keeping:** when a section won't lift, check what it would
overtake before adding to it. The fix for "the chorus is too small" was one part
subtraction in the *previous* section and one part register in the chorus — never
more drums.

Filed as [[../decisions/06-the-chorus-has-to-arrive]].
