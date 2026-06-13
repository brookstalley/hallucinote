# `install-remote-script` / `/ableton-mcp-install` vendors the WRONG `hallucinote_mcp` copy in a dev setup → guaranteed handshake mismatch

**Severity:** M — in any environment with both the installed plugin AND an editable
dev-repo install of `hallucinote_mcp`, the install vendors the dev copy, which
diverges from the plugin the server actually runs — producing a server↔Remote-Script
version mismatch that blocks every push until manually corrected. Cost us multiple
Live-restart cycles, 2026-06-13.

**Root cause.** `install-remote-script` copies the Remote Script from whichever
`hallucinote_mcp` the *invoking Python* imports. The MCP **server**, by contrast,
always launches from the **plugin** (`uv run --project ${CLAUDE_PLUGIN_ROOT}`). In
a dev setup the shell's `python3 -m hallucinote_mcp.cli` resolves the **editable
dev-repo** install — a different copy. The version is a content fingerprint of the
wire-shape files (`wire.py`/`schema.py`/`dispatcher.py`/`actions`/`handlers`/
`remote_script`), and active dev work keeps those drifting, so:
- dev-repo `hallucinote_mcp` fingerprint ≠ plugin `hallucinote_mcp` fingerprint
- install (from shell) → vendors dev copy into Live
- server (the plugin) → different fingerprint → **handshake refuses every call**

Observed: dev `0.1.0+46bd3bd7aa37`, plugin `0.1.0+4288d582ffc4`. Vendoring the dev
copy made the Remote Script `46bd…` while the running server stayed `4288…`.

**Two compounding defects:**
1. **Install vendors the wrong source.** It should ALWAYS vendor from the SAME copy
   the server runs (the plugin / `CLAUDE_PLUGIN_ROOT`), independent of the invoking
   shell's import resolution. Fix: resolve the plugin's `hallucinote_mcp` explicitly
   (plugin root / `CLAUDE_PLUGIN_ROOT`) and vendor from there; or hard-error when the
   imported `hallucinote_mcp` isn't the plugin copy, with a teaching message.
2. **`preflight` lies about which is "the server."** Run from the dev shell, preflight
   reports `package.version` (dev repo) as "the server" and compares the vendored copy
   against it — so `matches_mcp_server` is computed against the WRONG reference. It said
   `True` after I vendored the dev copy, then the *real* server refused. Preflight
   should resolve the actual running server's source (the plugin), not the invoking
   interpreter's package.

**Workaround (until fixed):** force the plugin copy —
`PYTHONPATH=<plugin>/hallucinote_mcp/src python3 -m hallucinote_mcp.cli install-remote-script …`
and verify with the same `PYTHONPATH` on `preflight`.

**Verifiable signal.** In a repo + plugin coexistence setup, `/ableton-mcp-install`
vendors the plugin's Remote Script (matching the launched server) and `preflight`
reports `matches_mcp_server` against the *running* server — so a fresh install never
yields a server↔Remote-Script mismatch. Surfaced 2026-06-13 dogfooding the swell push.
