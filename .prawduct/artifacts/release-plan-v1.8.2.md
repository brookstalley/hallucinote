# Release plan — v1.8.2

**vPREV:** v1.8.1 · **vNEW:** v1.8.2 (patch) · **Cut:** 2026-08-11

## What this release is

A **documentation and governance release. No product code changes** — the only
non-doc files touched are the four version surfaces, `uv.lock`, one new
doc-parity test, and a comment-only `pyproject.toml` edit. Two clusters, held
back deliberately from separate cuts so marketplace consumers get one update
(owner's call, recorded by the doctor session at the v1.8.1 hold):

| Cluster | Substance |
| --- | --- |
| `release-readiness` | The public documentation scrub (PR #450): README overhauled with a real captured hero from the from-scratch punk-fate session, public CHANGELOG revived and current, docs audience index locked by a parity test, tree-wide stale-command sweep, known-issues split, pull → bake → build taught in quickstart/FAQ, release-process gains the CHANGELOG-distillation step this very cut follows. |
| `norm-ratification` | The norm registry ratified (PR #448): `## Direction` sections in six strategy artifacts, the preferences Enforcement table rewritten as the norm index — 27 norms, all under `.prawduct/`. |

## Release classification

| scope | disposition | blocker |
| --- | --- | --- |
| release-readiness | ships |  |
| norm-ratification | ships |  |

## Re-vendor impact

**Re-vendor: not required.**

    git diff v1.8.1..develop --name-only | grep -E \
      'hallucinote_mcp/src/hallucinote_mcp/(wire|schema|dispatcher)\.py|/(actions|handlers|remote_script)/'

Returns nothing (verified at the cut). No `_FINGERPRINT_PATHS` file is touched,
so the handshake fingerprint is unchanged and consumers need nothing beyond the
ordinary plugin update.

## Step 3 — no plans archived, again deliberately

Neither shipping scope has a build plan (docs work ran under the session's task
list + Critic rounds; the norm work under the doctor runbook), so `plan-backfill`
has no candidates from this release. TOUR remains live with C1/D1 open — it was
mis-archived once tonight by exactly this step (upstream defect prawduct#634,
reverted same hour by the tree owner after independent verification), so the
manual Status check was run with particular care: **no plan was archived at this
cut.** `active_build_plan` stays empty.

## Verification

- Full suite green at the pre-bump tree: **4986 passed, 2 skipped** (docs-index
  parity tests are the +3 over v1.8.1's baseline).
- Both merged PRs passed CI (#448, #450); #450 additionally carried two Critic
  rounds (0 blocking) and an independent PR review (0 blocking).
- `tests/unit/test_version_parity.py` green at the post-bump tree; `uv lock`
  re-run and `uv lock --check` clean.

## Known gaps carried, not fixed here

- **Both scopes ship with no build plan** — described instead by PR #450's
  review trail and the doctor runbook's records. Retroactive plans would be
  fiction (same reasoning as v1.8.1's backlog-migration).
- **#449**: `src/hallucinote/inventory.py` error strings still teach the retired
  `python -m hallucinote.inventory refresh` invocation — code change, priced a
  review round, deferred with an issue.
- The v1.8.1 plan's "release-process.md does not document the release-plan
  artifact" gap is **fixed in this cut** (step 3 now names it).
