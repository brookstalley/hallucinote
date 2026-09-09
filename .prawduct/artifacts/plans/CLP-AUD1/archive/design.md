---
lifecycle: superseded
archived: 2026-09-08
superseded_by: "brookstalley/hallucinote#284 (session-view audio clip creation and push/pull surface)"
unbuilt_at_archive: "no readable `## Status` roster — completeness cannot be read, and an unreadable plan is not evidence of completion"
maintained: false
---

> **Archived — no longer maintained.** This plan records what was built, not what will be. Do not edit it to reflect later changes; write those where they are true.

# CLP-AUD1 — Audio-Clip DB Model: Design

**Item:** clip kind discriminator + audio fields in the DB model. Stage 0a of the
AUD-1M4V umbrella — the foundation CLP-AUD2 (placement), ENV-8H1T (envelopes on
audio tracks), and AUD-9R3V (recording/ingest) all build on. Requirements: R1.3,
R2.1–R2.2 in `.prawduct/artifacts/plans/AUD-1M4V/discovery.md`; LOM property
evidence: `docs/research/audio-first-class/lom-audio-clip-surface.md` §4 +
`lom-probe-results.md` (probe 1). User locks: wave-1 field set (lock 3, warp
markers deferred); producer-led framing (lock 5).

## User decisions (2026-06-10, planning session)

**File references are song-relative.** Stored as POSIX paths relative to the song
directory (canonically an `assets/` subdir — where AUD-9R3V's recorded takes will
also land); resolved to absolute at push/analysis time. Absolute paths are allowed
and stored as-given (with a push-time existence check living in CLP-AUD2). Keeps
the private `hallucinote-songs` repo portable across machines/collaborators.

## Schema (wave-1 field set, locked)

`clips` table (`src/hallucinote/db/schema.sql`) gains, via the `_ADDED_COLUMNS`
idempotent-ALTER mechanism (`src/hallucinote/db/connection.py`):

| Column | Type | Semantics (LOM-verified units) |
|---|---|---|
| `kind` | TEXT NOT NULL DEFAULT 'midi' | `'midi'` \| `'audio'` discriminator |
| `audio_file` | TEXT | song-relative POSIX path (or absolute, stored as-given) |
| `audio_gain` | REAL | Live clip gain, **0–1 linear** |
| `pitch_coarse` | INTEGER | semitones, −48..+48 |
| `pitch_fine` | REAL | cents, −50..+50 |
| `warping` | INTEGER (0/1) | warp on/off |
| `warp_mode` | INTEGER | Live's warp-mode enum int; named constants in code |
| `start_marker` | REAL | **beats when warped, seconds when not** |
| `end_marker` | REAL | same dual unit |

Column-level CHECKs are kept minimal (SQLite ALTER limits + house style: "planner /
generator validates per kind"); the invariants live in the mutator (dual-layer
defense, same as envelopes):

- `kind='audio'` ⇒ `audio_file` NOT NULL; host track `kind='audio'`.
- `kind='midi'` ⇒ all audio columns NULL (unchanged legacy shape — every existing
  row is already valid under the DEFAULT).
- Audio clips host no notes; MIDI clips ignore audio fields.

`length_beats` stays NOT NULL for both kinds — it is the authored placement length
(slot/arrangement extent), not derived audio duration.

## Questions the rows must answer (persisted-format lock-in enumeration)

1. *What does clip X play?* → `audio_file` + resolution helper (analysis ingest,
   R1.3 — `src/hallucinote/audio/` reads the file by path).
2. *How is it conformed to the song?* → warping/warp_mode/markers/gain/pitch
   (CLP-AUD2's push emits these onto the created Live clip).
3. *Is this clip MIDI or audio?* → `kind` (push routing, envelope hosting in
   ENV-8H1T, note-op guards).
4. *Future (not blocked, not built):* takes/comping (AUD-9R3V) will model take
   lanes as their own rows referencing clips — nothing in wave 1 precludes that;
   warp markers (deferred, lock 3) are an additive child table later; loop points
   are additive columns later (excluded from the locked wave-1 set).

## Mutator surface

- New `create_audio_clip(conn, *, track_id, slot, length_beats, audio_file,
  name=None, gain=None, pitch_coarse=None, pitch_fine=None, warping=None,
  warp_mode=None, start_marker=None, end_marker=None, actor=..., ...) -> str` in
  `src/hallucinote/db/mutations/clips.py` — emits `clip_created` with `kind:
  'audio'` + audio fields in the payload (one event vocabulary; the kind is
  payload, not a new event constant).
- `create_clip` is unchanged in signature and writes `kind='midi'` explicitly.
- `update_clip`'s field whitelist gains the audio fields, guarded by kind (audio
  fields on a MIDI clip → ValueError, and vice versa for note-ish updates).
  `kind` itself is immutable (a conversion is delete+create, same doctrine as
  track_id/slot).
- Note-write surfaces (`insert_notes`, `replace_clip_notes`) refuse audio-clip
  targets with a teaching message.
- Path helper `resolve_audio_path(song_dir, ref)` (engine-side, pure) implements
  the relative-resolution decision; `audio_file` is stored exactly as authored.

## Out of scope (explicit)

- Push/pull of audio clips and the `create_audio_clip` bridge handlers — CLP-AUD2
  (stage 1). Until it ships, audio-clip rows are authorable but unsynced; the push
  planner's existing behavior for unknown clip kinds must *refuse loudly*, not
  silently emit a MIDI create (a planner guard is in this item's scope since this
  item introduces the second kind).
- Envelope hosting on audio tracks — ENV-8H1T (stage 2).
- Take lanes / comping model — AUD-9R3V (stage 3).
- Warp markers — deferred per lock 3.
- build.py *generator* helpers for audio (sampling patterns etc.) — the mutator +
  exports are the wave-1 authoring surface.
