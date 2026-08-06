---
artifact: operational-spec
version: 1
depends_on:
  - artifact: architecture
last_validated: 2026-08-06
---

# Operational Spec

**(Not relevant as conventionally scoped — there is nothing operated.)**

Hallucinote is a locally-installed desktop authoring tool. There is no server we run,
no environment to provision, no deploy, no rollback, no on-call, no capacity or cost
management. Every process runs on the user's own machine and is started by the user or
by their agent host.

The two genuinely operational procedures that *do* exist are documented where the
people who need them will look:

- **Releasing a version** — [`docs/release-process.md`](../../docs/release-process.md).
  The step that bites: a release must re-vendor when the wire-shape fingerprint has
  changed, or installed users hit a handshake mismatch.
- **Installing and repairing a user's bridge** — `/hallucinote:ableton-mcp-install`,
  with `python -m hallucinote_mcp.cli preflight` as the diagnostic. Recovery for each
  runtime is tabulated in [`architecture.md`](architecture.md).

Revisit this artifact if a hosted component is ever introduced — a shared song
registry, a rendering service, or anything with an uptime expectation.
