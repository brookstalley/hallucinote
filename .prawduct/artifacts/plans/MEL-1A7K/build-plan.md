# MEL-1A7K — Phase 2b Build Plan: declared melodic profile + profile-relative grading + motivic-economy

Design: [`design.md`](design.md). Model: [`melody-model.md`](../../melody-model.md).
Research: [`research.md`](research.md). Precedent mirrored:
`src/hallucinote/performance/realization.py` (`PerformanceProfile` / `apply_profile`).

## Requirements Confidence: **High**

The problem, success, and scope are each one-sentence statable (design §0) and the
proven `PerformanceProfile` precedent removes the design unknowns.

**Scope clarifications (resolving review B2 + W3 at the plan level):**
- **Learn-back = declaring the `MelodicProfile` in build.py** (design §0 Success + §1
  Learn-back row + §0 Out-of-scope (g)). Once the revealed intent is written down as
  the profile, the line grades as matched and never re-flags — the declaration IS the
  learn-back; **no separate markdown-annotation surface is built this phase** (it adds
  no measurement the declaration doesn't, and is explicitly descoped, not silently
  dropped). No chunk builds an annotation surface; that is intentional and stated.
- **`phrase_arch` + `motif_dna` are DEFERRED out of the v1 profile** (design §3, W3) —
  no guaranteed read side this plan; they enter the profile when their read side
  ships. Chunk 1 ships the v1 fields only and pins the deferral with a test.

**One Medium
assumption, and it is a flagged PENDING by-ear call, not a requirements gap:** the
exact appetite→fraction grading edges (what step-fraction band is `high`, what
repetition-coverage is a `high`-repetition hook). *What would raise it:* render +
measure sun-zone-done's two hooks objectively (Chunk 4 does this) and let the user's
ear set the thresholds — Live is UP but UNATTENDED this run, so the build surfaces
the numbers and STOPS at the threshold decision (PENDING). The readings themselves
(repetition number, profile-relative divergence detection, `shaped_reading`) are
deterministic and need no ear.

## Verification strategy

Per-chunk: full `pytest` suite green (the contract — `prawduct-hook test-status`
first to avoid re-runs); plus chunk-specific behavioral verification listed in each
Done-when. The both-sides loop is verified by the CLI (`python3 -m
hallucinote.tools.melody_lens`) producing profile-relative output. The 2a tests must
pass byte-for-byte every chunk (the no-profile path is unchanged) — a 2a test
changing is a contract break to flag, never to weaken. **Foreign API: none** for
every chunk (pure-stdlib symbolic layer; no Live, no MCP, no external SDK).
**Render note:** the only render/measure step is Chunk 4's objective measurement of
the two hooks — render is available, but the threshold/profile decisions it feeds
are PENDING by-ear (Live unattended). The melody layer itself is render-free.

## Governance checkpoints

1. **After Chunk 1** (architecture validation) — the thin end-to-end slice proves
   `MelodicProfile` → `SectionMelody.profiles` → lens → one profile-relative finding
   → CLI render. Confirm the no-profile path is byte-for-byte unchanged.
2. **After Chunk 3** (midpoint) — full grading + `shaped_reading`; confirm the
   reggae-hook regression is pinned and the universal-verdict bug cannot recur.
3. **Before completion** (Chunk 5/6) — the `/compose-review` skill edit; coordinate
   the COLLISION with **ARR-9K4T ONLY** (MEL + ARR-9K4T edit the `/compose-review`
   READ step; ARR-7M3D wires into `/mix-review` and does NOT collide — W1 fix);
   confirm no double-reporting; **and APPLY the canonical-doc deltas (design §7) to
   `melody-model.md`** (B1 fix — the canonical edit is a Chunk 6 deliverable, the
   verifiable signal is met in the canonical doc, not only recorded in design §7).

---

## Chunk 1 — THIN VERTICAL SLICE: `MelodicProfile` + one profile-relative finding, end to end

- **Type:** code
- **Foreign API:** none
- **Goal.** Prove the whole path with the *single simplest* gradable field
  (`harmonic_freedom` vs `non_chord_tone_fraction`, which the lens already computes):
  declare a profile → thread it through `SectionMelody` → lens emits one
  profile-relative `info` finding → CLI renders it. Widen only after the path works
  (planning.md "the first chunk is special").
- **Scope.**
  - New `src/hallucinote/melody/profile.py`: the `MelodicProfile` frozen dataclass
    with the **v1 fields** (design §3): `name`, `idiom`, `contour_intent`,
    `apex_position`, `ambitus_min`, `ambitus_max`, `step_appetite`,
    `harmonic_freedom`, `repetition_appetite` + the `Appetite`/`ContourIntent`
    Literals + `__post_init__` validation + `to_dict()`. (The object lands whole;
    only ONE field is *graded* this chunk.) **`phrase_arch` and `motif_dna` are
    DEFERRED OUT of v1** (W3 fix, design §3): neither has a guaranteed read side this
    plan (`phrase_arch`'s read side is the OPTIONAL Chunk 5; `motif_dna` is read by no
    chunk) — landing them would be a both-sides gap + the speculative catalog the
    design's own DISCOVERED-FROM-FRICTION rule forbids. The `PhraseArch` Literal lands
    with `phrase_arch` when its read side ships, not now. `ContourIntent` uses
    `"level"` (NOT `"static"`) to match the read-side `ContourShape` exactly (W2 fix,
    design §3 — no translation table).
  - `melody/lens.py`: `SectionMelody` gains optional `profiles: Mapping[str,
    MelodicProfile] | None = None`; `analyze_melody`/`analyze_arrangement` gain
    optional `profiles=` (default `None` = unchanged 2a path); `MelodicLine` gains
    `profile_name: str | None = None`; one new finding `kind="harmonic-freedom-
    mismatch"` fired when declared `harmonic_freedom="low"` but NCT share is high
    (or `high` but the existing `unresolved-nct` finding is suppressed).
  - `arrangement.py`: `section_melody_inputs(profiles=...)` passthrough.
  - `melody/__init__.py`: export `MelodicProfile` + the Literals.
  - `tools/melody_lens.py`: `render()` prints `profile_name` + any profile-relative
    finding when present.
- **Done when:**
  1. A `MelodicProfile(name="locked", harmonic_freedom="low")` on a high-NCT line
     yields exactly one `harmonic-freedom-mismatch` `info` finding; the same line
     with NO profile yields the 2a output unchanged (the conflated-state test:
     profile-present vs profile-absent are distinguished, `learnings.md`).
  2. A declared profile for a layer name that doesn't exist in the section yields the
     `declared-but-unmatched` typo finding (enumerate-every-state).
  3. `MelodicProfile.__post_init__` rejects an empty name and a bad Literal; tests
     pin both. A test pins the v1 field set — asserts `MelodicProfile` has the nine
     v1 fields and does **NOT** have `phrase_arch` / `motif_dna` (W3 deferral made
     semantic, not accidental — `learnings.md` "pin the NEW convention with a
     regression test that names what now FAILS"). `ContourIntent` includes `"level"`
     and NOT `"static"` (W2; pinned so a regression can't silently re-diverge from
     `ContourShape`).
  4. Full `pytest` green; **the 2a `test_lens.py`/`test_*` suite passes byte-for-byte**
     (the no-profile path unchanged) — verified, not assumed.
  5. `python3 -m hallucinote.tools.melody_lens` renders the new finding on a synthetic
     fixture (CLI smoke).
  6. `/critic chunk` run and blocking findings resolved; committed; chunk marked `[x]`.
- **Critic mode:** inference picks `chunk` (multi-chunk, non-final). No override.

## Chunk 2 — the rest of profile-relative grading (contour, apex, ambitus, step appetite)

- **Type:** code
- **Foreign API:** none
- **Scope.** Add the remaining divergence findings from the design §4 table over
  values the lens ALREADY computes: `contour_intent` vs `contour_shape`,
  `apex_position` vs measured apex (tolerance), `ambitus_min/max` vs `ambitus`,
  `step_appetite` vs `step_fraction`. Each fires only on divergence beyond tolerance
  AND with enough notes (the 2a `_STATIC_FINDING_MIN_NOTES` gate). Appetite→fraction
  edges land as **named module constants with placeholder values** explicitly marked
  `# PENDING by-ear calibration — see build-plan Chunk 4 / design §8`.
- **Done when:**
  1. Each gradable field has a divergence-fires test AND a match-is-silent test
     (both states).
  2. The appetite→fraction edge constants are isolated, named, and carry the PENDING
     marker comment (so Chunk 4 can set them in one place — no magic numbers
     scattered).
  3. Full suite green; 2a path unchanged.
  4. `/critic chunk`; committed; `[x]`.
- **Critic mode:** inference picks `chunk`.

## Chunk 3 — the profile-relative `shaped_reading` (the recorded-correction keystone)

- **Type:** code
- **Foreign API:** none
- **Scope.** Add `MelodicLine.shaped_reading: Literal["shaped","aimless","ungraded"]`
  per design §4: `ungraded` when no profile or the profile is silent/`free` on both
  `contour_intent` and `repetition_appetite`; `shaped` when measured contour +
  repetition are consistent with the declared intents; `aimless` ONLY when a definite
  declared intent is contradicted. (Uses the repetition number stubbed as
  `None`-tolerant here; Chunk 4 supplies the real number — `shaped_reading` grades on
  `contour_intent` alone until then, which is sufficient for the keystone.)
- **Done when:**
  1. **The reggae-hook regression test is pinned**: a third-based line with an `arch`
     + `high`-repetition profile reads `shaped`, never `aimless` — the recorded bug
     (model §7) made permanently impossible, not just deferred.
  2. A `free`-contour / silent profile yields `ungraded` and can NEVER yield
     `aimless` (the universal-verdict-forbidden test).
  3. A definite `arch` profile over a no-net-shape line reads `aimless` — but the
     emitted *finding* is a question, never a verdict (severity `info`, phrased as a
     question — pinned).
  4. Full suite green; 2a path unchanged.
  5. `/critic chunk`; committed; `[x]`.
- **Critic mode:** **override to `final`.** `shaped_reading` is the architectural
  keystone that resolves the recorded universal-verdict correction; its coherence
  (Goals 4 + 7) matters before Chunk 4 builds the economy reading on top. (planning.md
  "Override forward to `final` on an early chunk that lands an architectural keystone.")

## Chunk 4 — the within-line motivic-economy / repetition reading + objective calibration

- **Type:** code
- **Foreign API:** none
- **Scope.**
  - New `src/hallucinote/melody/economy.py` (leaf, stdlib): the within-line
    repetition number — fraction of the line covered by its most-repeated
    multi-interval n-gram over the *interval* sequence (Temperley-shaped:
    interval-based so a transposed repeat counts; multi-interval so a single repeated
    interval does not inflate it — research C4). Named heavyweight theory in the
    docstring: COSIATEC + Kolmogorov simplicity (research C5/C6), NOT shipped.
  - Wire it into `MelodicLine` (new field) + `repetition_appetite` grading (design §4)
    + feed it into `shaped_reading` (Chunk 3 left it `None`-tolerant).
  - Record the **C7 null** in the module docstring: no "make it catchier" lever.
  - **Calibration (the discovered-from-friction step):** a small calibration path
    (script or test-printed) runs the REAL sun-zone-done hooks through the real
    reading and PRINTS the numbers (`learnings.md` "calibrate against real cases").
    sun-zone-done lives in the sibling `../hallucinote-songs` repo and builds against
    the installed engine — so calibration runs there (or via a checked-in synthetic
    fixture mirroring the two hooks' note arrays if the sibling repo isn't on PATH).
- **Done when:**
  1. The repetition number is high on a cell-repeated fixture, low on a
     through-composed fixture, interval-based (transposed repeat counts),
     multi-interval (single repeated interval does NOT inflate it) — tests pin all.
  2. `repetition_appetite` grading fires on divergence, silent on match (both states).
  3. The C7-null docstring note is present.
  4. **PENDING by-ear (FLAGGED, NOT resolved this run):** the appetite→fraction edge
     constants (Chunk 2 placeholders + this chunk's repetition edge) are set by
     running the two hooks through the real reading and surfacing the objective
     numbers — but the *threshold values* and *which profile each hook declares* are
     a creative lock-in left to the user's ear (Live UNATTENDED). The build PRINTS
     the measured numbers and STOPS; it does NOT auto-apply a profile to the hooks and
     does NOT guess the edges. Acceptance for THIS run: the numbers are surfaced and
     the PENDING decision is documented in the plan Status — not that the thresholds
     are finalized.
  5. Full suite green; 2a path unchanged.
  6. `/critic chunk`; committed; `[x]`.
- **Critic mode:** inference picks `chunk`.

## Chunk 5 — OPTIONAL (friction-gated): LBDM phrase segmentation + per-phrase contour

- **Type:** code
- **Foreign API:** none
- **Build ONLY IF Chunk 4's calibration surfaces that whole-section contour is too
  coarse on the real hooks** (Decision-Record 3 — discovered-from-friction; drop this
  chunk if the friction does not appear, and say so in the plan Status). If built:
  new `src/hallucinote/melody/segmentation.py` — LBDM (Cambouropoulos, research C2):
  deterministic, corpus-free, over pitch-interval / IOI / rest change + proximity.
  Recompute the existing contour facts per LBDM phrase (research C8b). Named
  heavyweight theory: IDyOM/Grouper (research C1/C3), NOT shipped.
- **Done when (if built):**
  1. LBDM detects an obvious phrase break in a two-phrase fixture; per-phrase contour
     differs from whole-line contour where it should; tests pin both.
  2. Full suite green; 2a path unchanged.
  3. `/critic chunk`; committed; `[x]`.
- **If NOT built:** record in Status "Chunk 5 dropped — no segmentation friction
  surfaced on the real hooks (Decision-Record 3)"; it does not block completion.
- **Critic mode:** inference picks `chunk`.

## Chunk 6 — wire `/compose-review` + scaffold + APPLY canonical `melody-model.md` deltas (cumulative-final)

- **Type:** cumulative-final
- **Foreign API:** none
- **Scope.**
  - `skills/compose-review/SKILL.md`: thin prose update — "if a line declares a
    `MelodicProfile`, the lens grades against it (profile-relative, still a question);
    if not, it reports the neutral facts as today." **COLLISION-coordinate with
    ARR-9K4T ONLY** (W1 fix): MEL + ARR-9K4T both edit `/compose-review`'s READ step;
    **ARR-7M3D does NOT collide here** — it wires into `skills/mix-review/SKILL.md`
    (verified `ARR-7M3D/design.md` DR-4; ARR-9K4T's own §7 already concluded ARR-7M3D
    does not collide on `/compose-review`). Land this item's clause as a self-contained
    sibling bullet; run a tree-wide grep for the melody-lens prose to confirm no
    contradiction (`learnings.md` "Pattern sweeps are tree-wide").
  - `tools/templates/song/build.py.tmpl` (N1 — the scaffold *template*, NOT
    `scaffold_song.py` the renderer; `melody_report()` lives at `build.py.tmpl:125`):
    gains a commented-out `profiles={...}` example.
  - `tools/melody_lens.py` `render()`: final pass printing all new fields cleanly.
  - **APPLY the design §7 canonical deltas to `.prawduct/artifacts/melody-model.md`**
    (B1 fix — this is a DELIVERABLE of this chunk, NOT punted out of the item). Once the
    §7 deltas ship as code (Chunks 1–5), the model's prose is stale against reality:
    §3.C still reads "Angle C honestly returned no surviving verified claims" (upgrade
    to the nuanced pass-3 result — §7 delta 1); §4 still reads "Anticipated components,
    all declared, none computed-for-you" (becomes BUILT-in-part — §7 delta 2, with
    `phrase_arch`/`motif_dna` marked declared-future/deferred per W3); §7 gains the
    profile-relative `shaped_reading` + within-line repetition + LBDM-or-deferred +
    the C7 null (§7 delta 3); §3.B keeps the memorability kill + tightens the
    chorus/lyrics caveat (§7 delta 4); §8 phase 2(b) marked **built** (§7 delta 5).
    The cumulative-final Critic pass on this chunk IS the governance for the canonical
    edit (the design-phase scope constraint that forbade editing canonical docs applied
    to the *design* phase, not this *build* chunk).
- **Done when:**
  1. `/compose-review` SKILL.md reflects profile-relative grading; tree-wide grep
     shows no stale "lens reports only neutral facts, no grading" prose left behind.
  2. The scaffold template (`build.py.tmpl`) carries the `profiles` example;
     `test_scaffold_song.py` (if it asserts template content) updated to match — the
     doc/template-as-deliverable lock (`learnings.md` "When a doc or duplicated contract
     IS the deliverable, lock it with a drift/parity test").
  3. The both-sides loop runs end-to-end via the CLI against a profile-declaring
     fixture (or sun-zone-done if the sibling repo is on PATH): profile → grading →
     render.
  4. **`.prawduct/artifacts/melody-model.md` is edited** so §3.B, §3.C, §4, §7, and §8
     reflect shipped reality per the design §7 deltas — the item's VERIFIABLE SIGNAL
     ("melody-model.md records the 2b framing + a both-sides decision") is MET in the
     canonical doc, not just recorded in design §7. The model's Status line ("authoring
     side designed, pre-build") advances to reflect 2b shipped. Confirm no other
     melody-model.md prose contradicts the shipped code (Critic Goal-4 coherence).
  5. Governance checkpoint 3: confirm MEL/ARR-9K4T don't double-report in
     `/compose-review` (ARR-7M3D excluded — different skill, W1).
  6. Full suite green.
  7. `/critic final` THEN `/critic cumulative` (`merge-base...HEAD`) — the `/pr create`
     gate; blocking findings resolved; committed; `[x]`.
- **Critic mode:** `Type: cumulative-final` triggers the cumulative pass on top of the
  chunk's `final` review.

---

## Status

- [x] Chunk 1 — thin slice: `MelodicProfile` + harmonic-freedom grading end-to-end
- [x] Chunk 2 — remaining profile-relative gradings (contour/apex/ambitus/step)
- [x] Chunk 3 — profile-relative `shaped_reading` (keystone; Critic `final`)
- [x] Chunk 4 — within-line repetition reading + objective calibration (PENDING by-ear edges)
- [x] Chunk 5 — OPTIONAL LBDM segmentation — **BUILT** (whole-section contour proved too coarse on the real hooks — DR-3 friction surfaced; see below)
- [x] Chunk 6 — wire `/compose-review` + scaffold + APPLY canonical `melody-model.md` deltas (cumulative-final) — code+docs DONE; `/critic final`+`cumulative` + PR are the MAIN AGENT's to run (this builder does not run Critic/PR)

### Chunk 4 calibration — the REAL sun-zone-done hooks (PENDING by-ear, NOT resolved)

Measured by running `_reggae_lead_chillin` / `_metal_lead_no_time` (sun-zone-done,
sibling repo) through the real economy reading + the lens. The build SURFACES these;
the threshold VALUES and which profile each hook declares are the user's by-ear
creative lock-in (Live unattended) — NOT finalized here, NOT auto-applied.

| hook | onsets | contour | apex | ambitus | step_frac | leap_frac | post-skip-rev | alphabet | repetition_coverage |
|---|---|---|---|---|---|---|---|---|---|
| REGGAE 1 cycle | 14 | descending | 69 @ 0.538 | 17 | 0.167 | 0.833 | 0.30 | 5 | 0.0 |
| REGGAE 4 cycles | 56 | **level** | 69 @ 0.127 | 17 | 0.167 | 0.833 | 0.30 | 5 | 1.0 |
| METAL 1 cycle | 9 | valley | 76 @ 0.000 | 12 | 0.50 | 0.50 | 0.667 | 6 | 0.0 |
| METAL 4 cycles | 36 | **level** | 76 @ 0.000 | 12 | 0.50 | 0.50 | 0.533 | 6 | 1.0 |

**The by-ear inputs to relay:** (1) appetite→fraction edges — placeholders in
`lens.py` (`_STEP_FRACTION_LOW_MAX=0.4`, `_STEP_FRACTION_HIGH_MIN=0.7`,
`_APEX_POSITION_TOLERANCE=0.2`, `_REPETITION_LOW_MAX=0.25`, `_REPETITION_HIGH_MIN=0.5`),
each carrying `# PENDING by-ear calibration`. (2) which profile each hook declares —
NOT auto-applied. **Note the WITHIN-LINE vs ACROSS-CYCLE repetition split the numbers
exposed: a single hook cycle reads 0.0 coverage; the tiled loop reads 1.0 — the unit
the `repetition_appetite` grades against (one cycle vs the looped section) is itself a
by-ear lock-in.**

### Decision-Record 3 outcome — Chunk 5 BUILT (segmentation friction surfaced)

The calibration shows whole-section contour IS too coarse on the real hooks: both the
4-cycle reggae and metal lines read **`level`** at the whole-section level even though
each cycle has a clear shape (`descending` / `valley`). Since `melody_report()` reads
the tiled multi-cycle section layers, this flattening hits real readings — exactly the
DR-3 trigger ("whole-section contour is too coarse on the actual hooks"). Chunk 5
(LBDM per-phrase contour) was therefore built — it locates the per-cycle shape the
whole-section read masks.

**Context (cross-session handoff):** ALL CHUNKS BUILT (1–6, incl. the OPTIONAL Chunk
5). Code + docs complete, full suite green (2855 passed / 2 skipped). **The MAIN
AGENT still owns: `/critic final` (Chunk 3 keystone + Chunk 6), `/critic cumulative`
(the `/pr create` gate), and the PR** — this builder did NOT run Critic or open a PR.
Phase 2a (read side) shipped + wired. This plan added the AUTHORING side
(`MelodicProfile`, mirroring the proven `PerformanceProfile`), profile-relative
grading, the profile-relative `shaped_reading` (resolving the recorded universal-
verdict bug — NOT a universal rule), the within-line motivic-economy reading, and
LBDM per-phrase contour. **Learn-back = declaring the `MelodicProfile` in build.py** (no separate
markdown-annotation surface this phase — descoped, design §0 (g)). **`phrase_arch` +
`motif_dna` deferred out of v1** (no guaranteed read side — design §3 / W3).
**PENDING by-ear (Live unattended):** the appetite→fraction grading edges +
which profile each sun-zone-done hook declares — Chunk 4 surfaces the objective numbers
and STOPS; the user's ear sets the thresholds and picks the profiles. **Collisions:**
Chunk 6 edits `skills/compose-review/SKILL.md`, which **ARR-9K4T also edits — coordinate
with ARR-9K4T ONLY**; ARR-7M3D wires into `skills/mix-review/SKILL.md` and does NOT
collide here (W1 — verified ARR-7M3D/design.md DR-4 + ARR-9K4T/design.md §7).
**Canonical doc:** Chunk 6 APPLIES the design §7 deltas to
`.prawduct/artifacts/melody-model.md` (B1 — the verifiable signal is met in the
canonical doc, not deferred out of the item). **Boundary:** MEL owns line-level
within-line repetition; ARR-9K4T owns cross-instrument/arrangement-level recurrence
(no shared code; different inputs).

## Files this plan will touch (collision analysis)

- `src/hallucinote/melody/profile.py` (NEW)
- `src/hallucinote/melody/economy.py` (NEW)
- `src/hallucinote/melody/segmentation.py` (NEW, optional / friction-gated)
- `src/hallucinote/melody/lens.py` (extended — additive, 2a path unchanged)
- `src/hallucinote/melody/__init__.py` (export the new authoring surface)
- `src/hallucinote/arrangement.py` (`SectionMelody.profiles` + `section_melody_inputs` + `analyze_arrangement` passthrough — additive, N2)
- `src/hallucinote/tools/melody_lens.py` (render the new fields)
- `src/hallucinote/tools/templates/song/build.py.tmpl` (scaffold *template* `melody_report()` `profiles` example — N1, NOT `scaffold_song.py`)
- `skills/compose-review/SKILL.md` (**COLLISION with ARR-9K4T ONLY** — coordinate; ARR-7M3D is `/mix-review`, does NOT collide — W1)
- `.prawduct/artifacts/melody-model.md` (Chunk 6 — APPLY design §7 deltas to the canonical doc; B1)
- tests under `tests/unit/melody/` + `tests/unit/tools/` (NEW/extended)

---

## Review resolution (independent reviewer verdict: REVISE → resolved)

All 2 blocking findings and 3 warnings resolved in the design phase (no render or
human decision required for any of them). What changed:

- **B1 (canonical-doc edit deferred out of the plan).** Chunk 6 now has an explicit
  deliverable to **APPLY** the design §7 deltas to `.prawduct/artifacts/melody-model.md`
  (done-when #4), governed by the chunk's cumulative-final Critic pass. The §7 header,
  governance checkpoint 3, Status, and Files sections all now state the canonical edit
  is a Chunk 6 deliverable — the verifiable signal is met in the canonical doc, not
  punted out. (The design-phase scope constraint that forbade editing canonical docs
  applied to the *design* phase; the *build* applies them under Critic governance.)
- **B2 (learn-back silently dropped).** Resolved with the benign reading made explicit:
  **learn-back = declaring the `MelodicProfile` in build.py** (design §0 Success + §1
  Learn-back row, both rewritten). The second mechanism the §1 table named (a "settled
  'yes that's the character'" markdown annotation) is moved to an explicit Out-of-scope
  bullet **(g)** with rationale (adds no measurement the declaration doesn't; DB/markdown
  annotation surface is descoped, not silently dropped). Build-plan Requirements
  Confidence + Status restate it. No annotation-surface chunk — intentional and stated.
- **W1 (collision scope factually wrong).** Corrected everywhere (design §9, Chunk 6
  scope, governance checkpoint 3, Status, Files): the `/compose-review` collision is
  **MEL + ARR-9K4T ONLY**; **ARR-7M3D wires into `/mix-review`** and does not collide
  (verified directly against `ARR-7M3D/design.md` DR-4 + `ARR-9K4T/design.md` §7, not
  restated from the prior summary — the "link, don't summarize" miss is fixed).
- **W2 (`ContourIntent` ≠ `ContourShape`).** `ContourIntent` now uses `"level"` (NOT
  `"static"`) to match the read-side `ContourShape` exactly (verified `contour.py:28`).
  The "no translation table" claim is preserved and now true; the two intentionally
  asymmetric members (`"insufficient-data"` read-only, `"free"` intent-only) and how the
  grading reconciles them are documented (design §3). Chunk 1 done-when #3 pins it.
- **W3 (`phrase_arch` + `motif_dna` author-side without read side).** Both **deferred
  out of the v1 profile** (reviewer option (a) — the cleanest, matching the design's own
  DISCOVERED-FROM-FRICTION rule): neither has a guaranteed read side this plan
  (`phrase_arch`'s is the optional Chunk 5; `motif_dna` is read by no chunk). They stay
  named-but-deferred in the model's §4 anticipated list (§7 delta 2) so nothing is
  silently dropped. Chunk 1 ships the nine v1 fields only and pins the deferral with a
  test that asserts the field set (W3 made semantic). The `PhraseArch` Literal lands
  with its field when the read side ships.
- **N1/N2 (builder's-discretion notes, addressed since cheap):** the scaffold edit is
  scoped to the template file `tools/templates/song/build.py.tmpl` (not `scaffold_song.py`);
  design §9 now states `analyze_arrangement()` also gains the `profiles=` passthrough.

**Residual blocking: none.** Every blocking finding was resolvable in the design phase
(spec/scope fixes — no render, no human decision). The one pre-existing PENDING by-ear
call (appetite→fraction thresholds + which profile each hook declares, Chunk 4) is a
calibration lock-in, NOT a review finding, and remains correctly flagged.
