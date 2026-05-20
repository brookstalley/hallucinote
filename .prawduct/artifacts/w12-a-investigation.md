# W12-A — Idempotent mutators + per-branch DB filename (investigation)

**Status**: investigation complete, design proposed, awaiting user sign-off before implementation.
**Date**: 2026-05-19
**Branch**: `feat/wave-12-state-hygiene`
**Build-plan spec**: `.prawduct/artifacts/build-plan.md` W12-A + `docs/v1-build-plan.md` Wave 12

## TL;DR

47 mutators in `src/hallucinote/db/mutations.py` (2312 lines). Of those, ~22 are state-changing creates/updates that need an idempotency pass; the rest are already shaped right (deletes-by-id, partial updates, append-only audit). I recommend a **6-element design** below; the 2 starred items need explicit user sign-off because they're pervasive and partially reversible:

1. **Actor model**: add `'build'` to `events.ACTORS`; build.py threads `actor='build'`. ★ *signoff*
2. **Identity strategy**: per-kind table below (mostly piggybacking existing UNIQUE constraints, plus three new identity rules for sections / cue_points / envelopes / device_chains / arrangement_clips where no UNIQUE exists).
3. **Tombstone model**: build.py opens `M.begin_build` (returns request_id), tracks touched entity ids during the build, calls `M.end_build` which deletes any build-owned rows (latest event actor ∈ `{'build','system'}`) NOT in the touched set, per-song. Pulled rows (actor='sync') untouched. ★ *signoff*
4. **No-op event semantics**: when state matches, emit nothing — mutator return-value signals `(id, kind)` where `kind ∈ {'created','updated','unchanged'}`. No NO_CHANGE event row pollution.
5. **Per-branch DB filename**: `<slug>-<sanitized-branch>.db` where sanitized = `branch.replace('/', '--')`. Outside a repo or detached HEAD: fall back to `<slug>.db`. Helper in `db/connection.py` (`resolve_db_path(slug, root=Path('songs'))`).
6. **Build.py template**: wraps the build in `with M.build_session(conn, song_id, owner='build.py') as bs:` context manager (auto begin/end + actor injection via threadlocal-free pattern — pass `actor` through mutator kwargs).

Implementation size estimate: **~600-900 LoC** + ~25-35 new tests. **Critic chunk-level mandatory** per the wave-plan mark. Best done as a single chunk, not split — the mutator-by-mutator refactor wants atomic semantics.

---

## Mutator inventory + identity decision per kind

47 functions in `src/hallucinote/db/mutations.py`:

| # | Mutator | Category | Current identity | Idempotency disposition |
|---|---|---|---|---|
| 1 | `create_request` | provenance/audit | new every call | KEEP — audit trail, append-only |
| 2 | `close_request` | provenance/audit | by request_id | KEEP — already addresses-by-id |
| 3 | `request` (ctx mgr) | provenance/audit | wraps 1+2 | KEEP |
| 4 | `record_markdown_ref` | provenance/audit | by path | KEEP — W8-B already upsert-shaped |
| 5 | `create_song` | song | UNIQUE(name) | **UPSERT**: identity = `name`; no-op if title/key/timing_mode unchanged |
| 6 | `set_song_timing_mode` | song | by id | KEEP — partial update |
| 7 | `create_track` | tracks | UNIQUE(song_id, track_index) | **UPSERT**: identity = `(song_id, track_index)`; no-op if name/instrument_uri/kind unchanged |
| 8 | `set_track_mixer` | tracks | by id | KEEP — partial update |
| 9 | `create_clip` | clips | UNIQUE(track_id, slot) | **UPSERT**: identity = `(track_id, slot)`; no-op if length/name/section_role unchanged |
| 10 | `update_clip` | clips | by id | KEEP |
| 11 | `delete_clip` | clips | by id | KEEP |
| 12 | `insert_notes` | notes | append-by-clip | AGENT EDIT — used by `update_notes_by_tag`, not build.py |
| 13 | `replace_clip_notes` | notes | clip-scoped | KEEP — already whole-clip replacement (idempotent by shape) |
| 14 | `update_note` | notes | by id | AGENT EDIT |
| 15 | `delete_notes` | notes | by id | AGENT EDIT |
| 16 | `update_notes_by_tag` | notes | tag-scoped | AGENT EDIT |
| 17 | `add_arrangement_clip` | arrangement | **NO UNIQUE** | **UPSERT**: identity = `(song_id, track_id, clip_id, start_bar)`; add CHECK or app-layer guard |
| 18 | `remove_arrangement_clip` | arrangement | by id | KEEP |
| 19 | `create_section` | sections | **NO UNIQUE** | **UPSERT**: identity = `(song_id, name, start_bar)` (per Wave 0 fbr-3 — same name at different bars is intentional repeat) |
| 20 | `update_section` | sections | by id | KEEP |
| 21 | `delete_section` | sections | by id | KEEP |
| 22 | `add_tempo_point` | tempo_map | UNIQUE(song_id, start_bar) | **UPSERT**: identity = `(song_id, start_bar)`; no-op if tempo_bpm/ramp unchanged |
| 23 | `update_tempo_point` | tempo_map | by id | KEEP |
| 24 | `remove_tempo_point` | tempo_map | by id | KEEP |
| 25 | `add_time_signature_point` | time_signature_map | UNIQUE(song_id, start_bar) | **UPSERT**: identity = `(song_id, start_bar)`; no-op if numerator/denominator unchanged |
| 26 | `update_time_signature_point` | time_signature_map | by id | KEEP |
| 27 | `remove_time_signature_point` | time_signature_map | by id | KEEP |
| 28 | `add_cue_point` | cue_points | **NO UNIQUE** | **UPSERT**: identity = `(song_id, position_bar)`; no-op if name/color unchanged. Note: this differs from Wave 0 fbr open-Q7 disambiguation discussion; if duplicate-name cues at different positions are intentional, the identity is fine; if duplicate cues at same position are a user error, surface a teaching error. **CALL OUT**: confirm position is the right identity. |
| 29 | `remove_cue_point` | cue_points | by id | KEEP |
| 30 | `create_return` | returns | UNIQUE(song_id, position) | **UPSERT**: identity = `(song_id, position)`; no-op if name/vol/pan/mute/solo/color unchanged |
| 31 | `update_return` | returns | by id | KEEP |
| 32 | `delete_return` | returns | by id | KEEP |
| 33 | `set_send_level` | sends | PK(from_track_id, to_return_id) | KEEP — already upsert-shaped (REPLACE INTO semantics needed if not already) |
| 34 | `remove_send` | sends | by composite PK | KEEP |
| 35 | `create_device_chain` | device_chains | **NO UNIQUE** | **UPSERT**: identity = `(parent_*_id, position)` where parent_*_id is whichever of the three FK cols is set |
| 36 | `delete_device_chain` | device_chains | by id | KEEP |
| 37 | `create_device` | devices | UNIQUE(chain_id, position) | **UPSERT**: identity = `(chain_id, position)`; no-op if kind/display_name/preset_uri unchanged |
| 38 | `delete_device` | devices | by id | KEEP |
| 39 | `set_device_parameter` | device_parameters | UNIQUE(device_id, name) | **UPSERT**: identity = `(device_id, name)`; no-op if value_display/value_normalized unchanged (already partially shaped, verify) |
| 40 | `remove_device_parameter` | device_parameters | by id | KEEP |
| 41 | `create_envelope` | envelopes | **NO UNIQUE** | **UPSERT**: identity = `(song_id, target_kind, target_*_id, parameter_path)`; no-op (envelope rows have no other content — breakpoints are separate) |
| 42 | `delete_envelope` | envelopes | by id | KEEP |
| 43 | `add_breakpoint` | breakpoints | append-by-envelope | AGENT EDIT — not used by build.py (replace_breakpoints is) |
| 44 | `remove_breakpoint` | breakpoints | by id | AGENT EDIT |
| 45 | `replace_breakpoints` | breakpoints | envelope-scoped whole-replace | KEEP — already whole-envelope replacement |
| 46 | `create_ableton_session` | ableton | new every call | KEEP — sessions are not build-owned |
| 47 | `link_db_to_ableton` | ableton | UNIQUE(session_id, db_kind, db_id) | KEEP — already upsert-shaped per W3 |

**Summary**: 13 mutators need real upsert refactoring (rows above marked **UPSERT**). The other 34 are either already idempotent, are partial updates (`set_*`), are agent-edit primitives (`update_note` / `delete_notes` — not build.py callers), or are append-only (audit). The actual code touch is concentrated.

---

## Design decisions

### 1. Actor model — **NEEDS SIGN-OFF**

**Proposal**: add `'build'` to `events.ACTORS`. The new set: `{"user", "llm", "sync", "generator", "system", "build"}`.

`build.py` (via the W12-A context manager) threads `actor='build'` on every mutator call. This gives clean discrimination at tombstone time: build-owned rows (latest event actor ∈ `{'build','system'}`) vs. pulled (actor='sync') vs. authored-via-LLM (actor='llm') vs. test-fixture (actor='system'). The `'system'` actor stays the default for tests + ad-hoc REPL work; `'build'` is a deliberate signal "this row came from running build.py."

Alternatives:
- (a) Keep build = `'system'`. Tombstone fires on actor IN `('system', 'build')`. Risk: test fixtures and ad-hoc REPL calls also use `'system'`, so a build can tombstone someone's test-only data. Rejected.
- (b) Per-entity owner column on every table. Way too invasive for the v1 timeline.

**Recommend (a)**: add `'build'` to ACTORS.

### 2. Identity strategy

Per the table above. The new identity rules (no existing UNIQUE constraint):
- `sections`: `(song_id, name, start_bar)`
- `cue_points`: `(song_id, position_bar)` — see CALL OUT in table
- `envelopes`: `(song_id, target_kind, target_*_id, parameter_path)`
- `device_chains`: `(parent_*_id, position)`
- `arrangement_clips`: `(song_id, track_id, clip_id, start_bar)`

For each, the upsert is enforced at the mutator (not the schema) for v1 — adding UNIQUE constraints retroactively on existing DBs is fiddly with SQLite. v1.1 follow-up: add the missing UNIQUE constraints to the schema for defense in depth.

### 3. Tombstone model — **NEEDS SIGN-OFF**

**Proposal**:
```python
with M.build_session(conn, song_id, owner='build.py') as bs:
    # Every mutator call passes actor='build' (injected by context manager).
    M.create_song(conn, name='falling-walking', ...)
    M.create_track(conn, song_id=sid, track_index=1, ...)
    # ... etc.
# On context exit:
#   For each (kind, song_id) build owns, query all rows.
#   For each row not in bs.touched, check its latest event actor.
#   If actor IN ('build', 'system'), delete it. Cascades handle children.
#   Pulled rows (actor='sync') are skipped — their state is authoritative.
```

The build-session tracks `bs.touched: set[tuple[kind, id]]` in memory (no temp table). Every mutator that returns an id, the context manager intercepts the call and records it. Build kinds covered: songs, tracks, clips, arrangement_clips, sections, tempo_map, time_signature_map, cue_points, returns, device_chains, devices, device_parameters, envelopes (+ breakpoints via replace_breakpoints' whole-envelope semantic — breakpoints are leaves of envelope ownership).

**The "latest event actor" check** is what protects pulled state. Implementation: for each candidate-for-delete row, query `SELECT actor FROM events WHERE <table_match> ORDER BY seq DESC LIMIT 1`. If `'sync'`, skip. If `'build'`/`'system'`, delete (cascades). If `'llm'`/`'user'`/`'generator'`, also skip (these are non-build user mutations the author may want to keep). This means only `'build'` and `'system'`-actor rows are tombstone candidates — both build-owned and the historical default.

**Edge cases**:
- A song with no events for a row (legacy data): treat as `'system'`-owned (default), tombstone-eligible.
- A row created during the build but later modified by `'llm'` (e.g., LLM tweaks a clip's length mid-build): the latest actor is `'llm'`, so it survives tombstoning. This is the right protection.
- A pulled clip's envelope gets a breakpoint added by build.py: replace_breakpoints is whole-envelope, so the breakpoints become 'build'-owned even if the envelope itself is 'sync'. This is fine — build.py is the author of the breakpoint state.

**Alternatives**:
- (a) Build.py declares its manifest upfront (list of identities it owns). Brittle — requires the build to know its entire output before running. Rejected.
- (b) No tombstoning — build.py is upsert-only, stale rows survive. Loses the "branch-switch silently stale" benefit which is the whole reason for W12-A. Rejected.
- (c) Track touched-set in a temp table (request_touches). Survives crashes; current proposal loses the touched-set if Python exits mid-build. Possibly worth it — the alternative is "if build crashes, no tombstoning happens" which is acceptable (the user re-runs build).

**Recommend the in-memory touched-set approach** with the actor-discrimination tombstone above.

### 4. No-op event semantics

When a mutator detects "state matches, nothing to change," it returns the existing id + `kind='unchanged'` and **emits NO event**. Rationale: the events table is an audit trail of state changes; a no-op isn't a state change. Polluting events with NO_CHANGE rows makes downstream "what did this build cycle do" queries useless.

Mutator return shape changes (slight breaking change):
```python
# Before:
tid = M.create_track(conn, song_id=sid, track_index=1, name='Drums')
# Returns: str (the track id)

# After:
result = M.create_track(conn, song_id=sid, track_index=1, name='Drums')
# Returns: dict-like or namedtuple: {id: '...', kind: 'created'|'updated'|'unchanged'}
# To get just the id: result.id  (or result['id'])
```

This is a callsite update across the codebase (~80-ish callsites). The CLI / build.py / sync layer needs to adapt. **Most callers can stay unchanged** by accessing `.id` on the return — only callers that care about created-vs-updated need the new info.

**Alternative**: keep the return as bare id, expose `kind` via a parallel `M.last_action_kind` query. Slightly more code, slightly less clean. Rejected in favor of structured return.

### 5. Per-branch DB filename

**Proposal**: new helper `db.connection.resolve_db_path(slug, root=Path('songs'))`:
```python
def resolve_db_path(slug: str, root: Path = Path('songs')) -> Path:
    """Return songs/<slug>/<slug>-<branch>.db when inside a git repo,
    falling back to songs/<slug>/<slug>.db outside a repo or on detached HEAD."""
    branch = _git_current_branch()  # returns None on detached HEAD / no repo
    if branch is None:
        return root / slug / f"{slug}.db"
    sanitized = branch.replace('/', '--')
    return root / slug / f"{slug}-{sanitized}.db"
```

`build.py` template change:
```python
# Before:
DB_PATH = Path(__file__).parent / "falling-walking.db"

# After:
from hallucinote.db import resolve_db_path
DB_PATH = resolve_db_path('falling-walking', root=Path(__file__).parent.parent)
```

Old `<slug>.db` files remain on disk (gitignored), easy to `rm`. Branch switches pick up the right file silently. Detached HEAD falls back to the canonical name.

**Open question**: should the helper warn at the CLI when there's a `<slug>.db` on disk AND a `<slug>-<branch>.db` on disk for the SAME song? Two DBs for one song could be confusing. Recommendation: silent for v1 (the gitignore + filenames are visible enough); v1.1 surfaces a `--list-dbs` helper if it becomes a real friction.

### 6. Build.py template

```python
# Before (today):
def build(reset: bool = False) -> str:
    if reset and DB_PATH.exists():
        DB_PATH.unlink()
    conn = init_db(DB_PATH)
    try:
        existing = Q.get_song_by_name(conn, "falling-walking")
        if existing and not reset:
            print(f"song already exists; use --reset to rebuild")
            return existing["id"]
        # ... 80+ mutator calls
        return song_id
    finally:
        conn.close()

# After (W12-A):
def build() -> str:
    """Build the song as a state-converger. Re-running is a no-op when state matches."""
    conn = init_db(resolve_db_path('falling-walking'))
    try:
        with M.build_session(conn, song_name='falling-walking', owner='build.py') as bs:
            # All mutator calls within receive actor='build' from the session.
            # bs.touched accumulates (kind, id) pairs.
            song_id = M.create_song(conn, name='falling-walking', title='Falling, Walking', key='Dm')
            # ... 80+ mutator calls — most unchanged
        # On exit: end_build runs, tombstones build-owned-but-not-touched rows.
        return song_id
    finally:
        conn.close()

if __name__ == "__main__":
    build()  # No more --reset — re-running converges to current build.py output.
```

`--reset` becomes unnecessary in normal flow (the converger handles it). Keep a `--drop-db` escape hatch for the rare "I want a totally fresh DB" case (e.g., schema migration testing).

---

## Test plan

New test file `tests/unit/db/test_idempotency.py` (~25-35 tests):

1. **Per-mutator idempotency** (13 tests, one per UPSERT mutator above):
   - Call mutator twice with identical args → second call returns `kind='unchanged'`, emits no event, no state change.
   - Call twice with same identity but different non-identity field → second call returns `kind='updated'`, emits ONE event with the diff.
2. **Build session lifecycle** (5 tests):
   - `begin_build` returns request_id; events tagged with it.
   - Touched-set accumulates correctly.
   - `end_build` tombstones unhugged rows.
   - Pulled rows (actor='sync') survive `end_build`.
   - Crash mid-build leaves no half-built state (transaction wraps).
3. **Tombstone semantics** (5 tests):
   - LLM-modified row survives tombstoning.
   - Empty build → tombstones every existing row.
   - Re-running same build → zero net events.
   - Build that pulled rows + author rows: only author rows tombstoned for non-touched.
   - Build that added a track + removed it from build.py: track gets tombstoned next build.
4. **Per-branch DB filename** (4 tests):
   - In repo on branch `develop`: `falling-walking-develop.db`
   - In repo on `feat/wave-12`: `falling-walking-feat--wave-12.db`
   - Outside repo: `falling-walking.db`
   - Detached HEAD: `falling-walking.db`
5. **Integration tests** (3-5 tests):
   - Falling-walking build.py round-trip: build → build again → zero net events.
   - Pull-then-build preserves pulled state.
   - Build → manually edit DB → build again → manual edit survives.

Expected suite delta: 1298 → ~1325-1335 (+25-35 new tests).

---

## Implementation order

1. **Schema** (no migration needed — new behaviors are pure runtime):
   - Add `'build'` to `events.ACTORS` (one-line change in `events.py`)
   - No schema column adds (identity is enforced by mutators, not new UNIQUE constraints — v1.1 follow-up files those)
2. **Connection helper**: `resolve_db_path` in `db/connection.py` + 4 tests.
3. **Mutator refactor**: per the 13 UPSERT mutators, change body to "SELECT WHERE identity → if exists + state matches: return unchanged; if exists + state diffs: UPDATE + emit; else INSERT + emit." Mutator-by-mutator with tests written alongside.
4. **Return type change**: introduce `MutatorResult` (frozen dataclass or NamedTuple) with `.id` + `.kind`. Update mutator signatures + call sites (~80 sites across codebase).
5. **Build session**: `M.build_session` context manager. Tracks touched-set via wrapping mutator returns. Runs tombstone on exit.
6. **Build.py template**: update `songs/falling-walking/build.py` + canary songs' build.py to use new shape. Verify each builds clean on first + second run with zero net events on the second.
7. **Tests**: per the plan above.

---

## What I need from the user

Two explicit sign-offs before I start coding:

**(A) Actor model — `'build'` as a new actor.**
The alternative is keeping build at `'system'` but it conflates build-owned with test/REPL data. Cleaner to introduce the new actor.

**(B) Tombstone model — actor-based discrimination.**
Build-owned rows (actor IN `('build', 'system')`) not touched in the latest build get deleted; pulled rows (actor='sync') survive; LLM/user-authored rows (actor IN `('llm', 'user', 'generator')`) survive.

If you say yes to both, I'll implement in the order above. Estimated session-time: 2-4 hours for a single agent run (it's a lot of mutator-by-mutator work plus tests). If you'd rather split into two PRs (refactor first, then tombstone+per-branch), say so.

If you want different choices on (A) or (B), explain what and I'll re-scope.

## Sequencing question

Per the v1 sequencing, **W12-A → W9 → Wave 10 (parallel)**. W12-A blocks W9 because W9-A's build.py template uses the new state-converger semantics. Worth noting that the build.py changes I make here (template + canary song updates) are forward-compatible with W9's expanded template — W9-A inherits the W12-A pattern and adds scaffolding for *new* songs from scratch.
