# `ableton_clip(action='replace_notes')` on an ARRANGEMENT clip is non-atomic — it leaves orphan notes behind

**Severity:** H — `replace_notes` is documented as "REPLACE the clip's entire note
array," and agents/recovery flows rely on that total-replace semantic to make a clip
faithful to the DB. On an **arrangement** clip it does NOT fully replace: a subset of
pre-existing notes survives the call, so the clip ends up with the new notes PLUS
stale orphans. The call reports success (`notes_written: N`, `ok`) with no warning.
Same subsystem as the two 2026-06-21 arrangement-materialization bugs (stacking,
bulk-drop); this is the **note-write** path rather than clip (re)duplication.

**Engine / server:** `0.1.0+4372b6734f8d`. Song `alien`, branch `compose/alien`.

## What happened

The `Drums chorus2` arrangement clip (track 1, arrangement_clip_index 7, beats
256–288) held **248** notes: the 243 build.py-intended notes **plus 5 stale ghost
notes** left over from an earlier push generation (low velocity, off-grid, and —
tellingly — carrying much older Live `note_id`s: 162, 186, 206, 214, 216, vs the
current generation's contiguous 237–479 block).

To make the clip faithful to build.py, I called:

```
ableton_clip(action='replace_notes', track_index=1, location='arrangement',
             clip_index=7, notes=[<the 243 exact DB notes>])
→ { ok: true, notes_written: 243 }
```

Expected: clip now holds exactly those 243 notes. **Actual:** the clip held **248** —
the 243 new notes (fresh `note_id`s 480–722) **and the same 5 stale orphans**
(unchanged ids 162/186/206/214/216). So `replace_notes` replaced the *prior
current* 243 notes but left the 5 older orphans untouched.

The 5 survivors were not edge cases: each sat inside the clip's `[0, 32)` beat extent
**and** inside the bounding box (pitch 35–49, time 0–31.75) of the new note set — so
any bounding-box clear-before-write should have caught them.

## Likely cause

The handler does not appear to use a true `Clip.set_notes()` (which replaces the
whole note list) or a full-extent clear. It looks like it clears via a *scoped*
`remove_notes_extended` (e.g. derived from the incoming notes) or an
apply-modifications path that misses notes from an older write generation. A true
total-replace would leave zero survivors.

## The workaround that worked (and confirms it's a clear-scope problem)

Surgical removal via the LOM directly cleared the orphans (arg order
`remove_notes_extended(from_pitch, pitch_span, from_time, time_span)`):

```
ableton_probe(action='call', path='song.tracks[0].arrangement_clips[6]',
              method='remove_notes_extended', args=[40, 1, 22.59, 0.06])   # ...per ghost
```

Five tight (pitch, time) windows removed exactly the 5 orphans (248→247→…→243),
leaving the 243 correct notes intact. So the notes ARE removable; `replace_notes`
just doesn't clear them.

## Suggested fixes

1. **Make `replace_notes` a true total-replace on arrangement clips**: clear the
   whole clip extent first — `remove_notes_extended(0, 128, 0, clip.length)` (or
   `clip.select_all_notes()` + remove) — *then* write, OR route through
   `Clip.set_notes()` which replaces the full list. Add a post-write assertion that
   `len(get_notes_extended) == len(written)` and HALT/warn on mismatch.
2. **Return the actual resulting count**, not just `notes_written`, so a caller can
   detect the orphan-survival immediately (here it would have read 248, not 243).
3. Cross-reference: a build↔Live arrangement verifier (filed separately,
   2026-06-22-systematic-build-vs-live-arrangement-verification-capability.md) is the
   detection backstop for exactly this class of silent drift.

## Workaround (today)

After `replace_notes` on an arrangement clip, re-read with `ableton_note(action=
'list', location='arrangement')` and compare the resulting set to what you wrote;
if orphans survived, clear them with `ableton_probe` →
`arrangement_clips[i].remove_notes_extended(pitch, 1, t, span)` over tight windows.
