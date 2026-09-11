---
lifecycle: completed
archived: 2026-09-08
maintained: false
---

> **Archived — no longer maintained.** This plan records what was built, not what will be. Do not edit it to reflect later changes; write those where they are true.

# AUD-4W7K — Build Plan (`compare_to` baseline diffs for MixReports)

Item: `compare_to` baseline diffs (audio-analysis, M/M, `stage: ready`; spike §9 defer
2026-05-23). Diff two MixReports keyed to DB audit-log seq numbers, surface per-metric
deltas with significance flags — the A/B verification workflow from the audio-analysis
spike ("Take comparison and A/B verification" section,
`.prawduct/artifacts/research-spike-audio-analysis.md`). One branch
(`feature/aud-4w7k-compare-to-baseline-diffs`), **stacked on
`feature/aud-3f8m-master-bus-automation`** (PR #154, unmerged — both touch
`report.py`/`analyze.py`); one PR into `develop` once #154 merges.

## Requirements Confidence: **Medium**

- **Problem (one sentence):** There is no structured way to verify that a mix change
  did what it predicted — `MixReport.compare_to` is a reserved skeleton (always
  `None`), so before/after questions need a human re-listening instead of a metric
  diff.
- **Success (one sentence):** `analyze_mix(..., compare_to=<seq>)` populates
  `MixReport.compare_to` with baseline provenance + per-metric deltas + significance
  flags, where `<seq>` resolves through the DB-audit-seq tag captures now record at
  render time (the deferred `manifest.db_seq` linkage the render handler docstring
  already names).
- **Out of scope (one sentence):** Diffing per-section metrics, masking pairs,
  timing/rhythm metrics, and verification results (additive later if wanted);
  reference-track / genre-target baselines (spike mentions them — separate item);
  any auto-verdict findings derived from deltas (see design decision below).

**Why Medium, not High:** the diff substrate is solid (both sides are the stable
`to_json_dict()` schema — dict-level diff, no deserializer needed), but the
significance thresholds and the seq-resolution semantics are design choices to be
validated against real analysis JSONs, not settled requirements.

**Design decision — deltas are neutral evidence, not verdicts.** The spike frames
diffs as "structured before/after metric diffs so the LLM or user can verify a
proposed change did what it predicted." A delta is not good or bad without intent
(learnings: "lens numbers validate, not just describe"), so this item adds **no new
finding kinds** — `compare_to` is evidence the interpreter grades against intent,
like every other lens.

**Open assumptions / unknowns:**

- `[ASSUMPTION: significance for dB-domain loudness metrics (lufs_i, lufs_s_median,
  lufs_m_peak, true_peak_dbtp) = a single named constant, starting at 0.5 dB (~JND),
  calibrated in Chunk 01 by diffing real sun-zone-done analysis JSONs before test
  assertions freeze it (learnings: calibrate against real cases) | MED impact | user
  can re-tune on the QLT-3D8R listening day]`
- `[ASSUMPTION: the diff payload lives inside the existing reserved `compare_to`
  field as {"baseline": provenance, "deltas": [...], "added_surfaces": [...],
  "missing_surfaces": [...]} — the backlog's "MixReport.deltas" wording is satisfied
  in substance, no new top-level field | LOW impact | user can override]`
- `[ASSUMPTION: seq resolution = exact match on the baseline report's recorded
  db_seq, latest timestamp wins a tie, no match → explicit error (no fuzzy
  nearest-seq); pre-existing reports without db_seq can only be baselines via an
  explicit path | MED impact | user can override]`
- `[ASSUMPTION: diff scope = per-surface loudness (master + stems + returns, stems
  keyed by surface id) + overshoot count; everything else explicitly descoped above
  | MED impact | user can veto the descope]`

**What would raise confidence:** the Chunk 01 calibration step — diff two real
on-disk sun-zone-done analysis JSONs and read the noise floor before freezing the
significance constant (~15 min, planned in).

## Status

- [x] Chunk 01: diff engine + `compare_to` end-to-end via explicit baseline path
- [x] Chunk 02: db_seq provenance + seq resolver + surfacing sweep
Context: plan authored 2026-06-10; branch stacked on AUD-3F8M (PR #154).
**Chunk 01 done 2026-06-10. Calibration evidence (Done-when 1):** master-loudness
deltas across the 6 sun-zone-done analysis JSONs (2026-05-29..06-03) —
same-mix re-capture pairs (06-03 02:41→03:34; 05-29→05-30) sit at
|Δ| 0.02–0.13 dB for lufs_i / lufs_m_peak / true_peak_dbtp, real mix-version
bumps at 0.36–2.5 dB, so the planned 0.5 dB constant is KEPT for those three.
**Adjusted from the plan's single-constant assumption:** lufs_s_median wobbles
0.38–0.63 dB between near-identical takes (3 s short-term blocks are
arrangement-timing sensitive) — it gets its own 1.0 dB floor
(`SIGNIFICANCE_SHORT_TERM_DB`), or 0.5 dB would flag noise. Real-pair
verification: the v3→v4 diff (06-02→06-03) flags exactly the known story —
master true peak 1.52→−0.96 dBTP, 8 overshoots→0. **Honest caveat for
QLT-3D8R:** near-silent reverb returns (−50..−67 LUFS) flag large dB deltas
that may be capture-tail variance, not mix moves — before/after absolutes are
in each row so consumers can weigh it; whether quiet surfaces deserve an
absolute-level floor is a listening-day question. Critic (final-mode run on
the chunk): 0 blocking / 1 warning (this evidence record) / 2 notes —
missing-baseline error test added; baseline schema/song validation before the
DSP pass deferred to Chunk 02 (noted there).
**Chunk 02 done 2026-06-10.** **Explicit deviation from the plan's wording
(governance checkpoint):** the plan said "the render handler reads the
song's latest event seq" — the render handler runs inside Live's vendored
env with no hallucinote package, so the read lives in the MCP server's
forward-time preprocessor (`server._attach_render_db_seq`, mirroring the
established `_absolutize_render_output_dir` pattern) and the handler just
writes the forwarded param into the manifest. Provenance is best-effort
(no DB / engine → untagged manifest, never a blocked render) and the seq
is "latest DB state at render time", NOT proof of what Live played —
mutate-without-push mislabels the key; caveat surfaced in the server
docstring + the analyze action's compare_to description. Critic final:
0 blocking / 3 warnings (tagged change-log entries added for both chunks;
provenance overclaim softened; summary now carries overshoot_delta and
counts the overshoot change in significant_delta_count) / 4 notes
(deviation recorded here; `connection.connect()` adopted; explicit-db_seq
passthrough test + non-int db_seq resolver guard added; backlog flips
stay pending merge per Done-when 4). Remaining: cumulative Critic vs the
stack base + PR; backlog pass (AUD-4W7K shipped on merge, MIX-6D2N note).

## Scaffolding

Existing project — no scaffold work. Tests in `tests/unit/audio/` (pytest, synthetic
fixtures; `HALLUCINOTE_SKIP_AUDIO=1` opt-out for DSP-heavy tests, though the differ
itself is pure-dict math). Verification beyond tests: diff two real sun-zone-done
analysis JSONs on disk (no Live needed); if fewer than two analysis JSONs exist on
disk, calibration uses a perturbed copy of one and the real two-take signal is
flagged in the PR as pending the next render.

---

## Chunk 01 — diff engine + `compare_to` end-to-end (thin slice)

new `src/hallucinote/audio/compare.py`: `diff_reports(current: dict, baseline: dict)
-> dict` operating on `to_json_dict()`-shaped dicts (no deserializer — the JSON
schema is the contract, see `src/hallucinote/audio/report.py::MixReport.to_json_dict`).
Diffs per-surface loudness — master, stems, returns, keyed by surface id so
added/removed tracks surface as `added_surfaces`/`missing_surfaces`, never silent
misalignment — plus overshoot count. Each delta row: surface, metric, before, after,
delta, significant (|delta| ≥ the named constant; non-finite/null on either side →
delta null + significant false, mirroring `_finite_or_none` semantics).
`analyze_mix` (`src/hallucinote/audio/analyze.py`) gains `compare_to` accepting an
explicit baseline-JSON path in this chunk (the int-seq form is Chunk 02): loads the
baseline dict, calls `diff_reports`, populates `report.compare_to`.

The existing `test_compare_to_field_is_reserved_skeleton` and the "reserved" wording
in `tests/unit/audio/test_report.py` pin the *old limitation* this item explicitly
supersedes — updating them to the new contract is a requirement change being
implemented, not a weakened test; say so in the commit.

- **Type:** code
- **Depends on:** none
- **Deliverables:** new `src/hallucinote/audio/compare.py`;
  `src/hallucinote/audio/analyze.py` (compare_to plumb);
  `src/hallucinote/audio/report.py` (docstring: compare_to no longer "reserved");
  new `tests/unit/audio/test_compare.py`; updated `tests/unit/audio/test_report.py`,
  `tests/unit/audio/test_analyze.py`.
- **Tests:** pure-dict differ units — identical reports → all deltas 0 +
  insignificant; a perturbed master lufs_i past the constant → significant with
  correct sign; stem present only in current/baseline → added/missing, not a diff
  row; null/non-finite metric on one side → null delta, never a crash; analyze-level
  — `analyze_mix(compare_to=<path>)` on a synthetic capture populates
  `report.compare_to` and serializes through `to_json_dict()` (allow_nan=False
  backstop holds).
- **Acceptance criteria:** `analyze_mix(..., compare_to=<baseline path>)` returns a
  report whose `compare_to` carries baseline provenance + per-metric deltas +
  significance flags; calibration evidence (real-JSON diff, noise floor vs the 0.5 dB
  constant) recorded in chunk notes.
- **Done when:**
  1. Calibration diff on real on-disk analysis JSONs recorded in chunk notes
     (constant kept or adjusted + evidence)
  2. Acceptance criteria met and tests pass
  3. `/prawduct:critic` run (inference: chunk) and blocking findings resolved
  4. Committed and chunk marked `[x]` in Status

## Chunk 02 — db_seq provenance + seq resolver + surfacing sweep

Implement the deferred audit linkage named in
`hallucinote_mcp/src/hallucinote_mcp/handlers/render.py` (module docstring,
"DB-side audit linkage (`manifest.db_seq`) is deferred"): at capture time the render
handler reads the song's latest event seq (`events` table,
`src/hallucinote/db/queries.py` query conventions) and writes `db_seq` into
`manifest.json`. `src/hallucinote/audio/io.py::CaptureSet` gains `db_seq: int | None`
(tolerant of old manifests); `MixReport` gains `db_seq` copied from the capture and
serialized. New resolver in `src/hallucinote/audio/compare.py`:
`resolve_baseline(analysis_dir, seq)` — scan `analysis/*.json` for matching `db_seq`
per the resolution assumption (exact match, latest tie-break, explicit error on
none). `analyze_mix`'s `compare_to` now also accepts an int seq (requires the new
`analysis_dir` param); the MCP analyze action
(`hallucinote_mcp/src/hallucinote_mcp/actions/analysis.py` +
`handlers/analysis.py`) exposes `compare_to` and passes the analysis dir it already
writes to. Also take the Chunk 01 Critic note: validate the baseline's
schema_version/song_slug right after the fail-fast load (against
`capture.song_slug` / `SCHEMA_VERSION`) so a wrong baseline refuses *before*
the DSP passes, not after.

**Surfacing sweep (the contract-drift class that blocked twice on 2026-06-10):**
grep-driven sweep of every surface that teaches the old "compare_to reserved /
deferred" contract — `report.py` module header, `render.py` handler docstring's
"deferred" paragraph, the analyze action's tool description, `/mix-review` skill
text, spike §9 defer note gets a decision-record update — before the Critic finds
them.

- **Type:** cumulative-final
- **Depends on:** Chunk 01
- **Deliverables:** `hallucinote_mcp/src/hallucinote_mcp/handlers/render.py`,
  `hallucinote_mcp/src/hallucinote_mcp/actions/analysis.py`,
  `hallucinote_mcp/src/hallucinote_mcp/handlers/analysis.py`,
  `src/hallucinote/audio/io.py`, `src/hallucinote/audio/report.py`,
  `src/hallucinote/audio/compare.py`; tests in `tests/unit/audio/` and the MCP
  handler test tree.
- **Tests:** manifest with/without `db_seq` loads (old captures stay loadable);
  resolver — exact match, tie → latest, no match → explicit error, reports lacking
  db_seq skipped; analyze-level int-seq path end-to-end against a temp analysis dir;
  handler-level — render writes db_seq, analyze threads compare_to through.
- **Acceptance criteria:** the backlog item's verifiable signal —
  `analyze_mix(..., compare_to=<seq>)` populates the report's deltas + significance
  flags via the db_seq tag; old captures and reports degrade honestly; no surface
  still teaches the reserved/deferred contract.
- **Done when:**
  1. Acceptance criteria met and tests pass
  2. `/prawduct:critic` run (inference: final) and blocking findings resolved
  3. `/prawduct:critic cumulative` against the stack base (`develop...HEAD` once
     #154 merges; until then the AUD-3F8M branch point) clean — the
     `/prawduct:pr create` gate (base: develop)
  4. Committed, chunk marked `[x]` in Status; backlog pass via `/prawduct:backlog`:
     AUD-4W7K → shipped on merge; note on MIX-6D2N (its predictor consumes these
     deltas) if its text assumes compare_to is still open

## Early Feedback Milestone

**Milestone chunk:** 01 — diffing two existing analysis JSONs already answers "did
the change move the numbers?" without waiting for seq plumbing.

## Governance Checkpoints

**Commit & PR cadence:** commit per chunk after its Critic passes; one PR into
`develop` after Chunk 02's final + cumulative reviews pass (`/prawduct:pr`, base
develop, after #154 merges — note the stack in the PR description if it goes up
first).

- After Chunk 01: review the significance-constant calibration evidence and the
  neutral-evidence (no new finding kinds) decision before seq plumbing builds on
  the same payload shape.
