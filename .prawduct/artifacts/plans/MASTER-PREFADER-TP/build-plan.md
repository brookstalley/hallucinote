# MASTER-PREFADER-TP — Build Plan

Branch: `fix/master-prefader-true-peak`. Critic mode: **cumulative** (base `develop`).

The 5th 2026-06-14 swell-dogfood report: the MixReport `master` loudness block (true-peak,
overshoots, LUFS) is measured PRE master-fader — the HallucinoteAnalyzer sits in the master
DEVICE CHAIN, which Live processes before the master mixer volume. So `master.true_peak_dbtp`
is the mix BUS, not the delivered output, and nothing says so. An agent trims the master fader
expecting the reported TP to move; it doesn't (cost a wasted swell render).

## Requirements Confidence: **High** (firsthand scoping)
- **Problem:** master metrics are pre-fader bus, unlabeled → "is my master clipping at delivery?"
  is unanswerable from the report.
- **Success:** the report carries a DELIVERED (post-fader) true-peak + the master fader gain, and
  documents that `master.loudness` is the pre-fader bus.
- **Out of scope:** moving the analyzer tap post-fader (Live has no post-master-fader insert);
  delivered LUFS as a separate field (the agent can shift any master metric by `master_fader_db`);
  a master limiter's post-fader effect (a master limiter sits IN the chain → already captured).

## Key facts (verified)
- `live_fader_db(normalized)` (`src/hallucinote/audio/levels.py`) is the CALIBRATED Live-12 curve
  (0.85→0 dB unity) — `20·log10(vol)` would be wrong. Already used by the analysis handler.
- The master fader volume is in the DB (`tracks.volume` where `kind='master'`). The handler already
  opens that conn + reads tracks (`_collect_stem_gains`).
- `analyze_mix` is DB-agnostic (takes declared_* params), so the handler must thread the master
  volume in → the analysis handler changes. **UPDATE (rebased onto develop 2026-06-20):** the
  analysis handler now lives in `server_side/analysis.py`, which MCP-7F2K relocated OUT of
  `_FINGERPRINT_PATHS` — so this is **NO fingerprint flip, no re-vendor**. (When this plan was
  written 2026-06-13 the file was under `handlers/` and a flip was expected.) All parts
  (analyze.py, report.py, server_side/analysis.py) are no-flip.

### Chunk 1: master delivered true-peak + fader gain + pre-fader label
- **report.py:** `MixReport` gains optional `master_fader_volume`, `master_fader_db`,
  `delivered_true_peak_dbtp` (default None; serialized in `to_json_dict`).
- **analyze.py:** `analyze_mix(master_fader_volume=None)` → `master_fader_db = live_fader_db(v)`,
  `delivered_true_peak_dbtp = master.loudness.true_peak_dbtp + master_fader_db` when known; doc the
  pre-fader-bus framing.
- **server_side/analysis.py (no flip — non-fingerprinted post-MCP-7F2K):** read the `kind='master'`
  row volume, pass `master_fader_volume=`; surface `master_fader_db` + `delivered_true_peak_dbtp`
  in the result summary.
- **docs/skill:** mix-review labels `master.loudness` the pre-fader BUS and points to
  `delivered_true_peak_dbtp` for the delivery/clipping question.
- **Tests:** analyze (non-unity fader → delivered TP = bus + live_fader_db); report round-trip;
  handler (master row volume → report carries the fields); None-safe when no master volume.

## Re-vendor note
**No re-vendor required.** Originally (2026-06-13) the analysis handler lived under `handlers/`
and a fingerprint flip was expected. MCP-7F2K since relocated it to `server_side/analysis.py`,
which is excluded from `_FINGERPRINT_PATHS`; rebasing this branch onto develop (2026-06-20) placed
the change there, and the running fingerprint is verified UNCHANGED. Engine-only + server_side —
no `/mcp`+`/ableton-mcp-install` re-vendor needed.

## Status
- [x] Chunk 1: master delivered true-peak + fader gain + pre-fader label
  - report.py: `master_fader_volume`/`master_fader_db`/`delivered_true_peak_dbtp`
    fields + `_finite_or_none` widened to None-safe (muted master -inf → JSON null).
  - analyze.py: `analyze_mix(master_fader_volume=)` → `live_fader_db` delivered TP.
  - server_side/analysis.py (no flip): `_collect_master_fader_volume` reads the
    `kind='master'` row, threads it into `analyze_mix`, surfaces delivered TP +
    fader dB in the summary.
  - skills/mix-review: labels `master.loudness` the PRE-fader bus, points to
    `delivered_true_peak_dbtp` for the delivery/clipping question.
  - Tests: analyze (delivered = bus + live_fader_db; None-safe; muted → -inf →
    null), report round-trip + muted-null, handler (`_collect_master_fader_volume`
    + end-to-end report/summary). Full suite 3715 passed, 2 skipped.
