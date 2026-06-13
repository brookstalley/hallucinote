# INS-3W8P — install resolves the *running server*, not the invoking interpreter

Backlog: **INS-3W8P** (`stage: ready`, effort M). Branch: `fix/install-resolve-running-server`.
Critic mode: **cumulative** (single feature, one review over `develop..HEAD`).

## Confidence Check

1. **Problem.** `/ableton-mcp-install` resolves `hallucinote_mcp` via the *invoking*
   interpreter (`hallucinote_mcp.__file__` → `package_root()`). In any coexistence setup
   (installed plugin **and** an editable clone on `sys.path`, incl. the README's
   `pip install -e`), the invoking copy can diverge from the copy the **plugin actually
   launches**. Two defects fall out: install **vendors the wrong source**, and **preflight
   lies** — it computes `matches_mcp_server` against the invoking copy, reporting `true`
   while the real server refuses. Observed live 2026-06-13: dev `46bd…` vendored, server
   stayed `4288…`, handshake refused every call; cost multiple Live-restart cycles.

2. **Success.** In a coexistence setup, `/ableton-mcp-install` vendors the Remote Script
   matching the **launched** server and preflight's `matches_mcp_server` is computed
   against the **running** server — so a fresh install never yields a server↔Remote-Script
   mismatch, *provably so when the editable clone diverges from the plugin*.

3. **Out of scope.** The dev-vs-use topology recommendation (separate doc/backlog —
   worktrees, switch skill); any change to the runtime handshake itself (it already
   catches mismatches correctly — it's the *pre-install* check that was blind).

## Design decision — ask the authoritative source

The open question the backlog raised ("is `CLAUDE_PLUGIN_ROOT` available in the skill's
bash env?") is **answered: NO** (empirically empty in the harness shell this session). So
backlog fix-options (a) `UV_PROJECT_ENVIRONMENT/CLAUDE_PLUGIN_ROOT` and (b) disk-discover
`~/.claude/plugins/cache/…` both fail — (a) has no env var, (b) can't find a `--plugin-dir`
root (arbitrary path) and is fragile against CC internals.

**Third option (chosen): the running server self-reports its identity.** The server process
*is* the ground truth and is reachable over MCP independent of Live (so it works while Live
is closed, which install requires). It already computes `__version__` and knows
`package_root()`. Expose both via a static, Live-independent resource the install skill reads
and threads to the CLI. Robust for the marketplace plugin, `--plugin-dir`, and the
`pip install -e` user path alike; degrades gracefully (old server lacking the resource →
fall back to today's behavior + caveat; the runtime handshake remains the ultimate net).

Note: `resources/` is **not** in `_FINGERPRINT_PATHS`, so adding the resource does **not**
change the server fingerprint — no re-vendor is forced by this change alone.

## Boundary

New contract surface: **server identity → install skill → install CLI** (version handshake
boundary). Document it in `boundary-patterns.md`. Consumers of the preflight JSON shape: the
`ableton-mcp-install` + `ableton-mcp-uninstall` skills (this repo) — both updated here.

## Chunks

- [x] **C1 — Server self-report resource.** Add `ableton://server/info` (static,
  Live-independent) → `{base_version, fingerprint, version, package_root}`. Register in
  `resources/__init__.py`; add URI to `RESOURCE_URIS`; bump the "11 → 12 static" counts in
  `resources/__init__.py` + `server.py` docstrings + MCP server-instructions text. Unit
  tests: resource returns the live `__version__` + a readable `package_root`; URI-list lock
  test updated. *Done when:* `test_resource_uri_list_matches_design` passes with the new URI
  and a handler test asserts the payload shape.

- [x] **C2 — CLI honesty + right-source vendor.** `preflight` gains `--server-version V`:
  relabel `package` as the invoking interpreter, add a `server` block
  `{version, confirmed}`, add `coexistence_divergence`, and compute `matches_mcp_server`
  against the server reference (falls back to invoking + `confirmed:false` when absent).
  `install-remote-script` gains `--from-package-root PATH` (vendor source override → passed
  to `vendor_remote_script(source_root=…)`) and `--require-server-version V` (assert the
  source's computed version == V *before* vendoring; refuse with a teaching error otherwise);
  always emit `vendored_version` in the JSON. Reject a `--from-package-root` that isn't a
  parseable `hallucinote_mcp` package. Unit tests for every branch (honest matches,
  divergence flag, right-source vendor, require-version refusal, bad-source refusal).

- [x] **C3 — Skill + artifacts.** Rewrite `skills/ableton-mcp-install/SKILL.md` Step 1/3/5
  to: read `ableton://server/info` first; pass `--server-version` to preflight and
  `--from-package-root`/`--require-server-version` to install-remote-script; branch on
  `coexistence_divergence` with a teaching message; fall back gracefully when the resource
  is absent (old server). Add the boundary-patterns surface + a `docs/` note. `uninstall`
  skill unaffected (no server reference) — confirm.

## Acceptance (the verifiable signal)

A coexistence simulation (source_root A ≠ server-version B) drives the CLI: preflight reports
`matches_mcp_server` against B and flags `coexistence_divergence`; `install-remote-script
--from-package-root A --require-server-version B` **refuses** (A computes ≠ B); pointed at the
B copy it vendors and `vendored_version == B`. Full suite green; Critic cumulative 0-blocking.
