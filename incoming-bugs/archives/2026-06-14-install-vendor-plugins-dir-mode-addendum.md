# Addendum to the install-vendor-wrong-copy bug: in `--plugins-dir` mode the dev repo IS the active plugin — don't hardcode the marketplace path in the fix

**Severity:** S — refines
`archives/2026-06-13-install-remote-script-vendors-wrong-copy-in-dev-setup.md`
with a second observed environment. The fix proposed there ("vendor from the copy
the server actually runs / `CLAUDE_PLUGIN_ROOT`") is correct — this note just
flags an assumption that would break it if implemented naively.

**New data (2026-06-14).** This machine now runs Claude Code with
`--plugins-dir ~/source/hallucinote`, i.e. **the dev repo is loaded directly as
the active plugin**, and the user **deleted the marketplace cache**
(`~/.claude/plugins/cache/hallucinote`). So the running MCP server launches from
the **dev repo** (`0.1.0+4057d968452f`), and the vendored Remote Script was the
stale `0.1.0+46bd3bd7aa37` — the same handshake-mismatch failure, but with the
roles inverted from the original report: here vendoring *from the dev repo* is the
*correct* action, because the dev repo is what the server runs.

**Implication for the fix.** "Always vendor from the marketplace plugin, never the
dev repo" is the wrong rule — it's environment-specific. The durable rule is
**vendor from whatever copy the running server launches from**, which in this
setup is the `--plugins-dir` target. Resolve it via `CLAUDE_PLUGIN_ROOT` (which
points at the active plugin whether that's a marketplace cache dir *or* a
`--plugins-dir` repo), not by assuming a marketplace path. Likewise `preflight`
should report `matches_mcp_server` against that resolved root.

**Verifiable signal.** `/ableton-mcp-install` and `preflight` both work without a
manual `PYTHONPATH` override in (a) marketplace-plugin setups and (b)
`--plugins-dir <repo>` setups, because both resolve the same `CLAUDE_PLUGIN_ROOT`
the server launched from. Surfaced 2026-06-14 dogfooding the swell rebuild.
