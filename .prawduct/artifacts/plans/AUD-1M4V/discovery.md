# AUD-1M4V — Audio as First-Class Material: Discovery & Requirements

**Status:** discovery complete 2026-06-10. This is the artifact the umbrella's
verifiable signal demands: requirements (producer-led), LOM probe evidence, and the
staged plan across children. Children carry `refs:` here.

**Method.** Requirements were derived from expert practice first — what world-class
producers, mix engineers, and mastering engineers consider essential — then each
requirement was mapped to a verified mechanism. The LOM constrains *mechanisms*,
never *scope* (user direction; `feedback_tools_are_conveniences_not_limits`).

**Research corpus** (raw results; LINK, don't restate):

- `docs/research/audio-first-class/producer-practice.md` (+ raw
  `producer-practice-deep-research.json`) — adversarially verified practice (12
  surviving findings; mastering produced none and was re-researched separately)
- `docs/research/audio-first-class/mastering-practice.md` — platform/standards/named-
  engineer sourced mastering norms
- `docs/research/audio-first-class/lom-audio-clip-surface.md` +
  `lom-recording-automation.md` — LOM research passes
- `docs/research/audio-first-class/lom-probe-results.md` (+ raw `.jsonl`, driver) —
  **empirical Live 12.4.1 verdicts; supersede the research passes where they differ**

## User locks (2026-06-10)

1. **In-Live recording first** for vocal ingest; file-import is the secondary entry.
2. **Master/group automation is a must-have early** — right after the audio-clip DB model.
3. **Warp depth: minimal place-and-conform in wave 1**; warp-marker DB modeling later.
4. **Probe tool is permanent** (shipped: `ableton_probe`, chunk 01).
5. **Producer-led requirements** — capabilities framed as what the music needs.

## Requirements

Grouped by workflow stage. Each carries its source (research file) and mechanism
(probe verdict). REQ-IDs are referenced by the staged plan below.

### R1. Recorded performance (vocals and any audio take)

- **R1.1 Multi-take recording with bounded, curated take sets.** Comping is the
  near-universal pro vocal workflow: ~4–8 takes, tracked section-by-section, edits
  placed in the singer's silences (producer-practice #1). *Mechanism:* take lanes +
  scripted recording + `duplicate_clip_to_arrangement` comping substitute — all
  probe-CONFIRMED. Comp **selection** stays human/agent-directed curation; the system
  stages takes and executes the chosen comp, it never auto-comps.
- **R1.2 Record against the click end-to-end** (lock 1): verify input routing →
  teach-on-invalid (arm silently no-ops with no input device — probe 5b) → arm →
  metronome → `fire(record_length=beats)` → poll → ingest `file_path` (valid during
  recording — probe 5). Count-in is LOM-read-only; the workflow reads it and tells the
  performer what Live will do, it cannot set it.
- **R1.3 Ingest = modeled + analyzable.** A recorded/imported clip lands in the DB
  (file ref + placement) and is readable by the existing analysis pipeline
  (`src/hallucinote/audio/`). Pitch-extraction-to-MIDI is a separate later axis.
  `[ASSUMPTION: held from build plan | HIGH impact | user can veto]`
- **R1.4 Timing/tuning edits preserve performance.** Cut-and-slide before time-stretch
  (stretch smears vocal formants); tuning is selective per-note, never blanket;
  deliberate hard-tune is an aesthetic mode, not correction (producer-practice #2, #3).
  These are *guardrails for the agent's editing behavior*, not v1 build items.

### R2. Audio as compositional material (sampling)

- **R2.1 Place any audio file** in session or arrangement — one call each, probe-
  CONFIRMED (`create_audio_clip` on ClipSlot / Track / TakeLane).
- **R2.2 Conform to the song** (lock 3): warp on/off + mode matched to material
  (Beats / Complex Pro / Re-Pitch — algorithm choice is craft, producer-practice),
  gain, pitch_coarse/fine, start/end markers. Warp-marker-level editing later; the
  write API exists (RS needs `Live`-module-constructed `WarpMarker` objects —
  probe 8 — a handler detail, not a ceiling).
- **R2.3 Resampling as committed material**: record the master (or any track) onto an
  audio track via Resampling routing — probe-CONFIRMED 5c. Destructive commit is
  creative discipline (producer-practice), and it requires zero extra mechanism beyond
  R1.2's recording path.

### R3. Automation as production craft

- **R3.1 Mixer/send/device envelopes on audio-track session clips** — the moment audio
  clips exist in the DB, the existing envelope family covers audio tracks unchanged
  (probe 3: end-to-end CONFIRMED on a real audio clip). Volume rides, send throws,
  filter moves: same authored-envelope model as MIDI tracks today.
- **R3.2 Performed automation on master / group / return tracks** (lock 2). Arrangement
  clips cannot host envelopes (probe 2, definitive) and arrangement automation lanes
  have no LOM write surface — the verified mechanism is **realtime automation
  recording**: `session_automation_record` + `record_mode` + `begin_gesture` →
  scripted value ramp during playback → `end_gesture` (probes 4/4b: master + return
  CONFIRMED, playback-verified; groups share the shape). This is a NEW mechanism
  class, distinct from breakpoint envelopes:
  - *write-only* (no LOM read of arrangement automation) — verification via
    `automation_state` (0/1/2), playback observation, and `.als` XML dump (gzipped
    XML, format documented — `lom-recording-automation.md` Topic B5);
  - *realtime* — a gesture costs wall-clock proportional to its length;
  - *async transport state* — `record_mode` applies ~300 ms after the set (probe 10);
    poll, never trust same-call read-back.
  Master-bus filter sweeps are established electronic transition craft
  (producer-practice #verified) — this mechanism is what makes them authorable.
- **R3.3 Layered level control doctrine** (producer-practice): clip gain → moderate
  compression → rides. Clip gain is R2.2; rides are R3.1/R3.2; the doctrine itself is
  agent guidance (mix-intent vocabulary), not new plumbing.

### R4. Mix architecture

- **R4.1 Sub-bus (group) routing stays the first-class answer** for collective moves —
  groups preserve internal balances (producer-practice). R3.2 extends automation TO
  groups; nothing replaces sub-bus routing as structure. (Group track *creation* has no
  LOM path — groups remain template/operator-side, consistent with TPL-2D8K.)
- **R4.2 Master chain via template** — TPL-2D8K's `.als`-template answer stands;
  this umbrella references it, never duplicates it.

### R5. Release-readiness verification (mastering)

The analysis pipeline already measures BS.1770 LUFS-I/S/M + true peak per stem and
master (`src/hallucinote/audio/loudness.py`). Mastering research
(`mastering-practice.md`) adds these verification requirements:

- **R5.1 Genre-declared loudness, never a hardcoded target.** Platforms normalize
  (-14-ish) but pros reject "-14 as a goal"; the song declares its intended loudness
  presentation and the analyzer verifies against *that* — the same
  declared-profile-over-universal shape as the melody lens
  (`project_melody_model_meta_answer`).
- **R5.2 True-peak ceiling as a declarable check**: -1.0 dBTP default, -2.0 when
  hotter than -14 LUFS (Spotify/AES TD1008).
- **R5.3 Mono-fold verification** + mono bass below ~100–150 Hz for club-destined
  songs (declared, per-song).
- **R5.4 Limiter restraint is measurable** — final-limiter gain-reduction depth
  exposed (>~4 dB average GR = pumping territory, a checkable fact).
- **R5.5 Deliverable staging**: pre-master bounce carries headroom + no brickwall
  limiting; mastered render is a separate artifact; dither once / iff bit-depth drops
  / last. Heads/tails inspection.
- Album-aware loudness (multi-track releases) noted for the event-store era; out of
  this umbrella's scope.

### Never-dos (agent guardrails distilled from research)

No blanket pitch-correction on leads; no time-stretch-first timing fixes on vocals;
no widening the low end / no excessive stereo width without a mono check; never
master to a hardcoded LUFS number; never double-limit; dither exactly once. These
land in the mix/production skill guidance, not as code.

## Staged plan (the children, re-scoped by evidence)

Order respects lock 2 (master automation early) and the dependency spine
(DB model → placement → envelopes → performed automation → recording workflow).

| Stage | Item | Re-scope from evidence |
|---|---|---|
| 0 | **CLP-AUD1** — audio-clip DB model | Foundation, unchanged in spirit; wave-1 fields per lock 3: kind discriminator, file ref, gain, pitch, warping+mode, start/end markers. Warp markers deferred (R2.2). |
| 1 | **CLP-AUD2** — audio clip placement | **REDEFINED:** browser-load workaround is obsolete (probe 1); becomes thin `create_audio_clip` handlers (session + arrangement + take lane) + push/pull surface for CLP-AUD1 rows. |
| 2 | **ENV-8H1T** — envelopes on audio tracks | **REDUCES to a routing change:** existing session-clip envelope family works on audio clips (probe 3). Mostly deleting the refusal at `sync/push/envelopes.py:193` + tests. |
| 3 | **NEW: performed automation** (master/group/return) | R3.2's mechanism: gesture-recorded scripted ramps + automation_state/.als verification. Needs a new backlog child (no existing ID covers it). Lock 2 places it immediately after stage 1. |
| 4 | **NEW: recording workflow** (vocal ingest) | R1.1–R1.3: routing verify/teach, arm, record_length takes, take-lane staging, comp execution, DB ingest. In-Live first (lock 1); file-import entry point falls out of stage 1 for free. |
| 5 | **R5 verification additions** | Incremental additions to the existing analyzer (genre-declared loudness check, mono-fold, limiter GR, deliverable staging). Stageable independently; gated on QLT-3D8R listening-day calibration discipline for any new coaching. |
| — | **ENV-3M7K** (auto-partition) | Unchanged; still the answer for song-spanning envelopes over per-section clips (MIX-3S7P's deferred DubDelay arc). |
| — | **ENV-4M2T** (return-side envelope clips) | **Partially superseded:** performed automation (stage 3) covers return mixer/send arcs without a return session-clip model. Keep open only for *clip-locked* return device envelopes; revisit after stage 3. |
| — | **AUD-6T2K** (source separation) | Unchanged; fallback for stemless reference analysis, not part of this spine. |

**Out of scope for the umbrella (explicit):** pitch-to-MIDI extraction from audio
(R1.3 assumption); auto-comping (R1.1 — curation stays directed); group-track
creation via LOM (impossible; template-side); album-aware loudness (event-store era).

## Decision record

- **Performed automation is a new mechanism class, not an envelope variant** —
  write-only, realtime, async-transport; verified by `automation_state` + playback +
  `.als` dump. Alternatives considered: (a) `.als` XML editing as the primary write
  path (rejected for v1: requires the set closed, breaks the live round-trip loop;
  retained as verification/fallback), (b) waiting for Ableton to expose arrangement
  automation (no signal through 12.4 — AbletonOSC #112/#205 still open).
- **CLP-AUD2's browser-load design is retired** on probe evidence; the backlog item is
  updated rather than a new one created (same need, simpler mechanism).
- **Comping is curation**: the system stages and executes; choosing the take is
  performance judgment (producer-practice #1; `feedback_great_art_not_software`).
