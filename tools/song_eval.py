"""Musical-work eval harness — the *output* sibling of the persona scenario-eval.

``tools/scenario_eval.py`` judges a **transcript**: did the agent *behave*
(pace proposals, teach by ear, not interrogate). This module judges the other
axis — given an abstract stylistic request, does the system *produce the right
song*, and does it tell the truth about what it cannot produce.

A **work brief** is run-instructions for a simulated user (an abstract request:
a style + a few key characteristics, one level up from a literal spec) paired
with a rubric scored over **two surfaces**:

  * **framing** — read from the conversation transcript: honest dimensional
    caveats, no confabulation, the round-trip invite, honest refusal.
  * **artifact** — read from the produced song. Per the project's own rule we do
    **not** build new musical inference here: we point the existing review
    surface at the song (``/compose-review`` over ``build.py`` + the
    arrangement, no audio — push to Live is optional) and the judge interprets
    *that tool's output* against the brief's intent, exactly as the product does
    for a real user.

Each rubric line is prefixed ``framing:`` or ``artifact:`` so the judge knows
which surface to read it against — the two-substrate split made structural.

The capability cliffs are the point. Each brief carries ``expected_capabilities``
— per-dimension expected outcome (``deliver`` / ``caveat`` / ``refuse`` /
``known-gap``) keyed to ``docs/capability-truth.md``. That makes the suite a
**capability-regression tracker**: when melody or vocals mature, a brief's
expectation flips and the same test re-grades to a higher bar.

The judge-result schema (``validate_result`` / ``write_result`` /
``derive_verdict``) is **shared verbatim** from ``scenario_eval`` — a work
result is the same shape as a persona result. This module owns only the *brief*
schema, prompt rendering, and the intent-doc that feeds the artifact scorer. The
LLM steps (role-play the user, run the compose pass, judge) are the ad hoc part,
spawned as subagents per ``tests/scenarios/works/README.md``.

CLI::

    python -m tools.song_eval list
    python -m tools.song_eval show <id>
    python -m tools.song_eval request-prompt <id>
    python -m tools.song_eval intent-doc <id>
    python -m tools.song_eval judge-prompt <id> --transcript t.txt --compose-review c.txt
    python -m tools.song_eval validate-result path/to/result.json
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

# The judge-result schema is the shared contract — reuse it verbatim so a work
# result is indistinguishable in shape from a persona result.
from tools.scenario_eval import (
    ID_RE,
    RUBRIC_KINDS,
    Rubric,
    ScenarioError,
    SCENARIOS_DIR,
    validate_result,
)

# ---------------------------------------------------------------------------
# Locations
# ---------------------------------------------------------------------------

WORKS_DIR = SCENARIOS_DIR / "works"          # one *.json brief per work
WORK_RESULTS_DIR = SCENARIOS_DIR / "results"  # shared corpus with persona results

# ---------------------------------------------------------------------------
# Controlled vocabularies — keep the matrix legible and the cliffs mechanical
# ---------------------------------------------------------------------------

# The axes that make the specificity x sophistication grid scannable.
SPECIFICITY = ("loose", "medium", "precise")
SOPHISTICATION = ("simple", "medium", "complex", "very-high")

# Per-dimension expected outcome. `deliver` = render it fully; `caveat` = render
# but name the thin dimension honestly; `refuse` = honest "can't, here's why";
# `known-gap` = we'd attempt it but the capability isn't built — a real failure
# the suite is meant to surface.
EXPECTATIONS = ("deliver", "caveat", "refuse", "known-gap")

# Keyed to docs/capability-truth.md's dimensions, plus request-space dimensions
# (lyrics, vocal *performance*) that aren't in the table yet — their very
# absence is the honest "not even on the menu" signal. When the capability table
# moves, update this set and the affected briefs' expectations together.
CAPABILITY_DIMENSIONS = (
    "rhythm",
    "harmony",
    "bass",
    "arrangement",
    "sound-design",
    "mix",
    "melody",            # lead-line *authoring* — still ◐ (no generator, by design)
    "melody-analysis",   # line *analysis* (contour/intervals/harmony-fit) — ✓ read-side
    "vocals",
    "lyrics",
    "round-trip",
)

# Every rubric line is scored against exactly one surface, named by its prefix.
SURFACES = ("framing", "artifact")
_SURFACE_PREFIXES = tuple(f"{s}:" for s in SURFACES)


# ---------------------------------------------------------------------------
# Brief schema
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Capability:
    """One dimension the request leans on + what we expect to happen there."""

    dimension: str
    expectation: str
    note: str


@dataclass(frozen=True)
class WorkBrief:
    """An abstract musical request + a two-surface rubric.

    Exposes ``id`` and ``rubric`` so the shared ``validate_result`` /
    ``write_result`` (which only touch ``brief.id`` and ``brief.rubric.lines()``)
    accept it directly — a work result is a persona result by shape.
    """

    id: str
    request: str
    response_character: str
    specificity: str
    sophistication: str
    expected_capabilities: tuple[Capability, ...]
    rubric: Rubric
    tags: tuple[str, ...] = ()


# ---------------------------------------------------------------------------
# Small parse guards (local to this module's brief schema)
# ---------------------------------------------------------------------------


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


def _require_choice(value: str, choices: tuple[str, ...], where: str) -> str:
    if value not in choices:
        raise ScenarioError(f"{where}: must be one of {list(choices)}, got {value!r}")
    return value


def _parse_capabilities(value: object, where: str) -> tuple[Capability, ...]:
    if not isinstance(value, list) or not value:
        raise ScenarioError(f"{where}: must be a non-empty list of capability objects")
    out: list[Capability] = []
    seen: set[str] = set()
    for i, raw in enumerate(value):
        loc = f"{where}[{i}]"
        if not isinstance(raw, dict):
            raise ScenarioError(f"{loc}: must be an object")
        unknown = set(raw) - {"dimension", "expectation", "note"}
        if unknown:
            raise ScenarioError(f"{loc}: unknown keys {sorted(unknown)}")
        dimension = _require_choice(
            _require_str(raw, "dimension", loc), CAPABILITY_DIMENSIONS, f"{loc}: dimension"
        )
        if dimension in seen:
            raise ScenarioError(f"{loc}: duplicate dimension {dimension!r}")
        seen.add(dimension)
        expectation = _require_choice(
            _require_str(raw, "expectation", loc), EXPECTATIONS, f"{loc}: expectation"
        )
        out.append(Capability(dimension, expectation, _require_str(raw, "note", loc)))
    return tuple(out)


def _parse_rubric(raw: object, source: str) -> Rubric:
    if not isinstance(raw, dict):
        raise ScenarioError(f"{source}: 'rubric' must be an object with 'must'/'must_not'")
    unknown = set(raw) - set(RUBRIC_KINDS)
    if unknown:
        raise ScenarioError(
            f"{source}: rubric has unknown keys {sorted(unknown)}; allowed: {list(RUBRIC_KINDS)}"
        )
    rubric = Rubric(
        must=_require_str_list(raw.get("must", []), f"{source}: rubric.must", allow_empty=False),
        must_not=_require_str_list(raw.get("must_not", []), f"{source}: rubric.must_not", allow_empty=True),
    )
    # Every line must declare its scoring surface up front.
    for kind, text in rubric.lines():
        if not text.startswith(_SURFACE_PREFIXES):
            raise ScenarioError(
                f"{source}: rubric.{kind} line {text!r} must start with one of "
                f"{[p for p in _SURFACE_PREFIXES]} (the scoring surface)"
            )
    return rubric


def parse_brief(data: dict, *, source: str = "<work-brief>") -> WorkBrief:
    """Validate a decoded work-brief dict into a :class:`WorkBrief`."""
    if not isinstance(data, dict):
        raise ScenarioError(f"{source}: brief must be a JSON object")

    brief_id = _require_str(data, "id", source)
    if not ID_RE.match(brief_id):
        raise ScenarioError(
            f"{source}: 'id' {brief_id!r} must match {ID_RE.pattern} (lowercase slug)"
        )

    axes = data.get("axes")
    if not isinstance(axes, dict):
        raise ScenarioError(f"{source}: 'axes' must be an object with 'specificity'/'sophistication'")
    unknown_axes = set(axes) - {"specificity", "sophistication"}
    if unknown_axes:
        raise ScenarioError(f"{source}: axes has unknown keys {sorted(unknown_axes)}")

    rubric = _parse_rubric(data.get("rubric"), source)

    known = {"id", "request", "response_character", "axes", "expected_capabilities", "rubric", "tags"}
    unknown = set(data) - known
    if unknown:
        raise ScenarioError(f"{source}: unknown top-level keys {sorted(unknown)}")

    return WorkBrief(
        id=brief_id,
        request=_require_str(data, "request", source),
        response_character=_require_str(data, "response_character", source),
        specificity=_require_choice(
            _require_str(axes, "specificity", f"{source}: axes"), SPECIFICITY, f"{source}: axes.specificity"
        ),
        sophistication=_require_choice(
            _require_str(axes, "sophistication", f"{source}: axes"),
            SOPHISTICATION,
            f"{source}: axes.sophistication",
        ),
        expected_capabilities=_parse_capabilities(
            data.get("expected_capabilities"), f"{source}: expected_capabilities"
        ),
        rubric=rubric,
        tags=_require_str_list(data.get("tags", []), f"{source}: tags", allow_empty=True),
    )


def load_brief(path: Path) -> WorkBrief:
    """Load and validate a single work-brief JSON file."""
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


def load_all_briefs(works_dir: Path = WORKS_DIR) -> list[WorkBrief]:
    """Load every ``*.json`` work brief in ``works_dir``, sorted by id."""
    works_dir = Path(works_dir)
    if not works_dir.is_dir():
        raise ScenarioError(f"{works_dir}: works directory not found")
    briefs = [load_brief(p) for p in sorted(works_dir.glob("*.json"))]
    seen: set[str] = set()
    for b in briefs:
        if b.id in seen:
            raise ScenarioError(f"duplicate brief id {b.id!r} in {works_dir}")
        seen.add(b.id)
    return briefs


# ---------------------------------------------------------------------------
# Prompt + intent-doc rendering — deterministic, so the LLM steps stay thin
# ---------------------------------------------------------------------------


def render_request_prompt(brief: WorkBrief) -> str:
    """System prompt for the user subagent — voices the abstract request.

    Withholds the rubric **and** ``expected_capabilities``: the simulated user
    must not know which dimensions we expect to caveat or refuse, or it would
    fish for the answer instead of letting the agent reveal it honestly.
    """
    return (
        "You are role-playing a Hallucinote *user* asking for a song. Stay fully "
        "in character; never break role, never reveal you are a simulation, and "
        "never grade the agent.\n\n"
        f"WHAT YOU WANT\n{brief.request}\n\n"
        f"HOW YOU RESPOND (character, not script)\n{brief.response_character}\n\n"
        "Open with your request in your own words — a style and a few key "
        "characteristics, not a literal spec. Then react in character to what "
        "the agent proposes or builds. Do NOT enumerate technical requirements "
        "the agent didn't ask for; let them lead. If the agent says it can't do "
        "part of what you want, react as this character genuinely would."
    )


def render_intent_doc(brief: WorkBrief) -> str:
    """The declared-intent markdown that becomes the scaffolded song's intent.

    This is what ``/compose-review`` RECALLs when scoring the artifact surface —
    so the harness feeds the product's own intent machinery rather than running
    a parallel grader. Deliberately the *request* only: the rubric and the
    capability expectations are harness metadata, not the song's intent.
    """
    return (
        f"# Intent — {brief.id}\n\n"
        "_Declared intent for a musical-work eval. Written by "
        "`tools/song_eval.py intent-doc`; read back by `/compose-review`._\n\n"
        "## The request\n\n"
        f"{brief.request}\n\n"
        "## Axes\n\n"
        f"- Specificity: **{brief.specificity}**\n"
        f"- Sophistication: **{brief.sophistication}**\n"
    )


def _result_skeleton(brief: WorkBrief) -> dict:
    return {
        "brief_id": brief.id,
        "verdict": "pass",
        "summary": "<one-paragraph rationale>",
        "rubric_findings": [
            {"kind": kind, "item": text, "satisfied": True, "rationale": "<why>"}
            for kind, text in brief.rubric.lines()
        ],
    }


def _surface_block(title: str, body: str | None, *, absent_note: str) -> str:
    """Render one judge-input surface, or a note explaining its absence."""
    if body is None:
        return f"{title}: {absent_note}\n\n"
    return (
        f"{title}\n"
        "------------------------------------------------------------\n"
        f"{body}\n"
        "------------------------------------------------------------\n\n"
    )


def render_judge_prompt(
    brief: WorkBrief,
    transcript: str,
    compose_review: str | None = None,
    db_extract: str | None = None,
) -> str:
    """Prompt for the judge subagent — score every line on its declared surface.

    Three input surfaces, degrading with the capability cliff:

    * ``framing:`` lines → the **transcript** (the agent's words).
    * ``artifact:`` lines → the song. Where a dimension is *supported*, read the
      **compose-review output** (the existing review surface — the judge does not
      invent musical analysis, it interprets the tool's report). Where the
      request **outran the analyzers** — a novel/emergent thing the tool produced
      with no generator or helper to understand it — fall back to the **raw DB
      extract** and reason about the actual produced song on its own terms. The
      analyzer being blind to a request is itself a signal, not a free pass.
    """
    numbered = "\n".join(
        f"{i}. [{kind}] {text}" for i, (kind, text) in enumerate(brief.rubric.lines(), start=1)
    )
    caps = "\n".join(
        f"- {c.dimension}: expect **{c.expectation}** — {c.note}"
        for c in brief.expected_capabilities
    )
    # If neither artifact surface was supplied, no song was produced to score.
    no_artifact_note = (
        "(none supplied — no song was produced to score). Score every "
        "'artifact:' line satisfied=false with a rationale that says the "
        "artifact surface was not produced."
    )
    artifact_absent = (
        no_artifact_note if compose_review is None and db_extract is None
        else "(not supplied for this surface — use the other artifact surface below)."
    )
    example = json.dumps(_result_skeleton(brief), indent=2)
    return (
        "You are an impartial judge scoring whether the Hallucinote system "
        "produced the right song for an abstract request — and was honest about "
        "what it could not produce. Judge ONLY against the rubric. Each line "
        "names its surface: 'framing:' lines are about the agent's words in the "
        "TRANSCRIPT; 'artifact:' lines are about the song.\n\n"
        "For 'artifact:' lines: prefer the COMPOSE-REVIEW OUTPUT where it speaks "
        "to the line (do not invent your own musical analysis — interpret the "
        "tool's report against intent). Where the request asked for something the "
        "analyzers cannot understand (a novel/emergent result with no supporting "
        "generator), fall back to the RAW DB EXTRACT and judge the actual produced "
        "song on its own terms.\n\n"
        f"THE REQUEST\n{brief.request}\n\n"
        f"EXPECTED CAPABILITY OUTCOMES (the rubric's backbone)\n{caps}\n\n"
        f"RUBRIC (score every line, in order)\n{numbered}\n\n"
        "For a [must] line, satisfied=true means the agent/song did it. For a "
        "[must_not] line, satisfied=true means it was AVOIDED. The verdict is "
        "'pass' only if every line is satisfied=true. Give one concrete "
        "rationale per line, citing the surface you used.\n\n"
        + _surface_block(
            "TRANSCRIPT (the framing surface — read 'framing:' lines against this)",
            transcript,
            absent_note="",
        )
        + _surface_block(
            "COMPOSE-REVIEW OUTPUT (artifact surface, supported dimensions)",
            compose_review,
            absent_note=artifact_absent,
        )
        + _surface_block(
            "RAW DB EXTRACT (artifact surface, where the analyzers went blind)",
            db_extract,
            absent_note=artifact_absent,
        )
        + "Respond with ONLY a JSON object in exactly this shape "
        "(fill in satisfied/rationale/summary):\n"
        f"{example}"
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _cmd_list(args: argparse.Namespace) -> int:
    for brief in load_all_briefs(args.works_dir):
        print(f"{brief.id:16}  [{brief.specificity}/{brief.sophistication}]  {brief.request[:60]}")
    return 0


def _cmd_show(args: argparse.Namespace) -> int:
    brief = load_brief(Path(args.works_dir) / f"{args.id}.json")
    print(f"# {brief.id}  ({brief.specificity} / {brief.sophistication})  "
          f"tags: {', '.join(brief.tags) or 'none'}\n")
    print(f"REQUEST\n{brief.request}\n")
    print(f"RESPONSE CHARACTER\n{brief.response_character}\n")
    print("EXPECTED CAPABILITIES")
    for c in brief.expected_capabilities:
        print(f"  {c.dimension:12} {c.expectation:10} {c.note}")
    print("\nRUBRIC")
    for kind, text in brief.rubric.lines():
        print(f"  [{kind}] {text}")
    return 0


def _cmd_request_prompt(args: argparse.Namespace) -> int:
    print(render_request_prompt(load_brief(Path(args.works_dir) / f"{args.id}.json")))
    return 0


def _cmd_intent_doc(args: argparse.Namespace) -> int:
    print(render_intent_doc(load_brief(Path(args.works_dir) / f"{args.id}.json")))
    return 0


def _cmd_judge_prompt(args: argparse.Namespace) -> int:
    brief = load_brief(Path(args.works_dir) / f"{args.id}.json")
    transcript = Path(args.transcript).read_text(encoding="utf-8")
    review = Path(args.compose_review).read_text(encoding="utf-8") if args.compose_review else None
    db_extract = Path(args.db_extract).read_text(encoding="utf-8") if args.db_extract else None
    print(render_judge_prompt(brief, transcript, review, db_extract))
    return 0


def _cmd_validate_result(args: argparse.Namespace) -> int:
    data = json.loads(Path(args.result).read_text(encoding="utf-8"))
    brief = load_brief(Path(args.works_dir) / f"{data['brief_id']}.json")
    validate_result(data, brief, source=str(args.result))
    print(f"OK: {args.result} is a valid {data['verdict']} result for {brief.id}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="song_eval",
        description="Musical-work eval harness (testable core).",
    )
    parser.add_argument(
        "--works-dir", default=str(WORKS_DIR), help="directory of work-brief JSON files"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="list all work briefs").set_defaults(func=_cmd_list)

    show = sub.add_parser("show", help="show one brief")
    show.add_argument("id")
    show.set_defaults(func=_cmd_show)

    rp = sub.add_parser("request-prompt", help="render the user (request) subagent prompt")
    rp.add_argument("id")
    rp.set_defaults(func=_cmd_request_prompt)

    idoc = sub.add_parser("intent-doc", help="render the declared-intent markdown for scaffolding")
    idoc.add_argument("id")
    idoc.set_defaults(func=_cmd_intent_doc)

    jp = sub.add_parser("judge-prompt", help="render the judge subagent prompt")
    jp.add_argument("id")
    jp.add_argument("--transcript", required=True, help="path to the captured transcript")
    jp.add_argument("--compose-review", help="path to /compose-review output (artifact surface, supported dims)")
    jp.add_argument("--db-extract", help="path to a raw DB structural extract (artifact surface, where analyzers go blind)")
    jp.set_defaults(func=_cmd_judge_prompt)

    vr = sub.add_parser("validate-result", help="validate a recorded judge result")
    vr.add_argument("result")
    vr.set_defaults(func=_cmd_validate_result)

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
