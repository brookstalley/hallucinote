# `push_cli execute` gives zero mid-run progress — opaque for minutes (worst during the realtime perform)

**Severity:** M — a full push can run 8–11+ min (the `performed_automation`
phase plays the whole arrangement in realtime), and for that entire time there is
**no progress signal whatsoever**. The operator (or driving agent) cannot tell
which phase it's in, whether routing cleared, whether it's hung, or how far the
perform has progressed. Surfaced dogfooding the swell push (2026-06-13).

**Observed — all three candidate channels are silent until exit:**
1. **stdout + stderr**: the per-phase summary (`[ok] tracks 23/23`, the halt-cause
   block, etc.) is printed **only at the end**. Mid-run the captured output file is
   **0 bytes** (verified while the process was live).
2. **`.last-push-state.json`**: written **only at the end** of a run — during run 2
   it still held run 1's stale `outcome: partial` (mtime ~13 min old). Not flushed
   per-phase, so it can't be polled for progress.
3. **Live transport probe** (workaround attempt): during `performed_automation`
   the push issues a single long `perform_batch` MCP call that holds the bridge for
   the whole union span, so a concurrent `ableton_session(info)` probe just queues
   behind it — and risks perturbing the realtime gesture record. Not a usable
   progress source.

**Why it matters.** An 8–11 min operation with no heartbeat is indistinguishable
from a hang. The agent has to either block on the exit notification (learning
nothing until ~10 min in) or burn turns poking at empty files. The perform phase —
the longest and most opaque — is exactly where you most need "it's playing, ~60%
through the span, not stuck."

**Proposed fix (layered, cheapest first):**
1. **Flush `.last-push-state.json` after each phase**, not just at the end. The
   file is already the canonical progress artifact; per-phase flush makes it
   poll-able (`watch cat`, or an agent reading it between turns) for phase-level
   progress + which phase is current. Highest value / lowest cost.
2. **Stream per-phase lines to stderr** as phases start/finish (keep stdout as the
   final JSON for parsing): `[device_sidechain] 5/5 ok`, and crucially a START line
   for the long phase: `[performed_automation] performing union span 0–910 beats
   (~7m10s), transport playing…` so the operator knows the ETA up front.
3. **Intra-perform heartbeats** (deeper): the perform handler owns the transport,
   so it knows `current_song_time`; have it emit a heartbeat (current beat / % of
   span) every few seconds to a progress file or stderr, so the 10-min phase isn't
   a black box.

**Verifiable signal.** During a multi-minute push, a watcher can see the current
phase advance and, for the perform, a position/ETA — without parsing buffered
output or probing Live. Relates to the push observability surface (`.last-push-
state.json` / `.last-push-errors.json`).
