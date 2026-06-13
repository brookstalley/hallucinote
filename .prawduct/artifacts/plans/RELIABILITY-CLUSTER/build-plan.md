# Build Plan — Song Round-Trip Reliability Cluster

**Branch:** `fix/song-roundtrip-reliability` (off `develop`)
**Critic mode:** cumulative (one roll-up at the end — project rule for waves of small/ready chunks, `feedback_critic_cadence_for_small_chunks`)
**Theme:** Close the framework gaps on the *working-song critical path* — scaffold →
pick → compose → push → mix → bake. Every chunk traces to a real **swell dogfood**
report and is already `stage: ready` in the backlog with a documented verifiable signal,
so requirements precede code (no invented scope).

## Confidence Check
- **Problem:** A first-class song can't reliably round-trip today — the swell dogfood hit
  a wall of push/compose/bake friction + correctness bugs (silently-dropped dialed params,
  re-push halts, partial pushes, instrument-less routing failure).
- **Success:** Each item's backlog "verifiable signal" is met, full suite green, cumulative
  Critic blocking-free, merged to develop.
- **Out of scope:** Live operator-verification items (SNP-8R4K verify, SDC-7K3M pull-capture),
  MCP async-render (MCP-4T6Y, `stage: design`, touches the fingerprint), and the BAK-3M9T
  umbrella (`stage: requirements`). These need a live set or a requirements pass.

## Chunks

- [x] **1 · RTE-2P9X** — Push `routing` phase now runs AFTER `devices`, so an instrument-bearing
  MIDI track has audio output before routing resolves to an audio submaster bus (PRE-MAIN).
  Adopted the parallel agent's stash (`_PHASE_NAMES` + `plan_push_song` reorder + docstrings +
  order tests + 3 docs), **completed the surfaces it missed** (`skills/ableton-push/SKILL.md`
  frontmatter; `test_push_cli.py` ×2 positional order asserts), and **closed the parity-guard
  gap** (added SKILL.md to `_ENUMERATING_DOCS`). Tree-wide sweep clean; 198 affected tests pass.
  *Signal:* phase order is `mix < devices < routing`; no fresh-push routing halt for an
  instrument-bearing MIDI track.

- [ ] **2 · SKL-8N3V** — `/song-new` postlude says call `ensure_loaded` with no params (the
  `song_slug` reading errors unknown-param). Skill text + a parity assertion if one exists.
  *Signal:* the skill shows the no-params call.

- [ ] **3 · INV-3K8W** — `preset_query` teaching errors point AT the fix: a pattern containing
  `/` teaches name-only matching + `path_prefix`; `path_prefix[0] == root` is detected and
  named. *Signal:* both error strings name the correct call shape.

- [ ] **4 · SYN-6B4Q** — cues planner skips-with-warning cues beyond the current arrangement
  extent (idempotently placed on a later push once the arrangement grows); hard-errors only
  past the composed song length. *Signal:* a skeleton push with out-of-extent cues completes
  (warned); a later push places them.

- [ ] **5 · SYN-5C3J** — `push_cli --pin <version>` (or env knob) runs a push under a pinned
  engine version for the editable-install + parallel-engine-dev mismatch lockout; error-recovery
  guide documents it. *Signal:* `--pin` runs a pinned push; the guide documents the recovery.

- [ ] **6 · SYN-9F2L** *(keystone, impact L)* — push devices planner applies `params_dialed`
  by preferring the display `value` string (inverted via the param display curve), handles
  center-zero `normalized`, and **WARNS whenever a dialed write is skipped** (the silent drop is
  the bug). *Signal:* a snapshot-authored device's dialed value lands after push; any skip warns.

- [ ] **7 · DPP-7H2K** — (a) non-monotonic params settable by explicit-unit display string
  (`'150 Hz'`, `'120 ms'`) via unit-keyed parsing; (b) `set_parameter` echoes a
  sub-display-precision real-unit value; (c) doc fix — bare track-name in `set_sidechain` /
  `set_input_routing` examples. *Signal:* each sub-signal in the backlog entry.

- [ ] **8 · SYN-3C8K** — `probe-and-link` reconciliation cascades stale **clip**-link drops (and/or
  the clips planner verifies slot non-emptiness against the probe before downgrading to
  replace-only); `default_scaffold_unmatched_tracks` classifies on session reuse, not only on
  fresh `auto_session_created`. *Signal:* re-push across a set-swap completes the clips phase;
  scaffold classification populated on reuse.

## Context
Chunk 1 done. Next: chunk 2 (SKL-8N3V).
