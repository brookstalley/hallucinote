# Release plan — v1.8.1

**vPREV:** v1.8.0 · **vNEW:** v1.8.1 (patch) · **Cut:** 2026-08-10

The first release-plan artifact this repo has carried. `check-releasability`
requires one (`.prawduct/artifacts/release-plan-vX.Y.Z*.md` carrying a
`## Release classification` section) and no prior version had it, so that gate has
been failing closed through past cuts unnoticed. `docs/release-process.md` still
does not mention the artifact — recorded as a gap below rather than fixed silently
here, since this release already carries corrections to that document.

## What this release is

A **bookkeeping and documentation release. No product code changes at all** — the
only non-`.md`/`.yaml` files touched are the four version surfaces and `uv.lock`.
Two clusters:

| Cluster | Substance |
| --- | --- |
| `backlog-migration` | The backlog moved to GitHub Issues (225 items). What *ships* here is the `backlog_service_repo` cutover key, the frozen-history banner, the relocated backlog norms, and the audit record — the 225 issues themselves live on the tracker, not in this tag. |
| `release-process-docs` | Two corrections to `docs/release-process.md` that the v1.8.0 cut proved wrong. |

## Release classification

| scope | disposition | blocker |
| --- | --- | --- |
| backlog-migration | ships |  |
| release-process-docs | ships |  |

## Re-vendor impact

**Re-vendor: not required.**

    git diff v1.8.0..develop --name-only | grep -E \
      'hallucinote_mcp/src/hallucinote_mcp/(wire|schema|dispatcher)\.py|/(actions|handlers|remote_script)/'

Returns nothing. No `_FINGERPRINT_PATHS` file is touched, so the handshake
fingerprint is unchanged and Live keeps talking to the already-vendored Remote
Script. Consumers need nothing beyond the ordinary plugin update.

## Step 3 — no plans archived, deliberately

`plan-backfill` proposed archiving exactly one plan, `plans/TOUR/build-plan.md`,
because `scope=tour` shipped in v1.8.0. **Declined**, and this is the *second*
consecutive cut at which that would have been wrong: TOUR's own `## Status` still
has **Chunk C1 and Chunk D1 unticked**, so archiving it would record two unbuilt
chunks as done. `--apply` was therefore never run — TOUR was the only candidate,
so there was nothing else to archive.

This is exactly the failure the `release-process-docs` cluster in this same release
exists to prevent (*"`plan-backfill` archives by SCOPE, not by completeness"*). The
correction landed and was immediately load-bearing.

`active_build_plan` was already **empty** and stayed that way — not the literal
`null`, which would resolve to `.prawduct/null` and mis-fire the
missing-build-plan advisory. The four other live plans (`ARR-PROJ`, `ENV-8K2R`,
`ENV-9P4T`, `SYN-8Q3F`) are correctly left in place.

## Verification

- Full suite green at the pre-bump tree: **4983 passed, 2 skipped**.
- `tests/unit/test_version_parity.py`: **4 passed** — all four lockstep surfaces at
  1.8.1 (`pyproject.toml` canonical, `hallucinote_mcp/pyproject.toml`,
  `.claude-plugin/plugin.json`, `src/hallucinote/__init__.py`).
- `uv lock` re-run (`hallucinote` and `hallucinote-mcp` 1.8.0 → 1.8.1) and
  `uv lock --check` clean. The lock records workspace member versions and the
  plugin launches with `uv run --frozen`, so a bump without a re-lock ships a
  stale lock — v1.6.1 shipped recording 0.9.0 before this step existed.
- Both merged PRs passed CI (#446, #219).

## Known gaps carried, not fixed here

- **`backlog-migration` ships with no build plan.** It was driven by the plugin's
  MG4 migration-scrub runbook, so `check-releasability` warns a scope is shipping
  undescribed. The runbook plus `migration-scrub-decisions.md` are the
  description; a retroactive build plan would be fiction.
- **`docs/release-process.md` does not document this artifact** that
  `check-releasability` requires. A natural third correction for the next pass at
  that document.
- **Three source citations still point at the frozen backlog file** — filed as
  **#445**, including a user-facing MCP error string. Deferred because
  `cost-of-commit` prices those `.py` files `costs-a-round`.
- **32 migrated items carry no verifiable signal**; **11 are flagged `non_atomic`**
  awaiting an owner split. Both disclosed in the change-log and the audit record.
- **No completeness detector survives the cutover** — `verify-migration` is
  single-use by construction. Accepted with the bounded exposure documented.
- **`/Users/<account>` appears in 22 historical commits.**
  `tests/unit/tools/test_no_tracked_home_paths.py` guards the tracked tree (clean)
  but cannot reach history. Already an owner decision: **PRC-6N2X** records "go
  public without rewriting history, tip-only scrub, accepted."
