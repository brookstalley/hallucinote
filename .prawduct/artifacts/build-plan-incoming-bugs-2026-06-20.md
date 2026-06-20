# Build Plan — Incoming bugs triage 2026-06-20

**Branch:** `fix/incoming-bugs-2026-06-20` (worktree `../hallucinote-wt-incoming-bugs`)
**Base:** develop (0f62a4c) · **Baseline:** 4325 passed, 2 skipped
**Critic mode:** cumulative (worktree is gate-blind → Critic runs via independent Agent on `develop..HEAD`, PR via gh — see [[feedback_worktree_governance_gates_blind]])
**Work type:** bugfix (×3) — root cause confirmed against live code; each chunk needs a regression test.

## Confidence check

- **Problem:** Three reproducible bugs filed today from the same `alien` / `compose/swell` "fresh set + re-push" recovery: (1) set-swap silently mislinks DB tracks onto a default scaffold by bare index; (2) rack-preset (`.adg`/`.adv`) instruments load as empty shells on a fresh push because the snapshot carries `browser_path` only; (3) the per-track arrangement-clip read is undiscoverable and lacks `note_count`/`muted`.
- **Success:** (1) reused-session re-push onto a fresh scaffold drops the mislinked links and re-creates all tracks; (2) a `browser_path`-only `.adg`/`.adv` snapshot loads the actual preset (chains populated), empty-rack loads fail loud instead of hundreds of misleading errors, and a dialed pan param pushes via normalized value; (3) `ableton_clip(list, arrangement)` returns `note_count`+`muted` and `ableton_arrangement` signposts the read.
- **Out of scope:** §2 batch `set_parameters` optimization (explicitly an optimization, not the bug — defer to backlog); persisting `preset_query` at author/capture (user chose the load-side fix; capture-side durable fix is a follow-up).

## Decisions locked (with user)

- **Bug 2 core = honor `browser_path` → `.adg`/`.adv` as a standalone load source** (relax the contract for an actual preset FILE; fixes existing snapshots in place). NOT enforcing `preset_query` at capture.
- All three bugs fully this session.

## Chunks

### Chunk 1 — Bug 3: identity-aware stale-link reconcile (M)
**Files:** `src/hallucinote/sync/push/probe.py` (reconcile sweep ~537-565; `check_coherence` ~1057-1106), `tests/unit/sync/test_push_cli.py`.
**Deliver:** Stale-link reconcile drops a surviving track link when the live track now at its `ableton_index` is not the DB track's identity — i.e. the index was not consumed by a name-match (`consumed_live_track_indexes`) / is scaffold-unmatched. Cascade dropped track → its clip/device links. Same identity check in `check_coherence`.
**Acceptance:** New regression test — reused session, DB track "Drums" pre-linked to `ableton_index=1`, fresh probe = `1-MIDI`..`4-Audio` at 1-4: assert the stale link to index 1 is dropped and the DB track is unmatched (→ re-created), clip/device links cascade. Existing reconcile tests still green.

### Chunk 2 — Bug 1: arrangement-clip read fields + signpost (L)
**Files:** `hallucinote_mcp/src/hallucinote_mcp/handlers/clip.py` (arrangement branch ~94-101), `hallucinote_mcp/src/hallucinote_mcp/actions/arrangement.py` (info action ~54-65), `hallucinote_mcp/tests/unit/test_actions_clip.py`.
**Deliver:** Add `muted` (`bool(clip.muted)`) and `note_count` (`len(clip.get_notes_extended(...))`, guarded → `None` for audio/non-MIDI clips) to the arrangement list payload. Add a `tips=` signpost on `ableton_arrangement` `info` pointing at `ableton_clip(action='list', location='arrangement')`.
**Acceptance:** Updated payload-shape test asserts the new keys; audio-clip case yields `note_count: None`; `FakeClip` gains `get_notes_extended`. **Wire-shape change → fingerprint flip → operator re-vendor** (enqueue operator-verification).

### Chunk 3 — Bug 2 core: honor browser_path standalone load (H)
**Files:** `hallucinote_mcp/src/hallucinote_mcp/handlers/device.py` (`load_handler` ~1128-1209), `src/hallucinote/sync/push/devices.py` (`_emit_device_calls` ~205-253), tests on both sides.
**Deliver:** When `browser_path` points at a `.adg`/`.adv` preset file and no `preset_uri`/`preset_query` is present, resolve it against the browser and load THAT preset (not a bare class). Push emits `browser_path` as a standalone selector when it's the only identity present. Replace the current "browser_path requires preset_uri" `ValueError` with the standalone-file path.
**Acceptance:** Loader test — `.adg` browser_path, no preset_uri → resolves a preset item (not the empty class node). Push test — captured device with browser_path only emits a load call carrying browser_path. Existing load contract tests (preset_uri fallback) still green.

### Chunk 4 — Bug 2 robustness: fail-loud empty rack + §3 pan normalized (H)
**Files:** `src/hallucinote/sync/push_execute.py` (empty-rack guard; `_SET_PARAM_NO_CURVE_HINTS` ~347), `src/hallucinote/sync/push/devices.py` if needed, tests.
**Deliver:** (a) After a device load whose snapshot recorded N>0 nested chains comes back `chain_count==0`, halt that device's nested writes with one clear "preset content did not load" error instead of emitting hundreds of `chain_index out of range`. (b) Add the non-monotonic display message (`display_value.py:230`) to the normalized-retry hints so a pan `50L`/`50R` param falls back to normalized `value`; verify a normalized value is available to fall back to (else capture-side fix).
**Acceptance:** Test — empty-rack load result + expected chains → single halt/error, no per-pad writes attempted. Test — pan param with non-monotonic display retries via normalized.

## Status

- [x] Chunk 1 — Bug 3 reconcile (SYN-SCAFFOLD-MISLINK: scaffold-aware track-link drop + device cascade + check_coherence; 5 new tests + 1 contract update; 4330 green)
- [x] Chunk 2 — Bug 1 arrangement read (note_count + muted on `ableton_clip(list, arrangement)`, audio-guarded; `ableton_arrangement` info signpost; 2 new tests; fingerprint flips → operator-verify enqueued; 4332 green)
- [x] Chunk 3 — Bug 2 core load (SYN-RACK-PRESET-RELINK: honor browser_path `.adg`/`.adv` standalone in `load_handler`; push emits standalone browser_path for a preset file; 4 new tests; fingerprint flips → operator-verify; 4336 green)
- [x] Chunk 4 — Bug 2 §3 pan (non-numeric/non-monotonic display refusals now trigger the normalized-value retry; 1 new test; 4337 green)

**Context:** All chunks done & committed. Bug 2 §2 (batch set_parameters) = out of scope (optimization). Bug 2 #3 (fail-loud on empty-rack) DEFERRED → backlog: see below.

## Deferred (filed to backlog)

**Bug 2 fix #3 — fail-loud on empty-rack load.** Deferred, NOT silently dropped.
- After Chunk 3 the PRIMARY empty-rack cause (browser_path-only rack presets) is fixed — they now load populated, so this is a diagnostics improvement for the residual degenerate case (a rack with nested chains but NO loadable identity at all).
- The naive static-planner version (skip nested writes when a rack has no DB selector) is **incorrect**: it can't tell a freshly-kind-only-loaded empty rack from one already populated in Live on a **re-push** — that's a runtime fact, and 8 existing tests encode that no-selector nested racks DO emit nested writes (the re-push/roundtrip contract).
- A load-handler version (raise on selector+rack+0-chains) false-positives on a legitimately-empty saved rack preset (handler can't know the DB's expected chain count).
- The only correct implementation compares the load's **runtime** chain_count against the DB's expected chain count in the execute loop and suppresses that device's dependent nested writes — a non-trivial execute-loop feature warranting its own design. Filed for a future cycle. On completion, archive the three `incoming-bugs/2026-06-20-*.md` reports to `incoming-bugs/archives/` with a resolution note.
