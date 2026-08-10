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
| 82–90 s | exponential urgency | **SOUND → LIVE** | the device chain assembling, envelopes drawing |
| **90 s** | **THE CRASH** | *the false summit* | `14/14 phases OK · 50/50 faithful` |
| 90–108 s | the argument (rock vs brass) | **MEASURE** | the lenses disagree with all of it |
| 108–112 s | 5/8 industrial deadlock | *the hard part* | two wrong diagnoses, then the real one |
| 112.3–124.3 s | 7/4 chorus, both sides integrate | **ITERATE → IMPROVE** | the fix lands, audibly, on the downbeat |
| 124.3–127.7 s | the octave teardown | *coda* | the reason gets written down |

### The three beats that carry the story

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

Every render is the same arrangement at the same tempo, sample-aligned and the
same length, so the audio track is a **stitched sequence of real renders** that
switch state at musical boundaries. Nothing is faked: each segment is genuine
audio of the song at a state it actually occupied. The only artifice is the splice,
and the owner has ruled the piece need not be authentic to real-time UX — only
accurate about capability.

Splices land on the two biggest transients in the song, which mask them:

| Boundary | Switch to | Carries |
|---|---|---|
| 90 s (verse crash) | **S1** | brass width corrected 155 % → 125 % |
| 112.3 s (chorus) | **S2** | guitars genuinely stereo; chorus bass audible |

`S0` = brass 155 %, guitars mono (pre-fix). `S2` = current state
(`captures/20260810T154011Z`). **S0 must be regenerated — capture retention already
pruned the original.** Demo masters must live OUTSIDE `captures/`, or the
retention sweep will eat them again mid-production.

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

**A caveat card covering BOTH the simulated window and the video's compression.**
The point is precise and worth not blurring: *everything shown is real; the UX
does not happen this way.* Wording to the effect of —

> Simulated chat window. Hallucinote runs from any Claude Code terminal session.
> Real song creation is more iterative and takes longer than shown.

This is the honest counterpart to the piece's thesis. The demo claims the tool
CHECKS ITS OWN WORK; it must not also imply the work happens in two minutes.
Every measurement, finding and render in the video is genuine — the timeline is
what is compressed, along with the panel being a reconstruction rather than a
screen capture of a terminal.

## Tooling still to build

`~/Movies/hallucinote-capture/make_video.py` needs three things:

1. **Punch-in framing per action window.** `windowrec` captures 2520×1396, so at
   1080p delivery there is a free ~2.3× digital punch-in with no softness — a
   5-second knob move becomes a real close-up. `action_windows` currently carry
   only a speed; they need a crop rect (interpolated across the window) plus an
   optional highlight.
2. **A lens block kind.** `block_for()` has only `PROMPT` and `CLAUDE`, so a
   structured lens read wraps as a paragraph wall. Needs a compact mono stat block.
3. **Audio-state switching** at the two splice boundaries.
4. **Terminal styling + the caveat card** — see the owner requirements above.

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
