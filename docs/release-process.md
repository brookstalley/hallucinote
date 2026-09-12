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

Each cluster in `origin/main..develop` needs a `.prawduct/change-log.md` entry, written
on the feature branch inside its single **ship-stamp commit** (change-log entry +
backlog close + any project-state record, batched — see the **Backlog norms** in
[`.prawduct/artifacts/project-preferences.md`](../.prawduct/artifacts/project-preferences.md),
rule 1, PRC-5W2N).

**An entry with no `release=` key IS the release-pending marker** — that absence is what
`prawduct-hook check-releasability` enumerates, and it is the only marker. So at release:

- For each pending entry being released, add `| release=vNEW` to its
  `<!-- prawduct: … -->` tag line.
- For any shipped cluster with **no entry**, write one now (reconstruct from its commit
  bodies — `git show -s <sha>`), tagged `release=vNEW` directly.
- Never write a placeholder value. `check-releasability` treats *any* value as "already
  released", so `release=unreleased` silently drops the entry's whole scope out of the
  pending set and the work never ships.

Tag-line grammar for a new entry is two keys plus the type: `type=feature|fix|docs|chore
| scope=<tag> | release=vNEW`. **`status=` and `chunks=` are retired** — nothing reads
either, and the derived-view regenerator that once did is gone. Historical entries carry
them and are preserved verbatim; do not add them to a new one. Which chunks an entry
shipped belongs in the entry body, where readers actually look.

Give a scope a distinct id when a second half of earlier work ships separately (e.g.
`SDC-7K3M-pull` against the already-shipped `SDC-7K3M`), so the two don't collide in the
pending set — `scope` is what `check-releasability` groups by, and two entries sharing
one scope are one line to the gate.

`prawduct-hook stamp-merged` is likewise **deprecated and inert** — it warns and does
nothing. Do not call it.

#### Do NOT roll the log here

Stamping `release=vNEW` is all step 1 does to the log. **The entries you just stamped
have to stay in `.prawduct/change-log.md` until step 3 has run**, because
`plan-backfill` reads their `scope=`/`release=` tags out of that file to decide which
build plans retire — fold them out now and the plan sweep sees nothing to archive.

Rolling the log is therefore the *last* act of step 3, not an act of step 1. This
subsection exists because the fold used to live here, which is unsatisfiable: it asked
for the live log "comfortably under the ceiling" while also "keeping the last few
releases for context", and one release of entries is larger than the whole ceiling —
so the step could be followed exactly and still leave the log 2.5× over (142 KB at
v1.9.0). See step 3, *Roll the log*.

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

Also write the **release-plan artifact** `check-releasability` requires:
`.prawduct/artifacts/release-plan-vNEW.md`, carrying a `## Release
classification` table that dispositions every release-pending scope (use the
previous release's as the template). Then verify with `prawduct-hook
check-releasability --release vNEW` — it should report `releasable` with no
pending scopes.

#### Roll the log — LAST, and only now

`plan-backfill` and `check-releasability` have both read the log by this point, so the
shipped entries have no reader left. Fold **every entry carrying a `release=` key** out
of [`.prawduct/change-log.md`](../.prawduct/change-log.md) and into
[`.prawduct/change-log-archive.md`](../.prawduct/change-log-archive.md) — verbatim,
newest-first, under the existing header.

**The rule is "every tagged entry", not "enough to get under the ceiling".** What
should remain in the live log when you are done is the header and nothing else: a
release publishes its entries and resets the file. That makes the file's size mean
something — it measures *unreleased* work, so the ~55 KB nudge
(`oversized_file_threshold_kb`) becomes a real signal that a lot is unshipped, instead
of firing after every release on entries that are already out the door.

**Move only entries that already carry a `release=` key.** Archiving a release-pending
entry drops its scope out of the release gate silently, which is the one failure this
step can cause. Assert it after you write:

```sh
grep '^<!-- prawduct: ' .prawduct/change-log-archive.md | grep -v 'release=' && echo "STOP: pending entry archived"
grep -c '^<!-- prawduct: ' .prawduct/change-log.md   # 0, or only entries that landed mid-release
```

The fold is a file edit, so it rides step 7's `chore(release): vNEW` commit like every
other change here — it is not a separate commit.

**Known gap — the archive is invisible to `plan-backfill`.** It reads
`.prawduct/change-log.md` only (`lib/plan_backfill.py` → `shipped_scopes`), so once an
entry is folded out, that scope can no longer retire a plan. Within one release that is
fine — the sweep runs before the fold, which is the whole reason for this ordering — but
a plan **missed** at its own release cannot be caught up automatically later: its tag is
in the archive where the sweep cannot see it. If `plan-backfill` comes up empty on a plan
you know shipped, grep the archive for its scope and archive it by hand
(`prawduct-hook archive-plan <path> --state completed --release vX.Y.Z`). Filed upstream
against prawduct.

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

That grep answers the **hard** question — will Live *refuse* the call? It is not the
whole question, because the install vendors far more of the package into Live than the
handshake guards: `analyzer/` (which Live *executes* during a render), `resources/`,
`client.py` and the rest. A release that changes only those leaves the fingerprint
still and the vendored copy stale, so a `not required` verdict derived from the grep
alone would be wrong. Ask the **advisory** question too:

```sh
git diff vPREV..develop --name-only | grep 'hallucinote_mcp/src/hallucinote_mcp/' | grep -vE \
  '/(cli|tests|m4l)/|/(wire|schema|dispatcher)\.py|/(actions|handlers|remote_script)/|src/hallucinote_mcp/server\.py$'
```

A hit there and none above is the honest verdict **`Re-vendor: recommended`** — the
handshake will pass, Live keeps running the previous copy of that code, and consumers
should re-vendor to get the fix. One exception: hits confined to `server_side/` are
vendored but never *executed* in Live (they run in the MCP server process), so they
alone still read **`not required`**. The same distinction is machine-readable at
`preflight`'s `remote_script.candidates[*].matches_vendored_content` +
`differing_paths` (advisory) beside `matches_mcp_server` (hard).

Record the verdict in the release commit body and the change-log entry as
**`Re-vendor: required`**, **`Re-vendor: recommended`** or **`Re-vendor: not
required`**, so consumers know without having to diff.

### 6. Distill the public CHANGELOG entry

`CHANGELOG.md` is the **public** release record — the file README sends users to
— and its header promises it is distilled at release time from the internal
change-log. Keep that promise here, at the cut, or it strands again (it sat two
minors stale between v1.6.0 and v1.8.0 precisely because no step owned it):

- Write a `## [vNEW] — YYYY-MM-DD` section at the top: user-facing
  Added/Fixed/Changed entries distilled from this release's change-log clusters.
  Translate away chunk ids and backlog ids; write for someone *using* Hallucinote.
- Carry the step-5 verdict as an **Upgrade note** whenever the re-vendor is
  required — that is the consumer-facing fact of the release.

### 7. Commit the release on `develop` and push

```sh
git add pyproject.toml hallucinote_mcp/pyproject.toml src/hallucinote/__init__.py \
        .claude-plugin/plugin.json .prawduct/change-log.md .prawduct/project-state.yaml \
        .prawduct/release-notes.md docs/engine-pin.md CHANGELOG.md
git commit -m "chore(release): vNEW — <headline>"   # body: clusters + Re-vendor verdict
git push origin develop
```

(These nine files plus `uv.lock` are the canonical release fileset. The first three
are the lockstep product-version surfaces from step 2 beyond `plugin.json`. `uv.lock`
**does** record the workspace members' versions — a bump without a re-lock leaves the
lock stale, and the plugin launches with `uv run --frozen`, which uses the lock as-is.
After the version bump, run `uv lock` and confirm `uv lock --check` passes before
committing; add `uv.lock` to the release commit when it changed. The lock drifted
unnoticed across three releases before this step existed — v1.6.1 shipped with the
lock still recording 0.9.0. CI now enforces `uv lock --check` on every push/PR to
`develop` and `main` (`.github/workflows/ci.yml`), so a stale lock can no longer
reach a release unnoticed.)

### 8. Promote `develop` → `main`

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

### 9. Tag the merge commit and return to `develop`

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

**The back-merge must fast-forward — do NOT pass `--no-ff` here.** This is the one
merge in the process that is deliberately *not* a merge commit, so it is an
explicit exception to the repo-wide "always `--no-ff`" habit (and to step 8, two
paragraphs up, which *does* require it). The release merge already has the
`chore(release)` commit as a parent, so `origin/main` fast-forwards cleanly onto
`develop` and the two branches land on the identical commit. Forcing a merge
commit instead leaves `develop` one commit ahead of `main` forever, and step 10's
`git rev-list --count origin/main..develop` then reads `1` rather than `0` — the
check appears to fail while nothing is actually wrong. Harmless in content (the
next release absorbs it with an empty diff) but not worth the false alarm; it
happened at the v1.8.4 cut.

**If `main` is checked out in another worktree**, `git checkout main` in step 8
refuses outright. Do not disturb that worktree. Promote with plumbing from
`develop` instead — verify the merged tree first, then build the merge commit and
push it straight to the remote ref:

```sh
git merge-tree --write-tree origin/main develop   # must equal `git rev-parse develop^{tree}`
MERGE=$(git commit-tree <tree> -p origin/main -p develop \
        -m "Release: merge develop into main — vNEW")
git push origin $MERGE:main
```

That produces the same two-parent merge commit step 8 describes. The local `main`
ref stays where the other worktree has it and is that session's to update.

### 10. Verify

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

### 11. Publish the GitHub Release

The tag is the record; the **Release** is what a person lands on. Steps 1–10 leave
six annotated tags and, until 2026-08-12, zero Release objects — so anyone arriving
at the repo saw no release at all.

```sh
gh release create vNEW --draft --verify-tag \
  --title "vNEW — <the tag's own subject line>" \
  --notes-file <notes>            # notes come from the change-log entries carrying release=vNEW
```

- **Draft first, always.** A published Release notifies watchers and is the most
  outward-facing artifact the process produces. A draft is invisible and deletable,
  so it is reviewed before it exists publicly.
- **`--verify-tag`** refuses to invent a tag, so a typo fails instead of creating a
  release pointing at nothing.
- A draft's URL reads `releases/tag/untagged-<hash>` until it is published. That is
  normal — the tag binds on publish, and `gh release view vNEW --json tagName`
  already shows the right tag.
- **Release notes are reader-facing positioning prose**, so the norm in
  `project-preferences.md` § Documentation & prose governs them: write what the
  release IS, and never define it by what it isn't.
- Attach any media the release is the canonical home for (`gh release upload`). Note
  that a release asset serves from `github.com/.../releases/download/...`, which
  **will not** render as an inline player in markdown — only a
  `user-attachments` URL does that, and obtaining one is a web-UI upload with no
  `gh` equivalent.

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
| **Vendored content** (advisory) | `install_paths.vendored_content_fingerprint`, reported by `preflight` | any *vendored* file changes — the wire-shape set plus `analyzer/`, `resources/`, `client.py`, … | `<12-hex>` |

The **Today** column deliberately names the file rather than a number: a literal here
is a copy of a value that moves every release, and it sat at `1.6.0` through three
cuts before anyone noticed.

The product version (all four lockstep surfaces) is **marketing/changelog metadata**.
The **handshake fingerprint** is what actually gates whether Live will talk to the
server — and it is computed from file *content*, not from any version string. A release
can bump the product version without flipping the fingerprint (docs/CLI/resources-only)
**or** flip the fingerprint on a patch bump (any change under `actions/`, `handlers/`,
`wire.py`, …). Always compute it (step 5); never infer it from the version number.

The last row is the one not to read as a second gate. It is **advisory**: it moves for
everything the install ships into Live, which is a strict superset of the handshake set,
so a hard mismatch always implies an advisory one but never the reverse. "Fingerprint
unchanged" therefore does not mean "the vendored copy is current" — it means Live will
still *talk* to the server while possibly running last release's `analyzer/`. Nothing
refuses an install on this signal; it exists so the staleness is visible instead of
silent.

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
     the auto-updated server and the existing vendored Remote Script still agree, so
     **calls keep working**. That is not the same as "nothing to do": the install ships
     more into Live than the handshake guards, so a release touching `analyzer/`,
     `resources/` or `client.py` leaves Live running the *previous* copy of that code
     with every call still green. That is the `Re-vendor: recommended` verdict, and the
     consumer sees it in the same preflight at
     `remote_script.candidates[*].matches_vendored_content: false` (with
     `differing_paths` naming the files). Nothing breaks; they simply don't have the
     fix until they re-vendor.

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
- [ ] change-log entries stamped `release=vNEW` (`status=` is RETIRED — do not write it)
- [ ] all four product-version surfaces bumped to `vNEW` (`test_version_parity.py` green)
- [ ] `plan-backfill --apply` run and its named plans checked against their own `## Status`
- [ ] `release-plan-vNEW.md` written; `check-releasability --release vNEW` reports `releasable`
- [ ] **log rolled LAST** (after the two hooks above): every `release=`-tagged entry folded
      into `change-log-archive.md`, live log back to just its header
- [ ] `engine-pin.md` Engine + Plugin rows bumped
- [ ] **Re-vendor verdict computed (step 5) and recorded in the release commit + notes**
- [ ] `CHANGELOG.md` `## [vNEW]` entry distilled (step 6), upgrade note if re-vendor required
- [ ] `chore(release): vNEW` committed + pushed to `develop`
- [ ] `develop`→`main` `--no-ff` merge pushed
- [ ] annotated `vNEW` tag on the merge commit pushed
- [ ] verified: `origin/main..develop` == 0, `main` tagged `vNEW`
