# Migration scrub decisions — markdown backlog → GitHub Issues

The owner-confirmed decisions for Hallucinote's one-time backlog migration
(`skills/backlog/migration-scrub.md`, MG4). This file is the audit record: the
migration is one-time and irreversible in part, so a choice remembered only in a
session transcript is a choice nobody can later audit.

## Which build ran it (runbook precondition)

| Fact | Value |
| --- | --- |
| `prawduct-hook version` | **3.3.0** |
| Plugin source | directory source `/Users/brookstalley/source/prawduct` (marketplace entry `prawduct`, `autoUpdate: true`) |
| Plugin ref at run time | `develop@2e1c1fc` (session banner) |
| `--plugin-dir` used? | No — the session loaded the directory-source marketplace plugin |
| `backlog` op present? | Yes — full op set incl. `import`, `restructure-preview`, `verify-migration`, `export` |

Recorded because a migration later found incomplete must be able to answer
*which build ran it* — the `samsung-frame-art-loader` precedent (7 of 9 items
never reached GitHub, cutover already recorded, no build recorded anywhere).

## Step 0 — target repo

| Decision | Value |
| --- | --- |
| **Target `owner/repo`** | **`brookstalley/hallucinote`** |
| Owner confirmed | 2026-08-10 |
| Issues enabled | Yes |
| Visibility at migration time | **PRIVATE** |
| Pre-existing issues on target | **0** (so `untriaged` is 0 and the completeness arithmetic is exact) |

Not inferred from the git remote — named and confirmed by the owner, per the
runbook's Step 0 guard.

**Flagged and accepted:** the backlog carries candid internal material — owner
rulings, Critic findings, dogfood bug reports. These stay private only as long as
the repo does. Flipping `brookstalley/hallucinote` public later publishes all 225
issues with it.

## Step 3c — archive scope

| Decision | Value |
| --- | --- |
| **`--archive-scope`** | **`all`** |
| Owner confirmed | 2026-08-10 |

**Why `all`, measured rather than assumed.** 70 of 111 live items (**63%**) cite
at least one archived id, spanning **60 distinct** archived items. Under `open`
the skipped archive stays only in the git-tracked source markdown, which the
skill stops reading at cutover — so no adapter op at any flag reaches it, and
those 60 cited ids would dangle inside the new tracker.

**Cost the owner accepted:**

- ~339 writes rather than ~111 (an archived item is a create *plus* a status
  reconcile to closed — the create path carries no initial-state field), all
  metered by `_PacingTransport`.
- ~20 minutes wall clock. Sized on serial `gh` round-trip latency × call count,
  **not** on rate-limit risk: a live 295-item `all` run measured zero pacing
  waits (VRF-009), so the 900-points/minute budget is a safety belt, not the
  governor.
- Titles needing a conforming rewrite rise from 97 to **192** (see below).
- Archived items are reachable but not visible by default — `list` defaults to
  `state=open`, as does add-time dedup, so seeing them takes an explicit
  `--state closed|all`. Under *either* scope archived items are absent from
  add-time dedup, so a duplicate of a previously-dropped item can be re-filed
  with no signal.

## Restructure pre-pass scope (Step 3b)

| Decision | Value |
| --- | --- |
| **Depth** | Titles + `kind` for all 225; **templated body sections for the 111 live items only** |
| Archive bodies | Preserved **verbatim** (runbook permits; templating closed history is cost without return) |
| Owner confirmed | 2026-08-10 |

Originals are preserved regardless — `original_title:` / `original_body:` block
fields, the MG2 export backup, and git history of the source file.

## Pre-import corpus state (measured with the plugin's own code, zero writes)

Via `migrate.collect_records` + `migrate.preflight_titles` against
`.prawduct/backlog.md`:

| Fact | Value |
| --- | --- |
| Total parsed records | **225** |
| Live (Open + Promoted) | **111** (110 open + 1 promoted) |
| Archived | **114** (103 shipped, 11 dropped) |
| Id collisions | **0** |
| Invalid-PFX / unaliasable ids | **0** — both Step 1b greps return empty |
| Non-conforming titles, scope `all` | **192 of 225** — 182 over the 72-char budget, 127 non-atomic, 1 placeholder |
| Non-conforming titles, scope `open` | 97 of 111 — 89 too long, 67 non-atomic |

Multi-segment ids (`AUD-TIMBRE-CALIB`, `ARR-FROMBUILD`, `PSH-PHASEORDER`,
`BLD-RESET`, `ARR-CMPHALT`, `ARR-ORPHAN`, `ARR-VERIFY`, `WS-BOOTSTRAP`) are
**valid** PFX shapes under `ids._PFX_RE` and were deliberately left alone —
renaming them would break inbound references across `related:` fields, the change
log, and `project-state.yaml`.

## Disposition table (Step 2 → Step 3)

Owner-confirmed **2026-08-10**. Applied at Step 7, *after* the
`verify-migration` gate passes, because confirmed dispositions are deliberate
divergence from the source and the gate cannot distinguish that from a stranded
item. Every item below still **imports first** — drops and merges do not reduce
the import set.

| id | action | reason |
| --- | --- | --- |
| `MCP-6B4W` | **merge → `MCP-7J2Q`** | Same root cause: `run_on_main` releases `_main_bout_lock` in a `finally` that also runs on the timeout path (`dispatch.py:200-204`), and the timeout cancels nothing. One coherent redesign of the timeout semantics closes both. Survivor retitled to the shared root. |
| `VEW-3M8F` | **drop** | Its verifiable signal now passes: `scope_rollups` in `project-state.yaml` is populated and `.prawduct/release-notes.md` exists. Separately, `regen-views` no longer exists in `tools/` — it moved into the plugin, so the subject is no longer product code. |
| `ARR-2S9D` | **keep, narrowed** | The spectral correlate shipped via `AUD-8T3K`: `SPECTRAL_CENTROID` exists (`audio/energy.py:46`) and is fed through `realize_energy` (`analyze.py:59`). `energy.py:39` reserves this item for *further* keys, so the remaining scope is retitled to that, not discarded. |
| `INS-6K1T` | **drop** | Native Linux support is gated on Ableton shipping a Linux build — an external dependency with no timeline. Re-file if that changes. |
| `SYN-7T3M` | **drop** | 24 chars, no scope and no verifiable signal — the vaguest item in the corpus. |
| `GEN-2T8M` | **drop** | Its own title said "REVISIT WHETHER NEEDED" and went 62d unrevisited; per-part `feel` baked at generation time is the standing answer. |
| `MIG-3T7K` | **drop** | Realtime concurrent editing / cloud DB is not at an actionable altitude; belongs in `VISION.md` if anywhere. |
| `ARR-8P5K` | **keep (open)** | A standing axis-taxonomy coherence guard that owes no new code. Not offered for a ruling; migrated as-is rather than assuming a drop. |

**Clusters examined and deliberately NOT merged** (the corpus-wide altitude
question, run before any title rewrite):

- `ENV-3M7K` / `ENV-4M2T` / `MIX-7K2D` — three different mechanisms, not one
  defect: planner auto-partition across per-section clips; clip-locked *return*
  device envelopes; and a decision-record on whether envelope identity admits
  per-section timelines. Verified by reading all three bodies.
- The `ING-*` family (6 items) — deliberate L0/L1 legs of one design. Better
  served by parent/child links than a fold.

**Verified genuinely open** (signal checked against code, all absent):
`AUD-5M8H` (no `AUDIO_CAPTURED`), `AUD-3K9D` (no reference fixtures),
`AUD-6T2K` (no `separation.py`), `DEV-1F9X` (no `hallucinote-core`; the
discriminator is still only in `compat.py`), `SCF-2N6T` (no rename path in
`push_cli.py`), `WSP-3R7K` (only `init_workspace.py` writes a `.gitignore`),
`EVL-9R3T` (snapshots timestamped 2026-05-31; the signal demands post-2026-06-01).

## Known data-quality gaps carried across (disclosed, not silently fixed)

- **32 of 111 live items carry no `Verifiable signal:`**, violating this
  backlog's own stated discipline ("Every item names a probe a future scrub can
  run"). Owner decision 2026-08-10: **migrate without an Acceptance section and
  file no follow-up.** Acceptance criteria were deliberately *not* invented for
  them — fabricating a requirement the source never stated is worse than an
  absent one.
- **11 items flagged `non_atomic`** for owner manual split (never auto-split: a
  split mints new ids, and 1 PFX = 1 issue): `DOC-7K3M`, `MCP-3D6Q`, `MCP-4B7W`,
  `AUD-7R3M`, `ARR-2B6K`, `AUD-3K9D`, `AUD-7W1N`, `EVT-4K8H`, `TST-8K1M`,
  `SYN-8Q3F`, `MEL-1A7K`.
- **143 `body-too-long` WARN-only lint findings.** Not blocking on any write
  path; these bodies are deliberately rich (rationale, boundary notes, probes).

## Restructure plan verification (offline, zero writes)

| Check | Result |
| --- | --- |
| Plan entries | **225** over 225 source items (114 archive title+kind, 111 live title+kind+sections) |
| `restructure.apply` | `ok: True`, 225 entries, **0 warnings**, 0 unaddressable |
| `preflight_titles` on the applied records | **0 blocking offenders** — the import will not refuse |
| Title lengths | min 43, max 67, against the 72 budget |
| Body sections | Derived from each item's own structure (`**Verifiable signal:**` → Acceptance; `**Boundary/NARROWED/...**` → Scope-out). Nothing paraphrased; `original_title`/`original_body` preserved verbatim by the importer. |

## Import (Step 4) — what actually happened

Ran in **two passes**, both with `--archive-scope all --restructure plan.json`:

1. First pass took a **GitHub 502 on a `repos/…/labels` call after 127/225
   created** and cut resumably (`resumable: True`, 0 failed, 0 collisions, 0
   unreconciled).
2. The resume created the remaining **98**, skipping the 127 already-migrated on
   their `id:PFX` alias: `98 created, 127 skipped, 0 rejected, 0 collision(s) of
   225 source item(s) (225 restructured by plan)`.

Pacing: ≥2303 REST points, **no throttling — the budgets never bound**, matching
VRF-009's finding that serial `gh` latency, not the rate ceiling, governs.

> **Trap worth recording.** The first pass was piped through `tee`, so the shell
> reported **tee's** exit code — the failed import looked like exit 0. Read the
> log body, never the exit status. Both WARNING lines the runbook names
> (`N rejected`, `N imported but NOT reconciled`) were absent on the final pass.

## Step 6 gate — passed

    prawduct-hook backlog verify-migration --repo brookstalley/hallucinote \
      --from .prawduct/backlog.md --archive-scope all

**Exit 0**, with the same `--archive-scope` used at import:

```json
{"repo": "brookstalley/hallucinote", "source_items": 225, "aliased": 225,
 "missing": [], "unaliasable": [], "collisions": [], "status_mismatch": [],
 "duplicate_alias": []}
```

## Cutover — recorded 2026-08-10

- `backlog_service_repo: brookstalley/hallucinote` set in
  `.prawduct/project-state.yaml`.
- Frozen-history **blockquote** banner written at the head of
  `.prawduct/backlog.md` (a blockquote, not an HTML comment, which is invisible
  in GitHub's rendered view), naming the cutover date, the tracker, the read
  commands, and that divergence from the tracker is expected.
- `legacy.py` deliberately **not** retired — that is portfolio-wide, not this
  repo's business.

## Step 7 dispositions — applied after the gate

| id | action | result |
| --- | --- | --- |
| `MCP-6B4W` | merge → `MCP-7J2Q` | `#324 --superseded-by--> #322`; #324 CLOSED, survivor #322 OPEN |
| `VEW-3M8F` | dropped | #249 CLOSED |
| `INS-6K1T` | dropped | #273 CLOSED |
| `SYN-7T3M` | dropped | #286 CLOSED |
| `GEN-2T8M` | dropped | #272 CLOSED |
| `MIG-3T7K` | dropped | #289 CLOSED |

Every disposed item confirmed **closed, not missing** — the check Step 5 could
not yet make. Final rollup: **225 items — 105 open, 103 shipped, 17 dropped**
(111 open − 6 disposed = 105; 11 + 6 = 17). Local cache synced (225 rows, FTS
on) and the briefing snapshot persisted.

> ⚠️ **Do not re-run `import` or `verify-migration` from here.** The import
> reconciles status against the *source markdown*, so a re-run reopens all six
> disposed items; the gate would report each disposal as `status_mismatch` and
> exit 4 on a migration that is entirely correct. If something is wrong now, fix
> it on the tracker.
