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

- **[DOC-3P7K]** Post-split accuracy pass on the deep reference docs
  `effort: S · impact: S · area: docs · source: dogfood · added: 2026-06-03 · status: open · related: project-root-contract`

  The user-facing docs (README, quickstart, skills, collaboration, faq, song-authoring-conventions, song-new-checklist) were reoriented to the two-repo + plugin reality (`/hallucinote:*` skills, songs in their own repo) on `docs/post-split-accuracy`. The deeper engine-internal reference docs still carry pre-split framing: `docs/snapshot-schema.md`, `docs/capability-truth.md`, `docs/polyrhythms.md`, `docs/terminology.md` — mostly in-repo `songs/<slug>/` workflow examples and a few unprefixed skill names. Lower priority (engine-internal, not the composing surface). **Verifiable signal:** `grep -rlE '/(song-new|ableton-push|compose-part)\b' docs/*.md | grep -v hallucinote:` returns nothing across the active (non-archive) docs. (split dogfood, 2026-06-03)

- **[AUD-3F8M]** Master-bus windowing to verify post-fader automation (mixer_volume / mixer_pan)
  `effort: M · impact: S · area: audio-analysis · source: critic · added: 2026-06-02 · status: open · related: AUD-8H2M`

  AUD-8H2M verifies `device_parameter` (timbre) and `send_level` (return level) automation, but `mixer_volume` / `mixer_pan` are **post-fader** — invisible to the pre-fader stem tap (`audio/levels.py`), so `audio/automation.verify_envelope_realization` reports them `measurable=False` rather than verifying them. A volume swell or pan move IS visible on the **master** (post-fader sum) and in attribution. A master-bus-windowing pass — window the master (and/or the post-fader contribution) around a declared mixer envelope breakpoint and confirm the level/balance change — would close the gap. Scope: extend `_run_automation_verifications` to route mixer kinds to a master-windowed measurement; needs the per-stem post-fader contribution (attribution already estimates this) or a post-fader tap. **Verifiable signal:** a declared `mixer_volume` swell on a real capture reports `measurable=True` + `realized` from master-bus windowing, not the current post-fader skip. (cumulative Critic + AUD-8H2M scoping, 2026-06-02)

- **[AUD-4S8T]** Source-side fix: make capture STOP transport-bracketed (kill the per-surface length ramp)
  `effort: M · impact: S · area: audio-analysis · source: dogfood · added: 2026-06-02 · status: open · reviewed: 2026-06-03 · related: AUD-1C7K`

  AUD-1C7K is handled read-side by `trim_to_common_length` (starts are sample-aligned; only tails differ). But the underlying cause remains: per-surface `sfrecord~` recordings STOP at staggered times — a measured ~20ms/surface wall-clock ramp (buffer-INDEPENDENT: 512→128 left the 170ms spread unchanged) tied to the render's sequential per-surface disarm (`handlers/render.py` `_set_arm_on_all(arm=False)`), NOT the transport stop-crossing the spec intends. Fixing it at the source would make captures equal-length by construction (no trim, and sample-exact tails for any future cross-surface tail analysis). The spec's transport-bracketed stop already works for at least one surface (the master, in sun-zone-done), so the mechanism is achievable — but the master-stop is INCONSISTENT (shortest in sun-zone-done, longest in the calibration set), so why some surfaces' stop-crossing fires and others fall through to the disarm isn't pinned. **Likely touches the `.amxd` observer (Max GUI, human-authored) + render disarm sequence.** Low priority — trim handles the read side. **Verifiable signal:** a full render produces per-surface WAVs of equal (or ≤1-buffer-spread) length with no read-side trim. (AUD-1C7K source investigation, 2026-06-02)
  **PARTIALLY SHIPPED (the ring-out half) on develop (commit 515c6ab, merge `fix/reverb-rt60-decay-tail`).** `render.py` now records `ring_out_beats` past the arrangement end (analyzer `set_stop_at_beat(end_beat + ring_out)`, transport target extended, loop off+restored, manifest carries it) so the reverb tail is captured — no `.amxd` change. **STILL OPEN (the residual this item now tracks):** the ORIGINAL equal-length-by-construction goal — killing the ~20ms/surface wall-clock stop ramp so per-surface WAVs come out the same length by construction — is NOT addressed. The read-side `trim_to_common_length` from AUD-1C7K handles that residual for now; this item stays open for the source-side stop-ramp fix (the `.amxd` observer + render disarm sequence work described above).

- **[SYN-2M9P]** Push planner emits master device-LOAD calls that can never execute (DEV-2M9K follow-up)
  `effort: S · impact: M · area: sync · source: critic · added: 2026-06-02 · status: open · related: DEV-2M9K`

  Follow-up to the DEV-2M9K fix (commit on `fix/master-load-bridge`): Ableton Live 12.4 has no LOM path to load a device onto the master track, so `ableton_device(action='load', master=true)` now refuses up front. But `plan_push_devices` (`src/hallucinote/sync/push/devices.py` ~47-61) still walks the master strip and emits a `device.load(master=true)` for every *unbound* master-strip device chain. At execute time that load fails, and `push_execute.py:577-591` marks the **devices phase HALTED** (`outcome='partial'`, `EXIT_PARTIAL`) and all downstream phases (envelopes / arrangement / cues) **PENDING** — so any song that authors a master-strip device chain in its DB gets a reliably PARTIAL push, re-planned on every run. (Latent today: sun-zone-done's master limiter+EQ live in the saved `.als`, not the DB, so no current song triggers it. This halt also existed pre-DEV-2M9K — the old silent mis-load raised the misleading `_raise_silent_noop` — but it now fails cleanly without corrupting a regular track.)

  **Fix direction:** the planner should NOT emit `device.load` for master-strip chains (they're impossible), while STILL emitting master device-PARAMETER writes (`set_parameter` works on a hand-placed master device). I.e. master devices are configure-only across the whole stack — `load_handler`, render setup, and now the push planner — mirroring the "place by hand once" contract. Consider a one-line push-state note when a master chain is skipped so the user knows to place it by hand.

  **Verifiable signal:** `plan_push_devices` on a song with a master-strip device chain emits zero `device.load` calls addressed `master=true` (only `set_parameter`/param calls), and an execute-path regression test drives a refused-master scenario through `push_execute` asserting the devices phase is NOT halted by it. (No such regression test exists today — the sync tests only assert plan-level emission; Critic note, DEV-2M9K review 2026-06-02.)

- **[MEL-1A7K]** Melody as a first-class structural dimension — author + analyze + master it (**URGENT**)
  `effort: L · impact: L · area: melody · source: user · added: 2026-05-31 · status: in-progress · related: ARR-8P5K, ARR-1H9C, ARR-3R8F`

  **Progress (2026-05-31): phase 1 (research + model artifact) DONE.** Two verified
  deep-research passes (45 confirmed claims; pass 1 22/25 on expectation/contour/
  universals/taxonomy, pass 2 23/25 on harmony-coupling + memorability; motivic/
  phrase angle honestly returned no surviving claims — open follow-on).
  `.prawduct/artifacts/melody-model.md` written (the verifiable signal), folded into
  `arrangement-model.md` (taxonomy "Melody — the line layer" subsection), the
  project-state manifest, and `scope.later`. The thesis: **no universal "good
  melody" function** — a genre-general substrate + a declared per-song profile, the
  lens grading the line against its OWN intent (the metaperformer pattern, learn
  intent back per-song). Melody placed as a **"line layer"** (pitch reads harmony,
  rhythm reads feel, owns contour + motivic economy). **Remaining (phase 2, the
  both-sides build, read-side first):** the symbolic melody lens
  `src/hallucinote/melody/` (contour + intervals + harmony-fit reusing `theory`),
  wired into `/mix-review` beside the harmony + performance lenses; then the
  declared-profile authoring surface; then tune-by-ear on sun-zone-done's two hooks.

  **User mandate (2026-05-31, URGENT):** *"approach melody the same way we did rhythm, polyrhythm, energy, and harmony. We need to seriously analyze and master melody."* Melody is the conspicuous gap in the dimension taxonomy (ARR-8P5K): form/recurrence, ENERGY, HARMONY (ARR-1H9C, shipped), and PERFORMANCE / rhythm-feel (read-side shipped; authoring 2b landing) all got the both-sides treatment — but **melodic content itself has no dedicated authoring intent and no analysis lens.** Today a melody is just notes at the raw floor plus the arrangement `Motif`/reference scaffold, which addresses the *recurrence* of a line, not its melodic *substance* (contour, intervallic profile, scale-degree function, phrase arc, singability, hook).

  Apply the exact house discipline that worked for harmony + performance:
  1. **A verified deep-research pass FIRST** (the performance pass set the bar — 24/25 claims confirmed on primary sources, adversarial 3-vote verification). Survey the computational-melody literature: contour theory, Narmour's implication-realization, Huron's melodic expectation (*Sweet Anticipation*), Gestalt/proximity grouping, tonal tension + voice-leading, motivic transformation, phrase/arch structure, tessitura/range, hook/earworm/memorability research, and melodic-rhythm coupling. No blog/marketing source carries a finding.
  2. **A `melody-model.md` design artifact** (parallel to harmony's + `performance-model.md`) recording the research-backed framing, the COUPLING to harmony (chord-tone vs non-chord-tone, scale-degree function, tension/resolution), to rhythm (melodic rhythm / feel, ARR-3R8F), and to energy (register/contour as intensity), plus the ruler-not-stamp boundary — a melody *generator* is a stamp; the authoring surface is a declared melodic INTENT (contour shape / phrase-arc / range / motif-DNA), the composer/LLM bringing the actual musical idea (great-art-not-software).
  3. **BOTH SIDES, always.** An authoring surface (express the line's intent) AND a read-side analysis lens — contour shape, intervallic/leap profile, non-chord-tone usage *against the harmony*, phrase arc, repetition-vs-variation balance, range/singability — the masking-analyzer / harmony-lint shape: *"is the line doing what it intends, and is it a good line?"*, info coaching never a verdict.

  Heavy coupling: melody is likely NOT an orthogonal axis but a line whose PITCH dimension reads harmony (ARR-1H9C) and whose RHYTHM dimension reads the feel layer (ARR-3R8F / performance) — the taxonomy refactor (ARR-8P5K) should absorb it (intent → realization channels, not a flat peer axis). Governed by ruler-not-stamp, one-source-of-truth, discovered-from-friction, both-sides. **Verifiable signal:** a `.prawduct/artifacts/melody-model.md` exists recording the research-backed framing + a both-sides decision; a melody analysis lens exists (read side) OR a decision-record states melodic correctness stays composer-owned at the note floor with rationale. **Sized:** large (research → design → incremental both-sides build, friction-driven like performance). (user melody mandate 2026-05-31)

  **Update (2026-05-31b): phase 2a read-side LENS shipped.** `src/hallucinote/melody/` — `lens` + `contour` + `intervals` + `harmony_fit` (pure stdlib, render-free, the melodic counterpart to `theory.lint` / `performance.lens`) + the `Arrangement.section_melody_inputs()` adapter; 27 tests, full suite green (2691). Measures the genre-general substrate facts (step↔leap proximity, post-skip reversal, alphabet, contour shape + apex + variability, ambitus) and harmony-fit against the `Progression` (chord-tone/scale-tone/chromatic, Bharucha NCT-resolves-by-step, chord-tone-on-strong-beat); classifies `active`/`static`/`insufficient-data` with `static-line` + `unresolved-nct` coaching questions (info, never verdicts). The **verifiable signal is met** (model artifact + read-side lens both exist). A build-time correction proved the thesis: an early `step≥0.5→shaped else wandering` rule mislabeled the third-based reggae hook "wandering" → dropped the shaped-vs-aimless verdict to the profile-relative phase 2b (no universal verdict).

  **Update (2026-06-01): phase 2a read-side surface WIRED + onboarding capability reconciled.** The lens gained a user-facing home: `analyze_arrangement()` + `tools/melody_lens.py` CLI + a per-song `melody_report()` convention (sun-zone-done + the scaffold template), wired into **`/compose-review`** (the render-free compositional surface — retargeted from `/mix-review`, which is audio-driven; see `melody-model.md` §7 *Read-side surface*). Resolved the capability intersection with the parallel onboarding/teaching work (merged from develop): split melody **authoring** (◐, permanent) from melody **line-analysis** (✓ read-side) across `capability-truth.md`, the onboarding model, song-new/install skills, and the persona/work eval rubrics (+ a `melody-analysis` `song_eval` dimension). 13 new tests; full suite 2579 passed / 210 skipped.

  **Update (2026-06-03): phase 2b authoring side SHIPPED (`feature/mel-1a7k-melody-profile`).** The declared **`MelodicProfile`** (`melody/profile.py`, mirroring the proven `performance.realization.PerformanceProfile` — read-only declared intent, NO `apply_*` because pitch is the musical idea; nine v1 fields, `phrase_arch`/`motif_dna` DEFERRED until their read side lands), **profile-relative grading** (each declared field graded against its measured value as an info QUESTION: harmonic-freedom / contour / apex / ambitus / step-appetite / repetition-appetite), the profile-relative **`shaped_reading`** (`shaped`/`aimless`/`ungraded` — the recorded universal-verdict bug made permanently impossible: a `free`/silent profile can NEVER read `aimless`, the third-based reggae hook reads `shaped`), the within-line **motivic-economy** reading (`economy.py` — n-gram self-similarity over the interval sequence; COSIATEC/Kolmogorov named, not shipped; C7 null pinned), and **LBDM per-phrase contour** (`segmentation.py`, OPTIONAL — built because calibration proved whole-section contour too coarse on the looping hooks). Wired into `/compose-review` + the scaffold template; `melody-model.md` §3.B/§3.C/§4/§7/§8/§9 updated to shipped reality. Full suite green (2854). **PENDING by-ear (a creative lock-in, not a gap):** the appetite→fraction grading edges (named `# PENDING by-ear calibration` placeholder constants in `lens.py`) + which profile each sun-zone-done hook declares — the build SURFACED the objective hook measurements (build-plan Status table) and STOPPED at the threshold/profile decision; Live unattended, NOT auto-applied. See EVL-9R3T for refreshing the stale pre-change eval snapshots.

- **[MIX-3S7P]** Per-section pan + reverb-send automation (atmospheric space that snaps back) — needs a host-clip strategy (**HIGH PRIORITY** — user)
  `effort: M · impact: M · area: mix · source: user · added: 2026-06-01 · status: open · related: AUD-8H2M`

  **Raised by the user (2026-06-01, sun-zone-done back-half rework):** *"Let's play with pan and reverb a bit more, especially in intro and break. Nothing cheesy or annoying, just… a little more space. Then snap back to the baseline when we get to verse/chorus."* The intent: the atmospheric sections (intro = the dawn polyrhythm cloud; break = the ethereal eureka suspension) get a wider image + a wetter Plate tail, returning to the baseline mix at verse1 and integration.

  **Why deferred (not a quick change).** `mixer_pan` + `send_level` envelopes are **session-clip routed** (Live 12.4 LOM — confirmed in `src/hallucinote/sync/pull/envelopes.py:237,406` and the `songs/sun-zone-done/sun-zone-done.md` "Deferred" note): each needs a hosting clip covering its beat range, exactly the constraint the Amp Type envelope hit (solved there by ONE monolithic 736-beat Rhythm Gtr clip). But the organ / lead / steel are authored as **per-section clips**, so a song-spanning pan/send envelope would have GAPS where those tracks are tacet (the metal choruses) — there is nothing to host the envelope across the gap. And the exact amounts ("a little more space") are render-gated to tune by ear. So it's a host-clip-strategy decision + automation authoring + a render pass, not a one-line tweak.

  **The ask.** Decide the host-clip strategy for per-section MIXER/SEND automation (the mixer analog of the Amp-envelope monolithic-clip pattern): either (a) give the automated tracks a monolithic clip to host their mixer envelopes, or (b) author per-section session-clip-routed envelope segments, or (c) a cleaner mechanism. Then author the first use: intro + break get an elevated Plate send + a slightly wider pan on organ/lead/steel, snapping to baseline at verse1 + integration. Couples to AUD-8H2M (the analyzer can't yet VERIFY time-varying mix moves landed in the render — same envelope-realization blind spot). Kept STATIC for v1 (conservative sends in `captured_session.json`).

  **Verifiable signal:** a decision-record naming the host-clip strategy for mixer/send envelopes + sun-zone-done authoring per-section pan/send automation for intro+break that returns to baseline (verifiable by the breakpoints in the DB; realization render-gated). **Sized:** medium. (user pan/reverb-space request, 2026-06-01)

- **[ARR-4V7P]** Vertical (inter-layer) harmonic constraint — the counterpoint near-miss
  `effort: M · impact: M · area: arrangement · source: review · added: 2026-05-30 · status: open · related: ARR-1H9C`

  Fugue/Bach is an instructive near-miss: the model's HORIZONTAL devices map beautifully (subject = motif, answer = transpose, stretto = overlapping motif references, augmentation/inversion = literal variation ops) — but the model is BLIND to the vertical constraint. Voices must form valid counterpoint when combined, and nothing represents or enforces consonance/dissonance BETWEEN layers. It scaffolds the entrances and gives zero help with the actual hard part. Per ruler/stamp a counterpoint GENERATOR is out (a stamp); the ruler-consistent move is a read-side vertical-interval / consonance ANALYSIS lens ("layers X and Y clash here — intended dissonance or error?"), the same shape as the masking analyzer. Representation of inter-layer harmonic constraint is tied to the harmony-axis decision (ARR-1H9C). **Verifiable signal:** a vertical-consonance analysis exists OR a decision-record says inter-layer correctness stays composer-owned at the note floor. **Sized:** medium. (arrangement-model counter-example review, 2026-05-30)

- **[ARR-3R8F]** Rhythm/feel collision as a first-class structural axis (the rhythm analog of ARR-1H9C)
  `effort: L · impact: M · area: arrangement · source: user · added: 2026-05-30 · status: open · related: ARR-1H9C`

  Raised by the user (2026-05-30, sun-zone-done): "rhythm is just as important in the world as harmony or melody." The harmony axis (ARR-1H9C) made tonal collision/resolution a recorded structural intent that the build realizes + a lens verifies. Feel/microtiming, by contrast, is per-generator-call only (deliberately, per `docs/song-authoring-conventions.md` — punk drums + lazy bluegrass guitar in one section is valid) — the arrangement model carries NO structural representation of a rhythmic *collision* or *resolution*. sun-zone-done needed exactly that (the development trades feel cell-by-cell mirroring its harmonic trade; the outro resolves into a new synthesized feel) and realized it via per-call feel + hand-recorded intent (`songs/sun-zone-done/decisions/07-rhythmic-collision-and-resolution.md`). The open question: is there a ruler-consistent first-class representation — e.g. a per-section / per-cell *feel intent* (drag / push / grid / swing) co-equal to energy + harmony that the build realizes and a read-side timing lens verifies (the rhythm analog of the harmony conformance lens, related to the cross-rhythm analyzer C8) — OR does feel correctly stay per-call with intent recorded in markdown? Grain is part of the decision (per-section? per-cell? per-part?). **Verifiable signal:** `arrangement-model.md` records a decision (substrate vs per-call+markdown) with rationale; if substrate, sections/cells can carry a feel-intent attribute. **Sized:** large. (sun-zone-done rhythmic-collision work, 2026-05-30)

  **Update (2026-06-01): second concrete data point — the integration PLAYGROUND.** Reinventing sun-zone-done's integration (decisions/08) needed exactly the missing thing: two worlds *interplaying* (call-response, half↔double-time trade, simultaneous interlock) at the bar/cell grain — not a whole-section genre, not a whole-bar harmony-driven trade (the development's `_dev_collision`). It was authored song-local (`_integration_play` + `INTEG_CELLS` in build.py), per the confirmed framework decision to keep interplay song-local until a second song needs it. This is now the SECOND song-local interplay site (development was the first). When this axis is designed, both should generalize from it. Tightly coupled to **GEN-1S4K** (the same gap viewed as generator-altitude — the toolkit's section-archetype builders forced the old "smash").

- **[ARR-2B6K]** Arrangement-model honest boundaries — unmetered / non-musical-axis / texture-mass
  `effort: M · impact: S · area: arrangement · source: review · added: 2026-05-30 · status: open`

  Three known boundaries from the counter-example review, recorded so they're tracked rather than silently assumed (the model degrades to the raw note floor for all three). (a) **Unmetered / free-rhythm** (Gregorian chant, Indian alap, recitative, rubato ambient): the bar-centric scaffold is ill-fitting; a future time-based (seconds / free-pulse) authoring mode could help. (b) **Non-musical organizing axis** (film/game picture-sync, text/liturgy through-composed, and generative/aleatoric/interactive where the piece is a process/ruleset — Eno, Cage, adaptive scores): OUT OF SCOPE BY DESIGN — process-as-primitive was deliberately excluded (ruler/stamp); document, don't build, unless product scope changes. (c) **Texture-mass / spectral** (Ligeti, Xenakis): the unit is a mass, not a motif/note; a future cloud/mass authoring helper could help. All three already noted in `arrangement-model.md` "What is deliberately NOT modeled." **Verifiable signal:** revisit only when a real target song needs (a) or (c); (b) stays documented-out. **Sized:** medium if ever built. (arrangement-model counter-example review, 2026-05-30)

- **[ARR-4M3T]** Meter changes as a first-class arrangement primitive (per-section / per-bar time signature — incl. a single 3/4 bar)
  `effort: L · impact: M · area: arrangement · source: user · added: 2026-06-02 · status: open · related: ARR-3R8F, ARR-8P5K, ARR-2B6K`

  Raised by the user (2026-06-02, sun-zone-done back-half). The arrangement model assumes one global 4/4 meter and places sections on **integer bar lines** — `src/hallucinote/arrangement.py` `plan()` accumulates `bar += s.bars` (ints), `section()` validates/stores int `bars`, and every song does its own arithmetic against a `BEATS_PER_BAR = 4.0` constant. There is no representation of a time-signature *change*, an odd meter (5/4, 7/8), or a single borrowed bar (e.g. one bar of 3/4). Note the DB layer is already ahead of the authoring layer: the mutators `add_arrangement_clip` / `create_section` / `add_cue_point` already take **float** bars, so the persistence model can represent odd boundaries today — the gap is in `plan()` / `section()` / the per-song beat math, not the store.

  **The concrete example (the motivating friction).** sun-zone-done's core rhetorical device is the reggae→metal RUDE INTERRUPTION ("chillin in the sun — NO TIME FOR THAT"): the chill should be SEVERED mid-bar and the metal kick the door in early. We shipped (2026-06-02) the **length-preserving "early slam"** — `_interrupt_tail(..., next_metal=chorus)` in `songs/sun-zone-done/build.py` pulls the chorus's opening slam (crash + gallop kick + pedal-bass door-kick) a beat early onto beat 4 of the verse's final bar ("on 4 rather than 1"), while the chill lead hangs unresolved and the chorus still confirms on its own downbeat. That gives the *felt* early arrival WITHOUT touching the grid (zero blast radius, render-gated, reversible). But it is NOT a true steal: the verse is still 24 full bars and the song length is unchanged. The user's desired ideal is the **literal** steal — *a single bar of 3/4 at the seam* that truly slides the metal forward and **shortens the segment / the song**.

  **Implications I called out (why this is L, not a quick patch).** Going from "felt early slam" to "literal 3/4 bar that shortens the song" means a section boundary lands on a non-4/4 beat, and **every absolute-beat consumer downstream shifts**:
  - **The monolithic Rhythm Gtr clip** (`_compose_rhythm_gtr`) computes `section_start_beats = (sec.start_bar - first_bar) * BEATS_PER_BAR` — assumes uniform 4/4; a 3/4 bar desyncs its seams from `arr.plan()`.
  - **The Amp Type envelope** breakpoint times (`_amp_segments`, absolute beats — `[(0.0,0.0),(160.0,5.0),(224.0,0.0),…]`) and any other absolute-beat automation move.
  - **Cue points + section bar ranges** become fractional; tests that assert exact bar/beat positions (the notes baseline, the amp-breakpoint list, `test_build_produces_canonical_shape` section ranges) all shift.
  - **Every read-side lens** (`theory.lint`, `performance.lens`, `melody.lens`) takes `beats_per_bar` as a single uniform value and reads strong beats / bar grouping off it — they must become meter-aware (per-section, ideally per-bar) or they'll mis-grade the odd bar.

  So the real deliverable is a **per-section (and ideally per-bar) time signature** carried on the arrangement (the natural home alongside energy/harmony), `plan()` doing beat-accurate placement instead of `bar += s.bars`, and the lenses + monolithic-clip + envelope math reading meter from the model rather than a constant. This is the foundation for odd meters and metric modulation generally — the 3/4 interruption is just the first concrete need. **BOTH SIDES** (house discipline, ARR-8P5K): an AUTHORING surface (declare a section/bar's meter) AND meter-aware reads (the lenses above, plus possibly a "does the metric displacement land where intended?" check). Friction-driven: build it when this (or a second odd-meter song) forces it; until then the early-slam is the recorded interim. **Verifiable signal:** `arrangement-model.md` records a meter-change decision with rationale AND either `Arrangement.plan()` places a non-4/4 section beat-accurately (a single 3/4 bar shortens the song's total beats) OR a decision-record states meter stays globally-4/4 with the early-slam as the sanctioned interruption idiom. **Sized:** large (model core + per-song beat math + lens meter-awareness + test re-baselining). (sun-zone-done interruption work, 2026-06-02)

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

  **Update 2026-05-31 (perf-lens phase 2a, branch feature/performance-lens):** follow-up **(a) the performance READ-side is SHIPPED** — `src/hallucinote/performance/` (lens + correlation + dynamics + ensemble): per-part timing deviation (push/drag/looseness), the human/sloppy 1/f-correlation metric (lag-1 acf primary + DFA α; calibration showed DFA unreliable below N≈48), flat-dynamics detection, articulation, and inter-part ensemble lock — render-free, pure stdlib, mirroring `theory/lint`, wired into `/mix-review`, validated on sun-zone-done (reproduces the flat-organ + feels-quantized findings; reads the white-jitter drums as *sloppy*). The "generalize the by-hand `microtiming_check.py`" framing is moot (no such file existed; authored fresh against performance-model §7). **Still open:** (b) the AUTHORING profile (the 2b grading-against-*declared*-intent + energy-coupling), (c) the audio-side 1/f + perceived-onset extension, (d) folding ARR-3R8F. Item stays `open` for (b)–(d).

  **Update 2026-05-31b (perf-authoring, branch feature/performance-authoring):** follow-up **(b) the AUTHORING side now has its FIRST PRIMITIVE** — `src/hallucinote/performance/realization.py` (`PerformanceProfile` + `apply_profile` + the promoted `pink_noise` generator + BREATH/HUMAN/LOOSE presets): the declared profile (magnitude-scaled, seeded, deterministic) realizes the GERM "Random" channel — small additive **1/f-correlated** timing + velocity breathing — over a finished part. Closed-loop validated through the *shipped* §7 lens: a mechanical part run through a profile reads `human` (not mechanical, not sloppy), de-flattens dynamics, and the verdict is magnitude-invariant (structure, not size — the design's decisive claim, now a regression). 17 new tests; the `pink_noise` generator was promoted from the calibration test fixture into production so the correlation constants describe what `apply_profile` actually emits. **Still open within (b):** the genre-baseline as a *declared profile field* (lay-back stays the generators' job today — one source of truth) + the energy↔performance coupling (§5) + phrase-arc curves (§4.3); plus the lens reading the *declared* profile for conformance (today it reads authored notes, not declared intent). The flagship *tune-by-ear* pass (which parts, what `k`) is deliberately left for the user's ear, not auto-applied. Item stays `open` for the rest of (b) + (c)–(d).

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

- **[EVL-9R3T]** Refresh the stale pre-melody-analysis scenario-eval snapshots (retention policy DONE)
  `effort: S · impact: S · area: eval-harness · source: critic · added: 2026-06-01 · status: open · related: MEL-1A7K`

  (1) **Retention policy — DONE (2026-06-01).** `tests/scenarios/results/` now pins the latest-passing `canonical-<brief>.json` per brief (committed, durable evidence for the non-unit-testable onboarding work) + its `canonical-<brief>.transcript.md` (the latest transcript, reviewable for judge-tuning); ad-hoc timestamped runs are gitignored. `write_result(canonical=True)` writes the stable name; policy documented in `tests/scenarios/results/README.md`; the 10 prior timestamped results were migrated (latest per brief → canonical, older dupes dropped). (2) **Stale snapshots — OPEN.** `canonical-priya.json` + `canonical-elena.json` were judged on 2026-05-31 under the *old* melody framing ("melody is my thin spot" as PASS); the briefs now carry the two-sided authoring-vs-analysis rubric (MEL-1A7K phase 2a), so a fresh scenario-eval pass should re-grade them (LLM-simulated persona role-play + judge — not deterministically regenerable, hence deferred, never hand-edited; canonicalize the passing re-run via `write_result(canonical=True)` + save its transcript). **Verifiable signal:** fresh `canonical-priya.json`/`canonical-elena.json` dated post-2026-06-01 against the updated briefs. (Critic cumulative note + melody phase-2a 2026-06-01)

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

- **[DEV-4X2N]** `ableton_analysis(action='extract')` flattens only top-level device chains; no test pins the exclusion
  `effort: S · impact: S · area: device · source: critic · added: 2026-06-01 · status: open · related: DEV-7K4H`

  The structural-dump handler (`hallucinote_mcp/.../handlers/analysis.py:_extract_song_structure`) collects devices via `get_devices_for_track` / `get_devices_for_return`, which by design don't recurse into nested rack chains (one-level via `get_device_chains_for_rack_device`; recursive racks unmodeled — see DEV-7K4H). The caveat is documented in the handler docstring + action tips, but the `_seed_full_song` test fixture builds only a top-level chain, so a regression that started dropping rack containers wouldn't be caught. When nested-rack pull lands (gated on `hallucinote-mcp` `get_device_chains`), extend the extract to flatten nested chains and add a seed with an Instrument/Audio-Effect Rack. **Verifiable signal:** `_seed_full_song` (or a sibling fixture) builds a nested rack and a test asserts the extract's device shape for it. (Critic note, extract-action 2026-06-01)

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

- **[ARR-7M3D]** Energy-realization is unmeasured in audio (declared curve vs rendered intensity) — measurement-coverage gap
  `effort: M · impact: L · area: energy · source: user · added: 2026-06-01 · status: open · related: ARR-8P5K`

  **Both-sides gap (ARR-8P5K's own principle: "a dimension authored but unmeasured is half-built").** ENERGY is a first-class authored dimension — `Arrangement.section(..., energy=)` → `arr.energy_curve` (sun-zone-done declares 0.25→1.0 across 9 sections). The READ side is only *symbolic*: `/compose-review` reads whether the authored curve "builds, breathes, peaks" from build.py/arrangement (SKILL.md L61) — it never checks the audio. The MixReport measures per-section loudness (`audio/analyze.py` `_measure_sections` → `SectionMetrics`) but **nothing joins the two**: no tool confirms the declared energy[section] is actually realized as rendered intensity (loudness + spectral density + onset rate). A section authored energy=0.9 that renders quieter/sparser than an energy=0.6 section ships unflagged — the exact "is the chorus actually lifting?" question, gone dark on the audio side. Harmony (ARR-1H9C conformance lint) and performance (perf lens) both got the realization check; energy did not.

  **Verifiable signal:** a read-side check exists that takes the arrangement's `energy_curve` + a MixReport and reports per-section declared-vs-measured intensity divergence (rank-correlation of declared energy against measured loudness/density, flagging inversions), wired into `/mix-review`; OR a decision-record states energy-realization stays a by-ear judgment with rationale. Today: no reference to the authored `energy_curve` anywhere in `src/hallucinote/audio/` — the curve never reaches the audio analyzer (the incidental `energy` hits there are all acoustic/spectral energy, a different quantity).

- **[ARR-9K4T]** Recurrence/form has no read-side — motif recall & recapitulation are authored but unverifiable — measurement-coverage gap
  `effort: M · impact: L · area: recurrence · source: user · added: 2026-06-01 · status: open · related: ARR-8P5K, MEL-1A7K`

  **Both-sides gap.** RECURRENCE/FORM is a first-class authored dimension — `Arrangement.motif()` + `vary()` + reference — and recapitulation is load-bearing in sun-zone-done (the integration QUOTES the registered `polyrhythm-cloud` motif; the outro AUGMENTS the `no-time-stab` motif via `V.augment`). The AUTHORING side is shipped; the READ side does not exist. **No tool verifies a registered motif was actually recalled, detects a recapitulation, or measures motivic economy** (is the song built from a small recurring cell-set, or scattered?). The melody lens's motivic/n-gram reading is explicitly NOT-YET (`melody/lens.py:48-50`) and is line-level anyway; this gap is the *cross-instrument / arrangement-level* recurrence read (e.g. "the integration organ's notes ARE `shift`s of the polyrhythm motif — confirmed"). MEL-1A7K owns the melodic-LINE motivic-economy slice; this is the structural recurrence-realization sibling under ARR-8P5K.

  **Verifiable signal:** a read-side that, given an arrangement, reports which registered motifs recur where (and as which variation: transpose/augment/invert/…) plus a motivic-economy summary, wired into `/compose-review`; OR a decision-record states recurrence-realization stays composer-owned with rationale. Today: no motif-recall / recapitulation reader exists in `src/hallucinote/` analysis or lens code (the few incidental `recur` substring hits are unrelated).

- **[SYN-4P2D]** First push of a >8-section song into a fresh default Live set hard-fails — set ships with only 8 scenes, push doesn't auto-create them, raw per-clip IndexError
  `effort: S · impact: L · area: sync · source: user · added: 2026-06-01 · status: open`

  **Recurring first-push trap (user, 2026-06-01: "a real gap that will bite us over and
  over").** A default Ableton Live set ALWAYS ships with exactly 8 scenes, so the FIRST
  push (auto-session, fresh set) of ANY song with >8 sections fails *deterministically*
  at the `clips` phase — this is the common new-song path, not an edge case.
  Hit live pushing sun-zone-done (9 sections) into a fresh default Live set (8 scenes,
  2026-06-01). The `clips` phase creates one session clip per section in scene slots
  1..N; if the set has fewer than N scenes, every section-N clip fails with
  `ableton_clip('create') failed: IndexError: clip_index 9 out of range [1, 8]` (one per
  affected track — here 5), halting `execute` at `clips` (4/10 phases). The push does
  NOT create the scenes it needs, and the failure surfaces as N raw per-clip IndexErrors
  rather than one actionable message. Workaround that unblocked it:
  `ableton_scene(action='create')` to add the 9th scene, then re-run execute (idempotent).
  Fix options (pick one): (a) the planner emits a `scenes` phase ensuring
  `scene_count >= max section slot` before `clips`; (b) `clips` auto-creates a missing
  slot on demand; (c) at minimum a pre-flight coherence check that fails fast with "song
  needs N scenes; set has M — add N−M" instead of per-clip IndexErrors. **Verifiable
  signal:** push a ≥9-section song into a default 8-scene set and it completes (or fails
  with the single actionable message), not 5 raw IndexErrors.

  **Dedup note (2026-06-03):** absorbs the PSH-1S9C dogfood duplicate (same bug — a >8-section song pushed into a fresh default 8-scene set hard-fails at the `clips` phase because the push doesn't auto-provision scenes). PSH-1S9C dropped with `closes: SYN-4P2D`.

- **[SNG-4H2D]** Migrate the existing composed songs' `build()` lifecycle to the shared `run_build` harness
  `effort: S · impact: S · area: song-tooling · source: builder · added: 2026-06-03 · status: open · related: GEN-1S4K`

  Follow-up to the 2026-06-03 helpers DRY hoist (user-raised: "every song's build.py duplicates helpers like get-track-id-from-name"). That pass hoisted the duplicated HELPER FUNCTIONS into the library (`Q.tracks_by_name` / `Q.returns_by_name` in `db/queries.py`, `arrange_section` in `hallucinote/authoring.py`) and migrated all four songs to use them; it also added `hallucinote.authoring.run_build` (the open-DB → optional soft-reset → `build_session` → close lifecycle every `build()` repeats) and adopted it in the `/song-new` scaffold template (so every NEW song is DRY by construction) + covered it with unit + scaffold-e2e tests.

  **Deferred here:** the three *existing composed* songs (`falling-walking`, `full-band-rock`, `sun-zone-done`) + `missing` still carry the explicit `conn = init_db; try; … with build_session; finally close` harness inline. Migrating them to `run_build` means wrapping each `build()` body in a `compose(conn)` closure — a whole-body reindent (sun-zone's is ~90 lines), which is churn-heavy and reindent-risky for modest gain, so it was left as its own focused change rather than bundled into the philosophy PR. Behavior-preserving + fully test-caught (each song's build test + the converger test rebuild it). **Verifiable signal:** no song `build.py` contains `conn = init_db(DB_PATH)` / `with M.build_session(` inline — all delegate to `run_build`. **Sized:** small (mechanical, per-song, test-gated). (helpers DRY hoist follow-up, 2026-06-03)

## Promoted

_(no items)_

## Archive

Closed investigations — no fix possible / structural-close on Ableton's roadmap. Kept for search so a future scrub doesn't re-open them without new evidence. Status `dropped` = investigated and intentionally not pursued; `shipped` = built and closed.

- **[WSP-1K4D]** Route the render captures dir through the project-root contract (`server.py` `songs/` literal)
  `effort: S · impact: S · area: mcp-render · source: critic · added: 2026-06-03 · status: shipped · closed-by: feature/songs-split · related: project-root-contract`

  The render `output_dir` default (`server.py` `_absolutize_render_output_dir`) defaulted to `Path("songs")/<slug>/"captures"/<ts>` off `os.getcwd()`. SHIPPED (feature/songs-split): it now resolves the song dir via `resolve_song_dir(<slug>)` (guarded import; the residual `os.getcwd()/songs/<slug>` at `server.py:280` is the deliberate engine-absent fallback for a uvx MCP-only install), so captures travel with the resolved song dir.

- **[MIX-6K2P]** Track-mixer volume/pan should be dB-aware on the MCP surface
  `effort: S · impact: M · area: mcp-mixer · source: builder · added: 2026-05-30 · status: shipped · closed-by: feature/mixer-db-surface`

  Surfaced during sun-zone-done mix work. `ableton_device(action='set_parameter')` already accepts `value_display='-3.5 dB'`, but `ableton_track(action='set_property', property='volume')` was raw-0..1-float only and `info` reported only the raw float — so any agent doing dB-native mix thinking had to hand-apply Live's nonlinear fader curve. **Verifiable signal:** `ableton_track(action='set_property', property='volume', value_display='-8 dB')` resolves to v≈0.65; `ableton_track(action='info')` returns a `volume_db` field. **Sized:** small. (sun-zone-done mix session 2026-05-30)

  **Shipped 2026-06-01 (feature/mixer-db-surface):** `set_property volume`/`panning` now accept `value_display`; `info` reports `volume_db` (null when muted); the response echoes the achieved `value_display`. **Architecture deviation from the original note (reuse `levels.py`):** `levels.py` lives in the main `hallucinote` package and imports numpy; the MCP server is deliberately stdlib-only (`mcp>=1.0` sole dep, fully isolated from `hallucinote`). Importing it would break that boundary. Instead the conversion reuses Live's OWN native fader curve via the existing `handlers.display_value.solve_raw_for_display` (the same numeric `str_for_value` inverter the device `set_parameter` already uses) — exact, no numpy, no duplication. The shared continuous-write contract `_resolve_continuous` was hoisted to `display_value.resolve_continuous_write` so device `set_parameter`/`set_parameter_in_rack` AND track volume all share one implementation (no lock-test needed — single source). `volume_db` reads via the new `display_value.display_number_for`. Snapshot capture gets `volume_db` for free (the `/song-snapshot` probe builds from `info` responses); the DB store stays Live-native normalized float (no data-model change, as the note required). Pan has no dB sense, so no `panning_db` and pan `value_display` is refused with a teaching error. 19 new tests; full suite 2813 green. Cumulative Critic at PR time per `feedback_critic_cadence_for_small_chunks`.

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

- **[AUD-3T6L]** Reverb RT60 tolerance (±0.15 s) is too tight for in-mix intent-matching
  `effort: S · impact: M · area: audio · source: verification · added: 2026-06-02 · status: pending`

  Reverb verification compares the measured decay-tail RT60 against the composer's declared INTENT (Plate 3.0 s, Room 0.8 s) with a fixed ±0.15 s band (`REVERB_TOLERANCE_S`). With the ring-out anchor fixed, sun-zone-done measured A-Plate **3.37 s vs 3.0** and B-Room **1.26 s vs 0.8** — both flagged out-of-tolerance. But (a) Live's Reverb RT60 is a nonlinear function of Decay Time + Room Size + diffusion, so the realized RT60 legitimately diverges from the nominal device knob, and (b) in-mix measurement at low wet SNR carries real error. A ±0.15 s ABSOLUTE band is unrealistically tight. Consider a relative tolerance (~±15–20 %), an SNR/span-aware confidence band, or reframing as a "decays N % longer/shorter than intent" producer's note rather than a binary verdict. **Verifiable signal:** a sub-0.5 s realized-vs-intent gap on a clean (high-span) capture no longer reads as a hard warning. **Sized:** small. (reverb verification session 2026-06-02)

- **[AUD-7D2P]** sun-zone-done open set diverges from the authored reverb device (stock Reverb vs Hybrid Reverb)
  `effort: M · impact: M · area: audio · source: verification · added: 2026-06-02 · status: pending`

  During reverb verification the open Live set's A-Plate return carried Live's **stock Reverb** (Decay Time knob 2.5 s), but `captured_session.json` authored a **Hybrid Reverb**. So the in-mix RT60 verdicts (A-Plate 3.37 vs intent 3.0; B-Room 1.26 vs 0.8) were measured against a device that ISN'T the authored one — the set was never re-pushed from the rebuilt DB, or the Hybrid Reverb load fell back to stock. Before treating any reverb-vs-intent gap as a real authorship issue: re-push sun-zone-done from the DB so the AUTHORED devices are measured, then re-run render+analysis and re-assess. Also confirm whether the Hybrid Reverb load path is reliable (did the push silently fall back to stock?). **Verifiable signal:** the A-Plate return device class matches `captured_session.json` (Hybrid Reverb) after a fresh push. **Sized:** medium. (reverb verification session 2026-06-02)

- **[SNG-D1FF]** "Diffusion" — a denoising-as-form song (+ a target-chord noise-schedule generator)
  `effort: L · impact: M · area: song · source: user · added: 2026-06-03 · status: pending`

  **Concept:** the song is structured like a diffusion/denoising model. There is a single massive
  TARGET chord the whole piece resolves to at the very end. Over the song, the music plays only tiny
  fragments of it — and at the start those fragments are deliberately "wrong" notes (noisy, out-of-chord,
  scattered). As it progresses the fragments coalesce toward the true chord: wrong notes get rarer,
  in-chord notes denser/more confident, until the final reveal lands the full sonority cleanly.

  **Why it's interesting:** form = a denoising schedule. The "noise level" is a real, authorable curve
  (probability of a wrong note + scatter of timing/register), monotonically decreasing — maps naturally
  onto authoring-as-code (a per-section noise parameter that biases pitch selection toward/away from the
  target chord's tones).

  **Open design questions:** what's the target chord (rich/polytonal?); is the schedule linear or does it
  have plateaus/setbacks (a few "reverse-diffusion" moments where it gets noisier for drama?); do rhythm +
  density also denoise (arrhythmic → locked)? single timbre or does instrumentation resolve too? how long
  (the reveal needs runway to feel earned).

  **Possible new capability:** a "target-chord-with-noise-schedule" generator primitive (bias note pitches
  toward a chord by a 0→1 coalescence parameter) — reusable beyond this song. (user idea 2026-06-03)
- **[AUD-6R2M]** Reverb verification is ill-posed for multi-source returns (the real RT60 blocker)
  `effort: M · impact: M · area: audio-analysis · source: dogfood · added: 2026-06-02 · status: shipped · reviewed: 2026-06-03 · closed-by: 515c6ab (merge fix/reverb-rt60-decay-tail) · related: AUD-1C7K, AUD-4S8T`

  Found while validating the AUD-1C7K alignment fix on a real sun-zone-done capture (2026-06-02). With capture alignment now sample-exact (proven by a known-offset calibration — δ=0), reverb verification STILL returns garbage RT60 (A-Plate measured ~50s vs declared 3.0s). Cause is **multi-source contamination**, not alignment: `_declare_reverb_intent` declares RT60 on *every* audible send into each return, so A-Plate / B-Room are each fed by many tracks at once. The wet return is `IR ⊗ (drums + gtr + lead + …)`; `verify_reverb_send` deconvolves it by a SINGLE dry stem, leaving the other sends as unexplained signal → a noise-like "IR" → a 46–53s RT60. The single-dry-source deconvolution assumption (spike §7 / Chunk 3) doesn't hold for real multi-send reverb buses.

  **Fix directions (pick after design):** (a) deconvolve the return against the SUM of its declared dry sources (gain-weighted by send level) instead of one; (b) a dedicated single-source verification send (mute other sends, or a transient probe); (c) a non-deconvolution RT60 estimate (Schroeder/EDT on the return's own decay after a gate, no dry needed). **Verifiable signal:** `verify_reverb_send` (or its successor) returns a physically-plausible RT60 (within tolerance of declared) on a multi-send reverb return in a real capture. (AUD-1C7K validation, 2026-06-02)

  **SHIPPED on develop (commit 515c6ab, merge `fix/reverb-rt60-decay-tail`).** Replaced single-dry deconvolution with per-return decay-tail RT60 (`audio/reverb.measure_return_rt60`, dry-source-free). The successor refuses to fabricate (`sufficient_tail=False`) when there's no ring-out — which is why AUD-4S8T (capture the ring-out) was done alongside.

- **[PSH-1S9C]** Push should provision (or pre-check) session scenes for clip slots — halts mid-`clips` on a fresh set instead of failing fast
  `effort: S · impact: M · area: sync · source: dogfood · added: 2026-06-01 · status: dropped · reviewed: 2026-06-03 · closes: SYN-4P2D · related: AUD-8H2M`

  Found dogfooding the sun-zone-done push (2026-06-01, first full push to a fresh set). The song has 9 sections → session clips land at slot indices 1–9, but Live's default fresh set has only 8 scenes, so `ableton_clip('create')` raised `IndexError: clip_index 9 out of range [1, 8]` for the 5 `outro` clips (drums/bass/organ/lead/steel). The push **halted mid-`clips` (32/37)** — phases 5–10 never ran. Manual fix: `ableton_scene(action='create')` to add a 9th scene, then re-run `execute` (idempotent — it recovered cleanly, all 10 phases). Two ruler-consistent fixes: (a) the `clips` phase auto-provisions scenes up to the max required slot before creating clips (the planner knows the slot count), or (b) the `--probe` coherence check counts Live's scenes vs the max clip slot and **fails fast with a clear message** ("song needs 9 scenes, set has 8 — add scenes or shorten") rather than halting partway. Prefer (a) — the push already mutates the set; provisioning scenes is in-scope and removes a manual step for every 9+ section song. **Verifiable signal:** a fresh-set push of a ≥9-section song completes without manual scene creation, OR the coherence check refuses pre-dispatch with a scene-count message. **Sized:** small. (sun-zone-done first-push dogfood, 2026-06-01)

- **[DEV-2M9K]** `ableton_device(action='load', master=true)` no-ops — can't add master-bus devices via the bridge
  `effort: S · impact: M · area: device · source: dogfood · added: 2026-06-02 · status: shipped · reviewed: 2026-06-03 · closed-by: #129 (commit de34b8c) · related: SYN-2M9P`

  Found during sun-zone-done mix-review (2026-06-02): loading a device onto the MASTER strip silently no-ops — `RuntimeError: load: Live did not append a device on master 0 after browser.load_item. Existing chain: [(empty)]` — even on an EMPTY master chain (so it's not the "matching class already present" no-op the error guesses). Track/return loads work fine; master device-PARAMETER writes work fine (`set_parameter`/`get_parameters`/`delete`/`list` with `master=true` all succeed); only `load` on master is broken. Likely cause: the load handler routes `browser.load_item` to `song.view.selected_track` and, for `master=true`, never selects `song.master_track` first (track/return loads select their track, so they work) — so the load targets nothing. **Impact:** no master-bus mastering chain (limiter, master EQ, glue comp) can be authored through the bridge. Blocked the user's chosen clipping fix (a −1 dBTP master limiter); worked around by EQ low-end cleanup + (pending) a manual one-drag Limiter the user adds, after which `set_parameter master=true` configures it. **Fix is likely small** (select `master_track` before `load_item`, mirror the track path) **but testing it needs a full Live quit+reopen** — Live caches Control Surface modules ([[project_mcp_reconnect_workflow]]) — so iterating is a restart loop; lives in `hallucinote_mcp` ([[project_mcp_server_stdlib_only]]). **Verifiable signal:** `ableton_device(action='load', master=true, kind='Limiter')` appends a Limiter to the master chain on both an empty and a non-empty master. **Sized:** small (one selection fix + a Live-restart test cycle). (sun-zone-done mix-review, 2026-06-02)

  **ROOT CAUSE CONFIRMED (2026-06-02).** `load_handler` (`hallucinote_mcp/.../handlers/device.py:750-751`) does `view.selected_track = parent` then `browser.load_item(item)`, with `parent = song.master_track` for master. **Live silently refuses to set `selected_track` to the master track** — the assignment doesn't take — so `browser.load_item` loads onto whichever *regular* track was previously selected. The post-load check then inspects the *master* chain, sees no new device, and raises the misleading "did not append on master" — while the device actually landed on the selected regular track. PROVEN: after several failed master-loads, track 6 (Steel) held two stray `Limiter`s + a stray `HallucinoteAnalyzer` (cleaned up). "Works once" = the first master-load of a session lands correctly because no regular track is selected yet; once any regular track gets selected, every master-load mis-fires. **Fix direction:** after `view.selected_track = parent`, assert `view.selected_track is parent`; if Live didn't honor it (master case), do NOT call `load_item` (it mis-targets) — either find the correct master-load mechanism (research: can Live's API add a device to `master_track` at all?) or fail loudly. The render's master-analyzer auto-load needs the same fix (or a master-specific path). Needs Live quit+reopen to test the Remote Script change ([[project_mcp_reconnect_workflow]]).

  **Severity note (2026-06-02): `ableton_render` master capture silently depends on this.** The render's "auto-load HallucinoteAnalyzer on every track + return + master (idempotent)" uses the same broken path for the master, so it has NEVER actually loaded the analyzer there — it only works because the analyzer persists in the saved `.als` from an earlier placement ("auto-load" = load-if-missing; on the master it was never missing). Confirmed by deleting the master analyzer mid-session: the render then failed to re-add it with the identical `browser.load_item` error. So **rendering the master on a genuinely fresh set (no pre-saved master analyzer) is also broken**, not just adding mastering devices — this is a render-pipeline dependency, not only a convenience gap. Recovery without the fix = a human re-adds the analyzer (and any master device) by hand in Live.

  **SHIPPED on develop (#129, commit de34b8c).** Master device-LOAD now refuses loudly (no silent mis-target onto a regular track) and the render master-analyzer is detect-only — master devices are place-by-hand-once / configure-only across the stack. NOTE: the push-PLANNER follow-up — `plan_push_devices` still emits impossible `device.load(master=true)` calls that halt the devices phase at execute time — remains tracked separately as **SYN-2M9P**.

- **[AUD-1C7K]** Sample-accurate capture alignment — per-surface WAVs are NOT the same length (breaks reverb verification)
  `effort: M · impact: M · area: audio-analysis · source: user · added: 2026-06-02 · status: shipped · reviewed: 2026-06-03 · closed-by: #130 (commit 1bbac6a) · related: AUD-5M8H, AUD-2D6T, AUD-4S8T`

  Raised by the user (2026-06-02, sun-zone-done v4 full render). `ableton_render` captures each surface (every track + return + master) through its own `HallucinoteAnalyzer` / `sfrecord~` instance, and each one **finalizes independently** — so the per-surface WAVs come out at DIFFERENT lengths. Observed in `songs/sun-zone-done/captures/v4-full/`: frame counts climbed monotonically by ~512/surface in capture order — `01 Drums` 11784704 … `master` 11792384, a spread of **7680 frames (~0.16s @ 48kHz)**. They are not sample-aligned.

  **Impact (concrete, today).** `ableton_analysis(analyze)` hard-fails: *"dry and wet must be the same length; got dry=11784704, wet=11789824 — the analyzer's PDC alignment should guarantee this."* The reverb verification (Wiener-deconvolved IR + RT60) needs the dry stem (a track) and the wet stem (its return) to be identical length; the independent-finalize spread violates that. The workaround — trim every WAV to the min length — let `analyze` run but the misalignment then **broke the deconvolution itself** (garbage RT60 ≈ 364s, 11 false `reverb_out_of_tolerance` findings). So loudness + overshoot attribution survived, but ALL reverb verification was unusable for the v4 review. Misalignment also silently smears any future cross-stem phase/timing analysis.

  **User's proposed direction (the WHY — capture it):** make all captures latch on a **common clock / external sync event** rather than each detecting transport-cross independently — e.g. broadcast a single transport-cross trigger to every `sfrecord~` so they start (and stop) on the same sample, and/or encode an absolute sample timestamp into each capture so the analyzer can align post-hoc to sub-millisecond accuracy. A common sample-accurate start+stop yields identical lengths *by construction* — no trim, no deconvolution smear. Touches the Max/Live-side capture patch (`sfrecord~` triggering) + the analyzer's PDC-alignment contract; lives in `hallucinote_mcp` (stdlib-only server [[project_mcp_server_stdlib_only]]) + the Max patch. **Verifiable signal:** a full render produces per-surface WAVs of IDENTICAL frame count (or a recorded per-surface sample-offset the analyzer honors), and `ableton_analysis(analyze)` runs on a fresh capture with reverb verification producing physically-plausible RT60s (no length-mismatch ValueError, no trim workaround). **Sized:** medium (Max-patch sync trigger + analyzer alignment contract + a length-equality assertion in the capture manifest). (sun-zone-done v4 full-render mix review, 2026-06-02)

  **SHIPPED on develop (#130, commit 1bbac6a) — read-side.** `trim_to_common_length` trims captured surfaces to a common length so `ableton_analysis(analyze)` runs (starts are sample-aligned; only tails differed). NOTE: the source-side cause — the per-surface stop-ramp that makes WAVs unequal-length in the first place — is NOT fixed here; it remains tracked as the open residual **AUD-4S8T** (read-side trim handles it for now).

- **[AUD-8H2M]** Time-varying automation (sends / volume / device-param flips) is authorable but its audio realization is unverifiable — measurement-coverage gap
  `effort: M · impact: M · area: audio · source: user · added: 2026-06-01 · status: shipped · reviewed: 2026-06-03 · closed-by: 256c5cb · related: MSK-8R3D, ENV-1T9M, ARR-8P5K, AUD-3F8M`

  **Both-sides gap.** The framework authors time-varying envelopes — `M.create_enum_envelope` (sun-zone-done's Amp Type Clean↔Heavy genre flip), `generators.envelopes.volume_swell` / `sidechain_trigger`, and (planned) dynamic sends. The audio analyzer **cannot verify any of these were realized in the render**: `audio/levels.py:13-15` explicitly DEFERS volume automation ("a stem that ducks under one section reads slightly hot — deferred"); MSK-8R3D(a) notes the same static-fader caveat narrowly. So the song's single most audible gesture — the Amp Type flip into HEAVY at the metal sections and the break — is never confirmed to have happened in audio, and a dry-reggae/wet-metal dynamic send (decision 05, deferred) would be equally invisible. A time-varying mix/timbre move is authored-but-unmeasured.

  **Verifiable signal:** a MixReport pass that windows a stem around a declared envelope breakpoint and confirms the expected change (level step for volume/send, spectral/timbre shift for an Amp/device-param flip), reporting realized-vs-declared; OR a decision-record scoping automation-realization out with rationale. Today: `audio/levels.py:15` ("volume automation … deferred"); no envelope-aware section windowing in `audio/analyze.py`.
  **SHIPPED on develop (commit 256c5cb).** `audio/automation.py` windows each declared envelope breakpoint; `device_parameter` (Amp flip) → directional spectral-centroid shift, `send_level` → level step; `MixReport.automation_verifications` + `automation_not_realized` finding. NOTE: `mixer_volume`/`mixer_pan` are reported `measurable=False` (post-fader → invisible to the pre-fader stem) — verifying those needs **master-bus windowing**, tracked separately as the follow-up **AUD-3F8M**.

- **[RND-7K3M]** Render silently burns the full wait window when Live's audio engine is OFF — no pre-flight, no actionable cause (CRITICAL)
  `effort: S · impact: L · area: render · source: user · added: 2026-06-01 · status: shipped · reviewed: 2026-06-03 · closed-by: #122 (commit 026d59d)`

  **SHIPPED (fix/render-audio-engine-preflight):** structural transport-advance
  pre-flight added to `render_handler` — after `start_playing()` it samples
  `current_song_time` over ~0.5s; a frozen transport raises fast with the
  audio-engine cause (re-select output / Options ▸ Audio Engine On) instead of
  blocking the full ~song-length window. The LOM exposes no engine flag (verified by
  introspecting `song`+`application`), so the transport-advance probe is the detector.
  Unit-tested via a new `_engine_check` seam + a direct `_default_engine_preflight`
  test (no Live needed). **Pending (honest-confidence):** live verification of the
  engine-off path requires re-vendoring the Remote Script (`/ableton-mcp-install`) +
  a Live restart so the running surface picks up the new handler — deferred to the
  user's next Live session. Also not addressed: a mid-render stall (engine on then
  driver hiccup) still waits the full `max_wait_s` (the beats×5-as-seconds heuristic
  is over-generous) — a separate, rarer follow-on.

  **User-flagged CRITICAL (2026-06-01): "renders can fail because no audio engine, but it
  doesn't tell you, so it takes a long time."** When Live's audio engine is OFF (e.g. the
  output device vanished — headphones unplugged — Live shows "the audio engine is off" and
  refuses to play), `ableton_render(action='render')` still arms, issues play, and WAITS
  THE FULL transport window for `current_song_time` to reach `stop_at_beat`. The transport
  never advances, so it burns the entire ~song-length wait (~4 min for a 184-bar song) and
  returns `status='incomplete'` with only a vague "Live's audio thread may have stalled"
  hint — never naming the real cause. Fix: PRE-FLIGHT the transport/engine before the long
  wait — (a) after seek+play, confirm `current_song_time` advances within a short probe
  (~1–2 s) and abort fast with "transport not advancing — is Live's audio engine on? (check
  the output device / Options ▸ tick 'Audio Engine On')"; and/or (b) read the engine-on flag
  from the LOM if exposed. Fail in seconds with the real cause, not minutes with a vague one.
  **Verifiable signal:** start a render with the audio engine off → it aborts within a few
  seconds naming the audio-engine cause, not after the full song-length window.
- **[GEN-1S4K]** Generators operate at too high an altitude — section-archetype builders lock composition into "sections" instead of musicality (creativity ceiling) (**HIGH PRIORITY** — user)
  `effort: L · impact: L · area: generators · source: user · added: 2026-06-01 · status: shipped · reviewed: 2026-06-03 · closed-by: feature/sun-zone-back-half · related: ARR-3R8F, GEN-2T8M, ARR-8P5K, GEN-5K2D`

  **Raised by the user (2026-06-01, during the sun-zone-done back-half rework), two messages, verbatim:**
  > *"I'm worried about this reliance on generators. We shouldn't be limited to what they can do; they are only meant to make repetitive tasks easier."*
  > *"your comment about generators building a 'whole reggae section' or 'whole metal section' is proof — we are generating at too high of a level, or at least locking ourselves into song sections rather than musicality."*

  **The symptom that triggered it (the proof / worked example).** sun-zone-done's `integration` section came out as a *smash*, not a fusion: `met("integration")` emitted a whole-metal-section (gallop drums + 16th pedal bass + NO-TIME lead) and the reggae organ was merely *layered over* it. The intended "integration" was the protagonist *combining* the two worlds — active-while-relaxing, discovery/play. But the available toolkit offered only **whole-section builders** (`_reggae_layers` / `_metal_layers` → the `reg()` / `met()` helpers in `songs/sun-zone-done/build.py`) or a **whole-bar trade** (`_dev_collision`, also song-local). There was **no vocabulary for interplay** — call-and-response, half/double-time dialogue, simultaneous interlock of two worlds. So the only move the abstractions afforded was *superposition*. The smash is the direct artifact of the altitude problem (ARR-3R8F is the same gap viewed from the rhythm-axis side).

  **The diagnosis.** Generators have crept UP to the altitude of *section / genre archetypes* ("a reggae section", "a metal section") rather than *musical building blocks*. Three consequences:
  1. **The vocabulary is shaped like templates, not primitives.** To compose you reach for "give me a reggae section," which bakes a bundle of decisions (which parts play, which idioms, density, feel, how they relate) into one call.
  2. **It forces section-level thinking.** You assemble *sections*, not music. Anything living BETWEEN or ACROSS archetypes — interplay, partial blends, a part borrowing one world's feel + another's harmony, a 2-bar idea that isn't a "section" — has no purchase.
  3. **It caps creativity (the load-bearing concern).** Generators were meant to remove *repetitive bookkeeping* (place a one-drop on the kit's pads; voice a `Progression` as a skank) — a *ruler*. But the section-altitude helpers (`reg`/`met`/`_reggae_layers`/`_metal_layers`) make *arrangement decisions* (which instruments, how they relate) — a *stamp* (violates great-art-not-software / ruler-not-stamp). When the composer's intent doesn't match the archetype, the archetype fights them, and the path of least resistance is to accept the archetype — so the tool quietly narrows the music.

  **The tension to investigate (the open question).**
  - What is the **right altitude** for a generator/helper? The stated rule is "only to make repetitive tasks easier" (bookkeeping / ruler) — yet `_reggae_layers` et al. encode arrangement decisions (stamp). Where exactly is the line, and how do we keep helpers below it?
  - Are **section-archetype builders the wrong abstraction**? Should composition assemble from *finer musical primitives* (a kick pattern, an offbeat-skank rhythm, a voicing strategy, a feel offset) that the composer/LLM combines freely — rather than from pre-bundled "sections"?
  - The altitude problem exists at **two levels**: the section-builders are *song-local* (`build.py`), but even the *package-level* idioms (`reggae_one_drop`, `metal_gallop`, `reggae_skank`, `organ_bubble`, `palm_mute_power_chords`) bundle a genre's pattern + feel + velocity together — convenient, but coarse. Decide whether the package should ever ship genre-bundled idioms at all, or only genre-neutral primitives + composer-supplied parameters.
  - Couples to **GEN-2T8M** (LLM-direct vs deterministic transform — same "is the helper making the musical decision?" test), **ARR-3R8F** (rhythm/feel collision — the very interplay we couldn't express), **ARR-8P5K** (axis/altitude refactor), and the principles `feedback_prefer_llm_over_deterministic_module` + `feedback_great_art_not_software`.

  **What it should produce.** A recorded design position (a `docs/`/`.prawduct/artifacts/` decision-record) on **generator altitude / the ruler-stamp boundary for helpers** — what altitude helpers may operate at, whether section-archetype builders should be deprecated/refactored toward composable primitives, and a re-stated ruler-not-stamp line — using the sun-zone-done integration smash as the worked example. Possibly a refactor of `reg()`/`met()` toward primitive assembly, or a documented convention that section-altitude helpers are song-local conveniences ONLY and the package ships only sub-musical primitives.

  **Verifiable signal:** a decision-record/artifact exists stating the generator-altitude boundary (altitude + ruler/stamp re-statement) using the integration smash as the worked example; OR the section-archetype builders are refactored/documented per that decision. **Sized:** large (a philosophy review + likely architecture refactor). (user generator-altitude concern, 2026-06-01, sun-zone-done back-half rework)

  **SHIPPED (2026-06-03, feature/sun-zone-back-half):** A2 — generator-altitude-policy.md (helpers are rulers not stamps; no section-archetype builders in the package).

- **[LNT-1V9K]** Rethink build-gate verdicts — BLOCKING must mean "likely unintentional error", never "deliberate aesthetic choice" (**HIGH PRIORITY** — user)
  `effort: M · impact: L · area: governance · source: user · added: 2026-06-01 · status: shipped · reviewed: 2026-06-03 · closed-by: feature/sun-zone-back-half · related: ARR-1H9C, GEN-1S4K, ARR-3R8F`

  **Raised by the user (2026-06-01, sun-zone-done back-half rework), verbatim:**
  > *"We should be able to write that if we want. Please also grab a backlog item to refine and rethink our gate verdicts — blocking should only ever mean a likely unintentional error. Anything that's deliberate is fair game in art and music. We can ship 4'33 if we want."*

  **The trigger.** Reinventing the break as an ethereal *suspension* (drums + bass drop OUT) collided with the harmonic-conformance gate (`src/hallucinote/theory/lint.py`): the lone **BLOCKING** verdict, `harmonic-stasis`, fires when `declared > 1 and sounded <= 1`. A bass-less section with a declared multi-chord progression has `sounded == 0` (no harmony layer present) → classified as stasis → **build FAILS**. The agent's "clean fix" was to declare the break as a single sustained chord so the gate honors it as a deliberate field. That declaration happens to be musically honest here — BUT the composer should not have to contort the declaration to dodge a gate. **The gate is the thing to fix, not the art.**

  **The principle to encode.** A build-time lens is a **ruler, not a stamp** (great-art-not-software): it measures and ASKS; it must never VETO a deliberate musical choice. So:
  - **BLOCKING** must be reserved for things that are *almost certainly technical/structural errors* — a pitch out of MIDI range, a malformed/duplicate envelope, a clip of zero length, an envelope referencing a nonexistent parameter, a note past the clip end. Bugs, not aesthetics.
  - **Deliberate aesthetic choices must NEVER block** — silence (4'33"), a drone, harmonic stasis, atonality, dissonance, a declared progression the composer chooses to pedal, an absent layer. Surface them **loudly** as INFO/WARNING coaching questions ("the harmony never moves — deliberate field, or an unrealized opportunity?"), but **ship the build**.

  **The tension to resolve (preserve the original win).** The stasis gate exists as "the structural fix for the framework that let a whole song pedal one chord" — it was catching a genuine *realization BUG* (a generator silently failing to pick up declared chord changes), which is closer to unintentional than the pure-aesthetic cases. The redesign must keep catching that bug-shape while never blocking deliberate stasis. Candidate resolutions:
  1. **Downgrade `harmonic-stasis` to WARNING** (loud, printed, in test-evidence) and remove the `raise` in `build.py`; rely on the per-song test asserting `report.ok`/`stasis_sections` to catch *regressions* in songs that INTEND movement — moving the "is this a bug?" judgment to the song's own tests (where intent lives) rather than a global gate.
  2. **Keep a block but require explicit intent to clear it** — a per-section `intentional_stasis=True` / a declared single chord already clears it; extend that opt-out to "declared movement, deliberately pedaled" and to "no harmony layer present" (absence ≠ stasis — `sounded == 0` should never be a block; you can't realize movement with no harmonic agent).
  3. **Split the verdict**: `sounded == 0` (no agent) → INFO; `present-but-pedaled` → WARNING; never BLOCKING.
  - Couples to `ARR-1H9C` (the harmony axis that introduced the gate), `GEN-1S4K` (the altitude concern — same session, same "tools shouldn't narrow the music"), and the lens philosophy already stated in `lint.py` ("it REPORTS; it never edits"). Audit ALL build-time lenses for any other BLOCKING/raise-on-aesthetic verdicts (melody + performance lenses are already info-only — confirm).

  **Verifiable signal:** a decision-record + refactor where no build-time lens emits BLOCKING for a deliberate aesthetic choice (verified by a test that ships a deliberately-static / silent / bass-less section and asserts the build succeeds with a non-blocking finding); BLOCKING reserved for technical/structural errors with an enumerated list. **Sized:** medium (verdict-semantics refactor + tests + the `build.py` raise). (user gate-verdict concern, 2026-06-01, sun-zone-done back-half rework)

  **SHIPPED (2026-06-03, feature/sun-zone-back-half):** A1 — harmonic-stasis downgraded to WARNING + harmonic-absence INFO; no build-time lens blocks an aesthetic choice; gate-verdict-policy.md.

- **[REV-2W8K]** A structured, PER-SONG-CONFIGURABLE review workflow — stop chasing our tails across arrangement/production/harmony/mix at once (**HIGH PRIORITY** — user)
  `effort: M · impact: L · area: process · source: user · added: 2026-06-01 · status: shipped · reviewed: 2026-06-03 · closed-by: feature/sun-zone-back-half · related: GEN-1S4K, LNT-1V9K, MEL-1A7K, ARR-8P5K`

  **Raised by the user (2026-06-01, during the sun-zone-done back-half work), verbatim:**
  > *"Let's find a more structured way to review parts of the song rather than just ad hoc 'listen to whole song and give feedback' or 'ask specific things about a specific section'. Let's build a structured review process into our model… Music is so complex that it's easy to chase our tails across arrangement, production, harmony, instrumentation, etc."*
  > *"bring workflow into the framework, using our typical abstractions so we don't try to cram every song and every collaboration into the SAME workflow — we are just intentional about the workflow for any particular song."*

  **The problem.** Today review is ad-hoc: "listen to the whole song and react" or "ask about one section." Both review on ALL concerns at once (arrangement + sound + harmony + mix), which is exactly what produces tail-chasing — fixing harmony invalidates the mix, re-arranging wastes the sound pass, etc.

  **Research (verified, 2026-06-01; sources cited).** World-class producers organize review along **three axes** and the discipline is choosing ONE deliberately per turn:
  1. **Concern-ordered passes** — the dominant engineering tradition: songwriting → arrangement → sound/production → performance/comp → mix → master, each stage *enhancing* not *redoing* the prior; "you'll never get a great mix of a song with a poor arrangement" ([LANDR](https://blog.landr.com/hard-truths-arrangement/); [iZotope](https://www.izotope.com/en/learn/mixing-while-producing-music-good-or-bad-idea.html)). The stated reason is **rework cost** — fixing arrangement during mixing forces re-architecting and often loses the "vibe."
  2. **Element-at-a-time (subtractive)** — Rubin's "I'm not a producer, I'm a reducer": remove until the identity is *challenged*, then stop; the removal is the diagnostic ([Melodics](https://melodics.com/blog/how-to-produce-like-rick-rubin)). Finneas: carve space around the protected lead.
  3. **Section-at-a-time (structural)** — Nashville Number System + film-scoring **spotting sessions**: chart structure / fix where each section's music acts and its emotional job, against a temp/reference track, BEFORE committing parts ([Sweetwater](https://www.sweetwater.com/insync/the-nashville-number-system-demystified/); [Packt: spotting session](https://subscription.packtpub.com/book/business-and-other/9781837636891/2/ch02lvl1sec05/what-is-a-spotting-session)).

  **The load-bearing principle: ONE review axis per turn** (a `/compose-review` or `/mix-review` pass declares its concern and is *forbidden* to edit the others). That single constraint converts ad-hoc "react to everything" into stage-gated discipline. Feedback stays **question-not-verdict against declared intent** (already our `/compose-review` + `/mix-review` posture — Quincy's "director frame," the spotting "score the subtext").

  **The per-song config (the user's key insight — don't force one workflow).** Persist a chosen **workflow archetype** as song-level intent (our markdown-intent home); the review skills read it and enforce its axis order. Researched archetypes:
  - **A. Ordered-Pass / Band-Song** (pop/rock/singer-songwriter): strict arrangement→sound→performance→mix gates. The default; lowest rework.
  - **B. Sound-First / Electronic-Beat**: *rejects* the ordered model — sound design IS the compositional event, so sound+arrangement reviewed together, "mix-while-producing" sanctioned (Timbaland; iZotope's electronic carve-out).
  - **C. Subtractive / Through-Composed Art Piece**: build dense, run Rubin passes element-at-a-time ("remove until identity is challenged"). *(sun-zone-done likely lives here.)*
  - **D. Spotting-Gate / Cinematic-Narrative**: function-first — fix where + why each section's music acts against a temp reference, then check realization section by section.
  - **E. Charting / Number-System**: review structure on a key-independent section chart first; lock nothing instrument-level until the chart is approved (structure-volatile collaborations).

  **Adversarial caveat (don't ship received wisdom).** "Arrangement before mix" is a *default with documented exceptions*, NOT a law — archetypes B and C exist because the sources themselves dissent (the layers inform each other; the rule is "don't let the mix do the arrangement's job," not "never touch a fader while arranging"). Encode it as Hallucinote's default, not its only mode.

  **What it should produce.** A `.prawduct/artifacts/` review-workflow model (parallel to harmony/performance/melody models) recording the axis taxonomy + the archetypes + the one-axis-per-turn rule; a per-song `review_workflow` intent annotation (the config); and `/compose-review` + `/mix-review` reading the archetype and **refusing cross-axis edits in a single turn**. House disciplines apply: ruler-not-stamp (the workflow guides, never makes the musical decision), one-source-of-truth (the archetype declared once), both-sides (a config surface + the skills that read it), discovered-from-friction (start with the archetypes the research names; add when a real song needs one). **Verifiable signal:** a review-workflow model artifact exists naming the axes + archetypes + the one-axis-per-turn rule; AND a per-song archetype annotation is read by at least one review skill that enforces its axis. **Sized:** medium (model + a per-song config + wiring the two review skills). (user structured-review-workflow ask, 2026-06-01; research-backed)

  **SHIPPED (2026-06-03, feature/sun-zone-back-half):** A3 — review-workflow-model.md (one axis per turn, 5 archetypes) wired into /compose-review + /mix-review; per-song review_workflow annotation.
