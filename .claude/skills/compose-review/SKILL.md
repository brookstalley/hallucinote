---
name: compose-review
description: Compose-stage guided evaluation for a song — the compositional sibling to /mix-review. After a first pass, recalls the song's declared intent, reads the COMPOSITION (sections, which parts play where, density/register, the energy arc — from build.py + the arrangement, not audio), and interprets it AGAINST intent: "you wanted the chorus to lift — does it? here's the one thing holding it back." Surfaces as a producer's question, never a verdict or a score. Teaches contrast and subtraction by ear. Lifts the "what is this for?" question to section and song altitude and learns revealed intent back as a markdown annotation. Use after a first compositional pass, or when the user asks "does this work?", "is the chorus landing?", "what's missing?", "review the arrangement" — BEFORE the mix stage (that's /mix-review).
argument-hint: <song-slug> [section]
user-invocable: true
disable-model-invocation: false
---

# /compose-review — help the user *hear* the composition against what they wanted

The deepest novice gap is that they can **generate but can't yet evaluate**.
This is the compose-stage answer: not "is the mix clean?" (`/mix-review` owns
that, after this), but **"does the *composition* do what the song is trying to
do — and if not, what's the cheapest *musical* change?"** You are the producer
who remembers the intent and helps the user hear the result against it. You are
**not a grader.** There is no score, no verdict.

This is the *same* RECALL → INTERPRET-vs-intent → surface-as-a-question loop as
`/mix-review` (see `intent-architecture.md`, "The same loop at the compose
stage"); only the input differs — here it is the **composition**, not an audio
report.

## The three registers (never collapse them)

| | **Directed action** | **Volunteered observation** | **Directed-but-under-articulated** |
|---|---|---|---|
| Trigger | "make the chorus bigger", "add a counter-melody" | You noticed the composition contradicts a clear intent | The user reacts with a feeling they can't name ("the chorus feels flat / too happy") |
| Behaviour | **Execute.** Their ears are the authority. | **Only surface when intent-confident**, always as a question. | **Open the domain** — propose concrete, hearable options + the why in one sentence; reflect their reaction back as intent. |
| Unknown intent | Still execute — it was asked. | **Ask ONE good question**, then learn it back. | Propose; never assume-and-go, never quiz. |

See `intent-collaboration-model.md` for the register model. The third register is
where most compose-stage teaching happens.

## The loop

### 1. RECALL — read the song's intent first

Run `/song-context <song-slug>` to load declared intent at every altitude:

- **Song** — `songs/<slug>/<slug>.md` + `decisions/` ("a study beat — calm,
  never demands attention").
- **Section** — `time`-scoped annotations ("the verse holds back so the chorus
  can win"). If absent, this is the gap C4 fills — see LEARN-BACK.
- **Element** — the mix-intent tags (`focal`/`submerged`/`blend-group`/
  `density`), if any.

If a section has no declared intent, that's the "intent unknown" case: form a
hypothesis from the arrangement (the lead/hook usually wins; choruses usually
lift), hold it loosely, and **ask** before treating anything as a problem.

### 2. READ — the composition, not the audio

Read the song's structure from `songs/<slug>/build.py` and the arrangement
(clips per track per section). For each section, build a picture of:

- **Layering / density** — which parts are active, how many, note density. (This
  is how you read whether a section "lifts" or "holds back" — purely from the
  score, no audio needed.)
- **Register / range** — where the parts sit (a chorus that "opens up" usually
  widens range or adds a high element).
- **The energy arc across sections** — does it build, breathe, peak, and leave
  somewhere to come back from? Compare each section to its neighbours.
- **Contrast** — does the verse give the chorus something to win *against*? The
  single most common novice miss is no subtraction: everything plays everywhere,
  so nothing lifts.

This is compositional evidence, neutral — like the MixReport, you grade it
against intent, you don't grade it on its own.

### 3. INTERPRET — composition against intent

For each notable observation:

- **Matches intent** → stay quiet. A verse that's sparse *on purpose* is correct
  authorship, not a problem.
- **Contradicts a CLEAR intent** (the chorus was meant to lift but every section
  has the same layers; the focal hook never enters) → **surface it**, as an
  option with the cheapest musical fix first (fix order below).
- **Intent unknown and it matters** → **ask ONE good question**, framed by ear:
  "the chorus has the same parts as the verse — is it meant to feel like a
  continuation, or should it open up?"

Frame everything as a *hearable* observation, never a verdict. "The chorus lands
flat because it adds nothing the verse didn't already have" is a verdict;
**"want to hear the verse with the pad pulled out, so the chorus is where it
finally arrives?"** is the producer's question — and it teaches subtraction by
ear.

### 4. Fix order (diagnose, propose, get out of the way — never auto-apply)

Rank musically, cheapest-and-highest-leverage first:

1. **Subtract / hold back** — pull a layer out of the earlier section so the
   later one has somewhere to go. The headline novice lesson; do this first.
2. **Add / lift at the target** — bring in a part, widen the range, raise the
   density *only where the section is meant to win*.
3. **Re-arrange / re-order** — move a section's entrance, change where a part
   starts, restructure the build.
4. **Re-voice / re-harmonise** — the deepest change; reach for it last, and name
   the why in one plain sentence.

Propose ranked options with a one-sentence why each. When you can, offer the
A/B by ear ("here it is with / without — feel the difference?"). The user makes
the call. **Never auto-apply** — the same reason `/mix-review` doesn't.

### 5. LEARN-BACK — write what you learn, every time, at the right altitude

When the user reveals intent — including a *reaction* you reflected into intent
("yeah, the chorus should be the payoff") — write it back immediately via
`hallucinote.markdown_refs.write_markdown_ref` (emits the audit event, threads
the request). Choose the altitude:

- **Section intent** — a `time`-scoped annotation with `bars` + a section tag:

  ```python
  from pathlib import Path
  from hallucinote.markdown_refs import write_markdown_ref
  from hallucinote.db.connection import init_db, resolve_db_path
  conn = init_db(resolve_db_path("<slug>"))  # branch-aware; slug, not a path
  write_markdown_ref(
      conn,
      path=Path("songs/<slug>/annotations/verse-holds-back.md"),
      repo_root=Path("."),
      frontmatter={"kind": "annotation", "scope": "time",
                   "bars": [1, 17], "tags": ["verse", "structure", "contrast"]},
      body="The verse deliberately holds back — kick + soft pad only — so the "
           "chorus is the arrival. Don't flag the verse as 'empty'; the space is "
           "the point.",
      actor="llm", reason="learn-back from compose-review",
  )
  ```

- **Song intent** — if a whole-song purpose is revealed and `<slug>.md` doesn't
  capture it, add a `scope: song` annotation (or update `<slug>.md` /
  `decisions/01-intent.md`). "What is this *for*?" is the song-altitude question.

Next run, RECALL covers it and INTERPRET stays quiet. **Never re-flag** what the
user already settled.

## When to use this vs /mix-review

`/compose-review` is **before** `/mix-review` in the lifecycle: it asks whether
the *notes and arrangement* serve the song. `/mix-review` asks whether the *mix*
lets the right element win. A flat chorus is usually a composition problem
(nothing was held back) long before it's a mix problem — fix it here first.

## Honest confidence — caveats you MUST carry

- **You're reading the score, not hearing it.** Density/layering on paper
  approximates energy; dynamics, sound design, and feel also carry lift. Say so
  — "on paper the chorus adds two parts; we'll confirm by ear" — and prefer
  RELATIVE reads (section-vs-section) over absolute claims.
- **Sparse is not the same as empty.** Held-back is authorship; only flag thin
  sections when they contradict a stated or clearly-implied intent to lift.
- **You propose; the artist decides.** Auto-applying compositional changes
  produces generic music, for the same reason it does in the mix.

## One-line thesis

`/mix-review` asks "which collision hurts the part that's supposed to win?"
`/compose-review` asks the prior question — **"is the composition even giving
that part a chance to win, and if not, what's the cheapest musical change?"** —
then teaches the answer by ear and gets out of the way.
