# Feature request — sample-accurate, semantically-addressed device-parameter clip envelopes (driver: swell's windowed sample reveal) (2026-06-12)

Context: hallucinote-songs `swell`. Engine 0.9.0, hallucinote-mcp 0.1.0, Live 12.x.
Design: `songs/swell/decisions/17-buried-we-centerpiece.md`. Pairs with the
sample-instrument request; the windowed-reveal *generator* that consumes these
envelopes is song-local (see that request's "Scope boundary" note).

## The need
swell windows a sample per phrase via Simpler `S Start`/`S Length`
(probe-confirmed automatable) and flips Sampler `Reverse` at the phrase center.
These are **per-phrase, tightly-timed** moves: the phrase center sits on the
fixed eighth-note ruler (`decisions/02-breath-scalar.md`) and the window edges
decide where the words appear. Two requirements for them to hold up:

### 1. Sample-accurate, clip-scoped `device_parameter` envelopes
`decisions/16-meter-hat-and-master-swell.md` records that the master-swell bus
ride is only **perform-fidelity** (~2.5 Hz gesture-record) *because the bus
carries no clip*. The sample-instrument track **does** carry a triggering MIDI
clip, so its device-parameter envelopes can be **clip envelopes** —
sample-accurate. Please **confirm the push materializes clip-scoped
`device_parameter` envelopes sample-accurately** (not via the perform path); if
only the perform path exists for device params today, **add the clip-envelope
path**. Per-phrase window edges blur to mush at 2.5 Hz — the precision is the
whole point of the device.

### 2. Semantic addressing (survive re-push)
Author the envelope target as **(track role/name + device kind + parameter
name)**, resolved at push like the `set_track_routing` FK in decision 16 —
surviving device re-creation, renames, and the rebuild→push loop. Building
against raw device indices is brittle exactly where swell re-pushes most.

## Ordering note
`S Start`/`S Length`/`Reverse` are **device-wide, not per-note**; each phrase's
value must land **at or just before** the trigger note-on (one-shot evaluation at
note-on). The push should guarantee the breakpoint precedes the note, or document
the convention, so a window doesn't play with the *previous* phrase's settings.

## Acceptance
A per-phrase `S Start`/`S Length` envelope authored by semantic reference pushes
and plays with window edges on the intended eighth-note positions
(sample-accurate), stable across re-push.
