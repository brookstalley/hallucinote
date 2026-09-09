---
lifecycle: completed
archived: 2026-09-08
unbuilt_at_archive: "no readable `## Status` roster — completeness cannot be read, and an unreadable plan is not evidence of completion"
maintained: false
---

> **Archived — no longer maintained.** This plan records what was built, not what will be. Do not edit it to reflect later changes; write those where they are true.

# ROUNDTRIP-CLUSTER — sidechain SOURCE pull-capture + extract coverage

Branch: `fix/sdc-7k3m-pull-capture`. Critic mode: **cumulative** (base `develop`).

Triage source: autonomous backlog/bug-report sweep, 2026-06-13. Verify-first
(per `feedback_backlog_ready_items_may_be_already_shipped`) collapsed a ~15-item
candidate set to **2 genuine builds + 6 drift reclassifications** — same pattern as
the prior RELIABILITY-CLUSTER. The drift catches are tracked as the backlog
reconciliation deliverable (not chunks); see "Backlog reconciliation" below.

## Scope

**IN (code):**
- **C1 — SDC-7K3M pull-capture** (medium, correctness). Completes the device
  sidechain SOURCE round-trip. Author + push already shipped on develop (`9868e75`):
  `devices.sidechain_source_track_id` FK, `set_device_sidechain` mutator,
  `plan_push_device_sidechain` push phase. REMAINING (this item's open `ready`
  scope) = the PULL-capture half: bake the SOURCE from a live set via
  `ableton_device(get_input_routing)` into the DB. Engine-only — the MCP
  `get_input_routing_handler` already exists (`handlers/device.py:1250`, returns
  `has_input_routing` + `current_type`/`current_channel`), so NO MCP change, NO
  fingerprint flip, NO re-vendor.
- **C2 — DEV-4X2N** (small, coverage). Regression test pinning that
  `_extract_song_structure` flattens only the top-level device chain (nested rack
  inner devices excluded). The behavior is documented + deliberate (nested-rack
  pull is gated on DEV-7K4H); the `_seed_full_song` fixture had no nested rack, so
  a regression that started dropping rack containers wouldn't be caught.

**OUT (deferred, with reason):**
- SDC-7K3M **Live round-trip verification** — operator-gated (Live occupied at
  author-time); enqueued in `operator-verification.md`. The unit tests (fake MCP
  results) verify the planner + apply logic, mirroring how the push half shipped.
- **Auto-CLEAR on a non-track input** — V1 apply captures a clear distinct-track
  match and no-ops every ambiguous case (self-match, name collision, non-track
  input). Tightening to Ableton-authoritative clearing is gated on Live
  verification of how Live reports an un-sidechained device's default input — a
  fact I cannot verify without a session. Documented limitation, not a silent drop.
- **PSH-3H8M** (perform-hang watchdog) — re-verified deferred (see reconciliation).
- **ENV-5R2J / ARR-6T8N** — HELD (see reconciliation).

## Confidence Check (C1)

1. **Problem.** A device sidechain SOURCE set/changed in Live is not captured back
   into the DB — author+push round-trips it, but there is no pull path, so the
   `/snapshot-bake-recent-changes` workflow can't bake it and the mix survives only
   in the `.als` (defeats the build.py+snapshot source-of-truth model).
2. **Success.** A `device-sidechain` pull domain probes `get_input_routing` per
   linked top-level device; the apply handler resolves Live's `current_type`
   (a track display_name) → a song-track FK and writes through
   `set_device_sidechain`; unit-tested with fake results (probe emitted per linked
   device; apply sets a distinct-track match, no-ops self/none/ambiguous,
   re-verifies link, is idempotent).
3. **Out of scope.** Live round-trip verification (operator-gated); auto-clear
   policy (Live-gated); MCP-side changes (getter exists).

## Boundary investigation (C1)

Crosses the **Pull Planner / Result API** surface (`boundary-patterns.md`). A new
`PullCall` key kind `device_sidechain_source:<device_id>` needs a `_HANDLERS` entry
AND an `apply_pull_results` branch (the boundary doc's stated rule). Both added in
the same change; boundary doc + `PullCall` docstring updated to document the new key
kind's normalized result shape. Consumer: `/snapshot-bake-recent-changes` skill —
given a light note pointing at the new domain (no rewrite of its dry-run flow).

## Chunks

- [x] **C1 — SDC-7K3M pull-capture.**
  - `plan_pull_device_sidechain(conn, *, song_id, session_id)` in
    `sync/pull/devices.py` — mirrors `plan_pull_device_parameters`' linked-device
    iteration (top-level chain, master skipped, returns included), emits
    `device_sidechain_source:<id>` = `ableton_device(get_input_routing, ...)`.
  - `_apply_device_sidechain_source(...)` in `sync/pull/devices.py`. Policy:
    re-verify device link (defense in depth) → `has_input_routing` False → no_op →
    `current_type` None → no_op → resolve `current_type` via `Q.tracks_by_name`:
    self-match (device's own host track) → no_op; exactly one OTHER track →
    `set_device_sidechain(..., channel=current_channel)` (idempotent); ambiguous →
    warning; no song-track match → V1 no_op (documented).
  - Register `device-sidechain` in `pull_cli._DOMAINS`; export the planner from
    `sync/pull/__init__.py`; add `_HANDLERS["device_sidechain_source"]` + apply
    branch in `sync/pull/plan.py`.
  - Update `boundary-patterns.md` (Pull Planner section) + the `PullCall` docstring
    in `sync/pull/_core.py` + a light note in the bake skill.
  - Tests in `tests/unit/sync/test_pull.py`: planner emits one probe per linked
    device (skips unlinked, master); apply sets a distinct-track source, no-ops
    self/none/`has_input_routing=False`/ambiguous, re-verifies link, idempotent
    second-apply; unknown-key guard still fires.
  - Enqueue Live round-trip in `operator-verification.md`.

- [x] **C2 — DEV-4X2N extract top-level-only regression test.**
  - In `hallucinote_mcp/tests/unit/test_handlers_analysis.py`: seed a nested rack
    (top-level rack device with an inner chain holding a device) and assert
    `_extract_song_structure`'s device dump contains the top-level rack device but
    NOT the inner-chain device — pinning the documented exclusion.

## Acceptance

`pull_cli execute device-sidechain <session>` probes each linked device's input
routing and bakes a distinct-track source into `devices.sidechain_source_track_id`
(idempotent, link-gated, conservative on ambiguity). Extract test pins top-level-only.
Full suite green; Critic cumulative 0-blocking. MCP fingerprint UNCHANGED
(engine-only) — no re-vendor.

## Backlog reconciliation (verify-first drift catches — the triage deliverable)

- **DEV-2H6K → resolved-by-D4.** `device_names.py`'s `_CLASS_TO_DISPLAY` merge
  table is DELETED (Arc 4/D4); Live's native `class_display_name` flows to
  `devices.kind`; the loader matches on `kind`. The merged-display re-push failure
  mode (Phaser/Flanger → "Phaser-Flanger") is structurally gone.
- **SNG-4H2D → stale-here.** Target songs (falling-walking, full-band-rock,
  sun-zone-done) moved to the private hallucinote-songs repo; `songs/missing/` has
  no build.py. The migration belongs in the songs repo, not here.
- **VEW-3M8F / VEW-7T2C / BLG-7K2Q → framework-coupled, deferred.** All target
  `tools/product-hook` / `.prawduct/critic-review.md` / critic SKILL.md —
  plugin-provided, NOT tracked here (only 5 migrate/eval tools are in `tools/`).
  Per `project_prawduct_framework_authorship`, not a sibling build.
- **PSH-3H8M → confirmed-deferred.** Re-verified in current code: ceiling
  (`automation.py:1956-1981`) + pre-perform reset (`_arm_and_seek:1922-1932`)
  exist; the real residual is a `run_on_main` timeout (high blast radius,
  Live-only-tunable, `_FINGERPRINT_PATHS`). Diagnosis already in the backlog.
- **ENV-5R2J → HELD (note sharpened).** The mutator gate encodes host-kind
  *eligibility*; the planner encodes the *route*. A true dedup needs a neutral
  shared module (a DB-layer→sync-layer import is a layering inversion) — its own
  focused change, not a rushed bundle.
- **ARR-6T8N → HELD.** Low impact ("unlikely in real songs"); left `ready`.
- Delete the stale **PSH-CLUSTER** plan (both chunks `[x]`; briefing flagged it).
