# Wave 0 — Triage

**Source.** `solo-piano-ambient-runbook.md`, `full-band-rock-runbook.md`, `odd-meter-experimental-runbook.md` (2026-05-19).

**Procedure.** Each numbered finding here corresponds to one or more runbook entries (cited). Severity is the synthesis of the agent's "Severity guess" + cross-canary corroboration (a finding three agents hit is harder to dismiss than one). Disposition maps each finding to a downstream wave/chunk in `.prawduct/artifacts/build-plan.md` and `docs/v1-build-plan.md`, OR to `.prawduct/backlog.md`, OR to an **explicit v1 punt with rationale**.

**Triage outcome at a glance.** 3 architectural blockers that need a v1 disposition decision (D1, D2-D3, H1). 5 important findings that fit existing waves with minor scope adjustment. ~10 paper-cuts that go to backlog. **No build-plan reshape is forced** — the existing wave skeleton holds — but Wave 10 (sync UX) and Wave 9 (new-song) each need 1-2 chunks added, and the envelope-reach + meter-ratchet questions need explicit "ship vs. document non-support" calls. Recommendations below; user sign-off needed on the punt calls.

---

## Group A — Authoring path / new-song chicken-and-egg

All three canaries hit this on step 1 of every run. **Wave 9 is correctly scoped already**; the triage adds two specific sub-asks.

| # | Finding | Severity | Canary | Disposition |
|---|---|---|---|---|
| A1 | No `/new-song` skill — agent must reverse-engineer from `falling-walking` | **important** | spa-1, fbr-1, ome-1 | **W9-A** (existing plan). |
| A2 | No documented snapshot schema; `captured_session.json` shape lives only in `capture.py` docstring | **important** | spa-2, fbr-2, ome-2 | **W9-A — ADD**: snapshot schema doc (`docs/snapshot-schema.md`) + JSON Schema file the templates reference. |
| A3 | Chicken-and-egg: capture wants a real Live set; new song has none → user must hand-author the snapshot | **important** | spa-2, fbr-2, ome-2 | **W9-A — ADD**: a minimal "hello-world" song under `tools/templates/song/` so new authors copy a template, not the historical falling-walking. |
| A4 | README promises "Claude scaffolds `songs/punk-fate/`" — aspirational; no helper exists | important | spa-1 | **W9-A** (subsumed). |
| A5 | No way to create `ableton_sessions` row without raw Python (`/ableton-push` refuses to invent) | **blocker** | spa-7, fbr-7, ome-7 | **W9-B + W9-C** (existing plan). |
| A6 | `replay_capture` silently strips `[A-Z]-` slot prefix; lookup by snapshot name fails | paper-cut | spa-3 | **Backlog**: add one-line warn + schema doc note. |

**Net plan change:** W9-A scope grows by ~2 items (snapshot schema doc + hello-world template). No new chunks.

---

## Group B — Push pipeline ceremony cost

| # | Finding | Severity | Canary | Disposition |
|---|---|---|---|---|
| B1 | Per-phase `plan → execute → apply` ceremony compounds: full-band-rock had **49 mix calls + 21 clip calls + 8 device calls** to hand-marshal, time-capped the run before envelopes/arrangement/cues | **important** | spa-7b, fbr-7a, ome-7e | **NEW chunk — recommend W10-E**: `push_cli execute` subcommand that takes the plan + an MCP callback (or streams calls + collects results), reducing per-phase user/agent overhead from 10s of round-trips to 1. Critical for any realistic-size song. |

**Net plan change:** add **W10-E** to Wave 10.

---

## Group C — Push idempotency / additive surprises

`W10-A` is currently scoped to arrangement-phase idempotency. Canaries surfaced two adjacent additive footguns at the **device** and **return** levels — same family of bug, different phase.

| # | Finding | Severity | Canary | Disposition |
|---|---|---|---|---|
| C1 | `devices` phase emits `load` unconditionally even when an equivalent device already sits at that chain index — duplicates the device (`A-Reverb` → `Reverb \| Reverb`) | **important** | spa-8 | **W10-A (expanded)**: idempotency check covers devices phase too. |
| C2 | `returns` phase emits `create` even when a functionally-equivalent return exists in Live (default A-Reverb / B-Delay vs. snapshot's `Reverb` / `Delay`) | **important** | ome-7d | **W10-A (expanded)**: idempotency check covers returns phase too. |
| C3 | `arrangement` phase plan tells the agent "must clear existing arrangement clips" with no `clear_track` MCP action suggested | paper-cut | spa-7e | **W10-A** (already in scope). |

**Net plan change:** W10-A's investigation broadens from arrangement-only to "phase planners that emit creates/loads against potentially-occupied Live state." `build-plan.md` already reflects the rename to "Push idempotency: arrangement + devices + returns."

---

## Group D — Envelope reach (RESOLVED 2026-05-19, corrected after PR reviewer caught LOM error)

The first-pass triage flagged D1/D2/D3 as architectural blockers and recommended v1.1 punts. User challenge + a focused D2 investigation reshaped the group. A subsequent PR review (2026-05-19) caught a factual error in the D1/D3 disposition: the triage cited `_TRACK_LEVEL_GAP_HINT` at `handlers/automation.py:75-82` which claims envelopes work on "arrangement (or session)" clips, but the empirically-enforced code at `automation.py:839-858` (Wave 2 finding W2-10 — see `git log -- .prawduct/artifacts/bug-triage-wave2.md` for the original investigation; doc deleted in the v0.9.0 hygiene sweep) REJECTS mixer/pan/send/device_parameter envelopes on arrangement clips — these target_kinds work on **session clips only**, then `duplicate_to_arrangement` carries the envelope along. Dispositions below are corrected for the actual constraint.

| # | Finding | Severity | Canary | Disposition (corrected) |
|---|---|---|---|---|
| D1 | Long envelopes spanning multiple session clips can't be pushed today. Solo-piano-ambient's headline target | **important** | spa-7d | **W10-F — refuse with teaching for v1; partition as v1.1.** Live 12.4 LOM requires mixer/send/device_parameter envelopes on a SESSION clip; the existing teaching error at `automation.py:846-857` spells out the path ("author on session clip, then `duplicate_to_arrangement`"). The real D1 problem: when no single session clip covers the envelope's beat range, today's planner skips with a vague warn. **v1 fix**: planner-side refuse-with-teaching matching the D2 pattern ("envelope spans beats [X,Y] but no session clip covers it; extend or split a session clip to host it, or partition the envelope by hand into per-section sub-envelopes"). **v1.1 enhancement**: planner auto-partitions the envelope across existing per-section session clips; pull stitches adjacent identical envelopes back into one logical envelope. |
| D2 | Master envelopes silently dropped on push | **blocker** | fbr-7c | **W10-F — ship loud refusal in v1.** D2 investigation confirmed no LOM path: `create_automation_envelope` lives only on `Clip`; master can't host clips; Utility-on-master dies at the same boundary; M4L mirror is a sub-bus pattern not an MCP path. **Decision (user 2026-05-19): reject at BOTH DB-mutator AND planner layers; teaching message points users at the sub-bus pattern (no M4L mention).** |
| D3 | Mixer envelopes on audio tracks unreachable — surfaced via the lead-vocal sidechain placeholder | **important** | fbr-7c | **W10-F — refuse with teaching for v1.** Audio tracks can't host MIDI session clips (Hallucinote's DB models clips as MIDI-only for v1; audio clips are `scope.later`). Live's audio session clip slots could in principle host envelopes via LOM, but Hallucinote can't address them until audio clips land in the DB. **v1 fix**: planner refuses with teaching message ("mixer/send envelopes on audio tracks require audio session clips, not modeled in v1; route the source to a sub-bus group track and automate the group's volume"). **v1.1 enhancement** (gated on audio-clip DB model): support envelopes on audio session clips once they're addressable. |

**W10-F scope (consolidated, corrected):**
- (a) D1 — planner-side refuse-with-teaching when no single session clip covers the envelope's beat range; teaching message points at "extend/split session clip OR partition envelope by hand"
- (b) D2 — DB-mutator validation + planner refusal for master-targeted envelopes; teaching message pointing at sub-bus pattern; extend `handlers/automation.py` module docstring with D2 finding; add `ableton://guides/gaps` entry
- (c) D3 — planner refuses mixer/send envelopes on audio tracks; teaching message points at sub-bus group pattern; same dual-layer (DB-mutator + planner) rejection
- (d) **Fix the stale `_TRACK_LEVEL_GAP_HINT` text (lines 75-82) and module docstring (lines 13-18)** — both currently claim "arrangement (or session)" which contradicts the enforced session-only rule. Either rewrite to "session only — `duplicate_to_arrangement` carries the envelope" or remove the parenthetical
- (e) Tests covering all three refusal paths + the stale-hint fix

Size: ~300-500 LoC + ~8-12 tests. **Critic mark: yes** (locks in three non-support contracts; touches the load-bearing envelope-emitter family). 1 chunk. The matching v1.1 partition + audio-clip-envelope work are filed as backlog items separately.

---

## Group E — Push planner partial-state inconsistencies

| # | Finding | Severity | Canary | Disposition |
|---|---|---|---|---|
| E1 | Phase planners are inconsistent: envelopes skip-with-note, devices fail-per-call, **arrangement hard-crashes** with uncaught `ValueError` | **important** | fbr-7d | **NEW chunk — recommend W10-G**: normalize partial-state behavior across all phase planners (lean: every phase planner returns a structured `{calls, skipped, errors}` payload, never raises; the apply layer turns errors into per-call failed results consistent with devices' current behavior). |
| E2 | Cue points fail when arrangement extent is too short — error message is good but plan didn't warn at plan time | paper-cut | fbr-7e | **Backlog**: add a "this phase depends on arrangement extent" note to the cues-phase plan. Already mostly addressed by good error text. |

**Net plan change:** add **W10-G** for partial-state normalization. (Or merge with W10-A if scope feels right.)

---

## Group F — Round-trip name drift

Wave 7 closed the envelope round-trip; these are **name** round-trip drift findings that surfaced after W7.

| # | Finding | Severity | Canary | Disposition |
|---|---|---|---|---|
| F1 | Pull overwrites return name with the auto-generated `Reverb \| Reverb` string created by C1's device duplication (push-then-pull breaks parity) | **important** | spa-8 | **Resolved transitively by C1's fix**. Add explicit regression test: "push twice in a row, pull, names unchanged." |
| F2 | Pull overwrites `display_name` on devices — author's `"Sidechain Comp (drum-key)"` becomes Live's canonical `"Compressor"` | **important** | fbr-7b | **W10 polish** (recommend rolling into W10-A): pull-side `display_name` should be treated as DB-authoritative when it differs from Live's canonical name. Or document that `display_name` is volatile. |

**Net plan change:** F1 covered by C1. F2 fits W10-A's expanded scope.

---

## Group G — Plugin / device identity gaps

Wave 13 is correctly scoped for the cross-machine plugin story. Canaries surfaced one new bug worth a sub-task.

| # | Finding | Severity | Canary | Disposition |
|---|---|---|---|---|
| G1 | `PluginDevice` fails identically whether VST is missing or URI is wrong — error message indistinguishable | **important** | fbr-7b | **W13-B** (existing plan — compat check + REQUIREMENTS report). |
| G2 | Stock device class names don't always match loader `kind` — `AnalogDevice` is rejected, `Compressor2` works as `Compressor`, etc. — no canonical mapping table | **important** | fbr-7b | **Backlog — new entry**: "device kind canonical mapping table + loader auto-fallback (`AnalogDevice` → search for `Analog`)." Probably fits as a W13-A sub-task. |
| G3 | Snapshot for VSTs carries `{class, name, guess_uri}` only — no manufacturer / format / unique fingerprint | **important** | fbr open Q2 | **W13-A** (existing plan — capture extension for `(class, display_name, manufacturer, pack_name, params_dialed)` already in spec). |
| G4 | No higher-level "load Live's stock Grand Piano on this track" affordance — author has to know the URI | **important** | spa-7c | **W14-A** (existing plan — `pick_instruments_for_song` MCP prompt). |

**Net plan change:** G2 → backlog with W13-A linkage. Others fit existing plan.

---

## Group H — Non-4/4 meter support

Canary 3 (`odd-meter-experimental`) was designed to find these. Two are blockers; one is an open scope question.

| # | Finding | Severity | Canary | Disposition (recommended) |
|---|---|---|---|---|
| H1 | Within-section meter ratchet **silently dropped on push**. DB models all 10 `time_signature_map` rows; planner emits only bar-1 + warns about the rest. Live 12.4 MCP has no per-bar meter automation | **blocker** for the meter-ratchet feature | ome-7b | **W10-H — ship loud refusal in v1; punt working impl to v1.1 (user 2026-05-19).** `plan_push_time_signature_map` refuses at plan time when >1 row is present; teaching message points at "single global meter for v1, per-bar-arrangement-clip workaround coming in v1.1." Same dual-layer pattern as D2. |
| H2 | **Every generator in `src/hallucinote/generators/` hard-codes `bar * 4.0`** — unusable for non-4/4 songs. No doc warns | **important** | ome-3 | **Triggers W14-B** (Generator library audit). Recommend the W14-B audit's first task is: parametrize every generator on `beats_per_bar`, OR rename to `*_4_4` and document. The triage's read: the audit was contingent on Wave 0 finding "same primitive hand-rolled 5×"; we got a stronger signal — "every generator is meter-overfit." **W14-B is triggered.** |
| H3 | No library helper for "convert pulse-of-meter BPM to Live's quarter BPM" (eighth-pulse 168 → quarter 84 for 7/8) | paper-cut | ome-7a | **Backlog**: add `hallucinote.tempo.to_live_bpm(pulse_bpm, pulse_kind, time_signature)` helper or a docs sentence. |

**Net plan change:** add **W10-H** for meter-ratchet refusal. **Mark W14-B as triggered** (no longer contingent).

**H1 disposition (user 2026-05-19): ship loud refusal in v1; punt working impl to v1.1.** `plan_push_time_signature_map` refuses at plan time when >1 `time_signature_map` row is present, with a teaching message ("Within-section meter changes aren't supported in v1 — Live 12.4's MCP has no `song_signature` automation target_kind. Either consolidate to a single global meter, or wait for v1.1 which will explore the per-bar-arrangement-clip workaround"). DB-mutator side also rejects (mirroring W10-F D2's dual-layer pattern). Gaps-guide entry; v1.1 milestone tracker filed.

---

## Group I — Schema / data-model uncertainties

| # | Finding | Severity | Canary | Disposition |
|---|---|---|---|---|
| I1 | Repeated sections: schema permits both "one clip, N placements" and "N clips, N placements" — semantics unspecified, agent picked the latter by guess | **important** | fbr-3 | **Backlog**: add `docs/song-authoring-conventions.md` documenting the repeated-section pattern. Trivial doc fix; high-leverage for new authors. Could also live as a W9-A artifact. |
| I2 | Cue-point duplicate names (3× "chorus") — Live UI shows ambiguous locator entries | paper-cut | fbr-3 | **Backlog**: planner-side auto-disambiguation (`chorus 1`, `chorus 2`, ...) OR document the convention. |
| I3 | All three canaries named their test file `test_build.py` (mirroring falling-walking) — pytest collected them in isolation fine but blew up at the full-suite collection step with `import file mismatch` collisions under rootdir-discovered + prepend-import-mode. **Implicit convention is "unique basenames per song"; nothing documents it.** | **important** | (suite collection, not a runbook step) | **Resolved in this triage** by renaming canary tests to `test_<slug>_build.py` and adding a per-song convention comment to `pyproject.toml`. Future `W9-A` template should bake the naming convention in (`tests/test_{{slug}}_build.py`). |

**Net plan change:** none. Two backlog adds.

---

## Group J — Read surfaces (MCP gap)

| # | Finding | Severity | Canary | Disposition |
|---|---|---|---|---|
| J1 | `ableton_clip` has NO action that reads back notes from an existing clip. Fractional polyrhythm positions cannot be verified via MCP — only by visual Live inspection or `.als` parsing | **important** | ome-7e | **MCP gap — add to `hallucinote_mcp/src/hallucinote_mcp/resources/guides/gaps.md`** + new backlog entry: "add `ableton_clip(action='read_notes')` to MCP surface." Note: this is the gap-#4 family but in the read direction. Probably belongs in a post-v1 MCP-gap wave; for v1 the workaround is the pull path. |

**Net plan change:** add gaps.md entry + backlog item. (Wave 11's `hallucinote://` read surface targets the DB side, not the MCP side — different gap.)

---

## Group K — Polyrhythm precision

| # | Finding | Severity | Canary | Disposition |
|---|---|---|---|---|
| K1 | Polyrhythm offset `(7.0/5)*3/2 → 2.0999999999999996` (IEEE 754 sub-LSB drift). DB faithfully round-trips; the issue is on the AUTHOR side | paper-cut | ome-8 | **Backlog**: future polyrhythm helper (`hallucinote.polyrhythm(n, against=k)`) should use `fractions.Fraction` and float-convert at the mutator boundary. Document the trap in `docs/polyrhythm-authoring.md` (or annotate generators). |

**Net plan change:** backlog add.

---

## Group L — Default-set cleanup

| # | Finding | Severity | Canary | Disposition |
|---|---|---|---|---|
| L1 | Push is additive; Live's 4 default tracks (1-MIDI through 4-Audio) and pre-existing returns are left stranded after push. User clutter | paper-cut | spa-final, fbr-final, ome-final | **W12-C** (existing plan — promote `unmatched_live_tracks` from informational to YES/NO confirmation). Same family of finding. |

**Net plan change:** none. Covered by W12-C.

---

## Net build-plan diff (recommended)

### Wave 9 — W9-A scope grows by two items
- ADD: snapshot schema doc (`docs/snapshot-schema.md`) + JSON Schema file
- ADD: minimal hello-world song template under `tools/templates/song/` (so authors copy a template, not historical falling-walking)
- ADD: `docs/song-authoring-conventions.md` covering repeated-section pattern (I1)

### Wave 10 — add four chunks (E/F/G/H)
- **W10-A** (existing) — expanded scope: arrangement + devices + returns idempotency (build-plan.md retitled).
- **W10-E (NEW)** — push_cli `execute` subcommand for streamed plan→MCP→results, removing the per-phase ceremony tax. **Critic mark: chunk** (touches the push surface that every wave depends on).
- **W10-F (NEW, RESOLVED, corrected post-PR-review)** — Envelope reach (D1/D2/D3 consolidated):
  - D1: planner refuse-with-teaching when no single session clip covers the envelope's range; v1.1 enhancement = auto-partition
  - D3: planner refuses mixer/send envelopes on audio tracks (no MIDI session clip path; audio clips not in v1 DB); teaching points at sub-bus group
  - D2: DB-mutator + planner refusal for master-targeted envelopes; teaching message points at sub-bus pattern (no M4L mention)
  - Fix stale `_TRACK_LEVEL_GAP_HINT` text + module docstring (both falsely claim "arrangement or session" works for these target_kinds)
  - Tests for all three refusal paths + the stale-hint fix; gaps-guide entry
  - **Critic mark: chunk**. Size ~300-500 LoC + 8-12 tests.
- **W10-G (NEW)** — Partial-state normalization across phase planners (E1 — no more uncaught `ValueError` in arrangement).
- **W10-H (NEW, RESOLVED)** — Meter-ratchet authoring-time refusal + docs (H1). DB-mutator + planner refuse when >1 `time_signature_map` row present; teaching message points at "single global meter for v1, per-bar-arrangement-clip workaround coming in v1.1." Same dual-layer pattern as D2.

### Wave 14 — W14-B promoted from contingent to triggered
- **W14-B is triggered.** Generator library audit MUST happen: every generator hard-codes 4/4. Either parametrize on `beats_per_bar` (preferred) or rename to `*_4_4` and document.

### Wave 13 — small addition
- ADD: G2 backlog item (device kind canonical mapping) — fits as a W13-A sub-task.

### Backlog adds (paper-cuts + adjacent gaps)
- A6: `replay_capture` slot-prefix-strip warning
- E2: cues phase plan should warn about arrangement-extent dependency
- G2: device kind canonical mapping table + loader auto-fallback
- H3: `hallucinote.tempo.to_live_bpm` helper
- I2: cue-point auto-disambiguation
- J1: `ableton_clip(action='read_notes')` MCP gap
- K1: polyrhythm helper using `fractions.Fraction`

### Items needing explicit user sign-off

ALL RESOLVED (2026-05-19):

1. ✅ **D1 / D3**: tractable engineering, not a v1.1 punt — route long envelopes through arrangement clips. W10-F chunk.
2. ✅ **D2**: confirmed no LOM path (D2 investigation); ship loud refusal in v1 at DB-mutator + planner layers with sub-bus teaching message (no M4L). W10-F chunk.
3. ✅ **H1**: ship loud refusal in v1; punt working impl to v1.1. W10-H chunk.
4. ✅ **W10 new chunks (E/F/G/H)**: scoped and Critic-marked above. Wave 10 grows from 4 chunks to 8.
5. ✅ **W14-B trigger**: confirmed triggered. Generators get parametrized on `beats_per_bar` (or renamed `*_4_4` + documented).

---

## Cross-cutting observations

**The brief's "headline targets" all failed.** Each canary was designed to stress a specific axis: long envelopes (solo-piano-ambient), third-party VST + repeated sections + master fade (full-band-rock), within-section meter ratchet (odd-meter-experimental). **All three headline targets surfaced architectural blockers**, not bugs. The good news: the canaries did exactly what Wave 0 was designed for. The harder news: the v1 reliability gate now has to absorb 3-4 explicit "ship vs. document non-support" decisions.

**The DB consistently held up; the push pipeline consistently fell short.** Every canary's DB-side build was clean. Every canary's push-side run found blockers. This is consistent with the architectural lock noted in `docs/v1-build-plan.md`: the DB is mature; the sync layer is where v1 reliability has to be earned.

**No data corruption, no Live wedges.** All three runs left Live in a clean-enough state for the next canary. The MCP surface degrades gracefully under partial state.

**The "per-phase ceremony" finding is the single highest-leverage fix.** Full-band-rock's 49 mix calls + 21 clip calls compounded into a time-cap that prevented the rest of the run from executing. Every realistic-size song will hit this. W10-E should be the first Wave 10 chunk shipped.
