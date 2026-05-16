---
description: PR lifecycle management — create, update, merge, or check status with independent reviewer
argument-hint: "[create|update|merge|status]"
user-invocable: true
disable-model-invocation: false
allowed-tools: Bash(gh *), Bash(git *), Bash(python3 tools/product-hook test-status), Read, Write, Agent
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

### Step 2: Independent review — MANDATORY
**STOP. Do NOT proceed to step 3 until the reviewer agent has completed and written its evidence file.**

Spawn a **separate agent** (via the Task tool) for independent review. The reviewer must run in its own context — it has NOT seen your reasoning, and that independence is the point.

First, compute the evidence file path: take the current branch name, replace every `/` with `--`, append `.json`. For example, `feature/add-auth` becomes `feature--add-auth.json`. The full path is `.prawduct/.pr-reviews/<computed-filename>`.

Create the `.prawduct/.pr-reviews/` directory if it doesn't exist.

Tell the reviewer agent: "You are the PR reviewer. Read `.prawduct/pr-review.md` for your review instructions. The project is at `[project directory]`. The base branch is `[base branch]`. Review the changes on the current branch. Write your findings to the exact path: `.prawduct/.pr-reviews/[computed-filename]` — use this path exactly as given, do not compute your own filename."

**Pass the exact full path — do not ask the reviewer to compute the filename.** The reviewer's own instructions reinforce this: "Write to the exact file path provided by the caller."

**Wait for the agent to complete.** Then:
- Read the evidence file at `.prawduct/.pr-reviews/[computed-filename]`
- If the file does not exist, the review did not complete — do NOT proceed
- Present findings to the user: BLOCKING → stop and fix. WARNING → present, proceed unless user objects. NOTE → include in output.

### Step 3: Verify review gate
Before creating the PR, confirm:
- The evidence file `.prawduct/.pr-reviews/<branch-name>.json` exists
- It contains valid JSON with a `findings` array and `summary` field
- There are no unresolved BLOCKING findings

If any check fails, STOP. Do not create the PR.

### Step 4: Create PR
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
- Include review findings summary in the PR description
- **Never run `gh pr create` without a valid evidence file on disk**
