---
lifecycle: completed
archived: 2026-09-08
unbuilt_at_archive: "no readable `## Status` roster — completeness cannot be read, and an unreadable plan is not evidence of completion"
maintained: false
---

> **Archived — no longer maintained.** This plan records what was built, not what will be. Do not edit it to reflect later changes; write those where they are true.

# ENV-7G4K — Performed Automation: Design

**Item:** master/group/return mixer + device-parameter automation via gesture-recorded
scripted ramps. Stage 0b of the AUD-1M4V umbrella (parallel to CLP-AUD1 — zero
dependency on audio clips, probe 4). Requirements: R3.2 in
`.prawduct/artifacts/plans/AUD-1M4V/discovery.md`; mechanism evidence:
`docs/research/audio-first-class/lom-probe-results.md` (probes 4/4b/10).
User lock: **must-have early** (2026-06-10).

## User decisions (2026-06-10, planning session)

1. **Authoring reuses the envelope model.** The authored WHAT stays
   `envelopes` + `automation_breakpoints` — the same vocabulary as every other
   automation target. Performed recording is a second push *mechanism* for targets
   session clips can't host. No new authoring concept; no `performed_gestures` table.
2. **Performing happens in push, fingerprint-gated.** Push performs arcs whose
   breakpoint fingerprint changed since the last perform, skips unchanged ones, and
   reports wall-clock cost in the plan output (Visible Costs). No separate manual
   perform command.
3. **Wave-1 target surface is full:** master + group + return — mixer volume/pan,
   sends, and device parameters (master-chain filter sweeps are the canonical use).
   Group is the one unprobed host shape → chunk-level probe step before code.
4. (CLP-AUD1 sibling decision, recorded there: song-relative file refs.)

## The mechanism (probe-verified, Live 12.4.1)

Arrangement clips cannot host envelopes (probe 2) and arrangement automation lanes
have no LOM write surface. The verified write path is realtime automation recording:

```
save transport/record state
song.session_automation_record = True
song.record_mode = True          # ASYNC — applies ~300 ms later (probe 10):
                                 # poll, NEVER trust same-call read-back
seek to span start
param.begin_gesture()
song.start_playing()
loop (~10 Hz): read song.current_song_time (beats) on the main thread,
               set param.value = interp(breakpoints, current_beat)
param.end_gesture()
song.stop_playing(); restore saved state
```

Driving the ramp off `current_song_time` (beats) rather than computed wall-clock
seconds makes tempo maps free — the interpolation is in beat-space, which is what
the breakpoints are authored in.

**Properties of the mechanism class** (decision record in discovery.md):
*write-only* (no LOM read of arrangement automation), *realtime* (a gesture costs
wall-clock proportional to span/tempo), *async transport state*. Runtime
verification is `param.automation_state` (0 none / 1 active / 2 overridden) +
playback observation; deep verification is the gzipped-`.als` XML dump
(`lom-recording-automation.md` Topic B5) — used in the integration smoke, not in
runtime code.

## DB / engine changes

**Envelope targets.** Existing target kinds already address master/group
(`mixer_volume`/`mixer_pan`/`send_level` via `target_track_id` — master and group
are `tracks` rows; `device_parameter` via `target_device_id` — master/return chains
are `device_chains` rows). Missing: a return track's *own* mixer. Add two target
kinds to the `envelopes` CHECK (`src/hallucinote/db/schema.sql`):

- `return_mixer_volume` — `target_send_return_id NOT NULL`, all other FKs NULL
- `return_mixer_pan` — same shape

Song DBs are disposable/regenerable (`build.py --reset`; schema.sql comment at the
`returns` table), so the CHECK edit needs no migration machinery.

**Eligibility replaces refusal.** The W10-F dual-layer kind-refusal
(`db/mutations.py::_envelope_track_kind_refusal` +
`sync/push/envelopes.py::_warn_unreachable_track_kind`) currently refuses
mixer/send/device envelopes on master/group hosts. That becomes *routing*: host
kind `midi` → session-clip path (unchanged); `master`/`group`, return-side targets,
and device params on master/return chains → perform path. `audio` hosts stay
refused until ENV-8H1T (their path is session-clip envelopes once audio clips
exist — probe 3). The teaching messages ("route to a sub-bus instead") are deleted
where they're now wrong, not weakened.

**Performed-state fingerprint.** New table:

```sql
CREATE TABLE IF NOT EXISTS performed_automation (
    id            TEXT PRIMARY KEY,
    envelope_id   TEXT NOT NULL UNIQUE REFERENCES envelopes(id) ON DELETE CASCADE,
    fingerprint   TEXT NOT NULL,   -- sha256 of (target addressing, parameter_path,
                                   --  ordered (time_beats, value, curve_kind) list)
    performed_at  TEXT NOT NULL
);
```

Written by a mutator (event-emitting, per the mutator discipline) when the perform
call succeeds. Push compares authored fingerprint vs stored: changed/missing →
perform; equal → skip. The table is disposable with the DB — a `--reset` re-performs
everything, which is correct (slower, never wrong). Write-only means we can never
diff against Live; the fingerprint is the honesty mechanism, and `automation_state`
is the post-write check.

## Bridge changes

New action `perform` on the existing **`ableton_automation`** tool
(`hallucinote_mcp/src/hallucinote_mcp/actions/automation.py` +
`handlers/automation.py`), following the probe add-a-tool recipe (actions register,
handlers pure functions, dispatcher/server untouched).

- Params: target addressing (mirrors `write_envelope`'s target_kind branches +
  return-mixer addressing), `breakpoints` (time_beats/value/curve list),
  `span` (start/end beats), `settle_timeout_ms`.
- `runs_on_worker=True` — the handler sleeps and polls; every Live touch goes
  through `context.run_on_main()`; transport mutation serialized under
  `live_state_lock` (same pattern as `seek_handler`,
  `handlers/session.py`).
- Restores `record_mode` / `session_automation_record` / re-enable of overridden
  automation in a `finally:` — a failed perform must not leave the set armed.
- Returns: `automation_state` after settle, beats performed, wall-clock spent.
- Curve semantics: ramp interpolation honors `curve_kind` per segment (linear /
  hold / fast / slow) — same vocabulary the session-clip path records.

## Push integration

New push phase after the envelope phase (`sync/push/plan.py`): select eligible
envelopes → fingerprint → emit one `ableton_automation(action='perform')` call per
changed arc, with the plan output naming each arc and its estimated wall-clock
(span beats / tempo) and stating that the transport will play. Apply layer records
`performed_automation` state + event on success. Existing pull is untouched
(write-only surface — nothing to pull).

## Out of scope (explicit)

- Audio-track envelope routing (ENV-8H1T, stage 2 — deletes the audio refusal).
- Clip-locked return *device* envelopes (ENV-4M2T residual — revisit after this).
- `.als` XML editing as a write path (rejected in discovery decision record;
  retained as smoke-test verification).
- Arrangement-automation *reading* (no LOM surface; nothing to build).
- Song-spanning session-clip envelope auto-partition (ENV-3M7K).

## Open questions carried into the build plan

- Group-host gesture recording (probes covered master + return; groups share the
  shape but were not explicitly probed) → chunk 01 probe step via `ableton_probe`.
- Re-record-over-existing-span semantics (does a second perform cleanly overwrite
  the first?) → chunk 01 probe step; the fingerprint gate assumes overwrite works.
