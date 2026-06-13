# Bug report — `probe-and-link` leaves stale **clip** links on a Live-set swap, breaking the clips phase on re-push (2026-06-12)

Context: pushing `swell` from hallucinote-songs (branch `compose/missing`, DB
`songs/swell/swell-compose--missing.db`). Engine checkout `develop @ 0dc395c`
(one commit past the `v0.9.5` release commit `8d56555`); plugin 0.9.5;
hallucinote-mcp `0.1.0+486e7e2653ec`; Live 12.x Suite. The song itself is
unchanged and builds clean (`build.py` → 22 tracks, 8 sections, 8930 notes,
shape tests green).

## TL;DR

`probe-and-link --probe` strictly reconciles **track** and **return** links
against the probe, but performs **no reconciliation of `clip` links**. When the
Live set bound to a session is closed and a *different* set is opened, then the
same session is reused, the stale clip links survive. `execute`'s clips planner
treats "a `clip` link exists" as "the clip exists in Live", so it skips
`ableton_clip(action='create')` and emits **`replace_notes` only** — which fails
on every clip:

```
ableton_clip('replace_notes') failed: IndexError: session slot 2 on track 7 is
empty; create a clip first with ableton_clip(action='create', ...)
```

All 84 clips fail; the push halts at the `clips` phase (5/13 phases ok).

## Reproduction (what actually happened)

1. `swell` was pushed earlier (multiple sessions accumulated in the DB: four
   `ableton_sessions` rows from 2026-06-11 and one minted 2026-06-12 22:09,
   `0b4e364c…`). The 06-12 session was bound to some Live set, which got the
   full clip projection (`ableton_links` rows with `db_kind='clip'`).
2. That Live set was closed. A **fresh default set** was opened — canonical
   scaffold `1-MIDI / 2-MIDI / 3-Audio / 4-Audio`, returns `A-Reverb / B-Delay`,
   tempo 120, 8 scenes.
3. `probe-and-link --song swell --probe` auto-selected the most-recent session
   `0b4e364c…` (single-song DB, 4 sessions). Strict reconciliation **dropped 21
   stale track links + 4 stale return links** (their `ableton_index` no longer
   appeared in the probe) — correct. The **84 `clip` links were left intact**.
4. `execute --song swell --probe`:
   - `tempo_map`, `time_signature_map` ok
   - `tracks` 21/21 ok (links were dropped → recreated)
   - `returns` 4/4 ok (recreated)
   - `scenes` 1/1 ok
   - **`clips` 0/84 ok, 84 failed → halted**, every failure the IndexError above.

`ableton_links` for the session right after the halt:

```
db_kind  count
clip     84      <-- stale, survived reconciliation; never re-created
return   4       <-- fresh (just created by execute)
track    21      <-- fresh (just created by execute)
```

So the tracks/returns were correctly re-materialized, but the clip planner
believed 84 clips already existed and emitted replace-only against empty slots.

## Root cause

`probe-and-link`'s strict reconciliation enumerates the probe's **tracks and
returns** and drops any link whose `ableton_index` is absent. Clips are not in
the track/return probe, so **`clip` links are never candidates for the drop**.
When the bound set changes, clip links dangle. The `clips` planner's
create-vs-replace decision keys off link presence, so a dangling clip link
silently downgrades `create + replace_notes` to `replace_notes`-only.

This only bites when a session is **reused across a Live-set swap**. A fresh
`--auto-session` push never hits it (no clip links to go stale).

## Suggested fixes (any one closes it; first is the cleanest)

1. **Cascade clip-link drops in reconciliation.** When a track link is dropped
   as stale, drop the `clip` links parented by that track (same session). More
   generally: a `clip` link whose `(resolved track, slot)` is empty/absent in
   the probe is dangling and should be dropped exactly like a track/return link.
   This restores the "links describe Live truth" invariant the rest of the
   pipeline assumes.
2. **Make the clips planner verify before downgrading.** Before emitting
   replace-only, confirm the slot is non-empty in the probed snapshot; if empty,
   emit `create` first. (The coherence `--probe` snapshot is already in hand.)
3. **Let `replace_notes` auto-create on an empty slot** (or have `execute`
   treat the IndexError as "create then retry"). Weakest option — papers over
   the stale-link invariant violation rather than fixing it.

## Secondary observation (same code path)

On session **reuse** (`auto_session_created == false`),
`default_scaffold_unmatched_tracks` comes back **empty** even though the four
unmatched Live tracks are the exact canonical defaults (`1-MIDI` … `4-Audio`).
The clean-default-scaffold classifier appears gated on
`auto_session_created == true`, so the nice "delete the default scaffold? (Y/n)"
UX degrades to the generic Case-2 unmatched-Live refuse-and-confirm on reuse.
Worth classifying the scaffold regardless of whether the session was freshly
minted.

## Workaround used

Deleted the 84 stale `clip` links for the session
(`DELETE FROM ableton_links WHERE session_id = … AND db_kind = 'clip'`) and
re-ran `execute`. With clip links gone, the clips planner emitted
`create + replace_notes` and the push completed.
