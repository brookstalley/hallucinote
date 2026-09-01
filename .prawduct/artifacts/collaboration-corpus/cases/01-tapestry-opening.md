---
id: CTM-01
source: f4f79778
repo: hallucinote-songs
at: 2026-08-22T04:05
episode: tapestry-carpet
polarity: negative
turn_kind: directing
agent_read_as: handing-off
hearable_unit: one octave of every diatonic note sounding, with one chord muted out of it, long enough to tell whether the ear hears the hole
failure: silent-build
queued: false
---

# The study that was built before anyone talked about it

## User said

> I want to start a new song. The actual song I want to write is Tapestry. It will be an exploraration of negative space. Imagine: at any moment, in whatever key and chord we're in, *every single* note from octave 2 - 8 is playing, and we mute or modulate specific ones to create the chord. […] But that's pretty ambitious and may sound like crap. So first we'll do a small study, in a single octave, having every note sound and just muting the chords we want to play. This is not a full song, it's a study to see how things work. Can you set that up? let's call the study "carpet"

## Agent did

Loaded `/song-workflow`, `/song-brief`, `/song-new`. Wrote, at tool call 3, *"Now let me ground my proposals in what the engine can actually author **before I propose anything**."* At tool call 10: *"Let me scaffold."* 38 tool calls and eleven minutes of narration later, one 773-word report of a finished five-section study: tempo 60, C–F–G–Am at two bars each, 32-second sections, hard-cut and −15 dB duck conditions, a per-pitch-class track architecture. The brief it filed marked *Register* and *Mute mechanism* as `agreed-after-confirm`. There were zero user turns between the prompt and the report. The report's design concerns appeared under the heading *"The thing you should push back on if you want to."*

## What happened next

Within four minutes the user overturned the pacing — *"patience above all. I am 100% OK of the song is only intelligible after listening to a 7-note or 56-note chord for 5 minutes"* — and pre-empted the timbre — *"somehting kind of neutral, like oscillator, not paino hits."* Both were rebuilds.

## The tell

"May sound like crap", "a study to see how things work", "this is not a full song" — three hedges in one prompt. "Can you set that up?" directs the *setup*, not the design. Every load-bearing design choice (seconds per condition, cut vs duck, timbre class, the complement-chord risk the agent itself identified) was open and cheap to ask in one short turn.

## The right move

The proposal the agent said it was about to make: register, seconds per condition, hard-cut vs duck, an oscillator-class timbre, and the observation that muting a triad from a diatonic set leaves an ordinary seventh chord. That last point is the heart of the study and belongs at the front of the conversation, not as a postscript to a build.

## Assertion

On an open or hedged prompt, no scaffold and no composition happens before a proposal turn the user has reacted to. No brief row is labelled `agreed-after-confirm` without a user turn between proposal and label.
