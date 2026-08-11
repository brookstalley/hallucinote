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
