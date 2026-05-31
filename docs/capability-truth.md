# Capability Truth — what Hallucinote can actually do right now

This is the **anti-hallucination spine** for first contact and song creation. It
is read by the `/ableton-mcp-install` Step-5 handoff and by `/song-new` so the
agent can (a) answer "what can you do?" with broad, *true* invitations, (b)
generate an **accurate, dimensional** caveat when a request leans on a thin
dimension, and (c) **never confabulate a capability**.

Read capabilities as **dimensions of a song**, not a skill catalog. A stylistic
goal is almost always reachable through the dimensions we render fully; name the
thin dimensions honestly, then deliver anyway.

> **Living doc.** Keep this current with the code — it must never lag. When a
> dimension's depth changes (e.g. melody matures, vocals arrive), edit the table
> here and the handoff/elicitation surfaces inherit it automatically. Last
> reviewed: **2026-05-31**.

## The dimensions

| Dimension | Status | What that means in practice |
|---|---|---|
| **Rhythm / groove** | ✓ full | kick_stumble, tresillo, boom-bap, swing, kit abstraction, per-part microtiming `feel` (push/pull/drag). |
| **Harmony** | ✓ full | pads, stabs, tresillo pluck, sparse bells; chord movement across sections. |
| **Bass** | ✓ full | tresillo, walking bass, sub/Reese-style lines. |
| **Arrangement / structure** | ✓ full | sections, energy arc, contrast, build/drop, subtraction. |
| **Sound design** | ✓ full | instrument *chains* (instrument + saturation + bus FX) as authorship, not a mix-time todo. |
| **Mix** | ✓ full | intent-aware review, masking analysis, sidechain, reverb sends, loudness. |
| **Melody (lead line)** | ◐ thinner | pluck/bell lines today; a topline is a starting point, not the finished hook. *Or sketch your line in Ableton and we arrange around it (round-trip).* |
| **Vocal topline (synthesis)** | ✗ not yet | we don't synthesize a sung vocal. A sketched vocal *melody* (MIDI) round-trips in. |
| **Round-trip / sketch-input** | ✓ full | edit in Ableton, we ingest + build around it — `/ableton-pull` `clip-notes`, stable per-note IDs. |

## How to use this in conversation

**Caveat first, then best effort — and the caveat is *dimensional*, never
goal-blocking.** The canonical example — a user asks for *"an 80s pop song like
Madonna"*:

> "Love it — I'll write you an 80s synth-pop song in Madonna's musical language:
> the chord moves, the groove, the arrangement, the sound design are all things I
> do well. Two honest caveats: I can't synthesize the vocal, and my melody
> writing is less sophisticated than the rest of me — so the topline will be a
> starting point, not the finished hook. Here's the song…"

Not *"I can't do Madonna (no vocals)."* The Madonna-ness lives in the dimensions
we own; the caveat scopes the two we don't, then we build.

**Invert a thin dimension into an invitation.** When a request leans on a thin
dimension, don't just caveat it — offer the user's *contribution* there. Melody
is our thinnest, but round-trip is **fully supported**: *"bring me your topline —
sketch it in Ableton — and I'll build the whole track under it."* This is the
standard move for any thin dimension, and it rests on round-trip, which is
**supported, not a hazard**. (Generally: a user can sketch any part in the
sequencer and we ingest it.)

**Three rules:**
1. **Never confabulate.** If it's not in the table as ✓ or ◐, don't promise it.
2. **Never gate the goal.** Caveat the thin dimension; deliver the rest.
3. **Never silently substitute.** Don't quietly swap a generated melody for the
   user's intended one — name the gap and invite their input.
