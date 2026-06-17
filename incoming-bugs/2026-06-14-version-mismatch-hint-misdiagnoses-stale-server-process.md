# Version-mismatch error hint misdiagnoses a stale *server process* as a stale Remote Script

**Date:** 2026-06-14
**Where:** `hallucinote_mcp` version-gate error (raised by every tool call when
server-half and Remote-Script-half fingerprints differ), and the
`/ableton-push` skill's Step 0a handling.

## What happened

Mid-session (after the user pulled the framework to `v0.9.8` and re-vendored the
Remote Script), `ableton_browser(action='plugins_list')` failed the version gate:

```
MCP server side reports 0.1.0+9906f659d471,
Remote Script side is 0.1.0+e10695d17559
```

The error's `hint` says: *"If the Remote Script side is stale (the common case):
run `/ableton-mcp-install` to refresh the vendored copy … then restart Live."*

That was the **wrong fix** for this case. Diagnosis:

- `python -m hallucinote_mcp.cli preflight` → on-disk source = `e10695`,
  vendored Remote Script = `e10695`, `matches_mcp_server: true`.
  (The two on-disk halves already agree.)
- `ableton://server/info` → running server = `9906f6`, but its
  `package_root` is the **same** dev source dir that on-disk fingerprints as
  `e10695`.

Same directory, two fingerprints ⇒ the source files were edited *after* the
server process started. The stale half is the **running MCP server python
process** (holding pre-pull code in memory), not the Remote Script. Re-vendoring
would just re-emit `e10695` — which Live already has — and a Live restart does
nothing for a stale *server* process. The actual fix is to respawn the MCP
server (`/mcp` → reconnect, or restart Claude Code).

This is the dev-repo-as-plugin setup (`--plugins-dir ~/source/hallucinote`),
where "git pull + re-vendor + reopen Live + reconnect the TCP bridge" leaves the
uv-launched server process untouched — so a stale *server* is arguably the
*more* common cause here than a stale Remote Script.

## Suggested fix

The version-gate error already has all three facts available cheaply. Make the
hint **diagnose before prescribing** instead of assuming the Remote Script is
behind:

1. Compare the running server fingerprint against the *on-disk* package
   fingerprint (not just against the Remote Script). If they differ but the
   on-disk package == Remote Script, the **server process is stale** → tell the
   user to restart the MCP server, not re-vendor.
2. Only when the Remote Script != on-disk package should the hint recommend
   `/ableton-mcp-install` + Live restart.
3. Bonus: have `/ableton-push` Step 0a run this three-way comparison and print
   the correct remediation, so the orchestrator doesn't have to hand-derive it
   (as happened here) from `preflight` + `ableton://server/info`.

## Impact

Low-frequency but high-confusion: a user following the literal hint re-vendors
and restarts Live repeatedly while the real culprit (server process) never
changes, and the gate keeps firing. The bypass (`allow_version_mismatch=true`)
is tempting but unsafe for a bulk push.
