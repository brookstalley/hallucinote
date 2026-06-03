# Capability Truth — what Hallucinote can actually do right now

This is the **anti-hallucination spine** for first contact and song creation. It
is read by the `/ableton-mcp-install` Step-5 handoff and by `/song-new` so the
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
> reviewed: **2026-06-01** (melody gained a read-side *line-analysis* capability —
> the symbolic melody lens, wired into `/compose-review`; *authoring* a finished
> hook stays thin, by design).

## The dimensions

| Dimension | Status | What that means in practice |
|---|---|---|
| **Rhythm / groove** | ✓ full | kick_stumble, tresillo, boom-bap, swing, kit abstraction, per-part microtiming `feel` (push/pull/drag). |
| **Harmony** | ✓ full | pads, stabs, tresillo pluck, sparse bells; chord movement across sections. |
| **Bass** | ✓ full | tresillo, walking bass, sub/Reese-style lines. |
| **Arrangement / structure** | ✓ full | sections, energy arc, contrast, build/drop, subtraction. |
| **Sound design** | ✓ full | instrument *chains* (instrument + saturation + bus FX) as authorship, not a mix-time todo. |
| **Mix** | ✓ full | intent-aware review, masking analysis, sidechain, reverb sends, loudness. |
| **Melody — line analysis** | ✓ read-side | the symbolic **melody lens** reads any monophonic line's contour, intervals, and harmony-fit and coaches it *against your declared intent* (`/compose-review`, `tools/melody_lens.py`) — including a topline you sketched in. It measures, it never invents the hook (that's yours). No universal "good melody" verdict. |
| **Melody — lead-line *authoring*** | ◐ thinner | I won't write your finished hook — that's your art, by design (no melody generator, ever). A generated topline is a starting point, not the finished hook. *Sketch your line in Ableton and I'll arrange under it (round-trip) — and read whether it lands its intent (line analysis above).* |
| **Vocal topline (synthesis)** | ✗ not yet | we don't synthesize a sung vocal. A sketched vocal *melody* (MIDI) round-trips in — and the line analysis above reads it. |
| **Round-trip / sketch-input** | ✓ full | edit in Ableton, we ingest + build around it — `/ableton-pull` `clip-notes`, stable per-note IDs. |

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
(contour, how it sits on the chords) via `/compose-review`."* That is a stronger,
more honest inversion than "melody's my weak spot": you keep the hook, I build the
world around it and hold up the mirror. The round-trip itself is **supported, not a
hazard** — a user can sketch any part in the sequencer and we ingest it.

**Three rules:**
1. **Never confabulate.** If it's not in the table as ✓ or ◐, don't promise it.
2. **Never gate the goal.** Caveat the thin dimension; deliver the rest.
3. **Never silently substitute.** Don't quietly swap a generated melody for the
   user's intended one — name the gap and invite their input.
