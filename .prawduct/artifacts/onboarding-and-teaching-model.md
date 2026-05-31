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
3. **Caveat first, then best effort.** There is *always* something not supported
   yet (today: melody is thin, no vocal synthesis; tomorrow something else).
   Every boundary is named honestly *before* we attempt the best version we can.
   Never gate, never silently substitute.
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
actually do *right now* — not a skill catalog. Status per capability with a
best-effort-fallback note:

| Capability | Status (2026-05-31) |
|---|---|
| Rhythm / groove (kick_stumble, tresillo, kit abstraction, per-part `feel`) | ✓ shipped |
| Harmony (pads, stabs, tresillo pluck, sparse bells) | ✓ shipped |
| Bass (tresillo, walking) | ✓ shipped |
| Arrangement / structure (sections, energy arc, contrast) | ✓ shipped |
| Sound design (instrument chains as authorship) | ✓ shipped |
| Mix (intent-aware review, masking, sidechain) | ✓ shipped |
| Melody (single-line lead writing) | ◐ partial — pluck/bell only; lead-line generation in progress |
| Vocals (synthesis / topline) | ✗ none |

The agent reads this to (a) answer "what can you do?" with broad, *true* example
invitations, (b) generate an **accurate** caveat when a request crosses a
boundary (value #3), and (c) never confabulate a capability. The boundary moves
as Melody ships — the table moves with it. *Caveat-first only works if the agent
knows its own edges; this is that knowledge.*

**Home:** TBD per "design portable behavior now" decision — likely a doc the
onboarding behavior + `song-new` both read. Must stay trivially updatable so it
never lags the code.

### 2. Intent spine — *reuse, extended to the compose stage*

`intent-architecture.md` already defines this: three layers, per-song/section/
element scoping, the `focal/blend-group/submerged/density` tag vocabulary, the
markdown corpus (`annotations/`, `decisions/`), the learn-back reflex. **No
rebuild.** The new work is altitude + timing:

- **One portable question at every altitude — *"what is this for?"*** Song,
  section, element. The element level exists (mix tags); lift the same question
  to **section intent** ("the verse holds back so the chorus can win") and
  **song intent** as the teaching backbone. These are prose annotations in the
  existing corpus, not a new schema.
- **Intent is discovered retrospectively, not interrogated up front.** Novices
  often don't know their intent until they react to something concrete.
  Generate fast, then teach intent by reflecting reactions back as intent
  ("you said that chorus felt 'too happy' — *that's* intent; let's name what you
  want instead") and learn-back per the existing CAPTURE step.
- **Per song, never a global user profile** — consistent with the existing
  model. (This also settles the expertise question: infer fluency per request,
  validate when a decision needs it; do *not* persist an expertise profile.)

### 3. Adaptive collaboration mode — *(new behavioral)*

Open by sorting **what the user wants from the session**, not their skill (which
novices can't self-assess, and which is per-domain anyway):

> *"Want me to just build this for you, or build it with you — stopping at the
> few choices that shape how it turns out?"*

- **For you** = the expert / just-make-it path: drive end-to-end (existing
  creative-prompt norm).
- **With you** = the guided-learning path: the stops are teaching choices with a
  real fork, not status updates.

Within the session, infer per-domain fluency from phrasing; validate only when a
decision genuinely needs it (the Bach case). This replaces `song-new`'s current
`make-me-X` / `scaffold-only` mode split.

### 4. Teaching-by-choice — *(the new interaction verb)*

The atomic move on the "with you" path and in the third register:

**propose → name the why in one sentence → offer a real fork (often an A/B) that
*is* the lesson.**

> "I held the verse to kick + soft snare so the chorus opens up — want to hear it
> with the full kit too, to feel the difference?"

Hearing the with/without teaches contrast better than any explanation, and the
novice makes the call (value #4). The single highest-leverage novice lesson this
delivers is **contrast and subtraction** — the verse holding back so the chorus
wins — which is teachable purely by ear, no theory required.

### 5. Guided evaluation — *the existing INTERPRET loop, at the compose stage*

The deepest novice gap (per research) is that they can generate but can't
*evaluate*. `mix-review` already does intent-aware interpretation for mixing.
Apply the same `RECALL → INTERPRET vs intent → surface as a question` loop at the
**compositional** stage, after the first pass: "you wanted the chorus to lift;
here's whether it does; here's the one thing holding it back." This is where the
lesson consolidates. Likely a lightweight compose-stage sibling to `mix-review`.

## What changes (proposed — not yet applied)

- **New:** the Capability Truth doc; the for-you/with-you opener; a compose-stage
  guided-evaluation surface.
- **Extend:** `song-new` Phase 1 — lighter, altitude-aware intent elicitation;
  mode split becomes for-you/with-you. Lift section/song intent into the existing
  corpus.
- **Amend two CLAUDE.md norms:**
  - "Stop only on high-stakes decisions" — a *teaching choice* is a legitimate
    stop on the with-you path, distinct from a summarize-and-ask.
  - "Creative product prompt → drive end-to-end, phase boundaries aren't
    user-facing checkpoints" — needs a pedagogical carve-out; the norm currently
    assumes the expert case as the default.
- **Generalize the producer model:** add the third register to
  `intent-collaboration-model.md`.

## Deliberately not decided here

- **Distribution / repo first-run.** User chose "design portable behavior now";
  how composers eventually receive Hallucinote (shared repo vs packaged) is
  deferred. A fresh clone today still greets everyone with the developer/
  governance session briefing — out of scope until distribution settles, but
  flagged.
- **No build plan yet.** Shape first. This artifact is the shape; chunking,
  tests, and sequencing come after review.
