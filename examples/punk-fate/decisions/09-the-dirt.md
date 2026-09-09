---
kind: decision
scope: song
date: 2026-08-11
tags: [sound-design, chains, distortion, saturation, mix, headroom, portability]
---

# The dirt — two more gain stages, and where Live let them go

**Question.** "Where's the distortion?" Two of the four tracks carried dirt
(drum Saturator, bass Saturator); the guitar and the synth "vocal" — the two
loudest punk signatures in the band — carried none.

**Who decided.** User, by ear. [[05-signal-chains]] had already named the exact
knob to reach for: *"If it wants more dirt by ear, add Pedal `Guitar Dirt`
before the compressor — that's the knob to reach for."* This is that moment;
the decision anticipated it correctly.

## What changed

| Track | Before | After |
|---|---|---|
| **01 Drums** | Garage Kit → Saturator *Hard Punch* → Glue Comp | same chain, Saturator **Drive 6.9 → 11.0 dB**, **Output −11 → −13.5 dB** |
| **03 Guitar** | Dual Amped Crunch → Glue Comp | → Glue Comp → **Pedal *Guitar Dirt*** |
| **04 Voice** | Square Dirty Lead → Glue Comp | → Glue Comp → **Saturator *Rough Tone*** |
| **02 Bass** | *Gritty Bass* Saturator already present | unchanged — it was never the problem |

The drum Saturator's output came down as its drive went up, so the added grit is
*timbre*, not level. All 14 devices remain stock Live (`compat check --probe`:
**14/14 native**), so `portability=strict` still holds and
`REQUIREMENTS.md` still lists no third-party installs.

**Voice, not fuzz.** The synth vocal is already a square wave — stacking fuzz on
a square is mush. *Rough Tone* adds midrange bite and clipping, which is what a
shouted voice through a cheap PA actually does.

## The chain position is Live's constraint, not a choice

[[05-signal-chains]] said *before* the compressor. **It is after it**, and that
is not an oversight: `ableton_device(action='load')` tail-appends, and Live 12.4
exposes **no reorder API** — the push refuses to insert mid-chain rather than
silently double a signal path. Reaching the authored order would mean deleting
and re-adding the compressor, losing its preset, to buy a difference that cuts
the other way for this genre: compressing first and driving second saturates a
signal whose dynamics are already even, which is *more* wall-of-sound, not less.
Taken deliberately, recorded rather than quietly re-specified.

**The one thing this cost.** Both new devices appended *after* the
HallucinoteAnalyzer, which is the capture tap — so the analyzer stopped being
terminal and the stems would have been captured **pre-distortion**. Deleting the
analyzer and letting the render's auto-load put it back at the tail fixed it;
the manifest now reports `terminal: true` on all four tracks and
`analyzer_not_terminal: []`. **Anything appended to a chain after a render has
to re-check this** — the render reports `ok` either way, and a pre-dirt stem
looks like a perfectly good capture.

## Headroom held — measured, not assumed

[[07-the-bass-carries-the-engine]] bought its headroom the hard way, so two new
gain stages had to be checked rather than hoped about. A 16-bar verse render
(beats 32–64), analyzed:

| | value |
|---|---|
| master true peak (bus, pre-fader) | **+0.13 dBTP** |
| **delivered true peak** (after the −4 dB master fader) | **−3.87 dBTP** |
| **overshoots** | **0** |
| `master_fader_db` | −4.0 — **read correctly**, not the stale `0.0` that trap in [[07-the-bass-carries-the-engine]] warns about |

The single finding is `master_clipping_risk` at **severity `info`** (bus peak
above a −1.0 dBTP reference), which the −4 dB fader already answers. Saturation
*reduces* peaks while raising density, so the dirt cost density, not headroom.

### Then the full song, all eight sections

The verse window left the loudest material unmeasured, so the whole arrangement
was rendered (384 beats + 8 ring-out) and analyzed:

| | verse window | **full song, current** | [[07-the-bass-carries-the-engine]] |
|---|---|---|---|
| master true peak (bus) | +0.13 | **+1.93 dBTP** | +1.29 dBTP |
| delivered true peak | −3.87 | **−2.07 dBTP** | ≈ −2.7 dBTP |
| overshoots | 0 | **4** | 1 |
| sections analyzed | 1 | **8** | 8 |

**This number has run-to-run spread, and quoting one run as exact would be
false precision.** Three full-song renders of materially identical arrangements
came back at delivered **−2.59 / −2.60 / −2.07 dBTP** with **3 / 2 / 4**
overshoots. The capture is a *realtime* pass through Live, not an offline bounce,
so buffer alignment moves the sampled peak between runs. Read this as **delivered
≈ −2.1 to −2.6 dBTP, 2–4 pre-fader bus overshoots**, not as a fixed figure — and
if a future pass wants to detect a real change, it needs a delta bigger than that
spread.

**The honest delta: the dirt costs roughly 0.5–0.6 dB of bus peak and a couple
more overshoots** than the state [[07-the-bass-carries-the-engine]] reached. All
are `severity: warning` and all sit on the **pre-fader bus**; delivered never
approached 0 dBTP, so nothing clips at the output — and the master fader is not
the lever that would move them, trimming a stem is.

Left as-is, deliberately: a handful of transient bus overshoots across 115
seconds of music whose stated production stance is *raw and blown-out basement
punk* is a measurement worth recording, not a defect worth flattening. It is
written down so the next pass can disagree with numbers in hand rather than
rediscover them.

**Where the evidence lives.** `measurements/2026-08-11-punk-pass-full-song.json`
— committed next to the song, not left in `/tmp` where a citation dangles for
every later reader. It is deliberately *not* in `analysis/`: that directory holds
exactly the before/after pair the tour narrates, and
`tests/preferences/test_tour_freshness.py` asserts the pair is exactly two, so
filing a third there breaks the tour's evidence contract. Promoting a run into
the tour's set is a tour edit, and belongs with whoever re-cuts that narrative.

**Where the report lives.** `/tmp/punk-fate-renders/analysis/20260811T164051Z.json`,
deliberately *not* `analysis/`. That directory holds exactly the before/after
pair the tour narrates, and `tests/preferences/test_tour_freshness.py` asserts
the pair is exactly two — a working measurement filed there breaks the tour's
evidence contract. Re-run it into the song only when it becomes the song's
evidence, not while it is still a probe.
