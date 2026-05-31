# Backlog — Hallucinote

<!--
Migrated 2026-05-29 from the legacy priority-band format (P0–P6) to the
structured `/backlog` v2 format (id + metadata bar + body). Migration was
non-interactive: effort/impact were inferred from the original priority band
(P0/P1 → impact M/L, low effort; P3 → impact S, effort S; etc.) and from each
entry's "Sized:" note where present. Original bodies are preserved verbatim,
including the "Verifiable signal:" probes the prior format required.

Prior-format discipline that still applies (load-bearing):

1. **Close-in-the-same-PR.** When a PR ships work resolving a backlog item,
   set its status to `shipped` with `closed-by:` in the SAME PR. The git log is
   the audit trail. Critic + PR reviewer flag PRs that ship work matching an
   open item without closing it.
2. **Verifiable signal required.** Every item names a probe a future scrub can
   run to confirm it's still pending — a file:line, a function to grep, a CLI
   to run, or a behavior to reproduce. Without it the item is unscrubable.
3. **Trust-but-verify on scrub.** A scrub re-reads code against each item, not
   just the item's text. Items with `added`/`reviewed` > 60 days are suspect.

Three canonical sections below: ## Open (pickable) · ## Promoted (in an active
build plan) · ## Archive (shipped/dropped, kept for search). Items move between
sections only via explicit `/backlog update` calls.
-->

## Open

- **[MIX-6K2P]** Track-mixer volume/pan should be dB-aware on the MCP surface (reuse `levels.py` calibration)
  `effort: S · impact: M · area: mcp-mixer · source: builder · added: 2026-05-30 · status: open`

  Surfaced during sun-zone-done mix work. `ableton_device(action='set_parameter')` already accepts `value_display='-3.5 dB'` and inverts it to the raw value, but `ableton_track(action='set_property', property='volume')` is raw-0..1-float only, and `ableton_track(action='info')` reports only the raw float (e.g. `0.65`), no dB. So any agent doing dB-native mix thinking (gain-staging, "trim drums 4 dB") must hand-apply Live's nonlinear fader curve. The calibration ALREADY EXISTS and is exact in [0.40, 1.00] as `dB = 40·(v − 0.85)` — `src/hallucinote/audio/levels.py` (`live_fader_db` / `live_fader_gain`), used by the analyzer for mix-level reconstruction. Fix: (a) `ableton_track set_property volume` accepts an optional `value_display` in dB (mirror device `set_parameter`), inverting via levels.py; (b) `ableton_track info` (and the snapshot capture) surface a `volume_db` alongside the raw float; same for pan where meaningful. Keep the DB store in Live's native normalized float (correct unit) — this is a surface-ergonomics fix only, not a data-model change. **Verifiable signal:** `ableton_track(action='set_property', property='volume', value_display='-8 dB')` resolves to v≈0.65; `ableton_track(action='info')` returns a `volume_db` field. **Sized:** small. (sun-zone-done mix session 2026-05-30)

- **[ARR-4V7P]** Vertical (inter-layer) harmonic constraint — the counterpoint near-miss
  `effort: M · impact: M · area: arrangement · source: review · added: 2026-05-30 · status: open · related: ARR-1H9C`

  Fugue/Bach is an instructive near-miss: the model's HORIZONTAL devices map beautifully (subject = motif, answer = transpose, stretto = overlapping motif references, augmentation/inversion = literal variation ops) — but the model is BLIND to the vertical constraint. Voices must form valid counterpoint when combined, and nothing represents or enforces consonance/dissonance BETWEEN layers. It scaffolds the entrances and gives zero help with the actual hard part. Per ruler/stamp a counterpoint GENERATOR is out (a stamp); the ruler-consistent move is a read-side vertical-interval / consonance ANALYSIS lens ("layers X and Y clash here — intended dissonance or error?"), the same shape as the masking analyzer. Representation of inter-layer harmonic constraint is tied to the harmony-axis decision (ARR-1H9C). **Verifiable signal:** a vertical-consonance analysis exists OR a decision-record says inter-layer correctness stays composer-owned at the note floor. **Sized:** medium. (arrangement-model counter-example review, 2026-05-30)

- **[ARR-3R8F]** Rhythm/feel collision as a first-class structural axis (the rhythm analog of ARR-1H9C)
  `effort: L · impact: M · area: arrangement · source: user · added: 2026-05-30 · status: open · related: ARR-1H9C`

  Raised by the user (2026-05-30, sun-zone-done): "rhythm is just as important in the world as harmony or melody." The harmony axis (ARR-1H9C) made tonal collision/resolution a recorded structural intent that the build realizes + a lens verifies. Feel/microtiming, by contrast, is per-generator-call only (deliberately, per `docs/song-authoring-conventions.md` — punk drums + lazy bluegrass guitar in one section is valid) — the arrangement model carries NO structural representation of a rhythmic *collision* or *resolution*. sun-zone-done needed exactly that (the development trades feel cell-by-cell mirroring its harmonic trade; the outro resolves into a new synthesized feel) and realized it via per-call feel + hand-recorded intent (`songs/sun-zone-done/decisions/07-rhythmic-collision-and-resolution.md`). The open question: is there a ruler-consistent first-class representation — e.g. a per-section / per-cell *feel intent* (drag / push / grid / swing) co-equal to energy + harmony that the build realizes and a read-side timing lens verifies (the rhythm analog of the harmony conformance lens, related to the cross-rhythm analyzer C8) — OR does feel correctly stay per-call with intent recorded in markdown? Grain is part of the decision (per-section? per-cell? per-part?). **Verifiable signal:** `arrangement-model.md` records a decision (substrate vs per-call+markdown) with rationale; if substrate, sections/cells can carry a feel-intent attribute. **Sized:** large. (sun-zone-done rhythmic-collision work, 2026-05-30)

- **[ARR-2B6K]** Arrangement-model honest boundaries — unmetered / non-musical-axis / texture-mass
  `effort: M · impact: S · area: arrangement · source: review · added: 2026-05-30 · status: open`

  Three known boundaries from the counter-example review, recorded so they're tracked rather than silently assumed (the model degrades to the raw note floor for all three). (a) **Unmetered / free-rhythm** (Gregorian chant, Indian alap, recitative, rubato ambient): the bar-centric scaffold is ill-fitting; a future time-based (seconds / free-pulse) authoring mode could help. (b) **Non-musical organizing axis** (film/game picture-sync, text/liturgy through-composed, and generative/aleatoric/interactive where the piece is a process/ruleset — Eno, Cage, adaptive scores): OUT OF SCOPE BY DESIGN — process-as-primitive was deliberately excluded (ruler/stamp); document, don't build, unless product scope changes. (c) **Texture-mass / spectral** (Ligeti, Xenakis): the unit is a mass, not a motif/note; a future cloud/mass authoring helper could help. All three already noted in `arrangement-model.md` "What is deliberately NOT modeled." **Verifiable signal:** revisit only when a real target song needs (a) or (c); (b) stays documented-out. **Sized:** medium if ever built. (arrangement-model counter-example review, 2026-05-30)

- **[ARR-8P5K]** Axis model — candidate neglected musical dimensions + possible refactor of "axes"
  `effort: L · impact: L · area: arrangement · source: user · added: 2026-05-30 · status: open · related: ARR-1H9C, ARR-3R8F, ARR-4V7P, ARR-2B6K`

  Umbrella design investigation (user + builder, 2026-05-30, sun-zone-done). Hallucinote models a few structural dimensions (form/recurrence, ENERGY, HARMONY [ARR-1H9C, shipped]); timbre is the separate instrument-chain subsystem. The microtiming "feels-quantized" finding raised the question: what OTHER dimensions are neglected, and is a flat list of *orthogonal* axes even the right mental model? Likely NOT — the dimensions COUPLE — so the deliverable is the minimal set of authored intents with the right coupling/derivation, **explicitly NOT 1000 axes**. Governed by ruler-not-stamp, one-source-of-truth (no "inconsistent triple"), *discovered-from-friction-not-speculative* (do NOT pre-build; let genres force each gap), and **BOTH-SIDES** — every dimension needs an AUTHORING surface (express the song's intent) AND a MEASUREMENT/ANALYSIS lens (determine whether the song is actually doing it). This is already the house pattern: harmony = `Progression` author + conformance-lint read; mix = per-section intent + masking analyzer; energy = authored curve + a read-side derivative-shape coaching lens. A dimension authored but unmeasured (or measured but un-authorable) is half-built.

  **Candidate dimensions + hypotheses:**
  - **PERFORMANCE** (microtiming + dynamics/velocity + tempo-expression + articulation) — the live one; a deep-research pass is in flight (workflow `wf_5d654e53-0b8`). HYPOTHESIS: not a sprawling per-note humanizer (a stamp) but an authored performance PROFILE (ruler) + deterministic STRUCTURED realization (correlated deviation, NOT random jitter — Keil's "participatory discrepancies") + a read-side "mechanical / human / sloppy" coaching lens (masking-analyzer shape). Decomposes into (a) an energy-COUPLED intensity component, (b) an energy-INDEPENDENT genre groove/style baseline (swing, drag, pocket), (c) local expression (phrase arcs). See ARR-3R8F (the rhythm-collision slice) + `songs/sun-zone-done/decisions/07`.
  - **ENERGY ↔ PERFORMANCE COUPLING (the refactor seed):** user insight — there is "score-based energy" (orchestration density / register / harmonic tension — already how the energy curve is built) AND "performance-based energy" (push / tighten / crescendo); a section building tension shows in BOTH. HYPOTHESIS: energy is the single authored intensity INTENT with TWO realization channels (compositional + performative), over a genre groove-baseline, with deliberate decoupling overrides (the convention-break is the template) — NOT two independent dials that can contradict. This is the likely "refactor": intent → realization-channels, rather than flat peer axes.
  - **METER / PULSE / METRIC-FEEL** — felt pulse distinct from time-signature AND tempo: half-time / double-time (the song's reggae-vs-metal feel at constant 180), swing subdivision, compound (6/8), hemiola, clave, metric modulation, and free/unmetered (already filed: ARR-2B6K boundary (a)). HYPOTHESIS: the next real axis after performance, sharing the TIME domain with it — swing likely lives INSIDE performance (microtiming) while the metric-feel LAYER (the pulse level the music is felt in) may be its own thin axis. The half-time→double-time gear-shift is already a first-class discontinuity in `arrangement-model.md`. Forced by the first swung-jazz / Latin-clave / chant song.
  - **TEXT / LYRIC / PROSODY / FLOW** — for vocal genres (rap, chant, Motown, art song) the word-rhythm / stress / rhyme / flow-against-grid is PRIMARY art, not decoration (rap flow IS the music; chant is text-governed). Today: placeholder melody + an intent annotation only. HYPOTHESIS: its own SUBSYSTEM (like sound-design / instrument-chains), not an arrangement axis. Forced by the first real rap or chant.

  **Sub-gaps already on the board (incomplete, not neglected):** voice-leading (harmony voices "dumb close-position"; → ARR-4V7P vertical lens); macro key-area / modulation narrative (per-section progressions + `harmonic_plan` exist; the song-level tonic→away→home arc is lightly modeled — untested since sun-zone-done stays in E).

  **DECIDED (2026-05-30, research-backed — deep-research pass, 24/25 claims confirmed on primary sources: Cancino-Chacón/Widmer 2018, KTH/Director Musices, Performance Worm, Hennig 2011 1/f, Iyer, Danielsen, Palmer):** the FRAMING is settled and recorded in `arrangement-model.md` "The dimension taxonomy". (1) Taxonomy = **structure intents** (form/energy/harmony, + meter-feel candidate) · **realization layers** (performance — DERIVED from the structure intents, NOT a peer axis) · **subsystems** (sound-design, + text/flow candidate) · the note floor. (2) Performance = the KTH **metaperformer** profile→realization pattern (a ruler): genre groove-baseline + energy/harmony coupling + deliberate overrides; realized as STRUCTURED 1/f-correlated deviation (NOT white noise), small / genre-calibrated; both-sides (symbolic lens + audio ground-truth). (3) swing ∈ performance; the metric grid ∈ meter-feel. (4) **metered-only scope** documented as a limitation-not-a-flaw (`arrangement-model.md` SCOPE BOUNDARY + `project-state.yaml` `scope.later` + ARR-2B6K); unmetered / free-time = future research. The verifiable signal is MET (the dimensions section exists, with rationale + citations).

  **Open follow-ups (implementation — friction-driven, do NOT pre-build):** (a) the performance READ-side — a symbolic deviation-structure / 1-f / flat-dynamics lens (generalize the by-hand `microtiming_check.py`) + extend `audio/timing.py` / `cross_rhythm.py` with the 1/f metric + perceived-onset; (b) the AUTHORING surface — a performance-profile object (the generators' `lazy` / `lag` / `push` defaults are proto-profiles); (c) let genres force meter-feel + text/flow + the unmetered time-base fork; (d) fold / relate ARR-3R8F into this once (a)/(b) land. **Sized:** large (design DONE; implement incrementally as genres force it). (sun-zone-done performance/axes design session, 2026-05-30)

- **[BLG-7K2Q]** Backlog accuracy structural enforcement — `product-hook backlog-stale-check` + Critic "closed-but-not-removed" goal
  `effort: S · impact: M · area: backlog-tooling · source: builder · added: 2026-05-21 · status: open`

  Both target files (`tools/product-hook`, `.prawduct/critic-review.md`) carry uncommitted v1.5 framework WIP introducing `/critic verify-resolutions` mode — landing this as a sibling would PR the framework work per memory `project_prawduct_framework_authorship`. **Two parts:** (a) `product-hook backlog-stale-check` subcommand — parses backlog entries, surfaces > 60-day candidates + diff-grep against recent PRs flags shipped-but-not-removed candidates; output rides the session briefing; (b) Critic / PR-reviewer goal extension — for cumulative reviews, grep diff for keywords matching open backlog headlines + named files/functions; flag PRs that ship work matching an entry without deleting it in the same diff. **Verifiable signal:** `python3 tools/product-hook backlog-stale-check` exists and exits 0; `.claude/skills/critic/SKILL.md` (or `.prawduct/critic-review.md`) contains a goal block naming "backlog closed-but-not-removed". **Sized:** small once unblocked. **Land after** v1.5 framework sync (verify-resolutions) ships, or coordinate with the user to bundle into that sync. (Arc 5 P0 deferral 2026-05-21)

- **[VEW-3M8F]** Derived-views drift: `regen-views` no longer errors but still emits nothing (and now errors post-merge on missing build-plan)
  `effort: M · impact: M · area: views · source: critic · added: 2026-05-19 · status: open`

  Refreshed 2026-05-22: `python3 tools/product-hook regen-views` now exits 0 (no `ModuleNotFoundError`), and `tools/lib/` exists. The source-of-truth side is healthy — tagged change-log entries (`chunks=...|status=...|release=...|scope=...`) land in `.prawduct/change-log.md` for every entry since 2026-05-20. The view-derivation side is still inert: `scope_rollups: {}` in `.prawduct/project-state.yaml` stays empty, and `.prawduct/release-notes.md` is never created. Likely a tag-parsing or write-side bug in the regen logic. Two paths: (a) fix the regen path (likely in the framework-WIP `tools/product-hook` — coordinate with the upstream sync); (b) flip `views_enabled: false` in `project-state.yaml` until the fix lands. **Verifiable signal:** `scope_rollups` block in `project-state.yaml` is non-empty AND `.prawduct/release-notes.md` exists after a `regen-views` run. (W10-B/C/D + W12-C/W15-D + W15-B Critic notes, 2026-05-19/20; refreshed 2026-05-22) **Update 2026-05-29 (v1.4.0 release):** `regen-views` now *errors* (`ERROR: build-plan not found`, exit 2) when run after a completed build-plan was deleted — but governance ("Completing Work") + `/pr merge` delete `build-plan.md` on merge, so the Status view input is legitimately gone at exactly the moment a release wants to regen release-notes. `plan_regen` is all-or-nothing: the missing build-plan blocks the release-notes + scope-rollup views too. Release proceeded with change-log.md as the canonical store (release tags flipped to `v1.4.0` by hand) + the git tag. Fix candidate: make `plan_regen` treat a missing build-plan as "no Status view to regen" (skip, don't raise) so release-notes/scope-rollups still derive post-merge.

- **[VEW-9QH4]** Change-log entries missing for post-v1.4.0 unreleased batch + no release-tag vocab for unreleased work
  `effort: S · impact: M · area: views · source: critic · added: 2026-05-29 · status: open · related: VEW-3M8F`

  Build-cycle step 10 calls for a tagged change-log entry when `views_enabled: true`, but C8 (#106), C8c (#108), and analysis-code-version (this PR) added none — partly because every existing tag uses a concrete *shipped* version (`release=v0.9.0 … v1.4.0`) and there's no `unreleased`/`next` convention, so post-release work can't be tagged without either pre-bumping (against `feedback_no_premature_version_bump`) or mislabeling as the shipped v1.4.0. Decide a convention (e.g. `release=unreleased`, flipped to the real version at release cut — mirrors how v1.4.0 tags were flipped by hand) and backfill the batch. Couples with the regen-views drift item above. **Verifiable signal:** the unreleased develop commits since v1.4.0 each have a `## ` change-log entry, and the tag vocab documents an unreleased-work value. (analysis-code-version PR reviewer note, 2026-05-29)

- **[ARR-5T1W]** Arrangement-VIEW state pull (loop region, follow mode, view zoom)
  `effort: M · impact: M · area: arrangement · source: reflection · added: 2026-05-17 · status: open`

  Distinct from arrangement-clip-placement pull (which M+1-3b shipped). `ableton_arrangement(action='info')` exposes the view state but there is no DB home for loop region or view zoom today; tempo/signature are better diffed against `tempo_map`/`time_signature_map` via dedicated probes. Needs an explicit decision: add DB columns for view state (probably on `ableton_sessions` — it's session-bound view state, not authored song data) or leave view state non-round-tripped per "DB is the score, not the rehearsal-room state." Filed for explicit decision, not silent drop. **Verifiable signal:** a `ableton_sessions` column for loop region exists OR a decision-record in `decisions/` says "view state intentionally not round-tripped." (reflection, M+1-3 re-plan 2026-05-17)

- **[DOC-2P6J]** W8-C framework-coupled wiring — session briefing + CLAUDE.md addendum for song context
  `effort: M · impact: M · area: framework-wiring · source: reflection · added: 2026-05-19 · status: open`

  The Wave 8 plan named two targets: (a) extend `tools/product-hook` so the session briefing surfaces in-scope song decisions + annotations; (b) add a CLAUDE.md addendum mirroring the existing `/learnings [topic]` guidance for song context. Both files are in the parked-upstream-framework set per memory `project_prawduct_framework_authorship` — adding hallucinote-specific behavior conflicts with the in-flight upstream sync. W8-C shipped only the SKILL.md guidance enhancement; the framework-coupled pieces are deferred. Then: (1) `product-hook` should detect "song in-scope" (any file touched in `songs/<slug>/`) and inject a `Song context:` block with the song's 5 most-recent markdown decisions + structural-fact annotations + `Q.get_annotations_for_song(..., kind='intent'|'structure')` from the W23-B annotations table; (2) CLAUDE.md should add a line: "Before non-trivial composition, run `/song-context [topic]` and read DB annotations via `ableton_annotation(action='list')`." **Verifiable signal:** session in a `songs/<slug>/` touch injects a `Song context:` block; CLAUDE.md mentions `ableton_annotation(action='list')`. (W8-C descope 2026-05-19; expanded for W23-B 2026-05-22)

- **[MSK-8R3D]** Masking level-reconstruction refinements (masking C3 follow-ons)
  `effort: M · impact: M · area: masking · source: critic · added: 2026-05-29 · status: open`

  (a) **Volume automation**: C3 applies only the STATIC fader gain; a stem that ducks under one section reads slightly hot — evaluate the per-section volume envelope. (b) **Attribution/loudness level-correction**: C3 corrects the masking input only; `band_attribution`/`master_bus_attribution`/per-stem loudness still run on pre-fader stems (same F1 property) — decide whether to correct them too (changes shipped metrics, so separate). (c) **>15.5 kHz analysis ceiling** (Critic NOTE): bins above the top Bark edge are dropped while the "air" label runs to ∞ — document or extend the table. (d) Reindex tombstone-prefix uses POSIX `/` (Windows edge; macOS-only today). **Sized:** small-medium. (masking 2026-05-29)

- **[AUD-4W7K]** `compare_to` baseline diffs for MixReports
  `effort: M · impact: M · area: audio-analysis · source: reflection · added: 2026-05-23 · status: open`

  Skeleton field reserved in audio-analysis MVP schema; implementation deferred. Diff two MixReports keyed to DB audit-log seq numbers, surface metric deltas with significance flags ("low-mid ratio went from 0.31 → 0.24, ∆ -0.07 — meaningful improvement"). Enables A/B verification workflow described in audio-analysis spike §2 (`.prawduct/artifacts/research-spike-audio-analysis.md`). **Verifiable signal:** `analyze_mix(..., compare_to=<seq>)` populates `MixReport.deltas` with per-metric ∆ values + significance flags. (spike §9 defer 2026-05-23)

- **[MIX-6D2N]** Candidate mutation proposals — the "fix" side of master-bus diagnosis
  `effort: L · impact: M · area: mix · source: reflection · added: 2026-05-23 · status: open`

  Audio-analysis MVP diagnoses; this proposes ranked mutations with predicted metric deltas ("Lower rhythm guitar 1.5 dB in chorus — predicted master peak drops ~0.6 dB"). Requires a mutation-template library (sidechain insert, EQ carve, mixer-level adjust, limiter ceiling) + a predictor estimating post-mutation metric. Each proposal must cite which DB intent it's verifying or improving. **Verifiable signal:** `MixReport.proposals: list[Proposal]` populated with named mutations + predicted deltas + DB-intent citations. (spike §9 defer 2026-05-23)

- **[DEV-1F9X]** W13-B follow-up: extract shared plugin-discriminator into a single module
  `effort: S · impact: M · area: device · source: critic · added: 2026-05-20 · status: open`

  Both `src/hallucinote/sync/compat.py:_PLUGIN_CLASSES` + `_is_plugin_class()` and `hallucinote_mcp/.../handlers/device.py:1236-1241` (`is_third_party_plugin`) implement the same logic (explicit set + `"Plugin" in class_name` substring). Lock-tests keep them consistent (`test_plugin_classes_lock_matches_mcp_side` + `test_classify_device_substring_branch_routes_to_third_party`) — sufficient short-term, but drift-prone long-term. Natural home: W11-A's `hallucinote-core` shared package. **Verifiable signal:** a `hallucinote-core` package exists; both compat.py and device.py import the discriminator from it. **Defer until** W11-A's extraction lands so the move happens once rather than twice. (v0.9.0 cumulative Critic note + PR reviewer note 3, 2026-05-20)

- **[SNG-7H4M]** Future sibling skill: `/song-import` — ingest an existing Ableton Live set into a new Hallucinote song dir
  `effort: L · impact: M · area: song-tooling · source: builder · added: 2026-05-20 · status: open`

  Sibling to `/song-new`. `/song-new` scaffolds from templates (no Live required); `/song-import` would capture an open Live set + pull notes / arrangement / envelopes into a fresh DB + generate a build.py thin wrapper. Today the agent can do this manually by chaining `tools.scaffold_song` + `tools/capture.py` + `/ableton-pull`, but `/ableton-pull` is built for state diffs on an existing DB, not first-ingest of clips/notes/arrangement. Needs a "pull first-time everything" path (gated on pull-side scope items below). Naming chosen to match the `<scope>-<action>` convention. **Verifiable signal:** `.claude/skills/song-import/` exists. (skills-replace-prompts refactor, 2026-05-20)

- **[KIT-3Q8B]** Cross-song shared drum-kit mappings (post-M1-C)
  `effort: M · impact: M · area: drum-kit · source: builder · added: 2026-05-20 · status: open`

  M1-C ships `drum_pad_mappings` scoped per-song (rows reference `devices.id`, which is per-song). The same Drum Rack `.adg` loaded on machine A and machine B has the same pad layout (chain names + MIDI notes are kit-intrinsic). Hoisting mappings into a shared layer keyed on `(preset_uri OR preset_query OR plugin_identity)` would let one capture run benefit every song using that kit. Aligns with memory `project_cross_song_reuse` (shared kits/grooves/templates). Non-trivial schema + ownership design (who owns the mapping when two captures disagree). **Verifiable signal:** `drum_pad_mappings` table has a shared/hoisted layer keyed on preset identity, not per-song device_id. **Sized:** medium. (M1-C scoping 2026-05-20)

- **[TMP-5K1R]** Per-scene tempo/signature as the supported workaround for the multi-bar tempo gap
  `effort: M · impact: M · area: tempo · source: reflection · added: 2026-05-19 · status: open · related: TMP-9X2D`

  Hallucinote DB stores `tempo_map` and `time_signature_map` keyed by `start_bar`. Live exposes per-scene tempo/sig (each session-view scene can override the global values when launched). A sync-side change could map "bar X starts a new section" → "create a scene with tempo Y at that bar boundary," giving users multi-bar tempo/sig in the supported architecture without the missing LOM envelope API. Scope: schema-level decision on scene-bar binding, planner emit logic in `plan_push_tempo_map` (use scene path when non-bar-1 rows are present + scenes are part of the song's structure), test coverage. **Verifiable signal:** `plan_push_tempo_map` emits scene-create calls for non-bar-1 rows. **Defer until** a song actually needs multi-bar tempo (falling-walking doesn't). (W6-F 2026-05-19)

- **[SCF-2N6T]** Clean-default-scaffold: option (a) "rename last instead of delete last" path
  `effort: M · impact: S · area: scaffold · source: builder · added: 2026-05-20 · status: open`

  Today's `cleanup-default-scaffold` ships option (b): push the song first (which creates the song's tracks), then delete the four defaults. Option (a) — delete N-1 defaults, rename the last to absorb one of the song's DB tracks — is cheaper at the LOM level (avoids creating then deleting tracks) but requires probe-and-link rerun to pick up the renamed track. Worth adopting if the cleanup latency becomes user-visible. **Verifiable signal:** `cleanup-default-scaffold` documents both modes and lets the caller choose. **Sized:** medium. (neon-feedback test session 2026-05-20)

- **[AUD-9D3P]** Audio-pipeline cumulative-Critic cleanup: propagate stdlib-only reversal to the decision record
  `effort: S · impact: S · area: audio-analysis · source: critic · added: 2026-05-28 · status: open`

  Findings the cumulative Critic surfaced against `main`; live in the #99/#100 audio code on develop. (c) **Propagate the stdlib-only reversal** to the decision record at `.prawduct/project-state.yaml:258` ("Python 3.10+ stdlib-only runtime") — the branch added six core deps; `change-log.md` justifies it but the decision record wasn't updated. **Signal:** project-state.yaml decision reflects the dep adoption. _((a) "drop unused librosa" pruned 2026-05-29 — masking.py + timing.py now import librosa for STFT + onset detection, so it is load-bearing, not droppable. (b) dead `OvershootWindow` import shipped on feature/variable-tempo-windowing 2026-05-29.)_ (cumulative Critic, offline-cache PR 2026-05-28)

- **[DEV-6T2W]** `inventory_handler` 15s server-side main-thread ceiling vs. the walk
  `effort: S · impact: S · area: device · source: critic · added: 2026-05-28 · status: open`

  The `inventory` action runs inside `run_on_main`, whose server-side `done.wait` uses the default `_main_thread_timeout=15.0s` (not overridden); the client-side `_INVENTORY_READ_TIMEOUT=180.0` only extends the wire-response wait, not main-thread completion. A genuinely pack-heavy single root could trip a spurious `TimeoutError` (and keep freezing Live, since Python can't interrupt the running walk) before the 20000-entry breadth cap engages. Untriggered on the author's Suite install (13884 loadables, no partials). **Signal:** inventory action passes an extended `_main_thread_timeout`, or a doc line documents the ceiling. (PR reviewer, offline-cache PR 2026-05-28)

- **[INS-4H8M]** Fingerprint `HallucinoteAnalyzer.amxd` for install drift detection (parity with the Remote Script)
  `effort: S · impact: S · area: install · source: builder · added: 2026-05-28 · status: open`

  Preflight already reports Remote Script drift via `installed_remote_script_version` → `compute_version_for` → `remote_script.candidates[*].matches_mcp_server`, so the install skill knows when the vendored package is stale. The `.amxd` has no equivalent: `installed_analyzer_amxd` only reports presence (path-or-None), so the install skill must *blindly ask* the user to overwrite even when source and installed are byte-identical. Add a content fingerprint for the binary device (it's a binary container — hash the bytes, e.g. sha256, don't reuse the text-normalizing `compute_version_for` path which the P3 NUL-byte guard already excludes from fingerprinting). Surface `source_fingerprint` + `installed_fingerprint` (+ a `matches` bool) in preflight alongside the M4L block, and teach `/ableton-mcp-install` Step 3d to **skip the copy + the overwrite prompt entirely when they match**, only prompting when the installed device differs (newer-or-customized-vs-repo). **Verifiable signal:** an `analyzer_fingerprint(path)` (or similar) helper exists in `install_paths.py`; preflight JSON carries an analyzer `matches`/fingerprint field; `/ableton-mcp-install` Step 3d branches on it. (install session 2026-05-28 — reinstall blindly re-prompted to overwrite an identical .amxd)

- **[AUD-3K9D]** Tonal balance reference curves + small internal genre corpus
  `effort: M · impact: S · area: audio-analysis · source: reflection · added: 2026-05-23 · status: open`

  Compute long-window average spectra for a handful of professionally-mixed reference tracks per genre tag; surface as comparison targets in MixReports. Stem-level LUFS targets within a mix are *not* standardized in literature — building this internally is the honest path per audio-analysis spike §5. **Verifiable signal:** `tests/fixtures/audio/references/<genre>/*.wav` exists + `MixReport.reference_curve_delta` populated when song carries a genre tag. (spike §9 defer 2026-05-23)

- **[AUD-7W1N]** Full realtime audio-feature set + streaming dashboard
  `effort: L · impact: S · area: audio-analysis · source: reflection · added: 2026-05-23 · status: open`

  Audio-analysis MVP emits 3 OSC features (LUFS-M, sample peak, low-mid band power). Post-MVP: add LUFS-S, all six bands, spectral centroid, spectral flatness; expose the OSC sidecar's ring buffer via an MCP resource (e.g. `ableton://audio/features/stream`) for live mix coaching during playback. Currently the sidecar collects but doesn't expose externally. **Verifiable signal:** MCP resource yielding per-track frames at ≥20 Hz exists; MVP's 3-feature emit replaced or extended with the fuller set. (spike §9 defer 2026-05-23)

- **[AUD-2D6T]** Audio-capture take retention: rolling window + pinned takes
  `effort: M · impact: S · area: audio-analysis · source: reflection · added: 2026-05-23 · status: open`

  Captures are heavy (~165 MB per song per take); audio-analysis MVP keeps everything indefinitely. Add a rolling-window cleanup (keep last N captures per song) with explicit "pin this take" marker for important reference points. Analysis JSONs always retained (cheap). **Verifiable signal:** a `tools/audio-prune` (or similar) exists with `--keep N` + pinned captures have a `.pinned` marker file. (spike §9 defer 2026-05-23)

- **[AUD-5M8H]** `AUDIO_CAPTURED` event kind for capture audit trail
  `effort: S · impact: S · area: audio-analysis · source: reflection · added: 2026-05-23 · status: open`

  Audio-analysis MVP records DB seq number in the capture manifest but emits no event. Adding an event kind would put capture timestamps into the audit log, supporting "when was this take captured" queries via the existing `queries.get_events_for_song`. Additive (event-kinds are append-only per boundary-patterns). **Verifiable signal:** `events.AUDIO_CAPTURED` constant exists; emitted by `ableton_render` on capture-success with `{captures_dir, manifest_seq, track_count}` payload. (spike §9 defer 2026-05-23)

- **[SYN-1T4K]** `_TRANSACTION_DEPTH` module-level state may leak under thread/async patterns
  `effort: S · impact: S · area: sync · source: critic · added: 2026-05-19 · status: open`

  W7-A's SAVEPOINT-based reentrant `transaction()` keeps depth in a module-level `dict[int, int]` keyed by `id(conn)`. Single-threaded today (per project preferences "Sync throughout. SQLite WAL + timeout=10.0. No async planned"), but multi-threaded use would interleave the counter. Defensive options: (a) `WeakKeyDictionary` keyed by the connection object; (b) attach the counter to the connection via a wrapper; (c) `threading.local`. **Sized:** ~5 LoC + 1 thread-safety test. (W7 cumulative-Critic note 3, 2026-05-19)

- **[SYN-8H2W]** `_serialize_markdown` defensive: list items may contain `,` / `[` / `]`
  `effort: S · impact: S · area: sync · source: critic · added: 2026-05-19 · status: open`

  W8-B's `write_markdown_ref` calls `_serialize_markdown` to round-trip frontmatter through the YAML-subset parser. List items (`tags`, `related`, `bars`) get serialized as `[a, b, c]` without quoting. If a future tag or `related` path contains `,` or `[` / `]`, the parser silently splits or fails. Today's tags are slug-shaped so this isn't exercised, but the wrap is the LLM-facing surface. Defensive fix: (a) quote list items containing those chars, (b) reject at serialization with a teaching error, or (c) switch to multi-line list format. **Sized:** ~10 LoC + 2 tests. (W8-B Critic cumulative note 3, 2026-05-19)

- **[SYN-3D7M]** `_apply_session_clips_for_track` cascades `delete_clip` → `arrangement_clips` silently
  `effort: S · impact: S · area: sync · source: critic · added: 2026-05-17 · status: open`

  Design-consistent with the project's cascade discipline, but the cross-domain side effect is invisible in `out.details` (no per-row events for the cascaded placements). Worth counting + logging cascaded arrangement-clip placements when a session-clip delete fires during pull. (PR review #22, 2026-05-17)

- **[SYN-9K5T]** `_apply_session_clips_for_track` silently tolerates missing `length` / `name` on populated entries
  `effort: S · impact: S · area: sync · source: critic · added: 2026-05-17 · status: open`

  Via `_floats_differ(None, X) → False`, unlike `_apply_arrangement_clips_for_track` which warns explicitly on missing fields. Asymmetry, not a correctness bug. Tighten for parity. (PR review #22, 2026-05-17)

- **[ARR-6T8N]** `duplicate_to_arrangement` spurious-clip detection is start-time-only
  `effort: S · impact: S · area: arrangement · source: critic · added: 2026-05-18 · status: open`

  Chunk W2-H detects the B-24 side effect by comparing arrangement_clips' start_times before vs after the call. If a pre-existing clip already sits at exactly `dest_beats + source.length`, its start_time is already in the before-set and the new spurious clip slips past detection. Object-identity diff (`id(c)`) would be more robust — though Live's wrapper recreation (B-1) makes that fragile too. Unlikely in real songs. (critic W2 N2, Chunk W2-H 2026-05-18)

- **[DEV-2H6K]** Confirm Phaser/Flanger and Eq3/FilterEQ3 round-trip class_name preservation in real Live
  `effort: S · impact: S · area: device · source: critic · added: 2026-05-18 · status: open`

  Chunk W2-B's `device_names` mapping merged `Phaser`/`Flanger` to display `Phaser-Flanger` (similarly `Eq3`/`FilterEQ3` → `EQ Three`, `AutoPan` → `Auto Pan-Tremolo`) because Live 12.x merged these device families under one browser node. Load works for either source class_name; but when the device is captured (`device.list`), the reported `class_name` may be the merged form, breaking deterministic re-push. Post-D4 (commit `305742c`, "structural display-name shift — delete `_CLASS_TO_DISPLAY`"), the mapping was restructured to `device_names.py` with rack-root lookup only — the round-trip may be structurally solved. Real-Live verify path: load via `kind='Flanger'`, re-capture, confirm class_name preserved. If not, planner needs `preset_uri` for merged-display devices. **Verifiable signal:** real-Live smoke confirms class_name preservation; or a unit test pins the post-D4 invariant. (critic W2 N1, Chunk W2-B 2026-05-18; D4 context added 2026-05-22)

- **[TST-4M9D]** FastMCP private-API access in `test_server.py`
  `effort: S · impact: S · area: tests · source: critic · added: 2026-05-18 · status: open`

  Three tests reach into `mcp._tool_manager._tools[name]` directly to fetch a `Tool` for `.run()`. The existing `registered_tool_names` helper tries multiple attribute names for FastMCP version-drift resilience; a symmetric `get_registered_tool(mcp, name)` would centralize the version-coupling. **Verifiable signal:** `get_registered_tool` helper exists in tests. (critic W2 N1, Chunk W2-1 2026-05-18)

- **[TST-7K3H]** Clear + note_expression: omit-required-args path untested
  `effort: S · impact: S · area: tests · source: critic · added: 2026-05-18 · status: open`

  `ableton_automation(action='clear', target_kind='note_expression')` raises the gap-citing `NotImplementedError` regardless of whether note_pitch / note_start_beats / axis were supplied (gap check fires before parameter validation). Asymmetric with `write_envelope` which validates first. Either add a docstring note or a one-line test pinning the precedence. (critic, Chunk D 2026-05-18)

- **[DEV-5T1M]** W6-K real-Live smoke — remaining surfaces
  `effort: M · impact: S · area: device · source: reflection · added: 2026-05-19 · status: open`

  Wave 6 shipped a substantial MCP-side surface validated against fakes. Sidechain smoke landed with `c80d4a6` (2026-05-22 — S/C Gain refusal fix). Still wants real-Live empirical confirmation: (a) `read_envelope` round-trips on a mixer_volume / device_parameter envelope; (b) `get_device_chains` structure on a real Drum Rack; (c) `load_in_rack` + `set_parameter_in_rack` on an InstrumentGroupDevice; (d) `set_input_routing` finds the right RoutingType by display_name; (e) W5-F deferred — round-trip parity on parameter-dialed native instruments via the W5-D pull path. (W6 close-out 2026-05-19; sidechain shipped 2026-05-22)

- **[SYN-2K8T]** One raw `conn.execute("SELECT ...")` JOIN read in `sync/push.py:1452`
  `effort: S · impact: S · area: sync · source: critic · added: 2026-05-17 · status: open`

  The original two-SELECT concern (PR #24) is down to one — the remaining read is a join between `arrangement_clips` and `clips` to resolve envelope addressing; harder to factor into a `queries.py` helper because of the JOIN. Worth doing for consistency, but lower-leverage than when there were two. (PR review #24, 2026-05-17; refreshed 2026-05-22)

- **[MET-9D4H]** Wave plan headers missing top-level `Requirements Confidence` field
  `effort: S · impact: S · area: methodology · source: critic · added: 2026-05-17 · status: open`

  Each M+1 chunk has an inline Confidence check, but the wave-level header in `build-plan.md` lacks a `Requirements Confidence: High|Medium|Low` declaration. Methodology cleanup — apply to the next wave header rather than retrofitting. (critic, M+1 final 2026-05-17)

- **[AUD-6T2K]** Source separation fallback for stemless audio inputs (lazy-import demucs)
  `effort: L · impact: S · area: audio-analysis · source: reflection · added: 2026-05-23 · status: open`

  When users want to analyze an imported reference track (not authored in Hallucinote — no stems available), use HT-Demucs v4 to derive vocals/drums/bass/other pseudo-stems. PyTorch dep + ~9.2 dB SDR; lazy-import only when invoked so the dep stays optional. Audio-analysis MVP's normal mode is "we have the stems via `sfrecord~`" — separation is the fallback for analyzing reference tracks, not the primary path. **Verifiable signal:** `src/hallucinote/audio/separation.py` exists with `separate_stems(mixed_audio) -> dict[str, ndarray]` gated behind a `[audio-separation]` extras group. (spike §9 defer 2026-05-23)

- **[ENV-3M7K]** Wave 0 / D1 v1.1: planner auto-partition envelopes across per-section session clips
  `effort: L · impact: S · area: envelope · source: builder · added: 2026-05-19 · status: open`

  v1 ships refuse-with-teaching (W10-F) for long envelopes whose range exceeds any single session clip. v1.1: planner detects the multi-clip case, splits the DB's logical envelope at session-clip boundaries, emits one sub-envelope per covering session clip; pull stitches adjacent identical envelopes back. Natural Hallucinote shape. Requires push-side split + pull-side stitch + round-trip test coverage. (Wave 0 triage Group D 2026-05-19)

- **[ENV-8H1T]** Wave 0 / D3 v1.1: mixer envelopes on audio tracks via audio-clip DB model
  `effort: M · impact: S · area: envelope · source: builder · added: 2026-05-19 · status: open · related: P6-AUD-CLIP`

  Gated on `scope.later` "audio clips: clip kind discriminator, file references, warp metadata." Once audio session clips are addressable, the envelope-emitter family can host mixer/send envelopes on audio session clips the same way it does for MIDI session clips. v1 ships refuse-with-teaching (W10-F). (Wave 0 triage Group D 2026-05-19)

- **[GEN-5K2D]** Wave 0 paper-cut: polyrhythm helper using `fractions.Fraction`
  `effort: S · impact: S · area: generators · source: builder · added: 2026-05-19 · status: open`

  `(7.0 / 5) * 3 / 2.0` yields `2.0999999999999996` (IEEE 754 sub-LSB drift). The SQLite REAL column round-trips it faithfully, but authoring introduces it without warning. A future `hallucinote.polyrhythm(n, against=k)` helper should compute via `fractions.Fraction(against, n)` and float-convert only at the mutator boundary. (Wave 0 canary `odd-meter-experimental` runbook step 8, 2026-05-19)

- **[ENV-1T9M]** Envelope discovery on pull — envelopes authored only in Live
  `effort: L · impact: S · area: envelope · source: builder · added: 2026-05-19 · status: open`

  W7-A (2026-05-19) ships `plan_pull_envelopes` in DB-mirrored mode. It does NOT discover envelopes the user authored *only* in Live — that would explode the read surface (~10s-100s of probes per pull). A future "envelope discovery" pass could batch-probe likely surfaces (clips/devices/tracks mutated recently per `events` log). Not blocking V1. (W7-A 2026-05-19)

- **[DEV-7K4H]** Recursive nested-nested rack chain support
  `effort: L · impact: S · area: device · source: builder · added: 2026-05-19 · status: open`

  W6-I/J ship one-level-deep nested-rack support. Live allows racks-inside-racks-inside-racks; addressing beyond one level requires a path-style API (e.g., `chain_path=[2, 1, 3]`). Not exercised by today's songs. (W6-I/J 2026-05-19)

- **[ENV-4M2T]** Return-side device_parameter envelopes need a return-track session-clip model
  `effort: L · impact: S · area: envelope · source: builder · added: 2026-05-18 · status: open`

  W4-B routes track-side mixer/pan/send/device_parameter envelopes through session clips on the parent track. Return tracks have arrangement-side mixer state but the DB has no session-clip model for returns (`clips.track_id` references `tracks(id)` only). Live 12.4 only accepts device_parameter envelopes on session clips, so return-side envelopes get warn+skip today. Non-trivial: schema branch + mutators + push/pull routing. (W4-B 2026-05-18)

- **[NOT-9H3K]** Live API residual on gap #4: true surgical Ableton-side note writes
  `effort: M · impact: S · area: note · source: builder · added: 2026-05-17 · status: open`

  V1 close-out shipped READ-with-stable-IDs + WRITE-whole-clip (sufficient for compose/produce). Residual: per-note Ableton writes that preserve playback continuity (Live retriggers a clip on `set_notes` during playback) — would land via `apply_note_modifications` / `add_new_notes` / `remove_notes_by_id`. Out of V1 scope per `scope.never` (no live-performance use case). Re-open if performance use cases enter scope. (V1 close-out 2026-05-17)

- **[GEN-2T8M]** Hallucinote-side quantize / swing / groove module — REVISIT WHETHER NEEDED
  `effort: M · impact: S · area: generators · source: reflection · added: 2026-05-17 · status: open`

  Original M-3 scoping reaffirmed the DB-as-source-of-truth principle for note timing. But memory `feedback_prefer_llm_over_deterministic_module` says: before proposing a transform module (quantize/groove/timing math), ask whether the LLM can do it directly. The microtiming-as-authorship note (`feedback_microtiming_is_authorship`) reinforces this — feel is baked at pattern-helper generation time, not via a post-hoc transform. **Decision needed:** does this module still earn its keep, or should it be removed from backlog entirely in favor of LLM-direct timing offset authorship + the per-helper `feel` parameter? Defer until a real song needs structured grooves; downgrade-or-remove on the next scrub. (reflection, Wave M-3 user pivot 2026-05-17; flagged for re-decision 2026-05-22)

- **[INS-6K1T]** Native Linux support — gated on Ableton shipping a Linux build
  `effort: L · impact: S · area: install · source: builder · added: 2026-05-19 · status: open`

  Today: README + install skill warn-and-confirm; `_live_preferences_root()` returns `None` on Linux (existing Wine/CrossOver branch in `install_paths.candidate_user_libraries()` is best-guess). If Ableton ships native Linux: real preferences root, `live_is_running()` Linux branch (`pgrep -i -f 'Ableton Live'`), `live_log_path()` mapping, decision on Wine fallback. (W15-C 2026-05-19)

### Future / event-store era (P6 — far horizon, kept open)

- **[CLP-AUD1]** Audio clips: clip kind discriminator, file references, warp metadata, warp markers
  `effort: L · impact: M · area: clip · source: user · added: 2026-05-17 · status: open`

  (migrated from legacy P6) Gates several deferred envelope + import items above.

- **[CLP-AUD2]** Session-view audio clip placement via browser-load workaround
  `effort: M · impact: S · area: clip · source: builder · added: 2026-05-19 · status: open`

  Live 10–12 has no `ClipSlot.create_audio_clip`. The only path is async browser-load: set `song.view.highlighted_clip_slot = target_slot`, then `application.browser.load_item(audio_browser_item)`. Caveats: async (no completion callback), audio must be addressable as a BrowserItem (Library/User/Places — not arbitrary filesystem path), browser-indexing dependent. Could expose as `ableton_clip(action='load_audio_to_session', track_index, clip_index, browser_uri)`. (W6-D investigation 2026-05-19)

- **[RTE-1K9T]** Track routing: sidechain, parallel busses, input/output routing config
  `effort: L · impact: S · area: routing · source: user · added: 2026-05-17 · status: open`

  (migrated from legacy P6) Schema + sync work.

- **[TRK-2H6K]** Group tracks (`tracks.parent_track_id` + Live group semantics)
  `effort: L · impact: S · area: track · source: user · added: 2026-05-17 · status: open`

  (migrated from legacy P6)

- **[SYN-7T3M]** Pull-side sync follow-on
  `effort: M · impact: S · area: sync · source: builder · added: 2026-05-17 · status: open`

  (status W5-D 2026-05-19) **Shipped:** mix-state, cue points + score globals, device chain structure, arrangement-clip placements, session-view clip slots, note pull via stable-ID read + whole-clip write, device-parameter values. **Deferred (above):** envelope pull (gated on `hallucinote-mcp` envelope read surface), nested rack chain pull (gated on `hallucinote-mcp` `get_device_chains`). (migrated; rewritten 2026-05-17; W5-D update 2026-05-19)

- **[EVT-4K8H]** Event replay function (`replay(events) → state`) and merge tooling
  `effort: L · impact: S · area: event-store · source: user · added: 2026-05-17 · status: open`

  (migrated from legacy P6) Required for cross-DB event-stream merges; only useful after the event-store flip.

- **[EVT-9M2T]** Post-hoc event annotation (`event_annotations` table) for narrative on-the-fly addition to history
  `effort: M · impact: S · area: event-store · source: user · added: 2026-05-17 · status: open`

  (migrated from legacy P6)

- **[MIG-3T7K]** Real-time concurrent editing / cloud DB migration
  `effort: L · impact: S · area: migration · source: user · added: 2026-05-17 · status: open`

  (migrated from legacy P6) Out of foreseeable scope; mutator-discipline + storage abstraction keep the door open.

- **[TST-8K1M]** Song tests (on-demand layer): DB consistency + mix hygiene + audio/spectral
  `effort: M · impact: S · area: tests · source: user · added: 2026-05-17 · status: open`

  (migrated from legacy P6) Land per-chunk as appetite allows; not gating any chunk's completion.

## Promoted

_(no items)_

## Archive

Closed investigations — no fix possible / structural-close on Ableton's roadmap. Kept for search so a future scrub doesn't re-open them without new evidence. Status `dropped` = investigated and intentionally not pursued; `shipped` = built and closed.

- **[ARR-1H9C]** Harmony/key as a first-class structural axis (the biggest arrangement-model gap)
  `effort: L · impact: L · area: arrangement · source: review · added: 2026-05-30 · status: shipped · closed-by: feature/harmonic-substrate · related: ARR-4V7P`

  Surfaced by a counter-example review of the arrangement model (`arrangement-model.md`). The model carries ONE structural curve — energy — but functional-tonal music (sonata form, jazz changes, 12-bar blues, most pop) is driven by HARMONIC tension/resolution: tonic-vs-dominant established and resolved, modulation, the recap landing home. The model can author the notes but cannot carry "this section is in the dominant, resolved to tonic at the recap" AS STRUCTURE — it's blind to the thing doing the dramatic work. **Verifiable signal:** sections can carry a harmonic attribute (key/mode/function) AND `arrangement-model.md` records the substrate-vs-notes decision with rationale. **Sized:** large. (arrangement-model counter-example review, 2026-05-30)

  **Resolved 2026-05-30 (feature/harmonic-substrate):** DECISION — harmony is a modeled substrate (a harmonic axis co-equal to energy), recorded with rationale in `arrangement-model.md` ("Known gaps surfaced in review"). BUILT (Chunks A–E): `hallucinote.theory` (`Chord` — slash bass, polymodal `split`, free-form function labels; `Mode`; `Progression` — authored harmonic-rhythm timeline, functional/modal toggle); chord-aware generators (skank, bass, power chords, organ bubble) that voice a progression; `transpose_diatonic` (the key-aware variation op; `transpose` stayed key-blind); the `Arrangement` carrying per-section `progression` + a read-side `harmonic_curve` parallel to `energy_curve`; and a build-time conformance lens (`theory.lint`) that FAILS the build on harmonic stasis (the structural fix for the one-chord drone — a per-section key/mode label alone wouldn't have prevented it). DEMONSTRATED by sun-zone-done (Chunk F): a 184-bar through-composed arc, modes flipping E Dorian↔Phrygian over a constant E, resolving into a polymodal both-at-once fusion chord. Both verifiable-signal conditions met. DEFERRED: DB-promotion of the harmony axis (in-memory today, like `function`/`energy`); the VERTICAL/inter-layer consonance constraint stays open as ARR-4V7P. Ships with the Chunk F commit; cumulative Critic at PR time per `feedback_critic_cadence_for_small_chunks`.

- **[TMP-1R7K]** `_position_bar_to_beats` raises on `start_bar < 1.0`; collectors don't validate it
  `effort: S · impact: S · area: tempo · source: critic · added: 2026-05-29 · status: shipped · reviewed: 2026-05-29 · closed-by: fix/tempo-geometry-followups`

  `_collect_tempo_map` / `_collect_sections` feed `row['start_bar']` straight into `_position_bar_to_beats`, which raises `ValueError` below the 1-based bar floor, and `add_tempo_point` / section mutators don't validate `start_bar >= 1.0` at write time. Pre-existing, project-wide (the 1-based bar convention is everywhere) — a latent gap, not introduced by variable-tempo. **Verifiable signal:** either the bar-position mutators reject `< 1.0` with a teaching error, or the collectors document/guard the floor. **Sized:** small. (PR reviewer note, variable-tempo-windowing 2026-05-29) **Shipped 2026-05-29:** bar-floor teaching error (`_require_bar_floor`) now applied tree-wide at all five bar-position mutators (`create_section`, `add_tempo_point`, `add_time_signature_point`, `add_cue_point`, `add_arrangement_clip`); `arrangement_clips` gains the `CHECK(start_bar>=1.0)` + `CHECK(end_bar>start_bar)` it uniquely lacked. Shipped on `fix/tempo-geometry-followups`, full suite 2412 green, Critic clean. Verifiable signal met — mutators reject `< 1.0` with a teaching error.

- **[TMP-8M4H]** `BeatSampleMap` models `ramp='linear'` tempo points as steps
  `effort: S · impact: S · area: tempo · source: critic · added: 2026-05-29 · status: shipped · reviewed: 2026-05-29 · closed-by: fix/tempo-geometry-followups`

  Variable-tempo windowing (`section.BeatSampleMap`) treats each `tempo_map` segment as constant bpm from its `start_beat`. A row with `ramp='linear'` (tempo glides to the next point) is approximated as a step at the segment's own bpm — only `ramp='hold'` is exact. For a linear ramp the true beat→seconds curve integrates a linearly-varying bpm (a log term), so a long ramp's mid-segment boundaries drift slightly. **Verifiable signal:** `BeatSampleMap` consumes the `ramp` field (interpolates bpm across a `linear` segment) rather than ignoring it. **Sized:** small. (Critic note, variable-tempo-windowing 2026-05-29) **Shipped 2026-05-29:** `BeatSampleMap` now integrates linear ramps via the closed-form log integral (`section.py`); shipped on `fix/tempo-geometry-followups`, full suite 2412 green, Critic clean. Verifiable signal met — `BeatSampleMap` consumes the `ramp` field.

- **[TMP-9X2D]** Multi-bar tempo / time-signature automation — NO MCP-SIDE FIX POSSIBLE
  `effort: L · impact: M · area: tempo · source: reflection · added: 2026-05-18 · status: dropped · reviewed: 2026-05-19 · related: TMP-5K1R`

  Bar-1 case solved (W5-A 2026-05-18). Multi-bar cannot be closed via MCP: the underlying Live LOM does not expose `create_automation_envelope` from any song-level path. `song.master_track.mixer_device.song_tempo` IS a `DeviceParameter` but has no envelope-creation path. `signature_numerator/denominator` are plain int properties; per Ableton's forum (t=144193) time-signature automation is unsupported in the API. Sources: Cycling74 LOM, gluon/AbletonLive12 `_MxDCore/LomTypes.py`, Live 12 release notes. **Workarounds**: per-scene tempo/sig (see TMP-5K1R); real-time step-write (degraded, lost on reload). The planner's "warn and skip non-bar-1 rows" is the right shape until Ableton extends the API. (corrected W4-E entry; investigation closed W6-F 2026-05-19)

- **[ENV-2M9K]** Live 12.4 envelopes are step-only — plan-time warn shipped
  `effort: L · impact: M · area: envelope · source: reflection · added: 2026-05-18 · status: dropped · reviewed: 2026-05-19`

  `plan_push_envelopes` emits a per-envelope `plan.warn` when any breakpoint has `curve_kind in {'linear', 'fast', 'slow'}`, surfacing round-trip lossiness at plan time. Only `'hold'` curves round-trip losslessly. No segment-curve API exists in Live 10–12. `Live.Clip.AutomationEnvelope` exposes exactly two public methods (`insert_step`, `value_at_time`). Ableton's own Push remote script calls only `insert_step`. Sources: Structure-Void's LOM XML (Live 10.1.19), gluon Live 12, Live 12 release notes. **Workaround if curve fidelity is required:** emit a dense sequence of stepped points approximating the desired curve (XML bloat + post-load editability cost). The structural close is on Ableton's roadmap. (real-Live smoke, W4-E 2026-05-18; warn shipped W5-E; investigation closed W6-C 2026-05-19)

- **[DEV-8T4M]** Live 12.4 hides the mixer column on tracks with empty device chains
  `effort: S · impact: S · area: device · source: reflection · added: 2026-05-18 · status: dropped · reviewed: 2026-05-18`

  MIDI tracks created via `ableton_track(action='create')` with no devices loaded show NO volume/pan/sends/master faders. Loading any device into the chain makes the mixer column appear. Mixer state IS settable via MCP regardless — Live just hides the UI surfaces. Not a Hallucinote bug; documented in the push skill prose. (real-Live smoke, W4-E 2026-05-18)

- **[DEV-3K7H]** Drum Rack browser name-collision is a per-machine library hazard
  `effort: M · impact: M · area: device · source: reflection · added: 2026-05-19 · status: dropped · reviewed: 2026-05-22`

  Empirical (W7-0 2026-05-19): `kind='Drum Rack'` actually loaded an `InstrumentGroupDevice` because that machine had a saved Instrument Rack preset named "Drum Rack" higher in the browser walk. Per-machine library state, not a code bug. **Mitigations shipped:** Arc 7 / P5 surfaces `loaded_class_name` in the load response so callers can detect mismatches; Arc 7-tail E2 confirmed the symmetric replace-in-place case. **Workaround today:** use `preset_uri` for unambiguous loads; verify the returned `loaded_class_name` matches the snapshot's expected class. **Remaining fix candidates if it resurfaces:** restrict display-name walks to canonical category roots, or prefer the empty-rack canonical URI when the name matches a built-in rack class. (W7-0 session 2026-05-19; refreshed 2026-05-22)
