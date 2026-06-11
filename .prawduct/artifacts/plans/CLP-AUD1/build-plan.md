# CLP-AUD1 — Build Plan (audio-clip DB model)

Item: clip kind discriminator, file references, warp metadata (clip, L/L,
`stage: design` → ready; AUD-1M4V stage 0a — the foundation for CLP-AUD2, ENV-8H1T,
AUD-9R3V). Design: `.prawduct/artifacts/plans/CLP-AUD1/design.md`; wave-1 field set
user-locked 2026-06-10. One branch (`feature/clp-aud1-audio-clip-model`), one PR
into `develop`. Pure DB/engine work — no Live, no bridge.

## Requirements Confidence: **High**

- **Problem (one sentence):** The DB models clips as implicitly-MIDI, so audio
  material has no durable representation and every downstream audio capability
  (placement, envelopes, recording ingest) is blocked.
- **Success (one sentence):** Audio-clip rows with the locked wave-1 field set are
  creatable/updatable/deletable through event-emitting mutators with kind-guards on
  both sides (no notes on audio clips, no audio fields on MIDI clips), and the push
  planner refuses unsynced audio clips loudly.
- **Out of scope (one sentence):** Push/pull and bridge handlers (CLP-AUD2),
  envelope hosting (ENV-8H1T), take lanes (AUD-9R3V), warp markers (deferred).

**Why High:** the field set and units are user-locked and LOM-verified
(`lom-audio-clip-surface.md` §4, probe 1); the mutator/event/dual-guard patterns
are established house conventions; no foreign API is touched.

**Open assumptions / unknowns:**

- `[ASSUMPTION: warp_mode stored as Live's enum int with named constants in code
  (not a TEXT enum) — matches the LOM value domain directly and avoids a mapping
  that drifts | LOW impact | user can override]`
- `[ASSUMPTION: loop_start/loop_end excluded from wave 1 (not in the locked field
  set); additive columns later if conform-to-song needs them | LOW impact | user
  can correct]`
- `[ASSUMPTION: the song directory for relative-path resolution is the directory
  containing the song's build.py (= the songs-repo song folder); helper takes it
  as an explicit argument so the policy is caller-owned | MED impact | user can
  veto]`

**What would raise confidence:** N/A.

## Status

- [ ] Chunk 01: schema + audio-clip mutators + events (thin slice)
- [ ] Chunk 02: kind-guards across surfaces, path helper, planner refusal, docs
Context: chunk 01 committed (b1a3330): wave-1 columns + create_audio_clip mutator.
Chunk 02 built 2026-06-10: kind-guards sweep closed TWO holes beyond the named spec —
pull would have DELETED audio rows on every sync (session + arrangement apply paths,
now exempted+warned) and push_notes would have misreported audio clips as pushed.
Path helper landed package-top-level (`src/hallucinote/paths.py`) to stay stdlib-only
(audio/ drags numpy). 3154 passed. Next: cumulative Critic → PR. Parallel item ENV-7G4K is
file-disjoint except `src/hallucinote/db/schema.sql` (different regions — clips vs
envelopes CHECK); mechanical rebase-on-merge, whichever lands second.

## Scaffolding

Existing project — no scaffold work. Tests in `tests/unit/db/` and
`tests/unit/sync/` (pytest). Verification beyond tests: a throwaway build.py-style
script creates an audio track + audio clip against a scratch DB and dumps the row +
emitted events (no Live involved).

---

## Chunk 01 — schema + audio-clip mutators + events (thin slice)

The locked wave-1 columns land on `clips` via `_ADDED_COLUMNS`
(`src/hallucinote/db/connection.py`) + the canonical definitions in
`src/hallucinote/db/schema.sql` (design.md table — kind discriminator defaulting
`'midi'`, audio_file, audio_gain, pitch_coarse/fine, warping, warp_mode,
start/end markers, with the schema comment recording the dual beats/seconds marker
unit). `create_audio_clip` mutator in `src/hallucinote/db/mutations/clips.py` per
design.md "Mutator surface": audio-host-track guard (track `kind='audio'`),
audio_file required, `clip_created` event with kind + audio fields in payload;
`create_clip` writes `kind='midi'` explicitly. Export via
`src/hallucinote/db/mutations/__init__.py`.

- **Type:** code
- **Deliverables:** `src/hallucinote/db/schema.sql`,
  `src/hallucinote/db/connection.py`, `src/hallucinote/db/mutations/clips.py`,
  `src/hallucinote/db/mutations/__init__.py`; tests in
  `tests/unit/db/test_mutations.py` (+ schema test file if column presence is
  pinned there).
- **Tests:** create_audio_clip persists every wave-1 field + emits event with
  state-paired payload (house pattern); non-audio host track refused; missing
  audio_file refused; fresh-DB and existing-DB (`_ADDED_COLUMNS`) both yield the
  columns; legacy MIDI rows valid under the default; delete cascades unchanged.
- **Acceptance criteria:** scratch-DB script creates an audio clip and the row +
  event read back with the full locked field set; full suite green.
- **Done when:**
  1. Acceptance criteria met and tests pass
  2. `/prawduct:critic` run (inference: chunk) and blocking findings resolved
  3. Committed and chunk marked `[x]` in Status

## Chunk 02 — kind-guards across surfaces, path helper, planner refusal, docs

The discriminator becomes load-bearing everywhere it could be silently wrong:
`update_clip` whitelist gains audio fields with kind-guards both ways (audio fields
on MIDI clip → ValueError; kind immutable); note-write surfaces
(`src/hallucinote/db/mutations/` notes mutators) refuse audio-clip targets with a
teaching message; the push planner (`src/hallucinote/sync/push/clips.py`) refuses
`kind='audio'` clips loudly ("audio clip push is CLP-AUD2; row authored but not
synced") instead of emitting a MIDI create — pattern-scoped: every site that
assumes clips are MIDI, found by grep for the clip-create call + notes paths, not
by line number. New pure helper `resolve_audio_path(song_dir, ref)` (new
`src/hallucinote/audio/paths.py` or sibling) implementing the song-relative
decision. Data-model doc touch: the clips section of whichever engine doc records
table semantics (locate by grep at build time) gains the kind/audio-field rows.

- **Type:** cumulative-final
- **Deliverables:** `src/hallucinote/db/mutations/clips.py` (+ notes mutators
  file), `src/hallucinote/sync/push/clips.py`, new path helper module (landed as
  `src/hallucinote/paths.py` — package top-level so it stays stdlib-only; audio/
  drags numpy); tests in `tests/unit/db/test_mutations.py`,
  `tests/unit/sync/test_push_song.py`, `tests/unit/test_paths.py`; doc +
  `.prawduct/change-log.md` entry.
- **Tests:** update guards both directions; kind immutability; notes-on-audio
  refusal; planner refusal (warn text + no MIDI create emitted); path helper
  (relative resolves under song_dir, absolute passes through, POSIX separators);
  existing MIDI push behavior byte-identical (regression).
- **Acceptance criteria:** the item's verifiable signal — audio-clip rows are
  fully authorable with guards at every MIDI-assuming surface, and an unsynced
  audio clip can never silently push as MIDI.
- **Done when:**
  1. Acceptance criteria met and tests pass
  2. Committed, then `/prawduct:critic cumulative` against `develop...HEAD` clean —
     the `/prawduct:pr create` gate (base: develop)
  3. Chunk marked `[x]` in Status; backlog pass via `/prawduct:backlog`:
     CLP-AUD1 → shipped on merge, CLP-AUD2 note ("model landed, placement
     unblocked"), AUD-1M4V umbrella note (stage 0a done)

## Early Feedback Milestone

**Milestone chunk:** 01 — the scratch-DB script shows a real audio-clip row with
the locked field set and its emitted event.

## Governance Checkpoints

**Commit & PR cadence:** commit per chunk after its Critic passes; one PR into
`develop` after Chunk 02's cumulative review passes (`/prawduct:pr`, base develop).

- After Chunk 01: review the persisted shape against design.md's "questions the
  rows must answer" before guards spread the discriminator across surfaces (the
  schema is the lock-in; the guards are reversible).
