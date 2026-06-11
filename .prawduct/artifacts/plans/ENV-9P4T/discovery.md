# ENV-9P4T — Performed Automation at Mix Scale: Discovery

**Item:** plain-track mixer targets + single-pass batched recording for performed
automation. Extends **ENV-7G4K** (shipped) / **AUD-1M4V** R3.2. Status: discovery,
2026-06-11.

**Why this is a NEW requirement, not ENV-7G4K leftovers.** ENV-7G4K decision 3 fixed
the wave-1 target surface at **master + group + return** and recorded the
one-pass-per-arc transport cost as a residual. Ordinary tracks were explicitly out.
"Volume + pan rides on 10+ instrument tracks, written in one run-through" is therefore
a parent requirement this doc *writes* — not a design against an unstated one
(building tripwire #1). User driver (2026-06-11): a real mix needs continuous
volume/pan/send/device rides on every track, and the per-arc transport replay doesn't
scale to that count.

## The requirement (problem / success / out-of-scope)

1. **Problem.** A plain track's own volume/pan automation can't be a continuous
   arrangement-view ride today. It only routes through the **per-clip session-clip
   path** (`classify_envelope_route` → `_route_for_host_kind`, `sync/push/envelopes.py:221`),
   which segments at clip boundaries and is MIDI-only. The **perform** path that *does*
   write continuous arrangement lanes is scoped to master/group/return **and** plays the
   transport once **per arc** (`plan_push_performed_automation` emits one call per changed
   arc; cost summed sequentially, `sync/push/perform.py:301`). N arcs over a song ⇒ N full
   playthroughs.
2. **Success.** (a) `perform` accepts a **plain track's** `mixer_volume`/`mixer_pan`
   (+ existing `send_level`/`device_parameter`), giving any track a continuous
   arrangement ride independent of clip seams; (b) **one push records all changed
   performed arcs across all tracks in a single transport run-through** — wall-clock ≈ one
   song length, not N×; (c) a **documented safety stance** for arrangement automation the
   user hand-edited in Live (perform is write-only; re-record can silently clobber it).
   Verified on a ≥10-track set via `automation_state==1` per param + playback.
3. **Out of scope.** Tempo/signature automation (`song.tempo` is a plain float, not a
   `DeviceParameter` — LOM-blocked, W6-F; separate axis). Building a **live-LOM** read of
   arrangement automation (no surface exists). Audio-clip placement (CLP-AUD2);
   audio-track envelopes (ENV-8H1T). Session-clip auto-partition (ENV-3M7K). `.als`
   **write-back** (rejected in AUD-1M4V; see read-side note).

## What actually has to change (grounded in code)

### Write side A — plain-track mixer targets (smaller than it looks)

The mechanism is **already present**; only the routing gate and an authoring choice are
missing:

- The **handler** `_resolve_perform_target` already resolves a non-master `track_index`
  mixer — `parent = _resolve_track(track_index); mixer = parent.mixer_device; return
  mixer.volume|panning` (`handlers/automation.py:1571-1591`).
- The **planner** `_arc_addressing` already addresses non-master tracks for
  `mixer_volume`/`mixer_pan`/`send_level` (`sync/push/perform.py:113-154`).
- These branches are reached **today only for group tracks**, because
  `classify_envelope_route` routes a *midi-host* mixer envelope to `session_clip`
  (`sync/push/envelopes.py:221-228`).

⇒ Plain-track perform is **a routing/authoring decision + a probe**, not new handler
machinery. The change lives almost entirely in `_route_for_host_kind` and a new way for
the author to say "ride this continuously."

**Open authoring fork (see Open Questions):** per-clip envelope (session-clip; travels
with a looped clip; within-clip shapes) vs continuous ride (perform; one arrangement
lane; clip-boundary-independent). A plain track can want either. Default proposal:
*infer from span* — an envelope whose span exceeds one covering session clip (or which no
single session clip covers) routes to perform; otherwise session-clip. An explicit
per-envelope route flag is the fallback if inference proves ambiguous.

### Write side B — single-pass batched recording (the real new machinery)

Live records **every parameter moved during one arrangement-record pass** — that's a
mixer riding several faders in one take. The batched shape:

- resolve all changed arcs' params up front,
- arm record once, seek to the **union** span start,
- play the transport **once** over `[min(starts), max(ends)]`,
- each tick, set every param whose span covers the current beat,
- one pass instead of N.

**The real work is per-parameter gesture windowing.** Arcs have different spans. If A
rides 0–512 and B only 128–256, B's `begin_gesture`/`end_gesture` must open at 128 and
close at 256 while A stays open — otherwise B records a flat value across the whole song
and **clobbers automation outside its intended range**. The current handler opens one
global gesture (`handlers/automation.py:1752,1805`); batching needs per-arc gesture
entry/exit inside the shared pass.

Shape: a batched `perform` (a list of `{target, breakpoints, span}`) or a new
`perform_batch` action; the push phase emits **one** batched call instead of one-per-arc.
Fingerprint-gating **composes** — include only the changed arcs in the pass.

### Read side — `.als` harvest (the answer to the write-only gap)

Perform is **write-only**: no LOM read of arrangement automation (ENV-7G4K). A user
hand-edit to a performed lane is invisible to pull and overwritten by re-record. The
**only** read path is the `.als` file, and it is **CONFIRMED viable** —
`docs/research/audio-first-class/lom-recording-automation.md:76-82`: gzipped XML;
`LiveSet > {MasterTrack|Track} > AutomationEnvelopes > Envelopes > AutomationEnvelope`,
`EnvelopeTarget > PointeeId` → the parameter's `AutomationTarget Id`, `Events >
FloatEvent(Time in beats, Value)`. The repo **already reads `.als`** for ENV-7G4K
breakpoint-fidelity verification (`tests/integration/test_live_smoke.md:241,258`,
`s7-smoke-test.als`), so the parse is precedented, not greenfield.

**The ugly, enumerated honestly:**
- **Save-gated, not live.** The `.als` reflects the last *save*, not Live's in-memory
  state. Harvest workflow = "save in Live → read the file." Unsaved edits are invisible.
  **No programmatic save** ships today — `ableton_session(action='snapshot')` is deferred
  (`actions/session.py:289`) and the save mechanism is an open design question leaning to
  Live's undo-checkpoint, not `.als` save-as (`docs/archive/mcp-tool-design.md:745`). The
  raw LOM likely exposes no `song.save`/`save_as` either (unverified — definitive check is
  `ableton_probe(action='describe', path='song')` on a scratch set). Freshness oracle is
  the `.als` **file mtime** vs the harvest request time, not a save command or a (likely
  absent) Live dirty-flag; v1 prompts "Cmd-S first" and verifies mtime advanced.
- **ID join.** Events are keyed by numeric `PointeeId` you must resolve to "track 3 mixer
  volume" by walking the device/mixer tree and matching `AutomationTarget Id`s.
- **Undocumented, version-pinned format.** Ableton publishes no `.als` schema; element
  names/nesting shift across versions. A parser is reverse-engineered and pinned to Live
  12.4 (consistent with the repo's existing probe posture).
- **DB reconciliation.** Map Live track index ↔ DB id via `ableton_links`, then decide:
  drifted Hallucinote arc, or new human-authored arc the DB never had?
- **Batch cadence.** Harvest is an out-of-band operation gated on save, not part of the
  live round-trip loop.

**Why it's worth the ugly:** it closes the write-only gap that makes the whole perform
mechanism dangerous — detect drift (harvest vs last-written fingerprint), **ingest**
hand-drawn arcs into the DB (true round-trip), and stop silently clobbering edits.

**Important nuance:** AUD-1M4V rejected `.als` as a **write** path (needs the set
*closed*, breaks the live loop). **Reading is a different proposition** — *save*-gated,
not *closed*-gated; complementary to the LOM write path, not a replacement. The prior
rejection does not apply to harvest. Recommendation: a **separable** capability (its own
item if committed); with it, ENV-9P4T's safety stance upgrades from "warn before clobber"
to "detect-and-preserve."

## Safety stance (this resolves the clean-slate fork)

The read-safety requirement **decides the gating question**. Keep **per-arc fingerprint
gating** — it is a *data-safety feature*, not just a speed one: an unchanged authored arc
means we never touch Live, so a manual edit to that lane **survives**. Then batch the
*changed* subset into one pass. Do **not** go clean-slate-re-record-all: it maximizes the
chance of clobbering a hand edit. ("Fine to start over" = acceptable worst-case
wall-clock, not a license to wipe Live edits.)

- **v1 (no harvest):** loud Visible-Cost overwrite warning naming each span the pass will
  rewrite + owned-lane bounding (only ever re-record *authored* arcs).
- **v2 (with harvest):** detect-and-preserve — harvest, compare to last-written
  fingerprint, skip/ingest the lanes the human touched.

## Open questions (carried to planning)

- **Authoring fork** — how does an author declare continuous-ride vs per-clip for a plain
  track? (infer-from-span default; explicit flag fallback.)
- **Plain-track perform probe** — does a non-master/non-group track's mixer record cleanly
  the same way master+return did? ENV-7G4K probed master+return (groups assumed); plain
  tracks unprobed. *(No Live access this session — a 2nd agent is on a song; defer to a
  scratch set.)*
- **Multi-gesture-in-one-pass probe** — do overlapping `begin/end_gesture` windows on
  distinct params within one record pass each record correctly?
- **Shrunk/deleted-arc cleanup** — re-record overwrites only the re-recorded span; an arc
  the author *deletes* leaves stale Live automation (write-only ⇒ can't erase via LOM).
  Mitigations: neutralize by re-recording a flat value over the old span, manual clear, or
  harvest-then-reconcile. (Existing ENV-7G4K residual, sharpened at scale.)
- **Master device automation dependency** — automating a master-bus limiter via perform
  needs the device **already placed** (`sync/push/perform.py:164`), because master device
  *loads* are LOM-blocked (DEV-2M9K; `handlers/device.py:651-670`). Orthogonal to this
  item but a dependency for that use case — place by hand / `.als` master template
  (TPL-2D8K, AUD-1M4V R4.2), then perform drives it.

## Decision record

- **Plain-track perform is a routing extension, not new machinery** — handler + planner
  already resolve non-master track mixers (reached today only for groups). The gate is
  `classify_envelope_route`/`_route_for_host_kind` + an authoring choice.
- **Single-pass batching is the scaling answer** — one record pass captures all moved
  params; per-parameter gesture windowing is the new work; fingerprint-gating composes by
  including only changed arcs.
- **Keep per-arc gating for data safety** — it protects hand-edited lanes; clean-slate
  re-record-all is rejected as the default for exactly that reason.
- **`.als` harvest is the read/round-trip path** — confirmed viable, precedented in the
  repo's verification; scoped as a separable sibling capability; the prior `.als`-as-write
  rejection does not apply to reading.
