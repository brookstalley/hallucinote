---
artifact: build-plan
version: 1
scope: RELFOLD-0910
branch: fix/release-fold-in-0910
depends_on:
  - artifact: api-contract
  - artifact: architecture
  - artifact: release-backlog-audit-2026-09-10
governed_by:
  - artifact: api-contract
    dispositions:
      - "Refuse-and-teach over silent wrong behavior → conforms (01 replaces a silent destruction of an unreadable sidechain source with a pre-delete warning; 04 replaces a silently-wrong capture under a soloed rack chain with a named warning the manifest also records)"
      - "Errors teach — structured recovery information, never a bare string → conforms (01 names the device; 03 names the transient state AND the re-seat that heals it; 04 names the rack and the chain)"
      - "The MCP surface is versioned by content fingerprint, never a hand-maintained number → APPLIES. Chunks 03 and 04 both touch fingerprinted paths under `handlers/`, so this scope REQUIRES a re-vendor and a full Live restart. Batched deliberately: one re-vendor, not two."
      - "No compatibility shims for consumers that cannot exist → conforms (03 and 04 add response/manifest fields; no existing caller changes shape)"
      - "Mutator signatures keyword-only after conn → inapplicable; no chunk touches a mutator"
      - "Timing transforms stay in the engine, off the MCP surface → inapplicable; no chunk touches timing"
      - "The MCP tool surface stays inside the band where tool-selection accuracy holds → conforms; no tool and no action is added, only fields on existing responses"
      - "These interfaces stay internally scoped → conforms; nothing changes about what is published"
partition: >
  serial. Six chunks, but three of them (05, 06 and the bookkeeping half of 01)
  are documentation and backlog state that only the coordinator may write, and
  the three code chunks are one-to-three files each. Delegation would cost more
  than it saves and the coordinator would still own the combined suite, the
  Critic, the fingerprint question and every state update. Chunk 01 owns
  `sync/chain_rebuild.py` + its tests; 02 owns
  `hallucinote_mcp/.../handlers/device.py` + `analyzer_identity` guard tests;
  03 owns `handlers/device.py` (load response) — 02 and 03 SHARE a file and are
  therefore strictly ordered, never parallel; 04 owns `handlers/render.py` + its
  tests; 05 owns tests only; 06 owns artifacts and backlog.
last_validated: 2026-09-10
---

## Requirements Confidence

**Level:** High for 01, 02, 03, 05, 06. High for 04 — the one open question
(refuse vs warn) was put to the owner and answered **warn**, 2026-09-10.

1. **What problem are we solving?** Six backlog items filed as residue of this
   release's own work are coupled to what is shipping: they leave a destructive
   path silent, a guard half-closed, a brittle cross-package guard, and three
   bookkeeping claims that are now false.
2. **What does success look like?** A release cut where every shipped guard
   either covers its stated class or names its limit out loud, and no open
   backlog item contradicts the code that shipped.
3. **What's out of scope?** #482 (the render-integrity lens limits — left out on
   the prior session's reasoning that R1/R2 and RENDERGUARD must prove each
   other separately; recorded in the release notes rather than silently).
   Operator-verification re-runs, which need Live and the owner.

## A requirement changed under this plan — #534 is NOT built

The audit recommended building **#534** (`_PARAM_EPSILON` is absolute and
step-blind) and the owner approved it. Reading the code to build it showed the
defect **is not reachable through the path chain-rebuild actually takes**, so
building a tolerance change would have been a fix to nothing.

`_capture` reads every parameter **off Live** (`chain_rebuild.py:474` — "Read
everything the demolish phase is about to destroy"), `_restore` writes that same
journal value back, and `_verify_parameters` compares the journal value against
the read-back. Both ends are Live-sourced and the write is verbatim, so the
compared values are identical by construction: `str(float(v))` is round-trip
exact for a double, and narrowing the same double to float32 twice yields the
same float32.

Measured, not reasoned — every case round-trips at **exactly 0.0**, including
the two the item calls breaching:

| parameter | captured | reads back | \|delta\| |
| --- | --- | --- | --- |
| EQ Eight frequency, 22000 Hz | 22000.0 | 22000.0 | 0.0 |
| gain, the item's measured case | 4.110000133514404 | 4.110000133514404 | 0.0 |
| `Note PB Range`, stepped | 41.0 | 41.0 | 0.0 |
| `Semitone`, stepped | 3.0 | 3.0 | 0.0 |

This **reproduces the item's own Pass 1** ("re-wrote each parameter's existing
value … round-tripped at exactly 0.0 across 29 parameters"). The item's Actual
section is drawn from Pass 2, the *perturbing* pass, which deliberately wrote
off-grid values (41.424 into a stepped parameter) — something chain-rebuild
never does, because it never invents a value.

So #534 is re-scoped, not built, and chunk 05 pins the property that makes the
epsilon safe. **Flagged rather than silently dropped**, per the norm.

## Chunks

### Chunk 01: chain-rebuild warns before it destroys an unreadable sidechain source (#544)

The unreadable-sidechain-source warning fires on two surfaces — `capture.py:2019`
and `push/plan.py:817` — and not on the third, which is the destructive one.

**#544's stated mechanism is wrong and the item must be corrected.** It says the
source is "never journaled … and never restored". It is both: `chain_rebuild.py`
captures `input_routing` and restores it at `:978-1008`, with a dedicated alert
when the write fails. The real gap is narrower and still real: a source the
probe **cannot read** is captured as *absent*, so the restore writes nothing,
the delete/reload destroys it, and nothing warns — the restore only alerts on a
write it *attempted*.

- [x] Import `sidechain_armed_in_probe` / `unreadable_sidechain_source_warning`
      and call them on the probed parameter list the journal is built from.
- [x] The warning fires **before the first delete**, so the operator can abort.
- [x] Test: an armed device whose source is unreadable warns, naming the device.
- [x] Test: an armed device whose source IS readable adds no warning.
- [x] Correct #544's body — the "never journaled" claim.

**Done when:** both tests pass and no fourth copy of the arming predicate exists.

### Chunk 02: the sidechain-enable hints are named on the MCP side (#545)

`SIDECHAIN_ENABLE_PARAM_HINTS` is mirrored across a package boundary the engine
cannot import across, and the guard keeping the mirror honest scrapes handler
**source text** between two literal anchors. It works and fails loudly; it is
brittle against reformatting.

- [x] The handler exposes the hints as a named module constant and matches
      against it.
- [x] The guard imports both sides — no source scraping, regex, or anchors.
- [x] Adding a hint on one side alone still fails the guard.

**Scope-out, AMENDED mid-build:** the gain-param match was originally scoped
out ("same shape, separate change") and was then folded in anyway, because
naming the enable set while leaving its neighbour an inline `or` chain leaves
the module with two idioms for one thing. Recorded rather than left for a reader
to discover: the refactor is literal-for-literal, and the gain constant is
underscore-PRIVATE where the enable one is public. That asymmetry is the whole
scope-out surviving — what the original scope-out protected was the *guard*, and
the gain set still has no engine mirror, no drift guard and no dispatcher test,
so a public name beside the enable set would advertise protection it does not
have.

### Chunk 03: `device load` says it landed past the analyzer tap (#546)

`ableton_device(action='load')` onto a rendered track lands past the
`HallucinoteAnalyzer` and says nothing; an operator reading the chain order
infers silent under-measurement. No harm is reachable — `render(start)` re-seats
the tap before any capture — but only the source says so. An *Errors teach* gap.

- [x] Such a load returns a note naming the transient state and the re-seat.
- [x] A load with no analyzer, or one landing before the tap, says nothing new.

**Scope-out:** changing *where* `load` places the device, or making it re-seat
the tap — the render-start sweep owns that.

### Chunk 04: a soloed rack chain warns, and the manifest records it (#550)

The shipped solo guard refuses a render under a soloed **track or return**. A
soloed rack **chain** is invisible, and chain solo is first-class here
(`is_soloed`, `device_chains.solo`).

**Owner decision, 2026-09-10: WARN, do not refuse.** A chain solo silences
sibling chains inside one rack, not the song — the master bus still carries every
track — so the blast radius is narrower than a track or return solo, and
rendering while auditioning one layer of a rack is a thing an author legitimately
does. Record the reason in `decisions/`-equivalent (the change-log entry).

- [x] The pre-render mixer read enumerates chain solo for rack devices on tracks
      **and** on returns.
- [x] A soloed chain warns, naming the rack and the chain, and the render proceeds.
- [x] Manifest `mixer_state` carries chain solo whether or not anything warned.
- [x] Track/return solo still **refuses** — this chunk must not weaken #548.

**Scope-out:** chain mute and chain volume. Racks nested inside a rack chain
(top-level racks only) — stated in the docstring, in `architecture.md` §
*What is deliberately not modeled*, and in `boundary-patterns.md`.

**Consumer investigation (Capture Manifest is a declared contract surface).**
Done rather than asserted. `boundary-patterns.md` enumerates the manifest's
consumers — `audio/io.py` `load_capture` and `resolve_baseline`, `takes.py`
`recency_key`, `tools/make_demo_media.py` (the one published consumer) and
`server._record_audio_capture_event`. A repo-wide sweep
(`grep -rn 'mixer_state\|muted_tracks\|soloed_chains' src/ hallucinote_mcp/src/
tools/`) returns **no manifest consumer at all**: the only hits are
`node_features.py` / `handlers/device.py`, which are the unrelated device-chain
`mixer_state`. The manifest's whole mixer block is write-only today — read by
people and by reports, by no code. No consumer iterates manifest keys
generically either (`audio/io.py` reads `tracks` and `returns` by name), so the
two new members break nothing and need no migration.

That absence is itself the finding #529 now carries: the write side records the
mixer and the read side never learned it was there.

### Chunk 05: the epsilon's safety is pinned by a test (#534, re-scoped)

No production defect (see above), but the property that makes `_PARAM_EPSILON`
safe is untested — nothing in `tests/` references `_verify_parameters` or the
constant. That is the same shape as the defect the previous cycle found: tests
pinning that a number exists, never that anything depends on it.

- [x] Test: a capture→restore→verify round trip over Live-sourced values —
      including a large-magnitude frequency and an integer-stepped parameter —
      reports **no** mismatch.
- [x] Test: a parameter left at its class default (the regression the epsilon
      exists to catch) IS reported.
- [x] Re-scope #534 to the residue: the epsilon is safe only because the restore
      never invents a value, and that is now a pinned contract.

### Chunk 06: the bookkeeping the release cannot ship with (no code)

- [x] **#533 → `status=shipped`.** Fixed at `chain_rebuild.py:826`; change-log
      carries `scope=CHAIN-RESTORE-STR`. Open-but-shipped.
- [x] **#526 residue read.** #537 closed 2026-09-10; #526's body says in terms it
      "must NOT be built as currently written" and must not be closed on #537's
      merge without someone reading the residue. Read it and re-scope.
- [x] **#529 re-scope.** Its premise ("`manifest.json` records no fader values")
      is now partly false — RENDERGUARD added per-surface `mixer_state`.
- [x] **`architecture.md` learns three new packages.** `assets` (9 files / 2,491
      lines), `features` (8 / 1,413) and `spectral` (7 / 1,763) are all new since
      v1.8.6 and carry zero mentions. This is what the briefing's staleness
      advisory is pointing at.
- [x] **The five bare release-pending scopes** — `CHAIN-RESTORE-STR`,
      `docs-hygiene`, `governance-file-sizes`, `advisory-clearing`,
      `effort-s-burndown` — get a plan or an explicit recorded no-plan
      disposition, so `check-releasability`'s warning is answered rather than
      carried.
- [x] **#482's exclusion is recorded** in the release notes, not left silent.
- [x] **#489 surfaced** to the owner: the R5 upstream report is unsent and this
      repo is now firing the exact advisory it describes. Egress is the owner's.

## Status

- [x] 01 — sidechain warning (#544)
- [x] 02 — named hints (#545)
- [x] 03 — load says it landed past the tap (#546)
- [x] 04 — chain solo warns (#550)
- [x] 05 — epsilon safety pinned (#534 re-scoped)
- [x] 06 — bookkeeping and artifacts

**Critic mode:** cumulative at the end — the diff crosses two risk surfaces
(engine `sync/`, MCP `handlers/`) and the fingerprint question spans chunks 02-04.

## Context

Cut from detached HEAD at `origin/develop` (`6dfdadb`), because `develop` itself
is checked out in `../hallucinote-release-readiness` and belongs to that session.

**Re-vendor impact: REQUIRED.** Chunks 02, 03 and 04 touch
`hallucinote_mcp/src/hallucinote_mcp/handlers/device.py` and
`.../handlers/render.py`, both inside `_FINGERPRINT_PATHS`. Nothing in this scope
exists in Live until the Remote Script is re-vendored and Live is fully
restarted — the same clock the RENDERGUARD solo guard is already on.

## Close

Five Critic rounds, then the PR reviewer. Everything they raised is fixed or
accepted with a recorded reason.

No counts travel with that sentence — not the commits, not the findings, not the
SHA the gate was last satisfied at. The same rule this bundle applied to
`architecture.md`'s package list: a number a reader cannot check at a glance
decays first and silently, and an earlier draft of this very paragraph said
"nine commits" while its own commit made ten. Ask the repo instead:
`git log --oneline origin/develop..HEAD`, `prawduct-hook check-cumulative-critic`,
`prawduct-hook evidence list --kind review`.

**Not archived deliberately.** On gitflow this plan archives at the
`develop→main` release via `plan-backfill`, not at the feature merge — the same
rule that keeps the RENDERGUARD-0910 plan live. A briefing advisory suggesting
otherwise during this window is expected.

**One item is carried forward, and it is FILED rather than noted**: the
chain-solo advisory envelope's mixed branch (some chains soloed, some
unreadable) is untested — **#553**. It was first written into
`.prawduct/.handoff-notes.md`, which is gitignored, so it would not have
survived the merge: a deferral that does not merge is a drop for everyone but
the machine that wrote it. Same correction the master-strip limit got at #552.
