# Release plan — v1.8.3

**vPREV:** v1.8.2 · **vNEW:** v1.8.3 (patch) · **Cut:** 2026-08-11

## What this release is

The **worked-example release**: the demo song `punk-fate` and the tour that
documents how it was made, in two chapters. One shipping scope, `tour`, in two
change-log clusters — the second was authored after v1.8.2 was already cut.

**Patch, not minor:** no product capability changed. Outside `docs/`, `examples/`
and `.md`, the release touches exactly four files — `conftest.py` (test harness),
`tests/preferences/test_tour_freshness.py`, `pyproject.toml`, and
`.prawduct/project-state.yaml` — plus the four version surfaces and `uv.lock` at
the cut itself. No file under `src/hallucinote/` changes except `__version__`.

| Cluster | Substance |
| --- | --- |
| `tour` (B1, C1, D1) | The demo song lands as `examples/punk-fate/` — authored end-to-end from a one-sentence prompt in a live session, with its decisions, annotations, attempt ledger, analysis reports and shape tests in the default suite. `docs/tour.md` documents that session beat by beat against real artifacts; the README gets the evidence graft; `tests/preferences/test_tour_freshness.py` locks every quoted snippet, figure and asset. |
| `tour` (chapter 2) | The same song back in the studio for three measured re-cuts — 1/f performance breathing, a garage drum vocabulary, real gain staging, and the lead swap that retired the square-wave "vocal" — as beats 11–16, with `decisions/08`–`11` and `measurements/`. Plus the docs pass that corrected five stale claims the chapter left around it, and the Critic round that caught a published number contradicted by its own evidence (beat 14's bus-vs-delivered peak). |

## Release classification

| scope | disposition | blocker |
| --- | --- | --- |
| tour | ships |  |

## Re-vendor impact

**Re-vendor: not required.**

    git diff v1.8.2..develop --name-only | grep -E \
      'hallucinote_mcp/src/hallucinote_mcp/(wire|schema|dispatcher)\.py|/(actions|handlers|remote_script)/'

Returns nothing (verified at the cut). No `_FINGERPRINT_PATHS` file is touched, so
the handshake fingerprint is unchanged and consumers need nothing beyond the
ordinary plugin update.

## Step 3 — TOUR archives at this cut

Unlike v1.8.2, where this step wanted to archive `TOUR` with C1 and D1 still
unbuilt (upstream defect prawduct#634; reverted that hour), the manual `## Status`
check now passes cleanly: **7 of 7 chunks ticked, none open** (A1–A4, B1, C1, D1).
The plan's scope is what this release tags, so `plan-backfill --apply` archiving it
is correct rather than a premature declaration of done.

One thing the plan itself records and this cut inherits: **chapter 2 matched none
of A1–D1.** The listening session happened after the plan was complete, so its work
has no chunk and the cumulative Critic could grade none — recorded in the plan's
Context addendum rather than back-filled as a fake chunk. Archiving TOUR does not
imply chapter 2 was planned work; it means the plan that produced chapters 0–10 is
finished.

`active_build_plan` is cleared to empty (never the literal `null` — the pointer
reader would resolve that to `.prawduct/null`).

## Known-open, shipping anyway

Three items are on file against what this release ships, none of them a blocker:

- **#451** — the tour's freshness lock covers most quoted figures but not beat 12's
  five build-derived counts (no committed artifact carries them yet, so a source of
  truth has to exist first) or the two lens files at beats 5 and 11.
- **#454** — `format_requirements_md` renders 8 of 9 `DeviceStatus` values and drops
  `preset_query_unverified`; since `regen_requirements` never passes
  `browser_dry_runs`, that is the default path, so every generated `REQUIREMENTS.md`
  under-reports its built-in device list. Harmless for punk-fate (every dropped
  class is stock Live, so "no third-party plugins" stays true).
- **#455** — the song evidence tree has no retention lifecycle, while `docs/assets/`
  has two. Left at `stage: requirements`: the retention numbers are an owner call.

## Owner decision pending (does not gate the release)

`tour-walkthrough-design.md` §The concision rule carries a **dated amendment open to
veto**: the media item cap is now accounted per editing session (6 screenshots ·
4 audio items = 16 files, 7.0 MB against the unchanged 12 MB byte cap). It was
written because chapter 2 shipped 16 files and reconciled them by editing the
enforcing test's comment while still citing the artifact as its authority — a norm
changed in code instead of in the norm. If the owner rejects per-session accounting,
the remedy is dropping two of chapter 2's four media items, **not** re-relaxing the
test.
