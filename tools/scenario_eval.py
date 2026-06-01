"""Onboarding C0: the scenario-eval harness — testable core.

The onboarding & teaching work is agent *behavior* (the install-tail handoff,
the elicitation flow, the Capability Truth), not unit-testable logic. We verify
it with **scenario briefs**, not scripted transcripts: the conversation must
*float* (the agent asks slightly different questions each run), so string-
matching lines is brittle. A brief is run-instructions for a simulated user
paired with a behavioral rubric the (floating) transcript is judged against.

This module is the deterministic substrate — brief schema + loader, prompt
rendering, and the judge-result schema + recorder. The LLM steps (role-play the
persona, judge the transcript) are the ad hoc part, spawned as subagents per the
procedure in ``tests/scenarios/README.md``. Mirrors ``tools/scaffold_song.py``:
the testable core lives here; the skill/runner is an interactive wrapper.

Brief format is **JSON** (not YAML): JSON is the project's serialization
standard (PyYAML is deliberately absent), it is stdlib-loadable and trivially
schema-validatable, and a rubric expressed as arrays of lines maps exactly onto
the "per-rubric-line rationale" the judge must emit.

CLI::

    python -m tools.scenario_eval list
    python -m tools.scenario_eval show <id>
    python -m tools.scenario_eval persona-prompt <id>
    python -m tools.scenario_eval judge-prompt <id> --transcript path/to.txt
    python -m tools.scenario_eval validate-result path/to/result.json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Locations
# ---------------------------------------------------------------------------

# this file is tools/scenario_eval.py; parent=tools/, parent.parent=repo root.
_REPO_ROOT = Path(__file__).resolve().parent.parent
SCENARIOS_DIR = _REPO_ROOT / "tests" / "scenarios"
BRIEFS_DIR = SCENARIOS_DIR / "briefs"
RESULTS_DIR = SCENARIOS_DIR / "results"

ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
RUBRIC_KINDS = ("must", "must_not")


class ScenarioError(ValueError):
    """A brief or judge-result failed schema validation. Fails loud."""


# ---------------------------------------------------------------------------
# Brief schema
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Rubric:
    """What the agent **must** and **must not** do, judged over the transcript.

    Each entry is one discrete line the judge scores individually — this is the
    "per-rubric-line rationale" guarantee made structural.
    """

    must: tuple[str, ...]
    must_not: tuple[str, ...]

    def lines(self) -> list[tuple[str, str]]:
        """Flatten to ``(kind, text)`` pairs in a stable order: must, then must_not."""
        return [("must", t) for t in self.must] + [
            ("must_not", t) for t in self.must_not
        ]


@dataclass(frozen=True)
class Brief:
    """A scenario brief — run-instructions for a simulated user + a rubric.

    Four parts per the design doc (onboarding-and-teaching-model.md): persona,
    goal, response_character, rubric. ``tags`` are optional and map a brief to
    the build-plan chunk(s) it gates (e.g. ``["third-register", "C2"]``).
    """

    id: str
    persona: str
    goal: str
    response_character: str
    rubric: Rubric
    tags: tuple[str, ...] = ()


def _require_str(data: dict, key: str, where: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ScenarioError(f"{where}: '{key}' must be a non-empty string")
    return value


def _require_str_list(value: object, where: str, *, allow_empty: bool) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(x, str) or not x.strip() for x in value):
        raise ScenarioError(f"{where}: must be a list of non-empty strings")
    if not value and not allow_empty:
        raise ScenarioError(f"{where}: must not be empty")
    return tuple(value)


def parse_brief(data: dict, *, source: str = "<brief>") -> Brief:
    """Validate a decoded brief dict into a :class:`Brief`. Raises ScenarioError."""
    if not isinstance(data, dict):
        raise ScenarioError(f"{source}: brief must be a JSON object")

    brief_id = _require_str(data, "id", source)
    if not ID_RE.match(brief_id):
        raise ScenarioError(
            f"{source}: 'id' {brief_id!r} must match {ID_RE.pattern} "
            "(lowercase slug)"
        )

    rubric_raw = data.get("rubric")
    if not isinstance(rubric_raw, dict):
        raise ScenarioError(f"{source}: 'rubric' must be an object with 'must'/'must_not'")
    unknown_rubric = set(rubric_raw) - set(RUBRIC_KINDS)
    if unknown_rubric:
        raise ScenarioError(
            f"{source}: rubric has unknown keys {sorted(unknown_rubric)}; "
            f"allowed: {list(RUBRIC_KINDS)}"
        )
    rubric = Rubric(
        must=_require_str_list(rubric_raw.get("must", []), f"{source}: rubric.must", allow_empty=False),
        must_not=_require_str_list(rubric_raw.get("must_not", []), f"{source}: rubric.must_not", allow_empty=True),
    )

    tags_raw = data.get("tags", [])
    tags = _require_str_list(tags_raw, f"{source}: tags", allow_empty=True)

    known = {"id", "persona", "goal", "response_character", "rubric", "tags"}
    unknown = set(data) - known
    if unknown:
        raise ScenarioError(f"{source}: unknown top-level keys {sorted(unknown)}")

    return Brief(
        id=brief_id,
        persona=_require_str(data, "persona", source),
        goal=_require_str(data, "goal", source),
        response_character=_require_str(data, "response_character", source),
        rubric=rubric,
        tags=tags,
    )


def load_brief(path: Path) -> Brief:
    """Load and validate a single brief JSON file."""
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise ScenarioError(f"{path}: brief file not found") from exc
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ScenarioError(f"{path}: invalid JSON — {exc}") from exc
    brief = parse_brief(data, source=str(path))
    if brief.id != path.stem:
        raise ScenarioError(
            f"{path}: brief id {brief.id!r} must match filename stem {path.stem!r}"
        )
    return brief


def load_all_briefs(briefs_dir: Path = BRIEFS_DIR) -> list[Brief]:
    """Load every ``*.json`` brief in ``briefs_dir``, sorted by id."""
    briefs_dir = Path(briefs_dir)
    if not briefs_dir.is_dir():
        raise ScenarioError(f"{briefs_dir}: briefs directory not found")
    briefs = [load_brief(p) for p in sorted(briefs_dir.glob("*.json"))]
    seen: set[str] = set()
    for b in briefs:
        if b.id in seen:
            raise ScenarioError(f"duplicate brief id {b.id!r} in {briefs_dir}")
        seen.add(b.id)
    return briefs


# ---------------------------------------------------------------------------
# Prompt rendering — deterministic, so the LLM step stays thin
# ---------------------------------------------------------------------------


def render_persona_prompt(brief: Brief) -> str:
    """The system prompt for the persona subagent (role-plays the user).

    Deliberately withholds the rubric: the simulated user must not know what the
    agent is being graded on, or it will lead the witness.
    """
    return (
        "You are role-playing a Hallucinote *user* in a conversation with the "
        "Hallucinote agent. Stay fully in character; never break role, never "
        "reveal you are a simulation, and never grade the agent.\n\n"
        f"WHO YOU ARE\n{brief.persona}\n\n"
        f"WHAT YOU SAT DOWN TO MAKE\n{brief.goal}\n\n"
        f"HOW YOU RESPOND (character, not script)\n{brief.response_character}\n\n"
        "Improvise in character. Open with what you want to make, then react to "
        "what the agent says the way this persona would. Defer ('you decide') "
        "only where the character would genuinely have no answer. Keep turns "
        "short and natural, like a real chat."
    )


def render_judge_prompt(brief: Brief, transcript: str) -> str:
    """The prompt for the judge subagent — emit a result matching the schema."""
    lines = brief.rubric.lines()
    numbered = "\n".join(
        f"{i}. [{kind}] {text}" for i, (kind, text) in enumerate(lines, start=1)
    )
    example = json.dumps(_result_skeleton(brief), indent=2)
    return (
        "You are an impartial judge scoring a transcript of the Hallucinote "
        "agent talking with a simulated user. Judge ONLY against the rubric "
        "below — not your own taste. The conversation is allowed to float; do "
        "not penalize wording, only behavior.\n\n"
        f"PERSONA\n{brief.persona}\n\nGOAL\n{brief.goal}\n\n"
        f"RUBRIC (score every line)\n{numbered}\n\n"
        "For a [must] line, satisfied=true means the agent did it. For a "
        "[must_not] line, satisfied=true means the agent AVOIDED it. The verdict "
        "is 'pass' only if every line is satisfied=true. Give one concrete "
        "rationale per line, citing the transcript.\n\n"
        "TRANSCRIPT\n"
        "------------------------------------------------------------\n"
        f"{transcript}\n"
        "------------------------------------------------------------\n\n"
        "Respond with ONLY a JSON object in exactly this shape "
        "(fill in satisfied/rationale/summary):\n"
        f"{example}"
    )


def _result_skeleton(brief: Brief) -> dict:
    return {
        "brief_id": brief.id,
        "verdict": "pass",
        "summary": "<one-paragraph rationale>",
        "rubric_findings": [
            {"kind": kind, "item": text, "satisfied": True, "rationale": "<why>"}
            for kind, text in brief.rubric.lines()
        ],
    }


# ---------------------------------------------------------------------------
# Judge-result schema + recorder
# ---------------------------------------------------------------------------


def derive_verdict(findings: list[dict]) -> str:
    """A run passes iff every rubric line is satisfied."""
    return "pass" if all(f.get("satisfied") is True for f in findings) else "fail"


def validate_result(data: dict, brief: Brief, *, source: str = "<result>") -> dict:
    """Validate a judge result against the brief's rubric. Raises ScenarioError.

    Enforces three properties that give "per-rubric-line rationale" teeth:
      1. shape/types of every field,
      2. completeness — every rubric line is scored exactly once, none invented,
      3. consistency — the recorded verdict matches the findings.
    """
    if not isinstance(data, dict):
        raise ScenarioError(f"{source}: result must be a JSON object")

    if data.get("brief_id") != brief.id:
        raise ScenarioError(
            f"{source}: brief_id {data.get('brief_id')!r} != brief {brief.id!r}"
        )

    verdict = data.get("verdict")
    if verdict not in ("pass", "fail"):
        raise ScenarioError(f"{source}: verdict must be 'pass' or 'fail', got {verdict!r}")

    _require_str(data, "summary", source)

    findings = data.get("rubric_findings")
    if not isinstance(findings, list):
        raise ScenarioError(f"{source}: 'rubric_findings' must be a list")

    expected = brief.rubric.lines()
    if len(findings) != len(expected):
        raise ScenarioError(
            f"{source}: {len(findings)} findings but rubric has {len(expected)} lines "
            "— score every line exactly once"
        )

    for i, (finding, (kind, text)) in enumerate(zip(findings, expected)):
        loc = f"{source}: rubric_findings[{i}]"
        if not isinstance(finding, dict):
            raise ScenarioError(f"{loc}: must be an object")
        if finding.get("kind") != kind or finding.get("item") != text:
            raise ScenarioError(
                f"{loc}: must match rubric line {i + 1} ([{kind}] {text!r}); "
                f"got [{finding.get('kind')}] {finding.get('item')!r}"
            )
        if not isinstance(finding.get("satisfied"), bool):
            raise ScenarioError(f"{loc}: 'satisfied' must be a boolean")
        _require_str(finding, "rationale", loc)

    derived = derive_verdict(findings)
    if derived != verdict:
        raise ScenarioError(
            f"{source}: verdict {verdict!r} is inconsistent with findings "
            f"(derived {derived!r}) — all lines satisfied iff pass"
        )

    return data


def write_result(
    data: dict,
    brief: Brief,
    *,
    results_dir: Path = RESULTS_DIR,
    now: datetime | None = None,
    canonical: bool = False,
) -> Path:
    """Validate, stamp with a UTC timestamp, and record a judge result.

    Two filename modes (see ``tests/scenarios/results/README.md`` for the
    retention policy):

    * ``canonical=False`` (default): ``<brief_id>-<UTC timestamp>.json`` — an
      ad-hoc run. These are **gitignored**: LLM-simulated runs are
      non-deterministic, so accumulating them in git is churn, not signal.
    * ``canonical=True``: ``canonical-<brief_id>.json`` (stable name, overwrites)
      — the pinned latest-passing result, **committed** as the durable
      verification evidence for this behaviorally-judged (non-unit-testable) work.
    """
    validate_result(data, brief, source="<write_result>")
    stamped = dict(data)
    moment = now or datetime.now(timezone.utc)
    stamped.setdefault("timestamp", moment.isoformat())

    results_dir = Path(results_dir)
    results_dir.mkdir(parents=True, exist_ok=True)
    fname = (
        f"canonical-{brief.id}.json" if canonical
        else f"{brief.id}-{moment.strftime('%Y%m%dT%H%M%SZ')}.json"
    )
    out = results_dir / fname
    out.write_text(json.dumps(stamped, indent=2) + "\n", encoding="utf-8")
    return out


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _cmd_list(args: argparse.Namespace) -> int:
    for brief in load_all_briefs(args.briefs_dir):
        tags = f"  [{', '.join(brief.tags)}]" if brief.tags else ""
        print(f"{brief.id:12}  {brief.goal}{tags}")
    return 0


def _cmd_show(args: argparse.Namespace) -> int:
    brief = load_brief(Path(args.briefs_dir) / f"{args.id}.json")
    print(f"# {brief.id}  (tags: {', '.join(brief.tags) or 'none'})\n")
    print(f"PERSONA\n{brief.persona}\n")
    print(f"GOAL\n{brief.goal}\n")
    print(f"RESPONSE CHARACTER\n{brief.response_character}\n")
    print("RUBRIC")
    for kind, text in brief.rubric.lines():
        print(f"  [{kind}] {text}")
    return 0


def _cmd_persona_prompt(args: argparse.Namespace) -> int:
    print(render_persona_prompt(load_brief(Path(args.briefs_dir) / f"{args.id}.json")))
    return 0


def _cmd_judge_prompt(args: argparse.Namespace) -> int:
    brief = load_brief(Path(args.briefs_dir) / f"{args.id}.json")
    transcript = Path(args.transcript).read_text(encoding="utf-8")
    print(render_judge_prompt(brief, transcript))
    return 0


def _cmd_validate_result(args: argparse.Namespace) -> int:
    data = json.loads(Path(args.result).read_text(encoding="utf-8"))
    brief = load_brief(Path(args.briefs_dir) / f"{data['brief_id']}.json")
    validate_result(data, brief, source=str(args.result))
    print(f"OK: {args.result} is a valid {data['verdict']} result for {brief.id}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="scenario_eval",
        description="Onboarding scenario-eval harness (testable core).",
    )
    parser.add_argument(
        "--briefs-dir", default=str(BRIEFS_DIR), help="directory of brief JSON files"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="list all briefs").set_defaults(func=_cmd_list)

    p_show = sub.add_parser("show", help="print one brief")
    p_show.add_argument("id")
    p_show.set_defaults(func=_cmd_show)

    p_pp = sub.add_parser("persona-prompt", help="render the persona subagent prompt")
    p_pp.add_argument("id")
    p_pp.set_defaults(func=_cmd_persona_prompt)

    p_jp = sub.add_parser("judge-prompt", help="render the judge subagent prompt")
    p_jp.add_argument("id")
    p_jp.add_argument("--transcript", required=True, help="path to the transcript file")
    p_jp.set_defaults(func=_cmd_judge_prompt)

    p_vr = sub.add_parser("validate-result", help="validate a recorded judge result")
    p_vr.add_argument("result", help="path to a result JSON file")
    p_vr.set_defaults(func=_cmd_validate_result)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except ScenarioError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
