# Project Preferences

Developer preferences for how code is written in this project. Captured during discovery, updated as preferences evolve. Every session should read this before writing code.

## Language & Runtime

- **Language**: Python
- **Version**: 3.10+ (declared in `pyproject.toml`); local venv uses 3.12
- **Package manager**: **`uv`**, against the locked environment. `uv.lock` is authoritative and CI gates `uv lock --check`; the plugin builds its environment with `uv run --frozen`. Skills invoke the CLI as `"$PY" -m hallucinote.cli <cmd>`, resolving `$PY` once from `ableton://server/info`'s `python` — the interpreter of the env the plugin already built (`docs/running-the-engine.md`); the older `uv run --project <plugin-root> --frozen hallucinote <cmd>` spelling is no longer what ships. (Ratified 2026-08-10: `uv` is the norm because it is the one with CI enforcement behind it. A local `pip install -e .[dev]` venv still works for editing and is not forbidden, but it is a personal convenience — nothing verifies it, and a "green" claim must come from the locked environment.)

## Code Style

- **Naming**: `snake_case` for functions/variables, `PascalCase` for classes, `UPPER_SNAKE` for module-level constants (see `generators/primitives.py`, `db/events.py`)
- **Formatting**: No formatter configured. Project follows PEP 8 spacing and ~88-col lines by convention. (Critic-enforced.)
- **Linting**: `ruff check .` and `mypy`, both configured in `pyproject.toml` and both
  gating CI on every push/PR to `develop` and `main` (INF-2C4X, `.github/workflows/ci.yml`).
- **Type annotations**: Required on public functions. PEP 604 unions (`int | None`), `Sequence`/`Iterable` from `typing` for inputs, concrete `list[...]` for outputs. `from __future__ import annotations` at the top of every module.
- **Imports**: Absolute (`from hallucinote.db import mutations as M`). Grouped stdlib / third-party / local with blank lines between groups. Aliases used freely for cross-module clarity (`mutations as M`, `events as E`).
- **Docstrings**: Module docstrings stating intent + discipline. Function docstrings explain *why* and any non-obvious convention, not signatures (types carry that). One-liners are fine for trivial helpers.
- **Comments**: Sparse. When present, they capture invariants, design rationale, or workarounds — not what the code does.

## Testing

- **Framework**: `pytest>=8.0`
- **Style**: Descriptive function names (`test_replace_clip_notes_is_atomic`), assert-style, fixtures for shared setup. Helpers like `_make_note` for terse cases.
- **Coverage expectations**: Happy path + key error paths. Event-emission paired with state change for every mutator. Cascades/FK behavior covered explicitly.
- **Testing strategies**: Example-based plus property-based via Hypothesis (enabled Wave M-4 for the first invariant-rich surface). `tests/conftest.py` registers `dev` (max_examples=20, default) and `ci` (max_examples=200, opt-in via `HYPOTHESIS_PROFILE=ci`) profiles. Active property tests: `tests/unit/generators/test_bar_beats_properties.py` (note-array transforms) and `hallucinote_mcp/tests/unit/test_envelope_properties.py` (envelope breakpoint validation). Extend Hypothesis coverage when a surface has clear named invariants worth fuzzing.
- **Test location**: three categories, intentionally separated.
  - **Platform / authoring** (`hallucinote` library) — `tests/unit/{db,sync,generators,capture}/` mirrors `src/hallucinote/` packages. NO song-specific code or data; use synthetic fixtures.
  - **MCP plugin** (`hallucinote-mcp` package) — `hallucinote_mcp/tests/{unit,integration}/` mirrors the MCP package layout. NO song-specific code or data.
  - **Song-specific** — `<slug>/tests/test_*.py` lives alongside `build.py` and `captured_session.json` in the song's workspace, so each song is a self-contained unit (per `docs/VISION.md` "songs as git repos"). Authored songs live in their own workspace repos (the framework⇄songs split); the one in-repo case is the `examples/` bounded exception, whose demo song's tests (`examples/punk-fate/tests/`) run in this repo's default suite. These tests assert song-level shape (track count, a baseline note count, the expected sections in order) and may load that song's snapshot; thresholds live in the test files. Per-song test filenames must be unique across songs (`test_<slug>_build.py`, never bare `test_build.py`). These tests never test platform behavior incidentally.
  - Pytest discovers all three via `[tool.pytest.ini_options].testpaths`; `pyproject.toml` holds the authoritative list, so this prose points at it rather than restating a value that drifts. Song test dirs intentionally have no `__init__.py` (rootdir-discovered) so they don't collide with the platform `tests/` package namespace.
- **Parallelization**: `pytest-xdist>=3.6` is declared in `[dev]` deps and installed. The auto-grouping in `conftest.py` assigns each test file an `xdist_group` based on its parent directory, so same-directory tests stay serial on one worker (preserving fixture isolation) and different directories fan out. Default invocation is serial; `pytest -n auto --dist loadgroup` opts into parallel (~5s vs ~10s serial as of post-J-2 baseline).

## Architecture Patterns

- **Data modeling**: SQLite with raw schema in `db/schema.sql`. Rows surface as `sqlite3.Row` for reads; mutators take/return primitive dicts and ints. Dataclasses (`@dataclass`) for in-process value objects like `ToolCall` / `PushPlan`.
- **Error handling**: Plain exceptions (`ValueError`, `KeyError`). No custom exception hierarchy. Never swallow exceptions silently — waive a genuinely necessary broad catch with `# prawduct:allow prawduct/broad-except -- <reason>`, stating the reason. This is the only spelling a new site may use: the legacy `# prawduct:ok-broad-except` form was migrated out of the code in full (2026-08-11), and the check is `git grep -n 'ok-broad-except' -- '*.py'` returning nothing. An unqualified tree-wide grep still hits `.prawduct/` records, which carry the retired spelling as append-only history and must not be edited to make a grep pass.
- **Async**: **The `hallucinote` engine and CLI are sync throughout** — SQLite WAL + `timeout=10.0`, no async planned, because this is a single-user authoring tool with no concurrency to serve. **This does not extend to the MCP server**, where every tool handler is `async` and dispatches through `anyio.to_thread`: FastMCP runs sync tool functions inline on the event loop, so a blocking handler freezes the whole server. That is an availability norm and it wins at its layer — see `architecture.md` § Direction.
- **File organization**: Layer folders inside `src/hallucinote/`: `db/` (state + events + mutators + queries), `generators/` (pure musical building blocks), `sync/` (DB↔Ableton bridge). Song-specific builders live at `<slug>/build.py` in a song workspace (in this repo: `examples/punk-fate/build.py`, the bounded exception) and consume the library.
- **DB discipline (load-bearing)**: All writes go through `db.mutations`. Every mutator emits an `events` row in the same transaction. This is the seed for an eventual event-store flip — see `MEMORY.md`. **Never use raw SQL in callers** outside `db/`.
- **Generators are pure**: `generators/*` functions take parameters and return `list[NoteDict]`. They never touch the DB or MCP. Persistence happens at the caller.
- **Sync is a plan, not a side effect**: `sync.push` returns `PushPlan` / `ToolCall` objects. The agent executes; `apply_push_results` feeds outcomes back into the DB. Keeps the layer testable without Live running.

## Tooling

- **Key libraries**: **the MCP server is stdlib-only *at import time*** (`sqlite3`, `json`, `dataclasses`, `pathlib`) because the Remote Script imports it inside Live — engine imports are lazy, at call time. The **engine itself depends on numpy/scipy/librosa/soundfile at runtime**, deliberately, and that stack must not be trimmed to shrink the build (`nonfunctional-requirements.md` § Direction). `pytest` for tests. The MCP bridge (`hallucinote_mcp/`) is in-repo and ships with the plugin — not an external dependency.
- **Dev commands**:
  - `uv run --frozen pytest` — the locked environment; this is what a "green" claim must come from
  - `pytest` — full suite in a local editable venv (serial by default; under ~10s on the J-2 baseline)
  - `pytest -n auto --dist loadgroup` — parallel via pytest-xdist (auto-grouped by test subdirectory per `tests/conftest.py`; roughly 1.6× faster)
  - Current test count + timings: see `.prawduct/.test-evidence.json` (canonical; this prose intentionally avoids restating numbers that drift)
  - `python examples/punk-fate/build.py [--reset]` — build the demo song into its SQLite DB
- **DB files (prescriptive)**: **one SQLite DB per song**, in the song's own directory (`<songs_root>/<slug>/`), named `<slug>-<branch>.db` inside a git repo (branch sanitized `/` → `--`) and plain `<slug>.db` outside one or on detached HEAD — `db.connection.resolve_db_path` owns the rule. The directory name and `songs.name` (the slug) must match. The slug is filesystem-safe: `[a-z0-9_-]+` (lowercase, digits, hyphens, underscores). Human-facing names with spaces / capitals / punctuation go in `songs.title`. No sidecar config files; the DB schema is the source of truth for song metadata. `*.db` is gitignored.

## Documentation & prose

- **Write what a thing IS. Never define it by what it isn't.** (Ratified 2026-08-11; **absolute reading restored by owner ruling 2026-08-12**; retroactive — apply when touching existing prose.) State the capability, the mechanism, the fact; the negative space is implicit and the reader draws it themselves. *Why:* defining by contrast argues with someone who isn't in the room, which reads as defensive and plants the doubt it set out to answer — and it dates the doc to whatever it was reacting to.

  **The banned form is a contrast-definition**: a sentence that characterizes the product, a component, or the process by naming a thing it isn't. `"unlike X"`, `"what makes this different from Y"`, `"this isn't a Y"`, `"we don't do Z"`, a `## What it isn't` section, an FAQ entry answering a critic — and equally the quieter shapes: "a long agentic workflow, not a chat", "Ableton is the speaker, not the score", "verified, not assumed". Rewrite each positively; the rewrite is almost always the better sentence, because it has to say the thing outright.

  **The test: does the sentence name a foil?** A foil is an alternative the subject is set against. "Ableton is the speaker, **not the score**" names one — so does "a long agentic workflow, **not a chat**". That is a contrast-definition, and it is banned. **Plain negation names no foil**: "Live isn't running", "verify consumers aren't broken" deny a predicate and offer nothing to measure the subject against, so they stay. (An earlier wording of this test asked whether removing the negated half left the subject undefined. It was self-invalidating — "Ableton is the speaker" survives that deletion perfectly well, so the test cleared the very sentence the row bans. Replaced 2026-08-12 after the Critic caught it; do not reinstate it.)

  **Four carve-outs, all owner-ratified. Nothing here is pending, and adding a fifth is a ruling, not a judgment call:**
  - **Naming prior art as lineage** — "plain-text music has a long line behind it: TidalCycles, Sonic Pi, Lilypond, DAWproject". Naming other tools is fine; ranking yourself against them is the banned move. (Ratified 2026-08-12.)
  - **A limitations register**, which states plain facts rather than defence. In scope that is VISION's `## Non-goals`, SECURITY's out-of-scope list, and CONTRIBUTING's CI-gaps section; `docs/known-issues.md` is the same genus but sits outside the scope above, so it is an illustration rather than a governed case. (In the owner's original 2026-08-11 wording as "Narrow exception" — it did **not** arrive with the rejected narrowing.)
  - **A prescriptive rule may prohibit.** "Write tests alongside the code, never after" is an instruction, not a description of a thing. The norm governs prose that *describes*. (Ratified 2026-08-12, having been applied by that day's sweep and recorded as pending until the owner ruled.)
  - **Verbatim quotation is untouchable.** `docs/tour.md` quotes session transcript, the user's own words, and code from `build.py`. Rewriting captured evidence to satisfy a prose norm would falsify the thing the page exists to show — the tour's whole claim is that its artifacts were captured rather than staged. (Ratified 2026-08-12, same route.)

  **Scope — positioning prose** (owner-set 2026-08-12). The criterion: **prose a prospective user or contributor reads while deciding whether to use or contribute to this project.** Today that is exactly `README.md`, `CONTRIBUTING.md`, `SECURITY.md`, `docs/VISION.md`, `docs/faq.md`, `docs/tour.md` — and a new file meeting the criterion (a landing page, a pitch, a getting-started doc) joins the scope by being what it is, without needing a ruling. Reference docs elsewhere under `docs/`, agent-read `skills/`, `.prawduct/artifacts/`, shipped song artifacts under `examples/`, and the frozen `docs/archive/` are outside it — in operating instructions the construction disambiguates ("the list itself, not the wrapper") rather than defends, and precise agent instructions are the product. Pulling an *existing* out-of-scope file in is the owner's call, not a sweep's.

  **This scope clause governs THIS row only.** The person-centred positioning norm below is deliberately unscoped and stays tree-wide — that is the norm whose own bundle missed "Claude authors MIDI and the mix" in five surfaces, and narrowing it by proximity to this row would undo that lesson.

  **A note for whoever is tempted to narrow this.** It was narrowed twice by the agent on the day it shipped, both times right after review found prose violating it, and the owner rejected the first narrowing on review. "The corpus violates it" is evidence about the corpus. If a sentence seems to need a third carve-out, surface it and let the owner rule — editing the rule to fit your own prose is the failure this line exists to catch.
- **Markdown prose uses semantic line breaks — one sentence per line.** (Owner-set 2026-08-12.) A sentence ends, a newline follows; no hard wrap at a column, and no whole-paragraph-on-one-line either. *Why:* a hard wrap makes a one-word change reflow its paragraph, so the diff reports a paragraph where a word changed — this branch generated an entire whitespace-only reflow commit before the rule existed, which is the cost made visible. Rendered output is unaffected: markdown folds single newlines inside a paragraph. **Applied so far to the positioning corpus** (README, CONTRIBUTING, SECURITY, VISION, faq, tour). The rest of `docs/` and `skills/` are still hard-wrapped at ~70 columns; convert a file when you next touch it substantially, in its own whitespace-only commit, never mixed with a wording change. **Any mechanical rewrap must verify the word stream is unchanged before writing** — the transform that did the first six refused a file when a closing quote went missing, which is the failure mode to design against.
- **Positioning centres the person, not the tool.** (Ratified 2026-08-11 alongside the row above; retroactive on the same terms — apply when touching existing prose, and the "Claude authors MIDI and the mix" survivors this norm's own bundle missed are the worked example of why a sweep has to be tree-wide.) The user holds the subject position on the creative verbs; the tool builds, measures and reports. Concrete and modest, and allowed to convey that the thing is enjoyable — powerful and fun are compatible with understated. Steer clear of grandiosity ("a revolutionary way to write music") and of condescension ("now you don't have to do the hard stuff") alike; both cost credibility with the people this is actually for.

## Workflow

- **Branching model**: **gitflow** — `develop` is the primary integration branch; `main` is release-only.
- **Branching**: feature-branches — every feature/fix branch is cut from `develop` and PR'd back to `develop`. Direct commits to protected branches only for trivial fixes (and only when `Branching` is `direct`, which it isn't here).
- **Branch flow**:
  - `feature/...` / `fix/...` / `refactor/...` → PR target: `develop`
  - `develop` → `main`: release PRs only; cut periodically when a batch of work is ready to ship. No direct commits to `main`.
- **Protected branches**: `main`, `develop` (no direct commits).
- **PR creation**: `wait_for_user` (default — only create PRs when explicitly asked; set to "automatic" to create PRs after Critic review passes).
- **PR merge**: `automatic` — merge after CI passes (or no CI configured) and PR review is clean. The cumulative Critic + independent PR reviewer gates already provide review independence; a second user-side confirmation adds friction without added safety.
- **Backlog backend**: **GitHub Issues** on `brookstalley/hallucinote` (cutover 2026-08-10 — `backlog_service_repo` in `project-state.yaml`). Reach it through `/prawduct:backlog` or `prawduct-hook backlog <op> --repo brookstalley/hallucinote`; ids resolve via each issue's `id:<PFX>` label. `.prawduct/backlog.md` is frozen history and is not read. Two consequences worth knowing before you rely on a read: archived items need an explicit `--state closed|all` (`list` defaults to open, as does add-time dedup), and **a wrong `--repo` returns a confident answer rather than an error**, so a typo reads as an empty backlog rather than a failure.
- **Backlog norms (load-bearing — these three outlived the markdown file they were written in)**:
  1. **Close-in-the-same-PR, as ONE ship-stamp commit.** When a PR ships work resolving a backlog item, land the whole ship-stamp as a single commit on the branch: the backlog close (`status=shipped` + `closed-by:`), the change-log entry, and any project-state record together — never three bookkeeping commits (**PRC-5W2N**). The git log is the audit trail. Critic + PR reviewer flag PRs that ship work matching an open item without closing it. *This is the rule `docs/release-process.md` and `docs/song-authoring-conventions.md` cite; it lives here now, not in a frozen file.*
  2. **Verifiable signal required.** Every item names a probe a future scrub can run to confirm it is still pending — a `file:line`, a function to grep, a CLI to run, or a behaviour to reproduce. Without one the item is unscrubable. (Known debt: 32 items migrated at cutover carry no signal.)
  3. **Trust-but-verify on scrub.** A scrub re-reads code against each item, not just the item's text. Items whose `added`/`reviewed` is more than **30 days** old are suspect. (Tightened from 60d by the 2026-07-02 audit: this repo's velocity made 60d too slow — the BLG-7K2Q precedent found 4 of 8 `ready` items already shipped. The 2026-08-10 migration scrub found 2 more.)
- **Backlog prerequisites**: backlog reads/writes now need the `gh` CLI authenticated with `repo` scope **and network reachability** — a hard prerequisite a markdown file never had. Offline, `prawduct-hook backlog cache-query …` serves the last synced state (`sync` to refresh, `exit 6` means the cache could not be read, which is NOT "nothing matched"); anything else fails until connectivity returns.
- **Delegation**: **pre-approved** for a build plan whose chunks are independent, on this shape — the coordinator creates an isolated worktree per chunk (`git worktree add`, never the harness's own isolation, which hands you a tree you cannot name until the agent is already inside it), writes the brief into it at `.prawduct/.delegate-brief.md` so an abandoned worktree is visible at a later session start, and integrates. **File ownership must be disjoint by construction and stated per delegate** — if you cannot say who owns what without reopening the other briefs, the partition isn't ready. Record the decision either way in the plan's `partition:` field; "serial, because these chunks share a module" is an answer and silence is not.
  - **Delegate verification**: the narrowest run that covers the delegate's own change — normally the one or two test files its diff touches, plus a targeted grep or a real CLI invocation for anything prose- or contract-shaped. **Never the full suite**, which is the coordinator's run at integration. This is a cost bound, not a rigor discount, and what it prevents fails *silently*: several whole-suite runs contending on one box each report a different total, none complete, all exiting 0. A green you cannot attribute to a known set of tests is not evidence.
  - **Delegates never govern.** No Critic, no Status boxes, no `project-state.yaml`, no change-log entry, no PR. They return a branch and a report naming what they verified, what they assumed, and **any wording they decided rather than took from an artifact, marked `proposed`** — that last item is what makes the coordinator's cross-delegate read possible, and it is the seam nobody else checks.
- **Incoming-bugs triage → archive**: `incoming-bugs/` is the local, **untracked** dropbox where dogfood / agent bug + feature reports land. Triage each through `/prawduct:backlog` into a backlog item, then move the report to `incoming-bugs/archives/` (don't delete — that preserves the evidence locally; and never `rm -rf` the dropbox, other agents actively drop reports there).
  **The whole tree is gitignored** (owner decision, 2026-08-06, when the repo went public): raw triage reports are working notes, not published artifacts. So a report **cannot be cited as a durable reference** — a tracked path into it would dangle for every reader who does not have the local file. **The backlog item IS the provenance.** When a triaged report needs to be pointed at from tracked content (a source comment, a plan, a `refs:` field), cite the **backlog id**; where no item exists, restate the finding inline so the record is self-contained. This inverts the earlier link-don't-summarize handling of these particular files, and only these — everything tracked still prefers a link.

---

**What belongs here**: How you want code written. Conventions, tools, style preferences, workflow preferences.

**What doesn't belong here**: What to build (product-brief), system design (data-model, architecture), performance targets (nonfunctional-requirements), or deployment (operational-spec).

## Enforcement

Each preference above should be enforced by one of three mechanisms — assign the mechanism when you add the preference so it doesn't quietly become aspirational.

| Mechanism | Where it lives | What it catches | Trade-off |
|---|---|---|---|
| **Linter** | `ruff check .` + `mypy`, both gating CI (INF-2C4X) | Mechanical style/naming rules | Preferred where a rule exists. A preference with no corresponding enabled rule still falls through to Critic — "a linter is configured" is not the same as "this rule is enforced". |
| **Test** | `tests/preferences/test_*.py` (or equivalent) | Structural rules with named exceptions (AST checks, config-presence checks) | Bakes the rule into CI; refuses to be silent. Cost: re-validate when the rule's shape changes. |
| **Critic** | `/critic` review (Goal 4: Project Preferences) | Judgment-required rules (semantic naming, "appropriate" anything, what counts as a "boundary") | No false-confidence test. Cost: requires reviewer per chunk; misses violations between reviews. |

**Audit home** says which time-domain organ walks the norm for erosion and decay: `janitor`
(the deep Norm Health sweep — the default, and the only honest answer for a norm whose
violations leave no machine-readable trace) or `advisory` (a session-sync probe, which must
name the mechanical hook it fires on). Reviews catch violations in a diff; audit homes catch
the norm dying slowly.

### Code-level norms

| Preference | Mechanism | Enforcement artifact | Audit home | Why |
|---|---|---|---|---|
| `from __future__ import annotations` on every module | Critic | ruff is configured and gates CI (INF-2C4X), but no enabled rule covers this — Critic still owns it; promote to a `ruff` rule to mechanize | janitor | Deferred annotation evaluation keeps forward references and PEP 604 unions working uniformly across the 3.10+ floor, instead of per-module surprises |
| All writes go through `db.mutations` (no raw SQL in callers outside `db/`) | Critic | Goal 4 (project preferences) — high-priority rule; consider an AST-based `tests/preferences/test_no_raw_sql_outside_db.py` if violations recur | janitor | A caller reaching around the mutators makes the event log a lie — the one failure the data model cannot absorb (`data-model.md` § Direction) |
| Every mutator emits a paired `events` row in the same transaction | Critic | Goal 4 — paired-write discipline; covered behaviorally by `test_mutations.py` event assertions | janitor | Same-transaction emission makes the log complete by construction, which is what keeps the event-store flip a reinterpretation rather than a rewrite |
| Generators stay pure (no DB / MCP imports under `generators/`) | Critic | Goal 4 — easy candidate for an import-graph test if drift starts | janitor | Purity is what makes musical primitives testable without a DB or Live, and reusable across songs that share no state |
| `sync.*` produces plans, never invokes MCP tools directly | Critic | Goal 4 | janitor | A plan is inspectable and testable without Live running; a side effect is neither |
| Snake/Pascal/UPPER naming, PEP 604 unions, grouped imports | Critic | ruff is configured and gates CI (INF-2C4X); enable the `E`, `I` and `UP` rule sets in `[tool.ruff]` to mechanize this row | janitor | Mechanical consistency that should cost no review attention — the row exists to be promoted into ruff, not to be argued per-PR |
| Test file lives next to the module it tests (mirror layout) | Critic | Goal 4 | janitor | Mirror layout is what makes "is this covered?" answerable by looking, and keeps the three test trees from blurring |
| One DB per song in `<songs_root>/<slug>/` (per-branch filename via `resolve_db_path`); slug = `[a-z0-9_-]+`; display name in `songs.title` | Test + Critic | Schema `CHECK` on `songs.name` + Python regex in `create_song` enforce the slug; Critic Goal 4 catches setup violations (rogue paths, sidecar config files) | janitor | A song is forkable only if its directory is self-contained and its name is filesystem-safe on every platform |
| Never swallow exceptions silently; waive a necessary broad catch with `# prawduct:allow prawduct/broad-except -- <reason>` | Critic | Goal 4 + the framework's waiver rail (`docs/waivers.md`) | janitor | A swallowed exception converts a loud failure into a silent wrong answer, which in an authoring tool means corrupted work the user cannot know to re-check |
| Close-in-the-same-PR, as ONE ship-stamp commit (PRC-5W2N) | Critic + PR reviewer | Both flag a PR shipping work that matches an open backlog item without closing it | janitor | The git log is the audit trail; three bookkeeping commits scatter one decision across a history nobody can then read back |
| Every backlog item names a verifiable signal a future scrub can run | Critic | `/prawduct:backlog` add/update review | janitor | An item with no probe is unscrubbable, so it can only ever be re-read rather than re-verified — 32 items migrated at cutover carry this debt |
| Trust-but-verify on scrub; items older than 30 days are suspect | janitor | Scrub re-reads code against each item, not the item's text | janitor | Tightened from 60d by the 2026-07-02 audit — this repo's velocity made 60d too slow (BLG-7K2Q found 4 of 8 `ready` items already shipped; the 2026-08-10 migration scrub found 2 more) |
| Committed media under `docs/assets/` matches the tour's evidence manifest (item cap) and stays ≤ 12 MB; quoted `build.py` snippets appear verbatim in the source; quoted mix numbers match the committed analysis reports | Test | `tests/preferences/test_tour_freshness.py` | janitor | The repo is public and its history permanent, so media weight is a one-way door; and a worked example that drifts from its source is worse than none (tour-walkthrough-design §Capture tooling 5) |
| Prose says what a thing IS; never defines it by what it isn't (§ Documentation & prose) | Critic | Goal 4 — judgment-required, over the positioning-prose scope only (README, CONTRIBUTING, SECURITY, VISION, faq, tour). The tell is a **contrast-definition** — a `## What it isn't` heading, "unlike X", "what makes this different from Y", an FAQ entry answering an objection nobody raised, and the quiet shapes too ("a long agentic workflow, not a chat"). Test: does the sentence name a **foil** — an alternative the subject is set against? Then it is a contrast-definition. Plain negation names no foil ("Live isn't running") and passes, as do the four owner-ratified carve-outs: prior-art lineage, a limitations register, a prescriptive rule (an instruction may prohibit), and verbatim quotation (never rewrite captured evidence to satisfy a prose norm). Scope note: the owner's personal `brooks-writing-style.md` (outside this repo) bans the narrower "not just X, it's Y" reframe; this row is the general rule, binding here, and the two agree where they overlap | janitor | Defining by contrast argues with someone who isn't in the room, which plants the doubt it answers and dates the doc to whatever it was reacting to. Ratified 2026-08-11 after an intermediate draft of the launch-readiness pass shipped exactly that mistake; the agent narrowed it twice the same day, and the owner restored the absolute reading on 2026-08-12 while ratifying the prior-art carve-out |
| Positioning puts the user in the subject position of the creative verbs (§ Documentation & prose) | Critic | Goal 4 — the tell is the tool holding the creative verb ("Claude writes it", "the agent composes") where the user should | janitor | The audience most primed to distrust AI tooling reads tool-as-author as a claim on their authorship; it also misdescribes what the product does, which is build what the user decided |

### Architectural norms — homed in their artifacts

Pointer rows. The statement, why, status and rulings live in the named `## Direction`
section; this index exists so the norm is findable and its enforcement is assigned.

| Norm | Home | Mechanism | Audit home |
|---|---|---|---|
| `_FINGERPRINT_PATHS` = exactly the vendored∩executed set | `architecture.md` § Direction | Test (fingerprint parity) + Critic | janitor |
| Server-side-only code lives in `server_side/` | `architecture.md` § Direction | Critic | janitor |
| MCP handlers are `async` via `anyio.to_thread` | `architecture.md` § Direction | Test (`test_threading_invariants.py`) + Critic | janitor |
| Long operations are `start` + `status`, never blocking | `architecture.md` § Direction | Critic | janitor |
| Push is idempotent and diff-reconciling; arrangement is a projection (pull contained) | `architecture.md` § Direction | Test + Critic | janitor |
| Multi-user concurrency stays out of the wire shape | `architecture.md` § Direction | Critic | janitor |
| Parsing must never be executing | `security-model.md` § Direction | Critic | janitor |
| Executable composition accepted; mitigation is disclosure in `SECURITY.md` | `security-model.md` § Direction | Critic | janitor |
| Loopback-only; beyond-loopback is unsupported | `security-model.md` § Direction | Critic | janitor |
| Dependencies locked; CI gates `uv lock --check` | `security-model.md` § Direction | Linter/CI (`uv lock --check`, INF-2C4X) | janitor |
| Content-fingerprint versioning, not semver | `api-contract.md` § Direction | Test (handshake) + Critic | janitor |
| Errors teach — structured recovery info, never a bare string | `api-contract.md` § Direction | Test + Critic | janitor |
| Refuse-and-teach over silent wrong behavior | `api-contract.md` § Direction | Critic | janitor |
| No shims to unshipped consumers; one-major aliases on the authoring API | `api-contract.md` § Direction | Critic | janitor — the support-window deferral is **event-bound** (first external song repo, or a break report), so the Norm Health sweep walks it; no dated probe applies |
| Mutator signature triple (kw-only after `conn`; `actor`/`request_id`/`reason`) | `api-contract.md` § Direction | Test + Critic | janitor |
| Timing transforms stay in the engine, off the MCP surface | `api-contract.md` § Direction | Critic | janitor |
| Tool-surface budget — adding a tool is a decision | `api-contract.md` § Direction | Critic | janitor |
| Interfaces stay internally scoped despite the public repo | `api-contract.md` § Direction | Critic | janitor |
| DB is materialized state, never source of truth | `data-model.md` § Direction | Critic | janitor |
| Identity is a Python UUID, never autoincrement | `data-model.md` § Direction | Test + Critic | janitor |
| Live's positional ids are never identity | `data-model.md` § Direction | Critic | janitor |
| Open song DBs via `init_db`, never bare `connect` | `data-model.md` § Direction | Test (schema canary) + Critic | janitor |
| MCP server is stdlib-only at import time | `nonfunctional-requirements.md` § Direction | Test (import guard) + Critic | janitor |
| Full suite runs with no path argument | `nonfunctional-requirements.md` § Direction | Linter/CI | janitor |
| No telemetry; no outbound network calls of our own | `observability-strategy.md` § Direction | Critic | janitor |

**Rule for adding a new preference:** assign a mechanism. If the preference can be expressed as "every file/function/config matches pattern X with named exceptions" → write a test. If a linter rule already exists for it → configure the linter. If it requires understanding intent → assign to Critic. Never leave a preference unassigned.

**False-confidence guardrail:** if a generated test would pass on conforming code but couldn't reliably catch a real violation (e.g., greppy heuristics for semantic rules), prefer Critic over a weak test. A green test that doesn't actually check the rule is worse than no test.
