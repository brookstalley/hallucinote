<!-- Build Plan — SMP-6V2K wave 1 (place and conform). Tier 1 (Source of Truth).
     WHAT to build. For HOW (governance, test discipline, Critic), read
     /prawduct:methodology building. Design artifact: design.md beside this file. -->
---
artifact: build-plan
version: 1
scope: SMP-6V2K
branch: plan/smp-6v2k-sampling
depends_on:
  - artifact: design
    path: .prawduct/artifacts/plans/SMP-6V2K/design.md
  - artifact: data-model
  - artifact: architecture
  - artifact: sync-boundary-contract
  - artifact: api-contract
governed_by:
  - artifact: data-model
    dispositions:
      - "all writes go through mutators, one event each → conforms: pull ingest writes audio clips through `create_audio_clip` / `update_clip`, never raw SQL"
      - "the DB is materialized state, never source of truth → conforms: the audio file is the source (in git under `assets/`), the clip row is materialized from `build.py`"
      - "an existing song DB is opened through `init_db` → conforms: no new open path"
  - artifact: architecture
    dispositions:
      - "`_FINGERPRINT_PATHS` names exactly the code vendored into and executed in Live → engaged, not departed: chunk 02 edits `actions/clip.py` and `handlers/clip.py`, both fingerprint-bearing, so the wave carries a re-vendor + Live restart and says so at every hand-off"
  - artifact: sync-boundary-contract
    dispositions:
      - "a phase that could not DETERMINE its state must not report OK → conforms: a missing sample file fails its clip loudly rather than reporting a pushed clip that plays silence"
      - "planners produce plans and never send → conforms: chunks 03-05 add planner rows and apply-side handling only"
  - artifact: project-preferences
    dispositions:
      - "the MCP server is stdlib-only at import time → conforms: no new imports in the server or Remote Script; path resolution already lives in stdlib-only `paths.py`"
      - "no shims to unshipped consumers → conforms: the deferred `audio_path` no-op is replaced, not wrapped"
partition: |
  Parallel in two waves, on a file-disjoint partition. The plan-time "serial" reading
  located the collision in the wrong place: the four refuse-loudly sites live in four
  separate modules — `hallucinote_mcp/.../{actions,handlers}/clip.py` (02),
  `sync/push/clips.py` + `sync/push/arrangement.py` (03), `sync/push/envelopes.py` (04),
  `sync/pull/clips.py` (05) — so nothing collides on files. What is genuinely ordered is
  the WIRE CONTRACT, and only chunk 02 moves it.
  .
  Wave A, in parallel: **02** (the wire — create, the conform properties, and the audio
  read surface) and **04** (envelope routing — planner-side only; the envelope wire
  already exists and probe row 3 confirmed it end-to-end on a real audio session clip).
  .
  Wave B, in parallel once 02 has landed and the Remote Script is re-vendored: **03**
  (push clips + arrangement) and **05** (pull ingest). 03 additionally needs chunk 01's
  recreate verdict before its reconcile rule is written.
  .
  Then **06** (docs), coordinator-owned.
  .
  Each delegate owns its modules and its own test files and touches nothing else. The
  coordinator owns the wire contract, the combined suite, the re-vendor handshake, the
  operator-verification entries, and all governance.
last_validated: 2026-09-09
critic_mode: null
---

# Build plan — SMP-6V2K wave 1: an authored sample lands in Live, and a dragged-in one comes back

> **Reconciled against `requirements.md` on 2026-09-09; buildable.** Wave 1 carries
> **R1.1** (place and conform), **R1.2** (round-trip), **R1.4** (automation on audio
> hosts) and the *verdict* half of **R1.5** (reverse) — and nothing else. **R1.6** (asset
> store, normalization, provenance) and **R1.7** (derived audio is regenerable) are wave
> 3's; **R3.6** (sample-accurate alignment) belongs to the spectral family and has no
> wave-1 surface. All three are named in "Scope boundary" below rather than silently
> dropped.
>
> The reconciliation found one real gap, folded into chunk 02: **R1.2 needs a *read*
> surface on the wire, and there is none.** `list_handler` reports `name` and `length` for
> a session clip and nothing else (`hallucinote_mcp/src/hallucinote_mcp/handlers/clip.py`
> — the session branch of the slot loop); no `file_path`, no gain, no warp state, not even
> a flag saying the clip is audio. Pull cannot ingest what the wire will not report. Chunk
> 02 therefore grows the read half as well as the write half, and chunk 05 depends on it.

Backlog: **#284** (CLP-AUD2 — session-view audio clip creation and push/pull surface),
**#268** (ENV-8H1T — mixer envelopes on audio tracks via the audio-clip model).
Design: `.prawduct/artifacts/plans/SMP-6V2K/design.md`.

The DB already models an audio clip completely and the LOM calls were probe-confirmed
on Live 12.4.1. This wave is the wiring between them: three refuse-loudly paths
(`sync/push/clips.py`, `sync/push/arrangement.py`, `sync/pull/clips.py`), one
`refused_audio` envelope route, and one reserved-but-inert MCP parameter, all of which
name CLP-AUD2 as the scope that would close them.

## Requirements Confidence

**Level:** High for the mechanism, **Medium** for two contract details that chunk 01
settles before anything is built on them.

**Why high on the mechanism:** every Live-side call this wave needs was executed against
the user's own Live 12.4.1 and recorded with its error shapes —
`docs/research/audio-first-class/lom-probe-results.md` rows 1a (`ClipSlot.create_audio_clip`),
1b (`Track.create_audio_clip`), 1c (the two error shapes: MIDI-track refusal and
invalid-path refusal), and 3 (a mixer envelope on a real audio session clip, written and
read back). The DB half shipped as CLP-AUD1 and SMP-7K2D chunks 1–2, with mutators,
validation and events already in place.

**The two Medium items, both real contract risks:**

1. **`clips.reverse` claims a materialization that the LOM research says does not exist.**
   `db/schema.sql` says reverse is "materialized at push as Live's clip reverse (a playback
   parameter)"; `lom-audio-clip-surface.md` §4 says "**No `reversed` property** — clip
   reverse is not LOM-accessible (confirmed absent)". One of them is wrong and a column
   whose stated push behaviour does not exist will fail the first time a song sets it.
   SMP-7K2D's chunk 0 was written to settle exactly this and never ran.
2. **`Clip.file_path` is read-only**, so re-pointing a clip at a different file is a
   delete-and-recreate. That makes the clips phase's reconcile *destructive* for a case the
   MIDI path never had, and destructive arrangement reconciles are where this project has
   been bitten before (ARR-PROJ). The behaviour of `create_audio_clip` against an **occupied**
   slot, and whether a recreate preserves or drops the clip's envelopes, are not in the probe
   record.

**What raises it:** chunk 01 — one Live session, both questions plus the two wave-4
questions batched in so the operator is asked once.

**Open assumptions:**

- `[ASSUMPTION: warp defaults and Complex Pro are reachable as plain `warp_mode` ints |
  MED impact | settled in chunk 01 by reading `available_warp_modes` on a real clip]`
  Probe row 1a recorded that `warping` defaults **true** on a created clip but did not
  enumerate the mode ints. An authored `warp_mode` that silently means a different
  algorithm than the author named is a wrong-sounding song with no error.
- `[ASSUMPTION: an audio clip created in the arrangement needs no session counterpart |
  LOW impact | user can override]` `Track.create_audio_clip(path, beats)` places directly,
  so the arrangement phase does not have to route through a session clip and
  `duplicate_to_arrangement` the way the MIDI path does. Chunk 03 uses the direct call.
- `[ASSUMPTION: this wave does NOT build acquisition or transforms | HIGH impact | user
  can reorder]` A sample reaches `assets/` by hand in wave 1 (copy the file in, author the
  path). Extraction from a movie file is wave 3's, the sample lens is wave 2's. Wave 1 is
  the spine both stand on, and it is what makes the first line audible in the set.

## Scope boundary — what this plan does NOT do

- **No acquisition, no analysis, no DSP.** Waves 2 and 3.
- **No sampler / Simpler sample assignment.** Wave 4 (#330) — except that chunk 01 asks its
  probe questions while Live is open, so wave 4 starts unblocked.
- **No take lanes or comping.** In AUD-1M4V's scope, not in this song's path.
- **No warp-marker authoring.** AUD-1M4V lock 3 deferred it; the write API exists (probe
  row 8) and needs `Live`-module-constructed marker objects. Wave 1 conforms with warp
  mode + markers + transpose only.
- **No arrangement-clip envelopes.** Probe row 2 is definitive: arrangement clips cannot
  host them. Chunk 04 is session clips only, exactly as the MIDI path already is.

## Status

- [x] Chunk 01: the Live session that settles the reverse contract and the recreate semantics *(operator-gated; gates only 03's reconcile rule)* — ran 2026-09-09 on Live 12.4.5
- [x] Chunk 02: `ableton_clip` creates a real audio clip, and the audio property surface is complete *(wave A)*
- [x] Chunk 03: the clips and arrangement phases materialize `kind='audio'` *(wave B)*
- [x] Chunk 04: an audio-track session clip hosts envelopes (#268) *(wave A)*
- [x] Chunk 05: pull ingests audio clips, including one dragged in by hand *(wave B)*
- [x] Chunk 06: the docs say what is true, and the contract artifacts track *(coordinator)*
- [x] Chunk 07: the two refusals settle against chunk 01's verdicts *(wave B; planner tests, then the live "Done when" of chunk 03 applies to it)* — built 2026-09-09

**A ticked box here means the code is built, reviewed and green — it does NOT mean the
wave is done.** Chunks 02-05 and 07 each carry a live "Done when" clause that only an
operator at a running Live can discharge, and none of them has been. Chunk 01's tick is
different in kind — it *was* the operator session, and its verdicts are on disk. Chunk 07's
handler edit re-flips the wire fingerprint, so the re-vendor handshake is owed again before
any live clause runs. The conditions still standing are named under *Definition of done*
below, and `capability-truth.md` rates the capability accordingly.

---

### Chunk 01: the Live session that settles the reverse contract and the recreate semantics

**Type:** code · **Foreign API:** Live Object Model (Live 12.4.x) · **Visual change:** no
· **Operator-gated:** yes — needs a running Ableton Live, the Hallucinote plugin loaded so
`ableton_probe` is on the wire, and a human at the machine.

**It does not gate wave A.** Rows 1a, 1b and 1c of
`docs/research/audio-first-class/lom-probe-results.md` are recorded responses from a real
Live 12.4.1 (2026-06-10), which is what the chunk-02 "verify-api" step asks for: creation
in both locations and both error shapes are already contract-grade. Chunk 02 is built
against those rows, and chunk 04 against row 3, before this chunk runs.
`[DECISION: wave A builds against the 2026-06-10 probe record rather than waiting on a
fresh session | the "verify-api" bar is *recorded responses from a running Live*, and rows
1a-1c/3 are exactly that; blocking two chunks on operator availability buys no new fact |
user can override]`

**What is still genuinely open**, and therefore what this chunk owes downstream: the
**reverse** verdict (a possible small addition to chunk 02 and the schema comment), the
**warp-mode int map** (validation only — the wire passes the int through and Live refuses a
bad one either way), and the **recreate semantics**, which chunk 03 needs before it writes
its reconcile rule. Chunk 05 and chunk 04 need nothing from here.

**Spec.** A probe pass through the shipped `ableton_probe` bridge, appended to
`docs/research/audio-first-class/lom-probe-results.md` as a dated section (that file is
already the canonical verdict record and supersedes the research passes where they differ).
Questions, in the order a builder needs them:

1. **Reverse.** Does a `Clip` on Live 12.4.x expose any settable reverse? `describe` a real
   audio clip and diff against the property list `lom-audio-clip-surface.md` §4 recorded.
   The answer rewrites either the schema comment or wave 3's plan.
2. **`available_warp_modes`** on a real audio clip: the int → algorithm mapping, so
   `WARP_MODES` in `db/mutations/clips.py` can be checked against Live rather than trusted.
3. **Recreate semantics.** `create_audio_clip` into an **occupied** slot: error, replace, or
   silent no-op? Then delete-and-recreate a clip that hosts a mixer envelope — does the
   envelope survive, and if not, what does `automation_envelope` return afterwards?
   **And, on the same clip: does `duplicate_clip_to_arrangement` carry an envelope off an
   AUDIO session clip the way it does off a MIDI one?** Chunk 04 surfaced this: once an
   audio clip can host an envelope, `envelope_hosting_clip_ids` returns audio clip ids, and
   `push/arrangement.py` routes any placement in that set through duplicate-onto-cleared
   precisely so the envelope travels with it. Chunk 03 otherwise places audio with
   `Track.create_audio_clip(path, beats)` directly, which carries nothing. The two stories
   collide on exactly one row — an audio placement whose source clip hosts a ride — and the
   answer decides which one wins.
4. **Path handling.** Confirm the absolute-path requirement and re-record the two error
   shapes from row 1c against this Live build.
5. **Batched for wave 4** (#330 chunk 0, so the operator is asked once): how a sample
   assigns to Simpler/Sampler via LOM, whether an arbitrary `assets/` file is reachable that
   way, and whether Simpler exposes an automatable `Reverse` alongside `S Start` / `S Length`.

**Acceptance.** Every question answered with a recorded call and its literal response;
the reverse verdict stated unambiguously; the warp-mode map written down.

**Done when:** (0) `verify-api` — the probe calls above executed against the running Live
and their responses captured, before any handler is drafted; (1) the results section is
appended with the Live build number and date; (2) the `clips.reverse` schema comment is
corrected to whatever is true, or confirmed correct; (3) if reverse is absent, a note lands
on #237 saying the column's materialization moves to wave 3/4.

---

### Chunk 02: `ableton_clip` creates a real audio clip, and the audio property surface is complete

**Type:** code · **Foreign API:** Live Object Model · **Visual change:** no

**Spec.** `ableton_clip(action='create', kind='audio', audio_path=...)` currently returns
`audio_path_deferred` and loads nothing. Replace that no-op (do not wrap it — no shims to
unshipped consumers):

- **Session:** `clip_slot.create_audio_clip(abs_path)`. **Arrangement:**
  `track.create_audio_clip(abs_path, position_beats)`.
- The handler takes an **absolute** path — resolution from the song-relative form is the
  engine's job through `paths.resolve_audio_path`, which is where it already lives, and the
  server stays stdlib-only.
- Map the two probe-recorded refusals to the project's teaching-error shape rather than
  letting a `RuntimeError` reach the wire: an audio clip on a MIDI track, and a path that is
  not a valid audio file (which is also what a missing file looks like from Live).
- `set_property` currently covers `gain / pitch / warp / loop_start / loop_end / muted /
  color`. Add what the DB models and the wire cannot yet carry: `warp_mode`, `start_marker`,
  `end_marker`, and pitch **fine** (the existing `pitch` is coarse semitones). Reverse only
  if chunk 01 found it.
- Update the action's `tips`, which today tell the reader session audio creation is
  unsupported and to drag from the browser.
- **The read half — the reconciliation gap.** `list_handler` reports a session clip as
  `{clip_index, empty, name, length}` and an arrangement clip with `note_count` (already
  `None` for audio). Nothing on that wire says a clip *is* audio, let alone what file it
  plays. Add, for both locations: a discriminator (`is_audio`, read off `clip.is_audio_clip`
  — the mirror of the `is_midi_clip` guard the arrangement branch already uses), and, when
  it is audio, `file_path`, `gain`, `pitch_coarse`, `pitch_fine`, `warping`, `warp_mode`,
  `start_marker`, `end_marker`. Absent for MIDI clips rather than null-filled, so a reader
  cannot mistake "MIDI" for "audio with no file". This is the surface **R1.2** round-trips
  through and the one chunk 05 plans against; it is the wire's half of the contract, so it
  ships here rather than being discovered in chunk 05.

**Re-vendor.** `actions/clip.py` and `handlers/clip.py` are both in `_FINGERPRINT_PATHS`, so
this chunk flips the wire fingerprint: the Remote Script must be re-vendored
(`/hallucinote:ableton-mcp-install`) and Live restarted before anything downstream works.
Every later chunk in this wave depends on that handshake.

**Tests.** Handler unit tests against the fake LOM in `hallucinote_mcp/tests/` covering both
locations, both error mappings, and each new property; **read-surface tests asserting an
audio clip reports its discriminator and its properties and that a MIDI clip omits them
entirely**; a wire/schema test that the new params are declared; the version-fingerprint
test will flip and is expected to.

**Done when:** (0) `verify-api` — chunk 01's recorded responses are the contract the fakes
are built against, not the docs; (1) tests green; (2) a real audio clip created in both
locations against a running Live, recorded in `.prawduct/operator-verification.md`.

---

### Chunk 03: the clips and arrangement phases materialize `kind='audio'`

**Type:** code · **Visual change:** no

**Spec.** Two refuse-loudly paths become real phases. Scope them by the pattern, not by
line: **every branch in `sync/push/` that tests a clip or placement row for `kind == 'audio'`
and warns rather than acting.**

- **Clips phase (`push/clips.py`, contract phase 6).** Plan a create for each `kind='audio'`
  row: resolve `audio_file` through `paths.resolve_audio_path` against the song dir,
  **check the file exists before planning the call** — a missing sample must fail its clip
  loudly, because a clip that pushes and then plays silence is the "reported OK without
  determining state" failure the sync contract forbids — then emit the create plus the
  authored conform properties (gain, transpose, warp/warp_mode, markers).
- **Reconcile.** `Clip.file_path` is read-only, so a row whose `audio_file` changed is a
  delete-and-recreate, and chunk 01 says what that costs. The rule this chunk writes down:
  same file → update properties in place; different file → recreate; and if the probe
  showed envelopes do not survive, the recreate re-emits them rather than silently dropping
  a ride the author wrote.
- **Envelope-hosting audio placements — the seam chunk 04 opened.** `envelope_hosting_clip_ids`
  now returns audio clip ids, and `push/arrangement.py` routes a placement whose source clip
  is in that set through **duplicate-onto-cleared** rather than create+fill, so the envelope
  travels with the clip. Placing audio with the direct `Track.create_audio_clip(path, beats)`
  call would carry no envelope. Decide this row explicitly against chunk 01's answer: if
  `duplicate_clip_to_arrangement` carries envelopes off an audio session clip, an
  envelope-hosting audio placement takes the duplicate path like a MIDI one and only the
  envelope-free ones use the direct call; if it does not, the direct call is used throughout
  and the envelope is re-emitted rather than silently dropped. Either way this is one branch
  with a test, not an accident.

- **Arrangement phase (`push/arrangement.py`, contract phase 13).** Today an audio placement
  skips the **whole track's** projection so that manually-placed clips are not wiped. Once
  audio placements materialize, an audio track becomes projectable like any other — but the
  arrangement-as-projection redesign's clear-then-create shape means a track carrying
  hand-placed clips would lose them. Project audio tracks the DB has placements for; keep the
  skip (and its warning) for a track that has none, and say which is which in the report.
- **Idempotency.** A second push of an unchanged song plans no work. This is the property the
  MIDI path holds and the one a destructive reconcile most easily breaks.

**Tests.** Planner tests (no Live): create-from-authored-row; missing file → loud failure;
unchanged row → no-op; changed path → delete+create ordering; arrangement projection with and
without DB placements; the existing warn-and-skip tests are **rewritten to assert the new
behaviour**, never deleted.

**Done when:** (1) tests green; (2) a song with one authored audio clip pushes into a real
set — session and arrangement — and a re-push is a no-op; (3) the operator-verification
entry names the sample file used.

---

### Chunk 04: an audio-track session clip hosts envelopes (#268)

**Type:** code · **Visual change:** no

**Spec.** `push/envelopes.py` routes an envelope whose host is an audio track to
`refused_audio` and teaches CLP-AUD2 as the reason. That reason is gone after chunk 03.
Remove the refusal so an audio host routes exactly like a MIDI host — `session_clip` when a
single session clip covers the envelope's span, `perform` when none does — which is what
probe row 3 confirmed end-to-end on a real audio clip. Arrangement clips stay refused
(probe row 2).

**Tests.** The route table gains audio-host cases; the existing `refused_audio` tests are
rewritten to assert the routing they now get.

**Done when:** (1) tests green; (2) a volume ride authored under an audio clip pushes and is
audible in the set; (3) the sync-boundary contract's phase-11 section reflects the new route.

---

### Chunk 05: pull ingests audio clips, including one dragged in by hand

**Type:** code · **Visual change:** no

**Spec.** `sync/pull/clips.py` warns and skips both directions of audio today. Make pull
read what Live has:

- An audio clip in a slot the DB links → update the row's conform properties (`gain`,
  `pitch_coarse/fine`, `warping`, `warp_mode`, markers) through `update_clip`.
- An audio clip in a slot the DB does **not** know → create the row through
  `create_audio_clip`, storing Live's absolute `file_path` back in the form
  `clips.audio_file` is defined to carry: song-relative POSIX when the file lives under the
  song dir, absolute otherwise. This is the case that matters most — it is how a line the
  user dragged into Live becomes part of the song's source instead of living only in the
  `.als`.
  **Do not reach for `portable_path` here.** Its middle form collapses a path outside the
  base to `~/…`, and `resolve_audio_path` — the resolver `clips.audio_file` is read back
  through — does not expand `~`; only `resolve_portable_path` does. A `~`-collapsed
  reference in this column would resolve as a relative path under the song dir and fail at
  the next push. Two forms only, and a test that pins the outside-the-song-dir case to
  absolute.
- Notes stay refused on audio clips (`pull/notes.py` already does this, correctly).
- The empty-slot delete path must keep its existing audio exclusion honest: now that audio
  clips are known, an audio slot the DB no longer has is a real delete, not an unknown.

**Tests.** Pull-plan tests for each case, including a hand-dragged clip whose file sits
outside the song dir (absolute form preserved, not rewritten).

**Done when:** (1) tests green; (2) a clip dragged into Live by hand survives a pull → push
round trip with its warp settings intact; (3) the mutator/event path is used throughout —
no raw write SQL.

---

### Chunk 06: the docs say what is true, and the contract artifacts track

**Type:** doc-only

**Spec.** The wave changes what the product can do, so the surfaces that state that change
with it — including the three stale claims the audit found (design.md § "Three stale claims"):

- **`docs/capability-truth.md`** gains an audio-material row (place a sample, conform it,
  round-trip it) with the wave's honest boundaries: no acquisition, no offline transform, no
  sampler assignment yet. This table is the anti-confabulation spine; it must not lag.
- **`docs/known-issues.md`** — "Human audio can't be read back through the bridge" is now
  half wrong: a *clip* comes back; a recorded take still does not. Split it accordingly.
- **`.prawduct/artifacts/authorship-model.md`** — open problem §2's stated reason ("Live
  won't let us create session audio clips") is refuted; the asset-store half stays open and
  points at wave 3.
- **`.prawduct/artifacts/sync-boundary-contract.md`** — phases 6, 11 and 13 gain their audio
  behaviour. It is a description that tracks the code, so it changes when the code does.
- **`docs/song-authoring-conventions.md`** — how a song references a sample, and D3's
  conform-in-Live-first doctrine.
- **Change-log**, `learnings.md` if the wave taught anything durable, the
  operator-verification entries, and the backlog: close **#284** and **#268**, update
  **#237** and **#330** with chunk 01's verdicts, and file wave 2 and 3 as items.

**Done when:** every surface above is edited or explicitly ruled inapplicable; the backlog
reflects reality.

### Chunk 07: the two refusals settle against chunk 01's verdicts

**Type:** code · **Foreign API:** Live Object Model (Live 12.4.x) · **Visual change:** no
· **Operator-gated:** no for the build (planner tests carry it), yes for the live
"Done when" (it is chunk 03's live clause, re-run over the two paths this chunk opens).

**Why it exists.** Chunk 03 shipped two `plan.blocked` refusals whose reasons say "run chunk
01": a linked clip whose `audio_file` changed (`sync/push/clips.py`) and an arrangement
placement whose source audio clip hosts an envelope (`sync/push/arrangement.py`). Chunk 01
has run, and `docs/research/audio-first-class/lom-probe-results.md` rows 16-16c hold the
answers. Leaving the refusals in place now would be a capability the project knows how to
build and declines to — `capability-truth.md` already says so.

**Spec.** Against the recorded verdicts, in the same modules chunk 03 owns:

1. **Re-pointed `audio_file` → delete-and-recreate that re-emits the ride** (rows 16, 16b).
   `create_audio_clip` into an occupied slot is a hard error, and a recreate drops every
   envelope the clip hosted, so the plan is `delete_clip` → `create` (with the conform
   properties the create already carries) → re-emit each envelope the row hosts, in that
   order, as one planned sequence. The envelope re-emit reuses the envelopes phase's own
   planner, not a copy. A second push of the unchanged song still plans nothing.
2. **Envelope-hosting audio placement → the duplicate route** (row 16c).
   `duplicate_clip_to_arrangement` carries a ride off an audio session clip exactly as off a
   MIDI one, so an audio placement whose source clip is in `envelope_hosting_clip_ids` takes
   the duplicate-onto-cleared path MIDI already takes; envelope-free audio placements keep
   the direct `Track.create_audio_clip(path, beats)` call. The duplicate copies the
   *conformed* session clip, which closes the arrangement conform gap for those rows — the
   run's per-placement conform warning must stop firing for them and keep firing for the
   direct-create ones.
3. **Path error shapes** (row 17): the chunk-02 teaching-error mapping gains the third source
   string, `ValueError: Please provide an absolute path`.
4. `capability-truth.md`'s audio row drops the two "still refuse" sentences and says what
   the push now does; the arrangement-conform caveat narrows to envelope-free placements.

**Open, decided here rather than downstream:** whether *every* audio placement with a
session source should take the duplicate route so all of them arrive conformed. Not in this
chunk — the duplicate carries the session clip's length, not the placement's, and the
positional-link renumbering ARR-PROJ fixed was born in exactly that path; the extent gap is
a separate item, [#509](https://github.com/brookstalley/hallucinote/issues/509).
`[DECISION: only envelope-hosting audio placements duplicate; the rest keep
the direct create | the verdict licenses the envelope case and nothing more, and the length
mismatch is unprobed | user can override]`

**Tests.** Planner tests (no Live): changed path → delete, create, conform, envelope
re-emit in that order; unchanged row → no-op; envelope-hosting audio placement → duplicate
call and no conform warning; envelope-free → direct create and the warning; the new error
string maps to the teaching shape.

**Done when:** (0) `verify-api` — the recorded responses in probe rows 16, 16b, 16c and 17
(`docs/research/audio-first-class/lom-probe-results.md`, Live 12.4.5) are the contract the
sequence and the routing are built against, not the design prose; (0b) the two `_UNPROBED`
refusals are gone and nothing else in `sync/push` cites chunk 01 as pending; (1) planner
tests above green; (2) `capability-truth.md` updated;
(3) chunk 03's live "Done when" re-queued in `operator-verification.md` naming the two new
paths.

---

### Found and deferred, filed rather than carried

Three things this wave surfaced and filed. One was then fixed inside the wave after all:

- **[#504](https://github.com/brookstalley/hallucinote/issues/504)** — the arrangement
  integrity assert could not see a *dropped* audio placement: a missing audio clip reported
  `skipped_audio` (a `_CLEAN` member) rather than `missing_clip`. **Fixed in this wave**
  (`sync/arrangement_verify.py` checks presence for audio before skipping the note
  comparison; two tests), because chunk 03 made the clear-then-rebuild path destructive for
  audio and an assert blind to the drop it can cause was not deferrable. Close at merge.
- **[#505](https://github.com/brookstalley/hallucinote/issues/505)** — `replace=True`
  deletes a clip before Live can refuse the create. Mitigated here (the error names the
  emptied slot and points at undo), not prevented; prevention needs the fake LOM to model
  track kind.
- **[#506](https://github.com/brookstalley/hallucinote/issues/506)** — the arrangement
  summary credits tracks that were later skipped. Pre-existing; the new `placed_audio`
  counter follows the existing pattern on purpose so all three are fixed together.

### The link seam — found at chunk 05 integration, filed as [#507](https://github.com/brookstalley/hallucinote/issues/507)

A pull-ingested audio clip arrives **unlinked**. Pull never writes an `ableton_link` —
verified, not assumed: `link_db_to_ableton` has exactly two callers, `push/probe.py` and
`push/plan.py`, both push-side, and `probe_and_link`'s clip pass only *drops* stale links
(the SYN-3C8K cascade), never establishes one. So the clips phase sees `clip_at is None`
for a clip that demonstrably exists in Live, and plans a create into an occupied slot —
which needs `replace=True`, which deletes the user's dragged-in clip and rebuilds it on
every push until something links it.

This lands directly on the wave's definition of done ("a second line dragged in by hand
comes back on pull and survives a re-push"), so it closes inside wave 1, not after it.
**Correction, after chunk 03 landed and the fix was actually attempted.** This section
first said the fix belongs in `probe_and_link`. That was wrong, and the reason is worth
keeping: **`probe_and_link` is a standalone `push_cli` subcommand and is not part of
`execute_push`.** Putting the reconcile there would fix the seam only for someone who
remembers to run a separate command, which is not the round trip the definition of done
describes.

**What actually happens today**, now that chunk 03 is readable rather than guessed at: an
unlinked audio row whose file is present plans `create(..., replace=True)`. The slot's
existing clip is deleted and rebuilt from the same file, then re-conformed from the DB. So
this is **churn plus loss of un-modeled hand work** — warp *markers* are the concrete
casualty, since the DB models warp mode but not individual markers — rather than loss of
the sample. Bounded, real, and wrong.

**Where it should go is a design decision, not a patch**, and there are three candidates
with different owners: pull writes the link when it ingests (crosses the "links are
push-owned" boundary, but pull is what actually observed the correspondence); the clips
phase records it (planners produce plans and never write, so it would need the link to come
back through `apply_push_results`); or `execute_push` gains a session-clip reconcile pass of
its own. Deciding that at the end of a long wave, against a phase whose destructive
reconcile is itself waiting on chunk 01's verdict, is how a considered fix becomes a
regression. **Filed instead**, with this analysis, and named in the definition of done
below so the wave cannot be called finished while it stands. It is
[#507](https://github.com/brookstalley/hallucinote/issues/507), at `stage: requirements`
because the choice of home is the work.

## Definition of done (the wave)

A movie line copied into `songs/<slug>/assets/`, referenced from `build.py`, pushes into a
Live set as a warped, transposed audio clip in the session and as a placement in the
arrangement (**the arrangement copy carries conform only when its clip hosts an envelope** —
that placement duplicates the conformed session clip; an envelope-free one is a direct create
at Live's defaults and the run says so); a volume ride
authored under it pushes; a second line dragged in by hand in Live comes back on pull and
survives a re-push; and `capability-truth.md` says exactly that and no more.

**Not met yet, and these are the three things standing in the way:**

1. ~~**Chunk 01 has not run.**~~ It ran 2026-09-09 (Live 12.4.5). ~~The two paths that
   refused pending its verdicts still refuse~~ — **chunk 07** built the rule the same day:
   a re-pointed (or MIDI-occupied) slot is delete → create → conform → re-emit envelopes, and
   an envelope-hosting audio placement duplicates like a MIDI one, which also carries its
   conform. Envelope-free placements keep the direct create and its conform gap; the
   extent gap is route-independent and filed as
   [#509](https://github.com/brookstalley/hallucinote/issues/509). Nothing in `sync/push`
   cites chunk 01 as pending.
2. **The link seam** above ([#507](https://github.com/brookstalley/hallucinote/issues/507))
   — "survives a re-push" is the clause it fails.
3. **Nothing has been live-verified on the audio path.** The only live evidence this wave
   has is a pure-MIDI regression check (a concurrent session's push: 58/58 clips, 116/116
   placements, no orphans), which discharges R6.4 and says nothing about audio.

`capability-truth.md` reflects exactly this: the audio row ships at ◐, not ✓.
