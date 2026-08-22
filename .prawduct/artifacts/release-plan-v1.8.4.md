# Release plan — v1.8.4

**vPREV:** v1.8.3 · **vNEW:** v1.8.4 (patch) · **Cut:** 2026-08-11

## What this release is

The **prose release**: the user-facing corpus read against the writing guide, the
README rewritten at the owner's request, and the song-overview *generator* fixed
so future scaffolded songs stop inheriting the defect the scrub found by hand.
One shipping scope, `docs-writing-quality`, in a single change-log cluster
covering both commits.

**Patch, not minor:** no product capability changed. The release touches nine
files — seven under `docs/` or `examples/`, plus `README.md` and one template,
`src/hallucinote/tools/templates/song/song.md.tmpl` — and then the four version
surfaces and `uv.lock` at the cut itself. No executable code path changes; the
template is data read by the song scaffolder.

| Cluster | Substance |
| --- | --- |
| `docs-writing-quality` | README: the forty minutes reattributed from the prompt to the session, the lifecycle diagram's analysis caption renamed to "composition, mix, and audio measurements" (with the `<desc>` element corrected to match, so screen-reader users don't keep the retired framing), and 1334 → 1008 words by merging two sections that described the same three capabilities. Corpus scrub: 15 docs / 24,646 words against `brooks-writing-style.md` — two point-first failures fixed (`punk-fate.md`, `docs/quickstart.md`), three banned hype words, two run-ons split. Generator fix: `song.md.tmpl` carried the same paperwork-first ordering plus a pointer at an internal artifact no user workspace contains. |

## Release classification

| scope | disposition | blocker |
| --- | --- | --- |
| docs-writing-quality | ships |  |

## Re-vendor impact

**Re-vendor: not required.**

    git diff v1.8.3..develop --name-only | grep -E \
      'hallucinote_mcp/src/hallucinote_mcp/(wire|schema|dispatcher)\.py|/(actions|handlers|remote_script)/'

Returns nothing (verified at the cut). No `_FINGERPRINT_PATHS` file is touched, so
the handshake fingerprint is unchanged. Marketplace consumers get the new docs and
the fixed template through the ordinary plugin auto-update and need do nothing in
Ableton Live — no `/ableton-mcp-install`, no Live restart.

## Step 3 — nothing archives at this cut

`plan-backfill` reports **0 plans to archive**: this release's only scope is
`docs-writing-quality`, which no build plan claims — the work was two direct docs
commits on `develop`, not planned chunked work. Four plans stay live and correctly
so (`ARR-PROJ`, `ENV-8K2R`, `ENV-9P4T`, `SYN-8Q3F`) — none of their scopes is
tagged by this release.

`active_build_plan` was already empty coming into the cut and stays empty. It is
not set to the literal `null` (the pointer reader would resolve that to
`.prawduct/null` and mis-fire the missing-build-plan advisory).

## Known-open, shipping anyway

The three items recorded against v1.8.3 (#451 tour freshness gaps, #454
`format_requirements_md` dropping `preset_query_unverified`, #455 song-evidence
retention) are **unchanged by this release** and remain open. None is a blocker,
and nothing here touches their code.

Carried forward from the v1.8.3 plan and still pending: the owner veto on
`tour-walkthrough-design.md` §The concision rule (per-editing-session media item
accounting). This release does not add media items and does not disturb that
question.

One advisory is active at the cut and is **not** release-gating:
`[norm-lifecycle]` — `architecture.md` cites brookstalley/hallucinote#350, whose
work is shipped, so the norm's rationale has decayed. The remedy is a re-affirm
plus cleanup item or a recorded retirement (`docs/norms.md` § Trajectory); it is
scheduled work, not a defect in what ships here.
