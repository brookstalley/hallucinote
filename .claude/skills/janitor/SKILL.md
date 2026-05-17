---
description: Periodic codebase maintenance — systematic health check across VCS hygiene, code quality, documentation fitness, test coverage, dependencies, controllability, and more
argument-hint: "[staleness=Nd] [scope=theme,...] [survey-only]"
user-invocable: true
allowed-tools: Bash(git *), Bash(npm *), Bash(python3 *), Read, Write, Edit, Glob, Grep, Agent
---

You are performing periodic codebase maintenance — a systematic health check that surfaces what day-to-day development overlooks. This is not a feature task. Your goal is to find what has drifted, accumulated, or been missed, then fix it through the standard Prawduct build cycle.

## The Janitor's Perspective

Approach this codebase as if seeing it for the first time after months away. The builders who work here daily have adapted to its quirks — your value is fresh eyes. Look for things that are:

- **Drifted** — once correct, now outdated (docs, configs, dead branches, stale TODOs)
- **Accumulated** — grew without anyone deciding to add it (duplication, complexity, unused dependencies)
- **Overlooked** — never wrong enough to fix in the moment (test gaps, missing tooling, organizational debt)

## Investigation Themes

These themes are universal starting points — they apply to any project regardless of domain, language, or technology. **They are not a checklist.** Adapt each theme to what you find in this specific codebase. A firmware project's "controllability" looks different from a web app's. A console game's "test fitness" looks different from a backend service's.

After investigating all themes, step back and ask: **what else has drifted, accumulated, or been overlooked that doesn't fit any theme?** The best janitor finding is often one nobody expected. Every project has its own maintenance needs shaped by its domain and history — discover them.

### Version Control Hygiene

Is the repository's history and branch structure clean and navigable?

- Branches that were merged but never deleted
- Branches with no activity within the staleness window (default: 14 days; see Arguments)
- Branches superseded by other work — started, then abandoned in favor of a different approach
- Orphaned work that was started but apparently abandoned with no resolution
- Files that should be ignored but aren't (build artifacts, editor files, secrets) — or vice versa

### Structural Clarity

Does the project's file organization reflect its architecture? Would a new contributor find things where they expect them?

- Source and test layout — intuitive, consistent, and conventional for this language and framework
- Module boundaries — do directory, package, or namespace boundaries match logical component boundaries?
- Configuration organization — scattered across the tree or collected sensibly?
- Dead directories — remnants of old features, experiments, or refactors that weren't cleaned up

### Code Health

Are the codebase's internal qualities sound? Would a domain expert reviewing this code find it unsurprising?

- Encapsulation — is internal state leaking across boundaries? Are there public APIs that should be private?
- Duplication — repeated logic that should be consolidated, or near-identical implementations that diverged
- Separation of concerns — are responsibilities clearly divided, or is business logic tangled with infrastructure?
- Coupling — are components appropriately independent? Can one module change without rippling?
- Complexity — is complexity proportionate to what the code actually does?
- Unmodeled state-based problems — anywhere the code moves through a discrete set of conditions (phases, modes, lifecycle stages, UI views, connection status, workflow steps) where the current condition governs what's valid, but the conditions aren't enumerated, valid/invalid transitions aren't named, and "what condition are we in" has to be reconstructed from flag combinations or order-dependent conditionals. Look for clusters of interdependent booleans that must stay in sync, phase/stage/mode variables whose transitions are scattered across call sites, and recovery paths that don't have a known-good condition to return to. Flag candidates for explicit modeling regardless of implementation shape (enum, class, protocol, reducer, type, schema, or doc all qualify) — the goal is to make the conditions, transitions, and invariants explicit, not to impose a particular mechanism.

### Artifact Fitness

Do all forms of documentation — comments, READMEs, specs, configs, generated docs, inline TODOs — describe the current system accurately?

- Stale documentation that no longer matches the code it describes
- Redundant documentation saying the same thing in multiple places (creating drift risk)
- Missing documentation where complexity or non-obvious behavior warrants explanation
- Orphaned docs describing removed or replaced features
- TODOs for work that was completed, or abandoned long enough to decide on

### Template Currency

Have product artifacts kept pace with framework template improvements?

When the session briefing shows template drift advisories, or when running a full survey, compare the product's place-once artifacts against the current framework templates. Check `.prawduct/sync-manifest.json` for `place_once_templates` entries — stored hashes indicate which template version was used when the product was created.

- project-preferences.md — Are there new preference fields the product hasn't declared?
- conftest.py — Are there new test infrastructure patterns available?
- boundary-patterns.md — Are there new contract surface types to consider?
- test-specifications.md — Are there new testing strategies (e.g., property-based testing) in the template that this product's specs don't address? Note: this is a planning artifact, not a place-once file — it won't have a `place_once_templates` entry. Compare by reading the framework template directly from `framework_source/templates/test-specifications.md`.

For each difference between the template and the product's version:
1. Read the current framework template (resolve via `sync-manifest.json` → `framework_source`, or try `../prawduct`)
2. Read the product's version of the file
3. Identify sections or fields in the template that are absent from the product's version
4. Assess whether each missing section is relevant to this product's domain and structural characteristics
5. Recommend additions where appropriate, noting "not applicable" where not

This is advisory, not mechanical — a CLI tool doesn't need property-based testing guidance just because the template now includes it. Use the product's structural characteristics and domain to judge relevance.

### Test Fitness

Are tests earning their maintenance cost? Do they catch real bugs and document real behavior?

- Behavioral coverage — are edge cases, error paths, and boundary conditions tested?
- Test quality — testing behavior (durable) or implementation details (brittle)?
- Test reliability — flaky tests or hidden dependencies on external state or ordering?
- Test organization — is the structure intuitive and navigable?
- Test speed — fast enough that developers (and agents) actually run them?

### Dependency Health

Are external dependencies current, justified, minimal, and secure?

- Unused dependencies — imported but not used, or listed but not imported
- Deprecated or unmaintained dependencies with no migration plan
- Known security vulnerabilities in current dependency versions
- Version constraints that are too tight (blocking updates) or too loose (risking breakage)

### Controllability

Can a developer — human or AI agent — control, debug, test, and observe the entire system effectively?

- Can the full system be built and run from a clean checkout with documented steps?
- Can individual components be tested in isolation?
- Are there development tools, scripts, or fixtures that are missing, broken, or undocumented?
- Can an agent exercise the system end-to-end for debugging and verification?
- Is there adequate observability (logs, metrics, debug output) for diagnosing problems during development?

### Obsolescence

Has past work left behind artifacts that no longer serve a purpose?

- Dead code — functions, classes, or modules that nothing calls
- Completed migrations — migration logic for transitions that finished
- Exhausted feature flags — flags for features that shipped or were abandoned
- Unnecessary backwards compatibility — shims, fallbacks, or adapters for versions nobody runs
- Resolved TODOs — comments marking work that was done but the marker wasn't removed
- Stale build plans — `.prawduct/artifacts/build-plan.md` from completed work (all Status items checked). Clean up: delete plan file

$ARGUMENTS

Arguments are optional. When provided, they adjust the janitor's behavior:

- **Staleness window**: Duration for branch inactivity detection. Default: 14 days. Example: `/janitor staleness=30d`
- **Scope**: Limit investigation to specific themes. Example: `/janitor scope=vcs,tests`
- **Survey only**: Produce findings without executing fixes. Example: `/janitor survey-only`

Theme shorthand for scope: `vcs`, `structure`, `code`, `docs`, `templates`, `tests`, `deps`, `control`, `obsolescence`

## Process

### Step 1: Orient

Understand the project before investigating. Read `project-state.yaml` to learn the domain, structural characteristics, language, and current state. Scan the directory structure. Identify the build system and test infrastructure. Read `.prawduct/backlog.md` if it exists — backlog items may overlap with maintenance findings.

Also read `project-preferences.md` (if present in `.prawduct/artifacts/`) to understand the project's declared conventions — language idioms, code style, testing approach, architecture patterns, and workflow preferences. These preferences are the project's stated standards, but they may not reflect current practice. Note them for comparison during the survey.

**Framework health pre-check.** Verify `.prawduct/sync-manifest.json` exists and `framework_source` is reachable. If framework infrastructure is broken or the manifest is missing, advise running `/prawduct-doctor` before proceeding — the janitor needs a healthy framework connection for Template Currency checks and general context.

This context shapes how you interpret every theme. "Structural clarity" means something different for a 500-line CLI tool than for a multi-service platform. "Controllability" means something different for firmware with a hardware simulator than for a web app with a dev server.

### Step 2: Survey

Work through each investigation theme (or the scoped subset), adapting your inquiry to this specific project. For each theme:

1. Investigate from that perspective
2. Note specific findings with file paths, line numbers, and concrete descriptions
3. Note project-specific concerns that the theme prompts but doesn't explicitly list
4. When `project-preferences.md` exists, note where actual code patterns diverge from stated preferences — flag these for reconciliation rather than assuming the code is wrong

**Do not fix anything during the survey.** Fixing during investigation creates tunnel vision — you optimize one area while missing systemic patterns across the codebase.

### Step 3: Reconcile

Before triaging, resolve findings where the correct resolution requires user judgment. Many findings are clear-cut — a dead branch is always cleanup, an unused import is always removal. But some findings are genuinely ambiguous, and triaging them without user input produces wrong priorities.

**Preference divergence** is the most important category. When `project-preferences.md` exists and the survey reveals that actual code patterns differ from stated preferences, this divergence is bidirectional:

- The code may have **drifted** from convention, and should be fixed
- The project may have **evolved** past its stated preferences, and the preferences file is stale

You cannot determine which without the user. For each divergence, use the infer-confirm-proceed pattern:

1. **State** what you found: "Preferences say snake_case for all functions, but the API layer consistently uses camelCase across 12 modules"
2. **Infer** the most likely explanation from context — git history, scope of divergence, whether it looks deliberate or accidental: "This looks intentional — the API layer matches the external contract's naming"
3. **Recommend** a resolution: "I'd update preferences to note this exception rather than renaming 47 functions"
4. **Confirm**: "Does that match your intent?"

Batch related divergences — don't ask one per message. Group by theme and present as a single confirm-or-correct block. Read fatigue signals: if the user starts answering with just "yes" or "sounds good," compress remaining questions into a single batch or infer more aggressively.

**This pattern extends beyond preferences.** Any finding where "drift or evolution?" is genuinely unclear should be reconciled: architectural patterns that don't match stated conventions, test approaches that diverge from declared strategy, documentation that contradicts implementation. When in doubt about intent, infer and confirm — don't interrogate.

**Record resolutions immediately.** If the user says preferences are stale, updating `project-preferences.md` becomes part of the janitor's work. If the user says code drifted, the fix enters triage with appropriate severity. Don't leave resolutions in conversation alone — they must reach an artifact or the findings list.

### Step 4: Triage

Categorize each finding on two dimensions:

**Severity:**
- **HIGH** — Actively harmful: bugs waiting to happen, misleading documentation, broken tooling, security concerns, significant duplication causing drift
- **MEDIUM** — Suboptimal but stable: could be cleaner, minor duplication, test gaps for non-critical paths
- **LOW** — Cosmetic or minor: style inconsistencies, slightly verbose docs, minor organizational improvements

**Effort:**
- **Quick** — Minutes, no risk (delete a dead branch, remove a stale TODO)
- **Moderate** — Straightforward but requires care (consolidate duplicated logic, update stale docs)
- **Significant** — Requires design thought or carries meaningful risk (restructure modules, change test architecture)

Present the complete findings to the user, organized by theme, with severity and effort tags. Include a recommended execution plan: what to fix first and why. Group quick fixes into a "quick wins" bundle.

### Step 5: Plan

After the user approves the scope, write a build plan to `.prawduct/artifacts/build-plan.md` (or update the existing one) following Prawduct methodology. Review the chunking and planning guidance in this project's CLAUDE.md.

**Chunking strategy for maintenance work:**
- Bundle quick fixes into a single "quick wins" chunk
- Group related moderate findings into coherent chunks (e.g., "VCS cleanup", "documentation refresh", "test gaps")
- Give significant findings their own chunk
- Preference updates resolved in Reconcile get their own chunk (or bundle with related doc updates)
- Order chunks: low-risk high-value first, high-risk last
- Each chunk must be independently testable and reviewable

### Step 6: Execute

Review the build cycle in this project's CLAUDE.md before writing any code. Follow the standard build cycle for each chunk:

- Run the full test suite before starting
- Build: understand the chunk spec → implement → verify
- Run the full test suite after each chunk
- Invoke the Critic as a separate agent after each chunk (mandatory for medium+ changes)
- Update artifacts as you go — if your cleanup changes something an artifact describes, update the artifact
- If `project-preferences.md` specifies PR preferences, follow them; otherwise, wait for the user to request a PR via `/pr`


### Step 7: Close

After all approved work is complete:
- Summarize what was changed, what was deferred, and why
- If template drift advisories were addressed, update the stored template hashes in `.prawduct/sync-manifest.json` → `place_once_templates` to mark them as reviewed. For each entry where the product's artifact was updated to incorporate the template's new content, recompute the template hash from the current framework template and write it back. This clears the advisory from future session briefings.
- Triage `.prawduct/backlog.md`: resolve items addressed by maintenance, remove stale items, add any new items discovered during maintenance
- Capture learnings in `.prawduct/learnings.md` if the maintenance surfaced patterns worth remembering
- Reflect: did the maintenance reveal systemic issues that suggest process changes, new tooling, or methodology updates?

## Important

- This is maintenance, not feature work. Do not add new functionality or refactor for taste.
- The survey is the most valuable phase. Resist the urge to fix things as you find them.
- Adapt themes to the project. The themes are prompts for investigation, not a fixed taxonomy of concerns.
- When removing code (dead code, backcompat shims, migrations), verify the paths are truly unreachable before deleting.
- If a finding requires significant redesign, flag it for a dedicated work cycle. The janitor cleans; it doesn't renovate.
- Follow the full Prawduct methodology: build plan, Critic review, reflection, learning capture. Maintenance work is real work and gets full governance.
