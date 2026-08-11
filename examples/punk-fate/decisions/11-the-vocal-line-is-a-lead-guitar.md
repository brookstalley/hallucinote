---
kind: decision
scope: song
date: 2026-08-11
tags: [sound-design, chains, instruments, lead-guitar, timbre, distortion, portability]
---

# The vocal line is a second guitar now

**Question.** "The voice patch is still very main street electrical parade. It's
standing in for a vocal line but I think it needs to be an expressive, noisy,
punk lead guitar. Can you make it sound more angry and punk? The notes are fine,
it's the timbre that's very beep beep beep bloop."

**Who decided.** User, by ear, after [[10-it-has-to-sound-punk]] fixed the
rhythm guitar and the master bus but left track 4 as the original Operator.

## What this overturns

[[05-signal-chains]] chose Operator *Square Dirty Lead* for the Voice track with
an explicit and genuinely good argument:

> A square wave sits in roughly the formant territory of a shouted vocal, which
> is the only reason a synth can credibly *sing* here.

**The formant reasoning was correct and the conclusion was still wrong.** Sitting
in the right frequency range makes a sound *legible* as a vocal line; it does not
make it sound like a person, and a stable square wave with 33 ms glide reads as a
synth lead — which in a punk record is a genre error, not a timbre nuance. The
measured tell was there the whole time: the Voice stem's spectral centroid was
**2125 Hz** while every other part sat at 77–604 Hz (committed:
`measurements/2026-08-11-sound-punk-full-song.json`; an earlier draft quoted
2112 Hz from the superseded in-session v1 analysis). Nothing else in the band was
anywhere near it, so it floated on top as a separate, obviously-electronic
object.

The brief's own framing ("a staccato mono-synth singing the vocal line") is what
carried the synth this far. The user's call — *"yeah punk was mostly just bass
and one guitar, but here we are"* — retires it: the line is now played by a
second guitarist.

**A knock-on this frees.** [[05-signal-chains]] rejected *Dual Amped Heavy* for
the rhythm guitar because "a scooped metal tone would leave a hole exactly where
the vocal synth lives." There is no vocal synth any more, so that constraint is
void — and the hole is now where the lead guitar *wants* to be.

## The new chain

`Instrument Rack Guitar-Dual Amped Heavy` → `Glue Compressor Guitar - Lead Solo`
→ `Saturator Rough Tone`. Still 100 % stock Live; `portability=strict` holds.

**The preset lied again, exactly as [[10-it-has-to-sound-punk]] predicted it
would.** *Dual Amped **Heavy*** loaded with both nested amps on
**`Amp Type: Rock`, Input Gain 7.0** — a mid-gain rock tone, not a heavy one.
Read back before dialing, per that decision's rule; it took one
`get_parameters` call and would otherwise have been a third pass on the same
complaint.

| | as loaded | dialed |
|---|---|---|
| Amp Type (both amps) | Rock | **Lead** — the high-gain, mid-forward voicing |
| `Amp Gain` macro | 7.00 | **9.29** |
| Amp Middle | 5.40 | **6.80** — a lead has to cut, not scoop |
| `Room` macro | 25 | **9** — dry and in your face |
| `Velocity Sens` macro | 40 % | **70 %** — this is the "expressive" ask; the part already has [[08-sloppy-but-enthusiastic]]'s velocity breathing, and at 40 % the rack was throwing most of it away |
| `Note Off Volume` macro | −24 dB | **−12 dB** — string/release noise, the "noisy" ask |
| Saturator *Rough Tone* Drive | 4.8 dB | **9.0 dB** (Output −5.1 → −8.5 dB, so it is grit, not level) |
| track fader | −17.1 dB | **−8.0 dB** — a lead guitar sits up, a synth stand-in was hiding |
| Reverb / Delay sends | 0.38 / 0.40 | **0.16 / 0.12** — slapback-drenched is the *vocal* treatment; a punk lead is close-mic'd and mean |

**Why the whole chain had to be deleted and rebuilt.** The instrument must be
first in a Live chain, `ableton_device(action='load')` tail-appends, and Live
12.4 exposes no reorder API ([[09-the-dirt]]). Swapping an instrument is
therefore a full teardown — delete all four devices in descending order, reload
in authored order. Given the delete defect logged this same session
(`incoming-bugs/2026-08-11-master-device-delete-also-removed-a-track-device.md`),
every other track's chain was re-listed after the teardown and confirmed
byte-identical before reloading.

**The track is still named `04 Voice`, deliberately.** `build.py` keys on
`TRACK_VOICE = "04 Voice"`, and the *role* is unchanged — it is still the vocal
line, just played by a guitar. Renaming it would break the build to gain
nothing. The name records the part's function; this decision records its
instrument.

## Measured, full song, all eight sections

| | square lead | **lead guitar** |
|---|---|---|
| Voice stem spectral **flatness** | 0.1103 | **0.1471** (+33 %) |
| Voice stem spectral centroid | 2125 Hz | **2309 Hz** |
| Voice stem LUFS-I (pre-fader) | −8.2 | −11.3 |
| **master** spectral flatness | 0.1916 | **0.2471** (+29 %) |
| master spectral centroid | 495 Hz | **595 Hz** |
| master LUFS-I | −11.6 | **−11.4** |
| delivered true peak | −0.34 dBTP | **−0.40 dBTP** |
| overshoots / findings | 0 / 0 | **0 / 0** |

Flatness is the number that answers "beep beep bloop": it rises as a signal
moves from pure tone toward noise, and a square wave is about as tonal as a
synthesised sound gets. The Voice stem's went up a third, and it dragged the
whole master up 29 % with it — **the single biggest jump in noisiness of any
pass on this song**, larger than the entire dirt pass in [[09-the-dirt]]. The
drums, bass and rhythm-guitar stems' flatness moved by at most 0.001 (the
guitar's third decimal shifts, 0.1557 → 0.1545), which confirms nothing else
was disturbed by the teardown. Evidence:
`measurements/2026-08-11-lead-guitar-full-song.json`.

## Still open

Unchanged from [[10-it-has-to-sound-punk]], and now doubled: **both** guitar
racks have `Articulate` parked at 0, so neither switches articulation across the
song. On the lead that also means the rack's *Glide* chain never engages — the
one thing the old Operator did do (33 ms portamento) that the guitar currently
does not, and slides are core lead-guitar vocabulary. Automating `Articulate`
per section in `build.py` would buy palm-mute/ring on the rhythm and slides on
the lead from the same change. **UNDECIDED, owner: next compose pass.**
