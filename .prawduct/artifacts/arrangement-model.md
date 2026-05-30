# Arrangement Model — Hallucinote design foundation

**Status:** foundational. This is the durable design that governs how Hallucinote
represents song *arrangement* — the structure that makes a collection of parts a
*song that develops, varies, and tells a story over time*. Derived from a deep
design session (2026-05-30) that pressure-tested the model against Boléro,
anti-Boléro, 80s pop, Sinatra/Riddle, Aphex Twin, and Steve Reich, and from a
verified deep-research pass on what master arrangers across classical, jazz/pop,
and producer traditions actually do.

> **North star:** we are making *songs for the ages* — great art, not software,
> not sequences. Software is easy; great art is hard. Every primitive below
> exists to remove *bookkeeping* so all attention goes to the art. See memory
> `feedback_great_art_not_software`.

---

## The governing principle: Ruler, not Stamp

Every candidate capability is sorted by one test:

> **Does it remove BOOKKEEPING, or does it make a MUSICAL DECISION?**

- A **ruler** removes bookkeeping — note arithmetic, identity, ordering, presence,
  references, pure math. It hands back raw material and gets out of the way.
  (`chord_tones`, `apply_feel`, the variation ops below.) Rulers *free*.
- A **stamp** makes the musical decision — it returns a finished gesture or
  idiom-in-a-box. (`reggae_one_drop` — right only when you genuinely want that
  idiom as furniture.) Stamps *constrain*; they are poison when the thing being
  stamped *is* the art.

**The arrangement model is all rulers.** Hallucinote carries *identity, presence,
references, and arithmetic*; the composer (LLM) makes every *musical* decision —
what each motif is, what each layer plays, how a variation sounds, how a
recapitulation fuses. Helpers are **discovered from repeated mechanical friction,
never designed speculatively** — that is what keeps them rulers.

---

## Research foundation (verified)

A deep-research pass (20 sources, 25 claims adversarially verified, 21 confirmed)
found the conceptual primitives of arrangement to be **strikingly convergent**
from 250-year-old sonata form to modern pop/producer craft:

- **Sections are functional, not just labeled** — each has a narrative + energy
  *job* (intro builds mood · verse = same frame/changing content · prechorus =
  tension build · chorus = invariant hook/climax · bridge = contrast by
  reorchestration · outro = conclusion).
- **Energy is a staged, cumulative arc**, built by *adding and stripping
  orchestration layers over time* ("successive/horizontal orchestration").
- **The motif is the atom** — a compact, modular cluster, smaller than a melody,
  moved and transformed around the song. *Unity-vs-variety* (recognizable return
  + transformation) is THE mechanism for "same but evolved."
- **Variation operations are a small canonical set**: transposition, inversion,
  retrograde, augmentation, diminution, fragmentation. (A competing 7-op list was
  refuted 0-3; use these six.)
- **Recapitulation is the payoff primitive** — earlier material returns *fused or
  resolved* (sonata restates the 2nd theme in the home key; pop lifts the final
  chorus up a step).

**Refinements forced by the killed claims** (these matter):
1. Sparse→dense is a *tendency, not a rule* — **subtraction matters as much as
   addition** (the "withhold until final chorus" absolutism was refuted 1-2).
2. Contrast is *one* engagement lever, not the master lever (refuted 0-3).
3. Post-1990s songs often *drop* energy into the chorus (Nobile) — so **energy
   direction must be authored per-transition, never implied by section type.**

**Honest caveat:** the named-practitioner attributions (Riddle, Quincy, Martin,
Beato) did *not* survive verification — they collapsed into generic role
definitions. The model rests on durable theory + well-corroborated craft, not
"X said Y." A targeted practitioner pass is open work, not a dependency.

---

## The primitives

All are **rulers**. The composer authors the music; these carry the structure.

| Primitive | What Hallucinote holds (ruler) | What the composer authors (art) |
|---|---|---|
| **Section** | name, function, bar-range, authored *energy* + *direction*, character/genre | what the section *is* |
| **Recurrence** | "same section, instance N" + a **delta** | what changes each pass |
| **Layer** | which part-roles are *present* in an instance; `(part, instrument/timbre, register)` | what each layer *plays* |
| **Motif** | a named, referenceable atom, independent of any section | the motif itself |
| **Variation op** | the canonical six as pure-math functions, applied at *any* scope (motif / layer / whole instance) | whether & where to apply |
| **Reference / recap** | a link: "this section quotes/develops that motif" | how the fusion sounds |
| **Energy curve** | an authored per-section/transition scalar + direction | the actual intensity intent |

### Cumulative development = per-iteration deltas

The heart of the original question ("how do verse 1/2/3 stay the same yet
differ?") is answered: a recurring section is **one identity + a delta per
instance** — never independent clips. Deltas are **multi-axis and bidirectional**:

- add / **strip** a layer (orchestration)
- swap **timbre/instrument** on a layer (reorchestration — Boléro, Riddle)
- shift **register / octave**
- **rhythmic intensification** (denser subdivision, fills)
- add a **counter-melody** layer
- **time / phase offset** on a layer (Reich phasing; connects to
  `feedback_microtiming_is_authorship`)
- **note-add** to a cell (Reich additive process)

"Verse 1 stripped → verse 2 → verse 3 full" is layer-presence deltas; "metal
time, reggae instrumentation" is a timbre delta; the integrating final chorus is
a motif **reference** + multi-scope `transpose`.

---

## The derivative question — curve is the model, derivative is a lens

Musical *motion* is felt as derivatives: rising = tension, falling = release,
accelerating = intensifying, sudden = jerk. This is true and worth honoring — but
**derivatives are a lens we look through, not a cage we author inside.** The
decision (2026-05-30):

- **Store the curve / delta-sequence; never store velocity/acceleration/jerk as
  separate authored dimensions.** They are computable off the curve (a ruler),
  and storing them invites authoring an *inconsistent* triple. One source of
  truth.
- **Not across all dimensions.** Expressive derivative-content concentrates on
  energy/density. A uniform v/a/jerk engine across register, pan, brightness… is
  machinery that sits unused — the overcomplication tell.
- **Discontinuity is first-class — and a derivative model fights it.** The best
  moves (the half-time→double-time gear-shift, the drop, the reggae↔metal
  whiplash) are *discontinuities* where jerk is infinite. A v/a/jerk-based model
  is biased toward smoothness and would push every transition toward a graceful
  ramp — exactly wrong for a song whose thesis is the violent cut. **We must be
  able to cut to black at full speed.**
- **Where derivatives earn a place — as a ruler and a lens, optional, read-side:**
  (a) an *intent vocabulary* for authoring the energy/density curve (`build`,
  `accelerate`, `plateau`, `drop`, `ease`) that compiles to a curve the composer
  then owns; (b) an *analysis lens* — the arrangement review reports the curve's
  derivative shape and coaches it against arranger craft ("your build is linear;
  the masters accelerate into the chorus"), same shape as the masking analyzer.

---

## Pressure test — where it holds, where it strains

The model **held in every case**, because it degrades gracefully to the raw
`_note` floor. Value is proportional to how much *reusable structure* the music
has.

| Tradition | Result | What it taught |
|---|---|---|
| **Boléro** | holds (purest recurrence-delta) | Layer must carry timbre; reorchestration = timbre delta |
| **Anti-Boléro** | holds | deltas must be bidirectional (strip, not just add) |
| **80s bubblegum** | holds (home case) | variation ops compose at *section-instance* scope (final-chorus key lift) |
| **Sinatra / Riddle** | holds | antiphony/interlock is *authored, not modeled* (would be a stamp) |
| **Aphex Twin** | strains | scaffold must be **optional**, degrade to note floor for continuous-morph; sound-design is the *instrument-chain* subsystem, not arrangement |
| **Steve Reich** | holds (after refinement) | deltas include **time/phase offset** and **note-add**; the *process* stays authored |

### What is deliberately NOT modeled (and why)

- **Inter-layer interlock** (call-and-response, antiphony) — the gesture is art;
  I author where the answer lands.
- **Processes** (phasing rules, generative/algorithmic evolution) — would be a
  stamp; the composer is the generative intelligence. Phasing = recurrence with
  an evolving time-offset delta.
- **Texture-mass / micropolyphony** (Ligeti clouds, Xenakis) — the unit is a
  mass, not a motif; author as raw notes.
- **Aleatoric / chance** — Hallucinote models *deliberate* arrangement.
- **Sound design / timbre-granular** — belongs to the instrument/device-chain
  subsystem (see `feedback_sound_is_composition`), not arrangement.

The bedrock is always raw note placement (`_note(pitch, start, dur, vel)`); the
arrangement scaffold sits **on top** as optional, composable sugar — never the
only path.

---

## Known gaps surfaced in review (2026-05-30)

A counter-example review found the model strong but with two honest gaps the
original pressure test missed (backlogged for decision):

- **Harmony/key is a second structural axis — and it's unmodeled.** The model's
  only structural curve is *energy*. But functional-tonal music (sonata, jazz
  changes, blues, most pop) is driven by *harmonic* tension/resolution —
  tonic↔dominant, modulation, the recap landing home. The model can author the
  notes but can't carry "this section is in the dominant, resolved at the recap"
  AS STRUCTURE; it's blind to the thing doing the dramatic work. This is the
  highest-priority gap: a real decision — **harmony as a modeled substrate (a
  harmonic axis co-equal to energy: key / mode / function per section, composer
  still authors the notes, a read-side lens verifies them) vs. harmony stays in
  the notes.** → `backlog ARR-1H9C`.
- **Counterpoint's vertical constraint is unmodeled (a near-miss).** Fugue maps
  beautifully *horizontally* (subject=motif, answer=transpose, stretto=overlapping
  references, augment/invert=ops) but the model represents nothing about whether
  layers form valid counterpoint *when combined*. The ruler-consistent fix is a
  read-side consonance lens, not a generator. → `backlog ARR-4V7P`.

The three boundaries above ("deliberately NOT modeled") are tracked in
`backlog ARR-2B6K`; #3 (process/non-musical-axis) stays out by design.

## Where it lives

**Build-time first.** A `hallucinote.arrangement` Python module (Section,
Recurrence/delta, Layer, Motif, Reference) + the six variation ops as rulers in
`generators.primitives`. It composes notes and emits the *same* DB rows
(clips, sections, placements, notes) through the existing mutators — no schema
change. The composer authors variations; the module carries identity/presence/
references/arithmetic.

**DB promotion is deferred — deliberately.** The *concepts* are 250-year-stable,
but the *representation granularity* (how a layer maps to clips, whether energy
is stored or derived, delta encoding) is unsettled — the research itself flagged
this. We discover the shape from this song's friction, then crystallize the
proven shape into DB columns (`blueprint` / `derived_from` / `variation_tag` /
section `function`+`energy`) as a phase-2 once it has earned its schema. This
serves the cross-song-reuse + event-store goals (`project_cross_song_reuse`,
`architecture_db`) without guessing.

**Energy is authored, not derived** — an intensity *intent* the composer attaches
(guiding which layers are present), with direction explicit per transition.

---

## First demonstration: sun-zone-done

This song is the forcing function for the capability — the same role it played
for the reggae/metal generators. The narrative arc (mostly-reggae punctuated by
short metal → a convention-break that swaps time-feel and instrumentation → an
integrating final chorus that fuses both worlds + polyrhythm callback → an
enlightenment outro) exercises every primitive: recurrence-deltas (verses),
timbre deltas (the break), motif + reference (the integration), the optional
note-floor (the hand-authored polyrhythm motif), and authored energy with a
deliberate *discontinuity* at every genre flip. See `build-plan.md`.
