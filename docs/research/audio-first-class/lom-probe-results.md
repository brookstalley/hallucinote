# LOM probe results — Live 12.4.1, empirical (AUD-1M4V chunk 02)

Executed 2026-06-10 against the user's running Live 12.4.1 (build 2026-05-20) via the
`ableton_probe` bridge tool (describe/get/set/call+then). Raw record:
`lom-probe-results.jsonl` (195 probe records); driver: `lom-probe-driver.py`
(plus follow-up probes recorded in the JSONL). These results supersede the
LIKELY/UNKNOWN labels in `lom-audio-clip-surface.md` and
`lom-recording-automation.md`.

## Verdict table

| # | Question | Verdict | Evidence |
|---|----------|---------|----------|
| 1a | `ClipSlot.create_audio_clip(abs_path)` | **CONFIRMED** | Created from `/tmp/aud1m4v_probe.wav`; `file_path` round-trips; `warping` defaults **true**; 2.0s file → `length` 4.0 beats @120bpm |
| 1b | `Track.create_audio_clip(path, beats)` (arrangement) | **CONFIRMED** | Clip created at 16.0 beats |
| 1c | Error shapes | **CONFIRMED** | MIDI track → `RuntimeError: Audio clips can only be created on audio tracks`; bad path → `ValueError: The provided path does not appear to point to a valid audio file` |
| 2 | Arrangement clips host automation envelopes? | **NO — CONFIRMED** | `automation_envelope(param)` → `None`; `create_automation_envelope(param)` → `RuntimeError: Not a session clip or parameter belongs to another track.` |
| 3 | Mixer envelope on **audio session clip** end-to-end | **YES — CONFIRMED** | `create_automation_envelope(track volume)` → Envelope; `insert_step(0,4,0.5)` ok; `value_at_time(2.0)` → `0.5` (ENV-8H1T's "audio tracks can't host" refusal is now only a missing-audio-clip problem) |
| 4 | Scripted **master** automation write (realtime record) | **YES — CONFIRMED** | `session_automation_record=True` + `record_mode=True` + `begin_gesture` + 40-step 100 ms value ramp during playback + `end_gesture` → `automation_state` 0→**1**; manual set afterwards → **2** (overridden); **playback test: volume moved by itself** 0.60→0.78 with no writer attached |
| 4b | Same mechanism on **return** track | **YES — CONFIRMED** | Identical recipe → `automation_state` 0→1. Group tracks: not directly testable (LOM cannot create group tracks) but the mechanism is track-kind-agnostic — same no-clip shape as master/return |
| 5 | Scripted session **audio recording** | **YES — CONFIRMED** | Routing set via `$path` RoutingType + `arm=True` + `clip_slot.fire(record_length=8.0)` → `is_recording` true; auto-finished at exactly 8.0 beats; `warping` true. **`file_path` is valid DURING recording** (`…/Samples/Recorded/PROBE-AUDIO 0001 […].aif` under the project dir) |
| 5b | Arm with invalid input routing | **SILENT NO-OP — CONFIRMED** | With no audio input device enabled, "Ext. In" is not in `available_input_routing_types` (offered: Resampling, other tracks, returns, Main, No Input) and `arm = True` reads back false. Workflow must verify routing first and teach the refusal |
| 5c | Resampling routing | **CONFIRMED** | `input_routing_type = available[…Resampling]` via `$path`; recorded the master bus with no input device — the resampling-as-material workflow is fully scriptable |
| 6 | Take lanes (12.2 API) | **CONFIRMED** | `create_take_lane()` → TakeLane; `take_lanes[0].create_audio_clip(path, 32.0)` → Clip with `is_take_lane_clip` true; **comping substitute `duplicate_clip_to_arrangement(lane_clip, t)` works** (returns the copied Clip) |
| 7 | Undocumented envelope-event API | **CONFIRMED (session clips)** | `events_in_range(0,4)` callable on a session-clip envelope (RS-visible, not in M4L docs) |
| 8 | Warp markers | **CONFIRMED with RS caveat** | Read: `WarpMarkerVector`, elements expose `beat_time`/`sample_time` floats. `move_warp_marker(0.0, 0.25)` (floats) works. `add_warp_marker(dict)` **fails at RS level** (`No registered converter … TWarpMarker from … dict` — the dict form is M4L-only sugar); accepts a real `WarpMarker` object (`$path` to an existing one worked). A future warp handler constructs markers via the `Live` module natively |
| 9 | `count_in_duration` | **READ-ONLY — CONFIRMED** | value 0; set → `AttributeError: property of 'Song' object has no setter` |
| 10 | `record_mode` apply semantics | **ASYNC — CONFIRMED** | Immediate read-back after set returns the OLD value; reads true ~300 ms later. Any handler touching transport-adjacent Song state must poll, not trust same-call read-back |
| 11 | `application.major_version` | **ABSENT at RS level** | AttributeError; use `application.get_major_version()`/`describe application` instead |

## ENV-7G4K chunk 01 step 0 follow-ups (2026-06-11)

Executed via `env7g4k-probe-driver.py` (records appended to the JSONL, probes
prefixed `ramp1-up`/`ramp2-down`). Wire calls carried `allow_version_mismatch=true`
(server `c0b443e0e4c0` vs Remote Script `a5479db86125` — the probe surface is the
one the original 195 records ran against). Scratch default set, master volume.

| # | Question | Verdict | Evidence |
|---|----------|---------|----------|
| 12 | Re-record overwrite (the fingerprint-gate assumption) | **YES — CONFIRMED** | Probe-4 recipe twice over the same span from beat 0: ramp 1 ascending 0.30→0.90 → playback (no writer) reads 0.30/0.33/0.36/0.39 ascending, `automation_state` 1; ramp 2 descending 0.90→0.30 re-performed over the same span → the SAME beats read 0.90/0.87/0.84/0.81 descending — ramp 1 fully replaced in the gesture-held region. `automation_state` stays **1** after re-record AND after playback (never 2/overridden). Replacement is bounded by the gesture-held region, which matches the perform handler (deterministic beat spans) |
| 12a | Driver-latency caveat | noted | Recorded slope was ~5× shallower than authored: each driver step paid a TCP round trip (~400 ms vs the intended 100 ms), stretching the recorded span. Driver-only artifact — the shipped handler steps worker-side in the Remote Script process with no per-step wire hop |
| 13 | Group-host gesture recording | **STILL BLOCKED — needs one human action** | No group track in any open set and LOM cannot create one (re-confirmed: `describe song` lists no group-creation method). Workaround attempted: LOM CAN set `song.view.selected_track` ($path), but sending Cmd+G via System Events fails — `osascript is not allowed to send keystrokes (1002)`, Accessibility not granted to the agent host. Unblock = either grant Accessibility, or Cmd+G any track in Live, then run `env7g4k-probe-driver.py group` |

## Still open (consciously)

- **Breakpoint quality / thinning** of the recorded ramp: needs a saved `.als` to dump
  (LOM cannot save the set). Low risk: the playback test shows a musically smooth ramp.
  Verify during the first real master-automation chunk via the `.als` XML dump.
- **Punch-bounded recording** (`punch_in`/`punch_out` + loop): flags confirmed present;
  mechanics untested. Probe when the recording workflow chunk builds region-scoped writes.
- **Group-track automation write**: mechanism confirmed on master + return; group track
  untestable until a set with a group exists (LOM cannot create groups). Re-verify
  opportunistically in a real song. → Row 13 (2026-06-11): one human Cmd+G (or an
  Accessibility grant) unblocks; `env7g4k-probe-driver.py group` then runs the probe
  unattended.

## Architecture consequences (feed `discovery.md`)

1. **CLP-AUD2 as designed is obsolete** — no browser-load workaround; session and
   arrangement audio clip placement are one-call handlers.
2. **ENV-8H1T reduces to CLP-AUD1** — once audio clips exist in the DB, the existing
   session-clip envelope routing covers audio tracks unchanged.
3. **Master/group/return automation = a new "performed automation" mechanism**
   (record-mode + gesture + scripted ramp), categorically different from breakpoint
   envelopes: write-only (no LOM read of arrangement automation), realtime (takes
   wall-clock time proportional to the gesture), verified via `automation_state` +
   playback observation + later `.als` dump. The `.als` XML path remains the
   out-of-band read/verify fallback.
4. **Vocal recording is fully scriptable** (routing → arm → fire(record_length) →
   file_path), including during-recording state; take lanes + duplicate-to-arrangement
   give a scriptable takes-and-comping shape (comp SELECTION stays human/agent-directed,
   matching the producer-research finding that comping is curation, not automation).
