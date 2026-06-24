# Bug: arrangement-integrity comparator FALSE-HALTs the push on (1) Live's same-pitch overlap truncation and (2) half-eps bucket instability

**Type:** bug — the ARR-PROJ integrity assert (`assert_arrangement_materialized`) over-fires.
**Severity:** H. It HARD-HALTs the arrangement push (`execute --only arrangement`) and
fails `verify-arrangement` (exit 1) on a materialization that is in fact **faithful** —
every note ONSET is present in Live; the only differences are durations Live itself
clamped because its clip model forbids same-pitch overlap, plus a pure rounding
artifact. The safety net built to catch the 06-21 bulk-drop / 06-22 orphan bugs now
blocks a correct render. Any song that authors same-pitch note stacks/overlaps
(`add_wildness`, layered doublings, legato) or uses micro-timing `feel` offsets that
land starts on a half-eps boundary will hit this.

**Engine / server:** `0.1.0+4372b6734f8d`. Surfaced on song `alien` (compose/alien),
a 22-EDO song with `add_wildness` stacks + per-part `feel` micro-timing.

> **✅ STILL REPRODUCES on `1.5.0` (`d80fe21`, develop) — 2026-06-23.** A full
> `push execute --song alien --probe` HALTs at the `arrangement` phase
> (`49/50 ok, 1 failed`) on `arrangement.integrity_assert`; `verify-arrangement`
> (exit 1) reports the **identical 9 divergences** enumerated below — neither
> comparator defect has been addressed. **Operational workaround that unblocks the
> push:** `execute --only arrangement --probe` (materializes correctly; still
> asserts) then `execute --only cues --probe` (exit 0) — the arrangement clips ARE
> placed; only the post-phase assert over-fires, and `cues` runs independently of
> it. (Tangential, self-healed: that full run also left one orphan arrangement clip
> at the song-end boundary beat — `Noise 2 @ 480.0` — which a subsequent standalone
> `--only arrangement` clear+rebuild swept; a one-time artifact, not this comparator
> bug, noted so triage isn't surprised by a `1 orphan clip(s)` line.)

**Files:** `src/hallucinote/sync/arrangement_compare.py` (the comparator —
`compare_clip_notes`, `_bucket`, `_dur_vel_match`); consumed by
`src/hallucinote/sync/arrangement_verify.py` (`assert_arrangement_materialized` /
`verify_song_arrangement`).

## Symptom

After a clean rebuild (`build.py --reset`) + `execute --only clips` + `execute --only
arrangement`, the arrangement phase completes all placement calls (98/98) then HALTs on
the final `arrangement.integrity_assert`. `verify-arrangement --song alien` (exit 1)
reports the same 9 divergent placements:

```
[diverged] Human Riff  / prechorus1 @ 112: 3 missing, 3 extra, 0 mismatch
[diverged] Human Riff  / prechorus2 @ 224: 3 missing, 3 extra, 5 mismatch
[diverged] Human Riff  / chorus2    @ 256: 0 missing, 0 extra, 9 mismatch
[diverged] Human Riff  / chorus3    @ 352: 0 missing, 0 extra, 22 mismatch
[diverged] Drums       / verse1     @ 48 : 0 missing, 0 extra, 6 mismatch
[diverged] Drums       / bridge     @ 288: 0 missing, 0 extra, 4 mismatch
[diverged] Drums       / chorus3    @ 352: 0 missing, 0 extra, 1 mismatch
[diverged] Sub Bass    / chorus1    @ 144: 0 missing, 0 extra, 16 mismatch
[diverged] Sub Bass    / bridge     @ 288: 0 missing, 0 extra, 1 mismatch
```

Re-running `execute --only arrangement` reproduces it **identically** (deterministic —
not a transient stack/orphan that a fresh clear sheds, which is what the skill's
"re-run, it's idempotent" remedy assumes).

## Root cause — TWO independent comparator defects

### Finding 1 — `mismatch` is Live truncating overlapping same-pitch notes (64/64 cases)

build.py legitimately authors **overlapping same-pitch notes**: a note whose duration
extends past the next onset of the SAME pitch (wildness stacks, sustained riff tones
under feel jitter, layered sub-bass). Live's MIDI clip model forbids two same-pitch
notes from overlapping, so on `set_notes` it **truncates the earlier note to end
exactly at the next same-pitch onset**. This is faithful: every onset survives; only
the duration is clamped to what Live can hold.

Verified against the real notes — for **all 64** `mismatch` notes, `live.dur ==
(next_same_pitch_onset − start)` to <1.5e-3 beats:

```
Human Riff chorus2  p63 s0.612 : DBdur 0.255 -> LIVEdur 0.150  (next p63 onset 0.762, gap 0.150)
Human Riff chorus3  p63 s20.667: DBdur 0.283 -> LIVEdur 0.083  (next p63 onset 20.750, gap 0.083)
Drums      verse1   p38 s43.000: DBdur 0.500 -> LIVEdur 0.250  (next p38 onset 43.250, gap 0.250)
Sub Bass   chorus1  p33 s24.025: DBdur 2.200 -> LIVEdur 2.000  (next p33 onset 26.025, gap 2.000)
Drums      bridge   p36 s63.000: DBdur 0.500 -> LIVEdur 0.003  (next p36 onset 63.003, gap 0.003)
...  64/64 explained by trim-to-next-same-pitch-onset (incl. 1 merge-to-longer where the survivor runs to the next onset).
```

`_dur_vel_match` requires `abs(a.dur - b.dur) <= eps` (eps=1e-3), so every clamped note
fails → `mismatch` → `has_corruption()` → HALT. The comparator already models the
same-pitch COLLAPSE (one note per (pitch,start)); it does **not** model the same-pitch
overlap TRIM that necessarily accompanies it.

### Finding 2 — `_bucket()` half-eps rounding instability (false `missing`+`extra`)

`_bucket(start, eps) = round(start / eps)` with eps=1e-3. Per-part `feel` offsets place
some starts on an **exact half-eps boundary** (start/eps = N.5). `round()` is
half-to-even AND the DB value vs Live's round-tripped value differ by sub-ULP noise, so
the SAME note buckets to adjacent integers on the two sides — surfacing as BOTH
`missing` (DB bucket) and `extra` (Live bucket). The "missing" and "extra" lists contain
the **identical note** (same pitch/start/dur/vel):

```
prechorus1 MISSING: p56 s17.9825 d0.5 v118 | p68 s5.9675 d1.0 v118 | p68 s13.9775 d1.0 v118
prechorus1 EXTRA  : p56 s17.9825 d0.5 v118 | p68 s5.9675 d1.0 v118 | p68 s13.9775 d1.0 v118   # same 3 notes
```

Proof of the instability:
```
17.9825/1e-3 = 17982.5      round = 17982   round(+1ulp) = 17983   # flips
 5.9675/1e-3 = 5967.5       round = 5968    round(-1ulp) = 5967    # flips
13.9775/1e-3 = 13977.4999.. round = 13977   round(+1ulp) = 13978   # flips
```

These are not drops or orphans — the note is provably present on both sides. 6 such
false divergences across prechorus1 + prechorus2 (the ε-bucket boundary is hit only by
feel-offset starts ending in `…x5` at the 4th decimal).

## Impact

- `assert_arrangement_materialized` HALTs the arrangement push for a faithful set →
  the push reports PARTIAL/fail, blocking the documented note-edit workflow
  (`rebuild → execute --only arrangement`) and the downstream render.
- `verify-arrangement` exits 1 on a faithful set → the "before you trust a set / before
  a render" gate cries wolf.
- Triggers on common authoring: any same-pitch overlap (wildness, doublings, legato
  sustains) and any feel/micro-timing that lands a start on a half-eps boundary. Not
  alien-specific.

## Repro

1. `python songs/alien/build.py --reset`
2. `… push probe-and-link --auto-session --song alien --probe`
3. `… push execute --song alien --only clips --probe`
4. `… push execute --song alien --only arrangement --probe`  → HALTs at integrity_assert
5. `… verify-arrangement --song alien`  → exit 1, the 9 divergences above

## Suggested fixes

**Finding 1 (the load-bearing one).** Teach the comparator that Live's same-pitch
overlap trim is faithful. Options, best first:
- **Normalize same-pitch overlaps in BOTH note sets before comparing** — clamp each
  note's duration to the next same-pitch onset (the transform Live applies) on the DB
  side too, then compare. Faithful trims vanish; a genuine drop/drift still shows.
- Or relax `_dur_vel_match` to accept `live.dur <= db.dur` when `start + live.dur`
  coincides (±eps) with the next same-pitch onset in the DB stack.
- Consider pre-clamping same-pitch overlaps in the **materialization/mutator** path so
  the DB never stores a duration Live can't hold (makes DB==Live and removes a class of
  "smell"); the comparator fix is still wanted as the backstop.

**Finding 2.** Replace the hard `round()` bucket with a stability-safe scheme: bucket on
`floor(start/eps + 0.5)` is no better — instead match within tolerance via sorted
nearest-neighbor (greedy pair DB↔Live notes of equal pitch whose starts are within
eps), or widen/î half-open the bucket and reconcile boundary collisions. A note must
never appear in both `missing` and `extra`.

Both should be unit-testable in `arrangement_compare.py` (it's pure) — add cases:
(a) a DB stack with a same-pitch overlap whose Live twin is trimmed to the next onset →
faithful; (b) a note at start = k·eps + eps/2 with sub-ULP noise on one side →
faithful.

## Notes for the song side (not a workaround — flagging the authoring dimension)

The same-pitch overlaps in `add_wildness` / feel layers are arguably a build.py smell
(durations that no DAW can represent), but the FRAMEWORK should materialize+verify them
gracefully rather than HALT. Filed per the user's "don't work around it" directive; the
alien render is blocked pending the comparator fix (the Live arrangement itself is
faithful — every onset present, durations clamped only where Live's model requires).
