# Terminology

This document fixes the meaning of overloaded terms — *session*, *arrangement*,
*clip* — across the four layers we touch: **Ableton's UI / Live API**, the
**Hallucinote MCP** (`hallucinote_mcp/`), the **DB schema**
(`src/hallucinote/db/schema.sql`), and the **sync layer**
(`src/hallucinote/sync/`).

If a term in code or in a plan disagrees with this doc, **this doc wins** —
fix the code (or the doc, after discussing). Treat this as load-bearing —
terminology drift is expensive to unwind.

## The two Live views

Ableton Live has two views of the same set of tracks:

| View | Live UI name | Live API | Playback model |
|---|---|---|---|
| Session view | **Session View** | `track.clip_slots[i].clip` | Non-linear; clip slots fired manually or via scenes |
| Arrangement view | **Arrangement View** | `track.arrangement_clips[i]` | Linear timeline; clips scheduled at time positions |

A `Clip` is a Live object that lives EITHER in a session-view slot OR at a
position on the arrangement timeline — same Clip class, different containers.
There is **no stable identity** for a Live `Clip` across operations; only
positional indices.

## "Session" — three distinct things

| Meaning | Where it lives | Disambiguator |
|---|---|---|
| Live's **Session View** (clip-slot grid) | Live UI; MCP `ableton_clip(location='session', …)` | Always qualify: **"Session View"** or **"session-view clip slot"** |
| Live's **Set / Song document** (the whole `.als` file) | Live API `Live.Song.Song`; MCP `ableton_session(…)` | Always qualify: **"Live Set"** or **"the Set"** when talking about the document |
| Our **sync session** (DB row pairing one Hallucinote song to one Live Set) | DB table `ableton_sessions`; sync layer's `session_id` param | Always qualify: **"sync session"** or **"ableton_sessions row"** |

The MCP tool `ableton_session(action='info' / 'set_tempo' / 'play' / …)` uses
Live's **Set** sense — it's the top-level document tool. Note that
`ableton_session(info)` returns tempo + signature + transport + loop + master
mixer + counts; it overlaps with `ableton_arrangement(info)` on
tempo/signature/loop.

The MCP tool name `ableton_session` is **misleading** given the three-way
ambiguity, but renaming it would ripple across the entire MCP surface; for
now we live with it. Always read it as "operate on the Set."

## "Arrangement" — view vs. placements

Three related concepts the word "arrangement" can mean:

| Concept | Definition | Where it lives |
|---|---|---|
| **Arrangement View** | Live's linear timeline view, as a UI surface | Live UI |
| **Arrangement view state** (a.k.a. "arrangement-view metadata") | View-level state: loop region, follow mode, zoom, total length | Live API `Live.Song.Song.loop_*`, etc.; MCP `ableton_arrangement(action='info'/'set_loop'/'control_view')` |
| **Arrangement clip** (a.k.a. "arrangement-clip placement") | A `Clip` placed at `(start_time, end_time)` on a track's timeline | Live API `track.arrangement_clips[i]`; DB `arrangement_clips` table; sync link kind `"arrangement_clip"` |
| **The arrangement *model*** (the compositional structure layer) | The Section / Recurrence-delta / Motif / variation-op + energy & harmony design — *how a song develops over time*. It **produces** the placements above; it is **not** the Live/DB placement concept | `.prawduct/artifacts/arrangement-model.md`; `hallucinote.arrangement` (materializes to `sections` / `arrangement_clips` / cues) |

**The DB `arrangement_clips` table holds arrangement clip placements.** Each
row is one Clip placed on one track at one time range:
`(song_id, track_id, clip_id, start_bar, end_bar)`.

**The MCP tool `ableton_arrangement(…)`** addresses the Arrangement *View* —
its scope is view state + cue points + view controls + loop + arrangement-level
tempo/sig (overlap with `ableton_session`). It does **NOT** today expose any
read action that returns the per-track clip-placement list — that gap remains
open.

When you read or write the word "arrangement" in code, comments, or a build
plan, ask: **is this about the view, or about clip placements?** If unclear
from context, qualify it: `arrangement_view_*`, `arrangement_clip(s)_*`.

### What `ableton_arrangement(action='info')` returns

`{tempo: bpm, signature: {numerator, denominator}, length_beats: float, loop: {…}, cue_count: int}` —
all **view-level / song-level** state, no per-track / per-clip data.

It is **not** a probe for the DB `arrangement` table. Confusing these two
is what triggered this doc.

## "Clip" — definition vs. placement

| Concept | Definition | Where it lives |
|---|---|---|
| **Clip (definition)** | The musical content: notes / audio path / display name / length | DB `clips` table; addressed by `clips.id` |
| **Clip placement** | An instance of a Clip in a session slot OR on the arrangement timeline | DB `arrangement` table (for arrangement placements); session-side: today the `clips` row carries the `slot` column directly (no separate placements table — a session clip IS a clip definition bound to one slot via `ableton_links`) |
| **Live `Clip` object** | The Live API's runtime representation | `track.clip_slots[i].clip` or `track.arrangement_clips[i]` — no separation of definition vs. placement on Live's side |

### Clip `kind` — MIDI vs. audio (CLP-AUD1)

The `clips` table carries a `kind` discriminator: `'midi'` (default; every
legacy row) or `'audio'`. MIDI clips host notes; audio clips host an
`audio_file` reference (song-relative POSIX path or absolute, stored
as-given — resolved via `hallucinote.paths.resolve_audio_path`) plus the
wave-1 conform fields (`audio_gain`, `pitch_coarse`/`pitch_fine`, `warping`,
`warp_mode`, `start_marker`/`end_marker`). See
`src/hallucinote/db/schema.sql` for column truth, including the
beats-when-warped / seconds-when-not marker-unit duality. `kind` is
immutable — converting a slot between MIDI and audio is delete+create, same
doctrine as `track_id`/`slot`. Kind-guards hold at every MIDI-assuming
surface: note mutators refuse audio targets, `update_clip` refuses audio
fields on MIDI rows, and the push planner refuses `kind='audio'` clips
loudly (audio-clip push/pull is CLP-AUD2 scope — rows are authorable but
unsynced until it ships).

Our DB **splits** definition from arrangement-side placement (so one Clip
content can be placed multiple times on the timeline). Live does not split
them. The sync layer reconciles by:

- **Session clips**: 1:1 binding via `ableton_links` between `clips.id` and
  `(session, track_index, clip_index)` where `clip_index` is the 1-based slot.
- **Arrangement clips**: 1:1 binding via `ableton_links` between an
  *arrangement-clips-table row* (`arrangement_clips.id`) and
  `(session, track_index, arrangement_clip_index)`.

### Index-name conventions

| Index name | Meaning | Bounds |
|---|---|---|
| `track_index` | 1-based position into `song.tracks` | `1 .. len(song.tracks)` |
| `return_index` | 1-based position into `song.return_tracks` | `1 .. len(song.return_tracks)` |
| `scene_index` | 1-based scene row | `1 .. len(song.scenes)` |
| `clip_index` | **Session-view** 1-based clip-slot index on a track | `1 .. len(track.clip_slots)` |
| `arrangement_clip_index` | 1-based index into `track.arrangement_clips` (order = start time) | `1 .. len(track.arrangement_clips)` |
| `device_index` | 1-based slot in the track / return device chain | `1 .. len(parent.devices)` |
| `cue_index` | 1-based index into `song.cue_points` | `1 .. song.cue_points` count |

`clip_index` is **only** the session-slot index. For arrangement placements,
always use the fully qualified `arrangement_clip_index`. The codebase
already follows this — `push.py` `_LINK_KINDS` distinguishes the
`"clip"` (session) and `"arrangement_clip"` (arrangement) kinds with the
matching field names.

## Layer-by-layer name map

| Concept | Live API | MCP tool / action | DB table | Mutator(s) | Event kind | Link kind |
|---|---|---|---|---|---|---|
| Arrangement clip placement | `track.arrangement_clips[i]` | `ableton_clip(action='list', location='arrangement', …)` | `arrangement_clips` | `add_arrangement_clip` / `remove_arrangement_clip` | `ARRANGEMENT_CLIP_ADDED` / `ARRANGEMENT_CLIP_REMOVED` | `arrangement_clip` |
| Session-view clip slot | `track.clip_slots[i].clip` | `ableton_clip(location='session', …)` | `clips` (with link to slot via `ableton_links`) | `create_clip` / `create_audio_clip` / `delete_clip` / `replace_clip_notes` (MIDI only) | `CLIP_CREATED` / `CLIP_DELETED` / `CLIP_NOTES_REPLACED` | `clip` |
| Arrangement-view metadata | `Live.Song.Song.{loop_*, view, …}` | `ableton_arrangement(action='info'/'set_loop'/'control_view')` | — (no single DB home; tempo/sig live in maps; loop has no DB home today) | — | — | — |
| Set-level state (the Live document) | `Live.Song.Song.{tempo, signature, master_track, transport}` | `ableton_session(action='info'/'set_tempo'/'set_signature'/'play'/'stop'/'seek'/'snapshot'/'set_master_property')` | varies (`tempo_map`, `time_signature_map`, master via `tracks(kind='master')`) | `set_master_*`, tempo/sig-map mutators | various | — |
| Track routing / monitor (RTE-1K9T) | `track.{output,input}_routing_type` + `current_monitoring_state` | `ableton_track(action='set_output_routing'/'set_input_routing'/'set_monitoring_state')` | `tracks.{output,input}_routing_kind/_target_id/_channel`, `tracks.monitoring_state` | `set_track_routing` | `TRACK_ROUTING_SET` | — (uses the `track` link) |
| Sync session (DB↔Live binding) | — | — | `ableton_sessions` + `ableton_links` | `create_ableton_session`, link mutators | — | — |

## Forbidden / loaded terms

- **"the arrangement"** (unqualified) — ambiguous between the view and the
  set of clip placements. Always qualify: *Arrangement View*,
  *arrangement clip placements*, *arrangement-view state*.
- **"session"** (unqualified) — three distinct meanings. Always qualify:
  *Session View*, *Live Set*, *sync session*.
- **"clip"** (unqualified) is acceptable when context disambiguates (e.g.,
  inside `ableton_clip(location='arrangement', …)`). Otherwise: *clip
  definition*, *session clip*, *arrangement clip*.
- **"clip_index"** alone is **session-only** — never use it for arrangement
  placements.

## Completed rename: `arrangement` → `arrangement_clip`

Shipped 2026-05-17. The DB table, mutators, event kinds, link kind, and
arg/payload name all carry the `arrangement_clip` form now. The MCP-side
`location='arrangement'` enum value is **deliberately unchanged** — it
names Live's Arrangement *View*, not our DB.

For any song DB created before this commit, run
`python tools/migrate_arrangement_clip.py <path/to/song.db>` — idempotent,
single transaction, rewrites the table + indexes + event-row `kind` values
+ `payload_json.arrangement_id` keys + `ableton_links.db_kind` rows.

## Where to add new term mappings

When a new MCP action / DB table / sync kind is added, add it to the
**Layer-by-layer name map** table above. When a Critic round catches a
terminology drift, link the finding back to this doc.
