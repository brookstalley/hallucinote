# Runbook — solo-piano-ambient

> **Historical session log.** Filenames and paths reflect the state at
> session time (2026-05-19). Per-song bootstrap test files are now
> named `test_<slug>_build.py` (post-Arc-6 convention); references
> below to `tests/test_build.py` reflect the older bare-name pattern
> the run used.

**Agent run start**: 2026-05-19 11:53 PT (session begin)
**Agent run end**: 2026-05-19 12:05 PT (~12 min wall clock)
**Live state at start**: 4 tracks / 2 returns / 8 scenes / 120 BPM (default new set, Live 12.4 via MCP bridge)
**Agent**: fresh-context Wave 0 canary, posing as a moderately sophisticated user.

## Friction Log

### Step 1: Scaffold `songs/solo-piano-ambient/`

- **Goal**: create `build.py`, `captured_session.json`, `tests/test_build.py`, `decisions/`, `annotations/` for a new song from a brief.
- **Command/skill invoked**: none — no `/new-song` skill exists.
- **What happened**: I had to hand-create every file and directory. To know the canonical shape I had to read `songs/falling-walking/` end-to-end, including the `falling-walking.md` overview which **explicitly says it's historical, not a template**. The README's "Compose a new song from a prompt" section promises "Claude scaffolds `songs/punk-fate/`" but offers no concrete guidance on what gets scaffolded, what imports to use, what the snapshot format is, or how the score-half vs mix-half split works in `build()`.
- **What was missing or confusing**:
  - No `/new-song` skill, no scaffolding template, no `docs/song-bootstrap.md` or equivalent.
  - The only complete worked example (`falling-walking`) is large (~860 lines of build.py) and song-specific. There's no minimal "hello-world" song to copy from.
  - `falling-walking.md` warns at the top that it's "historical, not a template" but is the only model available — so the canonical user move IS copying from it, against the doc's stated wishes.
  - The README claim ("Claude scaffolds ... writes a `build.py` against the library's generators") is aspirational; in practice the agent has to derive the entire scaffold by reverse-engineering the example.
- **What I did instead**: Hand-created the directory tree, copied the structure of `falling-walking/build.py` aggressively (the top imports, the `_apply_envelopes` helper verbatim, the `_arrange_section` helper verbatim, the section-builder pattern, the `build()` / `report()` / `__main__` shape). Logged each copy in code comments.
- **Severity guess**: **important** — the "compose a new song from a prompt" path is the headline feature; today it requires the agent to do a lot of reverse-engineering before writing the first useful line of song-specific code. A scaffold skill or even a `docs/song-bootstrap.md` would compress this from ~15 min to ~2 min.

### Step 2: Hand-author `captured_session.json`

- **Goal**: produce a snapshot representing the target session shape (1 piano MIDI + 2 returns + master) so the score-half of `build.py` has something to replay against.
- **Command/skill invoked**: none — there is no skill or CLI for "snapshot the target shape before the song exists in Live."
- **What happened**: I read `hallucinote/capture.py` to understand the snapshot schema, then hand-wrote a `captured_session.json` mirroring falling-walking's shape. The canonical capture path (`compile_snapshot` + a sequence of `ableton_*` probes) expects a real Ableton set ALREADY populated with the target tracks/returns. But this is a brand-new song — there IS no Live set to capture from yet.
- **What was missing or confusing**: This is the chicken-and-egg the brief calls out:
  - `hallucinote.capture` (docstring) says "capture once (live Ableton -> snapshot.json), then replay into the DB through mutators". Fine for a song you've prototyped manually in Live.
  - For a new song authored from a prompt, there's no source Live state to capture. The agent must hand-author a snapshot describing the *intended* session shape, then `replay_capture` materializes it in the DB, then push materializes it in Live.
  - There's no documentation that this is the prescribed pattern. The only hint is that falling-walking's `captured_session.json` exists alongside its `build.py` and is the seed for the score-half.
  - No JSON Schema for the snapshot — schema is documented only as a module docstring in `capture.py`.
- **What I did instead**: Wrote the file by hand, mirroring falling-walking's shape but dramatically smaller (1 track, 2 returns, master). Added a `_note` field at the top explaining it was hand-authored.
- **Severity guess**: **important**. Same "no path for new songs" problem as Step 1 from a different angle.

### Step 3: `replay_capture` strips Live's `[A-Z]-` slot prefix more aggressively than expected

- **Goal**: look up the reverb return by name in the DB after `replay_capture` ran.
- **Command/skill invoked**: `returns["A-Reverb"]` in build.py.
- **What happened**: `KeyError: 'A-Reverb'`. After investigating, the DB row was stored under the name `Reverb` (the `A-` prefix had been stripped by `capture.strip_return_slot_prefix`). The snapshot field reads `"A-Reverb"` but the DB row reads `"Reverb"`.
- **What was missing or confusing**:
  - `_RETURN_SLOT_PREFIX = re.compile(r"^[A-Z]-")` strips ANY single uppercase-letter + dash prefix on the way into the DB, not just the literal `A-` / `B-` Live emits.
  - There is no docstring warning on `captured_session.json`'s shape that says "return names lose their slot prefix during replay." The W4-C convention (DB stores stripped, Live re-adds the prefix on push) is documented inside `capture.py` but invisible to an author who just looks at the example snapshot.
  - The behavior matters for downstream lookups by name (envelope authoring, send-level mutations, anything that takes a `target_send_return_id` keyed by name).
- **What I did instead**: Added a comment in build.py noting the gotcha and looked up the return as `returns["Reverb"]`. The corresponding test assertion documents this (`assert return_names == ["Delay", "Reverb"]`).
- **Severity guess**: **paper-cut** for someone who finds the comment; **important** if you don't and silently lose the lookup. Documenting this on `captured_session.json`'s schema would be a one-line fix.

### Step 4: Tests file — `falling-walking/tests/test_build.py` is the only model

- **Goal**: write shape assertions mirroring falling-walking's pattern.
- **Command/skill invoked**: copied `songs/falling-walking/tests/test_build.py` shape, adapted assertions.
- **What happened**: Straightforward. Patterns transfer cleanly. Two tests written: `test_build_runs_clean_and_produces_canary_shape` (counts + presence + envelope spans) and `test_bloom_has_overlapping_chord_voicings` (intentional overlap detection).
- **What was missing or confusing**: Nothing — the falling-walking test file is a good model. But again, no template — copy-paste from a song that says "historical, not a template."
- **What I did instead**: Successful copy.
- **Severity guess**: **paper-cut**. Same scaffold-skill complaint as Step 1.

### Step 5: `python3 songs/solo-piano-ambient/build.py --reset`

- **Goal**: build the DB end-to-end.
- **Command/skill invoked**: `python3 songs/solo-piano-ambient/build.py --reset`.
- **What happened**: First run crashed with the `KeyError: 'A-Reverb'` (Step 3). After fixing the lookup, clean run. Final report:
  ```
  song_id=ec3541c86607488191102faa1c908f3a, timing_mode=native, tracks=2
    track  0  Master           (master, 0 clips)
    track  1  01 Piano         (midi, 3 clips)
        slot 1  Prelude            32.0bt     5 notes
        slot 2  Bloom              96.0bt    31 notes
        slot 3  Recede             64.0bt    12 notes
  total notes: 48
  sections: ['prelude', 'bloom', 'recede', 'silence']
  arrangement entries: 3
  envelopes: 2
    mixer_volume   2 breakpoints
    send_level     9 breakpoints
  ```
- **What was missing or confusing**: nothing once Step 3 was understood.
- **Severity guess**: clean.

### Step 6: `pytest songs/solo-piano-ambient/tests/ -v`

- **Goal**: verify shape assertions pass.
- **Command/skill invoked**: `pytest songs/solo-piano-ambient/tests/ -v`.
- **What happened**: 1 fail, 1 pass on first run — the failing assertion was `assert return_names == ["A-Reverb", "B-Delay"]` (my author-side wrong assumption, same root cause as Step 3). Updated the assertion to the actual stripped names (`["Delay", "Reverb"]`) per the no-fix discipline (the test now documents the real DB state). 2/2 pass after that.
- **What was missing or confusing**: nothing — the test was correctly catching my misunderstanding. Working as intended.
- **Severity guess**: clean.

### Step 7: Push to Live — chicken-and-egg with `ableton_sessions`

- **Goal**: push the DB into the running default Live set.
- **Command/skill invoked**: followed `/ableton-push` skill conventions manually.
- **What happened**: The skill requires `<session_id>` (the `ableton_sessions.id` row) as a required arg and explicitly refuses to invent one. The skill says "If the user hasn't created one, they should do so via `M.create_ableton_session(conn, song_id=..., name=\"...\")` first." There is no skill, no CLI subcommand, no MCP prompt, and no flag on `push_cli` to create an `ableton_sessions` row. I had to drop into Python by hand:
  ```python
  from hallucinote.db import init_db, mutations as M, queries as Q
  conn = init_db(Path('songs/solo-piano-ambient/solo-piano-ambient.db'))
  song = Q.get_song_by_name(conn, 'solo-piano-ambient')
  sid = M.create_ableton_session(conn, song_id=song['id'], name='canary-w0-push')
  conn.commit()
  ```
- **What was missing or confusing**:
  - No `/new-song` skill, no `/bind-song-to-live` skill, no `push_cli create-session` subcommand, no `--auto-session` flag.
  - No MCP `start_new_song` prompt (the brief calls this out explicitly — confirmed gap).
  - For a first-time user this is a HARD wall: the push skill's argument-hint is `<song-slug> <session_id>` and the doc says "ask the user — never guess." So the user is stuck unless they read source code.
  - This is the friction the brief was designed to expose, and it landed exactly as expected.
- **What I did instead**: Hand-ran a Python one-liner to create the session row, then proceeded with push.
- **Severity guess**: **blocker** for a fresh user. The push skill is unrunnable without prior knowledge of the `ableton_sessions` table.

### Step 7b: Push phases ran cleanly (one device load failure)

- **Goal**: drive all 10 phases (tempo / signature / tracks / returns / clips / mix / devices / envelopes / arrangement / cues).
- **Command/skill invoked**: `python3 -m hallucinote.sync.push_cli` for plan/apply, MCP `mcp__hallucinote-mcp__ableton_*` for execute. Followed the skill's strict phase-order discipline (plan one phase → execute via MCP → apply → next phase).
- **What happened**: 9 of 10 phases ran clean. Per-phase summary:
  - **tempo_map**: 1 call, 1 applied (BPM 60). OK.
  - **time_signature_map**: 1 call, 1 applied (4/4). OK.
  - **tracks**: 1 call (`create '01 Piano' midi`), 1 applied → Live's track 5. OK.
  - **returns**: 0 calls (already linked by probe-and-link). OK.
  - **clips**: 3 calls (Prelude/Bloom/Recede atomic create+notes), 3 applied. OK.
  - **mix**: 10 calls (master vol/pan, piano vol/pan, both return vol/pan, both sends), 10 applied. OK.
  - **devices**: 3 calls; 2 applied, 1 failed — see Step 7c below.
  - **envelopes**: 1 call applied (piano volume swell on bloom session clip), 1 envelope SKIPPED by the planner with a warning — see Step 7d below.
  - **arrangement**: 3 calls (`duplicate_to_arrangement` for each session clip), 3 applied. OK.
  - **cues**: 1 batched call (4 cues), 1 applied. OK.
- **What was missing or confusing**:
  - Each phase requires THREE shell invocations (plan → execute many MCP calls → apply) PLUS hand-marshalling a results.json with the exact key from the plan plus the MCP response. This is heavy ceremony for an interactive session — the skill is designed for the agent to be a stitcher between the CLI and MCP, but the cost is high. I had to assemble ~10 results JSON blobs by hand. A `push_cli execute` subcommand that took the plan + an MCP callback would dramatically reduce per-step overhead.
  - The `notes` field on each phase plan is genuinely useful — the envelopes phase's note clearly explained why the send_level envelope was skipped.
- **Severity guess**: **important** — the per-phase ceremony is the dominant cost of running push; a "run-all" or "stream-results" wrapper would help.

### Step 7c: Device load failed — hand-authored `guess_uri` doesn't resolve

- **Goal**: load Live's stock Grand Piano Instrument Rack onto track 5.
- **Command/skill invoked**: `ableton_device(action='load', track_index=5, kind='InstrumentGroupDevice', preset_uri='query:Piano#GrandPiano')`.
- **What happened**: `{"ok": false, "error": "no loadable browser item found for preset_uri='query:Piano#GrandPiano'"}`. The hand-authored `guess_uri` in `captured_session.json` was made up — falling-walking's snapshot has values like `"query:Drums#FileId_5418"` that look opaque but presumably came from a real Live capture. Without running a browser probe, the author has no way to know what URI to put in the snapshot.
- **What was missing or confusing**:
  - There's no convention or example for "user wants stock Grand Piano on this track" — the canonical path apparently requires `ableton_browser(action='tree', ...)` or `ableton_browser(action='at_path', ...)` to find a `preset_uri` first.
  - The error message DID point at the recovery (`verify via ableton_browser(action='tree', ...) or pass preset_uri from ableton_browser(action='at_path', ...)`), which is excellent. But the author-side experience is: you're writing build.py, you want a piano, you have to round-trip through a probe to find an identifier the snapshot can carry.
  - For a song authored from a brief that specifies "Live's stock Grand Piano Instrument Rack (Core Library, ships with Live)" — there's no abstraction higher than the raw `preset_uri`.
- **What I did instead**: Logged it, accepted the failure (`apply: 2 applied, 1 failed`), and continued. The piano track has no instrument; clip playback in Live will be silent. The track exists, MIDI clips are populated, mixer state is correct — only the actual sound is missing.
- **Severity guess**: **important** — for any song authored without a prior Live capture, instrument loading is going to fail this way. A higher-level "load named factory device" affordance or a documented browser-probe-first workflow would help.

### Step 7d: Long send-level envelope SKIPPED — spans multiple session clips

- **Goal**: write the long reverb send envelope (the main canary target — ramps across bloom + recede, ~160 beats / 40 bars).
- **Command/skill invoked**: `python3 -m hallucinote.sync.push_cli plan envelopes ...`.
- **What happened**: The planner emitted ONE call (the volume swell, which sits entirely inside the bloom session clip), and SKIPPED the send-level reverb envelope with this note:
  ```
  envelope 3e518bbe... (send_level): no arrangement clip on track 5 covers beat range [32, 192];
  Live 12.4 requires session-clip routing for send_level envelopes (W4-B). Add an arrangement_clip
  placement spanning the envelope's range or trim breakpoints to fit an existing placement; skipping.
  ```
- **What was missing or confusing**: This is the central canary finding.
  - **The brief explicitly targets long envelopes** ("envelopes whose breakpoint lists span entire sections (~96+ bars of beats)"). The push pipeline cannot accept them as authored — they must fit inside a single session clip's beat range.
  - The phase order is `envelopes` BEFORE `arrangement` (per W4-A: `duplicate_to_arrangement` snapshots session-clip envelopes). So even if I tried to route the envelope through arrangement-clip routing, the arrangement clips don't exist when the envelopes phase runs.
  - The skill suggestion ("Add an arrangement_clip placement spanning the envelope's range or trim breakpoints to fit an existing placement") is itself contradictory: you can't add an arrangement_clip placement at this stage of push, and trimming breakpoints destroys the canary's intent.
  - This is an architectural gap, not a usage error. The author cannot satisfy the brief.
- **What I did instead**: Did not fix; logged. The DB still carries the full envelope with 9 breakpoints spanning [32, 192]; Live just doesn't reflect it.
- **Severity guess**: **blocker** for the canary's main goal. The whole point of this canary was to exercise long-envelope authoring; the push path cannot ship a multi-section-spanning send-level envelope today.

### Step 7e: `arrangement` phase plan warns the agent must manually clear Live's arrangement

- **Goal**: write arrangement clips for prelude / bloom / recede.
- **Command/skill invoked**: `push_cli plan arrangement`.
- **What happened**: Plan included this note: `"agent must clear existing arrangement clips on the involved tracks before running these duplicates (planner emits no pre-clear ops because it has no DB knowledge of Live's current arrangement state)"`. Fresh Live set, so the arrangement was empty and no clearing was needed.
- **What was missing or confusing**: The note's mitigation isn't explained — no MCP `ableton_arrangement(action='clear_track')` was suggested. The agent is left to figure out the clearing path. (I sidestepped it by relying on the fresh-state assumption.) For idempotent re-push or partial re-push, this is a latent footgun.
- **What I did instead**: Trusted the fresh-state assumption. Continued. Push succeeded.
- **Severity guess**: **paper-cut** for a fresh set; **important** for any re-push workflow.

### Step 8: Pull round-trip — return names drifted

- **Goal**: do a `mix-state` pull and verify the DB still matches the pushed state.
- **Command/skill invoked**: `python3 -m hallucinote.sync.pull_cli plan mix-state ...`, executed 6 MCP probes, ran `pull_cli apply`.
- **What happened**: `3 mutations, 7 no-ops, 0 skipped, 0 warnings`. Mutations applied:
  ```
  return 'Reverb' name: 'Reverb' -> 'Reverb | Reverb'
  return 'Delay'  name: 'Delay'  -> 'Delay | Delay'
  (plus mute/solo/color initialization, which were None in the DB and false/<color> in Live)
  ```
- **What was missing or confusing**: **This is the round-trip integrity finding.**
  - The push loaded a Reverb device onto Return 1 (`ableton_device(action='load', return_index=1, kind='Reverb')`) — but Return 1 in the default Live set already had a Reverb device. Loading appended a second one.
  - Live's return-name auto-generation appears to derive the return name from the chain's device names: with two Reverbs in the chain, the return name became `"A-Reverb | Reverb"`.
  - On pull, `strip_return_slot_prefix` peeled off the `A-` prefix, yielding `"Reverb | Reverb"`, which then OVERWROTE the DB's clean `"Reverb"` name.
  - Round-trip parity broken on return names after push-then-pull.
  - The deeper issue: push is documented as additive (per the skill: "Push does not delete Live state that isn't in the DB"). But it's additive on top of a return that ALREADY has the same-class device pre-populated. There's no detection or warning for "this Reverb load duplicates an existing one" — the devices phase planner doesn't probe Live's chain before emitting.
  - A user following the documented workflow (default Live set + `/ableton-push`) will silently duplicate any pre-existing default-set return devices.
- **What I did instead**: Logged the drift. Did not push again. The DB now reflects the round-trip-corrupted name; the original `Reverb` / `Delay` names are gone.
- **Severity guess**: **important** — round-trip name corruption is exactly the W7 wave's stated focus.

## Outstanding open questions

1. **What is the canonical workflow for "new song from a brief"?** README claims Claude scaffolds the directory; in practice the agent has to copy from an example that warns "not a template." Is there a `/new-song` skill on the roadmap? If so, this canary should be re-run with it.
2. **How should the agent pick an `instrument_uri` / `preset_uri` for stock Live devices without first probing the browser?** Is there a published catalogue of canonical URIs for common Live factory presets (Grand Piano, default Operator, etc.)? Or is the prescribed flow always "probe first, snapshot second"?
3. **What's the long-envelope-across-sections plan?** W6/W7 supposedly target long envelopes, but the push planner today refuses anything that doesn't fit in one session clip's beat range. Is the model that you must factor long envelopes into per-section sub-envelopes? Or is there an arrangement-clip-routed automation path planned for a later wave?
4. **Should `replay_capture` warn when a return name would change after slot-prefix stripping?** The transform is silent today. A one-line "stripped 'A-' from 'A-Reverb' -> 'Reverb'" log entry would have saved me ~5 min.
5. **Is there a way to bind a song to a Live set without dropping into Python?** The push skill explicitly refuses to invent a session, but offers no alternative path other than calling the mutator directly.
6. **Should the devices phase planner probe Live's existing chain before emitting `load`?** Today it doesn't, which is how the Reverb-on-Reverb duplication happened. A "device already present at position N with matching kind; skipping" check would solve the round-trip drift in Step 8.

## What I built

- `songs/solo-piano-ambient/build.py` — **clean run** after fixing the `A-Reverb` -> `Reverb` lookup. 48 total notes across 3 clips (Prelude 5, Bloom 31, Recede 12). Silence section is empty by design.
- `songs/solo-piano-ambient/captured_session.json` — hand-authored, 1 track + 2 returns + master. Validated by build.py round-trip.
- `songs/solo-piano-ambient/tests/test_build.py` — **2 passing tests**: `test_build_runs_clean_and_produces_canary_shape` (shape assertions) and `test_bloom_has_overlapping_chord_voicings` (overlap detection).
- `songs/solo-piano-ambient/decisions/` — empty dir created (per song-conventions, but no decisions yet).
- `songs/solo-piano-ambient/annotations/` — empty dir created.
- **Push attempt**: 10/10 phases executed; 9 fully clean, 1 partial:
  - Track + clips + mix + arrangement + cues + tempo + signature + return Reverb device + return Delay device → all OK.
  - Piano instrument load **failed** (made-up `preset_uri='query:Piano#GrandPiano'`). Track will play silently in Live.
  - Long send-level reverb envelope **skipped by the planner** because it spans bloom + recede (the central canary target).
  - Volume swell envelope on bloom: pushed OK.
- **Pull round-trip**: ran `mix-state` domain only. Round-trip succeeded but introduced **return-name drift** (`Reverb` → `Reverb | Reverb`, `Delay` → `Delay | Delay`) caused by the additive device load + slot-prefix-strip interaction.

## Final state

- **Live set state after run**: 5 tracks (1-MIDI, 2-MIDI, 3-Audio, 4-Audio, 01 Piano), 2 returns (A-Reverb | Reverb, B-Delay | Delay — second word added by the duplicated device load), 8 scenes, 60 BPM, 4/4. Arrangement view has 3 clips on track 5 (Prelude bar 1, Bloom bar 9, Recede bar 33), no clips in bars 49-57 (silence). 4 cue points at section boundaries. Piano track has NO instrument loaded — clip playback will be silent. Returns each have TWO devices (original Reverb/Delay + a second one loaded by push).
- **DB state after run**: `songs/solo-piano-ambient/solo-piano-ambient.db` exists, has 1 song row, 2 tracks (Master + Piano), 2 returns, 3 clips, 3 arrangement entries, 4 sections, 4 cues, 2 envelopes (1 reverb send + 1 volume swell), 48 notes. After pull, return names are corrupted to `Reverb | Reverb` and `Delay | Delay`.
- **Tests**: 2 passing, 0 failing.
- **Subjective overall friction level**: **high**. Specifically:
  - The "new song from a brief" path is full of cliffs (no scaffold, no schema docs, no session-binding helper).
  - The push pipeline works but has heavy per-phase ceremony.
  - The central canary target (long envelope spanning sections) is blocked by an architectural limitation that no doc warns about.
  - Round-trip drift on return names is a quality issue exactly in the W7 wave's lane.
  - The 4 default Live tracks (1-MIDI through 4-Audio) are stranded — push is additive and ignored them, so the user is left with clutter the workflow doesn't address.
