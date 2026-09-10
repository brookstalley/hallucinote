---
artifact: build-plan
version: 1
scope: RENDERGUARD-0910
branch: fix/render-guards-solo-and-stem-sum
depends_on:
  - artifact: api-contract
  - artifact: nonfunctional-requirements
  - artifact: build-plan-render-integrity
governed_by:
  - artifact: api-contract
    dispositions:
      - "Refuse-and-teach over silent wrong behavior, at every boundary → conforms (02 refuses a render under a soloed track and names the tracks; 01 turns an already-measured disqualification into a blocking finding instead of a field nobody reads)"
      - "Errors teach — structured recovery information, never a bare string → conforms (02's refusal names each offending track and the one-gesture fix; 01's finding carries the correlation and the offset it was disqualified on)"
      - "The MCP surface is versioned by content fingerprint → 02 touches `handlers/` and `actions/`, which ARE fingerprinted: the fix does not reach Live until the operator re-vendors, and the plan says so rather than letting it be discovered"
      - "No compatibility shims for consumers that cannot exist → conforms (the manifest and compare payload gain fields, and both are read defensively — `master_deltas_refused` is ABSENT rather than null on a healthy report, and manifests predating `mixer_state` stay readable)"
      - "Mutator signatures are keyword-only after conn, and every mutator accepts actor/reason → inapplicable because nothing here writes to the DB; every change is on the analysis read path or the render handler"
      - "Timing transforms stay in the engine and off the MCP surface → inapplicable because nothing here touches timing"
      - "The MCP tool surface stays inside the band where tool-selection accuracy holds → conforms (no tool and no action is added; `ableton_render(start)` gains a refusal and two manifest keys)"
      - "These interfaces stay internally scoped → conforms (nothing changes about what is published)"
partition: >
  serial, and deliberately ordered weakest-dependency-first. Chunk 01 owns
  `audio/{analyze,compare,report}.py` + tests; chunk 02 owns
  `handlers/render.py`, `actions/render.py` + tests. No file is named by both,
  and neither imports the other. 01 goes first because it is the guard that
  catches the whole class from the read side — including the cases 02's
  refusal cannot anticipate — so if only one ships, it should be 01.
last_validated: 2026-09-10
critic_mode: cumulative-final
---

# Build plan — RENDERGUARD-0910: a render under a soloed track is refused, and a master that is not the mix cannot be reported as a changed mix

## The incident

`incoming-bugs/2026-09-10-windowed-render-master-capture-13db-low.md`, including its
`## CORRECTION`. On `alien`, three consecutive renders produced a master surface
measuring **−22.6 LUFS-I** against a −8.6 baseline, and a `compare_to` advertising
"26 significant deltas / 112 section-level deltas" against a mix that had not changed.

**Cause: track 3 (Human Riff) was left soloed** (`solo: true`, `volume_db: −10.0`).
The master analyzer faithfully captured what the master bus contained — one track. The
0.9876 correlation with `track:3` is a correct capture of a soloed mix, the ~11 dB gap
is that track's own fader against a pre-fader stem tap, `return:2` was silent because
solo mutes the Voice that feeds it, and it survived a Live restart because solo is
saved in the `.als`.

**The superseded surface-binding reading in that file is wrong and is marked so.** No
indexing or binding fault exists; `surface_index: 0` is a red herring. This plan is
aimed at the two framework gaps that let a static, visible mixer state produce three
authoritative-looking wrong reports.

Filed as **#548** (the render does not refuse under solo) and **#549** (nothing gates
the report on the stem-sum residual).

## Requirements Confidence

**Level: High.** Both defects are confirmed by reading the code, and the incident
supplies the numbers each threshold is drawn against.

- **#549 — `sum_reconciliation` is computed, serialized, and read by nothing.**
  `audio/analyze.py:429` produces it; `:571` puts it on the report;
  `_derive_findings` (`:1385`) takes `integrity` and `phase_relations` and **not**
  `sum_reconciliation`, so it reaches no finding. `compare.py:148` computes master
  deltas unconditionally. The analyzer measured `correlation` **0.159** against a 0.959
  baseline and `gain_offset_db` **−32.65** — it *knew* the master was not the sum of
  its stems — and the report still read as a mix change.
- **#548 — the render neither refuses under solo nor records that it happened.**
  `ableton_render(action='start')` never reads solo or mute, and the manifest carries
  no mixer state, so a report cannot be audited for this after the fact. Solo is a
  normal thing to leave engaged while working by ear; a render is never valid under it.

**[ASSUMPTION: a soloed track always invalidates a render, while a muted one may be
deliberate.]** From the report's own reasoning and the incident. It is why 02 refuses on
solo and warns on mute — the asymmetry is a judgement, recorded here so it can be
overturned rather than discovered in the code.

## Out of scope

- **#482's reconciliation limits.** R1/R2 there fix what goes *into* the sum (return
  fader gains, per-surface unity reporting). Chunk 01 only *consumes* the result.
  Overlapping them would mean changing the number and the gate on it in one pass, and
  neither could then be trusted to have proven the other. 01 does not close #482.
- **The 16-beat probe render that reported `state: done` with header-only WAVs**, the
  `compare_to` naming a swept take, and the `back_to_arranger` refusal — all live in the
  same bug file, all real, none filed under this scope; the correction confirms the
  last is unrelated to this incident.
- Any change to the analyzer, the capture path, or surface binding. Nothing is wrong
  there, and the earlier reading that said otherwise is retracted.
- **Rack-chain solo.** Chain solo is first-class here (`handlers/device.py` `is_soloed`,
  the `device_chains.solo` column), and a soloed chain does change what renders — but it
  silences sibling chains inside one rack rather than the song, so it is materially
  weaker than a track or return solo and is new scope rather than a missed part of this
  guard. Filed rather than accepted, so it is not lost.

## Status

- [x] Chunk 01: a master the analyzer measured as not-the-mix is a blocking finding, and its deltas are refused
- [x] Chunk 02: a render refuses under a soloed track, warns under a muted one, and records the mixer state either way
- [x] Chunk 03: every lens block declares whether it gates, so none can ship inert

Context: cut from `origin/develop` @ `f6d6a2a` (detached HEAD; `develop` is checked out
in a sibling worktree owned by another session). Suite green at baseline via the
evidence store.

**An earlier pass on this branch built a fix for a surface-binding fault, on the
superseded root cause, and reverted it in full when the correction landed.** Recorded
because the branch's first name (`fix/master-surface-capture-binding`) is in the reflog
and a later reader deserves to know it was retracted rather than lost.

## Chunk 01 — the stem-sum residual gates the report

**Delivers.** `_derive_findings` accepts `sum_reconciliation` and emits a
`master_not_stem_sum` finding at `blocking` when correlation falls below a floor or
`gain_offset_db` leaves a band. `compare.py` refuses master and master-section deltas
on a report so disqualified, reporting the disqualification in their place.

**Why `blocking` is legitimate here.** `build-plan-render-integrity.md` design decision
2 exempts defect lenses from the analyzer's severity freeze: this is not an aesthetic
judgement but a measurement contradicting itself.

**Why stem deltas stay.** On the incident every stem was within 0.4 dB and correct.
Suppressing them would discard exactly the evidence that proves the master is the odd
one out.

**Acceptance.**
- A report with healthy reconciliation (baseline's 0.959 / small offset) produces no
  new finding and diffs exactly as today.
- A report carrying the incident's numbers (0.159 / −32.65) emits one `blocking`
  `master_not_stem_sum` finding naming both values.
- `compare_to` on that report emits no master surface deltas and no master section
  deltas, and says why — and the same holds when it is the BASELINE that is
  disqualified, since a stored report is re-used as a baseline for as long as it is the
  newest, and a capture made under a solo does not stop being wrong when later renders
  are measured against it.
- The refusal reaches the SUMMARY an operator reads, not only the report JSON: the
  significant-delta counts are what they act on, and a disqualified comparison makes
  those counts SMALLER, which without a stated reason reads as a quieter render.
- Stem deltas in that same comparison are unchanged.
- A report with no reconciliation at all (the lens skipped) is untouched — absence is
  not disqualification.
- Mutation check: revert the gate and the disqualification tests fail.

**Done when:** tests pass, `prawduct-hook test-evidence record`, artifacts updated,
`/prawduct:critic`.

## Chunk 03 — a lens cannot ship inert

**Arrived mid-build, from the user:** *"tests are suspect if that shipped"* — and they
are. The existing `sum_reconciliation` tests assert `is not None`, `.skipped is None`
and that it serializes. Every one pins that the number **exists and is correct**; not
one pins that anything **acts** on it. That is indistinguishable from a lens that
deliberately gates nothing, which is why the suite stayed green across the whole
render-integrity build while the defect sat in it.

Not a new requirement invented in chat: the gate-or-evidence split is already
`gate-verdict-policy.md`'s (defect lenses have physical ground truth and may block;
intent lenses rank authored intent and never fail a build). What was missing is that
nothing recorded WHICH each lens is, so no test could tell a deliberate evidence block
from a lens nobody wired.

**Delivers.** `FINDING_BEARING_BLOCKS` (block → the `_derive_findings` parameter that
reads it) and `EVIDENCE_ONLY_BLOCKS` (block → why it does not gate) on `report.py`,
and a test file asserting every `MixReport` measurement block appears in exactly one,
that a finding-bearing block's named parameter still exists, and that an evidence-only
exemption states a reason.

**Acceptance.**
- A `MixReport` block in neither map fails, naming it.
- Deleting `sum_reconciliation` from the gating map reproduces the original defect as a
  test failure — verified.
- A finding-bearing block whose `_derive_findings` parameter is removed fails.
- An evidence-only block with no stated reason fails.

**What it does not catch.** A parameter that exists and is ignored inside the function
body. Closing that needs the deriver to consume its inputs structurally rather than by
name, which is a redesign this scope does not carry — recorded so the guarantee is not
overstated.

## Chunk 02 — a render refuses under a soloed track

**Delivers.** `ableton_render(action='start')` reads solo and mute across
`song.tracks` AND `song.return_tracks` before arming — a return is a Track in Live and
carries solo, and soloing one silences every regular track's direct output. Any soloed
surface refuses the render, naming each. Muted surfaces warn and proceed. The manifest
records per-surface `kind`, `index`, `solo`, `mute` and the normalized fader `volume`
(the convention `master_fader_volume` already uses) so a report remains auditable after
the mixer state has moved on.

**Fingerprint flip: YES.** `handlers/` and `actions/` are both in
`_FINGERPRINT_PATHS`, so this does not take effect in Live until the operator
re-vendors the Remote Script and restarts Live. Queued for operator verification —
a refusal that fires against real Live solo state is not provable against a fake.

**Acceptance.**
- A song with one soloed track refuses, and the message names that track.
- Two soloed tracks are both named in one refusal.
- A soloed RETURN refuses, and the message names `return N` — the collection that is
  not `song.tracks` and is the easy one to miss.
- The refusal's own wording says `surface(s)`, not `track(s)`: it can name a return.
- A muted track or return warns, names it, and the render proceeds.
- A clean song renders exactly as today, with the new manifest fields present.
- The manifest carries solo/mute/volume for every track on a clean render.
- Mutation check: revert the solo read and the refusal tests fail.

**Done when:** tests pass, evidence recorded, `operator-verification.md` entry added
with `Visual change: no`, artifacts updated, `/prawduct:critic`.
