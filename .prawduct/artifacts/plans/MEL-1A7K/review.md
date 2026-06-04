# MEL-1A7K Phase 2b — Independent Adversarial Spec Review

**Reviewer role:** independent adversarial spec-reviewer (did NOT author the design).
**Artifacts reviewed:** `design.md`, `build-plan.md`, `research.md` (this dir).
**Grounding probes run (real code, not summaries):** `melody/lens.py`,
`melody/__init__.py`, `melody/contour.py`, `performance/realization.py`,
`performance/__init__.py`, `arrangement.py:section_melody_inputs`,
`tools/melody_lens.py`, `tools/templates/song/build.py.tmpl`,
`tests/unit/melody/test_lens.py`, the sibling `ARR-9K4T` + `ARR-7M3D` plans, and the
`/compose-review` SKILL. Ran `pytest tests/unit/melody/` (38 passed — clean 2a baseline).

**Verdict: REVISE.** Two blocking spec defects (a co-equal half of the verifiable
signal deferred out of the plan; a named success-criterion silently dropped). The
design is otherwise strong, deeply research-grounded, ruler-not-stamp-clean on its
core, and accurately mirrors the proven `PerformanceProfile` precedent. Fix the two
blockers and three warnings and it is buildable with High confidence.

---

## What is solid (verified, not assumed)

- **Ruler-not-stamp is honored on the core.** The decisive §2 boundary — `MelodicProfile`
  is read-only intent with NO `apply_*` that writes pitches (unlike `PerformanceProfile`,
  whose `apply_profile` legitimately writes timing because micro-timing is arithmetic,
  not a musical idea) — is correct and load-bearing. Verified against
  `realization.py`: `apply_profile` writes `start_beats`/`velocity`; pitch is never
  touched. The "no `melody()` generator" line holds.
- **Lens-measures-not-verdicts is preserved.** Every finding stays `severity="info"`;
  `MelodyFinding.kind` is a free-text `str` (lens.py:117), so new kinds
  (`harmonic-freedom-mismatch`, `declared-but-unmatched`) are non-breaking additions.
- **The shaped-vs-aimless verdict is correctly made profile-relative** (§4, Chunk 3),
  resolving the recorded reggae-hook universal-verdict bug permanently rather than
  deferring it. The regression test (Chunk 3 done-when #1) pins it.
- **2a-byte-for-byte claim is real for the one risky interaction.** The
  `harmonic_freedom="high"` NCT-suppression is profile-GATED;
  `test_unresolved_nct_finding_fires_on_stranded_dissonance` (test_lens.py:146) calls the
  lens with NO profile, so its path is genuinely unchanged. Good.
- **Foreign-API grounding is honest.** Build-plan correctly declares `Foreign API: none`
  for every chunk (pure-stdlib symbolic layer). No Live/MCP claim is made.
- **By-ear gating is correct and well-separated** (§8): *measuring* the hooks is
  deterministic and done this run; the appetite→fraction *thresholds* and *which profile
  each hook declares* are FLAGGED PENDING by-ear, not guessed. Honors the unattended-Live
  constraint precisely.
- **The sun-zone-done-is-in-the-sibling-repo reality is handled** (Chunk 4): calibration
  runs in `../hallucinote-songs` or via a synthetic mirror fixture; the engine repo never
  takes a song-repo dependency. The reggae-hook regression fixture is correctly synthetic
  in the engine's own `tests/unit/melody/`.

---

## BLOCKING

### B1 — A co-equal half of the verifiable signal (melody-model.md records the 2b framing) is deferred out of the plan, leaving the canonical model stale.

The brief's VERIFIABLE SIGNAL: *"melody-model.md records the phase-2b framing + a
both-sides decision."* The build-plan's Chunk 6 done-when #4 only verifies the deltas
are recorded **in design §7**, and explicitly states the actual `melody-model.md` edit
"is a separate Critic-governed change, **not this item's code**."

This punts a named half of the verifiable signal out of the plan entirely. Recording
deltas in design §7 is correct for the DESIGN phase (the scope constraint forbids
editing canonical docs now — that part is right). But the BUILD plan governs the build
phase, and once the §7 deltas become shipped code, `melody-model.md` is **stale against
reality** — its §3 still says "Angle C: no surviving claims," §4 still says
authoring is "anticipated, none built," §7 still defers shaped-vs-aimless. building.md
("Update artifacts as you go... artifact drift is the #1 recurring quality issue") and
the project's own learning "When a doc... IS the deliverable, lock it with a
drift/parity test" both say the model must be updated *as part of the build that makes
its prose false*. The Critic's Goal 4 (Coherence) will flag this drift at cumulative
review.

**Fix.** Add the `melody-model.md` canonical edit as an explicit deliverable of Chunk 6
(or a dedicated final `Type: doc-only` chunk): apply the §7 deltas to the canonical doc
so the model reflects shipped reality. This is the natural Critic-governed point — the
cumulative-final Critic pass on Chunk 6 IS the governance. Do not leave it as "a
separate change, not this item's code"; that is how the verifiable signal goes unmet at
plan completion and the model rots.

### B2 — Learn-back is named in the design's Success criterion and both-sides table but built by NO chunk and listed in NO out-of-scope.

Design §0 Success (line 41): *"the revealed intent is **learned back per-song** so it
never re-flags."* Design §1 both-sides table (line 76): a dedicated **Learn-back** row —
*"the revealed intent (a chosen profile, or a settled 'yes that's the character')
written back as a markdown annotation so it never re-flags."* Learn-back is also a
load-bearing leg of the metaperformer thesis the brief cites ("learn intent back
per-song"; model §1 item #3; memory `project_masking_and_intent_collaboration`).

Grep of the build-plan: learn-back appears in **zero** chunks and is **not** in scope
exclusions. It is silently dropped — exactly the Principle-2 failure the brief flags.

There is a plausible benign reading: "declaring the `MelodicProfile` in build.py IS the
learn-back" (you write the revealed intent down as code; once declared, the line grades
as matched and never re-flags). If that is the intent, the design must SAY it — and then
the §1 table's "**or** a settled 'yes that's the character' written back as a markdown
annotation" is a *second* mechanism that is then descoped, which also must be said.

**Fix.** Resolve the contradiction explicitly: either (a) add a chunk that delivers the
learn-back annotation surface, or (b) state in design §0/§1 and build-plan scope that
"learn-back for melody = declaring the `MelodicProfile` in build.py; no separate
annotation surface is built this phase," and move the "settled 'yes that's the
character' markdown annotation" to an explicit Out-of-scope bullet with rationale.
Silent omission is not an option.

---

## WARNINGS

### W1 — The collision scope is overstated: ARR-7M3D does NOT touch /compose-review (it wires into /mix-review). The design restated a collision fact the sibling artifact had already verified false.

Design §9 (line 437) and build-plan Chunk 6 + Status repeatedly assert *"ARR-9K4T +
ARR-7M3D BOTH also add readings to `/compose-review`'s READ step"* and *"Three items
editing the same skill file."* This is **false**. Verified directly:
`ARR-7M3D/design.md` wires its energy reading into **`skills/mix-review/SKILL.md`**
(DR-4, lines 309-355: "Surfaced via `/mix-review`", "render-gated"), never
`/compose-review`. ARR-9K4T's own design already did this analysis and concluded
(lines 322-323): *"ARR-7M3D does NOT collide with this item's `/compose-review` edit."*

The real collision on `/compose-review` is **MEL + ARR-9K4T only**. This is a
link-don't-summarize miss: the MEL design restated a collision claim instead of
re-verifying against the sibling artifacts (the project's "link, don't summarize"
learning, J-5). Over-coordinating with one harmless extra item is not dangerous, but the
spec states a false fact a builder will act on, and "three items, coordinate the order"
adds friction that does not exist.

**Fix.** Correct §9, Chunk 6 scope, and the Status line to "MEL + ARR-9K4T collide on
`/compose-review`; ARR-7M3D wires into `/mix-review` and does NOT collide here (verified
in ARR-7M3D/design.md DR-4 + ARR-9K4T/design.md §7)."

### W2 — `ContourIntent` vocabulary does NOT actually match the measured `ContourShape`, contradicting the design's "no translation table" claim and leaving the `static`-intent grading broken/no-op.

Design §3 (lines 156-159) claims `ContourIntent` is *"deliberately the same value-space
as the read-side `ContourShape` plus `free` and `static`-as-intent, so a declared intent
can be compared directly to a measured `contour_shape` **without a translation table**."*

Verified `contour.py:28`: `ContourShape = Literal["ascending","descending","arch",
"valley","level","insufficient-data"]`. The design's `ContourIntent` =
`["arch","ascending","descending","valley","static","free"]`. **They diverge:**
ContourShape has `"level"`; ContourIntent has `"static"` in its place. A declared
`"static"` intent vs a measured `"level"` shape is NOT a direct string comparison — it
needs exactly the mapping the design says it avoids. As written, Chunk 2's
`contour_intent` vs `contour_shape` divergence check either never matches `static`↔`level`
(silent no-op — a profile field that can never read as "matched") or needs an
undocumented translation Chunk 2 doesn't mention.

**Fix.** Reconcile the vocabularies: either use `"level"` (matching the read side) instead
of `"static"` in `ContourIntent`, or document the `static`→`level` mapping explicitly in
§3 and add it to Chunk 2's scope. Drop the "without a translation table" claim if a
mapping is retained.

### W3 — `phrase_arch` and `motif_dna` are declarable author-side fields with NO guaranteed read side — a both-sides gap and a speculative surface the design's own DISCOVERED-FROM-FRICTION rule forbids.

Chunk 1 lands `MelodicProfile` with ALL fields, including `phrase_arch` and `motif_dna`.
But:
- `phrase_arch`'s read side is "REPORTED contour-per-phrase facts (§5)" — and per-phrase
  contour comes from **Chunk 5, which is OPTIONAL and friction-gated (may be dropped
  entirely)**. If Chunk 5 is dropped, `phrase_arch` is a declarable intent that nothing
  ever reads → author side without read side (BOTH-SIDES violation for that field).
- `motif_dna` has **no read-side chunk at all**. Within-line repetition (Chunk 4) grades
  `repetition_appetite`, not `motif_dna`; cross-instrument recurrence is ARR-9K4T's job
  (§6). So `motif_dna` is purely declarative, read by nothing in this plan.

These are exactly the "speculative catalog" the design itself warns against (§3:
"DISCOVERED-FROM-FRICTION, NOT a speculative catalog"). The fields are `None`/empty-default
optional so they degrade gracefully and break nothing — which is why this is a warning,
not a blocker — but shipping declarable-but-unread fields is a both-sides + speculative
defect as written.

**Fix.** Pick one: (a) defer `phrase_arch` + `motif_dna` out of the v1 `MelodicProfile`
until their read side is built (cleanest — discovered-from-friction); or (b) make the
phrase-arc per-phrase contour read a NON-optional chunk so `phrase_arch` has a guaranteed
read side; or (c) explicitly document them in §3 + build-plan as "declared-but-not-yet-read
placeholders, intentionally inert until [named future phase]" with the rationale for
landing them early. State the choice.

---

## NOTES (builder's discretion)

- **N1 — Plan file-scoping precision.** Build-plan "Files this plan will touch" lists
  `src/hallucinote/tools/scaffold_song.py` for the scaffold `profiles` example, but the
  actual `melody_report()` lives in `src/hallucinote/tools/templates/song/build.py.tmpl`
  (verified: line 125). Scope the edit by the template file, not the renderer. (Plans go
  stale by file address — the project's line-scoping trap.)
- **N2 — design §9 wording vs build-plan.** Design §9 says only `section_melody_inputs()`
  gains a `profiles=` passthrough, but `melody_report()` calls `analyze_arrangement()`
  (verified in the template + CLI), so `analyze_arrangement` ALSO needs the passthrough.
  Build-plan Chunk 1 correctly lists both — but tighten design §9 to match so the builder
  doesn't thread profiles only halfway.
- **N3 — Chunk 1 is a genuine thin vertical slice** (profile → SectionMelody.profiles →
  lens → one `harmonic-freedom-mismatch` finding → CLI render) through every layer the
  later chunks widen. Dependency order is sound; the Chunk 3 `final`-override for the
  shaped_reading keystone is well-justified per planning.md. Chunks are independently
  reviewable.
- **N4 — Requirements Confidence: High is defensible** given the `PerformanceProfile`
  precedent removes the structural unknowns and the one Medium item (threshold edges) is
  honestly flagged as a PENDING by-ear call, not a requirements gap. The High holds once
  B1/B2 are resolved (a dropped requirement is a confidence problem, not just a coverage
  one).
- **N5 — Calibration-against-real-cases (Chunk 4):** if the sibling repo isn't on PATH and
  the synthetic mirror fixture is used, the "calibrate against the REAL hooks" discipline
  (learnings.md "DSP with a detection front-end") is only honored if the mirror is
  faithfully transcribed from `../hallucinote-songs`' actual `_reggae_lead_chillin` /
  `_metal_lead_no_time` note arrays. Make Chunk 4 state which source produced the surfaced
  numbers.
