---
artifact: build-plan
version: 2
# views_enabled: true — scope tag keeps this plan's change-log Status flips
# from colliding with prior releases' chunk IDs. All three chunks tag their
# change-log entries `scope=highroi-sweep`.
scope: highroi-sweep
depends_on:
  # Chunks B–C are the shipped BAK design's Chunks 2–3.
  - artifact: design
    path: .prawduct/artifacts/plans/BAK-7D2V/design.md
last_validated: null
---

# Build Plan — High-ROI sweep 2026-07 (VEW-7T2C + VEW-9QH4 + BAK-7D2V remainder)

Bundles three ready, high-benefit / low-work backlog items, sequenced for
maximum unattended autonomy. One branch may serve all three, but the two
concerns are thematically independent and **recommended to ship as two PRs**
(see *PR structure* below) — the plan is authored so that split is a clean cut
at the Chunk A / Chunk B boundary.

- **VEW-7T2C** (S/S) — canonicalize historical change-log tag lines to the
  `prawduct:` form so the lifecycle tooling sees the whole log.
- **VEW-9QH4** (S/M) — document the `release=unreleased` vocab for in-flight
  change-log work + audit-backfill any missing post-v1.4.0 entries.
- **BAK-7D2V** (S/L, **top priority**) — the pull-durability remainder:
  Chunk 2 (pull-side contract UX) + Chunk 3 (`/song-snapshot` loop-close).
  Chunk 1 (the replay guard) already shipped via PR #210. Full design:
  [`.prawduct/artifacts/plans/BAK-7D2V/design.md`](plans/BAK-7D2V/design.md) — chunks below are that
  artifact's Chunks 2–3, not re-derived here (link, don't summarize).

## Requirements Confidence

**Level:** High

**Why:** VEW items are mechanical edits to one tracked file (`.prawduct/change-log.md`)
with a verifiable parse signal; BAK Chunks 2–3 are already fully specified in
the shipped `.prawduct/artifacts/plans/BAK-7D2V/design.md` (chosen alternative C, refuse/warn matrix,
kind-set audit all locked in Chunk 1). No open design questions remain.

**Open assumptions / unknowns:**

- `[ASSUMPTION: the unreleased-work tag vocab is release=unreleased, flipped to the real vX.Y.Z at release cut (mirrors how v1.4.0 tags were hand-flipped, and how several historical entries already read release=unreleased) | LOW impact | user can override the token/mechanic before Chunk A]`
- `[ASSUMPTION: historical entries tagged `status=shipped release=unreleased` get their real shipped version resolved via git archaeology (tag-range containing the chunk); any genuinely undeterminable pre-v1.4.0 entry is marked release=pre-v1.4.0-untracked rather than assigned a fabricated version — never invent a version | MED impact | user can correct any specific flip]`
- `[ASSUMPTION: the framework-coupled tooling halves of both VEW items — the TAG_LINE_RE / stamp-merged / regen-views parser in the plugin-provided `product-hook` (upstream, NOT tracked in this repo; confirmed `git ls-files tools/` shows only 5 migrate/eval scripts) — are OUT of scope here and land with the upstream prawduct sync per memory project_prawduct_framework_authorship. This plan delivers only the in-repo change-log + docs halves | MED impact | user can redirect to also touch the upstream checkout]`
- `[ASSUMPTION: BAK operator-verification (dial-a-knob → pull → build refuses → snapshot → survives) is Live-gated and queued to operator-verification.md, NOT part of the autonomous build — the code/skill/doc deliverables are fully testable headless | LOW impact | user can attend a live session to drain it]`
- `[ASSUMPTION: ship as two PRs (VEW hygiene / BAK durability); could be one if preferred | LOW impact | user can override at PR time]`

**What would raise confidence:** N/A (High).

## Verification strategy

- **Chunk A** — parse the canonicalized `change-log.md` against the *live*
  plugin parser regex (`TAG_LINE_RE` in the 2.2.3 plugin cache), not prose:
  every tagged entry must match, and the count of `<!-- prawduct:` entries must
  equal the total tagged-entry count. (Memory: validate a template against the
  live schema, not prose — feedback_validate_template_against_live_schema.)
- **Chunks B–C** — headless unit tests exercise the new pull_cli print path
  (mix-domain apply with mutations > 0 emits the durability notice; zero-change
  and non-mix pulls stay quiet) and the capture re-stamp path (empty-diff
  re-stamp refreshes `captured_at` without content change). Skill/doc prose is
  reviewed for the pull→bake→build contract wording. Live end-to-end is queued
  as operator-verification, not gated in the build.
- Full green: `python -m pytest` with **no path arg** (memory:
  feedback_run_full_pytest_no_path — the path-scoped form skips hallucinote_mcp/tests).

## Status

> **These checkboxes are a DERIVED view of release state, not build state.** This
> plan sets `views_enabled`, so `regen-views` rewrites the boxes from each chunk's
> change-log `status=` tag. All three chunks are built, committed, and reviewed —
> but their change-log entries are statusless (release-pending) while the work sits
> on `develop`, so the boxes read unticked. The `develop→main` release stamps
> `status=shipped` and re-runs `regen-views`, which ticks them. Do not hand-edit
> them to `[x]`; that only gets overwritten. The Context block below is the
> authoritative build state.

- [ ] Chunk A: Change-log canonicalization + unreleased vocab (VEW-7T2C + VEW-9QH4) — committed c6e0808
- [ ] Chunk B: BAK-7D2V Chunk 2: pull-side contract UX — committed bf2d444
- [ ] Chunk C: BAK-7D2V Chunk 3: `/song-snapshot` loop-close (cumulative-final)

**Context:** All three chunks built + committed on `feat/highroi-sweep-2026-07`.
- **A**: 34 legacy change-log tag lines canonicalized to `prawduct:` form (incl.
  pipe-in-chunks-value fix + 3 foot-tag relocations), 10 `release=unreleased`→v1.5.0
  (git-ancestry verified), unreleased vocab documented in the header. 75/77 entries
  parse tagged as of this branch's tip (2 genuinely tag-less 2026-05-17 entries left
  as-is); 0 status/multiplicity warnings against the live parser. The total moves as
  entries land — the invariant is "every entry but those 2", not a fixed count.
- **B**: `pull_cli` durability notice via `capture.count_request_replay_asserted_events`
  (reuses the guard's kind set); `/ableton-pull` reframed.
- **C**: `/song-snapshot`'s empty-diff path BAKES the fresh capture (`capture merge`)
  to disarm the guard; `capture_cli restamp` + `capture.restamp_captured_at` survive as
  a documented operator override. `/song-pick-instruments` + `docs/song-workflow.md`
  contract wording. BAK operator-verification extended (checks 7–9) — Live-gated,
  not built.

**DONE — all governance complete (2026-07-20).** Branch `feat/highroi-sweep-2026-07`,
base `origin/develop`, working tree clean, full suite **green**. Chunks A–C plus a
repo-hygiene sweep (gitignore contract reconcile, four 2026-07-07 backlog items, three
2026-07-11 incoming-bug reports, stale remote branches deleted) — its own `type=process`
change-log entry.

The 2026-07-20 cumulative Critic (base develop) raised **1 blocking finding**, now
resolved: Chunk C's empty-diff path re-stamped `captured_at` on the STALE snapshot, and
an empty `capture diff` does not prove freshness — the diff never compares device
sidechain sources, drum-pad mappings, or per-chain authored props, all of which replay
re-asserts. A pull touching only those fields would have diffed clean, disarmed the
guard over old values, and let the next build silently revert the pulled work. Fixed by
baking the refresh via `capture merge`; locked by a doc-drift test on the skill's
commands plus paired tests pinning the diff's blind spot and merge's coverage of it.
Three Critic warnings also folded in: the REFUSE prose is now conditional on a
`captured_at` stamp (a legacy unstamped snapshot warns and still reverts), `regen-views`
was run after Chunk A's tag-line sweep, and this Status block is current.

**NEXT (user-triggered):** `/prawduct:pr` → `develop`. Then the Live
operator-verification (checks 7–9 in `operator-verification.md`) when a session is
attended — check 9 specifically exercises the blind-spot pull the Critic found.

---

### Chunk A: Change-log canonicalization + unreleased vocab

- **Items:** VEW-7T2C (form) + VEW-9QH4 (vocab + backfill) — coupled; one pass
  over `.prawduct/change-log.md`.
- **Type:** doc-only
- **Deliverables:**
  1. Every historical non-`prawduct:` tag line (`<!-- chunks=… status=… release=… scope=… -->`,
     ~35 of 73 today) rewritten to the canonical
     `<!-- prawduct: type=… | chunks=… | scope=… | status=… | release=… -->`
     form. Preserve `chunks`/`scope`/`status`/`release` values verbatim except
     the version resolution below; infer `type=` from the entry body
     (feature/refactor/infrastructure/process/audio…) — do not fabricate where
     unclear, use the closest honest category.
  2. Historical `status=shipped release=unreleased` entries: resolve `release`
     to the actual shipped version via git tag-range archaeology; mark any
     genuinely-undeterminable pre-v1.4.0 entry `release=pre-v1.4.0-untracked`
     (never invent a version — see Open assumptions).
  3. Document the unreleased-work vocab where entries are authored: a comment
     block in the `change-log.md` header stating `release=unreleased` for
     in-flight work, flipped to the real `vX.Y.Z` at release cut. (The
     methodology-side home is in the plugin and out of scope.)
  4. Audit post-v1.4.0 develop commits for missing `##` change-log entries;
     backfill any gap (the v1.5/1.6/1.7 releases wrote consolidated entries, so
     this is expected to be a confirming audit, not a large backfill — report
     the finding either way; do not silently claim "none missing").
- **Done when:**
  1. Live-parser check: every tagged entry matches `TAG_LINE_RE` from the
     2.2.3 plugin's `product-hook` (upstream; not tracked here); `grep -c '<!-- prawduct:'` equals the
     total tagged-entry count.
  2. Every post-v1.4.0 develop commit range is accounted for (entry exists, or
     explicitly noted why not).
  3. `/prawduct:critic chunk` run, blocking findings resolved.
  4. Committed; chunk marked [x] in Status.
- **Not in scope:** the plugin-side parser/regen-views changes (framework-coupled).

### Chunk B: BAK-7D2V Chunk 2: pull-side contract UX

- **Items:** BAK-7D2V (Chunk 2 of [`.prawduct/artifacts/plans/BAK-7D2V/design.md`](plans/BAK-7D2V/design.md)).
- **Type:** code
- **Deliverables** (per design §"Chunked build plan" item 2):
  1. `src/hallucinote/sync/pull_cli.py` — after a mix-domain apply with
     mutations > 0 (`_cmd_apply` / `_cmd_execute`), print the durability notice:
     staged in the regenerable DB only → bake with `/song-snapshot` before the
     next `build.py`, which will otherwise **refuse** (name the guard shipped in
     Chunk 1). Quiet on zero-change and non-replay-asserted (non-mix) domains —
     mirror the guard's `_REPLAY_ASSERTED_EVENT_KINDS` scope so the notice fires
     exactly when the guard would.
  2. `skills/ableton-pull/SKILL.md` — finish the BAK-3M9T Chunk D reframe: the
     skill text names the bake (`/song-snapshot`) as the closing move that makes
     a mix pull durable, and that a mix-domain pull left un-baked blocks the next
     build.
- **Done when:**
  1. Unit test: mix apply with mutations > 0 emits the notice; zero-change and
     clip/note/envelope/tuning pulls do not. Acceptance criteria met.
  2. `/prawduct:critic chunk` run, blocking findings resolved.
  3. Committed; chunk marked [x].
- **Visual change:** yes (pull_cli stdout wording) → queue an operator-verification
  entry for the live notice.

### Chunk C: BAK-7D2V Chunk 3: `/song-snapshot` loop-close

- **Items:** BAK-7D2V (Chunk 3 of [`.prawduct/artifacts/plans/BAK-7D2V/design.md`](plans/BAK-7D2V/design.md)) — closes the item.
- **Type:** cumulative-final
- **Deliverables** (per design §"Chunked build plan" item 3):
  1. `skills/song-snapshot/SKILL.md` — after a confirmed overwrite, state the
     guard is disarmed ("snapshot now newer than all pulled state"). Add a
     **re-stamp-on-empty-diff** affordance: where the skill currently hard-stops
     on exit 0 (SKILL.md:68, "no changes → delete refresh, stop"), offer "no
     content changes; refresh `captured_at` anyway?" — closes the
     pull→hand-revert-in-Live corner without `--force-replay`.
  2. `src/hallucinote/capture.py` — the code path backing the empty-diff
     re-stamp: refresh `captured_at` on the canonical snapshot without a content
     change (the skill's affordance needs a real CLI/entry it can call;
     `compile_snapshot`/`captured_at` live here from Chunk 1).
  3. `skills/song-pick-instruments/SKILL.md` — stamp `captured_at` (authoring
     time) on hand-authored snapshots, per design (absent → legacy handling).
  4. Docs: `docs/snapshot-schema.md` (done in Chunk 1) + `/song-workflow` name
     the pull→bake→build contract in one place.
- **Done when:**
  1. Unit test: empty-diff re-stamp updates `captured_at` with no content diff;
     a subsequent `replay_capture` no longer raises `StaleSnapshotError` for the
     re-baked song. Acceptance criteria met.
  2. Commit the chunk, then `/prawduct:critic cumulative` against
     `merge-base...HEAD` (the one cumulative pass — this is the `/prawduct:pr
     create` gate); blocking findings resolved.
  3. Committed; chunk marked [x]. BAK-7D2V backlog item → `update status=shipped`.
- **Visual change:** yes (skill-driven confirmation flow).
- **Operator verification (Live-gated, queued not built):** real Live session —
  dial a knob → `/ableton-pull` device-parameters → `build.py` refuses → notice
  seen → `/song-snapshot` → build passes, knob survives → `--force-replay`
  reverts. Append to `.prawduct/operator-verification.md` at chunk close (design
  §"Operator verification").

---

## PR structure (recommendation)

Two PRs off the same branch point, split at the A / B boundary:

1. **`chore/changelog-canonicalization`** — Chunk A only (VEW-7T2C + VEW-9QH4).
   Fast, mechanical, independently reviewable and revertable; unrelated to the
   durability work.
2. **`feat/bak-7d2v-pull-durability-ux`** — Chunks B + C (BAK-7D2V remainder),
   the cumulative-final review is this PR's create gate.

Ship as one PR only if the user prefers a single merge. `/prawduct:pr` at
merge time handles either shape.

## Deferred / out of scope (not silently dropped)

- Plugin-side parser (`TAG_LINE_RE`), `stamp-merged`, `regen-views`
  canonicalization — framework-coupled, lands with the upstream prawduct sync
  (memory: project_prawduct_framework_authorship).
- BAK "Open refinements" from the design: disarm-after-forced-replay
  (row-granular), guard for build.py-owned pulled domains — explicitly deferred
  in `.prawduct/artifacts/plans/BAK-7D2V/design.md`, not reopened here.
