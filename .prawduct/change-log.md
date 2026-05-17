# Change Log — Hallucinote

<!-- Append new entries at the top. Each entry is a ## section.
     This file is separate from project-state.yaml to reduce merge conflicts
     when multiple branches add entries simultaneously. -->

## 2026-05-17 — Install / uninstall skill cross-platform hardening

`hallucinote_mcp/src/hallucinote_mcp/install_paths.py` grew detection
helpers for User Library candidates (Windows OneDrive Documents
redirection, USERPROFILE divergence), installed Live versions, Live
process probing, `hallucinote-mcp` command resolution (PATH +
venv-bin/Scripts fallback, returning `(path, on_path)`), and MCP config
scanning across three scopes (project-local `.mcp.json`, global
top-level `~/.claude.json`, and the `projects.<cwd>.mcpServers` scope
that `claude mcp add` writes by default).

`python -m hallucinote_mcp.cli preflight` is a new CLI subcommand that
emits a JSON report consumed by both SKILL.md bodies — single source of
truth for install/uninstall detection. Both SKILL.md files rewritten to
drive off preflight: Claude Code now auto-detects Live state, User
Library location, installed Live versions, MCP config scope, and
malformed JSON instead of asking the user. Drift between SKILL.md copy
commands (rsync / robocopy / Copy-Item fallback) and `REMOTE_SCRIPT_EXCLUDE`
is now structurally enforced by `test_install_skill_consistency.py`.
