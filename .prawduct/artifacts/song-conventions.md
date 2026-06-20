# Song Conventions

How composer intent + decision rationale live alongside the structured song data, and how the LLM retrieves it before composing.

> **Companion docs.** This is the **WHY** corpus (intent: `decisions/` + `annotations/`, the frontmatter schema, the controlled mix/groove **tag vocabulary**). The **WHAT/HOW of code** (build.py, generators, the harmony axis, the `feel` dict) lives in [`../../docs/song-authoring-conventions.md`](../../docs/song-authoring-conventions.md); the **dimension taxonomy** in [`arrangement-model.md`](arrangement-model.md); the intent *mechanism* (markdown, not the retired DB `annotations` table) is governed by [`intent-architecture.md`](intent-architecture.md).

`/song-new` scaffolds the layout below from `tools/templates/song/`. (`songs/falling-walking/` is a **historical** worked example, not a template to copy.)

## Directory layout

```
songs/<song-name>/
  <song-name>.md          ← curated overview: concept, specs, form, build notes
  <slug>-<branch>.db      ← structured song data — one DB per git branch, gitignored (resolve_db_path)
  build.py                ← programmatic builder
  captured_session.json   ← optional initial-mix snapshot
  decisions/
    NN-slug.md            ← one deliberate choice per file (ADR-shaped; or dated YYYY-MM-DD-slug.md — the `date` frontmatter field is the queryable *when*)
  annotations/
    slug.md               ← scoped intent notes (timeless, no date required)
  attempts/
    YYYY-MM-DD-slug.md    ← attempt ledger: one tried move + its outcome per file (ATL-7K3M)
  tests/
    test_*.py
```

Files in `decisions/`, `annotations/`, and `attempts/` are atomic — one decision / one scoped intent / one tried move per file. The `<song-name>.md` is the curated overview; the dated/scoped files are the high-volume detail layer.

## When does something become a `decisions/` file vs an `annotations/` file vs stay in the overview?

**Decision** (`decisions/`) — a deliberate choice with rationale that future composers should see. ADR-shaped: a `date` field in frontmatter (the queryable *when*) and the *why* behind it. Filenames come in two flavors in the wild — `NN-slug.md` (the `/song-new` scaffolder default — ordering + a stable id) and `YYYY-MM-DD-slug.md` (historical songs); the filename only orders the file, the `date` field is what's queried.

> Example: "On 2026-05-26 we dropped the chorus pad re-articulation stabs because they retrigger the patch's slow-attack envelope, killing the bloom. The MIDI showed an 8-beat sustain but the audible note effectively ended at the first stab. Each chord now holds 7.5 beats — short breath at chord change, long bloom in between."

**Annotation** (`annotations/`) — timeless scoped intent. Not dated. Describes how a section/track/song *is* or *should feel*, not a change.

> Example: "Verse is sad, like weight getting worse. 8 bars of Dm = the 'seeking' — ear hunts for movement that won't come. Bass walks D → G → B♭ → A; harmonic rhythm accelerates."

**Overview** (`<song-name>.md`) — the orienting document. Concept, structural specs, harmony tables, form chart, track index mapping, MIDI pitch reference, "where things live." This is what a new agent reads first.

**Attempt** (`attempts/`) — a move you *tried* and how it turned out, **including the ones you reverted**. Decisions record what you *kept* and why; attempts record the *path*, especially the dead ends, so a later pass doesn't re-try them.

> Example: "v12: notch at ~2.2 kHz still let the bagpipes overwhelm the vocal and hollowed the tone. Reverted; gated under the vocal phrases instead (kept)." — `outcome: failed`, `resolution: reverted`, `related:` → the gate entry that worked.

The boundary heuristic: if it has a **date and a change you kept**, → `decisions/`. If it describes **what something is or should feel like**, → `annotations/`. If it's a **move you tried + how it turned out** (kept *or* reverted), → `attempts/`. If it's **reference data** (table of bar positions, MIDI pitch map, track list), → overview. A *tool* failure (a push glitch, a Live bug) is none of these — it's an `incoming-bugs/` report.

## Frontmatter schema

Every file in `decisions/`, `annotations/`, and `attempts/` opens with a YAML-subset frontmatter block:

```yaml
---
date: 2026-05-26          # required for decisions; ISO YYYY-MM-DD
kind: decision            # decision | annotation | structural-fact | attempt
scope: track-time         # song | time | track | track-time
track: 03 Synth Bass      # required when scope ∈ {track, track-time}; matches tracks.name
bars: [33, 40]            # required when scope ∈ {time, track-time}; [start] for point, [start, end] for range
tags: [dim7, bridge]      # optional; inline-list literal
related: [decisions/05-bridge.md]           # optional cross-links
outcome: failed           # attempt only, REQUIRED: worked | partial | failed
resolution: reverted      # attempt only, REQUIRED: kept | reverted | superseded
---
```

Then the prose body.

### Field reference

| Field | Type | Required when | Notes |
|---|---|---|---|
| `kind` | enum | always | `decision`, `annotation`, `structural-fact`, or `attempt` |
| `scope` | enum | always | `song`, `time`, `track`, or `track-time` |
| `date` | ISO date | `kind=decision` | `YYYY-MM-DD`; optional for annotations; conventional on attempts |
| `track` | string | `scope ∈ {track, track-time}` | Matches `tracks.name` in the DB (resolves to track_id on reindex) |
| `bars` | inline list of numbers | `scope ∈ {time, track-time}` | `[start]` (point) or `[start, end]` (half-open range); end > start |
| `tags` | inline list of strings | optional | Free-form taxonomy; queryable via FTS5 |
| `related` | inline list of paths | optional | Cross-links to other refs (path-relative-to-repo-root); on an attempt, links a failed move forward to the one that replaced it |
| `outcome` | enum | `kind=attempt` (required) | `worked`, `partial`, or `failed`. **Forbidden on every other kind.** |
| `resolution` | enum | `kind=attempt` (required) | `kept`, `reverted`, or `superseded`. **Forbidden on every other kind.** |

### Controlled `tags` vocabulary for mix + groove intent

`tags` are free-form, but two families carry a **controlled vocabulary** that the
analysis surfaces read (the masking analyzer and the holistic mix interpreter).
Using these exact tags lets the interpreter recall intent reliably instead of
guessing from prose. Markdown stays the single authored home for this intent —
there is NO structured DB field (see `.prawduct/artifacts/intent-architecture.md`).

**Mix-intent (per element / per section) — gates masking advice:**

| Tag | Meaning | Analyzer behaviour |
|---|---|---|
| `focal` | meant to be intelligible / must win here | flag anything masking it |
| `submerged` | deliberately buried as atmosphere | don't flag *its* being masked; instead check the element meant to pierce still pierces |
| `blend-group` | 2+ parts meant to fuse into one timbre | never flag intra-group masking; treat as one element |
| `density` | section is wash/density-intended | don't chase separation; only check the declared-to-pierce element |
| `clarity` | (default, usually implicit) | full masking analysis |

**Microtiming intent (groove) — recorded WHY for the `feel` offsets in `build.py`:**

`feel` · `groove` · `push` · `drag` · `swing` · `syncopation`

The `feel` numeric offsets are the WHAT (in `build.py`, → `notes.start_beats`);
these tags + prose are the WHY. A *relational* groove (the tension *between*
parts — "drums tight, guitar drags 25 ms") is **section-scoped** (`scope: time`),
because the section is where it's true; a single-part nuance is `track-time`.

**Scope guidance:** relationship/section feel → `scope: song`/`time`; per-element
mix-intent → `scope: track` or `track-time`; precise, bar-addressable intent →
`scope: track-time` + `bars`. Most micro-details ride as prose bullets inside the
relevant section/track file — no one-file-per-detail explosion.

### Parser rules

- Inline lists only — `[a, b, c]`. Block lists (`- a\n- b`) are NOT supported.
- Strings may be quoted (`"01 Drums"`) or bare (`01 Drums`).
- Unknown keys raise an error — catches typos at index time.
- Duplicate keys raise an error.
- Blank lines and `# comments` inside the frontmatter block are ignored.

### The attempt ledger (kind: attempt) — ATL-7K3M

An attempt records one tried move and how it turned out. Its value is the **negative
trail**: a `failed`/`reverted` entry stops a later pass from re-trying a known dead end. A
correction is **two linked entries** — the failed move's `related:` points forward to the
move that replaced it. `outcome` and `resolution` are both **required** on an attempt and
**forbidden** on every other kind.

```yaml
# songs/highland/attempts/2026-06-14-bagpipes-notch.md
---
date: 2026-06-14
kind: attempt
scope: track
track: Bagpipes
outcome: failed
resolution: reverted
tags: [mix, notch-filter, masking]
related: [songs/highland/attempts/2026-06-14-bagpipes-gate.md]   # → what worked instead
---
v12: notch at ~2.2 kHz still let the chanter overwhelm the vocal, and it hollowed the
bagpipe tone. Reverted.
```

```yaml
# songs/highland/attempts/2026-06-14-bagpipes-gate.md
---
date: 2026-06-14
kind: attempt
scope: track
track: Bagpipes
outcome: worked
resolution: kept
tags: [mix, noise-gate, masking]
---
v13: gated the bagpipes under the vocal's phrases (sidechained to the vocal). Drone holds
its timbre, clears space when the vocal enters. Kept.
```

**What belongs here vs not.** Musical-craft moves only — composition, arrangement, sound-
design, mix. Revealed *intent* ("the chorus should be the payoff") is an `annotation`, not
an attempt. A choice you *kept* with rationale you want future composers to see is a
`decision`. A *tool* failure (a push glitch, a stale server, a Live bug) is an
`incoming-bugs/` report. The ledger is **per-song** and **never a verdict** — a `failed`
row means "didn't achieve its goal *in this song*," read like a `--defensive` constraint,
not "never do this."

## Retrieval

The LLM retrieves relevant decisions + annotations via the `/song-context` skill before non-trivial composition work, and the **attempt ledger** via `/song-attempts` (or `song_context --kind attempt`) **before re-touching a part it has worked before**. Both query `markdown_refs` (the SQLite projection) with FTS5 fulltext, tag, kind, scope, track, and bar-range filters; `/song-attempts` adds an `--outcome` filter for "show me the dead ends."

The skill returns matching paths + previews. The LLM then `Read()`s the full files it wants.

## Indexing

`markdown_refs` is a rebuildable projection. Run:

```bash
python3 tools/reindex_markdown.py songs/<song-name>/<song-name>.db
```

The reindexer walks the corpus, upserts rows, refreshes FTS5, and tombstones rows whose file vanished. Idempotent — running twice in a row produces no diff.

## Authoring discipline

- One decision per file. Don't append to an existing decision file when a new decision arises — write a new file.
- Reference cross-cutting decisions via the `related` field, not by prose mention.
- Decision rationale captures *why* + *trade-off*, not just *what*. The mechanical change ("we dropped the stabs") belongs in the commit message; the *why* ("they retrigger the slow-attack envelope") belongs in the decision file.
- Annotations describe intent that should drive future work. If an annotation becomes stale (the intent changed), update it in place — annotations are timeless, but they evolve with the song.
- Filenames use lowercase letters, digits, hyphens. For decisions: `NN-short-slug.md` (the `/song-new` scaffolder default) or `YYYY-MM-DD-short-slug.md` (historical) — the filename only orders the file; the `date` frontmatter field is the queryable *when*. For annotations: `short-slug.md`.

## Relationship to the structured DB

The DB stores the *what* — notes, envelopes, devices, arrangement positions. The markdown corpus stores the *why*. Both are queryable; they reference each other:

- `markdown_refs.track_id` FK to `tracks(id)` resolves the frontmatter `track` field on reindex.
- `markdown_refs.song_id` FK to `songs(id)` resolves the `songs/<slug>/` path.
- The `related` cross-links are markdown-internal (point at other ref paths).

When the LLM records a deliberate decision during a compose session, it should write the file via `markdown_refs.write_markdown_ref(...)` — a one-call surface that serializes the frontmatter + body, writes the file to disk, upserts the `markdown_refs` projection row, refreshes FTS5, and emits the `MARKDOWN_REF_RECORDED` audit event threaded to the active `request_id`. This links the compose session to the decision it produced.

Pattern:

```python
from hallucinote.db import mutations as M
from hallucinote.markdown_refs import write_markdown_ref

with M.request(conn, actor="llm", intent="add C3' twist rationale",
               kind="compose", song_id=sid) as rid:
    write_markdown_ref(
        conn,
        path=Path("songs/falling-walking/decisions/2026-05-26-x.md"),
        repo_root=repo_root,
        body="...",
        frontmatter={"kind": "decision", "scope": "song", "date": "2026-05-26"},
        request_id=rid,
    )
```

Reindex of pre-existing files (via `reindex_corpus`) is a separate path that does NOT emit `MARKDOWN_REF_RECORDED` — projection rebuild is not a domain mutation.
