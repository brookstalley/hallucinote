# `push execute --only arrangement` is refresh-in-place, not create-from-session — the documented "notes→arrangement" recovery fails with IndexError

**Severity:** M (blocks the normal iterate-on-a-composed-part loop). When you edit
notes in `build.py` and want them in the *arrangement* (what plays in Arranger
view), the known gap is that re-pushing clips updates the SESSION clips + DB but
not the arrangement. The intuitive recovery — delete the stale arrangement clips,
then re-run the arrangement phase to re-materialize — **does not work**: the
`arrangement` phase only `replace_notes` on *pre-existing* arrangement clips; with
the clips deleted it throws `IndexError: clip_index … out of range`. So there is
no first-class "re-materialize the arrangement from the updated session clips"
path; you must hand-duplicate session clips into the arrangement.

**Engine version:** `0.1.0+b66e0a9b729d`.

## Repro (alien, branch `compose/swell`)

1. A pushed song with arrangement clips already placed (intro bars 1–12, verse1
   bars 13–28 across 5 tracks).
2. Edit `build.py` (rewrote the drums + intro → many more notes), rebuild the DB
   (converger, no `--reset`).
3. `push execute <session> --song alien --only clips --probe` → OK (9/9). Updates
   the **session** clips with the new notes. Arrangement clips are now stale (old
   note counts).
4. Attempt the documented recovery: delete the stale arrangement clips, then
   `push execute <session> --song alien --only arrangement --probe` →
   **`IndexError: clip_index … out of range` (9/9 failed)**. The phase assumed the
   arrangement clips still existed and tried to `replace_notes` into slots that no
   longer exist.

## What actually works (the manual workaround)

Don't delete + re-run arrangement. Instead, after `--only clips`, **duplicate the
updated session clips into the arrangement** at the correct beats
(`ableton_clip` duplicate-to-arrangement; intro→beat 0.0, verse1→beat 48.0),
which carries the new notes. Verify per-track clip counts to ensure no duplicates.
(Alternatively: refresh the existing arrangement clips' notes *in place* without
deleting them — but there's no documented one-shot for that either.)

## Why it matters

This is the core compose→hear iteration loop for any already-pushed song. The
`/ableton-push` skill + the project memory both describe the gap and imply a
"re-materialize" recovery, but the only phase that touches the arrangement is a
note-refresh, not a create-from-session. Net: a user iterating on a part has no
clean, documented path to get the edit into the arrangement that actually plays —
they hit an unhandled `IndexError` and must hand-drive `ableton_clip` duplication.

## Suggested fixes

- Make the `arrangement` phase **create-or-refresh**: if a DB `arrangement_clip`
  has no corresponding Live arrangement clip, duplicate the (updated) session clip
  into the arrangement at its span; if it exists, refresh notes in place. Then
  `--only arrangement` becomes the real re-materialize path.
- OR add an explicit `push execute --rematerialize-arrangement` (or a
  `--force-arrangement`) that clears + re-duplicates the song's arrangement clips
  from the current session clips.
- Until then, document the manual `ableton_clip` duplication workaround in the
  push skill's "notes→arrangement" note, and stop implying delete-then-`--only
  arrangement` works.

## Related

- Project memory `note-changes-dont-reach-arrangement` (the staleness gap).
- `incoming-bugs/2026-06-18-no-mcp-path-from-session-override-back-to-arrangement.md`
  (adjacent arrangement-materialization gap).
- Filed same session as the `devices`-phase 1243-call stall
  (`2026-06-19-push-devices-phase-reapplies-all-params-on-just-captured-set.md`).
