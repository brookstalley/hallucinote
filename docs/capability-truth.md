# Capability Truth — what Hallucinote can actually do right now

This is the **anti-hallucination spine** for first contact and song creation. It
is read by the `/hallucinote:ableton-mcp-install` Step-5 handoff and by `/hallucinote:song-new` so the
agent can (a) answer "what can you do?" with broad, *true* invitations, (b)
generate an **accurate, dimensional** caveat when a request leans on a thin
dimension, and (c) **never confabulate a capability**.

Read capabilities as **dimensions of a song**, not a skill catalog. A stylistic
goal is almost always reachable through the dimensions we render fully; name the
thin dimensions honestly, then deliver anyway.

See `song-authoring-conventions.md` -> "The toolkit reduces work — it never limits
what you can author" for the authoring-side counterpart (a missing helper is never
a limit).

> **Living doc.** Keep this current with the code — it must never lag. When a
> dimension's depth changes (e.g. melody matures, vocals arrive), edit the table
> here and the handoff/elicitation surfaces inherit it automatically. Last
> reviewed: **2026-09-09 (wave 2, after the Live session)** — the *Audio material* row's sampler-assignment and reverse halves move up to live-verified (chunk 17 ran); the hearing is recorded as ran-but-not-accepted; the symbolic carve moves DOWN into "Not in this", never having been pushed. Earlier the same day the row gained its ingest, recipe, sampler, feature and intelligibility language at "built, not yet run against a real set", one notch below the place-and-conform half that is live-verified. Prior: **2026-09-09** (an *Audio material* row, which the table had never
> carried at all — so the honest answer to "can you use samples?" was unwritten
> while the code to place one landed. It ships at ◐ rather than ✓ on purpose:
> the mechanism is built and unit-tested and its LOM calls are probe-confirmed,
> but nothing has run end-to-end against a real set, and a doc whose whole job is
> anti-confabulation must not be where that distinction goes missing. It becomes
> ✓ when the operator verification in `.prawduct/operator-verification.md`
> passes, and it gains transform / sampler / derivation language only as those
> waves actually ship. Prior: **2026-08-11** (the Mix — authoring row's "any Live edition" narrowed
> to Standard and Suite, matching the README: those are the editions actually
> exercised, and an Intro user asking "what can you do?" was getting the
> overclaim the rest of the corpus had already retired. Prior: 2026-06-17, split
> the Mix row into *authoring* (any edition) vs
> *measured review* (Max for Live only) so the edition gap is stated up front for
> Standard-edition users — the non-M4L analysis path is out of scope by design,
> AUD-8K2N; the only obligation is naming the gap honestly. Prior: 2026-06-12,
> track routing + the PRE-MAIN submaster bus shipped — folded into the Mix row;
> 2026-06-01, melody gained a read-side *line-analysis* capability — the symbolic
> melody lens, wired into `/hallucinote:compose-review`).

## The dimensions

| Dimension | Status | What that means in practice |
|---|---|---|
| **Rhythm / groove** | ✓ full | kick_stumble, tresillo, boom-bap, swing, kit abstraction, per-part microtiming `feel` (push/pull/drag). |
| **Harmony** | ✓ full | pads, stabs, tresillo pluck, sparse bells; chord movement across sections. |
| **Bass** | ✓ full | tresillo, walking bass, sub/Reese-style lines. |
| **Arrangement / structure** | ✓ full | sections, energy arc, contrast, build/drop, subtraction. |
| **Sound design** | ✓ full | instrument *chains* (instrument + saturation + bus FX) as authorship, not a mix-time todo. |
| **Mix — authoring** | ✓ full | the mix moves themselves, on **Live 12 Standard and Suite** (the editions this is exercised on; Intro and Lite are untested — their track ceilings and thinner device palette are the likely limits, so say so rather than promising): device chains, dialed params, sidechain, reverb sends, track input/output **routing** + submaster (PRE-MAIN) busses for master-like automation and sub-mixing (Live groups aren't LOM-creatable — a routing bus is the way). |
| **Mix — measured review** | ✓ with Max for Live | the *measured listen-back* — masking analysis, loudness, master attribution, reverb verification, per-part timing (`/hallucinote:mix-review`) — renders audio through the HallucinoteAnalyzer, which needs **Max for Live (Live Suite, or the M4L add-on)**. **Without Max for Live this half is unavailable** — there is no non-M4L analysis path (by design), and that turns on **M4L, not the edition**: a Standard owner with the add-on gets the measured review; a Suite owner always has it. Use the **symbolic** `/hallucinote:compose-review` (composition-level, reads the score not the audio) instead, and say plainly that a measured mix-review isn't available to them without M4L — never imply one ran when it didn't. |
| **Melody — line analysis** | ✓ read-side | the symbolic **melody lens** reads any monophonic line's contour, intervals, and harmony-fit and coaches it *against your declared intent* (`/hallucinote:compose-review`, `hallucinote.tools.melody_lens`) — including a topline you sketched in. It measures, it never invents the hook (that's yours). No universal "good melody" verdict. |
| **Melody — lead-line *authoring*** | ◐ thinner | I won't write your finished hook — that's your art, by design (no melody generator, ever). A generated topline is a starting point, not the finished hook. *Sketch your line in Ableton and I'll arrange under it (round-trip) — and read whether it lands its intent (line analysis above).* |
| **Vocal topline (synthesis)** | ✗ not yet | we don't synthesize a sung vocal. A sketched vocal *melody* (MIDI) round-trips in — and the line analysis above reads it. |
| **Round-trip / sketch-input** | ✓ full | edit in Ableton, we ingest + build around it — `/hallucinote:ableton-pull` `clip-notes`, stable per-note IDs. Audio clips ride this path too, at the maturity the row below states. |
| **Audio material (samples)** | ✓ live-verified 2026-09-09 (Live 12.4.5) | An audio file referenced from `build.py` places into a Live slot with its warp mode, transpose, gain and markers, and into the arrangement as a placement. **An arrangement copy plays the placement's span, but occupies a block it cannot shrink — BUILT AND UNIT-TESTED, NOT yet live-verified** (unlike the rest of this row, which was). After the placements apply, a second pass writes each copy's `end_marker` and `loop_end` to the authored span (addressed by the link Live returned, never a predicted index), so the copy is INTENDED to sound `end_bar`. Live's acceptance of those writes is probe-confirmed (row 27) only for a SHRINKING write; a placement authored LONGER than its sample is unprobed, and the push reports success from call ok-ness, not from hearing it. Say "built, not yet run against a real set" for the region write specifically — four boxes in `.prawduct/operator-verification.md` are still pending on it. What no push can change is the block the copy occupies on the timeline: `Clip.end_time` has no setter (probe row 27), so a copy can sit in a block running to the file's length — silent after its region ends, and overlapping whatever is placed behind it. Shorten those blocks in Live when the visual span matters. Two copies get no region and the run names them: a row authoring `warping = 0` (Live reads its markers in seconds while the arrangement is authored in bars), and a placement whose create did not land. **The arrangement copy is conformed only when its clip hosts an envelope**: that placement travels by `duplicate_clip_to_arrangement` of the conformed session clip, so its gain / warp / markers and its ride arrive with it; an envelope-free placement is a direct create at Live's defaults, and the run reports that its authored conform did not travel rather than implying one it did not apply. Re-pointing a clip at a different file (or a slot Live holds a MIDI clip in) is a delete-and-recreate that conforms the new clip and re-emits every envelope the row hosts, because a recreate drops them; it is said on the operator channel. A clip you drag into Live by hand is **staged** into the DB on pull (song-relative path when under the song dir, absolute otherwise) — the DB is materialized state, so fold it into `build.py` to keep it, as with a `clip-notes` pull; and pull writes no link for it, so until #507 lands the next push deletes and rebuilds that clip from the same file (hand-set warp markers are lost; the run alerts on the operator channel whenever its probe finds the slot occupied). A volume ride or send throw authored under an audio clip pushes. The LOM calls behind all of it were probe-confirmed on Live 12.4.1 and 12.4.5 (`docs/research/audio-first-class/lom-probe-results.md` rows 1-3, 14-17), the paths are unit-tested, and the end-to-end ran against a real set on 2026-09-09 — session and arrangement placement, conform round-trips, the re-point recreate with its ride, the missing-sample refusal, and the pull round trip, recorded box by box in `.prawduct/operator-verification.md` (SMP-6V2K wave 1). The ride under an audio clip was confirmed audible by the operator the same day. Say "works, with the stated gaps". **Live-verified 2026-09-09 (chunk 17 of SMP-6V2K wave 2, Live 12.4.5 — `lom-probe-results.md` rows 21-31)**: a Simpler row's `audio_file` is assigned on push and read back from the device, a second push emits nothing, and a hand-dropped sample survives capture -> replay -> push; `reverse=1` materializes through the derived cache in **both** the session and the arrangement, and flipping it forward re-points the clip while naming the delete-and-recreate cost first. Say "works" for those. Two dated verdicts came with it: Live's **Sampler (`MultiSampler`) cannot be assigned at all** — no `replace_sample`, no `sample` property — so the "only Simpler" teaching error stands; and `replace_sample` does **not** reset device parameters. Also live-verified in the same session: a sample enters through `hallucinote asset add` (normalized under `assets/sources/`, provenance in `assets/manifest.json`) and a real dialogue line went in that way; a line's F0, formants, energy, onsets and phrases are measured (`hallucinote sample-lens`, `/sample-lens`) and a follower generator writes a part from the contour — both ran on that line. `build.py` derives with a recipe (`derive(line, trim(...), normalize(...))` — trim, fade, normalize, reverse, pitch shift, stretch-to-bars, chop-at-onsets) into a content-addressed cache under `assets/derived/`. **Built and unit-tested, NOT yet run against a real set** — and this list is now short, which is the point: the score-dependent `carve` / `vocode` transforms (a symbolic or measured reference; never pushed to Live), and the mix report's per-turn speech-over-bed measurement (`speech_track=`), numbers only. Say "built, not yet run against a real set" for those. **Ran but did NOT land (chunk 17 section 5)**: the end-to-end hearing — a real dialogue line ingested, its lens read, an F0 follower written from its contour and pushed with a pitch ride — ran on real material and was heard, and the operator did not accept the musical result ("it does not really read as tracking"). The plumbing is verified; the output on that material is not. Say "the pipeline runs end to end; whether it makes music is unproven". **Not in this**: the symbolic `carve` has never been pushed to Live (built and unit-tested only — chunk 17's remaining debt); per-note MPE bends (`note_expression`) cannot be pushed at all — Live's Python API exposes no per-note expression surface under any name, so this is permanent rather than pending a Live update (#515), and the kind is now refused at the boundary with a teaching error — a monophonic line's glide goes through a `device_parameter` ride instead; source separation (#266); nested-rack sampler capture; a sampler's reverse intent. Formant-preserving grain-scatter (R4.3) is no longer gated — R6.2 was decided by ear on 2026-09-09 in favour of **Rubber Band**, so R4.3 is buildable and carries a non-Python binary dependency (`rubberband` on PATH). |

## How to use this in conversation

**Caveat first, then best effort — and the caveat is *dimensional*, never
goal-blocking.** The canonical example — a user asks for *"an 80s pop song like
Madonna"*:

> "Love it — I'll write you an 80s synth-pop song in Madonna's musical language:
> the chord moves, the groove, the arrangement, the sound design are all things I
> do well. Two honest caveats: I can't synthesize the vocal, and I won't *write*
> your finished hook — that's your art. But sketch the topline and I'll build the
> whole track under it, then read whether the line lands (its contour, how it sits
> on the chords). Here's the song…"

Not *"I can't do Madonna (no vocals)."* The Madonna-ness lives in the dimensions
we own; the caveat scopes the two we don't, then we build.

**Invert a thin dimension into an invitation.** When a request leans on a thin
dimension, don't just caveat it — offer the user's *contribution* there. Melody
*authoring* is thin, but round-trip is **fully supported** AND the melody lens now
**reads** a line: *"bring me your topline — sketch it in Ableton — I'll build the
whole track under it, then read whether it's a shaped line that lands its intent
(contour, how it sits on the chords) via `/hallucinote:compose-review`."* That is a stronger,
more honest inversion than "melody's my weak spot": you keep the hook, I build the
world around it and hold up the mirror. The round-trip itself is **supported, not a
hazard** — a user can sketch any part in the sequencer and we ingest it.

**Three rules:**
1. **Never confabulate.** If it's not in the table as ✓ or ◐, don't promise it.
2. **Never gate the goal.** Caveat the thin dimension; deliver the rest.
3. **Never silently substitute.** Don't quietly swap a generated melody for the
   user's intended one — name the gap and invite their input.
