# Research note — clip pitch-bend / CC envelope targets and curve shapes (ENV-6P3R)

**Dated 2026-08-11. Partial: the version question is answered, the M4L-bridge
question is not.** Recorded so the next person does not re-run the half that is
now settled.

## The question

ENV-6P3R (issue #281) asks for a deliberate probe rather than standing
acceptance of two Live gaps the codebase already works around:

1. Live 12.4 does not expose `create_automation_envelope` for clip
   **pitch-bend / CC** targets — `handlers/clip.py` skips those with a
   teaching message.
2. All envelope curves render as **steps**; ENV-2M9K shipped a plan-time warn.

The item frames both as "Live's gaps, not ours", and asks whether **Live 12.5+**
closes either, and whether the **M4L bridge (DEV-9C4L)** can cover the residual.

## Finding 1 — there is no Live 12.5 to probe (verified, not recalled)

As of 2026-08-11 the newest released Ableton Live is **12.4, released
2026-05-05**. Public sources show 12.4.x maintenance betas (12.4.5 as of June
2026) and **no 12.5 announced or in beta**.

So the item is not blocked on access to a version — it is waiting on a release
that has not happened. Nothing about the two gaps can have changed, because the
LOM surface has not moved since the gaps were recorded.

**This is the standing answer until a 12.5 (or a 13) ships.** Re-check at the
next minor release, not before; the question cannot have a different answer in
between.

Sources (2026-08-11):
- <https://www.ableton.com/en/release-notes/live-12/> — Live 12 release notes
- <https://help.ableton.com/hc/en-us/articles/212040005-Live-Release-Notes> — Live release notes index
- <https://www.ableton.com/en/blog/live-12-4-is-coming/> — the 12.4 announcement
- <https://en.wikipedia.org/wiki/Ableton_Live> — version table

## Finding 2 — the M4L-bridge half is STILL OPEN

Not answered here, and deliberately not guessed at. Live 12.4 bundles **Max
9.1.4**, so a bridge is plausible in principle, but "can M4L write a clip
pitch-bend or CC envelope that Live persists, and can it author a non-step curve"
is a question about runtime behavior of a specific Max/Live version pair. It
needs a real probe in a running Live — the same class of evidence
`docs/` already demands elsewhere — and answering it from documentation would be
exactly the recalled-not-verified claim the research-first rule exists to stop.

**What would close it:** with Live 12.4 + Max 9.1.4 open, attempt (a) a clip
pitch-bend envelope and (b) a non-linear curve segment via M4L, and record what
persists after a save/reload cycle.

## Disposition

Item #281 stays **open** on Finding 2. Its scope is now smaller and its trigger
is explicit: the version half is settled and dated, so a future session
re-opening this should skip straight to the M4L probe.

Meanwhile the shipped workarounds stand and are correct: the clip pitch-bend /
CC skip carries its teaching message, and ENV-2M9K's plan-time warn tells the
author that curves will render as steps.
