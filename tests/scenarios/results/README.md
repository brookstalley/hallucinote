# Scenario-eval results — retention policy

These are the recorded **judge verdicts** for the persona scenario briefs
(`../briefs/`) — the verification evidence for the onboarding & teaching flow,
which is *behaviorally judged*, not unit-testable (you can't assert transcript
text; an LLM judge scores the conversation against the brief's rubric). A result
JSON holds `brief_id` + `verdict` (pass/fail) + `summary` + per-rubric-line
`rubric_findings` (it does **not** embed the transcript).

## What's tracked vs. ignored

| File | Tracked? | What it is |
|---|---|---|
| `canonical-<brief>.json` | ✅ committed | the **pinned latest-passing** verdict per brief — the durable evidence + the expected-behavior reference. A reviewable diff when a rubric *intentionally* changes. |
| `canonical-<brief>.transcript.md` | ✅ committed (when saved) | the latest run's **transcript**, so a human or LLM can read what the agent actually did — to tune the judge, sanity-check, or out of curiosity. |
| `<brief>-<UTC-timestamp>.json` (+ `.transcript.md`) | ❌ gitignored | ad-hoc runs. LLM role-play + LLM judge are **non-deterministic**, so committing every run is churn, not signal — they're ephemeral working material. |

The rule lives in the repo-root `.gitignore` (ignore `results/*`, allowlist
`canonical-*`, `README.md`, `.gitkeep`).

**Why not gitignore everything?** Because these are the *only* in-repo proof the
behavioral gate was exercised and passed — fully ignoring them would leave a
non-unit-testable feature with no verification record. So we pin the latest, drop
the accumulation.

## How to canonicalize a run

The harness writes ad-hoc runs by default (timestamped, gitignored). To promote a
passing run to the committed canonical:

```python
from tools.scenario_eval import write_result, load_brief
write_result(judge_result, load_brief(briefs_dir / "priya.json"), canonical=True)
# -> tests/scenarios/results/canonical-priya.json  (stable name, overwrites)
```

Save the run's transcript alongside as `canonical-<brief>.transcript.md` so the
latest conversation stays reviewable. Commit both.

## Staleness note (EVL-9R3T)

`canonical-priya.json` and `canonical-elena.json` predate the melody-rubric change
(MEL-1A7K phase 2a split authoring vs. line-analysis). They are the last *actual*
runs but were judged against the older rubric — a fresh eval pass re-grades them
against the updated briefs. Tracked as backlog **EVL-9R3T**.
