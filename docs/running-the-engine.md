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
| `captures …`    | `python -m hallucinote.tools.captures_cli …` (render-take retention: list/prune/pin) |
| `context …`     | `python -m hallucinote.tools.song_context …` |
| `decisions …`   | `python -m hallucinote.tools.decisions_cli …` |
| `melody …` / `recurrence …` | the symbolic lenses (`tools.melody_lens` / `tools.recurrence_lens`) |
| `reindex …` / `scaffold …` / `inventory …` | `tools.reindex_markdown` / `tools.scaffold_song` / `hallucinote.inventory` |
| `init-workspace` | scaffold a songs workspace (`hallucinote.toml`, `.gitignore`, `git init`) in the cwd |
| `overview-drift <slug>` | report a `<slug>.md` Structure table or `build.py` docstring layout that has drifted from the form the DB carries (reports only; never rewrites). Songs scaffolded from 2026-08-11 run this at their build close automatically — this is the on-demand path for older ones. |
| `verify-arrangement` | audit the DB arrangement against Live (exit 1 on divergence) |
| `tuning-pull …` | capture Live's loaded alternate tuning onto a song (`/tuning-pull`'s apply step) |

`"$PY" -m hallucinote.cli --help`, or `… <command> --help`, prints the menu. (A
`hallucinote` console script is also registered in the env for interactive use, but
skills invoke via `"$PY" -m hallucinote.cli` because `$PY` is the one path
`ableton://server/info` hands them.)

## Capture retention (render takes)

Each render writes one take to `songs/<slug>/captures/<ts>/` — a 32-bit-float
WAV per track, return and master, roughly 23 MB per surface-minute, so a
full-length multi-track song costs gigabytes per take. A rolling window runs
automatically **at render start**: it keeps the **2 newest takes already on
disk** and removes the rest, then the render writes its own — so a song settles
at **3 takes** after each render. (`captures prune --song <slug> --keep 2` run
on its own leaves 2, because no new take follows it.)

Deleting an old take is safe because the durable measurement is the MixReport
in `songs/<slug>/analysis/` — analysis reads a take once and writes a
self-contained JSON, and baseline comparison (`compare_to`) resolves against
those JSONs, never the audio. Reports are never swept; what a sweep costs is
re-analyzing that specific take with different parameters.

To keep a reference take permanently, pin it — `"$PY" -m hallucinote.cli
captures pin songs/<slug>/captures/<ts>` (pinned takes are skipped by every
sweep and don't consume a keep slot). An unpinned take survives the next two
renders and is removed at the start of the third. `captures list` shows what's
on disk; `captures prune --song <slug> --dry-run` previews a sweep without
deleting. (These are `hallucinote.cli` subcommands — run them with `$PY` as
above; a bare `hallucinote` is not on PATH, and a silent `command not found` on
`pin` means the take it was meant to protect is swept at a later render.)

`HALLUCINOTE_CAPTURE_KEEP` changes the window and `HALLUCINOTE_CAPTURE_SWEEP=0`
turns the automatic sweep off. Both are read by the **MCP server process**, so
to affect the automatic sweep they must be set in the `env` block of this
server's entry in the user's Claude settings — exporting them in a terminal
reaches the CLI but not the server. The server logs `retention sweep disabled`
at INFO when the opt-out reached it, so the setting confirms itself.

## Why the interpreter, not `uv run`

`"$PY"` is the server's own `sys.executable`, so it *is* the prewarmed env — nothing
to resolve or build. `uv run --project <root>` would instead create/reuse uv's
default `<root>/.venv`, which is a **different** env from the bridge's and fails to
write under a read-only plugin root. Using the server's interpreter sidesteps both.
