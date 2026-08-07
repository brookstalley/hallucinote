"""Render a Claude Code session transcript into a publishable markdown excerpt.

The end-to-end tour quotes real agent output. Hand-written fake transcripts are
the first thing a skeptical reader catches, so the excerpts are *generated* from
the JSONL Claude Code already writes to ``~/.claude/projects/<slug>/*.jsonl`` —
and can be regenerated when behavior changes, instead of rotting.

Publishing that JSONL naively would be a disclosure bug. A session transcript
carries absolute ``/Users/<name>/…`` paths (including *dash-encoded* ones in
Claude Code's own project and task directory names), hook output, and the
contents of memory files injected as ``<system-reminder>`` blocks. So this
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

macOS/Linux paths are rewritten three ways: anything under the repo root becomes
repo-relative, any other home path collapses to ``~/``, and a dash-encoded home
path has its account segment replaced — so **this machine's** account name does
not ship in any of the three forms it appears in.

One qualification, because the guarantee is not uniform: a path belonging to a
*different* account (a transcript copied from another machine) is covered only by
the generic patterns, and those cannot express a hyphenated username in the dash
encoding — ``-Users-mary-jane-…`` would be bisected, shipping half the name. The
gate's bisection check catches that residue for the local account; for a foreign
one, pass ``--account`` or treat the excerpt as unreviewed.

**Tool names, including MCP tool names, DO ship** (``mcp__<server>__<tool>``
renders verbatim). That is deliberate, not an oversight: the tour's whole point
is showing which tools the agent actually called, and blanket-redacting server
names would gut the beat that demonstrates the Ableton bridge. The consequence is
that a rendered excerpt discloses which MCP servers the session had connected, so
**choosing which session to render is an editorial act** — render one whose tool
use you are willing to publish, rather than expecting this tool to launder it.

Usage::

    python tools/tour_transcript.py --session <path.jsonl> --out excerpt.md
    python tools/tour_transcript.py --project-dir ~/.claude/projects/<slug> \
        --start-at "make the drums drag" --exchanges 2
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
_ACCOUNT_SEGMENT = r"/(?:Users|home)/+[^/\s'\"`]+"

# The same home path, dash-encoded. Claude Code names its own project and task
# directories by flattening the cwd — ``~/.claude/projects/-Users-alice-source-
# repo/`` and ``/private/tmp/claude-…/-Users-alice-source-repo/…`` — so the
# account name ships in a form no slash-based pattern matches. This is not
# hypothetical: the first version of this tool passed its own
# ``grep -c '/Users/'`` acceptance check while a dash-encoded name would have
# gone straight into published output. Both the redactor and the gate key on it.
_DASH_ACCOUNT_SEGMENT = r"-(?:Users|home)-+[A-Za-z0-9_.]+"


def _account_rules(account: str) -> tuple[tuple[re.Pattern[str], str], ...]:
    """Literal patterns for *this* machine's account name, in both encodings.

    The generic patterns above cannot express a **hyphenated** username. In the
    dash encoding, ``-`` is the delimiter, so for an account like ``mary-jane``
    the slug ``-Users-mary-jane-source-repo`` matches only as far as
    ``-Users-mary`` — half the name ships, and because the gate re-scans with the
    same generic pattern it finds no ``-Users-`` remaining and passes. A shared
    pattern cannot catch its own blind spot.

    Knowing the actual name removes the ambiguity entirely: these run *before*
    the generic patterns, and the generic ones remain as a second layer for
    paths belonging to some other account (a transcript copied from elsewhere).
    """
    if not account:
        return ()
    name = re.escape(account)
    return (
        (re.compile(rf"/(?:Users|home)/+{name}", re.IGNORECASE), "~"),
        (re.compile(rf"-(?:Users|home)-+{name}", re.IGNORECASE), "-REDACTED"),
    )


def default_account() -> str:
    """This machine's account name, or ``""`` if it cannot be determined."""
    try:
        return Path.home().name
    except (OSError, RuntimeError):
        return ""


# Same principle for reminders: what must not ship is an injected block's
# *contents*, which a surviving ``<system-reminder>`` tag announces. The bare
# word in authored prose — an agent explaining the mechanism — is not a leak,
# and gating on it would refuse any session that discussed its own harness.
# Credential shapes. The path and reminder rules cover what the *harness*
# injects; these cover what a human pastes. A key typed into a prompt, or echoed
# back in assistant prose, arrives as an ordinary ``text`` block — it is not a
# tool_result and not a path, so every other rule here passes it straight
# through into a public repo whose history is permanent. The list is
# deliberately literal and high-signal rather than an entropy heuristic: a
# false refusal costs one `--account`-style investigation, while a false pass
# costs a leaked credential, and "fails closed" has to mean this too.
_CREDENTIAL_PATTERNS = (
    (r"\bghp_[A-Za-z0-9]{16,}", "a GitHub personal access token"),
    (r"\bgithub_pat_[A-Za-z0-9_]{20,}", "a fine-grained GitHub token"),
    (r"\bgh[opsu]_[A-Za-z0-9]{16,}", "a GitHub OAuth/server token"),
    (r"\bsk-[A-Za-z0-9_-]{20,}", "an OpenAI-style secret key"),
    (r"\bsk-ant-[A-Za-z0-9_-]{20,}", "an Anthropic API key"),
    (r"\bAKIA[0-9A-Z]{16}", "an AWS access key id"),
    (r"\bxox[baprs]-[A-Za-z0-9-]{10,}", "a Slack token"),
    (r"-----BEGIN [A-Z ]*PRIVATE KEY-----", "a private key block"),
    (r"(?i)\bauthorization:\s*(bearer|basic)\s+\S+", "an Authorization header with a credential"),
)

# Case-insensitive throughout: macOS paths are case-preserving but
# case-insensitive, so ``/users/alice`` addresses the same home directory and
# leaks the same name, while a case-sensitive rule neither redacts nor gates it.
FORBIDDEN = (
    (re.compile(_ACCOUNT_SEGMENT, re.IGNORECASE), "an absolute home path including an account name"),
    (
        re.compile(_DASH_ACCOUNT_SEGMENT, re.IGNORECASE),
        "a dash-encoded home path including an account name",
    ),
    (re.compile(r"</?system-reminder>", re.IGNORECASE), "an unpaired harness system-reminder tag"),
) + tuple((re.compile(pattern), description) for pattern, description in _CREDENTIAL_PATTERNS)

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
_HOME_PATH_DIR = re.compile(_ACCOUNT_SEGMENT + "/", re.IGNORECASE)
_HOME_PATH_BARE = re.compile(_ACCOUNT_SEGMENT, re.IGNORECASE)
_DASH_HOME_PATH = re.compile(_DASH_ACCOUNT_SEGMENT, re.IGNORECASE)

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


def redact(text: str, repo_root: Path, account: str | None = None) -> str:
    """Strip injected reminders and rewrite absolute paths.

    Repo-relative rewriting runs first: without it a repo path would collapse to
    ``~/source/<repo>/…`` and keep leaking the layout it sits in.
    """
    text = _SYSTEM_REMINDER.sub("", text)
    text = _HARNESS_MARKUP.sub("", text)

    # The bare-root rewrite must be ANCHORED at a path boundary. Unanchored, a
    # root of ``…/source/demo`` also matches inside ``…/source/demo-songs/x``,
    # producing ``.-songs/x`` — output that is both garbled and still discloses
    # the shape of a sibling repo. Only a root followed by ``/`` or ending the
    # token is this repo.
    root = re.escape(str(repo_root).rstrip("/"))
    text = re.sub(root + "/", "", text)
    text = re.sub(root + r"(?![^\s'\"`])", ".", text)

    # This machine's literal account name first — it is the only layer that can
    # resolve a hyphenated name in the dash encoding (see _account_rules).
    for pattern, replacement in _account_rules(
        default_account() if account is None else account
    ):
        text = pattern.sub(replacement, text)

    text = _HOME_PATH_DIR.sub("~/", text)
    text = _HOME_PATH_BARE.sub("~", text)
    return _DASH_HOME_PATH.sub("-REDACTED", text)


def assert_publishable(document: str, account: str | None = None) -> None:
    """Raise unless the rendered document is free of every forbidden pattern.

    The gate checks this machine's literal account name in addition to the
    generic patterns. Sharing only the generic ones with the redactor is what let
    a hyphenated name pass: the redactor mangled it into a form its own pattern
    no longer matched, and the gate agreed.
    """
    name = default_account() if account is None else account
    checks = [*FORBIDDEN]
    if name:
        # A literal check for the un-redacted name. Note this is *subsumed* by
        # the generic patterns above, which are checked first — it is
        # belt-and-braces, not an independent signal.
        checks.append(
            (
                re.compile(rf"[/-](?:Users|home)[/-]{re.escape(name)}"),
                "this machine's account name",
            )
        )
        # This one IS independent: it inspects the redactor's *output shape*
        # rather than re-running the redactor's own input patterns. A
        # ``-REDACTED`` marker immediately followed by a component of the account
        # name means redaction bisected the name instead of consuming it — the
        # exact residue a hyphenated username produced before the literal rules
        # existed, and the form no input-shaped pattern can see, because the
        # ``-Users-`` that would have announced it is already gone.
        for part in name.split("-")[1:]:
            if part:
                checks.append(
                    (
                        re.compile(rf"-REDACTED-{re.escape(part)}\b"),
                        "a bisected account name left behind by redaction",
                    )
                )
    for pattern, description in checks:
        match = pattern.search(document)
        if match:
            line = document.count("\n", 0, match.start()) + 1
            raise RedactionFailure(
                f"line {line}: {description} survived redaction "
                f"({match.group(0)!r}). Refusing to write — widen the redaction "
                f"rules rather than relaxing this check."
            )


def tool_line(block: dict, repo_root: Path, account: str | None = None) -> str:
    """Render one tool call as a single line: never the full input."""
    name = str(block.get("name", "?"))
    field = _TOOL_SUMMARY_FIELD.get(name)
    raw = block.get("input") or {}
    value = raw.get(field) if field and isinstance(raw, dict) else None
    if not isinstance(value, str) or not value.strip():
        return f"`{name}`"
    summary = redact(value.strip(), repo_root, account).splitlines()[0]
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


def to_turns(records: list[dict], repo_root: Path, account: str | None = None) -> list[Turn]:
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
                cleaned = redact(str(block.get("text", "")), repo_root, account).strip()
                if cleaned:
                    texts.append(cleaned)
            else:
                tools.append(tool_line(block, repo_root, account))

        if not texts and not tools:
            continue
        turns.append(
            Turn(
                role=str(rtype),
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
    account: str | None = None,
) -> str:
    """Full pipeline: load → filter → redact → render → gate."""
    turns = select(to_turns(load(session), repo_root, account), start_at, exchanges)
    document = render(turns)
    assert_publishable(document, account)
    return document


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--session", type=Path, help="path to a session .jsonl")
    source.add_argument(
        "--project-dir", type=Path, help="a ~/.claude/projects/<slug> dir; uses its newest session"
    )
    parser.add_argument("--out", type=Path, help="write here instead of stdout")
    parser.add_argument(
        "--account",
        help="account name to redact literally (default: this machine's). Set this when "
        "rendering a transcript recorded under a different account.",
    )
    parser.add_argument("--start-at", help="begin at the first prompt containing this substring")
    parser.add_argument("--exchanges", type=int, help="how many prompts to keep from the start")
    parser.add_argument(
        "--repo-root",
        type=Path,
        help="paths under this root render repo-relative (default: git toplevel of cwd)",
    )
    args = parser.parse_args(argv)

    # Source resolution is inside the try for a disclosure reason, not a tidiness
    # one: an unhandled TranscriptError here prints a traceback whose frames
    # quote the absolute project path this tool exists to keep out of the open.
    try:
        session = args.session if args.session else latest_session(args.project_dir.expanduser())
        repo_root = args.repo_root or repo_root_of(Path.cwd())
        document = build_excerpt(
            session.expanduser(), repo_root, args.start_at, args.exchanges, args.account
        )
    except (TranscriptError, OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        # OSError et al. are caught alongside the tool's own refusals for the
        # same disclosure reason, and they are the *likelier* arrival: a typo'd
        # --session raises FileNotFoundError, whose traceback prints the
        # absolute `/Users/<name>/…` path this tool exists to keep out of the
        # open — and, being unhandled, would also skip the stale-output removal
        # below. Catching only TranscriptError guarded the rarer half.
        #
        # Remove a stale --out from an earlier run. Leaving it is the worst
        # outcome of a refusal: the command failed, but the path still holds
        # plausible-looking content that a later step would publish as fresh.
        if args.out and args.out.exists():
            try:
                args.out.unlink()
                print(f"tour_transcript: removed stale {args.out}", file=sys.stderr)
            except OSError as unlink_exc:
                # Must not escape: an unhandled OSError here prints a traceback
                # quoting the absolute path, which is the disclosure this error
                # path exists to avoid.
                print(
                    f"tour_transcript: could not remove stale output ({unlink_exc.strerror}) "
                    f"— treat that file as STALE, not as this run's result",
                    file=sys.stderr,
                )
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
