# SNP-MIX-CLUSTER — Build Plan

Branch: `feature/snp-4k7m-mix-cluster`. Critic mode: **cumulative** (base `develop`).

Three backlog items the user picked for ROI (2026-06-13). Verify-first collapsed the set:
**MIX-3S7P is already shipped** (chunks 1+3 `[x]`, chunk 2 Live-gated → user said treat
operator-verification as passed) → it's a **close-out, not a build**. Two real builds remain.

## Requirements Confidence: **High**

Boundary + code investigation done firsthand (capture.py, reverb.py, analyze.py, report.py,
the `create_device_chain` mutator, mix-review SKILL).

---

### Chunk A: AUD-3T6L relative reverb RT60 tolerance (S, bugfix)

- **Problem:** `REVERB_TOLERANCE_S = 0.15` is a fixed ABSOLUTE band. Live's Reverb RT60 is
  a nonlinear function of Decay Time + Room Size + diffusion, so realized RT60 legitimately
  diverges from the nominal knob; a ±0.15 s absolute band false-positives on clean captures
  (sun-zone A-Plate 3.37 vs 3.0 = 0.37 s gap → flagged `reverb_out_of_tolerance` warning).
- **Success:** a sub-0.5 s realized-vs-intent gap on a clean (high-span) capture no longer
  emits a hard warning; the band scales with declared RT60.
- **Out of scope:** the full SNR/span-aware confidence band (the existing `tail_span_db`
  gating already handles unreliable low-span measurements); a new report field for the gap %.
- **Decision (recorded here):** **relative band with an absolute floor** —
  `tolerance = max(REVERB_TOLERANCE_FLOOR_S=0.15, REVERB_REL_TOLERANCE=0.20 * declared)`.
  Rationale: the device-nonlinearity error scales with RT60 magnitude (relative); the floor
  preserves the old band for very short RT60s. Alternatives weighed: pure relative (no floor
  → absurdly tight for sub-0.75 s reverbs); SNR/span band (deferred — proportionality, the
  span gate already covers it); reframe-as-note only (doesn't fix the band itself).
- **Boundary:** `ReverbVerification.within_tolerance`/`tolerance_s` are consumed by
  `analyze._run_reverb_verifications` (emits the warning Finding at analyze.py:979) and
  `report.py:798` (MixReport JSON). The change keeps the field shapes; only the band widens.
  `tolerance_s` stays a per-result field so a consumer sees the scaled band.
- **Done when:**
  1. `reverb.py`: `reverb_tolerance_s(declared)` helper + `REVERB_REL_TOLERANCE` /
     `REVERB_TOLERANCE_FLOOR_S`; `measure_return_rt60(tolerance_s=None)` defaults to the
     helper (explicit override preserved for tests).
  2. Existing reverb tests updated to the NEW contract (not weakened — they pinned the old
     requirement which AUD-3T6L intentionally changes); a regression test for the verifiable
     signal (clean 3.0 s declared / 0.37 s gap → `within_tolerance=True`, no warning).
  3. mix-review SKILL: one line framing an out-of-tolerance reverb as "% longer/shorter than
     intent" (producer's note), aligning with the relative band.
  4. Full suite green.

### Chunk B: SNP-4K7M master-track device snapshot authorship (M, feature)

- **Problem:** push side ships (DEV-6M2K loads master devices), but the snapshot models
  `song.master = {volume, panning}` with no `devices` array; `replay_capture` creates no
  master device chain; capture never probes the master chain. So a song author can't declare
  or round-trip a master Limiter — violating "sound design is authorship" at the master.
- **Success:** a `build.py` snapshot declares `song.master.devices=[...]`; `replay_capture`
  materializes them on the master chain; `compile_snapshot` attaches a probed master chain;
  the SNP-8R4K analyzer-strip joins the master path.
- **Out of scope:** master AUTOMATION envelopes (that's MAW-4K7P); a master rack walk beyond
  the existing one-level `_replay_devices` reuse (it already recurses).
- **Verified assumption:** `create_device_chain(parent_track_id=master_id)` is kind-agnostic
  (master is a track row, no kind guard) → master device chains work. (Backlog's one UNVERIFIED.)
- **Done when:**
  1. `replay_capture`: after the master mixer block, `if master.get("devices"):`
     `create_device_chain(parent_track_id=master_id)` + `_replay_devices(...)` — mirrors the
     track/return pattern exactly.
  2. `compile_snapshot`: master block carries `devices` (from a probed master chain arg),
     analyzer-excluded via `_exclude_analyzer_from_parent` (the SNP-8R4K join the code TODO
     at capture.py:774 promises).
  3. `migrate_snapshot` (`clean_snapshot_at_rest`): include the master parent in the
     analyzer-strip pass (remove the "master intentionally untouched" carve-out).
  4. `capture_plan`: add the master device-chain probe entry; `capture_cli` master probe.
  5. `docs/snapshot-schema.md`: document `song.master.devices`.
  6. Tests: replay a master device chain; compile_snapshot attaches + analyzer-filters the
     master devices; migrate strips a polluted master; full round-trip (declare → replay →
     master chain present). Live round-trip is operator-gated → user said treat as passed.

### Chunk C: MIX-3S7P close-out

Already shipped (chunks 1+3 `[x]`; chunk 2 render-verification Live-gated → treated passed
per user). Action: flip backlog `status=shipped` → Archive; no code.

## Status
- [x] Chunk A: AUD-3T6L relative reverb tolerance (reverb.py `reverb_tolerance_s`
      helper + floor/rel constants; `measure_return_rt60(tolerance_s=None)` defaults
      relative; tests renamed FLOOR + 2 regression tests; mix-review producer's-note
      framing). All audio tests green.
- [x] Chunk B: SNP-4K7M master device snapshot authorship (replay master chain via
      `create_device_chain(parent_track_id=master_id)`; compile_snapshot + migrate +
      snapshot_needs_migration join the master to the analyzer strip; capture_plan
      master probe; snapshot-schema.md doc; 8 tests + updated probe-set contract test).
- [x] Chunk C: MIX-3S7P close-out (6 items → Archive: AUD-3T6L, SNP-4K7M, MIX-3S7P, ARR-9K4T, SNP-8R4K, SDC-7K3M; MEL-1A7K held open — by-ear remains)

## Boundary investigation (Critic G5)
- **ReverbVerification contract** (`within_tolerance`/`tolerance_s`) — consumers:
  `analyze._run_reverb_verifications` (emits `reverb_out_of_tolerance` warning at
  analyze.py:979) + `report.py:798` (MixReport JSON serialization) + mix-review SKILL.
  Field shapes unchanged; only the band widens (per-result `tolerance_s` now scaled).
  analyze.py uses the default tolerance (no override) → relative band applies in prod.
- **Master device chain** — `create_device_chain` is kind-agnostic (verified: no kind
  guard; master is a track row), so `parent_track_id=master_id` works. `_replay_devices`
  already filters analyzers, so the master path is defended on both capture and replay.
  Mirrors the established track/return device-replay pattern exactly.
