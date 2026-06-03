"""Critic mode inference — picks the right ``/critic`` mode from git +
build-plan state so the builder doesn't have to declare it at every chunk.

Explicit ``$ARGUMENTS`` always wins (override path). When ``$ARGUMENTS`` is
empty / None / unrecognized, :func:`infer_mode` walks four rules in
precedence order and returns the first that fires:

  1. ``verify-resolutions`` — prior ``.critic-findings.json`` has
     BLOCKING/WARNING findings + ``commit_reviewed`` anchor resolves +
     uncommitted diff is non-empty AND is a subset of prior
     ``files_reviewed``. Signal: builder is in the middle of fixing
     findings from the last review.
  2. ``cumulative`` — working tree is clean (no uncommitted code) AND
     branch is ≥2 commits ahead of the detected base branch AND no
     ``cumulative``-mode findings file exists for current HEAD. Signal:
     builder has shipped chunks and is at the ``/pr create`` precondition
     point.
  3. ``final`` — active build plan with exactly one unchecked chunk left
     AND uncommitted work is present (the builder is on the last chunk),
     OR no build plan + uncommitted diff has ≥5 files (medium+
     non-chunked work).
  4. ``chunk`` when an active build plan grounds the choice (default
     for mid-plan reviews); ``final`` otherwise (no plan + no other
     rule fired — fail-safe to thoroughness, matching the SKILL's
     historical "missing/unrecognized → final" norm).

Deviation from build-plan rule 2: the spec reads "branch ahead of base by
≥2 commits AND no cumulative-mode record exists for the current HEAD"
with no working-tree-clean guard. Implemented WITH the clean-tree guard
so the rule doesn't over-fire mid-chunk-3-of-5 (which would silently
demote ``chunk``-mode reviews to 4-10 min ``cumulative`` runs at every
commit). The user-feedback motivation for the whole proportionality
thread was reducing review latency for small fixes — over-firing
cumulative would undo that. The guard preserves the spec's intent (run
cumulative when about to PR) without the cost.

Pure-ish: takes ``project_dir``, reads files under it, runs ``git``
subprocesses against it. Deterministic given fixed git state. Imports
only from the stdlib — no ``tools.product-hook`` dependency (per the
v1.5 Chunk 03 plan: "Imports only `tools.lib.core`"; product-hook
helpers are intentionally re-implemented here to keep the module
lightweight and importable from the slash-command shim).
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from .core import resolve_build_plan_path

# Verbose-string mode constants — used to recognize prior findings'
# ``mode`` field. Must stay in lockstep with ``tools/product-hook``'s
# ``_CRITIC_MODE_*`` constants. (Persisted form is verbose; caller-side
# short tokens are what we return / accept as ``args``.)
_MODE_VERIFY_RESOLUTIONS_VERBOSE = (
    "verify-resolutions (delta review, prior findings only)"
)
_MODE_CUMULATIVE_VERBOSE = "cumulative (bundle review, ready for merge)"

# Short-token caller-side mode names — what ``$ARGUMENTS`` carries and
# what :func:`infer_mode` returns as the first element of its tuple.
_VALID_ARG_MODES = frozenset({
    "chunk",
    "final",
    "cumulative",
    "verify-resolutions",
})

# Candidate base branches probed in order — first one that resolves wins.
# Mirrors the convention used by ``/pr`` and the cumulative-Critic gate
# (typically ``main``; ``develop`` for gitflow projects).
_DEFAULT_BASE_BRANCHES = ("main", "master", "develop")

# Mirrors ``_METADATA_PREFIXES`` in ``tools/product-hook``. Kept in sync
# manually — duplication is acceptable for this small set; extracting to
# ``tools.lib.core`` would expand core's surface for one consumer.
_METADATA_PREFIXES = (
    ".prawduct/",
    ".claude/settings.json",
    ".claude/skills/",
    "tools/product-hook",
)


def infer_mode(
    project_dir: Path | str,
    args: str | None = None,
) -> tuple[str, str]:
    """Infer the right ``/critic`` mode for the current project state.

    Parameters
    ----------
    project_dir : Path | str
        Project root (contains ``.prawduct/``). Coerced to ``Path``.
    args : str | None
        The ``$ARGUMENTS`` string passed to ``/critic``. When non-empty
        and parseable as one of the recognized mode tokens, that token
        wins outright (rationale ``"explicit-args"``). Empty / None /
        unrecognized → trigger inference.

    Returns
    -------
    (mode, rationale) : tuple[str, str]
        ``mode`` is the short-token form (``chunk`` / ``final`` /
        ``cumulative`` / ``verify-resolutions``). ``rationale`` is a
        human-readable string suitable both for stdout reporting and the
        ``mode_chosen_by`` field in ``.critic-findings.json``.
    """
    project_dir = Path(project_dir)

    if args is not None:
        stripped = args.strip()
        if stripped:
            token = stripped.split()[0]
            if token in _VALID_ARG_MODES:
                return token, "explicit-args"

    prawduct_dir = project_dir / ".prawduct"

    if _rule_verify_resolutions_fires(prawduct_dir, project_dir):
        return "verify-resolutions", (
            "rule-1 verify-resolutions: prior findings have actionable "
            "(BLOCKING/WARNING) entries with a resolvable commit_reviewed "
            "anchor, and the current uncommitted diff is a non-empty "
            "subset of prior files_reviewed (builder is mid-fix)"
        )

    cumulative_reason = _rule_cumulative_fires(prawduct_dir, project_dir)
    if cumulative_reason:
        return "cumulative", f"rule-2 cumulative: {cumulative_reason}"

    final_reason = _rule_final_fires(prawduct_dir, project_dir)
    if final_reason:
        return "final", f"rule-3 final: {final_reason}"

    # Rule 4: chunk only when an active build plan grounds the choice;
    # otherwise fall through to ``final`` (the historical fail-safe norm
    # documented in the SKILL files). Without a plan there's no "chunk"
    # for chunk-mode to scope to — defaulting to ``final`` matches the
    # rule "missing/unrecognized → final" the SKILL has always promised.
    total, _complete = _count_build_plan_chunks(prawduct_dir)
    if total > 0:
        return "chunk", (
            "rule-4 chunk: active build plan, prior chunks committed, "
            "no fix-in-progress signal, no cumulative precondition"
        )
    return "final", (
        "rule-4 final: no active build plan and no other rule fired — "
        "fail-safe to thoroughness"
    )


# ---------------------------------------------------------------------------
# Rule predicates
# ---------------------------------------------------------------------------


def _rule_verify_resolutions_fires(
    prawduct_dir: Path, project_dir: Path
) -> bool:
    """Rule 1: prior findings + anchor resolves + diff ⊆ prior scope."""
    findings_path = prawduct_dir / ".critic-findings.json"
    if not findings_path.is_file():
        return False
    try:
        data = json.loads(findings_path.read_text())
    except (json.JSONDecodeError, OSError):
        return False

    commit_reviewed = data.get("commit_reviewed")
    if not isinstance(commit_reviewed, str) or not commit_reviewed.strip():
        return False

    findings = data.get("findings")
    if not isinstance(findings, list):
        return False
    actionable = [
        f for f in findings
        if isinstance(f, dict) and f.get("severity") in ("blocking", "warning")
    ]
    if not actionable:
        return False

    prior_files = data.get("files_reviewed")
    if not isinstance(prior_files, list) or not prior_files:
        return False
    prior_set = {f for f in prior_files if isinstance(f, str) and f.strip()}
    if not prior_set:
        return False

    if not _commit_resolves(project_dir, commit_reviewed):
        return False

    diff_files = _get_uncommitted_code_files(project_dir)
    if not diff_files:
        return False

    # Subset check: every uncommitted file must be in the prior review's
    # surface. Even one file outside scope means the builder added new
    # work alongside the fix — that's a chunk/final case, not a verify
    # pass. (Symmetric with ``_verify_resolutions_gate_check`` in
    # product-hook; same "diff ⊆ scope" contract.)
    return diff_files.issubset(prior_set)


def _rule_cumulative_fires(
    prawduct_dir: Path, project_dir: Path
) -> str:
    """Rule 2: clean tree + ≥2 commits ahead + no fresh cumulative record.

    Returns rationale string when the rule fires, empty string otherwise.
    """
    # Clean working tree — see module docstring's deviation note for why
    # this guard is added on top of the spec.
    if _get_uncommitted_code_files(project_dir):
        return ""

    base_branch = _detect_base_branch(project_dir)
    if not base_branch:
        return ""

    commits_ahead = _commits_ahead_of_base(project_dir, base_branch)
    if commits_ahead < 2:
        return ""

    # Skip if a cumulative-mode record already covers current HEAD.
    head_sha = _git_head_sha(project_dir)
    findings_path = prawduct_dir / ".critic-findings.json"
    if head_sha and findings_path.is_file():
        try:
            data = json.loads(findings_path.read_text())
        except (json.JSONDecodeError, OSError):
            data = {}
        if (
            data.get("mode") == _MODE_CUMULATIVE_VERBOSE
            and data.get("commit_reviewed") == head_sha
        ):
            return ""

    return (
        f"branch is {commits_ahead} commits ahead of {base_branch}, "
        "working tree clean, no fresh cumulative-mode record for "
        "current HEAD"
    )


def _rule_final_fires(prawduct_dir: Path, project_dir: Path) -> str:
    """Rule 3: last unchecked chunk in progress, or no-plan medium+ work.

    Returns rationale string when the rule fires, empty string otherwise.
    """
    total, complete = _count_build_plan_chunks(prawduct_dir)
    if total > 0:
        # Active build plan.
        unchecked = total - complete
        if unchecked == 1 and _get_uncommitted_code_files(project_dir):
            return (
                f"last unchecked chunk of {total}-chunk plan is in "
                f"progress ({complete} marked [x], current chunk has "
                "uncommitted work)"
            )
        return ""

    # No active plan — fall back to size-based final for medium+ work.
    diff_files = _get_uncommitted_code_files(project_dir)
    if len(diff_files) >= 5:
        return (
            f"no build plan, session diff has {len(diff_files)} changed "
            "files (medium+ work — full review warranted)"
        )
    return ""


# ---------------------------------------------------------------------------
# Internal helpers — git + build-plan parsing
# ---------------------------------------------------------------------------


def _is_metadata_path(filepath: str) -> bool:
    """Mirrors ``tools/product-hook``'s ``_is_metadata_path``."""
    return any(filepath.startswith(p) for p in _METADATA_PREFIXES)


def _get_uncommitted_code_files(project_dir: Path) -> set[str]:
    """Return uncommitted-change file paths (vs HEAD), minus metadata.

    Includes modifications, staged changes, untracked files. Rename
    targets are returned (porcelain ``XY <old> -> <new>``). Uses
    ``--untracked-files=all`` so a new directory expands to per-file
    entries rather than collapsing to ``?? subdir/`` (the default
    ``--untracked-files=normal`` undercounts new directories — caught
    by ``test_wins_for_no_plan_medium_plus_work``).
    """
    proc = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=str(project_dir),
        capture_output=True,
        text=True,
        timeout=10,
    )
    if proc.returncode != 0:
        return set()
    files: set[str] = set()
    for line in proc.stdout.splitlines():
        if len(line) < 4:
            continue
        path = line[3:].strip()
        if " -> " in path:
            path = path.split(" -> ", 1)[1].strip()
        # Strip optional surrounding quotes (porcelain quotes paths
        # containing special chars).
        if path.startswith('"') and path.endswith('"'):
            path = path[1:-1]
        if path and not _is_metadata_path(path):
            files.add(path)
    return files


def _commit_resolves(project_dir: Path, sha: str) -> bool:
    """True iff ``sha`` resolves to a commit in this repo."""
    proc = subprocess.run(
        ["git", "rev-parse", "--verify", f"{sha}^{{commit}}"],
        cwd=str(project_dir),
        capture_output=True,
        text=True,
        timeout=10,
    )
    return proc.returncode == 0


def _detect_base_branch(project_dir: Path) -> str:
    """First ``_DEFAULT_BASE_BRANCHES`` candidate that resolves, or ``""``."""
    for candidate in _DEFAULT_BASE_BRANCHES:
        proc = subprocess.run(
            ["git", "rev-parse", "--verify", "--quiet", candidate],
            cwd=str(project_dir),
            capture_output=True,
            text=True,
            timeout=10,
        )
        if proc.returncode == 0:
            return candidate
    return ""


def _commits_ahead_of_base(project_dir: Path, base: str) -> int:
    """Number of commits on HEAD since merge-base with ``base``. ``-1`` on failure."""
    proc = subprocess.run(
        ["git", "rev-list", "--count", f"{base}..HEAD"],
        cwd=str(project_dir),
        capture_output=True,
        text=True,
        timeout=10,
    )
    if proc.returncode != 0:
        return -1
    try:
        return int(proc.stdout.strip())
    except ValueError:
        return -1


def _git_head_sha(project_dir: Path) -> str:
    """``git rev-parse HEAD`` or ``""`` on failure."""
    proc = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=str(project_dir),
        capture_output=True,
        text=True,
        timeout=10,
    )
    if proc.returncode != 0:
        return ""
    return proc.stdout.strip()


def _count_build_plan_chunks(prawduct_dir: Path) -> tuple[int, int]:
    """Count chunks in the active build plan's Status section.

    Mirrors ``tools/product-hook``'s ``_count_build_plan_chunks``. Resolves the
    plan via the ``active_build_plan:`` pointer (falls back to
    ``artifacts/build-plan.md``), so scope-named plans are counted too.
    Returns ``(total, complete)``; ``(0, 0)`` if plan/Status absent.
    """
    plan_path = resolve_build_plan_path(prawduct_dir)
    if not plan_path.is_file():
        return 0, 0
    try:
        content = plan_path.read_text()
    except OSError:
        return 0, 0
    in_status = False
    in_comment = False
    total = 0
    complete = 0
    for line in content.splitlines():
        stripped = line.strip()
        if stripped == "## Status":
            in_status = True
            continue
        if not in_status:
            continue
        if stripped.startswith("## ") and stripped != "## Status":
            break
        if "<!--" in stripped:
            in_comment = True
        if "-->" in stripped:
            in_comment = False
            continue
        if in_comment:
            continue
        if stripped.startswith("- [ ]"):
            total += 1
        elif stripped.startswith("- [x]") or stripped.startswith("- [X]"):
            total += 1
            complete += 1
    return total, complete
