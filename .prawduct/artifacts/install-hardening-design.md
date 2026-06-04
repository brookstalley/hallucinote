# Install Hardening — move every install mutation into tested, atomic Python

**Status:** designed (2026-06-04). Build plan: `.prawduct/artifacts/build-plan.md`.
**Area:** `hallucinote_mcp` (the stdlib-only, isolated MCP package). **Type:** refactor +
hardening (behavior-preserving for a *successful* install; behavior-*correcting* for the
failure modes). **Size:** large (new module surface + CLI subcommands + skill rewrites +
test expansion). Principles: structural-fix-over-patch (`feedback_engineering_rigor`),
ruler-not-stamp (the skill orchestrates; Python does the deterministic work), tests-are-
contracts.

## Problem (observable)

The `/ableton-mcp-install` and `/ableton-mcp-uninstall` skills hand-author **every
filesystem mutation in shell** — `rsync`/`robocopy`/`cp`/`rm`, plus JSON config
read-merge-write — across **three platform variants** kept in sync only by a
string-matching consistency test. Concretely, this just bit a real install
(2026-06-03, `~/source` plugin install):

1. **A zsh glob aborted the copy mid-install.** `install_paths.rsync_exclude_args()`
   correctly returns `--exclude=*.pyc`, but the skill pasted it into a zsh command line
   where `*.pyc` glob-expanded with no match → zsh aborted the whole line *after* the
   preceding `rm -rf` + `mkdir` + stub-write had run. Result: a **half-installed Remote
   Script** (stub present, vendored package missing) that would load a broken Control
   Surface in Live. Only the agent's vigilance caught it.
2. **~8 permission-prompting Bash calls**, several read-only probes that preflight
   already covers, several mutations interleaved — no single reviewable "this is the
   destructive step" moment.
3. **No atomicity.** Any failure/abort between the `rm` and the copy leaves a broken
   install with no rollback.
4. **The mutation logic is untested.** Only arg-*generation* and *detection* are
   covered; the copy, the stub write, the analyzer copy, and all MCP-config
   read/merge/write/delete are shell in the skill body — zero unit tests.
5. **Cross-platform drift risk.** Three hand-maintained copy variants
   (rsync / robocopy / PowerShell-fallback) reconciled by a brittle SKILL.md
   string-drift test rather than one behavior.

## Success (what "right" looks like)

- **Every install/uninstall filesystem mutation is performed by tested, atomic,
  cross-platform Python** in `hallucinote_mcp`, exposed through CLI subcommands. The
  skills contain **zero** hand-authored copy / delete / JSON-edit shell.
- **A mid-operation failure never leaves a broken install.** The Remote Script is
  swapped in atomically from a fully-built-and-verified staging dir; the live target is
  always either the complete old install or the complete new one.
- **The load-bearing excludes and the MCP-config decision matrix are unit-tested
  behaviors**, not SKILL.md string-drift checks.
- **Install and uninstall are symmetric** — same detection, mirror-image mutation.
- **Permission prompts collapse** to the genuinely destructive operations (which
  *should* confirm), each a single atomic call, not a chain of `rm`/`mkdir`/`rsync`/
  `find`.

## Out of scope

Remote Script runtime behavior; the M4L analyzer internals; the version-fingerprint
mechanism; Live-edition detection improvements; Windows long-path heroics beyond what
`shutil` provides; the `plugin.json` `mcpServers` entry (it stays — see *MCP config*
below, it composes correctly with the new override logic).

## Architecture

`install_paths.py` keeps its role: **read-only detection + path math** (unchanged). All
mutation moves into two new stdlib-only modules, a read/write split:

| Module | Concern | Key surface |
|---|---|---|
| `install_ops.py` | Remote Script + analyzer + stub **file-tree** mutations | `vendor_remote_script`, `write_remote_script_stub`, `verify_remote_script`, `install_analyzer`, `remove_remote_script`, `remove_analyzer` |
| `mcp_config.py` | MCP **config** read/merge/write/delete + the decision matrix | `plan_mcp_config`, `merge_server_entry`, `write_config_atomic`, `delete_entry` |

CLI subcommands (in `hallucinote_mcp/cli/`, alongside `preflight`) make these scriptable
and the skill's only mutation surface. Each is thin: parse args → call the function →
emit a JSON result (`{"ok": bool, ...}`):

- `install-remote-script --user-library PATH [--force]`
- `install-analyzer --user-library PATH [--force]`
- `configure-mcp --scope {user,project} --cwd PATH --registered {true,false}` (drives `plan_mcp_config` → write-or-skip)
- `uninstall-remote-script --user-library PATH`
- `remove-mcp-config [--cwd PATH]`

### The atomicity strategy (the core robustness win)

`vendor_remote_script(package_root, install_dir, *, force)` — never mutates the live
target until a complete, verified tree exists:

1. Stage into a sibling temp dir on the **same filesystem** as the target
   (`<UL>/Remote Scripts/.Hallucinote.staging-<pid>`) so the final swap is a rename.
2. Copy the package tree via `shutil.copytree(..., ignore=_ignore)`, where `_ignore`
   applies the existing `REMOTE_SCRIPT_EXCLUDE_*` constants **in Python** — and
   reproduces rsync's anchoring: exclude `server.py` **only when the source dir is the
   package root** (so `remote_script/server.py` survives); exclude `cli`/`tests`/
   `__pycache__`/`m4l` dirs and `*.pyc` **anywhere**. No shell, no glob expansion, ever.
3. Write the Control Surface stub (`__init__.py`) into the staging dir.
4. **Verify the staged tree** (`verify_remote_script`): required files present, excludes
   held (no package-root `server.py`, no `cli`/`tests`/`m4l`/`__pycache__`/`*.pyc`,
   `remote_script/server.py` kept). If verify fails → delete staging, raise structured
   error. **The bad state is caught before it can ever become the live install.**
5. **Atomic swap with rollback:** move an existing target aside to
   `.Hallucinote.backup-<pid>`, move staging → target, delete backup. If the
   staging→target move fails, move the backup back. (Windows can't `os.replace` onto a
   non-empty dir, so use move-aside-then-move-in on every platform for one code path.)
6. Return a structured `VendorResult` (target, version, the verify report, what was
   replaced).

A crash leaves only collectable `.staging`/`.backup` dross; the **live target is always
the complete old or complete new install** — the half-install of failure mode #1 is
structurally impossible.

`install_analyzer(src, dst, *, force)` — copy to `dst.tmp`, then `os.replace` → `dst`
(atomic file swap). Refuse overwrite unless `force` (the user may have customized the
`.amxd` via the Max GUI); the skill owns the ask.

### MCP config — the decision matrix, keyed on PATH not plugin-detection

The earlier discussion framed this as "is the server plugin-provided?" Investigation
shows that's the wrong key — it would couple Python to Claude Code's plugin-cache layout.
The correct key is **two runtime facts the skill is positioned to know** plus the
command resolution Python already computes. `plan_mcp_config` is a pure, fully
unit-testable truth table:

Inputs: `command_path: Path|None`, `on_path: bool` (from `install_paths`),
`already_registered: bool` (supplied by the skill from `/mcp` — the agent can see the
loaded servers), `scope: 'user'|'project'`, `cwd`.

| `command_path` | `already_registered` | `on_path` | → Plan |
|---|---|---|---|
| `None` | — | — | **error** — "pip install hallucinote-mcp, re-run" |
| set | true | true | **skip** — the registered entry (plugin bare command or existing config) launches fine. *(This is the pyenv/PyPI/global happy path — and exactly what the 2026-06-03 install correctly did.)* |
| set | true | **false** | **write** absolute-path entry at **user scope** — overrides the broken bare registration via precedence (Local>Project>User>Plugin). *(The venv-not-activated case the earlier thread worried about — now handled.)* |
| set | false | true | **write** bare command at chosen scope. |
| set | false | false | **write** absolute path at chosen scope. |

This dissolves the "plugin-provided" murkiness: when the registered command is on PATH it
works regardless of *who* registered it; when it isn't, a user-scope absolute override
wins by precedence. `plugin.json`'s bare `mcpServers` entry stays as the on-PATH default;
the skill writes an override only in the not-on-PATH row. Keeps the
`#143`/`#144` fix and closes its venv gap.

`merge_server_entry(config, command, args)` sets `mcpServers["hallucinote-mcp"]` without
clobbering other servers; `write_config_atomic(path, config)` is temp+`os.replace`;
`delete_entry(path, json_pointer)` walks the pointer from `existing_mcp_config_files()`
and atomically rewrites (uninstall's mirror).

### Skill = orchestration only

**install:** preflight (1 read) → present the plan + confirm (Live closed, User Library,
scope) → `configure-mcp`/`install-remote-script`/`install-analyzer` (≤3 atomic, self-
verifying mutations) → render the existing fresh/update hand-off. From ~8 mixed
read/mutate Bash calls to 1 read + ≤3 clearly-described mutations; the mutations *should*
prompt (they touch Live's library), but each is now one atomic operation, not a chain.

**uninstall:** preflight → confirm → `uninstall-remote-script` + `remove-mcp-config`
(deletes across every scope `existing_mcp_config_files()` finds) → render. Symmetric.

The SKILL.md's correctness contract moves from "the doc contains the right rsync string"
to "the doc invokes the right CLI subcommand" + "the Python applies the right excludes" —
strictly stronger (a real behavioral test, not string-drift). `test_install_skill_consistency.py`
is updated to the new contract, not weakened.

## Test plan

- `test_install_ops.py` — vendor excludes (anchored root `server.py` excluded /
  `remote_script/server.py` kept / `cli`,`tests`,`m4l`,`__pycache__`,`*.pyc` absent),
  **atomicity** (verify-fail aborts without swapping; a staged failure leaves the prior
  target intact; idempotent re-vendor), stub written, analyzer copy + overwrite guard,
  `verify_remote_script` catches missing/extra. Synthetic package tree under `tmp_path`.
- `test_mcp_config.py` — `plan_mcp_config` truth table (all five rows), merge doesn't
  clobber siblings, atomic write, delete-by-pointer, malformed handling.
- `test_install_skill_consistency.py` — updated: skills invoke the CLI subcommands; the
  exclude contract is asserted against the Python constants/behavior.
- CLI smoke tests — each subcommand's JSON shape + exit behavior.

## Chunks (see build-plan.md)

1. **Vendor core** — `vendor_remote_script` (atomic + excludes) + `write_remote_script_stub`
   + `verify_remote_script` + `install-remote-script` CLI + tests. *(Thin vertical slice;
   also the direct fix for the failure that triggered this work.)*
2. **Analyzer + removals** — `install_analyzer`, `remove_remote_script`, `remove_analyzer`
   + CLI + tests (the uninstall file side).
3. **MCP config** — `mcp_config.py` (`plan_mcp_config` + merge/write/delete) + `configure-mcp`
   / `remove-mcp-config` CLI + tests.
4. **Skill rewrite** — install + uninstall SKILL.md to orchestration-only; update the
   consistency test to the new contract.
5. **Integration + final** — dry-run install/uninstall against a tmp User Library;
   `/critic final`; learnings + doc reconciliation.
