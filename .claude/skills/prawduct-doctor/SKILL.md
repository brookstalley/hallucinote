---
description: Product repo setup, health check, and repair
argument-hint: "[target-path] [--name NAME]"
user-invocable: true
disable-model-invocation: false
allowed-tools: Bash(python3 *), Read, Glob
---

You are managing prawduct product repo setup and health. Detect the current context and take the appropriate action.

## Context Detection

1. Check if an explicit target path was provided as an argument
2. Check if the current directory has `.prawduct/` (is a product repo)
3. Check if `tools/prawduct-setup.py` exists locally (framework repo)

Then route:

| Context | Action |
|---|---|
| Explicit target path provided | **Onboard**: set up the target as a product repo |
| Current dir is a product repo (has `.prawduct/`) | **Health check**: validate and offer repair. If health is good, mention available per-feature migrations (`migrate --enable-coverage`, `migrate --enable-settings-layout`, `migrate --enable-operator-verification`) when relevant. |
| User asks "enable coverage" / "turn on F4" / "stamp settings layout" / "run migrate-settings" / "enable operator verification" / "turn on F10" / similar | **Migrate**: see Migrate Flow below |
| User asks to "verify VRF-NN" / "drain operator verification" / "mark verified" | **Verify**: see Verify Flow below |
| User asks "audit learnings" / "retire structurally-enforced learnings" / "check lifecycle metadata" / similar | **Audit Learnings**: see Audit Learnings Flow below |
| Current dir is the framework repo (has `tools/prawduct-setup.py`) and no target | Ask what the user wants to do |

## Onboard Flow (target path provided)

1. Confirm the target directory and product name with the user
2. Run: `python3 tools/prawduct-setup.py setup <target> --name "<name>" --json`
   - If running from a product repo, resolve the framework path first:
     check `.prawduct/sync-manifest.json` for `framework_source`, or use `PRAWDUCT_FRAMEWORK_DIR`, or try `../prawduct`
3. Parse the JSON result and report what was done
4. Tell the user: **"Open `<target>` in a new Claude Code session for governance to activate. Hooks and the session briefing won't fire until then."**

## Health Check Flow (current dir is a product repo)

1. Resolve the framework path from `.prawduct/sync-manifest.json` `framework_source`, or `PRAWDUCT_FRAMEWORK_DIR` env var, or sibling `../prawduct`
2. Run: `python3 <framework>/tools/prawduct-setup.py validate "$CLAUDE_PROJECT_DIR" --json`
3. Parse the JSON result and present findings:
   - **healthy**: "All checks pass. Your prawduct setup is healthy."
   - **degraded**: List warnings, explain implications, offer fixes
   - **broken**: List failures, recommend repair
4. If `needs_restart` is true: **"Restart Claude Code to pick up updated settings/CLAUDE.md."**
5. If framework is unreachable: advise setting `PRAWDUCT_FRAMEWORK_DIR` or cloning framework as `../prawduct`
6. If repair needed: offer to run `python3 <framework>/tools/prawduct-setup.py setup "$CLAUDE_PROJECT_DIR" --json`

## Migrate Flow (per-feature v1.4 opt-ins)

The `migrate` subcommand surfaces v1.4 features that require explicit user intent. Two flags exist; each requires its own invocation (the subcommand rejects multiple flags in one call).

### `--enable-coverage` (F4 — symbol-coverage enforcement)

Workflow commitment: once enabled, the Critic's Goal 1 BLOCKS on changed files missing from `.test-evidence.json`'s `changes_referenced`. Use when the user asks to "enable coverage", "turn on F4", "switch to executed coverage", or similar.

1. Resolve the framework path the same way as Health Check (manifest `framework_source`, env, sibling).
2. Confirm intent with the user — surface the BLOCKING consequence.
3. Run: `python3 <framework>/tools/prawduct-setup.py migrate --enable-coverage "$CLAUDE_PROJECT_DIR" --json`
4. Relay both `actions` (file mutations) and `notes` (deprecation + next-step guidance). The "next-PR consequence" note is the most important.
5. If notes mention legacy evidence shape, point the user at `python3 tools/test-reference-verify --merge-into .prawduct/.test-evidence.json` (Python floor) or stronger language-native tools for `coverage_level: executed`.

### `--enable-settings-layout` (F5 — canonical settings.json)

Mostly a signal operation: stamps `v1_4_settings_migrated: true` in the manifest as the explicit user opt-in for the canonical minimal `.claude/settings.json` layout. For products already on the minimal shape (single-line `python3 product-hook <event>` dispatches), the file mutation is a no-op; for older repos with v1/v3 markers, it runs an aggressive cleanup pass. v1.4.1's Critic surfaces a NOTE on products lacking this flag — running migrate now silences that NOTE in advance. Use when the user asks to "stamp settings layout", "run migrate-settings", "opt into the new settings", or similar.

1. Resolve the framework path the same way as Health Check.
2. Confirm intent — note this is mostly a no-op for products that have synced regularly, but the flag is the v1.4.1 NOTE quieting signal.
3. Run: `python3 <framework>/tools/prawduct-setup.py migrate --enable-settings-layout "$CLAUDE_PROJECT_DIR" --json`
4. Relay `actions` and `notes`. The "already on the canonical minimal layout" note is the common case and confirms the no-op outcome.

### `--enable-operator-verification` (F10 — pre-merge human-verification gate)

Enables the `/pr create` BLOCKING gate that reads `.prawduct/operator-verification.md`. While the gate is on, any entry with `**Status:** pending` blocks PR creation; the queue is the work-log for visual / live-integration changes that automated tests can't fully cover. Per-PR override available via `/pr create --accept-pending-verification "rationale"` (rationale is recorded back into each entry). Use when the user asks to "enable operator verification", "turn on F10", "enable visual gate", or similar.

1. Resolve the framework path the same way as Health Check.
2. Confirm intent — emphasize the BLOCKING consequence: every future PR will block on pending entries, and the override requires a non-empty rationale.
3. Run: `python3 <framework>/tools/prawduct-setup.py migrate --enable-operator-verification "$CLAUDE_PROJECT_DIR" --json`
4. Relay `actions` (file mutations) and `notes` (the next-PR consequence). The migration places `.prawduct/operator-verification.md` from template if absent.

### `--force` (all three migrations)

Re-runs the migration even when the manifest tracks it as complete. Use cases:
- `--enable-coverage --force`: re-surface evidence-shape NOTEs after wiring up a verifier.
- `--enable-settings-layout --force`: re-normalize settings.json after a hand-edit.
- `--enable-operator-verification --force`: re-place the queue template if missing.

## Verify Flow (drain operator-verification queue)

Drains a single pending entry in `.prawduct/operator-verification.md` after the human-verification step is genuinely complete.

1. Resolve the framework path the same way as Health Check.
2. Confirm the user has actually performed the verification described in the entry's `**Verify:**` checklist — `verify` is a deliberate user action, not a session-time auto-flip.
3. Run: `python3 <framework>/tools/prawduct-setup.py verify "$CLAUDE_PROJECT_DIR" <VRF-id> --json`
4. Relay `previous_status` → `status` ("pending → verified") and the action line. If the entry was already verified, the command is a no-op and surfaces a note.

Refuses to verify an `accepted` entry — `accepted` means the gate was overridden via `--accept-pending-verification`; flipping to verified would erase the override rationale. Edit the file by hand if the verification is now genuine.

## Audit Learnings Flow (lifecycle metadata triage)

The `audit-learnings` subcommand walks `.prawduct/learnings.md`, reads the optional per-entry metadata comment, and reports promotion candidates (advisory), retirement candidates (sentinel-protected), and stale single-confirmation entries (>90 days old).

The metadata comment is a single line placed immediately after each `## Title`:

```markdown
## My learning
<!-- prawduct-learning: confirmations=2; created=2026-02-22; sentinel=tests/test_critic.py::test_summaries_check -->

Body of the learning…
```

All three fields are optional. An entry without the comment is treated as "active, no lifecycle metadata" and stays untouched.

Use when the user asks to "audit learnings", "retire structurally-enforced learnings", "check lifecycle metadata", or similar.

1. Resolve the framework path the same way as Health Check.
2. Run: `python3 <framework>/tools/prawduct-setup.py audit-learnings "$CLAUDE_PROJECT_DIR" --json`
3. Relay each list — surface promotion candidates as advisory ("the rule has been confirmed twice — consider whether it belongs in `learnings.md` or can move to historical detail"), retirement candidates pending `--apply` ("the declared sentinel passes; running with `--apply` moves the entry to `learnings-detail.md`"), stale flags ("the entry is over 90 days old with no second confirmation — has the rule held up?"), and errors (failing sentinels, malformed dates).
4. If the user confirms intent to retire, re-run with `--apply`: `python3 <framework>/tools/prawduct-setup.py audit-learnings "$CLAUDE_PROJECT_DIR" --apply --json`. The `--apply` invocation mutates two files: `.prawduct/learnings.md` (entry removed) and `.prawduct/learnings-detail.md` (entry appended under the "Historical (structurally enforced)" section).

The audit is read-only by default. Promotion is always advisory — `learnings.md` doesn't have a sectioned active/promoted split; the count just surfaces in the report. Retirement is the only mutation, and only when `--apply` is passed AND the sentinel passes.

## Important Notes

- The `setup` subcommand auto-detects repo state (new, v1/v3/v4/v5) and routes to the correct action
- Setup is idempotent — running it twice produces no changes on the second run
- The `migrate` subcommand is one-shot per feature (tracked in `sync-manifest.json`) and idempotent without `--force`
- Hooks and governance only activate in the target's own Claude Code session, not the current one
- The `validate` subcommand makes no changes — it's read-only
