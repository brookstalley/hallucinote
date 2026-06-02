---
description: Post-sync advisory management — list, inspect, dismiss, undismiss, or resolve the advisories surfaced in the session briefing
argument-hint: "list [--state=active|dismissed|resolved|all] [--feature=<name>] | show <id> | dismiss <id> [--reason \"...\"] | undismiss <id> | resolve <id>"
user-invocable: true
disable-model-invocation: false
context: fork
allowed-tools: Read, Bash(python3 tools/product-hook advisory*)
---

You are managing **post-sync advisories** — the "this project should probably do X, but we won't force it" nudges that sync probes raise and the session briefing surfaces under `ADVISORIES (post-sync, N active)`. They are informational, never gates.

All work goes through one command: `python3 tools/product-hook advisory <subcommand>`. Do not edit `.prawduct/.advisories.json` by hand — it is the per-clone nag log, owned by the advisory store.

## Subcommands

| Invocation | What it does |
|---|---|
| `python3 tools/product-hook advisory list` | List **active** advisories (default). |
| `python3 tools/product-hook advisory list --state=active\|dismissed\|resolved\|all` | Filter by lifecycle state. `all` shows every state. |
| `python3 tools/product-hook advisory list --feature=<name>` | Filter to one feature (e.g. `--feature=backlog`). Combines with `--state`. |
| `python3 tools/product-hook advisory show <id>` | Full detail on one advisory. For a resolved/dismissed (compact) entry it **re-runs the probe** to reconstruct the full evidence list. |
| `python3 tools/product-hook advisory dismiss <id> [--reason "..."]` | Dismiss (sticky — won't re-surface even if the trigger persists). Reason optional but encouraged. |
| `python3 tools/product-hook advisory undismiss <id>` | Clear a dismissal — returns to active if the probe still fires on next sync. |
| `python3 tools/product-hook advisory resolve <id>` | Manually mark resolved now (rare — usually a probe or the recommended action does this). |

## How to use this skill

1. Parse `$ARGUMENTS` into a subcommand + args. If empty, run `list` (active) as the default and show the result.
2. Run the matching `python3 tools/product-hook advisory ...` command and relay its output.
3. For `dismiss`/`undismiss`/`resolve`, confirm the id exists first if the user is unsure — run `list --state=all` and check. A `not found` result means the id is wrong or the advisory was already garbage-collected.
4. Resolution normally happens automatically: run the advisory's `recommended_action`, and the next sync clears it (the probe stops firing once the project-state fact is set). Prefer that path over manual `resolve`.

$ARGUMENTS
