# Engine + bridge: one environment

Hallucinote's **engine** (`hallucinote`) and **bridge server** (`hallucinote_mcp`)
both run in a **single** environment — the plugin's uv env at
`${CLAUDE_PLUGIN_DATA}/venv`, built by `uv sync --all-packages` from the plugin's
committed `uv.lock`. They can't silently diverge because there is nothing to keep in
sync: both are workspace members of the *same* project, installed **editable** from
the *same* source the bridge runs.

This supersedes the old two-environment pin (a separate editable clone for
`build.py` vs the plugin's server-env). There is no second environment now — skills
run the engine via the **server's own interpreter** (`ableton://server/info` →
`python`, i.e. `"<python>" -m hallucinote.cli …`), so `build.py` and the bridge
execute in the exact same env. No clone, no `pip install`, no PyPI.

## Current pin (keep honest when versions move)

- Engine `hallucinote`: **1.6.1** (`pyproject.toml`; `uv.lock` pins the same, editable).
- Plugin: **1.6.1** (`.claude-plugin/plugin.json`).

**Plugin, engine, and MCP-package versions move in lockstep (since 1.5.0).** Root
`pyproject.toml [project].version` is the canonical product version; the plugin
manifest, the MCP package's `pyproject.toml`, and `src/hallucinote/__init__.py`
carry a literal copy, and `tests/unit/test_version_parity.py` fails CI on drift. The
coupling is *by source* (`uv.lock` records `hallucinote` as an editable workspace
member, `editable = "."`); the lock + the commit are the pin. The one version that
is **deliberately decoupled** is the MCP server's handshake `BASE_VERSION+fingerprint`
(`hallucinote_mcp/src/hallucinote_mcp/__init__.py`) — see [§Version surfaces in the
release process](release-process.md#version-surfaces).

## Checking alignment

```bash
# Engine version the plugin's lock pins:
grep -A1 'name = "hallucinote"' uv.lock | grep version

# Engine + server package version at runtime (inside the plugin env):
python -m hallucinote_mcp.cli version
```

For the **Live** side, the Remote-Script ↔ server version handshake guards drift
(see the README troubleshooting *"version handshake missing"*). See
`.prawduct/artifacts/plans/INS-7V2D/design.md` §6 for the env design rationale.
