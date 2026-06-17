# MCP version fingerprint — design decision (MCP-7F2K)

**Status:** design (research → ready). Decides the *approach*; build plan follows.
**Backlog:** `MCP-7F2K` (mcp · M/M · related INS-3W8P, INS-4H8M, MCP-4T6Y).
**Grounded in code, 2026-06-17.** All file refs are `hallucinote_mcp/src/hallucinote_mcp/…`.

## Problem (grounded)

The server version is `__version__ = f"{BASE_VERSION}+{fingerprint}"`
(`__init__.py:111`). The fingerprint is a SHA-256 over the **whole-file bytes** of
every file under `_FINGERPRINT_PATHS` (`__init__.py:21-78`):

```python
_FINGERPRINT_PATHS = ("wire.py", "schema.py", "dispatcher.py",
                      "actions", "handlers", "remote_script")
```

The handshake compares the **full version string** (base+fingerprint) on both the
install pre-vendor guard (`cli/install.py:89`, `--require-server-version`) and
preflight's `matches_mcp_server` (`cli/preflight.py:55`). So **any byte change to
any file in those paths flips the version**, and a flipped version makes
`matches_mcp_server` go false → the user is prompted to re-run
`/ableton-mcp-install` and re-vendor the Remote Script.

**The over-trigger:** `handlers/` is in the fingerprint and contains handler
modules that **never execute in Live**. `handlers/analysis.py` is declared
`runs_server_side=True` (its actions in `actions/analysis.py:102,166,208`) and its
own docstring says *"Both actions are server-side — analysis touches disk + the
song DB only, never Live"* (`handlers/analysis.py:8-9`). The dispatcher honors this
at `dispatcher.py:409` (`if action.runs_server_side:` → run in the MCP server
process, `context=None`, never sent over TCP to Live). The `hallucinote` engine
import in that module is function-local *precisely because* it is "only exercised
on the MCP server side" (`handlers/analysis.py:30-34`). Yet the module's bytes are
hashed into the fingerprint — so a **read-side analysis fix** (the exact scenario
that filed MCP-7F2K) flips the handshake version and nags every user to re-vendor,
even though nothing that runs *in Live* changed.

## What the handshake is actually for

The Remote Script is a **vendored copy** of the package files that run *inside
Live*. The handshake exists to answer one question: **is Live's vendored copy
stale relative to the code the server expects to run there?** So the fingerprint
should cover exactly the set of files that are **(i) vendored into Live AND
(ii) executed in Live.** The bug is that the current set includes files that fail
(ii): server-side-only handlers are vendored (dead weight) but never run in Live,
so their changes are irrelevant to staleness — and must not flip the handshake.

This reframe is the whole decision: **fingerprint the Live-crossing surface, not
the server's internals.** The codebase already has the boundary as a first-class,
enforced declaration — `schema.Action.runs_server_side` (`schema.py:153`,
validated in `__post_init__` at `schema.py:204-222`). We don't have to invent the
category; we have to make the fingerprint *respect* it.

## The three candidate approaches

### (a) Narrow the fingerprint to wire-crossing files only
Keep the content-hash mechanism; shrink the hashed set to files that execute in
Live. **Correct in spirit, but `handlers/` is a mix** (Live-side LOM handlers +
the server-side analysis handler), so "narrow" can't be done by top-level path
alone — it needs the server-side files *separated out first*. That is (c). So (a)
is the **goal**, achieved **via** (c).

### (b) Fingerprint the declared contract structurally
Hash only the wire contract shape — `TOOLS`, action names, `ParamSpec`
name/type/required/enum, Request/Response shapes — not implementation bytes.
- **Pro:** flips *only* when a caller-visible contract changes; immune to all
  implementation churn (refactors, logging, analysis fixes).
- **Fatal con as the *primary* mechanism:** it would **suppress re-vendor for
  Live-side handler bug fixes**. A fix to a Live-executed handler (same params,
  corrected behavior) leaves the contract identical, so (b) wouldn't bump the
  version — and Live would keep running the **old, buggy** vendored handler with no
  prompt to update. That is a correctness regression in the *opposite* direction
  from MCP-7F2K: today we over-prompt; pure-(b) would *under*-prompt exactly when
  the user needs the fix in Live. The handshake must still fire on Live-side
  implementation changes, because those *are* the staleness it guards.

### (c) Separate vendored-and-executed code from server-only code
Structurally partition handlers (and their action specs) so server-side-only
modules live in a path the fingerprint (and, optionally, the vendor) can exclude
wholesale — keyed off the existing `runs_server_side` declaration. This makes (a)
mechanical and keeps the fingerprint a pure, import-free file walk.

## Decision

**Adopt (c) in service of (a). Reject (b) as the primary mechanism; keep it as an
optional hard/soft refinement (below).**

Rationale: the fingerprint should measure "Live-side code drift," nothing more and
nothing less. (c)+(a) makes the *measured set* equal the *Live-executed set*,
which is correct by definition — server-side changes stop flipping it (fixes
MCP-7F2K) while every Live-side change still does (preserves the guard's value).
(b) alone breaks the second half.

### Mechanics (build sketch — for a follow-on plan, not this doc)

1. **Relocate the server-side handler set** (today: `handlers/analysis.py`; the
   general rule is *every module reachable only from `runs_server_side=True`
   actions*) into a path-distinguished location, e.g. `handlers/server_side/`.
   Relocate its action spec(s) (`actions/analysis.py`) alongside if practical —
   their param schemas are also server-side-only (validated server-side, never by
   the Live dispatcher). Priority is the **handler** module: handler bodies are
   the high-churn source; action param specs change rarely.
2. **Remove that location from `_FINGERPRINT_PATHS`** (and add a rationale comment
   mirroring the existing `node_features` exclusion note at `__init__.py:59-62`).
   Keep the fingerprint an import-free file walk — path-based exclusion preserves
   that (vs. importing `schema`/`actions` to ask each action whether it's
   server-side, which would make the fingerprint fragile and engine-coupled).
3. **Isolation invariant + test** (mirror the microtune FR-6 grep-assert): assert
   (i) every module under the server-side location is referenced only by
   `runs_server_side=True` actions, and (ii) **no Live-side handler imports from
   the server-side location.** (ii) is what makes the exclusion *safe* — it
   guarantees a server-side change cannot transitively alter Live-side behavior.
   Shared utilities that both sides use must stay in the fingerprinted set (a
   change there legitimately flips the version); the test enforces the import
   direction, not a ban on sharing.
4. **Preserve INS-3W8P.** The version string shape is unchanged
   (`base+fingerprint`); `ableton://server/info`, `--require-server-version`, and
   `matches_mcp_server` semantics are untouched. The fingerprint simply flips less
   often — only on genuine Live-crossing changes. No handshake-protocol change, so
   no Remote-Script-side coordination needed.

### Optional refinement — hard vs. soft version delta (defer unless wanted)
A second, **structural contract hash** (approach (b), computed *additionally*) can
classify a version mismatch:
- **HARD** — the contract hash differs → server and Live can't agree on the wire;
  re-vendor is mandatory and may block a push (today's behavior).
- **SOFT** — only the Live-side *implementation* fingerprint differs (contract
  same) → Live is running compatible-but-older code; surface as a **non-blocking
  advisory** ("a newer Live-side build is available; re-vendor when convenient"),
  never a hard stop.

This further reduces friction (a Live-side handler fix becomes a gentle nudge, not
a blocking handshake failure) and directly serves the "user trust in the
handshake" goal — but it adds a second hash and a severity concept. **Not required
to fix MCP-7F2K**; propose as a phase 2 only if the core fix proves insufficient.

## Risks / open questions (resolve at build time)

- **Registry coupling.** Does anything Live-side import `handlers/analysis.py`
  transitively at registry-build time? We keep vendoring it by default (harmless —
  the engine import is function-local), so module import still resolves; we only
  change the *fingerprint* set. If a later step also drops server-side handlers
  from the **vendor** (they're dead weight in Live's User Library), that must be
  gated on the registry tolerating their absence — a separate decision.
- **Boundary accuracy.** The fix rests on `runs_server_side` being declared
  correctly. Audit: today only `actions/analysis.py` declares it; `render` and
  `automation` write to disk but are Live-driving (OSC/LOM) and correctly *not*
  server-side. Confirm no handler that should be `runs_server_side` is missing the
  flag before keying exclusion off it.
- **`actions/` granularity.** `actions/` is fingerprinted wholesale; if the action
  spec is not relocated with the handler, a change to `actions/analysis.py`'s param
  schema still flips the version. Acceptable interim (param specs are low-churn);
  full correctness relocates the spec too.

## Related
- **INS-3W8P** (shipped) — server/info + `--require-server-version`; this design
  preserves all of it.
- **INS-4H8M** — fingerprint the `HallucinoteAnalyzer.amxd`. Same guiding
  principle ("fingerprint only what crosses the boundary that matters"), but the
  `.amxd` *does* run in Live (M4L), so its separate raw-byte fingerprint is
  legitimate — distinct mechanism, shared philosophy. Couple the framing, not the
  code.
- **MCP-4T6Y** — listed related on the backlog item; reconcile when that item is
  picked.
