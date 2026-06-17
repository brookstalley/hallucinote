# Note-content changes never reach arrangement clips (silent stale render/playback)

**Date:** 2026-06-15
**Severity:** high — silent correctness bug. The agent believes notes are pushed
(push reports success, DB + session clip are correct), but the **arrangement**
(what plays / renders) keeps stale notes. No warning anywhere.

## Repro (swell, real)

1. Song already pushed once (arrangement clips materialized via
   `duplicate_to_arrangement`, `arrangement_clip` links written).
2. Rewrite a part's notes in build.py (timpani summit: 30 → 303 notes), rebuild.
3. Push the changed notes — tried all of:
   - `push-notes --changed` / `push-notes --clip <id>` → reports "N pushed".
   - full `execute --probe` → `clips 91/91 ok`.
4. Render → the timpani is unchanged in every metric across 4 renders.
5. Ground truth via `ableton_probe` `get_notes_extended` on
   `song.tracks[14].arrangement_clips[3]` ("Timpani summit"): **24 notes**
   (the OLD version). DB clip has 303. The session clip link
   (`ableton_links` db_kind='clip', ableton_index=6) is updated; the
   arrangement clip is a separate copy and was never rewritten.

## Root cause

- `push_notes` (and the `clips` phase) `replace_notes` on the clip resolved via
  the `clip` link → the **session** clip.
- The arrangement clip is a distinct copy made once by
  `plan_push_arrangement` → `duplicate_to_arrangement`.
- `plan_push_arrangement` is idempotent on the **existence** of the
  `arrangement_clip` link (`already_linked` skip) — it never compares note
  content of the source clip vs the arrangement copy, so a re-push with changed
  notes emits zero arrangement ops ("arrangement skipped (idempotent)").
- Net: note edits land in session clips + DB; the arrangement the render/transport
  plays is frozen at first-materialization. Silent.

## Why it's nasty

Every downstream signal says "success": push exit 0, `clips N/N ok`, DB correct,
`/mix-review` runs clean — but it's analyzing audio of the OLD notes. The only
way to catch it is to probe arrangement-clip note counts directly, which no
normal workflow does. I burned ~4 full render+analyze cycles (~45 min) chasing a
"level-capped timpani" that was really a stale arrangement.

## Fix directions (pick one)

1. **Best:** `push_notes` should also rewrite the linked arrangement clip(s) — a
   note change to a clip that has an `arrangement_clip` link must propagate there
   (replace_notes on the arrangement clip, or re-duplicate).
2. The `clips` phase / `plan_push_arrangement` should fingerprint source-clip
   note content vs the arrangement copy and re-emit `duplicate_to_arrangement`
   (after clearing the stale clip + link) when they diverge — i.e. make the
   idempotency check content-aware, not existence-only.
3. **Minimum:** when `push_notes` updates a clip that has an `arrangement_clip`
   link, emit a LOUD warning ("session clip updated; arrangement copy is now
   stale — playback/render will not reflect this until the arrangement is
   re-materialized") + document the re-materialize path. Silence is the worst part.

## Workaround used

Clear the stale arrangement clips + their `arrangement_clip` links, then re-run
the arrangement phase so `duplicate_to_arrangement` re-copies the updated session
clips. (Fiddly + undiscoverable — hence this report.)
