# LOM research 1 — audio clip + envelope surface (Live 12.4.1)

Research pass 1 of 2 for AUD-1M4V discovery (2026-06-10). Method: web sources
(cycling74 LOM apiref, Ableton release notes, nsuspray Live 11.0 RS API dump,
gluon's decompiled Live 12 Remote Scripts, AbletonOSC) cross-checked against the
locally installed Live 12.4.1 build 2026-05-20 (`_MxDCore/LomTypes.pyc` gate-table
disassembly — independently re-verified in the main session). Labels:
CONFIRMED / LIKELY / UNKNOWN-needs-probe.

## Headlines

1. **CLP-AUD2's browser-load premise is OBSOLETE.** `ClipSlot.create_audio_clip(abs_path)`
   exists (CONFIRMED in apiref + installed LomTypes; landed in the 12.2 beta cycle).
   `Track.create_audio_clip(file_path, position_beats)` ditto (arrangement; audio track,
   not frozen, not recording; abs path to a valid audio file; returns the Clip).
   12.4 fixed a crash in arrangement-clip creation via these calls — 12.4.x is the floor.
   Also on `TakeLane` (12.2). NOT in Live 11.
2. **Envelope write surface is Remote-Script-only** (absent from the M4L gate table):
   `Clip.automation_envelope(param)`, `Clip.create_automation_envelope(param)`,
   `AutomationEnvelope.insert_step(time, length, value)`, `value_at_time(time)`.
   Parameter-keyed and clip-type-agnostic → audio session clips should host
   mixer/send/device envelopes exactly like MIDI session clips (ENV-8H1T's blocker
   melts once audio clips exist). UNKNOWN-needs-probe: end-to-end on a real audio clip.
3. **Arrangement clips: LIKELY still cannot host automation envelopes** ("Returns None
   for Arrangement clips" — Live 11 doc; Push 12.4.1 still gates on
   `not is_arrangement_clip`). Arrangement automation lives on track lanes with NO LOM
   write surface. → master/group automation has no clip path (see research pass 2).
4. **Audio clip properties** (CONFIRMED settable): warping, warp_mode, gain (0–1 linear),
   pitch_coarse/fine, start/end markers, loop points (seconds unwarped / beats warped),
   looping, ram_mode. Read-only: file_path (no re-pointing — delete+recreate;
   `SimplerDevice.replace_sample` is 12.4, device-level only), sample_length,
   sample_rate, available_warp_modes, is_audio_clip. **No `reversed` property** —
   clip reverse is not LOM-accessible (confirmed absent).
5. **Warp markers**: read since 11.0 (`warp_markers`, AudioClips only); write —
   `add_warp_marker({'beat_time': b[, 'sample_time': s]})`, `remove_warp_marker`,
   `move_warp_marker` — registered in 12.0 and 12.4.1 LomTypes (landed 11.x).
   RS-accessible; RS may take WarpMarker objects vs M4L's dicts (probe call shape).
6. **Recording surface** stable since 11: arm/can_be_armed, current_monitoring_state,
   input_routing_type/channel (+available_* lists, settable), session_record(_status),
   trigger_session_record(), record_mode, session_automation_record,
   re_enable_automation(), capture_midi (MIDI ONLY — no audio capture-after-the-fact),
   clip_slot.fire() records on armed audio tracks. fire(record_length=, …) kwargs:
   in apiref, LIKELY at 12.4 RS — probe.
7. **Group tracks**: no clips (slots are launch proxies, `is_group_slot`); mixer params
   reachable + settable; no clip-envelope write path.
8. `LooperDevice.export_to_clip_slot(slot_id)` (12.1) — bonus path to materialize audio
   into a session slot.

## Probe list contributed (merged into build-plan chunk 02)

create_audio_clip (both) constraints; arrangement automation_envelope expect-None;
audio-clip envelope end-to-end; group/master realtime-record (pass 2 owns it);
dir() diff vs 11.0 inventory; warp-marker write shape; fire(record_length=).

## Caveat

No public RS API dump exists for 12.x (nsuspray stops at 11.0). The 12.x RS surface is
inferred from the M4L gate table + Push internals; `LiveAPI_MakeDoc` run inside 12.4.1
would produce the authoritative XML if we want it.
