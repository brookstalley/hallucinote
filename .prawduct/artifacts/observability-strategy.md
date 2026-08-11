---
artifact: observability-strategy
version: 1
depends_on:
  - artifact: architecture
last_validated: 2026-08-06
---

# Observability Strategy

**No telemetry, by decision.** Hallucinote emits no metrics, traces, or usage data, and
makes no outbound network calls of its own. There is no fleet to observe — every
instance runs on one user's machine, and the person who can see a problem is standing
in front of it. Adding telemetry would be a product decision requiring consent, not an
engineering gap to close.

What replaces it, for the three questions that actually get asked:

**"What happened to my song?"** — the `events` table. Every state change appends a row
with a monotonic `seq`, in the same transaction as the change. This is the audit trail,
and it is per-song and local. See [`data-model.md`](data-model.md).

**"Why is the bridge not working?"** — `python -m hallucinote_mcp.cli preflight`
diagnoses install state and prints the version handshake. The fingerprint mismatch
error is itself the primary diagnostic signal in this system: it converts a class of
silent, hours-long debugging sessions into one structured message naming the fix.
Per-runtime failure symptoms and recovery are tabulated in
[`architecture.md`](architecture.md).

**"Why does the mix sound wrong?"** — the domain's real observability surface. Render
writes per-surface WAVs plus a manifest; analysis writes a `MixReport` JSON to
`songs/<slug>/analysis/` carrying per-stem loudness (LUFS-I/S/M, true peak), masking
attribution, per-return RT60, timbre metrics, and realized-vs-declared automation
verification. That report is a versioned schema with programmatic consumers, so
changing its shape is a contract change (see [`api-contract.md`](api-contract.md)).

**Errors as observability.** Because the primary consumer is an LLM, error responses
carry `valid_actions`, parameter requirements, and recovery hints — the error is the
next turn's input. A bare error string is a defect here in a way it wouldn't be in a
human-operated system.

## Direction

Ratified 2026-08-10.

- **No telemetry. Hallucinote emits no metrics, traces or usage data, and makes no
  outbound network calls of its own.**
  Why: there is no fleet to observe — every instance runs on one user's machine, and the
  person who can see a problem is standing in front of it. So telemetry would buy the
  project nothing it cannot get by asking, while spending the user's trust in a tool that
  currently makes no network calls at all. Adding it is a **product decision requiring
  consent**, not an engineering gap to close; a PR that adds a first outbound call is
  amending this norm whether or not it says so.

- The audit trail (`events`), the install diagnostic (`preflight` + the fingerprint
  handshake), and the mix-analysis surface (`MixReport`) are the substitutes named above.
  Their governing norms are ratified in [`data-model.md`](data-model.md) § Direction and
  [`api-contract.md`](api-contract.md) § Direction — the `MixReport` in particular is a
  versioned schema with programmatic consumers, so changing its shape is a contract
  change.
