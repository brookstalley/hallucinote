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

## Triage finding (2026-06-13)
Verifying each `ready` item against real code (the project's "verify the proposed fix
against the real code before building" learning) revealed that **CLR-A (#160) already
landed four of them** — INV-3K8W, SYN-6B4Q, SYN-9F2L, SKL-8N3V (doc-half) — but left
them `open` in the backlog (BLG-7K2Q drift). The genuine remaining build collapses to
**DPP-7H2K + SYN-3C8K**, plus the `--pin` knob half of SYN-5C3J. RTE-2P9X was completed
from the parallel agent's stash. This is quality-over-breadth: deep work on the two
truly-unbuilt items.

## Chunks

- [x] **1 · RTE-2P9X** — Push `routing` phase now runs AFTER `devices`, so an instrument-bearing
  MIDI track has audio output before routing resolves to an audio submaster bus (PRE-MAIN).
  Adopted the parallel agent's stash (`_PHASE_NAMES` + `plan_push_song` reorder + docstrings +
  order tests + 3 docs), **completed the surfaces it missed** (`skills/ableton-push/SKILL.md`
  frontmatter; `test_push_cli.py` ×2 positional order asserts), and **closed the parity-guard
  gap** (added SKILL.md to `_ENUMERATING_DOCS`). Tree-wide sweep clean; 198 affected tests pass.
  *Signal:* phase order is `mix < devices < routing`; no fresh-push routing halt for an
  instrument-bearing MIDI track.

- [x] **2 · SKL-8N3V** — `/song-new` postlude says call `ensure_loaded` with no params (the
  `song_slug` reading errors unknown-param). Skill text + a parity assertion if one exists.
  *Signal:* the skill shows the no-params call.

- [x] **3 · INV-3K8W** — already done + tested in CLR-A (#160), both branches. No code; close backlog. — `preset_query` teaching errors point AT the fix: a pattern containing
  `/` teaches name-only matching + `path_prefix`; `path_prefix[0] == root` is detected and
  named. *Signal:* both error strings name the correct call shape.

- [x] **4 · SYN-6B4Q** — already done in CLR-A (#160): extent-partition cue planner + benign deferred-cue warnings. No code; close backlog. — cues planner skips-with-warning cues beyond the current arrangement
  extent (idempotently placed on a later push once the arrangement grows); hard-errors only
  past the composed song length. *Signal:* a skeleton push with out-of-extent cues completes
  (warned); a later push places them.

- [ ] **5 · SYN-5C3J** — `push_cli --pin <version>` (or env knob) runs a push under a pinned
  engine version for the editable-install + parallel-engine-dev mismatch lockout; error-recovery
  guide documents it. *Signal:* `--pin` runs a pinned push; the guide documents the recovery.

- [x] **6 · SYN-9F2L** *(keystone, impact L)* — already done in CLR-A (#160): devices planner picks wire form per param (display→value_display, normalized-only→raw value, neither→warn-never-drop), center-zero-safe, with `test_plan_push_devices_warns_for_unwritable_params` + display-preferred tests. No code; close backlog. — push devices planner applies `params_dialed`
  by preferring the display `value` string (inverted via the param display curve), handles
  center-zero `normalized`, and **WARNS whenever a dialed write is skipped** (the silent drop is
  the bug). *Signal:* a snapshot-authored device's dialed value lands after push; any skip warns.

- [x] **7 · DPP-7H2K** — DONE this session. (a) `canonical_magnitude` normalizes unit-scaling families (Hz/kHz, ms/s) so non-monotonic displays resolve via `value_display='150 Hz'`/`'120 ms'` instead of refusing (strict generalization — single-unit params unchanged, genuinely-non-monotonic still refuse). (b) `value_real`/`value_real_unit` echoed on a recognised-unit `value_display` write (shared `_attach_real_unit_echo` across both set_parameter sites). (c) bare track-name routing examples (NOT index-prefixed `1-Drums`) in action help + handler docstring + mix-sidechain skill. **Flips the MCP fingerprint** (touches `handlers/`+`actions/`) → re-vendor + `/mcp` reconnect needed to go live. 1196 MCP tests green. — (a) non-monotonic params settable by explicit-unit display string
  (`'150 Hz'`, `'120 ms'`) via unit-keyed parsing; (b) `set_parameter` echoes a
  sub-display-precision real-unit value; (c) doc fix — bare track-name in `set_sidechain` /
  `set_input_routing` examples. *Signal:* each sub-signal in the backlog entry.

- [x] **8 · SYN-3C8K** — DONE this session. Reconciliation cascades stale clip-link drops (clip link dangles when its parent track link is dropped on a set-swap → clips-phase halt); classifier now populates `default_scaffold_unmatched_tracks` on session reuse, not only fresh auto-session (**decision: dropped the `auto_session_created` gate** — the canonical-name signature is the real discriminator; flipped `test_..._no_default_scaffold_when_not_auto_session` → `..._classified_on_session_reuse` to the corrected spec, per the SYN-3C8K dogfood requirement). Repurposed the nested-link boundary test to lock clip-only cascade. New field `unlinked_stale_clips` (auto-serialized via `asdict`); skill surfaces it + Case 1 relaxed. 822 sync tests green. — `probe-and-link` reconciliation cascades stale **clip**-link drops (and/or
  the clips planner verifies slot non-emptiness against the probe before downgrading to
  replace-only); `default_scaffold_unmatched_tracks` classifies on session reuse, not only on
  fresh `auto_session_created`. *Signal:* re-push across a set-swap completes the clips phase;
  scaffold classification populated on reuse.

## Context
Chunk 1 done. Next: chunk 2 (SKL-8N3V).
