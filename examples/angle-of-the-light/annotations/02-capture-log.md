---
kind: annotation
scope: song
date: 2026-08-06
tags: [tour, capture, evidence, provenance]
---

# Capture log

This song is two deliverables at once: a piece of music, and the documentary
record of it being written. The second one has a property the first does not —
**most of it cannot be re-shot**. A finished song can be photographed at leisure;
a session view half-populated, an arrangement three sections long, or a mix
before its problem was fixed exist only while they are true.

So capture runs *alongside* composition, not after it.

## The source transcript — the one artifact that happens exactly once

```
~/.claude/projects/-Users-brookstalley-source-hallucinote/
    9bb2fc6d-5f46-4207-8ff5-20d37682b874.jsonl
```

Recorded here because the harness writes it automatically and continuously, but
**nothing else points at it**. A `/clear` keeps the file and loses the pointer,
and the session that authored this song is not reproducible. Render it with
`python tools/tour_transcript.py --session <path>`; the redaction gate fails
closed, so choosing what to render is an editorial act, not a mechanical one.

Session started from a `/clear` on `feat/tour-walkthrough`; the brief arrives a
few turns in, preserved verbatim in
[`01-the-brief.md`](01-the-brief.md).

**The transcript spans more than one session file** — but not for the reason
first written here, and the correction is worth keeping. The original note
predicted that fixing the MCP attachment (the `hallucinote` plugin was neither a
marketplace plugin nor dev-loaded, so nothing declared the `hallucinote-mcp`
server) would fork the transcript, because relaunching with `--plugin-dir`
starts a new process. **It did not.** The relaunch resumed into the same JSONL,
so `9bb2fc6d` holds the brief *and* the entire composition, Live calls included
— verifiable by counting `hallucinote-mcp__ableton` occurrences in it.

The splits that actually happen are ordinary ones: a `/clear`, or quitting the
host application. Which means the rule for D1 is simpler than the original note
implied — **do not reason about where a beat lives, grep for it.** Each row below
is recorded from the file's observed content, never from a prediction about
where the work was going to land.

Record each new session's path in this list as it starts:

| Session JSONL | Holds |
|---|---|
| `9bb2fc6d-5f46-4207-8ff5-20d37682b874` | Beat 1 — the brief, the proposal, the meter decision. **Also all of beats 2–7**: the composition, and the push to Live (115 Ableton calls). |
| `d29313eb-6e93-44a2-8bb5-3da229b4602d` | No beat. Orientation after a `/clear`; discovered Screen Recording was never granted to the host app, which is why capture had produced nothing. Ends at the restart that grants it. |
| `5b429604-02ba-493e-9794-fb0db07011fd` | No beat. The restart worked — capture produced its first real PNG. But the same restart dropped `--plugin-dir`, so no `hallucinote-mcp` server was attached and the push could not run. Ends at a second relaunch. |
| _(next)_ | Beats 8–9 — the mix conversation and the iterate A/B, neither of which has happened yet |

Two consecutive no-beat sessions is itself worth a line in the walkthrough, if D1
wants it: the environment cost two restarts before a single note could be heard,
and neither restart was the composition's fault. That is the ordinary texture of
this work, and the tour's premise is that it does not get sanded off.

## Capture liberally, commit selectively

These are different budgets and conflating them breaks the design.

**Capture** is unbounded and untracked. Working shots and mixes go to
`examples/angle-of-the-light/_capture/` (git-ignored). Shoot anything that might
matter; disk is cheap and the moment is not.

**Commit** is capped hard by the design's evidence budget — 4 screenshots · 1
hero · 3 audio clips, at most 12 files, ≤12 MB total, enforced by a test at D1.
The cap is the thesis of the whole document (concision), so the test does not get
relaxed to admit extras. Every committed asset is produced by `tools/`, never by
hand, so a re-shoot is a re-run.

The narrowing from many to twelve is a curation pass, and it happens at C1 with
everything already in hand. That is strictly better than shooting to a budget
from the start, because it lets the *finished* story choose its own evidence.

## Amendment to the build plan's C1

C1 as written says: *"spend the evidence budget, exactly once, against the
finished song."* That is now known to be partly wrong, and it is recorded here
rather than silently worked around.

Three of the ten beats want an artifact that stops being true once the song is
done:

| Beat | Artifact | Why it cannot wait for C1 |
|---|---|---|
| 7 Materialize | Session view *filling in* | A finished set is full. "Filling in" is a state, not a view. |
| 6 Arrangement | The arrangement growing | The whole-form shot works at the end; the *becoming* does not. |
| 8 Production & mix | The mix **before** the fix | Beat 8 is a kick/bass collision and the producer question it raised. Once fixed, the evidence of the problem is gone. |
| 9 Iterate | The A/B pair | The "before" is by definition a discarded state. It must be rendered while it exists. |

C1 keeps its role as the **curation and budget-enforcement** pass — it still
spends the cap exactly once, and every committed asset still comes from the
tools. What changes is that some of its raw material is acquired earlier. C1 no
longer assumes the finished set is the only possible subject.

## The process must be tellable, which means it must be minimal

The owner's framing: *"show the whole creative process, from prompt to song to
refinement to production, in a minimum number of steps."*

This is a constraint on **how the song is composed**, not only on how the document
is written, and the reason is the transcript. The session log is the record. If
the song is built in forty small corrections, the log honestly contains forty
steps — and no editing at D1 turns that into four without *staging* it, which
breaks the premise that everything in the tour actually happened.

So compose in deliberate, large, named moves. Each move should be a step someone
would recognize as a step: "lay the harmonic spine", "write the call and its
inverted answer", "put the feel arc in", "fix the kick/bass collision". Fewer,
bigger, each with a reason — which is also how the `decisions/` records want to be
written, so the two obligations pull the same direction.

The four-act spine the document has to carry:

| Act | Beats | The one thing it proves |
|---|---|---|
| **Prompt** | 1 | The brief was answered, not auto-decided |
| **Song** | 2 – 6 | Harmony, feel, melody, form — authored as code |
| **Production** | 7 – 8 | It lands in Live, and the agent has an ear |
| **Refinement** | 9 | One change, heard. The money shot. |

Beats 3–6 are the compression risk: four beats inside one act, each showing a
different *capability*. Grouped by capability they read as a feature tour; grouped
by process they are one continuous act of writing. D1 owns that framing, but B1
owns whether the underlying work supports it.

**One corollary worth stating, because it cuts against the instinct to polish:**
refinement is an *act*, so it needs at least one real, visible before-and-after —
but only one or two. A song that visibly took twenty refinement passes tells a
worse story than one that took two good ones, even if the twenty produce a
marginally better mix.

## Standing obligations while composing

- **Render a full mix at each section milestone**, not just at the end. Beat 9's
  A/B is an intermediate pair by construction; the others give the story its arc.
- **Screenshot before fixing anything interesting.** The bug is the evidence.
- **Never stage a shot.** If an artifact would have to be manufactured to look
  right, it does not go in the tour. The premise of the document is that all of
  it happened.
