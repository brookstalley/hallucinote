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

## The dimension taxonomy — structure intents · realization layers · subsystems

> Added 2026-05-30 after a verified deep-research pass on expressive-performance
> modeling (Cancino-Chacón/Widmer 2018 canonical review; KTH/Director Musices;
> the Performance Worm — Dixon/Goebl/Widmer 2002; Palmer 1997; Hennig et al. 2011
> on 1/f timing; Iyer 2002; Danielsen 2023). Answers "what dimensions does a song
> have, and how do we add them without sprawling into 1000 axes?" See `backlog
> ARR-8P5K`.

A song's dimensions are **not a flat list of orthogonal axes**. They sort into
three kinds, and knowing which kind a candidate is tells you how to model it:

1. **Authored structure intents** — the song's *bones*: deliberate, largely-
   orthogonal decisions the composer authors. Today: **form/sections**, **energy**
   (the intensity intent), **harmony** (key/mode/progression). Candidate:
   **meter-feel**, which on inspection (ARR-4M3T, 2026-06-02) is **two
   sub-dimensions**: (i) **felt pulse level** — half/double-time, compound, clave,
   hemiola; the felt subdivision, *distinct from* time-signature and tempo (the
   half→double-time gear-shift is already a first-class *discontinuity* — see the
   derivative section); and (ii) **literal meter / time-signature** — the metric
   grid's shape per section/bar (5/4, 7/8, a borrowed 3/4 bar that shortens the
   song). Both stay **candidates** (not built): promote (ii) to a built structure
   intent — carried on the arrangement beside energy/harmony, with `plan()` placing
   non-4/4 sections beat-accurately and the read-side lenses becoming meter-aware —
   when a **second** odd-meter song forces it, OR when the user accepts the literal
   steal's blast radius (every absolute-beat consumer) over the shipped
   length-preserving **early-slam** interim (recorded in the ARR-4M3T backlog entry,
   the source of truth for its shipped status). swing stays ∈ performance; the
   metric grid ∈ meter-feel(ii). Each is a ruler + (ideally) a read-side lens.
2. **Realization layers** — *how the bones are rendered*. **Derived from** the
   structure intents (+ a genre profile + deliberate overrides), NOT authored as
   competing dials. **Performance** (microtiming, dynamics, articulation) is the
   first member. **This category is the answer to "no 1000 axes": a realization
   layer reads the structure intents; it does not add a new one.**
3. **Subsystems** — separate concerns with their own model. Today: **sound-design /
   instrument-chains** (`feedback_sound_is_composition`). Candidate: **text / lyric
   / prosody / flow** (the primary art for rap, chant, art-song — its own subsystem,
   not an arrangement axis).

Underneath all three is the raw **note floor** (`_note(pitch, start, dur, vel)`),
which every layer degrades to.

**Both-sides status (2026-06-03).** The structure-intent MEASURE halves are being
realized by named siblings — exactly as *"a dimension authored but unmeasured is
half-built"* predicts: **energy** by **ARR-7M3D** (declared `energy_curve` vs rendered
intensity — Spearman ρ + inversions), **recurrence/form** by **ARR-9K4T**
(cross-instrument motif-recall + recapitulation read), with **harmony** (ARR-1H9C
conformance lint) and **performance** (the perf lens) the shipped precedents. Each is a
*lens* — it reports declared-vs-realized divergence as info/coaching, never a stamp or a
verdict the composer didn't ask for. (Links to the siblings' designs; not restated here.)

**Coherence pass 2026-08-11 (ARR-8P5K, the recurring guard).** Re-run against
the siblings that landed since the 2026-06-03 pass. Two findings, both recorded
rather than built — the umbrella still owes no code:

- **Spatial image is a shipped lens for a dimension this taxonomy never names.**
  STR-4C8N (v1.8.0) added per-stem/per-section L/R correlation + mono-sum loss
  and a stereo reading in `/mix-review`. "Stereo" appears nowhere above. Placed
  now: it is **not** a structure intent (nobody authors a spatial curve) but part
  of the **sound-design subsystem** — width and placement are dialled in the
  device chain, which is where `feedback_sound_is_composition` already puts them.
  Its read side belongs to the mix lenses, beside masking.
- **And it is in the half-built state this doc warns about.** The MEASURE half
  shipped with no authoring intent: `DeclaredWidthControl` is a *readback of a
  dialled device parameter*, not a declared spatial intent, so there is nothing
  for the lens to grade the song against — only "here is what the audio did".
  By this doc's own both-sides rule (*"a dimension measured but un-authorable is
  half-built"*) spatial image is currently half-built. The authoring/graded half
  is **STR-9P4M**, deliberately gated: it grades taste, so the analyzer freeze
  binds it until the listening day (QLT-3D8R). This is a known, dated gap, not
  an oversight — naming it is the guard's whole job.

**The rule for adding any new lens (2026-08-10 owner ruling).** The analyzer
freeze is no longer a blanket "no new lenses": it is **no new lens that GRADES
or COACHES**. A determinate physical measurement that emits no findings and no
grades — correlation, mono-sum loss in dB — is outside it; a lens whose
thresholds encode taste is inside it and waits for the listening day. Read that
before adding a read side to any dimension here.

A fourth relationship exists: a **composite line that reads the other dimensions**.
**Melody** is the case (decided 2026-05-31) — not an orthogonal structure intent
with universal rules, and not a derived realization, but a *line* whose PITCH reads
**harmony** and whose RHYTHM reads the **feel/performance** layer, while it owns
the **contour + motivic shape** neither substrate carries. See the subsection below
and [`melody-model.md`](melody-model.md).

### Performance — the first realization layer (decided 2026-05-30)

> **Full spec, verified research foundation (with citations), the measurement-lens
> design, and the phased delivery plan: [`performance-model.md`](performance-model.md).**
> The summary below is the integrated framing; that artifact is the owner doc.

Performance is the gap between the *score* (which notes) and the *rendition* (how
they are played). The decision:

- **Profile → realization (the KTH "metaperformer" pattern).** The composer/LLM
  *declares a performance profile*; a deterministic layer *computes* the per-note
  deviations. Declared intent (WHAT) vs computed execution (HOW) — a **ruler**, not
  a humanize-stamp. (Director Musices: a global magnitude `k` (default 1) scales
  each rule; "the user acts as a metaperformer … leaving execution to the computer.")
- **A derived realization layer, NOT a peer axis.** Performance **reads** the
  structure intents; it does not duplicate them. Its macro intensity (push /
  tighten / crescendo) is **derived from the `energy` curve** — the Performance Worm
  is literally a 2-D tempo×loudness trajectory, "a direct analogue to an energy
  curve." Dynamics may read harmonic tension. **One source of truth: intensity is
  authored once, as energy; performance renders it** (the "score-energy vs
  performance-energy" coupling — one intent, two channels).
- **Profile components:** (a) a **genre groove-baseline** — named, energy-
  INDEPENDENT (reggae drag, jazz swing, funk pocket, straight, rubato; feel is
  genre-specific and inseparable from sound — Iyer 2002, Danielsen 2023); (b) the
  **energy/harmony coupling** (derived, not authored); (c) **deliberate overrides**
  — decouple where the art demands (the convention-break is the template).
- **Realization is STRUCTURED, not random.** Human timing is **1/f long-range-
  correlated, NOT white noise** — listeners prefer 1/f over white at matched
  magnitude and judge it *more precise* (Hennig et al. 2011). So: deterministic
  structured deviations (genre profile + phrase-arch from structure) **plus** a
  small, separate, **correlated (1/f)** noise supplement (the GERM model's additive
  Random term) — **never white-noise jitter** (the discredited "humanize" default).
  Magnitude **small and genre-calibrated, not maximized** (exaggerated microtiming
  *lowers* groove — Madison 2011, Senn 2016).
- **Two grains, one parameter set:** per-note deviations (discrete parts — drums,
  bass, riffs, rap onsets) AND continuous curves (sustained / legato / rubato).
- **Both sides (mandatory).** AUTHOR = the profile above. MEASURE = a performance
  lens: **symbolic-primary** (per-part deviation *structure* + the 1/f-correlation
  metric + flat-dynamics detection, build-time on the DB notes, beside the harmony
  conformance lint) **+ audio ground-truth** (the existing `audio/timing.py` +
  `cross_rhythm.py` — already do swing/phase/structured-vs-jitter — extended with
  the 1/f metric + perceived-onset). It grades **mechanical / human / sloppy**
  against the declared profile + the energy-coupling. *A dimension authored but
  unmeasured is half-built.* **MEASURE side SHIPPED (phase 2a):** the symbolic
  lens is `src/hallucinote/performance/` (lens + correlation + dynamics + ensemble),
  wired into `/mix-review`; see [`performance-model.md`](performance-model.md) §7.
  **AUTHOR side — first primitive SHIPPED (phase 2b):** `performance.realization`
  (`PerformanceProfile` + `apply_profile`) realizes the declared profile's additive
  **1/f breathing**, closing the loop — a mechanical part run through it reads
  *human* by the very lens above. So the dimension is now *both measured AND (first-
  cut) authorable*: a composer can declare a profile and make a part human, not just
  diagnose that it isn't. **Still half-built on purpose:** the profile's *declared
  genre-baseline field* + the energy-coupling, and the lens grading against a
  *declared* profile (today it reads what was authored, not what was declared) —
  friction-driven follow-ons, tracked (ARR-8P5K (b)–(d)).
- **swing vs meter (the boundary):** swing is a *performance* microtiming parameter
  (it deviates *from* the grid); the metric grid it deviates from is *meter-feel(ii)*,
  the literal-meter sub-dimension (a candidate structure intent — see the two-sub-dim
  split in the taxonomy above). Clean split.

### SCOPE BOUNDARY — performance is METERED-only (a documented limitation, not a flaw)

Every foundational performance model (KTH, the Performance Worm, basis-function
models, ASAP-style datasets) measures deviation **against a metric grid**.
**Gregorian chant (unmetered), free rubato, and rap-flow (speech-rhythm) have no
fixed grid to deviate from** — *"a single 'offset from the grid' time model does
NOT cleanly span metered and unmetered music"* (the research's central caveat). The
score-vs-performance split survives if recast as *conceptual-plan vs realization*,
but the **time base** must fork (grid-relative for metered; absolute-time +
reference-pulse or onset-sequence for free) under the same expression parameters.

**Decision: metered-first.** Hallucinote's performance layer covers metered music
(reggae, metal, jazz/swing, funk/Motown, most pop, rap-on-a-grid). **Unmetered /
free-time performance is out of current scope — a known, documented limitation, NOT
a defect.** Users should understand: *performance/feel authoring is grid-relative;
truly unmetered traditions degrade gracefully to the raw note floor.* The free-time
model is **future research** — forked when chant / free-rubato actually forces it
(discovered-from-friction). Mirrored in `project-state.yaml` `scope.later`; see
`backlog ARR-2B6K` (unmetered boundary) + `ARR-8P5K` (the axis investigation).

### Melody — the line layer (decided 2026-05-31)

> **Full spec, two verified research passes (45 confirmed claims), the both-sides
> measurement design, and the phased plan: [`melody-model.md`](melody-model.md).**
> The summary below is the integrated framing; that artifact is the owner doc.

Melody is the line a listener carries home — and the dimension where a machine most
easily produces the *plausible-but-dead* (in-key, in-rhythm, forgettable). The
decision:

- **No universal "good melody" function — substrate + profile, measured against
  intent.** The research is decisive: there are **no absolute melodic universals,
  only statistical ones** (Savage et al. 2015); contour **does not cluster into
  discrete types** and the "melodic arch" is **style-specific** (Chinese folksong
  averages descend); the pitch-vs-rhythm complexity balance is a **style
  specialization**. So a melody model is a small genre-GENERAL **substrate**
  (proximity/small intervals, small alphabet, harmonic anchoring, the *existence*
  of contour + economy) + a declared per-song **profile** (contour intent, range,
  step↔leap appetite, harmonic freedom, repetition appetite) → the lens grades the
  line **against its own declared intent** and **learns it back per-song**, never a
  universal verdict. This **is the metaperformer pattern again** (same as
  performance's genre groove-baseline) — and the user's mandate framing.
- **A line that reads the substrates, not a peer axis.** PITCH reads **harmony**
  (empirically coupled — tonal hierarchy at strong beats, stepwise non-chord-tone
  resolution by anchoring, tension as pitch-space distance; modest, statistical,
  classical-bound). RHYTHM reads the **feel/performance** layer. CONTOUR + motivic
  shape are melody's own. One source of truth: the line does not re-declare chords
  or groove — it reads `theory` + `performance`.
- **The organizing principle is EXPECTATION** (information content — surprisal/
  entropy; Pearce/IDyOM), the genre-general spine separating *shaped* from *random
  walk* from *mechanical drone*. As with performance's 1/f, the theory is the north
  star but the lens ships **cheap corpus-free proxies** (proximity, alphabet size,
  contour structure, within-line repetition, harmony-fit) — no trained model, no ML.
- **Both sides (mandatory), read-side first.** AUTHOR = the declared melodic
  profile (no `melody()` generator — inventing the line is the art, ruler-not-stamp).
  MEASURE = a symbolic melody lens (`src/hallucinote/melody/`) beside the harmony
  conformance lint + performance lens — contour, intervallic/leap profile, range,
  motivic economy, and harmony-fit against the `Progression`. *A dimension authored
  but unmeasured is half-built.* **Status: research + model artifact + READ-SIDE
  LENS shipped** (`src/hallucinote/melody/` — `lens`+`contour`+`intervals`+
  `harmony_fit`, 27 tests, validated on sun-zone-done's two hooks; classifies
  `active`/`static`, the shaped-vs-aimless verdict deferred to the profile-relative
  phase 2b). Next: the declared melodic-profile authoring surface + grading.
- **Motivic economy — two distinct reads, one boundary (ARR-8P5K).** *Line-level*
  motivic economy (does a single line reuse its own cells?) is the **melody lens**'s
  (MEL-1A7K, within-line repetition). *Cross-instrument* recurrence/recapitulation (is
  the song built from a shared recurring cell-set across instruments — which registered
  motif recurs where, and as which variation?) is the **arrangement-level recurrence
  read**'s (ARR-9K4T). One source of truth: the two reads never both claim the same
  verdict.

### SCOPE BOUNDARY — melody is pitched-discrete-monophonic-line-only

The melody layer models **pitched, discrete-onset monophonic lines** (a hummable
line, a riff, a vocal hook) — the unit the discrete-pitch/small-alphabet substrate
and single-line anchoring model actually describe. Dense polyphony / texture-mass
(the unit is a mass, not a line — inter-line counterpoint is the separate
vertical-consonance lens, ARR-4V7P), pitch-continuous / microtonal lines, and
unmetered/free-time rhythm all **degrade to the raw note floor**. A documented
limitation, not a flaw. See `melody-model.md` §6.

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

**Recurrence READ side (ARR-9K4T).** The recurrence/recap dimension now has a
read-side ruler: a build-time symbolic lens (`hallucinote.recurrence`, surfaced via
`hallucinote.tools.recurrence_lens` to `/compose-review`) reports which *registered*
motifs recur where and as which variation, plus a motivic-economy summary — parallel
to the harmony conformance lint / melody lens / performance lens, closing the
both-sides gap for recurrence. It is **detect-only** (DR-1 Option A): it infers
recalls from the realized section layers, so the **author-side "Reference / recap"
link above remains documented-but-unbuilt** — `Arrangement` has no `reference()`
method yet (the authored-link half is the tracked deferred work, ARR-9K4T Chunk 5).
See the lens for the method; info-only, never a verdict (ruler-not-stamp).

Detection and *counting* are separate: the matcher reports every reading it finds,
including the tier-4 `derived (<op>, <coverage>)` partial account it falls back to
when no clean op is recoverable, but a sub-threshold derived reading is marked
`partial` and excluded from the economy figures. Without that split the transform
group's near-universal low-coverage readings make every registered motif read as
recurring, which empties `never_recalled` and silences the lens's only coaching
question. The floor (`analyze_recurrence(min_coverage=…)`) applies to the derived
tier alone — a clean recovered op, `fragment` included, is a recall at any coverage.

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

The energy curve now also has an **audio-realization lens** (ARR-7M3D):
`MixReport.energy_realization` reports per-correlate Spearman ρ of declared
`energy_curve` rank vs measured per-section intensity (LUFS-S + onset density)
and names rank inversions — parallel to the harmonic-conformance lint and the
performance lens, closing energy's BOTH-SIDES MEASURE half.
The lens is a ruler: it reports ranked intensity vs intent and never re-authors
the curve. See `src/hallucinote/audio/energy.py` for the method.

**DECIDED 2026-08-11 (ARR-2S9D): two correlates suffice; the spectral one stays
unbuilt.** The music-perception literature backs a third intensity correlate —
spectral density / flux / centroid, since a chorus often "opens up" the spectrum
at matched loudness, which LUFS alone cannot see (ARR-7M3D `research.md`
§2/§4) — and `realize_energy` is correlate-agnostic (it ranks whatever
`measured` supplies, and `correlate_rho` is open-keyed), so the build is small.
It is deliberately not built, for two reasons that both have to change first:

1. **Discovered-from-friction, and no friction has been recorded.** The
   governing rule for this correlate was set when it was deferred: ship
   loudness + density, add the spectral one *when a real case shows the two
   miss it*. No such case has been logged. Building it now is the speculative
   pre-build that rule exists to prevent.
2. **It is not the neutral measurement it looks like.** The 2026-08-10 owner
   ruling narrowed the analyzer freeze from "no new lenses" to **no new lens
   that GRADES or COACHES** — a determinate physical number carrying no
   threshold is outside it. Spearman ρ is determinate, but *which* spectral
   measure (flux vs centroid vs flatness) and how it is windowed are taste-laden
   choices, and the ρ lands in `/mix-review`'s coaching read of whether a
   section lifts. So this sits inside the freeze, and the listening day
   (QLT-3D8R) is still owed.

**What flips this:** a logged case where a section's declared energy rises, both
loudness and onset density read flat, and the ear says it lifted. That is the
friction the rule waits for — and by then the listening day should have
calibrated the surrounding thresholds anyway.

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
- **Unmetered / free-time *performance* feel** (chant, free rubato, rap-flow) — the
  performance realization layer is grid-relative (metered-only) by design; see the
  dimension-taxonomy SCOPE BOUNDARY above. A documented limitation, not a flaw;
  these degrade to the note floor. (`backlog ARR-2B6K` / `ARR-8P5K`.)

The bedrock is always raw note placement (`_note(pitch, start, dur, vel)`); the
arrangement scaffold sits **on top** as optional, composable sugar — never the
only path.

---

## Known gaps surfaced in review (2026-05-30)

A counter-example review found the model strong but with two honest gaps the
original pressure test missed. The first (the harmony axis) has since been
**resolved and built** (Chunks A–E, branch `feature/harmonic-substrate`); the
second (the vertical/counterpoint constraint) remains open.

- **Harmony/key as a structural axis — RESOLVED: harmony is a modeled substrate.**
  *Decision (2026-05-30):* harmony is a first-class axis co-equal to energy, not
  left in the notes. A per-section key/mode *label* alone would not have prevented
  the one-chord drone — a composer can still pedal the tonic under an "E Dorian"
  tag — so the substrate carries an authored **chord progression with harmonic
  rhythm** that the parts compose against, plus a **build-time conformance lens**
  that NAMES "declares movement but the parts play only the tonic" (harmonic
  stasis) as the realization bug-shape. *(Originally this lens FAILED the build;
  per LNT-1V9K it now surfaces stasis as a loud WARNING and never blocks — a
  ruler, not a stamp — and the song's own test gates the regression via
  `report.stasis_sections`. See `gate-verdict-policy.md`.)* *Built:*
  `hallucinote.theory` (`Chord` — slash
  bass, polymodal `split`, free-form function labels; `Mode`; `Progression` — an
  authored harmonic-rhythm timeline, functional/modal toggle); chord-aware
  generators (skank, bass, power chords, organ bubble) that *voice* a progression;
  `transpose_diatonic` (the key-aware variation op — `transpose` stayed key-blind);
  and the `Arrangement` carrying per-section `progression` + a read-side
  `harmonic_curve` parallel to `energy_curve`. *Bias:* sophistication is the
  default (functional harmony, modal harmony, AND legitimate stasis/minimalism all
  first-class; simple I–IV–V is a supported fallback, never the default) — but
  "default to sophisticated" lives in the model's vocabulary, the conventions/
  skills, and a read-side coaching lens ("static drone — minimalist intent, or an
  unrealized opportunity? the masters reharmonize the repeat"), never baked into a
  ruler (an auto-passing-chord inserter would be a stamp). The composer still
  authors every note. *Demonstrated by* sun-zone-done's 184-bar through-composed
  arc (modes flipping E Dorian↔Phrygian over a constant E, resolving into a
  polymodal both-at-once fusion). *Deferred:* DB-promotion of the harmony axis
  (in-memory today, like `function`/`energy`); the VERTICAL constraint below.
  → `backlog ARR-1H9C` (resolved).
- **Counterpoint's vertical constraint is unmodeled (a near-miss) — STILL OPEN.**
  Fugue maps beautifully *horizontally* (subject=motif, answer=transpose,
  stretto=overlapping references, augment/invert=ops) but the model represents
  nothing about whether layers form valid counterpoint *when combined*. The
  harmony axis above models the harmony a single part realizes against the changes,
  not inter-LAYER consonance. The ruler-consistent fix is a read-side consonance
  lens (the masking-analyzer shape), not a generator. → `backlog ARR-4V7P`.

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
