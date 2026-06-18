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

## Why it's framework-shaped — two distinct gaps

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

## Workaround (no fix needed in-song)

The Arrangement clip is healthy — the only correction is to re-engage the
Arrangement. Session clips are already stopped/disarmed (`playing_slot_index`
== `-2` on every track) and the playhead is cued at bar 243 (beat 968). The user
clicks **Back to Arrangement** in Live's transport bar, then Play — the preview
sounds. (Optionally delete the leftover Session clip in track 24 / slot 9 so it
can't re-hijack on a future Session launch.)
