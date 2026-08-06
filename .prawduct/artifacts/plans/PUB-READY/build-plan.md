---
artifact: build-plan
version: 1
plan_id: PUB-READY
last_validated: null
---

# Build Plan — Public-Repo Readiness (PUB-READY)

**Critic mode:** cumulative-final

## Problem

The repo is being made public. An audit of `develop` @ v1.7.1 found the engineering
substrate sound (4614 tests green, ruff/mypy/uv-lock clean, CI real, no secrets,
MIT LICENSE + CONTRIBUTING present, all README links resolving) but six classes of
public-exposure gap:

1. README prose contradicts the shipped version ("approaching 1.0" vs v1.7.1).
2. Tracked docs name a *private* sibling project (`cordyceps`) and carry 15
   hardcoded `/Users/brookstalley/...` filesystem paths.
3. No `SECURITY.md` / `CODE_OF_CONDUCT.md` — both flagged by GitHub's community
   profile, and SECURITY matters unusually much here because the product installs
   a Remote Script into Live's User Library and runs an MCP server against a
   local application.
4. `incoming-bugs/` (65 files) is an internal triage inbox tracked in git.
5. Two *required* strategy artifacts are absent — `api-contract.md`
   (`exposes_programmatic_interface` recorded) and `architecture.md`
   (`multi_process_distributed: client-server` recorded) — plus five optional ones.
6. Housekeeping debt: gitignore contract drift, a stale completed build plan,
   `project-state.yaml` at 42KB, `learnings.md` at 48KB, 3 untriaged bug reports.

## Success

A visitor to the public repo sees consistent versioning, zero personal filesystem
paths or private-project names, standard community-health files, and
contributor-facing architecture + API-contract documentation. All four session
advisories are cleared or consciously dispositioned.

## Out of scope

- **Hero image and demo-song walkthrough** — deferred by the owner to a dedicated
  pass with a new demo song showing the full create → push → arrange flow.
  `docs/assets/hero.svg` stays a placeholder until then.
- **Product code changes.** This plan touches docs, artifacts, and repo metadata only.
- **Backlog → GitHub Issues migration** (the `backlog_service_repo` advisory) — a
  separate decision with its own migration cost.

## Requirements Confidence

**High.** Every item was enumerated and explicitly authorized by the owner. The
one judgment call the owner resolved directly: `.prawduct/` stays tracked (it is
deliberately public — the README links `authorship-model.md`), while
`incoming-bugs/` becomes local-only.

## Chunks

- [ ] **C1 — README version coherence.** Drop "approaching 1.0" / "It's early"
      framing; state the shipped version honestly. Keep the Known Issues section
      intact — it is the page's most trust-building content.
- [ ] **C2 — Privacy scrub.** Remove the `cordyceps` private-project reference;
      replace all 15 `/Users/brookstalley/...` absolute paths with repo-relative
      or placeholder forms. Covers 7 files.
- [ ] **C3 — Untrack `incoming-bugs/`.** Triage the 3 pending reports into the
      backlog FIRST (they are real, unfiled requirements), then `git rm --cached`
      the tree and gitignore it.
- [ ] **C4 — Community health files.** `SECURITY.md` (disclosure channel, scope,
      supported versions, the Remote Script / MCP trust boundary) and
      `CODE_OF_CONDUCT.md` (Contributor Covenant 2.1, the ecosystem standard).
- [ ] **C5 — Required strategy artifacts.** Author `api-contract.md` and
      `architecture.md` for real. Stub the five optional ones with a one-line
      "(not relevant — reason)" where genuinely not relevant, or author briefly
      where they are.
- [ ] **C6 — Housekeeping.** `prawduct-hook update-gitignore`; delete the
      completed AUD-2D6T plan; compact `project-state.yaml` and `learnings.md`
      per the hook's guidance (never delete learnings — move narrative to
      `learnings-detail.md`).

## Done when

All six chunks `[x]`, full no-path `python -m pytest` green, ruff + mypy + `uv
lock --check` clean, `/prawduct:critic cumulative` run with zero unresolved
blocking findings.

## Context

Branch `chore/public-readiness` off `develop` @ v1.7.1 (develop == main).
