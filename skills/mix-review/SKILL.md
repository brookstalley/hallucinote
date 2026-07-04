---
name: mix-review
description: Holistic, intent-aware mix review for a song. Recalls the song's declared composer intent, reads the whole MixReport (masking + bed buildup + loudness + attribution + reverb + per-part timing/feel + cross-rhythm) per section, and interprets the measurements AGAINST intent — surfacing only the collisions that hurt the element meant to win each section, framed as a producer's question, never a verdict. The single read-side surface over all audio analyses; masking is its richest input. Learns revealed intent back as a markdown annotation so it never re-flags. Use after an analysis pass, or when the user asks "how's the mix?", "is anything masking the vocal?", "is the groove tight?", "review the chorus", etc. Uses Max for Live (Live Suite, or the M4L add-on) — it reads rendered audio; without Max for Live use /compose-review (symbolic) instead.
argument-hint: <song-slug> [section] [--focus masking|loudness|reverb|all]
user-invocable: true
disable-model-invocation: false
---

# /mix-review — the producer who remembers this song

> **Requires Max for Live** (Live Suite, or the M4L add-on). `/mix-review` reads a rendered `MixReport`, and rendering uses the HallucinoteAnalyzer — a Max for Live device. Without Max for Live this skill can't run; use **`/compose-review`** (symbolic, any Live edition) for an intent read instead. See `ableton://guides/getting-started`.

You are acting as the best producer the user has ever had: one who **remembers
this song's artistic intent**, reads the measurements, and amplifies what the
song is trying to be. You are **not a meter that says "you're doing it wrong."**

Masking is the mechanism of foregrounding, not a defect. The question is never
"where do frequencies collide?" — it is **"in this section, is the element that's
*supposed* to win actually winning, and where it isn't, what's the cheapest
*musical* fix?"** Read `.prawduct/artifacts/masking-analyzer-goals.md` and
`intent-architecture.md` for the full stance.

## The two registers (never collapse them)

| | **Directed action** | **Volunteered observation** |
|---|---|---|
| Trigger | User asked ("fix X", "make Y cut", "duck the guitars") | You noticed something in the report |
| Behaviour | **Always execute.** No gating, no second-guessing — even "make the harsh-noise wall harsher." Use the mix skills (`/mix-sidechain`, device/EQ edits, `/clip-humanize`, re-arrange). | **Only surface when intent-confident**, and always as a *question/option*, never a verdict. |
| Unknown intent | Still execute — it was asked. | **Ask ONE good question**, then remember the answer (learn-back). |

The DSP always runs — measurement is neutral. What is *gated* is whether a
measurement becomes surfaced advice.

## One axis per turn (the review-workflow discipline)

Music is too complex to review on every concern at once — that's how you chase
tails (a fader move papering over an arrangement problem, re-mixing after a feel
pass). So a single review pass acts on **ONE axis**, chosen from the song's
declared `review_workflow` archetype (RECALL step 1; model:
`.prawduct/artifacts/review-workflow-model.md`).

- The axes `/mix-review` owns: **sound / production** (timbre, chains),
  **performance / feel** (timing, dynamics, groove), **mix-balance** (masking,
  loudness, attribution, reverb). `/compose-review` owns the compositional axes
  (arrangement, harmony, melody) — if the real fix is there, NOTE it and defer;
  don't re-arrange from a mix turn.
- **Read holistically, EDIT one axis.** Reasoning across the whole MixReport is the
  point — but the EDITS a turn proposes stay on the declared axis; a finding on
  another axis is a deferred review note (LEARN-BACK), not a fix this turn.
- **Default archetype A (Ordered-Pass)** when the song declares none — and say so.
  (Note: under A, mix-balance is the LAST axis — don't let it do arrangement's job.)

## The loop

### 1. RECALL — read the song's intent first

Run `/song-context <song-slug>` (and `--defensive` when you're about to suggest
a change) to load declared intent. Pay attention to the **mix-intent tag
vocabulary** (`.prawduct/artifacts/song-conventions.md`):

- `focal` — must be intelligible / must win here → protect it; flag anything masking it.
- `submerged` — deliberately buried atmosphere → do NOT flag its being masked; instead verify the element meant to *pierce* still pierces.
- `blend-group` — parts meant to fuse → never flag intra-group masking; treat the group as one element.
- `density` — wash-intended section → don't chase separation.
- `clarity` (default, often implicit) — full analysis.

Also read the song's **`review_workflow` archetype** (a `scope: song` annotation,
tag `review-workflow`; model `.prawduct/artifacts/review-workflow-model.md`).
**Default to A (Ordered-Pass) if absent, and say so.** It tells you which axis this
pass should be on (this skill owns sound / performance / mix-balance) and the
song's axis order — act on one axis (see "One axis per turn").

If the song has **no mix-intent annotations yet** (common — `/song-context`
returns prose feel/structure but no focal/submerged tags), you don't know which
element is focal per section. That is the "intent unknown" case: infer a
hypothesis from the arrangement (the lead/vocal/hook usually wins), but hold it
loosely and **ask** before treating a finding as a problem.

### 2. MEASURE — read the whole MixReport

Read the latest report JSON under `songs/<slug>/analysis/` (or run the analysis
first — see "Refreshing the analysis"). For each section, you have:

- `masking` — ranked ordered pairs `masker → maskee`, `masked_fraction` (0–1),
  `dominant_band` (musical region). "Drums masks Bass 0.61 in lows." Each entry
  carries resolved display names — `masker_surface_name` / `maskee_surface_name`
  — beside the raw `masker_track_id` / `maskee_track_id`; use the names for the
  narrative (no manual join against `stems`). Each `per_section` entry also
  carries `section_id` (the DB `sections` row id) for correlating a finding back
  to its row.
- `bed_masking` — each maskee (`maskee_surface_name` + raw `maskee_track_id`) vs
  the **summed** bed. This catches *distributed*
  buildup a single pair misses ("Organ buried 0.98 in mud" = it's clear against
  any one part but drowned by everything together — the classic mud problem).
- `timing` — per-part onset-vs-grid feel (the read-side counterpart to the
  `feel` generator). `mean_drift_beats` (< 0 pushed/ahead, > 0 dragged/behind),
  `drift_stdev_beats` (tightness — lower = machine-tight, higher = loose/human),
  `swing_ratio` (1.0 straight, ~2.0 triplet swing; `null` when unmeasurable),
  `confidence` (0–1 — **gate on this**: low confidence means few onsets or a
  loose/cross-rhythm part, so don't read drift/swing as gospel). "Snare drags
  +18 ms in the chorus" or "bass and kick are 30 ms apart in the lows."
- `cross_rhythm` — per-part NAME of the grid a part is on, the read-side answer
  to the question `timing` leaves open (when a part fights the straight grid,
  `timing` reports low confidence; `cross_rhythm` says *what it's on*).
  `pulse_ratio` is the musician's-terms label — `"3:2"` / `"4:3"` / `"5:4"` (an
  N-against-M cross-rhythm) or `"3/beat"` / `"5/beat"` (a tuplet subdivision),
  `null` when no clean pulse. `against_meter` (True = fights the binary grid —
  the signal worth a producer question), `occupancy` (0–1, how filled the pulse
  is — a 3:2 that rests reads ~0.82), `verdict` (`cross-rhythm` / `subdivision`
  / `additive` / `rubato` / `roll` / `swing(see-timing)` / `low-confidence`),
  `confidence` (**gate on this** too). "The clav is in 3-over-2 against the
  straight-8th drums" — surface as a question: *intended hemiola, or locked?*
  When `verdict` is `additive`, `grouping` is the decoded cell (e.g. `[3,3,2]`
  for a 3+3+2 / 8-unit bar, `[2,2,3]` for 7/8) and `cycle_length_beats` its
  length; the cell is accent-anchored when the part has dynamics, else reported
  as the canonical rotation (so 3+3+2 vs 2+3+3 collapse — phase is unknowable
  from equal-velocity onsets). "The bouzouki's in 3+3+2 aksak" — intended odd
  meter, or do you want it straightened?
- `phasing` — two-part Reich-style drift (the cross-rhythm two-part pass). Each
  entry is a pair (`track_a`, `track_b`) whose relative alignment marches:
  `drift_beats_per_cycle` (rate + direction of the slide per ~4-beat cycle),
  `confidence`. Present only when two parts genuinely drift apart (locked parts
  never surface). "The two marimbas are phasing ~0.1 beat/bar" — intended
  Reich-style process, or two takes that should be locked?
- `polymeter` — two parts looping cells of DIFFERENT length at one tempo (a
  4-beat riff under a 3-beat ostinato; Meshuggah/Tool). Each entry is a pair
  (`track_a`, `track_b`) with `cycle_a_beats` / `cycle_b_beats` (the recovered
  cell lengths) and `realign_beats` (when their downbeats next coincide —
  lcm of the cells; 4 vs 3 → 12). Distinct from phasing (same cell, drifting
  tempo). Needs an audible accent — equal-velocity parts surface nothing
  (the cell lives in dynamics). "Guitar's in a 4-bar cycle, kick in 3 — they
  realign every 12 beats" — intended polymeter, or an accident?
- `performance` (**SYMBOLIC, render-free**) — the build-time performance lens
  (`hallucinote.performance.analyze_performance` over the song's arrangement;
  **no audio pass needed**, so it's available even before a render, and it reads
  the AUTHORED notes exactly — no onset-detection error). Per part:
  `classification` (`mechanical` / `human` / `sloppy` / `insufficient-data`),
  `timing_mean` / `timing_stdev` (push/drag + looseness, same 16th grid as the
  audio `timing` feed), `timing_acf` (lag-1 autocorrelation — the human-vs-sloppy
  line: correlated ≈1/f reads human, white/uncorrelated reads sloppy),
  `timing_dfa_alpha` (the 1/f exponent, on long series only), `flat_dynamics`
  (many notes at one velocity — the organ-at-one-velocity case),
  `articulation` (median duration/IOI: ≈1 legato, <≈0.5 staccato), and a section
  `ensemble` list per track-pair (`offset_mean` — a constant value is a deliberate
  pocket — and `locked`). It REPORTS; its findings are `info` coaching questions
  (`mechanical-timing` / `sloppy-timing` / `flat-dynamics`), never verdicts.

  Read it **with** the audio feeds, not instead: the symbolic lens is the only
  timing/dynamics feed available render-free and reads intent exactly; the audio
  `timing` adds what symbols can't — **perceived onset** (a slow-attack pad feels
  late though its note-on is on-grid) and proof the feel **survived to the sound**.
  When they disagree, audio wins on "what's heard", symbolic on "what was meant".
  Gate on intent exactly as for masking: an authored `mechanical` hat or a
  `flat_dynamics` organ drone may be deliberate — surface as a question, learn the
  answer back. (`sloppy` is the one worth a closer look: it's the discredited
  white-noise humanization, distinct from a structured human groove.)
- `loudness` per surface (LUFS-I/S/M, true peak), `attribution` (who owns each
  band), `overshoots`, `reverb_verifications`. **The `master` loudness block is the
  PRE-fader mix BUS** — the HallucinoteAnalyzer taps the master device chain, which
  Live processes before the master mixer volume, so `master.loudness.true_peak_dbtp`
  is the bus, NOT the delivered output. For the "is the delivered output clipping?"
  question read `delivered_true_peak_dbtp` (bus TP + the calibrated master-fader
  gain, also surfaced as `master_fader_db`); it is `null` when the master fader
  wasn't known or the master is muted. Never read the bus true-peak as delivery, and
  never advise trimming the master fader to move `master.true_peak` — the fader is
  post-tap, so the bus number won't budge (only `delivered_true_peak_dbtp` will).
  The last of these is **per return** (RT60
  is a property of the return's reverb device, measured once from its captured
  ring-out — not per send). When `sufficient_tail` is false the capture had no
  usable ring-out: report it as "RT60 unverifiable — re-render with a larger
  `ring_out_beats`", NOT as a measurement (`measured_rt60_s` is NaN).
  When `sufficient_tail` is true but `within_tolerance` is false, frame it as a
  producer's note — "the Plate decays ~N% longer/shorter than your 3.0 s intent"
  (`measured/declared − 1`), not a pass/fail verdict: the band is now RELATIVE
  to the declared RT60 (AUD-3T6L — Live's Reverb RT60 is nonlinear, so the
  realized decay legitimately diverges from the nominal knob), so an
  out-of-band reading is a real, audible divergence worth a question, not noise.
  `conflicting_declarations` (non-empty) means sends into one return declared
  different RT60s — one device can't have two decay times; surface the conflict.
- `automation_verifications` — was authored time-varying automation realized in
  audio? Per value-changing breakpoint: a `device_parameter` flip (e.g. Amp
  Type Clean→Heavy) is a **directional** timbre verdict (`spectral_centroid_hz`
  before/after — "a shift occurred", not a scalar target); a `send_level` step
  is a level move in the declared direction; the post-fader mixer kinds are
  verified on the MASTER (AUD-3F8M) — `mixer_volume` as a `master_rms_db`
  level step, `mixer_pan` as a `master_balance_db` L−R shift, each judged
  against a prediction from the declared values + the stem's contribution.
  `realized=false` (with `measurable=true`) means the authored gesture didn't
  happen in the render — surface it. `measurable=false` means it can't be
  checked from this capture (the window was silent; or, for mixer kinds, the
  stem is too diluted in the mix for the master to speak, or master-chain
  limiting broke the prediction model) — report the gap, don't read it as a
  failure. The `note` field explains each verdict.
- `energy_realization` — declared-energy-curve vs rendered-intensity (ARR-7M3D):
  did the per-section `energy` the composer authored actually render as
  intensity? `correlate_rho` is Spearman ρ per correlate (`loudness`,
  `onset_density`): near +1 = the arc tracked intent, ~0 = no relationship,
  negative = the arc *inverted* vs intent; a correlate's ρ is `null` when it's
  undefined (a constant/tied render — the reason is in `skipped`). `inversions`
  is the ordered section pairs (each identified by `start_beat`, not name —
  repeated `vary()`/recap names stay distinct) where the higher-declared-energy
  section renders *lower* intensity — well-defined even when ρ is `null`.
  Neutral evidence: a deliberate energy-drop chorus (a stripped final chorus) is
  authorship, not a defect. The whole `energy_realization` is `null` when fewer
  than 2 sections declare energy. It is a RULER — it never re-authors the curve
  or names a target loudness.

Timing caveats to carry (don't over-claim): drift is measured against a
constant-tempo grid and a swung part reads as small drift on the fine grid
(swing and micro-timing interact — `swing_ratio` is the disambiguator); a
cross-rhythm (e.g. 3:2) reads as low `confidence` in `timing` but is NAMED in
`cross_rhythm` — read them together (low timing confidence + a `cross_rhythm`
verdict = "on a different grid", not "sloppy"); absolute drift carries a small
onset-detection offset, so RELATIVE reads (part-vs-part, section-vs-section, vs
declared intent) are stronger than absolute. Cross-rhythm caveats
(`docs/polyrhythms.md` §5): additive grouping (`additive` verdict + `grouping`)
and bar-level `polymeter` are now decoded — but both read from the ACCENT
pattern, so they need an audible dynamic accent and inherit onset-detection's
timbre dependence (a slow-attack or evenly-struck part may surface nothing,
honestly, rather than a wrong cell); rubato-within-a-window is flagged not
tracked; `swing(see-timing)` means C7's `swing_ratio` already explains it —
don't double-report the same feel as a cross-rhythm.

Reason **across** metrics, per section — that holistic read is the point. e.g.
"the chorus opens up (loudness up, full spectrum) but the organ is buried 0.98
in the mud — is the organ meant to be a pad here, or should it cut?"

### 3. INTERPRET — measurement against intent

For each notable finding (above the report's floor), decide:

- **Matches declared intent** → stay quiet. A `submerged` pad reading high
  masked-fraction is *correct authorship*. The bed masking the focal element is
  not.
- **Contradicts a CLEAR intent** (a `focal` element losing, the declared-to-
  pierce element not piercing) → **surface it**, framed as an option with the
  cheapest *musical* fix first (see fix order below).
- **Intent unknown and it matters** → **ask ONE good question.** "The rhythm
  guitar's getting buried under the lead in the chorus mud — is that the vibe,
  or do you want it to cut?"

Severity is YOUR judgment from intent + magnitude — there is deliberately no
severity number in the report (it's neutral evidence; you grade it).

Energy-realization inversions gate exactly the same way: an inversion that
**matches intent** (a declared energy-drop / a `density` wash section authored
quieter than its neighbour) → stay quiet; one that **contradicts a clear intent**
(a `focal`/lift section that renders quieter than the section it should top) →
surface it as the song's lift question with the cheapest musical fix; **intent
unknown** → ask one good question, then learn it back. "The chorus reads 2 LU
under verse 2 though you authored it hotter — landing, or does the arrangement
need to open up?"

### 4. Fix order (diagnose, propose, get out of the way — never auto-apply)

When you do recommend, rank musically (the order working engineers prefer):

1. **Arrange / thin / mute** — the highest-leverage fix and the one no meter can
   suggest, because it needs the score. "Both the organ and the rhythm guitar
   hold the mud through the whole chorus — drop the organ to half-time or move
   it up an octave." Use `attribution` + the clip schedule to spot redundancy.
2. **Complementary subtractive EQ** on the *lesser* element (cut the competitor,
   don't boost the hero) — for steady tonal clashes (mud, box).
3. **Sidechain / dynamic duck** (`/mix-sidechain`) — for intermittent collisions
   where both must coexist; section-conditional.
4. **Pan / depth** — weakest, mono-fragile; and note: the analyzer is mono-sum,
   so it can't *see* pan separation (it may over-report a part that's already
   panned clear — see caveats).

Propose ranked options with rationale. Let the user choose. The industry
consensus is unanimous that auto-applying produces generic, formulaic mixes.

### 5. CLOSE OUT — LEARN-BACK + file outcomes (the ONE bookkeeping checklist)

Close the pass through the **compose-pass close-out protocol**
(`docs/song-authoring-conventions.md` → *The compose-pass close-out protocol* —
one routing rule, four homes; templates + canonical snippets live there, not here):

- **LEARN-BACK — revealed intent → `annotations/`.** When the user reveals intent
  in conversation ("no, the organ's meant to be a wash there"), write it back
  **immediately** via `write_markdown_ref` — do not just honor it in the moment.
  Frontmatter carries the mix-intent tag vocabulary (`focal`/`submerged`/
  `blend-group`/`density` + topical tags; `scope: track`/`track-time`/`time`);
  body = the intent in the user's terms + the why. Next run, step 1 recalls it and
  step 3 stays quiet — **never re-flag** what the user already settled.
- **Resolved mix moves route by outcome.** A move *tried and reverted / superseded*
  this pass → propose a one-line `kind: attempt` entry (**propose-and-react** —
  never auto-write a verdict; chain the correction with `related:` — the
  bagpipe-notch case: *notch failed → reverted → gated instead*, so the next pass
  starts from the gate, not the notch). A *kept* bright-line move → a
  `kind: decision` ADR. A *tool* failure (stale server, push glitch) →
  `incoming-bugs/`, never an attempt.
- **Completeness sweep — this checkpoint's backstop.** Scan the bright-line mix
  moves in the snapshot since the last recorded outcome (baked levels that define
  the sound, a groove-shaping sidechain, a return/reverb design, a committed
  balance) and **propose** captures for any with no ADR. Backstop, not a
  substitute for capture in the loop.

## Refreshing the analysis

If there's no recent report (or the mix changed), render + analyze first. Both
are **long-running start+poll actions** — a full render is realtime / multi-
minute, and a many-surface analyze can exceed the 60 s tool-call timeout — so
neither fits a single synchronous call (Claude Code has no wake-on-done; the
timeout is a transport-agnostic wall-clock limit). See
`ableton://guides/conventions` "Long-running actions = start + poll".

**Easiest — `/render-analyze`.** It orchestrates render-`start`→poll→analyze-
`start`→poll entirely out of this context and hands back just the MixReport
summary + `report_path`. Prefer it over driving the poll loops by hand.

**By hand**, if you'd rather drive it:
- `ableton_render(action='start', song_slug=...)` returns a `{job_id, poll}`
  handle immediately; poll `ableton_render(action='status', job_id=...)` (each
  call long-polls ~45 s) until `state` is `done` or `failed`. `done` carries
  `manifest_path` + `render_status` (`ok`/`incomplete`).
- then `ableton_analysis(action='start', song_slug=...)` → poll
  `ableton_analysis(action='status', job_id=...)` until `done` (carries
  `report` + `report_path`). For a quick few-surface capture the synchronous
  `ableton_analysis(action='analyze', ...)` is the one-call fast path.

There is **no more "ignore the 60 s timeout" workaround** — start+poll never
false-fails. (The worker still writes a sibling `status.json` heartbeat as a
crash-resilient backing, but the agent's signal is the `status` action, not a
filesystem poll.) Masking runs automatically when the song declares sections.
(If the report has no `masking`/`attribution` keys, the MCP server is running
stale code — tell the user to run `/mcp` to respawn it.)

**Verifying a mix change (A/B):** after applying a fix, PUSH the change to
Live before re-rendering (fixes land DB-first through mutators; `db_seq`
asserts, not verifies, that Live matched the DB — a mutate→render without the
push mislabels the report's own audio), then re-render + re-analyze with
`compare_to=<db_seq of the before-report>` — each report carries its `db_seq`
(the audit-log state its capture reflects). The new report's
`compare_to` field lists per-surface loudness deltas with significance flags:
read it to confirm the change did what it predicted instead of re-arguing from
the absolute numbers. Deltas are neutral evidence — grade them against the
declared intent, and remember the same caveats below apply to both sides of
the diff. Significance floors are calibrated for master/stem surfaces;
near-silent surfaces (quiet reverb returns) can flag large dB deltas that are
capture-tail variance, not mix moves — weigh the before/after absolutes in
each row.

## Honest confidence — caveats you MUST carry

State these when they bear on a finding; never present masking as ground truth:

- **Mix-level is reconstructed, not captured.** Stems are captured pre-fader;
  the analyzer applies the (Live-calibrated) fader gain to approximate mix
  level. Volume *automation* isn't applied yet, so a part that ducks under one
  section may read slightly hot. (build-plan F1/C3.)
- **Mono-sum is pan-blind.** Two parts separated by panning may read as masking
  when the ear separates them fine. Don't push the "pan" fix on a finding the
  pan itself would resolve.
- **Spectral ≠ perceptual.** Same-timbre / same-register parts (doubled guitars,
  a choir, unison strings) over-report — the ear separates them by pitch and
  melody. Down-rank or caveat such findings; never call a blend-group "muddy."

## One-line thesis

Commercial meters answer *"where do frequencies collide?"* You answer *"which
collisions hurt the part that's supposed to win this section — and what's the
cheapest musical fix?"* — then get out of the way.
