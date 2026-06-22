# `execute --only arrangement` silently drops ALL notes for a track (empty arrangement clips) — and `ableton_clip list` note_count masks it

**Severity:** H — a primary instrument (Human Riff, the EBM backbone) rendered
**completely silent** across the entire song, with NO error and a push that reported
`OK`. The silence is invisible to every cheap check (`ableton_clip list` reports the
*correct* note counts), so it's only caught by rendering + reading a stem's loudness
(or `get_notes_extended`). Sibling to the stacking bug filed
2026-06-21-arrangement-rematerialize-stacks-notes-on-mid-timeline-clip-edit.md —
same subsystem (arrangement re-materialization), opposite failure (drop vs stack).

**Engine / server:** `0.1.0+4372b6734f8d`. Song `alien`, branch `compose/swell`.

## What happened

Recovering from the stacking bug, I cleared the WHOLE arrangement (every clip on
every track) and rebuilt onto the empty timeline:

```
push probe-and-link --song alien --probe          # dropped 49 stale arrangement links
push execute --song alien --only arrangement --probe   # re-duplicated all 49, "ok (49 call(s))"
```

`execute` reported success. But the **Human Riff** track's 9 re-duplicated
arrangement clips came out with **ZERO notes** — every other track copied fine. The
render then captured Human Riff as digital silence (−999 dBFS, 0% active) for the
entire song. Ground-truth proof:

- `get_notes_extended` on the Human Riff verse1 **arrangement** clip → `[]` (0 notes).
- `get_notes_extended` on the Human Riff verse1 **session** clip → 64 notes (intact).
- `get_notes_extended` on the Drums verse1 **arrangement** clip → 503 notes (fine).
- A prior render (db_seq 1901) had Human Riff at LUFS −8.8 / TP +5.4 — it WAS a
  dominant element; this render (db_seq 2447) has it `null`/silent.

So the source session clips were intact; the **bulk re-duplication dropped the notes
for one track**. (Possibly a timing/ordering issue — the track was the most heavily
re-pushed/automated; or the subsequent `performed_automation` pass interfered. The
manual fix below proves the notes were copyable.)

## The masking trap: `ableton_clip(action='list')` note_count lies

`ableton_clip(action='list', location='arrangement', track_index=7)` reported
`note_count: 64` for the verse1 arrangement clip that actually had **0** notes. It
appears to report the **source session clip's** count, not the arrangement clip's
real contents. This is dangerous: the integrity check an agent would naturally run
(list clips, compare counts to the DB) shows everything correct while the arrangement
is silent. The only reliable read was `get_notes_extended` (or a render).

→ **Fix the note_count** to reflect the arrangement clip's own notes
(`len(get_notes_extended(...))`), so a post-materialize integrity sweep can catch a
dropped-notes clip.

## A THIRD oddity: `duplicate_to_arrangement` deletes sibling EMPTY clips

While repopulating Human Riff manually, a single
`duplicate_to_arrangement(track=7, clip=3, start=112)` (onto a region where empty
sibling clips sat at 144–480) **removed the 7 trailing empty clips** — no
`spurious_clips_*` reported. Duplicating onto a region with **no** existing clips was
clean (siblings with notes survived). So the spurious-clip handler appears to treat
pre-existing empty clips as "spurious" and delete them. Benign here (they were empty)
but a landmine if those clips had content.

## The manual fix that worked (and proves the data was fine)

Per-clip `duplicate_to_arrangement` from the (intact) session clips, onto an EMPTY
timeline region, copied the notes correctly every time:

```
# delete the empty Human Riff arrangement clips, then for each section:
ableton_clip(action='duplicate_to_arrangement', track_index=7,
             clip_index=<session slot>, start_beats=<section beat>)
# verify with get_notes_extended — chorus3 came back with its 305 notes
```

So `duplicate_to_arrangement` is reliable **one call at a time onto empty regions**;
the bulk `execute --only arrangement` path is what dropped them.

## Suggested fixes

1. **Post-materialize integrity assertion in `execute`**: after the arrangement
   phase, assert each arrangement clip's `len(get_notes_extended)` equals its source
   session clip's note count (modulo Live coalescing). HALT + report on a mismatch
   instead of reporting `OK`. This single guard would have turned a silent
   1-hour debugging session into a one-line failure.
2. **Root-cause the bulk drop**: why does re-duplicating all N placements drop notes
   for one track while a per-clip call succeeds? Suspect ordering/timing (the track
   had just been re-pushed via `--only clips` + carried the most performed
   automation), or interaction with the immediately-following `performed_automation`
   pass.
3. **Fix `ableton_clip list` note_count** to read the arrangement clip's own notes,
   not the source session clip's (the masking trap above).
4. **`duplicate_to_arrangement` spurious-clip handler**: don't delete pre-existing
   empty arrangement clips as "spurious" (or only delete clips it itself just created
   at the wrong position).

## Workaround (today)

After ANY arrangement (re)materialization, verify per track with `get_notes_extended`
(NOT `ableton_clip list` note_count) or a render+stem-loudness check before trusting
it. To repopulate a dropped track: delete its empty arrangement clips, then per-clip
`duplicate_to_arrangement` from the session clips onto the cleared region.
