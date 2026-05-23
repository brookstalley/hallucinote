# Research Spike — Audio Analysis for Mix Verification

**Status:** research; direction agreed in conversation; no code yet.
**Goal:** figure out how Hallucinote can play a mix and answer questions like
*is this muddy?*, *is the reverb on the snare doing what I asked?*, *are the
track volumes balanced?*, *is the master clipping and why?*
**Audience constraint (agreed):** Hallucinote users will have **Live Suite**.
M4L is assumed available.
**Date:** 2026-05-23

---

## TL;DR

1. **Audio extraction:** one M4L device per track (and on returns + master)
   does double duty — emits realtime features over OSC *and* writes per-stem
   WAV files to disk via `sfrecord~` during the same playback pass. No UI
   automation, no virtual audio driver, no macOS Accessibility permission.
2. **Analysis stack:** `pyloudnorm` + `librosa` + `numpy/scipy` +
   `pyroomacoustics.experimental.rt60` + `soundfile`. All MIT/BSD/ISC. No
   PyTorch, no AGPL. ~600 LOC weekend MVP.
3. **Differentiator:** Hallucinote knows track role, section boundaries, send
   wiring, and has dry+wet pairs naturally available via send routing. That
   converts several open research problems (reverb verification, role-aware
   loudness balance, section-scoped masking, master-bus contribution
   attribution) into *regression-test-shaped* measurements. **No commercial
   tool can ask these questions** because they don't have the score.
4. **Reserved surface already exists:** `docs/v11-requirements.md:206` names
   `ableton_render` and `ableton_analysis` as planned-but-deferred MCP tools.
   With `sfrecord~` they collapse to the same plumbing — one playback pass
   renders and analyzes.
5. **Master-bus diagnosis is in scope; auto-fix is out.** We propose
   ranked mutations with predicted metric deltas; the LLM/user chooses;
   the mutator applies; re-render verifies. Every change is auditable.
6. **Don't chase end-to-end neural mixing.** State of the art is "still far
   from professional engineers." The moat is *verification of declared
   intent*, not replacing the engineer's choices.

---

## 1. Getting audio out of Ableton

### Decision: M4L `sfrecord~` unified device

One `HallucinoteAnalyzer.amxd` per track + returns + master, doing two
things at audio rate inside Live:

- **Feature stream** → OSC over UDP to a Python sidecar (LUFS-M, 1/3-octave
  band power, spectral centroid, true peak) for realtime mix-coaching.
- **Sample capture** → `sfrecord~` writes that track's audio to a
  Hallucinote-controlled WAV path during playback for offline analysis.

One playback pass produces both. Realtime only (no faster-than-realtime),
but in practice we're playing the arrangement anyway to capture features.

### Options considered

| Path | Verdict | Why |
|---|---|---|
| LOM `output_meter_*` | Rejected | Smoothed peak only; can't resolve frequency. UI-visibility-gated. Significant GUI load. |
| **M4L `sfrecord~` + OSC** | **Chosen** | Same device does features + samples; in-API control; zero UI automation; PDC keeps dry+wet aligned for deconvolution. |
| M4L OSC features only + PyAutoGUI export | Rejected (was prior recommendation) | UI brittleness, macOS Accessibility permission grant required, separate code paths for features and samples. |
| BlackHole 16ch + per-track External Out | Rejected | Virtual driver install, per-song routing setup, no advantage over `sfrecord~` once M4L is given. |
| BlackHole 2ch + solo-loop capture | Rejected | N× realtime, breaks reverb verification (each track is a separate non-deterministic playthrough). |
| Live-native Resampling tracks | Reserve as M4L-free fallback | Works without M4L but mutates song state (temp tracks, undo pollution, project-folder writes). Kept in mind if the Suite assumption ever changes. |
| Bounce-in-Place via Live API | Dead end | LOM exposes `is_frozen` read-only; no freeze/flatten verb. |

### Why `sfrecord~` wins

- **No song-state mutation.** Writes to a Hallucinote-controlled path
  outside the project. No temp tracks, no recorded session clips, no
  undo-history pollution.
- **The `.amxd` is required anyway.** Realtime feature streaming has no
  Live-API path — features must come from inside the audio graph, which is
  M4L either way. Adding `sfrecord~` to a device we're already shipping is
  incremental, not a new component.
- **Unified surface.** `ableton_render` and `ableton_analysis` collapse to
  the same plumbing.
- **Per-track config is parameter writes.** Each `.amxd` instance exposes
  `record_arm` (bool) and `output_path` (string); the Remote Script sets
  these via the existing socket. No track creation, no input routing
  matrix, no folder-layout assumptions.
- **PDC handles alignment.** Live's plugin delay compensation aligns each
  track's recorded file at the master bus, so dry+wet pairs are
  sample-aligned for reverb deconvolution.

### Architecture sketch

```
Ableton Live
├── Remote Script (existing) ──TCP──> MCP server ──> LLM agent
├── HallucinoteAnalyzer.amxd on every track + returns + master
│         ├── OSC features over UDP:11001 ──> Python sidecar (realtime)
│         └── sfrecord~ writes WAV ──> captures/<timestamp>/<track>.wav
│
└── (nothing else needed — no virtual driver, no UI automation)
```

### Open questions a prototype answers

- Sustainable OSC frame rate for ~12-track sessions.
- The right realtime feature set (proposal: LUFS-M, LUFS-S, true peak, 1/3-octave bands 20–20k, spectral centroid, spectral flatness).
- `sfrecord~` start/stop latency relative to transport — does the Live transport tick arrive at every device with the same phase, or do we need a "pre-roll" handshake.
- Whether the OSC sidecar lives as a thread inside the MCP server or as a child process (probably child process — UDP receiver doesn't share state with the TCP MCP loop).

---

## 2. Ergonomics, install, and state management

### Install (extends `ableton-mcp-install`)

Fully automatic:

- Copy `HallucinoteAnalyzer.amxd` to `~/Music/Ableton/User Library/Presets/Audio Effects/Max Audio Effect/` — same shape as the Remote Script copy that skill already does.
- Probe for M4L runtime; if missing, fail loud with a clear "you need Live Suite" message rather than silently degrading.

User action required:

- The existing one-time Ableton Preferences click for the Remote Script (unchanged).
- **No new permissions.** No PyAutoGUI, no virtual audio driver, no macOS Accessibility grant.

### Per-song wiring (silent auto-load)

The analyzer is plumbing, not creative content — it loads silently:

- `/song-new` adds the analyzer last in chain on every track + return + master it creates.
- `/track-new-with-instrument`, `/return-new` add the analyzer to new tracks they create.
- Pre-existing songs: the first analysis request triggers an idempotent "ensure analyzer on every track + return + master" sweep. Probes each device chain; loads the analyzer where missing. Silent.
- The analyzer appears in `/song-snapshot`'s captured state. Intentional — it's part of the song's runtime configuration, not a transient overlay.

### File tracking and gitignore

Per-song folder additions:

```
songs/<slug>/
├── captures/<iso-timestamp>/           ← gitignored (heavy)
│   ├── master.wav
│   ├── track-01-kick.wav
│   ├── track-02-snare.wav
│   ├── return-01-reverb.wav
│   └── manifest.json                   ← capture metadata: DB seq number,
│                                          declared-intent snapshot, sample rate,
│                                          analyzer version
└── analysis/<iso-timestamp>.json       ← checked in (small, valuable)
```

`.gitignore` additions:

```
songs/*/captures/
.hallucinote/stems/      # if we use a global staging dir
*.amxd~                  # Max backup files
```

Checked in:

- `analysis/<timestamp>.json` (MixReport — typically <50 KB)
- `HallucinoteAnalyzer.amxd` itself (in `hallucinote_mcp/src/hallucinote_mcp/m4l/` or similar)
- Any reference-track metric tables (computed once, reused across songs)

**Take retention.** Stems are ~165 MB per song per take at 48k/32f stereo per stem with ~12 tracks. Recommend a local rolling window (keep the most recent N captures, configurable) plus an explicit "pin this take" mechanism for reference points. Analysis JSONs are cheap; keep them all — the historical trail of MixReports *is* the audit log of mix evolution.

### Take comparison and A/B verification

The intent-aware angle pays off here. Every capture is tagged with the DB's audit-log sequence number at capture time (the DB already has the event log per the state-store / event-store architecture). Diffs become first-class:

- *"Did making the bass less muddy work?"* — diff MixReport at `seq=4823` vs `seq=4824`; the mutator events between them are the change.
- *"Compared to my reference track?"* — load reference, run the same metrics, diff.
- *"Did the LLM's chorus suggestions improve loudness consistency?"* — diff before/after the chorus-tweak event range.

MixReport schema includes a `compare_to` field that points to a baseline (previous take, named reference, or genre target). The `compare_to` resolver loads the baseline metrics and emits per-metric deltas with significance flags (e.g., "low-mid ratio went from 0.31 → 0.24, ∆ -0.07 — meaningful improvement; integrated LUFS went from -10.4 → -10.5, ∆ -0.1 — noise"). No human listening test needed for the *measurable* questions.

Worth noting what A/B testing does **not** mean here:
- We're not running user studies on randomized mix variants.
- We're not training a model on preference data.
- We *are* providing structured before/after metric diffs so the LLM or user can verify a proposed change actually did what it predicted.

---

## 3. Analysis techniques (offline-on-stems)

### Library stack (MIT/BSD/ISC only)

```
soundfile        — stem IO (NOT scipy.io.wavfile — broken on float32 edges)
pyloudnorm       — BS.1770-4 / EBU R128 (integrated, short-term, momentary, LRA)
numpy/scipy      — FFT, filtering, true-peak oversample, autocorrelation
librosa 0.11     — STFT, spectral_centroid/flatness/rolloff, onset
pyroomacoustics  — pull just .experimental.rt60.measure_rt60 (Schroeder)
```

Deliberately excluded: **essentia** (AGPL — contaminates downstream),
**aubio** (dormant, GPL), **madmom** (NumPy-2 incompat, inactive),
**spleeter** (dead since TF1.x), **demucs** (deferred until a stemless-input
use case shows up; PyTorch is heavy and lazy-importable if needed).

### Problem-by-problem map

**Muddiness.** STFT → integrate to named bands (sub 20–60, low 60–200, low-mid 200–500, mid 500–2k, high-mid 2k–6k, air 6k+). Diagnostic ratio: low-mid / total RMS; > 0.22–0.25 on a full mix is the standard "muddy" flag. Add spectral centroid (< 1.5 kHz on full-range = dark) and spectral flatness (high flatness in low-mid = too many instruments competing).

**Loudness / balance.** `pyloudnorm` per stem and per master. True peak *not* in pyloudnorm — 15 lines: 4× `scipy.signal.resample_poly` then `np.max(np.abs(...))`. PSR/PLR = peak − integrated. Stem-level LUFS targets within a mix are *not standardized in literature* — we need our own table per genre, derived from a small internal reference corpus.

**Reverb verification (killer feature).** Hallucinote knows the send wiring, so we have both dry and wet stems for free. IR by Wiener-regularized deconvolution: `IR(ω) = WET·conj(DRY) / (|DRY|² + ε)`. RT60 from the IR via `pyroomacoustics.experimental.rt60.measure_rt60`. Compare to declared decay-time intent in the DB. **Blind RT60 estimation is hard; this isn't blind — it's regression testing.**

**Delay verification.** `scipy.signal.correlate(wet, dry, mode='full')`; peak beyond zero lag = delay time. Successive autocorrelation peak ratio in dB = feedback level. Compare to declared intent.

**Masking (custom DSP).** No mature Python lib does iZotope-style inter-track masking. Build it: STFT-align stems, Bark-band power, Schroeder spreading function, per-tile masking threshold, count masked-tile ratio per stem-pair. **Section-scoped using the DB's clip schedule** — only analyze pairs that play simultaneously in a given arrangement window. ~1–2 weeks + a synthetic test corpus to validate.

**Transient / onset.** `librosa.onset.onset_strength`. "Kick buried by bass" reduces to: kick onsets on the kick stem → ±20 ms window on the bass 60–120 Hz band → if RMS at kick-onset is within 3 dB of non-onset RMS, kick is masked.

**Stereo image.** Pure NumPy mid/side. Correlation < 0.3 = mono compatibility risk.

### Realtime vs offline split

| Question | Realtime (OSC) | Offline (rendered stems) |
|---|---|---|
| Muddiness band ratios | ✓ | ✓ |
| LUFS momentary / short-term | ✓ | ✓ |
| LUFS integrated, LRA | — | ✓ (needs full track) |
| True peak | ✓ | ✓ |
| Stereo correlation | ✓ | ✓ |
| Reverb RT60 from IR | — | ✓ (needs tail) |
| Send/return deconvolution | — | ✓ (needs dry+wet pair) |
| Section-scoped masking | — | ✓ (needs multi-stem alignment) |
| Delay autocorrelation | — | ✓ |
| Master-bus contribution attribution | — | ✓ (needs synchronized stems + master) |

---

## 4. State of the art

Three tiers:

- **Commercial (iZotope, Sonible, LANDR, RoEx, Gullfoss)** — same handful of techniques (reference-curve EQ matching, masking detection via psychoacoustic models, equal-loudness level balancing, ML "what instrument" classifiers driving a known DSP chain). **All are blind to the score.**
- **Academic (Queen Mary's De Man / Reiss / Stables, Sony's Martínez-Ramírez)** — moved from rule-based knowledge engineering to differentiable mixing consoles and end-to-end neural mixing. Honest evaluations: "still far from professional engineers."
- **Foundation (BS.1770, RT60 estimators, source separation)** — commodity-mature.

### What's solved vs. what's open

| Problem | Status |
|---|---|
| Loudness measurement (BS.1770) | ✅ Solved |
| Per-stem balance | ✅ Solved |
| Tonal-balance reference curves | ✅ Solved |
| Masking detection | 🟡 Algorithms known; no Python library; we build it |
| Reverb RT60 (blind) | 🟡 Speech-tuned; noisy on dense music |
| **Reverb verification with dry+wet pairs** | ✅ **Solved (and unusually clean for us)** |
| Source separation | ✅ Solved (HT-Demucs v4) |
| **Master-bus diagnosis with stems + master** | ✅ Solvable (see §6) |
| "Mix sounds bad, why" (single answer) | ❌ Open — don't promise diagnosis |
| Drum punch quantification | ❌ Open |
| End-to-end neural mixing | ❌ Not professional-grade |

### Intent-aware angle (Hallucinote's moat)

Knowing the score collapses inference into measurement. Examples:

- "Verify the snare reverb produced ~30% wet at 1.2 s decay" — already have dry, target, and wet. Compute RT60 + wet/dry ratio. Regression test.
- "Bass and kick mask in 60-100 Hz during the verse" — window analysis to verse bars using clip schedule. Commercial tools can't do this.
- "Lead vocal should be focal but it's -6 dB below the rhythm guitar" — trivial when track role is a DB field.
- "Master clips at chorus drop" — attribute contribution per stem; the DB knows which stems play at that bar.

The pattern: **knowing the score collapses inference into measurement.** That's the differentiator.

---

## 5. Build order (highest leverage first)

1. **Per-track LUFS + true peak, section-windowed by arrangement.** Most common mix question, cheapest implementation.
2. **Send/return verification via wet/dry deconvolution + RT60.** Cheap, structural, no ML. Hallucinote-specific.
3. **Muddiness band ratios + tonal-balance reference per section.**
4. **Master-bus contribution attribution.** Per-band stem contribution at clipping moments. See §6.
5. **Section-scoped masking analyzer (custom DSP).** Bark-band masking from primitives. The custom piece worth writing.
6. **Dynamics rollup.** PSR per section, full-song PLR.

Deliberately deferred:
- End-to-end neural mixing (SOTA isn't professional-grade)
- Automatic EQ suggestion (consumer-tool territory; not our moat)
- Source separation (only needed for stemless reference inputs)
- Drum punch quantification (no reliable measure exists)

---

## 6. Worked example — master-bus clipping diagnosis & iterative fix

The case where every stem sounds clean but the master is clipping. Walkthrough:

### Diagnose

1. **Master record alongside stems.** Same `.amxd` instance placed on `master_track` writes the master output WAV. This is the ground truth for "what does the audience actually hear."
2. **True-peak detection.** 4× oversampled per BS.1770. Catches inter-sample peaks that pure-sample analysis misses — common cause of "stems look fine, master overshoots" surprise.
3. **Time-localize.** Returns `[(start_beat, end_beat, peak_dBTP, dominant_band)]` — concrete arrangement coordinates, not "the mix is loud."
4. **Per-band master analysis.** Where is the overflow — low-end pileup, mid-band stack, transient spike?
5. **Per-stem contribution attribution.** At each clipping moment, rank stems by RMS in the offending band during that window:
   > *"Master peaks +1.2 dBTP at bar 34; kick contributes 38% of 60-120 Hz energy, bass 31%, rhythm guitar 18%, others sub-5%."*

   This is only possible because we have synchronized per-stem captures + the master. Commercial maskers see only the mixed master.

6. **Distinguish broken from intentional.** The DB knows the master chain. If a limiter sits on master, "peak -0.1 dBTP" is the limiter doing its job, not a bug. The honest report is **peak + LUFS-I + PLR + presence of master limiter** — never a binary "clipping yes/no."

### Propose fixes (never auto-apply)

Hallucinote owns the mutator path. Every change is a DB mutation that re-pushes to Live. The analysis layer proposes candidates ranked by **impact-per-minimal-change**, each citing the metric it targets:

> 1. **Lower rhythm guitar 1.5 dB in chorus section** — single mixer write at the chorus cue. Predicted: master peak drops ~0.6 dB, low-mid ratio unchanged.
> 2. **Sidechain bass to kick at 60-120 Hz, 4:1, 8 ms attack** — insert sidechain on bass. Predicted: low-band peak drops ~2.3 dB, bass LUFS-S drops ~1.2 dB.
> 3. **Add -1 dB ceiling on master limiter** (or insert one if absent) — global. Predicted: hard true-peak ceiling at -1 dBTP, LUFS-I increases ~0.4 dB.
> 4. **EQ-carve bass at 80 Hz (-3 dB, Q=1.4)** — bass mixer-chain insert. Predicted: kick subjective punch up; bass LUFS-S drops ~0.8 dB.

Each candidate is a *predicted metric delta*, not a vibe assertion.

### Apply and verify

1. User (or LLM, per Hallucinote conventions) picks one or more.
2. Mutator applies → re-render → new MixReport.
3. Diff against the prior MixReport:
   > *"Master true-peak: +1.2 dBTP → -0.4 dBTP ✓ predicted ~-0.6 dB, observed -1.6 dB (better than expected — the sidechain compounded with the level cut). Integrated LUFS: -10.2 → -10.4 (held). Low-mid ratio: 0.24 → 0.23 (held). Result: clipping resolved without changing tonal balance."*

The loop is **measurable**. We don't claim "the mix sounds better"; we claim concrete metric deltas. Verification of intent, not opinion-asserting.

### What we deliberately don't do

- **Auto-apply fixes.** Black-box autofix breaks the DB's auditable-intent strength. Every mutation must be a deliberate choice with a predicted outcome.
- **Promise diagnosis of "sounds bad."** Quality-prediction models output a scalar, not a cause. We surface measurable conditions; the human (or LLM) interprets.
- **Treat the master like a stem.** Master-bus FX (limiter, glue compressor, EQ) are *intentional*; the DB knows they're there. A limiter pinning at -0.1 dBTP is not clipping — it's the limiter working as designed.

---

## 7. Honest gaps

- **"This mix sounds bad, why" is genuinely unsolved end-to-end.** Surface measurable conditions; don't promise a single diagnosis.
- **Reverb RT60 on dense material is noisy.** Mitigation: analyze the return-track audio directly (cleaner than blind master estimation).
- **Stem-level LUFS targets aren't standardized.** Build a small internal reference corpus per genre.
- **Loudness models disagree.** BS.1770 (broadcast) ≠ Glasberg-Moore (psychoacoustic) ≠ what an ear does in a busy verse. Use BS.1770 as a reproducible baseline.
- **No public dataset of intent-aware multitrack mixes.** Fine — we measure against declared targets, not train against preference data. Benchmarking needs a small internal eval set.
- **`sfrecord~` introduces a Max-patch artifact in the repo.** Visual-environment editing rather than text-editor diffs. Real but small ongoing cost; the patch is short and rarely changes once written.
- **Suite assumption is a constraint.** If the audience ever expands to Live Standard users, the Live-native Resampling-tracks fallback (§1 table) becomes the alternative — slower-path but still in-API, no external driver.

---

## 8. What this means for the v1.1 reserved tools

`docs/v11-requirements.md:206` reserves `ableton_render` and `ableton_analysis`. With `sfrecord~`, they collapse to shared plumbing:

- **`ableton_render`** → set `record_arm=true` and `output_path` on every analyzer device, set transport to arrangement start, play to end. Returns the `captures/<timestamp>/` directory of WAVs + a `manifest.json` (DB seq number, intent snapshot, sample rate, analyzer version).
- **`ableton_analysis`** has two flavors:
  - **Streaming** — exposes the OSC feature sidecar's ring as a resource. The LLM can subscribe to per-track LUFS-M / band ratios during playback.
  - **Post-render** — takes a `captures/` directory + song DB; returns a `MixReport` (per-stem + per-master metrics + intent-aware findings keyed to DB state + optional `compare_to` diff against a baseline).

Both let the LLM ask intent-aware questions like *"during the chorus, is the lead vocal LUFS-M median ≥ 3 dB above the rhythm guitar?"* and *"did the bass-cut at seq=4823 improve master headroom?"* without leaving the MCP boundary.

---

## 9. MVP definition

### Goal

Prove the end-to-end shape works on one known song. *Structural* validation — does the architecture hold together — not analytical sophistication. Success = the headline master-bus contribution attribution demo runs from a single MCP call, with three representative analyses backing it.

### In scope (must work end-to-end)

**Capture path**
- `HallucinoteAnalyzer.amxd` exposing two parameters: `record_arm` (bool) and `output_path` (string).
- `sfrecord~` writing 32-bit float stereo WAVs at Live's sample rate.
- OSC emitter sending three features (LUFS-M, true peak, low-mid band power) at ~30 Hz. *Minimal feature set on purpose — the OSC path is being plumbing-validated, not feature-completed.*
- Auto-load on every audio track + return + master, hooked into `/song-new` and triggered idempotently on first analysis request for pre-existing songs.

**Render action**
- One MCP action: `ableton_render` arms every analyzer, sets `output_path` per track to `songs/<slug>/captures/<timestamp>/<track-id>.wav`, starts transport at arrangement start, stops at arrangement end, disarms.
- Returns the captures directory path and a `manifest.json` (DB seq number, intent snapshot, sample rate, track-id ↔ filename map, analyzer version).

**Analysis pipeline — three analyses**
1. **Per-stem loudness.** LUFS-I + LUFS-S + true peak per stem and on the master.
2. **Master-bus contribution attribution.** True-peak overshoot detection on the master; for each overshoot, rank stems by RMS in the dominant band during that window.
3. **Reverb verification (one declared send).** For one snare→reverb-return pair with declared decay time in the DB, Wiener-deconvolve the IR, compute RT60, compare to intent.

**Output**
- `MixReport` JSON at `songs/<slug>/analysis/<timestamp>.json`. Schema: per-stem metrics, master metrics, top-3 master overshoots with attribution, reverb verification result, `findings` list keyed to DB intent (track role, send target). `compare_to` field present in schema but not implemented (skeleton only).

**MCP surface**
- `ableton_render` — capture stems.
- `ableton_analysis(action='analyze')` — run pipeline on a captures dir.
- `ableton_analysis(action='get_latest_report')` — read the JSON.

### Out of scope (explicit defer)

- Section-scoped masking analyzer (custom DSP — 1-2 weeks; post-MVP).
- Tonal-balance reference curves and genre reference corpus.
- Realtime streaming UI / live mix coaching (OSC features land but only basic three; no live dashboard).
- `compare_to` baseline diffing (field reserved; implementation deferred).
- Candidate mutation proposals (sidechain, EQ carves, limiter inserts) — MVP diagnoses, does not propose.
- Multi-song validation; pin/unpin for take retention; rolling-window cleanup.
- Source separation fallback for stemless input.
- Section-windowed analysis (e.g., chorus-only LUFS) — full-song aggregates only in MVP.

### Chunks

| Chunk | Focus | Deliverables |
|---|---|---|
| **A. Capture plumbing** (~2 days) | The `.amxd` and the render action work end-to-end | `.amxd` with `sfrecord~` + 3-feature OSC; auto-load wired into `/song-new` + idempotent sweep; `ableton_render` MCP action producing a captures dir + manifest |
| **B. Analysis + report** (~2 days) | The three analyses produce a `MixReport` | `analyze_mix(captures_dir, song_db)` function; `MixReport` schema; `ableton_analysis` MCP action; tests for loudness/attribution/RT60 against synthetic fixtures |
| **C. Worked-example demo** (~1 day) | The headline demo runs from a single LLM-driven session | A known song deliberately mixed to clip on master; demo transcript showing render → analyze → MixReport correctly identifies the dominant contributors |

Total: ~3–5 days. Each chunk gets a `/critic` review per the build plan; reflection at chunk boundaries.

### Success criteria

The MVP is done when **all** of these pass:

1. **Auto-load:** open a song with no analyzer present, call `ableton_analysis(action='analyze')`, sweep populates the analyzer on every track + return + master with no user intervention. Verified by probing the device chain post-sweep.
2. **PDC alignment:** capture a 4-bar arrangement with a kick stem and the master. Cross-correlate kick stem against master at a kick-onset window. Peak at zero lag ± 64 samples (≈1.3 ms at 48 k). This proves dry/wet pairs will deconvolve cleanly.
3. **Loudness fidelity:** per-stem LUFS-I matches Live's own meter readout within ±0.2 LU on a known reference stem (synthetic -23 LUFS pink noise round-trip).
4. **Master-bus attribution correctness:** on a deliberately-overdriven test song (boost kick + bass +6 dB in the chorus), MixReport flags chorus bars, lists kick + bass as top-2 contributors with combined attribution >60% in the 60-200 Hz band.
5. **Reverb verification correctness:** load a known IR with declared RT60 = 1.2 s; measured RT60 from Wiener-deconvolved dry/wet pair lands within ±0.15 s. (Tested against a synthetic dry impulse + known IR before testing in-song.)
6. **Test suite:** every capability has a pytest exercising it against synthetic fixtures. Suite runs in <30 s. All pass.
7. **Critic review on each chunk:** no blocking findings outstanding.

### Demo script

The "did it work" moment, as a single LLM-driven session:

```
> /song-pick <demo-song>
> Please render the current arrangement and analyze the mix.

LLM calls: ableton_render() → captures/2026-05-23T14:30:00/
LLM calls: ableton_analysis(action='analyze', captures_dir=...)
        → analysis/2026-05-23T14:30:00.json

> Why is the master clipping in the chorus?

LLM reads the MixReport, surfaces:
  "Master overshoots +1.4 dBTP between bar 33-40 (chorus 1).
   Dominant band: 60-200 Hz.
   Contributors: kick 41%, bass 33%, rhythm guitar 14%.
   The kick+bass low-end stack is the cause; the reverb send on snare
   verified at RT60 1.18 s (declared 1.2 s, within tolerance — not
   the cause)."
```

That MixReport — concrete bars, named stems, percentage attribution, *and* an exonerated suspect — is the artifact no commercial tool can produce.

### Deferred-from-MVP roadmap

Order is suggestive, not committed:

1. **Section-windowed analysis** — same metrics scoped to chorus / verse / bridge using clip-schedule. Likely the highest-impact next step.
2. **Section-scoped masking analyzer** (custom DSP). The custom piece worth writing; differentiator vs. iZotope.
3. **`compare_to` baseline diffs.** Take-over-take comparison keyed to DB seq numbers. Enables the A/B verification workflow described in §2.
4. **Candidate mutation proposals.** The "fix" side of §6 — ranked mutations with predicted metric deltas. Requires a small library of mutation templates (sidechain insert, EQ carve, mixer-level adjust).
5. **Tonal balance reference curves** + small internal reference corpus per genre.
6. **Full realtime feature set** + streaming dashboard (LUFS-M, all bands, centroid, flatness — useful for live mix coaching).
7. **Take retention policy** (rolling window, pin-this-take mechanism).
8. **Source separation fallback** (lazy-import demucs) for analyzing imported reference tracks without stems.
