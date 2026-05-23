---
description: PR lifecycle management — create, update, merge, or check status with independent reviewer
argument-hint: "[create|update|merge|status]"
user-invocable: true
disable-model-invocation: false
allowed-tools: Bash(gh *), Bash(git *), Bash(python3 tools/product-hook test-status), Bash(python3 tools/product-hook check-cumulative-critic), Bash(python3 tools/product-hook check-operator-verification), Bash(python3 tools/product-hook accept-operator-verification *), Bash(python3 tools/product-hook check-pr-doc-only), Bash(python3 tools/product-hook check-pr-trivial), Read, Write, Agent
---

You are managing the PR lifecycle for this project. Detect the current state and take the appropriate action.

**CRITICAL: The independent PR review is the core value of this skill. Do NOT skip, defer, or abbreviate the reviewer agent step. If you create a PR without running the reviewer first, the review gate has failed.**

## Context Detection

Check git state to determine the action:

1. Run `git branch --show-current` to get the current branch
2. Run `git log --oneline main..HEAD` (or the configured base branch) to see commits ahead
3. Check if a PR already exists: `gh pr list --head <current-branch> --json number,state,statusCheckRollup,reviewDecision`
4. Check for uncommitted changes: `git status --short`

Then route:

| State | Action |
|---|---|
| No PR for current branch, branch has commits ahead of base | **Create** |
| PR exists, new local commits not pushed | **Update** |
| PR exists, CI green, approved (or no required reviewers) | **Merge** |
| PR exists, other state | **Status** |

The user can override with explicit arguments: `create`, `update`, `merge`, `status`.

$ARGUMENTS

## Create Flow

### Step 1: Branch hygiene
Verify on a feature branch (not main/master/develop). Verify commits ahead of base. If uncommitted changes, offer to commit or stash. **Before running the test suite, run `python3 tools/product-hook test-status` — if it exits 0 (`current`), the saved `.prawduct/.test-evidence.json` already covers the current tree (HEAD + uncommitted edits) and re-running is wasteful. Only run the suite if `test-status` reports `stale` or evidence is missing.** When you do run, write fresh evidence so the next caller can skip it.

### Step 1b: Doc-only fast-path
**Run `python3 tools/product-hook check-pr-doc-only`.** This mirrors the stop hook's session-end behavior at the PR boundary: when every file in `merge-base...HEAD` ends in `.md`, the cumulative-Critic and PR-reviewer gates add no value and are skipped.

- **Exit 0 (`doc-only`)**: Skip Steps 2, 2b, 3, and 4 — jump straight to Step 5 (Create PR). Note the skip in the PR description (e.g. "Doc-only PR — review gates skipped per check-pr-doc-only"). Tell the user which gates were skipped and why.
- **Exit 1 (anything else — `not-doc-only`, `empty-diff`, `no-base`, `git-failed`)**: Proceed to Step 1c.

### Step 1c: Trivial-code fast-path
**Run `python3 tools/product-hook check-pr-trivial`.** Parallel to Step 1b for the proportional-effort knob on code work: when every commit on `merge-base...HEAD` is fileset-eligible per the `Type: trivial` path bounds (no edits under `agents/`/`methodology/`/`templates/`, no `CLAUDE.md` edits, no test-file removals, no newly-tracked files), every chunk's rationale was Critic-passed in chunk-mode review and the cumulative pass would add no signal. The cumulative-Critic and PR-reviewer gates are skipped. Size is intentionally not a bound — trivial is a semantic claim, validated per-chunk by Critic Goal 3 (rationale-vs-diff fit).

- **Exit 0 (`trivial`)**: Skip Steps 2, 2b, 3, and 4 — jump straight to Step 5 (Create PR). Note the skip in the PR description (e.g. "Trivial-code PR — review gates skipped per check-pr-trivial; every commit is fileset-eligible per Type: trivial bounds"). Tell the user which gates were skipped and why.
- **Exit 1 (anything else — `not-trivial: commit <sha> <bound>`, `empty-diff`, `no-base`, `git-failed`)**: Proceed to Step 2. The gate fails closed; any failure to evaluate falls through to the full review path.

### Step 2: Cumulative-Critic gate — MANDATORY
**Run `python3 tools/product-hook check-cumulative-critic`.** This gate requires a fresh, blocking-free `cumulative`-mode Critic record covering `merge-base...HEAD`. If it exits non-zero, **STOP**: invoke `/critic cumulative` to produce the missing record, resolve any blocking findings, then re-check. Do NOT proceed to Step 3 until this gate passes.

While `/critic cumulative` runs (~4-10 min), do prep that doesn't depend on findings: `/learnings` for next-chunk topics, draft the PR description in your head, audit `.prawduct/backlog.md` for items this branch resolves, capture deferred chunk-boundary reflections. Reorganizes wait time; doesn't shorten it.

### Step 2b: Operator-verification gate — MANDATORY when `$ARGUMENTS` doesn't include `--accept-pending-verification`
**Run `python3 tools/product-hook check-operator-verification`.** Exit 0 means the gate is satisfied (either the queue requirement is off, or every entry is verified/accepted). Exit 1 means there are pending entries in `.prawduct/operator-verification.md` — stderr names the first ID and suggests next steps.

When pending entries exist, two paths:

1. **Verify the items** (preferred): for each pending `VRF-NNN`, complete the human-verification step described in the entry, then run `python3 tools/prawduct-setup.py verify <project_dir> <VRF-NNN>` to flip its status. Re-run the gate.
2. **Override for this PR**: if the user explicitly passes `--accept-pending-verification "rationale"` in `$ARGUMENTS`, run `python3 tools/product-hook accept-operator-verification "<rationale>"`. This flips every pending entry to `accepted` and records the rationale into each entry — the queue file is the work-log. The override is per-PR; future PRs will block again if new pending entries appear.

If the user did NOT supply the override flag and pending entries exist, **STOP**: do not proceed to Step 3 until either path above is taken. Present the stderr message and the two options to the user.

### Step 3: Independent review — MANDATORY
**STOP. Do NOT proceed to step 4 until the reviewer agent has completed and written its evidence file.**

Spawn a **separate agent** (via the Task tool) for independent review. The reviewer must run in its own context — it has NOT seen your reasoning, and that independence is the point.

First, compute the evidence file path: take the current branch name, replace every `/` with `--`, append `.json`. For example, `feature/add-auth` becomes `feature--add-auth.json`. The full path is `.prawduct/.pr-reviews/<computed-filename>`.

Create the `.prawduct/.pr-reviews/` directory if it doesn't exist.

Tell the reviewer agent: "You are the PR reviewer. Read `.prawduct/pr-review.md` for your review instructions. The project is at `[project directory]`. The base branch is `[base branch]`. Review the changes on the current branch. Write your findings to the exact path: `.prawduct/.pr-reviews/[computed-filename]` — use this path exactly as given, do not compute your own filename."

**Pass the exact full path — do not ask the reviewer to compute the filename.** The reviewer's own instructions reinforce this: "Write to the exact file path provided by the caller."

**Wait for the agent to complete.** Then:
- Read the evidence file at `.prawduct/.pr-reviews/[computed-filename]`
- If the file does not exist, the review did not complete — do NOT proceed
- Present findings to the user: BLOCKING → stop and fix. WARNING → present, proceed unless user objects. NOTE → include in output.

### Step 4: Verify review gate
Before creating the PR, confirm:
- The evidence file `.prawduct/.pr-reviews/<branch-name>.json` exists
- It contains valid JSON with a `findings` array and `summary` field
- There are no unresolved BLOCKING findings

If any check fails, STOP. Do not create the PR.

### Step 5: Create PR
Push branch with `-u`. Draft title and description from work context + review findings summary. Create via `gh pr create`. Update `pr_number` in the evidence file.

## Update Flow

1. Push new commits to remote
2. If substantive changes (not just formatting/comments), re-run the reviewer on the delta
3. Update PR description if scope changed
4. Update evidence file

## Merge Flow

**Check `project-preferences.md` for `PR merge` setting.** If set to `wait_for_user` (default), present the PR URL and findings summary to the user and wait for them to say "merge" before proceeding. If set to `automatic`, merge after CI passes and review is clean.

1. Verify CI checks pass (`gh pr checks`)
2. Verify no merge conflicts
3. Verify PR review evidence exists for this branch — if missing, run the reviewer first
4. Merge using squash strategy (or project-configured strategy from project-preferences.md)
5. Delete remote branch, switch to base branch, pull, delete local branch
6. Clean up evidence file
7. Clean up build plan: delete `.prawduct/artifacts/build-plan.md` if it exists. Git preserves full plan history.

## Status Flow

Show: PR URL, CI status, review status, approval status, merge readiness.

## Evidence

PR review evidence is stored in `.prawduct/.pr-reviews/<branch-name>.json` (with `/` replaced by `--` in filenames). The stop hook BLOCKS session end if a PR exists without review evidence.

## Important

- The PR reviewer runs as a **separate agent** — it must have independent context
- The reviewer reads `.prawduct/pr-review.md` for its instructions
- Run the full test suite before creating a PR — but check `python3 tools/product-hook test-status` first; skip the run if it reports `current`
- **Doc-only fast-path (Step 1b):** when `check-pr-doc-only` reports the entire `merge-base...HEAD` diff is `.md`, the cumulative-Critic and PR-reviewer gates are skipped. The gate fails closed — any error in evaluation falls through to the full review path. Mirrors the stop hook's `_session_changes_are_doc_only` exemption at the PR boundary.
- **Trivial-code fast-path (Step 1c):** when `check-pr-trivial` reports every commit on `merge-base...HEAD` is fileset-eligible per the `Type: trivial` path bounds (no `agents/`/`methodology/`/`templates/`/`CLAUDE.md` edits, no test deletions, no new files), the cumulative-Critic and PR-reviewer gates are skipped. Per-chunk Critic rationale-vs-diff review is the judgment backstop; the cumulative pass would add no signal when each chunk already cleared its own gate. Fails closed.
- **Run `python3 tools/product-hook check-cumulative-critic` before creating a PR** — this gate refuses to open a PR without a fresh, blocking-free `cumulative`-mode Critic record (see Step 2). The cumulative review (`merge-base...HEAD`) catches cross-chunk integration cracks per-chunk reviews can't see.
- **Run `python3 tools/product-hook check-operator-verification`** — when `operator_verification_required: true`, the gate refuses to open a PR if `.prawduct/operator-verification.md` has any pending entries. Drain via `python3 tools/prawduct-setup.py verify <dir> <VRF-id>` or override per-PR with `--accept-pending-verification "rationale"` (see Step 2b).
- Include review findings summary in the PR description
- **Never run `gh pr create` without a valid evidence file on disk**
