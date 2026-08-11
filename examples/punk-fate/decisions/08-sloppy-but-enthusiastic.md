---
kind: decision
scope: song
date: 2026-08-11
tags: [feel, groove, humanize, performance-profile, drums, garage, punk]
---

# Sloppy but enthusiastic — four players, not four offsets

**Question.** The song was "definitely Beethoven, but not especially punk. Where
are the garage drums? Where's the sloppy but enthusiastic timing?"

**Who decided.** User, by ear; diagnosed in the code, then corrected once against
the project's own performance model (see *The correction* below).

## The diagnosis: a constant offset is not sloppiness

[[04-per-part-feel]] shifted each part by a fixed amount — guitar −0.010 beats,
bass +0.006, snare −0.012. That is a **perfectly quantized band with two tracks
slid a few ticks**. Measured on the committed build, the bass sat at **0.00 ms of
grid deviation** — every one of its 623 notes the identical distance from the
grid.

The cause is structural. `generators.primitives.apply_feel` keys its shift on the
**within-bar position**, so bar 3 beat 2 gets the same offset as bar 47 beat 2,
forever. The lookup *cannot express* bar-to-bar variance. The performance lens
grades exactly this shape **mechanical** — "tightness, not lateness, is the
mechanical signal".

## The correction: white noise is the OTHER failure

The first fix here was a hand-rolled per-note random nudge. That was wrong, and
the Critic caught it against
[`.prawduct/artifacts/performance-model.md`](../../../.prawduct/artifacts/performance-model.md)
§3.8/§4.4, which names both failure modes in one sentence: human breathing is
*"a **1/f** noise supplement — **never white noise**. This is the line between
human and either mechanical (no noise → a precisely-shifted grid) or **sloppy**
(white/large noise)."*

So a per-note i.i.d. nudge moves the song from the *first* failure to the
*second* — and the repo ships the lens that says so, wired into `/mix-review`.
Measured on that first attempt, the drums read **`sloppy`, lag-1 acf 0.135**.

**The resolving insight is that magnitude and structure are independent axes.**
The lag-1 autocorrelation of 1/f noise is magnitude-invariant, which the shipped
calibration states outright. So punk can have a *large* deviation and still read
**human** — "sloppy" as the user means it (not machine-tight) and "human" as the
lens measures it (correlated) are not in conflict. The song did not need
uncorrelated noise; it needed loud breathing.

## What ships

Each part is a `Player` carrying what is **authored** — and declaring a
**profile** for what is *realized*:

| | drag | rush | profile (timing σ / velocity σ) |
|---|---|---|---|
| **Guitarist** | −0.010 | 0.014 | `punk-downstroke` 0.030 / 12 — loosest, rushes hardest |
| **Bassist** | +0.006 | 0.004 | `punk-anchor` 0.016 / 7 — an anchor that wobbles is not an anchor |
| **Drummer** | 0 (+ backbeat accents) | 0.007 | `punk-kit` 0.018 / 11 |
| **Singer** | 0 (+ phrase-start accents) | 0.011 | `punk-shout` 0.032 / 11 — widest |

- **`drag`** is [[04-per-part-feel]]'s constant offset, kept unchanged; the
  ~16-tick guitar-vs-bass gap still carries the groove. `apply_profile`
  deliberately does not re-author the constant lay-back, so the two layers
  compose cleanly. **Verified after the rework, not assumed** — measured mean
  grid offsets over the verse: guitar **−0.0087 beats (−2.6 ms, ahead)**, bass
  **+0.0043 (+1.3 ms, behind)**, a **12.5-tick** gap in the declared direction.
  The breathing is zero-mean, so it widens the spread without eating the gap.
- **`rush`** is forward creep across a bar, reset at the downbeat. An excited
  player doesn't *start* early, they *get* early. It is a deliberate
  accelerando, **not** a fluctuation — which is why it stays authored here
  rather than becoming noise. This is the "enthusiastic".
- **The breathing** is `performance.apply_profile` over the finished part
  (`_perform`), seeded per part. Applied to the whole part in time order,
  because that is what makes it 1/f — a draw taken per note at emission time is
  memoryless by construction.
- **`heat`** scales `rush` at the call site and the profile's `k` at `_clip`
  time. The finale runs 1.3, the coda 1.5.

### The result, measured by the project's own lens

```
part        classification   stdev  lag1-acf    dfa  onsets
01 Drums    human           0.0185     0.623   0.99     183
02 Bass     human           0.0162     0.543   1.02     128
03 Guitar   human           0.0309     0.385   0.89     287
04 Voice    human           0.0324     0.716   1.38      67
```

All four **`human`** (threshold `STRUCTURED_ACF_MIN` = 0.2), with DFA α ≈ 1.0 —
the signature of genuine 1/f. Before the pass the same parts were mechanical;
under the naive fix they were sloppy. Committed at
`measurements/2026-08-11-performance-lens.txt`; regenerate by running
`performance.lens.analyze_performance` over the verse clips.

### One thing the measurement changed my mind about

The kit was first split into **two** breathing streams — hats on one, kick and
snare on the other — to model a hand wobbling more than a foot. It measured
**worse**: the drums came back `sloppy` at acf 0.135 while everything else read
`human`, because interleaving two *independent* 1/f series in time order gives a
combined series that is uncorrelated at lag 1. **Two streams is two performers.**
A drummer's limbs are coupled, and that coupling is most of why a kit sounds like
a person. One stream for the kit: acf **0.135 → 0.623**.

## Garage drums are vocabulary, not just deviation

Breathing alone doesn't make a kit sound like a room. `_punk_beat` also writes
ghost snares between the backbeats, opens the hat where a hand would lean on it,
drops ~6% of hats outright, and adds a second kick where the foot gets ahead of
itself. Measured over the 16-bar verse: **53 ghost snares** at velocity 26–53,
**8 of 128 hats dropped**, 13 extra kicks. **The dropped hat does more work than
any amount of deviation** — the hole is the thing no drum machine produces.

These are **discrete authorship choices** — *which* bar the drummer misses a hat
in — not timing fluctuation, so they use the file's own `_rand` (a blake2b of the
note's identity) rather than the performance profile. Choosing where a hat is
absent is composition; how the played notes drift is performance.

Power chords also stopped being simultaneous: `_power` sweeps root → 5th → octave
a few milliseconds apart, because a downstroke is a pick crossing three strings
and at this gain the sweep *is* the attack. `_chug` scatters note durations, since
a right hand mutes inconsistently — capped just under the gap to the next hit,
because a same-pitch note that outlasts its successor's onset gets truncated by
Live rather than heard as longer.

## Determinism is a hard constraint

`build.py` is a state-converger. Every deviation is seeded from the note's or
part's identity via blake2b — deliberately **not** the builtin `hash()`, which
Python salts per process.

The idempotence test alone does **not** prove this: it runs both builds in one
interpreter, where `hash()` is stable too, so a regression would ship green.
`test_performance_is_identical_across_SEPARATE_processes` builds twice in
subprocesses under **different `PYTHONHASHSEED`s** and compares every note.
Verified that the distinction is real: `hash(repr(key))` returns
`982645869554869255` and `-4090188738807391417` under the two seeds; blake2b
returns the same value both times.

## The bug this surfaced

`_fill` and `_punk_beat` both write a snare on beat 3 of the fill bar. Under one
shared offset the two landed on **exactly the same tick** and the DB deduped them
silently. Once each note carried its own deviation they became a genuine ~5 ms
overlap — and a Live clip cannot hold two overlapping same-pitch notes, so Live
merged them and the push's arrangement integrity assert failed on `01 Drums /
Verse Drums`. There is a **duration** half to the same rule, and it bites harder.
`_chug` caps its note-length scatter against the *authored* onset gap, but the
breathing then moves adjacent onsets relative to each other and reopens overlaps
the cap had closed. Live truncates those, so the DB would store durations the
renderer discards — measured by removing the guard: **63 notes**.
`_no_same_pitch_overlap()` trims them, and
`test_no_note_sounds_past_its_own_retrigger` locks it, because the onset test
below reads only `start_beats` and passes identically whether the duration guard
runs or not.

`_one_hit_at_a_time()` collapses same-pitch notes within 0.03 beats
to the louder one; it removed **8** double-triggers that had been in the song,
inaudible, since it was written. Locked by
`test_no_clip_double_triggers_the_same_pitch`, because the symptom appears only
at push time — the build reports success either way.
