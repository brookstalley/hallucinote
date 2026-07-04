<!-- Sync boundary contract — SYN-8Q3F (audit 2026-07-02 rec #8). Tier 1 (Source of Truth).
     Derived from the phase IMPLEMENTATIONS (file:line referenced), not from prose.
     Complexity budget: a new push phase needs a section here (test-enforced:
     tests/unit/sync/test_sync_boundary_contract.py) AND a _PHASE_DEPS entry; a new
     executor special-case pass needs an entry in §Executor in the same change. -->
---
artifact: sync-boundary-contract
version: 1
scope: SYN-8Q3F
depends_on:
  - artifact: build-plan
    path: .prawduct/artifacts/plans/SYN-8Q3F/build-plan.md
last_validated: 2026-07-04
---

# Sync boundary contract — the 14 push phases

**Scope.** What each push phase may **assume** (from prior phases / the pre-phase
gates / the DB), what it must **re-probe from Live**, and its **failure/halt
policy** — plus the executor's cross-phase contract and the apply-layer dispatch.
Line references are against `feat/syn-8q3f-structural` @ develop 6f2b0ba.

**The trust chain in one paragraph.** Planners are pure DB→plan functions: they
read the song DB + `ableton_links` and *never* talk to Live
(`push/plan.py:25-48` — the thunk contract). All Live truth enters through three
doors: (1) the **pre-phase gates** (`push_cli._cmd_execute` — coherence check +
arrangement probe, §Gates), (2) **apply_push_results** writing link rows between
phases (§Apply), and (3) the **executor's explicit re-probe passes**
(`push_execute.py`, §Executor). A planner that "assumes X is linked" is therefore
really assuming: the coherence gate validated the parent links against a fresh
probe, and every prior phase that creates X halted the push if it failed.

---

## Gates (before any phase runs — `push_cli._cmd_execute`, push_cli.py:694-808)

| Gate | What it establishes | Failure policy |
|---|---|---|
| Phase-target validation (`push_execute.validate_phase_targets`, push_execute.py:91-131; called pre-probe at push_cli.py:763-774 per PSH-PHASEORDER) | `--only/--start-at/--stop-after` name real phases, coherent window | `PhaseTargetError` → stderr teaching message, exit 2, no Live traffic |
| Coherence check (`push/probe.py:976-1134 check_coherence`; wired push_cli.py:776-796) | session row exists; every `track`/`return` link points at a live index; no link points at a canonical default-scaffold track (set-swap signature) | refuse execute, exit 1, per-error `recovery` hints. **Opt-out:** `--no-coherence-check`. Nested links (clip/device) are NOT validated — a stale parent cascade-invalidates them (probe.py:1003-1007); residual risk note R1 below |
| Arrangement probe (`_probe_live_arrangement_clips_via_mcp`, push_cli.py:798-808) | per-track Live arrangement clip inventory, feeding the projection's clear | a per-track probe failure leaves the lane out of the map; the arrangement planner then skips that track with an alert (arrangement.py:191-202) rather than guess |
| `probe_and_link` (separate subcommand, NOT run by execute; push/probe.py:360-748) | name-matched track/return links; W20-A device links by (parent, position, class); W18-B/SYN-3C8K/SYN-SCAFFOLD-MISLINK stale-link reconciliation | additive only (never deletes Live entities); duplicate names link-first + note; case near-matches noted, not linked |

## Executor cross-phase contract (`push_execute.execute_push`, push_execute.py:640-1510)

- **Phase-bounded error accumulation** (module docstring :15-19): within a phase
  every call runs and per-call failures accumulate (`_dispatch_calls`, :936-1102);
  at the phase boundary any failure **halts** (`_halt`, :1145-1171 — later phases
  PENDING). No internal retry; re-running `execute` IS the retry (push idempotent).
- **Connection loss halts immediately** mid-batch (:967-982, `_CONNECTION_EXCS` =
  `LiveConnectionError`/`OSError` only, :684-690) → outcome `connection_lost`,
  exit 2. Other exceptions from `send_fn` deliberately propagate (wire-protocol
  bugs must not be mislabeled connection loss).
- **Plan errors halt pre-dispatch** (:1203-1222): a planner's `plan.errors`
  (hard authoring error, `_core.py:57-63`) halts the phase with zero calls
  dispatched — the DB describes something unmaterializable.
- **Apply between phases** (:1291-1292, `_apply_results` :1104-1129): successes
  are applied even on a failed phase, so link rows are live for the next
  plan/convergence. Apply-layer warnings ride the errors file without flipping
  the phase.
- **State file always written** (`_flush_state`, :742-797): at every phase start,
  on mid-phase heartbeat (every 25 calls, :59), and terminally — atomic replace.
  `.last-push-errors.json` only on errors (stale one deleted on clean re-run,
  :1481-1485). The push is one attributed request row, closed with
  ok/partial/failed (:716-727, :1487-1499). **A contract-drift `ValueError` from
  the apply layer is converted to a controlled phase halt (SYN-8Q3F Chunk 03) —
  see §Apply.**
- **Per-phase special-case passes** (complexity-budget rule 4 — new entries must
  be added here):
  - *devices*: diff-reconcile — re-probe `get_parameters` per device, drop
    already-current `device_parameter:` writes (:1243-1259 →
    `device_param_diff.py`; skip-on-confident-equal, keep-on-any-doubt).
  - *devices*: empty-rack guard — re-probe `get_device_chains` for each rack a
    nested write addresses; drop doomed writes, synthesize ONE clear failure
    (:1260-1272 main pass, :1324-1342 convergence pass → `empty_rack_guard.py`;
    suppress-on-confident-empty, keep-on-any-doubt).
  - *devices*: convergence re-plan — after an all-ok pass, re-run the planner once
    so params of devices loaded THIS pass land same-push (:1301-1349, SYN-9F2L).
  - *devices*: post-phase pad probe — best-effort `pad_info` per linked Drum Rack,
    persisted via `M.replace_drum_pad_mappings`; never affects the outcome
    (:491-583, :804-826; runs on ok AND skipped, not on halt).
  - *devices dispatch fallbacks*: preset-URI miss → browser search + one retry
    (:305-398 M1-B); refused `value_display` → one retry as enum or normalized
    (:415-488 SYN-9F2L); orphan-param hint rewrite (:261-281 SYN-2D9K).
  - *arrangement*: post-phase integrity assert — FRESH re-probe of every clip's
    audible note set vs the DB collapsed set; HALT on silent corruption; per-clip
    probe failures degrade to a benign "N unverified" warning (:1370-1453,
    ARR-PROJ Chunk 3).
  - *cues*: handler-deferred cues (`skipped_out_of_range`) surface as benign
    warnings, never failures (:1039-1064, SYN-6B4Q).
  - *pre-loop*: alt-tuning notices (gated, inert for tuning_ref NULL;
    :1173-1184, MICROTUNE).

## Apply layer (`push/plan.py:400-538 apply_push_results`)

Table-driven on the `<kind>:` prefix of each result key: `_LINK_KINDS` (:285-297,
writes an `ableton_links` binding from the declared result field),
`_ACK_ONLY_KINDS` (:308-397, no DB write), the dedicated `perform_batch` branch
(:450-507, per-arc fingerprint recording gated on `automation_state == 1` +
`updates_written`, planned-vs-returned count cross-check). Failed results are
skipped (the executor already recorded them). Runs in ONE transaction (:438) — a
mid-batch raise rolls back every link in the batch.

**Unknown-kind policy (deliberate, SYN-8Q3F Chunk 03).** A key kind outside
`KNOWN_RESULT_KEY_KINDS` raises `ValueError` with the full key + the declaration
instruction (:533-537) — fail-loud, because a silent skip would mean a
planner-emitted write records nothing and re-fires every push (the exact
silent-drop the table exists to prevent). Three layers close the class:

1. **Static exhaustiveness guard** (`tests/unit/sync/test_push.py
   test_every_emitted_push_key_kind_is_declared` + pull twin): every `key=` literal
   any planner emits must be declared. Adding a planner kind without an apply
   policy fails the suite — the structural fix for the twice-shipped bug
   (`device_param_override` 2026-06-18, `device_chain_props` 2026-06-20).
2. **Registry constant** `KNOWN_RESULT_KEY_KINDS` — the single union the guard,
   the apply dispatch, and the error message share.
3. **Controlled runtime halt**: `execute_push` catches the apply-layer
   `ValueError` (genuinely-unknown kind — reachable only from a non-planner
   result source or cross-version skew — or a malformed key/arc) and halts the
   phase with the teaching message in the errors file, terminal state written,
   request closed `partial`, exit `EXIT_PARTIAL`. Before SYN-8Q3F this escaped as
   a raw traceback (violation V4, fixed).

## Diff engines (float equality — two engines, intentionally asymmetric)

| Engine | Site | Semantics | Failure asymmetry that justifies it |
|---|---|---|---|
| Push devices diff | `push/device_param_diff.py:44-48 _floats_equal` | `abs(a-b) <= max(1e-6, 1e-6·max(abs a, abs b))` — tight, rel+abs | a false EQUAL silently skips a dialed write (wrong mix); a false DIFFER is one redundant write. Skip only on proven equality. |
| Pull drift diff | `pull/_core.py:21 _FLOAT_EPS = 1e-3`; `_floats_differ` :111-123 (absolute), `_normalized_values_match` :126-137, `_raw_values_match` :140-156 (relative, floored) | loose — absorbs Live display-rounding (0.6249 vs 0.6250) | a false DIFFER churns a DB row + event on every pull; a false SAME misses a sub-0.1% hand nudge (musically negligible). |

**Cross-engine invariant (pinned by `tests/unit/sync/test_diff_float_semantics.py`):**
push epsilon ≤ pull epsilon, i.e. any pair the push diff deems equal (skips the
write) the pull diff must deem un-drifted — otherwise a captured set would
oscillate: push skips the write, pull "detects" drift, mutates the DB, push then
differs again. The reverse gap (pull-same but push-differ) is safe: one redundant
write, then fixed-point. `arrangement_compare.py:44` (`DEFAULT_EPS_BEATS=1e-3`)
is note-geometry comparison, not a param diff engine — out of this invariant.

---

## The 14 phases

Order + dependency data: `push/plan.py` `_PHASE_NAMES` / `_PHASE_DEPS`
(SYN-8Q3F Chunk 02 — the executor runs the declared tuple; the validator proves
the tuple satisfies the declared deps). "Assumes" = trusted without checking
Live; every phase additionally assumes the §Gates ran (links truthful).

### 1. `tempo_map` (`push/tempo.py:11-51`)
- **Assumes:** nothing from prior phases; DB `tempo_map` rows.
- **Re-probes:** nothing.
- **Failure/halt:** no error path of its own; bar-1 row → one `set_tempo` call;
  non-bar-1 rows skipped with warn (LOM gap — no per-bar tempo automation).
  Per-call failure → boundary halt. Ack-only key `tempo_point:`.

### 2. `time_signature_map` (`push/tempo.py:54-100`)
- Symmetric with tempo_map (`time_signature_point:` ack-only; same LOM gap warn).

### 3. `tracks` (`push/tracks.py:12-73`)
- **Assumes:** link rows are truthful (gate-validated) — emits `create` only for
  unlinked non-master tracks; master skipped (no Live-side create).
- **Re-probes:** nothing.
- **Failure/halt:** per-call failure → boundary halt (everything downstream needs
  tracks, so halting here is load-bearing). Link recorded from `track_index`
  (`_LINK_KINDS`). Idempotent: fully-linked song → empty plan (SKIPPED).

### 4. `returns` (`push/tracks.py:76-105`)
- Mirror of tracks for returns (`return:` link kind).

### 5. `scenes` (`push/scenes.py:25-63`)
- **Assumes:** DB clip `slot` values are the needed scene count (derived from the
  same rows the clips phase reads, so they can't disagree).
- **Re-probes:** Live-side — the `ensure_count` handler reads `len(song.scenes)`
  and appends the deficit; the planner never reads the current count.
- **Failure/halt:** single idempotent call, ack-only (`scene:`); failure →
  boundary halt (clips would IndexError without it — SYN-4P2D).

### 6. `clips` (`push/clips.py:11-154`)
- **Assumes:** **every clip's track linked — RAISES `ValueError` otherwise**
  (clips.py:72-80, W3-C strict; see violation V2 for how that raise surfaces).
  Assumes scenes provisioned (phase 5). Linked-clip slot content is irrelevant:
  `create` carries `replace=True` (:88-103) so an occupied slot is replaced —
  re-probe avoided by making the write state-independent.
- **Re-probes:** nothing.
- **Failure/halt:** audio clips refuse-with-warn (CLP-AUD1, :51-61 — a MIDI
  create would corrupt the slot). Per-call failure → boundary halt. `clip:` link
  kind (create returns `clip_index`; `replace_notes` returns none → link skip,
  plan.py:516-520).

### 7. `mix` (`push/mix.py:25-176`)
- **Assumes:** tracks + returns linked. Master needs no link
  (`set_master_property`, :61-83). Only non-NULL DB fields are written (:95-98) —
  NULL means "never authored", never "reset Live".
- **Re-probes:** nothing — unconditional idempotent re-emit (no diff pass; cheap
  LOM writes).
- **Failure/halt:** unlinked track → warn + skip (:88-93). Unlinked return →
  **emits the create itself** (:116-127 — violation V3, phase overlap with
  phase 4). Send with either end unlinked → warn + skip (:158-163). Per-call
  failure → boundary halt. All keys ack-only except the fallback `return:`.

### 8. `devices` (`push/devices.py:28-638`)
- **Assumes:** tracks/returns linked (warn + skip whole parent otherwise,
  :96-103/:119-126); device links truthful — a linked device's load is skipped
  entirely, trusting W20-A probe matching + SYN-SCAFFOLD-MISLINK cascades;
  nested devices arrive WITH the rack preset (never loaded, only param-addressed
  by `device_path`, :513-573); master devices load without a parent link
  (`master=True`, :77-92, DEV-6M2K).
- **Re-probes (executor-side, §Executor):** per-device `get_parameters`
  (diff-reconcile), per-rack `get_device_chains` (empty-rack guard), post-phase
  `pad_info`.
- **Failure/halt:** placeholder + analyzer rows skip-with-warn (:164-185).
  Param with no writable form → operator **alert**, never a silent drop
  (:499-510, SYN-9F2L). Corrupt stored JSON (browser_path/preset_query/override
  path) → warn/alert + degrade (:236-272, :401-409). Per-call failure → boundary
  halt, after the executor's one-shot fallbacks. Keys: `device:` (link),
  `device_parameter:` / `device_param_override:` / `device_chain_props:`
  (ack-only).

### 9. `routing` (`push/routing.py:52-222`)
- **Assumes:** tracks linked; **devices loaded** (a MIDI track exposes *audio*
  output routing — the only kind that can target a submaster bus — only once an
  instrument is loaded, RTE-2P9X); a track-target's Live display name == its DB
  `name` (push created it with that name, D6).
- **Re-probes:** nothing (deliberate — D7, no fingerprint gate; idempotent
  re-emit like mix).
- **Failure/halt:** unlinked track → warn + skip (:101-117, deliberately `warn`
  not `alert` — unreachable on the gated path). Dangling/unresolvable/unknown
  routing target → **alert** + skip that direction (:161-201). Per-call failure →
  boundary halt. Ack-only keys.

### 10. `device_sidechain` (`push/devices.py:641-742`)
- **Assumes:** devices linked (phase 8 — its plan runs after devices' apply);
  source track exists in Live under its DB `name` (FK resolved to display name,
  same D6 convention as routing); source track's own link only needed to prove
  it's in the song (`by_id`, :663).
- **Re-probes:** nothing.
- **Failure/halt:** source FK not in the song → **alert** + skip (:676-681);
  unlinked device → warn + skip (:686-690 — see violation V6 on the message's
  wrong mechanism claim). Per-call failure → boundary halt. Ack-only
  (`device_sidechain:`).

### 11. `envelopes` (`push/envelopes.py:45-163` + emitters)
- **Assumes:** tracks/clips/returns/devices linked (each emitter warn+skips a
  missing link — :434-482, :678-690, :756-770, :829-838, :899-912); a covering
  session-clip placement exists for clip-hosted rides (geometry computed from the
  DB, never re-probed); runs BEFORE arrangement (W4-A — `duplicate_to_arrangement`
  snapshots the session clip, so clip envelopes must exist first).
- **Re-probes:** nothing.
- **Failure/halt:** `clip_cc`/`clip_pitch_bend` → warn + skip (LOM gap, :97-119);
  perform-routed families are NOT emitted here (noted + left to phase 12,
  ENV-7G4K/9P4T); zero-breakpoint → warn + skip. **Unknown `target_kind` RAISES
  `ValueError`** (:159-162, schema-belt; same plan_fn-raise surface as V2).
  Per-call failure → boundary halt. `envelope:` link kind (handler returns
  `envelope_index`).

### 12. `performed_automation` (`push/perform.py:325-508`)
- **Assumes:** tracks/returns/devices linked (per-arc warn + "arc pending, next
  push retries", :108-262); the `performed_automation` fingerprint table is an
  honest memory of what Live's lanes hold (NOT re-probed — the perform surface is
  write-only; an unchanged fingerprint means "do not re-record", which is what
  protects hand-edited Live lanes); `perform_target_key` stays field-identical to
  the handler's `_PreparedArc.addressing_key()` (cross-package parity test,
  :265-307).
- **Re-probes:** verification is handler-side: per-arc `automation_state == 1` +
  `updates_written > 0` gate the fingerprint write at apply
  (perform.py:511-571) — an unverified arc re-performs next push.
- **Failure/halt:** duplicate-target arcs: recorded lanes claimed first, extra
  arcs **alert** + defer (:424-454, ENV-8K2R #3). One `perform_batch:` call with
  a derived read ceiling (:487-496) — realtime cost surfaced via alert. Restore
  failures + count mismatches → apply warnings (plan.py:461-506). Watchdog for a
  dead worker = **PSH-3H8M**, not this contract.

### 13. `arrangement` (`push/arrangement.py:91-331`)
- **Assumes:** tracks linked (alert + skip whole track otherwise); envelope-bearing
  placements' source clips linked (duplicate route); the DB is the ONLY author of
  the timeline (projection: clear then rebuild, ARR-PROJ).
- **Re-probes:** the pre-phase arrangement probe supplies each track's current
  Live clips for the clear (§Gates); a lane ABSENT from the probe map → alert +
  skip that track (:191-202 — unknown state must not be cleared into). Probe map
  `None` (non-execute callers) → loud alert, no clear emitted (:155-161).
  Post-phase: the executor's integrity assert re-probes every placement FRESH.
- **Failure/halt:** §6a all-or-nothing per track — every link validated BEFORE
  any of that track's calls (clear included) join the plan; an unmaterializable
  track emits nothing + alert (audio/CLP-AUD2 → warn) (:204-291). Clears emitted
  descending-index (:298-320). Per-call failure → boundary halt;
  `ArrangementIntegrityError` → halt (silent corruption must not report OK).
  Keys: `arrangement_clip:` (link), `arrangement_clip_clear:` /
  `arrangement_clip_notes:` (ack-only).

### 14. `cues` (`push/arrangement.py:334-488`)
- **Assumes:** arrangement materialized (Live clamps `set_or_delete_cue` to
  `[0, last_event_time]`); DB arrangement extent = the authored truth for "can
  this cue EVER be placed".
- **Re-probes:** none client-side; the handler answers the runtime half
  ("placeable NOW?") via `on_out_of_range='skip'` — deferred cues report back as
  benign warnings (§Executor).
- **Failure/halt:** cue past the composed extent → **`plan.error`** → phase halts
  pre-dispatch with the DB-grounded message (:408-428, SYN-6B4Q); no arrangement
  authored → all deferred with warn (:429-435). Duplicate names auto-suffixed at
  plan time (:437-459, W19-E). One `cue_batch:` call, `if_exists='skip'`
  (idempotent re-push). Ack-only.

*(`plan_push_sections` is deliberately NOT a phase — no canonical Live surface;
plan.py:156-158, arrangement.py:491-507.)*

---

## Contract violations found (follow-up candidates — do NOT silently normalize)

- **V1 (fixed in SYN-8Q3F Chunk 02): phase-count prose drift.** "thirteen-phase" /
  "13 phases" in `push_execute.py:2,656`, `push_cli.py:695`, `push/plan.py:80,160`
  vs 14 names in `_PHASE_NAMES` (the `device_sidechain` "9b." splice). Fixed on
  the files the chunk already touches.
- **V2 (open, behavior): a plan_fn raise escapes the executor as a raw
  traceback.** `plan = phase.plan_fn()` (push_execute.py:1195) is uncaught, so
  the clips planner's W3-C strict `ValueError` (clips.py:72-80) — reachable via
  `--only clips` / `--start-at clips` against unlinked tracks — and the envelopes
  unknown-target-kind raise (envelopes.py:159-162) bypass the terminal state
  write and leave the request row open. Same class as V4; should become a
  controlled halt. → build-plan Chunk 06.
- **V3 (open, design): the mix phase owns a second return-creation path.**
  `plan_push_mix` emits `ableton_return(create)` for unlinked returns
  (mix.py:116-127), duplicating phase 4's job. Unreachable on the gated full-push
  path (returns halts first) but live under `--only mix` / direct planner calls —
  two phases can create the same entity kind. Decide: drop the fallback (strict,
  matches clips' W3-C posture) or keep for direct-call ergonomics and document.
  → Chunk 06.
- **V4 (fixed in SYN-8Q3F Chunk 03): unknown result kind escaped as a
  traceback.** The apply-layer `ValueError` (plan.py:533-537) propagated out of
  `execute_push` uncaught — no terminal state file, request left open, exit = a
  Python traceback. This is the runtime half of the twice-point-patched bug
  class. Now a controlled phase halt (§Apply).
- **V5 (fixed inline, prose): stale "via plan_push_clip" guidance.** Five
  operator-facing strings still named `plan_push_clip` as the track-creation
  path (moved to `plan_push_song_tracks` in W3-C): push/mix.py:91 (+ its
  docstring :39-42), pull/mix.py:96, pull/clips.py:56,114, pull/devices.py:221.
  Not test-pinned; corrected to name the tracks phase.
- **V6 (open, prose): device_sidechain's deferral message names the wrong
  mechanism.** devices.py:687-690 says an unlinked device's sidechain is
  "deferred to the devices-convergence re-plan" — the convergence pass re-runs
  `plan_push_devices` only; what actually resolves the deferral is that the
  `device_sidechain` PHASE plans after the devices phase's apply. The branch is
  near-unreachable on the gated path (a failed load halts devices). → Chunk 06
  (message fix).
- **V7 (open, prose): `plan_push_song` docstring overclaims the warn-not-empty
  convention.** plan.py:160-166 says every empty phase carries a "no … to push"
  warn; `plan_push_song_tracks`/`_returns` return a bare empty plan when fully
  linked (tracks.py:44-45) and `plan_push_arrangement_clip_notes` emits neither.
  The executor treats both identically (SKIPPED), so behavior is fine — align the
  prose or the planners. → Chunk 06.

**Residual risk (documented design, not a violation):**
- **R1:** the coherence gate validates only track/return links; a stale *device*
  link whose parent survived is caught by nothing until the devices phase writes
  through it (probe.py:1003-1007 accepts this cost/benefit; ANALYZER-INDEX and
  SYN-SCAFFOLD-MISLINK each closed one concrete instance). Watch for a third
  instance before generalizing.
- **R2:** phase 12's fingerprint table is trust-without-verify of Live lane
  state by design (write-only surface); a hand-deleted Live lane whose arc
  fingerprint is unchanged will NOT be re-performed until the envelope changes.
