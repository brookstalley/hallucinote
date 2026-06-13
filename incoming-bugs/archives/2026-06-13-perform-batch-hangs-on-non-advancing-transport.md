# `performed_automation` (`perform_batch`) hangs indefinitely when the transport won't advance

**Severity:** M — a hung perform blocks the rest of the push (`arrangement`, `cues`
never run) AND blocks recovery: you can't tell it's hung vs. legitimately playing
the ~8-11 min span, and the only way out is `kill -9`, which leaves more dirty
state. Surfaced dogfooding the swell push, 2026-06-13.

**Repro / observed.**
1. A push reached `performed_automation` and was playing the master-swell span;
   the user manually **stopped the transport** mid-record. The `execute` process
   wedged (had to `kill`).
2. On the **next** `execute`, the perform phase **never advanced** — the transport
   stayed frozen at a fixed position while `perform_batch` waited. The process sat
   `STAT=S`, **0.0% CPU**, for 4.5 min with the output buffer empty; no timeout, no
   error, no progress. Diagnosis: `perform_batch` issued the play + recorded-span
   wait, but the transport never moved (residual state from the interrupted prior
   perform), so the call blocked forever. `kill -9` was the only exit.

**The robustness gap.** `perform_batch` assumes the transport will traverse the
span and return; it has **no watchdog** for "transport position hasn't advanced in
N seconds" and **no upper bound** ("span is M beats ≈ T seconds at tempo; if we're
still here at, say, 1.5×T, abort"). So any condition that stops the transport
advancing — a user stop, a modal dialog, residual state from a prior interrupted
perform — turns into an indefinite hang instead of a clean, teaching failure.

**Proposed fix.**
- **Watchdog:** poll `song.current_song_time` during the record wait; if it hasn't
  advanced for N seconds (and `is_playing` is false / unexpectedly stopped), abort
  the phase with a structured error ("transport stopped advancing at beat X of the
  Y-beat span — perform aborted; check for a manual stop / modal dialog / restart
  Live to clear residual transport state").
- **Hard ceiling:** derive the expected wall-clock from span-beats / tempo and
  abort at a multiple of it.
- **Pre-perform reset:** before playing, force a known-clean transport state (stop
  + reposition to span start; clear loop/punch) so a prior interrupted perform
  can't poison the next one. (Would have prevented step 2 entirely.)
- Pairs naturally with the mid-run progress gap (separate filing): even a single
  "perform: beat X/Y" heartbeat would have made the hang obvious in seconds.

**Verifiable signal.** Stopping the transport mid-perform (or starting a perform
with a wedged transport) ends in a structured abort within seconds-to-watchdog,
not an indefinite 0%-CPU hang; `arrangement`/`cues` either run (clean retry) or the
failure names the cause. **Related:** the push mid-run observability gap and the
phase-targeted-execute request (a `--start-at performed_automation` retry would
make recovery one command) — both filed 2026-06-13.
