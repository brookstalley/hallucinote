---
date: 2026-08-11
kind: attempt
scope: song
tags: [feel, groove, humanize, performance-profile, drums, compose-review]
outcome: kept
resolution: kept
related: ../decisions/08-sloppy-but-enthusiastic.md
---

The song read as "definitely Beethoven, but not especially punk." Three moves on
the feel; **one kept, two reverted** — and both dead ends are worth not
re-walking.

1. **Per-note white-noise scatter on top of the constant offsets.** *Reverted.*
   It does fix the diagnosed problem ([[../decisions/04-per-part-feel]]'s
   constant offset is a quantized band slid a few ticks — the bass measured
   0.00 ms of grid-deviation stdev). But memoryless noise is the *other* failure
   mode: `.prawduct/artifacts/performance-model.md` §3.8/§4.4 calls 1/f
   correlation the line between human and **sloppy**, and the repo already ships
   `performance.apply_profile` for exactly this. Measured on the attempt: drums
   `sloppy`, lag-1 acf 0.135. Caught by the Critic, not by ear.

2. **Two breathing streams for the kit** — hats on one, kick/snare on the other,
   to model a hand wobbling more than a foot. *Reverted.* It measured **worse
   than one stream**: interleaving two *independent* 1/f series in time order
   gives a combined series uncorrelated at lag 1, so the kit came back `sloppy`
   (acf 0.135) while every other part read `human`. **Two streams is two
   performers.** One stream for the whole kit: acf → 0.623.

3. **A declared `PerformanceProfile` per player, realized over the finished
   part, on top of the authored drag/accents/rush.** *Kept.* All four parts read
   `human` (acf 0.385–0.716, DFA α ≈ 1.0), and the guitar-vs-bass groove gap
   [[../decisions/04-per-part-feel]] protects survived at 12.5 ticks in the
   declared direction.

**The lesson worth keeping:** "sloppy" as a *listener* means it (not
machine-tight) and "sloppy" as the performance lens measures it (uncorrelated)
are opposite goals. The resolving fact is that the human/sloppy verdict depends
on the deviation's **correlation**, not its **magnitude** — so a punk-sized
deviation can still read human, and reaching for a bigger random nudge is
reaching down the wrong axis.

Filed as [[../decisions/08-sloppy-but-enthusiastic]].
