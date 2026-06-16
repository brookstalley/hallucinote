# Running the engine (the `hallucinote` CLI)

The composing engine ships **inside the plugin**. The plugin's uv environment holds
both the MCP bridge and the `hallucinote` package (one `uv sync --all-packages`), so
there is **no separate engine install** — no clone, no PyPI. Skills run engine
commands with the **plugin's own interpreter**, the one the bridge server is already
running in.

## The invocation

1. **Resolve the interpreter once per session.** Read `ableton://server/info` → its
   `python` field (the running server's interpreter, inside the prewarmed plugin env).
   Call it `$PY`.
2. **Run any engine command with it:**

   ```bash
   "$PY" -m hallucinote.cli <command> [args]
   ```

   This executes in the **same env as the bridge** — guaranteed version-synced, no
   env to build, and it works even when the plugin root is read-only. Your **cwd
   stays the songs workspace**, so `--song <slug>` and relative paths resolve there.

To run a song's `build.py` (it imports `hallucinote`), run it with the same interpreter:

```bash
"$PY" songs/<slug>/build.py [--reset]
```

## Commands

| `hallucinote.cli <command>` | was |
|---|---|
| `push …`        | `python -m hallucinote.sync.push_cli …` |
| `pull …`        | `python -m hallucinote.sync.pull_cli …` |
| `compat …`      | `python -m hallucinote.sync.compat …` |
| `capture …`     | `python -m hallucinote.tools.capture_cli …` |
| `context …`     | `python -m hallucinote.tools.song_context …` |
| `decisions …`   | `python -m hallucinote.tools.decisions_cli …` |
| `melody …` / `recurrence …` | the symbolic lenses (`tools.melody_lens` / `tools.recurrence_lens`) |
| `reindex …` / `scaffold …` / `inventory …` | `tools.reindex_markdown` / `tools.scaffold_song` / `hallucinote.inventory` |

`"$PY" -m hallucinote.cli --help`, or `… <command> --help`, prints the menu. (A
`hallucinote` console script is also registered in the env for interactive use, but
skills invoke via `"$PY" -m hallucinote.cli` because `$PY` is the one path
`ableton://server/info` hands them.)

## Why the interpreter, not `uv run`

`"$PY"` is the server's own `sys.executable`, so it *is* the prewarmed env — nothing
to resolve or build. `uv run --project <root>` would instead create/reuse uv's
default `<root>/.venv`, which is a **different** env from the bridge's and fails to
write under a read-only plugin root. Using the server's interpreter sidesteps both.
