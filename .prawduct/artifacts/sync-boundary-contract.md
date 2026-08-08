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
Line references are against this branch's HEAD (SYN-8Q3F chunks applied).

**The trust chain in one paragraph.** Planners are pure DB→plan functions: they
read the song DB + `ableton_links` and *never* talk to Live
(`push/plan.py:25-51` — the thunk contract). All Live truth enters through three
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
| Arrangement probe (`_probe_live_arrangement_clips_via_mcp`, wrapped by `_cmd_execute._probe_arrangement_lanes`) | per-track Live arrangement clip inventory, feeding the projection's clear | **NOT a pre-phase gate** (PSH-ARRPROBE): it is passed as a THUNK and resolved inside the arrangement phase's planner, because the map is keyed by Live track index and a first push CREATES those tracks in the `tracks` phase — a pre-phase map described the pre-push numbering and made every track read as unprobed. The thunk re-probes `ableton_track(list)` itself; it does NOT reuse the coherence probe's track list. A per-track probe failure still leaves the lane out of the map, and the arrangement planner still skips that track rather than guess — but now via `PushPlan.blocked`, so the phase reports `incomplete` (non-zero exit), not `skipped` |
| `probe_and_link` (separate subcommand, NOT run by execute; push/probe.py:360-748) | name-matched track/return links; W20-A device links by (parent, position, class); W18-B/SYN-3C8K/SYN-SCAFFOLD-MISLINK stale-link reconciliation | additive only (never deletes Live entities); duplicate names link-first + note; case near-matches noted, not linked |

## Executor cross-phase contract (`push_execute.execute_push`, push_execute.py:640-1576)

- **Phase-bounded error accumulation** (module docstring :15-19): within a phase
  every call runs and per-call failures accumulate (`_dispatch_calls`, :936-1103);
  at the phase boundary any failure **halts** (`_halt`, :1179-1205 — later phases
  PENDING). No internal retry; re-running `execute` IS the retry (push idempotent).
- **Connection loss halts immediately** mid-batch (:967-982, `_CONNECTION_EXCS` =
  `LiveConnectionError`/`OSError` only, :684-690) → outcome `connection_lost`,
  exit 2. Other exceptions from `send_fn` deliberately propagate (wire-protocol
  bugs must not be mislabeled connection loss).
- **Plan errors halt pre-dispatch** (:1237-1256): a planner's `plan.errors`
  (hard authoring error, `_core.py:57-63`) halts the phase with zero calls
  dispatched — the DB describes something unmaterializable.
- **Apply between phases** (:1325-1333, `_apply_results` :1104-1164): successes
  are applied even on a failed phase, so link rows are live for the next
  plan/convergence. Apply-layer warnings ride the errors file without flipping
  the phase.
- **State file always written** (`_flush_state`, :742-797): at every phase start,
  on mid-phase heartbeat (every 25 calls, :59), and terminally — atomic replace.
  `.last-push-errors.json` only on errors (stale one deleted on clean re-run,
  :1547-1548). The push is one attributed request row, closed with
  ok/partial/failed (:716-727, :1549-1567 — try/finally: the errors-file
  write cannot leave the request open, review W1). **A contract-drift `ValueError` from
  the apply layer is converted to a controlled phase halt (SYN-8Q3F Chunk 03) —
  see §Apply.**
- **Per-phase special-case passes** (complexity-budget rule 4 — new entries must
  be added here):
  - *devices*: diff-reconcile — re-probe `get_parameters` per device, drop
    already-current `device_parameter:` writes (:1277-1293 →
    `device_param_diff.py`; skip-on-confident-equal, keep-on-any-doubt).
  - *devices*: empty-rack guard — re-probe `get_device_chains` for each rack a
    nested write addresses; drop doomed writes, synthesize ONE clear failure
    (:1294-1306 main pass, :1364-1382 convergence pass → `empty_rack_guard.py`;
    suppress-on-confident-empty, keep-on-any-doubt).
  - *devices*: convergence re-plan — after an all-ok pass, re-run the planner once
    so params of devices loaded THIS pass land same-push (:1335-1392, SYN-9F2L).
  - *devices*: **pre-phase chain probe + link reconcile** (PSH-DEVDUP) — a
    lazily-resolved, once-per-push `ableton_device(list)` per linked parent
    (`_probe_live_device_chains`), fed to `reconcile_device_links` and then to
    the planner. Resolved INSIDE the devices `plan_fn`, so it sees the parents
    `tracks`/`returns` created. Without it "unlinked" was read as "absent" and
    push appended a SECOND copy of an FX chain Live already had.
  - *devices*: **post-phase integrity assert** (PSH-DEVDUP) — FRESH re-probe of
    every parent's chain vs the DB's authored device classes; HALT when Live
    carries MORE of a class the DB authors there (the duplication signature).
    Extra/short/drift and unreadable parents degrade to warnings. Runs on the
    dispatched path AND the "skipped, nothing to push" path — a doubled chain
    hides in the fully-linked state (`device_chain_verify.py`).
  - *devices*: post-phase pad probe — best-effort `pad_info` per linked Drum Rack,
    persisted via `M.replace_drum_pad_mappings`; never affects the outcome
    (:491-583, :804-826; runs on ok AND skipped, not on halt).
  - *devices dispatch fallbacks*: preset-URI miss → browser search + one retry
    (:305-398 M1-B); refused `value_display` → one retry as enum or normalized
    (:415-488 SYN-9F2L); orphan-param hint rewrite (:261-281 SYN-2D9K).
  - *arrangement*: post-phase integrity assert — FRESH re-probe of every clip's
    audible note set vs the DB collapsed set; HALT on silent corruption; per-clip
    probe failures degrade to a benign "N unverified" warning (:1423-1507,
    ARR-PROJ Chunk 3).
  - *cues*: handler-deferred cues (`skipped_out_of_range`) surface as benign
    warnings, never failures (:1039-1064, SYN-6B4Q).
  - *pre-loop*: alt-tuning notices (gated, inert for tuning_ref NULL;
    :1207-1218, MICROTUNE).

## Apply layer (`push/plan.py:485-623 apply_push_results`)

Table-driven on the `<kind>:` prefix of each result key: `_LINK_KINDS` (:351-363,
writes an `ableton_links` binding from the declared result field),
`_ACK_ONLY_KINDS` (:374-463, no DB write), the dedicated `perform_batch` branch
(:535-592, per-arc fingerprint recording gated on `automation_state == 1` +
`updates_written`, planned-vs-returned count cross-check). Failed results are
skipped (the executor already recorded them). Runs in ONE transaction (:523) — a
mid-batch raise rolls back every link in the batch.

**Unknown-kind policy (deliberate, SYN-8Q3F Chunk 03).** A key kind outside
`KNOWN_RESULT_KEY_KINDS` raises `ValueError` with the full key + the declaration
instruction (:619-624) — fail-loud, because a silent skip would mean a
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
| Push devices diff | `push/device_param_diff.py:44-55 _floats_equal` | `abs(a-b) <= max(1e-6, 1e-6·max(abs a, abs b))` — tight, rel+abs | a false EQUAL silently skips a dialed write (wrong mix); a false DIFFER is one redundant write. Skip only on proven equality. |
| Pull drift diff | `pull/_core.py:33 _FLOAT_EPS = 1e-3`; `_floats_differ` :123-135 (absolute), `_normalized_values_match` :138-149, `_raw_values_match` :152-168 (relative, floored) | loose — absorbs Live display-rounding (0.6249 vs 0.6250) | a false DIFFER churns a DB row + event on every pull; a false SAME misses a sub-0.1% hand nudge (musically negligible). |

**Cross-engine invariant (pinned by `tests/unit/sync/test_diff_float_semantics.py`):**
push-equal ⟹ pull-no-drift, **per channel** — any pair the push diff deems equal
(skips the write) the pull matcher for that value's channel must deem un-drifted;
otherwise a captured set churns: push skips the write, pull "detects" drift and
mutates the DB. The reverse gap (pull-same but push-differ) is safe and expected:
one redundant write, then fixed-point. **Channel boundary (found while pinning):**
the invariant holds *raw-vs-raw* (both relative) and *unit-scale-vs-absolute*
(bounded domain), but pairing push's relative 1e-6 against pull's ABSOLUTE
matchers at raw magnitudes violates it (18000.0 vs 18000.016 is push-equal yet
`_floats_differ`-drifted) — which is exactly why pull's raw channel uses the
relative `_raw_values_match` (DEV-4P7R). The test pins that disagreement as a
known boundary: any new pull comparison of raw-magnitude values must use the raw
matcher. One unsampled corner remains: push's normalized branch compares in RAW
space after projection (`device_param_diff.py:104-111`), so for a pathological
parameter range with |hi| >> hi−lo (ratio ≳1000) the same boundary exists inside
push's own normalized compare — realistic Live params sit well inside it. `arrangement_compare.py:44` (`DEFAULT_EPS_BEATS=1e-3`) is note-geometry
comparison, not a param diff engine — out of this invariant.

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
  **an UNLINKED device is no longer assumed absent** (PSH-DEVDUP): with a
  `live_devices_by_parent` probe map the planner emits a load ONLY for a
  position Live's authored chain does not reach, and REFUSES (hard `plan.error`,
  halt before dispatch) when the slot is occupied or the parent was unreadable.
  Without a map (pure-planner callers) the pre-PSH-DEVDUP "load on faith"
  behavior is preserved;
  nested devices arrive WITH the rack preset (never loaded, only param-addressed
  by `device_path`, :513-573); master devices load without a parent link
  (`master=True`, :77-92, DEV-6M2K).
- **Re-probes (executor-side, §Executor):** per-parent `ableton_device(list)`
  (PSH-DEVDUP pre-phase chain probe + link reconcile, and again post-phase for
  the integrity assert), per-device `get_parameters` (diff-reconcile), per-rack
  `get_device_chains` (empty-rack guard), post-phase `pad_info`.
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
- **Re-probes:** the arrangement probe (resolved at THIS phase, not before the
  loop — §Gates) supplies each track's current Live clips for the clear; a lane
  ABSENT from the probe map → `blocked` + skip that track (unknown state must
  not be cleared into). Probe map `None` (non-execute callers) → loud alert, no
  clear emitted (:155-161) — an alert, not `blocked`: everything is still
  planned.
  Post-phase: the executor's integrity assert re-probes every placement FRESH.
- **Failure/halt:** §6a all-or-nothing per track — every link validated BEFORE
  any of that track's calls (clear included) join the plan; an unmaterializable
  track emits nothing + `blocked` (audio/CLP-AUD2 → warn, a deliberate no-op)
  (:204-291). A phase carrying blocked reasons is reported `incomplete` with a
  non-zero exit and its reasons verbatim — never `skipped (idempotent)`. Clears emitted
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
plan.py:217-219, arrangement.py:491-507.)*

---

## Contract violations found (follow-up candidates — do NOT silently normalize)

- **V1 (fixed in SYN-8Q3F Chunk 02): phase-count prose drift.** "thirteen-phase" /
  "13 phases" in `push_execute.py`, `push_cli.py`, `push_notes.py`, `push/plan.py` (base-revision lines)
  vs 14 names in `_PHASE_NAMES` (the `device_sidechain` "9b." splice). Fixed on
  the files the chunk already touches.
- **V2 (open, behavior): a plan_fn raise escapes the executor as a raw
  traceback.** `plan = phase.plan_fn()` (push_execute.py:1229) is uncaught, so
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
  traceback.** The apply-layer `ValueError` (plan.py:619-624) propagated out of
  `execute_push` uncaught — no terminal state file, request left open, exit = a
  Python traceback. This is the runtime half of the twice-point-patched bug
  class. Now a controlled phase halt (§Apply).
- **V5 (fixed inline, prose): stale "via plan_push_clip" guidance.** Five
  operator-facing strings still named `plan_push_clip` as the track-creation
  path (moved to `plan_push_song_tracks` in W3-C): push/mix.py:91 (+ its
  docstring :39-42), pull/mix.py:96, pull/clips.py:56,115, pull/devices.py:221.
  Not test-pinned; corrected to name the tracks phase.
- **V8 (open, behavior): apply-layer non-ValueError raises reproduce V4.**
  The Chunk 03 halt net catches `ValueError` only; a `sqlite3.IntegrityError`
  from inside the apply transaction (e.g. `link_db_to_ableton`'s events
  INSERT against a row deleted mid-cycle — the PSH-3K9D bug-#2 shape) still
  escapes `execute_push` as a raw traceback with the request row left open.
  The transaction rollback still protects DB state, so not blocking — but
  the V4 closure is ValueError-deep, not exception-deep. Candidate for the
  V2 / Chunk-06 controlled-halt treatment; decide catch-widening there,
  with a DISTINCT hint (an integrity error is not "declare the kind").
- **V6 (open, prose): device_sidechain's deferral message names the wrong
  mechanism.** devices.py:687-690 says an unlinked device's sidechain is
  "deferred to the devices-convergence re-plan" — the convergence pass re-runs
  `plan_push_devices` only; what actually resolves the deferral is that the
  `device_sidechain` PHASE plans after the devices phase's apply. The branch is
  near-unreachable on the gated path (a failed load halts devices). → Chunk 06
  (message fix).
- **V7 (fixed in SYN-8Q3F Chunk 02, prose): `plan_push_song` docstring
  overclaimed the warn-not-empty convention.** The base-revision docstring said
  every empty phase carries a "no … to push" warn; `plan_push_song_tracks`/
  `_returns` return a bare empty plan when fully linked (tracks.py:44-45) and
  `plan_push_arrangement_clip_notes` emits neither. The Chunk 02 docstring
  rewrite (plan.py:222-228) now states both shapes are reported SKIPPED.

**Residual risk (documented design, not a violation):**
- **R1:** the coherence gate validates only track/return links; a stale *device*
  link whose parent survived is caught by nothing until the devices phase writes
  through it (probe.py:1003-1007 accepts this cost/benefit; ANALYZER-INDEX and
  SYN-SCAFFOLD-MISLINK each closed one concrete instance). Watch for a third
  instance before generalizing.
- **R2:** phase 12's fingerprint table is trust-without-verify of Live lane
  state by design (write-only surface); a hand-deleted Live lane whose arc
  fingerprint is unchanged will NOT be re-performed until the envelope changes.
