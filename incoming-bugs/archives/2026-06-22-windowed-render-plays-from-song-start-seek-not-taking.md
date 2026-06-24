# Bug: windowed render (`start_at_beat` > 0) plays the whole song from the top — the pre-roll seek isn't taking

**Type:** bug — wasteful + confusing for region renders.
**Severity:** M. The captured WAV is correctly windowed, but Live plays from beat 0 to get
there, so a 38-second region render takes ~3.5 minutes (full-song playback) and the user
hears the entire song lead-up.

**Engine / server:** `0.1.0+4372b6734f8d`. Surfaced rendering `alien` beats 288–360.

## Symptom

`ableton_render(action='start', song_slug='alien', start_at_beat=288, stop_at_beat=360)`
(72-beat region ≈ 35 s of audio) ran for **218 s** — i.e. it played from ~beat 0 to 360
(360 beats ≈ 174 s @ 124 BPM + overhead), not from `start_at_beat − pre_roll` (≈ 284).
The user (watching Live) confirmed playback started "at the beginning of the song." The
capture window itself is correct (the WAV is just the bridge region).

## Root cause (suspected)

The handler intends to seek to `start_at_beat − pre_roll_beats` then play
(`handlers/render.py`: "seek transport to start and play"; "the seek lands at
start_at_beat − pre_roll_beats (clamped at 0)"). But the seek isn't **taking** — most
likely the Back-to-Arrangement override latch (a leftover firing session clip) makes Live
ignore the `current_song_time` set and roll from 0, the same latch documented in
`ableton://guides/error-recovery`. The render's pre-flight only verifies the transport
*advances* (samples `current_song_time` twice), not *where* it started, so a from-0
playback passes the check.

## Suggested fix

- Before seeking, **clear the back_to_arranger latch** (`ableton_session(action=
  'back_to_arrangement')`) so the seek takes — windowed renders are the whole point of
  `start_at_beat`.
- Strengthen the pre-flight to assert the post-seek `current_song_time` is near
  `start_at_beat − pre_roll` (not just "moving"), so a from-0 fallback surfaces loudly
  instead of silently wasting full-song playback time.

## Workaround

Full-song renders (`start_at_beat=0`, the default) are unaffected (they start at 0
legitimately). Only region renders pay the cost.
