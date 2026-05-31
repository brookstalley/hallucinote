# Performance Model — the rendition layer (microtiming · dynamics · articulation)

**Status:** **phase 2a SHIPPED + phase 2b first primitive SHIPPED.** The symbolic
performance lens (the read side, §7) is built and merged: `src/hallucinote/
performance/` (`lens` + `correlation` + `dynamics` + `ensemble`), pure stdlib,
render-free, validated on sun-zone-done (it reproduces the flat-organ + "feels-
quantized" findings and reads the white-jitter drums as *sloppy*, not human),
wired into `/mix-review`. The **authoring side now has its first primitive**
(`realization`: `PerformanceProfile` + `apply_profile`) — the GERM "Random"
channel (small, additive, **1/f-correlated** breathing) that flips a mechanical
part to *human* through the very lens that measures it (the closed loop, §4.4,
§7). Still deferred (friction-driven): the genre-baseline profile field, the
energy↔performance coupling (§5), phrase-arc curves (§4.3), and the audio
extension (2c). Foundational design artifact for the **performance realization
layer** — the detailed, reference-backed home for what `arrangement-model.md` §
*The dimension taxonomy* names as **the first realization layer**; read that
section first for where this sits among the song's dimensions.

**Sources.** A verified deep-research pass (2026-05-30): 5 search angles, 22
primary academic sources fetched, 107 candidate claims extracted, 25 adversarially
verified (3-vote, majority-refute kills), **24 confirmed / 1 killed**. Full
citations in [References](#references); the per-claim provenance is preserved in
§ *Research foundation*.

> **North star:** *songs for the ages — great art, not software.* A score is a set
> of notes; a *performance* is how a human plays them — the lay-back, the swell,
> the breath, the lock between players. That rendition is where most of music's
> humanity lives. This layer exists so Hallucinote can **author that rendition as
> intent and verify it as fact** — not bolt on a "humanize" afterthought. See
> `feedback_great_art_not_software`, `feedback_microtiming_is_authorship`.

---

## 1. Where this sits — a realization layer, not a peer axis

Per `arrangement-model.md` § *The dimension taxonomy*, a song's dimensions sort
into **authored structure intents** (form, energy, harmony, + meter-feel),
**realization layers** (how the bones are rendered — *derived* from the structure
intents), and **subsystems** (sound-design; text/flow). **Performance is the first
realization layer.** It is **not** a new axis the composer dials independently — it
**reads** the structure intents (especially energy and harmony) and renders them,
plus a genre identity and deliberate overrides. This is the single most important
framing decision (confirmed by the research, §2.4): treating performance as a peer
axis would create the "inconsistent triple" the energy-derivative decision already
refused — two dials for one idea, free to contradict.

## 2. Governing principles

1. **Ruler, not stamp — the metaperformer pattern.** The composer/LLM *declares a
   performance profile*; a deterministic layer *computes the per-note deviations*.
   Declared intent (WHAT) vs computed execution (HOW). This is the architecture the
   literature most directly endorses (§2.6) and the only one consistent with
   *ruler-not-stamp* — an auto-humanizer that decides *how loose* would be a stamp.
2. **A realization layer, not a peer axis** (§1) — performance reads energy/harmony;
   it does not duplicate them.
3. **Structured, not random.** Human feel is *correlated* deviation (1/f), not
   white-noise jitter (§2.8). "Human, not sloppy" is therefore a measurable
   property of *deviation structure*, not of magnitude.
4. **Both sides, always.** Every dimension needs an **authoring** surface AND a
   **measurement/analysis** lens (the house pattern: harmony = `Progression` +
   conformance lint; mix = intent + masking analyzer). A performance layer authored
   but unmeasured is half-built.
5. **Metered-only, by design (a documented limitation, not a flaw)** — see §6.

---

## 3. Research foundation (verified)

The literature is strikingly convergent: expressive performance **should** be
modeled as a first-class layer separate from the score, and 40 years of work
establishes *what* to represent and *how*. The findings below each carry their
adversarial-verification result.

**3.1 — The score-vs-performance split is foundational** *(merged, 2-1 / 3-0).*
Expressive performance is the performer's deliberate shaping of parameters **not
prescribed by the notated score** — tempo, timing, dynamics, intonation,
articulation [Cancino-Chacón/Widmer 2018; Palmer 1997]. Palmer frames it as a
distinct cognitive+motor domain (interpretation → planning → movement). *Nuance
that matters for us:* the "notated-score" framing is Western-art-music-specific;
for oral/improvised traditions (chant, rap-flow, jazz improv) the split is better
cast as **conceptual-plan vs realization** — this qualifies but does not refute
layering (see §6).

**3.2 — The canonical, genre-general parameter set** *(merged, all 3-0).*
**Loudness/dynamics, expressive tempo/timing, and articulation**, with optional
**intonation** and **timbre** [Cancino-Chacón/Widmer 2018]. The KTH rule system /
Director Musices models all of them concretely: microtiming (inter-onset
deviations, swing/inégales, ensemble timing scaled to tempo), dynamics (sound level
in dB), articulation (offset-to-onset duration / micropauses), tempo curves
(phrase-arch, final ritardando), intonation (cent deviations) — per-note, in
musical context [Friberg/Bresin/Sundberg]. *Caveat:* a given rule's coverage can be
partial (DM's ensemble-swing was implemented only for eighth notes in 4/4) — the
*dimension* is modeled even where a *rule* is narrow.

**3.3 — Represent at MULTIPLE grains simultaneously** *(merged, both 3-0).*
Per-note deviations (slower/faster, louder/softer, staccato/legato) **and**
higher-level phrase/section shaping (gradual ritardando). "A complete multi-level
performance can be reasonably represented as a **linear combination of expressive
shapes at different hierarchical levels**" [Widmer & Goebl 2004]. Slowly-varying
parameters are expressible as continuous *time-shape* curves coupled to a note or
phrase. *Caveat:* the linear-superposition assumption is a deliberate
simplification; later work shows nonlinear cross-feature interactions exist — this
refines the *realization method*, not the multi-grain principle.

**3.4 — The macro layer is a 2-D tempo-loudness trajectory (≈ a 2-D energy curve)**
*(merged, all 3-0).* The **Performance Worm** renders expression as a continuous
trajectory in tempo (BPM) × loudness (sone) space, built at **beat** level by
interpolating measured points and smoothing with an adjustable Gaussian window
(0.5–2 beats) that trades local detail against global trend [Dixon/Goebl/Widmer
2002; Langner & Goebl 2003]. This is *"a direct analogue to an energy curve, but
two-dimensional"* — the empirical basis for the **energy↔performance coupling** (§5).

**3.5 — Performance is a TRANSFORMATION OF the score, a derived overlay** *(merged,
3-0 / 2-1).* Rule systems take a notated score and **modify nominal values** of
performance variables; ML systems take score + phrase analysis + tempo/dynamics
curves and learn "deviations from the score" [Friberg/Bresin/Sundberg; Widmer &
Goebl 2004]. The cleanest precedent for our layer: performance shapes notated
structure while remaining a **distinct representation** — a *derived overlay*, more
than an independent parallel axis. (Vindicates §1.)

**3.6 — The endorsed architecture: the KTH "metaperformer" pattern** *(3-0).* The
user **declares a profile** (which rules are active + a global magnitude parameter
`k`, default 1, scaling each rule's effect, + per-rule parameters); the program
**computes the realization** (the actual per-note timing/loudness/articulation
deviations). *"By manipulating rule parameters, the user can act as a metaperformer
… leaving the technical execution to the computer. Different interpretations of the
same piece can easily be obtained"* [Friberg/Bresin/Sundberg]. This **is** the
declared-profile / computed-realization split — and our ruler.

**3.7 — Deviations are STRUCTURED, not random** *(merged, all 3-0).* Expressive
deviations "act out" the music's hierarchical grouping structure to communicate it;
they are governed by structural/stylistic constraints and contain a separable
*rationally-explainable* component (learnable, with cross-performer commonalities —
e.g. higher-pitch-correlates-with-louder was *learned*, not pre-programmed)
[Cancino-Chacón/Grachten/Widmer 2017; Widmer 2005]. In rule systems, human-likeness
comes from structured generative rules **with stochastic noise as an explicitly
ADDITIVE, separate supplement** — the **GERM** model: **G**enerative (structural,
deterministic) + **E**motional + **R**andom (1/f timekeeper + white motor noise) +
**M**otion [Juslin/Friberg/Bresin 2002]. Random is a small additive term, never the
core. *Qualification:* a genuinely creative/individual residual persists and resists
full modeling — the claim is a *separable explainable component*, not full
explainability.

**3.8 — The decisive "human, not sloppy" finding: 1/f, not white noise** *(merged,
all 3-0).* Human timing deviations exhibit **long-range (1/f, fractal) correlations**
— a fluctuation now influences fluctuations tens of seconds later. In a controlled
listening test with **magnitude held constant** (zero-mean, σ=50 ms), listeners
**significantly preferred** the 1/f-correlated humanization over white noise **and
judged it more precise** [Hennig et al. 2011]. Because professional "humanize" tools
typically apply *white* noise, **the correlation STRUCTURE (not the deviation
magnitude) is what produces the perceived human touch — random per-note jitter is the
wrong model.** Replicated in commercial recordings [Sogorski/Geisel/Priesemann 2018].
*Caveat (mechanism, not conclusion):* Colley & Dean (2019) argue short-range
autocorrelation can reproduce the 1/f signature — so the *generative mechanism* is
contested, but the **"not white / correlated" core is undisputed**, and the
perception study used a single purpose-built pop stimulus (limits the *perception*
result's genre-generality).

**3.9 — Feel is genre/idiom-SPECIFIC, and inseparable from sound** *(merged, 3-0 /
3-0 / 2-1).* Swing, backbeat, behind-the-beat funk, and laid-back reggae are
**distinct, culturally-situated microrhythmic techniques**, not a single universal
offset and not random error [Iyer 2002]. The experience of groove requires
**particular genre-typical CONFIGURATIONS of temporal AND sonic (timbre) features
together** [Danielsen et al. 2023] — so a performance layer needs **per-genre
profiles**, and timing cannot be modeled fully independently of sound.
*Important counter-current (bounds the magnitude):* controlled-listening studies
[Madison 2011; Davies 2013; Senn et al. 2016] find microtiming deviations do **not**
reliably *increase* perceived groove and that **exaggerated** deviations **lower**
it. Both camps agree deviations are structured and that magnitude matters → **keep
deviation small and genre-calibrated, never maximized.**

**3.10 — Representation is medium-dependent at the bottom grain** *(3-0).* For
discrete-onset instruments, dynamics = per-note velocity; for continuous/orchestral,
dynamics = a per-time-instant loudness curve. A genre-general layer must support
**both a per-event (note-attached) and a continuous-curve representation**, mapped
from score features via a basis-function-style decomposition into a per-position
*trend* plus a per-note *local deviation* [Cancino-Chacón/Grachten/Widmer 2017].
This per-event-vs-curve split maps onto our metered/discrete (drums, bass, riffs,
rap onsets) vs continuous/sustained (pads, rubato, chant) distinction.

**Killed claim (do not rely on):** the specific R² magnitudes for nonlinear-over-
linear dynamics models (0.62→0.75 Chopin; 0.55→0.65 Beethoven) **failed verification
0-3** — the *direction* (expression has learnable interaction structure) stands via
3.7, but not those numbers.

**Open questions carried from the research** (also §6, §7):
- **Magenta** (Groove MIDI / GrooVAE / Performance RNN) representation — the closest
  modern precedent (per-note timing-offset + velocity vs a learned "groove
  embedding") — was **not** among the surviving verified claims; resolve before
  committing the *implementation*, not the framing.
- **Unmetered time model** — no single "offset from grid" representation spans
  metered and unmetered (§6).
- **Inter-part ensemble phase** (one-drop bass-vs-kick, behind-the-beat funk) —
  per-part-pair vs per-part-against-shared-reference was not settled (KTH's
  Ensemble-swing models it only narrowly).

---

## 4. The authoring model — the performance profile

A **performance profile** is the declared intent (the ruler's input); the
realization is computed. Authored **per-part**, modulated **per-section**.

**4.1 Profile components**
- **Genre groove-baseline** — a named, reusable profile carrying the characteristic
  deviations of an idiom (reggae one-drop drag, jazz swing, funk/Motown behind-the-
  beat pocket, straight/tight, romantic rubato). **Energy-INDEPENDENT** (a sleepy
  reggae verse still drags). Per §3.9, genre-specific and coupled to sound.
- **Magnitude `k`** (KTH; default 1) — the single tuning dial scaling the profile's
  strength. Small / genre-calibrated, never maximized (§3.9).
- **Energy/harmony coupling** — the macro intensity (push/tighten/crescendo) is
  **derived** from the energy curve; dynamics may read harmonic tension. **Not
  re-authored** (§5).
- **Deliberate overrides** — decouple a part from its energy-default where the art
  demands (the convention-break — reggae groove through a HEAVY amp — is the
  template).

**4.2 Parameter set** (§3.2): **timing** (onset deviation from grid; swing ratio;
ensemble offset), **dynamics** (per-onset velocity / loudness), **articulation**
(offset-to-onset duration; staccato↔legato; micropauses). Optional: **intonation**
(cents — for pitched-continuous instruments), **timbre** (genre couples feel to
sound; mostly the sound-design subsystem's concern).

**4.3 Two grains, one parameter set** (§3.3, §3.10): **per-note deviations** for
discrete parts (drums, bass, riffs, rap onsets) **and** continuous **time-shape
curves** for sustained/legato/rubato parts. A complete part ≈ a per-position trend +
a per-note local deviation.

**4.4 Realization — structured deterministic + correlated noise** (§3.7, §3.8):
1. **Generative (deterministic):** the genre profile's characteristic offsets +
   structure-derived shaping (phrase-arch, ensemble lock) — the bulk of the feel.
2. **Random (small, additive, CORRELATED):** a **1/f** noise supplement for
   breathing — **never white noise**. This is the line between *human* and either
   *mechanical* (no noise → a precisely-shifted grid) or *sloppy* (white/large noise).
3. Magnitude small and genre-calibrated (§3.9).
This is the GERM decomposition; the LLM authors the profile (the *what*), the ruler
realizes it (the *how*). **No learned model is required** — and the prefer-LLM-over-
deterministic-module principle is honored: intelligence lives in the profile choice,
not a trained net.

> **The seed already exists.** The reggae/metal generators' baked `lazy` / `lag` /
> `push` defaults are *proto-profiles* (a fixed deterministic offset per idiom). The
> performance layer generalizes them into declared, named, magnitude-scaled profiles
> + the additive 1/f layer + the read-side lens.
>
> **Shipped (phase 2b, first primitive).** `performance.realization` —
> `PerformanceProfile(name, timing_sigma, velocity_sigma, k, seed)` +
> `apply_profile(notes, profile, *, seed)` — realizes the **additive 1/f layer**
> (correlated timing + velocity breathing) over a finished part, deterministically.
> It does NOT re-author the constant lay-back (the generators keep that — one
> source of truth); it adds the GERM "Random" channel that the deterministic
> `feel`/`lazy`/`push` cannot. Closed-loop test: a mechanical part run through a
> profile is read `human` by the §7 lens. The *declared genre-baseline as a profile
> field*, the energy-coupling (§5), and phrase arcs (§4.3) remain follow-ons.

---

## 5. The energy ↔ performance coupling (formalized)

The user's insight, now load-bearing and research-backed (§3.4, §3.5): there is
**score-energy** (orchestration density, register, harmonic tension — already how
the energy curve is realized compositionally) and **performance-energy** (the
players pushing, tightening, swelling). A section building tension shows in **both**.

**Decision:** **energy is the single authored intensity intent**, with **two
realization channels**:
- **Compositional channel** — density/register/harmony (the existing "successive
  orchestration" build).
- **Performative channel** — the macro tempo-loudness trajectory (the Performance
  Worm), **derived from the energy curve** (build → push + crescendo + tighten).

Performance therefore **reads energy** (and harmonic tension) and **adds** the
genre groove-baseline (energy-independent) + local expression + overrides. It does
**not** introduce a competing intensity dial — *one source of truth, no inconsistent
triple* (the same discipline as the energy-derivative decision in
`arrangement-model.md`). Overrides are where the art decouples the channels (calm-
but-tense; frantic-but-quiet).

---

## 6. Scope boundary — METERED-only (a documented limitation, not a flaw)

Every foundational model here (KTH, the Performance Worm, basis-function models, the
ASAP-style datasets) measures deviation **against a metric grid**. **Gregorian chant
(unmetered), free rubato, and rap-flow (speech-rhythm) have no fixed grid to deviate
from** — *the research's central caveat: a single "offset from the grid" time model
does NOT cleanly span metered and unmetered music.* The score-vs-performance split
survives if recast as conceptual-plan vs realization (§3.1), but the **time base**
must fork: grid-relative for metered; absolute-time + reference-pulse or
onset-sequence for free — **under the same expression parameters** (timing relations,
dynamics, articulation generalize; only the time base changes).

**Decision: metered-first.** The performance layer covers metered music — reggae,
metal, jazz/swing, funk/Motown, most pop, rap-on-a-grid. **Unmetered / free-time
performance is out of current scope: a known, documented limitation, NOT a defect.**
Users should understand: *performance/feel authoring is grid-relative; truly
unmetered traditions degrade gracefully to the raw note floor* (`_note`). The
free-time model is **future research** — designed and built only when chant / free
rubato actually forces it (*discovered-from-friction*). Mirrored in
`project-state.yaml` `scope.later`; tracked in `backlog ARR-2B6K` (unmetered
boundary) and `ARR-8P5K` (axis investigation).

---

## 7. The measurement model — the performance lens (the other half)

Per principle 4 (both sides), the read side is co-equal with authoring. It answers
*"is the rendition doing what the profile intended?"* and makes **"human, not
sloppy" measurable**, classifying every part as:
- **mechanical** — near-zero / flat deviation (a constant-offset shifted grid; flat
  velocity — e.g. an organ at one velocity across hundreds of notes),
- **human/grooving** — *structured, correlated* (≈1/f) deviation + the right
  inter-part phase,
- **sloppy** — high-variance *uncorrelated* (white) jitter.

**Two feeds** (mirrors harmony's symbolic lint + the audio mix-check):
- **Symbolic lens (primary, build-time) — SHIPPED (phase 2a).** Runs on the
  authored notes (exact onsets + velocities), `src/hallucinote/performance/`,
  fed by `arrangement.Arrangement.section_perf_inputs()` (parallel to
  `section_lints`). Measures per-part deviation **structure** (mean = lay-back/
  push; variance = looseness; the **1/f-correlation metric** = human-vs-sloppy —
  **lag-1 autocorrelation primary, DFA α on long series**, because calibration
  showed DFA is unreliable below N≈48; `correlation.py`), **flat-dynamics**
  detection + articulation (`dynamics.py`), and **inter-part ensemble** lock/
  pocket (`ensemble.py`). Cheap, exact, render-independent — sits beside the
  harmony conformance lint and is the only timing/dynamics feed available without
  a render. Classifies each part **mechanical / human / sloppy / insufficient-
  data**; findings are `info` coaching questions, never verdicts (authored feel is
  not error). **Deferred to 2b:** conformance to a *declared* profile + the
  energy-coupling read — they need the authoring-profile object (§4) that 2b
  builds; today the lens reads what's authored, not what was *declared*.
- **Audio ground-truth (secondary)** — the **existing** `audio/timing.py`
  (`analyze_timing_window` → `PartTiming`: per-part onset-vs-grid feel, swing ratio,
  confidence) + `audio/cross_rhythm.py` (inter-part phase; already distinguishes a
  *constant offset* from *jittered noise*). Its irreplaceable value the symbolic
  feed cannot give: **perceived onset** (a slow-attack pad *feels* late even when the
  note-on is on-grid) and verification that the authored feel **survived to the
  actual sound**. Needs a **modest** extension — the **1/f-correlation metric** + per-
  onset dynamics — not a rebuild.

Findings are framed against intent (the masking-analyzer shape): *"you declared a
loose reggae pocket; the organ bubble is mechanically flat (one velocity, zero
timing structure)."*

---

## 8. Phased delivery plan

Strictly sequenced (per the user, 2026-05-30):

1. **Document & integrate (THIS artifact + the taxonomy + the manifest + scope) —
   DONE when this lands.** The research is a native part of the platform's design
   and planning materials, reference-backed, not an add-on.
2. **Platform implementation (friction-driven).** Build incrementally, discovered
   from real need (the *discovered-from-friction* discipline): (a) **DONE** — the
   symbolic performance lens (read side first — quantifies the gap, needs no Live):
   `src/hallucinote/performance/` (lens + correlation + dynamics + ensemble),
   wired into `/mix-review`; (b) the performance-profile authoring surface —
   **first primitive DONE** (`realization`: `PerformanceProfile` + `apply_profile`,
   the declared magnitude-scaled profile + the additive **1/f breathing** layer,
   closed-loop-validated against the §7 lens); **still open** — the genre-baseline
   as a declared profile field + the energy-coupling read (§5); (c) extend
   `audio/timing.py` / `cross_rhythm.py` with the 1/f metric + perceived-onset;
   (d) resolve the open questions (§3) — the Magenta representation review,
   ensemble-phase representation.
3. **Bring it to a song.** Apply to sun-zone-done (the flagship already strains it —
   the constant-offset finding + the flat organ + the rhythmic-collision work in
   `songs/sun-zone-done/decisions/07`) and tune by ear. **Partial:** the lens now
   RUNS on sun-zone-done (regression-locked in its tests — it reproduces the flat
   organ + the feels-quantized mechanical timing, and reads the white-jitter drums
   as *sloppy*); and the 2b authoring primitive now EXISTS to fix them. The actual
   *tune-by-ear* pass on the flagship (which `apply_profile` to which parts, at what
   `k`) is a creative decision left for the user's ear — deliberately not auto-applied.

Out of band, fed by genres rather than pre-built: **meter-feel** as a structure
axis (the grid swing deviates from), **text/lyric/flow** as a subsystem (rap, chant),
and the **unmetered time-base fork** (§6).

---

## 9. References

Adversarial-verification provenance: 24/25 verified claims, all on the primary
sources below; no blog/marketing source carries a finding.

- **[Cancino-Chacón/Widmer 2018]** Cancino-Chacón, Grachten, Goebl & Widmer (2018).
  *Computational Models of Expressive Music Performance: A Comprehensive and Critical
  Review.* Frontiers in Digital Humanities 5:25. — the field's canonical review;
  the canonical parameter set + multi-level framing.
  https://www.frontiersin.org/journals/digital-humanities/articles/10.3389/fdigh.2018.00025/full
- **[Palmer 1997]** Palmer, C. (1997). *Music Performance.* Annual Review of
  Psychology 48:115–138. — the score-vs-performance cognitive/motor domain.
  https://www.annualreviews.org/content/journals/10.1146/annurev.psych.48.1.115
- **[Friberg/Bresin/Sundberg]** The KTH rule system / **Director Musices** (Friberg,
  Bresin & Sundberg). — concrete per-note rules for timing, dynamics (dB),
  articulation, tempo curves, intonation; the **metaperformer** `k` pattern.
  https://www.diva-portal.org/smash/get/diva2:1246181/FULLTEXT01.pdf
- **[Dixon/Goebl/Widmer 2002; Langner & Goebl 2003]** *The Performance Worm: Real-
  Time Visualisation of Expression based on Langner's Tempo-Loudness Animation* (ICMC
  2002) / Computer Music Journal. — the 2-D tempo-loudness trajectory ("≈ a 2-D
  energy curve").
  https://www.researchgate.net/publication/2534712 ·
  https://journals.sagepub.com/doi/10.1177/102986490500900101
- **[Widmer & Goebl 2004]** Widmer & Goebl (2004). *Computational Models of
  Expressive Music Performance: The State of the Art.* Journal of New Music Research
  33(3). — multi-level performance as a linear combination of expressive shapes.
- **[Cancino-Chacón/Grachten/Widmer 2017]** (2017). *An Evaluation of Linear and Non-
  Linear Models of Expressive Dynamics…* Machine Learning 106. — basis-function
  decomposition (per-position trend + per-note deviation); learnable structure.
  https://link.springer.com/article/10.1007/s10994-017-5631-y
- **[Hennig et al. 2011]** Hennig et al. (2011). *The Nature and Perception of
  Fluctuations in Human Musical Rhythms.* PLOS ONE 6(10):e26457. — the 1/f finding +
  the matched-magnitude listening preference. (Replication: Sogorski/Geisel/
  Priesemann 2018; mechanism dispute: Colley & Dean 2019.)
  https://pmc.ncbi.nlm.nih.gov/articles/PMC3202537/
- **[Iyer 2002]** Iyer, V. (2002). *Embodied Mind, Situated Cognition, and Expressive
  Microtiming in African-American Music.* Music Perception 19(3):387–414.
  https://online.ucpress.edu/mp/article/19/3/387/61913/
- **[Danielsen et al. 2023]** Danielsen et al. (2023). *Shaping Rhythm: Timing and
  Sound in Five Groove-Based Genres.* Popular Music (RITMO). — groove = genre-typical
  configs of temporal AND sonic features.
  https://www.cambridge.org/core/journals/popular-music/article/BBC410F9849DB982AEBFACEA14D38F32
- **[Juslin/Friberg/Bresin 2002]** Juslin, Friberg & Bresin (2002). *Toward a
  computational model of expression in music performance: The GERM model.* Musicae
  Scientiae. — Generative + Emotional + Random(1/f) + Motion; random as a separate
  additive term.
- **[Madison 2011; Davies 2013; Senn et al. 2016]** Controlled-listening groove
  studies — the magnitude counter-current (exaggerated microtiming lowers groove).
  https://www.frontiersin.org/journals/psychology/articles/10.3389/fpsyg.2015.01232/full ·
  https://www.nature.com/articles/s41598-019-55981-3
- **[Ohriner 2019]** Ohriner. *Music Theory Online* 25.1 — rhythm/flow analysis
  (relevant to the future rap-flow subsystem).
  https://mtosmt.org/issues/mto.19.25.1/mto.19.25.1.ohriner.html
- **[ASAP / Kosta TENOR 2018]** Expressive-performance MIR datasets (aligned score↔
  performance; MazurkaBPM). https://github.com/fosfrancesco/asap-dataset ·
  https://www.tenor-conference.org/proceedings/2018/12_Kosta_tenor18.pdf
- **[Magenta — UNVERIFIED in this pass]** Gillick et al. (2019), *Learning to Groove
  with Inverse Sequence Transformations* (GrooVAE / Groove MIDI Dataset);
  Performance RNN. Closest modern per-note-deviation+velocity precedent — review
  before implementation (§3 open questions). https://arxiv.org/abs/1905.06118 ·
  https://magenta.tensorflow.org/groovae

---

*This artifact is the owner doc for the performance realization layer. It folds into
`arrangement-model.md` (§ The dimension taxonomy), `project-state.yaml`
(`scope.later` + `artifact_manifest`), and `backlog` ARR-8P5K / ARR-3R8F / ARR-2B6K.
Related: [`intent-architecture.md`](intent-architecture.md) (the measurement↔intent
loop the read-side lens plugs into — the performance lens sits beside the harmony
conformance lint) and [`../../docs/song-authoring-conventions.md`](../../docs/song-authoring-conventions.md)
§ Per-part feel (the per-call `feel` proto-profile this generalizes). Status
advances to "in build" only when phase 2 begins.*
