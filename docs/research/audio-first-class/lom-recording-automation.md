# LOM research 2 — scripted recording + realtime automation recording (Live 12.4.1)

Research pass 2 of 2 for AUD-1M4V discovery (2026-06-10). Method: binary docstrings
extracted from the installed Live 12.4.1 executable (`strings` over
`/Applications/Ableton Live 12 Suite.app/Contents/MacOS/Live`), disassembly of the
bundled Remote Scripts (`_MxDCore/LomTypes.pyc`, `ableton/v2` + `pushbase` session
recording components, `APC64/recording.pyc`, `Push2/routing.pyc`), cross-checked
against cycling74 apiref, Ableton manual/release notes, AbletonOSC issues, and
community evidence. "Binary docstring" = verbatim from the installed build.

## TOPIC A — scripted audio recording

- **`clip_slot.fire(record_length=…, launch_quantization=…, force_legato=…)`** —
  CONFIRMED (binary docstring): firing an EMPTY slot on an armed audio track starts
  recording; `record_length` auto-finishes ("Can only pass record_length to empty
  slots"). **record_length is in BEATS** (quarter-note units) — confirmed from
  `pushbase/fixed_length.pyc` (bars are converted via time-sig before passing).
- **`song.trigger_session_record(record_length?)`** — CONFIRMED; records into
  selected/next empty slot on ALL armed tracks; calling again stops+plays.
  `song.session_record` get/set; `session_record_status` (off/transition/on).
- **Count-in**: `song.count_in_duration` CONFIRMED present (index: 0=None, 1=1 bar,
  2=2 bars, 3=4 bars) — read+observe; settable LIKELY NO (probe). `song.is_counting_in`
  read/observe. `song.metronome` get/set; click volume NOT in LOM (confirmed absent).
- **Monitoring**: `track.current_monitoring_state` get/set; enum order IN=0, AUTO=1,
  OFF=2 (read from binary enum registration). Vocal recording: OFF or AUTO+external
  monitoring to avoid feedback.
- **File destination**: recorded samples land in the project's `Samples/Recorded/`
  (temp folder if Set never saved) — manual-confirmed. `Clip.file_path` validity
  DURING/immediately-after recording: UNKNOWN-needs-probe.
- **Take lanes (12.2+)**: `Track.create_take_lane()`, `Track.take_lanes`,
  `TakeLane.{name, arrangement_clips, create_audio_clip(path,time), create_midi_clip}`.
  `Clip.is_take_lane_clip` exists at RS level (not in M4L whitelist). Arrangement
  recording auto-creates a lane per pass; **you cannot target a lane for recording**,
  and **comp selection has NO LOM surface** (confirmed absent). Scripted comping
  substitute: `track.duplicate_clip_to_arrangement(lane_clip, time)` (probe-worthy).
- **Arrangement record**: `song.record_mode` (the Arrangement Record button) is fully
  scriptable; `punch_in`/`punch_out` flags bound recording to the global loop region;
  `song.back_to_arranger` global + **NEW 12.x `Track.back_to_arranger`** per-track
  (binary + cycling74). `arrangement_overdub` is MIDI-only.
- **Latency**: only `Device.latency_in_samples/_in_ms` are LOM-visible. Driver/round-trip
  latency + Driver Error Compensation are preferences-only (confirmed absent from API).
  Live compensates recorded placement engine-side; verify empirically by recording a
  known click.

## TOPIC B — realtime automation recording (the master/group write path)

- **Why it's the only in-LOM path** — CONFIRMED: `Clip.automation_envelope` binary
  docstring: "Returns None for Arrangement clips. Returns None for parameters from a
  different track." No track/master-level envelope accessor exists anywhere in the
  12.4.1 surface.
- **The lever combination** — CONFIRMED: `song.session_automation_record` (the global
  Automation Arm; despite the name it governs arrangement automation too) +
  `song.record_mode = True` + transport playing ⇒ parameter gestures in that window
  are written as arrangement automation. `punch_in/punch_out` + loop markers bound the
  write window. `re_enable_automation()` (song + per-parameter) clears overrides.
- **THE SMOKING GUN** — CONFIRMED (binary docstring): `DeviceParameter.begin_gesture` —
  "Notify the begin of a modification of the parameter, when a sequence of
  modifications have to be consider a consistent group — for example, **when recording
  automation**." + `end_gesture`. RS-exclusive (absent from M4L). Push's encoders call
  exactly this on touch/release.
- **Do programmatic value-sets write breakpoints?** LIKELY YES: M4L `live.object`
  value-sets (same C++ setter as RS `.value=`) record automation per community evidence
  (M4L "automation recorder" devices exist and work; `live.remote~` is the path that
  does NOT record). Needs probe #1 to call CONFIRMED.
- **Verification readback**: `DeviceParameter.automation_state` (0 none / 1 playing /
  2 overridden), read+observe — expect 0→1 after a successful write.
- **Breakpoint quality**: Live thins/smooths recorded gestures (forum-evidenced);
  RS timers tick ~60 Hz max (100 ms realistic). "Simplify Envelope" is UI-only. No LOM
  control over thinning — verify written shape via .als dump.
- **NEW undocumented 12.x envelope-event API** — CONFIRMED in binary:
  `AutomationEnvelope.{events_in_range, delete_events_in_range, create_event}` +
  `EnvelopeEvent(ControlCoefficients|Vector)` classes. RS-visible, not in M4L docs.
  Gated behind `Clip.automation_envelope` (session clips) — does NOT reach
  arrangement/master. Probe whether `create_automation_envelope` secretly works on
  arrangement/take-lane clips (its docstring does not repeat the restriction).
- **.als XML fallback** — CONFIRMED viable: gzipped XML; master automation at
  `LiveSet > MasterTrack > AutomationEnvelopes > Envelopes > AutomationEnvelope`
  (`EnvelopeTarget > PointeeId` → the parameter's `AutomationTarget Id`;
  `Events > FloatEvent(Time in beats, Value)`; leading `Time="-63072000"` event = the
  initial value). hodel33/ableton-project-processor round-trips mixer automation at the
  XML level in the wild. Constraint: Live must not have the set open. Fits the existing
  snapshot/build pipeline as an out-of-band mechanism.
- 12.x release-notes sweep: NO arrangement-automation API added through 12.4.
  AbletonOSC issues #112 (envelope modification) and #205 (master/return) still open.

## Prioritized probes (merged into build-plan chunk 02)

1. **B-critical**: master-track scripted automation write — session_automation_record +
   record_mode + playback, 100 ms ramp on master volume inside begin/end_gesture; check
   automation_state==1; repeat WITHOUT gestures; repeat on a group track.
2. **A-critical**: armed-track session take end-to-end — routing set,
   fire(record_length=8.0), poll is_recording, read file_path timing + destination.
3. Breakpoint quality via .als dump (FloatEvent count vs write rate).
4. count_in_duration settability + is_counting_in behavior.
5. Take lanes: create/name/create_audio_clip; two-pass arrangement record;
   duplicate_clip_to_arrangement as comping substitute.
6. Envelope-event API reach: create_event on session clip; try arrangement + take-lane
   clips to chart the actual gate.
7. Punch-bounded recording: loop + punch_in/out + record_mode — do audio AND automation
   respect the window (clean region-scoped master writes).

Key local artifacts: /tmp/lomdig/live_strings.txt, /tmp/lomdig/api_docs_region.txt,
/tmp/lomdig/lom_surface.txt (regenerable; binary-extraction helpers in /tmp/lomdig/).
