# Build Plan — Absolute positive-framing norm + positioning sweep

## Why this exists

The prose norm *Write what a thing IS; never define it by what it isn't* was
ratified by the owner on 2026-08-11 and then narrowed **twice the same day by
the agent**, each time after review found shipping prose that violated it. Both
narrowings were recorded as pending owner veto rather than as ratified.

On 2026-08-12 the owner ruled on both:

- **Narrowing 1 — REJECTED.** The "competitor/critic (banned) vs mechanism
  (fine)" test is withdrawn. A factual distinction that defines a thing by
  naming what it isn't is banned like any other contrast-definition. The
  clause the owner originally wrote — *no "this isn't a Y"* — means what it
  says.
- **Narrowing 2 — RATIFIED.** Naming prior art as lineage stays permitted;
  ranking this product against it remains the banned move.

The ruling is retroactive by the norm's own terms, so the prose that narrowing 1
was written to rescue has to be rewritten positively.

## Requirements Confidence

**High.** The rule and both dispositions came from the owner directly. The one
genuinely open question — which prose the rule governs — was put to the owner
before any edit and answered: **positioning prose only**. That answer is
recorded in the norm as an explicit scope clause so no future agent has to
re-derive it.

`[ASSUMPTION — owner-confirmed]` Scope is `README.md`, `CONTRIBUTING.md`,
`SECURITY.md`, `docs/VISION.md`, `docs/faq.md`, `docs/tour.md`. Reference docs
under `docs/`, agent-read `skills/`, `.prawduct/artifacts/` and the frozen
`docs/archive/` are outside it.

## The test this plan applies

The banned form is a **contrast-definition**: a sentence that characterizes the
product, a component, or the process by naming a thing it isn't.

- Banned — "a long agentic workflow, not a chat"; "Ableton is the speaker, not
  the score"; "Verified, not assumed".
- Not the banned form — plain negation, which names no foil: "Live isn't
  running", "verify consumers aren't broken". They deny a predicate and offer
  nothing to measure the subject against.

The operative test is **does the sentence name a foil** — an alternative the
subject is set against. (An earlier wording asked whether removing the negated
half left the subject undefined; that was self-invalidating, since "Ableton is
the speaker" survives the deletion and the test therefore cleared a sentence
this plan bans. Caught by the Critic, replaced everywhere.)
- Permitted by ratified carve-out — prior-art lineage (VISION's TidalCycles /
  Sonic Pi / Lilypond / DAWproject paragraph) and a limitations register
  (`known-issues.md`, VISION's `## Non-goals`), which state plain facts.

This distinction is the literal reading of "define it by what it isn't"; it is
not a third carve-out. Recorded here so the Critic can test it rather than
having to reconstruct it.

## Chunks

- **C1 — Amend the norm.** Rewrite the `## Documentation & prose` row in
  `.prawduct/artifacts/project-preferences.md`: restore the absolute rule,
  delete the rejected mechanism carve-out, keep the prior-art and
  limitations-register carve-outs, add the scope clause, and state the
  contrast-definition test. Sync the matching enforcement-table row. Record the
  ruling in `project-state.yaml`'s `norm_registry_ratified` as owner-decided,
  clearing the pending-veto status.
- **C2 — Sweep the positioning corpus.** Rewrite every contrast-definition in
  the six in-scope files positively. Surface, rather than exempt, any sentence
  that resists positive rewriting.
- **C3 — Record and verify.** Change-log entry under a `docs-positive-framing`
  scope; full suite green (`tests/preferences/test_tour_freshness.py` asserts
  tour prose against committed sources, so tour edits are load-bearing).
  **Critic mode:** cumulative — the review's value here is judgment about prose,
  and the agent authored the very test being applied, so the coverage gate
  passing this interval as a docs-only free edge is not a reason to skip it.

## Done when

- No contrast-definition survives in the six in-scope files.
- `project-preferences.md` states the absolute rule, its two ratified carve-outs
  and its scope; no text anywhere still asserts the rejected narrowing.
- `project-state.yaml` records both dispositions as the owner's.
- Suite green; change-log entry filed; `/prawduct:critic` run and findings
  dispositioned.

## Status

- [x] C1 — Amend the norm
- [x] C2 — Sweep the positioning corpus
- [x] C3 — Record and verify

## Context

Branch `docs/norm-absolute-positive-framing`, cut from `develop` at 9a5469c
(v1.8.5). Baseline suite green at 5005 passed / 2 skipped.

Next after this cycle: **#329**, the demo video embedded in the README. It was
deferred behind this sweep because both rewrite README prose.
