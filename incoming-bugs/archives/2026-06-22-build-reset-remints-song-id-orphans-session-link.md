# Bug: `build.py --reset` re-mints the song_id and orphans the Ableton session/link (contradicts its docstring)

**Type:** bug (or, at minimum, a docstring that lies).
**Severity:** M. Recoverable (`--auto-session` re-links), but it silently breaks the
documented contract and, on a fresh default-scaffold set, would resurface the
index-mislink failure mode the `--auto-session` discipline exists to avoid.

**Engine / server:** `0.1.0+4372b6734f8d`. Song `alien`.

> **⚠️ COULD NOT REPRODUCE on `0.1.0+2f9d648a60aa` (2026-06-22, later same day).**
> Ran `python songs/alien/build.py --reset` on the newer engine: the song_id stayed
> **`38842238afb1…` (stable, NOT re-minted)**, and the preserved projection survived —
> `ableton_sessions` still held session `442044…` keyed to that song_id with all 128
> `ableton_links` rows intact, and `verify-arrangement` / `pull … clip-notes`
> auto-selected the session and read Live with **no** re-bootstrap. That's exactly the
> behaviour preferred fix #1 (idempotent song identity by stable key) would produce, so
> it looks like #1 (or equivalent) **landed between `4372b6734f8d` and `2f9d648a60aa`.**
> Action for triage: confirm the fix is intentional, then (a) close this, and (b) make
> the docstring's "preserves the Ableton projection across `--reset`" promise *true on
> the record* (it now appears to be). Worth a regression test that asserts song_id
> stability + link survival across `--reset`. NOTE: not yet verified on a **fresh
> default-scaffold** set (`1-MIDI`, …) — the original `--auto-session` hazard only bit
> there, so re-check that case before fully closing.

## The contract (what the docstring promises)

`build()` in a song's `build.py` (and the SKILL/skills docs) say `--reset` is a SOFT
reset that "wipes build.py-authored content (clips, notes, arrangement, sections,
tempo/meter maps, cue points, envelopes) but preserves the mix layout (tracks, returns,
devices, sends) AND the Ableton projection (`ableton_sessions` + `ableton_links`)."

So after `--reset` you should be able to reuse the existing session and push.

## What actually happens

```
# before: .last-push-state.json → song_id 9d32472388…, session 3d6bd4d7e9…
$ python songs/alien/build.py --reset
  song_id=38842238afb1…      # ← NEW song_id, not the prior one
$ hallucinote push probe-and-link --song alien --probe
  push_cli probe-and-link: no session_id given and this DB has no sessions —
  bootstrap one with `--auto-session` …      # ← projection is GONE for the new song
```

`replay_capture(...)` minted a **new** song row (fresh UUID) instead of reusing the
existing "alien" song, so the preserved `ableton_sessions` / `ableton_links` (keyed to
the OLD song_id) are orphaned and invisible to the new song. The "preserves the Ableton
projection" promise doesn't hold across a `--reset`.

## Why it matters

- The documented "rebuild, then reuse the session and push" loop fails at probe-and-link
  with a confusing "no sessions" error.
- Recovery is `probe-and-link --auto-session`, which re-mints a session and re-links by
  NAME. On `alien` that linked cleanly (the live set has real track names). **But** on a
  fresh default-scaffold set (`1-MIDI`, `2-MIDI`, …) the by-name match can't
  disambiguate, and you're back in the index-mislink hazard that motivated the
  "fresh-set push → use `--auto-session`, never the reused session" rule. The docstring
  telling people the link survives a `--reset` actively steers them wrong.

## Root cause (suspected) + fixes

Either:
1. **`replay_capture` should be idempotent on song identity** — find-or-create the song
   by stable key (slug/name) so the song_id is stable across rebuilds; then the
   preserved sessions/links remain valid and the docstring becomes true. (Preferred.)
2. **Or the soft-reset should re-point the preserved `ableton_sessions`/`ableton_links`
   at the new song_id** as part of the reset.
3. **At minimum, fix the docstring + SKILL docs** to say `--reset` drops the projection
   and you must re-bootstrap with `--auto-session` — and have probe-and-link's "no
   sessions" error mention that `--reset` is the likely cause.

## Repro

1. Push a song so it has a session + links.
2. `python songs/<slug>/build.py --reset`.
3. `hallucinote push probe-and-link --song <slug> --probe` → "this DB has no sessions".
4. Note the song_id printed by step 2 differs from the pre-reset song_id.
