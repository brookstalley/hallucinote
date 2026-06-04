# MEL-1A7K — Phase 2b Research: the MOTIVIC / PHRASE angle (pass 3)

**Stage:** RESEARCH (design-only; no production code).
**Directive:** DEEP + adversarially verified, house deep-research bar. Targets the
angle a prior pass (`melody-model.md` §3.C) returned **no surviving claims** on:
motivic transformation/economy (Réti, Schoenberg), phrase structure (Caplin), grouping/
segmentation (GTTM, LBDM), and motivic/repetition memorability. Goal: inform (i) the
declared melodic-PROFILE vocabulary and (ii) a principled, *computable* MOTIVIC-ECONOMY
metric — or honestly confirm the angle resists computation.

**Method.** 8 web searches across the 4 sub-angles + adversarial counter-searches;
fetched + locally text-extracted **5 primary PDFs** (the WebFetch summarizer could not
read the binary PDFs, so each was `pdftotext`-extracted and read directly — exact
tables/figures below are from the extracted text, not a summary). Each claim carries a
confidence and the three caveats the brief demands: **measurable-from-a-symbolic-line?**,
**perceptually-validated?**, **genre-bound?**.

---

## Headline (the design-shaping result)

**The prior pass's §3.C "no surviving claims" was too pessimistic — but only because
it framed the angle as "is there a validated *theory of motivic development*." Framed
as "is there a *computable, perceptually-grounded structural fact about repetition and
phrasing*," pass 3 finds a small set of GENUINELY operationalizable findings — and an
equally important set of honest NULLs.** The pattern is sharp and it is itself the
finding:

- **Segmentation (grouping)** → **computable AND benchmarked**. Local boundary models
  (LBDM/Grouper) and the statistical IDyOM run from a bare monophonic pitch+IOI+rest
  sequence, are deterministic/corpus-light, and have *measured* agreement with human
  phrase marks (best mean F1 ≈ 0.66, ceiling set by inter-annotator F1 itself ≈ .14–.82).
  **C1–C3.**
- **Motivic economy as compression / repetition** → **computable, with a real but
  NARROW perceptual anchor**. The *simplicity/efficient-encoding* hypothesis is corpus-
  validated and the within-melody repetition structure is computable; BUT the only
  *perceptual* compression validation is for **pairwise melodic SIMILARITY (NCD)**, not
  for an intrinsic single-line "economy score." **C4–C6.**
- **Motivic-rarity / repetition as a MEMORABILITY lever** → **the prior KILL HOLDS**.
  Re-checked on the primary source: m-type (repetition) features were computed and lost
  to global-contour + tempo. **C7 (a confirmed null).**
- **Réti developing-variation / Caplin sentence-period** → **resists computation from a
  bare line** (Réti is non-falsifiable by its critics; Caplin is harmony/cadence-bound).
  **C8–C9 (confirmed nulls — they shape the profile-relative design).**

**Net for the design:** the motivic-economy reading should be a **descriptive,
profile-relative repetition/compressibility ruler** (substrate fact, never a verdict),
explicitly NOT a "this melody is too samey / too wandering" score — exactly the §1
substrate+profile thesis, now backed on its weakest dimension. The phrase-arc / sentence-
period parts of the profile vocabulary should be **declared intents the lens reports
against**, not computed classifications, because the classification resists computation.

---

## Verified claims (ranked by confidence)

### Angle 3 — GROUPING / SEGMENTATION (the strongest, most measurable angle)

**C1 — Automatic melodic phrase segmentation works from a bare symbolic line, and its
agreement with human phrase marks is *measured*. Best mean F1 ≈ 0.66.** *(HIGH.)*
The canonical comparative evaluation (Pearce, Müllensiefen & Wiggins, ISMIR 2008 →
*Melodic Grouping in MIR*, 2010) ran on a 1705-melody subset of the **Essen Folksong
Collection** (78,995 events, ~46 events/melody, ~12% of notes pre-boundary) with folk-
expert phrase annotations as ground truth. Results, in order of mean F1 (extracted Table 1):

| Model | Precision | Recall | F1 |
|---|---|---|---|
| **Hybrid** (Grouper+LBDM+GPR2a+IDyOM, logistic-regr.) | 0.87 | 0.56 | **0.66** |
| **Grouper** (Temperley) | 0.71 | 0.62 | 0.66 |
| **LBDM** (Cambouropoulos, k=0.5) | 0.70 | 0.60 | 0.63 |
| **IDyOM** (statistical, k=2) | 0.76 | 0.50 | 0.58 |
| **GPR2b** (a single GTTM rule alone) | 0.47 | 0.42 | 0.39 |

Sign tests between per-melody F1 were significant at α=0.01 (except GPR2a vs LBDM).
- **Measurable from a symbolic line?** YES — inputs are pitch interval, inter-onset
  interval (IOI), and rest; nothing else.
- **Perceptually validated?** YES, against expert annotations; and Thom et al. (2002)
  found *human output cannot be distinguished from three of the algorithms (Grouper,
  IDyOM, LBDM)*.
- **Genre-bound?** Trained/tested on folk monophony; generalization to riffs/EDM hooks
  unverified, but the rules (proximity, change) are genre-general Gestalt.
- Source: https://ismir2008.ismir.net/papers/ISMIR2008_228.pdf (and the archived copy
  https://archives.ismir.net/ismir2008/paper/000228.pdf).

**C2 — The LBDM is a *purely local, deterministic, corpus-free* boundary detector — the
cheapest stdlib-implementable segmenter, and the right one for our core.** *(HIGH.)*
Cambouropoulos's LBDM (ICMC 2001) combines a **change rule** (boundary strength ∝ the
degree of change between consecutive *pitch interval / IOI / rest* values) with a
**proximity rule**, normalizes, and picks local peaks above a weighted-mean threshold.
No training, no corpus, fully deterministic — it fits the stdlib-only, render-free core
exactly as `melody.intervals` already does. Original eval: recall 63–74% of a musician's
score-marked boundaries (precision ~55%, threshold-dependent) — consistent with the
0.70/0.60/0.63 in C1.
- **Measurable?** YES, trivially (it's arithmetic over the interval/IOI/rest sequences).
- Sources: the model is described in the C1 paper §2.2; original ICMC 2001 paper
  (text via http://ikee.lib.auth.gr/record/297382 — 401 on direct fetch, but its method
  is reproduced verbatim in the C1 source). A formal restatement:
  https://hal.science/hal-02986464/document

**C3 — A statistical learner with NO music-theoretic rules (IDyOM) segments about as
well as the best rule-based models — confirming melodic structure is largely
*surface/expectation-driven*, recoverable without a grammar.** *(HIGH.)* IDyOM marks a
boundary where a note's information content (unexpectedness) spikes; it equalled the
rule-based models (F1 0.58 vs 0.63–0.66) and the hybrid of all four beat any single one.
This is the §3.1–3.2 IDyOM thesis re-confirmed at the *phrase* level. *Caveat:* IDyOM
needs a training corpus and an ML stack — **out of scope for the stdlib core** (same
verdict the model already records for "IDyOM vs proxies," §7 design note); cite it as the
theory that justifies the cheap local proxy (LBDM), not as something we ship.
- Source: same as C1.

### Angle 1 — MOTIVIC ECONOMY as compression / repetition

**C4 — "A melody is encoded efficiently by exploiting its repeated patterns" is a
corpus-validated compositional reality, and the repetition structure is computable —
but the *strong* perceptual validation of compression is for PAIRWISE similarity, not an
intrinsic single-line score.** *(HIGH for the split; this is the decisive design fact.)*
Two threads:
  - **Pairwise (validated perceptually):** Pearce & Müllensiefen (2017) model human
    melodic-**similarity** ratings with **Normalised Compression Distance (NCD)** —
    "the length of a compressed encoding of x *given a model trained on y*." NCD is a
    metric *between two melodies*; the normalised symmetric form best fit perceived
    similarity and was competitive on the MIREX-2005 similarity task. It is **NOT** an
    intrinsic "how economical is this one line" measure.
    Source: https://www.marcus-pearce.com/assets/papers/PearceMullensiefen2017.pdf
  - **Intrinsic (corpus-validated, not yet perceptually):** Temperley (2024, *Melodic
    Pattern Repetition and Efficient Encoding*, EMR 18(2)) tests three hypotheses about
    *within-melody* repeated intervallic patterns on Essen (6,208 songs) + Barlow-
    Morgenstern (9,788 themes) and confirms all three: repeated intervallic patterns
    tend to be (1) **metrically parallel** (same metric position), (2) **short-distance**
    (long-distance repeats add scale-degree, not pure-interval, identity), and (3)
    **multi-interval** (≥2 intervals, not a single repeated interval). r=.98 (B&M) /
    .84 (Essen) for the doubling-distance ↔ parallelism relationship, p<.05.
    Source: https://doi.org/10.18061/emr.v18i2.9289 (text extracted from
    https://pdfs.semanticscholar.org/e678/886bf6aa13959d1265a11bd1d578a46e73fa.pdf)
- **Design read:** a motivic-economy ruler CAN compute intrinsic repetition (n-gram
  self-similarity / a within-line compression ratio / interval-pattern recurrence), and
  Temperley tells us *what kind* of repetition is musically real (metrically-parallel,
  short-distance, multi-interval — these are the right features to count). But because
  the only *perceptual* compression anchor is pairwise, the intrinsic number must ship as
  a **descriptive fact graded against the profile's declared repetition appetite**, never
  a universal "economical = good." This is precisely the lens's existing honesty stance.

**C5 — Geometric pattern discovery (SIATEC / COSIATEC / SIATECCompress) computes maximal
repeated patterns by *compression*, and compression-ratio correlates with how well the
discovered patterns match human-analyst patterns — but the task is HARD (best symbolic-
monophonic three-layer F1 ≈ 0.68) and the algorithms are heavyweight.** *(HIGH for the
numbers; MEDIUM that it's worth implementing.)* Meredith's family represents a melody as
a point-set (onset, pitch); SIATEC finds **maximal translatable patterns (MTPs)** and
their **translational equivalence classes (TECs)**; COSIATEC/SIATECCompress select TECs
to maximally compress, ranking by **compression ratio + compactness**. On the JKU
Patterns Development Database:
  - SIATECCompress avg F1 ≈ **50%** over 5 pieces; COSIATEC hit **71% (Beethoven)** /
    **60% (Mozart)**; on a Bach-fugue task SIATECCompress ≈ 30%, and there was a **strong
    correlation between compression factor and F1** (compressing better ⇒ matching human
    patterns better). Source: http://www.titanmusic.com/papers/public/MeredithOHSI2018.pdf
  - MIREX 2014 (independent benchmark, symbolic monophonic): best establishment F1 0.926,
    occurrence F1 0.855, but **three-layer F1 only 0.679**; organizers: "discovery of
    repeated *sections* was addressed well … *themes and motifs required more attention*"
    — i.e. fine-grained motif discovery is the unsolved part.
    Source: https://music-ir.org/mirex/wiki/2014:Discovery_of_Repeated_Themes_&_Sections_Results
- **Measurable?** YES but **expensive** (SIA family is ~O(n²) in memory/time over the
  point-set; recent work explicitly studies its memory usage). For a *short single hook*
  it's tractable, but it is far heavier than the stdlib n-gram/LBDM path.
- **Genre-bound?** Validated on classical; the geometry is genre-general.
- **Design read:** the compression-ratio-as-economy idea is *principled* (Kolmogorov-
  complexity grounding, C6) and *measurable*, but COSIATEC is over-engineered for our
  need. **Prefer the cheap proxy** (Temperley-informed n-gram repetition / a bzip-style
  within-line compression ratio), name COSIATEC as the heavyweight theory — mirroring the
  lens's existing "IDyOM is the theory, n-gram is the proxy" pattern exactly.

**C6 — The theoretical justification for "compressibility ≈ structure" is Kolmogorov
complexity + the perceptual *simplicity principle*; this is a respectable grounding, not
hand-waving.** *(MEDIUM-HIGH.)* Meredith (2018) grounds music analysis in Kolmogorov
complexity (the shortest program that reproduces the object) via Chater's (1996)
reconciliation of the simplicity and likelihood principles: "the perceptual system
chooses the simplest organization it is able to construct." So a compression-based
economy reading isn't arbitrary — it operationalizes a cognitive principle.
- *Caveat:* Kolmogorov complexity is **uncomputable** in general (Meredith says so
  explicitly); every practical measure (LZ77, bzip2, COSIATEC) is an *approximation*, and
  the simplicity principle is a *framework*, not a per-melody verdict. Cite it as the
  "why a repetition ruler is principled," never as "this melody scored 0.7, therefore X."
- Source: http://www.titanmusic.com/papers/public/MeredithOHSI2018.pdf

### Angle 4 — MEMORABILITY via motivic/repetition features

**C7 — CONFIRMED NULL (the prior KILL holds): motivic/repetition (m-type) features do
NOT predict earworm likelihood; the predictive melodic features are global CONTOUR and
turning-point gradient, plus tempo.** *(HIGH — verified directly on the primary source's
results section.)* Jakubowski, Finkel, Stewart & Müllensiefen (2017) computed **all
83 features including the FANTASTIC second-order m-type repetition features**
(`mtcf.mean.productivity`, mean m-type entropy, mean Yule's K — "the rate at which
musical m-types are repeated"). A random-forest variable-importance selection kept the
**top three**: `dens.step.cont.glob.dir` (commonness of *global contour*),
**tempo**, and `dens.int.cont.grad.mean` (commonness of *turning-point gradient*).
**No m-type / repetition feature survived into the top predictors.** Cross-validated
melody-only classification: **62.5%** (chance 50%); in the logistic regression only the
global-contour variable reached p<.05 (7.08, p=.03); tempo was not significant in that
model. INMI tunes: faster tempo (M=124.10 bpm), MORE common global contour, LESS common
turning-point gradient.
- This is a genuine *negative* result for "motivic rarity/repetition drives
  memorability," computed on the very features the prior pass killed 0-3. **The kill
  stands.**
- *Caveat on the sibling kill ("lyrics/chorus dominate earworms"):* this paper's design
  *did not distinguish* sections and *extracted the chorus* as the canonical excerpt —
  so it neither supports nor refutes chorus-dominance; the kill should remain "not
  established," not "refuted." (The chorus-as-INMI-content claim lives in other work
  the prior pass already rejected.)
- Source: https://www.apa.org/pubs/journals/releases/aca-aca0000090.pdf

**C7-adjacent — weak, opposite-direction signal worth noting, not relying on.**
*(LOW.)* The Jakubowski lit review cites Eerola et al. on explicit memory: "explicit
memory was enhanced for tunes that [repeat] … however *less* repetition of motives, a
smaller average interval size, simple contour, and complex rhythms" aided memory in some
analyses — i.e. the repetition↔memory link is **inconsistent in sign** across studies.
Do not author a "more/less repetition ⇒ catchier" rule. Reinforces: repetition is a
profile-relative appetite, never a memorability optimizer.

### Angle 2 — PHRASE STRUCTURE (Caplin sentence-period) — confirmed NULL for computation

**C8 — Caplin's sentence/period theory of formal functions is NOT computable from a bare
monophonic pitch+rhythm line: it is defined by *harmony and cadence*, which a single line
does not carry.** *(HIGH — this is a structural fact about the theory, adversarially
robust.)* Caplin (1998, *Classical Form*) builds theme-types on Schoenberg's "basic idea"
+ tight-knit/loose design and **beginning/middle/end functions realized by harmonic
progression and cadence** (e.g. a period's antecedent ends on a half cadence, the
consequent on a PAC). The distinguishing evidence is cadential/harmonic, not melodic-
contour. No validated classifier assigns sentence-vs-period from a bare line; even the
*harmony-aware* computational form literature struggles — Roman-numeral analysis has not
exceeded ~50% accuracy in general, and "no existing studies … annotate substantial corpora
… closely capturing human annotators" for form.
- **Measurable from a symbolic *monophonic* line?** **NO** — the discriminating features
  (cadence type, harmonic function) are absent from a single line.
- **Design read:** put phrase-architecture into the profile as a **DECLARED intent**
  ("sentence-like fragmentation into the cadence" / "antecedent-consequent pairing") that
  the lens *reports observations against* (e.g. "you declared a sentence; the line does
  fragment in its 2nd half — the durations halve") — NOT a classification the lens
  computes and verdicts. This is the §1 substrate+profile thesis applied to phrasing.
- Sources: https://global.oup.com/academic/product/classical-form-9780195143997 ;
  theme-type taxonomy https://jameshepokoski.com/wp-content/uploads/2021/07/2020-rev.-from-2006-2008-The-Classification-of-Theme-Types-Period-Sentence-Hybrid-.pdf ;
  form-computation difficulty https://arxiv.org/html/2407.21130v1

**C8b — The "melodic arch" phrase shape IS measurable and corpus-attested as a
*statistical tendency* — but the existing lens already captures it, and §3.7 already
records its style-specificity.** *(HIGH.)* Huron (1996, *The Melodic Arch in Western
Folksongs*, Essen 6,000+ songs): phrases disproportionately ascend then descend
(inverted-U); melodic pitch declination is ~1/10 that of speech; skips tend toward
tessitura extremes, then reverse (the gap-fill the lens already reads). **This adds no
new measurable beyond `contour.contour_shape` + `apex` + `post_skip_reversal` already
shipped** — it *re-confirms* them and confirms arch is a *phrase-level* tendency, so the
right new move is to compute the existing contour facts **per LBDM-segmented phrase**, not
just per section. Source: https://www.academia.edu/50292501/The_Melodic_Arch_in_Western_Folksongs

### Angle 1 (Réti/Schoenberg) — confirmed NULL for a verdict-bearing metric

**C9 — Réti's "thematic process" / developing-variation analysis resists computation
because its own discipline judges it *non-falsifiable and analyst-subjective*; the modern
formalizations are pitch-cell transformation toolkits, not validated economy metrics.**
*(HIGH — the critique is the consensus.)* Réti (1951) claims "there is nothing in a piece
but what comes from the theme," but the standard critique is a "lack of methodology …
relies on the analyst's subjectivity … any two melodies can be related," and he disregards
rhythm/tonality. Schoenberg's developing-variation/Grundgestalt is a generative
*compositional* principle, not a measurement. Modern computational responses (Mazzola-style
topological formalization of Réti; a UWO thesis modelling intervallic transformations in
early Schoenberg) build **transformation toolkits over ordered pitch/duration intervals** —
which is *exactly the six variation ops the arrangement layer already ships*
(`generators.variations`: transpose/invert/retrograde/augment/diminish/fragment) — not a
"how economical is this melody" score.
- **Design read:** there is **no developing-variation metric to build**; the
  *transformation ops* (the authoring rulers) already exist and melody reuses them, exactly
  as `melody-model.md` §3.C / §4 already states. The motivic-DNA part of the profile is a
  **declared cell + which ops generate the line**, measured by C4/C5 repetition readings,
  not by a Réti classifier.
- Sources: Réti critique survey https://en.wikipedia.org/wiki/Rudolph_Reti ;
  topological formalization https://www.tandfonline.com/doi/abs/10.1080/17459730802518292 ;
  Schoenberg motivic-transform thesis https://ir.lib.uwo.ca/etd/7620/ ;
  developing variation overview https://en.wikipedia.org/wiki/Developing_variation

---

## Adversarial verification log (what I tried to refute, and the outcome)

- **Refute C1's F1 figures** → independently corroborated by the MIREX-2014 *different*
  task (C5) and by Thom et al. (2002) "human indistinguishable from 3 algorithms" — the
  ~0.6 ceiling is consistent across sources and is itself bounded by *inter-annotator* F1
  (.14–.82). SURVIVES.
- **Refute "compression is perceptually validated for single-line economy"** → it is NOT;
  Pearce & Müllensiefen validate **pairwise NCD similarity**. The single-line claim is
  *downgraded to descriptive* (C4) — refutation succeeded against the strong form, which
  is why the design uses it only profile-relative.
- **Re-run the prior memorability KILL on the primary source** → m-type features were
  computed and lost to contour+tempo (C7). KILL HOLDS; not a stale kill.
- **Refute "Caplin is computable from a line"** → the discriminating evidence is
  harmonic/cadential, absent from a monophonic line; even harmony-aware form computation
  underperforms. NULL CONFIRMED (C8).
- **Refute "Réti gives a developing-variation metric"** → its own field calls it
  non-falsifiable; modern work yields transformation toolkits, not metrics. NULL
  CONFIRMED (C9).

**Sources that could NOT be opened/were excluded:** the ICMC-2001 LBDM PDF returned HTTP
401 (its method is reproduced in the C1 source, so the claim stands on a primary surrogate);
no blog/marketing/tutorial source carries any finding (Wikipedia is cited only for the
*existence of a critique consensus* on Réti and for the developing-variation definition,
not for any falsifiable measurement).

---

## Proposed deltas to `melody-model.md` (record-only — canonical edits happen later under Critic)

These are PROPOSED; do not edit the canonical doc in this phase.

1. **§3.C — UPGRADE from "no surviving claims" to a nuanced result.** Replace the blanket
   "Angle C returned no surviving verified claims" with: *the THEORY of motivic development
   (Réti/Caplin/developing-variation) resists computation from a bare line (C8, C9), but
   the adjacent COMPUTABLE facts — phrase segmentation (C1–C3), within-melody repetition
   structure (C4), compression-as-economy (C5–C6) — do survive, with the caveat that
   compression is perceptually anchored only pairwise (C4) and motivic-rarity does NOT
   predict memorability (C7, kill upheld).* This is a real pass-3 result, not a hand-wave.

2. **§4 — ADD to the declared-profile vocabulary, marking computability per field.**
   - `phrase-arch` — a DECLARED intent (arch / terraced-descent / sentence-fragmentation /
     antecedent-consequent), the lens REPORTS contour facts against it (C8, C8b);
     **not a computed classification.**
   - `repetition-appetite / motivic-economy` — now backed by C4/C5: declared as
     low↔high; the lens reports an intrinsic repetition reading (n-gram self-similarity
     or within-line compression ratio) **graded against the declared appetite**, never a
     universal verdict. Note Temperley's three structural facts (C4) as *what good
     repetition looks like* (metrically-parallel, short-distance, multi-interval) — a
     coaching prior, not a gate.
   - `motif-DNA` — a declared cell + the `generators.variations` ops that develop it
     (C9: the ops already exist; there is no Réti metric to add).

3. **§7 — ADD a motivic-economy reading + a phrase-segmentation step, both as the cheap
   proxy with the heavyweight theory named** (mirrors the existing IDyOM-vs-n-gram note):
   - Ship **LBDM** (C2) as the stdlib phrase segmenter (pitch-interval / IOI / rest change
     + proximity; deterministic; no corpus); name **IDyOM/Grouper** as the benchmarked
     theory (C1, C3). Then compute the existing contour facts **per phrase**, realizing
     C8b's "arch is a phrase-level tendency."
   - Ship a **within-line repetition / compressibility** reading (n-gram self-similarity or
     a bzip-style ratio) as the motivic-economy proxy (C4); name **COSIATEC + Kolmogorov
     simplicity** as the heavyweight theory (C5, C6). Report it as a profile-relative fact.
   - Record the **C7 null explicitly** in the design note: do NOT add a "make it catchier"
     repetition lever — motivic-rarity does not predict memorability.

4. **§3.B — keep the memorability kill, and tighten the chorus/lyrics caveat** per C7:
   the Jakubowski design extracted the chorus and didn't separate sections, so it is
   *silent* on chorus-dominance, not evidence for it.

## Proposed build-plan signals (for the next phase, not this one)

- **Thin-vertical-slice first chunk:** LBDM segmenter + per-phrase contour facts +
  a within-line repetition number, wired into the existing `MelodicLine` / `melody_report()`
  as new REPORTED fields (info-only, no verdict) — validated on sun-zone-done's two hooks
  (`_reggae_lead_chillin`, `_metal_lead_no_time`, §9). All deterministic, stdlib, render-free
  — **no by-ear call needed for the readings themselves.**
- **PENDING by-ear (flag for the unattended-Live constraint):** the *profile→line grading
  thresholds* (what repetition value counts as "matches a declared high-repetition pop
  hook" vs "matches a through-composed line") are calibration parameters. Render is
  available but there is no human ear this run — so **render + measure the two hooks
  objectively and surface the numbers; do NOT guess the threshold.** The exact "how samey
  is too samey for THIS profile" is a creative lock-in left to the user's ear, exactly as
  the performance tune-by-ear pass was (model §8 step 3).
- **No melody/counterpoint GENERATOR** — every output here is a ruler/lens (C9 confirms the
  intelligence is the authored cell + declared ops; the layer carries arithmetic).

---

## Primary sources (URLs cited inline above)

- Pearce, Müllensiefen & Wiggins — *A Comparison of Statistical and Rule-Based Models of
  Melodic Segmentation*, ISMIR 2008 → *Melodic Grouping in MIR*, 2010 (Table 1 F-scores).
  https://ismir2008.ismir.net/papers/ISMIR2008_228.pdf ·
  https://archives.ismir.net/ismir2008/paper/000228.pdf
- Cambouropoulos — *The Local Boundary Detection Model (LBDM)*, ICMC 2001 (method in the
  above; formal restatement) https://hal.science/hal-02986464/document
- Meredith — *Music Analysis and Data Compression* (COSIATEC/SIATECCompress, JKU F1,
  Kolmogorov/simplicity grounding), 2018. http://www.titanmusic.com/papers/public/MeredithOHSI2018.pdf
- MIREX 2014 *Discovery of Repeated Themes & Sections* Results (independent benchmark).
  https://music-ir.org/mirex/wiki/2014:Discovery_of_Repeated_Themes_&_Sections_Results
- Conklin & Anagnostopoulou — *Segmental Pattern Discovery in Music*, INFORMS J. Computing
  18(3), 2006 (viewpoint patterns; corpus/null-model significance — a pattern's interest is
  its over-representation vs a null model, i.e. it needs a background corpus).
  https://www.ehu.eus/cs-ikerbasque/conklin/papers/1526-5528-2006-18-03-0285.pdf
- Pearce & Müllensiefen — *Compression-based Modelling of Musical Similarity Perception*,
  JNMR 2017 (NCD validated for PAIRWISE similarity).
  https://www.marcus-pearce.com/assets/papers/PearceMullensiefen2017.pdf
- Temperley — *Melodic Pattern Repetition and Efficient Encoding: A Corpus Study*, EMR
  18(2), 2024 (within-melody repetition: metrically-parallel, short-distance, multi-interval).
  https://doi.org/10.18061/emr.v18i2.9289
- Jakubowski, Finkel, Stewart & Müllensiefen — *Dissecting an Earworm*, Psych. Aesthetics
  Creativity & the Arts 11(2), 2017 (m-type repetition features lost to contour+tempo;
  62.5% melody-only CV accuracy). https://www.apa.org/pubs/journals/releases/aca-aca0000090.pdf
- Caplin — *Classical Form*, OUP 1998 (sentence/period defined by harmony/cadence).
  https://global.oup.com/academic/product/classical-form-9780195143997 ·
  theme-type taxonomy https://jameshepokoski.com/wp-content/uploads/2021/07/2020-rev.-from-2006-2008-The-Classification-of-Theme-Types-Period-Sentence-Hybrid-.pdf
- Huron — *The Melodic Arch in Western Folksongs*, 1996 (arch as phrase-level statistical
  tendency). https://www.academia.edu/50292501/The_Melodic_Arch_in_Western_Folksongs
- Réti critique consensus https://en.wikipedia.org/wiki/Rudolph_Reti ; topological
  formalization https://www.tandfonline.com/doi/abs/10.1080/17459730802518292 ; Schoenberg
  intervallic-transform thesis https://ir.lib.uwo.ca/etd/7620/
- Computational-form difficulty (Roman-numeral / form accuracy ceilings)
  https://arxiv.org/html/2407.21130v1
