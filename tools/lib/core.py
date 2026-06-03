"""
Core utilities, constants, and shared helpers for prawduct-setup.

All constants and functions that are used across multiple commands live here.
Command-specific logic lives in init_cmd.py, migrate_cmd.py, sync_cmd.py,
and validate_cmd.py.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

FRAMEWORK_DIR = Path(__file__).resolve().parent.parent.parent
TEMPLATES_DIR = FRAMEWORK_DIR / "templates"


# =============================================================================
# Constants
# =============================================================================

try:
    PRAWDUCT_VERSION = (FRAMEWORK_DIR / "VERSION").read_text().strip()
except FileNotFoundError:
    PRAWDUCT_VERSION = "dev"

BLOCK_BEGIN = "<!-- PRAWDUCT:BEGIN -->"
BLOCK_END = "<!-- PRAWDUCT:END -->"

# Canonical list of framework-managed files. Used by create_manifest (at init)
# and run_sync (to backfill files added after a product was initialized).
# "description" is shown to the user when a file is backfilled (new capability onboarding).
MANAGED_FILES = {
    "CLAUDE.md": {
        "template": "templates/product-claude.md",
        "strategy": "block_template",
        "description": "Core principles and methodology instructions",
    },
    ".prawduct/critic-review.md": {
        "template": "templates/critic-review.md",
        "strategy": "template",
        "description": "Independent Critic review instructions (7 quality goals + coordinator pattern)",
    },
    ".prawduct/pr-review.md": {
        "template": "templates/pr-review.md",
        "strategy": "template",
        "description": "PR reviewer instructions for release-readiness assessment",
    },
    ".prawduct/build-governance.md": {
        "template": "templates/build-governance.md",
        "strategy": "template",
        "description": "Build governance reference — how to build against a plan (read before coding)",
    },
    ".claude/skills/pr/SKILL.md": {
        "template": ".claude/skills/pr/SKILL.md",
        "strategy": "template",
        "description": "/pr skill — PR lifecycle management (create, update, merge, status). Configure PR behavior in project-preferences.md",
    },
    ".claude/skills/janitor/SKILL.md": {
        "template": ".claude/skills/janitor/SKILL.md",
        "strategy": "template",
        "description": "/janitor skill — Periodic codebase maintenance (encapsulation, deduplication, cleanup)",
    },
    ".claude/skills/prawduct-doctor/SKILL.md": {
        "template": ".claude/skills/prawduct-doctor/SKILL.md",
        "strategy": "template",
        "description": "/prawduct-doctor skill — Product repo setup, health check, and repair",
    },
    ".claude/skills/learnings/SKILL.md": {
        "template": ".claude/skills/learnings/SKILL.md",
        "strategy": "template",
        "description": "/learnings skill — Look up project learnings and preferences relevant to your current task",
    },
    ".claude/skills/prawduct-advisory/SKILL.md": {
        "template": ".claude/skills/prawduct-advisory/SKILL.md",
        "strategy": "template",
        "description": "/prawduct-advisory skill — Manage post-sync advisories (list, show, dismiss, undismiss, resolve)",
    },
    ".claude/skills/backlog/SKILL.md": {
        "template": ".claude/skills/backlog/SKILL.md",
        "strategy": "template",
        "description": "/backlog skill — Structured backlog management (pick, add, find, list, update, migrate)",
    },
    ".claude/skills/critic/SKILL.md": {
        "template": "templates/skill-critic.md",
        "strategy": "template",
        "description": "/critic skill — Independent Critic review with structural tool restrictions (cannot run tests)",
    },
    "tools/product-hook": {
        "source": "tools/product-hook",
        "strategy": "always_update",
        "description": "Session governance hooks (reflection gate, Critic gate, session briefing)",
    },
    ".claude/settings.json": {
        "template": "templates/product-settings.json",
        "strategy": "merge_settings",
        "description": "Claude Code settings with hook configuration",
    },
}

# Managed directories: every matching file is synced like an always_update
# managed file, enumerated dynamically from the framework so new modules ship
# automatically without editing MANAGED_FILES. product-hook imports tools/lib
# at runtime (regen-views, operator-verification, advisories), so product repos
# MUST carry it — listing the package statically would re-introduce the
# ModuleNotFoundError class of bug every time a module is added.
MANAGED_DIRS: dict[str, dict] = {
    "tools/lib": {
        "glob": "*.py",
        "strategy": "always_update",
        "description": "product-hook runtime library (regen-views, operator-verification, advisories)",
    },
}


def effective_managed_files(framework_dir: Path) -> dict[str, dict]:
    """MANAGED_FILES plus every file under MANAGED_DIRS, enumerated from the
    framework directory.

    Managed-directory files are framework-owned (``always_update``), so they
    propagate to product repos on every sync and pick up newly-added modules
    without a code change here. Enumeration keys off ``framework_dir`` — when a
    caller passes an empty/fake framework dir (unit tests), no managed-dir files
    are added, preserving the static MANAGED_FILES set.
    """
    result: dict[str, dict] = dict(MANAGED_FILES)
    for dir_rel, dir_config in MANAGED_DIRS.items():
        src_dir = framework_dir / dir_rel
        if not src_dir.is_dir():
            continue
        for path in sorted(src_dir.glob(dir_config.get("glob", "*"))):
            if path.is_file():
                rel = f"{dir_rel}/{path.name}"
                result[rel] = {
                    "source": rel,
                    "strategy": dir_config.get("strategy", "always_update"),
                    "description": dir_config.get("description", ""),
                }
    return result


# Place-once files: created if missing, never overwritten. Template hashes
# are tracked in manifest["place_once_templates"] for drift detection.
# Shared between init_cmd.py and sync_cmd.py.
PLACE_ONCE_TEMPLATES: dict[str, str] = {
    ".prawduct/artifacts/project-preferences.md": "templates/project-preferences.md",
    ".prawduct/artifacts/boundary-patterns.md": "templates/boundary-patterns.md",
    ".prawduct/change-log.md": "templates/change-log.md",
    ".prawduct/backlog.md": "templates/backlog.md",
}

# Place-once binary files: copied without template rendering.
PLACE_ONCE_COPY: dict[str, str] = {
    "tests/conftest.py": "templates/conftest.py",
}

# Maps old file paths to new file paths. Applied during sync before the
# MANAGED_FILES loop, so product repos get file moves automatically.
FILE_RENAMES: dict[str, str] = {
    ".claude/commands/pr.md": ".claude/skills/pr/SKILL.md",
    ".claude/commands/janitor.md": ".claude/skills/janitor/SKILL.md",
    ".claude/skills/prawduct-setup/SKILL.md": ".claude/skills/prawduct-doctor/SKILL.md",
}

# Skill files placed during init. Each tuple: (skill_name, source_path).
# Source is either the framework's own .claude/skills/ copy or templates/.
SKILL_PLACEMENTS: list[tuple[str, Path]] = [
    ("pr", FRAMEWORK_DIR / ".claude" / "skills" / "pr" / "SKILL.md"),
    ("janitor", FRAMEWORK_DIR / ".claude" / "skills" / "janitor" / "SKILL.md"),
    ("prawduct-doctor", FRAMEWORK_DIR / ".claude" / "skills" / "prawduct-doctor" / "SKILL.md"),
    ("learnings", FRAMEWORK_DIR / ".claude" / "skills" / "learnings" / "SKILL.md"),
    ("prawduct-advisory", FRAMEWORK_DIR / ".claude" / "skills" / "prawduct-advisory" / "SKILL.md"),
    ("backlog", FRAMEWORK_DIR / ".claude" / "skills" / "backlog" / "SKILL.md"),
    ("critic", TEMPLATES_DIR / "skill-critic.md"),
]

# Session files that should be gitignored in product repos
GITIGNORE_ENTRIES = [
    ".claude/settings.local.json",
    ".prawduct/.critic-findings.json",
    ".prawduct/.test-evidence.json",
    ".prawduct/.pr-reviews/",
    ".prawduct/.session-git-baseline",
    ".prawduct/.session-handoff.md",
    ".prawduct/.session-reflected",
    ".prawduct/.session-start",
    ".prawduct/.subagent-briefing.md",
    ".prawduct/.gates-waived",
    ".prawduct/.sync-pending",
    ".prawduct/.advisories.json",
    ".prawduct/reflections.md",
    ".prawduct/sync-manifest.json",
    ".prawduct/artifacts/build-plan.md",
    "__pycache__/",
]

# Migration-era gitignore constants
V4_GITIGNORE_ENTRIES = [
    ".claude/settings.local.json",
    ".prawduct/.critic-findings.json",
    ".prawduct/.test-evidence.json",
    ".prawduct/.pr-reviews/",
    ".prawduct/.session-git-baseline",
    ".prawduct/.session-handoff.md",
    ".prawduct/.session-reflected",
    ".prawduct/.session-start",
    ".prawduct/.subagent-briefing.md",
    ".prawduct/reflections.md",
    ".prawduct/sync-manifest.json",
    ".prawduct/artifacts/build-plan.md",
    "__pycache__/",
]

V3_GITIGNORE_ENTRIES = [
    ".claude/settings.local.json",
    ".prawduct/.critic-findings.json",
    ".prawduct/.session-reflected",
    ".prawduct/.session-start",
    "__pycache__/",
]

V1_GITIGNORE_ENTRIES = [
    ".prawduct/traces/",
    ".prawduct/framework-observations/",
    ".prawduct/.cross-repo-edits",
    ".prawduct/.session-governance.json",
    ".prawduct/.orchestrator-activated",
]

V1_SESSION_FILES = [
    ".prawduct/.session-governance.json",
    ".prawduct/.orchestrator-activated",
    ".prawduct/.skill-context.json",
    ".prawduct/.active-skill",
]


# =============================================================================
# Core utilities
# =============================================================================


def log(msg: str) -> None:
    """Print status to stderr."""
    print(msg, file=sys.stderr)


def ensure_dir(path: Path) -> bool:
    """Create directory if missing. Returns True if created."""
    if path.is_dir():
        return False
    path.mkdir(parents=True, exist_ok=True)
    return True


# Optional project-state pointer naming the active build plan (relative to the
# `.prawduct/` dir). When unset, tooling uses the conventional default below, so
# repos that don't set it keep their existing behavior.
BUILD_PLAN_POINTER_KEY = "active_build_plan"
DEFAULT_BUILD_PLAN_REL = "artifacts/build-plan.md"


def read_str_yaml_key(state_path: Path, key: str) -> str | None:
    """Value of a top-level (column-0) ``key: value`` scalar, or None.

    Mirrors the column-0 idiom used by ``is_views_enabled`` and product-hook's
    ``_read_bool_yaml_key`` — no PyYAML dependency, fail-soft to None on a
    missing/unreadable file or absent key. Surrounding quotes and inline ``#``
    comments are stripped; an empty value reads as None.
    """
    try:
        content = state_path.read_text(encoding="utf-8")
    except OSError:
        return None
    needle = f"{key}:"
    for raw in content.splitlines():
        if raw[:1] in (" ", "\t"):
            continue
        line = raw.split("#", 1)[0].rstrip()
        if not line.startswith(needle):
            continue
        value = line.split(":", 1)[1].strip().strip("\"'")
        return value or None
    return None


def resolve_build_plan_path(prawduct_dir: Path) -> Path:
    """Resolve the active build-plan path (supports standard + scope-named plans).

    Reads an optional ``active_build_plan:`` pointer (a path relative to the
    ``.prawduct/`` dir) from ``project-state.yaml``; when set, that file is the
    active plan, letting a project name its plan by scope
    (``artifacts/v1.6.0-foo-plan.md``). When the pointer is absent, falls back to
    the conventional ``artifacts/build-plan.md`` — so repos that don't set it
    behave exactly as before. The returned path may not exist; callers treat a
    missing plan as "no active build plan."

    Kept in sync with the inline mirror in ``tools/product-hook``
    (``_resolve_build_plan_path``), which cannot import this module in product
    repos — a parity test pins the two together.
    """
    pointer = read_str_yaml_key(prawduct_dir / "project-state.yaml", BUILD_PLAN_POINTER_KEY)
    if pointer:
        return prawduct_dir / pointer
    return prawduct_dir / DEFAULT_BUILD_PLAN_REL


def compute_hash(path: Path) -> str | None:
    """Compute SHA-256 hex digest of a file's contents. Returns None if file missing."""
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def extract_block(content: str) -> tuple[str | None, str, str]:
    """Extract content between PRAWDUCT markers.

    Returns (block, before, after) where before + block + after == content.
    Returns (None, content, "") if markers are missing or malformed
    (e.g. BEGIN without END, or END before BEGIN).
    """
    begin_idx = content.find(BLOCK_BEGIN)
    end_idx = content.find(BLOCK_END)

    if begin_idx == -1 or end_idx == -1 or end_idx <= begin_idx:
        return (None, content, "")

    before = content[:begin_idx]
    block = content[begin_idx : end_idx + len(BLOCK_END)]
    after = content[end_idx + len(BLOCK_END) :]

    return (block, before, after)


def compute_block_hash(content: str) -> str | None:
    """SHA-256 of just the block content between markers. None if no markers."""
    block, _, _ = extract_block(content)
    if block is None:
        return None
    return hashlib.sha256(block.encode()).hexdigest()


def load_json(path: Path) -> dict:
    """Read and parse a JSON file. Raises on missing file or invalid JSON."""
    return json.loads(path.read_text())


def render_template(template_path: Path, subs: dict[str, str]) -> str:
    """Read a template file and apply variable substitutions."""
    content = template_path.read_text()
    for key, value in subs.items():
        content = content.replace(key, value)
    return content


def merge_settings(
    dst: Path,
    template_path: Path,
    subs: dict[str, str] | None = None,
    *,
    legacy_cleanup: bool = False,
) -> bool:
    """Create or merge .claude/settings.json.

    Merges hooks and companyAnnouncements from template into existing settings.
    Preserves user hooks and other settings keys. Applies subs to template before
    parsing (for banner {{PRODUCT_NAME}} substitution).

    With legacy_cleanup=True (migration path): also removes v1/v3 hooks and
    v1 statusLine references.

    Returns True if file was written.
    """
    template_text = template_path.read_text()
    if subs:
        for key, value in subs.items():
            template_text = template_text.replace(key, value)
    template = json.loads(template_text)

    if not dst.is_file():
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(json.dumps(template, indent=2) + "\n")
        return True

    try:
        existing = load_json(dst)
    except json.JSONDecodeError:
        log(f"  ! Could not parse {dst.name} — skipping merge")
        return False

    template_hooks = template.get("hooks", {})

    if legacy_cleanup:
        # Migration path: strip v1/v3 hooks AND current v4 hooks, keep user hooks.
        v1_markers = ["framework-path", "governance-hook", "prawduct-statusline"]

        def _is_v1_hook_entry(entry: dict) -> bool:
            for hook in entry.get("hooks", []):
                cmd = hook.get("command", "")
                if any(marker in cmd for marker in v1_markers):
                    return True
            return False

        v4_commands: set[str] = set()
        for entries in template_hooks.values():
            for entry in entries:
                for hook in entry.get("hooks", []):
                    if hook.get("type") == "command":
                        v4_commands.add(hook["command"])

        def _is_old_prawduct_hook(entry: dict) -> bool:
            if _is_v1_hook_entry(entry):
                return True
            for hook in entry.get("hooks", []):
                cmd = hook.get("command", "")
                if "product-hook" in cmd and not cmd.startswith("python3 "):
                    return True
            return False

        merged_hooks: dict = dict(template_hooks)
        for event, entries in existing.get("hooks", {}).items():
            if event not in merged_hooks:
                user_entries = [e for e in entries if not _is_old_prawduct_hook(e)]
                if user_entries:
                    merged_hooks[event] = user_entries
                continue

            user_entries = []
            for entry in entries:
                if _is_old_prawduct_hook(entry):
                    continue
                is_v4 = any(
                    hook.get("command") in v4_commands
                    for hook in entry.get("hooks", [])
                    if hook.get("type") == "command"
                )
                if not is_v4:
                    user_entries.append(entry)

            if user_entries:
                merged_hooks[event] = merged_hooks[event] + user_entries
    else:
        # Normal sync: strip current prawduct hooks, keep user hooks.
        def _is_prawduct_hook(entry: dict) -> bool:
            for hook in entry.get("hooks", []):
                if hook.get("type") != "command":
                    continue
                cmd = hook.get("command", "")
                if '/product-hook"' in cmd or "/product-hook " in cmd or cmd.endswith("/product-hook"):
                    return True
            return False

        merged_hooks = dict(template_hooks)
        for event, entries in existing.get("hooks", {}).items():
            user_entries = [e for e in entries if not _is_prawduct_hook(e)]

            if event not in merged_hooks:
                if user_entries:
                    merged_hooks[event] = user_entries
            else:
                if user_entries:
                    merged_hooks[event] = merged_hooks[event] + user_entries

    # Preserve other settings keys, but always update banner from template
    merged = dict(existing)
    merged["hooks"] = merged_hooks

    # Legacy cleanup: remove v1 statusLine if it references prawduct
    if legacy_cleanup and "statusLine" in merged:
        status_line = merged["statusLine"]
        if isinstance(status_line, str) and "prawduct" in status_line.lower():
            del merged["statusLine"]
        elif isinstance(status_line, dict):
            cmd = status_line.get("command", "")
            if "prawduct" in cmd.lower():
                del merged["statusLine"]

    # Always update companyAnnouncements from template (framework-managed)
    if "companyAnnouncements" in template:
        merged["companyAnnouncements"] = template["companyAnnouncements"]

    if json.dumps(merged, sort_keys=True) == json.dumps(existing, sort_keys=True):
        return False

    dst.write_text(json.dumps(merged, indent=2) + "\n")
    return True


def create_manifest(
    product_dir: Path,
    framework_dir: Path,
    product_name: str,
    file_hashes: dict[str, str | None],
) -> dict:
    """Build a sync manifest from the given file hashes.

    file_hashes maps relative file paths to their SHA-256 hex digests (or None).
    """
    files: dict[str, dict] = {}

    for rel_path, config in effective_managed_files(framework_dir).items():
        entry = dict(config)
        entry["generated_hash"] = file_hashes.get(rel_path)
        files[rel_path] = entry

    return {
        "format_version": 2,
        "framework_source": str(framework_dir),
        "framework_version": PRAWDUCT_VERSION,
        "product_name": product_name,
        "auto_pull": True,
        "last_sync": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "files": files,
    }


# =============================================================================
# Framework resolution
# =============================================================================


def _resolve_framework_dir(
    manifest: dict, cli_framework_dir: str | None, product_dir: Path | None = None
) -> Path | None:
    """Resolve the framework directory from CLI arg, env var, manifest, or sibling.

    Resolution order:
      1. --framework-dir CLI argument (explicit override; fail if invalid)
      2. PRAWDUCT_FRAMEWORK_DIR env var (explicit override; fail if invalid)
      3. framework_source from manifest (recorded at init; fall through if stale)
      4. Sibling ../prawduct relative to product dir (convention-based discovery)
    """
    # 1. CLI argument
    if cli_framework_dir:
        p = Path(cli_framework_dir).resolve()
        if p.is_dir():
            return p
        return None

    # 2. Environment variable
    env_dir = os.environ.get("PRAWDUCT_FRAMEWORK_DIR")
    if env_dir:
        p = Path(env_dir).resolve()
        if p.is_dir():
            return p
        return None

    # 3. Manifest value
    source = manifest.get("framework_source", "")
    if source:
        p = Path(source).resolve()
        if p.is_dir():
            return p

    # 4. Sibling ../prawduct relative to product dir
    if product_dir:
        sibling = (product_dir.parent / "prawduct").resolve()
        if sibling.is_dir():
            return sibling

    return None


def _try_pull_framework(fw_dir: Path, auto_pull: bool) -> list[str]:
    """Best-effort git pull/fetch of the framework repo before syncing.

    When auto_pull is True: runs ``git pull --ff-only`` (safe fast-forward).
    When auto_pull is False: runs ``git fetch`` and reports if behind upstream.

    Returns a list of human-readable notes (may be empty). Never raises.
    """
    notes: list[str] = []
    try:
        # Verify fw_dir is inside a git repo
        result = subprocess.run(
            ["git", "rev-parse", "--git-dir"],
            capture_output=True,
            text=True,
            cwd=str(fw_dir),
            timeout=30,
        )
        if result.returncode != 0:
            return notes  # Not a git repo — silently skip

        if auto_pull:
            # Check for dirty working tree
            status = subprocess.run(
                ["git", "status", "--porcelain"],
                capture_output=True,
                text=True,
                cwd=str(fw_dir),
                timeout=30,
            )
            if status.returncode == 0 and status.stdout.strip():
                notes.append("Framework has uncommitted changes — skipping pull")
                return notes

            # Fast-forward pull
            pull = subprocess.run(
                ["git", "pull", "--ff-only"],
                capture_output=True,
                text=True,
                cwd=str(fw_dir),
                timeout=30,
            )
            if pull.returncode == 0:
                if "Already up to date" not in pull.stdout:
                    notes.append("Framework updated via git pull")
            else:
                stderr = pull.stderr.strip()
                if "Not possible to fast-forward" in stderr or "fatal" in stderr:
                    notes.append("Framework pull failed (not fast-forwardable) — run git pull manually")
                else:
                    notes.append("Framework pull failed — run git pull manually")
        else:
            # Advisory mode: fetch + check if behind
            fetch = subprocess.run(
                ["git", "fetch", "--quiet"],
                capture_output=True,
                text=True,
                cwd=str(fw_dir),
                timeout=30,
            )
            if fetch.returncode != 0:
                return notes  # Fetch failed — silently skip

            behind = subprocess.run(
                ["git", "rev-list", "--count", "HEAD..@{upstream}"],
                capture_output=True,
                text=True,
                cwd=str(fw_dir),
                timeout=30,
            )
            if behind.returncode == 0:
                count = behind.stdout.strip()
                if count and int(count) > 0:
                    notes.append(f"Framework is {count} commit(s) behind upstream — consider running git pull")

    except FileNotFoundError:
        pass  # git not on PATH
    except subprocess.TimeoutExpired:
        notes.append("Framework git operation timed out")
    except Exception:  # prawduct:ok-broad-except — sync helper must never block session start
        pass

    return notes


# =============================================================================
# Template / file operations
# =============================================================================


def write_template(src: Path, dst: Path, subs: dict[str, str], *, overwrite: bool = False) -> bool:
    """Copy a template with variable substitution.

    Without overwrite: skips if dst exists.
    With overwrite: idempotent via content comparison.
    Returns True if file was written.
    """
    content = render_template(src, subs)

    if dst.is_file():
        if not overwrite:
            return False
        if dst.read_text() == content:
            return False  # Already up to date

    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(content)
    return True


def copy_hook(src: Path, dst: Path) -> bool:
    """Copy a hook script and make it executable. Updates if content changed.
    Returns True if file was written."""
    src_bytes = src.read_bytes()

    if dst.is_file():
        if dst.read_bytes() == src_bytes:
            return False  # Already up to date
        # Hook content changed — update it (hooks should stay current)
        dst.write_bytes(src_bytes)
        dst.chmod(dst.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        return True

    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    dst.chmod(dst.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return True


def update_gitignore(target: Path) -> dict:
    """Add prawduct entries to .gitignore and remove incorrect ones.

    Managed files (MANAGED_FILES) should be committed, not gitignored.
    Session files (GITIGNORE_ENTRIES) should be gitignored.
    Returns dict with 'modified' bool and 'unignored' list of paths
    that were removed from .gitignore (caller should advise user to
    git-add these).
    """
    gitignore = target / ".gitignore"

    if gitignore.is_file():
        content = gitignore.read_text()
        existing_lines = set(content.splitlines())
    else:
        content = ""
        existing_lines = set()

    modified = False
    unignored: list[str] = []

    # Remove lines that gitignore managed files (they should be committed)
    incorrectly_ignored = set()
    for rel_path in MANAGED_FILES:
        if rel_path in existing_lines:
            incorrectly_ignored.add(rel_path)

    if incorrectly_ignored:
        lines = content.splitlines(keepends=True)
        filtered = [line for line in lines if line.rstrip("\n") not in incorrectly_ignored]
        content = "".join(filtered)
        existing_lines -= incorrectly_ignored
        unignored = sorted(incorrectly_ignored)
        modified = True

    # Add missing session file entries
    missing = [e for e in GITIGNORE_ENTRIES if e not in existing_lines]
    if missing:
        parts = []
        if content and not content.endswith("\n"):
            parts.append("\n")
        if content.strip():
            parts.append("\n")
        parts.append("# Prawduct session files\n")
        for entry in missing:
            parts.append(entry + "\n")
        content += "".join(parts)
        modified = True

    if modified:
        gitignore.write_text(content)

    return {"modified": modified, "unignored": unignored}


def untrack_gitignored_files(target: Path) -> list[str]:
    """Remove gitignored session files from git tracking without deleting them.

    Runs 'git rm --cached' for any GITIGNORE_ENTRIES path that is currently
    tracked by git. Safe to call even if the repo has no such tracked files.
    Returns a list of paths that were untracked (may be empty).
    """
    # Verify this is a git repo
    check = subprocess.run(
        ["git", "rev-parse", "--git-dir"],
        capture_output=True,
        text=True,
        cwd=str(target),
        timeout=10,
    )
    if check.returncode != 0:
        return []

    untracked: list[str] = []
    for entry in GITIGNORE_ENTRIES:
        # Strip trailing slash on directory patterns (e.g. "__pycache__/").
        # ls-files needs the bare path; rm needs `-r` to recurse into the dir.
        rel = entry.rstrip("/")
        result = subprocess.run(
            ["git", "ls-files", "--error-unmatch", rel],
            capture_output=True,
            text=True,
            cwd=str(target),
            timeout=10,
        )
        if result.returncode != 0:
            continue  # Not tracked
        # File is tracked — remove it from the index. -r is required for
        # directory entries (e.g. .prawduct/.pr-reviews/) and harmless for files.
        rm = subprocess.run(
            ["git", "rm", "--cached", "--quiet", "-r", rel],
            capture_output=True,
            text=True,
            cwd=str(target),
            timeout=10,
        )
        if rm.returncode == 0:
            untracked.append(rel)

    return untracked


# =============================================================================
# Version detection
# =============================================================================


def detect_version(target: Path) -> str:
    """Detect repo version. Returns 'v1', 'v3', 'v4', 'v5', 'partial', or 'unknown'."""
    has_framework_path = (target / ".prawduct" / "framework-path").is_file()
    has_product_hook = (target / "tools" / "product-hook").is_file()
    has_sync_manifest = (target / ".prawduct" / "sync-manifest.json").is_file()

    if has_framework_path and not has_product_hook:
        return "v1"
    if has_framework_path and has_product_hook:
        return "partial"
    if has_product_hook and has_sync_manifest:
        # Distinguish v4 from v5 by manifest format_version
        try:
            manifest = load_json(
                target / ".prawduct" / "sync-manifest.json"
            )
            if manifest.get("format_version", 1) >= 2:
                return "v5"
        except (json.JSONDecodeError, OSError):
            pass
        return "v4"
    if has_product_hook and not has_framework_path:
        return "v3"
    return "unknown"


def infer_product_name(target: Path) -> str | None:
    """Read product_identity.name from project-state.yaml via regex.

    No PyYAML dependency — scans line by line for the name field under
    product_identity. Returns None if the file is missing, the field is
    absent, or the value is a template placeholder.
    """
    state_file = target / ".prawduct" / "project-state.yaml"
    if not state_file.is_file():
        return None

    in_product_identity = False
    for line in state_file.read_text().splitlines():
        stripped = line.strip()

        # Track when we're inside product_identity block
        if stripped == "product_identity:" or stripped.startswith("product_identity:"):
            in_product_identity = True
            continue

        # Exit block on unindented line (new top-level key)
        if in_product_identity and line and not line[0].isspace():
            in_product_identity = False
            continue

        if in_product_identity:
            match = re.match(r'\s*name:\s*["\']?([^"\'#\n]+?)["\']?\s*$', line)
            if match:
                name = match.group(1).strip()
                if name and "{{" not in name and name != "null":
                    return name

    return None


# =============================================================================
# Migration-shared operations
# =============================================================================


def write_template_overwrite(src: Path, dst: Path, subs: dict[str, str]) -> bool:
    """Compat alias for write_template(overwrite=True)."""
    return write_template(src, dst, subs, overwrite=True)


def replace_settings(dst: Path, template_path: Path, subs: dict[str, str] | None = None) -> bool:
    """Compat alias for merge_settings(legacy_cleanup=True)."""
    return merge_settings(dst, template_path, subs, legacy_cleanup=True)
