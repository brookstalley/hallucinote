---
artifact: security-model
version: 1
depends_on:
  - artifact: architecture
last_validated: 2026-08-06
---

# Security Model

The user-facing policy — how to report, what's in and out of scope — is
[`SECURITY.md`](../../SECURITY.md) at the repo root, which is the document people
actually read. This artifact records the trust decisions behind it.

## Threat model in one line

A **single-user, single-machine authoring tool** with no network service, no
multi-tenancy, no authentication, and no stored credentials. The realistic threat is
not a remote attacker; it is **untrusted content the user chose to run**.

## The one real trust boundary: a song is a program

A song's composition is Python (`build.py`) that the engine imports and executes.
Building a song you cloned from someone else runs their code with your privileges.

This is accepted, not mitigated. The executable composition is the feature — it is what
makes a song forkable, diffable, and reproducible, and sandboxing it away would remove
the product's reason to exist. The mitigation is **disclosure**: `SECURITY.md` states it
plainly and tells users to review a `build.py` as they would any program.

The line that *is* defended: **parsing must never be executing.** A song's data files —
`captured_session.json`, WAVs, analysis JSON — must not achieve code execution without
someone running `build.py`. A path from data to execution is a genuine vulnerability.

## Local surfaces, deliberately trusted

- **The loopback socket** (`127.0.0.1:9878`) is unauthenticated. Any local process can
  connect. Accepted: an attacker with local code execution has already won, and Live
  offers no authentication primitive to build on. Binding beyond loopback is outside
  the supported configuration.
- **The Remote Script** runs inside Live with Live's privileges, installed into Live's
  User Library by our own installer. In scope: the installer writing *outside* that
  directory (a traversal in the vendoring step). Out of scope: the fact that it writes
  into your own Live install.
- **`ableton_probe`** can mutate live state by design. Its exposure is bounded by a
  constrained path grammar (`song`/`application` roots, `.attr`/`[index]` steps only,
  regex-tokenized, anything outside rejected before evaluation) — that grammar is a
  correctness guard against agent mistakes, not an adversarial sandbox.

## Data handling

No PII, no credentials, no financial or health data, no telemetry, no outbound network
calls of our own. `handles_sensitive_data` is recorded as null in `project-state.yaml`
and that remains accurate.

The one privacy leak worth naming: a song's database and captures embed **absolute
filesystem paths** from the authoring machine. They are gitignored by default
(`hallucinote init-workspace` sets that up); a user who commits them anyway is
publishing their directory layout.

## Supply chain

Dependencies are locked (`uv.lock`) and CI gates `uv lock --check`, so a stale lockfile
cannot ship silently. The plugin builds its environment from that lockfile with
`uv run --frozen`.

## Direction

Ratified 2026-08-10. These bind future work; the narrative above describes it.

- **Parsing must never be executing.** A song's data files — `captured_session.json`,
  WAVs, analysis JSON — must not achieve code execution without someone running
  `build.py`.
  Why: executing `build.py` is the *one* trust boundary this product accepts, and it is
  accepted only because the user opts into it knowingly (see the disclosure norm below).
  A path from data to execution collects that trust without the opt-in, which makes it a
  genuine vulnerability rather than a design tradeoff — it is the single line whose breach
  turns an accepted risk into an unaccepted one.

- **The executable composition is accepted, not mitigated; the mitigation is disclosure.**
  Why: a song being a Python program is what makes it forkable, diffable and
  reproducible — sandboxing it away would remove the product's reason to exist. So the
  rail is `SECURITY.md` stating it plainly and telling users to review a `build.py` as
  they would any program. Proposals to sandbox composition are a product-identity change,
  not a hardening task.

- **The loopback socket is unauthenticated by decision; binding beyond loopback is outside
  the supported configuration.**
  Why: an attacker with local code execution has already won, and Live offers no
  authentication primitive to build on — so authentication here would buy nothing and cost
  every call. The norm is the *scope*: the moment the socket leaves `127.0.0.1` the threat
  model above stops holding, and that is a new security model, not a config flag.

- **Dependencies are locked and CI gates `uv lock --check`.**
  Why: a stale lockfile is the one supply-chain failure this project can actually suffer,
  and it fails silently — the gate is what converts it into a red build. The plugin builds
  from that lockfile with `uv run --frozen` so the shipped environment is the reviewed one.
