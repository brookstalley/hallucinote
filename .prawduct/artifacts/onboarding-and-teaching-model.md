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
2. **Assume users want to know more than they do** — but transfer it *implicitly*.
   The reasoning is always present in the flow, never hidden; but it arrives as a
   collaborator thinking out loud, not as instruction. **Never a classroom;
   creating a song never feels like homework.** Knowledge transfers in the natural
   flow of fleshing out what the song sounds like, or it stays implicit — the
   vocabulary only surfaces if the user reaches for it.
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

## Personas we're serving

Grounded in `docs/VISION.md` ("composers anywhere on the spectrum… same as an LLM
coding agent serving a middle-schooler and a senior engineer") and this
conversation. *The specific personas sketched earlier this session were not filed
and are reconstructed here — correct freely. That they lived only in conversation
is itself a finding: load-bearing personas belong in an artifact.*

Two independent axes that **compose**:

**Musical-expertise axis** (per domain, never a stored profile):
- **Hobbyist / no-theory** — has something in their head, can't yet name it
  musically (the Madonna kid). Value = guided growth.
- **Cross-domain musician** — fluent in one domain, reaching into another they
  don't command (the drummer who says "make it feel like Bach"). Value = the
  third register opens the unfamiliar domain.
- **Working producer** — competent, knows what they want, wants speed, leverage,
  and bulk operations. Value = directed execution; get out of the way.
- **Veteran** — wants the hard stuff (polytempic, microtonal) and zero friction.
  Value = leverage + honest capability edges.

**Session-goal axis** (what they came to do): **Create** new music · **Revise**
existing music · **Learn the tool** itself (forking, sync, semantic addressing).

The same person occupies different cells in different sentences — directed on
groove, under-articulated on harmony; creating today, revising tomorrow.

## The third register

The producer model in `intent-collaboration-model.md` has two registers. The
teaching North Star requires a third — without it, a novice reaching into a
domain they can't yet articulate gets either silent guessing or a curt question.

| Register | Trigger | Behavior |
|---|---|---|
| **Directed action** *(existing)* | "fix X", "make Y cut" | Execute. Obedience unconditional. The artist's ears are the authority. |
| **Volunteered observation** *(existing)* | Tool noticed something | Intent-gated; surface as a question, never a verdict. Stay quiet if it matches declared intent. |
| **Directed-but-under-articulated** *(new)* | User asked for something they can't yet specify — *"make it feel like Bach"*, *"a pop song like Madonna"* | **Open the domain.** Don't execute a silent best-guess (auto-accompaniment); don't just ask one question and proceed. Propose, name the *why* in one teachable sentence, and offer a real choice that grows their understanding. |

The third register fires on the **request, not the requester**: it triggers when
the ask is underspecified in some dimension (see the elicitation model below) —
never on a judgment that the user "is a novice." The drummer's "make it feel like
Bach" triggers it because *Bach* is unpinned, not because we decided the drummer
can't do harmony. Opening the domain *is* the elicitation.

## Read the request, not the requester — the elicitation model

We form **no judgment about user expertise** — no inference, no profile, no
novice/expert branch, no fluency detection. We assess exactly one thing: *is this
request specified enough to build something that matches what's in their head?*
That is a property of the **ask**, not the **asker**. An expert's "four-movement
symphony exploring atonality in the strings, classical elsewhere" is as
underspecified as a hobbyist's "a Madonna song" — and we treat them identically:
elicit. This **dissolves** the fluency-detection problem rather than solving it.

**Bias: elicit toward "enough to start," not "enough to finish."** The goal is a
first *concrete pass* the user can react to — not a complete spec. A reaction to
real music elicits more, and truer, direction than answers to abstract questions
(see "intent discovered retrospectively"). So only the **load-bearing** unknowns
get asked up front — the ones where a wrong guess wastes real work or is a
creative lock-in (tonal concept, form, the central tension). Cheap-to-revise
choices are made tastefully and *shown*; the artifact itself becomes the next
proposal, instantly redirectable. (This is also the pacing answer: don't fork
every elementary choice into an A/B — elicit at the expensive forks, just-do-
and-show at the cheap ones.)

**Two modes, one discipline:**

1. **Open elicitation** — request underspecified, user has more in their head:
   ask, lightly, *only* the load-bearing questions. At most one or two before
   handing them something concrete; more than that is interrogation.
2. **Proposal elicitation** — open questions stop yielding direction (the user
   says "I don't know, you decide," or vagueness repeats): **stop asking, start
   proposing.** A concrete, redirectable proposal — ideally a small set of
   *distinct* options — surfaces direction the user couldn't generate cold.
   Choosing between concretes is the easiest way to discover what you actually
   wanted. *"That's all the direction I have" is a cue to propose, never a
   license to assume.*

**The one discipline across both: never assume-and-go.** Every gap is either
elicited or *proposed and reacted to*. A proposal the user doesn't object to is
**confirmed** direction — we surfaced it; a silent assumption is not. That line
is the line between collaboration and auto-accompaniment.

**What keeps proposal-mode honest:**
- **Redirectable, not fait accompli** — "I'm thinking X, or it could be Y — what
  feels right?", never "I did X." The user visibly holds the wheel.
- **Name the why** — the proposal carries its reasoning ("atonal strings *in
  conflict* sells the four-movement arc as a struggle"), so the user learns the
  dimension they're now steering. **Teaching is not a separate novice branch — it
  is what good elicitation looks like.** The expert skims the why; the novice
  learns from it; we never decided which is which. The why is **one natural
  sentence of a collaborator's reasoning**, never a lesson — "I held the verse
  back so the chorus opens up," not "this is a deceptive cadence, which in theory
  means…". The concept transfers through the experience and the offhand naming;
  the theory vocabulary only comes out if the user asks for it. Never a classroom;
  never homework.

The transition signal (open → proposal) is usually implicit — a trailing-off, a
"whatever you think," a repeated vagueness. Read those as *propose now*, not
*assume now*. Never force a user to answer questions they don't have answers to:
a user who thinks by reacting is better served by a proposal than a fourth
question.

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
- **Collaborate when direction is absent — clear direction always wins.** This is
  a fallback, not an override: when the user *has* directed, execute (the
  directed-action register). When they haven't directed an elementary choice
  we're about to make, **don't decide it silently (that's auto-accompaniment) —
  propose it and invite reaction** per the elicitation model, often with an A/B:
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

## Session shapes: create, revise, learn-the-tool

The install-tail elicitation **routes on the user's answer** — it does not *ask*
which mode (no dependence menu); it reads intent from what they say ("start a new
song" vs "load falling-walking and fix the chorus").

**Create** — covered by pieces 1–5 above.

**Revise** — the user loads an existing song into Live and works on it. The load
path is the existing push flow (`/ableton-push` / "load \<song\>" from the install
handoff — *assumed to be the right piece; confirm*). Revision is **mostly
directed-action + volunteered-observation**, so the *existing*
`intent-collaboration-model` already fits it ("tighten the chorus", mix-review).
The teaching North Star applies less here — the user has material and intent;
leverage dominates. Two things this flow must get right:

- **Load-bearing caveat — sync-back is not safe yet.** Per `docs/VISION.md`,
  until note-level addressing lands, Ableton→DB is destructive ("we push, we do
  not pull safely"). A revision user who edits in Live expecting a clean
  round-trip can lose work. This is caveat-first at its most consequential —
  surface it *before* they start editing in Live, not after.
- **Revision still teaches by ear** — mix-review and the compose-stage guided
  evaluation apply: "the chorus you tightened now buries the vocal — hear it?"

**Learn-the-tool** — a *distinct teaching target*. This user wants to learn
Hallucinote's **workflow** (branch a chorus variant, push/pull, semantic
addressing), not music theory. The musical-teaching model (pieces 4–5) does
**not** cover this; it needs **tool-scaffolding** — the same
propose→explain→show-the-difference verb applied to *workflow* moves ("let's
branch this chorus so you can A/B it — watch what the diff shows"). Currently
unaddressed; flagged.

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

## Coherence review — resolved and open

Stress-testing the flow against the personas surfaced four tensions. Two are now
**resolved** by the "read the request, not the requester" reframe; two remain.

**Resolved:**

1. **Classifying users (was: "fluency detection" + "serving novices").** These
   were the same mistake — both assumed we must judge the user's competence and
   branch on it. We don't. We assess request-*completeness* and elicit; we never
   profile the requester. This dissolves the patronize-vs-auto-accompany dilemma:
   both collapse to "elicit when underspecified, propose when direction runs out,
   never assume-and-go." The novice gets a reasonable experience not from special
   scaffolding but from the same elicit-don't-assume behavior everyone gets.
   *Residual, deferred by choice:* the **technical** entry gate (clone / pip /
   MCP / Ableton click) still filters non-technical users. That's a distribution
   problem we are explicitly choosing not to fully solve now — we ensure a
   reasonable experience for whoever gets in, and revisit packaging later.

2. **Collaborate-by-default over-stepping the leverage personas.** Fixed by
   precedence: collaboration is the fallback when direction is *absent*; clear
   direction always wins (directed-action register). Pacing is handled by the
   load-bearing-vs-cheap rule in the elicitation model — elicit at expensive
   forks, just-do-and-show at cheap ones; don't fork everything.

**Open:**

3. **The transition signal (open → proposal) is a read, not a flag.** Users
   rarely say "that's all I've got"; they trail off or say "whatever you think."
   Reading those correctly — *propose now*, not *assume now*, and not *ask a
   fourth question* — is a judgment call we're asking the agent to make well
   every time. No mechanism guarantees it; it's a behavioral discipline that will
   sometimes misfire. Worth watching in practice.

4. **Revision: destructive-sync hazard + missing teaching target** (unchanged) —
   see "Session shapes": the unsafe sync-back caveat must fire *before* Live
   editing, and the learn-the-tool persona needs workflow-scaffolding the musical
   model doesn't provide.

**Net:** the reframe made the flow markedly more coherent — it's now genuinely
good for users *across the expertise spectrum*, because it stopped trying to tell
them apart. The live risks are behavioral (reading the elicitation transition
well) and technical (revision's sync hazard, the non-technical entry gate as a
deferred distribution problem), not structural.

## Persona walkthrough — the write-a-song scenario

Six personas spanning computer-expertise × music-expertise (incl. partial),
walked through the create flow. *Excluded by choice:* the "wants a pretty song,
no interest in learning" user — supported, not optimized for. **Verdict up front:
the interaction model (read-the-request → elicit → propose → implicit teaching)
holds for all six — it never breaks on *who* the user is.** The rough edges are
not in the model; they cluster in three places below.

| # | Persona | Comp / Music | Create-flow stress point |
|---|---|---|---|
| 1 | SWE hobbyist | high / low | Frictionless entry; references-as-spec ("like the Stranger Things theme") work; implicit-why delights a curious technical mind. Smoothest case. |
| 2 | Bedroom producer (self-taught) | high / high-production | Directed-action dominates; risk = over-proposing taxes them. Precedence (clear direction wins) must hold. Wants bulk leverage the linear compose flow under-serves. |
| 3 | Conservatory composer | low / very-high-theory | Entry gate is a real barrier. Once in: paradigm mismatch — score / orchestration vs generator / DAW; melody ◐, no notation-first path. Interaction model fine; the *capability ceiling* disappoints. Needs early, honest expectation-setting. |
| 4 | Cross-domain drummer | mod / expert-rhythm, novice-harmony | The third register's showcase: execute the drums, open the harmony — in one sentence. Risk = under-reading the underspecification and silently auto-accompanying "make it feel like Bach." |
| 5 | Singer-songwriter / topliner | low-mod / expert-melody + vocal | Brutal: their strength (melody, vocal) is our thinnest dimension (◐ / ✗). Best served by *inverting the gap* — "bring your melody, I'll build the track under it" — which leans on the caveated input / sync paths. |
| 6 | Curious newcomer (wants to learn) | mod / low | The North Star persona. Heavy proposal-mode; strong genre conventions (lo-fi) let us just-build-and-show. Risk = proposal overload / paralysis if we over-fork. |

**The rough edges cluster in three places — none is the interaction model:**

1. **Entry gate, and an inverse correlation.** The technical on-ramp
   (clone / pip / MCP / Ableton click) filters hardest exactly the *music-strong,
   computer-light* personas (3, 5) — the people most able to use the musical
   depth are the least served by the on-ramp. Deferred (distribution), but the
   walkthrough sharpens *who* it costs.
2. **Capability ceiling on melody / vocal — invert it into a contribution
   boundary.** Personas whose strength is melody / voice (5, partly 3) hit our
   thinnest dimensions. **New design move:** turn the gap into an invitation —
   "I can't write the finished hook or sing it; bring yours and I'll arrange the
   whole track under it." Caveat-first stops being an apology and becomes a
   collaboration boundary. (Leans on melody-input + the still-unsafe sync-back —
   note the dependency.) The conservatory composer additionally hits a *paradigm*
   limit (notated orchestration), which only early honesty fixes.
3. **The two behavioral judgment calls, confirmed live.** Reading the
   open→proposal transition (4, 6) and proposal *pacing* (6); plus
   collaborate-default yielding to the power producer (2). All already flagged;
   the walkthrough shows each biting a specific persona.

**Net:** reframing to "read the request, not the requester" paid off — the model
is robust across the whole spectrum. What's left to get right is *capability
honesty* (set the composer's and topliner's expectations early; offer the
gap-inversion to the topliner) and *behavioral judgment* (transition + pacing).
The entry gate remains the deferred distribution problem, now with a name for who
it costs most.

## Deliberately not decided here

- **No build plan yet.** Shape first. This artifact is the shape; chunking,
  tests, and sequencing come after review. (Likely thin vertical slice: the
  Capability Truth + the rewritten install-Step-5 handoff, since the
  intent-eliciting first-contact leans on both.)
- **Dev-session-briefing vs musician-first-contact** at the raw Claude Code
  session level remains a separate surface; the musician's entry is now settled
  (install tail), so this is narrowed, not urgent.
