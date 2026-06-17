---
artifact: requirements
feature: alternate-tunings (MICROTUNE)
status: ready
discovery_date: 2026-06-16
build_plan: .prawduct/artifacts/plans/MICROTUNE/build-plan.md
---

# Requirements — Composing in alternate tuning systems (MICROTUNE)

## 1. Problem & success (one sentence each)

- **Problem.** Hallucinote can only author in 12-tone equal temperament; a composer who
  has loaded an alternate tuning in Live (EDO, just intonation, historical, arbitrary
  Scala/`.ascl`, including non-octave) has no way to have Hallucinote compose *in* that
  tuning.
- **Success.** After the composer loads a tuning in Live, Hallucinote pulls it, lets the
  agent author parts whose **integer-MIDI** notes land on the intended scale degrees of
  that tuning, and reminds the composer to keep the tuning loaded for playback.
- **Out of scope (one sentence).** Hallucinote does not *load or set* a tuning (the Live
  API forbids it), does not ingest loose `.ascl` files, and does not make the core 12-TET
  path one line more complex.

## 2. Motivation & audience

This is a deliberately **niche** capability: the vast majority of songs are and will remain
12-TET. The explicit product directive is to **optimize for the 99.99% who never touch this**
— alternate-tuning support must be a bolt-on that the core path never imports, and a *lesser*
experience for the microtonal composer is acceptable in exchange for zero core complexity.

**Persona — the microtonal composer.** Advanced; already works in alternate tunings (e.g. a
Haken Continuum user); thinks natively in *scale-degree / step indices*, not Western note
names. Comfortable with a one-command, file-light workflow. Needs Hallucinote to respect the
tuning Live is already in, not to reinvent tuning management.

## 3. Verified constraints (the findings that shape everything)

1. **Live's tuning is read-only over the Live Object Model.** `Song.tuning_system` is
   `read-only` / `observe`; there is **no LOM method to set or load** a tuning. The
   `TuningSystem` object exposes only readable fields: `name`, `note_tunings` (relative note
   tunings in cents), `pseudo_octave_in_cents` (the period — not always 1200),
   `reference_pitch`, `lowest_note`, `highest_note`. Confirmed live: a fresh Set reads
   `song.tuning_system == None` (= 12-TET). → *We can capture and verify a tuning; we can
   never apply one. Loading stays a manual drag; push instructs + warns.*
2. **The LOM exposes no path to the source `.ascl`.** Acquisition therefore reads the tuning
   *data* and **reconstructs** an equivalent `.ascl` — sonically identical and re-draggable,
   but not the byte-original file.
3. **Loading a tuning in Live (the manual step we depend on):** open the browser's **Tuning
   section** (View/▾ menu, or it auto-opens), then **double-click** a shipped tuning in the
   **Tunings** label *or* **drag an external `.ascl`/`.scl` onto the open Tuning section**.
   The tuning applies to the **whole Set**, is **saved in the Set**, and individual MIDI
   tracks can opt out via a per-track **Bypass Tuning** toggle.
4. **Notes remain integer MIDI 0–127.** Live's active tuning reinterprets each MIDI number's
   pitch; the composer selects *which* MIDI number via a scale-degree→MIDI mapper.

Sources: [Song.tuning_system](https://docs.cycling74.com/apiref/lom/song/) ·
[TuningSystem class](https://docs.cycling74.com/apiref/lom/tuningsystem/) ·
[Using Tuning Systems — Live 12 manual](https://www.ableton.com/en/live-manual/12/using-tuning-systems/).

## 4. The user-confirmed product decisions

1. **Integer-MIDI notes** — no fractional/cents note storage (that would be a different
   feature, "Route B" per-note pitch bend).
2. **Acquisition is pull-from-Live, LOM-only** — no external-file ingest, no supply-a-path
   fallback. The composer loads the tuning in Live; Hallucinote reads it and caches a
   reconstructed `.ascl`.
3. **Per-song cache** — the reconstructed `.ascl` lives at `songs/<slug>/tunings/<name>.ascl`
   so the song is self-contained and the push re-load instruction names an exact file.
4. **Isolation over integration** — all logic in a new `hallucinote/tuning/` package the core
   never imports; the only core touchpoints are additive and inert when a song is 12-TET.

## 5. Functional requirements

- **FR-1 (pull).** Given a tuning loaded in Live, a command reads `song.tuning_system` and
  derives `{name, step_count, period_cents, reference_note, step_cents}`. `tuning_system is
  None` → a clear "no alternate tuning loaded" no-op.
- **FR-2 (cache).** Reconstruct a valid `.ascl` from that data and write it to
  `songs/<slug>/tunings/`; record the song-relative path in `songs.tuning_ref`.
- **FR-3 (map).** `degree_to_midi(degree, period=0) = reference_note + period*step_count +
  degree`, clamped to 0–127. This is the only authoring primitive the agent needs; resulting
  ints flow into the **existing, unmodified** generators.
- **FR-4 (honesty).** When a song has a tuning, the melody/recurrence lens output carries a
  one-line caveat that interval readings are 12-TET-relative (the lens math is not changed).
- **FR-5 (re-load + drift).** Push emits "load `<cached .ascl>` into Live's Tuning section
  before playback" and, at push time, re-reads `song.tuning_system` and **warns
  (non-blocking)** if the loaded tuning drifted from what the song stored (or none is loaded).
- **FR-6 (core inertness).** A 12-TET song (`tuning_ref IS NULL`) sees none of the above; the
  core 12-TET test suite is unchanged and nothing in the core path imports `hallucinote/tuning/`
  (grep-asserted).

## 6. Persisted format — the consumer queries it must answer (lock-in)

`songs.tuning_ref` + the stored tuning-data blob are a versioned format every future consumer
depends on. The queries that drive the field set:

- *"Which tuning is this song authored in?"* → `name` + the cached `.ascl` (content).
- *"What MIDI number is scale-degree k?"* → `step_count` + `reference_note` (the mapper's only
  inputs).
- *"Can the human re-load exactly this tuning?"* → the cached `.ascl` at `tuning_ref`.
- *"Did the tuning loaded in Live drift from what this song expects?"* → `step_cents` +
  `period_cents` for the push-time compare.
- *"Is this song even in an alternate tuning?"* → `tuning_ref IS NULL` ⇔ 12-TET (the 99.99%).

The cached `.ascl` is a **derived** artifact (synthesized, write-only); the blob is the
source the mapper, writer, and verify all read. No `.ascl` parser ships (pull-from-Live-only).

## 7. Success criteria (evaluable)

1. Loading a tuning in Live + one pull command yields `songs/<slug>/tunings/*.ascl` and a
   non-null `songs.tuning_ref`.
2. The agent authors a part in a non-12 tuning (e.g. 19-EDO) and the emitted notes are the
   expected MIDI step indices.
3. Re-dragging the cached `.ascl` into Live produces a tuning whose `note_tunings` matches the
   originally-pulled cents (round-trip).
4. A 12-TET song's build output and test suite are byte-identical to pre-MICROTUNE; no core
   module imports `hallucinote/tuning/`.

## 8. Prior art / related

- **VISION.md** already names microtonal authorship as aspirational ("Microtonal music via
  Max for Live or per-voice pitch bend… the DB representation makes it possible").
- **Backlog M4L item** names Max for Live as the long-term escape hatch for LOM gaps — a
  *different* path; MICROTUNE is LOM-native and does not depend on it.
- **Route B (per-note pitch bend)** via `note_expression` already works for small expressive
  detuning — complementary, not superseded.

## 9. Open questions / what raises confidence to High

- **The exact LOM dict shapes** of `note_tunings` / `reference_pitch` / `lowest_note` /
  `highest_note` are typed only as "dictionary" in the reference. **Resolved by** Chunk 1's
  `verify-api` probe against a real loaded tuning, before any column or writer is locked
  (foreign-API discipline). This is the sole gap between Medium and High confidence.
- **Blocking precondition:** the MCP↔Remote-Script version mismatch must be reconciled
  (`/ableton-mcp-install` + restart Live) before any LOM read is trustworthy.
