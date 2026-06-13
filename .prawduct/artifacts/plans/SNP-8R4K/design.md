# SNP-8R4K — The analyzer is measurement infrastructure, not authored content

`status: design` · `area: snapshot/sync` · driver:
`incoming-bugs/archives/2026-06-13-snapshot-capture-includes-hallucinote-analyzer-devices.md`
· child of the bake-turnkey umbrella **BAK-3M9T** · perf-coupled to **MCP-4T6Y**
(async renders)

## Root cause (one sentence)

The `HallucinoteAnalyzer` is modeled as **authored content** when it is actually
**out-of-band measurement infrastructure** — so it leaks into the song's source of
truth and its chain position is unmanaged, and every symptom below flows from that
one missing distinction.

## The full failure cascade (one defect, ten compounding failures)

The analyzer is a Max-for-Live audio tap the render injects on every measured
surface; it must be the chain's LAST device to measure the full output. Treated
as an ordinary device, it fails in a compounding chain:

1. **Inject** — render loads it on every surface, append-only, idempotent, and
   leaves it loaded (`handlers/render.py` `ensure_analyzers_loaded` →
   `analyzer/setup.py:301`). Now it's an ordinary chain device to everyone else.
2. **Mis-tap** — devices loaded after a render land *past* it (Live has no reorder
   API), so it's no longer terminal → per-stem WAV **under-measures** post-analyzer
   devices → silent wrong numbers.
3. **Leak** — `/song-snapshot` (`capture.py` `compile_snapshot`) and `ableton-pull`
   (`sync/pull/devices.py`) walk the chain and record it (+ its M4L params) into
   `captured_session.json` AND the song DB. (No analyzer filter exists in either —
   confirmed.)
4. **Persist** — it is now part of the song's *source of truth*; the song "owns" an
   analyzer device.
5. **Re-emit** — push (`sync/push/devices.py`) reads the DB and tries to materialize
   `kind="HallucinoteAnalyzer"` via the browser → no loadable node → **push
   fails/halts** (or resolves wrong).
6. **Multiply** — when push doesn't fail: push adds one *and* the render's
   ensure-load adds one → two analyzers. Next pull captures both → DB has two →
   next push two + render → three… **monotonic accumulation across pull/push
   cycles.** A tap that breeds.
7. **Drift** — each interleaved/duplicate analyzer shifts authored device positions;
   off-by-one becomes non-deterministic off-by-many; replay loads the wrong device
   into the wrong slot.
8. **Break the converger** — push is supposed to be idempotent (same DB → same
   Live). The analyzer makes DB and Live permanently disagree (DB has it, render
   re-adds it) → the converger fights the render: delete the tap (kills
   measurement) or add another (duplicate).
9. **Break portability** — the framework⇄songs split commits snapshots; songs build
   against an *installed* engine on *other* machines. A committed snapshot carrying
   an analyzer row won't build elsewhere (the `.amxd` path differs / isn't
   installed) → the snapshot is no longer a portable source of truth, which is the
   whole contract.
10. **Poison ownership** — a pulled analyzer carries an actor; `sync` makes the
    tombstone logic *protect* it (permanent pollution), `build` tombstones then
    re-pulls it. The song can never converge clean. (Same ownership machinery the
    SDC-7K3M Critic finding touched.)

The thread through all ten: **the analyzer exists in the authoring / persistence /
sync world, where it must not exist at all.**

## The reframe

This is not "filter the analyzer at capture" — that patches one leak (step 3) while
5–10 still bite through any filter gap. The correct frame: the analyzer is
**categorically outside the authoring domain.** The DB, the snapshot, push, pull,
the converger, build, and cross-machine reproduction must all behave *exactly as if
the analyzer does not exist.* It lives only in the Live runtime, owned solely by the
render subsystem, for the duration of measurement.

Decisive robustness principle (the accumulation risk forces it): **a filter can have
a gap; absence cannot.** The strongest guarantee against capture-and-multiply is for
the analyzer to **not be in the chain at the moments authoring/capture/push can
observe it** — you cannot capture, push, or duplicate what isn't there.

## Requirements

**Domain separation**
- **R1.** A first-class "infrastructure device" category, distinct from authored
  content; one shared, position-independent identity predicate used everywhere
  (today only `_find_analyzer_index` at `analyzer/setup.py:428` knows the analyzer).
- **R2.** Sole ownership: the render/analysis subsystem is the *only* thing that
  adds, positions, or removes the analyzer. No other subsystem creates, reconciles,
  or reasons about it.

**The authoring model is analyzer-free (kills cascade steps 3–10)**
- **R3.** The analyzer (and its params) never enters a snapshot or the DB.
- **R4.** Push never emits it, and defensively *skips* any analyzer row that exists
  (a legacy-polluted snapshot must not break a build).
- **R5.** Authored device positions are dense and analyzer-independent (rank among
  authored survivors, never the raw Live chain index) → **off-by-one impossible by
  construction**.
- **R6.** Idempotency restored: the model is analyzer-free → the converger never
  sees it → no fight with the render → **no accumulation**.
- **R7.** Portability: an analyzer-free snapshot builds on any machine; the local
  render injects the tap at measurement time. Song portability is decoupled from
  local measurement tooling.

**Measurement correctness (kills step 2)**
- **R8.** At capture time, on every measured surface, the analyzer is **present and
  strictly terminal** — re-asserted at the authoritative moment (render),
  self-healing whatever happened to the chain since the last render.
- **R9.** Never measure-and-lie: if a surface can't be made compliant, the
  report/manifest flags it (`analyzer_not_terminal`) rather than emitting
  under-measured numbers as if real.

**Robustness / legacy / constraints**
- **R10.** Survive existing pollution: songs whose committed snapshots already carry
  analyzer rows must (a) not break a push (R4) and (b) get a one-time cleanup.
- **R11.** Survive partial failure / manual Live edits: a stray or mis-ordered
  analyzer self-corrects at the next render and can never silently corrupt the model.
- **R12.** Live has no reorder API → "make last" = delete + re-add (one expensive
  M4L load — the `ensure_loaded` 25-surface load once blew the socket window). Keep
  that cost off the unchanged-surface path.

## Design — persistent analyzer + boundary exclusion (decision LOCKED: PERSISTENT, durable)

The analyzer stays **persistently loaded** on every measured surface. This is the
durable design (not an interim), chosen for **ad-hoc-capture simplicity**: any
analyze/capture can run at any time with the tap already in place — no per-pass
load/remove lifecycle to orchestrate, and one less moving part for the agent. Two
independent mechanisms make persistence safe and correct:

**Mechanism 1 — Boundary exclusion (the load-bearing model-cleanliness guarantee).**
Exclude the analyzer by *category* at both boundaries between Live-runtime and the
authoring model:
- *Pull/capture (Live→model):* `compile_snapshot`, `sync/pull/devices.py`,
  `tools/capture_cli.py` drop `is_analyzer(...)` devices and renumber the survivors
  densely (R3, R5). Identity-based → correct even when the analyzer is interleaved.
- *Push (model→Live):* skip any `is_analyzer` DB row with a warning (R4).
- One-time cleanup pass to strip analyzer rows from already-polluted committed
  snapshots/DBs (R10).
- Because the analyzer is *always* in the chain, this filter is what keeps the
  authoring model analyzer-free — it is **load-bearing, not a backstop**, so the
  identity predicate must be reliable (centralized — R1) and is reinforced
  defensively by the push-skip (R4) and the position-independent dense-renumber
  (R5). Together these break the cascade (steps 3→10): the model stays analyzer-free
  → push never adds one → render adds exactly one → **no multiply** (R6), no
  off-by-one (R5), portable snapshots (R7), no converger fight (R8/step 8).

**Mechanism 2 — Render owns the terminal-tap invariant (measurement correctness).**
At render start, before the capture pass, ensure on every measured surface that the
analyzer is present AND strictly last: no-op if already last; delete + re-add only
on surfaces where a device landed after it (R8/R12 — the M4L re-load cost is paid
*only on changed surfaces*); load if absent (R5/ensure-present). This self-heals any
intervening mis-order from ad-hoc loads or manual edits (R11). Plus observability
(R9): flag any surface that can't be made compliant rather than emitting
under-measured numbers as if real.

Together: the analyzer is **always available** (persistent → simple ad-hoc
captures), **always terminal at measurement** (Mechanism 2), and **always invisible
to authoring** (Mechanism 1).

### Why persistent (not ephemeral)
Persistent keeps the tap available for ad-hoc captures with zero orchestration and
removes the add-before/remove-after-per-render lifecycle entirely — lower complexity
where it's exercised most (the user's call). The accepted tradeoff: model-cleanliness
then *depends on* Mechanism 1's capture-filter being gap-free rather than being
guaranteed by absence — mitigated by the single centralized identity predicate +
defensive push-skip + position-independent renumber + observability (defense-in-depth
at the boundary). **Ephemeral** (analyzer exists only during a render, removed after)
would be cleaner-by-construction (absence beats filtering) but complicates every
ad-hoc capture (each analyze needs a load step), ties the tap's lifecycle to render
passes, and would pay the full multi-surface M4L reload per render — rejected for
those reasons.

### Other alternatives rejected
- **Out-of-chain tap** (analyzer on a dedicated send/return) — an audio M4L tap must
  be the terminal device to measure a chain's full output; there is no faithful
  out-of-chain equivalent.

## Migration (existing polluted songs + stale Live sets)

Two stale states already exist in the wild; both must be handled when users update
to the release that ships this fix. **"Rebuild the entire set is valid and OK"
(user, 2026-06-13)** — so we do NOT surgically reorder live sets (Live has no
reorder API anyway); we clean the source of truth and *guide* a rebuild. Two prongs
plus a version trigger:

**State 1 — polluted source of truth** (a committed `captured_session.json` / song
DB that already captured analyzer device rows).
- **Auto-migrated by chunk 1, functionally:** `compile_snapshot`, `_replay_devices`,
  and the pull path all strip `is_analyzer_device` + densify on read. So the first
  `build.py` / pull / push after updating produces a clean DB automatically — no
  analyzer rows reach the model, authored positions densify. The DB is derived
  (rebuilt from build.py + snapshot), so it is self-correcting; chunk 1 IS the
  State-1 trigger.
- **Clean-at-rest (chunk 2):** the committed snapshot FILE may still carry analyzer
  entries (ignored on replay, but dirty at rest). A cleanup pass rewrites
  `captured_session.json` — strip + densify — stamps a snapshot version so it runs
  once, and **announces what it stripped** (never a silent rewrite).

**State 2 — mis-ordered saved Live set** (an `.als` where authored devices were
loaded after the analyzer → per-stem captures under-measured them).
- The set is materialized output, not source of truth. With the model clean
  (chunk 1), the fix is to **rebuild the set from source** — a full push into a fresh
  set re-materializes authored devices in order and the render adds the analyzer last
  (chunk 3). User-blessed; no surgical reorder.
- **Guidance + trigger (chunk 4):** the push/compat preflight probes the bound set;
  if any chain has authored devices *after* the analyzer (or the analyzer interleaved
  among authored devices), it flags the set as pre-SNP-8R4K and emits guidance — *"this
  set predates the analyzer-infrastructure fix; devices after the measurement tap were
  under-measured. Rebuild from source: push into a fresh set."* **Not auto** — the
  operator owns the set; the rebuild is their action.

**The trigger ("on update to the version we push"):** State 1's model-clean is
automatic on the first build/pull/push after update (chunk 1's filters); the
snapshot-file rewrite (chunk 2) fires via a snapshot version stamp (rewrite once when
an unstamped/old snapshot is seen) or the `/song-snapshot` command. State 2's
guidance fires from the push preflight (chunk 4) on the first push to a stale set
after update. **All ship in the SAME release as chunks 1–3** so updating users get
the trigger + guidance, never a silent stale state.

## Touchpoints (current-state map, for the build)
- Identity: `analyzer/setup.py:428` `_find_analyzer_index` (only site that knows the
  analyzer) → promote to a shared `is_analyzer`/`is_infrastructure` helper (R1).
- Inject/position: `handlers/render.py` `ensure_analyzers_loaded` →
  `analyzer/setup.py:301` (idempotent, append-only, never repositions/removes).
- Delete API exists (`handlers/device.py`, 1-based `device_index`); **no reorder API**
  → reposition = delete + re-add (R12).
- Capture (no filter today): `capture.py` `compile_snapshot`, `sync/pull/devices.py`,
  `tools/capture_cli.py`.
- Push (no skip today): `sync/push/devices.py` `_emit_device_calls`.

## Boundary / contract notes
- **Snapshot contract** + **device-chain contract** (`boundary-patterns.md`):
  excluding the analyzer at capture changes the snapshot device shape (analyzer rows
  vanish; positions densify) — but toward the *intended* shape (authored-only). The
  one-time legacy cleanup (R10) is the migration for already-emitted snapshots.
- **Idempotency** is the load-bearing property restored (R6): document that the
  analyzer is outside the converger's domain.

## Relationships
- **BAK-3M9T** (turnkey live→source bake) — this is the highest-leverage child:
  capture pollution + ordering is trap #1/#2 of that umbrella.
- **MCP-4T6Y** (async render) — complementary, NOT a gate: the persistent design
  works today. Async renders just make the render pass (incl. Mechanism 2's
  occasional reposition) non-blocking.
- **DEV-5R8Q** (no reorder API / delete-descending) — shares the reorder constraint.
- **SDC-7K3M** — same device-chain + actor-ownership machinery.

## Decision log
- **Persistent analyzer is the DURABLE design** (not an interim) — user, 2026-06-13:
  "yes to persistent, it's handy to reduce complexity for ad hoc captures." Ephemeral
  rejected (complicates ad-hoc captures + per-render reload). Mechanism 1
  (boundary-exclusion filter) is therefore load-bearing, not a backstop.

## Open questions (resolve at build)
- The exact shared identity predicate (name + M4L class; whether to add an
  `is_infrastructure` flag to the `ableton_device(list)` payload for generic
  filtering). Load-bearing under the persistent design — pin it carefully.
- The legacy-cleanup shape (a `capture_cli`/snapshot migration vs a one-shot script)
  and how it reports what it stripped.
