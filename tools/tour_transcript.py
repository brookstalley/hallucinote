"""Render a Claude Code session transcript into a publishable markdown excerpt.

The end-to-end tour quotes real agent output. Hand-written fake transcripts are
the first thing a skeptical reader catches, so the excerpts are *generated* from
the JSONL Claude Code already writes to ``~/.claude/projects/<slug>/*.jsonl`` —
and can be regenerated when behavior changes, instead of rotting.

Publishing that JSONL naively would be a disclosure bug. A session transcript
carries absolute ``/Users/<name>/…`` paths, hook output, MCP server names, and
the contents of memory files injected as ``<system-reminder>`` blocks. So this
renderer **fails closed**:

* Record types are an explicit allowlist. An unrecognized ``type`` raises rather
  than being skipped — Claude Code adds record types over time (``file-history-
  delta`` appeared partway through this tool's development), and a silent skip
  would let a future type carrying who-knows-what pass unreviewed.
* Only ``text`` blocks survive. ``thinking`` is dropped, ``tool_result`` is
  dropped, and a tool call renders as a one-liner (name plus one identifying
  field) — never its full input, which is exactly where a stray absolute path
  hides.
* Every surviving string is redacted, and then the whole document is re-scanned
  for the forbidden patterns. If redaction missed one, nothing is written.

macOS/Linux paths are rewritten two ways: anything under the repo root becomes
repo-relative, and any other home path collapses to ``~/`` so the account name
does not ship.

Usage::

    python tools/tour_transcript.py --session <path.jsonl> --out excerpt.md
    python tools/tour_transcript.py --project-dir ~/.claude/projects/<slug> --turns 3
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

# Record types we render. Anything outside both this set and IGNORED_TYPES is a
# hard error — see the module docstring.
RENDERED_TYPES = frozenset({"user", "assistant"})

# Record types deliberately dropped, with the reason each is unsafe or useless
# to publish. Keeping the reasons here (rather than a bare set) is what lets a
# future maintainer judge whether a newly-added type belongs alongside them.
#
# To re-enumerate what a corpus actually contains (this list was wrong twice —
# probing one session missed six of the fifteen types below):
#
#   python -c "import json,glob,collections; c=collections.Counter(
#     json.loads(l).get('type') for f in glob.glob('*.jsonl')
#     for l in open(f) if l.strip()); print(c.most_common())"
#
IGNORED_TYPES: dict[str, str] = {
    "system": "hook output and harness diagnostics — local paths, never content",
    "attachment": "harness-injected file contents, not authored dialogue",
    "file-history-snapshot": "raw file bodies keyed by absolute path",
    "file-history-delta": "raw file diffs keyed by absolute path",
    "queue-operation": "harness queue events (task notifications) carrying temp paths",
    "custom-title": "session bookkeeping",
    "ai-title": "session bookkeeping",
    "mode": "session bookkeeping",
    "permission-mode": "session bookkeeping",
    "agent-name": "session bookkeeping",
    "bridge-session": "harness transport bookkeeping",
    "pr-link": "bookkeeping — a PR URL, not authored dialogue",
    "last-prompt": "duplicate of a user record already rendered",
}

# Content-block types inside a message. Same allowlist discipline.
RENDERED_BLOCKS = frozenset({"text", "tool_use"})
IGNORED_BLOCKS: dict[str, str] = {
    "thinking": "private reasoning, not authored output",
    "tool_result": "arbitrary command/file output — the richest leak surface",
}

# Patterns that must not survive into published output. The gate runs over the
# fully-rendered document, after redaction, so a miss anywhere fails the run.
# What leaks is the *account segment*, so that is what both the redactor and the
# gate key on. A bare ``/Users/`` token with no name after it — prose discussing
# the pattern itself, e.g. ``git log -S'/Users/'`` — discloses nothing and is
# deliberately allowed through; gating on it instead would refuse real sessions
# for a non-leak, and rewriting it would silently change the meaning of a quoted
# command.
_ACCOUNT_SEGMENT = r"/(?:Users|home)/[^/\s'\"`]+"

# Same principle for reminders: what must not ship is an injected block's
# *contents*, which a surviving ``<system-reminder>`` tag announces. The bare
# word in authored prose — an agent explaining the mechanism — is not a leak,
# and gating on it would refuse any session that discussed its own harness.
FORBIDDEN = (
    (re.compile(_ACCOUNT_SEGMENT), "an absolute home path including an account name"),
    (re.compile(r"</?system-reminder>"), "an unpaired harness system-reminder tag"),
)

_SYSTEM_REMINDER = re.compile(r"<system-reminder>.*?</system-reminder>", re.DOTALL)

# Harness markup wrapping slash-command echoes and their output. Not a
# disclosure risk, but it is not authored dialogue either: left in, a `/clear`
# renders as though the user had typed the literal XML as a prompt. Stripped to
# empty, the turn carries no text and is dropped by the caller.
_HARNESS_MARKUP = re.compile(
    r"<(command-name|command-message|command-args|command-contents"
    r"|local-command-stdout|local-command-stderr|local-command-caveat)>"
    r".*?</\1>",
    re.DOTALL,
)
# Ordered: the trailing-slash form first so ``~/`` keeps its separator, then the
# bare form so a path ending at the account segment (``/Users/alice``, at the end
# of a sentence) is caught too rather than sailing past the gate.
_HOME_PATH_DIR = re.compile(_ACCOUNT_SEGMENT + "/")
_HOME_PATH_BARE = re.compile(_ACCOUNT_SEGMENT)

# Per-tool field carrying the most useful one-line identifier. Values are
# redacted like any other string; anything not listed renders as a bare name.
_TOOL_SUMMARY_FIELD = {
    "Bash": "description",
    "Read": "file_path",
    "Edit": "file_path",
    "Write": "file_path",
    "NotebookEdit": "notebook_path",
    "Glob": "pattern",
    "Grep": "pattern",
    "Skill": "skill",
    "Agent": "description",
    "WebFetch": "url",
    "WebSearch": "query",
}


class TranscriptError(Exception):
    """Base class for refusals — every one of these means nothing is written."""


class UnknownRecordType(TranscriptError):
    """A record type outside both allowlists. Classify it before publishing."""


class UnknownBlockType(TranscriptError):
    """A content-block type outside both allowlists."""


class RedactionFailure(TranscriptError):
    """A forbidden pattern survived redaction. The fail-closed backstop."""


@dataclass(frozen=True)
class Turn:
    """One rendered contribution: a prompt, or an assistant response."""

    role: str
    timestamp: str
    text: str
    tool_lines: tuple[str, ...]


def repo_root_of(start: Path) -> Path:
    """Return the git top-level containing ``start``, or ``start`` itself.

    Used only to make paths repo-relative; a non-repo directory is not an error
    (the generic home-path collapse still applies).
    """
    try:
        out = subprocess.run(
            ["git", "-C", str(start), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return start
    return Path(out.stdout.strip() or start)


def redact(text: str, repo_root: Path) -> str:
    """Strip injected reminders and rewrite absolute paths.

    Repo-relative rewriting runs first: without it a repo path would collapse to
    ``~/source/<repo>/…`` and keep leaking the layout it sits in.
    """
    text = _SYSTEM_REMINDER.sub("", text)
    text = _HARNESS_MARKUP.sub("", text)
    root = str(repo_root).rstrip("/")
    text = text.replace(root + "/", "")
    text = text.replace(root, ".")
    text = _HOME_PATH_DIR.sub("~/", text)
    return _HOME_PATH_BARE.sub("~", text)


def assert_publishable(document: str) -> None:
    """Raise unless the rendered document is free of every forbidden pattern."""
    for pattern, description in FORBIDDEN:
        match = pattern.search(document)
        if match:
            line = document.count("\n", 0, match.start()) + 1
            raise RedactionFailure(
                f"line {line}: {description} survived redaction "
                f"({match.group(0)!r}). Refusing to write — widen the redaction "
                f"rules rather than relaxing this check."
            )


def tool_line(block: dict, repo_root: Path) -> str:
    """Render one tool call as a single line: never the full input."""
    name = str(block.get("name", "?"))
    field = _TOOL_SUMMARY_FIELD.get(name)
    raw = block.get("input") or {}
    value = raw.get(field) if field and isinstance(raw, dict) else None
    if not isinstance(value, str) or not value.strip():
        return f"`{name}`"
    summary = redact(value.strip(), repo_root).splitlines()[0]
    return f"`{name}` — {summary}"


def load(path: Path) -> list[dict]:
    """Parse a JSONL transcript, skipping blank lines.

    A malformed line is an error rather than a skip: a transcript we cannot
    fully parse is one we cannot claim to have fully filtered.
    """
    records = []
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        raw = raw.strip()
        if not raw:
            continue
        try:
            records.append(json.loads(raw))
        except json.JSONDecodeError as exc:
            raise TranscriptError(f"{path}:{lineno}: malformed JSON — {exc}") from exc
    return records


def _blocks_of(record: dict) -> list[dict]:
    """Normalize ``message.content`` to a block list (a bare str is one text block)."""
    content = (record.get("message") or {}).get("content")
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    if isinstance(content, list):
        return [b for b in content if isinstance(b, dict)]
    return []


def to_turns(records: list[dict], repo_root: Path) -> list[Turn]:
    """Filter records to publishable turns, raising on anything unclassified."""
    turns: list[Turn] = []
    for record in records:
        rtype = record.get("type")
        if rtype in IGNORED_TYPES:
            continue
        if rtype not in RENDERED_TYPES:
            raise UnknownRecordType(
                f"unrecognized record type {rtype!r}. Claude Code adds record "
                f"types over time; classify it in RENDERED_TYPES or "
                f"IGNORED_TYPES (with a reason) before publishing this session."
            )
        # Subagent chatter and harness-injected meta records are not authored
        # dialogue and routinely carry local paths.
        if record.get("isSidechain") or record.get("isMeta"):
            continue

        texts: list[str] = []
        tools: list[str] = []
        for block in _blocks_of(record):
            btype = block.get("type")
            if btype in IGNORED_BLOCKS:
                continue
            if btype not in RENDERED_BLOCKS:
                raise UnknownBlockType(
                    f"unrecognized content block {btype!r} in a {rtype} record; "
                    f"classify it before publishing."
                )
            if btype == "text":
                cleaned = redact(str(block.get("text", "")), repo_root).strip()
                if cleaned:
                    texts.append(cleaned)
            else:
                tools.append(tool_line(block, repo_root))

        if not texts and not tools:
            continue
        turns.append(
            Turn(
                role=str(rtype),
                timestamp=str(record.get("timestamp", "")),
                text="\n\n".join(texts),
                tool_lines=tuple(tools),
            )
        )
    return turns


def render(turns: list[Turn]) -> str:
    """Render turns to markdown: prompts as blockquotes, responses as prose."""
    parts: list[str] = []
    for turn in turns:
        if turn.role == "user":
            quoted = "\n".join(f"> {line}" if line else ">" for line in turn.text.splitlines())
            parts.append(quoted)
        else:
            if turn.text:
                parts.append(turn.text)
            if turn.tool_lines:
                parts.append("\n".join(turn.tool_lines))
    return "\n\n".join(parts).strip() + "\n"


def select(turns: list[Turn], start_at: str | None, exchanges: int | None) -> list[Turn]:
    """Trim to an excerpt: from the first prompt matching ``start_at``, ``exchanges`` prompts deep."""
    if start_at:
        for index, turn in enumerate(turns):
            if turn.role == "user" and start_at in turn.text:
                turns = turns[index:]
                break
        else:
            raise TranscriptError(f"no prompt containing {start_at!r} in this session")
    if exchanges is None:
        return turns
    kept: list[Turn] = []
    seen = 0
    for turn in turns:
        if turn.role == "user":
            seen += 1
            if seen > exchanges:
                break
        kept.append(turn)
    return kept


def latest_session(project_dir: Path) -> Path:
    """Return the most recently modified transcript in a project directory."""
    sessions = sorted(project_dir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime)
    if not sessions:
        raise TranscriptError(f"no *.jsonl transcripts under {project_dir}")
    return sessions[-1]


def build_excerpt(
    session: Path,
    repo_root: Path,
    start_at: str | None = None,
    exchanges: int | None = None,
) -> str:
    """Full pipeline: load → filter → redact → render → gate."""
    turns = select(to_turns(load(session), repo_root), start_at, exchanges)
    document = render(turns)
    assert_publishable(document)
    return document


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--session", type=Path, help="path to a session .jsonl")
    source.add_argument(
        "--project-dir", type=Path, help="a ~/.claude/projects/<slug> dir; uses its newest session"
    )
    parser.add_argument("--out", type=Path, help="write here instead of stdout")
    parser.add_argument("--start-at", help="begin at the first prompt containing this substring")
    parser.add_argument("--exchanges", type=int, help="how many prompts to keep from the start")
    parser.add_argument(
        "--repo-root",
        type=Path,
        help="paths under this root render repo-relative (default: git toplevel of cwd)",
    )
    args = parser.parse_args(argv)

    session = args.session if args.session else latest_session(args.project_dir.expanduser())
    repo_root = args.repo_root or repo_root_of(Path.cwd())

    try:
        document = build_excerpt(
            session.expanduser(), repo_root, args.start_at, args.exchanges
        )
    except TranscriptError as exc:
        print(f"tour_transcript: {exc}", file=sys.stderr)
        return 1

    if args.out:
        args.out.write_text(document, encoding="utf-8")
        print(f"wrote {args.out} ({len(document.splitlines())} lines)", file=sys.stderr)
    else:
        sys.stdout.write(document)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
