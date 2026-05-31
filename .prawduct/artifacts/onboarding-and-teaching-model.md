# Onboarding & teaching model — Hallucinote as a scaffold for what's in your head

Shape decided in conversation 2026-05-31. This governs the **onboarding and
song-creation** experience for users arriving through Claude Code. Read with:

- `intent-collaboration-model.md` — the producer stance (directed vs volunteered
  registers, learn-back). **This doc extends that model upstream** to the
  onboarding + composition stage and adds a third register.
- `intent-architecture.md` — where intent lives (WHAT/WHY/WHY-IT-CHANGED), the
  tag vocabulary, the RECALL→INTERPRET→CAPTURE loop. **Reused as-is**, lifted to
  the compose stage.
- `docs/VISION.md` — "structure unlocks competence", "move up the ladder of
  abstraction". This is the operational expression of that bet.

## North Star: a teaching instrument, not a vending machine

Most AI creative tools optimize for *dependence* — the magic button that keeps
you coming back because you never learned why it worked. Hallucinote chooses the
opposite. Four values, in the user's words, are load-bearing:

1. **A scaffold for what's in their head — not an auto-accompaniment system.**
   The machine never silently decides *for* the user in a domain they care
   about; it opens the domain up so they can choose.
2. **Assume users want to know more than they do.** Default to revealing the
   reasoning, not hiding it. Teaching is a first-class output, co-equal with the
   song.
3. **Caveat first, then best effort — and the caveat is *dimensional*, never
   goal-blocking.** A song has many dimensions (harmony, groove, arrangement,
   sound design, melody, vocal topline). A stylistic goal is almost always
   reachable through the dimensions we render fully; the caveat names the
   dimensions we render thinly, then we deliver anyway. Never gate, never
   silently substitute.
4. **We are not preserving users' novice-hood.** A novice should leave each
   session a slightly better musician. The song is the byproduct of the lesson.

For **experts** the value is leverage; for **novices** it is guided growth. The
same instrument serves both because it calibrates *per domain* and *per session*,
never by a global "beginner/expert" axis.

## The third register

The producer model in `intent-collaboration-model.md` has two registers. The
teaching North Star requires a third — without it, a novice reaching into a
domain they can't yet articulate gets either silent guessing or a curt question.

| Register | Trigger | Behavior |
|---|---|---|
| **Directed action** *(existing)* | "fix X", "make Y cut" | Execute. Obedience unconditional. The artist's ears are the authority. |
| **Volunteered observation** *(existing)* | Tool noticed something | Intent-gated; surface as a question, never a verdict. Stay quiet if it matches declared intent. |
| **Directed-but-under-articulated** *(new)* | User asked for something they can't yet specify — *"make it feel like Bach"*, *"a pop song like Madonna"* | **Open the domain.** Don't execute a silent best-guess (auto-accompaniment); don't just ask one question and proceed. Propose, name the *why* in one teachable sentence, and offer a real choice that grows their understanding. |

The third register is gated by **detected fluency in the relevant domain**, not by
a global skill level. The same drummer is "directed action" on groove and
"directed-but-under-articulated" on harmony — in the same sentence.

## The five load-bearing pieces

### 1. Capability Truth — the anti-hallucination spine *(new)*

A living, **capability-organized** source of truth for what Hallucinote can
actually do *right now* — read as **dimensions of a song**, not a skill catalog:

| Dimension | Status (2026-05-31) |
|---|---|
| Rhythm / groove (kick_stumble, tresillo, kit abstraction, per-part `feel`) | ✓ full |
| Harmony (pads, stabs, tresillo pluck, sparse bells) | ✓ full |
| Bass (tresillo, walking) | ✓ full |
| Arrangement / structure (sections, energy arc, contrast) | ✓ full |
| Sound design (instrument chains as authorship) | ✓ full |
| Mix (intent-aware review, masking, sidechain) | ✓ full |
| Melody (lead-line writing) | ◐ thinner than the rest — pluck/bell lines today |
| Vocal topline (synthesis) | ✗ not yet |

The agent reads this to (a) answer "what can you do?" with broad, *true* example
invitations, (b) generate an **accurate, dimensional** caveat when a request
leans on a thin dimension, and (c) never confabulate a capability.

**The caveat is dimensional, and the goal is still delivered.** The canonical
example — a user asks for *"an 80s pop song like Madonna"*:

> "Love it — I'll write you an 80s synth-pop song in Madonna's musical
> language: the chord moves, the groove, the arrangement, the sound design are
> all things I do well. Two honest caveats: I can't synthesize the vocal, and my
> melody writing is less sophisticated than the rest of me — so the topline will
> be a starting point, not the finished hook. Here's the song…"

Not *"I can't do Madonna (no vocals)."* The Madonna-ness lives in the dimensions
we own; the caveat scopes the two we don't, then we build. The boundary moves as
Melody matures — the table moves with it. *Caveat-first only works if the agent
knows its own edges; this is that knowledge.*

**Home:** a living doc both the onboarding handoff and `song-new` read. Must stay
trivially updatable so it never lags the code.

### 2. Intent spine — *reuse, extended to the compose stage*

`intent-architecture.md` already defines this: three layers, per-song/section/
element scoping, the `focal/blend-group/submerged/density` tag vocabulary, the
markdown corpus (`annotations/`, `decisions/`), the learn-back reflex. **No
rebuild.** The new work is altitude + timing:

- **One portable question at every altitude — *"what is this for?"*** Song,
  section, element. The element level exists (mix tags); lift the same question
  to **section intent** ("the verse holds back so the chorus can win") and
  **song intent** as the teaching backbone. Prose annotations in the existing
  corpus, not a new schema.
- **Intent is discovered retrospectively, not interrogated up front.** Novices
  often don't know their intent until they react to something concrete.
  Generate fast, then teach intent by reflecting reactions back ("you said that
  chorus felt 'too happy' — *that's* intent; let's name what you want instead")
  and learn-back per the existing CAPTURE step.
- **Per song, never a global user profile** — consistent with the existing
  model. (This settles the expertise question: infer fluency per request,
  validate when a decision needs it; do *not* persist an expertise profile.)

### 3. Collaborative by default — never offer to take the work away *(new principle)*

The session does **not** open by asking the user to pick a mode. Offering *"want
me to just build this for you?"* surfaces the dependence path as a legitimate
option — the exact thing the North Star fights. Instead:

- **Assume the user is invested and here for leverage.** Hallucinote is a helper
  that amplifies *their* work, not a service that does it instead of them.
- **Default to collaborative, always.** When the user isn't giving direction on
  an elementary musical choice we're about to make, **don't decide it silently
  (that's auto-accompaniment) — propose it and invite reaction**, often with an
  A/B:
  > "My first thought: E minor, power chords landing on the chorus, denser
  > harmony under the verses to make the chorus feel like a release. Sound right,
  > or do you hear it differently?"
- **The build-it-for-me path exists but is never *offered*.** A user can ask for
  it outright ("just make me something, I trust you"), and we'll oblige — but we
  never put it on the table as a menu choice. Available on request; never
  advertised.

This sharpens — and partly overrides — `song-new`'s current `make-me-X` /
`scaffold-only` split: collaboration is the default stance, not one of two
offered modes.

### 4. Teaching-by-choice — *the default interaction verb*

The atomic move, both in the third register and in ordinary collaborative
composition:

**propose → name the why in one sentence → offer a real fork (often an A/B) that
*is* the lesson.**

> "I held the verse to kick + soft snare so the chorus opens up — want to hear it
> with the full kit too, to feel the difference?"

Hearing the with/without teaches contrast better than any explanation, and the
user makes the call (values #1, #4). The single highest-leverage novice lesson
this delivers is **contrast and subtraction** — the verse holding back so the
chorus wins — teachable purely by ear, no theory required.

### 5. Guided evaluation — *the existing INTERPRET loop, at the compose stage*

The deepest novice gap (per research) is that they can generate but can't
*evaluate*. `mix-review` already does intent-aware interpretation for mixing.
Apply the same `RECALL → INTERPRET vs intent → surface as a question` loop at the
**compositional** stage, after the first pass: "you wanted the chorus to lift;
here's whether it does; here's the one thing holding it back." This is where the
lesson consolidates. Likely a lightweight compose-stage sibling to `mix-review`.

## The entry point — out of the install script

A typical user arrives having cloned the repo, read the README, and run
`/ableton-mcp-install` (guided through MCP setup). At that moment they are a
**music person, not a developer of this project** — and the install skill's
**Step 5 handoff** is the natural, portable place to flow into eliciting what
they want to make, and to explain capabilities.

Today Step 5 prints a static command menu ("load falling-walking", "start a new
song", "/ableton-pull …"). The refinement: that handoff becomes a **warm,
capability-honest invitation that opens an intent conversation** — surface what
Hallucinote does well (from the Capability Truth, in musical/dimensional terms),
invite the user to name what they want to work on, and proceed collaboratively
(piece #3). The dev-facing session briefing is a *different* surface; this is the
musician's first-contact moment, and it lives at the install tail.

## What changes (proposed — not yet applied)

- **New:** the Capability Truth doc; a compose-stage guided-evaluation surface.
- **Rewrite `/ableton-mcp-install` Step 5 handoff** from a command menu into a
  capability-honest, intent-eliciting, collaborative invitation.
- **Extend `song-new`:** lighter, altitude-aware intent elicitation; collaborate
  by default (propose-and-react), retiring the make-me-X / scaffold-only mode
  split. Lift section/song intent into the existing corpus.
- **Amend two CLAUDE.md norms:**
  - "Stop only on high-stakes decisions" — a *collaborative musical proposal /
    teaching choice* is a legitimate stop (creative lock-in), distinct from a
    summarize-and-ask.
  - "Creative product prompt → drive end-to-end" — needs a carve-out: don't
    silently decide elementary musical choices the user hasn't directed; propose
    them and invite reaction. The norm currently assumes the expert case.
- **Generalize the producer model:** add the third register to
  `intent-collaboration-model.md`.

## Deliberately not decided here

- **No build plan yet.** Shape first. This artifact is the shape; chunking,
  tests, and sequencing come after review. (Likely thin vertical slice: the
  Capability Truth + the rewritten install-Step-5 handoff, since the
  intent-eliciting first-contact leans on both.)
- **Dev-session-briefing vs musician-first-contact** at the raw Claude Code
  session level remains a separate surface; the musician's entry is now settled
  (install tail), so this is narrowed, not urgent.
