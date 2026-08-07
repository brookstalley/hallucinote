# Project Preferences

Developer preferences for how code is written in this project. Captured during discovery, updated as preferences evolve. Every session should read this before writing code.

## Language & Runtime

- **Language**: Python
- **Version**: 3.10+ (declared in `pyproject.toml`); local venv uses 3.12
- **Package manager**: `pip` against the editable install (`pip install -e .[dev]` into `.venv/`)

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
  - **Song-specific** — `songs/<slug>/tests/test_*.py` lives alongside `build.py` and `captured_session.json` so each song is a self-contained unit (per `docs/VISION.md` "songs as git repos"). These tests assert song-level shape (e.g., that falling-walking's build produces the expected track count, well above a baseline note count, the expected sections in order) and may load that song's snapshot. The exact thresholds live in the test files — see them for current contract values. These tests never test platform behavior incidentally.
  - Pytest discovers all three via `[tool.pytest.ini_options].testpaths = ["tests", "hallucinote_mcp/tests", "songs"]`. Song test dirs intentionally have no `__init__.py` (rootdir-discovered) so they don't collide with the platform `tests/` package namespace.
- **Parallelization**: `pytest-xdist>=3.6` is declared in `[dev]` deps and installed. The auto-grouping in `conftest.py` assigns each test file an `xdist_group` based on its parent directory, so same-directory tests stay serial on one worker (preserving fixture isolation) and different directories fan out. Default invocation is serial; `pytest -n auto --dist loadgroup` opts into parallel (~5s vs ~10s serial as of post-J-2 baseline).

## Architecture Patterns

- **Data modeling**: SQLite with raw schema in `db/schema.sql`. Rows surface as `sqlite3.Row` for reads; mutators take/return primitive dicts and ints. Dataclasses (`@dataclass`) for in-process value objects like `ToolCall` / `PushPlan`.
- **Error handling**: Plain exceptions (`ValueError`, `KeyError`). No custom exception hierarchy. Never swallow exceptions silently — per CLAUDE.md Critical Rule, mark intentional broad catches with `# prawduct:ok-broad-except`.
- **Async**: Sync throughout. SQLite WAL + `timeout=10.0`. No async planned — this is a single-user authoring tool.
- **File organization**: Layer folders inside `src/hallucinote/`: `db/` (state + events + mutators + queries), `generators/` (pure musical building blocks), `sync/` (DB↔Ableton bridge). Song-specific builders live under `songs/<name>/build.py` and consume the library.
- **DB discipline (load-bearing)**: All writes go through `db.mutations`. Every mutator emits an `events` row in the same transaction. This is the seed for an eventual event-store flip — see `MEMORY.md`. **Never use raw SQL in callers** outside `db/`.
- **Generators are pure**: `generators/*` functions take parameters and return `list[NoteDict]`. They never touch the DB or MCP. Persistence happens at the caller.
- **Sync is a plan, not a side effect**: `sync.push` returns `PushPlan` / `ToolCall` objects. The agent executes; `apply_push_results` feeds outcomes back into the DB. Keeps the layer testable without Live running.

## Tooling

- **Key libraries**: stdlib only at runtime (`sqlite3`, `json`, `dataclasses`, `pathlib`). `pytest` for tests. AbletonMCP is an external dependency invoked by the agent, not imported.
- **Dev commands**:
  - `source .venv/bin/activate` — required; package is installed editable into `.venv`
  - `pytest` — full suite (serial by default; under ~10s on the J-2 baseline)
  - `pytest -n auto --dist loadgroup` — parallel via pytest-xdist (auto-grouped by test subdirectory per `tests/conftest.py`; roughly 1.6× faster)
  - Current test count + timings: see `.prawduct/.test-evidence.json` (canonical; this prose intentionally avoids restating numbers that drift)
  - `python songs/falling-walking/build.py [--reset]` — build the example song into its SQLite DB
- **DB files (prescriptive)**: **one SQLite DB per song**, at exactly `songs/<slug>/<slug>.db`. The directory name, the DB filename, and `songs.name` (the slug) must all match. The slug is filesystem-safe: `[a-z0-9_-]+` (lowercase, digits, hyphens, underscores). Human-facing names with spaces / capitals / punctuation go in `songs.title`. No sidecar config files; the DB schema is the source of truth for song metadata. `*.db` is gitignored.

## Workflow

- **Branching model**: **gitflow** — `develop` is the primary integration branch; `main` is release-only.
- **Branching**: feature-branches — every feature/fix branch is cut from `develop` and PR'd back to `develop`. Direct commits to protected branches only for trivial fixes (and only when `Branching` is `direct`, which it isn't here).
- **Branch flow**:
  - `feature/...` / `fix/...` / `refactor/...` → PR target: `develop`
  - `develop` → `main`: release PRs only; cut periodically when a batch of work is ready to ship. No direct commits to `main`.
- **Protected branches**: `main`, `develop` (no direct commits).
- **PR creation**: `wait_for_user` (default — only create PRs when explicitly asked; set to "automatic" to create PRs after Critic review passes).
- **PR merge**: `automatic` — merge after CI passes (or no CI configured) and PR review is clean. The cumulative Critic + independent PR reviewer gates already provide review independence; a second user-side confirmation adds friction without added safety.
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

| Preference | Mechanism | Enforcement artifact |
|---|---|---|
| `from __future__ import annotations` on every module | Critic | ruff is configured and gates CI (INF-2C4X), but no enabled rule covers this — Critic still owns it; promote to a `ruff` rule to mechanize |
| All writes go through `db.mutations` (no raw SQL in callers outside `db/`) | Critic | Goal 4 (project preferences) — high-priority rule; consider an AST-based `tests/preferences/test_no_raw_sql_outside_db.py` if violations recur |
| Every mutator emits a paired `events` row in the same transaction | Critic | Goal 4 — paired-write discipline; covered behaviorally by `test_mutations.py` event assertions |
| Generators stay pure (no DB / MCP imports under `generators/`) | Critic | Goal 4 — easy candidate for an import-graph test if drift starts |
| `sync.*` produces plans, never invokes MCP tools directly | Critic | Goal 4 |
| Snake/Pascal/UPPER naming, PEP 604 unions, grouped imports | Critic | ruff is configured and gates CI (INF-2C4X); enable the `E`, `I` and `UP` rule sets in `[tool.ruff]` to mechanize this row |
| Test file lives next to the module it tests (mirror layout) | Critic | Goal 4 |
| One DB per song at `songs/<slug>/<slug>.db`; slug = `[a-z0-9_-]+`; display name in `songs.title` | Test + Critic | Schema `CHECK` on `songs.name` + Python regex in `create_song` enforce the slug; Critic Goal 4 catches setup violations (rogue paths, sidecar config files) |

**Rule for adding a new preference:** assign a mechanism. If the preference can be expressed as "every file/function/config matches pattern X with named exceptions" → write a test. If a linter rule already exists for it → configure the linter. If it requires understanding intent → assign to Critic. Never leave a preference unassigned.

**False-confidence guardrail:** if a generated test would pass on conforming code but couldn't reliably catch a real violation (e.g., greppy heuristics for semantic rules), prefer Critic over a weak test. A green test that doesn't actually check the rule is worse than no test.
