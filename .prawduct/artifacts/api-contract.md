---
artifact: api-contract
version: 1
depends_on:
  - artifact: architecture
  - artifact: boundary-patterns
  - artifact: security-model
last_validated: 2026-08-06
---

# API Contract

Hallucinote exposes three programmatic surfaces. They have **different stability
guarantees**, and conflating them is the main way a contributor gets surprised.

| Surface | Consumer | Stability |
|---|---|---|
| **MCP tools** (13, action-dispatched) | The agent, over stdio | Contractual — the handshake enforces it |
| **`hallucinote` CLI** | Skills, contributors | Contractual for flags + exit codes |
| **Python engine** (`src/hallucinote/`) | A song's `build.py` | Contractual for the *authoring* surface only |

Process topology and the fingerprint mechanism are in
[`architecture.md`](architecture.md); per-boundary consumer lists are in
[`boundary-patterns.md`](boundary-patterns.md). Not restated here.

## Consumer status — a note on going public

`project-state.yaml` records `exposes_programmatic_interface: consumers: internal`.
That was accurate while the repo was private. **Publishing the repo does not by itself
make these interfaces public commitments**, and this artifact declines to promise
otherwise: the MCP tool surface is designed for *this project's agent*, and the engine
API is designed for *songs*. Third parties may call both, and are welcome to, but
should read the versioning policy below before depending on either.

The one surface where a public consumer is genuinely expected is the **song-authoring
API** — because forking a song is a supported workflow, and a forked `build.py` is a
program written against that API.

## Recorded decision: versioning

**Approach — the MCP surface is versioned by *content fingerprint*, not semver.**

`__version__` is `BASE_VERSION` (`0.1.0`, effectively frozen) plus a short SHA-256 over
the whole-file bytes of every file defining the wire shape. Two halves of the same
source tree — the server and the copy vendored into Live — each compute it, and the
handshake refuses to proceed when they differ.

*Why not semver here.* Semver communicates compatibility between a library and a
consumer who chose their version. That is the wrong model: the two halves are the same
code, deployed twice by our own installer, and the only question worth asking is
**"are these byte-identical?"** A human-maintained version number answers that question
badly, because it is exactly the thing a contributor forgets to bump. The fingerprint
cannot be forgotten.

*What it costs.* Any wire-shape edit invalidates it, so contributors must re-vendor
(`/hallucinote:ableton-mcp-install`) and **fully restart Live**. That friction is
intentional — the alternative was silent drift.

**The plugin and engine are versioned by semver** (currently **1.7.1**, in
`.claude-plugin/plugin.json` and `pyproject.toml`, which must agree). Releases are
tagged; the marketplace auto-updates.

## Recorded decision: error model

**Approach — errors teach.** Every error response carries structured recovery
information rather than a bare string:

- `valid_actions` — the tool's real action list, so a wrong action name self-corrects
  on the next call instead of requiring a guess.
- Required/optional parameters for the attempted action.
- A hint, and where useful an example invocation.

*Why.* The primary consumer is an LLM. An error is not a log line to be read by a human
later; it is **the next turn's input**, and its quality directly determines whether the
agent recovers or flails. This converges with published MCP practice, and it is why
`tool(action='help')` exists as a first-class action generated from the same metadata
layer the dispatcher validates against — one source of truth, so help can't drift from
behavior.

**Refuse-and-teach over silent wrong behavior** is the governing rule at every
boundary. Concretely: a mid-song tempo change surfaces a refusal at the call site
rather than corrupting timing; a device enum with no normalized wire form is **skipped
with a warning** rather than set to the wrong value. Silent data loss is never the
fallback.

## Recorded decision: deprecation and compatibility

**Approach — no compatibility shims to unshipped consumers; aliases for one major
version where real consumers exist.**

Because the server and Remote Script are deployed together by our own installer, there
is no window in which an old client meets a new server — the handshake makes that state
unreachable. So a wire-shape change does **not** need a back-compat path, and adding one
is actively discouraged (it is code with no caller, which decays).

Where consumers do exist and did not choose their version — the **song-authoring
Python API**, called by every `build.py` in every song repo — the policy is different:

- Adding a keyword argument with a default is non-breaking; do it freely.
- Renaming or removing an authoring function breaks every song ever written against it.
  Provide an alias for one major version, and say so in `CHANGELOG.md`.
- **Mutator signatures are keyword-only after `conn`**, every mutator accepts
  `actor` / `request_id` / `reason`, and every mutator emits exactly one event in the
  same transaction as its state change. That triple is the contract that makes the
  future event-store migration cheap — it is not negotiable per-call.

*Deferral, dated.* A formal support window for the engine API is **not** defined, and
won't be until there is evidence of a third-party song repo depending on it.
**Revisit trigger:** the first external contributor song repo, or an issue reporting a
break from an engine change. (Recorded 2026-08-06.)

## The MCP tool surface

Thirteen tools, each dispatching on an `action` string. The count is a deliberate
budget — empirical work on tool-selection accuracy shows it degrading sharply past
roughly ten to twenty tools, and the pre-consolidation surface (52 tools) was well
into the failing region.

| Tool | Domain |
|---|---|
| `ableton_session` | Global state, master, transport, view, tempo, signature, snapshot |
| `ableton_track` | Track lifecycle, mixer, sends, routing, monitor state |
| `ableton_return` | Return-track lifecycle and mixer |
| `ableton_clip` | Session + arrangement clips; lifecycle, properties, `replace_notes` |
| `ableton_note` | Within-clip note operations |
| `ableton_device` | Devices on tracks/returns; load, parameters, routing |
| `ableton_automation` | Envelopes across seven target families |
| `ableton_arrangement` | Arrangement layout, cue points, loop region |
| `ableton_scene` | Session-view scenes |
| `ableton_browser` | Instruments, effects, plugins; search and fetch |
| `ableton_render` | Audio capture pipeline (`start` + `status`; sync `render` retired) |
| `ableton_analysis` | Loudness, masking, RT60, stereo image / declared width, realized-vs-declared automation |
| `ableton_probe` | LOM capability probing under a constrained path grammar |

**Deliberate exclusion.** Timing transforms — quantize, swing, groove — are *not* on
this surface. They live in the Hallucinote engine because they are compositional
authorship, and routing them through Live would put musical decisions on the wrong side
of the boundary.

**Transport.** Loopback TCP `127.0.0.1:9878`, length-prefixed JSON. Read timeouts are
selected per (tool, action) and must exceed the handler's own long-poll window.

**`ableton_probe` is a sharp tool by design.** Its `set` and `call` actions mutate live
state — settability is itself the finding a probe is looking for. Its path grammar is
constrained (`song`/`application` roots, `.attr` and `[index]` steps only, tokenized by
regex, anything outside rejected before evaluation). Probe in scratch sets.

## The CLI

Single entry point `hallucinote` (`hallucinote.cli:main`), invoked by skills as
`"$PY" -m hallucinote.cli <cmd>`, where `$PY` is resolved once from
`ableton://server/info`'s `python` — the interpreter of the environment the
plugin already built (`docs/running-the-engine.md`).

**Flags, exit codes, and output format are a contract** — skills parse this output, and
so does the MCP layer for analysis reports. A schema change to a report JSON can break
a consumer that no test covers, which is why the full no-path `python -m pytest` run is
mandatory: `testpaths` covers both `tests/` and `hallucinote_mcp/tests/`, and a
path-scoped run silently skips half the suite.

`python -m hallucinote_mcp.cli preflight` is the supported install-state diagnostic and
prints the version handshake — the first thing to ask for in a bug report.

## What is not a public API

- **The SQLite schema.** Materialized state, rebuilt from source. Read it for debugging;
  do not write to it, and do not depend on its shape. Writes go through mutators.
- **`server_side/`.** Deliberately outside the fingerprint; internal by construction.
- **Anything in `docs/archive/`.** Historical design documents, not shipped behavior.

## Direction

Ratified 2026-08-10. These bind future work; the narrative above describes it.

- **The MCP surface is versioned by content fingerprint, never a hand-maintained number.**
  Why: semver communicates compatibility to a consumer who *chose* their version, and
  these two halves are the same source tree deployed twice by our own installer — the only
  question worth answering is "are these byte-identical?". A human-maintained number
  answers it badly because bumping it is exactly what a contributor forgets; the
  fingerprint cannot be forgotten.
  Rulings: [[A staleness/version signature must be content-derived, never hand-bumped]]

- **Errors teach.** Every error response carries structured recovery information —
  `valid_actions`, the attempted action's parameter requirements, a hint, and where useful
  an example — never a bare string.
  Why: the primary consumer is an LLM, so an error is not a log line read by a human
  later; it is **the next turn's input**, and its quality decides whether the agent
  recovers or flails. This is why `tool(action='help')` is generated from the same metadata
  layer the dispatcher validates against — one source of truth, so help cannot drift from
  behavior.

- **Refuse-and-teach over silent wrong behavior, at every boundary.** When a value cannot
  round-trip faithfully, refuse at the call site or skip with a warning — never write the
  wrong value.
  Why: silent data loss in an authoring tool destroys work the user cannot know to
  re-check, which is strictly worse than a refusal they can see and route around. A
  mid-song tempo change refuses rather than corrupting timing; a device enum with no
  normalized wire form is skipped rather than set wrong. This is a stated product value,
  not a limitation to engineer away quietly.

- **No compatibility shims for consumers that cannot exist; one-major-version aliases
  where they can.**
  Why: the server and Remote Script deploy together and the handshake makes
  "old client meets new server" unreachable, so a wire-shape back-compat path is code with
  no caller — and code with no caller decays into a trap. The song-authoring Python API is
  the opposite case: every `build.py` ever written is a consumer that did not choose its
  version, so renaming or removing an authoring function earns an alias for one major
  version, announced in `CHANGELOG.md`.
  Status: steady-state. A formal support window for the engine API remains undefined —
  **revisit trigger:** the first external contributor song repo, or an issue reporting a
  break from an engine change. (Recorded 2026-08-06.)

- **Mutator signatures are keyword-only after `conn`, and every mutator accepts
  `actor` / `request_id` / `reason`.**
  Why: that triple is what lets the event log answer *who, under which request, and why*
  for any state change — the three questions a bare audit row cannot answer and a future
  event store cannot reconstruct after the fact. It is the contract that keeps the
  event-store migration a reinterpretation rather than a rewrite, so it is not negotiable
  per-call.

- **Timing transforms — quantize, swing, groove — stay in the engine and off the MCP
  surface.**
  Why: they are compositional authorship, and routing them through Live would put musical
  decisions on the wrong side of the boundary, where they become unversioned, undiffable,
  and invisible to a song's source.

- **The MCP tool surface stays inside the band where tool-selection accuracy holds;
  adding a tool is a decision, not a default.**
  Why: empirical work shows selection accuracy degrading sharply past roughly ten to twenty
  tools, and the pre-consolidation surface (52 tools) was well into the failing region. The
  budget is the norm; the current count lives in the descriptive table above, where it can
  change without unmaking this decision.

- **These interfaces stay internally scoped: publishing the repo does not convert them
  into public commitments.**
  Why: the MCP surface is designed for *this project's agent* and the engine API for
  *songs* — third parties may call both and are welcome to, but the design center does not
  move to them by default. The one surface where a public consumer is genuinely expected,
  the song-authoring API, already carries its own policy and revisit trigger above.
  Flipping `exposes_programmatic_interface` would re-derive the artifact set and force an
  assumption audit for a trust posture that did not change when the repo went public.
  (Owner ruling, 2026-08-10 ratification — `consumers: internal` stands.)
