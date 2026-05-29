# Intent architecture — where intent lives, how it's recorded, how it changes

Decided 2026-05-28. Cross-cutting; the masking analyzer is the first heavy
consumer but this governs ALL analysis/advice surfaces. Read with
`intent-collaboration-model.md` (the stance) and `masking-analyzer-goals.md`
(the perceptual north star).

## The three layers (don't conflate them)

The word "intent" blurs three things that want three different homes:

| Layer | What it is | Home | Lifecycle |
|---|---|---|---|
| **WHAT** | the material facts — note times, velocities, gains, automation, the `feel` offsets | `build.py` → materialized to the **disposable** DB (`notes`, `envelopes`, …) | edited in `build.py`, re-run to rebuild |
| **WHY** | artistic / mix / groove intent — "the vocal owns the chorus", "the pad is submerged here", "the intro pushes for urgency" | the git-tracked **markdown corpus** (`songs/<slug>/annotations/*.md`) | timeless but evolves; updated in place |
| **WHY-IT-CHANGED** | the decision to change something, with rationale + trade-off | the git-tracked **markdown `decisions/*.md`** (dated ADRs) | append-only history |

The measurement (`MixReport`) is none of these — it's neutral description, in
`songs/<slug>/analysis/`.

## Why the DB is NOT an authoring home for intent

The song DB is **gitignored and routinely `rm`'d + rebuilt from `build.py`**
(`docs/collaboration.md`: "Delete the local DB … and run `build.py`"). Anything
authored only into the DB dies on rebuild and is never shared. The DB
`annotations` table proves it: **0 rows across all 14 song DBs** — nobody uses
it, because the real workflow authors intent in markdown (which survives) and
`build.py` itself points at markdown for intent. The table is not just redundant,
it's a data-loss trap. → **Retire it** (build-plan C2). The only justifiable DB
home for derived intent would be a *cache rebuilt by `build.py`/reindex*, never a
hand-authored surface — and we don't need that yet (LLM-first: project the
structured view at interpret time; promote to a cache only if prose proves too
slow/ambiguous in practice).

## Mix-intent is a tag vocabulary, not a schema

The markdown frontmatter already spans the full granularity range —
`scope` (song / time / track / track-time), `track`, `bars`, `tags`. So the
intent modes the masking analyzer needs are just a **controlled tag vocabulary**
on top of what exists. No table, no migration:

- **Mix-intent modes:** `focal`, `blend-group`, `submerged`, `density`
  (+ `clarity` as the default, usually left implicit).
- **Microtiming intent:** `feel`, `groove`, `push`, `drag`, `swing`,
  `syncopation`.

**Granularity by placement, not by store:**

| Granularity | File / scope | Example |
|---|---|---|
| whole song | `<slug>.md`, `scope: song` | overall vibe |
| section feel / relationship | `chorus-feel.md`, `scope: song`/`time` | "3rd chorus: crash louder mid-section (splash accent)"; "drums tight, guitar drags 25ms — the friction IS the groove" |
| per-track intent | `pad-intent.md`, `scope: track` | "pad submerged under the lead — atmosphere, don't surface it" |
| precise, bar-addressable | own file, `scope: track-time`, `bars: [89,90]` | when it must be *queryable by bar* |

A **relational** groove (the tension *between* parts) is section-scoped — the
section is the unit where it's true, not the part. A single-part nuance is
track-time. Most micro-details ride as prose bullets inside the relevant
section/track file — no tiny-file explosion.

## Microtiming specifically

`feel` (`generators/primitives.py`, a `Mapping[float,float]` of within-bar
position → beat shift) is the **WHAT** — baked per-part, per-section at
generation time into `notes.start_beats`. Its current gap: the code says
freeform feel intent *"lives in the LLM prompt"* — i.e. ephemeral. The fix is to
route that WHY to markdown (`tags: [feel, groove, …]`) like all other intent.

- **Designed evolution across sections** (push in intro → settle in verse → rush
  the last chorus) = different feel dicts per section + one section annotation
  each. The change is authored.
- **Lifecycle change** (v2 should be lazier) = feel dict changes in `build.py`,
  the section annotation is updated in place (current WHY), and the decision gets
  a dated `decisions/` file (WHY-IT-CHANGED). The decisions log IS the groove
  change-history.
- **Boundary:** `feel` is a *periodic* per-bar template. Within-section
  evolution (last intro bar pushes harder, a ritard, a one-off fill) is
  **aperiodic** → author the notes directly; don't grow `feel` into a timeline.
  Its intent is still just a scoped annotation.

## The read-side: measurement ↔ intent, generalized

Each DSP module is a pure measurement producer. The **holistic interpreter**
(build-plan C6) is the single surface that reads the whole `MixReport` + recalled
intent and reasons across metrics — masking, loudness, attribution, reverb, and
(C7) timing-deviation together. The loop (from `intent-collaboration-model.md`):

```
RECALL (/song-context, markdown)  →  MEASURE (MixReport, neutral, always)
  →  INTERPRET vs intent           →  matches intent: stay quiet
                                      contradicts CLEAR intent: surface as a question
                                      intent unknown + matters: ask ONE question
  →  CAPTURE the answer            →  write a markdown annotation (learn-back)
  →  NEVER RE-FLAG                 →  next run RECALL covers it
```

This is why intent must live where RECALL can reliably read it (markdown +
populated `markdown_refs`) — hence the F5 reindex-hygiene blocker (build-plan
C5). Learn-back writes a **markdown** annotation via `write_markdown_ref(...)`,
never a DB `annotations` row.

## Severity stays out of the DSP

No module computes intent-graded severity. `masking.py` emits `MaskingPair` /
`BedMasking` evidence; the interpreter grades it against recalled intent in
conversation, in the two-register model (directed → execute; volunteered →
question). This resolves the missing-"role-column" contradiction (there is no
structured role field; roles are LLM-read prose) and keeps the tool from being
"a meter that says you're doing it wrong."
