# Arrangement Materialization — Systemic Redesign (arrangement-as-projection)

**Status:** DESIGN / DISCOVERY — captured 2026-06-22. Not yet built.
**Backlog tag:** ARR-PROJ (umbrella; supersedes the per-symptom patches listed in §10).
**Scope class:** behavior-changing refactor of the authorship spine. Stakes HIGH.
**Foreign API:** Ableton Live LOM (the MCP server ↔ Remote Script boundary).

This artifact is the output of a discovery-first pass requested 2026-06-22 ("really
step back … we've been playing whack-a-mole … understand and fix a systemic problem").
It supersedes the reflex of filing the two 2026-06-21 H-severity bugs as a six-part
convergent patch.

---

## 1. The problem — it is not N bugs, it is two foundational choices

The DB is the source of truth; Live's Arrangement is 100% derived. But the code treats
the derived artifact as **state to incrementally reconcile**, not as a **projection to
rebuild**. Every bug in the 13-month lineage (§10) traces to one of two choices:

### Choice 1 — the wrong primitive (`duplicate_to_arrangement`)
Note materialization copies a *session* clip onto the timeline via Live's
`Track.duplicate_clip_to_arrangement`. That primitive carries Live's **B-24 overlap-split
side effect**: duplicate onto an occupied region and Live splits/stacks the overlapped
clip. That single behavior *is* the 2026-06-21 stacking bug.

- The B-24 detection (`hallucinote_mcp/.../handlers/clip.py:752-822`) keys on **changed
  start-time**, so an exact-overlap stack (same start) slips through — flagged as
  **ARR-6T8N on 2026-05-18, the very first arrangement commit**, then dismissed as
  *"unlikely in real songs."* That dismissal is now the common case.
- **The primitive is not even necessary for plain MIDI notes.** Live exposes
  `Track.create_midi_clip(start, length)` + `Clip.set_notes()` — create an arrangement
  clip directly and fill it: no session source, no overlap-split. Confirmed present on
  the wire today (`ableton_clip(action='create', location='arrangement', notes=…)`,
  `clip.py:359-411`; `replace_notes(location='arrangement')`, `clip.py:845-883`).
- `duplicate_to_arrangement` is genuinely required for exactly **one** narrow feature
  (§5 caveats): arrangement clips cannot host mixer/pan/send/device-parameter envelopes
  (hard Live limit, `gaps.md:36-43`) — those must be authored on a session clip and
  inherited via duplicate.

### Choice 2 — the wrong strategy (positional-link incremental reconcile)
The DB↔Live correspondence lives in an `ableton_links` row storing Live's **positional**
`arrangement_clip_index` — an index Live silently renumbers on every delete. Maintaining
that link across Live-side edits is the *entire* purpose of the probe-and-link
reconciliation subsystem (`sync/push/probe.py:701-827`). SYN-3C8K, the FK-violation bug,
and SYN-4R7P are all link-reconciliation failures — and SYN-3C8K shipped a comment
asserting arrangement links "re-establish via the next push" that was false, which is
exactly what SYN-4R7P had to undo two weeks later.

### The missing guard
The WHAT (notes) is materialized once and **never diffed against source**. `note_count`
honestly reports the arrangement *copy's* own notes but nothing compares copy-vs-source,
so a stale or silently-dropped copy passes every cheap check while the render is corrupt
or silent. Push reports `OK`.

### Why patches can't converge
Each fix defended one more failure mode of a copy-with-positional-link model: *don't
double-materialize* (W10-A) → *refresh stale content* (PSH-6W2J) → *rebind drifted links*
(SYN-4R7P). The two 2026-06-21 bugs are those defenses **colliding**: re-duplicating onto
an occupied timeline (which the link model now permits) re-fires the B-24 split from
patch #1. The foundation keeps generating new interaction surfaces.

---

## 2. Goal / success criteria

1. Re-materializing a song's arrangement from the DB is **idempotent**: same DB → same
   arrangement, every push, regardless of the timeline's prior state.
2. A **post-materialization integrity assertion** compares each arrangement clip's real
   note content against its DB source and **HALTs + reports** on mismatch (no silent
   `OK`) — comparing the **collapsed audible set with tolerance**, NOT raw counts (see
   §6b). This single guard turns the silent corruptions into one-line failures.
3. The two H-severity 2026-06-21 bugs (stacking; bulk-drop) **cannot recur** by
   construction, not by added detection.
4. Materialization no longer depends on a positional link that Live renumbers; the
   probe-and-link arrangement-reconcile subsystem (SYN-3C8K/4R7P/FK complexity) is
   **removed or reduced to transient-within-a-push**, not extended.
5. The documented SYN-4R7P "delete the stale clip by hand → `execute --only arrangement`"
   recovery dance is **retired** from `skills/ableton-push/SKILL.md` and replaced by the
   single safe rebuild path.

---

## 3. Proposed architecture — arrangement as a pure projection of the DB

Stop reconciling; rebuild. Materialization becomes a deterministic projection:

```
PER TRACK that has arrangement placements and is being (re)materialized:
  clear the track's arrangement clips            # planned deletes, or a bulk-clear action
  for placement in DB.arrangement(track):
    clip = track.create_midi_clip(start, length) # direct create — NO duplicate, NO overlap-split
    materialize full clip from DB:               # notes, name, clip color, clip envelopes(see §5)
        clip.set_notes(DB.notes)
  assert sum(arrangement note_count) == DB note_count for the track   # HALT on mismatch
```

**What this deletes from existence:**
- B-24 stacking — no duplicate, no overlap-split, ever (for the note path).
- The silent one-track bulk-drop — every clip is created and filled explicitly, then
  verified; a drop becomes a halt, not a silent `OK`.
- The positional-link reconcile subsystem — the link becomes transient-within-a-push
  (used only to bind freshly-created clips for the cues phase that follows) or is removed
  entirely.
- The "~49 manual deletes" recovery and the foot-gun skill docs — clear+rebuild *is* the
  canonical path.

**Key economic finding (reshapes the build):** the create+fill primitives already exist
on the MCP wire. The redesign lives **mostly in the sync planner** (`plan_push_arrangement`),
not the Live-side handlers — so the MCP fingerprint barely moves (only an optional bulk
`clear_arrangement` action is new wire; even that can be expressed as planned per-clip
`delete` calls needing *zero* new wire). Smaller re-vendor + operator-verify surface than
the patch option would have required.

---

## 4. Load-bearing decisions (vetoable assumptions — correct any before build)

- `[ASSUMPTION: retire duplicate_to_arrangement for note-only placements; keep it ONLY
  for envelope-bearing placements | HIGH impact | user can override]` — the dual-path
  router (§5) is the crux. A note-only placement (the overwhelming common case) →
  create+fill; an envelope-bearing placement → duplicate-onto-cleared-region.
- `[ASSUMPTION: clear-then-rebuild per track, not whole-song atomic | MED impact]` — the
  unit of materialization is a track; a song-wide rebuild is N track rebuilds. (Per-track
  keeps the blast radius of a failure to one track and lets the integrity assert localize.)
- `[ASSUMPTION: the arrangement ableton_link becomes transient/removed, not maintained
  across pushes | HIGH impact]` — if rebuild is the only path, there is nothing to
  reconcile. The link, if kept at all, is bound fresh each push solely so the cues phase
  (which needs arrangement extent) can run. Confirm during design whether anything else
  reads the persisted arrangement link.
- `[ASSUMPTION: prefer the sync-planner-only implementation (existing wire) over a new
  Live-side bulk-clear, unless live testing shows planned per-clip deletes are too slow or
  index-fragile | MED impact]` — a dedicated `clear_arrangement` action is cleaner but
  flips the fingerprint; decide after the Chunk-1 live probe.
- `[ASSUMPTION: create+fill must materialize the FULL clip spec from the DB (notes +
  name + color + clip envelopes), not notes alone | MED impact]` — duplicate copied the
  whole clip; create+fill must not silently drop clip-level properties the DB knows.

---

## 5. The narrow exceptions the redesign MUST preserve

1. **Envelope-bearing clips (hard Live limit).** Arrangement clips can't host clip
   envelopes; the only way is author-on-session + `duplicate_to_arrangement` so the copy
   inherits them (`gaps.md:36-43`). The router sends these placements down the duplicate
   path — onto a **cleared** region (so no B-24 overlap). **Detection corrected by Chunk-2
   investigation (2026-06-22):** "envelope-bearing" is NOT a `target_clip_id` query as
   first framed. The DB CHECK constraint forbids `target_clip_id` on
   mixer/pan/send/device_parameter envelopes — those are *track/device/return*-scoped and
   materialized in the envelopes/performed phases, NOT on the arrangement clip. The clips
   that need the duplicate route are the ones a track-scoped envelope RIDES via a covering
   session clip (the W4-A snapshot-copy: `classify_envelope_route` → `session_clip`) plus
   `note_expression` (rides its note's clip). Detection reuses the authoritative
   `classify_envelope_route` + `_resolve_envelope_session_clip` (no routing drift), via the
   new `envelope_hosting_clip_ids(conn, song_id)` helper. Confirmed live on alien: exactly
   one host (an Alien Voice `send_level` clip); the Drums spike was therefore NOT
   envelope-lossy. See `chunk2-design.md` D4. This keeps the swell/ENV-4S2K feature
   working. Rare; bounded.
2. **Audio clips.** Session-view audio clips can't be created via LOM; arrangement audio
   placements come via duplicate or browser drag and are already an unlinked path
   (CLP-AUD1/2). Out of scope for the note-path redesign — leave the existing audio
   handling, route it explicitly.

---

## 6. Open questions — Live-gated (resolve via `verify-api` before/within the relevant chunk)

These CANNOT be root-caused headless and must be confirmed in an attended Ableton
session. They do not block the *design* (the projection architecture sidesteps all three),
but they gate the *build*:

1. **Why did one track silently drop all notes under bulk duplicate?** (2026-06-21 #13.)
   Suspected: ordering vs the following `performed_automation` pass, or a per-call vs
   bulk timing artifact. The redesign sidesteps it, but reproduce once to confirm the
   create+fill path does not inherit the same failure.
2. **Does `ableton_clip(list)` note_count truly mirror the source session clip**, or was
   that a Live duplicate-commit artifact? The code reads the arrangement clip directly
   (`clip.py:104-108`), so if it lies, the cause is Live-side. Confirm whether the
   integrity assertion can trust `get_notes_extended` on a freshly-created arrangement
   clip (it must, for the assert to be sound).
3. **Validate create+fill at scale on a real set** — create N arrangement clips +
   set_notes across a full song (≈49 placements, multiple tracks), confirm idempotent
   re-run and correct render. Confirm `create_midi_clip` start/length semantics match
   `_position_bar_to_beats`.

---

## 6a. Design constraints carried from project learnings (binding)

Surfaced via `/prawduct:learnings` 2026-06-22; each is load-bearing for the build:

- **Re-identify created arrangement clips by `start_time`, never `is`.** Live re-wraps
  API objects on every property access, so an identity scan silently fails. The create+fill
  path must resolve each freshly-created clip by stable value match (start_time), the same
  way the current spurious-clip handler does.
- **Resolve and validate ALL inputs before ANY write** (multi-write Live handlers). A
  mid-sequence raise during a track's clear+rebuild leaves Live half-materialized while the
  agent assumes nothing changed. Plan the whole track's materialization, validate, then
  execute; on partial failure, fail loud (per SYN-9F4K's fail-loud-on-empty-rack precedent).
- **The integrity assert must NOT read-back in the same callback as the write** ("trust the
  side effect, not the getter readback"). Read note counts in a fresh probe/callback, not
  inline after `set_notes`.
- **Tests use the re-wrapping fakes; the real proof is Live-gated.** A `list.append` fake
  passes for both stacking and dropping — exactly the false confidence that let these bugs
  ship. Unit-test the planner (it returns a `PushPlan`, testable without Live —
  `sync/push/_core.py:51`) and the handlers against `_ReWrappingFake*`
  (`hallucinote_mcp/tests/unit/`); the create+fill-at-scale and no-drop/no-stack proofs are
  Chunk-1 Live operator-verification, not unit tests.
- **All DB writes go through `db.mutations`** (no raw SQL in callers); cover the
  re-materialize cascade/FK behavior explicitly in tests.

**Tombstone-protection map — investigated and RULED OUT as the bulk-drop cause.** A
learning flags that an unregistered authorable event kind on a build-owned row gets
CASCADE-deleted by the next tombstone sweep (`db/mutations/build.py:86` `_LATEST_ACTOR_EVENTS`).
It does **not** explain the bulk-drop: arrangement notes live on the **session clip**
(`notes.clip_id → clips`; the `arrangement_clips` row is a placement with no own notes), the
clip row_kind has a special-case that protects it on any note-touching event, and the report
confirmed the **DB was intact** while the **Live** clips were empty. The redesign keeps the
arrangement a pure Live projection (no new persisted arrangement-note representation), so no
new event kind is introduced and this map needs no change. Recorded so the builder does not
chase a DB-tombstone cause for a Live-side materialization failure.

## 6b. Two 2026-06-22 reports folded in (post-design, same subsystem)

Two reports landed mid-design; both are on-target and binding:

**(A) `replace_notes` on an arrangement clip is non-atomic — leaves orphan notes**
(`incoming-bugs/2026-06-22-replace-notes-on-arrangement-clip-leaves-orphan-notes.md`, H).
The handler clears via a scoped `remove_notes_extended` derived from the *incoming* notes,
not a full-extent clear / `Clip.set_notes()`, so notes from an older write generation
survive (alien `Drums chorus2`: wrote 243, clip held 248 — 5 stale orphans with old
note_ids). **Binding constraint on the redesign:** the create+fill path MUST recreate the
clip — delete + `create_midi_clip` + `set_notes` on a **fresh** clip — and must NEVER
"optimize" to `replace_notes`-in-place on an existing arrangement clip, which is the
non-atomic path. Recreate sidesteps orphans by construction. (The `replace_notes` handler
bug is real for direct agent use and is filed separately, related to ARR-PROJ; the redesign
should also make `replace_notes` a true total-replace OR document it as
not-for-materialization.)

**(B) Systematic build↔Live arrangement verification capability**
(`incoming-bugs/2026-06-22-systematic-build-vs-live-arrangement-verification-capability.md`,
H capability). This is the spec for the integrity assert (Chunk 3) AND a new audit command.
It encodes **three mandatory normalizations** my first Chunk-3 framing got wrong — a raw
note_count compare cries wolf:

1. **Live collapses same-(pitch, start).** build.py legitimately authors stacked notes
   sharing pitch+start but differing in duration/velocity (e.g. `add_wildness`); Live holds
   one per (pitch,start). Compare the **distinct-(pitch,start) collapsed set**, not raw
   count (alien Human Riff chorus3: 332 raw DB → 305 Live, *faithful*).
2. **Float round-trip tolerance.** Compare start/duration with ε ≈ 1e-3 beats, pitch exact,
   velocity within a small tolerance (capture/probe introduces ~1e-7 noise).
3. **Read via the note API** (`get_notes_extended` / `ableton_note(list, location=
   'arrangement')`), NOT `ableton_clip list` note_count (which the bulk-drop bug showed can
   mirror the source session clip).

**New deliverable:** a `hallucinote verify-arrangement --song <slug>` audit command (fresh
build → per-clip canonical collapsed set vs Live, reporting `extra`/`missing`/`mismatch`
per (track, section), non-zero exit on divergence) — the **detection** layer complementing
the **prevention** (Chunk 3 push-time assert), sharing the same comparison logic. Reuses
`push-notes --changed`'s per-clip content fingerprint. This becomes a chunk in ARR-PROJ.

## 6c. Chunk-1 Live spike findings (2026-06-22) — architecture CONFIRMED

Attended Ableton session, alien set (5 MIDI tracks, faithful baseline), server
version-matched after a `/mcp` respawn. Probe sequence preserved at
`.prawduct/artifacts/plans/ARR-PROJ/chunk1-spike.py` (drives the real Drums track
via the in-process MCP TCP client; keeps note payloads out of agent context —
prints counts only). Two consecutive clear+create+fill rebuilds of the Drums
track (10 placements, ~2500 notes incl. a 771-note clip):

**Result — `pass1=True pass2=True idempotent=True net_noop_vs_baseline=True`.**
Every section's Live note_count matched the DB collapsed set exactly on both
passes; the second rebuild equalled the first; the track returned to byte-identical
baseline state (the mutation was a content no-op — fully reversible).

**§6 q1 (bulk-drop) — ANSWERED.** create+fill dropped nothing across two full
rebuilds. The drop cannot be reproduced *through the create+fill path*: there is
no `duplicate_to_arrangement`, no overlap-split, no session-copy step to lose. The
old bulk-drop's exact Live-side root cause stays uncharacterized (it lived in the
duplicate path the redesign deletes); reproducing it on the legacy path was not
pursued because the projection path provably sidesteps it. **B-24 stacking is
impossible by construction** — `create_midi_clip` makes a fresh empty clip at the
target beat; nothing overlaps, nothing splits.

**§6 q2 (note_count trust) — ANSWERED; trustworthy.** Both `ableton_clip(list)`
`note_count` (handler `clip.py:104-105`) and `ableton_note(list,
location='arrangement')` (`note.py:56`) call the SAME
`clip.get_notes_extended(0,128,0.0,clip.length)` on the **arrangement clip object
directly** — neither mirrors a session source by construction. Live confirmed: on
a source-less `create_midi_clip` clip (verse1), both reads returned 503 = the DB
collapsed count. A created arrangement clip has no session slot to mirror, so the
count can only be its own notes. **Refinement to §6b-B normalization #3:** the
integrity comparator must use the *note API* not because it reads a different
object, but because it needs note *content* (pitch/start/dur/vel tuples) for the
collapsed+tolerance compare — `clip(list)` gives only a bare count. The
"mirrors-the-source" symptom from the 2026-06-21 report, if real, is a Live-side
same-callback-readback staleness artifact (§6a), not a structural mirror — so the
assert MUST read in a fresh probe/callback (the spike did: a new `list` call after
the writes). Confirmed trustworthy under that discipline.

**§6b normalization #1 (Live collapses same-(pitch,start)) — CONFIRMED live.** DB
raw→collapsed: verse1 509→503, verse2 337→333, chorus3 771→770; Live held exactly
the collapsed count each time. A raw-count compare would have cried wolf on three
of ten clips. The comparator MUST collapse distinct-(pitch,start) before diffing.

**§6 q3 (create+fill at scale + semantics) — CONFIRMED.** `create_midi_clip(start,
length)` start/length semantics match `_position_bar_to_beats(start_bar)` +
`clip.length_beats` exactly (every clip resolved at the requested start within
1e-6, correct length). Idempotent at full-track scale across two rebuilds.

### Wire decision (Chunk-1d) — planner-deletes, NO new wire action

The arrangement-clip `delete` wire action **already exists** (`clip.py:455-507`:
`location='arrangement'` → `track.delete_clip(clip)` by 1-based index; indices
renumber down after each delete). The planner's own comment ("no MCP
arrangement-clip-delete action exists", `arrangement.py:130`) is **stale**.
Measured cost: descending-index delete cleared 10 clips in ~6.5–7.4s (~0.7s/clip);
create+fill ~5s/track (~0.5s/clip). A 5-track / ~49-placement song ≈ under a
minute end-to-end — acceptable.

**Decision: Chunk 2 uses planned per-clip `delete` calls (existing wire) →
ZERO MCP fingerprint change, no re-vendor. Chunk 6 (bulk `clear_arrangement`) is
NOT needed and is dropped unless a later, much larger song shows the per-clip loop
is too slow.** Planner constraint carried forward: emit deletes in **descending
index order** (or repeatedly delete index 1), and treat Live's post-delete
collection as renumbered — never cache an index across a delete.

**Open sub-item (acceptance):** an *audible* render of the rebuilt track was not
run — the note-API read-back proves note-for-note fidelity (stronger than audio for
counts), and `net_noop_vs_baseline=True` means the rebuilt Drums is note-identical
to the pre-spike arrangement the user was already hearing, so "render-correct" is
transitively established. A fresh render is available as the Early-Feedback
"hear-it" milestone if desired; queued in operator-verification.

## 7. Boundary / wire-shape surface (MCP fingerprint + re-vendor)

- The create+fill path reuses **existing** wire actions (`create`, `replace_notes`,
  `delete` on `location='arrangement'`) → **no fingerprint change** if implemented in the
  sync planner alone.
- An optional bulk `ableton_clip(action='clear_arrangement', …)` action **would** flip the
  fingerprint (it's a new wire action in `_FINGERPRINT_PATHS`) → re-vendor + operator-verify.
  Decide in Chunk 1.
- The integrity assertion is sync-side (compares DB counts vs `get_notes_extended` reads)
  → no wire change.
- Net: the systemic redesign can likely ship with **zero or one** new wire action — far
  less Live-side churn than its 13-month patch history.

---

## 8. Build shape (thin vertical slice first; chunked; Critic per chunk)

- **Chunk 1 — Live-gated spike + decision (verify-api).** In an attended session:
  reproduce the bulk-drop, confirm note_count trustworthiness, and validate
  create+fill-at-scale (the §6 questions). Decide planner-only-deletes vs new bulk-clear
  action. Output: a short findings note appended here + the go/no-go on the wire decision.
  *Thin vertical slice: materialize ONE track via create+fill end-to-end and render-verify.*
- **Chunk 2 — sync-planner rebuild path.** Rewrite `plan_push_arrangement` to the
  clear+create+fill projection for note-only placements; route envelope-bearing →
  duplicate-onto-cleared; route audio → existing path. Full clip-spec materialization
  (notes + name + color + envelopes).
- **Chunk 3 — integrity assertion.** Post-materialization per-track assert (arrangement
  note_count == DB) with a HALT + actionable report; regression test that a forced
  mismatch halts.
- **Chunk 4 — collapse the reconcile subsystem.** Remove/transient-ify the arrangement
  branch of probe-and-link (SYN-3C8K/4R7P logic) now that nothing maintains a persistent
  positional link; keep whatever the cues phase genuinely needs. Delete dead code, don't
  fallback (no back-compat to throwaway).
- **Chunk 5 — docs + skill.** Retire the SYN-4R7P recovery dance from
  `skills/ableton-push/SKILL.md` (lines 80, 82, 178); document clear+rebuild as canonical;
  update `ableton://guides/gaps`/`conventions` warnings.
- **(Optional) Chunk 6 — bulk `clear_arrangement` wire action** if Chunk 1 chose it;
  re-vendor + operator-verify.

Each chunk is no-back-compat (delete superseded paths). The two 2026-06-21 reports are the
acceptance witnesses: editing a mid-timeline clip + rebuild must not stack; bulk rebuild
must not drop; both must halt-on-mismatch rather than report OK.

---

## 9. Risks

- **The envelope-bearing dual path is where complexity re-enters.** If detection of
  "this placement carries a clip envelope" is wrong, an envelope clip could be routed to
  create+fill and lose its automation. Mitigate: the DB is authoritative about clip
  envelopes; make routing a pure DB query + test both branches.
- **`create_midi_clip` length/position semantics** may differ subtly from
  `duplicate_clip_to_arrangement` (e.g. loop/clip-end markers). Chunk 1 must confirm.
- **Cues phase coupling.** Cues need arrangement extent and run after arrangement; the
  rebuild must leave the same extent the cue planner expects. Verify in Chunk 2/4.

---

## 10. What this supersedes (collapse, don't keep patching)

These per-symptom items fold INTO this systemic effort (groom: relate/close as the
redesign lands, do not build independently):

- **2026-06-21 stacking** (incoming-bugs) — acceptance witness, not a separate patch.
- **2026-06-21 bulk-drop** (incoming-bugs) — acceptance witness; §6 q1+q2 are its live root-cause.
- **ARR-6T8N** (open) — B-24 start-time-only spurious detection; moot for the note path
  (no duplicate), narrowed to the envelope-bearing duplicate path only.
- The `note_count`-masking ask — subsumed by the integrity assertion (§6 q2 confirms the read).
- The "bulk clear primitive" ask — Chunk 6 (optional) or planner-deletes (Chunk 2).

Already-shipped relatives (context, not scope): PSH-6W2J (note→arrangement propagation),
SYN-4R7P / SYN-3C8K (link reconcile — to be removed by Chunk 4).
