# MICROTUNE — Compose songs in alternate tunings (pull-from-Live, isolated from the core)

**Branch:** `feat/microtune` (off `develop`). **Base for Critic/PR:** `develop`.
**Requirements:** `.prawduct/artifacts/alternate-tunings.md` (discovery, 2026-06-16).
**Critic mode:** per-chunk; Chunk 1 overridden to `final` (lands the persisted format, the
isolation seam, and the LOM acquisition path everything else depends on).

> **Blocking precondition for the whole build:** acquisition reads Live's LOM, so the
> **MCP↔Remote-Script version mismatch must be reconciled first** (`/ableton-mcp-install`
> + fully restart Live). Until then the LOM reads aren't trustworthy.

---

## Requirements Confidence: **Medium** → High after Chunk 1's verify-api

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
  1. new `hallucinote/tuning/read.py` reads `song.tuning_system` → tuning data
     `{name, step_count, period_cents, reference_note, step_cents}` (handles `tuning_system
     is None` → 12-TET / no-op with a clear message).
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

- [ ] Chunk 1: `tuning/` — LOM read + store + `.ascl` writer + cache + mapper + `tuning_ref`
- [ ] Chunk 2: worked authoring example (core untouched)
- [ ] Chunk 3: lens caveat + push instruction + drift-warn (gated)

## Context

A 0.01% feature built as an isolated bolt-on: a new `hallucinote/tuning/` package the core
never imports, plus one nullable column, one gated caveat, one gated instruction. Acquisition
is pull-from-Live (LOM read → reconstructed cached `.ascl`); the whole build is gated on the
version-mismatch fix. No `.ascl` parser — we only write. The mapper needs just step-count +
reference-note, so the core authoring loop (Chunk 2) needs no Live.
