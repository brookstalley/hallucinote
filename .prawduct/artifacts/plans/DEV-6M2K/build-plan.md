# Build Plan — DEV-6M2K: master device writing (re-enable across the gated surfaces)

**Type:** bugfix (un-gate code built on a refuted empirical premise)
**Size:** medium → build plan + Critic (cumulative, base `develop`)
**Branch:** `fix/master-device-writing` (off `develop`)
**Critic mode:** cumulative (base develop)

## Confidence Check

1. **Problem:** Four surfaces refuse / skip master-strip device loading on the premise
   (DEV-2M9K, shipped #129) that `song.view.selected_track = master` silently no-ops so
   `browser.load_item` can't target the master. That premise is **refuted** — live-proven on
   Live 12.4.2 (select master → `browser.load_item` → `delete_device` works end-to-end; see
   `.prawduct/artifacts/research-spike-automation-ingest.md` "✅ RESOLVED — DEV-2M9K REFUTED").
2. **Success:** A DB-authored master device chain pushes cleanly (load emitted, links, params
   follow); the render analyzer sweep auto-loads the master analyzer on a fresh set;
   `ableton_device(action='load', master=True)` appends to the master chain. No surface still
   cites the refuted "place by hand / forever-manual" contract.
3. **Out of scope:** master *automation envelope* writing (that's the sibling **MAW-4K7P** —
   the device-load discovery does NOT grant an envelope-creation surface for the master);
   nested rack chains; native-device live corroboration (operator-verification follow-up, below).

## Root Cause (bugfix discipline)

A shipped capability verdict was treated as durable truth across Live versions. The premise was
empirically true on some earlier build and silently fixed by a Live update. Captured as the
standing learning *"A shipped 'can't' is a dated snapshot — re-probe before defending"*
(`learnings.md`). The fix un-gates; the regression protection is the flipped + new tests below.

## Scope — the "4 surfaces" collapse to **3 code files**

The backlog lists 4 gated places; "render setup" and `analyzer/setup.py` are the **same code**
(render calls `ensure_analyzers_loaded`; `render.py` has no separate master gate — only naming/
manifest references). So:

| # | File | Change |
|---|------|--------|
| 1 | `hallucinote_mcp/.../handlers/device.py` (`load_handler` ~651-670) | Delete the `master` refusal block. The generic `select → browser.load_item → post-condition` path already handles master identically to tracks (`_resolve_parent` / `_refresh_parent` / `_parent_address` all branch master), and the existing post-load chain-grew check catches a hypothetical mis-load (silent-noop guard). Mirror the track path = the *same* path. |
| 2 | `hallucinote_mcp/.../analyzer/setup.py` (`_ensure_on_surface` ~325-341) | Delete the master detect-only `RuntimeError`. Master then falls through to the normal `preset_query` load path (already `**track_address`-driven, incl. `master: True`). Covers the render-setup surface too. |
| 3 | `src/hallucinote/sync/push/devices.py` (`_emit_device_calls` ~163-179) | Delete the SYN-2M9P master configure-only skip. Master falls through to the generic `if device_at is None:` load-emission path; `parent_kv = {"master": True}` is already set up. |

## Test strategy — tests encode the refuted premise (correct the contract, don't weaken it)

The test **doubles** themselves model the refuted behavior. Flipping them is *correcting a
contract built on a disproven empirical premise* (live-verified on Live 12.4.2), not weakening
a test to pass code. Each flip asserts the new, true behavior with equal-or-greater rigor.

- **`test_actions_device.py`** — Linchpin: `FakeSongView.selected_track` setter deliberately
  no-ops a master selection. **Fix the double** so master selection *sticks* (Live 12.4.2). Flip
  `test_load_refuses_on_master` → asserts master load succeeds + appends to master chain.
- **`test_analyzer_setup.py`** — Most tests pre-place the master analyzer (detect path, unchanged
  → stay valid; only DEV-2M9K comments updated). Flip `test_sweep_fails_loudly_when_master_
  analyzer_absent` → `..._auto_loads_master_analyzer_when_absent`. The fake here already supports
  master loading (plain `_FakeSongView`).
- **`test_actions_render.py`** — pre-placed master tests stay valid; comment updates only.
- **`test_push_devices.py`** — flip `test_plan_push_devices_walks_master_chain`: unlinked master
  device now emits exactly one `device.load(master=True)` + the standard "not linked yet" note.
  The other two master tests stay valid.
- **`test_syn_2m9p_master_load.py`** → rename to `test_dev_6m2k_master_load.py`, full premise-flip
  rewrite. The execute-path coverage becomes a **positive** test (master load dispatched →
  links → devices phase completes). Add a **multi-hop** test: unlinked master device with a
  dialed param → load → link → convergence re-plan emits the param.
- **`test_push_perform.py`** — `test_phase_warns_pending_when_master_device_unlinked` stays
  behaviorally valid (perform still defers an unlinked master device); **docstring-only** update
  (the device is now loaded by the devices phase, not hand-placed).

## Artifact coherence sweep (Pattern sweeps are tree-wide)

Sweep docs/skills/guides for stale "can't load master / place by hand / forever-manual" phrasing
(conventions, gaps guide, capability-truth, live_smoke). Update to the re-enabled contract.

## Operator-verification follow-up (F10 — needs live Ableton + Remote Script re-vendor)

The capability is already live-proven (M4L Align Delay). Enqueue in
`.prawduct/operator-verification.md` before closing DEV-6M2K:
1. **Native (non-M4L) device** load onto master (e.g. EQ Eight) — rule out a device-class quirk
   (the backlog's explicit before-close caveat).
2. Full **push** of a DB-authored master-strip chain completes without a PARTIAL halt.
3. Render on a **fresh set** (no pre-saved master analyzer) auto-loads the analyzer on the master.

(Handlers run Live-side in the vendored Remote Script → requires re-vendor + Live quit/reopen.)

## Knock-on re-triage (do at backlog step)

DEV-2M9K (shipped verdict retracted), SYN-2M9P (planner-skip no longer correct), TPL-2D8K
(hand-built `.als` master-template workaround — core motivation weakened to a convenience).

## Status

- [x] device.py un-gate + test flip
- [x] analyzer/setup.py un-gate + test flips/comments
- [x] push/devices.py un-gate + test flip + SYN→DEV-6M2K file rewrite
- [x] doc coherence sweep (server.py render tool description; guides had no stale text)
- [x] verify suite green (3371 passed / 2 skipped) → Critic (no findings) → operator-verification enqueued

**Context (handoff):** COMPLETE. Code + tests merged via PR #162 (squash `bc5d36e`), Critic
clean. All three live operator-verification checks PASSED on 2026-06-12 (Live 12.4.2, bridge
re-vendored to `9093dfef` + reconnected): native non-M4L EQ Eight load+delete on the master;
full DB-authored master Limiter+Ceiling push via `execute_push` (devices phase ok=2/0, no
PARTIAL halt); HallucinoteAnalyzer resolved + loaded onto the master via the sweep's
`preset_query`. DEV-6M2K shipped + archived; DEV-2M9K verdict retracted, SYN-2M9P planner-skip
retired, TPL-2D8K reduced to an optional convenience (impact L→S). Nothing left.
