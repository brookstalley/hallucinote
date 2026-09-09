<!-- Sync boundary contract — SYN-8Q3F (audit 2026-07-02 rec #8). Tier 1 (Source of Truth).
     Derived from the phase IMPLEMENTATIONS (module + symbol, never line numbers —
     see the note under Scope), not from prose.
     Complexity budget: a new push phase needs a section here (test-enforced:
     tests/unit/sync/test_sync_boundary_contract.py) AND a _PHASE_DEPS entry; a new
     executor special-case pass needs an entry in §Executor in the same change. -->
---
artifact: sync-boundary-contract
version: 1
scope: SYN-8Q3F
depends_on:
  - artifact: build-plan
    path: .prawduct/artifacts/plans/SYN-8Q3F/archive/build-plan.md
last_validated: 2026-07-04
---

# Sync boundary contract — the 14 push phases

**Scope.** What each push phase may **assume** (from prior phases / the pre-phase
gates / the DB), what it must **re-probe from Live**, and its **failure/halt
policy** — plus the executor's cross-phase contract and the apply-layer dispatch.

**Citations name symbols, never line numbers.** A line range is a claim that
goes stale on the next edit to the file it points at, silently — this artifact
carried ~70 of them and a single bundle invalidated a third. Every reference
here names the module and the function, which a grep resolves and a refactor
carries with it.

**The trust chain in one paragraph.** Planners are pure DB→plan functions: they
read the song DB + `ableton_links` and *never* talk to Live
(`push/plan.py` — the thunk contract). All Live truth enters through three
doors: (1) the **pre-phase gates** (`push_cli._cmd_execute` — coherence check +
arrangement probe, §Gates), (2) **apply_push_results** writing link rows between
phases (§Apply), and (3) the **executor's explicit re-probe passes**
(`push_execute.py`, §Executor). A planner that "assumes X is linked" is therefore
really assuming: the coherence gate validated the parent links against a fresh
probe, and every prior phase that creates X halted the push if it failed.

---

## Gates (before any phase runs — `push_cli._cmd_execute`, push_cli.py)

| Gate | What it establishes | Failure policy |
|---|---|---|
| Phase-target validation (`push_execute.validate_phase_targets`, push_execute.py; called pre-probe at push_cli.py per PSH-PHASEORDER) | `--only/--start-at/--stop-after` name real phases, coherent window | `PhaseTargetError` → stderr teaching message, exit 2, no Live traffic |
| Coherence check (`push/probe.py check_coherence`; wired push_cli.py) | session row exists; every `track`/`return` link points at a live index; no link points at a canonical default-scaffold track (set-swap signature) | refuse execute, exit 1, per-error `recovery` hints. **Opt-out:** `--no-coherence-check`. Nested links (clip/device) are NOT validated — a stale parent cascade-invalidates them (probe.py); residual risk note R1 below |
| Arrangement probe (`_probe_live_arrangement_clips_via_mcp`, wrapped by `_cmd_execute._probe_arrangement_lanes`) | per-track Live arrangement clip inventory, feeding the projection's clear | **NOT a pre-phase gate** (PSH-ARRPROBE): it is passed as a THUNK and resolved inside the arrangement phase's planner, because the map is keyed by Live track index and a first push CREATES those tracks in the `tracks` phase — a pre-phase map described the pre-push numbering and made every track read as unprobed. The thunk re-probes `ableton_track(list)` itself; it does NOT reuse the coherence probe's track list. A per-track probe failure still leaves the lane out of the map, and the arrangement planner still skips that track rather than guess — but now via `PushPlan.blocked`, so the phase reports `incomplete` (non-zero exit), not `skipped` |
| `probe_and_link` (separate subcommand, NOT run by execute; push/probe.py) | name-matched track/return links; W20-A device links by (parent, position, class); W18-B/SYN-3C8K/SYN-SCAFFOLD-MISLINK stale-link reconciliation | additive only (never deletes Live entities); duplicate names link-first + note; case near-matches noted, not linked |

## Executor cross-phase contract (`push_execute.execute_push`, push_execute.py)

- **Phase-bounded error accumulation** (module docstring): within a phase
  every call runs and per-call failures accumulate (`_dispatch_calls`);
  at the phase boundary any failure **halts** (`_halt` — later phases
  PENDING). No internal retry; re-running `execute` IS the retry (push idempotent).
- **Connection loss halts immediately** mid-batch (`_CONNECTION_EXCS` =
  `LiveConnectionError`/`OSError` only) → outcome `connection_lost`,
  exit 2. Other exceptions from `send_fn` deliberately propagate (wire-protocol
  bugs must not be mislabeled connection loss).
- **Plan errors halt pre-dispatch**: a planner's `plan.errors`
  (hard authoring error, `_core.py`) halts the phase with zero calls
  dispatched — the DB describes something unmaterializable.
- **Apply between phases** (`_apply_results`): successes
  are applied even on a failed phase, so link rows are live for the next
  plan/convergence. Apply-layer warnings ride the errors file without flipping
  the phase.
- **State file always written** (`_flush_state`): at every phase start,
  on mid-phase heartbeat (every 25 calls), and terminally — atomic replace.
  `.last-push-errors.json` only on errors (stale one deleted on clean re-run).
  The push is one attributed request row, closed with ok/partial/failed
  (try/finally: the errors-file write cannot leave the request open, review W1).
  **A contract-drift `ValueError` from
  the apply layer is converted to a controlled phase halt (SYN-8Q3F Chunk 03) —
  see §Apply.**
- **Per-phase special-case passes** (complexity-budget rule 4 — new entries must
  be added here):
  - *devices*: diff-reconcile — re-probe `get_parameters` per device, drop
    already-current `device_parameter:` writes (→
    `device_param_diff.py`; skip-on-confident-equal, keep-on-any-doubt).
  - *devices*: empty-rack guard — re-probe `get_device_chains` for each rack a
    nested write addresses; drop doomed writes, synthesize ONE clear failure
    (both the main pass and the convergence pass → `empty_rack_guard.py`;
    suppress-on-confident-empty, keep-on-any-doubt).
  - *devices*: convergence re-plan — after an all-ok pass, re-run the planner once
    so params of devices loaded THIS pass land same-push (SYN-9F2L).
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
    (runs on ok AND skipped, not on halt).
  - *devices dispatch fallbacks*: preset-URI miss → browser search + one retry
    (M1-B); refused `value_display` → one retry as enum or normalized
    (SYN-9F2L); orphan-param hint rewrite (SYN-2D9K).
  - *arrangement*: post-phase integrity assert — FRESH re-probe of every clip's
    audible note set vs the DB collapsed set; HALT on silent corruption; per-clip
    NOTE probe failures degrade to a benign "N unverified" warning (ARR-PROJ Chunk 3). ARR-ORPHAN2: a per-track LANE probe failure
    (`ableton_clip(list, location='arrangement')`) does NOT degrade — it is
    `lane_probe_failed`, counted as corruption, and HALTs. The planner reads the
    clear inventory from that same probe, so an unreadable lane was never cleared
    and never rebuilt, and orphan detection could not run on it.
  - *cues*: handler-deferred cues (`skipped_out_of_range`) surface as benign
    warnings, never failures (SYN-6B4Q).
  - *pre-loop*: alt-tuning notices (gated, inert for tuning_ref NULL; MICROTUNE).

## Apply layer (`push/plan.py apply_push_results`)

Table-driven on the `<kind>:` prefix of each result key: `_LINK_KINDS` (writes
an `ableton_links` binding from the declared result field),
`_ACK_ONLY_KINDS` (no DB write), the dedicated `perform_batch` branch
(per-arc fingerprint recording gated on the handler's `outcome`, with
`automation_state == 1` + `updates_written` as the floor for a server that
predates the field; planned-vs-returned count cross-check). Failed results are
skipped (the executor already recorded them). Runs in ONE transaction — a
mid-batch raise rolls back every link in the batch.

**Two channels out, and the split is load-bearing.** The return value is the
ACTIONABLE one: `push_execute` writes it into `.last-push-errors.json`, so
anything put there makes a clean push look failed. The optional `notes_sink`
callable is the BENIGN one, wired to the same `warnings` list the push state
file already carries. The perform phase's per-arc roll-up goes there — a
realtime phase that spends minutes of wall clock and reports `ok (1 call)`
leaves an author with nothing to act on, which is how a whole session's
divergence went unnoticed until it was heard (issue #471, ask 3). `notes_sink`
is optional; its absence costs the roll-up and nothing else.

**The `outcome` string is the contract.** The engine does not import the MCP
package — they ship and version separately — so `push/perform.py`'s
`PERFORM_OUTCOME_RECORDED` and `handlers/automation.py`'s constant of the same
name are two spellings of one wire value (`"recorded"`). Anything else the
handler reports is a non-recording, whatever it is called, so the apply layer
branches on inequality rather than on an enumeration it would have to keep in
step.

**Unknown-kind policy (deliberate, SYN-8Q3F Chunk 03).** A key kind outside
`KNOWN_RESULT_KEY_KINDS` raises `ValueError` with the full key + the declaration
instruction — fail-loud, because a silent skip would mean a
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
| Push devices diff | `push/device_param_diff.py _floats_equal` | `abs(a-b) <= max(1e-6, 1e-6·max(abs a, abs b))` — tight, rel+abs | a false EQUAL silently skips a dialed write (wrong mix); a false DIFFER is one redundant write. Skip only on proven equality. |
| Pull drift diff | `pull/_core.py _FLOAT_EPS = 1e-3`; `_floats_differ` (absolute), `_normalized_values_match`, `_raw_values_match` (relative, floored) | loose — absorbs Live display-rounding (0.6249 vs 0.6250) | a false DIFFER churns a DB row + event on every pull; a false SAME misses a sub-0.1% hand nudge (musically negligible). |

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
space after projection (`device_param_diff.py`), so for a pathological
parameter range with |hi| >> hi−lo (ratio ≳1000) the same boundary exists inside
push's own normalized compare — realistic Live params sit well inside it. `arrangement_compare.py` (`DEFAULT_EPS_BEATS=1e-3`) is note-geometry
comparison, not a param diff engine — out of this invariant.

---

## The 14 phases

Order + dependency data: `push/plan.py` `_PHASE_NAMES` / `_PHASE_DEPS`
(SYN-8Q3F Chunk 02 — the executor runs the declared tuple; the validator proves
the tuple satisfies the declared deps). "Assumes" = trusted without checking
Live; every phase additionally assumes the §Gates ran (links truthful).

### 1. `tempo_map` (`push/tempo.py`)
- **Assumes:** nothing from prior phases; DB `tempo_map` rows.
- **Re-probes:** nothing.
- **Failure/halt:** no error path of its own; bar-1 row → one `set_tempo` call;
  non-bar-1 rows skipped with an alert (LOM gap — no per-bar tempo automation).
  Per-call failure → boundary halt. Ack-only key `tempo_point:`.

### 2. `time_signature_map` (`push/tempo.py`)
- Symmetric with tempo_map (`time_signature_point:` ack-only; same LOM gap alert).
- **This phase is where the meter reach limit is enforced, and nowhere else.**
  The DB records the song's true meter map (within-song changes included); this
  planner pushes the bar-1 row, skips the rest, and alerts that Live's ruler will
  show the bar-1 meter for the whole song. The two-bar-ruler divergence is NOT
  reported here — it is reported where bar positions actually become beats, in
  §13 and §14.

### 3. `tracks` (`push/tracks.py`)
- **Assumes:** link rows are truthful (gate-validated) — emits `create` only for
  unlinked non-master tracks; master skipped (no Live-side create).
- **Re-probes:** nothing.
- **Failure/halt:** per-call failure → boundary halt (everything downstream needs
  tracks, so halting here is load-bearing). Link recorded from `track_index`
  (`_LINK_KINDS`). Idempotent: fully-linked song → empty plan (SKIPPED).

### 4. `returns` (`push/tracks.py`)
- Mirror of tracks for returns (`return:` link kind).

### 5. `scenes` (`push/scenes.py`)
- **Assumes:** DB clip `slot` values are the needed scene count (derived from the
  same rows the clips phase reads, so they can't disagree).
- **Re-probes:** Live-side — the `ensure_count` handler reads `len(song.scenes)`
  and appends the deficit; the planner never reads the current count.
- **Failure/halt:** single idempotent call, ack-only (`scene:`); failure →
  boundary halt (clips would IndexError without it — SYN-4P2D).

### 6. `clips` (`push/clips.py`)
- **Assumes:** **every clip's track linked — RAISES `ValueError` otherwise**
  (clips.py, W3-C strict; see violation V2 for how that raise surfaces).
  Assumes scenes provisioned (phase 5). For a MIDI clip the linked slot's
  content is irrelevant: `create` carries `replace=True` so an occupied slot is
  replaced, and the write is state-independent by construction.
- **Audio clips materialize here** (SMP-6V2K): a `kind='audio'` row plans a
  create carrying the resolved absolute path, plus one `set_property` per
  authored conform field (gain, pitch coarse/fine, warping, warp mode, start and
  end marker) keyed `clip_conform:{clip_id}:{property}`, ack-only because the
  value originates in the DB and records no Live-side index. **The file's
  existence is checked before the call is planned** — a clip that pushes and
  then plays silence is the "reported OK without determining state" failure this
  contract forbids, so a missing sample is `blocked`, not `error`: `error` halts
  the phase before dispatch and one typo'd path would stop a thirty-clip song
  pushing anything.
- **State-independence does NOT extend to audio.** `Clip.file_path` is
  read-only, so which file a slot plays can only be changed by delete-and-
  recreate — a destructive reconcile the MIDI path never had. The phase
  therefore accepts an optional session-clip probe (`live_session_clips_by_track`)
  and diffs against it: same file → conform in place; slot empty → recreate;
  file changed → **blocked**, because whether a recreate preserves the clip's
  envelopes is unprobed and neither dropping a ride nor re-emitting one that
  survived is known-good. **Probe-less is the safe degradation** — conform in
  place, no create, no delete — and it announces itself with an alert rather
  than acting on a guess. The execute path supplies it as a thunk resolved inside the
  phase, so it sees the tracks the `tracks` phase created on a first push.
  **A track whose probe FAILED is absent from the map, and absence is not
  emptiness** — the reader is tri-state (`PROBE_UNKNOWN`), because answering an
  unknown slot as an empty one plans a `replace=True` recreate against a clip
  the operator really has. The two unknown cases report differently, and the
  channel is the contract: **no probe at all** (a caller that deliberately did
  not probe) is a `warn` plus one song-level alert; **this track's probe
  failed** is `blocked`, so the phase reports `incomplete` with a non-zero
  exit — same ruling as the arrangement phase's per-track probe failure, for
  the same reason. A conform written without verifying which file Live holds
  must not exit 0 in silence.
- **Re-probes:** nothing on its own; the session-clip probe above is supplied by
  the caller (dict or thunk), never taken by the phase.
- **Failure/halt:** Per-call failure → boundary halt. `clip:` link
  kind (create returns `clip_index`; `replace_notes` returns none → link skip,
  plan.py). A blocked audio row leaves every sibling clip planned.

### 7. `mix` (`push/mix.py`)
- **Assumes:** tracks + returns linked. Master needs no link
  (`set_master_property`). Only non-NULL DB fields are written —
  NULL means "never authored", never "reset Live".
- **Re-probes:** nothing — unconditional idempotent re-emit (no diff pass; cheap
  LOM writes).
- **Failure/halt:** unlinked track → warn + skip. Unlinked return →
  **emits the create itself** (violation V3, phase overlap with phase 4). Send with either end unlinked → warn + skip. Per-call
  failure → boundary halt. All keys ack-only except the fallback `return:`.

### 8. `devices` (`push/devices.py`)
- **Assumes:** tracks/returns linked (warn + skip whole parent otherwise);
  device links truthful — a linked device's load is skipped
  entirely, trusting W20-A probe matching + SYN-SCAFFOLD-MISLINK cascades;
  **an UNLINKED device is no longer assumed absent** (PSH-DEVDUP): with a
  `live_devices_by_parent` probe map the planner emits a load ONLY for a
  position Live's authored chain does not reach, and REFUSES (hard `plan.error`,
  halt before dispatch) when the slot is occupied or the parent was unreadable.
  Without a map (pure-planner callers) the pre-PSH-DEVDUP "load on faith"
  behavior is preserved;
  nested devices arrive WITH the rack preset (never loaded, only param-addressed
  by `device_path`); master devices load without a parent link
  (`master=True`, DEV-6M2K).
- **Re-probes (executor-side, §Executor):** per-parent `ableton_device(list)`
  (PSH-DEVDUP pre-phase chain probe + link reconcile, and again post-phase for
  the integrity assert), per-device `get_parameters` (diff-reconcile), per-rack
  `get_device_chains` (empty-rack guard), post-phase `pad_info`.
- **Failure/halt:** placeholder + analyzer rows skip-with-warn.
  Param with no writable form → operator **alert**, never a silent drop
  (SYN-9F2L). Corrupt stored JSON (browser_path/preset_query/override
  path) → warn/alert + degrade. Per-call failure → boundary
  halt, after the executor's one-shot fallbacks. Keys: `device:` (link),
  `device_parameter:` / `device_param_override:` / `device_chain_props:`
  (ack-only).

### 9. `routing` (`push/routing.py`)
- **Assumes:** tracks linked; **devices loaded** (a MIDI track exposes *audio*
  output routing — the only kind that can target a submaster bus — only once an
  instrument is loaded, RTE-2P9X); a track-target's Live display name == its DB
  `name` (push created it with that name, D6).
- **Re-probes:** nothing (deliberate — D7, no fingerprint gate; idempotent
  re-emit like mix).
- **Failure/halt:** unlinked track → warn + skip (deliberately `warn`
  not `alert` — unreachable on the gated path). Dangling/unresolvable/unknown
  routing target → **alert** + skip that direction. Per-call failure →
  boundary halt. Ack-only keys.

### 10. `device_sidechain` (`push/devices.py`)
- **Assumes:** devices linked (phase 8 — its plan runs after devices' apply);
  source track exists in Live under its DB `name` (FK resolved to display name,
  same D6 convention as routing); source track's own link only needed to prove
  it's in the song (`by_id`).
- **Re-probes:** nothing.
- **Failure/halt:** source FK not in the song → **alert** + skip;
  unlinked device → warn + skip (see violation V6 on the message's wrong
  mechanism claim). Per-call failure → boundary halt. Ack-only
  (`device_sidechain:`).

### 11. `envelopes` (`push/envelopes.py` + emitters)
- **Assumes:** tracks/clips/returns/devices linked (each emitter warn+skips a
  missing link); a covering
  session-clip placement exists for clip-hosted rides (geometry computed from the
  DB, never re-probed); runs BEFORE arrangement (W4-A — `duplicate_to_arrangement`
  snapshots the session clip, so clip envelopes must exist first).
- **Re-probes:** nothing.
- **Failure/halt:** `clip_cc`/`clip_pitch_bend` → warn + skip (LOM gap);
  perform-routed families are NOT emitted here (noted + left to phase 12,
  ENV-7G4K/9P4T); zero-breakpoint → warn + skip. **Unknown `target_kind` RAISES
  `ValueError`** (schema-belt; same plan_fn-raise surface as V2).
  Per-call failure → boundary halt. `envelope:` link kind (handler returns
  `envelope_index`).
- **Host kind does not change the route.** An audio-track host partitions exactly
  like a MIDI one — `session_clip` when a single session clip covers the span,
  `perform` when none does — because `Clip.create_automation_envelope` is
  parameter-keyed and clip-type-agnostic, probe-confirmed end-to-end on a real
  audio session clip (write, `insert_step`, read back). There is no audio refusal
  in the classifier. **Arrangement clips remain impossible hosts**, and that is
  structural rather than a branch: every emitter addresses `location='session'`
  and resolves `clip_index` from the source session clip's own link, never from a
  placement.

### 12. `performed_automation` (`push/perform.py`)
- **Assumes:** tracks/returns/devices linked (per-arc warn + "arc pending, next
  push retries"); the `performed_automation` fingerprint table is an
  honest memory of what Live's lanes hold (NOT re-probed — the perform surface is
  write-only; an unchanged fingerprint means "do not re-record", which is what
  protects hand-edited Live lanes); `perform_target_key` stays field-identical to
  the handler's `_PreparedArc.addressing_key()` (cross-package parity test).
- **Re-probes:** verification is handler-side and now stated rather than
  derived: each arc carries an `outcome` (`recorded` / `unverified`) plus an
  `outcome_reason`, and the apply layer records a fingerprint only for
  `recorded`. `automation_state == 1` + `updates_written > 0` remain the floor
  for a server predating the field. An unverified arc re-performs next push.
  `automation_state` alone can never carry this: it reads 1 whenever ANY lane
  exists on the parameter, including one an earlier session wrote, so on every
  iteration after the first it is 1 no matter what the pass did (#471).
- **Positions before it plays.** The pass locates Live's START PLAYING POSITION
  (`handlers/_transport.py`), not just the playhead — those are separate
  properties and `start_playing()` rolls from the first. It then judges the
  ramp's own first beat against the span, so a transport rolling from somewhere
  else aborts instead of closing every gesture on a beat past the end and
  returning a clean result.
- **Failure/halt:** duplicate-target arcs: recorded lanes claimed first, extra
  arcs **alert** + defer (ENV-8K2R #3). One `perform_batch:` call with
  a derived read ceiling — realtime cost surfaced via alert. Restore
  failures + count mismatches → apply warnings (plan.py). Watchdog for a
  dead worker = **PSH-3H8M**, not this contract.

### 13. `arrangement` (`push/arrangement.py`)
- **This phase and §14 are where the two-bar-ruler divergence is reported**, not
  the meter phase: this is where an authored bar position actually becomes a Live
  beat. The alert names how many placements sit after a meter change, because
  push resolves them through the `time_signature_map` while
  `hallucinote.arrangement` accumulates whole bars against one uniform
  `beats_per_bar`. A song whose every placement precedes the first change
  diverges nowhere and is not alerted.
- **Assumes:** tracks linked (alert + skip whole track otherwise); envelope-bearing
  placements' source clips linked (duplicate route); the DB is the ONLY author of
  the timeline (projection: clear then rebuild, ARR-PROJ).
- **Audio placements project like any other** (SMP-6V2K). The whole-track audio
  skip is gone: a track the DB has placements for is projected, and a track it
  has none for is still left untouched — that distinction is now *named in the
  report* rather than being an unexplained absence. An audio placement is
  created directly via `Track.create_audio_clip(path, beats)`, which is why the
  phase needs no session counterpart for it.
- **Two audio gaps the phase reports rather than papers over.** A direct create
  loads a fresh clip at Live's defaults, and the planner cannot `set_property`
  the copy in the same plan: an arrangement clip is addressed by an index that
  exists only in the create's *result*, after apply, and predicting it is exactly
  the positional guess ARR-PROJ diagnosed as a root cause. So a placement with
  authored conform is planned and then reports what did not land. And a
  placement whose source clip **hosts an envelope** is `blocked` outright: the
  duplicate route exists to carry the envelope but is unprobed for audio, and
  the direct route carries no envelope at all — neither is known-good, so the
  phase refuses. Both close on one probe answer: whether
  `duplicate_clip_to_arrangement` carries an audio clip's conform properties and
  its envelope.
- **Re-probes:** the arrangement probe (resolved at THIS phase, not before the
  loop — §Gates) supplies each track's current Live clips for the clear; a lane
  ABSENT from the probe map → `blocked` + skip that track (unknown state must
  not be cleared into). Probe map `None` (non-execute callers) → loud alert, no
  clear emitted — an alert, not `blocked`: everything is still
  planned.
  Post-phase: the executor's integrity assert re-probes every placement FRESH —
  and (ARR-ORPHAN2) HALTs when that re-probe cannot list a lane, which is what
  makes the alert+skip above loud instead of an exit-0 "phase ok" over a track
  that kept its stale clips and got none of its placements.
- **Failure/halt:** §6a all-or-nothing per track — every link validated BEFORE
  any of that track's calls (clear included) join the plan; an unmaterializable
  track emits nothing + `blocked`. A phase carrying blocked reasons is reported
  `incomplete` with a non-zero exit and its reasons verbatim — never
  `skipped (idempotent)`. Clears emitted descending-index. Per-call failure → boundary halt;
  `ArrangementIntegrityError` → halt (silent corruption must not report OK).
  Keys: `arrangement_clip:` (link), `arrangement_clip_clear:` /
  `arrangement_clip_notes:` (ack-only).

### 14. `cues` (`push/arrangement.py`)
- Carries the same two-ruler divergence alert as §13, for the same reason: a
  cue's `position_bar` resolves through the meter map here.
- **Assumes:** arrangement materialized (Live clamps `set_or_delete_cue` to
  `[0, last_event_time]`); DB arrangement extent = the authored truth for "can
  this cue EVER be placed".
- **Re-probes:** none client-side; the handler answers the runtime half
  ("placeable NOW?") via `on_out_of_range='skip'` — deferred cues report back as
  benign warnings (§Executor).
- **Failure/halt:** cue past the composed extent → **`plan.error`** → phase halts
  pre-dispatch with the DB-grounded message (SYN-6B4Q); no arrangement
  authored → all deferred with warn. Duplicate names auto-suffixed at
  plan time (W19-E). One `cue_batch:` call, `if_exists='skip'`
  (idempotent re-push). Ack-only.

*(`plan_push_sections` is deliberately NOT a phase — no canonical Live surface;
plan.py, arrangement.py.)*

---

## Contract violations found (follow-up candidates — do NOT silently normalize)

- **V1 (fixed in SYN-8Q3F Chunk 02): phase-count prose drift.** "thirteen-phase" /
  "13 phases" in `push_execute.py`, `push_cli.py`, `push_notes.py`, `push/plan.py` (base-revision lines)
  vs 14 names in `_PHASE_NAMES` (the `device_sidechain` "9b." splice). Fixed on
  the files the chunk already touches.
- **V2 (open, behavior): a plan_fn raise escapes the executor as a raw
  traceback.** `plan = phase.plan_fn()` (push_execute.py) is uncaught, so
  the clips planner's W3-C strict `ValueError` (clips.py) — reachable via
  `--only clips` / `--start-at clips` against unlinked tracks — and the envelopes
  unknown-target-kind raise (envelopes.py) bypass the terminal state
  write and leave the request row open. Same class as V4; should become a
  controlled halt. → build-plan Chunk 06.
- **V3 (open, design): the mix phase owns a second return-creation path.**
  `plan_push_mix` emits `ableton_return(create)` for unlinked returns
  (mix.py), duplicating phase 4's job. Unreachable on the gated full-push
  path (returns halts first) but live under `--only mix` / direct planner calls —
  two phases can create the same entity kind. Decide: drop the fallback (strict,
  matches clips' W3-C posture) or keep for direct-call ergonomics and document.
  → Chunk 06.
- **V4 (fixed in SYN-8Q3F Chunk 03): unknown result kind escaped as a
  traceback.** The apply-layer `ValueError` (plan.py) propagated out of
  `execute_push` uncaught — no terminal state file, request left open, exit = a
  Python traceback. This is the runtime half of the twice-point-patched bug
  class. Now a controlled phase halt (§Apply).
- **V5 (fixed inline, prose): stale "via plan_push_clip" guidance.** Five
  operator-facing strings still named `plan_push_clip` as the track-creation
  path (moved to `plan_push_song_tracks` in W3-C): push/mix.py (+ its
  docstring), pull/mix.py, pull/clips.py, pull/devices.py.
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
  mechanism.** devices.py says an unlinked device's sidechain is
  "deferred to the devices-convergence re-plan" — the convergence pass re-runs
  `plan_push_devices` only; what actually resolves the deferral is that the
  `device_sidechain` PHASE plans after the devices phase's apply. The branch is
  near-unreachable on the gated path (a failed load halts devices). → Chunk 06
  (message fix).
- **V7 (fixed in SYN-8Q3F Chunk 02, prose): `plan_push_song` docstring
  overclaimed the warn-not-empty convention.** The base-revision docstring said
  every empty phase carries a "no … to push" warn; `plan_push_song_tracks`/
  `_returns` return a bare empty plan when fully linked (tracks.py) and
  `plan_push_arrangement_clip_notes` emits neither. The Chunk 02 docstring
  rewrite (plan.py) now states both shapes are reported SKIPPED.

**Residual risk (documented design, not a violation):**
- **R1:** the coherence gate validates only track/return links; a stale *device*
  link whose parent survived is caught by nothing until the devices phase writes
  through it (probe.py accepts this cost/benefit; ANALYZER-INDEX and
  SYN-SCAFFOLD-MISLINK each closed one concrete instance). Watch for a third
  instance before generalizing.
- **R2:** phase 12's fingerprint table is trust-without-verify of Live lane
  state by design (write-only surface); a hand-deleted Live lane whose arc
  fingerprint is unchanged will NOT be re-performed until the envelope changes.
