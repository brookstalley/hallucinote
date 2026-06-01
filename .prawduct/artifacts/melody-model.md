# Melody Model — the line layer (contour · expectation · motivic economy · harmonic fit)

**Status:** **read-side lens SHIPPED (phase 2a); authoring side designed, pre-build.**
The verified research foundation, the taxonomy placement, and the governing thesis
are settled, and the FIRST both-sides primitive — the symbolic **melody lens**
(`src/hallucinote/melody/`: `lens` + `contour` + `intervals` + `harmony_fit`) — is
built: a pure-stdlib, render-free read-side analyzer that measures the genre-general
substrate facts and classifies a line `active` / `static` / `insufficient-data`,
validated on sun-zone-done's two hand-authored hooks (§9); 27 tests, full suite
green. Built **read-side-first**, as performance was — it quantifies the gap and
becomes the authoring side's executable acceptance test. Wired into the read-side
**`/compose-review`** surface (the render-free compositional sibling to `/mix-review`)
via a per-song `melody_report()` convention + the `tools/melody_lens.py` CLI — see
§7 *Read-side surface*. Still pre-build (friction-driven follow-ons): the declared
melodic-PROFILE authoring surface + profile-relative grading + learn-back (§4), the
motivic-economy reading + the shaped-vs-aimless verdict (§7), and any thin authoring
rulers. See `arrangement-model.md` § *The dimension taxonomy* for where melody sits
among the song's dimensions; read that first.

**Sources.** TWO verified deep-research passes (2026-05-31), same adversarial
discipline as the performance pass (3-vote, majority-refute kills). Pass 1
(expectation, contour/universals, taxonomy): 6 angles, 28 primary sources, 113
candidate claims, 25 verified → **22 confirmed / 3 killed**. Pass 2 (the under-
covered angles: melody↔harmony coupling, memorability/hooks, motivic/phrase): 26
primary sources, 95 candidate claims, 25 verified → **23 confirmed / 2 killed**
(with one angle — motivic/phrase — honestly returning **no** surviving claims; see
§3b). **45 confirmed claims across both passes.** Full citations in
[References](#references); per-claim provenance with its verification vote in
§ *Research foundation*.

> **North star:** *songs for the ages — great art, not software.* A melody is the
> line a listener carries home — the part they hum, the thing that *is* the song
> for most people. It is also the dimension where a machine most easily produces
> the *plausible-but-dead*: in-key, in-rhythm, and utterly forgettable. This layer
> exists so Hallucinote can **author a line's intent and measure whether the line
> realizes it** — WITHOUT ever pretending there is one universal "good melody"
> function to optimize toward. The composer/LLM brings the actual musical idea;
> the layer carries arithmetic and holds up a mirror. See
> `feedback_great_art_not_software`, `feedback_prefer_llm_over_deterministic_module`.

---

## 1. The governing thesis — substrate + profile, measured against intent

> This is the load-bearing decision, and the research confirms it directly. It is
> also the user's mandate framing (memory `project_melody_model_meta_answer`): the
> cross-genre requirement means there is **no single right answer — there is a
> meta-answer applied per song.**

**There is no universal "good melody" scoring function, and building one would be
a stamp.** A bluegrass fiddle line, a techno acid hook, a Coltrane sheets-of-
sound run, a Gregorian-influenced chant, a trap melody, and a Bach fugue subject
do not share one rulebook. A lens that hard-coded "arch good · leaps bad · range
≤ an octave singable · low chromaticism" would flatten every idiom into one
aesthetic — the exact ruler-not-stamp violation the project refuses
(`arrangement-model.md` § *Ruler, not Stamp*).

The research says the same thing with citations: **there are no absolute melodic
universals — only statistical ones** (Savage et al. 2015, §3.6); **melodic
contour does not cluster into discrete types and the "melodic arch" is style-
specific** (Cornelissen et al.; Chinese folksong averages *descend* — §3.7); and
the **pitch-vs-rhythm complexity balance is a style-level specialization, not a
within-song law** (McBride et al. — §3.8). "Good melody" is genre-general
*principles* (proximity, a small alphabet, expectation management) realized in
genre-particular ways.

**The architecture this forces is the metaperformer pattern again** — identical
in shape to the performance layer's "genre groove-baseline + magnitude `k`":

1. **A genre-GENERAL substrate** — only what the research finds cross-culturally
   robust (pitch proximity / small intervals; a small pitch alphabet; harmonic/
   tonal anchoring; the *existence* of contour shape and motivic economy). The
   lens measures these **unconditionally, as neutral facts** — never as a pass/fail.
2. **A declared per-song / per-section melodic PROFILE** carrying the genre-
   PARTICULAR intent for *this* line: its contour intent, target range/register,
   step↔leap appetite, non-chord-tone freedom, repetition appetite, the idiom it
   belongs to. This is melody's analog of the declared genre groove-baseline.
3. **The lens grades the line against its OWN declared intent**, never a universal
   ideal — and (the `/mix-review` pattern, memory
   `project_masking_and_intent_collaboration`) **learns the revealed intent back
   per-song** as a markdown annotation, so a deliberate genre choice (a dense
   chromatic bebop head, a one-note minimalist drone) is never re-flagged as a
   defect. Findings are coaching QUESTIONS, never verdicts.

So "a meta-answer applied per specific song" = **universal substrate + declared
profile → measure relative to intent.** The intelligence (the melodic idea, the
profile choice) lives in the LLM; the ruler carries arithmetic and measurement
(`feedback_prefer_llm_over_deterministic_module`).

---

## 2. Where this sits in the taxonomy — a line over the substrates, not an orthogonal axis

Per `arrangement-model.md` § *The dimension taxonomy*, a song's dimensions sort
into **authored structure intents** (form, energy, harmony, + meter-feel),
**realization layers** (derived from the intents — performance is the first),
and **subsystems** (sound-design; text/flow). **Where does melody go?**

Melody is **not a fourth orthogonal structure intent with universal rules** — the
research kills that framing (no universal good-melody function, §1). Nor is it a
pure realization layer *derived* from the intents the way performance is — a great
melody is genuinely *authored*, not computed from energy + harmony. Melody is a
**line whose two dimensions read the substrates already modeled**:

- **Its PITCH dimension reads HARMONY** (`theory` — ARR-1H9C). Melodic pitch
  organization is substantially constrained by the prevailing chord/scale: chord
  tones on strong positions, non-chord-tones as decorated/resolved deviations,
  scale-degree stability following the tonal hierarchy. *How much* it is
  constrained, pass 2 quantifies (§3.A1–A5): real but **modest, statistical, and
  classical-bound** — strong enough to model, loose enough to never enforce. The
  melody lens therefore **reuses `theory.model`** (a melodic note is classified chord-
  tone / scale-tone / chromatic against `Progression.chord_at(beat)`) exactly as
  `theory.lint` does for chordal parts — the melody lens is the *horizontal*,
  single-line counterpart to the harmony lint's *vertical* conformance.
- **Its RHYTHM dimension reads the FEEL / performance layer** (`performance` —
  ARR-3R8F). Melodic rhythm (the durational pattern, the placement of notes in
  the bar) is distinct from harmonic rhythm and is rendered by the same
  microtiming/feel layer that renders every part. The melody lens does **not**
  re-measure timing feel — `performance.lens` already owns that. Melody owns the
  *symbolic* rhythmic content (the durational/contour pattern), not its
  microtiming realization.

What is **genuinely melody's own** — not owned by harmony or feel — is the
**CONTOUR and the MOTIVIC/expectation shape of the line**: the sequence of
ups/downs and their sizes, the arch/descent, the climax placement, the
step↔leap profile, the range, and the economy of repetition vs. development.
This is the melodic substance the arrangement `Motif`/`Reference` scaffold does
*not* capture (it carries a motif's *recurrence*, never its *shape*).

**Decision: melody is a `line` layer that reads harmony (pitch) and feel
(rhythm), and owns contour + motivic economy.** It is neither a new orthogonal
axis (no 1000 axes) nor a derived realization (the line is authored). This is the
taxonomy's third kind of relationship — a *composite that reads other
dimensions* — and it is exactly why the both-sides lens **reuses `theory`** rather
than re-deriving harmony. **Pass 2 confirms the split directly** (§3.A1–A5): its
own synthesis is *"model pitch against (inferred/known) harmony; model contour and
rhythm with more autonomy"* — melodic pitch is empirically harmony-coupled (tonal
hierarchy at strong beats; stepwise non-chord-tone resolution; tension as pitch-
space distance), while contour and rhythm carry the line's independent identity.
The structural placement is settled; the honest limit (the coupling is *modest in
magnitude and flattens outside tonal/classical idioms* — §3.A1) is precisely why
harmony-fit is graded against the declared profile (§5), never as a universal.

---

## 3. Research foundation (verified)

The literature is convergent on a surprising headline: **the listener-side
organizing principle of melody is EXPECTATION, and it is rigorously quantifiable
in information-theoretic terms** — but **what counts as a good realization is
statistical and style-specific, never a fixed rule.** Each claim below carries
its adversarial-verification vote.

### 3a. Pass 1 — expectation, universals, contour, taxonomy (22/25 confirmed)

**3.1 — Melodic expectation is modelable as unsupervised statistical learning;
unexpectedness is information content** *(3-0).* Pearce's **IDyOM** learns melodic
expectations purely from corpus exposure (variable-order Markov / multiple-
viewpoint models; a long-term corpus model + a short-term within-stimulus model),
with no labels and no theory about the outcomes it predicts. An event's
unexpectedness is its **information content `h = −log₂ p(event | context)`**
(surprisal); the model's contextual uncertainty is the **entropy `H`** (mean
information content) of its predictive distribution [Pearce & Wiggins 2012; Pearce
et al. 2010; Hansen & Pearce 2014]. *Caveat:* "theory-free" is narrow — it means
not being told the next-note answer, NOT that the input representation is
assumption-free (IDyOM's viewpoints can even include Narmour-derived features).

**3.2 — The statistical model predicts human expectation at least as well as, and
on complex contexts significantly better than, the best rule-based model** *(3-0).*
Across experiments of rising complexity, IDyOM equalled or beat Schellenberg's
two-factor Implication-Realization model, the gap widening with longer/realistic
contexts (German chorales: IDyOM R²adj = .63 vs the IR model's .13) [Pearce &
Wiggins 2006; Pearce 2005]. *Caveat:* "IDyOM *subsumes* IR" is too strong (it was
a killed claim — see 3.K1); both models leave **much variance unexplained**,
which the authors attribute to missing **harmonic/hierarchical structure** — a
direct empirical motivation for the melody↔harmony coupling (§5).

**3.3 — Expectation is driven by TWO independent, complementary mechanisms** *(3-0).*
Gestalt-like **pitch proximity** (prefer a small next interval) AND **statistical
learning** each explain unique variance in listeners' online expectations;
statistical learning carries the larger role, but **neither alone fully accounts**
for melody — the residual again points to harmonic/hierarchical structure [Morgan
et al. 2019; Verosky & Morgan 2021]. *Caveat:* proximity is a *tendency*, not a
rule; whether the proximity preference is innate or itself learned is an
unresolved origin debate (Temperley 2014 vs Pearce/Wiggins 2006) — the *co-
contribution* is solid, the *origin* is not.

**3.4 — The Implication-Realization model is overspecified; it reduces to two
orthogonal factors** *(3-0).* Schellenberg (1996/1997) showed Narmour's bottom-up
I-R principles are collinear/redundant and, via PCA, reduced them to **pitch
proximity** + **pitch reversal** (a leap tends to be followed by a step in the
opposite direction — the gap-fill / post-skip-reversal effect) with equal-or-
better predictive accuracy [Schellenberg 1997; corroborated Pearce & Wiggins
2006]. *Caveat:* the two-factor model is itself later superseded on fit by
statistical models — it is a *parsimonious approximation*, not the deepest model.

**3.5 — Huron's ITPRA is the dominant qualitative frame for expectation** *(3-0,
with documented critiques 3-0).* Expectation decomposes into five response systems
across a pre-outcome epoch (**I**magination, **T**ension) and post-outcome epoch
(**P**rediction, **R**eaction, **A**ppraisal); expectations are acquired largely
by statistical induction; predictive success yields limbic *reward*, failure a
*surprise* penalty; Huron extends Krumhansl's **tonal hierarchy** (zeroth-order
scale-degree distribution) with **tonal tendency** (first-order, what-follows-what)
[Huron 2006; Pearce & Müllensiefen 2007]. *Honest caveats (also verified 3-0):*
Huron makes little effort to *falsify* his mechanisms (mostly confirming
evidence); the statistical-vs-innate "chicken-and-egg" is acknowledged but
unresolved; and despite claiming higher-order internalization, his own analyses
use only 0th/1st-order models. Cite ITPRA as *Huron's theory*, not settled fact.

**3.6 — No absolute melodic universals, but strong STATISTICAL universals** *(3-0).*
Across 304 recordings from 9 world regions, **no exceptionless universals** but a
coherent set of above-chance statistical universals. The **pitch-domain set**:
discrete pitches; a **small pitch alphabet** (typically **≤ 7 scale degrees** per
octave); octave divided into **NON-equidistant** intervals; and **predominance of
small (stepwise/scalar) melodic intervals** — small-interval dominance appears in
**every society sampled**. The small-alphabet distribution is predicted by a
parameter-free generative model constrained by scalar motion + melody length +
information rate (r = 0.99), likely reflecting **memory-like information
constraints** [Savage et al. 2015; McBride et al. 2024]. *Caveats:* "universal" =
statistical, never exceptionless (genuine equidistant *tuning* systems exist —
Thai, Javanese slendro — though operative scales stay nonequidistant); the memory-
limit *mechanism* is a hypothesis, not proven.

**3.7 — Contour does NOT cluster into discrete types; the "melodic arch" is
style-specific** *(arch counter-example 3-0; no-clustering 2-1, MEDIUM).* Tested
across German + Chinese folksong and Gregorian chant, phrase contours show **no
discrete clusters** — contour is better modeled as a **continuous, statistically-
structured quantity** than as an Adams/Huron discrete typology. The **Chinese
folksong average descends** (not arch-shaped) — a counter-example to a strict
melodic-arch claim [Cornelissen et al.; Huron 1996; Savage 2015]. *Caveats:* the
no-clustering paper is a preprint (hence MEDIUM); "no clusters" ≠ "no structure"
— cite it to justify modeling contour as **continuous**, NOT as evidence against a
central tendency; the broader "arch OR descending, small-interval" formulation
survives as a statistical universal.

**3.8 — Melodic complexity & the pitch↔rhythm balance vary with STYLE, not
universally** *(3-0).* In folk (orally-transmitted) corpora there is a strong
**negative between-culture correlation** between pitch entropy and rhythm entropy
(r = −0.66) — cultures specialize in either pitch *or* rhythmic complexity — that
does **not** hold for notated art music. Total melodic information also tracks
transmission mode: folk melodies cluster at **intermediate** information (IQR
80–144 bits), art music far higher (245–673 bits) — all measured via IDyOM
[McBride et al. 2024]. **CRITICAL caveat (level-of-analysis):** the −0.66 trade-off
is **between cultures, NOT within songs** (within a corpus the correlation is
weakly *positive*) — it must **never** be authored as a within-song "trade pitch
for rhythm complexity" rule. The bit-ranges are descriptive; the "memory limits"
cause is a hypothesis.

**Killed claims (do not rely on):**
- **3.K1** *(1-2)* — "the statistical model *subsumes* Narmour/Schellenberg's
  bottom-up rules, so they needn't be a separate system." Refuted: Gestalt/
  proximity adds **independent** predictive power (3.3). Treat statistical learning
  and Gestalt principles as **complementary**.
- **3.K2** *(1-2)* — "descending-or-arched small-interval contour is a *cross-
  cultural universal*" (as unqualified stated). Only the hedged, style-specific
  version (3.7) survives.
- **3.K3** *(1-2)* — "contour is *definitively* continuous (vs discrete)" as a
  strong claim. Survives only as "no evidence of discrete clusters" (3.7) — a
  weaker, modeling-guidance form.

### 3b. Pass 2 — harmony coupling (A) · memorability (B) · motivic/phrase (C)

The focused second pass went **deep** on the three under-covered angles. Angle A
(harmony coupling) and Angle B (memorability) returned strong verified findings;
**Angle C (motivic/phrase) honestly returned no surviving verified claims** (3.C
below) — recorded as such, not hand-waved.

**Angle A — melodic pitch is empirically harmony-coupled.**

**3.A1 — Tonal-hierarchy + chord-tone coupling (the corpus statistic)** *(3-0).*
In classical corpora (Bach, Mozart, Beethoven, Chopin) tonally stable pitch
classes co-occur with metrically strong positions **beyond simple joint
probability**, and the pitch-class distribution at strong beats matches the
**Krumhansl-Kessler tonal hierarchy** (tonic > fifth/third > other diatonic >
chromatic) more closely than at weak beats (avg-metric-stability ↔ tonal-hierarchy
r = .77) [Prince & Schmuckler 2014]. *Caveats (decisive for our design):* the
coupling is **real but modest in magnitude** ("only weakly correlated" —
Temperley), is **classical-corpus-bound** (tonal hierarchies are documented as
**flatter in rock**), carries a tonal-hierarchy-vs-local-chord-tone confound, and
composers reach it by different routes. → harmony-fit must be a **graded reading
against the declared profile**, never a universal gate.

**3.A2 — The coupling is a COMPOSITIONAL statistic, not a perceptual meter cue**
*(3-0).* Tonal stability does **not** drive listeners' metric inference, though
the reverse (meter shaping harmonization) is perceptually active — an asymmetry
[White 2017]. *Design read:* the chord-tone/strong-beat tendency is something
composers **do**, useful as an authoring prior + a measurable lens fact, not a
perceptual law to enforce.

**3.A3 — Listeners parse pitch against an INFERRED harmony; melodic anchoring
governs NCT resolution** *(3-0 for the constraints + perceptual fit; 2-1 for the
above-chance chord-inference experiment).* Bharucha's anchoring: a non-chord-tone
resolves to a stable tone under two constraints — **asymmetry** (the stable anchor
must *follow* the unstable tone → resolution is **forward-in-time**) and **pitch-
proximity** (the anchor is a scale **neighbor** → **stepwise** resolution). Chord
tones occupy metrically stressed positions more than NCTs; stability ranks
**chord-tone > diatonic > chromatic**. Listeners rate melody/chord *fit* highest
for pure chord-tone melodies (3.55), higher for **anchored** NCTs (2.84) than
unanchored (2.60) [Bharucha 1984/1996]. *Caveats:* reliable chord-inference only
for moderately-trained listeners; Western-tonal; tone-duration modulates the
temporal-order effect. → **this is the cheap, well-grounded lens reading: does each
NCT resolve by step to a proximate chord tone, forward in time?**

**3.A4 — Melodic/tonal PITCH tension ≈ pitch-space distance from the prevailing
harmony** *(3-0).* Lerdahl & Krumhansl's four-component model (prolongational
structure + pitch-space distance + surface tension + voice-leading attraction)
predicts the rise/fall of **listener-rated** tension; the **hierarchical** model
fits far better (Bach chorale R² = .79) than a sequential reading (.08) [Lerdahl &
Krumhansl 2007]. *Caveats (why we do NOT implement it in the lens v1):* validated
on **4-part homophonic textures**, so application to an isolated single line is a
defensible-but-**indirect** extrapolation; the theoretical validation is contested
(Tymoczko: free parameters, post-hoc trees); the model is *"notoriously difficult
to implement computationally"*; fit is style-dependent. → name tension as **theory
+ future**, ship the cheap proxy (scale-degree stability + distance-from-tonic).

**3.A5 — Tendency-tone resolution is quantified by ATTRACTION (Newtonian
inverse-square)** *(3-0).* attraction = (ratio of anchoring strengths) × (1 /
semitone-distance²); the inverse-square makes **half-step** unstable→stable
motions strongest, so **leading-tone→tonic and 4̂→3̂** carry the strongest
attractions (and V7→I the strongest harmonic attraction) [Lerdahl & Krumhansl
2007]. *Caveat:* the attraction component is the most contested of the four; values
are model estimates *correlated with* (not derived from) listener data. → corroborates
3.A3's "NCTs resolve by step" as the lens's tendency-tone reading.

**Angle B — memorability has a real but WEAK, genre-bound signal.**

**3.B1 — Earworm potential is predicted by three melodic features — weakly** *(3-0;
two sub-claims 2-1).* Relative to a large pop corpus, earworm (INMI) tunes have
**faster tempo** (~124 vs 116 bpm), a **MORE common global contour** (often arch-
shaped), and a **LESS common turning-point gradient** — a *"familiar overall shape,
distinctively-leaping local detail"* profile. But melody-only cross-validated
classification was just **62.5%** (chance 50%); only global-contour reached p < .05
[Jakubowski, Finkel, Stewart & Müllensiefen 2017]. *Caveats:* **pop-genre-bound**
(authors call for cross-genre testing); did **not** replicate earlier interval/
duration findings; tempo near the ~120 bpm preferred-motor-tempo (entrainment
confound); the earworm-feature literature is *"fairly vague"* (Arthur 2023). →
memorability is an **optional, hedged, intent-relative reading**, never a gate.

**3.B2 — Recognition tracks contour VARIABILITY + corpus-relative DISTINCTIVENESS,
independent of exact pitch** *(3-0).* A **more variable contour** (steep up/down)
predicts more accurate recognition of heard melodies (**flat contours are missed**,
read as novel); point-of-recognition is predicted primarily by **timing- and pitch-
distinctiveness** (deviation from corpus norms), not rated familiarity (85% of POR
variance) [Müllensiefen & Halpern 2014; POR result: **Bailes 2010**]. *Caveats:*
modest coefficient (CI lower bound near zero); explicit-recognition only (contour
behaves differently in implicit memory); single Western corpus; expertise moderates.
→ a cheap proxy worth reporting (contour variability, alphabet/interval
distinctiveness), genre-relative, never a universal "make it catchier."

**3.B — Killed (recorded for transparency):** "motivic m-type **rarity** is the
strongest shared memorability predictor" *(0-3)* and "**lyrics/chorus** dominate
earworm content (≈50% more, ≈90% chorus fragments)" *(0-3)* — do **not** treat
motivic-rarity-as-primary-lever or verbal/chorus dominance as established.

**3.C — Angle C (motivic transformation, phrase structure, melodic rhythm):
NO surviving verified claims.** Schoenberg's developing variation / Grundgestalt,
Caplin's sentence/period & cadential function, and the perceptual salience of the
transformation operations (the classic "retrograde is hard to hear" — Dowling) were
fetched but **none survived** this pass's top-25 verification. Recorded honestly as
**open**. *This is not a blocker for the lens v1*: the **canonical six variation
ops** (transposition, inversion, retrograde, augmentation, diminution,
fragmentation) were **already verified and shipped** by the arrangement pass
(`arrangement-model.md` § *Research foundation*; `generators.variations`), and the
melody layer **reuses** them rather than re-deriving them. A dedicated third pass
on phrase-structure + transform-perceptual-salience is a **candidate follow-on**
(backlog), needed only if/when the line layer grows a phrase-architecture reading.

---

## 4. The authoring model — the declared melodic profile

A **melodic profile** is the declared intent (the ruler's input); the line itself
is authored by the LLM at the note floor (or via thin contour/transform rulers).
Authored **per melodic part**, modulated **per-section** (the metal lead and the
reggae lead in sun-zone-done are different profiles; a verse and a final-chorus
lift are different sections of one profile). Anticipated components, all
**declared, none computed-for-you**:

- **Idiom / genre baseline** — a named reference point (singable-pop-hook,
  bebop-head, modal-chant-like, riff-motif, through-composed-line) that sets
  default *expectations* for the readings below. Energy-independent, like the
  performance genre-baseline.
- **Contour intent** — the line's shape *as a continuous prior*, never a discrete
  type (3.7): e.g. an arch peaking late, a terraced descent, a static recitation.
  Climax/apex register + placement.
- **Range / tessitura** — target span and register (singability is genre-relative,
  not a universal ceiling).
- **Step↔leap appetite** — how much the line favors proximity (3.3, 3.6) vs.
  dramatic leaps; a bebop head and a hymn sit at opposite ends, both valid.
- **Harmonic freedom** — how freely the line leaves chord tones (chord-tone-locked
  → freely chromatic); the rate the §7 harmony-fit reading is graded *against*. The
  research-backed default for a tonal idiom (3.A1, 3.A3): chord tones favor strong
  beats, non-chord-tones resolve **by step, forward in time** (Bharucha anchoring).
  But the coupling **flattens in rock/modal** (3.A1 caveat) — so the default is a
  *profile setting*, not a baked rule; a modal or chromatic idiom declares looser.
- **Repetition appetite / motivic economy** — how much the line is built from a
  small developed cell vs. through-composed (reusing the arrangement layer's six
  variation ops, 3.C). The memorability levers (3.B) — a *conventional* overall
  contour with *distinctive* local detail — are an **optional, genre-bound** aim a
  pop-hook profile may declare, never a universal "make it catchier."

**The ruler/stamp boundary (decisive):** there is **no `melody()` generator** that
*invents* a line — that is the art, and inventing it would be the stamp that kills
it (`feedback_great_art_not_software`). What the layer MAY offer are thin
**rulers** over a line the composer already has: the motivic transformation ops
(transpose/invert/retrograde/augment/diminish — *already shipped* in
`generators.variations` for the arrangement layer; melody reuses them), a contour-
to-scale-degree mapping helper, and chord-tone snapping — each carries arithmetic,
none makes the melodic decision. **Discovered from friction, never speculative.**

---

## 5. The melody ↔ harmony ↔ feel coupling

Melody is the *line* layer that **reads** the substrates beneath it — §2. **One
source of truth:** the line does not re-declare the chords (it reads
`Progression`) and does not re-declare the groove (it reads / is rendered by
`performance`). The research makes the split concrete and asymmetric:

- **PITCH reads HARMONY** — empirically coupled (3.A1–A5): chord tones favor strong
  metrical positions and track the tonal hierarchy; non-chord-tones resolve by step
  forward in time (anchoring); tension rises with pitch-space distance from the
  prevailing chord. So the lens classifies each melodic note **chord-tone / scale-
  tone / chromatic** against `Progression.chord_at(onset)` and reads NCT
  resolution — reusing `theory.model`, the horizontal counterpart to the harmony
  lint's vertical conformance.
- **RHYTHM reads FEEL** — melodic rhythm's microtiming realization is the
  performance layer's job (`performance.lens`/`realization`); the melody layer owns
  only the *symbolic* durational pattern, not its push/drag/swing.
- **CONTOUR is melody's OWN** — the line's identity that neither substrate carries.

**Why the coupling is a graded reading, not a constraint.** The harmony coupling is
**modest in magnitude, a compositional tendency (not a perceptual law), and
flattens outside tonal/classical idioms** (3.A1, 3.A2). A rock riff, a modal hook,
or a chromatic bebop head legitimately sit looser to the chords. So the lens grades
harmony-fit **against the profile's declared harmonic-freedom** (§4) and frames
deviations as questions — exactly as `theory.lint` already treats out-of-chord
notes as a *warning* ("intended passing tones?"), never a blocking error. This is
the substrate+profile thesis (§1) applied to the single most-coupled dimension:
even *here*, the universal is a prior, the profile is the truth, intent is learned
back. There is **no competing intensity/harmony dial** — melody renders the chords
the harmony axis already declared (the same no-inconsistent-triple discipline the
energy and performance layers hold).

---

## 6. Scope boundary

Consistent with the performance layer's metered-only boundary and the arrangement
note floor: the melody layer models **pitched, discrete-onset monophonic lines**
(a hummable line, a riff, a vocal hook) — the unit the discrete-pitch + small-
alphabet substrate (3.6) and the single-line anchoring model (3.A3) actually
describe. It **degrades gracefully to the raw note floor** for material it does not
model:

- **Dense polyphony / texture-mass / cloud writing** — already out per
  `arrangement-model.md` (the unit is a mass, not a line); inter-line counterpoint
  is the separate vertical-consonance lens (ARR-4V7P), not this layer.
- **Pitch-continuous / microtonal / heavily-bent lines** — the discrete-pitch
  substrate assumption (3.6) does not hold; the lens reports low confidence rather
  than forcing a contour/interval read.
- **Unmetered / free-time** melodic rhythm — inherits the performance layer's
  metered-only boundary (a documented limitation, not a flaw).

Like every layer, the line is optional sugar on top of `_note`; nothing forces a
part to declare a melodic profile.

---

## 7. The measurement model — the melody lens (the read side, built first)

Per the both-sides principle, the read side is co-equal with authoring and (per
the build-order learning from performance) **ships first** — it quantifies the gap
on real songs and becomes the authoring side's executable acceptance test. It
answers *"is the line doing what its profile intends, and is it a shaped line
rather than a random walk or a mechanical drone?"* — framed as coaching questions,
never verdicts (authored melodic choice is not error, exactly as authored feel is
not error).

**Structure mirrors `performance.lens` / `theory.lint` exactly** — pure stdlib
(`statistics`), render-free, build-time over the authored `NoteDict`s; frozen
dataclasses + a `Severity` Literal + `to_dict()` boundary; a decoupled
`SectionMelody` input adapted from the arrangement layer by a new
`Arrangement.section_melody_inputs()` (parallel to `section_lints` /
`section_perf_inputs`), carrying the section's `Progression` because the pitch
reading reads harmony. Likely module shape: `src/hallucinote/melody/`
(`lens.py` + `contour.py` + `intervals.py` + a harmony-fit reader reusing
`theory.model`).

**What it measures, per melodic line, per section** (the genre-general substrate
facts, reported as neutral measurements):

- **Contour** (continuous, per 3.7 — never a discrete type label): direction-
  change profile, overall shape (net ascending/descending/arch/static via a
  cheap polynomial/centroid fit), **climax/apex** pitch + position, and **contour
  variability** (the steep-vs-flat gradient that 3.B2 ties to recognition — flat
  contours read as forgettable; reported as a neutral fact, genre-relative).
- **Intervallic profile**: **step↔leap ratio** (proximity, 3.3/3.6), interval-size
  distribution, **post-skip reversal** rate (gap-fill, 3.4), **pitch-alphabet
  size** (the ≤7 tendency, 3.6).
- **Range / tessitura**: total span, register.
- **Motivic economy / repetition**: within-line **n-gram self-similarity** — a
  *corpus-free* proxy for within-melody information/entropy (3.1, 3.8): a highly
  repetitive line is low-entropy/"hooky-or-boring", a through-composed line high-
  entropy. (This is the cheap, render-free analog of performance's lag-1-acf
  proxy for the 1/f theory — see the design note below.)
- **Harmony fit** *(reuses `theory.model`)*: each note classified **chord-tone /
  scale-tone / chromatic** against `Progression.chord_at(onset)` and the mode
  (3.A1, 3.A3). Reported: non-chord-tone fraction; the **chord-tone-on-strong-beat**
  tendency (do chord tones favor metrically strong onsets?); and **tendency-tone
  resolution** — does each NCT resolve **by step, forward in time**, to a proximate
  chord tone (Bharucha anchoring, 3.A3/3.A5)? The *horizontal, single-line*
  counterpart to `theory.lint`'s vertical conformance, graded against the profile's
  declared harmonic-freedom (§5), never as a universal gate.

**The classification (as shipped, phase 2a) is deliberately genre-SAFE:** `static`
(a near-monotone — tiny ambitus), `active` (a line with real melodic range), or
`insufficient-data` (too few notes). It does **not** verdict *shaped vs aimless/
random-walk* — that split is genre-relative (a third-based reggae hook, a chromatic
bebop head, and a folk tune each read against their own idiom) and needs the
**declared profile** to grade against, so it is a **phase-2b** capability. v1 instead
REPORTS the facts that feed that judgment (step↔leap, post-skip reversal, contour
shape, alphabet, harmony fit) without imposing a universal verdict — the same
honesty as `performance.lens` deferring declared-profile grading (and *more*
deferred, because melody is more genre-relative than feel). A deliberately static
line surfaces only as a coaching QUESTION, never a fail. This was a deliberate
build-time correction: an early `step_fraction ≥ 0.5 → shaped, else wandering`
rule mislabeled the genuine third-based reggae hook as "wandering" — exactly the
universal verdict the thesis (§1) forbids — so the verdict was dropped to 2b.

> **Design note — why proxies, not IDyOM.** Information content (3.1) is the
> theoretical north star for "shaped vs random," but IDyOM needs a trained corpus
> and an ML stack — incompatible with the stdlib-only core and
> `feedback_prefer_llm_over_deterministic_module`. So, exactly as the performance
> lens names *1/f* as the theory but ships **lag-1 autocorrelation** as the cheap
> robust proxy, the melody lens names *information content / expectation* as the
> theory and ships **corpus-free structural proxies** (proximity, alphabet size,
> contour structure, within-line n-gram repetition, harmony fit). The LLM brings
> the melodic intelligence and declares the profile; the ruler measures proxies.

Findings are framed against intent (the masking-analyzer / mix-review shape):
*"you declared a singable arch-shaped pop hook; this line has a 14-semitone leap
to its apex on a weak beat and never repeats a cell — intended, or has the hook
got lost?"* — and the revealed intent is **learned back per-song** so it never
re-flags.

### Read-side surface — `/compose-review`, not `/mix-review`

> Decision (2026-06-01), recorded here because it has lock-in. **The lens's
> user-facing home is `/compose-review`, not `/mix-review`.** Both are intent-aware
> read-side producers' surfaces, but they read different things: `/mix-review`
> interprets an **audio** `MixReport` (masking, loudness, reverb — it needs a
> render), while `/compose-review` (the compose-stage sibling that landed in
> parallel — `intent-architecture.md` "the same loop at the compose stage") reads
> the **composition** symbolically from `build.py` + the arrangement: density,
> register, energy arc, contrast. The melody lens is **pure-symbolic and
> render-free** — its kind matches `/compose-review` exactly. They are
> complementary halves of *"is the composition doing what it intends?"*:
> compose-review reads the *vertical/structural* facts (which parts play where,
> how dense), the melody lens reads the *horizontal line-level* facts (contour,
> intervals, harmony-fit, the static/unresolved-NCT coaching questions)
> compose-review structurally cannot see. Wiring it into `/mix-review` would have
> mis-coupled a build-time symbolic ruler to an audio surface and made it
> unavailable at the compose stage, where line-shape questions belong.
>
> **Mechanism (full harmony-fit needs the in-memory progression).** Harmony is
> authored in `build.py` and is **not persisted to the DB**, so a pure DB read
> cannot do the harmony-fit reading (chord-tone / NCT-resolution / strong-beat) —
> the §5 melody↔harmony coupling, the lens's richest output. The lens therefore
> runs **build-time over the in-memory `Arrangement`**: a song exposes a
> `melody_report()` (one line via `hallucinote.melody.analyze_arrangement(arr, …)`),
> and `tools/melody_lens.py <slug>` invokes it for `/compose-review` to fold into
> its INTERPRET-vs-intent loop. The scaffold template emits the convention so new
> songs get it for free; retrofitting older songs (falling-walking, full-band-rock)
> is a friction-driven follow-on.

---

## 8. Phased delivery plan

Strictly sequenced, mirroring the performance layer's proven order:

1. **Document & integrate (THIS artifact + the taxonomy update + the manifest +
   scope + backlog) — DONE when this lands** (with pass 2 folded in). The research
   is a native part of the platform's design materials, reference-backed.
2. **Platform implementation (friction-driven), read-side FIRST.** (a) **DONE** —
   the symbolic **melody lens** `src/hallucinote/melody/` (`lens` + `contour` +
   `intervals` + `harmony_fit`) + the `Arrangement.section_melody_inputs()` adapter,
   validated on sun-zone-done's two hand-authored hooks (§9); 27 tests. **Wired
   into `/compose-review`** (see §7 *Read-side surface* for why compose-review, not
   mix-review): `analyze_arrangement()` + the `tools/melody_lens.py` CLI + a per-song
   `melody_report()` convention (sun-zone-done + the scaffold template).
   (b) the **declared melodic profile** authoring surface (§4) + grading the lens
   against it + learn-back + the shaped-vs-aimless verdict. (c) any thin authoring
   rulers discovered from friction (contour→scale-degree, chord-tone snap) — never
   a `melody()` generator.
3. **Bring it to a song.** Run the lens on sun-zone-done; tune by ear. Which
   profile each line declares, and any rewrite, is a creative lock-in left to the
   user's ear — deliberately not auto-applied (as the performance tune-by-ear pass
   was).

---

## 9. First demonstration: sun-zone-done's hooks

The flagship already carries two **hand-authored melodic lines at the raw note
floor**, with no melodic dimension — the exact gap MEL-1A7K names, and the lens's
forcing function (the same role sun-zone-done played for harmony + performance):

- **`_reggae_lead_chillin`** ("chillin in the sun zone") — E Dorian, mid-register
  (E3–A4), mostly stepwise with an arch back to a held E4: should read *shaped*,
  small-alphabet, proximity-dominant, well-anchored to the Em harmony — a singable
  hook. The lens's "this is a good reggae line" baseline.
- **`_metal_lead_no_time`** ("NO TIME FOR THAT") — E Phrygian, upper register
  (E4–E5), octave leaps, the ♭2 (F♮) trademark non-tonic color, climax on E5:
  a *different valid profile* — angular, higher tessitura, more leap, deliberate
  ♭2 chromatic color against the mode. The lens must read it as realizing its OWN
  intent, not flag its leaps/♭2 as defects — the proof that grading is intent-
  relative, not universal.

Together they are the both-sides acceptance test: one lens, two profiles, neither
graded against the other's ideal.

---

## References

> Pass-1 sources first (provenance in §3a), then pass-2 (provenance in §3b).

- **[Pearce & Wiggins 2006]** *Expectation in Melody: The Influence of Context and
  Learning.* Music Perception 23(5):377–405. — IDyOM vs the two-factor IR model.
  https://www.marcus-pearce.com/assets/papers/PearceWigginsMP06.pdf
- **[Pearce & Wiggins 2012]** *Auditory Expectation: The Information Dynamics of
  Music Perception and Cognition.* Topics in Cognitive Science 4:625–652. PMID
  22847872. https://onlinelibrary.wiley.com/doi/full/10.1111/j.1756-8765.2012.01214.x
- **[Pearce et al. 2010]** *Unsupervised statistical learning underpins
  computational, behavioural, and neural manifestations of musical expectation.*
  NeuroImage. PMID 20005297.
- **[Hansen & Pearce 2014]** *Predictive uncertainty in auditory sequence
  processing.* Frontiers in Psychology 5:1052 (open-access; the verbatim IC/entropy
  definitions). — IDyOM project: https://www.marcus-pearce.com/idyom
- **[Pearce 2005]** *The Construction and Evaluation of Statistical Models of
  Melodic Structure…* PhD thesis, City University London.
  https://www.marcus-pearce.com/assets/papers/Pearce2005.pdf
- **[Morgan, Fogel, Nair & Patel 2019]** *Statistical learning and Gestalt-like
  principles predict melodic expectations.* Cognition 189:23–34. DOI
  10.1016/j.cognition.2018.12.015. PMID 30913527.
  https://www.sciencedirect.com/science/article/abs/pii/S0010027718303317
- **[Schellenberg 1997]** *Simplifying the Implication-Realization Model of Melodic
  Expectancy.* Music Perception 14(3):295–318. DOI 10.2307/40285723.
  https://online.ucpress.edu/mp/article-abstract/14/3/295/61992/
- **[Huron 2006]** *Sweet Anticipation: Music and the Psychology of Expectation.*
  MIT Press. (ITPRA.) — Review: Pearce & Müllensiefen, Empirical Musicology Review
  2(2). https://www.doc.gold.ac.uk/~mas03dm/papers/huron06-review.pdf
- **[Savage, Brown, Sakai & Currie 2015]** *Statistical universals reveal the
  structures and functions of human music.* PNAS 112(29):8987–8992. DOI
  10.1073/pnas.1414495112. PMID 26124105. https://www.pnas.org/doi/10.1073/pnas.1414495112
- **[McBride et al. 2024]** *Information and motor constraints shape melodic
  diversity across cultures.* arXiv:2408.12635v2 (PCI Evol. Biol. recommended,
  2025). https://arxiv.org/html/2408.12635v2
- **[Cornelissen, Zuidema, Burgoyne & Honing]** *Melodic contour does not cluster…*
  (preprint) + *Cosine Contours*, ISMIR 2021 (peer-reviewed anchor).
  https://archives.ismir.net/ismir2021/paper/000016.pdf
- **[Huron 1996]** *The Melodic Arch in Western Folk Songs.* (the targeted
  typology). — **[Adams 1976]** contour typology, Ethnomusicology.

*Pass 2 (harmony coupling · memorability):*

- **[Prince & Schmuckler 2014]** *The Tonal-Metric Hierarchy: A Corpus Analysis.*
  Music Perception 31(3):254–270. DOI 10.1525/MP.2014.31.3.254.
  https://online.ucpress.edu/mp/article-abstract/31/3/254/62649/
- **[White 2017]** *An Exploration of the Tonal-Metric Hierarchy.* + Temperley
  commentary. Empirical Musicology Review 12(1–2):19–37.
  https://emusicology.org/article/id/4709/ · https://emusicology.org/article/id/4705/
- **[Bharucha 1984/1996]** *Anchoring effects in music: The resolution of
  dissonance.* Cognitive Psychology 16:485–518; *Melodic Anchoring*, Music
  Perception 13(3):383–400, DOI 10.2307/40286176.
  https://online.ucpress.edu/mp/article/13/3/383
- **[Lerdahl & Krumhansl 2007]** *Modeling Tonal Tension.* Music Perception
  24(4):329–366. DOI 10.1525/MP.2007.24.4.329.
  https://www.fredlerdahl.com/s/Modeling-Tonal-Tension.pdf
- **[Jakubowski, Finkel, Stewart & Müllensiefen 2017]** *Dissecting an Earworm:
  Melodic Features and Song Popularity Predict Involuntary Musical Imagery.*
  Psychology of Aesthetics, Creativity, and the Arts 11(2):122–135. DOI
  10.1037/aca0000090. https://psycnet.apa.org/doi/10.1037/aca0000090
- **[Müllensiefen & Halpern 2014]** *The Role of Features and Context in Recognition
  of Novel Melodies.* Music Perception 31(5):418–435.
  http://mp.ucpress.edu/content/31/5/418
- **[Bailes 2010]** *Dynamic melody recognition: Distinctiveness and the role of
  musical expertise.* Memory & Cognition 38(5):641–650. DOI 10.3758/MC.38.5.641
  (the point-of-recognition result — attributed to Bailes, not Müllensiefen/Halpern).
- **[Dowling et al. 1999]** motivic-transform perceptual salience (retrograde/
  inversion poorly recognized vs transposition/contour) — fetched for Angle C;
  no claim survived this pass's verification (3.C). Provenance kept for the follow-on.

---

*This artifact is the owner doc for the melody line layer. It folds into
`arrangement-model.md` (§ The dimension taxonomy), `project-state.yaml`
(`scope.later` + `artifact_manifest`), and `backlog` MEL-1A7K. Related:
[`performance-model.md`](performance-model.md) (the sibling realization/feel layer
melody's rhythm reads), `theory` (`model.py`/`lint.py` — the harmonic substrate
melody's pitch reads), and memory `project_melody_model_meta_answer` (the
substrate+profile thesis). Status advances to "in build" only when phase 2 begins.*
