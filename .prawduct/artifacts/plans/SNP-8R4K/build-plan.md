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

- [ ] **1 — Centralized identity + boundary exclusion** (no-Live; the keystone — kills pollution/accumulation/off-by-one)
- [ ] **2 — Legacy cleanup** (no-Live; strip analyzer rows from already-polluted snapshots/DBs)
- [ ] **3 — Render terminal-tap + observability** (Live; durable measurement correctness)

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

## Chunk 2 — Legacy cleanup (no-Live; depends on chunk 1's predicate)

**Deliverable (R10):** a one-time pass (a `capture_cli`/snapshot migration or a
documented one-shot) that strips `is_analyzer` device rows from already-polluted
committed snapshots/DBs and re-densifies positions, reporting per file what it
stripped (never a silent rewrite).

**Acceptance:** running it on a snapshot known to contain analyzer rows produces a
clean, dense, analyzer-free snapshot and prints the removals; running it on a clean
snapshot is a no-op.

**Done when:** the cleanup exists + is documented; a test fixture (polluted snapshot)
round-trips to clean.

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
