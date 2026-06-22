# Note-edit arrangement re-materialization STACKS notes (corrupts the arrangement) when the edited clip isn't the last on its track

> **RESOLVED by ARR-PROJ (2026-06-22).** Root cause = the copy-with-positional-link
> materialization model (`duplicate_to_arrangement` re-firing Live's B-24 overlap-split
> onto an occupied timeline). The redesign replaces it with arrangement-as-projection:
> the note path now CLEARs + `create`+fills a fresh clip from the DB every push, so the
> overlap-split cannot occur by construction, and a post-phase integrity assert HALTs on
> any divergence (no silent `OK`). This is an **acceptance witness** for the redesign,
> not a separate patch — see `.prawduct/artifacts/arrangement-materialization-redesign.md`
> §1/§10 and the ARR-PROJ build plan (Chunks 1–5 built; broad live e2e tracked in
> `.prawduct/operator-verification.md`). Backlog item ARR-9X4T closes when the redesign
> merges.

**Severity:** H — silent, AUDIBLE corruption of the rendered arrangement (doubled /
tripled drum hits, stacked riffs), produced by following the **documented** recovery.
No error is raised; the push reports `OK`. Recovery from the corruption requires a
manual full-arrangement clear (~49 individual delete calls — there is no bulk
primitive). This is the common case: editing the notes of *any* mid-song section and
re-materializing.

**Engine / server:** `0.1.0+4372b6734f8d` (server confirmed; Remote Script freshly
re-vendored to the same fingerprint this session). Song `alien`, branch `compose/swell`.

## Summary

The skill (`skills/ableton-push`, "Re-materialize the arrangement after a note edit
(SYN-4R7P)") documents this recovery for getting edited session-clip notes into the
arrangement:

> re-push the clips (`execute --only clips`), **delete the stale arrangement clips in
> Live**, then re-run `probe-and-link --probe` → `execute --only arrangement --probe`.

Following it **corrupts the arrangement** whenever the deleted clip is NOT the last
clip on its track — i.e. almost always. Notes get stacked/split into clips, including
clips I never touched.

## What I did (exact repro)

1. Edited 3 session clips in `build.py` (Drums `chorus1` + `chorus2`, Human Riff
   `chorus1`), rebuilt the DB, `push execute --only clips --probe` → OK (session clips
   updated, verified higher note counts in DB).
2. Per the documented recovery, deleted those 3 **mid-timeline** arrangement clips in
   Live via `ableton_clip(action='delete', location='arrangement', …)`.
3. `push probe-and-link --song alien --probe` → reconciled.
4. `push execute --song alien --only arrangement --probe` → reported `[arrangement]
   ok (49 call(s))`, `OK`.

## What happened — `--only arrangement` re-duplicated ALL 49 placements onto a still-occupied timeline

The phase ran **49 calls** = every arrangement clip in the song, not just the 3 whose
links were dropped. Because the other 46 clips were still physically in Live's
arrangement, `duplicate_to_arrangement` landed copies onto occupied/overlapping
regions and triggered the documented B-24 split side effect — **stacking notes**.
Verified note counts (DB = source of truth vs Live arrangement after the recovery):

| clip | DB | arrangement after recovery |
|---|---|---|
| Drums chorus1 (edited) | 116 | **263** |
| Drums verse2 (NOT edited) | 337 | **429** |
| Drums chorus2 (edited) | 243 | 258 |
| Human Riff bridge (NOT edited) | 72 | **221** |
| Human Riff prechorus2 (NOT edited) | 49 | **132** |
| Human Riff verse2 (NOT edited) | 54 | **95** |

Tracks I did **not** delete any clip from (Alien Voice, Noise) stayed clean; Sub Bass
came out off-by-1. So the damage correlates with *which tracks had a mid-timeline
delete* — the delete renumbers that track's `arrangement_clip` indices, the reconcile
rebinds imperfectly, and the blanket re-duplicate then collides with the survivors.

## Root cause (best reading)

1. `execute --only arrangement` is **not incremental/idempotent** — it re-duplicates
   *every* placement (49), regardless of which links were dropped.
2. Deleting a mid-timeline arrangement clip makes Live **renumber** the later
   `arrangement_clip` indices (down-shift).
3. `probe-and-link` drops/rebinds links, but the non-deleted clips **remain in Live**.
4. The blanket re-duplicate therefore lands on **occupied** regions → `duplicate_to_
   arrangement`'s B-24 overlap/split side effect **stacks** notes. The spurious-clip
   handler doesn't catch exact-overlap stacking.

## The recovery that actually worked (and its cost)

Clear the **entire** arrangement — every clip on every track — then
`execute --only arrangement --probe` onto the **empty** timeline (the fresh-push
path). Result verified clean: every clip == its original materialization + exactly my
intended edits (Drums chorus1 82→116, Human Riff chorus1 32→36, etc.).

The cost: there is **no bulk/clear primitive**, so this was **~49 individual
`ableton_clip(delete)` calls** (10 rounds of "delete index 1 on each track"). That is
the "all this trouble" we want to stop hitting on every song update.

## Suggested fixes (pick)

1. **Make `execute --only arrangement` idempotent/safe**: before each
   `duplicate_to_arrangement`, delete any existing arrangement clip at the target
   `(track, start_beats)` (or skip when its note-fingerprint already matches the
   session clip). Then re-materialize is safe no matter what's already on the timeline.
2. **A one-command rebuild**: `push execute --rebuild-arrangement` (or
   `push rebuild-arrangement`) that atomically clears all arrangement clips and
   re-duplicates from session clips. This is the safe recovery as ONE step instead of
   ~49 manual deletes — and it should become the canonical note-edit→arrangement path,
   replacing the SYN-4R7P "delete the stale clip by hand" dance in the skill docs.
3. **Bulk clear primitive**: `ableton_clip(action='clear_arrangement', track_index=…)`
   (or song-wide) so any manual recovery isn't O(clips) round-trips.
4. **Reconcile correctness**: after *any* arrangement-clip deletion, treat the whole
   affected track's placements as stale (indices shifted) and clear+rebuild that track
   rather than duplicate-onto-occupied.

(1)+(2) together would make the everyday "I edited some notes, re-materialize" loop a
single safe command and remove the foot-gun entirely.

## Workaround (today)

Do **not** use "delete the stale arrangement clip → `execute --only arrangement`" for
any clip that isn't last on its track. Instead: delete **every** arrangement clip on
**every** track, then `execute --only arrangement --probe` onto the empty timeline.
Verify by listing each track's arrangement note counts against the DB before trusting
a render.

## Secondary note

`duplicate_to_arrangement` onto an occupied/overlapping region stacks notes via the
B-24 split side effect, and the count can come out either > or < the session clip
(stacking vs split-drop) — so a post-rematerialize "arrangement note_count == session
note_count" assertion would be a cheap guard the push could run itself.
