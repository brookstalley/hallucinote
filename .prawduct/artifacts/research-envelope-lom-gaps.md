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

---

# Research note — does `Clip.envelope_for_note` exist? (#515)

**Dated 2026-09-10. Complete: both halves of the question are answered.**
This section closes the "settle before building" note on #515.

## The question

#515 records that `write_envelope(target_kind='note_expression')` fails every
call on Live 12.4.5 — `AttributeError: 'Clip' object has no attribute
'envelope_for_note'` — and states that the fix depends on an unanswered
question: **was `envelope_for_note` removed in some Live version, or did it
never exist?** A removed method invites a version gate or a successor API; a
method that never existed means the codebase is built on a fabricated call and
the only honest fix is to stop advertising it.

A second question is implied by the first and matters more for the fix: **does
Live's LOM expose per-note expression (MPE) at all, by any name?**

## Finding 1 — it never existed. Three independent probes agree

The probe already on record (`docs/research/audio-first-class/lom-probe-results.md`
row 30) is direct LOM introspection on one running build: the clip's members
were enumerated and nothing note-scoped was there. That establishes *absent on
12.4.5*; it cannot establish *never existed*. Three further probes, run
2026-09-10, do.

**Probe A — the shipped binary's symbol table.** Live's Python API names appear
verbatim as strings in the application binary. Recipe (re-runnable, and the
reason no count is pinned in prose here):

```sh
B="/Applications/Ableton Live 12 Suite.app/Contents/MacOS/Live"
for s in create_automation_envelope get_notes_extended apply_note_modifications \
         remove_notes_extended note_id release_velocity envelope_for_note; do
  printf "%-30s %s\n" "$s" "$(strings -a "$B" | grep -cx "$s")"
done
```

Every known `Clip` LOM method resolves; `envelope_for_note` resolves **zero
times**. This is a different instrument from introspection — it reads the
name table rather than a live object graph — and it agrees.

**Probe B — Cycling '74's published Live Object Model reference** (the Max 9
LOM PDF, which documents the Live 12 surface). Its `Clip` class lists
`clear_envelope` and `clear_all_envelopes` and no note-scoped envelope
accessor. **Read this one with its limit in view**: the same PDF also omits
`automation_envelope` / `create_automation_envelope`, which demonstrably work
(`_find_existing_envelope` is exercised against real Live 12.4). So absence
from the PDF is *not* proof of absence from the API, and this probe is
corroboration only — it is recorded here so the next reader does not mistake
it for the load-bearing one.

**Probe C — GitHub-wide code search**, which is the probe that answers the
*historical* question the other two cannot. If the method had ever shipped, the
Live-scripting community would have used it: AbletonOSC, LOM dumps, remote
scripts, M4L devices.

```sh
gh api -X GET search/code -f q='envelope_for_note' --jq '.total_count'
```

Against `create_automation_envelope` and `get_notes_extended` this search
returns results in the dozens-to-hundreds. Against `envelope_for_note` it
returns a handful, and inspection shows **none of them are Ableton-related**
(an unrelated Rust DSP crate and one agent's notes file). A real LOM method
does not leave zero trace across every public Ableton project.

**Conclusion: `Clip.envelope_for_note` is not a removed API. It never
existed.** It entered this codebase as an invented call and became load-bearing
in three places before anything executed it against Live.

## Finding 2 — there is no per-note expression surface in the LOM at all

This is the finding that decides the fix, and it is stronger than #515 assumed.
`note_expression` is not a target kind waiting on the right method name — Live
exposes **no** note-scoped envelope API under any spelling. Searching the full
Live 12 LOM reference for `MPE`, `per-note`, `pressure`, `timbre`, `slide` and
`note_expression` returns nothing; the same names probed against the binary's
symbol table (`note_expression`, `expression_envelope`, `note_envelope`,
`per_note_envelope`, `get_note_expression`, `mpe_enabled`) all resolve zero
times. Live's own MPE editing exists — the binary carries internal per-note
event-envelope machinery and an MPE clip view — but none of it is projected
into the Python API.

So the gap is structural, not a naming miss, and it is not the kind of gap a
future minor release is especially likely to close. Two consequences:

- **There is nothing to route to.** Unlike `clip_cc` (encodable as
  control-change notes) or `clip_pitch_bend` (a device-parameter ride), a
  *polyphonic* per-note bend has no substitute on this surface. The
  `device_parameter` perform route recorded in row 30b is monophonic by
  construction — one parameter, one voice — which is why #515's own comment is
  careful to call it a stopgap and not a fix.
- **`docs/dubler.md` rests on the same phantom.** Its plan probes
  `clip.envelope_for_note(...)` per note as its discovery pass, and its premise
  ("MPE maps cleanly to `note_expression`") is refuted here. That plan cannot
  be built as written and must be corrected alongside #515, or a future reader
  will re-derive this research from scratch.

## What this makes the fix

Not "find the right call" — **stop advertising a capability that does not
exist, and point every recovery path at the route that does.** The mechanism is
already in the file: `clip_cc` and `clip_pitch_bend` are gap-blocked at the
handler boundary with a `NotImplementedError` carrying a teaching message,
raised *before* any Live call. `note_expression` joins them; it is the same
pattern, not a new one.

The requirements and acceptance criteria derived from this note live on #515.

## Re-check trigger

This answer cannot change without a new Live release that adds a per-note
envelope API — and per the ENV-6P3R finding above, no 12.5 has been announced.
Re-run probes A and C at the next minor release, not before. Probe C is the one
that would move first: a newly-exposed API shows up in community code within
weeks.
