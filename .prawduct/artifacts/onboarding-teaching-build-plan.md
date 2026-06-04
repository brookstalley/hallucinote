# Build Plan — Onboarding & Teaching Model

Implements `.prawduct/artifacts/onboarding-and-teaching-model.md`. Read that first;
it is the durable design. This plan is the **what/sequencing**; build-governance.md
is the **how**.

## Requirements Confidence: **High** (two chunks Medium)

Wave-level rollup of the per-chunk Confidence checks already declared inline (MET-9D4H
header-convention backfill, 2026-06-04 — level taken from the plan's own per-chunk text,
not fabricated): the format is settled in the design doc and most chunks are High; the
two Medium chunks are the `song-new` open→proposal split (C5, this header's §line 142)
and the revision-flow surface that reuses the mix-review INTERPRET loop (C9, §line 183).

**Scope this plan:** the *sitting-down-to-write-a-song* (create) experience.
**Deferred (next plans):** revision-flow polish, the learn-the-tool flow, and
distribution / the non-technical entry gate.

## Status

- [x] C0 — Scenario-eval harness (test substrate)
- [x] C1 — Capability Truth + install Step-5 handoff (thin vertical slice)
- [x] C2 — Elicitation core in `song-new`
- [x] C3 — Norm amendments + the third register
- [x] C4 — Compose-stage guided evaluation + section/song intent

**Context:** **C0 shipped.** The scenario-eval substrate is in:
`tools/scenario_eval.py` (JSON brief schema + loader, persona/judge prompt
renderers, judge-result validator + recorder, CLI), the six personas as briefs
under `tests/scenarios/briefs/`, a runner-procedure README, and 39 unit tests in
`tests/unit/tools/test_scenario_eval.py`. **Suite: 2158 passed, 132 skipped
(audio), 0 failed.** Critic (chunk): 0 blocking. Briefs are tagged by chunk
(C1–C4) so each downstream chunk knows its gating personas (C1→maya, elena;
C2→theo, priya, sam, dev; C4→sam, maya). **C1 shipped:** `docs/capability-truth.md` (dimensional living
doc) is read by both the rewritten `/ableton-mcp-install` Step 5b and `song-new`
Phase 1; static command menu removed. Maya brief passed all 8 rubric lines under
the harness (`tests/scenarios/results/maya-*.json`); Critic 0/0/0. **C2 shipped:** `song-new`'s mode menu retired
for "Read the request, not the requester" (collaborate-by-default + precedence,
two-modes-one-discipline, third register, gap-inversion; deliverable shape is a
read, not an offered mode). All four gates passed (theo, priya, sam, dev,
recorded under `tests/scenarios/results/`). Critic caught make-me-X rename drift
in two sibling docs — fixed tree-wide. **C3 shipped:** third register added to
`intent-collaboration-model.md`; two CLAUDE.md norms carved out (pedagogical +
propose-don't-decide-silently), both bounded by precedence. Regression caught a
real over-proposing friction on `dev` from the carve-out — fixed (precedence
dominates) and re-passed; `theo` pass. New learning recorded. Critic 1 note
(resolved). **Next: C4** — compose-stage guided evaluation (sibling to
`mix-review`'s RECALL→INTERPRET-vs-intent→surface-as-question loop) + section/
song-level "what is this for?" intent into the markdown corpus. **Requirements
Confidence: Medium** — confirm the compose-stage surface shape against
`mix-review` before building; gates = sam + maya. Branch
`claude/recent-commit-summary-GvY4p`.

**C4 shipped — ALL CHUNKS COMPLETE.** `/compose-review` skill (compositional
sibling to `/mix-review`); `intent-architecture.md` gained the compose-stage loop
+ the "what is this for?" altitude (song/section/element) convention; `song-new`
hands off to `/compose-review` after the first pass. Two new compose-stage briefs
(maya-evaluate, sam-evaluate) gate it — both passed via independent judges. Critic
(final) 0/0/0. The create-experience plan (C0–C4) is fully delivered and verified;
deferred to later plans (unchanged): revision-flow polish, the learn-the-tool flow,
the non-technical entry gate / distribution.

Enabling work (pre-C0, prior session): container-friendly test selection (root
`conftest.py` + `audio`/`ableton` markers; hermetic `test_resolve_db_path` fix).

**Fresh-container dev-env recipe** (the `.venv` + installs do NOT survive
container reclaim; they DO survive `/clear`):
```
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]' -e './hallucinote_mcp[dev]'
HALLUCINOTE_SKIP_AUDIO=1 OMP_NUM_THREADS=1 .venv/bin/python -m pytest -q
```
Worth promoting to a SessionStart hook (`session-start-hook` skill) so web
sessions self-provision.

Persistence note: committed under the unique name
`onboarding-teaching-build-plan.md` (the literal `build-plan.md` is gitignored);
a gitignored `build-plan.md` **symlink** points here so framework tooling (Critic
mode inference, stop-hook gates) resolves the canonical name. After a fresh clone,
recreate it: `ln -s onboarding-teaching-build-plan.md
.prawduct/artifacts/build-plan.md`.

---

## C0 — Scenario-eval harness

**Problem:** This work is agent *behavior*, not unit-testable logic; we need a
repeatable way to verify it without scripting brittle transcripts.
**Success:** A scenario brief (persona + goal + response-character + must/must-not
rubric) can be run — a simulated user converses with the system-under-test, a
judge scores the transcript against the rubric — and the pass/fail + rationale is
recorded. Re-runnable, floating conversation, no string-matching.
**Out of scope:** Full CI automation; an API-calling harness. The mechanism is
**spawned subagents** (one role-plays the persona from the brief; one judges
against the rubric) — the ad hoc, in-container approach.

- Requirements Confidence: **High** (format settled in the design doc; Theo brief
  is the worked example).
- Type: code + harness convention.
- **Done when:**
  - [ ] Brief schema defined and documented (persona / goal / response-character /
    rubric), stored under a `scenarios/` location (decide: `tests/scenarios/` vs a
    dedicated dir — mirror-layout convention favors `tests/scenarios/`).
  - [ ] The six walkthrough personas written as briefs (Maya, Dev, Elena, Theo,
    Priya, Sam).
  - [ ] A runner procedure: spawn a persona subagent + a judge subagent; capture
    transcript; judge emits pass/fail + per-rubric-line rationale; results recorded
    (e.g. `scenarios/results/`). Light tooling only — loader + result schema get
    unit tests; the LLM steps are the ad hoc part.
  - [ ] Unit tests for the deterministic pieces (brief loader, rubric/result
    schema validation). Full suite green; evidence recorded.
  - [ ] `/critic` (chunk).

## C1 — Capability Truth + install Step-5 handoff (thin vertical slice)

**Problem:** First contact (post-install) is a static command menu; it neither
states honest capabilities nor opens an intent conversation.
**Success:** A user finishing `/ableton-mcp-install` gets a capability-honest,
dimensional invitation that flows into "what do you want to make?" — and the agent
can answer "what can you do?" truthfully from a single source.
**Out of scope:** The full elicitation behavior (C2); revision/learn-the-tool
handoffs.

- Requirements Confidence: **High.**
- Foreign API: none.
- **Done when:**
  - [ ] Capability Truth authored as a living doc both the handoff and `song-new`
    read (dimensional table from the design doc, incl. round-trip / sketch-input,
    melody ◐, vocals ✗). Trivially updatable.
  - [ ] `/ableton-mcp-install` Step 5 rewritten: capability-honest invitation →
    intent elicitation handoff (replaces the static menu). Caveats are dimensional,
    never goal-blocking; the gap-inversion ("sketch it in Ableton, I'll build
    around it") is offered when relevant.
  - [ ] Scenario brief passes: **Maya** (high-comp / low-music) — frictionless
    entry, references-as-spec honored, capability stated truthfully, no
    confabulation.
  - [ ] Suite green; evidence recorded. `/critic` (chunk).

## C2 — Elicitation core in `song-new`

**Problem:** `song-new` splits into make-me-X / scaffold-only modes and can
silently decide elementary musical choices (auto-accompaniment).
**Success:** `song-new` reads the *request* (not the requester), elicits only
load-bearing unknowns toward a first concrete pass, shifts open→proposal when
direction runs dry, never assumes-and-go, names the why in one plain sentence
(implicit teaching, never a lecture), inverts thin-dimension gaps into
invitations, and lets clear direction override the collaborative default.
**Out of scope:** Guided post-compose evaluation (C4); norm-doc edits (C3).

- Requirements Confidence: **High** on principle; **Medium** on the open→proposal
  transition read (a judgment with no mechanism — the rubrics police it).
- **Done when:**
  - [ ] `song-new` elicitation behavior updated per the design doc (two modes, one
    discipline; load-bearing-only; gap-inversion; implicit why; precedence).
  - [ ] Mode split retired in favor of collaborate-by-default-with-precedence.
  - [ ] Scenario briefs pass: **Theo** (third register — must not auto-accompany
    "make it Bach"), **Priya** (gap-inversion to round-trip melody input),
    **Sam** (newcomer — proposal pacing, no paralysis), **Dev** (clear direction
    executed, not over-proposed).
  - [ ] Suite green; evidence recorded. `/critic` (chunk).

## C3 — Norm amendments + the third register

**Problem:** Two CLAUDE.md norms assume the expert case and would fight the
elicitation behavior; the producer model has only two registers.
**Success:** The "stop only on high-stakes" and "drive creative prompts
end-to-end" norms carry pedagogical / propose-don't-silently-decide carve-outs;
`intent-collaboration-model.md` documents the third (directed-but-under-
articulated) register.
**Out of scope:** New behavior (covered by C2) — this is the governance/doc layer
that legitimizes it.

- Requirements Confidence: **High.**
- Type: governance docs (no logic). Keep CLAUDE.md within its size budget.
- **Done when:**
  - [ ] CLAUDE.md behavioral-norms carve-outs added (concise).
  - [ ] Third register added to `intent-collaboration-model.md`.
  - [ ] Regression: re-run **Dev** + one directed-action brief — no new friction;
    re-run Theo to confirm no regression.
  - [ ] `/critic` (chunk) — or waive if strictly docs-only at commit time.

## C4 — Compose-stage guided evaluation + section/song intent

**Problem:** Novices can generate but not evaluate; intent is captured at the
element level but not lifted to section/song altitude at compose time.
**Success:** After a first pass, the agent helps the user hear the result against
stated intent (compose-stage sibling to `mix-review`); section- and song-level
intent are captured as prose annotations in the existing corpus.
**Out of scope:** Mixing review (exists); the learn-the-tool flow.

- Requirements Confidence: **Medium** (reuses the mix-review INTERPRET loop; the
  compose-stage surface is new — confirm shape against `mix-review` before
  building).
- **Done when:**
  - [ ] Section/song "what is this for?" intent captured into the markdown corpus
    (learn-back), altitude-aware.
  - [ ] Compose-stage guided-evaluation surface (RECALL → INTERPRET vs intent →
    surface as a question), modeled on `mix-review`.
  - [ ] Scenario briefs pass: **Sam** + **Maya** — post-pass evaluation lands as a
    hearable, intent-anchored observation, not a verdict.
  - [ ] Suite green; evidence recorded. `/critic` (chunk).

---

## Verification note

Behavioral chunks are "done" only when their scenario briefs pass under C0's
harness (judge rationale recorded). Deterministic code (Capability Truth loader,
brief/result schemas, any `song-new` helper logic) also carries ordinary unit
tests per project conventions (mirror layout, pytest, event-paired mutators where
DB is touched). The two known judgment risks — reading the open→proposal
transition (C2) and proposal pacing (C2/C4) — have no mechanism; the rubrics are
how we police them, and persistent misfires become learnings.
