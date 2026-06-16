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

- Engine `hallucinote`: **0.9.0** (`pyproject.toml`; `uv.lock` pins the same, editable).
- Plugin: **0.9.8** (`.claude-plugin/plugin.json`).

**Plugin version ≠ engine version, and that's fine.** They version independently;
the coupling is *by source* (`uv.lock` records `hallucinote` as an editable workspace
member, `editable = "."`), not by the version string. The lock + the commit are the
pin; the version strings are metadata.

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
