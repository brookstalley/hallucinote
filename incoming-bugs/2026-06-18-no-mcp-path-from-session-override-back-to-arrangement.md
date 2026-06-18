# No MCP path back to Arrangement after a session clip overrides a track — and probe `set` masks the silently-ignored write

**Severity:** M (authoring recovery dead-end) — once a Session clip fires on a
track whose real content lives in the Arrangement, there is **no working MCP
affordance to return that track to Arrangement playback**. The documented
recoveries (`ableton_clip` stop, `song.stop_all_clips()`) stop the Session clip
but do **not** re-engage the Arrangement, and the canonical LOM recovery
`song.back_to_arranger = 0` is silently ignored by Live through `setattr`. Net
user-visible symptom: a greyed-out Arrangement clip, then **"transport moving,
no audio."** The only fix found was the GUI **Back to Arrangement** button.

## What happened (swell, "ZZ Theme Preview" — track 24)

A preview was pushed to the Arrangement: clip **"Swell theme preview"** at beat
970, length 48, 24 notes, `muted=false`, instrument present, fader at 0 dB — a
healthy clip sitting right under the playhead. But it showed **greyed out** and
silent.

Diagnosis via `ableton_probe`:
- `song.tracks[23].playing_slot_index = 8` → **Session slot 9 was firing**
  ("ZZ Theme Preview 1", a 4-beat leftover preview clip). The track was in
  **session-override** mode, so Live ignores the Arrangement lane on that track
  and dims it. The Arrangement clip itself was never the problem.
- `song.back_to_arranger = true` (global latch).

Recovery attempts and what each did:
1. `ableton_clip(action='stop', track=24, slot=9)` → `playing_slot_index` went to
   `-2`. But the track stayed silent — Live does **not** auto-resume the
   Arrangement mid-clip.
2. `song.start_playing()` → `playing_slot_index` **jumped back to 8**; the
   disarmed-but-last-played slot re-fired on transport start (launch quant was
   `None`).
3. `song.stop_all_clips()` → every track's `playing_slot_index = -2` (no Session
   clip anywhere). **`back_to_arranger` stayed `true`.**
4. `ableton_session(action='seek', bar=243)` to beat 968 (two beats *before* the
   clip's 970 start) + `play` → playhead rolled through 970→984, yet
   `song.tracks[23].arrangement_clips[0].is_playing` stayed **`false`**. The
   latch suppressed even the start-boundary re-trigger. → silence everywhere the
   overridden tracks should have sounded ("transport moving, no audio").
5. `ableton_probe(action='set', path='song.back_to_arranger', value=0)` and
   again with `value=false` → both returned `ok:true` with **`old==true,
   new==true`** — the write did not land, with no error and no `changed` flag.

The only thing that would have re-engaged the Arrangement is the GUI **Back to
Arrangement** button.

## Why it's framework-shaped — three distinct gaps

**(1) No first-class "Back to Arrangement" recovery, and the LOM property write
is silently ignored.** I read the handler: `set_handler`
(`hallucinote_mcp/handlers/probe.py:219-245`) does a bare
`setattr(parent, attr, _resolve_arg(context, value))`, and `_resolve_arg`
(`:332`) passes scalars through unchanged — so `setattr(song,
'back_to_arranger', False)` genuinely executes and **Live ignores it** (a known
LOM quirk: the `back_to_arranger` setter doesn't re-engage the Arrangement; only
the GUI button / a fresh clip-boundary on a non-overridden track does). The
dedicated transport actions (`ableton_session` seek/play/stop, `ableton_clip`
stop, `stop_all_clips`) all work — there is simply **no action that performs the
"return to Arrangement" gesture**. An agent that pushes a preview to the
Arrangement but leaves a Session clip firing has no way out via MCP.

**(2) `probe set` reports a silently-ignored write as success.** `set_handler`
reads `old`, calls `setattr`, reads back `new`, and returns both with no
comparison. When Live ignores the write (no exception), the result is
`ok:true` + `old==new` — **indistinguishable from a successful set-to-the-
same-value**. The docstring says "settability is itself a probe finding," but a
no-op write surfaces no `changed`/`settable` signal at all. The same masking hit
`setattr(song, 'current_song_time', 968)` (returned `old==new`, no move) while
`ableton_session(action='seek')` relocated the playhead correctly — so an agent
reaching for `probe set` on these transport/state props gets a false "ok" and
silently wrong behavior.

**(3) No reliable "play from bar X" — `seek` + play doesn't honor the located
position.** Trying to audition the preview at bar 243, I repeatedly hit:
`ableton_session(action='seek', bar=243)` set `current_song_time` to 968 (and
reported it), but then **`ableton_session(action='play')` restarted from the
Arrangement Start Marker (~beat 8)** and `song.continue_playing()` resumed from
the **last-stopped position** — neither honored the freshly-seeked playhead. The
user watched it "start from 1 again" three times. Root cause is the Live
distinction: *Start* plays from the start marker, *Continue* from the last stop,
and `current_song_time`/`seek` move neither's source of truth in a way that
sticks across the play call (compounded by gap (2): the plain
`setattr(song,'current_song_time', …)` no-ops). Net: there is **no robust MCP
gesture for "locate to bar X and play from there,"** which is exactly what
auditioning a section/preview needs. The GUI (click the clip, hit space) works
because the click moves the start marker.

## How the trap was set (workflow note)

Track 24 held **both** a 48-beat Arrangement preview clip *and* a 4-beat Session
clip ("ZZ Theme Preview 1") in slot 9, and the Session clip was left **firing**.
This looks like a compose/preview path that auditions via a Session clip and
also duplicates to the Arrangement, leaving the Session clip playing — which
silently overrides the Arrangement content the author actually wants to hear.

## Suggested directions

1. **First-class recovery action:** `ableton_session(action='back_to_arrangement')`.
   Since `song.back_to_arranger = 0` via `setattr` is ignored by Live,
   investigate the call control surfaces actually use to clear it (it may be
   state-dependent, need a specific value/thread, or a different LOM entry
   point). If no reliable LOM call exists, surface a **teaching error** that
   names the GUI button and the override state, rather than silently failing.
2. **Make `probe set` report no-ops:** add `changed: old != new` to the result,
   and for a settable scalar where the read-back ≠ the requested value, flag it
   (`applied: false` / warning) instead of returning a bare `ok:true`. This
   turns "settability is a finding" into an *observable* finding.
3. **Guard the preview workflow:** when a Session clip is firing on a track that
   also has Arrangement content (or after `duplicate_to_arrangement`), warn that
   the Session clip will override the Arrangement, and/or stop+disarm the Session
   clip as part of the preview-to-arrangement handoff.
4. **A real "locate and play" action:** `ableton_session(action='play', from_bar=…,
   from_beat=…)` that moves the start marker (or sets `current_song_time` *and*
   uses whichever play call actually honors it) so an agent can audition a
   section/preview deterministically. Today seek+play/continue can't. At minimum,
   document the Start-vs-Continue-vs-start-marker semantics in
   `ableton://guides/conventions` so agents stop fighting it.

## The documentation gap is in-band: these surfaces should teach, not stay silent

The deeper miss here is that **none of these surfaces explained what was
happening at the moment it happened.** A prose entry in
`ableton://guides/conventions` would have helped, but the agent was mid-recovery
calling tools — the teaching has to come back *in the tool result*, the way
`device set_sidechain` / `gain_db` already raise teaching errors. Each surface
below currently returns a misleadingly-successful or silent result where it
should return a teaching message. Concrete copy the maintainer can lift:

- **`probe set` no-op** (read-back ≠ requested, settable scalar) — instead of
  bare `ok:true` + `old==new`:
  > "Write did not land: read-back (`true`) ≠ requested (`false`). Live silently
  > ignored this `setattr`. `song.back_to_arranger` cannot be cleared via the
  > API — use Live's **Back to Arrangement** button. `song.current_song_time`
  > won't move via `set` — use `ableton_session(action='seek')`."

- **`ableton_clip(action='stop')` / `song.stop_all_clips()` on a track still
  showing session-override** — add a `still_overridden: true` flag + note:
  > "Track 24's Arrangement lane is still overridden (greyed): stopping the
  > Session clip does not auto-resume the Arrangement mid-clip, and the override
  > latch can't be cleared via the API. Click **Back to Arrangement** to restore
  > Arrangement playback."

- **`ableton_session(action='play')` / `continue_playing` called after a `seek`
  that moved the playhead** — return a `started_from` field + note:
  > "Started from the Arrangement Start Marker (beat 8), not your seeked playhead
  > (beat 968). `play` = Start (start marker); `continue_playing` = resume from
  > last stop. Neither honors `seek`. To audition from bar X today, move the
  > Start Marker in the GUI (click the timeline there) then play."

- **reading `song.back_to_arranger == true`** (e.g. in `ableton_session` info) —
  surface it as a named state with the recovery, not a bare bool:
  > "`back_to_arranger` is latched: the Arrangement is overridden (a Session clip
  > fired, or an automated param was touched live). Overridden tracks are silent
  > until you click **Back to Arrangement**."

Until the recovery *action* exists (suggested direction §1), these teaching
messages are the minimum so an agent isn't left, as here, reading `ok:true`
results while the user hears silence.

## Workaround (no fix needed in-song)

The Arrangement clip is healthy — the only correction is to re-engage the
Arrangement. Session clips are already stopped/disarmed (`playing_slot_index`
== `-2` on every track) and the playhead is cued at bar 243 (beat 968). The user
clicks **Back to Arrangement** in Live's transport bar, then Play — the preview
sounds. (Optionally delete the leftover Session clip in track 24 / slot 9 so it
can't re-hijack on a future Session launch.)
