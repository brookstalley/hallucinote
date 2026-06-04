# MEL-1A7K — Phase 2b Design: the declared melodic-PROFILE authoring side + profile-relative grading + the motivic-economy reading

**Stage:** DESIGN + BUILD-PLAN. **Item:** MEL-1A7K (area: melody), URGENT user
mandate — "approach melody the same way we did rhythm, polyrhythm, energy, and
harmony." Effort L, impact L. IN-PROGRESS: phases 1 + 2a DONE.

**No production code written here.** Canonical-doc edits to
[`melody-model.md`](../../melody-model.md) are recorded as PROPOSED deltas (§7),
not applied — Critic governs those. Research is in
[`research.md`](research.md) (this dir) and the model's §3 — **linked, not
restated** (`feedback_link_dont_summarize`).

**What 2a shipped (the read side this design extends), so we don't re-derive it:**
`src/hallucinote/melody/` — `lens.py` (the `MelodicLine`/`MelodyReport` dataclasses,
the genre-safe `active`/`static`/`insufficient-data` classify, the two `info`
findings), `contour.py`, `intervals.py`, `harmony_fit.py`; the
`Arrangement.section_melody_inputs()` adapter; wired into `/compose-review` via
`analyze_arrangement()` + `tools/melody_lens.py` + the per-song `melody_report()`
convention. The model's §1 thesis and §7 read-side are the contract this design
honors.

---

## 0. Confidence-check (the three questions)

- **Problem.** Melody has a read side (2a) but **no authoring side**: a composer
  cannot DECLARE what a line is *trying to be* (its contour intent, range, step↔leap
  appetite, harmonic freedom, repetition appetite, phrase-arc), so the lens can only
  report neutral substrate facts — it cannot answer *"is the line doing what its
  declared profile intends?"* This is the half-built BOTH-SIDES gap the harmony,
  performance, and energy dimensions each closed. Two readings are also still
  missing from the read side: **profile-relative grading** (the substrate facts read
  against declared intent) and the **motivic-economy / within-line repetition**
  reading (research C4–C6).
- **Success.** A song can declare a `MelodicProfile` per line (mirroring the proven
  `PerformanceProfile`); the lens, given a profile, returns per-line
  **profile-relative observations** ("you declared chord-tone-locked; this line is
  62% non-chord-tone — intended?") and a **profile-relative shaped-vs-aimless**
  reading that does NOT re-fire the universal-verdict bug; the lens reports a
  **within-line repetition** fact (n-gram self-similarity, Temperley-shaped); the
  revealed intent is learned back per-song **by declaring the `MelodicProfile` in
  build.py** — once declared, the line grades as matched and never re-flags, so the
  declaration IS the learn-back (no separate markdown-annotation surface this phase;
  see §1 Learn-back row + the §0 Out-of-scope bullet); all of it surfaces
  in `/compose-review`. Verifiable signal (the item's): `melody-model.md` records
  the 2b framing + a both-sides decision (the canonical edit lands as a Chunk 6
  deliverable — NOT deferred out of the item; see §7 + build-plan B1 resolution),
  and the declared-profile authoring surface + profile-relative grading both exist.
- **Out of scope.** (a) Any `melody()` / counterpoint GENERATOR — that is the stamp
  the thesis forbids (§1; research C9 confirms the intelligence is the authored cell
  + declared ops). (b) IDyOM / COSIATEC / trained-corpus machinery — named as the
  heavyweight theory, never shipped (research C3, C5, C6; mirrors the lens's existing
  "IDyOM is the theory, n-gram is the proxy" note). (c) A computed sentence/period or
  developing-variation **classification** — both resist computation from a bare line
  (research C8, C9); phrase-arc / motif-DNA enter the profile as **declared intents
  the lens reports against**, not classifications. (d) **Cross-instrument /
  arrangement-level recurrence** — that is ARR-9K4T's owned half; this item owns
  **line-level** only (§6 boundary). (e) Auto-applying a profile to sun-zone-done's
  hooks — an irreducible by-ear creative lock-in, FLAGGED PENDING (§8, build-plan).
  (f) A "make it catchier" repetition lever — research C7 confirms the memorability
  KILL holds; motivic-rarity does not predict memorability.
  (g) **A separate learn-back markdown-annotation surface.** Learn-back for melody =
  **declaring the `MelodicProfile` in build.py**; once the revealed intent is written
  down as the profile, the line grades as matched and never re-flags — the
  declaration *is* the learn-back (exactly the metaperformer "intent learned back
  per-song," with build.py as the home per memory
  `project_intent_home_rationalization`: WHAT in build.py, WHY in markdown; a
  disposable DB-annotation surface is a data-loss trap). The §1 table's *"or a
  settled 'yes that's the character' written back as a markdown annotation"* named a
  **second** mechanism — that distinct annotation surface is **deliberately
  descoped this phase**: it adds no measurement capability the profile declaration
  doesn't already give (a "yes that's the character" with no profile change is a
  no-op against the lens), and the existing per-song `melody_report()` markdown +
  build.py already carry every revealed intent the lens consumes. Revisit only if
  friction shows a need to annotate "accepted as-is" *without* declaring a profile
  (DISCOVERED-FROM-FRICTION; no speculative surface now).

**Requirements Confidence: High** (see build-plan for the one Medium assumption:
the exact profile→line grading thresholds, which are a flagged PENDING by-ear call,
not a requirements gap).

---

## 1. The both-sides shape

Melody after 2a has a **read side** and **no author side**. This is the exact state
performance was in before `realization.PerformanceProfile`, and the design mirrors
that proven move primitive-for-primitive.

| Concern | Author side (this item) | Read side (this item) |
|---|---|---|
| **What the line intends** | `MelodicProfile` — a declared, frozen dataclass of *intents* (contour / range / step↔leap appetite / harmonic-freedom / repetition appetite / phrase-arc / motif-DNA). **No notes invented.** | the lens reads each declared intent and reports the line's measured value **against** it |
| **Shaped vs aimless** | the profile's `contour_intent` + `repetition_appetite` declare what "shaped" means *for this line* | `shaped` / `aimless` / `ungraded` reading, **profile-relative** — never the universal rule that mislabeled the reggae hook (§3) |
| **Motivic economy** | `repetition_appetite` (low↔high) declares how repetitive the line should be | a within-line repetition number (n-gram self-similarity, Temperley-shaped — research C4) graded against the appetite |
| **Learn-back** | **declaring the `MelodicProfile` in build.py IS the learn-back** — the revealed intent (the chosen profile) is written down as code; once declared, the line grades as matched and never re-flags | the lens reads the declared profile and stops flagging the now-intended character (no separate markdown-annotation surface — that distinct mechanism is descoped this phase, §0 Out-of-scope (g)) |

**Why mirror `PerformanceProfile` exactly** (the proven precedent in
`performance/realization.py`): a frozen dataclass of *declared intent* + a `name` +
a `to_dict()` boundary for recording it in the song's decision corpus; validation in
`__post_init__`; the intelligence in the *declared choice* (the LLM picks the
profile / writes the line), the module carries only arithmetic. The ONE structural
difference is decisive and is the ruler-not-stamp line (§2): `apply_profile()`
*realizes* a performance profile (it computes deviations and writes them onto notes,
which is legitimate because micro-timing breathing is arithmetic, not a musical
idea); **the melodic profile has NO `apply_*` that writes pitches** — pitch *is* the
musical idea. The melodic profile is *read-only intent the lens grades against*.

---

## 2. The ruler-not-stamp boundary, made explicit

This is the load-bearing constraint for this item and the model's §1/§4 thesis.

- **A `MelodicProfile` declares INTENT; it never produces a line.** There is no
  `melody()` generator, no `realize_melody(profile)`, no "fill in the contour."
  Inventing the line is the art — `feedback_great_art_not_software`; research C9
  confirms the intelligence is the authored cell + the chosen `generators.variations`
  ops, not a Réti/economy classifier. The composer/LLM brings the line; the profile
  records what it was *for*; the lens measures *whether it is*.
- **The lens MEASURES; it never verdicts what the composer didn't ask.** Every
  finding stays `severity="info"` (the 2a contract) and every grading is framed as a
  coaching QUESTION against the declared intent. "You declared X; the line measures
  Y — intended, or drifted?" is a ruler. "This melody is bad / too samey / wandering"
  is a stamp — forbidden.
- **Profile-relative is the anti-stamp mechanism.** The 2a build-time correction
  (an early `step_fraction ≥ 0.5 → shaped else wandering` rule mislabeled the
  genuine third-based reggae hook — model §7) is precisely why the shaped-vs-aimless
  reading is *deferred to 2b and made profile-relative*. A line is graded against
  *its own* declared appetite, never a universal ideal — a chromatic bebop head, a
  third-based reggae hook, and a folk tune each read against their declared idiom.
- **The motivic-economy number is descriptive, never a verdict** (research C4, the
  decisive design fact): within-line compression is perceptually validated only
  *pairwise* (NCD), never as an intrinsic single-line "economy score," so the number
  ships as a **profile-relative repetition fact** ("you declared high repetition;
  this line repeats its 3-note cell 4× — matches"), explicitly NOT "economical =
  good." This is the §1 substrate+profile thesis on its weakest dimension.

---

## 3. The authoring object — `MelodicProfile`

Home: a new module `src/hallucinote/melody/profile.py` (leaf — depends on nothing in
`melody` except shared literals; `lens.py` imports it, never the reverse, preserving
the leaf-lens layering the 2a docstring guards). Mirrors
`performance.realization.PerformanceProfile`: frozen dataclass, `name`,
`__post_init__` validation, `to_dict()`.

```python
@dataclass(frozen=True)
class MelodicProfile:
    name: str                              # reusable declared-intent label, e.g. "reggae-hook"
    idiom: str | None = None               # a named reference point (free text): "singable-pop-hook",
                                           #   "bebop-head", "modal-chant", "riff-motif", "through-composed"
                                           #   — sets defaults a human reads; never a computed key
    contour_intent: ContourIntent | None = None   # an arch / terraced-descent / level / free PRIOR (§3.7
                                           #   continuous, never a discrete-type target). None = unstated.
                                           #   "level" matches the read-side ContourShape exactly (W2 fix).
    apex_position: float | None = None     # 0..1 where the climax is intended (early / golden / final lift)
    ambitus_min: int | None = None         # intended range floor (semitones); singability is genre-relative
    ambitus_max: int | None = None         # intended range ceiling
    step_appetite: Appetite | None = None  # low | moderate | high — proximity vs leap (§3.3/3.6),
                                           #   a bebop head (low) and a hymn (high) both valid
    harmonic_freedom: Appetite | None = None  # low (chord-tone-locked) ↔ high (freely chromatic) — the
                                           #   rate harmony-fit is graded AGAINST (§5); flattens in rock/modal
    repetition_appetite: Appetite | None = None  # low (through-composed) ↔ high (cell-driven hook) — the
                                           #   rate the motivic-economy reading is graded against (research C4)
```

**DEFERRED OUT OF v1 (W3 fix — BOTH-SIDES + DISCOVERED-FROM-FRICTION):** two fields
that appeared in the model's §4 anticipated list are **NOT** added to the v1
`MelodicProfile`, because neither has a guaranteed read side in this plan and the
design's own anti-speculative-catalog rule (this section) forbids landing
declarable-but-unread fields:

- `phrase_arch` (declared phrase-arc intent) — its only read side is per-phrase
  contour, which lives in the **OPTIONAL, friction-gated Chunk 5** (may be dropped
  entirely). A declared intent that nothing is *guaranteed* to read is an
  author-side-without-read-side BOTH-SIDES violation. **Defer until the phrase-arc
  read side is a committed (non-optional) capability** — i.e. when Chunk 5's per-phrase
  contour ships *and* the friction for an arc *intent* (not just measurement) appears.
- `motif_dna` (declared cell name(s) + which `generators.variations` ops develop it) —
  read by **no chunk in this plan**. Within-line repetition (Chunk 4) grades
  `repetition_appetite`, not `motif_dna`; cross-instrument motif recurrence is
  **ARR-9K4T's owned half** (§6). Research C9 itself concluded the ops exist but there
  is "no metric to add" — so the field is purely declarative with no lens that reads
  it. **Defer until a reading consumes it** (likely surfaces from the ARR-9K4T
  boundary work, not this line-level item).

Landing them later when their read side exists is *exactly* DISCOVERED-FROM-FRICTION;
landing them now would be the speculative catalog this section forbids. The model's
§4 anticipated list still *names* them as future intents (§7 delta 2 marks them
"declared-but-not-yet-read, deferred from the 2b profile until their read side lands"),
so nothing is silently dropped — they are explicitly scheduled, not shipped inert.

with small closed vocabularies (Literals, not magic strings):
- `Appetite = Literal["low", "moderate", "high"]`
- `ContourIntent = Literal["arch", "ascending", "descending", "valley", "level", "free"]`
  — the read-side `ContourShape` value-space *minus* `"insufficient-data"* (which is a
  measurement-only "too few notes" state, never an *intent*) *plus* `"free"` (an
  explicit "no declared shape" intent). **Every other member is byte-identical to
  `ContourShape` (verified `contour.py:28`: `["ascending","descending","arch","valley",
  "level","insufficient-data"]`)**, so a declared `contour_intent` compares directly to
  a measured `contour_shape` by string equality — no translation table (W2 fix: the
  earlier `"static"` member diverged from the measured `"level"` and would have made
  the contour grading a silent no-op on that value; `"level"` aligns them). The two
  unmatched members are intentional and asymmetric: `"insufficient-data"` is read-only
  (you cannot *declare* an intent to have too few notes), `"free"` is intent-only (a
  measured shape is never "free"). The grading reconciles them explicitly: a `"free"`
  intent suppresses the contour-divergence finding entirely (no shape was declared to
  diverge from); a measured `"insufficient-data"` shape suppresses it too (the
  `_STATIC_FINDING_MIN_NOTES` gate already prevents grading too-short lines).

(The `PhraseArch` Literal that would have typed the deferred `phrase_arch` field is
**not defined in v1** — it lands with that field when its read side ships, W3 fix.)

**Every field is `None`/empty-default optional.** A profile that declares nothing is
legal and produces zero gradings (the line reads as unconstrained substrate facts,
exactly the 2a behavior — graceful degradation, no forcing). This is the
`PerformanceProfile`-mirroring "optional sugar on top of `_note`" discipline (model
§6): nothing forces a part to declare a profile.

**Calibrated presets** (mirroring `BREATH`/`HUMAN`/`LOOSE`) — a FEW named, idiom-
anchored profiles discovered from the two sun-zone-done hooks, NOT a speculative
catalog (DISCOVERED-FROM-FRICTION). Candidates, pending the build's measurement of
the actual hooks (§8): `SINGABLE_HOOK` (arch, moderate step, low harmonic-freedom,
high repetition — the reggae lead's character) and `ANGULAR_LEAD` (free/ascending,
high leap, moderate harmonic-freedom, low repetition — the metal lead's character).
Their exact numeric edges are a PENDING by-ear call (§8) — the presets land as
*named intent* (the Literals), with any numeric thresholds surfaced-then-set, never
guessed.

### Decision-Record 1 — profile attaches per-line via `melody_report()`, NOT onto `Arrangement.section()`

- **Decision.** A song declares its profiles inside its own `melody_report()` and
  passes them to the lens as a `{layer_name: MelodicProfile}` mapping (optionally
  per-section). `Arrangement.section()` and `PlacedSection` gain **no** melodic-
  profile field; the `SectionMelody` adapter gains an optional `profiles` mapping
  parameter the lens consumes.
- **Alternatives considered.**
  1. *Add `melodic_profile=` to `Arrangement.section(layers=…)`.* Rejected:
     `Arrangement` is bookkeeping that "deliberately does NOT decide any music"
     (its module docstring) — a melodic *intent* is a creative declaration, not
     plumbing, and threading it through `_SectionSpec` → `PlacedSection` →
     materialize would couple the structure layer to a creative axis it has no other
     reason to know about. ARR-7M3D's energy lens hit the mirror of this: energy is
     ALREADY a section field and STILL never reaches the read side because it isn't
     persisted; a melodic profile is even less a structure concern.
  2. *Persist profiles to the DB.* Rejected, and this is the same architectural fact
     ARR-7M3D and the 2a read-side surface both hit: **harmony-fit already requires
     the in-memory `Progression` (not in the DB), so the lens runs build-time over
     the in-memory arrangement anyway** (model §7 *Read-side surface*). A profile is
     declared intent that "lives in git-tracked markdown / build.py"
     (memory `project_intent_home_rationalization`: disposable DB = data-loss trap;
     WHAT in build.py, WHY in markdown). So profiles ride in build.py alongside the
     line they describe.
- **Rationale.** This mirrors `PerformanceProfile` exactly — a performance profile
  is *not* an `Arrangement` field either; it is declared in build.py and applied at
  note-authoring time. The melodic profile is declared in build.py and *graded*
  at `melody_report()` time. ONE-SOURCE-OF-TRUTH: the profile lives next to the line.
- **Trade-off accepted.** The profile→line binding is by layer *name* (a string),
  so a typo means "no profile for this line" (it reads as unconstrained substrate,
  not an error). Mitigation: the lens reports declared-but-unmatched profile names
  as an `info` finding ("you declared a profile for `lead` but no such line in this
  section — typo?"), the enumerate-every-state discipline
  (`learnings.md` "Detection that replaces a user question must enumerate every
  state").

---

## 4. Profile-relative grading (the read-side extension)

The lens gains a SECOND mode: given a `MelodicProfile` for a line, it emits
**profile-relative findings** (still `info`, still questions) ON TOP OF the 2a
neutral facts (which remain unconditionally reported). Each declared field that has
a corresponding measured value produces at most one finding, fired only when the
measured value *diverges* from the declared intent *beyond a tolerance* AND there are
enough notes to trust it (the 2a `_STATIC_FINDING_MIN_NOTES` gate discipline):

| Declared field | Measured against | Finding fires when (the divergence question) |
|---|---|---|
| `contour_intent` | `contour_shape` (already computed) | declared shape ≠ measured shape (e.g. declared `arch`, measured `descending`): *"you wanted an arch; the line reads descending — intended re-shape, or did the climax move?"* |
| `apex_position` | `apex_position` (computed) | measured apex > tolerance from declared (e.g. wanted a final lift @1.0, climaxes @0.2) |
| `ambitus_min/max` | `ambitus` (computed) | measured ambitus outside the declared band |
| `step_appetite` | `step_fraction` (computed) | measured step-fraction band ≠ declared appetite band (low/mod/high mapped to fraction ranges — the PENDING by-ear edges, §8) |
| `harmonic_freedom` | `harmony.non_chord_tone_fraction` (computed) | NCT share inconsistent with declared freedom (declared `low` but 60% NCT; declared `high` but the existing unresolved-NCT finding is then *suppressed* — high freedom means floating color is intended) |
| `repetition_appetite` | the new repetition number (§5) | measured repetition band ≠ declared appetite |

(`phrase_arch` and `motif_dna` are **deferred out of v1** — no guaranteed read side
this plan; W3 fix, §3. Their grading rows land when their read side ships.)

**The shaped-vs-aimless reading, made profile-relative** (the recorded correction).
A new per-line reading `shaped_reading: Literal["shaped", "aimless", "ungraded"]`:
- `ungraded` when no profile, or the profile declares neither `contour_intent` nor
  `repetition_appetite` (the genre-safe default — the universal verdict stays
  forbidden; this is the 2a behavior preserved).
- `shaped` when the line's measured contour + repetition are *consistent with* what
  its profile declared (an arch profile that arches; a high-repetition profile that
  repeats its cell). "Shaped" means "doing what it set out to do," NOT "good."
- `aimless` ONLY when a profile declared a definite intent (e.g. `contour_intent` is
  not `free`) AND the line contradicts it (no net shape, no apex where intended, no
  cell where high repetition was declared) — i.e. the line wanders relative to *its
  own* stated aim. Even then the *finding* is a question, never a verdict.

This is the metaperformer pattern (model §1): the universal is a prior, **the profile
is the truth**, intent is learned back. `aimless` can never fire on a line whose
profile is silent or `free` — which is exactly why the reggae-hook bug cannot recur.

### Decision-Record 2 — grade with a TWO-MODE lens, not a separate grader

- **Decision.** Extend `analyze_melody` / `analyze_arrangement` with an optional
  `profiles: Mapping[str, MelodicProfile] | None` parameter; the existing call
  (no profiles) is byte-for-byte unchanged. Profile-relative findings + the
  `shaped_reading` field are *additive* on the existing dataclasses.
- **Alternatives.** A standalone `grade_melody(report, profiles)` post-pass.
  Rejected: it would re-walk the section/line structure the lens already built and
  duplicate the layer-name binding — DRY violation, two source-of-truths for "which
  line is this." The two-mode lens is how `theory.lint` already grades against the
  declared mode/progression in one pass.
- **Trade-off.** `MelodicLine` grows two nullable fields (`profile_name`,
  `shaped_reading`). Acceptable: nullable, additive, `to_dict()`-covered, and the
  `None` path is the unchanged 2a output.

---

## 5. The motivic-economy / within-line repetition reading

A new module `src/hallucinote/melody/economy.py` (leaf, stdlib) plus an optional
phrase segmenter `src/hallucinote/melody/segmentation.py`. Both ship the **cheap
proxy with the heavyweight theory named** — the lens's established honesty pattern
(model §7 design note: IDyOM is the theory, n-gram is the proxy).

- **Within-line repetition** (research C4, the decisive split). Compute a
  **corpus-free** intrinsic repetition number over the line's *interval sequence*
  (not absolute pitch — Temperley's finding that long-distance repeats keep
  scale-degree, short keep pure-interval). Temperley's three structural facts say
  *what real repetition looks like* and are exactly the features to count
  (research C4): **metrically-parallel** (same metric position), **short-distance**,
  **multi-interval** (≥2 intervals, not a single repeated interval). The proxy: the
  fraction of the line covered by its most-repeated multi-interval n-gram (a
  bzip-style ratio is the alternative; n-gram self-similarity is simpler and more
  inspectable). Named heavyweight theory: **COSIATEC + Kolmogorov simplicity**
  (research C5/C6) — NOT shipped (O(n²), over-engineered for a short hook).
  **Reported as a profile-relative fact, never "economical = good"** (C4 caveat:
  compression is perceptually validated only pairwise).
- **Phrase segmentation** (research C1–C3, C8b). Ship **LBDM** (Cambouropoulos —
  research C2): a purely-local, deterministic, corpus-free boundary detector over the
  pitch-interval / IOI / rest change + proximity sequences. It is the cheapest
  stdlib-implementable segmenter and the right one for the stdlib-only core. Named
  heavyweight theory benchmarked against it: **IDyOM / Grouper** (research C1/C3,
  best mean F1 ≈ 0.66) — NOT shipped (needs a trained corpus + ML stack). Then
  **recompute the existing contour facts per LBDM-segmented phrase** — research C8b:
  the melodic arch is a *phrase-level* tendency, so the per-phrase contour read is
  where it actually lives, adding no new measurable but locating the existing ones
  correctly.
- **The C7 null is recorded in the design note** (and §7 delta): do NOT add a
  "make it catchier" repetition lever — motivic-rarity does NOT predict
  memorability (research C7, kill upheld on the primary source).

### Decision-Record 3 — segmentation is OPTIONAL sugar, repetition is the core 2b reading

- **Decision.** The within-line repetition number is the core motivic-economy
  reading (it is what `repetition_appetite` grades against, the BOTH-SIDES pairing).
  LBDM phrase segmentation + per-phrase contour is a *secondary* reading: valuable
  (locates the arch correctly) but not required to close the both-sides loop. It is
  built only if the first slice surfaces that whole-section contour is too coarse on
  the actual hooks (DISCOVERED-FROM-FRICTION; the build-plan sequences it last and
  lets it be dropped if friction doesn't appear).
- **Rationale.** Closing the authoring both-sides loop (profile + grading) is the
  item's verifiable signal; the repetition number is the minimum new read-side fact
  that loop needs. Segmentation is a refinement of an *existing* fact (contour),
  not a new both-sides axis. Avoids gold-plating (Principle 12).

---

## 6. The boundary with ARR-9K4T (coordinate, do not duplicate)

ARR-9K4T (`../ARR-9K4T/design.md`) builds the **cross-instrument / arrangement-level
recurrence** read — given the registered-motif graph, which motifs recur where and
as which variation, plus an arrangement-level **motivic-economy summary** (a small
recurring cell-set vs scattered, across the whole song / across instruments).

The boundary, explicit and non-overlapping:

| | MEL-1A7K (this item) | ARR-9K4T |
|---|---|---|
| **Unit** | ONE monophonic line (a single track's notes in a section) | the whole `Arrangement` — motifs recurring across sections / instruments |
| **Input** | a line's note sequence | the `arr.motifs` registry + each section's realized notes |
| **Repetition reading** | *within-line* n-gram self-similarity (undirected, over one line — research C4) | *directed* match of REGISTERED motifs against later sections under the closed transform set (ARR-9K4T §1; it explicitly cites MEL's deferred line-level n-gram as the OTHER half) |
| **"Economy"** | how repetitive is THIS line vs its declared `repetition_appetite` | how economical is the SONG's cell-set vs scattered (cross-section) |

ARR-9K4T's own research §1 already names the split: its detection half is *directed
pattern matching against a known query* (it owns the registered-motif graph);
MEL-1A7K's repetition reading is *undirected within one line* (no registry, no
query). **No shared code is required and none should be introduced** — they read
different inputs (one line vs the motif graph) and answer different questions. The
ONE thing to verify at integration (build-plan governance checkpoint): both surface
into `/compose-review` and must not double-report the same fact. They won't —
`melody_lens` reports per-line, `recurrence_lens` reports per-song — but the
checkpoint confirms the `/compose-review` prose distinguishes them.

---

## 7. PROPOSED deltas to `melody-model.md` (recorded here in DESIGN; APPLIED in build Chunk 6)

These extend, and are consistent with, the deltas `research.md` §"Proposed deltas"
already recorded. Quoted as deltas; the canonical doc is NOT edited *during the design
phase* (the scope constraint forbids touching canonical docs now). **But the canonical
edit is NOT punted out of the item — it is an explicit deliverable of build Chunk 6**
(B1 resolution): once the §7 deltas ship as code, `melody-model.md` is stale against
reality (§3.C, §4, §7, §8 prose become false), so Chunk 6 applies these deltas to the
canonical doc under the cumulative-final Critic pass that IS the governance. Leaving
the model stale would fail the item's verifiable signal ("melody-model.md records the
2b framing + a both-sides decision") and trip the Critic's Goal-4 coherence check
(building.md: "artifact drift is the #1 recurring quality issue"; learning "When a
doc... IS the deliverable, lock it with a drift/parity test").

1. **§3.C — UPGRADE from "no surviving claims" to the nuanced pass-3 result** (as
   `research.md` delta 1 states): the THEORY of motivic development (Réti/Caplin)
   resists computation from a bare line (C8, C9), but the COMPUTABLE facts — phrase
   segmentation (C1–C3), within-line repetition structure (C4), compression-as-
   economy (C5–C6) — survive, with the caveat that compression is perceptually
   anchored only pairwise (C4) and motivic-rarity does NOT predict memorability (C7).

2. **§4 — the authoring model becomes BUILT (in part), not anticipated.** Replace
   "Anticipated components, all declared, none computed-for-you" with: *the declared
   `MelodicProfile` (`melody/profile.py`) carries these declared intents* — and mark
   computability + build-status per field. The v1 profile ships `idiom`,
   `contour_intent`, `apex_position`, `ambitus_min/max`, `step_appetite`,
   `harmonic_freedom`, `repetition_appetite` (each with a read side — §4 grading
   table); `repetition_appetite` is graded against the within-line repetition reading
   (C4), noting Temperley's three structural facts (metrically-parallel,
   short-distance, multi-interval) as the *coaching prior* for what good repetition
   looks like, never a gate. **`phrase_arch` and `motif_dna` stay DECLARED-FUTURE
   intents — named in the anticipated list but NOT shipped in the v1 profile**,
   because neither has a guaranteed read side yet (W3 / §3 deferral): `phrase_arch`
   awaits the per-phrase contour read (optional Chunk 5), `motif_dna` awaits a reading
   that consumes it (likely the ARR-9K4T boundary). They are NOT computed
   classifications (C8/C9) and will enter the profile as *declared intents the lens
   reports against* only when their read side lands. Add the ruler-not-stamp note: the
   profile is **read-only intent** — unlike `PerformanceProfile` there is no `apply_*`
   that writes pitches, because pitch is the musical idea (§2 here).

3. **§7 — the read side gains profile-relative grading + the motivic-economy reading
   + the shaped-vs-aimless verdict** (extends `research.md` delta 3):
   - The classification gains a profile-relative `shaped_reading` (`shaped` /
     `aimless` / `ungraded`), made profile-relative exactly as the recorded
     correction demands — `aimless` can fire ONLY against a profile that declared a
     definite intent the line contradicts, never universally (closing the reggae-hook
     bug permanently, not just deferring it).
   - Ship the **within-line repetition** reading (n-gram self-similarity / bzip ratio)
     as the motivic-economy proxy (C4); name COSIATEC + Kolmogorov simplicity as the
     heavyweight theory (C5/C6); report it profile-relative.
   - **IF Chunk 5 shipped:** record **LBDM** (C2) as the optional stdlib phrase
     segmenter; name IDyOM/Grouper as the benchmarked theory (C1/C3); recompute contour
     facts per phrase (C8b's "arch is a phrase-level tendency"). **IF Chunk 5 was
     dropped** (no segmentation friction surfaced — Decision-Record 3): the canonical
     edit records LBDM/per-phrase contour as *named-but-deferred* (the theory is real,
     the friction did not appear), NOT as shipped — so the model never claims a
     capability the code lacks. The Chunk 6 builder writes whichever reflects reality.
   - Record the **C7 null** explicitly: no "make it catchier" lever.

4. **§3.B — keep the memorability kill; tighten the chorus/lyrics caveat** per C7
   (the Jakubowski design extracted the chorus and didn't separate sections, so it is
   *silent* on chorus-dominance, not evidence for it) — `research.md` delta 4.

5. **§8 — advance the phased-delivery plan.** Mark phase 2(b) the declared melodic
   profile authoring surface + profile-relative grading + the motivic-economy reading
   + the shaped-vs-aimless verdict as **built** when this lands; phase 3 (bring it to
   sun-zone-done, tune by ear) remains a creative lock-in left to the user's ear —
   deliberately NOT auto-applied (§8 step 3 here, the PENDING by-ear flag).

---

## 8. The flagship by-ear call (Live unattended this run) — FLAGGED PENDING

The model's §8 step 3 and §9 name the flagship demonstration: declare a profile for
each of sun-zone-done's two hand-authored hooks (`_reggae_lead_chillin`,
`_metal_lead_no_time`) and **tune by ear**. Two distinct things live here; only one
is by-ear:

- **NOT by-ear (deterministic, this run):** *measuring* the two hooks — running the
  new readings (repetition number, profile-relative gradings, `shaped_reading`)
  against the actual note arrays and surfacing the objective numbers. This is pure
  symbolic arithmetic, render-free, needs no ear. The build does this and SURFACES
  the numbers (e.g. "the reggae hook: step-fraction 0.71, repetition-coverage 0.55,
  contour=arch; the metal lead: step-fraction 0.30, repetition-coverage 0.20,
  contour=ascending").
- **PENDING by-ear (DO NOT guess):** (1) the **exact appetite→fraction edges** — what
  step-fraction band counts as `moderate` vs `high`, what repetition-coverage counts
  as a `high`-repetition hook vs a `through-composed` line, what apex/ambitus
  tolerance flags a divergence. These are calibration parameters; the build RENDERS +
  MEASURES the two hooks and surfaces the numbers, but the *thresholds themselves* are
  a creative lock-in. (2) **Which profile each hook declares**, and any rewrite — a
  creative lock-in left to the user's ear, deliberately NOT auto-applied (exactly as
  the performance tune-by-ear pass was). With Live UP but UNATTENDED, the build
  surfaces the objective measurements and STOPS at the threshold/profile decision;
  it does not auto-apply a profile to the song's hooks.

This honors the constraint: objective render + measurement IS available and is used
(the build prints the numbers); the irreducibly by-ear "how samey is too samey for
THIS profile" is FLAGGED, not guessed.

---

## 9. Wiring & collision surfaces

- **`/compose-review` (`skills/compose-review/SKILL.md`)** — the read-side home. The
  melody-lens already surfaces here (§"READ — the composition"). 2b adds: the lens
  now reports profile-relative gradings + the repetition number + `shaped_reading`
  when a song declares profiles. The skill's prose needs a thin update: "if the line
  declares a `MelodicProfile`, the lens grades against it (profile-relative, still a
  question); if not, it reports the neutral facts as today." **COLLISION FLAG (W1
  corrected):** the real collision on `/compose-review` is **MEL + ARR-9K4T only**.
  ARR-9K4T (recurrence) also adds a reading to `/compose-review`'s READ step.
  **ARR-7M3D (energy) does NOT collide here** — it wires into
  `skills/mix-review/SKILL.md`, not `/compose-review` (verified directly:
  `ARR-7M3D/design.md` DR-4 + §"`skills/mix-review/SKILL.md`" — "Surfaced via
  `/mix-review`", render-gated; and ARR-9K4T's own design §7 already concluded
  "ARR-7M3D does NOT collide with this item's `/compose-review` edit"). So **two**
  items edit this skill file → **edits must be coordinated** (sequence them, or land
  them as separate, clearly-scoped prose blocks; a tree-wide-grep parity check,
  `learnings.md` "Pattern sweeps are tree-wide"). The safe order: whichever lands
  first establishes the "the lens reports facts, grade against intent" framing; the
  other appends its reading as a sibling bullet. This item's edit is the smallest
  (one clause: "grades against the declared profile when present"). [The earlier
  "three items editing the same skill file" claim restated a collision fact instead
  of re-verifying against the sibling artifacts — the `learnings.md` "Link, don't
  summarize" miss, now corrected.]
- **`src/hallucinote/melody/`** — new `profile.py`, `economy.py`, optional
  `segmentation.py`; `lens.py` extended (additive); `__init__.py` re-exports
  `MelodicProfile` + the appetite/intent Literals + the presets (mirroring how
  `performance/__init__.py` exports `PerformanceProfile` + presets).
- **`src/hallucinote/arrangement.py`** — `SectionMelody` gains an optional
  `profiles` field; `section_melody_inputs()` gains a `profiles=` passthrough; **and
  `analyze_arrangement()` gains the same `profiles=` passthrough** (N2: `melody_report()`
  calls `analyze_arrangement`, so threading profiles only through
  `section_melody_inputs` would route them halfway — build-plan Chunk 1 lists both).
  **No** `Arrangement.section()` / `PlacedSection` change (Decision-Record 1). This is
  a contract-surface touch (the `SectionMelody` dataclass) — additive,
  backward-compatible (new field defaults `None`).
- **`src/hallucinote/tools/melody_lens.py`** — the CLI gains a path to load a song's
  declared profiles (the song's `melody_report()` already builds the arrangement; it
  now also passes its profiles, so the CLI needs no new arg — it just renders the
  new fields when present). `render()` extended to print gradings + repetition +
  `shaped_reading`.
- **`src/hallucinote/tools/templates/song/build.py.tmpl`** — the scaffold *template's*
  `melody_report()` convention (verified at `build.py.tmpl:125`, NOT in
  `scaffold_song.py` the renderer — N1) gains a commented-out `profiles={...}` example
  so new songs see the declared-profile path (mirrors how the scaffold seeds other
  conventions). Friction-driven retrofit of falling-walking / full-band-rock is a
  follow-on, not this item.
- **`COUPLING/SEQUENCE with ARR-9K4T:** independent code (different inputs, no shared
  module per §6), coupled ONLY at the `/compose-review` skill edit and a shared
  governance checkpoint that the two readings don't double-report. They can build in
  parallel; the skill edit is the merge point.

---

## 10. Test strategy (contracts)

- **`profile.py`** — `__post_init__` validation (empty name rejected; bad appetite /
  contour literal rejected); `to_dict()` round-trips; an all-`None` profile is legal.
- **profile-relative grading** — for each gradable field, one test that a divergence
  fires a finding and one that a match stays silent (the enumerate-both-states
  discipline). **The reggae-hook regression**: a third-based, `arch` + `high`-
  repetition profile over a leap-y third-based line reads `shaped`, NOT `aimless`
  (the recorded bug, pinned as a test). A `free`-contour profile NEVER yields
  `aimless`. A declared-but-unmatched layer name yields the typo finding.
- **`shaped_reading`** — `ungraded` with no profile / silent profile; `shaped` /
  `aimless` only against a definite declared intent.
- **`economy.py`** — the repetition number on a known cell-repeated line (high) vs a
  through-composed line (low); interval-based not pitch-based (a transposed repeat
  still counts — Temperley); multi-interval (a single repeated interval does NOT
  inflate it).
- **`segmentation.py`** (if built) — LBDM on a fixture with an obvious phrase break
  detects it; per-phrase contour differs from whole-line contour where it should.
- **No test weakened.** The 2a tests (`test_lens.py` etc.) must pass byte-for-byte —
  the no-profile path is unchanged. If any 2a test changes, that is a contract break
  to flag, not to make.
- **Calibration discipline** (`learnings.md` "DSP with a detection front-end" /
  "calibrate against real cases"): the appetite→fraction edges are calibrated by
  running the real sun-zone-done hooks through the real reading and reading the
  numbers BEFORE locking assertions — and the threshold *values* are the PENDING
  by-ear call (§8), surfaced not guessed.

---

*This design is the owner artifact for MEL-1A7K phase 2b. It extends
[`melody-model.md`](../../melody-model.md) (proposed deltas §7), mirrors the proven
`performance/realization.py` `PerformanceProfile` precedent, and coordinates the
line-level/arrangement-level boundary with [`ARR-9K4T`](../ARR-9K4T/design.md).
Research foundation: [`research.md`](research.md) + model §3 — linked, not restated.*
