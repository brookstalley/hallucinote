# Release plan — v1.8.5

**vPREV:** v1.8.4 · **vNEW:** v1.8.5 (patch) · **Cut:** 2026-08-11

## What this release is

The **launch-readiness release**: the user-facing corpus read critically from
the README outward, four contradictions closed, the questions a prospective
user asks before installing actually answered, and the framing recentred on the
person using the tool. Two shipping scopes, both docs.

**Patch, not minor:** no product capability changed. Beyond docs the release
touches two non-`.md` files — `.claude-plugin/marketplace.json` (a stale
description string) and one new test pinning the count that string carries —
plus the four version surfaces and `uv.lock` at the cut itself. No executable
code path changes.

| Cluster | Substance |
| --- | --- |
| `docs-launch-readiness` | Four contradictions: `marketplace.json` claimed the plugin "Requires the `hallucinote` Python engine installed" (stale since the plugin absorbed the engine — the first sentence a user reads, in the install dialog); VISION claimed audio round-trips in the present tense against `known-issues.md`; VISION's "impossible in every other tool" invited an argument it would lose; CONTRIBUTING taught pip/venv against a uv-gated CI and the deprecated `ok-broad-except` spelling. Omissions closed: what it costs to run (Claude usage and the Ableton bill), "the melody is yours" promoted out of the agent-facing `capability-truth.md`, whether you end up with a finishable Live set, build determinism, output ownership. "Any Live 12 edition" narrowed to Standard and Suite across all five surfaces that carried it — including `capability-truth.md`, the doc the install handoff and `/song-new` answer users from. Framing recentred so the user holds the creative verbs, with a "Who it's for" section covering curiosity, reach and leverage. Two prose norms ratified and registered. New guard: `test_marketplace_manifest_tool_count_matches_actual_registry`. |
| `release-process-docs` | Reconstructed at this cut from `f4f9ad2`, which landed on `develop` with no entry — exactly the gap step 1 warns about, found by running the audit it prescribes. Step 9's back-merge documented as the one deliberate fast-forward in the process (passing `--no-ff` there leaves `develop` permanently one commit ahead and makes step 10's count read 1), and step 8 gained the plumbing path for when `main` is checked out in another worktree. |

## Release classification

| scope | disposition | blocker |
| --- | --- | --- |
| docs-launch-readiness | ships |  |
| release-process-docs | ships |  |

## Re-vendor impact

**Re-vendor: not required.**

    git diff v1.8.4..develop --name-only | grep -E \
      'hallucinote_mcp/src/hallucinote_mcp/(wire|schema|dispatcher)\.py|/(actions|handlers|remote_script)/'

Returns nothing (verified at the cut). Two files under `hallucinote_mcp/` are
touched and neither is a `_FINGERPRINT_PATHS` member: `tests/unit/test_server.py`
(tests are not vendored into Live) and `install_paths.py` (a docstring; the
module is on CONTRIBUTING's explicit non-fingerprinted list). The handshake
fingerprint is unchanged, so marketplace consumers get the new docs through the
ordinary plugin auto-update and need do nothing in Ableton Live: no
`/ableton-mcp-install`, no Live restart.

## Step 3 — nothing archives at this cut

`plan-backfill` reports **0 plans to archive**: neither shipping scope is
claimed by a build plan — both were direct docs work on branches, not planned
chunked work. `check-releasability` emits a WARNING to that effect for
`docs-launch-readiness`; it is expected for a docs cluster and is not a
blocker. The four plans that stay live (`ARR-PROJ`, `ENV-8K2R`, `ENV-9P4T`,
`SYN-8Q3F`) are untouched — none of their scopes is tagged by this release.

`active_build_plan` was already empty coming into the cut and stays empty (not
the literal `null`, which the pointer reader would resolve to `.prawduct/null`
and mis-fire the missing-build-plan advisory).

## Known-open, shipping anyway

Four items were filed *by* this release's review and ship open by design —
they are the follow-on work it identified, not defects in what ships:
**#457** (a second worked example in an exposed genre), **#458** (measure and
publish per-song Claude usage — this release deliberately publishes no token
figure, because none is measured; #458's acceptance retires that hedging),
**#459** (decide the CI platform and Python matrix — CONTRIBUTING now states
the gap honestly, which closes the honesty problem and not the coverage one),
**#460** (test Live Intro/Lite or declare them unsupported). **#329** (the
2:10 demo video) gained a comment recording the requirement its acceptance was
missing: the delivered `.mp4` has to be *embedded* in the README to play
inline, since the current `.mp3` link makes a reader download a file to hear
anything.

Carried from v1.8.3 and unchanged here: #451, #454, #455, and the owner veto on
`tour-walkthrough-design.md` §The concision rule. This release adds no media
items and does not disturb that question.

The `[norm-lifecycle]` advisory (`architecture.md` citing shipped work
brookstalley/hallucinote#350) is still active and still **not** release-gating.

**One release-readiness fact worth stating plainly:** the repository is
private at this cut. Every install path in the README, the CI badge, and the
SECURITY advisory link only resolve for a reader once it is public. Cutting
v1.8.5 does not change that, and nothing in this release depends on it.
