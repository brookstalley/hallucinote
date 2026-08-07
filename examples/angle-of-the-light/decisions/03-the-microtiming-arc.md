---
date: 2026-08-06
kind: decision
scope: song
tags: [feel, microtiming, groove, arc]
---

## Context

The brief specifies feel per section: the verse's 4/4 is "pushing rock and roll",
its 3/4 is "flat out waltz", and then — the line that needed a reading —
"instrumentation changes, but microtiming is MORE pushing." The bridge is
"quantized"; the chorus is a "triumphant march."

Microtiming is authorship here, not a post-hoc humanize pass, so this had to be
decided before the parts were written rather than dialed afterward.

## Decision

A single arc across the whole piece, baked in at generation time per part:

    intro            free / rubato     no grid at all; bell tones placed by hand
    verse 4/4        +10 -> +30 ms     escalating push across the four cycles
    verse 3/4        MORE than the 4/4  the waltz out-rushes the rock
    riser            accelerating      the push collapses into the sweep
    bridge           EXACTLY 0 ms      hard quantize, no deviation anywhere
    chorus march     ~+5 ms            tight and confident, not rushing
    chorus reprise   two feels at once the verse push layered against the march
    outro            drag (negative)   everything falls behind as it collapses

The ambiguous line is read as: **the 3/4 waltz pushes harder than the 4/4 rock.**

## Why

The reading matters and could have gone the other way (it could have meant "the
verse escalates overall"). The waltz-pushes-harder reading was chosen because it is
the more interesting musical claim and it serves the call-and-response structure the
brief asks for: if the 4/4 is the call and the 3/4 is the response, then the response
already contradicts the call in **meter** and in **instrumentation**. Having it also
contradict in **feel** — answering a rushing rock bar with something even more
rushed, in a genre whose whole character is supposed to be poised — makes the answer
genuinely unsettling rather than merely different. A flat-out waltz that is also
ahead of itself is wrong in a way a listener feels before they can name.

The escalation across the four cycles (+10 -> +30 ms) is the anxiety accumulating
rather than sitting still, which is what stops a 28-beat verse with little harmonic
movement from feeling static.

The bridge's exact zero is the load-bearing contrast. Every other section in this
piece has a human hand in its timing; the bridge has none, and that absence is the
grimness — more than the descending harmony or the bit-crushed production, both of
which are decoration on the same idea. It only reads as absence because there is an
arc for it to be absent FROM.

## Narrative to sound

Pushing is wanting to get somewhere. The verse rushes because it is clawing, and it
rushes harder as it goes because clawing is exhausting and desperate, not measured.
The bridge stops pushing because machines do not want anything. The march does not
push because arrival does not need to hurry — it is the only section that is
comfortable in its own tempo, which is what makes it feel like triumph. And the
outro drags because falling is slower than climbing.

Decided by: agreed-after-confirm (the reading of the ambiguous line was stated
explicitly rather than assumed, and accepted).
