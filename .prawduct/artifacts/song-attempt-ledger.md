# Song Attempt Ledger — requirements (discovery, 2026-06-14)

**Status:** requirements (discovery captured; not yet built)
**Type:** feature — a per-song read/write surface for *what was tried and how it turned out*
**Stakes / risk:** medium. Internal tooling, single-user, no sensitive data — but
real lock-in once entries accumulate, so the storage shape is pinned here before code.
**Origin:** user, 2026-06-14 ("a log or ledger… that lets agents learn what worked and
what didn't"), then scoped in discovery to **per-song, augmenting annotations** with the
concrete example: *"we tried a notch filter on the bagpipes in v12, but they still
overwhelmed, so we reverted it and went to a noise gate."*

---

## 1. The problem (the gap three existing surfaces leave)

A song is made by iterating: try a move, hear/measure the result, keep it or back it
out, try something else. Today that **attempt → outcome → correction trail is not
recorded anywhere durable** — it lives only in the agent's working context and is gone
by the next session. The cost is **re-deriving dead ends**: nothing stops a later pass
from re-trying the notch filter that already failed in v12.

The three markdown surfaces a song already has each capture something adjacent but **not
this**:

| Surface | What it holds | Tense | What it does NOT hold |
|---|---|---|---|
| `decisions/` (`kind: decision`) | the *rationale* for a choice that was **made and kept** | forward ("why we did this") | the things we tried and abandoned |
| `annotations/` (`kind: annotation` / `structural-fact`) | **learned-back intent / structural facts** ("the chorus lifts") | current state | history; reverted attempts |
| *(missing)* **attempt ledger** | **try → outcome → what we did instead**, incl. dead ends | chronological | — |

Annotations carry "never re-flag" *intent* semantics; folding a reverted experiment into
them would pollute the intent layer with non-intent. So the ledger is a **distinct kind**,
not a stretched annotation — even though it **reuses the annotation machinery wholesale**
(see §4). That is what "augment the existing annotations" means here: same system, new kind.

---

## 2. What it is (one paragraph)

A per-song, append-mostly ledger of **attempts**: each entry records one thing tried
against a target (a part, a section, the whole mix), its **outcome** (worked / partial /
failed), and its **resolution** (kept / reverted / superseded-by →). Entries chain so a
correction reads as a narrative: *notch-filter (failed, reverted) → noise-gate (worked,
kept)*. It is **musical craft only**, **per-song**, and **pulled on demand** — the agent
(or user) queries it *before* re-trying something, to see whether it was already tried and
how it went.

**Feature-discovery three-liner (per `methodology/discovery.md` §"Discovery Recurs"):**
- **Problem:** reverted/failed attempts vanish; later passes re-try known dead ends.
- **Success:** before re-touching a part, `/song-context --kind attempt --track Bagpipes`
  returns "v12 notch filter → still overwhelmed → reverted → v13 noise gate (kept)", so the
  agent doesn't re-propose the notch.
- **Out of scope (this iteration):** cross-song promotion; auto-surfacing/push; any
  verdict or score; process/engineering lessons (those stay in prawduct learnings); a new
  versioning system.

---

## 3. Scope

**In:** musical-craft attempts (composition, arrangement, sound-design, mix); per-song;
negative results are first-class; pull-only retrieval; reuse of the existing markdown
corpus + FTS5 + write path.

**Explicitly out (recorded so it isn't silently assumed back in):**
- **Cross-song.** User scoped this per-song. A future "promote a generalizable lesson to a
  cross-song layer" is a *separate* item, not v1. (Contrast `project_cross_song_reuse`,
  which is shared *assets* — kits/grooves — not lessons.)
- **Push / auto-surface.** Retrieval is pull-only (user's choice). No briefing injection, no
  auto-surface at `/song-new` / `/compose-part` in v1.
- **Verdicts.** The ledger never grades or recommends — informs only (ruler-not-stamp,
  `feedback_great_art_not_software`). Its "what failed" rows are read the way
  `/song-context --defensive` already frames negation rows: *"read before composing
  against this,"* never *"don't do this."*
- **Process/tooling lessons.** "This push order was faster" is a prawduct learning or an
  incoming-bug, not a craft attempt. A lesson that's really a *tool gap* routes to
  `incoming-bugs/`, keeping the ledger about the art.

---

## 4. Design — reuse `markdown_refs`, add one kind

The corpus machinery (`src/hallucinote/markdown_refs.py`) already provides: a `kind`
vocabulary, `scope` (song/time/track/track-time), `track`, `bars`, `tags`, `related`
(linking), the `markdown_refs` projection + `markdown_refs_fts` FTS5 index, a one-call
LLM write surface (`write_markdown_ref`, which also emits the `MARKDOWN_REF_RECORDED`
audit event), and recall-on-read reindex. **~80% of this feature already exists.** The
delta:

1. **New `kind: attempt`** — extend `KINDS` (`markdown_refs.py:35`) and the `--kind`
   choices in `song_context.py:112` (and the decisions/annotations write CLI).
2. **Two new frontmatter keys** — extend `_ALLOWED_KEYS` (`:39`) + `Frontmatter` + the
   `_build_frontmatter` validation + `_serialize_markdown` field order:
   - `outcome`: `worked | partial | failed` (required when `kind: attempt`).
   - `resolution`: `kept | reverted | superseded` (required when `kind: attempt`;
     `superseded` pairs with a `related:` link to the successor entry).
   - Add `outcome` (and optionally `resolution`) as a first-class `markdown_refs` column
     via the **additive init_db migration** (`feedback_open_song_db_via_init_db`), so it's
     filterable. *(Minimal-migration fallback: carry outcome/resolution as `tags` instead —
     zero schema change — but a real column is recommended for queryability.)*
3. **Targeting reuses existing fields** — the bagpipes are `scope: track`, `track:
   Bagpipes`; a section-scoped move is `scope: track-time` + `bars: [..]`; a global mix
   move is `scope: song`. No new targeting vocabulary.
4. **Chains reuse `related`** — the failed entry links forward to the entry that replaced
   it; the ledger reads as a narrative.
5. **Storage location:** a dedicated `songs/<slug>/attempts/` directory (sibling to
   `decisions/` + `annotations/`), added to the discovery globs (`:263`). *(Alternative:
   `kind: attempt` files inside `annotations/`. Dedicated dir reads better in `git log` and
   keeps per-family globbing clean — recommended, low-stakes either way.)*

### Worked example — the bagpipe chain (two linked entries)

`songs/highland-anthem/attempts/2026-06-14-bagpipes-notch.md`
```
---
date: 2026-06-14
kind: attempt
scope: track
track: Bagpipes
outcome: failed
resolution: reverted
tags: [mix, notch-filter, masking, midrange]
related: [songs/highland-anthem/attempts/2026-06-14-bagpipes-gate.md]
---
v12: bagpipes were swamping the lead vocal in the 1.5–3 kHz band. Tried an EQ notch
at ~2.2 kHz on the Bagpipes channel. Cut enough to dent the drone but the chanter
harmonics still overwhelmed — and the notch hollowed the bagpipe tone. Reverted.
```

`songs/highland-anthem/attempts/2026-06-14-bagpipes-gate.md`
```
---
date: 2026-06-14
kind: attempt
scope: track
track: Bagpipes
outcome: worked
resolution: kept
tags: [mix, noise-gate, masking, midrange]
---
v13: instead of carving tone with a notch, gated the Bagpipes to duck them under
the vocal's phrases (sidechain the gate to the vocal). Drone holds its timbre,
clears space when the vocal enters. Kept.
```

---

## 5. Capture (write trigger)

`[ASSUMPTION: trigger | MED impact | user can correct]` — an attempt entry is written via
`write_markdown_ref` the **moment an attempt resolves** (kept / reverted / superseded),
which happens in two places:
- **Mid-iteration**, at a revert/replace (the bagpipe-revert moment) — the agent records
  it as it happens.
- **At the review checkpoints** (`/compose-review`, `/mix-review`) — the review prompts
  for any unlogged attempts since the last pass, the same learn-back moment annotations
  already use.

Low ceremony, **propose-and-react**: the agent drafts the entry and the user
confirms/edits, mirroring how annotations are written. This honors "augment the
annotations" — same mechanism, same checkpoints, plus the mid-iteration revert capture.

---

## 6. Retrieval (pull-only)

- **Mechanical retrieval is already there:** once `attempt` is an accepted kind,
  `Q.find_markdown_refs` surfaces it; `/song-context --kind attempt --track Bagpipes`
  (or a fulltext topic) returns the chain. The `--defensive` rendering mode already frames
  failed/negation rows as *"read before composing against this"* — the precise stance the
  ledger wants for "what didn't work."
- **Headline query (recommended thin skill `/song-attempts`):** "what have we already
  tried on `<target>`, and how did it go?" — a discoverable, single-purpose entry over the
  same query, scoped to `kind: attempt`. Pull-only tools get missed
  (`feedback`-grade lesson from today's melody-recurrence read-side discovery bug), so a
  named skill that screams its purpose beats a flag for adoption. *(If we'd rather not add
  a skill: document `/song-context --kind attempt` and stop there — mechanically
  sufficient.)*

---

## 7. Build surface + honest sizing

Touch list (framework provides the mechanism; content lives in the private songs repo —
the `project_root_contract_shipped` split):
- `markdown_refs.py` — new kind, two keys, validation, serialize order, new glob, schema column.
- `db/connection.py` `init_db` — additive `outcome`/`resolution` column migration.
- `db/queries.py` — (only if outcome becomes a filterable column) a kind/outcome filter.
- `tools/song_context.py` — `attempt` in `--kind` choices.
- the decisions/annotations **write** CLI (`tools/decisions_cli.py` precedent) — an attempt write path.
- `tools/scaffold_song.py` / `/song-new` — create `attempts/` on scaffold.
- skills: thin `/song-attempts` (retrieval) + capture wiring in `/compose-review` +
  `/mix-review`; discoverability-spine wiring (CLAUDE.md + `/song-workflow` +
  `docs/song-authoring-conventions.md`) per `project_song_workflow_discoverability_spine`.
- tests: parser accepts the new kind+keys and rejects bad outcome/resolution values;
  reindex picks up `attempts/`; round-trip of the worked example; query filters by kind.

**Sizing: small core, medium with full wiring.** The core (kind + fields + query) is
small because the corpus machinery already exists. The wiring (write path, scaffold,
two review checkpoints, the discoverability spine, docs, tests) is what makes it a medium.
No new infrastructure, no new index, no new query engine.

---

## 8. Open choices (low-stakes, reactable — not blocking)

1. **Naming** — `attempts/` + `kind: attempt` + `/song-attempts` (recommended) vs the
   user's word "ledger" (`ledger/` + `kind: ledger`). Pure ergonomics.
2. **`outcome`/`resolution` as first-class columns** (recommended, queryable, additive
   migration) **vs tags-only** (zero migration, less queryable).
3. **Dedicated `/song-attempts` skill** (recommended for discoverability) **vs documented
   `/song-context --kind attempt`** (zero new skill).
4. **Dir** — dedicated `attempts/` (recommended) vs `kind: attempt` inside `annotations/`.

## 9. Requirements confidence

**High.** Firsthand scoping against the real plumbing (`markdown_refs.py`,
`song_context.py` read in discovery), one concrete user example driving the schema, and a
clean reuse path. The only labeled assumption is the write trigger (§5), vetoable.
