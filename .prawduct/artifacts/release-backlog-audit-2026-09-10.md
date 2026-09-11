# Release backlog audit — 2026-09-10

**Scope of the audit:** the 91 open backlog items on `brookstalley/hallucinote`,
read against the 19 release-pending change-log scopes sitting on `develop` since
v1.8.6. The question asked: *what else should be folded in before the cut?*

**The shape of the answer.** The release window (2026-09-08 →) filed **63 backlog
items**; **36 are already closed** and shipped in these scopes. **27 are still
open**, and every one of them is residue of this release's own work. Those 27 are
where a fold-in decision lives — the other 64 open items predate the window and
are ordinary roadmap.

Of the 27, **six are coupled**: they ship a defect, a half-closed gap, or a
bookkeeping claim that is now false. The rest are honest follow-on.

## Fold in

| # | Effort | Why it is coupled | Verified |
| --- | --- | --- | --- |
| **#533** | — | **Already fixed; the item was never closed.** `_param_write_kwargs` hands the wire a string (`chain_rebuild.py:826`), and `scope=CHAIN-RESTORE-STR` is in the change-log. This is a `status=shipped`, not work. | `chain_rebuild.py:826-838` |
| **#534** | M/M | ~~`chain-rebuild`'s post-rebuild verify is **measured** to lie: `_PARAM_EPSILON = 1e-6` is absolute while float32 round-trip error is relative, and integer-stepped params breach it outright.~~ **WRONG — see the correction below.** The measurements are real and describe a path this module does not take. | `chain_rebuild.py:1185`, used `:1249` |
| **#544** | S/M | The unreadable-sidechain-source warning exists and fires on **two** surfaces — capture and push — and not on the third, which is the **destructive** one: `chain-rebuild` deletes and reloads, so a hand-set source is destroyed outright and silently. ~4 lines, no new predicate. | helpers at `capture.py:1909/:1929`; callers `capture.py:2019`, `push/plan.py:817`; **absent** from `chain_rebuild.py` |
| **#546** | S/S | Residue of #532, whose other half shipped. `device load` lands past the analyzer tap and says nothing; the state is transient and self-healing, but only the source says so. | zero `analyzer` references in `actions/device.py` |
| **#545** | S/S | Same sidechain cluster as #544 — cheaper together than twice. | — |
| **#526** | — | **An obligation this release created.** #537 closed today. #526's body says in terms: *"must NOT be built as currently written"* and *"not to be closed on #537's merge without someone reading the residue first."* That read is owed now, before the cut classifies the scope. | #537 `CLOSED 2026-09-10T20:28:03Z` |

Four of the six are S-effort or smaller; #534 read as the only real build and
turned out not to be one.

### Correction — #534 is not reachable, and this audit got it wrong

Added 2026-09-10, after the fold-in. **This row was the audit's one bad
recommendation and it is left standing above rather than quietly rewritten**,
because the reason it was wrong is the lesson.

The defect cannot reach the path `chain-rebuild` takes. `capture_chain` reads
every parameter **off Live**, `_restore` writes that same journal value back
verbatim, and `_verify_parameters` compares the two — so both ends are the same
Live-sourced float and the delta is zero by construction, not by tolerance. A
22 kHz frequency and a 41-step bend range round-trip at **exactly 0.0** through
the module.

That reproduces the item's own **Pass 1**. The item documents two measurement
passes and says in a heading *do not conflate them*: Pass 1 re-wrote each
parameter's existing value and round-tripped at 0.0 across 29 parameters; Pass 2
perturbed values off-grid and produced the breaching deltas. Every number in the
item's Actual section is Pass 2 — and Pass 1 is the production path.

**The audit repeated the item's framing instead of checking its premise against
the code.** Three of the six coupled items turned out to be wrong about the code
they described (#534 here, #544's mechanism, #526's blocker), and all three were
filed within three days by agents with the code in front of them. A backlog item
is a claim with a timestamp, not a finding. The fix to this audit's method is one
five-minute code read per item *before* recommending it, not after.

What shipped instead: two tests pinning the property that makes the tolerance
safe — the restore never invents a value — because nothing pinned it before.

## Decide before the cut — do not let these ship silently

- **#550 — the solo guard ships with a known hole.** RENDERGUARD-0910 refuses a
  render under a soloed *track or return*; a soloed rack **chain** is invisible,
  and chain solo is first-class here (`is_soloed`, `device_chains.solo`). It sits
  at `stage:design` because the refuse-vs-warn call is unmade, so it is not
  buildable as filed. Make the call and ship it (S/M), or ship the guard with the
  limitation named in the release notes. Shipping it unmentioned is the bad
  option.
- **#482 — the gate is now blocking over a sum with known limits.** RENDERGUARD
  turned `sum_reconciliation` into a **blocking** finding. #482's R1/R2 change
  what goes *into* that sum: a return with a non-unity fader is summed at full
  pre-fader level and **inflates the residual**. The prior session deliberately
  kept these apart so each proves the other — that reasoning holds — but it means
  the release ships a blocking gate over a sum that can read high for a benign
  reason. This is the same false-positive exposure the RENDERGUARD handoff flags
  as its box 7.
- **#529 — its premise is now partly false.** The body says *"`manifest.json`
  records no fader values."* RENDERGUARD added per-surface `mixer_state` to the
  manifest. Re-read and re-scope, or the item misleads whoever picks it.

## Not backlog, but blocks a clean cut

1. **`architecture.md` does not know about three new packages.** `assets`
   (9 files / 2,491 lines), `features` (8 / 1,413) and `spectral` (7 / 1,763) are
   all **new since v1.8.6** — 5,667 lines — with **zero** mentions in the
   architecture doc. The session briefing is firing this as a staleness advisory.
   Living Documentation: the reader's map does not contain a third of the new code.
2. **35 unticked operator-verification boxes** across 7 sections. Two matter for
   the cut: the **#291 witness FAILED twice**, its two defects are now fixed
   (#532, #533) and the box is **unblocked but not re-run** — nothing has proven
   the chain-rebuild fix against a real chain; and **RENDERGUARD box 7**, which
   prices the stem-sum false positive and is the one the handoff calls most
   important.
3. **Five release-pending scopes have no build-plan file** — `CHAIN-RESTORE-STR`,
   `docs-hygiene`, `governance-file-sizes`, `advisory-clearing`,
   `effort-s-burndown`. `check-releasability` warns on each: work shipping with no
   plan describing it.
4. **An open bug report with three unfiled defects.**
   `incoming-bugs/2026-09-10-windowed-render-master-capture-13db-low.md` is still
   in the drop-box. Its three suggested fixes shipped, but three observed defects
   were never filed: a 16-beat probe render that halted before its record window
   yet reported `state: done` with 104-byte header-only WAVs; a `compare_to`
   naming a report whose take retention had swept it; and the `back_to_arranger`
   refusal.
5. **#489 — the R5 upstream report is still unsent**, and this repo is now firing
   the exact advisory it describes (item 1 above is the symptom). R7 needs no new
   issue; it is comment material on `brookstalley/prawduct#724`. Egress is an
   owner decision, not an agent action.

## Read on the version

This is **not a patch**. `v1.8.6..HEAD` is 473 files, 76k insertions, three new
packages and new product capability across `audio/`, `sync/push/`, `assets/`,
`spectral/` and the MCP handlers. The `RELBLK-V19` scope name says v1.9 was
already the intent.

## Recommendation

Fold in **#533** (a close), **#544 + #545 + #546** (one small sidechain-and-tap
batch), and settle **#526**'s residue read. ~~Build **#534**~~ — **withdrawn**,
see the correction above: the defect is unreachable, and what it needed was the
test that pins why, not a tolerance change.
Decide **#550** explicitly. Leave **#482** out on the prior session's reasoning,
but say so in the release notes rather than silently.

Then close items 1-3 of *Not backlog* before the cut: the architecture doc, the
#291 re-run, and either plans or explicit no-plan dispositions for the five
bare scopes.

---

# Second pass — after RELFOLD-0910 merged

**Asked again:** *what else should be folded in before the cut?* Pass 1's six
items shipped (`64ac62d6`), so this pass re-reads the backlog against a tree
that already has them.

**Method, corrected.** Pass 1's own postmortem said its fix was *one five-minute
code read per item before recommending it, not after*. Every claim below was
read in the code first. Two candidates died that way, and they are recorded as
deaths rather than omitted — that is the point of the correction.

## The numbers

The release window (2026-09-08 →) has now filed **65** items: **41 closed**,
**24 open**. Backlog total is **88 open**, down from 91. The delta since pass 1
is five closed (#533, #544, #545, #546, #550) and two filed — **#552** and
**#553**, both raised by RELFOLD's own Critic rounds. Those two are the only
genuinely new fold-in decisions. The other 22 open window items were
dispositioned in pass 1 and nothing has moved under them.

## Fold in

| # | Effort | Why it is coupled | Verified |
| --- | --- | --- | --- |
| **#553** | S | One test for a branch **shipping in this release**. `_warn_under_chain_solo`'s envelope has three heads; the `elif certain:` head (some chains soloed, some unreadable) is the one #550 added and the only one untested. The read is correct and the arithmetic is sound — what is unpinned is the wording of an operator-facing sentence that only fires in the mixed case. | `handlers/render.py:359` |

That is the whole fold-in list. One test.

## Verified NOT to fold in — the code disagreed with the case for each

- **#552 (master strip is never walked) — ships as a named limit, on #550's own
  precedent.** The item is real: `_mixer_state._read()` walks `song.tracks` and
  `song.return_tracks` and never the master, so a soloed chain in a master rack
  is invisible and `manifest.mixer_state` has no master row. But it is **not
  silent**, which is the bar pass 1 set for #550 ("ship the guard with the
  limitation named, or fix it — shipping it unmentioned is the bad option").
  The limit is written in three release-visible places: the RELFOLD-0910
  entry in `change-log.md` (2026-09-10, *“Two limits the read never had”*),
  `architecture.md` § *What is deliberately not modeled*, and
  `boundary-patterns.md:295` — plus `_soloed_chains`' own docstring at
  `render.py:316-322`. It is also **not the one-line fix it looks like**: Live's
  master carries no `solo` attribute, so a naive master row reads `solo: None`
  and `_refuse_under_solo` — which deliberately refuses on an unreadable flag —
  would refuse **every render**. M-effort, `stage:design`, correctly out.

- **#495 (`PushPlan.warn()` writes the discarded channel) — the trap is latent,
  and RELFOLD did not fall into it.** This was worth re-asking, because RELFOLD's
  reflection names "I made the value correct" ≠ "the value arrives" as the
  failure it committed twice, and #495 is that failure's shape in the push
  planner. So: did RELFOLD's new sidechain warning go into `notes` (discarded)?
  **No.** `push/plan.py:820-823` routes it to `notes_sink` — the report's
  "Warnings (push still OK)" section — with a fallback to the returned list when
  no sink is given, and a comment reasoning about exactly that choice. The
  chain-rebuild half (`7215d6bf`) writes **both** `_operator_note` (stderr) and
  `alerts`. Both new warnings arrive. #495 stays what pass 1 called it: a live
  trap for the *next* author, not a defect in shipped behaviour.

- **The drop-box report's three unfiled defects — two are not defects, and the
  third is already caught.** `incoming-bugs/2026-09-10-windowed-render-master-capture-13db-low.md`
  is still in the drop-box and pass 1 flagged three observed defects in it as
  never filed. Read against the code:
  - *`state: done` with 104-byte header-only WAVs* is a **deliberate two-field
    contract**, not a defect: `render.py:1028-1034` documents `state` as the
    terminal-completion signal an agent polls and `render_status` as the
    ok/incomplete verdict, and `skills/render-analyze/SKILL.md:59` relays both.
    And the empty capture is **not silent downstream** — `measure_capture_span`
    compares captured duration against the manifest's declared span and
    `analyze.py:1432` raises `capture_span_mismatch`. A header-only WAV fails
    that by the whole window.
  - *`back_to_arranger`* — the report's **own correction** calls it unrelated to
    the incident and untested either way.
  - *`compare_to` naming a report whose take retention swept* — real, but a
    retention/ergonomics gap (the JSON survives; the audio for follow-up
    measurement does not), not a correctness failure. Ordinary roadmap.

  The report's **three suggested fixes all shipped** — the `sum_reconciliation`
  gate and the solo refusal as #548/#549, the manifest mixer state as
  RENDERGUARD. **The report is discharged and should be archived out of the
  drop-box**, with the `compare_to` retention note filed if it is wanted.

## Still owed before the cut — one new, one fixed, the rest unchanged

1. ~~`architecture.md` does not know about three new packages.~~ **Fixed** in
   RELFOLD — `assets`, `features` and `spectral` are all named now.
2. **`planless-scopes-disposition.md` is one row stale.** It answers five
   planless scopes; `check-releasability` now warns on **six**.
   **`MYPY-COMPARE-0911`** merged with #555 *after* the disposition was written
   and has no row. It is a legitimate no-plan (a single mypy error, one type
   widened — trivial by the size heuristic), so it needs the row, not a plan.
   An artifact whose only job is to answer that warning is the one place a
   missing row costs something.
3. **The operator-verification boxes are unchanged and not startable from here.**
   The #291 witness is unblocked (both defects fixed) and **never re-run** —
   nothing has proven chain-rebuild's restore against a real chain — and
   RENDERGUARD box 7 still has not priced the stem-sum false positive. Both need
   an attended Live sitting with a single writer.
4. **The suite is unproven for the cut.** `check-releasability` reports
   `unproven-suite`: the recorded evidence predates this session. A release
   publishes unrecallably; the cut needs a run recorded against the tip.
5. **#489's R5 upstream report is still unsent.** Egress crosses an owner
   boundary — unchanged, and still not an agent action.

## Recommendation

**Fold in #553** — one test, covering release code, and the cheapest item in the
window. Nothing else earns its way in.

Ship **#552** as a named limit on #550's precedent (already satisfied — no
action). Leave **#482**, **#534**, **#526**, **#529** and **#495** exactly where
pass 1 and RELFOLD put them; all five are dispositioned on the record.

Before the cut: add the `MYPY-COMPARE-0911` row, archive the discharged
drop-box report, record a suite run, and get the two operator boxes sat.
