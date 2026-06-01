# Requirements — Section-scoped masking analyzer

> **Read `masking-analyzer-goals.md` first.** That north-star doc reframes the
> goal from *collision detection* to *intent verification* ("is the element
> that's supposed to win this section actually winning?"). The DSP below is the
> **measurement layer**; the goals doc adds the **intent layer** (track roles +
> per-section focal element → musically-framed, intent-graded findings with
> arrangement-first fixes) that is the actual product. The sections marked
> **[pending intent-layer revision]** describe the measurement layer only — and the
> intent layer was **resolved as the *interpreter's* job, NOT a spec revision**:
> `masking.py` ships neutral evidence (`MaskingPair` / `BedMasking`, no
> `MaskingFinding`/severity); `/mix-review` grades it against recalled intent
> (LLM-first). See `intent-architecture.md` § *Severity stays out of the DSP*. Treat
> those markers as **resolved**, not pending.

Status: **SHIPPED** — the DSP is live (`src/hallucinote/audio/masking.py`); this is
now the accurate as-built spec, not a proposal. Owner artifact for the
`feature/masking-analyzer` work. Sources: research spike §3/§4/§9
(`research-spike-audio-analysis.md`) for the DSP; `masking-analyzer-goals.md`
for the perceptual/production framing (working-engineer research).

## 1. Problem & differentiator

**Problem.** When two instruments occupy the same frequency region at the same
time, the louder one *masks* the quieter — the maskee is present in the mix but
not clearly audible. Mixers fix this by EQ-carving, ducking, or arrangement.
There is no mature Python library for inter-track masking, and every commercial
tool (iZotope, Sonible, Gullfoss, RoEx) that detects it is **blind to the
score** — it can flag masking on the full mix but cannot answer *"the kick and
bass mask in 60–100 Hz **during the chorus**."*

**Differentiator (the moat).** Hallucinote has per-stem captures **and** the
arrangement, so it can scope masking to a named section and to the stem-pairs
that actually co-play there. Per the spike: *knowing the score collapses
inference into measurement.* This is the one analysis in the suite that no
commercial tool can produce, and it composes directly with the section-
windowing arc already shipped (loudness → per-section attribution →
variable-tempo windowing).

**Observable success.** For a song with declared sections and captured stems,
`ableton_analysis` returns, per section, a ranked list of stem-pairs with a
*masked fraction* and the *dominant masked frequency region* — e.g.
`chorus: bass masks kick 0.62 in 60–120 Hz`. On a synthetic fixture where stem
A is constructed to mask stem B in a known band, the analyzer reports that pair
with high masked fraction in that band; on a fixture where the two never share
time or frequency, it reports ~0.

## 2. Scope

**In scope (MVP of the masking analyzer):**
- Spectral inter-stem masking via a psychoacoustic model: STFT → Bark-band
  power → spreading-function excitation → per-tile masking threshold → masked-
  tile ratio per ordered stem-pair (A masks B).
- **Section-scoped**: computed over each `SectionWindow` (reuses the shipped
  `intersect_window` + `BeatSampleMap` so windows are variable-tempo accurate).
- Ranked findings per section: top masked pairs + dominant Bark/band region.
- `MaskingReport` surfaced on `SectionMetrics` (and optionally a song-wide
  pass), serialized into the existing `MixReport` JSON.
- Synthetic test corpus that *defines* correctness (there is no labeled ground
  truth for real music — see §7).

**Out of scope (explicit defer):**
- **Onset/transient masking** ("kick buried by bass" via onset-windowed RMS,
  spike §3) — a related but distinct heuristic; separate follow-on.
- **Auto-fix / EQ suggestions** — analysis reports; it never proposes or applies
  moves (spike §6 "never auto-apply"). A later layer may suggest.
- **Reference-curve / tonal-balance** masking — different problem (P3 backlog).
- **Stemless input** (source separation) — stems come from the capture.
- **Realtime** masking — needs multi-stem alignment; offline-only (spike §3 table).

## 3. DSP approach (grounded)

Pipeline per section window, on the section-sliced stem audio:

1. **STFT** (`librosa.stft`). Mono-sum each stem (masking is a per-ear spectral
   phenomenon; mid-sum is the standard simplification — stereo-aware masking is
   a future refinement). Window/hop are calibration parameters (start: 2048 /
   512 at 48 kHz ≈ 43 ms / 11 ms). Magnitude → power per (frame, FFT-bin).
2. **Bark-band power.** Map FFT bins to ~24 critical bands via the Zwicker Bark
   scale (`Bark = 13·atan(0.00076 f) + 3.5·atan((f/7500)²)`). Sum bin power into
   bands → per-(frame, Bark-band) power per stem. (Coarser than the 6-band
   `attribution.BANDS`; masking needs critical-band resolution.)
3. **Spreading function (Schroeder 1979).** A tone in one band raises the
   masking threshold in neighboring bands. Convolve each frame's per-band power
   with the standard two-slope spreading function in the Bark domain
   (`10·log10 SF(dz) = 15.81 + 7.5(dz+0.474) − 17.5·sqrt(1+(dz+0.474)²)` dB, dz
   in Bark) to get a *spread excitation* per band. This is the masker's reach.
4. **Per-tile masking threshold.** For an ordered pair (masker A, maskee B), the
   threshold in a tile is A's spread excitation minus a masking offset
   (tonality-dependent in MPEG; MVP uses a fixed offset, a calibration
   parameter). B is *masked* in that tile when B's own band power is below A's
   threshold **and** B carries non-trivial energy there (so silence ≠ masked).
5. **Masked-tile ratio.** Per ordered pair, masked fraction = masked tiles /
   tiles-where-B-has-energy, within the section. Also surface the Bark/band
   region carrying the most masked energy (so the report says *where*).

Output per section: ranked `(masker, maskee, masked_fraction, dominant_region)`
above a reporting floor. Symmetric pairs are reported as the dominant direction
(A masks B more than B masks A → report A→B).

6. **Cumulative bed mode (F2 — required).** Pairwise A→B structurally cannot see
   *distributed* low-mid buildup — the goals doc's #1 real-world clarity killer,
   where a maskee is clear against any single stem but buried under the *combined*
   bed. So in addition to ordered pairs, compute, for each maskee B, its masked
   fraction against the **sum of all other energized stems' spread excitation** in
   the window (`BedMasking`). This is the "is the vocal buried under everything
   together?" measure.

**Level-domain caveat (F1 — read before trusting real-song output).** Captured
stems are **pre-fader** (the M4L analyzer is a parallel tap in the device chain;
Live's volume/pan come after). Masking is a *relative-level* phenomenon, so the
DSP is only valid on stems reconstructed to **mix level** (DB volume/pan +
section automation — build-plan C3). `masking.py` is pure DSP over whatever audio
it's handed: the synthetic corpus feeds constructed signals directly (correct by
construction), and the handler must pass level-reconstructed stems for real
songs. Until C3 lands, real-song masking output is provisional and must be
labelled so.

Citations to carry into the build: Zwicker & Fastl *Psychoacoustics*; Schroeder,
Atal & Hall (1979) spreading function; MPEG-1 Audio psychoacoustic model 1
(threshold offset / tonality). All are textbook; **the precise slope and offset
constants are prototype-calibrated against the synthetic corpus** (Chunk 1).

## 4. Data model / output schema  (REVISED — LLM-first, evidence only)

> **Decision (2026-05-28):** the masking layer emits NEUTRAL EVIDENCE only — no
> `MaskingFinding`, no severity formula. There is no structured track-role field
> in the DB (F6); roles are LLM-read prose. Intent-graded severity, musical
> framing, and ranked fixes are the holistic interpreter's job (build-plan C6),
> done in conversation against recalled markdown intent. Baking severity here
> would require a role column that doesn't exist and would recreate the
> "meter that says you're doing it wrong" the goals doc rejects. See
> `intent-architecture.md`.

New frozen dataclasses in `report.py` (where `MasterOvershoot` / `SectionMetrics`
live — keeps `masking.py` able to import them without a cycle):

```
MaskingPair(frozen):
    masker_track_id: str
    maskee_track_id: str
    masked_fraction: float        # 0..1, share of B's energized tiles A masks
    dominant_band: str            # musical-region label, e.g. "presence (2-5 kHz)"
    dominant_region_hz: tuple[float, float]   # precise Bark-band edges (evidence)

BedMasking(frozen):               # cumulative: B vs sum of all other stems
    maskee_track_id: str
    masked_fraction: float
    dominant_band: str
    dominant_region_hz: tuple[float, float]
```

`dominant_band` speaks the engineer's region language (sub / lows / mud / body /
presence / brilliance / air) per the goals doc; `dominant_region_hz` carries the
precise Hz under the hood.

`SectionMetrics` gains `masking: list[MaskingPair]` and
`bed_masking: list[BedMasking]` (both ranked, top-N, like `attribution`).
Serialized in `_section_to_dict`. Empty lists when a section has < 2 energized
stems. **No new `Finding` kind** — masking is evidence the interpreter reads, not
a pre-judged finding.

`SCHEMA_VERSION` stays "1" while the audio schema is unreleased (consistent with
how `per_section` / `attribution` were added) — confirm at build time.

## 5. Integration

- **`analyze_mix`** gains optional `analyze_masking: bool = False` (or always-on
  when ≥2 stems + sections — decide in Chunk 3). Stays DB-agnostic: operates on
  `capture.stems` sliced to each `SectionWindow` via the shipped
  `intersect_window(..., beat_map=...)`.
- **`masking.py`** (new): `analyze_masking_window(stem_segments, sample_rate, *,
  top_n) -> MaskingWindowResult` (carrying `pairs: list[MaskingPair]` +
  `bed: list[BedMasking]`) — pure DSP, window-agnostic, synthetic-testable
  (mirrors `attribution.band_attribution`'s shape). `analyze_mix` calls it per
  covered section. Operates on whatever audio it's handed (see §3 level caveat).
- **MCP handler**: no new DB read required for correctness — energized-stem
  detection comes from the audio. **Optional optimization**: prune pairs that
  the DB clip schedule says never co-play in a section (avoids O(stems²) work on
  silent pairs). Filed as a perf follow-on, not MVP correctness.
- **Composes with** the section-windowing branches (`SectionWindow`,
  `BeatSampleMap`, per-section `attribution`). **Sequencing:** land
  `feature/per-section-attribution` + `feature/variable-tempo-windowing` first;
  masking builds on `BeatSampleMap` + `SectionMetrics`.

## 6. NFRs

- **Performance.** Cost is O(pairs × frames × bands) per section =
  O(stems² × section_frames × ~24). A 12-stem song with 6 sections at ~11 ms hop
  must complete in seconds, not minutes. Bound it: mono-sum (not per-channel),
  pair-prune via energy gate (skip a pair if either stem is silent in the
  section), and the optional clip-schedule prune. Measure on a synthetic
  12-stem fixture; set a budget (target < 10 s for a 4-minute song).
- **Determinism.** Same stems → same report (no RNG; fixed STFT params).
- **License.** numpy / scipy / librosa only — all MIT/BSD/ISC, already deps. No
  new dependency (the spike's deliberate constraint).
- **Honest confidence.** A masked fraction is a *model* output, not ground
  truth; the report wording must not over-claim (it flags *likely* masking, not
  "this is inaudible"). Pairs below the reporting floor are omitted, not
  asserted absent.

## 7. Test strategy — the synthetic corpus IS the spec

There is no labeled masking ground truth for real music, so correctness is
*defined* by constructed fixtures (extends `tests/unit/audio/fixtures.py`):

- **Clear mask**: loud broadband/low stem A + quiet stem B in the same Bark
  region, co-timed → high A→B masked fraction in that band; low B→A.
- **No frequency overlap**: A in low band, B in air band → ~0 both directions.
- **No time overlap**: A in first half, B in second half of the section → ~0.
- **Partial**: B masked only in part of the section → mid fraction.
- **Self/identical**: feeding a stem against itself → degenerate guard.
- **Energy gate**: a silent stem in the section → excluded, no divide-by-zero.
- **Determinism**: same input twice → identical output.
- **Perf**: 12-stem fixture completes within budget.

Property-style where natural (hypothesis): masked_fraction ∈ [0,1]; a louder
masker never *decreases* the maskee's masked fraction.

## 8. Risks & open questions (resolve in Chunk 1 prototype)

1. **Calibration.** Spreading-function slopes + masking offset + the "non-
   trivial energy" gate are parameters; pick defaults from literature, then tune
   against the corpus so the clear-mask fixture reads high and the no-overlap
   fixture reads ~0. **This is why Chunk 1 is a de-risking prototype, not the
   full build.**
2. **False positives.** Two stems sharing a band ≠ audible masking. The offset +
   energy gate + reporting floor exist to suppress these; validate the no-
   overlap and partial fixtures don't over-report.
3. **Mono-sum vs stereo.** Mono-sum can hide masking that panning resolves.
   MVP mono-sums (standard); note the limitation; stereo-aware is a follow-on.
4. **Declared-vs-rendered tempo** (inherited): windowing trusts the tempo map;
   see `BeatSampleMap` caveat. Constant-tempo songs unaffected.
5. **Perf at scale.** If O(stems²) is too slow, the clip-schedule prune moves
   from optional to required — measure before deciding.

## 9. Decision log

- **Spectral (Bark/spreading) masking first, onset-masking deferred** — the
  spectral model is the general case and the spike's named differentiator; onset
  masking is a narrower heuristic.
- **DB-agnostic `masking.py` + handler threading** — mirrors the proven
  `attribution` / `reverb` / sections pattern; keeps synthetic-fixture testing.
- **Synthetic corpus defines correctness** — no real ground truth exists; this
  is the spike's stated validation path ("+ a synthetic test corpus to validate").
- **No clip-schedule DB read for MVP correctness** — the windowed audio already
  encodes co-play; the schedule is a perf prune, deferred.
