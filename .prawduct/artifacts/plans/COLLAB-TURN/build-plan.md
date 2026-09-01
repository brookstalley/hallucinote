<!-- Build Plan — COLLAB-TURN (collaboration turn model). Tier 1 (Source of Truth).
     WHAT to build. For HOW (governance, test discipline, Critic), read /prawduct:methodology building.
     Design artifact (diagnosis, model, owner rulings): .prawduct/artifacts/collaboration-turn-model.md
     Evidence: .prawduct/artifacts/collaboration-corpus/ (cases CTM-01..20) -->
---
artifact: build-plan
version: 2
scope: collab-turn
branch: design/collaboration-turn-model
depends_on:
  - artifact: design
    path: .prawduct/artifacts/collaboration-turn-model.md
  - artifact: evidence
    path: .prawduct/artifacts/collaboration-corpus/README.md
governed_by:
  - artifact: project-preferences
    dispositions:
      - "Full suite runs with no path argument → conforms (coordinator's integration run)"
      - "Test file lives next to the module it tests → conforms (init_workspace test stays in tests/unit/tools/)"
      - "Never swallow exceptions silently → conforms (the governed-repo probe raises nothing and catches nothing)"
      - "All writes go through db.mutations / mutators emit events / generators pure / sync produces plans → inapplicable because this plan touches no DB, generator or sync code"
      - "Close-in-the-same-PR as ONE ship-stamp commit → conforms (chunk 06)"
  - artifact: architecture
    dispositions:
      - "_FINGERPRINT_PATHS names exactly the vendored Live-side code → conforms; the two MCP surfaces this plan edits (the primer string in server.py and resources/guides/getting-started.md) are outside the fingerprint by construction, so no re-vendor is triggered"
      - "server_side/ package, async handlers, start+status for long ops → inapplicable because no handler changes"
partition: >-
  Wave A delegated — chunks 01, 02, 03, 04 in four isolated worktrees, disjoint
  file ownership (see Delegation); coordinator integrates. Wave B serial —
  05 and 06 depend on Wave A's final wording and edit shared doc surfaces.
last_validated: 2026-09-01
---

## Requirements Confidence

**Level:** High for content; Medium for effect.

**Why:** Every norm, skill change and doc change below is specified by the
design artifact, which the owner ratified clause by clause on 2026-09-01
(*Resolved by the owner*). What holds the plan at Medium on one axis is the
thing no prose plan can prove: whether a **cold** agent, loading `CLAUDE.md`
plus one skill, actually holds a conversation to the user's hand-off instead of
regressing into the wall (CTM-07) or the early close (CTM-09). The August fix
decayed in one take. This plan answers that with the strongest levers prose
allows — precedence in `CLAUDE.md`, the vocabulary repeated nowhere and linked
everywhere, a drift lock on every surface — plus one live operator session as
the acceptance test. It does **not** build an eval: the scenario harness under
`tests/scenarios/` stays as it is (its rubrics are compatible; verified), and
the external eval framework consumes the corpus when it lands.

**Open assumptions:**
- `[ASSUMPTION: docs/tour.md is left unchanged — it is a record of a real session ("documented as they happened") and is locked by tests/preferences/test_tour_freshness.py; its "last decision they were asked to make" line is history, not a promise | LOW impact | user can override]`
- `[ASSUMPTION: governed repo = a .prawduct/ directory at the working directory or any ancestor up to the filesystem root; detection is a pure path probe with no plugin dependency | MED impact | user can override]`
- `[ASSUMPTION: .prawduct/artifacts/elicitation-and-stage-exit-criteria.md gets a status amendment naming what superseded it (the one-turn bound), not a rewrite — the three-state model and the no-unresolved-gap rule it defines remain in force | LOW impact | user can override]`
- `[ASSUMPTION: the scenario briefs under tests/scenarios/briefs/ are not edited — grep confirms none encodes the one-turn rule, and theo/sam already carry "propose, don't assume" and "must not interrogate" | LOW impact | user can defer]`
- `[ASSUMPTION: no CHANGELOG.md user-facing entry until release; the .prawduct/change-log.md entry carries scope=collab-turn per the repo convention | LOW impact]`

**What would raise it:** the operator session in chunk 06 — one loaded prompt
(*"make a rap song"* or the owner's choice) run against the merged norms in a
songs workspace, read for: no build before a proposal, identity not closed
while the user is adding, a hearing offered at the first unit and not required.

## Status

- [x] Chunk 01: `CLAUDE.md` — the norms, re-weighted
- [x] Chunk 02: `/song-brief` — from one turn to a conversation that ends at hand-off
- [x] Chunk 03: `/song-new` + `/getting-started` + governed-repo detection
- [x] Chunk 04: `/song-workflow` skill + `docs/song-workflow.md` — the hearing loop
- [x] Chunk 05: docs sweep — every remaining surface that promised "once"
- [x] Chunk 06: drift lock, bookkeeping, operator session, cumulative Critic

## Goal

Make the shipped agent work *with* the person: read each turn before acting,
build no further than the next hearable unit without offering to play it, keep
identity open until the user hands off, and open a loaded prompt's domain
instead of running with it — without bringing back the June failure of stopping
to ask permission at every procedural seam.

## Vocabulary — defined once, in the design artifact

Every chunk uses these words and **links** to
`.prawduct/artifacts/collaboration-turn-model.md` for their definitions; no
chunk restates them (the repo's *link, don't summarize* learning, and the
"rule restated in N carriers drifts in N-1" learning):

**turn kind** (directing / reacting / exploring / asking / delegating /
handing-off) · **hearable unit** · **the status offer** · **decline with
scope** · **owner column** (yours / offer me options / mine) · **loaded prompt**.

Two of them get a *short* definition in `CLAUDE.md` because that is the one
surface loaded every session; the skills point at `CLAUDE.md` and the artifact.

**Amendment, 2026-09-01 — definition vs rule.** As first written, "no chunk
restates them" could not be obeyed: the design artifact's own *Constraints*
require the norms to work cold from `CLAUDE.md` plus one skill, and chunks 02(b)
and 02(f) direct a skill to carry the reply-reading signals and the status offer.
Three independent chunk reviewers each found the same defect on a different file
— every one of them a file promising it did not restate and then restating. The
line the rule was reaching for:

- A **definition** — what a term *means* — has exactly two homes: this design
  artifact, and the short definition in `CLAUDE.md`. Nowhere else.
- A **rule stated in terms already defined** — what to *do*, and where it fires —
  belongs wherever it fires, and is not restatement. "Compose the first hearable
  unit, then offer a hearing" is a rule; "the hearable unit is the smallest thing
  that, once heard, …" is a definition.
- **Bounded exception:** `docs/song-workflow.md` may carry one one-line gloss of
  *hearable unit*, because it is human-facing and its reader does not auto-load
  `CLAUDE.md`. One doc, one term.
- **No file may claim it does not restate while restating.** The claim is worse
  than the restatement: a maintainer trusts it and never looks for the second
  copy.

Chunk 06 locks this — the definitional phrase may appear only in the artifact,
`CLAUDE.md`, and `docs/song-workflow.md`.

## Retired phrases — the sweep's target list

These are the promises the plan retires. Chunk 05 greps the tree for them and
chunk 06 locks the grep as a test. Historical records (`docs/tour.md`,
`.prawduct/artifacts/archive/`, the corpus, `.prawduct/change-log.md`,
`.prawduct/learnings*.md`) are exempt by path.

- `one consolidated turn` / `ONE consolidated turn` / `exactly one consolidated`
- `comes back **once**` / `Come back **once**` / `comes back once`
- `that was the last decision they were asked to make` (tour only — exempt)
- `collapses 5 other answers into one`
- `I drive this to a finished, rendered song without stopping` and its kin —
  any sentence in a skill that announces an uninterrupted drive to the finish

## Corpus traceability

| Chunk | Cases it answers |
|---|---|
| 01 | CTM-02, 03, 07, 09, 10, 12 (the two-sided rule), 13, 20 |
| 02 | CTM-01, 05, 07, 08, 09, 14, 15, 19 |
| 03 | CTM-10, 11, 13 (governed repo), 16 |
| 04 | CTM-04, 10, 11, 17 |
| 05 | CTM-07 (README/quickstart promise), CTM-14 (checklist §2/§11) |
| 06 | all — the lock |

## Delegation

**The owner asked for this plan to be built by parallel subagents**, which is
the standing approval; no further ask. Precedent for delegated builds exists
in this repo (DEV-4P7R / PR #177 ran independent agents in worktrees), though
no prior plan recorded a `partition:` line — chunk 06 makes the policy durable
in `project-preferences.md` so the question does not return.

**Wave A — four delegates, four isolated worktrees**, each cut from
`design/collaboration-turn-model` onto its own branch
(`collab/01-norms`, `collab/02-song-brief`, `collab/03-song-new`,
`collab/04-workflow`). The coordinator creates each worktree, writes the brief
into it at new `.prawduct/.delegate-brief.md` (per worktree), then dispatches the agent at that
directory. File ownership is disjoint by construction:

| Delegate | Owns (may edit) | Must not touch |
|---|---|---|
| 01 | `CLAUDE.md` | anything else |
| 02 | `skills/song-brief/SKILL.md` | `docs/skills.md` (05 mirrors the description from 02's result) |
| 03 | `skills/song-new/SKILL.md`, `skills/getting-started/SKILL.md`, `src/hallucinote/tools/init_workspace.py`, `tests/unit/tools/test_init_workspace.py`, the `init-workspace` CLI surface in `src/hallucinote/cli.py` if the flag needs plumbing | skill files other than the two named |
| 04 | `skills/song-workflow/SKILL.md`, `docs/song-workflow.md` | `README.md`, `docs/skills.md`, `docs/quickstart.md` |

**Model per chunk.** The owner's rule: Opus 5 for mechanical parts; Fable 5.1
where the result is materially better for it.

- **Fable — 01, 02, 04.** These are the surfaces a *cold agent reads to learn
  the register*: the always-loaded norms, the skill that runs the conversation,
  and the "READ THIS FIRST" lifecycle map. Their quality is the whole
  intervention. The August rewrite of the same surfaces was good on the opening
  turn and silent on everything after it; the failure was in what the prose
  did *not* say. That is a judgment-of-omission problem, and it wants the
  strongest writer.
- **Opus — 03, 05, 06.** Rescoping sentences against a fixed vocabulary, a
  bounded code change with tests, a tree-wide grep sweep, a parity test,
  bookkeeping.

**What each delegate returns:** its branch name, the diff summary, the exact
verification it ran (its ceiling, below), any wording it had to *decide* rather
than copy from the design artifact (marked **proposed**), and anything it left
for integration. Delegates do **not** run the Critic, tick Status boxes, touch
`project-state.yaml`, or write to the change log.

**Verification ceiling per delegate** (never the coordinator's run):
- 01, 02, 04: `python -m pytest tests/unit/test_song_lifecycle_doc_parity.py -q`
  plus `git grep -n` for each retired phrase inside the files they own.
- 03: `python -m pytest tests/unit/tools/test_init_workspace.py tests/unit/test_song_lifecycle_doc_parity.py -q`.

**Coordinator integration (Wave A → design branch):** merge the four branches
(`--no-ff`); disjoint ownership means no textual conflicts, but the coordinator
reads the four results *together* for vocabulary drift before merging — the
seam nobody else checks. Then `python -m pytest` with no path argument. Then
Wave B, serial, in the design worktree.

**Governance mechanics — worktree caveat.** Prawduct's gates run in the
primary checkout and are blind to this worktree (`feedback_worktree_governance_gates_blind`).
Per-chunk `chunk`-mode Critic reviews are therefore run as independent reviewer
Agents pointed at the design worktree with the chunk's section as the goal;
chunk 06's cumulative review is the same, against `origin/develop...HEAD`. The
PR is opened with `gh` into `develop`.

## Build Chunks

### Chunk 01: `CLAUDE.md` — the norms, re-weighted

- **Description:** Rewrite the *Hallucinote Behavioral Norms* section so that
  "the user leads the creative project" is the primary norm and the stop-less
  rule is explicitly **scoped to procedural stops**. Retire the *opening
  elicitation turn* bullet (the "exactly one consolidated turn" rule) and
  replace it with the design artifact's *Proposed norm text*: read the turn
  (six kinds; only directing and handing-off authorize a build; musing touches
  nothing); build to the hearable unit and **offer** a hearing before building
  further, never require one, remember a decline with scope; identity closes at
  hand-off, never by inference; the status offer; own / offer / execute per the
  owner column; a loaded prompt opens its domain. Rewrite the *Creative product
  prompts vs planning prompts* paragraph so "drive end-to-end" becomes "drive to
  the next hearable unit, offer, continue" — the deliverable is still the
  finished thing; what changes is how many units are built between offers. Add
  one sentence under the stop-less norm making the two-sidedness explicit:
  CTM-12 ("wait why are we pausing?") is still a failure. Add a short *Song
  work belongs in a songs workspace* norm: a song conversation opens with the
  music, governance advisories and the standing block are for engineering
  turns, and starting song work inside a governed repo earns a warning (chunk
  03 builds the probe). Every permission to propose or stop restates its
  precedence guard in the same breath (learnings: *A permission to collaborate
  must restate precedence*). Keep the section's other norms (sound design is
  composition; microtiming; attempt ledger; rationale ships in `decisions/`)
  unchanged except where they cite the retired one-turn rule.
- **Depends on:** none
- **Artifacts consumed:** `.prawduct/artifacts/collaboration-turn-model.md` §*The model*, §*Proposed norm text*, §*Resolved by the owner*; corpus cases CTM-02, 03, 07, 09, 10, 12, 13, 20
- **Deliverables:** `CLAUDE.md` (the Hallucinote Behavioral Norms section only; the Prawduct governance section above it is not touched)
- **Tests:** `tests/unit/test_song_lifecycle_doc_parity.py` still passes (CLAUDE.md must still name `/song-brief`); no retired phrase remains in the file
- **Acceptance criteria:** the section reads as a coherent set of norms a cold agent can act on, none of which contradicts another; the stop-less rule and the collaboration rule name each other's boundary; the six turn kinds and the hearable unit are each defined in one sentence and the rest is linked, not restated
- **Type:** doc-only
- **Critic mode:** final
  <!-- Keystone: every other chunk links here for precedence. Worth the full review before the skills are integrated against it. -->
- **Model:** Fable
- **Done when:**
  1. Acceptance criteria met; parity test green; retired-phrase grep clean in `CLAUDE.md`
  2. Independent reviewer Agent run against the chunk (see *Governance mechanics*); blocking findings resolved
  3. Merged to the design branch by the coordinator and chunk marked `[x]` in Status

### Chunk 02: `/song-brief` — from one turn to a conversation that ends at hand-off

- **Description:** Rewrite `skills/song-brief/SKILL.md` around the model while
  keeping what was right: the three-state relevance sweep, *a stage may not emit
  an unresolved gap*, the DESCRIBED-BUT-UNBUILT prohibition, the meter section,
  the existing-songs mode, the exit criteria, and the write-the-brief-after-
  scaffold ordering. What changes: (a) **Step 2 becomes the conversation** —
  open with the identity questions you cannot guess (at most two or three,
  CTM-19 is the exemplar), decide and *show* the craft, offer reads as
  redirectable, and keep talking until the user hands off; the *"one turn, not
  renegotiable"* bound is deleted, and its two failure modes (the stage that
  never converges; the turn that fragments) are re-expressed as *the status
  offer* and *the hearable unit*, which are what actually bound the
  conversation now. (b) **Reading the reply:** an answer that adds a noun is
  not a closure; silence on an asked item is still-thinking; identity is never
  closed by inference (CTM-09, quoted briefly as the cautionary case). (c) **No
  pickers on creative questions** — `AskUserQuestion` is for enumerable
  engineering choices (CTM-05, 08, 14). (d) **Loaded prompts** — the general
  rule with the artifact's symphony / rap / ambient / reference-artist
  examples; unpack briefly, state what you take as read, ask the two or three
  that change the song most. (e) **The brief template gains the owner column**
  (`yours / options / mine`) and the file is described as a ledger the stage
  updates every turn, not writes once; the *Still open* table's rows still name
  an owner and a closing stage. (f) **The stage closes with the status offer**,
  and hands the resolved values to `/song-new` exactly as before. (g) Frontmatter
  `description` rewritten to match (it currently promises ONE consolidated
  turn); chunk 05 mirrors it into `docs/skills.md`. (h) The *Design + rationale*
  link points at both the elicitation artifact (for the three-state model) and
  the collaboration artifact (for the conversation). Every permission to
  propose restates its precedence guard.
- **Depends on:** none (vocabulary comes from the design artifact, not from chunk 01's final wording)
- **Artifacts consumed:** `.prawduct/artifacts/collaboration-turn-model.md` (all of §*The model*); corpus cases CTM-01, 05, 07, 08, 09, 14, 15, 19; `.prawduct/artifacts/elicitation-and-stage-exit-criteria.md` for what is kept
- **Deliverables:** `skills/song-brief/SKILL.md`
- **Tests:** parity test green; retired-phrase grep clean in the file; the brief template in the file parses as the frontmatter schema `docs/song-authoring-conventions.md` defines (learning: validate a template against the live validator, not prose — run the annotation validator the conventions doc names against the template block)
- **Acceptance criteria:** a reader can follow the skill from a loaded prompt to a hand-off without meeting a step that says "one turn" or "then close"; the exemplar turn in the file is under ~300 words and asks about identity while showing craft; the owner column is in the template with its three values
- **Type:** doc-only
- **Model:** Fable
- **Done when:**
  1. Acceptance criteria met; tests and greps clean
  2. Independent reviewer Agent run against the chunk; blocking findings resolved
  3. Merged to the design branch by the coordinator and chunk marked `[x]` in Status

### Chunk 03: `/song-new` + `/getting-started` + governed-repo detection

- **Description:** Three bounded edits and one small code change. (a) In
  `skills/song-new/SKILL.md`: the *Deliverable shape* read stays, but every
  "drive end-to-end" / "chain through them, stopping only for…" sentence is
  rescoped to *drive to the next hearable unit, offer a hearing, continue*;
  the *Final report — creative product prompt* block (which today tells the
  agent to announce an uninterrupted drive and "immediately invoke
  `/song-pick-instruments` and continue") is rewritten so the first hearable
  unit — typically one part or one section, pushed and audible — precedes the
  rest of the palette and composition, with the status offer at that point;
  the Phase 1 paragraph stops describing the brief as one consolidated turn and
  links to `/song-brief`; the workspace check reads the new `governed_repo`
  flag and, when true, says so and warns before scaffolding (heads-up, never a
  block — the framework repo legitimately hosts `examples/`). (b) In
  `skills/getting-started/SKILL.md`: the *Not in a songs workspace* bullet
  gains the same governed-repo sentence; the *new song* branch describes
  `/song-brief` as the conversation, not "the elicitation stage that produces
  values". (c) In `src/hallucinote/tools/init_workspace.py`: add
  `governed_repo: bool` to `InitResult`, computed by a pure probe for a
  `.prawduct/` directory at the target directory or any ancestor (the same walk
  shape `find_workspace` uses for the marker); surfaced in `--check` output;
  plumbed through `src/hallucinote/cli.py` only if the check output is
  assembled there rather than from the dataclass.
- **Depends on:** none
- **Artifacts consumed:** design artifact §*The model* 3 (the status offer), §*Resolved by the owner* 2; corpus cases CTM-10, 11, 13, 16
- **Deliverables:** `skills/song-new/SKILL.md`, `skills/getting-started/SKILL.md`, `src/hallucinote/tools/init_workspace.py`, `tests/unit/tools/test_init_workspace.py`
- **Tests:** unit — `governed_repo` true with a `.prawduct/` at the directory, true with one at an ancestor, false otherwise, and unaffected by `already_workspace`; `--check` JSON carries the key; existing init-workspace tests unchanged and green
- **Acceptance criteria:** `"$PY" -m hallucinote.cli init-workspace --check` run inside this repo reports `governed_repo: true`; run inside a plain temp directory reports `false`; neither skill file contains a retired phrase or an announced uninterrupted drive
- **Model:** Opus
- **Done when:**
  1. Acceptance criteria met and tests pass
  2. Independent reviewer Agent run against the chunk; blocking findings resolved
  3. Merged to the design branch by the coordinator and chunk marked `[x]` in Status

### Chunk 04: `/song-workflow` skill + `docs/song-workflow.md` — the hearing loop

- **Description:** The lifecycle map gains what the corpus shows it is missing:
  a **hearing** after the first hearable unit, offered not required, before the
  rest is composed. Concretely, in both files: (a) stage 0's description stops
  saying "one consolidated turn" and describes the conversation that ends at
  hand-off, linking to `/song-brief` and the design artifact; (b) the arc
  gains a sentence at the compose step (stage 3) and in the *loop, not a line*
  framing: compose the first hearable unit → push → **offer** a hearing → the
  status offer → continue; the definitions-of-done table keeps its eight rows
  and its exact `N · \`/stage\`` format (the parity test depends on both) — the
  hearing is a property of the loop, not a ninth stage, and the doc says so
  where it says why stage 8 has no criterion; (c) the stage-0 *done when* row
  adds the owner column to what the brief must carry; (d) the *Creativity
  first* / *producer not gatekeeper* paragraph names the two-sided rule: never
  stop to summarize-and-ask, never build past a hearable unit without offering
  to play it; (e) the skill's *If you only remember one thing* line becomes
  four things, the fourth being the hearing offer. The exit-criteria table's
  single home is preserved; the design artifact link is added beside the
  elicitation artifact's.
- **Depends on:** none
- **Artifacts consumed:** design artifact §*The model* 1–3, §*Resolved by the owner* 1 and 3; corpus cases CTM-04, 10, 11, 17
- **Deliverables:** `skills/song-workflow/SKILL.md`, `docs/song-workflow.md`
- **Tests:** `tests/unit/test_song_lifecycle_doc_parity.py` green — in particular `test_workflow_doc_defines_done_for_every_authoring_stage`, `test_song_workflow_skill_does_not_undercount_the_checkpoints`, and every deep-link anchor still resolving; retired-phrase grep clean in both files
- **Acceptance criteria:** a reader of either file can say where in the loop the user first hears something and that they may decline; neither file promises "once"
- **Type:** doc-only
- **Model:** Fable
- **Done when:**
  1. Acceptance criteria met; parity test green; greps clean
  2. Independent reviewer Agent run against the chunk; blocking findings resolved
  3. Merged to the design branch by the coordinator and chunk marked `[x]` in Status

### Chunk 05: docs sweep — every remaining surface that promised "once"

- **Description:** Tree-wide, after Wave A is merged, so the wording it mirrors
  is final. Surfaces and the change at each: `README.md` *Under-specify on
  purpose* bullet (from "comes back **once**" to the conversation and the
  hearing offer, in the README's register); `docs/quickstart.md` step that says
  "Come back **once**"; `docs/skills.md` `/song-brief` row (copy the new
  frontmatter description from chunk 02's file — one source); `docs/song-new-checklist.md`
  the "One consolidated turn" paragraph near the top, §2 *Genre / style anchor*
  and §11 *References* (a loaded word *opens* its domain; delete "collapses 5
  other answers into one"); `hallucinote_mcp/src/hallucinote_mcp/resources/guides/getting-started.md`
  and the lifecycle primer string in `hallucinote_mcp/src/hallucinote_mcp/server.py`
  (verify each describes the brief as a conversation — both are outside
  `_FINGERPRINT_PATHS`, so no re-vendor; confirm by running the fingerprint
  before and after); `.prawduct/artifacts/elicitation-and-stage-exit-criteria.md`
  gets a dated status amendment at its top naming what the collaboration
  artifact superseded (the one-turn bound and the "watchable on camera"
  rationale) and what still stands. Then the sweep itself: `git grep -n` for
  every retired phrase across the tree, excluding the exempt paths; every hit
  is either changed or listed in the chunk's result with the reason it is
  exempt. `docs/tour.md` is exempt by the assumption above and is not edited.
- **Depends on:** Chunks 01–04 merged
- **Artifacts consumed:** the merged Wave A files (the source of wording); design artifact §*Retired phrases* via this plan
- **Deliverables:** `README.md`, `docs/quickstart.md`, `docs/skills.md`, `docs/song-new-checklist.md`, `hallucinote_mcp/src/hallucinote_mcp/resources/guides/getting-started.md`, `hallucinote_mcp/src/hallucinote_mcp/server.py` (primer text only), `.prawduct/artifacts/elicitation-and-stage-exit-criteria.md` (status block only)
- **Tests:** parity test green; `python -m pytest hallucinote_mcp -q` green (the primer string is read by MCP tests); fingerprint unchanged before/after
- **Acceptance criteria:** the retired-phrase grep returns hits only in exempt paths; the MCP fingerprint is byte-identical
- **Type:** doc-only
- **Model:** Opus
- **Done when:**
  1. Acceptance criteria met and tests pass
  2. Independent reviewer Agent run against the chunk; blocking findings resolved
  3. Committed and chunk marked `[x]` in Status

### Chunk 06: drift lock, bookkeeping, operator session, cumulative Critic

- **Description:** Make the sweep permanent and close the plan. (a) new `tests/unit/test_collaboration_norm_parity.py`,
  a sibling of the lifecycle
  parity test: asserts that no non-exempt markdown or skill surface, and
  neither MCP text surface, contains a retired phrase (the list lives in the
  test, with the exempt path set); that `CLAUDE.md` names all six turn kinds
  and the phrase "hearable unit"; that `skills/song-brief/SKILL.md`'s template
  carries the owner column with its three values; and that `docs/skills.md`'s
  `/song-brief` row equals the skill's frontmatter description (the mirror
  chunk 05 established). (b) `.prawduct/artifacts/project-preferences.md` gains a `Delegation`
  row (pre-approved: isolated worktrees, disjoint ownership, coordinator
  integrates; delegate verification ceiling = the narrowest test file that
  covers the delegate's own change) so the partition question does not return.
  (c) `.prawduct/change-log.md` entry, `scope=collab-turn`. (d) The design
  artifact's status line moves from *discovery complete* to *built — awaiting
  operator session*. (e) **Operator verification entry** in
  `.prawduct/operator-verification.md`: the owner starts a song in a songs
  workspace with the merged plugin from a loaded prompt of their choosing and
  reads the session against three things — no build before a proposal turn,
  identity not closed while they were still adding, a hearing offered at the
  first unit and not required. This is the acceptance test for the Medium
  axis of the confidence field. (f) Commit, then the cumulative Critic against
  `origin/develop...HEAD` via an independent reviewer Agent.
- **Depends on:** Chunk 05
- **Artifacts consumed:** this plan's §*Retired phrases*; `tests/unit/test_song_lifecycle_doc_parity.py` as the pattern
- **Deliverables:** new `tests/unit/test_collaboration_norm_parity.py`, `.prawduct/artifacts/project-preferences.md`, `.prawduct/change-log.md`, `.prawduct/artifacts/collaboration-turn-model.md` (status line, and the applied-norms pointer replacing the draft copy), `.prawduct/operator-verification.md`, `.prawduct/project-state.yaml` (added at build time: this plan retires a *ratified* norm, and a retirement is a lifecycle transition to record rather than a row to delete — the plan as written had no home for it)
- **Tests:** the new test, run first against the tree *before* chunk 05's edits (a discriminating test must be run against the examples it is meant to separate — check it out on the pre-sweep commit and confirm it fails there), then green on HEAD; `python -m pytest` with no path argument green
- **Acceptance criteria:** new test fails on the pre-sweep tree and passes on HEAD; full suite green; change-log entry present with the scope tag; operator entry queued
- **Type:** cumulative-final
- **Visual change:** yes — the operator session (e) is the human read of copy and register that no test can give
- **Model:** Opus
- **Done when:**
  1. Acceptance criteria met and the full suite passes
  2. Committed, then the cumulative review run and blocking findings resolved
  3. Chunk marked `[x]` in Status; `gh pr create` into `develop` when the owner asks

## Early Feedback Milestone

**Milestone chunk:** after Wave A merges (before chunk 05). **What the user can
do:** read the four rewritten surfaces together — `CLAUDE.md`, `/song-brief`,
`/song-new`, `/song-workflow` — as one voice, and correct register or
precedence before the sweep copies that wording into six more places.

## Governance Checkpoints

**Commit & PR cadence:** each Wave A delegate commits on its own branch; the
coordinator merges each with `--no-ff` after its review, so the design branch
carries one commit per chunk. Chunks 05 and 06 commit directly on the design
branch. Chunk 06's cumulative review makes the branch PR-ready.

- **After Wave A merges:** read the four files as one document. The seam to
  check is vocabulary drift — one delegate calling it a "playable unit", another
  "hearable" — and any permission to propose that lost its precedence guard in
  the rewrite.
- **After chunk 05:** the retired-phrase grep is the trajectory check; a hit in
  a non-exempt path means a surface nobody listed.
- **After chunk 06 (cumulative):** full-bundle review, then the operator
  session. If the session shows the wall or the early close again, that is a
  finding against the *prose lever itself*, and the answer is not a seventh
  chunk of prose — it is to bring the eval framework in sooner.
