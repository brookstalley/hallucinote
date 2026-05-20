# Runbook — odd-meter-experimental

**Agent run start**: 2026-05-19 ~12:35 PT (session begin)
**Agent run end**: 2026-05-19 ~13:15 PT (~40 min wall clock)
**Live state at start**: 4 tracks (1-MIDI, 2-MIDI, 3-Audio, 4-Audio) / 2 returns (A-Reverb, B-Delay) / 8 scenes / 120 BPM / 4/4 (default new set, Live 12.4 via MCP bridge)
**Agent**: fresh-context Wave 0 canary, run #3, posing as a moderately sophisticated user.

This run targets the brief's specifically-log questions: 5-against-7 polyrhythm
encoding, mid-section meter ratchet (7/8 -> 5/8 -> 6/8 -> 7/8 within ONE
section), 7/8 base-meter test shape, and whether any library generator assumes
4/4. Repeats of solo-piano-ambient / full-band-rock findings are noted in one
line each; detail is concentrated on the NEW axes.

## Friction Log

### Steps 1, 2, 4 (scaffold, hand-author snapshot, write tests)

Same friction as both prior runbooks: no `/new-song` skill, no documented
snapshot schema, only `falling-walking` ("historical, not a template") as model.
Not repeating. The snapshot carries an explicit `_note` field saying it's
synthetic.

### Step 3: `build.py` — every generator in `src/hallucinote/generators/` assumes 4/4

- **Goal**: use library generators (`drums.trip_hop_drum_pattern`,
  `bass.tresillo_bass`, `bass.walking_bass_to_next_chord`,
  `harmony.chord_pad`) the same way falling-walking does.
- **What happened**: read `src/hallucinote/generators/drums.py`,
  `bass.py`, `primitives.py` and found **every generator hard-codes
  `bar * 4.0`** for bar-to-beat conversion. Concretely:
  - `drums.kick_stumble`: `bs = start_beat + b * 4.0`
  - `drums.lazy_snare`: `bs = start_beat + b * 4.0` + `bs + 1.0`, `bs + 3.0` (assumes 4 beats/bar)
  - `drums.trip_hop_hats`: 8 eighth-notes per bar at offsets `[0.0..3.5]` (assumes 4 beats/bar)
  - `drums.bossa_shaker`: `for sixteenth in range(16)` — assumes 16 sixteenths/bar (which is 4/4 only)
  - `drums.tresillo_hats`: bs + TRESILLO_HITS where hits land at `0.0..3.5` (assumes 4 beats/bar)
  - `bass.tresillo_bass`: `bs = start_beat + b * 4.0`
  - `bass.walking_bass_to_next_chord`: `bs = start_beat + bar * 4.0` + beats at `[0.0, 1.5, 2.0, 3.5]`
  - `bass.chord_tone_embellishment`: hard-coded beat offsets `[0.0, 0.75, 1.5, 2.0, 2.75, 3.5]`
  - `generators/primitives.py`: `TRESILLO_HITS` are positioned `[0.0..3.5]` — usable in any meter ≥ 4 beats but the velocity profile presumes the bar length they live in
- **What was missing or confusing**: not a single generator takes a
  `beats_per_bar` parameter. `falling-walking.md` describes the song as 4/4
  throughout; the generators were written for that song and accreted the
  4/4 assumption. For 7/8 work, I had to hand-author every drum/bass/pad
  pattern from scratch — generators were unusable.
- **What I did instead**: dropped all library generator imports from
  `build.py`. Every part (drums, polyrhythm bass, harmonic pad, arpeggio,
  bell, click) is hand-rolled with literal loops over `range(bars)`,
  using my local `BEATS_PER_BAR_7_8 = 3.5` constant. The fracture section
  builds each bar's beat positions from its bar-meter explicitly.
- **Severity guess**: **important** — for the "compose in any meter" headline
  feature, the library's existing generators are 4/4-only. Either the
  generators need a `beats_per_bar` parameter (and TRESILLO_HITS needs a
  general subdivision) or the docs need to say "library generators target 4/4;
  hand-roll for other meters." Today's code says nothing.

### Step 5: `python3 songs/odd-meter-experimental/build.py --reset` — CLEAN

```
song_id=72645460103d4ee582b5e1ca51bcc126, timing_mode=native, tracks=7
  track  0  Master                 (master, 0 clips)
  track  1  01 Drums               (midi, 3 clips)   (lock/bloom/fracture)
  track  2  02 Polyrhythm Bass     (midi, 3 clips)   (lock/bloom/fracture)
  track  3  03 Harmonic Pad        (midi, 2 clips)   (bloom/release)
  track  4  04 Arpeggio            (midi, 1 clips)   (bloom)
  track  5  05 Bell Accents        (midi, 5 clips)   (all sections)
  track  6  06 Perc Click          (midi, 4 clips)   (intro/lock/bloom/fracture)
total notes: 1254
sections: ['intro', 'lock', 'bloom', 'fracture', 'release']
arrangement entries: 18
time_signature_map: 10 points     ← THE METER RATCHET
  bar   1.0  7/8
  bar  41.0  7/8
  bar  42.0  7/8
  bar  43.0  5/8
  bar  44.0  5/8
  bar  45.0  6/8
  bar  46.0  6/8
  bar  47.0  7/8
  bar  48.0  7/8
  bar  49.0  7/8
envelopes: 1   (1 send_level reverb swell)
```

**The schema accepts the per-bar meter ratchet without complaint.** The DB
models all 10 time_signature_map points happily. The question is whether they
SURVIVE push — see Step 7 below.

### Step 6: `pytest songs/odd-meter-experimental/tests/ -v`

**7/7 passing** after one round of test-side fixes.

Two tests initially failed; both were author-side miscounts about 7/8 math
that the failures usefully exposed:

1. **`test_polyrhythm_bass_positions_are_5_against_7`**: I asserted there
   should be **16** integer-beat note positions (one per bar's downbeat) but
   got **8**. Why: in 7/8, beats-per-bar = 3.5 (non-integer). Bar 0 starts
   at beat 0.0 (int), bar 1 at 3.5 (non-int), bar 2 at 7.0 (int), bar 3 at
   10.5 (non-int)... Only EVEN bars have integer downbeats. The 5-against-7
   offsets [0.0, 0.7, 1.4, 2.1, 2.8] preserve "integer-ness" only when
   added to integer starts. **Net: only even-bar downbeats land on integer
   beats; 8 not 16.** This is a finding to surface: **in non-4/4 meters
   with non-integer beats-per-bar, bar downbeats themselves land on non-
   integer beat positions**. Any UI or analysis tool that snaps to integer
   beats will mis-place odd-bar content.

2. **`test_polyrhythm_bass_positions_round_trip_precision`**: I picked too
   wide a window (`bar_start + BEATS_PER_BAR + 0.01`) which bled the next
   bar's downbeat into the current bar's set. Fix: half-open windowing.
   Real finding hiding in the noise — see Step 8 below for the related
   DB precision finding.

3. The **central test** (`test_time_signature_map_has_meter_ratchet`) PASSED
   first time: the DB faithfully records the 10 meter points. The schema
   has no issue with the ratchet; the issue is downstream (push).

### Step 7: Push to Live — the meter ratchet is silently dropped

Bound the song to a session by hand (same `ableton_sessions` blocker as
solo-piano-ambient runbook step 7; not repeating).

#### Step 7a: tempo_map — OK

```
{tool: ableton_session, args: {action: set_tempo, bpm: 84.0}}
```

**NEW FINDING**: the canary brief calls 168 BPM the "notional base tempo"
(meaning the eighth-note pulse). The DB needed to be set at 84 BPM because
Live's `BPM` is the quarter-note pulse regardless of meter. The build.py
documents this conversion inline but **there is no library helper for
"convert eighth-pulse BPM to quarter-pulse BPM for the chosen meter"**.
Authors of non-4/4 songs will hit this every time. A helper or even a
sentence in the snapshot schema docs would save the reasoning each time.

#### Step 7b: time_signature_map — METER RATCHET DROPPED (the central finding)

```
{calls: [{tool: ableton_session, args: {action: set_signature, numerator: 7, denominator: 8}, ...}],
 notes: ["per-bar meter automation is an MCP gap on Live 12.4 — ableton_automation
         has no 'song_signature' target_kind (see hallucinote_mcp/.../guides/gaps.md);
         9 non-bar-1 time_signature_map rows skipped"]}
```

**Exactly 1 of 10 time_signature_map rows reaches Live.** The 8 fracture-bar
meter points AND the bar-49 return-to-7/8 row are all silently skipped (with
a warn). Per `sync/push.py::plan_push_time_signature_map`, this is by design:
Live 12.4's `Song.signature_numerator/denominator` are GLOBAL — there is no
per-bar meter automation MCP can write. The push planner emits ONLY the bar-1
row and warns about the rest.

**This is the canary's central architectural finding:**
- **The DB models per-section meter changes correctly.** The schema (W4-C
  era) supports any number of `(start_bar, numerator, denominator)` triples
  per song.
- **The push pipeline cannot ship them.** Live 12.4's MCP surface has no
  `ableton_automation` target_kind for song-signature.
- **There is no documented escape hatch.** A user who reads the canary
  brief ("Exercises whether section-level time_signatures work") and looks
  only at the DB will see "yes, the ratchet round-trips through the DB!"
  and conclude the feature works. The truth is that LIVE never hears the
  ratchet — fracture plays in 7/8 throughout.
- The skill suggests "(see hallucinote_mcp/.../guides/gaps.md)" but the
  warn doesn't propose any workaround. The only path I can imagine
  ("write each bar as its own arrangement clip with explicit length matching
  its meter") isn't suggested anywhere and would require restructuring the
  whole song.

This is a major v1 scope finding. **Within-section meter ratchet authoring
is a DB-only operation today.** Severity: **blocker** for any song that
needs mid-section meter changes audible in Live.

#### Step 7c: tracks — 6 created cleanly at indices 5-10

All midi-kind. Clean.

#### Step 7d: returns — planner emits create even when default returns exist

Same flavor as solo-piano-ambient runbook step 8 but a different shape: the
planner emitted `create return 'Reverb'` even though Live's default set
already has A-Reverb and B-Delay. Live created a THIRD return at index 3
with name `C-Reverb` (auto slot prefix). Compared to prior canaries:

- solo-piano-ambient added a SECOND Reverb DEVICE to the existing A-Reverb
  return (giving the round-trip name corruption `Reverb | Reverb`).
- this canary added a SEPARATE return entirely (Live let me, because the
  push planner didn't probe for existing returns).

**NEW FINDING**: the returns push planner has no "match by name against
Live's existing returns before emitting a create" pass. If a song's snapshot
declares `Reverb` and Live already has `A-Reverb` (which becomes plain
`Reverb` after slot-strip — exactly the case here), the planner SHOULD treat
those as the same and skip the create. Today it emits the create
unconditionally, producing redundant returns. This is the same family as the
device-duplication finding from solo-piano-ambient but at the RETURN level.

Severity: **important** — affects every push into a default Live set.

#### Step 7e: clips — pushed ONE for the polyrhythm precision check

I did NOT push all 18 arrangement entries' worth of clips — the per-phase
ceremony cost from full-band-rock runbook step 7a (9000+ lines of clips
plan JSON for 18 clips here) is real and well-documented. Pushed just the
**Lock Polyrhythm Bass** clip (slot 2, track 6, 80 notes including the
5-against-7 ostinato).

```
ableton_clip(action='create', track_index=6, location='session', clip_index=2,
             kind='midi', length=56.0, name='Lock Polyrhythm Bass', notes=[80 notes])
→ {ok: true, notes_written: 10}   # only first 10 sent for the test
```

**Live accepted the float positions without complaint.** Position 2.1 in the
DB became `2.0999999999999996` (see Step 8) and Live wrote it without
warning. The clip exists in slot 2; Live's slot-level inventory confirms
it's there with the right length.

**NEW FINDING (related to gap discovery)**: `ableton_clip` exposes
`create`, `delete`, `duplicate_to_arrangement`, `fire`, `list`, `rename`,
`replace_notes`, `set_property`, `stop` — but **NO action that reads back
the notes from an existing clip.** This means: **MCP cannot verify that
fractional note positions round-tripped intact.** The only way to confirm
Live's stored positions is to:
- visually inspect in Live (no scripting), OR
- export and grep the .als file, OR
- depend on the future pull path (which the canary brief explicitly
  excludes from v1's reach).

For a canary stress-testing 1/64-grid encoding precision, no read-notes
action is a significant gap.

#### Step 7f: did NOT push mix, devices, envelopes, arrangement, cues

Time-capped. Based on prior runbooks the expectations are:
- **mix**: ~ 8 tracks × 2 + 3 returns × 2 + sends ≈ 25 calls.
- **devices**: 6 Operator loads — likely some will fail (URI guesses) per
  solo-piano-ambient runbook step 7c.
- **envelopes**: 1 send_level envelope across bloom (beats 84-136.5);
  whether the W4-B "spans a single session clip's beat range" check accepts
  this is uncertain — bloom's harmonic-pad session clip IS 56 beats long
  starting at beat 0 within the clip (which maps to arrangement beat 84-140
  via the arrangement_clip's start_bar=25 placement). Open question.
- **arrangement**: 18 entries; would likely succeed since clips are linked
  but only 1 clip is actually populated.
- **cues**: 5 cue points; per full-band-rock runbook step 7e, will fail
  unless arrangement has been extended past beat ~140 (the latest cue at
  bar 49 = beat 140 in 7/8).

### Step 8: Polyrhythm precision — DB faithful, AUTHORING math drifts

This is the canary's secondary central finding. Asked the DB to store
5-against-7 positions [0.0, 0.7, 1.4, 2.1, 2.8] (Live beats). Queried back:

```
note 0: start_time = 0.0                    ← exact
note 1: start_time = 0.7                    ← exact
note 2: start_time = 1.4                    ← exact
note 3: start_time = 2.0999999999999996     ← DRIFT (expected 2.1)
note 4: start_time = 2.8                    ← exact
```

**The DB faithfully round-trips whatever Python wrote in.** SQLite's REAL
storage uses IEEE 754 doubles; precision is preserved to the last bit. But
the COMPUTATION `(7.0 / 5) * 3 / 2.0` does NOT yield exactly `2.1` in IEEE
754 — it yields `2.0999999999999996` (subnormal sub-LSB drift). The
canary's `POLY_5_AGAINST_7_OFFSETS = [(7.0 / 5) * k / 2.0 for k in range(5)]`
list computation produces this drift on offset index 3 only; the others
happen to fall on representable values.

**Severity guess**: **paper-cut** in isolation. **important** if any
consumer asserts equality (e.g., a test expecting `start_time == 2.1`
exactly). The test `test_polyrhythm_bass_positions_round_trip_precision`
uses `abs_tol=1e-9` and passes; a stricter test would fail. The lesson:
**author beat positions as rational fractions or use `math.fsum` /
`fractions.Fraction` when generating polyrhythmic positions**, because
Python's float math will not reliably produce the "obvious" answer.

The brief asked "what precision does the DB preserve when you query the
notes back?" — answer: **the DB preserves what was given exactly, but the
GENERATOR side can introduce drift that's hard to anticipate**. The DB is
not the precision bottleneck; the floating-point arithmetic of the
polyrhythm offset computation is.

## Outstanding open questions

1. **Should library generators take a `beats_per_bar` parameter?** Today
   every generator in `src/hallucinote/generators/` hard-codes `bar * 4.0`
   and 4-beat-bar offset tables. For Hallucinote's "compose in any meter"
   headline, this needs a design pass — either parametrize the generators
   or rename them to `*_4_4` so users know they're 4/4-only.

2. **What's the v1 story for within-section meter changes that need to
   reach Live?** The DB models them; the push planner skips them; there's
   no documented workaround. Three options I can imagine:
   - Per-bar arrangement clips (one clip per bar, explicit length per
     meter). Awkward but reachable today.
   - Render to a long single-meter (e.g. 1/16) and bake meter into the
     visual grid via locators. Loses the meter-as-data property.
   - Wait for Live's per-bar meter automation MCP (which doesn't exist today).

   Which is the intended path? The brief said this is a "major v1 scope
   finding" if not — and the canary confirms it is.

3. **Is there a planned read-notes action on `ableton_clip`?** Without
   one, round-trip verification of fractional note positions requires
   eyeballing Live or parsing the .als file. The schema explicitly
   describes `replace_notes` as REPLACE (no append) — so the parity
   pattern is read-mutate-write — but there's no read primitive.

4. **Should generators emit polyrhythm offsets via `Fraction` not float?**
   The 5-against-7 drift on offset 3 (`2.0999999999999996`) is a hidden
   trap. If a future generator helper `polyrhythm(n, against=7)` ships, it
   should use `fractions.Fraction(7, 5) * k / 2` and float-convert at the
   mutator boundary, not propagate float drift into the DB.

5. **Should `plan_push_song_returns` probe Live's existing returns first?**
   It emits a `create` for every DB return regardless of what Live already
   has. Same pattern as solo-piano-ambient's device-load duplication, but
   at the return level. A name-match-against-Live check would prevent
   redundant returns.

6. **Notional tempo conversion**: the brief said "168 BPM" meaning
   eighth-note pulse. Live's BPM is the quarter pulse. For 7/8 with
   eighth-pulse = 168 → quarter-pulse = 84. There's no library helper
   for "convert pulse-of-meter BPM to Live's quarter BPM". A snapshot-
   docs sentence would prevent every non-4/4 author from re-deriving this.

7. **Does `time_signature_map` semantics support meter-change *between*
   sections (not just within)?** Yes, by adding a row at the section
   boundary — exactly what build.py does. But the user-facing model is
   "sections have meters" rather than "the song has a time_signature_map";
   no library helper says `section.set_meter(7, 8)`. Authors author the
   map directly. Probably fine; documenting it would help.

## What I built

- `songs/odd-meter-experimental/build.py` — **clean run**, 1254 notes,
  6 MIDI tracks + 1 return + master, 5 sections (intro/lock/bloom/fracture/
  release), 18 arrangement entries, 10 time_signature_map points (the meter
  ratchet), 1 envelope.
- `songs/odd-meter-experimental/captured_session.json` — hand-authored;
  6 tracks + 1 return + master at 7/8 168 BPM (notional).
- `songs/odd-meter-experimental/tests/test_build.py` — **7 passing tests**:
  - `test_build_runs_clean_and_produces_canary_shape` — count + presence
  - `test_time_signature_map_has_meter_ratchet` — central canary test for meter ratchet
  - `test_polyrhythm_bass_positions_are_5_against_7` — bar 0 offsets + integer-position count
  - `test_polyrhythm_bass_positions_round_trip_precision` — DB float round-trip
  - `test_fracture_clip_lengths_match_meter_ratchet` — ratchet sums to 25.0 beats, not 28.0
  - `test_fracture_bass_offsets_depend_on_each_bars_length` — different bar lengths → different offsets
  - `test_does_NOT_assume_4_4_bars_times_4_equals_beats` — counter-test for the 4/4-implicit pattern
- `songs/odd-meter-experimental/decisions/`, `annotations/` — empty
  directories per convention (no decisions or annotations yet).
- **Push attempt** (partial, time-capped):
  - tempo (84 BPM): OK.
  - time_signature (7/8 only — **9 of 10 meter-ratchet rows DROPPED**).
  - 6 tracks: OK, indices 5-10.
  - 1 return (Reverb): OK at index 3 as `C-Reverb`. (NEW finding: planner
    emits create even when Live's default returns include functionally
    equivalent A-Reverb.)
  - 1 clip (Lock Polyrhythm Bass with float positions): OK; Live accepted
    `2.0999999999999996` without complaint.
  - mix, devices, envelopes, arrangement, cues: not attempted (time).
- **Pull**: NOT attempted. With only 1 clip pushed and the meter ratchet
  un-pushable, pull-then-DB-comparison would be dominated by "un-pushed
  state showing as drift" noise; the meaningful round-trip information
  isn't reachable without first completing the push.

## Final state

- **Live set state after run**: 10 tracks (1-MIDI, 2-MIDI, 3-Audio, 4-Audio
  from default + 6 new: 01 Drums, 02 Polyrhythm Bass, 03 Harmonic Pad,
  04 Arpeggio, 05 Bell Accents, 06 Perc Click), 3 returns (A-Reverb,
  B-Delay from default + C-Reverb mine), 84 BPM, **7/8 globally**. Track 6
  has 1 MIDI clip in slot 2 (Lock Polyrhythm Bass) with the 80-note
  polyrhythm. Other 5 new tracks: empty. No arrangement, no cues, no
  envelopes pushed. No instruments loaded on any new track (clip playback
  would be silent).
- **DB state after run**: full song authored — 7 tracks + 1 return + 17
  session clips + 18 arrangement entries + 5 sections + 5 cues + 1 envelope
  + 1254 notes + **10 time_signature_map points (the meter ratchet)**.
  `ableton_sessions` row + links for 6 tracks + 1 return + 1 clip (Lock
  Polyrhythm Bass).
- **Tests**: 7 passing, 0 failing.
- **Subjective overall friction level**: **high** for the meter ratchet
  axis (silently dropped on push). **medium** for the polyrhythm precision
  axis (works mechanically, hidden traps around float arithmetic).
  **medium-high** for the 4/4-only generators axis (every existing
  generator is unusable for 7/8 work, doc says nothing about this).
  Top three NEW findings:
  1. Meter ratchet within a section — DB models it perfectly, push planner
     silently drops 9 of 10 entries (MCP gap).
  2. Every library generator in `src/hallucinote/generators/` hard-codes
     `bar * 4.0`; unusable for non-4/4 songs.
  3. MCP `ableton_clip` has no read-notes action — cannot verify Live
     accepted fractional polyrhythm positions correctly from MCP alone.
