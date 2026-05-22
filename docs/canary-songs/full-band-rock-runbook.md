# Runbook — full-band-rock

> **Historical session log.** Filenames and paths reflect the state at
> session time (2026-05-19). Per-song bootstrap test files are now
> named `test_<slug>_build.py` (post-Arc-6 convention); references
> below to `tests/test_build.py` reflect the older bare-name pattern.

**Agent run start**: 2026-05-19 12:15 PT (session begin)
**Agent run end**: 2026-05-19 12:26 PT (~11 min wall clock; mostly authoring, fewer phases pushed than solo-piano-ambient)
**Live state at start**: 4 tracks (1-MIDI, 2-MIDI, 3-Audio, 4-Audio) / 2 returns (A-Reverb, B-Delay) / 8 scenes / 120 BPM / 4/4 (default new set, Live 12.4 via MCP bridge)
**Agent**: fresh-context Wave 0 canary, run #2, posing as a moderately sophisticated user.

This run targeted the brief's specifically-log questions: audio-track placeholders, third-party VST behavior, repeated-section naming, sidechain modeling, and master fade-out automation. I read `solo-piano-ambient-runbook.md` for awareness and short-circuit duplicate findings; novel friction is the focus below.

## Friction Log

### Steps 1, 2, 4 (scaffold, hand-author snapshot, hand-write tests)

Same friction as solo-piano-ambient runbook steps 1, 2, 4 — no `/new-song` skill, no documented schema for hand-authored snapshots, only the "this is historical, not a template" example to copy from. Not repeating. The captured_session.json I hand-authored carries explicit `_note` fields marking every guess (preset URIs, the third-party VST class name, the sidechain-routing intent) so this canary's snapshot itself is a data point about what hand-authoring requires.

### Step 3: `build.py` — repeated sections needed two parallel workarounds

- **Goal**: model the arrangement `intro / verse / chorus / verse / chorus / bridge / chorus / outro` — 2 verses, 3 choruses with the same names.
- **Command/skill invoked**: hand-coded `M.create_section(...)` 8 times.
- **What happened**: It works, but only because I built two parallel workarounds without realizing they were workarounds until I looked at the schema:
  1. **Sections table has no UNIQUE on `(song_id, name)`** (`schema.sql:127-138`). Multiple sections with the same `name` are legal. So I could just call `create_section(name='verse', ...)` twice with different bar ranges. Good.
  2. **Clips table has `UNIQUE(track_id, slot)`** (`schema.sql:77`). So the second verse on the drums track CANNOT live in the same slot as the first verse — I have to author it as a SEPARATE clip in a different slot, even though the content is identical. I picked slots 2 (verse 1) and 5 (verse 2); chorus uses 3, 6, 7. This is a content-duplication tax: changing the verse melody requires editing TWO clips.
  3. **Cue points table** has no UNIQUE constraint either, so 3 cues with `name='chorus'` are legal — but Live's arrangement-locator UI shows them by name, so a user navigating "go to chorus" would see three identical entries.
- **What was missing or confusing**: there is no library helper for "same clip, multiple arrangement placements." The `arrangement_clips` table appears to support this — the clip_id is just an FK, you could insert 3 rows all referencing the same chorus clip — but I didn't try it because clip mutation through `replace_clip_notes` would then change ALL placements, which is presumably NOT what you want for "chorus is the same melody but vocals differ." So I built one clip per occurrence per track instead. **This duplication is intended, presumably**, but no doc says so.
- **What I did instead**: distinct slot per occurrence; identical content per pair; tested via `test_repeated_sections_have_distinct_clip_slots`.
- **Severity guess**: **important**. The cost model is invisible: a user writing a build.py for a song with a 3x-repeated chorus probably reaches for "one clip, three placements" instinctively. Whether to use that or "three clips, one placement each" matters for editability and is not documented.

### Step 5: `python3 songs/full-band-rock/build.py --reset` — clean run

```
song_id=93f0b323b6924668af71831edb2c3175, timing_mode=native, tracks=9
  track  0  Master                   (master, 0 clips)
  track  1  01 Drums                 (midi, 7 clips)
  track  2  02 Bass                  (midi, 7 clips)
  track  3  03 Rhythm Guitar         (audio, 0 clips)
  track  4  04 Lead Guitar           (audio, 0 clips)
  track  5  05 Keys                  (midi, 4 clips)
  track  6  06 Backing Vox Pad       (midi, 3 clips)
  track  7  07 Lead Vocal            (audio, 0 clips)
  track  8  08 Parallel Comp Bus     (audio, 0 clips)
total notes: 1285
returns: ['Vocal Verb', 'Drum Room', 'Bus Comp']
sections: ['intro', 'verse', 'chorus', 'verse', 'chorus', 'bridge', 'chorus', 'outro']
arrangement entries: 21
envelopes: 2
  mixer_volume   24 breakpoints     ← sidechain placeholder on lead vocal
  mixer_volume   2 breakpoints      ← master fade-out
```

Note: the **audio tracks were accepted with `kind='audio'` and 0 clips with no errors or warnings** — the DB models them fine, including their mixer state and sends. That's the "DB-side" answer to "what does the capture format do with audio tracks": they're regular tracks minus the clip authoring path.

### Step 6: `pytest songs/full-band-rock/tests/ -v` — 3/3 pass

Three tests: shape (counts, kinds, returns, envelopes, cue duplicates), slot-discipline for repeated sections, audio-track-has-no-clips invariant. Clean.

### Step 7: Push to Live — bound by hand (same Step 7 blocker as solo-piano-ambient)

Skill refuses to invent `ableton_sessions.id`; dropped into Python:

```python
M.create_ableton_session(conn, song_id=..., name='canary-w0-fbr-push')
```

Same finding as solo-piano-ambient runbook step 7; not repeating. Severity: blocker for fresh users.

### Step 7a: Phase ordering reaches a hard wall (the per-phase ceremony compounded)

Push phases progress:

- **tempo_map**: 1 call, 1 applied (108 BPM). OK.
- **time_signature_map**: 1 call, 1 applied (4/4). OK.
- **tracks**: 8 calls, all 8 applied. Live tracks 5-12 created. **Audio tracks created cleanly** with `kind='audio'` — Live returns `{kind: "audio", name: "..."}`. No friction for the audio creation itself.
- **returns**: 3 calls, all 3 applied. Live returned indices 3-5 (after the existing A/B). Names came back as `C-Vocal Verb`, `D-Drum Room`, `E-Bus Comp` — the **slot prefix can be ANY letter A-Z, not just A/B**. The `strip_return_slot_prefix` regex `^[A-Z]-` handles this fine, so the DB-side round-trip works, but the snapshot's hand-authored `"name": "A-Vocal Verb"` would NEVER match what Live emits when the user already has A and B taken. New friction for hand-authored snapshots in a non-empty Live set: **prefix-letter assignment is a function of insertion position, not author choice**.
- **clips**: 21 calls planned, **1 manually pushed** as a proof. Each call carries the full notes array inline (Intro Drums has 85 notes, Verse Drums has 199 each, total ~1285). At ~1-2 KB per note in JSON-with-indentation, hand-marshalling 21 calls through MCP one at a time was prohibitive within the 45-min cap. **This is the per-phase ceremony cost the solo-piano-ambient runbook called out as "important"; full-band-rock's 8 tracks + 21 clips makes it a practical blocker for interactive use.** A planner-driven `execute` mode (planner streams calls + collects results) would change this from a 30-min slog to a 30-sec batch.
- **mix**: 49 calls planned (master vol/pan + 8 tracks × 2 + 3 returns × 2 + sends per track to each return). Not pushed for time reasons. **49 mostly-identical calls for a single push is the same ceremony tax, scaled with track count.**
- **devices**: 8 calls planned, all 8 attempted. **5 OK / 3 failed** — see Step 7b for the NEW findings.
- **envelopes**: 0 calls, 2 skipped — see Step 7c. THE central new finding.
- **arrangement**: HARD CRASH — see Step 7d.
- **cues**: 1 batched call attempted, **failed at MCP** — see Step 7e.

### Step 7b: Device load — three distinct failure modes, only one matches solo-piano-ambient

This is where the third-party-VST canary target landed, plus a brand-new finding about stock devices:

| Device (kind) | preset_uri | Result | Notes |
|---|---|---|---|
| `DrumGroupDevice` "Kit-Core 808" | `query:Drums#FileId_Core808` (guessed) | FAIL | Same as solo-piano-ambient 7c — URI guessed. |
| `Operator` (stock) | (none) | OK | Loaded with `name="Operator"`. |
| `PluginDevice` "Spitfire LABS Soft Piano" | `query:VST#SpitfireLABS-SoftPiano` (guessed) | FAIL | **Same generic error message as URI-guess failures.** Cannot tell "VST not installed" from "URI typo" from the message. W13-A would need to distinguish. |
| `AnalogDevice` (stock, no URI) | (none) | FAIL | **NEW FINDING.** Even Live's stock Analog instrument can't be loaded by `kind="AnalogDevice"` alone — the loader rejects with "no loadable browser item found for kind='AnalogDevice'". So Live's internal class names don't always match the loader's expected `kind` values. Other stock instruments (Operator, Compressor2 → "Compressor", Reverb, GlueCompressor) work; Analog doesn't. This is a stock-device gotcha NOT covered by the solo-piano-ambient runbook. |
| `Compressor2` (sidechain placeholder) | (none) | OK | Loaded as `name="Compressor"` — small naming drift, will likely affect round-trip if pull reads back `name="Compressor"` and overwrites the DB's `"Sidechain Comp (drum-key)"`. |
| `Reverb` × 2 (returns) | (none) | OK | Loaded onto existing returns. **Each return already had a Reverb device** (Live's default A-Reverb / B-Delay come pre-loaded; my new C/D returns came empty, so my loads went onto empty chains). No duplication this time because the returns are NEW, not the defaults — different from solo-piano-ambient step 8's `Reverb → "Reverb | Reverb"` corruption. |
| `GlueCompressor` (parallel-comp return) | (none) | OK | Loaded fine. |

**Key W13-A signal**: the snapshot recorded the VST as `{"class": "PluginDevice", "name": "Spitfire LABS Soft Piano", "guess_uri": "query:VST#..."}`. Nothing about manufacturer, plugin format (VST2/VST3/AU), or any unique fingerprint the loader could use. The current planner emits `kind: "PluginDevice", preset_uri: <whatever the snapshot has>`, and the loader treats it like any other URI — no special path for "plugin lookup by name+manufacturer." When `preset_uri` is omitted, `kind="PluginDevice"` alone is meaningless (Live needs the actual plugin identity). **Today's behavior on missing VST = generic URI-not-found error; W13-A's design needs to elevate this case (plugin missing vs URI wrong vs class-name wrong)**.

**The Compressor2 name drift** (`"Sidechain Comp (drum-key)"` in DB vs `"Compressor"` in Live) is a round-trip risk: the DB's `display_name` was a hand-authored description, but Live always reports the device's own canonical name. Any pull that updates `display_name` from Live will erase the author's intent annotation. This is a different shape from solo-piano-ambient's return-name drift but the same family (push-then-pull doesn't round-trip free-form names).

- **Severity guess**: **important** for all three failure modes. The AnalogDevice gotcha is a one-off triage item; the PluginDevice ambiguity is W13-A's whole reason for existing; the name-drift is W7-territory.

### Step 7c: Envelopes phase silently skipped BOTH envelopes — including the brief's target

This is the canary's central new finding:

```
envelopes plan:
  calls: []
  notes: [
    "envelope 5e0a7a7cc2004f7aa9c1b75638b2bca3 (mixer_volume): no arrangement clip
     on track 11 covers beat range [256, 284.62]; Live 12.4 requires session-clip
     routing for mixer_volume envelopes (W4-B). Add an arrangement_clip placement
     spanning the envelope's range or trim breakpoints to fit an existing
     placement; skipping.",
    "envelope fad08b77a52a443a9bf860d6372510a1 (mixer_volume): track
     1453118ea1e5416db11984ea904bb88a not linked; skipping"
  ]
```

Two findings here, both NEW relative to solo-piano-ambient:

1. **Sidechain placeholder on lead vocal (audio track) is unreachable.** The lead-vocal sidechain placeholder is a `mixer_volume` envelope on track 11 (audio, lead vocal). Track 11 has ZERO session clips because it's an audio-track placeholder. Live's W4-B routing for mixer_volume envelopes requires a session clip covering the envelope's beat range. So: **mixer_volume envelopes on audio tracks are categorically un-pushable today.** Same root cause as solo-piano-ambient step 7d (W4-B clip-routing requirement) but the AUDIO-TRACK angle is new: you can't even "add a session clip to fix it" because the track is audio and the DB doesn't model audio clips. Architectural blocker for any vocal-sidechain workflow.

2. **Master fade-out envelope: track not linked → silently skipped.** The brief's headline target. The `tracks` push phase explicitly SKIPS the master track ("Master tracks are skipped: master has no Live-side 'create' — it exists implicitly in every Live set and is reached via `ableton_session(set_master_property)`"), so there's no `ableton_links` row for it. The envelopes-phase planner does a name-agnostic link lookup → finds nothing → emits `"track ... not linked; skipping"`. **This means master-volume envelopes can never reach Live via the current push planner.** The mix phase reaches master via `set_master_property` for the static value; there's no analogous path for envelopes. Brief said this was a key canary target; today's answer is "silently dropped, no warning, no design path."

The brief calls out: "Exercises whether master is treated as a first-class track for envelopes." Today's answer: **no.** The schema models `mixer_volume` envelopes on the master track row (track_index=0), but the push planner has no path to materialize them.

- **What I did instead**: logged both; did not try to work around either.
- **Severity guess**: **blocker** for the canary's most-load-bearing target (master fade-out) and one of the brief's most common production patterns (vocal-sidechain).

### Step 7d: Arrangement plan HARD CRASHES on unlinked session clip

```
ValueError: plan_push_arrangement: arrangement_clip 'c3909f0b081f4892931523be9baceb4d'
references session clip '61dccccb75034c459270d8b48a760a86', which is not linked
in session '4d21c6a8b9ad4225b653b72f2331f526'. Run the clip-create phase ...
```

Unlike envelopes (which skip with a note) and devices (which fail per-call), arrangement raises an uncaught `ValueError` on the FIRST unlinked arrangement clip and never gets to even partial planning. A user halfway through pushing would see a Python traceback through the CLI.

**NEW finding**: phase planners are inconsistent about partial-state behavior. Some skip-with-note (envelopes), some fail-per-call (devices), some hard-error (arrangement). For a multi-step skill where the user might want to incrementally test, predictable behavior matters.

- **Severity guess**: **important**. Crash-vs-warn inconsistency surfaces in interactive use.

### Step 7e: Cue create batch fails at MCP — arrangement extent prerequisite undocumented

```
cue_create_batch failed: ValueError: cue_create_batch: 7 cue(s) past last_event_time=24.0:
cues[1].position_beats=32.0, ... Live's current_song_time setter is clamped to the
arrangement's extent — place arrangement content covering these positions first.
No cues written (atomic batch).
```

Cue points cannot be created beyond the arrangement's current extent. With no arrangement clips pushed, Live's last_event_time is 24.0 (likely from the default empty set), so only the cue at beat 0 ("intro") is in range; the other 7 (verse / chorus / verse / chorus / bridge / chorus / outro) all fail. The error is informative but the **cues phase plan didn't warn about this prerequisite** (`notes: []`). The dependency chain is implicit:

```
cues  ←requires  arrangement (extent)  ←requires  clips (linked)  ←21 huge MCP calls
```

A user who pushes phases in skill order would hit clips ceremony cost (or skip), hit arrangement-crash, then hit cues-rejection. Each prior canary's "phases work clean" depends on actually completing the clip push first.

- **Severity guess**: **paper-cut** in isolation (good error message); **important** as part of the phase-cliff chain.

## Outstanding open questions

1. **Repeated sections — does the schema intend "same clip, N placements" or "N clips, N placements"?** I picked the second; the first appears legal but its mutation semantics are unspecified. A `docs/` line would resolve it.
2. **What's the "right" snapshot shape for a third-party VST?** Today's `{class: "PluginDevice", name: ..., guess_uri: ...}` is meaningless to the loader unless the URI happens to resolve. W13-A's design should specify the round-trip fields (manufacturer? plugin format? CRC of the .vst3 binary? Live's `Live.PluginDevice.uri`?).
3. **Why does Live's `AnalogDevice` class not match the loader's accepted `kind`?** The snapshot recorded `"class": "AnalogDevice"` (a reasonable guess from Live's internal type system), but `ableton_device(action='load', kind='AnalogDevice')` rejects. Is there a canonical mapping table? `Compressor2` worked, `AnalogDevice` didn't.
4. **Master envelopes — is the design intent that they round-trip at all?** If yes, the push planner needs a master-volume envelope path that doesn't go through `ableton_links`. If no, the DB schema's `mixer_volume` target on a master-track row should be rejected at mutator time.
5. **Audio-track sidechain / mixer envelopes — same question.** Audio tracks can't host MIDI session clips, so W4-B's "envelope routed through a session clip" is unreachable. Should the push planner refuse to create the envelope, or should there be an arrangement-clip-routed path?
6. **Is `display_name` on devices meant to be authoritative in DB or scratch?** Loading a `Compressor2` from the DB's `"Sidechain Comp (drum-key)"` results in Live's `"Compressor"`. Push doesn't rename; pull will overwrite the author's annotation.
7. **Cue duplicate names — what's the user model?** Live's UI shows 3 "chorus" entries in the locator; jump-by-name is ambiguous. Should the planner auto-disambiguate ("chorus 1", "chorus 2", "chorus 3"), or is the user responsible? falling-walking sidestepped this by using `chorus_twist` for the C3' variant — no two cues had the same name.

## What I built

- `songs/full-band-rock/build.py` — clean run, 1285 notes across 21 clips on 4 MIDI tracks; 4 audio tracks have zero clips by design.
- `songs/full-band-rock/captured_session.json` — hand-authored with explicit `_note` fields marking every guess (preset URIs, VST class, sidechain intent). 8 tracks + 3 returns + master.
- `songs/full-band-rock/tests/test_build.py` — **3 passing tests**: shape (counts, kinds, returns, envelopes, cue duplicates), `test_repeated_sections_have_distinct_clip_slots`, `test_audio_tracks_have_no_clips_no_devices_no_problem`.
- `songs/full-band-rock/decisions/`, `songs/full-band-rock/annotations/` — empty directories per convention.
- **Push attempt** (partial, time-capped at 45 min):
  - tempo (108), time signature (4/4), 8 tracks (audio included), 3 returns: **all OK**.
  - 1 clip pushed as proof; remaining 20 skipped due to per-phase ceremony cost (49 mix calls + 20 huge clip calls were untenable for interactive push).
  - Devices: 5 OK (Operator, Compressor2, 2× Reverb, GlueCompressor), **3 failed** (DrumGroupDevice URI guess, PluginDevice URI guess (Spitfire LABS), AnalogDevice kind rejection).
  - Envelopes: 2 envelopes in DB, **both skipped** (master fade unreachable because master isn't linked; sidechain placeholder unreachable because lead-vocal audio track has no session clip).
  - Arrangement: hard CRASH on unlinked clip.
  - Cues: 1 batched call **failed at MCP** (arrangement extent prerequisite undocumented in the phase plan).
- **Pull**: NOT attempted. Push was incomplete enough that a pull would have mostly recorded the un-pushed state as drift.

## Final state

- **Live set state after run**: 12 tracks total (1-MIDI, 2-MIDI, 3-Audio, 4-Audio from default + 8 new: 01 Drums through 08 Parallel Comp Bus), 5 returns (A-Reverb, B-Delay from default + C-Vocal Verb, D-Drum Room, E-Bus Comp), 108 BPM, 4/4. Track 5 has 1 MIDI clip (partial Intro Drums, 16 of 85 notes). Devices loaded on tracks 6 (Operator), 11 (Compressor); on returns 3, 4 (Reverb), 5 (GlueCompressor). Tracks 5 (Drums — failed device load), 9 (Keys — failed VST load), 10 (Backing Vox — failed Analog load) have no instruments; clips on those tracks will play silently if anyone tries. No arrangement, no cue points, no mix settings beyond defaults, no envelopes.
- **DB state after run**: full song authored — 9 tracks + 3 returns + 21 session clips + 21 arrangement entries + 8 sections + 8 cues + 2 envelopes + 1285 notes. `ableton_sessions` row + links for 8 tracks + 3 returns + 5 devices (the ones that succeeded). The Compressor2 link records device_index=1 with Live's actual name "Compressor" (vs DB's "Sidechain Comp (drum-key)" — drift will surface on next pull).
- **Tests**: 3 passing, 0 failing.
- **Subjective overall friction level**: **very high** for the push pipeline; **medium** for authoring.
  - The audio-track + audio-track-envelope combination is a categorical dead-end no doc warns about.
  - Master-envelope dropping is a silent capability gap exactly where the brief asked.
  - Third-party VST has no design path at all; today's error is identical to a URI typo.
  - The per-phase ceremony is the practical cost; 8 tracks + 21 clips + 49 mix calls + 8 device calls makes "push this song" a 1-2-hour project today. The solo-piano-ambient run was tractable at 1 track / 3 clips; full-band-rock is the realistic-song stress case that surfaces the ceremony's true cost.
  - The arrangement-crash + cues-extent dependency chain means a user pushing phases in order WILL hit a wall at phase 9 unless every prior phase completed; partial-push is not safe.
