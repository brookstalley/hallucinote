---
name: compose-review
description: >-
  Compose-stage guided evaluation for a song — the compositional sibling to /mix-review. After a first pass, recalls the song's declared intent, reads the COMPOSITION (sections, which parts play where, density/register, the energy arc — from build.py + the arrangement, not audio) AND the line-level melodic reading from the symbolic melody lens (contour, intervals, harmony-fit — `hallucinote.tools.melody_lens`) AND the form/recurrence reading from the symbolic recurrence lens (which registered motifs recur where + as which variation, plus motivic economy — `hallucinote.tools.recurrence_lens`), and interprets it AGAINST intent: "you wanted the chorus to lift — does it? here's the one thing holding it back." Surfaces as a producer's question, never a verdict or a score. Teaches contrast and subtraction by ear. Lifts the "what is this for?" question to section and song altitude and learns revealed intent back as a markdown annotation. Use after a first compositional pass, or when the user asks "does this work?", "is the chorus landing?", "is the hook/melody working?", "what's missing?", "review the arrangement" — BEFORE the mix stage (that's /mix-review).
argument-hint: <song-slug> [section]
user-invocable: true
disable-model-invocation: false
---

# /compose-review — help the user *hear* the composition against what they wanted

> **Running engine commands.** The symbolic lenses ship in the plugin's uv env. Resolve `$PY` once from `ableton://server/info`'s `python`; the `hallucinote melody …` / `recurrence …` commands below run as `"$PY" -m hallucinote.cli …`. See [`docs/running-the-engine.md`](../../docs/running-the-engine.md).

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

## One axis per turn (the review-workflow discipline)

Music is too complex to review on every concern at once — that's how you chase
tails (re-arranging after a sound pass, re-voicing what's really a layering
problem). So a single review pass acts on **ONE axis**, chosen from the song's
declared `review_workflow` archetype (RECALL step 1; model:
`.prawduct/artifacts/review-workflow-model.md`).

- The axes `/compose-review` owns: **arrangement** (layering / density / contrast /
  energy arc — and **form/recurrence**: which registered motifs recur where, read by
  the recurrence lens; recurrence is part of the arrangement axis, NOT a new axis),
  **harmony** (progression realization), **melody / line** (contour, intervals,
  harmony-fit). `/mix-review` owns the sonic axes (sound, performance, mix-balance) —
  don't reach into those here.
- **Read holistically, EDIT one axis.** You may notice problems on another axis —
  NOTE them (a deferred review note via LEARN-BACK), but don't fix them this turn.
- **Default archetype A (Ordered-Pass)** when the song declares none — and say so.

## The loop

### 1. RECALL — read the song's intent first

Run `/song-context <song-slug>` to load declared intent at every altitude:

- **Song** — `songs/<slug>/<slug>.md` + `decisions/` ("a study beat — calm,
  never demands attention").
- **Section** — `time`-scoped annotations ("the verse holds back so the chorus
  can win"). If absent, this is the gap C4 fills — see LEARN-BACK.
- **Element** — the mix-intent tags (`focal`/`submerged`/`blend-group`/
  `density`), if any.
- **Workflow** — the song's `review_workflow` archetype (a `scope: song`
  annotation, tag `review-workflow`). It declares the axis order this song uses
  (`.prawduct/artifacts/review-workflow-model.md`). **Default to A (Ordered-Pass)
  if absent, and say so.** It tells you which axis this pass should be on (this
  skill owns arrangement / harmony / melody) and whether axes are reviewed
  together (B) or subtractively (C). Act on one axis — see "One axis per turn."

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
  somewhere to come back from? Compare each section to its neighbours. This is
  the **symbolic, render-free** read of the authored `energy_curve` (the
  compose-axis this skill owns); its render-time complement is `/mix-review`'s
  `energy_realization` lens (ARR-7M3D), which checks whether that authored arc
  actually rendered as measured intensity (Spearman ρ + inversions).
- **Contrast** — does the verse give the chorus something to win *against*? The
  single most common novice miss is no subtraction: everything plays everywhere,
  so nothing lifts.

**Line-level melody (run the lens).** The bullets above you read by eye from the
score; the *melodic line itself* — its shape and harmonic fit — you cannot eyeball.
Run the symbolic melody lens:

```
"$PY" -m hallucinote.cli melody <song-slug>          # whole song
"$PY" -m hallucinote.cli melody <song-slug> --section <name>
```

Per monophonic line, per section, it reports: **contour** shape + apex,
**intervals** (step↔leap profile, post-skip reversal, pitch alphabet, ambitus),
**within-line repetition coverage** (how much of the line is a repeated multi-interval
cell), **per-phrase contour** (LBDM phrase segmentation — where the arch actually
lives, since a looping hook reads `level` whole-section), and **harmony-fit**
(chord-tone / non-chord-tone shares, whether non-chord-tones resolve by step, whether
chord tones favor strong beats) — plus coaching questions (a near-static line;
abundant *unresolved* non-chord-tones against the harmony).
These are **neutral facts, never a verdict**: there is no universal "good melody"
(a chromatic bebop head and a folk hook read differently against their own idiom —
see `.prawduct/artifacts/melody-model.md` §1), so grade them against the line's
**declared intent** exactly as you grade density. If a song's build.py has no
`melody_report()` wired yet, the lens says so (exit 3) — note it and read the line
by eye.

**If a line declares a `MelodicProfile`, the lens grades against it** (profile-
relative, still a question; melody-model.md §4). A song declares its profiles in
`build.py` (`{layer_name: MelodicProfile}`, passed to `analyze_arrangement(...,
profiles=...)`) — the declaration IS the learn-back, so a deliberate genre choice
(an angular metal lead, a third-based reggae hook) never re-flags. With a profile
present the lens adds profile-RELATIVE coaching questions on top of the neutral
facts: a `harmonic-freedom` / contour / apex / ambitus / step-appetite / repetition-
appetite divergence ("you declared a chord-tone-locked line; it's 60% non-chord-tone
— intended?"), and a profile-relative **shaped-vs-aimless** reading (`shaped` /
`aimless` / `ungraded`) that fires `aimless` ONLY against a definite declared intent
the line contradicts — never a universal verdict. With NO profile, the lens reports
the neutral facts exactly as before. Every melody finding stays a *question*.

This is compositional evidence, neutral — like the MixReport, you grade it
against intent, you don't grade it on its own.

**Recurrence / recapitulation (run the lens).** The melody lens reads a *single
line's* shape; the recurrence lens reads *form* — which **registered motifs** recur
across the whole arrangement (organ / lead / steel / …), where, and **as which
variation** (an `exact` quote, or a recovered `transpose` / `augment` / `diminish` /
`invert` / `retrograde` / `fragment`, or a bounded composition like
`diminish∘fragment`). Run it:

```
"$PY" -m hallucinote.cli recurrence <song-slug>          # whole song
"$PY" -m hallucinote.cli recurrence <song-slug> --section <name>
```

It reports each recall (motif → section → layer → variation) plus a **motivic-economy
summary** (cell-set size, recall coverage, a compression-ratio proxy). These are
**neutral facts, never a verdict**: authored recapitulation is not an error, and
economy is **style-relative** — a through-composed piece is *legitimately* less
economical than a minimalist one (`research.md` §2 Temperley), so the lens reports
the number and never says "be more economical." Grade each recall against the song's
**declared recurrence intent** ("the outro was meant to recall the hook augmented —
does it land there?"), exactly as you grade density. Two honest limits to carry: it
reads only **registered** motifs (a recurring free function never `arr.motif(...)` is
invisible — register it to track its recall), and it reads realized fact, not
declared intent. If a song's build.py has no `recurrence_report()` wired yet, the lens
says so (exit 3) — note it and read the recap structure by eye.

> **Boundary (READ §2 reads three distinct lenses — do not conflate them):**
> the **within-line melodic** read (one line's contour / intervals / n-gram
> repetition / harmony-fit, graded against its declared `MelodicProfile`) is the
> melody lens above; **recurrence** = **cross-instrument registered-motif**
> recall/recapitulation across the arrangement (this block); the **energy-curve
> realization** read is ARR-7M3D's and wires into `/mix-review`, NOT here (no
> collision on `/compose-review`). Each is a separate lens over a separate unit —
> one line, the motif graph, the section-energy curve — so they read beside each
> other without ever double-reporting.

### 3. INTERPRET — composition against intent

For each notable observation:

- **Matches intent** → stay quiet. A verse that's sparse *on purpose* is correct
  authorship, not a problem.
- **Contradicts a CLEAR intent** (the chorus was meant to lift but every section
  has the same layers; the focal hook never enters) → **surface it**, as an
  option with the cheapest musical fix first (fix order below).
- **Intent unknown and it matters** → **ask ONE good question**, framed by ear:
  "the chorus has the same parts as the verse — is it meant to feel like a
  continuation, or should it open up?" (Line-level too: "the lead leaps a lot and
  sits mostly off the chord — is that the angular character you want, or should the
  hook sing closer to the harmony?")

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

### 6. LOG ATTEMPTS — record what you tried and how it turned out

The learn-back above captures *intent* (where the song wants to land). The **attempt
ledger** captures the *path* — a move you tried and how it resolved, **especially the
reverted dead ends**, so a later pass doesn't re-try them. Different thing, same moment:
when a compositional move is resolved this pass (kept / reverted / replaced), propose a
one-line `kind: attempt` entry and let the user confirm (propose-and-react — don't
auto-write a verdict). Query the ledger *before* re-touching a part via `/song-attempts`.

```python
write_markdown_ref(
    conn,
    path=Path("songs/<slug>/attempts/2026-06-14-lead-octave-double.md"),
    repo_root=Path("."),
    frontmatter={"date": "2026-06-14", "kind": "attempt", "scope": "track",
                 "track": "Lead", "outcome": "failed", "resolution": "reverted",
                 "tags": ["arrangement", "doubling", "chorus"]},
    body="Tried doubling the lead an octave up through the chorus to lift it — "
         "muddied the 2–3 kHz band and buried it. Reverted; held the single line "
         "and subtracted the pad instead (that worked).",
    actor="llm", reason="attempt-log from compose-review",
)
```

`outcome` ∈ {worked, partial, failed}; `resolution` ∈ {kept, reverted, superseded}.
Chain a correction by adding `related: ["songs/<slug>/attempts/<the-move-that-worked>.md"]`
to the failed entry. Musical-craft only — a *tool* gripe (a push glitch, a Live bug) is an
incoming-bug, not an attempt; revealed *intent* is an annotation, not an attempt.

## When to use this vs /mix-review

`/compose-review` is **before** `/mix-review` in the lifecycle: it asks whether
the *notes and arrangement* serve the song. `/mix-review` asks whether the *mix*
lets the right element win. A flat chorus is usually a composition problem
(nothing was held back) long before it's a mix problem — fix it here first.

`/compose-review` is symbolic (it reads `build.py` + the arrangement), so it runs
on **any Live edition**. `/mix-review` reads rendered audio and **needs Max for
Live** (Suite, or the M4L add-on) — so without Max for Live, this is the intent
read you have.

## Honest confidence — caveats you MUST carry

- **You're reading the score, not hearing it.** Density/layering on paper
  approximates energy; dynamics, sound design, and feel also carry lift. Say so
  — "on paper the chorus adds two parts; we'll confirm by ear" — and prefer
  RELATIVE reads (section-vs-section) over absolute claims.
- **Sparse is not the same as empty.** Held-back is authorship; only flag thin
  sections when they contradict a stated or clearly-implied intent to lift.
- **You propose; the artist decides.** Auto-applying compositional changes
  produces generic music, for the same reason it does in the mix.
- **The melody lens reports facts, not a good/bad melody.** Contour, leap-rate,
  alphabet, and harmony-fit are *genre-relative* — a high non-chord-tone share is a
  defect in a hymn and the whole point in a bebop head; a static line is a flaw or a
  deliberate drone. Never read a lens number as a verdict. Ask whether the line
  realizes ITS intent, and **learn the answer back** (LEARN-BACK) so it never
  re-flags. The lens also reads the *line you wrote at the note floor* — including a
  topline a user sketched in and you arranged under — so it's the right surface for
  "is the hook landing?", not just "are the parts arranged right?"
- **The recurrence lens reports recall facts, not "good recapitulation."** It tells
  you a registered motif recurred (and as which variation) and reports motivic
  economy as a raw number — it never says a recall *should* be there or that material
  is "too scattered" (economy is style-relative — Temperley). It reads only
  **registered** motifs and reads realized fact, not declared intent: a recurring
  free function is invisible (register it), and a `derived` reading means "a partial
  recall I can't fully name," not "wrong." Grade each recall against the song's
  declared recurrence intent and learn the answer back.

## One-line thesis

`/mix-review` asks "which collision hurts the part that's supposed to win?"
`/compose-review` asks the prior question — **"is the composition even giving
that part a chance to win, and if not, what's the cheapest musical change?"** —
then teaches the answer by ear and gets out of the way.
