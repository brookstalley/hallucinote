> **RESOLVED 2026-06-20 (branch `fix/incoming-bugs-2026-06-20`).**
> `ableton_clip(action='list', location='arrangement')` now returns `note_count`
> (MIDI-only, `None` for audio) and `muted` per clip; `ableton_arrangement`'s
> `info` action carries a tip pointing at that read. See `handlers/clip.py` +
> `actions/arrangement.py` + tests in `tests/unit/test_actions_clip.py`. Wire-shape
> change → re-vendor to expose live (operator-verification enqueued).

# Per-track arrangement-clip read lives on `ableton_clip(list, arrangement)`, not `ableton_arrangement` — a discoverability gap, plus no `note_count`

**Severity:** L (ergonomics / discoverability — the capability EXISTS). Filed after
initially mis-diagnosing it as a missing capability; corrected here.

**Engine version:** `1.5.0`.

## The correction

The per-track arrangement-clip read **does exist**:

```
ableton_clip(action='list', track_index=5, location='arrangement')
-> {clips: [{arrangement_clip_index, name, start_beats, length}, ...]}
```

My first pass filed this as "no per-track arrangement read in the toolset." That
was wrong — I checked `ableton_arrangement`'s action menu (cues + loop + view +
`info` only), found nothing, and jumped straight to `ableton_probe`
(`song.tracks[i].arrangement_clips`, one `get` per property) without checking
`ableton_clip`'s menu. The read was one tool over the whole time.

## The actual (smaller) friction

1. **Discoverability.** When you're debugging *the arrangement* — "did the push
   materialize the clips on this track?" — `ableton_arrangement` is where you look
   first. It owns cues, loop, and a global `info`, but the per-track clip
   inventory lives on `ableton_clip`. An agent reasoning by tool-name lands on the
   wrong tool and (as I did) reaches for raw `probe`. A pointer in
   `ableton_arrangement(action='help')` / `info` ("for per-track clips use
   `ableton_clip(list, location='arrangement')`") would close this.

2. **No `note_count`.** `list` returns `{arrangement_clip_index, name,
   start_beats, length}` — enough to find missing/stray *placements*, but not to
   answer the actual user question that started this ("the track shows **no
   events**"). A long clip that is empty vs. full looks identical. You still need a
   `probe` or a clip open to tell. Adding `note_count` (and maybe `muted`) to the
   `list` payload would directly answer the "no events" class of report.

## Where it surfaced (alien, branch `compose/swell`, engine 1.5.0)

User report: "the Noise track shows no events across the whole song and has
multiple lanes the other tracks don't." `ableton_clip(list, arrangement)` on the
Noise track returned the real shape immediately once I used it:

```
Noise: [ {idx 1, "Noise 5", start 0.0,     length 400.647},   # one clip stretched over the whole song
         {idx 2, "Noise 4", start 400.647, length  32.24 } ]  # a stray tail clip
```

vs. the DB's 10 clean section placements (`Noise intro` … `Noise outro`). The
`length 400.647` / fractional `start` is the signature of a botched
`duplicate_to_arrangement` (the B-24 overlap-split side effect the
`duplicate_to_arrangement` help already documents) — not a missing read. Drums,
by contrast, listed a clean 10.

## Suggested fix (low effort)

- Add `note_count` (and `muted`) to the `ableton_clip(list, location='arrangement')`
  payload.
- Cross-reference from `ableton_arrangement` help/`info` to that read so agents
  debugging the arrangement find it without dropping to `probe`.

No new capability needed — this is a field add + a signpost.
