# ARR-7M3D — Research (LIGHT)

**Item:** ARR-7M3D — energy realization-check (does declared `energy[section]`
show up as rendered intensity?). Area: energy. Effort M, impact L.

**Stage:** RESEARCH (light directive). Goal: justify (a) the *measured-intensity
proxy* (which audio features stand in for "musical intensity") and (b) the
*rank-correlation* methodology (Spearman / flag-inversions over a linear/Pearson
fit). The DSP math is engineering; this pass only grounds the two design
choices so the DESIGN can commit to them under Critic.

**Research done:** Yes. 2 web searches, 4 primary/independent sources consulted
(plus the codebase grounding reads listed at the end). Result: BOTH choices are
confirmed by the literature; no n/a.

---

## 1. The gap, restated against the code (so the proxy claim is grounded)

ENERGY is a first-class authored axis: `Arrangement.section(..., energy=)` →
`Arrangement.energy_curve` (`src/hallucinote/arrangement.py:268`), a per-section
ordinal intent the composer owns (arrangement-model.md:260 "an authored
per-section/transition scalar"; :415 "Energy is authored, not derived").
sun-zone-done declares 0.25 → 1.0 across 9 sections.

The READ side is split-brained:

- **Symbolic** (`/compose-review`, SKILL.md:84) reads whether the *curve*
  "builds, breathes, peaks" off `build.py` — it never touches audio.
- **Audio** (`audio/analyze.py::_measure_sections` → `SectionMetrics`,
  `report.py:388`) measures per-section loudness (LUFS-I/S/M, true-peak) plus
  attribution/masking/timing — but **nothing joins the energy curve to the
  measured section intensity.** A section authored `energy=0.9` that renders
  quieter/sparser than an `energy=0.6` section ships unflagged.

Harmony got `theory.lint` (conformance) and performance got the perf lens;
energy is the one authored axis with no realization check. This is a genuine
BOTH-SIDES gap (every dimension needs an authoring surface AND a measurement
lens) — the authoring surface exists, the lens does not.

**What already exists to build the proxy from (no new DSP front-end needed):**
- `SectionMetrics.master.loudness.lufs_i` / `lufs_s_median` — per-section
  integrated / short-term loudness, already computed per section
  (`analyze.py::_measure_window`). This is the *level* correlate, in-hand today.
- `onsets.detect_onset_samples` / `detect_onsets_with_strength` — a calibrated
  spectral-flux onset front-end already used by timing/cross-rhythm. **Onset/event
  density per section is computable from the SAME windowed stems** the timing pass
  already slices (`analyze.py:504` `sliced_stems`) — count onsets across stems,
  divide by window beats. No new detector.
- Spectral density/flux/centroid is NOT yet computed anywhere. It would be the
  one *new* DSP primitive if the design wants the spectral correlate (librosa
  `spectral_flux` / `spectral_centroid` over the windowed master). See §4 on
  whether MVP needs it.

---

## 2. Proxy justification — what "musical intensity" measures as (VERIFIED)

The item proposes "loudness + spectral density + onset rate" as the measured
proxy for declared energy. The music-perception literature confirms that
**perceived intensity / arousal is multi-feature, with loudness dominant and
spectral + event-density features as strong secondary correlates** — exactly the
proposed triple.

- **Loudness is the dominant correlate.** Across continuous-rating studies,
  changes in loudness (and tempo) correlate positively with perceived arousal,
  with **loudness dominant** among acoustic features; dynamic loudness rises also
  drive listener "chills" (engagement) [1][3]. → Validates **LUFS as the primary
  intensity proxy.** LUFS is already perceptually weighted (K-weighting + log
  scale ≈ perceived loudness), so it is the *right* level feature, not raw RMS.

- **Spectral features (centroid/brightness, spectral flux, rolloff, entropy)
  are robust secondary arousal correlates.** "Beyond Intensity: Spectral
  Features Effectively Predict Music-Induced Subjective Arousal" finds spectral
  features predict arousal *even after* controlling for intensity/loudness [2];
  brightness/centroid, flux, rolloff, entropy show moderate positive correlation
  with arousal/tension [1][2]. Higher tension tracks "brighter sounds, increased
  spectral variation" [1]. → Validates **spectral density/flux/centroid** as a
  legitimate secondary intensity correlate (a chorus often "opens up" the
  spectrum even at matched loudness — a thing LUFS alone can't see).

- **Event density** appears in the same arousal feature sets [1]. → Validates
  **onset/event rate** as the third correlate (a busier chorus reads denser).

**Design implication:** the proxy is a *composite* of features that are
individually monotonic-positive with intensity but on incommensurable scales
(dB vs Hz vs onsets/beat). You cannot sum them into a single "intensity number"
without arbitrary weights — and arbitrary weights would be a STAMP (the helper
inventing the musical decision). This is the second reason rank-correlation is
the right frame (§3): rank each section by each correlate independently, compare
*orderings* to the declared energy ordering. No cross-feature unit reconciliation
needed.

---

## 3. Methodology justification — Spearman / flag-inversions, NOT Pearson (VERIFIED)

The item asks: rank-correlation (Spearman) vs flagging inversions. Both, and the
literature says why rank-based is correct here, not linear:

- **The declared energy curve is an ordinal intent, not a calibrated target.**
  `energy=0.9` means "more intense than 0.6," not "−9 LUFS." The composer
  authored a **rank ordering** of section intensity. Spearman assesses *monotonic*
  association and is the standard choice for **ordinal data and monotonic-but-
  nonlinear relationships**; Pearson assumes a *linear* relationship and normality
  [4][5]. Forcing a Pearson/linear fit would invent a scale the composer never
  declared (STAMP) and would *underestimate* a genuinely strong monotonic
  relationship that happens to be curvilinear [4].

- **The proxy↔perception mapping IS monotonic-but-nonlinear.** LUFS is already
  log; perceived loudness ≈ log SPL; the composite of dB + Hz + onsets/beat has
  no reason to be linear in `energy`. Spearman is robust to exactly this
  curvilinearity and to **outliers / relevant extreme values** [4][5] — e.g. one
  break section that's near-silent won't distort the rank read the way it would a
  Pearson r.

- **"Flag inversions" is the actionable, composer-facing output; Spearman ρ is
  the summary scalar.** They are complements, not alternatives:
  - **Spearman ρ over (declared energy, measured correlate)** per correlate
    (loudness, density, spectral) gives one honest "did intensity track intent
    overall?" number per axis. ρ near +1 = realized; near 0 = no relationship;
    negative = the arc is *inverted* vs intent.
  - **Inversion flags** are the local, fixable findings: an *adjacent or
    notable* pair where the higher-declared-energy section measures *lower*
    intensity (a discordant pair in Kendall/Spearman terms). This is what
    `/mix-review` surfaces as a producer question: "you authored the chorus
    hotter than verse 2, but it renders 2 LU quieter — intended, or did the
    arrangement not land?" The ρ tells you *whether* to look; the inversion list
    tells you *where*.

  → **Design choice: compute Spearman ρ per correlate AND emit per-pair
  inversion findings.** The inversion list is the BOTH-SIDES "where," ρ is the
  "whether." (Kendall's τ is a defensible alternative summary and is literally
  "fraction of concordant minus discordant pairs," which is conceptually the
  inversion count normalized — worth a one-line note in the design as the
  rationale for which scalar, but Spearman is the more familiar/expected choice
  and `scipy.stats.spearmanr` is already a dependency-free win since scipy is in
  use, e.g. `loudness.py` imports `scipy.signal`.)

---

## 4. Proxy scope for MVP — what to build vs defer (a DESIGN input, flagged)

The literature backs all three correlates, but DISCOVERED-FROM-FRICTION says
build the minimum that closes the gap and add the rest when friction demands:

- **Loudness correlate (LUFS-S median per section): in-hand today.** Zero new
  DSP. This alone closes the headline gap ("energy=0.9 section renders quieter
  than energy=0.6"). It is the *dominant* perceptual correlate [1][3], so an
  MVP that ships loudness-only is honest, not a corner-cut.
- **Onset/event density: cheap, reuses the calibrated onset front-end** already
  windowed in `_measure_sections`. Low marginal cost; strong second signal.
- **Spectral density/flux/centroid: the one NEW primitive.** Defer unless the
  loudness+density read proves insufficient — adding a spectral-intensity feature
  is a clean follow-on once friction shows loudness+density miss a real case
  (e.g. a chorus that opens the spectrum at matched loudness). **Flag in the
  build-plan as the deferred third correlate, not silently dropped.**

This keeps the lens a RULER: it reports per-section measured intensity ranked
against declared intent and names inversions — it never re-authors the energy
curve or declares the "correct" intensity. It is info/coaching surfaced via
`/mix-review`, parallel to masking/timing/perf, gated on intent (a deliberately
quiet "peak" — e.g. a stripped final chorus, the Nobile energy-drop at
arrangement-model.md:238 — is authorship, not a defect; the inversion is
surfaced as a question, never a verdict).

---

## 5. By-ear flag for the build-plan (CONSTRAINT this run)

Live is UP but UNATTENDED — objective render + measure is available, no human
ear. Implications for verification planning:

- The Spearman ρ and inversion detection are **fully objective** — render
  sun-zone-done (declared 0.25→1.0 across 9 sections), run `analyze_mix`, compute
  ρ(declared, measured-loudness) and the inversion list, assert the realized arc.
  No by-ear call. This is the primary verification and is doable this run.
- **One PENDING by-ear call:** the *threshold for what counts as a notable
  inversion* (how big a rank-flip / how many LU of "wrong-direction" before
  surfacing). The proxy↔perception mapping's exact sensitivity is a perceptual
  judgment. DESIGN should NOT guess the number. Plan: render + measure
  objectively, surface the *measured* inversions and their magnitudes, and leave
  the surfacing threshold as a PENDING by-ear tune (mirrors the existing reporting
  floors `_MASKING_REPORTING_FLOOR` / `_TIMING_MIN_CONFIDENCE` in `analyze.py`,
  which are themselves calibrated-not-guessed gates). Spearman ρ itself needs no
  threshold to *report*; only the per-pair "is this inversion worth a question"
  gate does.
- **Calibration-first discipline applies** (learnings: "DSP with a detection
  front-end: calibrate against real cases"): if the design uses the onset
  density correlate, run sun-zone-done's real sections through the onset
  front-end and read the per-section densities BEFORE locking any test
  assertions — the onset detector has known slow-attack/multi-trigger failure
  modes (learnings line 99; the C7 calibration story).

---

## 6. PROPOSED canonical deltas (recorded here; NOT applied — Critic governs edits)

- **arrangement-model.md** — under "The derivative question" / the read-side
  lens bullet (:303–308), add a sentence that the energy curve now has an
  *audio realization lens* (declared `energy_curve` vs measured per-section
  intensity, Spearman + inversions), parallel to harmonic conformance and the
  perf lens — closing the BOTH-SIDES gap for energy. Link to the lens, don't
  restate the method.
- **skills/mix-review/SKILL.md** — in MEASURE (§2), add an `energy_realization`
  feed bullet alongside `loudness`/`timing`/`performance`: per-section
  declared-vs-measured intensity, Spearman ρ per correlate, and the inversion
  list; gated on intent in INTERPRET (a deliberate energy-drop chorus is
  authorship — surface inversions as a producer question, never a verdict). This
  is the wired-in surface the VERIFIABLE SIGNAL asks for.
- **report.py** — a new `EnergyRealization` dataclass on `SectionMetrics` or
  (better, since it's a cross-section read) a top-level `MixReport.energy_realization`
  field: per-correlate Spearman ρ + a list of inversion findings. Mirror the
  `to_json_dict()` explicit-serialization boundary. Exact shape is DESIGN's call.

---

## Sources

Web (intensity correlates):
- [1] "Music communicates social emotions: Evidence from 750 music excerpts,"
  Scientific Reports (2024) — multi-feature arousal/tension correlates incl.
  loudness, spectral centroid/flux/rolloff/entropy, event density.
  https://www.nature.com/articles/s41598-024-78156-1
- [2] "Beyond Intensity: Spectral Features Effectively Predict Music-Induced
  Subjective Arousal" — spectral features predict arousal beyond loudness.
  https://www.researchgate.net/publication/258443279_Beyond_Intensity_Spectral_Features_Effectively_Predict_Music-Induced_Subjective_Arousal
- [3] Melodic-expectation / music-evoked chills (bioRxiv 2024) — dynamic loudness
  rises drive engagement; loudness dominant among intensity features.
  https://www.biorxiv.org/content/10.1101/2024.10.02.616280v2.full

Web (rank-correlation methodology):
- [4] "Spearman's Correlation Explained," Statistics By Jim — Spearman for
  ordinal / monotonic-nonlinear / outlier-robust; Pearson assumes linearity;
  Pearson underestimates curvilinear-monotonic relationships.
  https://statisticsbyjim.com/basics/spearmans-correlation/
- [5] "Correlation Coefficients: Appropriate Use and Interpretation,"
  Anesthesia & Analgesia (2018) — use Spearman for non-normal continuous,
  ordinal, or outlier-laden data as a measure of monotonic association.
  https://journals.lww.com/anesthesia-analgesia/fulltext/2018/05000/correlation_coefficients__appropriate_use_and.50.aspx

Codebase grounding (read, not cited as research):
- `src/hallucinote/arrangement.py` (`energy_curve` :268, `section(energy=)` :150)
- `src/hallucinote/audio/analyze.py` (`_measure_sections`, `_measure_window`)
- `src/hallucinote/audio/report.py` (`SectionMetrics`, `StemMetrics`, `LoudnessMetrics`)
- `src/hallucinote/audio/loudness.py` (LUFS-I/S/M, true peak; scipy already a dep)
- `src/hallucinote/audio/onsets.py` (calibrated spectral-flux onset front-end)
- `skills/mix-review/SKILL.md`, `skills/compose-review/SKILL.md` (symbolic energy read)
- `.prawduct/artifacts/arrangement-model.md` (energy in the taxonomy; derivative lens)
