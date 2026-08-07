# Elicitation & stage exit criteria — a stage may not emit an unresolved gap

**Status:** adopted (2026-08-07) — the stage, the three-state model and the
per-stage criteria ship as norms in `docs/song-workflow.md`,
`docs/song-authoring-conventions.md` and the nine song skills. Two parts are
**not** adopted and are tracked in the backlog, not here: the CLAUDE.md amendment
(owner ratification pending) and the docstring-test lint (deferred, needs its own
build cycle). **Related:** `onboarding-and-teaching-model.md`
(the elicitation registers this operationalizes), `intent-collaboration-model.md`
(propose-and-react), `song-conventions.md` (`decisions/` + `attempts/` schema),
`tour-walkthrough-design.md` (which names this work as a prerequisite for the
next take), `gate-verdict-policy.md` (why none of this is a build-blocking lint).

---

## The defect

The lifecycle in `docs/song-workflow.md` has well-named stages and **no
definition of done for any of them**. A stage can therefore end while a
load-bearing question it was the right place to answer is still open — and,
worse, can end with that question *written down as though it were answered*.

Two failures compound:

1. **No exit criteria.** Nothing says what must be *decided* before the next
   stage starts, so "the code ran" stands in for "the question is closed."
2. **No elicitation.** The one skill that nominally elicits (`/song-new`
   Phase 1) is buried inside a *scaffolding* skill, and CLAUDE.md's stop-less
   norms tell the agent to drive straight through it. The moment where asking
   pays most is the one the norms don't protect.

### Evidence — `examples/angle-of-the-light` (v1, at commit `97816e1`)

- **The Shifter that never existed.** `build.py:_outro`'s docstring said the
  closing octave drop "rides a Shifter device-parameter envelope instead" of
  being authored as notes. There was no Shifter on any track and the DB held
  zero envelopes. The compose stage deferred the *mechanism*, wrote the deferral
  as prose that reads as settled, and no later stage picked it up. **Nothing
  failed**: the build ran clean, the push reported OK, and `decisions/01` cited
  the drop as load-bearing. The song ended flat while every document about it
  said otherwise.
- **The same shape, closed.** The brief's *"the ominous notes are suddenly major
  **somehow**"* also deferred a mechanism — and that one got answered in-stage
  (`decisions/01-the-tritone-transfiguration.md`). Identical shape, opposite
  outcome. The only difference is whether the stage closed it.
- **The budget nobody costed.** The brief under-budgeted three of its own
  sections against its own stated 45–60 s floor. Caught late, by arithmetic
  someone happened to run, not by a stage gate.

**A documented mechanism with no implementation is worse than an admitted gap,
because every later reader takes it as done.**

### The structural cause of non-elicitation

`/song-new`'s `argument-hint` requires `<tempo> <signature> <sections-csv>` and
step 2 shells out to `hallucinote.cli scaffold` with those as **required
arguments**. The agent cannot run the stage without having already decided the
three dimensions elicitation exists to resolve. So it invents them to make the
command run, and the invented values become the song. Elicitation isn't skipped
out of laziness — the tool ordering forbids it.

---

## The principle

> **A stage may not emit an unresolved gap.**

Under-specifying is the user's prerogative. Closing the gap is the *stage's*
job — by deciding it in-stage (proposing, and reading the reaction), or by
marking it explicitly open. What is forbidden is passing an unresolved gap
downstream **in the clothes of a decision**.

## Three states, and a forbidden fourth

Every dimension a stage touches ends in exactly one of three states. This is the
model — never two, never a binary of "answered / not answered".

| State | Meaning | Behaviour | Blocks stage exit? |
|---|---|---|---|
| **DECIDED** | A value is chosen and the *mechanism* that realizes it is named | Record the value; file an ADR if the move is bright-line-substantive | No |
| **UNDECIDED** | The song depends on this and nobody has chosen | Named in the ledger with the stage that will close it | **Yes** |
| **NOT-APPLICABLE** | The song, as described, does not depend on this | Recorded once; **never** surfaced to the user as a question | No |

**The forbidden fourth state: DESCRIBED-BUT-UNBUILT** — prose in a docstring, a
decision record or a brief that names a mechanism which does not exist in
`build.py`, the snapshot, or the DB. This is the v1 Shifter. It is not a legal
state, it is the defect. UNDECIDED is the honest form of the same situation and
is always available.

### NOT-APPLICABLE is a first-class answer

It is reachable **by the agent's own judgement from the material** — it never
requires asking the user. Recording it (rather than merely skipping) is what
lets a later stage distinguish *"we considered this and it does not apply"* from
*"nobody looked."*

> **Silence about a non-applicable dimension is correct. Silence about an
> undecided one is the defect.**

An ambient soundscape has no drum style, no meter argument, and possibly no
tempo worth pinning. Asking anyway is not thoroughness — it reads as
incompetence, and it is exactly how a mechanism becomes a compliance ritual
people route around. A checklist people route around is worse than none, because
it launders the gap it failed to catch.

## The relevance test

Applied per dimension, cheap enough to run honestly:

> **Does the song, as described so far, depend on this?**

Three-way, in one pass:

- The material **doesn't imply it** → NOT-APPLICABLE. Record, stay silent.
- The material implies it **and the user pinned it** (or it follows
  unambiguously from what they pinned) → DECIDED. Restate it so it's
  correctable; don't re-ask.
- The material implies it **and nobody has chosen** → UNDECIDED. This, and only
  this, is a gap.

If a prompt never implies percussion, drum style is not a gap. If it never
implies harmonic motion, a progression may not be either. **The dimension list
below is a prompt for thinking, not a form to fill in.**

## The ledger

One artifact, not seven checklists: **`songs/<slug>/annotations/01-the-brief.md`**.

It carries the user's prompt verbatim, the three-state resolution table, and the
section time budget. Every stage's exit criterion reduces to the same sentence:
*this stage owns no UNDECIDED row, and no row is DESCRIBED-BUT-UNBUILT.*

The brief becomes the **artifact of elicitation** rather than something the user
hand-writes — which is also what gives `docs/tour.md` beat 1 something to show.

Division of labour among the song's markdown, unchanged from
`song-conventions.md`: the **brief** is where a dimension's *state* lives;
`decisions/` carries the WHY of a kept move; `attempts/` carries the path
including reverted dead ends; `annotations/` carries revealed intent. The brief
is an annotation because it is the origin record of intent, not a decision about
craft.

---

## The elicitation pass — `/song-brief`

A new lifecycle stage **0**, in front of `/song-new`. It exists as its own stage
for three reasons: the norms drive the agent straight through anything embedded
inside a scaffolding skill; `/song-new`'s CLI requires as arguments the very
values elicitation produces; and the tour needs a nameable beat.

**Four constraints, load-bearing:**

1. **Propose, don't interrogate.** Informed proposals carrying reasoning and a
   recommendation, inviting a one-word reaction — not blank questions that hand
   the work back. *"I'd propose 132 BPM, here's the arithmetic"*, never *"what
   tempo?"*. A blank question is the auto-accompaniment failure wearing a
   politeness costume: it looks collaborative and transfers zero expertise.
2. **One consolidated turn.** Every proposal, disclosure and piece of arithmetic
   arrives in a single message. Sequential Q&A would violate the stop-less norm
   for real, and is unwatchable on camera.
3. **Its output is the brief.** The turn is not conversation that evaporates;
   it is drafted into `annotations/01-the-brief.md`, and the user's reaction
   edits that file.
4. **Load-bearing AND unstated only.** Cheap-to-revise choices are made
   tastefully and *shown* (the artifact is the next proposal); expensive forks
   are proposed. Nothing already stated is re-asked.

**Silence is a valid pass.** A fully-directed prompt with no applicable
undecided dimension produces a brief with a resolution table and **no
questions** — and the stage moves on without stopping. The pass is not
obliged to find something.

### The dimension prompts

Not a form. Each is run through the relevance test first; most songs will mark
several NOT-APPLICABLE. Drawn from what actually bit v1.

| Dimension | Applicable when | Why it bites |
|---|---|---|
| **Harmony** — key, mode, progression | the prompt makes any tension/release claim | "tension → dissolve → resolve" is a harmonic claim; without a key it is a mood word |
| **Tempo** | the prompt states a duration, or a groove that depends on pulse | 45 s at 90 and at 140 BPM are different songs; the section budget is unsolvable without it |
| **Production stance** | the prompt names ≥2 sonic worlds | whether the worlds argue in the production too, or only in the writing, is a whole-record decision made once |
| **Named narrative turns** | the prompt names a turn without a musical mechanism | *"suddenly major somehow"*, *"finally integrated"* — a destination with no route |
| **Meter** | the prompt names or implies a meter beyond a steady 4 | *see the projection rule below* |
| **Section time budget** | the prompt states a duration **and** names sections | v1 under-budgeted three of its own best moments; arithmetic, not taste, catches it |
| **Mechanism for every named gesture** | the prompt names an audible event (a bend, a riser, a drop, a crash) | the Shifter. A gesture with no mechanism is the defect's home |

The last row is the general form of the v1 failure and the one most worth
internalizing: **a named gesture is not DECIDED until the thing that produces it
is named** — a generator call, an envelope, a device, or hand-authored notes.

### Meter is a projection concern, not a modelling one

**Owner ruling, authoritative:** *the song itself is 7/4 or whatever; if we have
to represent it as 1/4 or 1/8 in Live, fine.*

Elicit what the meter genuinely **is** — *"full 7-rhythm, or 4-then-3?"* is a
real musical question with a real answer, and it changes the groove. Never ask
the user to accommodate a downstream constraint, and never offer *"we'll fake it
as a global 1/4"* as though it were a creative option. It isn't; it is a
rendering detail the user should not have to hold.

**Today the model cannot record the answer.** `M.add_time_signature_point`
raises for any `start_bar > 1.0`:

> `refusing to author meter at start_bar=25.0 — Live 12.4's MCP has no
> song_signature automation target_kind` — `src/hallucinote/db/mutations/score.py`

That is a **projection limitation that has leaked into the model layer**, and it
is a separate defect, sequenced by the owner. This design does not fix it and
does not design around it as permanent. Consequence, stated plainly rather than
smoothed over: for a song with a genuine within-song meter change, the
`/song-new` exit criterion below is **currently unsatisfiable** — the brief will
carry the true meter map and the DB will refuse to hold it, so the row stays
UNDECIDED with the *engine*, not the user, named as its owner. The criterion is
the requirement; the code is what has to move.

(`docs/song-authoring-conventions.md` used to claim the time-signature map
supported "per-section meter changes (between sections only)". The code refuses
all of them, so that page was **corrected in this same change** — it now records
the refusal and the projection framing. The stale claim is a small worked example
of the defect this design is about: prose that named a capability nobody built,
which every later reader took as done.)

---

## Per-stage exit criteria

Short by design; a checklist nobody reads is worse than none. Every one is
applicability-gated — read each as *"…for the dimensions this song depends on."*

**The criteria themselves live in
[`docs/song-workflow.md` → *Definitions of done*](../../docs/song-workflow.md#definitions-of-done)**,
which is the canonical copy. They are not restated here: this artifact and that
doc carried the table twice for one commit and the two had **already diverged**
on arrival — which is the same failure as the per-section-meter claim this work
had to go back and fix, and exactly what the repo's *link, don't summarize*
learning exists to stop.

What belongs here is the *design* reasoning behind the table, which the doc
does not carry:

- **Each stage's criterion reduces to one sentence** — *this stage owns no
  UNDECIDED row, and no row is DESCRIBED-BUT-UNBUILT.* The per-stage wording is
  that sentence specialized to what the stage can actually see.
- **Stages 5 and 7 are deliberately redundant with stage 3.** Stage 3 should
  catch a missing mechanism at authoring time; 5 catches it as a phase that
  pushed zero of something the brief requires (v1's push reported OK with zero
  envelopes), and 7 catches it as a gesture absent from the measurement. The gap
  that matters is the one that survives every stage, so the late nets are worth
  their cost.
- **Stage 8 (`/song-snapshot` + iterate) has no exit criterion by design** — it
  is the loop-back, not a stage with a downstream consumer to protect. It cannot
  emit a gap because it emits nothing; the next pass through stages 3–7
  re-applies their criteria.

---

## Worked example — the v2 prompt

Run on `~/angle-of-light/v2-prompt.md`, the owner's real next starting prompt.
That file also records the gaps the owner already knows are there, which makes
it the acceptance test.

**Relevance sweep.** Applicable and already DECIDED, so not asked: instrumental
(nothing implies vocals), the palette (rock kit, brass, timpani, industrial),
the energy arc (stated moment by moment), total length (45 s), drum style
(stated — expressive rock, timpani across the brass). NOT-APPLICABLE, recorded
silently: alternate tuning, loop-seamlessness, DJ/stem delivery.

**UNDECIDED — the consolidated turn (5 proposals, 2 statements):**

1. **Tempo — I'd propose 132.** 45 s at 132 is ~33 bars of 4/4 budget, which
   fits your eight moments with the 7/4 chorus bar at 3.2 s — long enough for the
   samba/rumba cross-rhythms to be *heard* rather than implied. Above ~144 the
   7/4 stops feeling relaxed; below ~120 the argument doesn't fit.
2. **Harmony — I'd propose D minor throughout, with the chorus arriving on D
   major.** Parallel-major arrival is the most legible "resolves tension" there
   is, and it costs no modulation. For the argument itself: the brass answers in
   D dorian against the rock's D aeolian — same tonic, different sixth — so the
   two are arguing harmonically as well as metrically, without a key change.
   The industrial bridge takes a chromatic descent.
3. **Production stance — I'd propose split, then converge.** Rock close-mic'd
   and tight; brass in a large hall, distant, long tail; the bridge with almost
   no reverb at all (the raw break you already named); the chorus in **one shared
   space**, because "integrated" has to be audible in the production or it is only
   audible in the score. The alternative is a unified production throughout with
   only the writing arguing — cleaner, less dramatic.
4. **What "integrated" means — I'd propose same material, reconciled.** The
   rock riff and the brass counter-line turn out to be one melody at two rates,
   and the 7/4 bar is what lets both fit without either bending. The alternative
   is new material both play — more triumphant, but it throws away the argument
   you spent the verse building.
5. **The 7/4 — full 7, or 4-then-3?** You said full-7 for the chorus; I'll take
   that. Same question for the verse alternation: is that genuinely alternating
   bars of 4 and 3, or one 7 felt as an argument? They groove differently.
6. **Statement, not a question — the budget.** At 132: intro 5 s · verse 14 s ·
   bridge (4× 5/8) 4.5 s · chorus 16 s · outro 5 s ≈ 44.5 s. Your intro asks for
   5–8 s and your bridge for "a few" 5/8 measures; two 5/8 bars is 2.3 s, which
   reads as a stumble rather than a section, so I've costed four. Say if you want
   the shape different and I'll re-cost.
7. **Statement, not a question — the octave drop.** "Pitch bends everything down
   an octave over a few seconds" will be a **Shifter on the master, ahead of the
   limiter, `Pitch Coarse` automated 0 → −12** across the outro's last bar —
   master so it catches the reverb tails and sends, pre-limiter so the shift
   doesn't re-introduce peaks past the ceiling.

**Against the gaps the v2 file names:** it lists five — harmony, tempo,
production style, what "integrated" means, and whether 7/4 is felt or literal.
The pass raises **all five**, and they are items 1–5.

It also raises **two the file does not name**: the section time budget (item 6 —
the v1 failure mode, caught by arithmetic) and the octave-drop mechanism (item 7
— *literally the v1 fatal bug*, and the reason the state model has a forbidden
fourth state at all). Item 7 is the proof the design does work the owner's
stated defect and not merely their stated gap list.

Seven items, five of which take a one-word reaction and two of which take none.

## Worked example — the sparse case

Prompt: *"an ambient soundscape, something to work to."* No rhythm, no sections,
no meter, no duration.

Relevance sweep: percussion → NOT-APPLICABLE (nothing implies it; **drum style
is never asked**). Meter → NOT-APPLICABLE (no metrical claim). Section time
budget → NOT-APPLICABLE (no duration and no sections stated). Named narrative
turns → NOT-APPLICABLE (none named). Tempo → NOT-APPLICABLE as a *groove*
decision; it survives only as an arbitrary pad-rate, which is cheap to revise,
so it is *shown* rather than asked.

What remains UNDECIDED and genuinely load-bearing: **one** — the harmonic
centre, because "something to work to" implies non-distracting, and whether that
means a static drone, a slow modal drift, or a loop of two chords is the whole
character of the piece and is expensive to reverse.

So the pass is **one proposal**: *"I'd propose a slow drift around a D pedal —
static enough to disappear behind work, moving enough not to feel like a stuck
note. Say if you'd rather it be genuinely static, or genuinely harmonic."* Plus
one shown inference: *"Going with ~4 minutes, no sections — say if you want it
longer."*

The remaining six dimension prompts are recorded NOT-APPLICABLE and **never
appear in the turn**. The design stays quiet.

---

## RECOMMENDATION — the CLAUDE.md amendment (not applied)

`CLAUDE.md`'s behavioural norms are owner-ratified, so this is proposed text
only — **and until it is ratified the design is inert for any agent that does
not open `/song-workflow`**, because CLAUDE.md is auto-loaded every session and
the skills are not. Tracked as **DOC-5H2T** so the request has a durable home
rather than living only in this artifact's prose (the repo has twice paid for a
deferral that lived in prose alone).

Why the current text doesn't already carry it: CLAUDE.md line 43 enumerates the
lifecycle as `/song-new → … → /mix-review` with "the two review checkpoints", so
an agent following it *correctly* starts at the scaffold. The pedagogical
carve-out does gesture at proposing rather than auto-deciding, but it is written
around *"an elementary musical choice"* mid-composition and names no stage,
artifact or bound — so it neither authorizes the opening turn nor limits it to
one. Ratifying the text below is what makes stage 0 reachable.

Add to **"Stop only on high-stakes decisions or must-answer questions"**, as a
third bullet in the stop list:

> - **The opening elicitation turn** — exactly one consolidated turn, at the
>   start of song work, proposing the load-bearing choices the prompt left open
>   (`/song-brief`). This is the pedagogical carve-out at the front of the work
>   rather than mid-composition, and it is bounded: **one turn, proposals not
>   questions, and nothing already stated is re-asked.** Under-specifying is the
>   user's prerogative; closing the gap is the stage's job. A stage may not emit
>   an unresolved gap — it decides it in-stage, or marks it explicitly open.
>   Where a directed prompt leaves no applicable open dimension, the turn is
>   skipped silently; this is never an excuse for a second turn.

And amend **"Creative product prompts vs planning prompts"**, replacing the
sentence *"Drive the workflow end-to-end (scaffold → compose → sound design →
mix → verify) before declaring done"* with:

> Drive the workflow end-to-end (**elicit** → scaffold → compose → sound design
> → mix → verify) before declaring done. The one place the drive-through pauses
> is the opening elicitation turn — see `/song-brief`. Each stage has a
> definition of done (`docs/song-workflow.md` → *Stage exit criteria*): a stage
> may not hand a load-bearing question downstream dressed as a decision.

---

## Deliberately not built

- **No lint, no build gate.** Aesthetic and completeness judgements never fail a
  build (`gate-verdict-policy.md`: BLOCKING is reserved for *likely errors*).
  Enforcement here is behavioural, plus the repo's Critic.
- **No schema for the ledger.** Prose in the brief, per the standing preference
  for LLM intelligence over deterministic structure. Promote to a typed field
  only if prose proves ambiguous in practice.
- **No fix to the meter refusal.** Owner-sequenced, above. Filed as **TMP-7B3X**
  (lift the policy refusal out of the mutator so the model can record what the
  song *is*); the projection half — how a declared meter map materializes in
  Live — stays with **TMP-4J6Q**.

### Split — the docstring test, not built here (TST-4M9P)

The **docstring test** is the one mechanically-checkable rule in this design,
and it is the one that would have caught v1 automatically. A narrow, honest
version: scan a song's `build.py` comments and docstrings for Live device names
present in `ableton://browser/*`, and assert each appears in
`captured_session.json` or the DB; likewise for the words *envelope* and
*automation* against the envelope tables. It is code plus tests plus a
false-positive budget, it needs its own build cycle, and shipping it half-done
would produce exactly the noisy gate this design argues against. Specified here,
deliberately deferred, and **filed as TST-4M9P** — its acceptance test is that,
run against the v1 song at `97816e1`, it flags the phantom Shifter.

What *did* ship as a mechanical check is narrower and different in kind:
`tests/unit/test_song_lifecycle_doc_parity.py` locks the lifecycle map and the
exit-criteria table against multi-site drift (every surface names stage 0; every
deep-link resolves; the table has exactly one home). That guards *this design's
own documentation*, not a song's prose — the two together are the reason the
"Deliberately not built" list above is shorter than it looks.
