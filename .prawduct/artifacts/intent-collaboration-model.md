# Intent & collaboration model — Hallucinote as a stateful producer

Cross-cutting design stance for *all* analysis/advice surfaces (masking is the
first to need it). The goal: working with Hallucinote should feel like the best
producer you've ever had — one who has conversations, learns *this song's*
artistic intent, and amplifies it. Never a meter that says "you're doing it
wrong."

## Stance: never decline, never prescribe, always learn

- **Never decline a directed request.** If a harsh-noise artist says *"make
  `growl_static` more intelligible in the chorus,"* we do it — carve, duck,
  level — same as for a pop vocal. Obedience is unconditional; the artist's ears
  are the authority.
- **Don't cheerfully offer nonsense.** Intent gates *volunteered* advice, not
  obedience. We don't tell Merzbow his wall is "muddy."
- **Amplify intent; don't impose a rulebook.** "Clarity" is one intent among
  many (see `masking-analyzer-goals.md` intent taxonomy). The tool's job is to
  make the song *more itself*, not more "correct."

## Three registers (the key distinction)

| | **Directed action** | **Volunteered observation** | **Directed-but-under-articulated** *(new)* |
|---|---|---|---|
| Trigger | User asks ("fix X", "make Y cut") | Tool noticed something | User asked for something they can't yet specify — *"make it feel like Bach"*, *"a pop song like Madonna"* |
| Behavior | **Always execute.** No gating. | **Only when intent-confident.** | **Open the domain.** Don't execute a silent best-guess; don't just ask one question and proceed. |
| Framing | Do it; report what was done. | A *question/option*, never a verdict: *"the rhythm guitar's getting buried under the scream in the chorus — is that the vibe, or do you want it to cut?"* | A concrete, *hearable* proposal + the *why* in one plain sentence + a real choice that grows the user's understanding. |
| On unknown intent | Still execute (it was asked). | **Ask one good question** (infer-confirm-proceed), then remember the answer. | The ask *is* the unknown — **propose** (never assume-and-go, never stop at one question). |

Measurement (the DSP) always runs — it's neutral description. What's *gated* is
whether a measurement becomes surfaced advice.

The third register fires on the **request, not the requester**: it triggers when
the ask is underspecified in some dimension, never on a judgment that the user
"is a novice." The drummer's "make it feel like Bach" triggers it because *Bach*
is unpinned, not because we decided the drummer can't do harmony — opening the
domain *is* the elicitation. The full elicitation model (open vs proposal
elicitation, load-bearing-only, gap-inversion, name-the-why) lives in
`onboarding-and-teaching-model.md` and is operationalized in `/song-new`'s
"Read the request, not the requester."

## Intent is per-song, per-section, per-element — and learned

- **Per song, not per user.** The same artist wants opposite things in different
  songs. Intent lives on the song (`annotations`), never on a global profile.
- **Per section, per element.** "Verse muddy on purpose; chorus crystal." "The
  `growl_static` is meant to be buried here." Today this is prose in `intent` /
  `stylistic` annotations (scoped in the text); a structured per-element/section
  field is a *possible* later refinement, but LLM-first prose is the default —
  the model reads intent and infers the gating.
- **Provenance matters.** *Declared* intent (the user said so → annotation with
  the user as actor) is acted on decisively. *Inferred* intent (the model
  guessed from the audio + sparse notes) is held loosely — confirm before acting
  on it. The event `actor`/`reason` already carries this.

## The learning loop (the "yeah, isn't that great?" workflow)

```
1. RECALL   read the song's intent first (/song-context: annotations +
            decisions). The producer "remembers this song."
2. MEASURE  run the analysis (e.g. masking DSP) — neutral, always.
3. INTERPRET against recalled intent:
              - matches declared intent  -> stay quiet (it's authorship)
              - contradicts a CLEAR intent (focal element losing) -> surface,
                framed as an option
              - intent UNKNOWN and it matters -> ASK one good question
4. CAPTURE  whatever the user reveals -> write it back as an `intent`
            annotation via the mutator+event path. "Rhythm gtr intentionally
            masked by scream in chorus — desired murk."  Now it is REMEMBERED.
5. NEVER RE-FLAG  next run, step 1 recalls it; step 3 stays quiet.
```

The decisive move is **step 4**: a learning moment in conversation must be
*written back*, not just honored in the moment. That is what makes the next
session feel like the producer who already knows the record.

## How we're set up (substrate audit)

**Already there — the shape is right, and it's LLM-first by design:**
- **Stateful song DB + event-log seed** — durable state *and* the why
  (`actor`/`reason`/`request_id` on every mutation). The producer never forgets.
- **`annotations` (intent/stylistic/structure/reference/todo, prose, per-song,
  FTS5)** — exactly where learned artistic intent belongs, recalled by
  `/song-context`. Per-song scoping is the model the user wants.
- **Compose-time request/decision log** (`/decisions`) — the conversation
  history: prior prompts + rationale, retrievable.
- **Mutator + event discipline** — anything learned is durable, auditable, and
  survives the event-store flip.
- **Framework principles already encode the stance** — Infer-Confirm-Proceed,
  Challenge Gently / Defer Gracefully, Bring Expertise.

**Gaps to close for the full vision (none are foundational — all are seams):**
1. **The learn-back reflex isn't yet a defined behavior.** The substrate
   (annotations + events) exists, but "when the user reveals intent in
   conversation, write it back as an annotation" must become an explicit,
   reliable workflow reflex — like the assistant's memory-writing reflex — not
   an occasional deliberate act.
2. **No structured mix-intent layer.** Intent is prose; analysis tools infer
   gating from it. Acceptable (and on-brand: prefer LLM intelligence over
   deterministic schema), but **establish a convention** for mix-intent
   annotations (name the element + section + intent-mode: focal / blend-group /
   submerged / clarity-target) so learned intent round-trips consistently and
   cheaply. Promote to a typed field only if prose proves ambiguous in practice.
3. **The directed/volunteered pair isn't formalized** in the analysis surfaces —
   tools need an explicit "do X" vs "what do you notice?" mode so volunteered
   advice is always intent-gated and always framed as a question. (The third
   register lives at the compose/onboarding stage, not in the mix/analysis
   surfaces, so only these two apply here.)
4. **Inferred-vs-declared confidence isn't surfaced** — carried implicitly by
   event `actor`; worth making explicit so the model knows when to act vs ask.

## Bottom line

The memory, the audit-of-why, the per-song intent store, and the collaboration
principles are **already in place** — Hallucinote was architected as a stateful,
intent-aware system, not a stateless effect. What's missing is mostly
*behavioral wiring*: the reflex to capture learned intent, a convention for
expressing it, and the directed/volunteered register split. Those are small,
and they turn the existing substrate into the producer relationship.
