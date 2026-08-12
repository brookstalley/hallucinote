---
artifact: design
scope: demo-video
status: approved
approved_by: owner
approved_on: 2026-08-10
related:
  - artifact: tour-walkthrough-design   # a DIFFERENT deliverable — see "Not the tour"
  - backlog: STR-4C8N
last_validated: 2026-08-10
---

# The vision piece — a ~2:10 demo built from `the-argument`

## Not the tour

`tour-walkthrough-design.md` covers the README/`docs/tour.md` media — screenshots,
a hero still, audio clips, under a byte budget. **This is a different deliverable:**
one continuous ~2:10 video of a song being conceived, built, measured and fixed.
They share a song and some tooling; they are not the same artifact and neither
supersedes the other.

## Thesis

Not *"it builds a song"* — every AI-music demo is a build demo, and it invites the
one comparison this product loses on (`docs/VISION.md`: the target is never "AI
fills in a chord progression"). The thesis is:

> **It checks what it made against what you asked for, and tells you where they
> disagree.**

That requires holding declared intent and rendered audio in the same place — the
pair Hallucinote has and a DAW doesn't.

It is earned, not asserted. On 2026-08-10 this song passed every check —
`14/14` push phases OK, `verify-arrangement` 50/50 faithful, automation verified
as recorded AND playing (playhead parked mid-sweep read back the exact authored
value) — while being wrong four ways: Lead Gtr had silently lost its arrangement
clips, the render had dropped its first 20 beats and reported `ok`, the chorus
bass was below its instrument's range (digital silence), and the guitars were
bit-exact mono despite a flanger declared to widen them. Every one was caught by
rendering the audio and measuring it. The last had been misdiagnosed twice first.

## The organising idea: the song's form IS the storyboard

This song was written to a narrative brief — ominous build, an argument, a
deadlock, an integration, a teardown. **Every workflow phase has an emotional twin
in that arc.** Mapping them onto each other is what lets six phases fit one
play-through: each beat is carried by music that already means the right thing, so
nothing needs a narrator.

| Song time | What the music is doing | Phase | The ONE image |
|---|---|---|---|
| 0–24 s | one drone, near silence | **IDEATION** | empty set; a sentence of intent typed |
| 24–51 s | voices accumulate | **CO-DEVELOPED PROPOSAL** | the two questions it won't answer for you, beside the craft it decides without asking |
| 51–82 s | machine pulse emerges, tremolo enters | **MUSIC → LIVE** | `build.py`, then 10 tracks + 50 clips materialising |
| 82–90 s | exponential urgency | **SOUND → LIVE** | the device strip, visible but nearly static — see below |
| **90 s** | **THE CRASH** | *the false summit* | `14/14 phases OK · 50/50 faithful` |
| 90–108 s | the argument (rock vs brass) | **MEASURE** | the lenses disagree with all of it |
| 108–112 s | 5/8 industrial deadlock | *the hard part* | two wrong diagnoses, then the real one |
| 112.3–124.3 s | 7/4 chorus, both sides integrate | **ITERATE → IMPROVE** | the fix lands, audibly, on the downbeat |
| 124.3–127.7 s | the octave teardown | *coda* | the reason gets written down |

### The three beats that carry the story

The brief lands across two owner turns BEFORE Claude answers. Replying after the
opening line alone made it a questionnaire served on a blank brief — and it
opened with "two things I can't decide for you", which frames an unprompted list
rather than an answer to what was just said. Letting the brief arrive first also
fills the dead air at the top of the piece.

**Collaboration (24–51 s)** — the philosophical heart, and almost nobody demos it.
Two registers in two colours: the questions it ASKS (*is anyone singing? does the
argument extend to harmony?*) beside the craft it DECIDES unasked (140 BPM, the
meter map, the section arithmetic). This is the identity/craft split from
`CLAUDE.md` made visible. Pure text over accumulating strings — nearly free to
shoot, and it says what the tool is.

**The false summit (90 s)** — sell the triumph completely. Full arrangement, every
gate green. The next twenty seconds take it away, and the fall only works from a
height.

**The deadlock (108–112 s)** — four seconds, three fast cards over the tritone:
*"it's the latched override"* → no; *"it's the automation arc"* → no; then
`Mod Phase 0.0°`. The song's deadlock section carries the moment the diagnosis
deadlocked. **Owner approved keeping this beat, 2026-08-10**, over the explicit
risk that it reads as "their tool misdiagnoses things" — it is what makes the
piece credible.

### The ending

The chorus is where the brief says rock and brass "finally integrate"; it is also
where the flanger lives and where the silent bass lived, so it is where every fix
becomes audible. Switching the audio to the corrected render **on that downbeat**
makes the song's resolution and the demo's resolution the same event. Then the
outro tears everything down an octave while `decisions/07-flanger-stereo-mod-phase.md`
is written: the sound collapses, the reason persists.

Closing card:

> Every check passed. The audio disagreed.
> **Hallucinote listens to what it made.**

## Audio: the mix assembles itself over ONE play-through

Owner constraint: **one play-through of the song**, and the audio must change to
reflect what the chat window shows.

Every render is the same arrangement at the same tempo, so the audio track is a
**stitched sequence of real renders** that switch state at musical boundaries.
Nothing is faked: each segment is genuine audio of the song at a state it
actually occupied. The only artifice is the splice, and the owner has ruled the
piece need not be authentic to real-time UX — only accurate about capability.

Two things this originally assumed, both since MEASURED and neither quite true:

- **The renders are not sample-aligned.** Capture starts when transport crosses
  the start beat, which lands on an audio-buffer boundary that varies per run.
  Against S0, S1 is 1024 samples EARLY and S2 is 1024 samples LATE (21.33 ms) —
  constant across the verse, chorus and outro, so a single per-state shift fixes
  it. Do not try to derive this by correlating the intro: it is a sustained
  drone and matches at many lags, which produced a spurious 152 ms / 813 ms
  reading before drum transients gave the real answer.
- **Render time is not song time.** A little pre-roll survives the
  transport-cross detection, so the file clock runs ~280 ms BEHIND the song.
  Beat 262 is at file 112.573 s, not 112.286 s. Anchor splices to the measured
  transient, and hunt in a window well under half a beat (214 ms at 140 BPM) —
  a ±1 s search lands on the wrong beat entirely.

`stitch_audio.py` (next to `make_video.py`) carries both corrections and writes
`demo-audio.wav`. Its crossfade is linear, not equal-power: the three states are
renders of one performance, so cos/sin summed them to +1.28 dBFS and clipped.

Splices land on the two biggest transients in the song, which mask them:

| Boundary | Switch to | Carries |
|---|---|---|
| 90 s (verse crash) | **S1** | brass width corrected 155 % → 125 % |
| 112.3 s (chorus) | **S2** | guitars genuinely stereo; chorus bass audible |

`S0` = brass 155 %, guitars mono, chorus bass silent (pre-fix). `S2` = every fix
landed. **All three now exist and are verified**, in
`~/Movies/hallucinote-capture/audio-states/{S0,S1,S2,S2-fresh}/` — outside
`captures/`, where the retention sweep cannot prune them as it pruned the
original S0.

Regenerating S0/S1 needed more than the flanger `Mod Phase` twiddle the first
plan assumed: **the chorus bass is a `build.py` fact, not a device parameter.**
Its roots were raised to E2/C#2/A1/B1 to clear the Electric Bass Palm rack's
lowest sample, so re-creating the silent-bass state means dropping
`CHORUS_HARMONY`'s roots an octave, rebuilding, and scoped-pushing that one clip
— then restoring. Skipping it would have quietly cost the 112.3 s splice its most
audible fix, leaving that boundary carrying only a stereo-width change.

`S2-fresh` is a fourth render taken AFTER the restore, and is what proves the
round-trip: it reproduces canonical S2 within measurement noise (Rhythm Gtr
corr +0.986 vs +0.985, brass +0.043 vs +0.035, chorus bass −23.4 vs −23.5 dB).

## Picture: two recordings, one locked

Picture and audio can only be locked once the playhead rolls.

- **REC-A** — the push (measured at 6m15s), speed-ramped into 0–90 s. Free to
  compress: nothing is playing, so there is no playhead to desynchronise.
- **REC-B** — a real-time pass from beat 210 to the end (37.7 s), **1×, unramped,
  locked to the audio**. Ramping here would visibly desync the playhead from what
  is heard.

Optionally shoot REC-B as the **performed-automation pass** rather than plain
playback: it is already a real-time transport pass, Live is visibly armed, and the
eight arcs draw themselves under the playhead. More interesting, and it is the
tool genuinely working.

**The device chain is thin in REC-A, and no framing can thicken it.** The push
loads devices over the API without moving Live's selection, so the detail view
sits on the C-Delay for the whole 86-second phase. Across source 140 → 178 s the
only pixel that changes is that Delay's Dry/Wet, 50 % → 100 % — verified by
diffing the two frames. Under the split frame the strip is at least never
hidden, and the sound-design beat is carried by the transcript's room/hall line.
Making it the image the storyboard wanted needs a pickup shot: load a chain with
Live's detail view focused, and record that separately.

**Reorder the push for REC-A.** A full push runs `performed_automation` BEFORE
`arrangement`, so that 132.5 s realtime pass happens over an EMPTY timeline — two
minutes of a playhead crawling across nothing, the longest and dullest phase.
Push everything, then `--only arrangement`, then `--only performed_automation`.

Measured phase durations (2026-08-10, fresh empty set, 374.8 s total) — these set
the ramp ratios: tempo/signature 1.1 s · tracks 5.1 · returns+scenes 1.5 · clips
29.1 · mix 33.7 · devices 86.0 · routing/sidechain/envelopes skipped ·
performed_automation 132.5 · arrangement 62.9 · cues 5.1.

## The chat window (owner requirements, 2026-08-10)

**Terminal, not a chat app.** Monospace body text and terminal-ish styling.
`render_panel` currently draws labels in `F_MONO` but the body in the
proportional `F_BODY`, which reads as a messaging product. It runs from a
terminal, so it should look like one.

**The terminal does not sit on Live. It sits beside it.** The frame is an
ultrawide split — 4500×1898, ~2.37:1 — with a 1476 px terminal column on the
left and Live's whole 3024 px window on the right.

That is the resolution of an argument the overlay layout could not win. As an
overlay the panel had to be somewhere, and every somewhere covered something:
parked bottom-left it sat exactly on Live's device-detail strip, so the chain
was never seen building; moved aside for that beat, it read as the window
jumping. Sizing it to its contents made all 25 turns resize it. Given its own
column, none of those questions exist — it opens at full size, never moves,
never resizes, and hides nothing.

Two things fall out of the split. Live is carried at **native 3024×1898**,
neither cropped nor resampled: fitting it to a 1080-tall frame was discarding
43 % of the vertical detail, and Live's UI is one-pixel rules and 11 px labels,
so it went soft exactly where the film asks you to read a value. And the column
is tall enough to hold 14 turns instead of 5, so the transcript reads as a
session rather than a ticker.

**A caveat pinned to the top of the terminal, for the whole film.** What it
qualifies is that window, so a band across the picture invited the reader to
attach it to Live instead. It no longer times out: the split frame gave the
terminal room to carry it permanently, and a disclosure that scrolls away after
nine seconds is one most viewers never see. Its band is *reserved* rather than
overdrawn, so a full transcript cannot grow up underneath it.

> Simulated chat window.
> Hallucinote runs from any Claude Code terminal session.
> Real song creation is more iterative and takes longer than shown.
> The Ableton build is pulled forward to run under the chat, not after it,
> so the conversation has something to watch.

This is the honest counterpart to the piece's thesis. The demo claims the tool
CHECKS ITS OWN WORK; it must not also imply the work happens in two minutes.
Every measurement, finding and render in the video is genuine — what is not
genuine is the *timeline*: it is compressed, the panel is a reconstruction
rather than a screen capture, and the Ableton build really runs AFTER the whole
conversation rather than underneath it. That last one is the disclosure the
earlier cuts owed and never paid; it is the single biggest liberty the piece
takes, and it is the one a viewer is least able to infer.

## Tooling still to build

> **Status 2026-08-12 — all three shipped; this section is kept for the record.**
> Verified in the code rather than assumed: `block_for()` now carries a `LENS`
> kind that renders the read as a table (newlines preserved, over-long rows
> clipped rather than wrapped, its own font and colour); `stitch_audio.py`
> performs the state switching, anchoring each splice to the loudest onset near
> the nominal boundary so the cut hides under a transient; and the caveat is
> implemented as a permanent reserved band inside the terminal panel. The cut
> itself exists — `~/Movies/hallucinote-capture/demo-cut.mp4`, 4500×1898,
> 132.9 s, 22 MB, rendered after the last tooling change — and was spot-checked
> at four timestamps: caveat card, split-frame layout, the built arrangement,
> and the lens table all render correctly.
>
> **The remaining work is delivery, not tooling** — see the "Dependency" note
> below and `brookstalley/hallucinote#329`.

The three items as originally written:

1. **A lens block kind.** `block_for()` has only `PROMPT` and `CLAUDE`, so a
   structured lens read wraps as a paragraph wall. Needs a compact mono stat block.
2. **Audio-state switching** at the two splice boundaries.
3. **Terminal styling + the caveat** — see the owner requirements above.

**There are no zooms.** Punch-ins were built, refined twice, and then cut. They
drew the eye to the framing rather than to what Live was doing; the one crop
that would have made the device chain legible was the corner the terminal had to
occupy; and animating a crop is not something `crop` can do, so the first
implementation was a stack of constant-crop slices that stepped up to 12 frames
at a time and read as chunky. (The fix for *that* — animating a uniform scale
by `k(t) = 1920 / w(t)` with `scale=…:eval=frame` and taking a constant window
out of it with `crop` — is the technique to reach for if a zoom is ever wanted
again. It is per-frame smooth and costs one encode per segment.) Side by side at
native resolution there is nothing to zoom past, so `action_windows` now carry
pacing only.

**The frame is too wide for the hardware encoder.** VideoToolbox refuses a
compression session above 4096 px (−12903) and this frame is 4500, so the
encoder is `libx264`. It is also quality-targeted (CRF) rather than
bitrate-targeted: the content is UI, which is what a fixed bitrate smears first,
and CRF spends nothing on the many near-static stretches — the whole 2:22 cut is
23 MB.

Retiming: `beats-final.json` currently has `beats: []` and 27 `tail_beats` all
crammed into the tail — that is what collapsed an earlier cut into "scroll text
over playback." Turns redistribute across the whole piece on the file's own
principle (each request lands a beat or two BEFORE the change it causes). ~27 will
not fit; ~18 is the estimate.

## The discipline that makes it work

Nine beats in 128 seconds is ~14 seconds each. That works **only if each beat is
one legible image.** The moment a beat tries to show two things it becomes
wallpaper. This is why the collaboration beat is text rather than a screen tour.

## Dependency

Beats 6–8 need **STR-4C8N** (stereo/mono-compat lens) finished — A1 landed
2026-08-10 (`d8dd047`). Showing `/mix-review` reporting mono-collapse before that
lens exists would be vaporware, which this demo cannot afford given its thesis.
Today's raw `/mix-review` output also leads with nine `automation_not_realized`
warnings that are mostly FALSE (spectral centroid is the wrong probe for a comb
filter) — STR-4C8N A2 fixes that, and unfixed it would put the tool crying wolf
on camera.
