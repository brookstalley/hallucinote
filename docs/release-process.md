# Release process — cutting a Hallucinote version

How a version of Hallucinote is cut and what it means for everyone running it. This
repo ships **one git-tracked artifact with two faces**: a Claude Code plugin (skills +
the `hallucinote-mcp` server) *and* a Remote Script that gets vendored into Ableton
Live's User Library. A release moves both — but they update through **different
channels with different timing**, and that asymmetry is the whole reason this document
exists (see [§What a release means for the people running it](#what-a-release-means-for-the-people-running-it)).

> This is a **manual** process, intentionally. It is **not** driven by `/prawduct:pr`
> (that skill governs feature→`develop` PRs; its release-promotion guard explicitly
> hands off to this file). The feature-level review gates — cumulative Critic,
> independent PR reviewer — already ran on each feature's `feature→develop` PR. The
> release does not re-review code; it *promotes already-reviewed code* and stamps it.

## Branching model (gitflow-on-`develop`)

| Branch | Role |
|---|---|
| `feature/*`, `fix/*` | one unit of work → PR into `develop` (`/prawduct:pr`, full gates) |
| `develop` | integration branch; the default base. Accumulates merged work between releases. |
| `main` | the **release surface**. Only ever advanced by the develop→main promotion below. Every commit on `main` is a tagged release boundary. |

`base_branch: develop` in `.prawduct/project-state.yaml` wires the Critic/PR gates to
`merge-base...HEAD` against `develop`. **`main` is downstream of `develop`, always.**

## What "a release" is

1. A **version bump** of the product — root `pyproject.toml` is canonical, carried in
   lockstep by `.claude-plugin/plugin.json`, `hallucinote_mcp/pyproject.toml`, and
   `src/hallucinote/__init__.py` (parity-tested; see [§Version surfaces](#version-surfaces)).
2. A `chore(release): vX` commit on `develop` that stamps the change-log + regenerates
   the derived views.
3. A **`develop`→`main` merge commit** (`Release: merge develop into main — vX`).
4. An **annotated tag** `vX` on that merge commit.

Releases are versioned with a plain `vMAJOR.MINOR.PATCH` scheme on the canonical
product version (root `pyproject.toml`). "Cut the next +0.0.1" = patch bump (e.g.
`0.9.6` → `0.9.7`). The release
bundles **everything on `develop` that isn't yet on `main`** — a release is a wholesale
promotion of `develop`, not a cherry-pick. Check the scope before cutting:

```sh
git fetch origin
git log --oneline --no-merges origin/main..develop   # everything this release will ship
```

If that list contains work with **no change-log entry**, stop and document it first
(step 1 below) — otherwise the release notes silently omit shipped clusters. This is a
known failure mode: clusters merged to `develop` without a change-log entry are
invisible to the release until someone audits `origin/main..develop` by hand.

## The procedure

Run from a clean `develop` that is green and fully pushed. Let `vPREV` = the current
release (`git describe --tags --abbrev=0 main`), `vNEW` = the bump.

### 1. Reconcile the change-log — every shipped cluster has an entry

Each cluster in `origin/main..develop` needs a `.prawduct/change-log.md` entry. Entries
authored on feature branches are **statusless**, then `prawduct-hook stamp-merged`
flips them to `status=merged` at merge time. On the feature branch, the entry lands
inside the single **ship-stamp commit** (change-log entry + backlog close + any
project-state record, batched — see `.prawduct/backlog.md` header rule 1, PRC-5W2N).
At release:

- For each `status=merged` entry being released: change `status=merged` →
  `status=shipped` and add `| release=vNEW` to the `<!-- prawduct: … -->` tag line.
- For any shipped cluster with **no entry**, write one now (reconstruct from its commit
  bodies — `git show -s <sha>`), tagged `status=shipped | release=vNEW` directly.

Tag-line grammar (matches existing entries): `type=feature|bugfix | chunks=A,B |
scope=area1,area2 | status=shipped | release=vNEW`. Use a distinct chunk id when a
second half of an earlier chunk ships separately (e.g. `SDC-7K3M-pull` vs the already-
shipped `SDC-7K3M`) so the rollups don't collide.

### 2. Bump the product version (all four surfaces, in lockstep)

Since 1.5.0 the product version lives in **four files that must stay identical** —
`tests/unit/test_version_parity.py` fails CI on any drift. Root `pyproject.toml` is the
canonical source; set all four to `vNEW` (number only, no `v`):

- `pyproject.toml` `[project].version` — **canonical**
- `hallucinote_mcp/pyproject.toml` `[project].version`
- `.claude-plugin/plugin.json` `"version"`
- `src/hallucinote/__init__.py` `__version__`

The handshake `BASE_VERSION` is **not** one of these — it is the wire-protocol epoch,
deliberately decoupled from the product version (see
[§Version surfaces](#version-surfaces) and step 5).

### 3. Archive the plans this release shipped

**There are no derived views to regenerate.** `prawduct-hook regen-views` is inert
and warns that it will be removed — build-plan `## Status` boxes are ticked by hand
(nothing overwrites them), and the release notes ARE the change log. Do not
hand-write `.prawduct/release-notes.md` to compensate; the `release=vNEW` tags you
set in step 1 are the record.

What this step *is*, on gitflow: the plans whose scopes this release just tagged
have been retained live since their feature merges, and now retire.

```sh
prawduct-hook plan-backfill --apply
```

It archives every plan whose scope the release tagged. Then clear
`active_build_plan` in `project-state.yaml` if it names one that just archived —
leave it **empty**, never the literal `null` (the pointer reader treats the
post-colon text as a path, so `null` resolves to `.prawduct/null` and mis-fires the
missing-build-plan advisory).

Verify with `prawduct-hook check-releasability --release vNEW` — it should report
`releasable` with no pending scopes.

### 4. Update the engine-pin row

In [`docs/engine-pin.md`](engine-pin.md) (§"Current pin"), bump **both** the **Engine**
and **Plugin** rows to `vNEW` — they move together now (step 2's lockstep).

### 5. Determine the re-vendor impact (do not skip — it's the consumer-facing fact)

Compute whether this release changes the Remote Script handshake fingerprint:

```sh
git diff vPREV..develop --name-only | grep -E \
  'hallucinote_mcp/src/hallucinote_mcp/(wire|schema|dispatcher)\.py|/(actions|handlers|remote_script)/'
```

Those paths are `_FINGERPRINT_PATHS`
(`hallucinote_mcp/src/hallucinote_mcp/__init__.py`). **Any** hit means the fingerprint
changed → **re-vendor required** (see [§What a release means…](#what-a-release-means-for-the-people-running-it)).
Record the verdict in the release commit body and the change-log entry as
**`Re-vendor: required`** or **`Re-vendor: not required`**, so consumers know without
having to diff.

### 6. Commit the release on `develop` and push

```sh
git add pyproject.toml hallucinote_mcp/pyproject.toml src/hallucinote/__init__.py \
        .claude-plugin/plugin.json .prawduct/change-log.md .prawduct/project-state.yaml \
        .prawduct/release-notes.md docs/engine-pin.md
git commit -m "chore(release): vNEW — <headline>"   # body: clusters + Re-vendor verdict
git push origin develop
```

(These eight files plus `uv.lock` are the canonical release fileset. The first three
are the lockstep product-version surfaces from step 2 beyond `plugin.json`. `uv.lock`
**does** record the workspace members' versions — a bump without a re-lock leaves the
lock stale, and the plugin launches with `uv run --frozen`, which uses the lock as-is.
After the version bump, run `uv lock` and confirm `uv lock --check` passes before
committing; add `uv.lock` to the release commit when it changed. The lock drifted
unnoticed across three releases before this step existed — v1.6.1 shipped with the
lock still recording 0.9.0. CI now enforces `uv lock --check` on every push/PR to
`develop` and `main` (`.github/workflows/ci.yml`), so a stale lock can no longer
reach a release unnoticed.)

### 7. Promote `develop` → `main`

`main` accumulates only merge commits, so it diverges from `develop` by the historical
release-merge commits (none introduce unique file content — verify with
`git log --oneline --no-merges origin/main..origin/main` being empty relative to
`develop`). The promotion is a no-fast-forward merge:

```sh
git checkout main && git pull --ff-only origin main
git merge develop --no-ff -m "Release: merge develop into main — vNEW"
git push origin main
```

A merge-tree dry-run (`git merge-tree $(git merge-base main develop) main develop`)
should show no conflicts — `develop` is strictly ahead in file content.

### 8. Tag the merge commit and return to `develop`

Tags are **annotated** and sit on the **`main`-side merge commit** (not the
`chore(release)` commit) — matching every prior `vX` tag:

```sh
git tag -a vNEW <main-merge-sha> -m "vNEW — <headline>"
git push origin vNEW
git checkout develop
git merge origin/main -m "Merge origin/main back into develop — vNEW release commit"
git push origin develop
```

The back-merge is **mandatory**, not optional tidiness: `main` accumulates the
release merge commits, and without returning them `develop` drifts "behind" main
by every release ever cut (it reached 15 commits before this step existed). The
back-merge introduces no file content — `develop` is strictly ahead in content —
it only reconciles history so `git rev-list --left-right --count main...develop`
reads `0 <N>` instead of `<releases> <N>`.

### 9. Verify

```sh
git rev-list --count origin/main..develop        # 0 — develop fully promoted
git describe --tags --exact-match origin/main     # vNEW
pytest tests/unit/test_version_parity.py -q        # all four product surfaces == vNEW
```

Build plans are **archived, never deleted** — step 3 does this, and an archived plan
stays findable by name while no longer reading as live work. Two things that step
cannot decide for you, both of which bit at the v1.8.0 cut:

- **`plan-backfill` archives by SCOPE, not by completeness.** A plan whose scope the
  release tagged is archived even if some of its chunks are unticked. At v1.8.0 it
  wanted to archive `TOUR` because `scope=tour` shipped, while chunks C1 and D1 were
  unbuilt — archiving would have declared them done. Check each plan it names against
  its own `## Status` before accepting, and restore any that still has open chunks.
- **`active_build_plan` is cleared only when the plan it names just archived.** Leave
  it EMPTY, never the literal `null`. A pointer at an unfinished parked plan stays
  meaningful between releases and should survive the cut.

## Version surfaces

There are **five** version strings. Four are the **product version** and move in
**lockstep every release** (since 1.5.0; pinned identical by
`tests/unit/test_version_parity.py`, which fails CI on drift). The fifth — the
handshake — is on its **own clock**. Full rationale in
[`docs/engine-pin.md`](engine-pin.md).

| Surface | File | Moves when | Today |
|---|---|---|---|
| **Product** (canonical) | `pyproject.toml` `[project].version` | every release (lockstep) | see `pyproject.toml` |
| **MCP package** (`hallucinote-mcp`) | `hallucinote_mcp/pyproject.toml` | every release (lockstep) | see `pyproject.toml` |
| **Plugin manifest** | `.claude-plugin/plugin.json` `version` | every release (lockstep) | see `pyproject.toml` |
| **Engine dunder** (`hallucinote`) | `src/hallucinote/__init__.py` `__version__` | every release (lockstep) | see `pyproject.toml` |
| **Handshake** | `BASE_VERSION` + content fingerprint, `hallucinote_mcp/src/hallucinote_mcp/__init__.py` | any wire-shape file changes (`_FINGERPRINT_PATHS`) | `0.1.0+<12-hex>` |

The **Today** column deliberately names the file rather than a number: a literal here
is a copy of a value that moves every release, and it sat at `1.6.0` through three
cuts before anyone noticed.

The product version (all four lockstep surfaces) is **marketing/changelog metadata**.
The **handshake fingerprint** is what actually gates whether Live will talk to the
server — and it is computed from file *content*, not from any version string. A release
can bump the product version without flipping the fingerprint (docs/CLI/resources-only)
**or** flip the fingerprint on a patch bump (any change under `actions/`, `handlers/`,
`wire.py`, …). Always compute it (step 5); never infer it from the version number.

## What a release means for the people running it

Three audiences, three different stories. The pivot for all of them is the **strict
version handshake**: every TCP call carries `server_version`, and the Live-side Remote
Script refuses the call unless `server_version == remote_script_version` (both are the
content fingerprint). The deep mechanics are in
[`docs/dev-vs-use-coexistence.md` §"The one constraint you can't engineer away"](dev-vs-use-coexistence.md#the-one-constraint-you-cant-engineer-away).

### Marketplace consumers, on this machine or any other

Installed via `/plugin marketplace add brookstalley/hallucinote` +
`/plugin install hallucinote@hallucinote`. The marketplace tracks the repo's **`main`**
branch. The two halves update on different channels:

1. **Plugin half (skills + the `hallucinote-mcp` server)** — updates **automatically**
   when `main` is pushed, via Claude Code's marketplace `autoUpdate`. No consumer action;
   the next Claude Code session (or `/mcp` respawn) runs the new server. There is **no
   `autoUpdate` field this repo sets** — it's the marketplace client default. (For why a
   *developer* deliberately opts out of this with `--plugin-dir`, see
   [`dev-vs-use-coexistence.md` §"Three coupling axes"](dev-vs-use-coexistence.md#three-coupling-axes-dont-conflate-them).)

2. **Remote Script half (the copy in Live's User Library)** — does **NOT** auto-update.
   Nothing outside the consumer's machine can rewrite their User Library. So:

   - **If the release flipped the fingerprint** (step 5 = re-vendor required): the
     auto-updated server now computes a new `server_version`, the stale vendored Remote
     Script still computes the old one, and **every bridge call fails** with
     `"version mismatch"` until the consumer **re-runs `/ableton-mcp-install` and fully
     quits + reopens Ableton Live**. `/mcp` alone is not enough — Live caches Control
     Surface modules at startup. The error message itself points at the fix; to preview
     without restarting, `python -m hallucinote_mcp.cli preflight` and look for
     `remote_script.candidates[*].matches_mcp_server: false`.

   - **If the release did not flip the fingerprint** (docs/CLI/resources/engine-only):
     the auto-updated server and the existing vendored Remote Script still agree —
     **nothing to do**, calls keep working.

   This is the asymmetry to internalize: **a fingerprint-flipping release auto-updates
   the consumer's server into a state that no longer matches their Live install, and
   only the consumer can repair it** (re-vendor + Live restart). Announce the re-vendor
   verdict in the release notes so it isn't discovered as a broken session.

### The dev+music machine (this repo's author)

If you both develop and make music on one machine, you are **not** a pure marketplace
consumer — you run `--plugin-dir` worktrees and the marketplace install is dropped.
Crossing the dev↔music boundary always costs a re-vendor + full Live restart **by
construction**, independent of releases. That topology (two worktrees, when to
`/ableton-mcp-install`) is its own document:
[`docs/dev-vs-use-coexistence.md`](dev-vs-use-coexistence.md) — especially
[§"The unavoidable boundary crossing"](dev-vs-use-coexistence.md#the-unavoidable-boundary-crossing--make-it-one-command)
and [§"What makes any topology safe regardless: INS-3W8P"](dev-vs-use-coexistence.md#what-makes-any-topology-safe-regardless-ins-3w8p)
(the running server self-reports its identity via `ableton://server/info`, so the
install vendors the *server's* copy, not the invoking interpreter's).

### Song-authoring environments (the Python engine)

`songs/*/build.py` import the `hallucinote` **engine**, which now ships **inside the
plugin's uv env** — there is no separate consumer engine install. A release ships the
new engine source *in the plugin*; the consumer gets it when they update the plugin
(uv rebuilds the env). Skills run the engine via the plugin's own interpreter
(`ableton://server/info` → `python`), so engine↔bridge alignment is automatic: one
env, one source. See [`docs/engine-pin.md`](engine-pin.md).

## Worked example — v0.9.7

> ⚠ v0.9.7 **predates** the 1.5.0 version-lockstep (step 2). The "engine stayed `0.9.0`"
> line below is historically accurate for that release but is **no longer how a bump
> works** — today all four product-version surfaces move together. Kept as a record, not
> a template.

- **Scope:** 5 clusters on `develop` since v0.9.6 (ROUNDTRIP sidechain pull-capture,
  RELIABILITY round-trip fixes, PSH-2R7K/5T9D, INS-3W8P, SNP-8R4K). Three had no
  change-log entry and were reconstructed at release time (step 1).
- **Bump:** plugin `0.9.6` → `0.9.7`; engine stayed `0.9.0`.
- **Re-vendor: REQUIRED.** `git diff v0.9.6..v0.9.7` touched four files inside
  `_FINGERPRINT_PATHS` — `actions/device.py`, `handlers/device.py`,
  `handlers/display_value.py` (DPP-7H2K) and `handlers/render.py` (SNP-8R4K). The
  `ableton://server/info` resource added by INS-3W8P is *outside* the fingerprint paths
  (`resources/`), so it did not contribute — but the release as a whole flips it.
  **Marketplace consumers must `/ableton-mcp-install` + restart Live for v0.9.7.**
- **Tag:** `v0.9.7` (annotated) on the `main`-merge commit.

## Hotfix / rollback

- **Hotfix:** branch from `main`, fix, PR into `develop` (so the fix isn't lost from the
  integration line), then run this process for a `+0.0.1` release. There is no separate
  hotfix-direct-to-main path — `main` is only ever advanced by promotion.
- **Rollback:** a release is a tag + a merge commit; nothing is destroyed. To unship,
  cut a forward release that reverts the offending commits. Do not rewrite `main`
  history — consumers' marketplace clients track it.

## Release checklist

- [ ] `origin/main..develop` scope reviewed; every cluster has a change-log entry
- [ ] change-log entries flipped to `status=shipped | release=vNEW`
- [ ] all four product-version surfaces bumped to `vNEW` (`test_version_parity.py` green)
- [ ] `prawduct-hook regen-views` run; `release-notes.md` `## vNEW` lists all clusters
- [ ] `engine-pin.md` Engine + Plugin rows bumped
- [ ] **Re-vendor verdict computed (step 5) and recorded in the release commit + notes**
- [ ] `chore(release): vNEW` committed + pushed to `develop`
- [ ] `develop`→`main` `--no-ff` merge pushed
- [ ] annotated `vNEW` tag on the merge commit pushed
- [ ] verified: `origin/main..develop` == 0, `main` tagged `vNEW`
