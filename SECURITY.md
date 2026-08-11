# Security Policy

## Reporting a vulnerability

**Please do not open a public issue for a security problem.**

Report privately through GitHub's [Security Advisories](https://github.com/brookstalley/hallucinote/security/advisories/new)
— that opens a channel visible only to the maintainers. If you can't use that, email
**brooks@tangentry.com** with `[hallucinote security]` in the subject.

Please include what you can: what you observed, how to reproduce it, the Hallucinote
version (ask Claude to *run preflight* — it prints the version; the CLI lives inside
the plugin's environment, so it won't import from a bare shell), your OS, and your
Live version. A proof of concept helps a lot.

**What to expect.** This is a small project, so response is best-effort rather than
contractual: an acknowledgement within about a week, an assessment of severity and a
fix plan after that. We'll credit you in the advisory and the changelog unless you'd
rather stay anonymous. If we conclude a report isn't a vulnerability, we'll explain
why rather than closing silently.

## Supported versions

Only the **latest released version** gets security fixes. There are no long-term
support branches. Releases are tagged in this repo and installed through the Claude
Code plugin marketplace, which auto-updates by default — so the practical advice is
to stay current.

## Trust model — read this before reporting

Hallucinote is a **local authoring tool**. It runs on your machine, drives a copy of
Ableton Live on that same machine, and exposes no network service to anyone else.
Several behaviors look alarming out of context but are the product working as
designed. Knowing which is which will save you time.

### Executing a song's `build.py` is intentional — and it is the sharpest edge

A song is a directory, and its composition is **Python source** (`build.py`) that the
engine imports and executes to produce the song's database. That is the core design
(it is what makes a song forkable, diffable, and reproducible), but it means:

> **Building someone else's song runs their code, with your user's privileges.**

Treat a song repository exactly as you'd treat any other repository you're about to
run — a cloned `build.py` is not data, it's a program. Review before building songs
from people you don't know. We are not going to sandbox this away; the executable
composition *is* the feature. Reports that amount to "`build.py` can run arbitrary
code" are working-as-designed and will be closed as such.

What *is* in scope here: a path where a song's data files (`captured_session.json`,
a `.wav`, an analysis JSON) achieve code execution **without** anyone running
`build.py`. Parsing shouldn't be executing.

### The Remote Script and the MCP bridge

`/hallucinote:ableton-mcp-install` copies a Control Surface script into Live's User
Library, and Live loads it at startup with Live's own privileges. The MCP bridge then
speaks to that script over a **loopback socket**. This is the only way to drive Live
programmatically, and it is deliberate.

In scope: anything that lets a **non-local** party reach that socket, or that makes
the installer write outside Live's User Library (a path-traversal in the vendoring
step, say). Out of scope: the mere fact that a local process can connect to a local
port, or that the installer writes into your own Live installation.

### Also out of scope

- Anything requiring an attacker to already have local access to your account.
- Vulnerabilities in Ableton Live, Max for Live, Claude Code, or third-party plugins.
  Report those to their vendors. We'll help route a report that turns out to be ours.
- Findings in `docs/archive/` — historical design documents, not shipped behavior.
- Dependency CVEs with no demonstrated reachable path through this codebase. Lockfile
  updates are welcome as ordinary pull requests.

## Hardening notes

- The bridge binds **loopback only**. If you have changed that, you are outside the
  supported configuration.
- Hallucinote sends no telemetry and makes no outbound network calls of its own.
- A song's SQLite database and its captures are regenerable build artifacts and are
  gitignored by default; the workspace setup (ask Claude to *"set up a songs
  workspace"*) writes that `.gitignore`. If you commit
  them anyway, be aware they carry absolute paths from your machine.
