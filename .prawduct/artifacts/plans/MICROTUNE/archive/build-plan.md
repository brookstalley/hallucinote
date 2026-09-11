---
lifecycle: completed
archived: 2026-09-08
maintained: false
---

> **Archived — no longer maintained.** This plan records what was built, not what will be. Do not edit it to reflect later changes; write those where they are true.

# MICROTUNE — Compose songs in alternate tunings (pull-from-Live, isolated from the core)

**Branch:** `feat/microtune` (off `develop`). **Base for Critic/PR:** `develop`.
**Requirements:** `.prawduct/artifacts/alternate-tunings.md` (discovery, 2026-06-16).
**Critic mode:** per-chunk; Chunk 1 overridden to `final` (lands the persisted format, the
isolation seam, and the LOM acquisition path everything else depends on).

> **Blocking precondition for the whole build:** acquisition reads Live's LOM, so the
> **MCP↔Remote-Script version mismatch must be reconciled first** (`/ableton-mcp-install`
> + fully restart Live). Until then the LOM reads aren't trustworthy.
>
> **REFRAMED 2026-06-16 (live probe — see `api-notes-tuning.md`).** A read-only probe
> confirmed the drift (server `0.1.0+c487d2b32ba7` vs Remote Script `0.1.0+dc62195e594a`),
> but the bypass warning scopes corruption risk to **mutating calls only** — and MICROTUNE
> mutates nothing in Live (it only *reads* `song.tuning_system`). So the mismatch is **not**
> a real blocker here; read-only probes with `allow_version_mismatch=true` are safe. The
> actual remaining gate is narrower: **a tuning must be loaded in a Set we can read** to
> capture the loaded-tuning dict shapes (verify-api). Everything that consumes the *derived*
> tuning-data blob is shape-independent and can be built now.

---

## Requirements Confidence: **High** (verify-api closed 2026-06-19)

Problem, success, and scope each state in a sentence (below), and all four steering
decisions are settled. The one open unknown is the **exact LOM dict shapes** of
`note_tunings` / `reference_pitch` / `lowest_note` / `highest_note` (the Cycling '74 ref
types them "dictionary" without internal structure). Chunk 1's `verify-api` reads them off a
real loaded tuning before any field or column is locked — that closes it to High.

---

## The four decisions that shape this (from the user)

1. **Notes are integer MIDI 0–127.** The tuning reinterprets each MIDI number's pitch; no
   fractional/cents note column. (Per-note cents would be Route B — not this.)
2. **Acquisition is pull-from-Live, LOM-only — no external-file ingest.** The user loads a
   tuning in Live (drag onto the browser's Tuning section, or double-click a shipped one);
   Hallucinote reads `song.tuning_system` and **synthesizes** a cached `.ascl` from the
   reported cents/period/reference. The cached `.ascl` is a faithful **reconstruction**
   (sonically identical, re-draggable), not the byte-original — the LOM exposes no file path.
   No supply-a-path fallback (explicitly declined).
3. **The cached `.ascl` lives per-song** (`songs/<slug>/tunings/<name>.ascl`) so the song is
   self-contained and the push re-load instruction points at an exact file. Treated as
   immutable.
4. **Optimize for the 99.99% who never use this. Isolation over integration.** The core
   12-TET path must not get more complex or slower; lesser experience for the microtonal
   user is acceptable.

### What "isolation" buys us (unchanged by the acquisition choice)

The existing generators already take **MIDI integers**. The microtonal composer (the agent)
computes pitches with a tuning→MIDI mapper and feeds plain ints into the **unchanged**
generators.

- **No `tuning=` param threaded through `generators/*`; no generalizing `theory/model.py`'s
  `% 12`.** Both untouched. (Microtonal composers think in raw step indices anyway — the
  accepted "lesser experience.")
- All alt-tuning logic lives in a **new self-contained `hallucinote/tuning/` package** the
  core path never imports. The only core touchpoints are *additive and inert when unused*: a
  nullable `songs.tuning_ref`, a one-line lens caveat gated on it, and a push instruction
  gated on it.

## Persisted format (lock-in — decided)

- **`songs.tuning_ref TEXT` (nullable; `NULL` = 12-TET, every existing/future song's
  default)** = song-relative path to the cached `.ascl`. Added via `ALTER TABLE ADD COLUMN`
  (`db/connection.py`); existing songs read back `NULL`, untouched.
- **The LOM-derived tuning data is the mapper's source**, stored compactly so no parser is
  needed: `{name, step_count, period_cents, reference_note, step_cents:[…]}` (the cents
  array is small; a rare-path JSON blob is fine). The mapper needs only `step_count` +
  `reference_note`; `step_cents`/`period_cents` are kept for the `.ascl` writer and verify.
  **Built as a sibling nullable column `songs.tuning_data TEXT`** — set together with
  `tuning_ref` by `set_song_tuning` (both `NULL` = 12-TET). `step_cents` lists degrees
  `1..step_count` relative to the unison (the implicit 0-cent degree 0 is unlisted, Scala
  convention); the last entry is the period (never assumed 1200 — non-octave tunings repeat
  elsewhere). The blob carries no reference *frequency*: the reconstruction preserves the
  tuning's interval structure, not its absolute pitch anchor (a `reference_hz` field stays
  additive for later, post-verify-api, without breaking stored songs).
- **The cached `.ascl` is a derived artifact** (synthesized from the above) — the human
  re-load file, not a second source of truth.

No `.ascl` *parser* in v1 — we only ever **write** `.ascl` (pull-from-Live-only).

## Open assumptions / unknowns (vetoable)

- `[ASSUMPTION: LOM-derived tuning data stored as a small JSON blob keyed to the song (or a tunings row); cached .ascl is write-only/derived | LOW impact | override: store only the .ascl + parse it back]`
- `[ASSUMPTION: the tuning→MIDI mapper is low-level (raw step indices + period), no non-12 note-name spelling | LOW impact | accepted "lesser experience"]`
- `[ASSUMPTION: reconstructed .ascl stamps song.tuning_system.name; original file comments/name formatting are not preserved | LOW impact]`
- `[ASSUMPTION: a push-time re-read of song.tuning_system warns if the loaded tuning drifted from what the song stored; it does not block the push | LOW impact]`

## Surface enumeration

New isolated package `hallucinote/tuning/` (LOM reader, `.ascl` writer, cache, mapper,
push-time verify) · one DB column (`db/schema.sql` + `db/connection.py` migration) · song
mutator/query pass-through (`db/mutations/songs.py`, `db/queries.py`) · one lens caveat gated
on `tuning_ref` (`tools/*_lens.py`) · one push instruction + drift-warn gated on `tuning_ref`
(`sync/push/plan.py` / `push_cli.py`) · a worked `build.py` example · docs note. Core
generators, `theory/`, and 12-TET lens math are deliberately **absent** from this list.

---

### Chunk 1: `hallucinote/tuning/` — LOM read → store + cached `.ascl` writer → `tuning_ref` + degree→MIDI mapper  *(thin vertical slice — the spine)*

**Type:** code · **Critic mode:** final (persisted format + isolation + acquisition seam)
**Foreign API:** ableton-live-mcp (LOM `Song.tuning_system`)

- **Precondition:** version mismatch reconciled (see top); a tuning loaded in Live.
- **Done when:**
  0. **verify-api** — read `song.tuning_system.{name, note_tunings, pseudo_octave_in_cents,
     reference_pitch, lowest_note, highest_note}` off a real loaded tuning; record the actual
     dict/array shapes in new `.prawduct/artifacts/plans/MICROTUNE/api-notes-tuning.md`.
     Columns, writer, and tests derive from these shapes, not from docs.
     **PARTIAL as of 2026-06-16** (`api-notes-tuning.md`): None-branch + read path + version
     drift confirmed live; **loaded-tuning dict shapes still PENDING** (no tuning loadable
     while Live was in use). Per the plan decision, the shape-independent spine (steps 2–5)
     proceeds now; only `read.py`'s loaded-tuning *extraction* (step 1) waits on this.
  1. new `hallucinote/tuning/read.py` reads `song.tuning_system` → tuning data
     `{name, step_count, period_cents, reference_note, step_cents}` (handles `tuning_system
     is None` → 12-TET / no-op with a clear message). **Loaded-tuning extraction ships as a
     clearly-marked stub + fixture test** pending verify-api's PENDING dict shapes; the
     None/no-op branch is fully implemented now (confirmed live). Close the stub once a
     tuning can be read — that's the last step to flip Chunk 1 to High confidence.
  2. new `hallucinote/tuning/ascl.py` **writes** a valid `.ascl` from that data
     (cents entries + period + `! @ABL` name/reference directives).
  3. new `hallucinote/tuning/cache.py` writes the `.ascl` into `songs/<slug>/tunings/` and
     returns the song-relative ref.
  4. `songs.tuning_ref TEXT` nullable column + migration (`db/connection.py`); the tuning
     data blob persisted; `db/mutations/songs.py` sets both, `db/queries.py` returns them.
     `NULL` path proven unchanged.
  5. new `hallucinote/tuning/mapper.py`: `degree_to_midi(degree:int, period:int=0) -> int`
     = `reference_note + period*step_count + degree`, clamped to 0–127.
  6. Tests: writer round-trips (data → `.ascl` text → re-readable cents) on captured
     fixtures (EDO, a JI/ratio tuning, a non-octave e.g. Bohlen-Pierce); mapper arithmetic;
     cache + `tuning_ref` round-trip through the DB; one integration test that pulls a real
     loaded tuning end-to-end. **The core 12-TET suite stays green and `tuning/` is imported
     by nothing in the core path (grep-asserted).**
  7. `/prawduct:critic final`; blocking findings resolved; committed; Status `[x]`.
     **← governance checkpoint (architecture/isolation/acquisition validation).**

### Chunk 2: Worked authoring example (proves the core stays untouched — no Live needed)

**Type:** code · **Critic mode:** chunk

- **Done when:**
  1. A worked `build.py` authors a short phrase in a non-12 tuning by computing MIDI ints via
     `tuning.mapper` (reading the stored tuning data) and feeding them into the **existing,
     unmodified** generators (`chord_tones`, a harmony voicing helper). 19-EDO fixture now;
     Brooks's Continuum tuning once pulled.
  2. Tests: the example builds; emitted notes equal the expected MIDI step indices; a 12-TET
     build of the same shape is byte-identical to feeding the ints directly (generators
     didn't change).
  3. Critic chunk; committed; Status `[x]`.

### Chunk 3: Honesty + re-load — lens caveat + push instruction + drift-warn (all gated on `tuning_ref`)

**Type:** code · **Critic mode:** final · **Visual change:** yes (push instruction copy)
**Foreign API:** ableton-live-mcp (push-time re-read of `song.tuning_system`)

- **Done when:**
  1. When `songs.tuning_ref is not None`, the melody/recurrence lens output carries a
     one-line caveat ("song is in a non-12 tuning; interval readings are 12-TET-relative") —
     no change to the interval math, just a gated banner (honest confidence; full step-aware
     lenses stay out of scope).
  2. Push (`sync/push/plan.py` / `push_cli.py`) emits, before the phase loop, "load
     `songs/<slug>/tunings/<file>.ascl` into Live's Tuning section before playback" when
     `tuning_ref` is set — existing manual-guidance pattern. (Push can't load it; LOM is
     read-only.)
  3. Push re-reads `song.tuning_system` and **warns (non-blocking)** if the loaded tuning
     drifted from what the song stored (or none is loaded).
  4. Tests: caveat present iff `tuning_ref` set; instruction emitted iff set; drift-warn
     fires on mismatch/none, silent on match; 12-TET songs see none of it.
  5. `/prawduct:critic final` (or `cumulative` if one PR); operator-verification entry for the
     instruction copy; committed; `[x]`. **← governance checkpoint (before completion).**

### Chunk 4: Pull-from-Live acquisition command (the capture flow)  *(LIVE-GATED — closes v1)*

**Type:** code · **Critic mode:** chunk · **Foreign API:** ableton-live-mcp (read `song.tuning_system`)
**Hard precondition:** a Live session with an alternate tuning **actually loaded** in the
browser's Tuning section (the constraint that has blocked verify-api throughout).

> **Decision 2026-06-19 (Brooks):** ship v1 *with* acquisition, not the bolt-on alone — so the
> three Live-gated remainders become this final chunk rather than post-merge backlog. Merge to
> `develop` only after this chunk is `[x]`. The pull command is mostly orchestration over pieces
> already built in Chunks 1–3, so the chunk is small; its crux is the verify-api shape capture.

- **Done when:**
  0. **verify-api (closes Chunk 1 step 0):** with the tuning loaded, read
     `song.tuning_system.{name, note_tunings, pseudo_octave_in_cents, reference_pitch,
     lowest_note, highest_note}` via `ableton_probe(action='get',
     path='song.tuning_system', allow_version_mismatch=true)`; record the **actual** dict/array
     shapes in `api-notes-tuning.md`.
  1. Close `read.py`'s `_extract_loaded_tuning` stub against those shapes (map
     `note_tunings`→`step_cents`, `pseudo_octave_in_cents`→`period_cents`,
     `reference_pitch`/`lowest_note`→`reference_note`); replace the stub-raises test with a
     real captured-shape fixture. **Flips Chunk 1 to High confidence.**
  2. A user-invocable command — `[ASSUMPTION: a dedicated tiny skill (e.g. `/tuning-pull`),
     sibling to `/ableton-pull`, kept separate so the 99.99% `/ableton-pull` path stays
     unpolluted (isolation ethos) | LOW impact | override: fold as a `--tuning` mode of
     `/ableton-pull`]` — assembles the spine for a given song slug: probe Live →
     `read_tuning_system` → `cache_ascl` (writes `songs/<slug>/tunings/<name>.ascl`) →
     `set_song_tuning` (persists `tuning_ref`+`tuning_data`); reports the captured tuning + the
     push re-load instruction. Clear no-op message when no tuning is loaded (None branch).
  3. Tests: orchestration over the built pieces (None-branch no-op; loaded → cache+persist
     round-trip using the captured-shape fixture); re-pull is idempotent (immutable cache
     overwrites deterministically).
  4. **Wire discoverability** (see learnings — a new song skill is undiscoverable otherwise):
     primer + `CLAUDE.md` + `/song-workflow` + handoffs, per the song-workflow spine.
  5. **Operator-verify** (rolls in Chunk 3's queued entry): pull against a real loaded tuning
     end-to-end; verify the 3 drift cases + the push instruction copy live.
  6. Critic `chunk`; committed; `[x]`. **← then the merge to `develop` is unblocked.**

---

## Out of scope (explicit boundaries)

- **Programmatic load/set of a tuning** — LOM read-only; the manual drag stays. Push
  *instructs* + *warns*, never performs it.
- **External `.ascl` ingest / supply-a-path** — acquisition is pull-from-Live-only (declined).
  No `.ascl` parser ships.
- **Preserving the byte-original `.ascl`** — the cached file is a faithful reconstruction from
  the LOM reading (the LOM exposes no source path).
- **Full tuning-aware review lenses; threading tuning through core generators / `theory/`
  `% 12`; non-12 note-name spelling; fractional-pitch storage; `tunings` index table; M4L
  bridge** — none in v1.

## Status

- [x] Chunk 1: `tuning/` — LOM read + store + `.ascl` writer + cache + mapper + `tuning_ref`.
      **Now High confidence (2026-06-19):** verify-api closed against a real loaded tuning
      (Wendy Carlos gamma) — `read.py`'s `_extract_loaded_tuning` stub replaced with the
      confirmed-shape extraction (flat `list[float]` `note_tunings`; standard 12-key
      `reference_pitch` → `reference_note=(octave+2)*12+index`); `TuningExtractionNotReady`
      retired for `TuningReadError`; stub-raises test replaced with the captured-shape
      fixture (`GAMMA_LOADED_RAW`). Critic `final`: no blocking findings. Core 12-TET suite
      untouched; isolation grep-asserted.
- [x] Chunk 2: worked authoring example (core untouched) — `test_authoring_example.py`'s
      `author_cadence` is the worked `build.py` compose step; a 19-EDO I–V–I authored via
      `tuning.mapper` flows through the UNCHANGED `chord_tones`/`chord_pad` + the real
      note-insertion pipeline. Tests: emitted notes == expected MIDI step indices; full DB
      round-trip; 12-TET build byte-identical to feeding raw ints (mapper transparent for the
      99.99%). Critic `chunk`: no findings. (User-facing tuning *doc* deferred to Chunk 3,
      where the push re-load + lens-caveat story completes the picture.)
- [x] Chunk 3: lens caveat + push instruction + drift-warn (all gated on `tuning_ref`).
      `tools/tuning_caveat.py` (core, tuning-agnostic read via `Q.get_song_tuning`)
      adds a one-line 12-TET-relative caveat to the melody + recurrence lens output;
      `sync/push/tuning_notice.py` emits the cached-`.ascl` re-load instruction and a
      non-blocking drift-warn (re-reads `song.tuning_system`: warns on nothing-loaded /
      different-tuning, silent on match) before the phase loop in `execute_push`. Both
      are core-side and import nothing from `hallucinote.tuning` (isolation grep-asserted).
      User-facing `docs/alternate-tunings.md` + FAQ pointer. 34 new tests; 4057 green.
      **Honest-confidence note:** the drift live re-read's *loaded-tuning* scalar reads
      (`name` + `pseudo_octave_in_cents`) are unverified pending verify-api (same
      Live-availability gate as `read.py`'s stub); the nothing-loaded branch rests on the
      confirmed None shape; the compare is name+period only (coarse, not the cents array).
      Operator-verification entry queued (instruction copy + the 3 drift cases).
- [x] Chunk 4: pull-from-Live acquisition command (LIVE-GATED) — **done 2026-06-19** once a
      tuning could finally be loaded. (0) verify-api closed (`api-notes-tuning.md`); (1)
      `read.py` extraction stub closed against the confirmed shapes (Chunk 1 → High);
      (2) `/tuning-pull` skill + `hallucinote.tuning.pull_cli` (`tuning-pull apply`,
      registered in `cli.py` by lazy string — isolation preserved) assemble probe →
      `read_tuning_system` → `cache_ascl` → `persist_tuning`, with a clean None no-op that
      won't clobber an existing tuning; (3) tests: `test_pull_cli.py` (cache+persist
      round-trip on the captured shape, idempotent re-pull, no-op, unknown-song, malformed
      probe); (4) discoverability wired (`docs/alternate-tunings.md` capture section,
      `docs/song-workflow.md` + `/song-workflow` side-paths, both off the 99.99% mainline);
      (5) operator-verified LIVE (end-to-end pull + all 3 drift cases + push copy — see
      `operator-verification.md`). **Merge to `develop` now unblocked.**

## Context

A 0.01% feature built as an isolated bolt-on: a new `hallucinote/tuning/` package the core
never imports, plus two nullable columns (`tuning_ref` + `tuning_data`), one gated caveat,
one gated instruction. Acquisition is pull-from-Live (LOM read → reconstructed cached
`.ascl`); the build is read-only so the version-mismatch is non-blocking (REFRAMED). No
`.ascl` parser — we only write. The mapper needs just step-count + reference-note, so the
core authoring loop (Chunk 2) needs no Live.

**Chunks 1–3 done (2026-06-16).** Built: `tuning/{model,mapper,ascl,cache,read,store}.py`,
`songs.{tuning_ref,tuning_data}` columns + migration + `set_song_tuning`/`get_song_tuning`,
`SONG_TUNING_SET` (Chunk 1); the 19-EDO worked authoring example (Chunk 2); the gated lens
caveat (`tools/tuning_caveat.py`) + push instruction/drift-warn (`sync/push/tuning_notice.py`)
+ `docs/alternate-tunings.md` (Chunk 3). All three core touchpoints (two nullable columns,
the lens caveat, the push instruction/drift-warn) are additive + NULL-inert; isolation
grep-asserted. **All chunks `[x]`.** Three items remain open, all gated on the SAME
Live-availability constraint (a tuning loaded in a readable Set), none in the v1 chunk scope:
(1) close `read.py`'s loaded-tuning *extraction* stub (verify-api step 0 PENDING — the sole
Medium→High remainder); (2) **wire the user-invocable acquisition command** — the spine exists
in parts (`read_tuning_system` → `cache_ascl` → `persist_tuning`) but nothing assembles them
into a `pull`-style command a composer runs to capture their loaded tuning (decision #2's
pull-from-Live flow); it depends on (1) and can't be exercised until a tuning is readable;
(3) operator-verify Chunk 3's drift live re-read + instruction copy (entry queued in
`operator-verification.md`). The worked example (Chunk 2) sidesteps (1)/(2) by constructing
`TuningData` directly, which is why authoring + push + caveat all work today without them.

**DECISION 2026-06-19 (Brooks): finish acquisition first** — do NOT merge the bolt-on alone.
The three remaining items are now **Chunk 4** (pull-from-Live command), which must be `[x]`
before the merge to `develop`. **Next session (Live + a loadable tuning required):** load a
tuning → run Chunk 4 (verify-api → close stub → build the command → wire discoverability →
operator-verify) → resolve the merge conflicts (the real one is the additive migration in
`db/connection.py`, which `develop` has moved under since branch point — resolve at final
merge, re-run migration round-trip tests) → `/prawduct:pr` into `develop`. Nothing further can
land without Live; the branch otherwise sits at 4068 green, Critic `final` clean.
