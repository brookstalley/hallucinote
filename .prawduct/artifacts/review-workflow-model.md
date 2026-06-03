# Review-Workflow Model — one axis per turn, configured per song

**Status:** decided + wired (2026-06-03). **Backlog:** REV-2W8K. **Related:**
`intent-architecture.md` (the RECALL→INTERPRET-vs-intent→question loop both review
skills share), `intent-collaboration-model.md` (the register model),
`gate-verdict-policy.md` + `generator-altitude-policy.md` (the sibling ruler-not-
stamp policies). **Principles:** `feedback_great_art_not_software` (the workflow
guides, never makes the musical decision), one-source-of-truth, both-sides,
discovered-from-friction.

## The problem

Today review is ad-hoc: "listen to the whole song and react," or "ask about one
section." Both review ALL concerns at once — arrangement + sound + harmony +
performance + mix — which is exactly what produces **tail-chasing**: fixing
harmony invalidates the mix; re-arranging wastes the sound pass; a fader move
papers over an arrangement problem. Raised by the user (2026-06-01), verbatim:

> *"Let's find a more structured way to review parts of the song rather than just
> ad hoc 'listen to whole song and give feedback'… Music is so complex that it's
> easy to chase our tails across arrangement, production, harmony, instrumentation."*
> *"bring workflow into the framework, using our typical abstractions so we don't
> try to cram every song and every collaboration into the SAME workflow — we are
> just intentional about the workflow for any particular song."*

## The three review axes (research-backed; sources cited)

World-class producers organize review along three axes; the discipline is choosing
ONE deliberately per turn:

1. **Concern-ordered passes** — the dominant engineering tradition: songwriting →
   arrangement → sound/production → performance/comp → mix → master, each stage
   *enhancing*, not redoing, the prior. "You'll never get a great mix of a song
   with a poor arrangement." The stated reason is **rework cost** — fixing
   arrangement during mixing forces re-architecting and often loses the vibe.
   ([LANDR](https://blog.landr.com/hard-truths-arrangement/),
   [iZotope](https://www.izotope.com/en/learn/mixing-while-producing-music-good-or-bad-idea.html))
2. **Element-at-a-time (subtractive)** — Rubin's "I'm not a producer, I'm a
   reducer": remove until the identity is *challenged*, then stop; the removal is
   the diagnostic. Finneas: carve space around the protected lead.
   ([Melodics](https://melodics.com/blog/how-to-produce-like-rick-rubin))
3. **Section-at-a-time (structural)** — Nashville Number System + film-scoring
   **spotting sessions**: chart the structure, fix where each section acts and its
   emotional job against a temp/reference, BEFORE committing parts.
   ([Sweetwater](https://www.sweetwater.com/insync/the-nashville-number-system-demystified/),
   [Packt: spotting session](https://subscription.packtpub.com/book/business-and-other/9781837636891/2/ch02lvl1sec05/what-is-a-spotting-session))

## The load-bearing rule: ONE review axis per turn

A `/compose-review` or `/mix-review` pass **declares its axis and is forbidden to
EDIT the others.** This single constraint converts ad-hoc "react to everything"
into stage-gated discipline. Specifics:

- **Read holistically, act on one axis.** The analysis may reason across all
  metrics/sections (that holistic read is the point) — but the EDITS a single turn
  proposes/makes stay on the declared axis. A finding on a *different* axis is
  NOTED for a later pass (learn-back as a deferred review note), never fixed now.
- **Feedback stays question-not-verdict against declared intent** (the existing
  posture of both skills — Quincy's "director frame," the spotting "score the
  subtext"). The workflow is a ruler: it guides the order of attention, it never
  makes the musical decision.

### Which skill owns which axes

| Axis | Owned by | Read surface |
|---|---|---|
| arrangement (layering / density / contrast / energy arc) | `/compose-review` | build.py + arrangement |
| harmony (progression realization, conformance) | `/compose-review` | `theory.lint` |
| melody / line (contour, intervals, harmony-fit) | `/compose-review` | `melody.lens` / `tools/melody_lens.py` |
| sound / production (timbre, device chains) | `/mix-review` | by ear + the chain |
| performance / feel (timing, dynamics, groove) | `/mix-review` | `performance.lens` + audio `timing` |
| mix-balance (masking, loudness, attribution, reverb) | `/mix-review` | the MixReport |

A turn picks ONE row, from the song's archetype order.

## The per-song archetypes (the config — don't force one workflow)

A song declares a **`review_workflow` archetype** as `scope: song` intent (the
markdown-intent home); the review skills read it and follow its axis order. Start
with the five the research names; add one only when a real song needs it
(discovered-from-friction):

- **A. Ordered-Pass / Band-Song** (pop / rock / singer-songwriter): strict
  arrangement → sound → performance → mix gates. **The default** — lowest rework.
- **B. Sound-First / Electronic-Beat**: *rejects* the ordered model — sound design
  IS the compositional event, so sound + arrangement are reviewed together and
  "mix-while-producing" is sanctioned (Timbaland; iZotope's electronic carve-out).
- **C. Subtractive / Through-Composed Art Piece**: build dense, then run Rubin
  passes element-at-a-time ("remove until the identity is challenged"). *(sun-zone-
  done lives here.)*
- **D. Spotting-Gate / Cinematic-Narrative**: function-first — fix where + why each
  section acts against a temp reference, THEN check realization section by section.
- **E. Charting / Number-System**: review structure on a key-independent section
  chart first; lock nothing instrument-level until the chart is approved
  (structure-volatile collaborations).

## Adversarial caveat (don't ship received wisdom)

"Arrangement before mix" is a **default with documented exceptions, NOT a law** —
archetypes B and C exist because the sources themselves dissent (the layers inform
each other; the rule is "don't let the mix do the arrangement's job," not "never
touch a fader while arranging"). Encode it as Hallucinote's default, not its only
mode. The archetype is the song's declared exception-or-default; the skills honor
it rather than imposing the ordered pass everywhere.

## How it's wired (both-sides)

- **Config surface:** a per-song `review_workflow` annotation (`scope: song`,
  `tags: [review-workflow, <archetype-letter>]`) names the archetype + axis order.
  sun-zone-done declares **C — Subtractive** (`annotations/review-workflow.md`).
- **The skills that read it:** `/compose-review` and `/mix-review` each gained a
  RECALL sub-step ("read the review_workflow archetype; default to A if absent")
  and a "One axis per turn" section enforcing the declared axis + deferring
  cross-axis findings.

## Default + extension

No annotation → archetype **A** (and say so). A song that needs a workflow the five
don't cover gets a new archetype added HERE first (with its axis order + the
friction that forced it), then declared on the song — never improvised per-song.
