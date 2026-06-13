# SNP-8R4K — Build Plan (analyzer as measurement infrastructure)

Design: `.prawduct/artifacts/plans/SNP-8R4K/design.md`. Child of **BAK-3M9T**
(turnkey bake umbrella). Decision LOCKED: **persistent analyzer** (durable, for
ad-hoc-capture simplicity) + boundary-exclusion as the load-bearing
model-cleanliness guarantee + render-owned terminal-tap for measurement correctness.

**Critic mode:** cumulative at PR.

**Context (cross-session handoff):** Not yet built — this is the design/plan only.
Chunk 1 is the keystone (ends the capture-pollution → push-as-own-device →
duplicate-accumulation cycle and the off-by-one). Chunks 1-2 are engine-side
(no-Live, unit-testable); chunk 3 is Live-gated (render). MCP-4T6Y (async renders)
is complementary, not a gate.

## Status

- [x] **1 — Centralized identity + boundary exclusion** (no-Live; keystone) — DONE on `fix/snp-8r4k-boundary-exclusion`: `analyzer_identity.py` + filter/dense-renumber at `compile_snapshot`, `_replay_devices`, pull `_diff_chain_devices`, + push `_emit_device_calls` skip; 23 tests; full suite 3550. Also **auto-migrates the model** (State-1 functional clean — see design §Migration).
- [ ] **2 — Snapshot-file cleanup + version stamp** (no-Live; State-1 clean-at-rest)
- [x] **3 — Render terminal-tap + observability** (Live; durable measurement correctness) — DONE on `fix/snp-8r4k-live-chunks`: pure `_reposition_action(analyzer_idx, chain_len) -> "absent"|"already_last"|"reposition"` in `analyzer/setup.py`; `_ensure_on_surface` re-asserts terminal at render start — no-op when already last (R12, no M4L reload on unchanged surfaces), delete_handler + re-load (appends → last) when a device landed past it (R8/R11), load when absent; re-reads the chain after any load for the actual analyzer index (robust param targeting) + terminal check. `AnalyzerInstance` gains `terminal` + `was_repositioned`; `render.py` manifest carries them per surface + a top-level `analyzer_not_terminal` roll-up (R9 — never measure-and-lie). 11 new tests (3 pure helper + 5 `_ensure_on_surface` + 4 render-manifest incl. forced non-terminal + ensure_loaded-action surfacing); operator-verification enqueued (Live: yes — real reposition deferred). Full suite green. NOT committed.
- [x] **4 — Push-preflight stale-set detection + rebuild guidance** (Live; State-2 migration trigger) — DONE on `fix/snp-8r4k-live-chunks`: pure detector `analyzer_staleness.py` (`find_authored_after_analyzer` + `detect_stale_analyzer_surfaces`, reuses `is_analyzer_device`, position-based on probe chain order); wired into `probe_and_link` (`_flag_stale_analyzer_set`) over the same `live_devices_by_parent` probe map, guidance via the non-fatal `result.notes` channel (no hard halt); 18 pure + 5 wiring tests; operator-verification enqueued (Live: yes — real firing deferred). Full suite green. NOT committed.

## Chunk 1 — Centralized identity + boundary exclusion (no-Live; keystone)

**Deliverable (Mechanism 1):**
- A single shared `is_analyzer(device)` / `is_infrastructure(device)` predicate
  (promote `analyzer/setup.py:428` `_find_analyzer_index`'s logic — name + M4L class
  — into one reusable home consumed by capture, pull, and push). Pin the predicate
  carefully: it is load-bearing under the persistent design (R1).
- **Capture filter + dense renumber:** `capture.py` `compile_snapshot`,
  `sync/pull/devices.py`, `tools/capture_cli.py` drop `is_analyzer` devices and
  assign each survivor's `position` as its rank among survivors (1..N), never the
  raw Live chain index (R3, R5). Position-independent → correct even when the
  analyzer is interleaved.
- **Push skip:** `sync/push/devices.py` `_emit_device_calls` skips any `is_analyzer`
  DB row with a warning, never emits a load for it (R4).

**Acceptance:** a synthetic Live-chain snapshot with an analyzer (last AND
interleaved variants) captures to an analyzer-free model with dense authored
positions; a DB carrying an analyzer row pushes with the analyzer skipped (warned),
not loaded; round-trip (capture→push→capture) is stable with no accumulation and no
position drift. Full suite green.

**Done when:** the three boundary sites consume the one shared predicate (grep shows
a single identity definition); tests cover the interleaved-capture renumber, the
push-skip, and a capture→push→capture stability assertion.

## Chunk 2 — Snapshot-file cleanup + version stamp (no-Live; State-1 clean-at-rest)

Chunk 1 already makes a polluted snapshot *functionally* clean (strip-on-replay), so
the model self-corrects on the next build. This chunk cleans the committed
`captured_session.json` **at rest** so the artifact itself stops carrying analyzer
rows (design §Migration, State 1).

**Deliverable (R10):** strip `is_analyzer_device` entries from a committed snapshot +
densify survivor positions, **stamp a snapshot version** so the rewrite runs exactly
once (an unstamped/old snapshot triggers it; a stamped one is a no-op), and
**announce per file what was stripped** (never silent). Triggered either by a
detect-and-rewrite on `/song-snapshot` / build, or an explicit migrate command —
keyed to the SNP-8R4K release version so it fires when users update.

**Acceptance:** a snapshot containing analyzer rows rewrites to clean + dense +
stamped, printing the removals; a clean/stamped snapshot is a no-op; the rewritten
snapshot builds + pushes identically to a hand-cleaned one.

**Done when:** the cleanup + version stamp exist + are documented; a polluted-snapshot
fixture round-trips to clean; the version stamp gates re-runs.

## Chunk 4 — Push-preflight stale-set detection + rebuild guidance (Live; State-2 trigger)

The migration trigger for already-saved Live sets where authored devices landed
after the analyzer (under-measured captures). The fix is **rebuild from source**
(user-blessed "rebuild entire set is OK") — this chunk DETECTS + GUIDES, never
auto-rebuilds (the operator owns the set). Design §Migration, State 2.

**Deliverable:** in the push/compat preflight (`sync/compat.py` / probe-and-link),
probe the bound set; if any chain has authored devices *after* the analyzer (or the
analyzer interleaved among authored devices), flag the set as pre-SNP-8R4K and emit
operator guidance — "this set predates the analyzer-infrastructure fix; devices after
the measurement tap were under-measured. Rebuild from source: push into a fresh set."
A warning (not a hard halt), version-keyed so it fires on the first push to a stale
set after updating.

**Acceptance (operator-verified):** pushing to a set with a device after the analyzer
surfaces the rebuild guidance; pushing to a clean/rebuilt set is silent. Enqueue in
`operator-verification.md`.

**Done when:** the preflight detection + guidance exist; Live-verified on a stale set;
no false-positive on a clean set.

## Chunk 3 — Render terminal-tap + observability (Live; durable correctness)

**Deliverable (Mechanism 2):** at render start, before the capture pass, for each
measured surface ensure the analyzer is **present and strictly last**:
- absent → load (appends last);
- present + already last → **no-op** (common case, zero cost);
- present + not last → delete + re-add (lands last) — the M4L re-load cost paid
  *only on changed surfaces* (R8/R12). Self-heals intervening mis-order (R11).
- **Observability (R9):** record per-surface terminal-tap confirmation in the
  capture manifest / MixReport; flag any surface that can't be made compliant
  (`analyzer_not_terminal`) so a reading agent never trusts an under-tapped stem.

**Acceptance (operator-verified):** after loading a device post-render (so it lands
after the analyzer), the next render repositions the analyzer to last on that surface
and the per-stem capture reflects the post-analyzer device; an un-fixable surface is
flagged, not silently under-measured. Enqueue in `operator-verification.md`.

**Done when:** Live-verified terminal-tap reposition + the observability flag in the
report; no full-chain reload on unchanged surfaces.
