# ARR-9K4T — Research: cross-instrument / arrangement-level recurrence read

**Stage:** RESEARCH (directive: LIGHT). **Mode:** DESIGN-ONLY — no production code.
**Item:** measurement-coverage gap. RECURRENCE/FORM is authored (`Arrangement.motif()`
+ `vary()` + the canonical-six variation ops); the READ side does not exist. No tool
verifies a registered motif was actually recalled, detects a recapitulation, or
measures motivic economy.

**Verdict up front:** **MOSTLY n/a on literature for the PRIMARY half; one cited
metric for the SECONDARY half.** The recurrence-detection half reads the
registered-motif graph directly and needs no literature — it is *directed pattern
matching against a known query under a closed transform set*, not undirected
pattern discovery. The motivic-economy half is the only part where the literature
earns its place, and it converges on one principled, corpus-free metric:
**description-length / compression as economy**. 3 primary sources consulted below;
all extracted from search-result abstracts (two source PDFs were binary/403-blocked
— flagged honestly under *Measurable vs not*).

---

## 1. The boundary that collapses the hard problem (why most literature is n/a here)

The motivic-pattern-discovery literature (SIATEC/COSIATEC, IDyOM n-grams) solves
**undirected discovery**: "given a piece, find the repeated patterns no one told you
about." That is genuinely hard and is what MEL-1A7K's deferred line-level n-gram
reading would need (melody/lens.py ~L48-50 — *"Motivic-economy / n-gram repetition
readings … are friction-driven follow-ons"*, line-level, NOT-YET).

ARR-9K4T is a **different, much easier problem on its detection half**: the
arrangement *registers* its motifs by name (`arr.motif("polyrhythm-cloud", …)`,
`arr.motif("no-time-stab", …)` — see the fixtures in §4). The query patterns are
**known**. The variation vocabulary is a **closed, six-element set** the project
already implements as pure functions (`generators/variations.py`: transpose,
transpose_diatonic, invert, retrograde, augment, diminish, fragment, + shift). So
"did the integration recall the polyrhythm motif, and as which variation?" is
answerable by **applying the canonical transforms to the registered motif and
testing for occurrence in the section's realized notes** — a directed
transform-and-match, no mining, no trained model, no corpus.

This is the same honesty the melody-model used: ship cheap exact substrate facts,
defer the corpus-trained ML. Here the substrate fact is *exact* (we own both the
query motif and the transform algebra), which is even cleaner than melody's proxies.

**A live structural finding (load-bearing for the design):** the arrangement
currently has **no recorded recap LINK**. `Arrangement` stores `self.motifs`
(name → notes) but has **no `reference()` method** — `grep "def reference"`
arrangement.py returns nothing. The taxonomy's "Reference / recap" primitive
(arrangement-model.md §"The primitives") is **documented but unbuilt**: the recap is
realized by *passing `motif.notes` as a raw list into a composer function*
(`_integration_play(…, poly.notes, no_time.notes)`; `_outro_lead(ob, no_time.notes)`
→ `V.augment(no_time_motif, 2.0)`). So the read-side cannot "follow a link that says
X recalls Y" — there is no link. It must **detect** the recall, OR the model must
**add the authored link** first. This is the central design fork (recorded as a
proposed delta in design.md, not decided here).

---

## 2. The economy metric — the one place literature earns its keep

When a song *does* recall a small set of cells everywhere vs. scatters unrelated
material, that is **motivic economy**, and the field's convergent way to quantify it
is **compression / minimum-description-length**: an economical piece compresses well
because a short dictionary of motifs + placement vectors reconstructs it.

- **Meredith, COSIATEC / SIATECCompress (geometric point-set compression).** Music
  is a **point set of (onset, pitch) pairs**; a *maximal translatable pattern (MTP)*
  is a sub-pattern, and its *translational equivalence class (TEC)* is "the set of
  translationally invariant occurrences of that MTP," encoded as ⟨P, V⟩ (a pattern
  P + the vectors V that map it onto its other occurrences). The economy figure is
  the **compression ratio** (original point count ÷ encoded size); COSIATEC
  "tends to achieve high compression ratios … typically between 2 and 4," and
  "the efficient encodings … seem to resemble the motivic-thematic analyses produced
  by human experts." This is the canonical, peer-reviewed statement that
  *compression ratio is a usable economy/quality metric* and that the TEC encoding
  (pattern + translation-vector set) is the right shape — **exactly the ⟨motif,
  occurrences⟩ shape ARR-9K4T already has from its registered motifs.**
  https://vbn.aau.dk/en/publications/cosiatec-and-siateccompress-pattern-discovery-by-geometric-compre/
- **Temperley (2024), "Melodic Pattern Repetition and Efficient Encoding: A Corpus
  Study," *Empirical Musicology Review* 18(2):97–116.** Confirms the
  repetition→efficient-encoding link empirically across classical themes, European
  folk songs, and the Rolling Stone rock corpus: "Melodies are full of repeated
  patterns … these repeated patterns aid the listener in creating an efficient
  encoding." Crucial **style-relativity caveat** for ruler-not-stamp: the *structure*
  of economical repetition is style-specific — repeated intervallic patterns "tend to
  be metrically parallel," purely-intervallic repetitions "tend to be confined to
  short distances" (longer ones add scale-degree repetition), and tend to span
  "multiple intervals rather than single ones." Translation: economy is real and
  measurable, but high vs. low is **not a universal good** — a through-composed piece
  is *legitimately* less economical than a minimalist one. The read must REPORT
  economy, never verdict it.
  https://emusicology.org/article/id/4613/
- **Pearce/Wiggins, IDyOM (variable-order n-gram / Markov, information content).**
  The expectation-theory alternative: model the melody as a variable-order n-gram and
  read per-event **information content (IC)** as surprisal; repetition lowers IC via
  the short-term model. This is the spine MEL-1A7K's *line-level* n-gram reading
  would use, and the melody-model already names expectation/IDyOM as its north star.
  **Deliberately NOT adopted here:** it is (a) line-level not cross-instrument, (b)
  needs a trained/corpus model for absolute IC, (c) answers "is this line shaped vs.
  random," a *different question* from "was the registered motif recalled." Cited to
  draw the boundary, not to import.
  https://onlinelibrary.wiley.com/doi/10.1111/j.1756-8765.2012.01214.x

**Chosen economy metric (principled, corpus-free, ruler-not-stamp):** a
**description-length-style economy summary** computed directly off the
already-known motif set — *not* a full COSIATEC run. Concretely the candidates
(to be specified in design.md): cell-set size (distinct registered motifs actually
recalled), total coverage (fraction of recalled-section note-mass explained by
recalled motifs + their detected variations), and a compression-ratio proxy
(realized note count ÷ [motif-library size + per-occurrence placement/variation
records]) — the COSIATEC ⟨P, V⟩ shape, but with P given rather than discovered. This
keeps the house pattern (cheap exact proxy now; full geometric discovery deferred to
the friction that forces MEL-1A7K) and stays a **fact, never a verdict** (Temperley's
style-relativity makes any "you should be more economical" a stamp).

---

## 3. Measurable vs. NOT measurable (honest)

**Measurable now, exactly, render-free, stdlib-only:**
- *Was registered motif M recalled in section S, and as which variation?* — apply the
  closed transform set to M, test occurrence-with-tolerance against S's realized
  notes. Exact because we own both M and the transforms.
- *Which variation* (transpose Δst, augment ×factor, invert, retrograde, diminish,
  fragment[window], shift) — recoverable by matching the realized notes against each
  transform's signature (e.g. augment ⇒ uniform onset/duration scaling; transpose ⇒
  uniform pitch offset, intervals preserved).
- *Motivic-economy summary* — cell-set size, coverage fraction, compression-ratio
  proxy, as in §2.

**NOT cleanly measurable / out of scope (flag, do not fake):**
- *Recall under COMPOSED transforms* (augment∘fragment∘shift — exactly the
  integration's `V.diminish(V.fragment(no_time, 0,4), 2.0)` and the outro's
  `V.augment(no_time, 2.0)`). Detecting an arbitrary *composition* of the six ops is
  a small search, tractable but a real scope dial — design.md must bound the search
  depth (likely: detect single-op + the specific 2-op compositions the fixtures use,
  report "partial/derived match" otherwise, never silently miss).
- *Tiling/looping artifacts.* Per learnings.md "Variation ops are tiling-safe only on
  single-cycle motifs" (L390): a registered motif is one clean cycle, but a section's
  realized layer is tiled. The matcher must align against the *single-cycle* motif and
  scan tiled positions — naive whole-span comparison will false-negative.
- *Undirected discovery of UNregistered recurring cells* — that is COSIATEC's job and
  MEL-1A7K's line-level deferral. Out of scope; would be a stamp-adjacent speculative
  build here.
- *"Is this recapitulation good?"* — Temperley's style-relativity forbids the verdict.
  Detect + report; the composer/ear judges.
- *Audio-side anything* — render-free by design, like the melody/theory/perf lenses.

---

## 4. Thin-slice test fixtures (the sun-zone-done quote + augment)

Confirmed by reading `hallucinote-songs/songs/sun-zone-done/build.py` (songs now
live in the sibling repo per memory `project_root_contract_shipped`):

- **Registered motifs** (L1241–1242): `poly = arr.motif("polyrhythm-cloud",
  _polyrhythm_cell())`; `no_time = arr.motif("no-time-stab", _no_time_motif())`.
- **The integration QUOTE / recap** (L1302–1303): `_integration_play(kit, …,
  poly.notes, no_time.notes)` — the polyrhythm cloud is recalled on the organ
  (`_climax_organ` → `_polyrhythm_callback(motif_notes, bars)` tiles it), and the
  no-time stab recurs diminished (`V.diminish(V.fragment(no_time_notes, 0,4), 2.0)`,
  L1002). The two-worlds-fused payoff.
- **The outro AUGMENT** (L1063 → L1035 `_augmented_no_time`): `V.augment(no_time_motif,
  2.0)` — the 8-beat anxiety hook stretched to 16 beats, "slowed to peace."
- **Read-side wiring precedent** (L1843 `melody_report()` + the in-build lens call at
  L1922): the per-song `*_report()` convention + `tools/melody_lens.py` CLI is the
  exact surface ARR-9K4T's read-side mirrors — a `recurrence_report()` convention and
  a `tools/recurrence_lens.py` feeding `/compose-review`. The lens runs build-time on
  the in-memory `Arrangement` (the motif registry + per-section layers), render-free,
  DB-decoupled — the lens stays a leaf, the adapter lives on the arrangement (same
  topology as `analyze_arrangement`/`section_melody_inputs`).

These three (quote, recap-via-diminish-fragment, augment) are the positive
detection cases; a scattered/no-recall synthetic arrangement is the negative case.

---

## 5. Boundary vs. MEL-1A7K (must not overlap)

| | ARR-9K4T (this) | MEL-1A7K (deferred, line-level) |
|---|---|---|
| Scope | **cross-instrument**, arrangement-level: registered motifs across organ/lead/etc. | **one monophonic line's** internal n-gram repetition |
| Query | **KNOWN** (registered motifs) → directed match | **UNKNOWN** → undirected discovery |
| Method | transform-and-match over the closed six ops + DL economy proxy | n-gram / IDyOM-style within-line |
| Source-of-truth | the `Arrangement` motif graph + per-section layers | the melody line's note sequence |
| Status | this item builds the read | melody/lens.py ~L48-50 NOT-YET |

Same boundary discipline the dimension taxonomy uses: ARR-9K4T reads the *form/recap*
structure intent; it does not re-implement melody's line reading.

---

## 6. What the design phase must decide (carried to design.md, not here)

1. **The model fork:** add an authored `Arrangement.reference(motif, section,
   variation)` recap-LINK primitive (the documented-but-unbuilt taxonomy primitive),
   so the read becomes *verify the declared link was realized* (cheap, exact, the
   harmony-lint shape) — OR stay **detect-only** (no model change; the read infers
   recalls from realized notes). PROPOSED DELTA to arrangement-model.md, decided under
   Critic governance later. (The honest both-sides framing: a `reference()` author
   surface + a realization-conformance read is the more complete answer and matches
   how harmony/performance/melody were each done; detect-only is the lighter MVP.)
2. **Transform-composition search depth** (single-op vs. the 2-op fixtures vs.
   bounded general) — see §3.
3. **The economy metric's exact formula + that it is INFO-severity only** (Temperley
   style-relativity → never blocking, never a "be more economical" nag).
4. **Tolerance** for occurrence matching (exact pitch/onset vs. feel-jitter slack —
   the breathed layers carry microtiming; the matcher likely aligns the *pre-breath*
   authored notes, or matches with onset tolerance). This is the only plausibly
   by-ear-adjacent dial; per the run constraint, if any threshold can't be fixed from
   the symbolic structure, the build-plan flags it PENDING and surfaces the measured
   number rather than guessing.

---

## Sources

- Meredith, *COSIATEC and SIATECCompress: Pattern discovery by geometric
  compression* — https://vbn.aau.dk/en/publications/cosiatec-and-siateccompress-pattern-discovery-by-geometric-compre/
  (MTP/TEC definitions, compression-ratio metric, ⟨P,V⟩ encoding, "resembles human
  motivic analysis"; source PDF was binary-blocked — extracted from the verified
  abstract + Semantic Scholar summary).
- Temperley (2024), *Melodic Pattern Repetition and Efficient Encoding: A Corpus
  Study*, Empirical Musicology Review 18(2):97–116 —
  https://emusicology.org/article/id/4613/ (repetition↔efficient-encoding link;
  style-relativity caveats; article page was 403/Anubis-blocked — extracted from the
  verified search abstract).
- Pearce/Wiggins, IDyOM / *Auditory Expectation: The Information Dynamics of Music
  Perception and Cognition*, Topics in Cognitive Science (2012) —
  https://onlinelibrary.wiley.com/doi/10.1111/j.1756-8765.2012.01214.x (variable-order
  n-gram, information content as surprisal; cited to DRAW THE BOUNDARY vs. MEL-1A7K,
  not adopted).
