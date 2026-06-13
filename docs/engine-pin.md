# Engine version pinning — why the two environments stay in sync

Hallucinote runs the **same `hallucinote` engine package in two environments**, and
they must not silently diverge. This is the record of how they're pinned and how to
check alignment.

## The two environments

| Environment | What it is | How the engine gets there | Authoritative pin |
|---|---|---|---|
| **Plugin server-env** | the bundled `hallucinote-mcp` bridge the plugin launches | `uv run --frozen` builds it from the plugin's committed `uv.lock` into `${CLAUDE_PLUGIN_DATA}/venv` | **`uv.lock`** (the `name = "hallucinote"` package, `source = { editable = "." }`) |
| **Composing / song-env** | where your `build.py` runs (`pip install -e .`) | you editable-install this checkout (README → *Clone and install*) | the engine version in your **`pyproject.toml`** at the checked-out commit |

`build.py`'s push path imports `hallucinote_mcp` as a library and reaches the engine;
the plugin's bridge runs the *same* engine source. If the song-env engine and the
plugin's locked engine come from different commits, analysis/push behavior can drift
without any error — hence this pin.

## Current pin (keep this row honest when versions move)

- Engine `hallucinote`: **0.9.0** (`pyproject.toml`; `uv.lock` pins the same, editable).
- Plugin: **0.9.7** (`.claude-plugin/plugin.json`).

**Plugin version ≠ engine version, and that's fine.** The plugin and the engine
version independently. The coupling guarantee is *by source*, not by the version
string: the plugin's `uv.lock` records `hallucinote` as an **editable workspace
member** (`editable = "."`), so the bridge always runs the engine source bundled at
the plugin's commit. The version string is metadata; the lock + the commit are the
pin. (So the 0.9.0/0.9.4 gap is recorded here on purpose, not a defect to "fix" with a
no-op engine bump.)

## Checking alignment

```bash
# Engine version the plugin's lock pins:
grep -A1 'name = "hallucinote"' uv.lock | grep version

# Engine version your composing env will install:
grep '^version' pyproject.toml

# Server/engine package version at runtime:
python -m hallucinote_mcp.cli version
```

For the **Live** side, the Remote-Script ↔ server version handshake already guards
drift (see the README troubleshooting *"version handshake missing"*); this record is
about the engine package the two *Python* environments run.

## Why it isn't enforced yet (and what would)

Today alignment is **by convention** — install the plugin and editable-install *this
same checkout* (README keeps the two on the same version "so they agree"). True
enforcement needs:

- the engine on **PyPI** + a song-side version pin (out of scope here — the songs
  repo currently builds against whatever `hallucinote` is installed), and
- **drift fingerprinting** (INS-4H8M) to fail loudly when the song-env engine doesn't
  match the bridge's.

Until then, this record makes the coupling — and any version gap — *visible* rather
than silent, which is its whole job. See `.prawduct/artifacts/plans/INS-7V2D/design.md`
§6 for the design rationale.
