> **RESOLVED 2026-06-20 (SYN-SCAFFOLD-MISLINK, branch `fix/incoming-bugs-2026-06-20`).**
> `probe_and_link` now drops a track link whose surviving index is occupied by a
> canonical default-scaffold track (gated on the canonical NAME, preserving the
> rename-in-Live case); device links cascade with the dropped parent (sibling of
> the SYN-3C8K clip cascade); `check_coherence` refuses execute on the same
> signature. See `src/hallucinote/sync/push/probe.py` + regression tests in
> `tests/unit/sync/test_push_cli.py`.

# Reused session mislinks DB tracks onto the fresh set's scaffold BY INDEX on a set-swap — only the track whose old index vanished gets created; clips then fail en masse

**Severity:** M (high-friction). The **documented** set-swap recovery — "discard the
messy set, open a fresh default one, re-push onto the **reused** session" (SYN-3C8K
says this is supported) — silently mislinks. The failure surfaces three phases later
as `clips` errors that look like a clips/scenes problem, not a linking problem, so it
misdirects. Recoverable only by abandoning the reused session for `--auto-session`.

**Engine version:** `1.5.0`. Song `alien`, branch `compose/swell`.

## What happens

Reusing the song's existing session (`probe-and-link` auto-selected it; the session
was bound to the now-discarded set), `--probe`, onto a **fresh default Live set**
(`1-MIDI` / `2-MIDI` / `3-Audio` / `4-Audio`):

- `probe-and-link` reported `default_scaffold_unmatched_tracks: [1-MIDI, 2-MIDI,
  3-Audio, 4-Audio]` (so scaffold detection fired) — `auto_session_created: false`.
- `execute` **`tracks` phase: "1/1 ok"** — created exactly ONE of the 5 song tracks.
- Live afterward: `[1-MIDI, 2-MIDI, 3-Audio, 4-Audio, Noise]`. Only **Noise** was
  created; Drums / Sub Bass / Human Riff / Alien Voice were treated as already-linked.
- `clips` phase: **10/49 ok, 39 failed**, every failure:
  `IndexError: session slot N on track K is empty; create a clip first`. The planner
  emitted `replace_notes` (clip-exists path) for clips it believed were linked.
- `ableton_links` for the reused session held **79 rows — 49 clip + 23 device +
  2 return + 5 track — ALL inherited from the discarded set.** The reconcile dropped
  almost none.

## Root cause: index-based link reconcile can't tell "same index, different track"

The reconcile drops a link only when its `ableton_index` "no longer appears in the
probe." On a set swap:

- Old session's 5 track links pointed at old indices **1–5**.
- Fresh set has 4 scaffold tracks at indices **1–4**.
- Links to indices **1–4 SURVIVE** (those indices still exist — now occupied by
  scaffold tracks) → 4 DB tracks stay "linked," now pointing at the **wrong** tracks
  (e.g. Human Riff, a MIDI track, bound to `3-Audio`). `tracks` phase sees them
  linked → does NOT create them.
- The link to index **5 DROPS** (the fresh set has only 4 tracks, so index 5 is
  absent) → that DB track (Noise) is unlinked → created. **That's why exactly one
  track gets made** — the one whose old index happened to fall off the end.
- The 49 clip + 23 device links survive the same way (their `(track,slot)` /
  device positions still "exist"), so `clips` emits `replace_notes` onto empty
  slots → the 39 `IndexError`s.

The tell: scaffold detection and stale-link reconciliation don't cross-check. A track
flagged `default_scaffold_unmatched` is, by definition, **not** any DB track — so any
DB-track link pointing at that index should be dropped. It isn't.

## Contrast: `--auto-session` is correct

Same fresh set, `probe-and-link --auto-session --probe`:

```
unmatched_db_tracks: [Drums, Sub Bass, Human Riff, Alien Voice, Noise]   # all 5 → create
default_scaffold_unmatched_tracks: 4
unlinked_stale_clips: 0
```

A fresh session has zero inherited links, matches DB tracks to live **by name**
(scaffold names don't match → all 5 created), and `execute` then ran `tracks 5/5`,
`clips 49/49`. Clean.

## Suggested fixes

1. **Cross-check scaffold against links.** When a probed track is classified
   `default_scaffold_unmatched`, DROP any `ableton_links` row whose `ableton_index`
   points at it — the scaffold track is provably not the DB track. This alone fixes
   the set-swap-reuse path SYN-3C8K claims to support.
2. **Reconcile on identity, not bare index.** Confirm a surviving track link still
   maps to a track whose NAME matches the DB track (the same name-match used for
   fresh linking). On mismatch, drop + re-create. Cascade to that track's clip /
   device links.
3. **Detect the set-swap and warn.** If a reused session's linked indices resolve to
   a set where most names no longer match (esp. all-default-scaffold), surface
   "this session was bound to a different set — re-link fresh? (`--auto-session`)"
   instead of silently rebinding by index.

## Workaround (today)

Re-pushing onto a freshly-created Live set: **always** `probe-and-link
--auto-session` (mint a new session). Do not reuse / auto-select the song's existing
session. (Companion to the same-day rack-load report:
`2026-06-20-fresh-push-loads-rack-presets-as-empty-shells-from-browser-path-only.md`
— both surfaced doing the standard "fresh set + re-push" recovery.)
