---
kind: decision
scope: song
date: 2026-08-10
tags: [sound-design, chains, instruments, portability]
---

# Signal chains — four tracks, four amps' worth of dirt

**Question.** What actually makes the sound of a basement punk four-piece, given
stock Live content only (`portability=strict`)?

**Who decided.** inferred, from the brief's production stance ("raw and
blown-out — saturated drum bus, distorted bass doubling the guitar, one short
room send, no polish").

| Track | Chain | Sends | Why this combination |
|---|---|---|---|
| **01 Drums** | Drum Rack *Garage Kit* → Saturator *Hard Punch* → Glue Compressor *Drum - Rock Parallel Room* | Reverb .12 | A real kit, not a machine — then driven and glued so the 200 BPM 8th-note hats stay a texture rather than a rattle. The parallel-room glue is what makes a four-piece sound like it's in a room instead of on a grid |
| **02 Bass** | Instrument Rack *Electric Bass Palm* → Saturator *Gritty Bass* → Glue Compressor *Bass - Punch* | dry | Palm-muted, because at 1.2 s a bar an open bass note is mud. The grit is what lets the bass double the guitar riff and still be heard as a separate instrument |
| **03 Guitar** | Instrument Rack *Guitar-Dual Amped Crunch* → Glue Compressor *Guitar - Controlled Dynamics* | Reverb .08, Delay .05 | Crunch, deliberately **not** *Dual Amped Heavy*: punk guitar is mid-forward, and a scooped metal tone would leave a hole exactly where the vocal synth lives. The compressor is load-bearing — fast downstroke 8ths disappear without it |
| **04 Voice** | Operator *Square Dirty Lead* → Glue Compressor *Guitar - Lead Solo* | Reverb .18, Delay .22 | A square wave sits in roughly the formant territory of a shouted vocal, which is the only reason a synth can credibly *sing* here. Room + slapback is the punk vocal treatment, applied to a thing that isn't a voice |

**Portability.** Every device is stock Live content selected by `preset_query`
(root + exact pattern + path prefix), so nothing bakes a per-machine FileId.
`compat check --probe` resolves 12/12 native on this machine with zero issues.

**The one thing that is deliberately absent.** No amp sim on top of the guitar.
*Dual Amped Crunch* already stacks two; a third gain stage at this tempo turns
the 8th-note wall into a single sustained buzz. The song's weight comes from the
drum saturation and the bass grit instead. If it wants more dirt by ear, add
Pedal *Guitar Dirt* before the compressor — that's the knob to reach for.

---

**SUPERSEDED 2026-08-11 by [[09-the-dirt]] for the guitar and voice rows.** It
wanted more dirt by ear, and the knob named above was the right one — Pedal
*Guitar Dirt* is now on the guitar, and Saturator *Rough Tone* on the voice.
Two caveats worth carrying back here:

- **Position.** Both landed *after* the Glue Compressor, not before it as this
  decision specifies. Live 12.4 has no reorder API and a device load
  tail-appends, so the authored order is not reachable without deleting and
  re-adding the compressor. See [[09-the-dirt]] for why post-compressor is
  defensible for this genre rather than merely tolerated.
- **The prediction held.** A third gain stage did not turn the wall into a
  sustained buzz — because the drive is post-compressor and the measured
  delivered peak stayed at −3.87 dBTP with zero overshoots. The concern was
  right to record; it just didn't bind.

---

**SUPERSEDED AGAIN 2026-08-11 — this table's *devices* were right and its
*settings* were never checked.** [[10-it-has-to-sound-punk]] found the guitar
row's *Dual Amped **Crunch*** running `Amp Type: Blues`, the Pedal *Guitar
Dirt* at **1.6 % drive**, and an undeclared **24 %-wet Reverb inside the guitar
rack** — so the chain this decision specifies was assembled correctly and sounded
clean. The rule it earned: **a preset name is a claim, not a measurement** — read
back the parameters that carry the intent after loading a chain.

**The Voice row is retired entirely by [[11-the-vocal-line-is-a-lead-guitar]].**
The square-wave formant argument above is sound about frequency range and wrong
about genre: it made the line legible as a vocal, not human, and it read as "main
street electrical parade". Track 4 is now a second guitar — `Guitar-Dual Amped
Heavy` on `Lead` amps. Two consequences flow back here:

- **The guitar row's "deliberately not *Dual Amped Heavy*" reasoning is void.**
  It was rejected because "a scooped metal tone would leave a hole exactly where
  the vocal synth lives." There is no vocal synth; the hole is now where the lead
  guitar belongs.
- **The master row this table never had is the real omission.** No compressor or
  limiter was specified for the master at all, so three passes bought loudness by
  pulling faders down. [[10-it-has-to-sound-punk]] added Glue → Limiter.
