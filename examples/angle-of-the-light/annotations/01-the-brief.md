---
kind: annotation
scope: song
date: 2026-08-06
tags: [intent, origin, brief, tour]
---

# The brief, as given

This is the prompt that generated the song, preserved **verbatim** rather than
summarized. It is the origin document: every decision record in `decisions/`
traces back to a line in here, and `docs/tour.md` beat 1 quotes it directly.

Keeping it unedited matters for a reason beyond provenance. The brief is
*imperfect* — it has a typo, it thinks aloud, it under-budgets three of its own
best moments, and it explicitly invites correction ("I'm going to brainstorm here
so please improve where you can"). A cleaned-up version would misrepresent what
actually happened, which is the one thing a walkthrough built on real artifacts
cannot afford to do.

## Verbatim

> Let's . be more creative on demo song. It needs to be surprising, capable,
> sophisticated at all layers: harmony, melody, rhythm, genre, narrative
> strucutre. I don't know if you're heard synth demos, but they are technically
> impressive and artistically void. This little demo song, call it 45 - 60
> seconds, needs to be a tour de force of the *artistic* capabilities hallucinote
> creates. I'm going to brainstorm here so please improve where you can:
>
> - semantic meaning: we start with doubt, we claw our way to success, but we can
>   never escape doubt.
> - style: varied, constantly changing. crazy; anything could happen, and it does.
> - instrumentation, rhythm, everything varies hugely over this short song. it
>   represents our lives: so much experience, such a short time we never really
>   know what's next and we can't explain what came before
> - structure: 5-10 second spooky, tension-building intro that starts simple and
>   layers more and more harmony to modulate through common to an uncommon and
>   stressful chord
> - splash and crash into a call-and-response verse that alternates 4/4 and 3/4
> - not too much harmonic movement, but enough to be obvious this is serious work.
>   Call it 28 beats (4/4 + 3/4 * 4)
> - verse 4/4 is pushing rock and roll, 3/4 part is flat out waltz.
>   instrumentation changes, but microtiming is MORE pushing
> - a riser showing production ability
> - a brief 2 measure, 5/8 bridge that explores mechanical and robotic themes.
>   Quantized, desceneding harmony, grim
> - a surprising chord change into the chrous; the grim evaporates, the sun rises,
>   the ominous notes are suddenly major somehow
> - a triumphant march for 4 measures
> - double down on triumph but bring in hints of the verse's instrumentation and
>   rhythm for 4 more more measures.
> - a crescendo that somehow morphs into a minor key, then a diminished minor,
>   then everything pitch bends down a whole octave while it fades out over one
>   4/4 measure.
> - production: slick for the most part. great stereo, great reverb, clever
>   delays, flange/phase on key parts. But the mechanical bridge is raw; small
>   room, fewer effects. Like a punk rocker left alone with a 4 track.

A follow-up message added one instruction:

> and keep that brief as the example of the prompt that generated the song

## The one word the brief left open

"the ominous notes are suddenly major **somehow**."

That "somehow" is the only place the brief names a *destination* without a
*mechanism*, and answering it is what the whole song hangs on. The answer is in
[`../decisions/01-the-tritone-transfiguration.md`](../decisions/01-the-tritone-transfiguration.md):
the ominous chord and the radiant chord are the same five pitches, and only the
bass moves.

## What was pushed back on, and why

Three of the brief's moments were under-budgeted **by its own 45–60 s floor** —
the structure as literally written totals ~41 s at 144 BPM, so the time was
already there and unspent. The 5/8 bridge went 2 bars → 4 (two chords cannot read
as a descent), the outro 1 bar → 2 (four events in 1.7 s reads as a glitch, and
this is the thesis), and the riser ~1 bar → 2. See
[`../decisions/02-the-time-budget.md`](../decisions/02-the-time-budget.md).

One reading was made explicit rather than guessed. "instrumentation changes, but
microtiming is MORE pushing" was taken to mean *the waltz rushes harder than the
rock does* — a flat-out waltz that is also ahead of itself is genuinely
unsettling, and it makes the response contradict the call in feel as well as in
meter. See [`../decisions/03-the-microtiming-arc.md`](../decisions/03-the-microtiming-arc.md).
