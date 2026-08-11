---
kind: decision
scope: song
date: 2026-08-11
tags: [sound-design, chains, distortion, amp, mix, loudness, limiter, master-bus]
---

# It has to *sound* punk — the preset names were lying

**Question.** "The performance is punk enough, but the sound just isn't. The lead
instrument sounds like an electronic trumpet, not a guitar. The drums are small.
The whole thing is kind of cute, and not at all noisy." Then, narrowing it:
*"it is definitely not a punk guitar"* and *"it really sounds electronic"*.

**Who decided.** User, by ear. This is the third pass at the same complaint —
[[05-signal-chains]] specified the dirt, [[09-the-dirt]] added two gain stages
and measured that headroom held. Both were satisfied by the *presence* of
distortion devices. Neither checked what those devices were actually set to.

## The finding: every chain was chosen by preset NAME, never verified by parameter

Nothing was broken. All 14 devices loaded, all `is_active: true`, the push
reported OK, the analyzer was terminal on all four tracks, and `compat check`
read 14/14 native. The song was assembled exactly as authored — and the
authored thing was clean.

| What the name promised | What the parameters actually said |
|---|---|
| Instrument Rack **"Guitar-Dual *Amped Crunch*"** | both nested Amps set to **`Amp Type: Blues`**, Input Gain 6.43/10 — a low-gain blues combo |
| Pedal **"*Guitar Dirt*"** | **`Drive: 1.6 %`** (default 0), `Mid: 29 %` — near-zero drive, and scooping the exact mids [[05-signal-chains]] said punk needs |
| — (undeclared anywhere) | a **Reverb at 24 % wet, 1.2 s decay, Room Size 100** hiding inside the guitar rack, on top of the 0.26 Reverb send |
| Saturator "Hard Punch" on drums | fine — but the drum track fader sat at **−13.9 dB**, the quietest thing in the band |
| — | **no compressor or limiter on the master at all** |

So: a clean sampled guitar, through a blues amp, in a big room, with the drums
turned down 11 dB below the bass. "Electronic trumpet" is a fair description of
what that produces, and "cute" is a fair description of the record.

**Why it read as *electronic* specifically.** `_power()` writes a power chord as
three separate notes with a pick sweep. On a real amp, distortion is what fuses
those three notes — the intermodulation between strings *is* the sound of an
electric guitar. With 1.6 % pedal drive into a blues amp there is almost no
intermodulation, so three sampled notes stay three sampled notes: an oscillator
stack, not a chord. The performance work in [[08-sloppy-but-enthusiastic]] was
never the problem, which is exactly why two passes of humanising didn't fix it.

## What changed

**Guitar — make it a guitar.**

| | before | after |
|---|---|---|
| Amp Type (both nested amps) | Blues | **Rock** |
| Input Gain | 6.43 | **8.80 / 9.00** (deliberately unequal — two amps, not one twice) |
| Amp Middle / Presence | 5.40 / 5.00 | **6.60 / 7.20** — mid-forward, per [[05-signal-chains]]'s own reasoning |
| Pedal *Guitar Dirt* Drive | 1.6 % | **42 %** |
| Pedal Mid / Bass / Treble | 29 / 62 / 58 % | **70 / 32 / 72 %** |
| Pedal Dry/Wet | 62 % | **100 %** |
| rack "Room" macro (the hidden reverb) | 30 | **6** |
| Reverb send / Delay send | 0.26 / 0.18 | **0.10 / 0.06** |
| rack Velocity Sens | 40 % | **60 %** |
| rack Note Off Volume | −24 dB | **−14 dB** — release/string noise, because "noisy" was asked for |

**Drums — stop solving loudness by subtraction.** Fader **−13.9 → −5.5 dB**,
Saturator Output −14 → **−11 dB**. Net ≈ 11 dB more drums.

**Master — the reason that was affordable.** A **Glue Compressor** (−14 dB
threshold, ratio 4, 10 ms attack, auto release, **Peak Clip on**, +4 dB makeup)
into a **Limiter** (ceiling −1.0 dB, auto release). Punk loudness comes from
glue and clipping, not from pulling faders down until nothing overshoots — which
is what [[07-the-bass-carries-the-engine]] and its attempt actually did, and why
the record ended up polite. All devices remain stock Live.

**Master fader parked at unity (0.85 = 0 dB), on purpose.** With the fader at
0 dB, *delivered peak == the measured bus peak*, so the delivered figure stops
depending on `master_fader_db` — a field the analyzer reports **stale**, proved
twice. Here: `measurements/2026-08-11-sound-punk-full-song.json` carries
`master_fader_db: -4.0` and derives `delivered_true_peak_dbtp: -4.34` from it
(the bus's −0.34, minus that 4.0) — while the fader was already at unity. The
next render settles it: `2026-08-11-lead-guitar-full-song.json`, same fader
position, reports `master_fader_db` ≈ 0 and bus == delivered to six decimals.
A day earlier the same field misread the other way on the chapter-1 mix — the
analyzer reported `master_fader_db: 0.0` while Live's own session info returned
a master volume of 0.775, about 3 dB down.

**So: read the bus peak plus a direct fader readback — never the derived
`delivered_true_peak_dbtp` alone.** The ceiling now lives on a device (Glue
Compressor → Limiter) that can be read back honestly, which is the durable half
of this fix.

## Measured, full song, all eight sections

| | [[09-the-dirt]] | **now** |
|---|---|---|
| master bus true peak | +1.93 dBTP | **−0.34 dBTP** |
| delivered true peak | ≈ −2.1 to −2.6 | **−0.34 dBTP** (fader at unity) |
| pre-fader bus overshoots | 2–4 | **0** |
| findings | 1 (`info`) | **0** |
| sections analyzed | 8 | **8** |
| guitar spectral centroid | 752 Hz | **604 Hz** |
| guitar spectral flatness | 0.083 | **0.156** |
| master spectral flatness | 0.191 | **0.192** |

Flatness is the one worth reading twice: it rises as a signal moves from tone
toward noise. The guitar stem's **nearly doubled** (0.083 → 0.156) **with zero
overshoots and ~1.7 dB more delivered level** — which is the measurable shape of
"noisier and louder at the same time," and the thing every previous pass traded
away. The *master's* flatness barely moved here (0.191 → 0.192): at the bus, the
square-wave voice still dominated the noisiness budget, and that is the number
[[11-the-vocal-line-is-a-lead-guitar]] finally moved. Evidence:
`measurements/2026-08-11-punk-pass-full-song.json` (before) and
`measurements/2026-08-11-sound-punk-full-song.json` (after).

**Corrected against the committed evidence, post-review.** This table
originally quoted its before-column as 481 Hz / 0.117 / master 0.158 — figures
read from the in-session v1 analysis, which was taken while the drum-bus Glue
was accidentally missing and was superseded by the committed captures. The
numbers above are the ones this record's own evidence files carry.

## The rule this pass earns

**A preset name is a claim, not a measurement.** `/song-pick-instruments`
selects by `preset_query` — root + pattern + path prefix — and a match on
`"Guitar Dirt.adv"` proves only that a file with that name loaded. Three
sessions trusted "Crunch" and "Dirt" and "Hard Punch" to mean crunch and dirt
and punch. **After loading a chain, read back the parameters that carry the
intent** — gain, drive, amp model, wet level — and record them, the way this
decision's table does. That check costs one `get_parameters` call per device and
would have caught all four problems above on day one.

Corollary: an undeclared device inside a rack (that 24 %-wet Reverb) is invisible
to every stage that reasons about the *track's* chain. Rack interiors need the
same read-back.

## What is still on the table

The rack's **`Articulate` macro is parked at 0 for the entire song**, so one
articulation plays throughout — the Mute/Open/Glide chains never switch. A real
punk guitarist palm-mutes the verse chug and lets the chorus ring, and `build.py`
already encodes that distinction in note duration (0.22 vs ringing). Automating
`Articulate` per section is the obvious next lever on "sounds electronic", and
it is a composition-time change (envelopes in `build.py`), not a snapshot one —
so it is named here as **UNDECIDED, owner: next compose pass**, not silently
dropped.
