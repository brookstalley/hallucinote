# Scenario-eval harness — behavioral regression for the onboarding & teaching model

Most of the onboarding & teaching work (`onboarding-and-teaching-model.md`) is
agent **behavior**, not unit-testable logic: the install-tail handoff, the
elicitation flow, the Capability Truth, the CLAUDE.md norms. We verify it with
**scenario briefs**, not scripted transcripts. The conversation must *float* —
the agent asks slightly different questions each run — so string-matching lines
is brittle. A brief goes up one level of abstraction: it is run-instructions for
a *simulated user* paired with a *behavioral rubric* the resulting transcript is
judged against.

Two layers:

- **Deterministic substrate** — `tools/scenario_eval.py` (brief schema + loader,
  prompt rendering, judge-result schema + recorder). Unit-tested in
  `tests/unit/tools/test_scenario_eval.py`.
- **The LLM steps** — role-play the persona, judge the transcript. These are the
  *ad hoc* part: spawned as subagents per the procedure below. There is no CI
  automation and no API-calling harness (out of scope for C0).

## Layout

```
tests/scenarios/
  README.md          # this file — schema + runner procedure
  briefs/*.json      # one brief per persona (id == filename stem)
  results/           # judge results accumulate here (one file per run)
```

## Brief schema

A brief is a JSON object with four content parts plus an id and optional tags.
Format is **JSON** (not YAML) because JSON is the project's serialization
standard, is stdlib-loadable and trivially schema-validatable, and a rubric
expressed as arrays of lines maps exactly onto the per-rubric-line rationale the
judge must emit.

| Field | Type | Notes |
|---|---|---|
| `id` | string | Lowercase slug; **must equal the filename stem**. |
| `persona` | string | Who they are (1–2 lines from the walkthrough). |
| `goal` | string | What they sat down to make. |
| `response_character` | string | *How* they respond, not *what*: vocabulary, what they know and don't, what they'd push back on, when they'd defer. The simulated user improvises in character from this. |
| `rubric.must` | string[] | Non-empty. Each line: one thing the agent **must** do. |
| `rubric.must_not` | string[] | May be empty. Each line: one thing the agent **must not** do. |
| `tags` | string[] | Optional. Maps the brief to the build-plan chunk(s) it gates, e.g. `["C2", "third-register"]`. |

The six briefs (`maya`, `dev`, `elena`, `theo`, `priya`, `sam`) are the personas
from the design doc's persona walkthrough.

## Judge-result schema

The judge emits a JSON object validated by `validate_result`:

| Field | Type | Notes |
|---|---|---|
| `brief_id` | string | Must equal the brief's id. |
| `verdict` | `"pass"` / `"fail"` | Must be **consistent** with findings: pass iff every line is satisfied. |
| `summary` | string | One-paragraph rationale. |
| `rubric_findings` | object[] | **Exactly one per rubric line, same order** (must then must_not). Each: `{kind, item, satisfied: bool, rationale}`. `item`/`kind` must match the rubric line verbatim. |
| `timestamp` | string | Stamped by `write_result` if absent (UTC ISO-8601). |

`satisfied` semantics: for a `must` line, `true` = the agent did it; for a
`must_not` line, `true` = the agent **avoided** it. The validator rejects
incomplete coverage, invented lines, and a verdict that disagrees with the
findings — that is what gives "per-rubric-line rationale" teeth.

## Runner procedure (ad hoc, per scenario)

Run from the repo root. The deterministic helpers render the prompts; the agent
spawns the two subagents and records the result.

1. **Pick a brief**: `python -m tools.scenario_eval list` then
   `python -m tools.scenario_eval show <id>`.
2. **Render the persona prompt**:
   `python -m tools.scenario_eval persona-prompt <id>`. Spawn a **persona
   subagent** with that as its instructions. It role-plays the user; it is *not*
   shown the rubric (so it can't lead the witness).
3. **Run the conversation**: a second agent plays the Hallucinote agent
   (the system under test) and converses with the persona subagent. Capture the
   full transcript to a file.
4. **Render the judge prompt**:
   `python -m tools.scenario_eval judge-prompt <id> --transcript transcript.txt`.
   Spawn a **judge subagent** with that prompt. It returns a JSON result.
5. **Record it**: write the judge's JSON through `write_result` (which validates
   + timestamps + names the file `<id>-<UTC>.json` under `results/`), or save it
   and check it with
   `python -m tools.scenario_eval validate-result results/<file>.json`.

A behavioral chunk (C1–C4) is "done" only when its gating briefs pass under this
harness, with the judge rationale recorded. The two known judgment risks —
reading the open→proposal transition and proposal pacing — have no mechanism;
these rubrics are how they are policed, and persistent misfires become learnings.
