---
date: 2026-05-20
kind: decision
scope: song
decided_by: agreed-after-confirm
tags: [signal-chains, portability-strict]
---

# Signal chains per track

## Question
What's the full chain (instrument + post-FX + sends) per track that gives this song its sound?

## Chains

| Track | Chain (top → bottom) | Sends (Plate / Room / DubDelay) | Rationale |
|-------|----------------------|---------------------------------|-----------|
| **01 Drums** | Drum Rack: *Hot Rod Kit* → EQ Eight → Drum Buss: *Boom in E* → Glue Compressor | 0.15 / 0.35 / 0.0 | Hot Rod Kit's full pad mapping (kick/snare/hat/ride/crash/china) serves both genres via velocity authoring. *Boom in E* (matches our tonic!) is Live's stock drum-bus glue — character + comp baked in, not a follow-up mix pass. |
| **02 Bass** | Tension: *Electric Driven Bass* → EQ Eight (HPF<35Hz) → Saturator: *Gritty Bass* → Compressor | 0.0 / 0.0 / 0.0 | Tension is physically modeled — articulation flips between fingered round and palm-muted tight on the same instrument. Saturator pre-bakes the growl. Bass gets ZERO sends — mud killer. |
| **03 Rhythm Gtr** | Tension: *Single Coil Guitar* → Amp → Cabinet: *4x12 Cab* → EQ Eight → Compressor | 0.10 / 0.20 / 0.0 | One modeled Strat-style guitar; Amp's Type+Drive parameters automated per section (Clean for reggae skanks, Heavy/Metalic for metal gallops). 4x12 cab is the metal weight, stays on for both — it's the character. |
| **04 Organ** | Instrument Rack: *Organ Bandstand* (Wavetable-based) → Chorus-Ensemble → EQ Eight (HPF<200Hz) | 0.20 / 0.0 / 0.15 | Bandstand has the drawbar bite for reggae skanking. Chorus-Ensemble bakes the Leslie-cabinet shimmer in. HPF keeps organ above the reserved vocal hole. Drops out entirely in metal sections at clip level — its absence is also a textural cue. |
| **05 Lead Voice** *(placeholder)* | Wavetable (bare, configured to mono saw lead) → Saturator: *A Bit Warmer* → EQ Eight → Compressor | 0.30 / 0.15 / 0.20 | Mono synth lead carries the vocal melody NOW; synthetic timbre makes "this is placeholder" obvious to the future ear. Saturator + Comp pre-applies the vocal-bus treatment so when real vocals arrive the FX chain matches and sidechain sources just repoint. See `decisions/05-vocals-and-placeholder-lead.md`. |
| **06 Counter-Melody** | Operator (bare, configured to bell-FM, octave-up) → Saturator: *A Bit Warmer* → EQ Eight (HPF<400Hz) → Compressor | 0.40 / 0.0 / 0.30 | Bell-y FM sits B4–E5, above the vocal register. PERMANENT layer — stays when vocals arrive. Higher reverb/delay sends put it slightly behind the vocal in depth, where a hook layer wants to live. |
| **07 Vocal Bus** *(empty)* | (no instrument, no devices) | 0.30 / 0.15 / 0.20 | Pre-wired with the Lead Voice's send levels so vocals inherit correct spatial placement. Vocal-tracking session will add EQ/Comp/De-Esser to taste. |

## Returns

| Return | Device | Notes |
|--------|--------|-------|
| **A: Plate** | Hybrid Reverb — *Hall* preset | Reggae spaces, lead voice, future vocals. Decay tuned post-push (~1.8s plate character). |
| **B: Room** | Hybrid Reverb — *Room* preset | Metal tightness, snare body. Short decay (~0.6s). |
| **C: DubDelay** | Echo — *Vintage Delay* preset | Reggae transitions, organ skanks, WHACK tail. Set dotted-8th tempo-sync post-load for dub feel. |

## Rationale

This is a song where the **sound design IS the storytelling**. The genre alternation (decisions/02) only works if each genre's sonic identity is fully present in its sections — which means saturation, amp character, room placement, and bus glue all ship in the snapshot, not as a follow-up mix pass.

A few choices that bear specific argument:

**Why Tension for both bass and guitar?**
Tension is Live's physically-modeled string instrument. It responds to articulation (velocity, pitch bend, note length) the way a real instrument does — which is exactly what we need for "same instrument, two genres" on both bass and rhythm guitar. The reggae sections will use longer notes + softer velocities; the metal sections will use shorter notes + harder velocities; the *same Tension preset* yields appropriate behavior for each because the model responds to playing technique. This is the cleanest authoring path to "channel-switched" tone without literal channel switching.

**Why Amp + Cabinet on rhythm guitar specifically?**
Live's Amp device has an internal Type parameter selecting between Clean, Boost, Crunch, Lead, Heavy, and Bass amp models. **Per-section automation of Amp.Type and Amp.Drive** gives us the "channel switch" the brief asked for, without resorting to two separate device chains. Cabinet stays constant — it's the speaker character, not the channel state.

**Why Drum Buss preset "Boom in E" specifically?**
Stock Live ships Drum Buss presets named for the resonant boom note (Boom in A, C, D, E, G). Picking the preset matching the song's tonic (E) means the drum-bus boom locks into the harmonic field. Tiny detail; high payoff.

**Why bare Wavetable + Operator for the leads, not stock presets?**
The lead voices have specific demands (mono, narrow register, specific Saturator chain) that no stock preset matches exactly. Loading bare and configuring during composition gives us authorship control without fighting a preset's defaults. The post-FX chains carry the character.

**Why Hybrid Reverb (twice) instead of stock Reverb + a different room?**
Hybrid Reverb is Live's newer best-in-class reverb. Using it for both Plate and Room returns gives consistent algorithmic character — the only difference between A and B is the preset (decay, size, character), not the device. Cleaner mental model than mixing Reverb + Hybrid Reverb or Reverb + Convolution.

**Why no Delay on Bass?**
Bass + delay = mud. Sends to Plate and Room are also zero on bass. Bass lives dry-center.

**Sidechain authorship (post-push wiring, intent flagged here):**
- Organ ducks under Lead Voice (~4 dB, fast attack, ~80ms release)
- Rhythm Gtr ducks under Lead Voice (~3 dB)
- When real vocals arrive, repoint sidechain source from Lead Voice → Vocal Bus

These ship as part of the chain on next recapture after wiring in Live.

## Portability

**Strict mode** — every device above is stock Live Suite content. `preset_query` selectors land in `captured_session.json` (composer-time, machine-independent). The song opens on any Suite install with no missing-device errors. `python -m hallucinote.sync.compat check sun-zone-done` should return clean.

Single ambiguity worth flagging: `Organ Bandstand` exists in both Instrument Rack and Wavetable folders — we use the Wavetable version (`path_prefix: "Wavetable"`). Verify on push.
