# Bug report — push `routing` phase precedes `devices`, so a freshly-created MIDI track can't route its (audio) output to a bus (2026-06-12)

Context: first adoption of the 0.9.5 PRE-MAIN submaster bus in `swell`
(hallucinote-songs). Engine checkout `develop @ 0dc395c` (post-`v0.9.5`);
plugin 0.9.5; hallucinote-mcp `0.1.0+486e7e2653ec`; Live 12.x Suite. Followed
`docs/song-authoring-conventions.md` "The PRE-MAIN submaster bus" verbatim:
`create_track(kind="audio")` for the bus, `set_track_routing(output_routing_kind="track", output_routing_target_id=bus)` on every sounding track, bus → master + `monitoring_state="In"`.

## TL;DR

The push phase order is `… mix → routing → devices …` (routing before
devices). A **newly-created MIDI track** has **no instrument** until the
`devices` phase. A MIDI track with no instrument emits **MIDI**, so its output
routing surface is MIDI-style (a list of other tracks + `No Output`) — an
**audio** bus is not a valid target yet. So `routing` fails for that track:

```
ableton_track('set_output_routing') failed: ValueError: output routing type
(track 22) 'PRE-MAIN' not in available ['01 Glitch', … '21 Voice Lead',
'No Output']
```

The push halts at `routing` (23/24 ok — only the brand-new track fails).

## Why it bit exactly one track

This push added two new tracks to a song already materialized once: a new MIDI
track (`22 Meter Hat`, Garage Kit) and the audio bus (`PRE-MAIN`). The 21
pre-existing instrument tracks already had their instruments from the prior
push, so at `routing` time they had **audio** output and `PRE-MAIN` resolved
fine (21 × ok). Only the freshly-created MIDI track — instrument still pending
in the later `devices` phase — failed.

Probes confirm the mechanism (taken at the halt, `PRE-MAIN` already created):

```
get_output_routing track 21 (Voice Lead, HAS instrument):
   available_types = ["Ext. Out", "Main", "PRE-MAIN", "Sends Only"]   # audio-style
get_output_routing track 22 (Meter Hat, NO instrument yet):
   available_types = ["01 Glitch", … "21 Voice Lead", "No Output"]    # MIDI-style — no PRE-MAIN
```

So it is not a naming / resolution problem (`PRE-MAIN` resolves for every
audio-output track); it is that an instrument-less MIDI track has no audio
output to route.

## Root cause

`routing` is ordered before `devices`. Audio-output routing of a MIDI track is
only meaningful **after** its instrument exists. For a track that pre-exists
with an instrument this is invisible; for a **first-push of a new MIDI track**
the two phases are in the wrong order.

## Suggested fixes (in rough preference order)

1. **Route MIDI-track audio outputs after `devices`.** Keep audio-bus / `Main`
   output routing on instrument tracks in a sub-pass that runs once the
   instruments exist. (Input routing, monitor state, and audio-track→bus
   routing can stay where they are.) The cleanest model: `routing` handles what
   doesn't depend on an instrument; a post-`devices` routing pass handles
   MIDI-track audio outputs.
2. **Make the routing planner instrument-aware.** When a MIDI track's
   `output_routing_kind='track'` target is an audio track and the source has no
   instrument yet, defer that one call to after `devices` (or load the
   instrument first), rather than hard-failing the phase.
3. **At minimum, a teaching halt.** If neither reorder lands soon, detect this
   exact case (new MIDI track, audio-bus target, no instrument) and emit a
   halt cause that says *"load the instrument first (devices phase) — a MIDI
   track has no audio output to route until it has an instrument"*, instead of
   the generic "not in available" list. The current message sends the author
   hunting for a name/availability problem that isn't the real cause.

## Workaround used

Loaded the instrument on the new MIDI track manually
(`ableton_device(action='load', track_index=22, kind="Drum Rack", preset_query=…)`),
set its output routing to the bus
(`ableton_track(action='set_output_routing', type_display_name="PRE-MAIN")`),
re-ran `probe-and-link --probe` (so the manually-loaded device is matched +
linked and the `devices` phase doesn't duplicate it — verified: the track ends
with exactly one Drum Rack), then re-ran `execute`. All 13 phases then
completed (`routing 24/24`, `devices 2/2`, no duplicate device).

## Note

The convention doc's worked example (`set_track_routing(... output_routing_target_id=bus)`
in a loop over instrument tracks) silently assumes the instruments already
exist at routing time. Worth a one-line caveat there: on a first push that
*creates* the instrument tracks, the audio-output routing can't resolve until
`devices` has run.
