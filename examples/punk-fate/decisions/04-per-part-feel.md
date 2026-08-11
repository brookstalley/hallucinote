---
kind: decision
scope: song
date: 2026-08-10
tags: [feel, groove, push, drag, performance]
---

# The band pulls against its own anchor

**Question.** What microtiming does each part carry?

**Answer.** Four different feels, baked in at generation time:

| Part | Shift | Intent |
|---|---|---|
| Guitar | every 8th ~**−0.010** beats (ahead) | The guitarist is dragging the band forward. This is the sound of a punk record |
| Bass | every 8th ~**+0.006** beats (behind) | The bassist refuses to rush. The guitar/bass gap is ~16 ticks and is the whole groove |
| Drums | snare backbeat **−0.012** (ahead), hats dead-on | Urgency in the backbeat without the kit as a whole rushing |
| Synth "vocal" | phrase starts **−0.014** (ahead) | The singer leans in at the top of every line |

**Who decided.** inferred.

**Rationale.** A punk band that is perfectly quantized sounds like a drum
machine, and a punk band that is *uniformly* humanized sounds like a sloppy drum
machine. What actually makes these records feel alive is that the parts disagree
by a consistent amount: guitar ahead, bass behind, drums holding the middle. The
tension is between the parts, not inside any one of them — so the shifts are
deterministic per part, not random jitter.

**Consequence.** Do not "humanize" this song after the fact. The feel is
authored; a post-hoc velocity/timing jitter pass would smear the guitar-vs-bass
gap that the groove depends on. Bar-1 downbeats clamp at 0.0 rather than going
negative (the mutator refuses negative absolute starts), which is correct — the
push should not exist before the song does.

---

**EXTENDED 2026-08-11 by [[08-sloppy-but-enthusiastic]] — read that one for the
live spec.** The shift column above is still exactly right and still shipping:
it is the `drag` dial on each of the four `Player` objects, and the ~16-tick
guitar-vs-bass gap is untouched. What this decision got wrong is that it was
*sufficient*. A constant per-part offset is a perfectly quantized band slid a
few ticks: measured on the committed build, the bass's grid deviation had a
**standard deviation of 0.00 ms** across all 623 notes — every note the identical
distance from the grid, which is exactly what this decision specified and
exactly why the song read as correct rather than as punk. The project's own
performance lens grades that shape *mechanical*. **1/f-correlated breathing**,
declared per player and realized by `performance.apply_profile`, now sits on top
of these offsets — not a per-note random nudge, which the same lens grades
*sloppy*.

The "do not humanize" warning stands as written: it refuses a **uniform**
post-hoc jitter pass over every part equally, which would smear the gap. It does
not refuse per-player breathing declared at generation time — and the gap
survived, measured after the rework: guitar −2.6 ms (ahead), bass +1.3 ms
(behind), 12.5 ticks apart in the declared direction.
