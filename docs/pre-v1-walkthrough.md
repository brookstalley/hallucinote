# Pre-v1 User Walkthrough — Creating and Working on a New Song

**Goal of this doc.** Mentally walk a realistic user — let's call her Maya — through the full arc of arriving at the repo, installing Hallucinote, composing a new song, iterating on it, pushing/pulling against Live, branching it, and coming back the next day. Identify gaps, friction points, and places we can't actually do what we promise.

**Method.** Live is not running for this exercise. Everything below is reasoned from the code, the skills, the prompts/resources, the README, VISION, and the project preferences. Where a step would succeed today, that's stated. Where it would stumble, snag, or quietly fail, that's flagged with **FINDING**.

**Audience.** The team prepping the v1 release.

---

## 0. The user before they arrive

Maya is a musician who has heard "Claude can build songs in Ableton against this Hallucinote thing." She:

- has Ableton Live 12.x installed,
- has Python (some version) on her Mac,
- has Claude Code installed,
- has never used MCP before, may or may not know what `pip` is,
- read the README's tagline ("describe musical intent in plain language") and is excited,
- has not read VISION.md, mcp-tool-design.md, or terminology.md, and isn't going to.

The product personality from VISION.md is "composers anywhere on the spectrum — hobbyist with no theory, working producer, thirty-year veteran." Maya is at the producer end but not technical.

---

## 1. First-time install

### 1.1 Cloning and installing

README §1 says:

```bash
git clone https://github.com/brookstalley/hallucinote.git
cd hallucinote
python -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]' -e 'hallucinote_mcp[dev]'
```

This works on macOS for anyone who already has `python3` and pip. But:

- **FINDING (friction, low):** Maya doesn't know what `[dev]` means or why she needs the dev extras to *use* the tool. The README briefly says "the installs aren't optional even when driving from Claude Code." A first-time user reads that and thinks "I'm not developing this, why?" — the explanation is true but doesn't land.
- **FINDING (friction, medium):** No explicit Python 3.11+ check at install time. `pyproject.toml` declares 3.10+; project-preferences notes 3.12 locally. If Maya is on system Python 3.9 (still common on stock macOS), `pip install -e` will fail with a confusing dependency error rather than a clear "you need Python 3.11+." A pre-flight check (in install skill or a `python -m hallucinote_mcp.cli doctor`) would catch this.
- **FINDING (gap, low):** Windows users get no install guidance. The install skill body has robocopy paths and OneDrive handling — clearly someone thought about Windows — but the README's quick start is mac-only (`python -m venv .venv && source .venv/bin/activate`). A Windows user clones and immediately gets stuck.
- **FINDING (gap, low):** Linux is mentioned in passing in the install skill but `hallucinote_mcp.install_paths` only enumerates User Library candidates for darwin and win32. A Linux user running the install skill will fail at "choose User Library" with no candidates.

### 1.2 Installing the Remote Script + MCP entry

README §2: quit Ableton, run `/ableton-mcp-install` from Claude Code.

This skill is unusually thorough — preflight detection, Live-version targeting, OneDrive redirection, atomic config write, version-handshake debugging guide. The orchestration is sound.

What it does NOT yet handle well:

- **FINDING (friction, medium):** The skill assumes Maya is in the cloned repo when she runs Claude Code. The preflight report uses `cwd` to find `.mcp.json`. If she opens Claude Code from her home directory and then `cd`s into the repo via tool calls, things will look strange. The skill body says "Run preflight **from the project directory**" — which is correct guidance, but invisible to the user; only Claude sees that. If Maya started `claude` from `~`, Claude *should* notice and prompt her to restart there. There's no explicit handling of this case in the skill.
- **FINDING (friction, low):** The skill prints a verbatim closing message including "try: `ableton_session(action='help')`" — but Maya can't type MCP calls. She types English. README §2 gets this right ("call ableton_session with action=info") but the install skill's final message instructs the user in a syntax they don't speak. Minor inconsistency.
- **FINDING (gap, medium):** The install skill explains the "one Ableton click" (Preferences → Link, Tempo & MIDI → Control Surface). For a user who has never touched that screen, this is opaque — there are three columns (Control Surface, Input, Output), it's not obvious which dropdown matters, and "leave Input/Output as None" is easy to misread as "don't touch anything." A screenshot or annotated description in the README would lower the failure rate dramatically.

### 1.3 Restarting Claude Code

README: "Quit and reopen Claude Code in this repo so it picks up the new `.mcp.json`."

- **FINDING (friction, low):** Maya is in Claude Code right now, talking to Claude. She has to quit the conversation she's actively having, restart, and re-establish context. We could mention this BEFORE running the install skill so she's not surprised. Bonus: the install skill could capture state to `.prawduct/.session-handoff.md` so the new session knows "you just installed; verify the bridge."

### 1.4 The verification call

> *"call ableton_session with action=info"*

Assuming everything worked, this returns tempo, signature, transport state, master mixer, track/return/scene counts. Maya sees JSON-ish numbers and either thinks "great, it works" or "ok, now what?"

- **FINDING (UX, medium):** There is no "you're set up; here are the three things to try next" hand-off. The MCP getting-started guide (`ableton://guides/getting-started`) is great context for Claude — but the user doesn't see it. A scripted post-install message ("Try: 'load falling-walking into Live', or 'let's start a new song called X'") would close the loop.

---

## 2. Loading the example song

### 2.1 The happy path

README §3: open Live (with Hallucinote selected as Control Surface), open Claude Code in the repo, say:

> *"load falling-walking into Live"*

Today, this works — IF Maya happens to have a fresh empty Live set open. Claude:

1. Runs `songs/falling-walking/build.py --reset` to (re)materialize the DB.
2. Probes Live via MCP (`ableton_track(action='list')`, `ableton_return(action='list')`).
3. Calls `python3 -m hallucinote.sync.push_cli probe-and-link <session_id> ...` to bind DB↔Live.
4. Iterates the ten phases (tempo → signature → tracks → returns → clips → mix → devices → envelopes → arrangement → cues), calling MCP for each phase's plan calls.
5. Reports counts.

When it finishes, Maya has the full song in Live's Arrangement View.

### 2.2 What's missing for "load falling-walking"

- **FINDING (gap, high):** **There is no `session_id`. The push skill requires one and refuses to invent it** (per its SKILL.md: "If the user hasn't created one, they should do so via `M.create_ableton_session(conn, song_id=..., name='...')` first; refuse to invent one"). Claude has to either (a) call `init_db` + `M.create_ableton_session` itself before running push, or (b) check if one already exists for this song. The skill doesn't tell Claude how to bootstrap this — it punts to "ask the user." Maya doesn't know what an `ableton_sessions.id` is.

  In practice, Claude will improvise: open the DB, query for a session, create one if missing, then proceed. This works but it's reinvented every time, undocumented as a workflow, and the skill explicitly says "refuse to invent one." There's a contradiction between the skill's strictness and what's actually needed for first-time use.

  **Fix sketch:** either a `/ableton-push` arg `--auto-session` that creates one if absent, or a separate `/song-bind` skill that pairs a DB with the currently-open Live set.

- **FINDING (UX, medium):** "Open Live with Hallucinote selected as Control Surface" is one-time setup. But "open Live with a fresh Live set" is a step Maya has to remember every time she wants to push from scratch. The push skill itself says "Push is additive: it does not delete Live state that isn't in the DB." If Maya pushes falling-walking into a Live set that already has six tracks from yesterday's experiment, she gets a Frankenstein. There's no warn-on-non-empty-set guard in the push skill — or even a message about it post-push.

- **FINDING (UX, medium):** The user has zero feedback during the push beyond "I'm pushing." Push touches ten phases, each emits N calls, each call goes through MCP. For falling-walking it's hundreds of calls. Claude *can* report per-phase ("clips: 32 calls, 32 applied, 0 failed") but the skill's "concisely" guidance often compresses that into one line. A progress indicator ("phase 5/10: clips") would help.

- **FINDING (UX quirk, medium — documented but unsolved):** Per the push skill's bottom note, after push Maya may see TWO weird things in Live:
  1. Tracks without devices show no mixer column.
  2. Envelopes written to MIDI clips don't appear in the per-clip envelope dropdown until she right-clicks the relevant mixer slider and chooses "Show Modulation."

  Both are Live 12.4 UX defaults, not Hallucinote bugs. But Maya doesn't know that, and her first reaction will be "the push didn't work / faders are missing / the swell isn't there." Claude should proactively flag these AFTER push, not only when she asks. Easy fix: end-of-push message that lists the two quirks.

### 2.3 Failure modes Maya will actually hit

- The `.mcp.json` has `"command": "hallucinote-mcp"` but Maya's venv isn't activated when she launches Claude Code. The MCP server fails to start; she sees "hallucinote-mcp tools unavailable." Nothing in Claude's response tells her to source the venv first.
- Live is running but she forgot the Control Surface dropdown step. The MCP server starts but `ableton_session(action='info')` returns a connection error. The error message *does* point at the Control Surface step (per the install skill), but only if the user asks Claude to debug it.
- She did the install correctly, but Live's Log.txt has a stale Python error from a previous attempt — Live caches the failed Control Surface and refuses to reload. Recovery is "fully quit Live and reopen." Not in the README's troubleshooting (there is no troubleshooting section).

**FINDING (gap, medium):** **README has no troubleshooting section.** Every install will go sideways for *someone*; centralizing common failures + recovery would save a lot of "I gave up after 20 minutes" exits.

---

## 3. Composing a new song from a prompt

This is the heart of the bet. README §3.2 promises:

> *"Let's make a 2-minute punk rock song that condenses the chord progressions of Beethoven's 5th into those 2 minutes. Four parts: drums, bass, lead guitar, and vocals on synth pad. Make the vocal melody consistent with the harmonic structure. Make the whole thing super punk. Call it punk-fate."*

> Claude scaffolds `songs/punk-fate/`, writes a `build.py` against the library's generators, builds `punk-fate.db`, and pushes the result into Live.

Let's walk through what actually happens.

### 3.1 Scaffolding the song directory

There is **no song scaffolding skill or template**. Claude is expected to create `songs/punk-fate/` from scratch, infer the conventions by looking at `songs/falling-walking/`, and produce:

- `songs/punk-fate/build.py` — a hand-authored Python file following falling-walking's structure
- `songs/punk-fate/captured_session.json` — a snapshot of the Live set's mix layout
- `songs/punk-fate/punk-fate.db` — the SQLite DB (gitignored, built by `build.py`)
- (optionally) `songs/punk-fate/tests/` — song-specific tests

Note: falling-walking has a sidecar `falling-walking.md` (concept doc — key/tempo/harmony/groove tables). That file pre-dates the annotations-in-DB direction the team is now planning. **A new song should not mirror it.** Composer intent ("verse seeks; chorus finds," "don't sidechain the bass on the bridge") is the home turf of the planned `annotations` table (HIGH PRIORITY backlog) — same data the .md held, but addressable by song / track / time range, queryable, and round-trippable. Until annotations land, intent is homeless either way; mirroring the .md would just create a doc-rot vector. (See §3.5.)

- **FINDING (gap, high):** **No scaffolding command/skill. `/song-new <slug>` does not exist.** *(Resolved in W9-A — the `/song-new` skill now scaffolds songs/<slug>/ with build.py, synthetic captured_session.json, tests, decisions/, annotations/. Originally specced as `/new-song`; renamed to `/song-new` in v0.9 for naming-convention consistency.)* Claude has to (a) reverse-engineer the convention from falling-walking each time, (b) hand-write a build.py from scratch, (c) decide what to put in `captured_session.json`, (d) decide whether to also fabricate a `falling-walking.md`-shaped sidecar (and the answer should be "no" — see the note above — but Claude can't know that from looking at the example). Failure modes:
  1. Claude misses a convention (e.g., the 1-based bar CHECK constraint, or the `slug` regex, or the `songs.title` vs `songs.name` split). The build fails at a CHECK constraint with a SQL error.
  2. Claude reproduces falling-walking's structure but with subtle drift (different section names, slightly different envelope authoring pattern). The next session sees inconsistency.
  3. Claude doesn't know whether `captured_session.json` should be filled in from a real Live set or fabricated. Falling-walking's snapshot was captured from a real Ableton session — for a brand-new song, there is no such session yet.
  4. Claude copies the falling-walking.md pattern out of "imitation is the safest default," producing a sidecar that the team has already decided is the wrong shape. Until the example has been refactored to NOT carry a concept .md, the example actively misleads.

  **The captured_session.json question is genuinely unanswered:** if the song doesn't exist yet, what do we capture? The chicken-and-egg problem is real. Options:
  - (a) Maya creates an empty Live set with the tracks/returns she wants, captures it, *then* composes against it.
  - (b) Claude fabricates a snapshot from a template (12 tracks, A-Reverb, B-Delay, no devices) and pushes; Maya then loads instruments manually in Live and re-pulls.
  - (c) Some other path.

  Today the codebase has neither a template snapshot nor a "compose against an empty set" path. Falling-walking is the only data point. **This is the single biggest gap blocking the README's promise.**

### 3.1.5 Falling-walking as a misleading exemplar

falling-walking's `falling-walking.md` is a thorough musical brief — keys, tempo, harmony tables, rhythmic feel per section, *why* the sections pair. It's a useful artifact for understanding the song, and it pre-dates the planned `annotations` table.

The forward-looking shape, per the HIGH PRIORITY annotations backlog item, is that all of that lives in the DB: song-scoped annotations ("D minor / 132 BPM / aesthetic = unabashedly electronic, powerful"), section-scoped annotations ("verse — 'falling, seeking' — bass walks D→G→B♭→A; harmonic rhythm accelerates"), track-scoped ("don't sidechain the bass on the bridge — let it bloom"). Same content the .md holds today, but addressable, queryable, round-trippable across sessions.

- **FINDING (gap, high — re-stated):** **The exemplar drifts the wrong direction.** Until falling-walking is refactored to ingest its concept-doc content into annotations (or until annotations is built and the exemplar moves first), every new song scaffolded by mimicking falling-walking will carry an obsolete pattern forward. The cheapest fix in the meantime: a stub line in `songs/falling-walking/falling-walking.md` noting "this file is historical; do not mirror in new songs." The right fix: build annotations and migrate.

### 3.2 What "compose a punk song" actually requires from Claude

To honor "punk rock condensing Beethoven's 5th's progressions in 2 minutes with 4 parts including a synth-pad vocal melody," Claude has to:

1. **Decode the user's request musically.** Beethoven 5th = C minor → relative E♭ major motion. Claude can plausibly do this from training knowledge.
2. **Pick a tempo and time signature.** Punk = fast, 4/4. Maybe 180 BPM.
3. **Lay out 4 tracks + returns.** Drums, bass, lead, "vocal pad."
4. **Decide what's a session-clip per section vs. a single long arrangement clip.** Falling-walking uses one clip per (section, track), placed via `add_arrangement_clip`. Claude probably mirrors this.
5. **Write notes for each clip.** Now we hit reality.

What generators are available? Looking at `src/hallucinote/generators/`:

- `drums.py`: `kick_stumble`, `lazy_snare`, `trip_hop_hats`, `tresillo_hats`, `bossa_shaker`, `ghost_kicks`, `ghost_snares`, `open_hat_lifts`, `trip_hop_drum_pattern`
- `bass.py`: `tresillo_bass`, `walking_bass_to_next_chord`, `chord_tone_embellishment`
- `harmony.py`: `chord_pad`, `chord_stab`, `tresillo_pluck`, `sparse_bell_top`
- `envelopes.py`: `volume_swell`, `sidechain_trigger`

- **FINDING (gap, high):** **The generator library is falling-walking-shaped.** Every primitive serves the trip-hop / bossa / calypso world the canary song was built in. There is no `punk_drum_pattern`, no `power_chord_stab`, no `four_on_the_floor`, no `palm_muted_eighths`. For a punk song, Claude will have to either (a) inline raw `NoteDict` lists (which is allowed — falling-walking does this for song-specific parts), or (b) pretend the generators apply when they don't.

  Option (a) is honest and works, but the structured-composition value proposition starts to look thin: if every new genre means Claude hand-writes raw note arrays, the generators are only a marketing surface, not a load-bearing layer. The VISION promise of "ask for two drum parts at 95 and 100 BPM with a bassline weaving between the kicks of both, and get back something musical" requires a much richer generator library — or it requires that Claude's raw-notes output is reliably musical, which is its own bet (and unrelated to whether generators exist).

  This is partly an "early-days" issue and partly a tension in the architecture: are generators meant to be a growing library that captures the canon of musical primitives, or are they a thin skim that the LLM mostly bypasses? VISION leans toward the former; today the codebase is the latter.

- **FINDING (gap, medium):** **No song annotations table yet** (it's in the backlog as HIGH PRIORITY). For a 2-minute Beethoven-punk song, Maya is going to want to say "the chorus echoes the first movement's fate motif on the lead, keep that consistent" and have Claude remember that across sessions. Today, the DB has no place for that. The README promises "iterate by talking" — but iteration requires memory of intent, and intent has no home. (See `.prawduct/backlog.md` HIGH PRIORITY "Song annotations" + "Provenance log" — both are sibling features and both block real iterative composition.)

### 3.3 Building the DB

Assume Claude got through 3.1 and 3.2 — `songs/punk-fate/build.py` exists. She runs `python3 songs/punk-fate/build.py --reset`.

If `captured_session.json` was fabricated (no real Live set yet), the build succeeds: replay_capture writes 4 tracks + 2 returns + master into the DB. Then build.py's score-half adds tempo, time signature, sections, cue points, clips, envelopes, arrangement entries.

- **FINDING (friction, low):** `replay_capture` raises if a song with that name already exists. So `--reset` is mandatory after the first build. The convention is OK but the failure mode ("song already exists") is a silent return rather than a useful error if `--reset` is omitted. Look at falling-walking's `build()`: it prints `"song already exists (id=...); use --reset to rebuild"` and returns the existing id. That's friendly. The pattern needs to be in any scaffolded build.py too — another reason scaffolding deserves a template.

### 3.4 Pushing to Live

Maya: *"push punk-fate to Live."*

`/ableton-push` runs. Same ten phases. Same `session_id` bootstrap question as falling-walking — Claude has to either create one or punt to Maya.

Assume Claude bootstraps the session. Push runs. The skill carefully matches DB tracks to Live tracks by name; with a fresh Live set, none of Maya's DB tracks match any existing Live tracks, so phase 3 creates all of them. Phase 5 (clips), phase 8 (devices — empty since we didn't capture any), phase 9 (envelopes), phase 10 (arrangement) all proceed.

End state: Maya has a Live set with 4 fresh tracks named the way Claude named them, all with clips and arrangement placements but **no instruments**. The "Late Nite Kit" / "Operator" / etc. that make falling-walking sound like falling-walking are loaded because falling-walking's `captured_session.json` captured them. Punk-fate's fabricated snapshot didn't.

- **FINDING (gap, high):** **A new song from a prompt has no instruments.** The DB models device chains, but a fabricated snapshot won't have any plausible punk instruments. Maya hits play and hears nothing (or default Operator presets). For the promise to hold ("get back something musical"), Claude needs to:
  - Browse Live's library (`ableton://browser/instruments`) and pick instruments per track,
  - OR ask Maya to load instruments manually after push,
  - OR have a curated "starter kit" of generic instrument mappings per genre.

  The MCP surface supports loading instruments (`ableton_browser` + `ableton_device(action='load')`); the install includes the browser resource. But the *workflow* of "compose a new song" doesn't include an instrument-picking phase. The README handwaves this entirely.

- **FINDING (gap, medium) — RESOLVED ARCHITECTURALLY in v0.9:** *originally framed as "No `compose_new_song` MCP prompt."* The workflow primitives that were specced as MCP prompts (`create_midi_track_with_instrument`, `setup_sidechain_compression`, `build_return_bus`, `humanize_clip_velocity`, `compose_section_pattern`) were migrated to Claude Code skills (`.claude/skills/track-new-with-instrument`, `/mix-sidechain`, `/return-new`, `/clip-humanize`, `/pattern-compose`) because MCP prompts are not assistant-callable in Claude Code. The compose-orchestration content originally proposed as `start_new_song` folded into the `/song-new` skill itself.

### 3.5 First listen

Assuming instruments somehow got loaded, Maya hits play in Live. The arrangement plays.

- **FINDING (UX, medium):** Live's arrangement view shows the clips, but the cue points (section markers) are not necessarily visible at zoom levels that fit a 2-minute song into the screen. The push skill writes cues last, after arrangement; they exist but Live's UI default zoom doesn't always surface them. Not a bug, but a discoverability issue — Maya may not realize the section markers are there. The post-push message could note this.

---

## 4. Iteration

The README models iteration as:

> Iterate by talking — *"the bridge feels flat, lift the lead an octave there"*, *"swap the chorus walk for a fill at bar 12"* — and ask Claude to push again.

### 4.1 "Lift the lead an octave in the bridge"

To do this, Claude needs to:

1. Find the bridge section's `clip_id` for the lead track.
2. Read the notes of that clip.
3. Transpose them +12 semitones.
4. Write them back via `replace_clip_notes`.
5. Re-push.

Step 2 has a wrinkle. `Q.get_notes_for_clip(conn, clip_id)` works fine if Claude is in Python (build.py runs Python). But Claude in a chat is *not* running Python continuously — it's making MCP calls. To read DB notes from MCP, Claude has to either:

- (a) write a one-off Python script that opens the DB and prints the notes,
- (b) use the MCP `ableton_note(action='list')` against the clip in Live (works post-W6/W7, returns Live's stable per-note IDs for the diff path).

- **FINDING (friction, medium):** **There is no MCP read path against the Hallucinote DB.** Every MCP tool is `ableton_*` — they read Live, not the DB. For the DB, you have to drop into Python. This is fine for build.py work; it's awkward for inline conversational iteration. Claude ends up writing `python3 -c "from hallucinote.db import ..."` one-liners, which is brittle and noisy.

  A `hallucinote_query` MCP tool (or matching resources, e.g., `hallucinote://song/<slug>/notes?clip=<id>`) would close this gap. Today the only "DB-aware" thing on the MCP side is the sync planner CLI, which is goal-shaped, not query-shaped.

### 4.2 "Swap the chorus walk for a fill at bar 12"

This requires Claude to (a) understand which section is the chorus, (b) find the right clip and track, (c) compose a fill that fits the existing groove, (d) replace the relevant notes.

- **FINDING (gap, high):** **No retrieval surface for compositional context.** Claude can read raw notes, but "the chorus's walking-bass pattern" is a higher-level concept. Without song annotations (HIGH PRIORITY backlog item) and without provenance with decision rationale (sibling HIGH PRIORITY), Claude rebuilds its understanding from raw rows every time. The `section_role` column on clips helps (it's set during build), but it's a single string, not a description of what was intended.

  This compounds across iterations. Session 3, Maya says "make the bridge sneakier." Claude has no record of why the bridge was authored the way it was, no record of whether "sneaky" has been used as a stylistic anchor before, no record of which decisions on the bridge are deliberate (don't touch) vs. opportunistic (improve freely). The DB has structure; it doesn't have *intent*.

  This is the bet at the heart of the VISION ("structure unlocks competence") meeting reality: structure is necessary but not sufficient. The annotations backlog item is the answer the team has already identified; it's just not built yet.

### 4.3 Pushing again

After the edit, Maya says "push the change." Push runs again. But push is *additive*. The clips that already exist in Live still exist; their note arrays get rewritten by `ableton_clip(action='replace_notes')`. Arrangement-clip placements that already exist get re-added... or do they?

Let me re-read the push skill: "Push is **additive**: it does not delete Live state that isn't in the DB. If the user wants to start clean, they should open a fresh Live set first."

This says push doesn't *remove* Live-only state. It doesn't say what push does about DB state that's already linked to Live state.

Looking at `mcp_names.py` / `push.py` would clarify, but from the skill: phase 5 (clips) emits `create` and `replace_notes` calls. If a clip is already linked (from a previous push), the planner should be idempotent — re-running should result in `replace_notes` on the existing clip, not `create` a duplicate. The link table (`ableton_links`) carries the binding.

- **FINDING (uncertain, medium):** **Idempotency on re-push is critical and under-documented.** If Maya pushes, edits in Live, pulls back, edits in DB, pushes again — does she get a clean update or duplicated clips? The push skill says "re-runnable: if the link already exists, it's an upsert" for the probe-and-link step, but doesn't say it for every phase. Falling-walking's tests probably exercise this (test_build re-runs with --reset), but the conversational "push, edit, push again" workflow needs a verified contract. **Worth a smoke test (S-2 in `tests/integration/test_live_smoke.md`, currently a placeholder per backlog).**

- **FINDING (gap, medium):** **Arrangement-clip placements are append-only on re-push.** Looking at the skill's phase table: `arrangement` phase emits `ableton_clip(action='duplicate_to_arrangement')`. If the link doesn't exist, push will duplicate again on every re-push. Need to confirm in code, but if true, this means iterative push doubles the arrangement every time. Critical and easy to miss in casual testing.

  → This deserves a focused look before v1. (Searching `sync/push.py` for arrangement-phase idempotency was out of scope for this exercise.)

### 4.4 Switching directions: pulling Maya's edits

> *"pull my Ableton edits back into the DB"*

`/ableton-pull` is well-shaped — clean conflict policy (Ableton wins), clear domain mapping (mix-state, score-globals, cue-points, devices, nested-rack-chains, device-parameters, arrangement-clips, session-clips, clip-notes, envelopes), graceful skip-with-warn for things it can't do.

Watchpoints:

- **FINDING (UX, medium):** The pull skill's "everything" domain runs 9+ probes in order. For a small song this is seconds; for anything bigger it's tens of seconds. There's no progress indicator and no way to say "just pull what changed." Per-call timing isn't reported. Acceptable for v1, but a future "fast pull" that probes a watermark / change-counter (if Live exposes one) would matter.

- **FINDING (limitation, documented but worth surfacing):** A note moved in Live surfaces as **delete + insert** on the DB side, **rotating the UUID**. Per the skill: "edit by UUID DB-side if preservation matters." Maya doesn't know notes have UUIDs and won't think to "edit by UUID." If she moves a note in Live and then later asks Claude to "transpose only the bell-tagged notes," any tags on the moved note will have been lost. We accept this for v1, but it deserves a one-line warning at pull time when notes were moved.

- **FINDING (gap, low):** Envelope **discovery** on pull — envelopes authored only in Live are not pulled (backlog item, W7-A close note). If Maya draws a fresh filter sweep in Live and pulls, the DB doesn't get it. She has to either author it DB-side and push, or it just doesn't round-trip. This is documented in the skill's "MCP-gap-blocked" section but worth flagging in the README's "Pull manual edits back" example.

### 4.5 Annotations / decisions in the loop

Imagine session 3, after the Beethoven-punk iteration, Maya says: *"actually, lift the chorus down a step instead of up — it should feel like collapsing."*

Today, that *direction* is captured nowhere durable. The chorus pitch changes. The reasoning ("collapsing") vanishes the moment the conversation context rolls over. Session 4, Claude has no idea why the chorus is in D♭ instead of D.

- **FINDING (gap, high — but already on the roadmap):** **Annotations + provenance are pre-v1 essentials for the iterative-composition promise.** The backlog flags both as HIGH PRIORITY. Without them, "iterate by talking" works for one conversation; across sessions, the user is constantly re-explaining context. For a v1 release that bills itself as LLM-collaborative, this is the gap. The team knows. Worth confirming whether v1 ships without them and accepts the cold-start cost, or pushes one of them into v1.

---

## 5. Branching and forking — "songs as git repos"

VISION promises:

> A song is a git repo. Branch a chorus variant, A/B against main, throw it away.

Maya wants to try a half-time bridge. She:

```bash
git checkout -b half-time-bridge
```

Then talks to Claude: *"give me a half-time variant of the bridge."*

Claude edits `songs/punk-fate/build.py` (or perhaps inserts a mutation), re-builds the DB, re-pushes to Live. Maya listens, doesn't like it, `git checkout main`.

What's on disk after the branch switch?

- `songs/punk-fate/build.py` → reverts to main's version ✓
- `songs/punk-fate/punk-fate.db` → gitignored. **NOT** reverted. Whatever the half-time branch wrote is still in the DB file.

- **FINDING (gap, high):** **The DB is gitignored, so branching does NOT branch song state.** The user has to remember to re-run `build.py --reset` after every branch switch, or the DB will reflect stale state from whichever branch built it last. For a casual user, this is invisible until "the Live set sounds wrong after I switched branches, why?"

  Two paths to fix:
  1. Commit `.db` files (SQLite is a binary blob; diffs are useless but state is preserved). Painful for storage but solves the workflow.
  2. Make `build.py --reset` (or a `/song-reset` skill) automatic — git hook that triggers on branch switch + repo-detected song dirs. Brittle.
  3. Re-author the build.py to be fully deterministic, then never store the DB at all — the build is the artifact. This is the current architecture aspirationally, but in practice the DB carries `captured_session.json` -derived state AND build.py -derived state, and only the second is fully reproducible.

  Path 3 is the right answer long-term; today's reality is closer to path 0 (gitignore + warn). Worth a README callout.

- **FINDING (gap, high):** **`captured_session.json` is committed but only ever generated once.** If Maya's Live set drifts (she adds a return, changes a master volume), her DB and her snapshot drift. The snapshot is a one-shot seed; there's no "refresh the snapshot" workflow. Long-term, this is fine because pull handles drift. Short-term, the relationship between "the snapshot" and "the current DB state" is fuzzy. A user who reads `captured_session.json` and finds it doesn't match their current state will be confused.

- **FINDING (gap, medium):** **Two branches, both built the DB, both pushed to Live — what's in Live?** Both pushes ran against the same Live set (Maya doesn't switch Live sets when she switches git branches). Push is additive. So Live now has both versions' clips, mixed together. The push skill doesn't have a "this branch's clips, none others" guard, because the branch is a git concept and the link table is a DB concept that doesn't track branches.

  Workaround: every branch switch, open a fresh Live set. Awkward, undocumented.

---

## 6. Coming back the next day

Maya closes Claude Code, closes Live, walks away. Next morning she opens Live, opens Claude Code, says:

> *"where were we?"*

Today:

- The session briefing (printed at session start by the Prawduct hook) summarizes prawduct state (project memory, recent commits, framework freshness) — but this is about the *framework*, not about *Maya's song*. There is no song-state briefing.
- Claude reads `CLAUDE.md`, `project-state.yaml`, memory files. None of these know about `punk-fate`.
- Claude could `ls songs/` and find `punk-fate/`, then read its `build.py` and infer state. This works but it's slow and re-derived every session.

- **FINDING (gap, high):** **No song-aware session briefing.** For an LLM-collaborative music tool, "what song am I working on, what state is it in, what was last touched" should be the FIRST line of context every session. Today it's not surfaced at all. Trivial fix: add a section to the session briefing that lists `songs/*/` directories with last-modified `build.py`. Less trivial fix: integrate the planned annotations/provenance log so the briefing shows "last session you raised the chorus and didn't like it" with rationale.

- **FINDING (friction, medium):** Maya never named her session. The git branch (`half-time-bridge`) is a name, but the Hallucinote `ableton_sessions` row has its own name. Two namespaces, both unindexed in the briefing.

- **FINDING (uncertain, medium):** If the `.mcp.json` is per-project and the MCP server was started yesterday with one Live set bound, what happens when she reopens today with a *different* Live set? Does the MCP bridge auto-rebind, or does it report stale state? (The Remote Script connects fresh on each Live start; the MCP subprocess respawns on each Claude Code start. So the runtime state is fresh. But the DB-side `ableton_sessions` row that bound to "yesterday's Live set" is still in the DB. Pushing or pulling against that session_id when Live has a different layout could surface confusing errors.) Worth verifying.

---

## 7. Distribution — "share the song with a friend"

VISION:

> Two collaborators on different continents can each run the song against their own Ableton, push and pull edits like code.

Maya has finished `punk-fate`. She wants to send it to Devon.

```bash
git push origin punk-fate
```

Devon clones. He has Hallucinote installed (presumed). He:

```bash
git checkout punk-fate
python3 songs/punk-fate/build.py --reset
```

The DB rebuilds from `build.py` + `captured_session.json`. Then `/ableton-push` materializes it into his Live.

What can go wrong?

- **FINDING (gap, high):** **Instrument identity does not portably round-trip.** `captured_session.json` carries `instrument_uri` like `"query:Drums#FileId_5418"` — a path into Live's local browser catalog. Devon's browser does not have FileId_5418 (it's an id local to Maya's library). On push, `ableton_device(action='load')` will fail to find the instrument, or load something different. The whole sound of the song depends on instruments that don't survive a cross-machine handoff.

  This is the same problem every DAW collaboration tool has, but VISION makes a stronger promise. For v1, "two collaborators on different continents" works only if both have the exact same Live library state. Otherwise punk-fate sounds like default presets on Devon's machine.

  Mitigations: (a) prefer Live native instruments over third-party where possible; the URI then resolves more reliably. (b) Capture instrument-class + display-name + dialed parameters so even if the exact preset is missing, the rough sound reproduces. (c) Bundle an Ableton Live "Pack" alongside the song for shareable preset state. None of these are in v1.

- **FINDING (friction, low):** Devon's `session_id` doesn't match Maya's. The `ableton_sessions` table is local to his DB rebuild. This is correct (sessions bind a DB to a Live set, per-machine) but undocumented in a "share with friend" workflow. A walkthrough doc would help.

- **FINDING (gap, low):** No documented merge story. If both Maya and Devon make changes in parallel, the eventual git merge will involve a binary `.db` file (gitignored so not actually merged), divergent `build.py` files, and possibly divergent `captured_session.json`. The VISION says "diff-able and reviewable like code" — this is true of `build.py`, not of the rest of the song's state. For v1, single-author flow is the only safe path.

---

## 8. Tests — "songs are testable"

VISION:

> Songs are testable. Assert over them. "Bass aligns with kick within 10ms in the verse."

Falling-walking has `songs/falling-walking/tests/test_build.py` and friends. The test asserts track count, section names, note counts. Good baseline.

- **FINDING (gap, medium):** **There is no library of song-level assertion helpers.** The example test calls `Q.get_*` query functions and asserts shape. For "bass aligns with kick within 10ms in the verse," Maya would have to (a) find verse-section clips, (b) find drums + bass clip, (c) extract kick notes (filter by pitch 36), (d) extract bass downbeats, (e) align by start_beat, (f) assert delta < 10ms. That's a lot of boilerplate per assertion.

  A `hallucinote.assertions` module — `assert_aligned(conn, song_id, section='verse', track_a='Drums', filter_a=KICK, track_b='Bass', tolerance=0.01)` — would make the VISION promise concrete. Today it's a possibility, not a feature.

- **FINDING (UX, low):** Punk-fate scaffolding doesn't include a `tests/` directory by default. If the song scaffolding skill (which doesn't exist) created one, with a `test_build.py` baseline, the discipline would self-propagate.

---

## 9. Recap of FINDINGS, by severity

### High severity — block v1 promises if unaddressed

0. **falling-walking is a misleading exemplar.** Its sidecar `.md` predates the annotations direction; a scaffolding agent will mirror it by default. Either annotate the file as historical or migrate it. (§3.1.5)
1. **No song scaffolding command/skill.** `/song-new <slug>` should exist. *(Shipped W9-A.)* (§3.1)
2. **`captured_session.json` chicken-and-egg.** No documented path for "compose a new song against no Live set." (§3.1)
3. **Generators library is genre-narrow.** Composing punk requires inlined raw notes; VISION's "structured access lets the model collaborate musically" leans on a library that doesn't exist yet. (§3.2)
4. **No instrument-picking phase in compose flow.** Push without devices = silent Live set. (§3.4)
5. **No song-level annotations table** — backlog HIGH PRIORITY but not built. Blocks iterative-composition memory across sessions. (§3.2, §4.2)
6. **No provenance log with decision rationale** — backlog HIGH PRIORITY but not built. Same as 5, complementary surface. (§4.5)
7. **Branch switch does not branch song state** (DB is gitignored). Stale state every branch flip. (§5)
8. **No song-aware session briefing.** "What song am I working on" is invisible to Claude on session start. (§6)
9. **Instrument identity does not portably round-trip.** Cross-machine collaboration sounds wrong. (§7)

### Medium severity — friction, surprising failures, missing UX

10. **`session_id` bootstrap is undocumented for first-time push** despite the skill explicitly forbidding invention. (§2.2)
11. **README has no troubleshooting section.** Every category of install/runtime failure needs a known-good recovery. (§2.3)
12. **No DB-aware MCP read path for inline iteration.** Forces `python3 -c "..."` improvisation. (§4.1)
13. **Arrangement-clip placements may not be idempotent on re-push** — needs verification + smoke test. (§4.3)
14. **Pull doesn't pulse-summarize timing or skip-unchanged.** Acceptable for v1, painful at scale. (§4.4)
15. **No `start_new_song` / `compose_section` MCP prompt** that captures the full "new song from a prompt" workflow. *(Resolved architecturally in v0.9: the workflow lives in the `/song-new` skill rather than an MCP prompt. See §3.4 + the entries there.)* (§3.4)
16. **Note-move-rotates-UUID surfaces zero warning** at pull time. (§4.4)
17. **Two-branch-one-Live-set Frankenstein** when branches both push without resetting Live. (§5)
18. **`captured_session.json` is a one-shot seed**; no refresh workflow when Live drifts. (§5)
19. **Cross-machine `ableton_sessions.id` is not shared** — documented in code, invisible in user docs. (§7)
20. **No library of song-level assertion helpers** — VISION promise of structural tests is bring-your-own-boilerplate. (§8)
21. **Live UI quirks (mixer-column-hidden, envelopes-not-visible) require user action** and are not flagged post-push automatically. (§2.2)
22. **MCC reconnect is two different lifecycles** (server respawn vs. Live restart) — drift mode is opaque. (§6)

### Low severity — polish

23. **`[dev]` in install instructions** is jargon for non-developers. (§1.1)
24. **No Python version preflight.** (§1.1)
25. **No Windows quick-start in README.** (§1.1)
26. **No Linux User Library candidates in install_paths.** (§1.1)
27. **Install skill final message uses MCP syntax** the user can't type. (§1.2)
28. **No "you're set up, try these three things" post-install hand-off.** (§1.4)
29. **Cue points may not show at Live's default zoom.** (§3.5)
30. **No documented multi-author merge story.** (§7)

---

## 10. Suggested v1 punch list (compressed)

If we had to ship in two weeks and could fix only a handful of these, the bang-for-buck list:

1. **Build `/song-new <slug>`** with a build.py template, a no-Live `captured_session.json` template (4 generic tracks + 2 returns), and a `tests/` skeleton. Closes #1, #2, parts of #4.
2. **Auto-bootstrap `session_id`** in `/ableton-push` when none exists, with a one-line user confirmation. Closes #10.
3. **README troubleshooting section** covering the top 5 install/runtime failures. Closes #11.
4. **Post-push UX message** that names the two Live UI quirks. Closes #21.
5. **A smoke test for push idempotency on the arrangement phase.** Verifies #13.
6. **Session briefing additions** for `songs/*/` last-modified + active song slug. Closes #8 partially.
7. **Pre-v1 commitment**: ship at least the **annotations** backlog item (the smaller of the two HIGH PRIORITY items) so iterative composition has SOMEWHERE to capture intent. Closes #5; partial credit on #6.
8. **Generators stretch goal**: add a `four_on_the_floor`, `power_chord_stab`, `palm_muted_eighths` to widen the library to one more genre. Demonstrates that the library can grow; doesn't pretend to solve #3 fully.

Items 9 (cross-machine instrument identity) and the full provenance log are honest "v1.1" candidates — too large for two weeks, but they should be in the announcement post as "next."

---

## 11. What this walkthrough did NOT exercise

For honesty, here's what I skipped or only sampled:

- **Live not running:** every claim about Live's behavior is inferred from skill docs, gaps.md, and the push/pull code shape. Real Live could surprise us in either direction.
- **The 10 MCP tools' help action** — I read the prompts list and the gaps guide, not the per-tool help payloads. There may be more discoverability or less than my walkthrough assumes.
- **`ableton_browser`** — I noted it exists; I didn't simulate a "browse for an instrument that sounds punk" call. Could be smooth, could be a mess.
- **MIDI capture (Maya playing a real keyboard into Live)** — out of scope of the "composer prompts Claude" walkthrough but a real flow for some users.
- **Audio tracks** — explicitly later/never in scope.
- **Push timing on large songs** — falling-walking is ~98 bars; a 10-minute ambient piece could exhibit different latency / failure profiles.
- **Verifying claims by grepping the codebase** — I leaned on skill docs and the backlog. Several FINDINGS marked "uncertain" deserve a direct code check (push idempotency on arrangement phase is the most important).

If any FINDING above turns out to already be handled in code, treat that as a documentation gap rather than a bug — the walkthrough is the user's view, and the user reads docs (and skills), not code.
