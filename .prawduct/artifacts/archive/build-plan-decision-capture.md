---
lifecycle: completed
archived: 2026-09-08
maintained: false
---

> **Archived — no longer maintained.** This plan records what was built, not what will be. Do not edit it to reflect later changes; write those where they are true.

# Build plan — Decision capture in the iterate loop

**Scope tag:** DEC-CAP
**Branch:** `feat/decision-capture` (worktree at `../hallucinote-decision-capture`)
**Source:** `backlog DOC-4F8M` (severity H, methodology)
**Size/type:** Medium · methodology/docs+skills (no engine code in Chunks 1–4)
**Critic:** worktree is gate-blind — review via independent Agent, PR/merge with `gh` (see memory `feedback_worktree_governance_gates_blind`).

## Confidence check

1. **Problem:** Decision/intent capture fires only at `/song-new` (front-loaded) and the two review checkpoints' LEARN-BACK. The bulk of a song's decisions are made in the `/compose-part` → push → react → refine loop (+ sound-design/automation/delegation), which prompts **zero** rationale capture — so `decisions/NN-*.md`, the durable corpus that survives `/clear` and feeds `/song-context`, stays frozen at the scaffold snapshot.
2. **Success:** A substantive creative/production move made in the iterate loop lands an ADR in `decisions/` **as part of being done** — silently, no per-iteration checkpoint — and what the agent misses is caught by a completeness check at the existing review checkpoints. Delegated sound-design/automation returns its rationale so the orchestrator files it.
3. **Out of scope:** (a) The DB `requests.decision_rationale` finer-grain audit path (`/decisions`) — already documented; referenced, not expanded. (b) Chunk 5 (derived-overview regeneration) — separable, different bug shape (artifact staleness, engine-side); deferred to backlog. (c) Any change to how `/song-context`/`/decisions` *query* — capture-side only.

## Design spine (resolves the central tension)

Capture is a **deliverable component, not a checkpoint** — the exact parallel to the existing "sound design is authorship" norm (the chain ships in the snapshot as part of *done*). So the WHY ships in `decisions/` as part of a substantive move being done: filed **silently, mid-flow** (respects the stop-less norm; `/compose-part` Step 6 explicitly forbids stop-to-ask iterations), and **only for bright-line-substantive moves** (so trivial iteration makes no ADR noise). Code stays necessary-but-not-sufficient: it carries the WHAT; the ADR carries the WHY + the narrative→sound mapping that has no home in code.

**The bright line** (authored once in the conventions doc, referenced everywhere):
- **Capture → `decisions/NN-*.md`:** a feel/groove choice (a feel arc), a sound-design subsystem, a structural/form change, a committed musical landing, a transition/hand-off plan, baked mix levels, a signal-chain choice.
- **Code only (no ADR):** velocity jitter, a single level/pan nudge, a length tweak, a mechanical refactor.
- **Routing:** kept move → `decisions/`; tried-and-reverted → `attempts/` (existing ledger).

## Chunks

### Chunk 1 — The norm + the canonical decision-file template
`docs/song-authoring-conventions.md`: add a **"Rationale is authorship — the WHY ships in `decisions/`"** section (sibling to "Sound design is authorship") stating the deliverable-not-checkpoint framing, the bright line, and the kept-vs-reverted routing. Add the **canonical decision-file template** the doc is already referenced for (currently a dangling ref from `/song-pick-instruments` Step 5) — frontmatter (`kind: decision`, scope, tags) + body shape (context / decision / why / narrative→sound mapping), written via `write_markdown_ref` so it's audit-threaded + FTS5-indexed like annotations/attempts.
`CLAUDE.md`: one behavioral-norm bullet ("A substantive decision isn't done until its WHY is recorded") alongside the existing sound-design / feel / attempt-ledger norms, pointing at the conventions section.
**Done when:** the norm + bright line + template exist; `/song-pick-instruments` Step 5's "see … for the decision-file template" now resolves.

### Chunk 2 — Wire capture into `/compose-part`
Add a closing **"Record the decision"** step at the *finished-move* boundary (after Step 5 "Verify it's finished", before "Next: read what you composed") — NOT per-iteration. Fires only on a bright-line-substantive move; writes `decisions/NN-*.md` via the Chunk-1 template; framed as part of *done* (cross-ref CLAUDE.md stop-less + the new norm). Extend `allowed-tools` if needed for the markdown write.
**Done when:** `/compose-part` ends with the gated capture step, framed silently (no stop-to-ask), routing kept→decision / reverted→attempt.

### Chunk 3 — Delegation carries capture
Where `/compose-part` / `/song-pick-instruments` / sound-design / automation work is delegated to a subagent, require the subagent to **return** its decision rationale (context/decision/why) as a structured part of its report, and the orchestrator files the ADR. Bake into the relevant skill delegation guidance + the new norm (ties to memory `feedback_subagent_explicit_staging`). Closes the "delegation launders the WHY" hole — and the concrete `NN-signal-chains.md`-skipped-under-delegation case the report cites.
**Done when:** the delegation guidance names the capture-return obligation; the orchestrator-files-it step is explicit.

### Chunk 4 — Completeness backstop at the review checkpoints
`/compose-review` + `/mix-review`: add a **§7 DECISION-COMPLETENESS** check (same shape/altitude as §5 LEARN-BACK / §6 LOG-ATTEMPTS, propose-and-react, never a verdict): "N substantive `build.py`/snapshot changes since the last recorded decision — here are the candidates; capture them?" The reliability net for "the agent forgot under execute-and-react pressure."
**Done when:** both review skills carry the completeness check, propose-and-react, writing via `write_markdown_ref`.

### Chunk 5 — Derived-overview rot (DEFERRED → backlog)
`<slug>.md` structure table + `build.py` docstring drift to scaffold defaults though derivable from `FORM`/constants. Generate-or-warn at build. Separable, engine-side, different bug shape — file via `/prawduct:backlog`, do not build here.

## Status
- [x] Chunk 1 — norm (CLAUDE.md) + canonical decision-file template (conventions doc; links the schema, doesn't duplicate it)
- [x] Chunk 2 — /compose-part Step 7 "Record the decision" (finished-move boundary, bright-line-gated, silent)
- [x] Chunk 3 — delegation carries capture (CLAUDE.md norm + /compose-part Step 7 + /song-pick-instruments Step 5 "survives delegation")
- [x] Chunk 4 — /compose-review §7 + /mix-review §7 DECISION-COMPLETENESS backstop
- [x] Chunk 5 — DEFERRED + filed to backlog as **DOC-4F8M** (derived-overview rot; not built here)

**Coherence fix that emerged (Chunk 1):** the canonical schema (`song-conventions.md`) **raises on unknown frontmatter keys**, requires `date` for decisions, and has `scope` ∈ {song,time,track,track-time}. The first template draft violated all three (`decided_by`, `scope: section`, no `date`) — would have broken the indexer; fixed. Also reconciled a pre-existing **dated-vs-numbered decision-filename** split (`song-new`/`song-pick-instruments` use `NN-`; `song-conventions`/`song-context`/historical `falling-walking` use dated) by documenting BOTH schemes honestly (filename orders; frontmatter `date` is the queryable *when*) rather than force-migrating real song data.

**Context:** Chunks 1–4 built; independent review = SOUND-WITH-NOTES (template verified schema-valid against the live validator `src/hallucinote/markdown_refs.py`; `write_markdown_ref` signature confirmed; design tension confirmed coherent). Both review WARNINGs cleared: (1) Chunk 5 actually filed to backlog as DOC-4F8M; (2) the dated-only contradiction at `song-conventions.md` "Authoring discipline" (`:186`, `:190`) reconciled. Ready to offer PR into develop.
