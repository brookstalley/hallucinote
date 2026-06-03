---
name: compose-part
description: Compose a part to a FINISHED audible state via the author-as-code loop — write/extend note-generating code in the song's build.py using hallucinote.generators, run the build (DB through mutators, events fall out), then scoped-push only the changed clips to Live. Notes are authored as code and never enter the agent's context. Use to write or rewrite a part (drums, bass, a lead line, a section's comp), iterate on feel/density, or fix a part that doesn't sound right. Supersedes /pattern-compose.
argument-hint: <slug> <what-to-compose> (e.g. "sun-zone-done verse2 bass — busier, walking into the chorus")
user-invocable: true
disable-model-invocation: false
allowed-tools: Read, Write, Edit, Bash(python3 songs/*), Bash(python3 -m hallucinote.sync.push_cli *), Bash(pytest songs/*), Bash(rg *), Skill(song-context), Skill(ableton-push), mcp__hallucinote-mcp__ableton_clip, mcp__hallucinote-mcp__ableton_track, mcp__hallucinote-mcp__ableton_session
---

# /compose-part

You compose a part to a **finished, audible** state. The deliverable is the part as it's meant to sound — not a scaffold with a "tune it later" list. This is the interactive author→build→scoped-push loop: you write the smallest correct note-generating **code**, a build expands it to notes and persists through mutators, and a scoped push materializes only what changed to Live. **The note array never enters your context** — you author the generator expression, not the data.

$ARGUMENTS

## The invariant (why this skill exists)

All composing goes through the DB so DB and Live never diverge. You author notes **as code** in `build.py` (the song's single authored home), the build writes them through mutators (`M.replace_clip_notes` → one `CLIP_NOTES_REPLACED` event → one batched `clip.set_notes()` on the wire), and `push-notes` ships only the changed clips. Typing a note array into a tool call is the thing this skill replaces: it bypasses the DB (the next full push wipes it) and burns context on data the model shouldn't hold.

**Modify / delete / total-replace are free.** The unit of change is the clip's complete note array, so "rewrite the whole bass line", "delete 2000 notes and add 2230 different ones", and "empty the clip" (`replace_clip_notes(notes=[])`) are all the same path at the same cost as a fresh write — one sub-second round-trip. Author the desired **end-state** in code; never express a diff or a per-note edit.

## The loop

### 1. Orient
- Resolve the song: `songs/<slug>/build.py`, its per-branch DB, and the push session id (the `ableton_sessions.id` — `push-notes` always takes it explicitly). If you don't know the session id, list sessions or use `--auto-session` semantics from a prior push.
- **Read intent for any non-trivial part.** Invoke `/song-context <slug>` to recall composer intent + prior decisions (genre, feel, what each section is *for*, what should win each section). Composing against stated intent is the difference between "notes" and "the right part". Skip only for throwaway/experimental parts.

### 2. Author the part as code
- Write or extend the part's note generation in `songs/<slug>/build.py` (in its `_compose_*` functions — match the song's existing structure; for a large part, a sibling module `build.py` imports is fine). Use the **authoring API** — `hallucinote.generators.{drums,bass,harmony,primitives}` — for full expressivity. See `docs/song-authoring-conventions.md` → **Authoring API** for the discoverable helper surface (what each module offers and where to import it).
- **Feel is authorship.** Bake genre-appropriate microtiming into the generator call via its `feel=` dict (push/pull/swing), coordinated across instruments where the genre calls for it. Don't defer it to a `/clip-humanize` pass — if the part doesn't feel right, the wrong `feel` went in at compose time. (`docs/song-authoring-conventions.md` → *Per-part feel*.)
- **Probe drum kits, don't assume GM.** Pad notes are kit-specific (Hot Rod Kit puts a cowbell at the GM ride slot). Ask the kit, per *Drum kits: probe, don't assume*.
- You can resolve a freeform feel/density intent ("lazy", "driving", "drag the eighths") to a concrete dict/parameter *in the code you write* — the LLM intelligence lives in authoring the expression, not in a server-side vocabulary.

### 3. Build (DB through mutators)
```
python3 songs/<slug>/build.py
```
The state-converger reconciles: changed parts re-author through mutators (events fall out), unchanged parts are no-ops. No `--reset` — that's the wipe-and-rebuild escape hatch. Run the song's shape tests if the change is structural: `pytest songs/<slug>/tests/`.

### 4. Scoped push (materialize only what changed)
```
python3 -m hallucinote.sync.push_cli push-notes <session_id> --changed
```
`--changed` pushes only the clips whose **note content** changed since the last push (content fingerprint, not event log — so a whole-DB rebuild that didn't alter a clip won't re-push it). Or target explicitly with `--clip <id>` (repeatable). The command runs in-process and prints a **counts-only summary** (`clips pushed, per-clip note counts, what was skipped + why`) — the notes never enter your tool-use channel.

**Precondition — structure must be linked first.** `push-notes` only touches notes on already-linked clips. For a brand-new track or clip, run a full push once (`/ableton-push`, i.e. `push_cli execute`) to create + link the structure, *then* iterate with `push-notes`. If a clip's track isn't linked, `push-notes` returns a teaching error per clip — that's your signal to run a full push first.

### 5. Verify it's finished
- The part is **audible and right**, in service of the section's intent. For `make-me-X` work, sound design (the device chain) and feel are part of *done*, not a deferred mix pass — see *Sound design is authorship*.
- Verify via DB-state assertions + the push summary's counts. (Live render is environment-dependent — don't gate on live capture.)

### 6. Iterate
Refine the code → `build.py` → `push-notes --changed`. Each loop is sub-second and token-free. Keep going until the part is finished — don't stop to ask "what next" between iterations (CLAUDE.md → *Stop only on high-stakes decisions or must-answer questions*).

## Named pattern shapes (where `/pattern-compose` went)
The named patterns the old `/pattern-compose` offered are importable helpers — you call them in `build.py` instead of asking a skill to inline notes:

| You want… | Call |
|---|---|
| tresillo (3-3-2) bass | `bass.tresillo_bass(...)` |
| walking bass into a chord change | `bass.walking_bass_to_next_chord(...)` |
| trip-hop drum pattern | `drums.trip_hop_drum_pattern(...)` |
| tresillo / bossa hats, ghost kicks/snares, open-hat lifts | `drums.tresillo_hats / bossa_shaker / ghost_kicks / ghost_snares / open_hat_lifts(...)` |
| chord pad / stab, tresillo pluck, sparse bell top | `harmony.chord_pad / chord_stab / tresillo_pluck / sparse_bell_top(...)` |

Full signatures live in the source (`src/hallucinote/generators/`); the index in `docs/song-authoring-conventions.md` → *Authoring API* is the discovery entry point. For anything no helper covers, **the absence of a helper is never a limit** — author the notes/envelopes/device-chain directly **in `build.py`** (still as code, still through the mutators), or write the generator. See `docs/song-authoring-conventions.md` -> *The toolkit reduces work — it never limits what you can author*. Never inline the data into a tool call.

## What this skill does NOT do
- **Per-note surgical edits** — blocked by the Live per-note-ID gap; the whole-array path makes it unnecessary anyway (author the end-state).
- **Velocity-only humanize** — that's `/clip-humanize` (a different axis: jitter on already-feel-correct parts). Don't use it to inject groove.
- **Structure** (creating tracks, instruments, clips for the first time) — that's `/ableton-push` / `/track-new-with-instrument`. This skill composes *notes* into structure that already exists in the DB.
