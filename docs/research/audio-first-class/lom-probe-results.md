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
| 13 | Group-host gesture recording | **YES — CONFIRMED** (2026-06-11, after Accessibility grant) | Group created agent-side: LOM-select track + keyboard-navigate focus onto the track header (Up-arrow past the top clip slot — Live's Edit>Group enables only with header focus; LOM `selected_track` alone leaves it disabled) + scripted Cmd+G. Probe-4 recipe on `tracks[0]('1-Group').mixer_device.volume`: `automation_state` 0→**1**, playback with no writer attached tracks the recorded ramp (0.40→ ascending, 4/4 sampled steps). Mechanism confirmed track-kind-agnostic across master/return/group — all wave-1 host shapes now probe-verified |

## Still open (consciously)

- ~~**Breakpoint quality / thinning**~~ RESOLVED — S-7 `.als` dump (2026-06-11,
  s7-smoke-test.als): all five performed arcs present with faithful shapes, spans, and
  endpoints (volume events stored as LINEAR AMPLITUDE, not slider-raw — e.g. raw 0.3 duck
  bottom reads as amp 0.063 ≈ −24 dB; device params stored in display units, Hz for
  Auto Filter Frequency). Recorded as hold-step pairs at ~2.5–3 Hz wall-clock — the
  handler's achieved step rate (run_on_main round-trip bound), below the ~10 Hz design
  aim. Two open residuals: (a) audibility of ~3 Hz stepping on wide device sweeps —
  operator listen pending (operator-verification.md); (b) the re-performed master arc
  wrote its final settle point ~1.3 beats past span end (17.34 vs 16.0) — harmless
  unless abutting later automation; backlog-note material.
- **Punch-bounded recording** (`punch_in`/`punch_out` + loop): flags confirmed present;
  mechanics untested. Probe when the recording workflow chunk builds region-scoped writes.
- ~~**Group-track automation write**~~ RESOLVED — row 13 (2026-06-11): confirmed on a
  group track via the same recipe; nothing about the mechanism is host-kind-specific.

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

## SMP-6V2K chunk 01 — the reverse contract and the recreate semantics (2026-09-09)

Executed against Live **12.4.5** (`application.get_major_version()` → 12, `get_minor_version()`
→ 4, `get_bugfix_version()` → 5) through the shipped `ableton_probe` bridge, server and
Remote Script both at wire fingerprint `c9abab64204b` (no version mismatch). Scratch default
set (two MIDI, two audio tracks); the sample was a generated 2.0 s mono 44.1 kHz WAV at an
absolute `/private/tmp/…/probe.wav` path. Raw records: the `smp6v2k-ch01-*` entries appended
to `lom-probe-results.jsonl`. Where a verdict below differs from `lom-audio-clip-surface.md`,
this section wins.

| # | Question | Verdict | Evidence |
|---|----------|---------|----------|
| 14 | **Reverse** — does a Live 12.4.x `Clip` expose any settable reverse? | **ABSENT — CONFIRMED** | `describe song.tracks[2].clip_slots[0].clip` on a real audio clip: 49 properties, 142 methods, **no property or method whose name contains "rev"**. The property list is exactly §4's (warping, warp_mode, gain, pitch_coarse/fine, start/end markers, loop points, looping, ram_mode settable; file_path, sample_length, sample_rate, available_warp_modes, is_audio_clip read-only). `clips.reverse` stays a derived-asset / sampler concern (design D6; #237) |
| 15 | **`available_warp_modes`** int → algorithm map | **CONFIRMED** | On the WAV clip: `[0, 1, 2, 3, 4, 6]` — every int except **5**. `ableton_clip(set_property, warp_mode=5)` → `RuntimeError: Invalid warp mode`; `warp_mode=6` → accepted, reads back 6. The only file-type-gated algorithm is REX (`.rx2` sources), so the gap at 5 pins the documented map `beats=0, tones=1, texture=2, repitch=3, complex=4, rex=5, complex_pro=6` — `WARP_MODES` in `db/mutations/clips.py` is correct as written. Creation default: `warping` true, `warp_mode` 0 |
| 16 | **Recreate semantics (a)** — `create_audio_clip` into an **occupied** slot | **ERROR — CONFIRMED** (neither replace nor no-op) | `song.tracks[2].clip_slots[0].create_audio_clip(path)` with a clip already there → `RuntimeError: This clip slot already has a clip`. Re-pointing a clip is therefore `delete_clip()` + `create_audio_clip()`, never a single call |
| 16b | **Recreate semantics (b)** — does an envelope survive delete-and-recreate? | **NO — CONFIRMED** | Before: `create_automation_envelope(track volume)` + `insert_step(0, 4, 0.5)`; `automation_envelope(volume).value_at_time(2)` → `0.5`, `has_envelopes` → `true`. Then `clip_slots[0].delete_clip()` → `create_audio_clip(path)` (same file) → `automation_envelope(volume)` → **`None`**. A recreate that must keep an authored ride has to re-emit it |
| 16c | **`duplicate_clip_to_arrangement` off an AUDIO session clip hosting an envelope** — does the ride travel? | **YES — CONFIRMED** (same as MIDI) | `song.tracks[2].duplicate_clip_to_arrangement(clip, 32.0)` → Clip at `start_time` 32.0; track `mixer_device.volume.automation_state` **0 → 1**. Control on `tracks[3]`: an envelope-free audio clip duplicated the same way leaves `automation_state` at **0**. As with MIDI the ride lands on the track's arrangement lane, not on the clip: the arrangement clip reads `has_envelopes` false and `automation_envelope(volume)` `None` (row 2 unchanged). The lane automation **survives deleting the session source** — `automation_state` still 1 after row 16b's `delete_clip()` |
| 17 | **Path handling** — absolute-path requirement + row 1c's error shapes on this build | **CONFIRMED, plus a third shape** | Relative path (`scratchpad/probe.wav`) → **`ValueError: Please provide an absolute path`** (a distinct string row 1c never recorded — the path check runs before the file check). MIDI track → `RuntimeError: Audio clips can only be created on audio tracks` (unchanged). Nonexistent absolute path → `ValueError: The provided path does not appear to point to a valid audio file` (unchanged) |
| 18 | **Wave 4 (#330)** — how a sample assigns to Simpler via LOM; is an arbitrary `assets/` file reachable? | **`SimplerDevice.replace_sample(abs_path)` — CONFIRMED** | `ableton_device(load, kind='Simpler')` on a MIDI track → `class_name` `OriginalSimpler`, `sample` `None`. `song.tracks[0].devices[0].replace_sample('/private/tmp/…/probe.wav')` → `None`, then `.sample` is a `Sample` whose `file_path` round-trips the arbitrary path verbatim. `Sample` surface: `file_path`, `length` (88200), `sample_rate`, `gain`, `start_marker` / `end_marker` **in SAMPLES as ints** (0 / 88199 — not beats, not seconds), `warping` (false by default here), `warp_mode`, `warp_markers`, per-algorithm knobs (`beats_*`, `tones_grain_size`, `texture_*`, `complex_pro_*`), `slices` + `insert_slice` / `remove_slice` / `move_slice` / `clear_slices` / `reset_slices`, `beat_to_sample_time` / `sample_to_beat_time`. The device also carries `crop()`, `warp_as(beats)`, `warp_double()`, `warp_half()`, `guess_playback_length()` |
| 19 | **Wave 4 (#330)** — does Simpler expose an automatable `Reverse` alongside `S Start` / `S Length`? | **NO PARAMETER — CONFIRMED; reverse is a destructive METHOD** | The parameter list (62 params, before and after a sample is loaded) has `S Start`, `S Length`, `S Loop On` / `S Loop Length` / `S Loop Fade`, `Sample Selector`, `Snap` — and **no `Reverse`**. `SimplerDevice.reverse()` exists ("Reverse the loaded sample"), returns `None`, and **re-points the sample at a derived file**: `sample.file_path` became `…/Live Recordings/2026-09-09 110958 Temp Project/Samples/Processed/Reverse/probe R.wav`. So on the sampler too a reversed sample is a *derived asset*, not a playback switch — D6's "or sets Simpler's Reverse parameter" half does not exist; the reversed-derived-asset half is the whole story, and the sampler route is `replace_sample(<reversed derived file>)` |
| 20 | Probe-tool finding (not LOM) — `ableton_probe(set)` on an **int** property | **BLOCKED from this client** | `set song.tracks[3].clip_slots[0].clip.warp_mode value=5` → `ArgumentError: Python argument types in None.None(Clip, str) did not match C++ signature: None(TPyHandle<AClip>, int)`. `value` is declared `type="any"`, the MCP schema is untyped, and Claude Code serializes an untyped argument as a string — so numeric property writes never reach Live as numbers. Workaround used here: `ableton_clip(action='set_property')`, whose `value` is typed. Backlogged as #508, a server-side coercion fix |

### What this settles downstream

- **Reverse** (row 14, row 19): the `clips.reverse` schema comment is correct and now
  live-confirmed; the column materializes only as a reversed derived asset (wave 3), and the
  sampler route is the same derived asset loaded via `replace_sample` (wave 4). #237 carries
  the note.
- **Warp-mode map** (row 15): `WARP_MODES` verified; no change.
- **Reconcile rule for a re-pointed `audio_file`** (rows 16, 16b): `delete_clip` → `create_audio_clip`
  → conform → **re-emit every envelope the row hosts**, in that order. The two `plan.blocked`
  refusals in `sync/push/clips.py` and `sync/push/arrangement.py` that cite this chunk can now be
  replaced by the rule — build-plan chunk 07.
- **Envelope-hosting audio placements** (row 16c): take the duplicate-onto-cleared route exactly
  as MIDI does; the direct `Track.create_audio_clip` call stays for envelope-free placements.
  Because the duplicate copies the *conformed* session clip, that route also closes the
  arrangement conform gap for those rows.
- **Path error shapes** (row 17): the chunk-02 teaching-error mapping gains a third source string
  (relative path).
