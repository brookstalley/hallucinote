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
> reviewed: **2026-09-09** (an *Audio material* row, which the table had never
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
| **Audio material (samples)** | ◐ built, not yet live-verified | An audio file referenced from `build.py` places into a Live slot with its warp mode, transpose, gain and markers, and into the arrangement as a placement — **the arrangement copy is not conformed and does not carry the placement's length**: Live's direct arrangement-create takes a path and a position and nothing else, and the planner cannot address the new clip until after the call returns, so an arrangement copy plays the whole file at Live's defaults. The run says so on every audio placement rather than implying a conform it did not apply; trim in Live for now; a clip you drag into Live by hand comes back into the song's source on pull, in a portable path form; a volume ride or send throw authored under an audio clip pushes. The LOM calls behind all of it were probe-confirmed on Live 12.4.1 and the paths are unit-tested — but the end-to-end has **not yet run against a real set**, so say "built, unverified", never "works". Two cases deliberately **refuse and say so** rather than guess: re-pointing a clip at a different file (a destructive recreate whose effect on envelopes is unprobed) and an arrangement placement whose clip hosts an envelope. **Not in this**: no acquisition or extraction from media, no offline transform (pitch shift, stretch, chop, reverse), no assigning a sample to Simpler/Sampler, and no feature extraction — you cannot yet derive a part from what a sample *sounds like*. Those are later waves of SMP-6V2K, and until they land the honest answer to "can you use samples?" is *place and conform, yes; transform or derive from, not yet.* |

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
