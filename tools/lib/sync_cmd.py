"""
Sync command for prawduct product repos.

Syncs product repo files with framework template updates, handling
manifests, renames, version migrations, and place-once files.
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import shutil
import stat
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from .core import (
    BLOCK_BEGIN,
    BLOCK_END,
    FILE_RENAMES,
    MANAGED_FILES,
    PLACE_ONCE_COPY,
    PLACE_ONCE_TEMPLATES,
    PRAWDUCT_VERSION,
    _resolve_framework_dir,
    _try_pull_framework,
    compute_block_hash,
    compute_hash,
    effective_managed_files,
    extract_block,
    infer_product_name,
    load_json,
    merge_settings,
    render_template,
    untrack_gitignored_files,
    update_gitignore,
)
from .advisory_store import run_sync_advisories
from .migrate_cmd import (
    enable_v1_4_views,
    migrate_backlog,
    migrate_change_log,
    migrate_project_state_v5,
    split_learnings_v5,
)


def _get_framework_head_commit(fw_dir: Path) -> str | None:
    """Return short SHA of framework HEAD, or None if fw_dir is not a git repo
    or git is unavailable. Used to record what commit a sync was anchored to.
    """
    try:
        result = subprocess.run(
            ["git", "-C", str(fw_dir), "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except Exception:  # prawduct:ok-broad-except — best-effort lookup at sync time
        pass
    return None


def _get_template_last_change(fw_dir: Path, template_rel: str) -> dict[str, str] | None:
    """Return the most recent commit that modified the given template, as
    {commit, date, subject}, or None when not derivable (not a git repo,
    template never committed, etc.). Used to enrich template-drift advisories
    so the briefing can show why a template drifted.
    """
    try:
        result = subprocess.run(
            ["git", "-C", str(fw_dir), "log", "-1", "--format=%h|%ai|%s", "--", template_rel],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            parts = result.stdout.strip().split("|", 2)
            if len(parts) == 3:
                return {
                    "commit": parts[0],
                    "date": parts[1].split(" ", 1)[0],
                    "subject": parts[2],
                }
    except Exception:  # prawduct:ok-broad-except — best-effort lookup
        pass
    return None


_HISTORICAL_RENDER_DEPTH_CAP = 100


def _match_historical_render(
    fw_dir: Path,
    template_rel: str,
    target_hash: str,
    subs: dict[str, str],
    cache: dict[tuple[str, str], str] | None = None,
) -> str | None:
    """Find a historical commit whose rendered template matches target_hash.

    Walks the framework's git history of `template_rel` (with --follow for
    renames), capped at `_HISTORICAL_RENDER_DEPTH_CAP` commits. For each
    historical commit, checks out the template content via `git show`,
    applies current `subs`, hashes, and compares to `target_hash`.

    A match means the product file's current content was produced by the
    framework at some past template version — i.e. the file is "stale-clean"
    rather than user-edited. Sync uses this to safely auto-resolve files that
    look edited only because the manifest's stored hash drifted.

    Returns short SHA (first 12 chars) on match, or None when:
      - fw_dir is not a git repo
      - the template was never tracked
      - no historical render matches within the depth cap
      - git is unavailable

    The optional `cache` (mutated in-place) maps (commit_sha, template_rel) →
    rendered_hash to avoid redundant git-show + render + hash work when
    multiple stale files share template history within one sync run.
    """
    if cache is None:
        cache = {}

    try:
        # --name-only emits each commit's SHA followed by the path the file
        # had at that commit, with blank-line separators. Parsing the path
        # per-commit lets us follow renames: `git show <sha>:<historical-path>`
        # works for old commits where the file lived at a different path,
        # whereas `git show <sha>:<current-path>` would fail.
        log_result = subprocess.run(
            ["git", "-C", str(fw_dir), "log", "--follow", "--format=%H",
             "--name-only", f"-n{_HISTORICAL_RENDER_DEPTH_CAP}",
             "--", template_rel],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except Exception:  # prawduct:ok-broad-except — best-effort lookup at sync time
        return None

    if log_result.returncode != 0 or not log_result.stdout.strip():
        return None

    # Parse alternating SHA / blank / path / blank entries into (sha, path) pairs.
    entries: list[tuple[str, str]] = []
    lines = log_result.stdout.splitlines()
    i = 0
    while i < len(lines):
        sha = lines[i].strip()
        i += 1
        if not sha:
            continue
        # Skip blank lines between sha and path
        while i < len(lines) and not lines[i].strip():
            i += 1
        if i < len(lines):
            path = lines[i].strip()
            entries.append((sha, path))
            i += 1
        # Skip trailing blank line(s) before next entry
        while i < len(lines) and not lines[i].strip():
            i += 1

    for sha, historical_path in entries:
        # Cache key uses the historical path so renamed templates cache correctly.
        cache_key = (sha, historical_path)
        if cache_key in cache:
            rendered_hash = cache[cache_key]
        else:
            try:
                show_result = subprocess.run(
                    ["git", "-C", str(fw_dir), "show", f"{sha}:{historical_path}"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
            except Exception:  # prawduct:ok-broad-except — best-effort lookup
                continue
            if show_result.returncode != 0:
                continue
            content = show_result.stdout
            for key, value in subs.items():
                content = content.replace(key, value)
            rendered_hash = hashlib.sha256(content.encode()).hexdigest()
            cache[cache_key] = rendered_hash
        if rendered_hash == target_hash:
            return sha[:12]

    return None


def _bootstrap_manifest(product: Path, fw_dir: Path) -> dict:
    """Create initial sync manifest for a prawduct repo that doesn't have one.

    Computes hashes of existing managed files so sync can track future changes.
    Files that don't exist get None (triggers creation on first sync).
    For files at old rename paths, uses the old path's content for hash computation
    so the rename + sync flow works correctly.
    """
    from .core import create_manifest

    # Read product_identity.name from project-state.yaml (committed, stable across
    # clones). Falls back to the directory name only when the identity block is
    # missing or unset — which would otherwise make the banner substitution drift
    # whenever the repo is cloned into a differently-named directory.
    product_name = infer_product_name(product) or product.name

    file_hashes: dict[str, str | None] = {}
    for rel_path, config in effective_managed_files(fw_dir).items():
        strategy = config.get("strategy", "template")
        file_path = product / rel_path

        # If file doesn't exist at new path, check old rename paths
        if not file_path.is_file():
            for old_rel, new_rel in FILE_RENAMES.items():
                if new_rel == rel_path and (product / old_rel).is_file():
                    file_path = product / old_rel
                    break

        if strategy == "block_template":
            if file_path.is_file():
                file_hashes[rel_path] = compute_block_hash(file_path.read_text())
            else:
                file_hashes[rel_path] = None
        elif strategy == "merge_settings":
            file_hashes[rel_path] = None  # merge_settings doesn't use hash
        else:
            file_hashes[rel_path] = compute_hash(file_path)

    return create_manifest(product, fw_dir, product_name, file_hashes)


def apply_renames(
    product: Path,
    manifest: dict,
    actions: list[str],
) -> None:
    """Apply file renames from FILE_RENAMES. Mutates manifest['files'] in place."""
    files = manifest.get("files", {})

    for old_rel, new_rel in FILE_RENAMES.items():
        old_path = product / old_rel
        new_path = product / new_rel

        old_in_manifest = old_rel in files

        if old_path.is_file() and new_path.is_file():
            # Both exist — delete old (it's a leftover)
            old_path.unlink()
            if old_in_manifest:
                del files[old_rel]
            # Ensure new path uses canonical config if available
            if new_rel in MANAGED_FILES and new_rel in files:
                saved_hash = files[new_rel].get("generated_hash")
                files[new_rel] = dict(MANAGED_FILES[new_rel])
                files[new_rel]["generated_hash"] = saved_hash
            actions.append(f"Removed leftover: {old_rel}")
        elif old_path.is_file():
            # Normal rename: move file, transfer manifest entry
            new_path.parent.mkdir(parents=True, exist_ok=True)
            old_path.rename(new_path)
            if old_in_manifest:
                old_entry = files.pop(old_rel)
                # Use canonical config if available (fixes stale template paths),
                # otherwise transfer the old entry as-is
                if new_rel in MANAGED_FILES:
                    files[new_rel] = dict(MANAGED_FILES[new_rel])
                    files[new_rel]["generated_hash"] = compute_hash(new_path)
                else:
                    files[new_rel] = old_entry
            actions.append(f"Moved: {old_rel} → {new_rel}")
        elif old_in_manifest and not old_path.is_file():
            # Stale manifest entry (file already deleted/moved)
            del files[old_rel]
            actions.append(f"Cleaned stale manifest entry: {old_rel}")
        # else: neither exists — nothing to do

    # Clean up empty parent directories of old paths
    seen_parents: set[Path] = set()
    for old_rel in FILE_RENAMES:
        parent = product / Path(old_rel).parent
        if parent not in seen_parents and parent.is_dir() and parent != product:
            seen_parents.add(parent)
            try:
                parent.rmdir()  # Only succeeds if empty
                actions.append(f"Removed empty directory: {Path(old_rel).parent}")
            except OSError:
                pass  # Not empty — that's fine


def migrate_v4_to_v5(product_dir: Path) -> list[str]:
    """Migrate a v4 product to v5 structure. Called from run_sync().

    Checks manifest format_version; skips if already v5.
    Runs learnings split, project-state update, and version bump.
    Idempotent.

    Returns list of actions taken.
    """
    actions: list[str] = []
    manifest_path = product_dir / ".prawduct" / "sync-manifest.json"

    if not manifest_path.is_file():
        return actions

    try:
        manifest = load_json(manifest_path)
    except json.JSONDecodeError:
        return actions

    if manifest.get("format_version", 1) >= 2:
        return actions  # Already v5

    # 1. Split learnings
    actions.extend(split_learnings_v5(product_dir))

    # 2. Update project-state.yaml
    actions.extend(migrate_project_state_v5(product_dir))

    # 3. Bump manifest version
    manifest["format_version"] = 2
    manifest["last_sync"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    actions.append("Bumped manifest to format_version 2 (v5)")

    return actions


# F5a auto-commit defaults. Kept as constants so tests can introspect them
# without re-parsing project-state.yaml. `release/*` is a fnmatch glob, not a
# regex — see `_branch_is_protected`.
_DEFAULT_PROTECTED_BRANCHES: tuple[str, ...] = ("main", "master", "release/*")
_SYNC_PENDING_MARKER = ".prawduct/.sync-pending"


def _read_sync_config(product: Path) -> dict:
    """Read F5a sync config from `.prawduct/project-state.yaml`.

    Returns a dict with keys:
      - auto_commit: bool — default True (F5 ships on by default; protected
        branches and WIP checks are the safety net)
      - protected_branches: list[str] — fnmatch globs; default
        ('main', 'master', 'release/*')

    Parsed via column-0 YAML scan (no PyYAML dependency) matching the pattern
    used elsewhere in product-hook for `views_enabled` / `coverage_required`.
    The block looked for is::

        sync:
          auto_commit: true
          protected_branches:
            - main
            - master
            - "release/*"

    Anything malformed falls back to defaults — sync must never block on
    config parse errors.
    """
    config = {
        "auto_commit": True,
        "protected_branches": list(_DEFAULT_PROTECTED_BRANCHES),
    }
    state_path = product / ".prawduct" / "project-state.yaml"
    if not state_path.is_file():
        return config
    try:
        text = state_path.read_text()
    except OSError:
        return config

    lines = text.splitlines()
    in_sync = False
    in_protected = False
    for line in lines:
        stripped = line.rstrip()
        if not stripped or stripped.lstrip().startswith("#"):
            continue
        # Column-0 keys exit sub-block scope.
        if not line.startswith((" ", "\t")):
            in_sync = stripped.startswith("sync:")
            in_protected = False
            continue
        if not in_sync:
            continue
        # Two-space indented child keys of `sync:`.
        if line.startswith("  ") and not line.startswith("   "):
            key_part = line[2:].split("#", 1)[0].rstrip()
            if key_part.startswith("auto_commit:"):
                value = key_part.split(":", 1)[1].strip().strip("\"'").lower()
                config["auto_commit"] = value in ("true", "yes", "on", "1")
                in_protected = False
            elif key_part.startswith("protected_branches:"):
                # Multi-line list follows; reset to capture entries.
                config["protected_branches"] = []
                in_protected = True
            else:
                in_protected = False
        elif in_protected and line.lstrip().startswith("- "):
            entry = line.lstrip()[2:].split("#", 1)[0].strip().strip("\"'")
            if entry:
                config["protected_branches"].append(entry)
    if not config["protected_branches"]:
        # User wrote `protected_branches:` with no entries — interpret as
        # "no protected branches" only if they spelled it `protected_branches: []`.
        # The empty-list-from-no-entries case is more likely a YAML mistake;
        # fall back to defaults to stay safe.
        config["protected_branches"] = list(_DEFAULT_PROTECTED_BRANCHES)
    return config


def _branch_is_protected(branch: str, patterns: list[str]) -> bool:
    """fnmatch each pattern against branch name. Empty branch (detached HEAD)
    is treated as protected — we don't auto-commit in detached HEAD because
    the commit would be unreachable after checkout."""
    if not branch:
        return True
    return any(fnmatch.fnmatchcase(branch, p) for p in patterns)


def _current_branch(product: Path) -> str:
    """Return current branch name or empty string when detached / not a repo."""
    try:
        result = subprocess.run(
            ["git", "-C", str(product), "symbolic-ref", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (subprocess.SubprocessError, OSError, FileNotFoundError):
        pass
    return ""


def _git_op_in_progress(product: Path) -> str:
    """Return the in-progress git op name, or empty string when none.

    Checks the well-known marker files in `.git/`. If `.git` is a file (git
    worktree), resolve the actual gitdir.
    """
    git_path = product / ".git"
    if not git_path.exists():
        return ""
    if git_path.is_file():
        # Worktree: .git is a file like `gitdir: /path/to/main/.git/worktrees/x`
        try:
            content = git_path.read_text().strip()
            if content.startswith("gitdir:"):
                git_path = Path(content.split(":", 1)[1].strip())
        except OSError:
            return ""
    markers = [
        ("MERGE_HEAD", "merge"),
        ("CHERRY_PICK_HEAD", "cherry-pick"),
        ("REVERT_HEAD", "revert"),
    ]
    # REBASE_HEAD is intentionally NOT a marker: unlike MERGE_HEAD /
    # CHERRY_PICK_HEAD / REVERT_HEAD (which git removes when the op ends or is
    # aborted), git leaves REBASE_HEAD behind after a rebase completes — it is
    # only overwritten by the *next* rebase. Its mere presence is therefore not
    # an in-progress signal; treating it as one produced a phantom "rebase in
    # progress" that blocked auto-sync and stuck in the session briefing. The
    # rebase-merge / rebase-apply directory check below is git's own
    # authoritative test (what `git status` uses), so real rebases stay covered.
    for filename, op in markers:
        if (git_path / filename).exists():
            return op
    # Interactive rebase uses a directory, not a file.
    if (git_path / "rebase-merge").is_dir() or (git_path / "rebase-apply").is_dir():
        return "rebase"
    return ""


def _git_porcelain(product: Path) -> list[tuple[str, str]]:
    """Return list of (status_code, path) from `git status --porcelain -z`.

    Empty list when not a git repo or git fails. Status codes are the raw
    two-char porcelain v1 codes (e.g., ' M', 'M ', '??', 'A ', 'AM').
    """
    try:
        result = subprocess.run(
            ["git", "-C", str(product), "status", "--porcelain", "-z"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (subprocess.SubprocessError, OSError, FileNotFoundError):
        return []
    if result.returncode != 0:
        return []
    entries: list[tuple[str, str]] = []
    # -z separates entries with NUL; each entry is "XY path" where rename/copy
    # would add a second NUL-separated source path. We don't auto-commit
    # renames anyway, so flatten the source-path entries into themselves.
    raw = result.stdout
    i = 0
    parts = raw.split("\0")
    while i < len(parts):
        entry = parts[i]
        if not entry:
            i += 1
            continue
        if len(entry) < 3:
            i += 1
            continue
        code = entry[:2]
        path = entry[3:]
        entries.append((code, path))
        # Rename/copy: next NUL field is the source path; skip it.
        if code[0] in ("R", "C"):
            i += 2
        else:
            i += 1
    return entries


def _framework_known_paths(manifest: dict) -> set[str]:
    """Paths sync owns or mutates — auto-commit may claim any of these.

    Anything NOT in this set is, by definition, outside the framework's
    write surface; user WIP. Sources:
      - manifest["files"] — the canonical per-product managed file list
        (every entry has a `template`/`source` that sync re-renders on
        each run, so drift here is always framework-authored)
      - `.prawduct/sync-manifest.json` — written every sync
      - `.prawduct/project-state.yaml` — mutated by enable_v1_4_views and
        the v5 migration path
      - `.gitignore` — kept current by update_gitignore

    `PLACE_ONCE_TEMPLATES` / `PLACE_ONCE_COPY` are *deliberately excluded*:
    sync only creates them when absent and never re-writes thereafter, so
    porcelain drift on `.prawduct/change-log.md`, `.prawduct/backlog.md`,
    or `tests/conftest.py` is virtually always user-authored content —
    sweeping that into `chore(sync):` would re-create the exact
    co-mingling F5a aims to prevent. The trade-off: first-time creation of
    a place-once file leaves an untracked file in the working tree for the
    user to commit deliberately, which is appropriate (initial content of
    change-log.md / backlog.md is a moment that deserves explicit
    acknowledgement).
    """
    known = set(manifest.get("files", {}).keys())
    known.add(".prawduct/sync-manifest.json")
    known.add(".prawduct/project-state.yaml")
    known.add(".gitignore")
    return known


def _classify_changes(
    porcelain: list[tuple[str, str]], known: set[str]
) -> tuple[list[str], list[str]]:
    """Partition porcelain entries into (framework_changed, wip_changed).

    A path counts as framework when it appears in `known` (see
    `_framework_known_paths`). Everything else is user WIP and blocks
    auto-commit.
    """
    framework_changed: list[str] = []
    wip: list[str] = []
    for _code, path in porcelain:
        if path in known:
            framework_changed.append(path)
        else:
            wip.append(path)
    return framework_changed, wip


def _write_sync_pending(product: Path, reason: str, blocked_by: list[str]) -> None:
    """Write the F5a sync-pending marker. Best-effort — never raises."""
    marker = product / _SYNC_PENDING_MARKER
    payload = {
        "reason": reason,
        "blocked_by": blocked_by,
        "version": PRAWDUCT_VERSION,
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    except OSError:
        pass


def _clear_sync_pending(product: Path) -> None:
    """Remove the F5a sync-pending marker if present. Best-effort."""
    marker = product / _SYNC_PENDING_MARKER
    try:
        if marker.is_file():
            marker.unlink()
    except OSError:
        pass


def _try_auto_commit(
    product: Path,
    *,
    actions: list[str],
    notes: list[str],
    manifest: dict,
) -> None:
    """F5a: auto-commit framework drift as a single marker commit per upgrade.

    Inspects `git status` after sync has finished writing files. Partitions
    changes into framework-known and user WIP using
    `_framework_known_paths(manifest)`. The auto-commit only stages and
    commits known framework paths; anything else is user WIP and blocks the
    commit (a `.sync-pending` marker explains why).

    Mutates `actions` and `notes` in place. Side effects:
      - on success: creates one commit, appends to `actions`, clears any
        prior `.sync-pending` marker
      - on precondition failure: writes `.sync-pending` marker, appends a
        descriptive note (visible to user via product-hook briefing)
      - silent no-op when not a git repo, when auto_commit is disabled, or
        when there is no framework drift to commit

    The contract is best-effort: any subprocess failure or unexpected git
    state degrades to "skip auto-commit, leave drift in working tree" — sync
    itself must never fail because of this step.
    """
    git_dir = product / ".git"
    if not git_dir.exists():
        return  # Not a git repo — nothing to commit against.

    config = _read_sync_config(product)
    if not config["auto_commit"]:
        return

    porcelain = _git_porcelain(product)
    known = _framework_known_paths(manifest)
    managed_changed, wip = _classify_changes(porcelain, known)
    if not managed_changed:
        # No framework-managed drift to commit. If a stale marker exists,
        # clear it — drift is resolved.
        _clear_sync_pending(product)
        return

    blocked_by: list[str] = []
    if wip:
        sample = ", ".join(wip[:3])
        extra = f" (+{len(wip) - 3} more)" if len(wip) > 3 else ""
        blocked_by.append(f"non-framework changes present: {sample}{extra}")

    op = _git_op_in_progress(product)
    if op:
        blocked_by.append(f"git {op} in progress")

    branch = _current_branch(product)
    if not branch:
        blocked_by.append("detached HEAD")
    elif _branch_is_protected(branch, config["protected_branches"]):
        blocked_by.append(f"branch '{branch}' is protected")

    if blocked_by:
        reason = "; ".join(blocked_by)
        _write_sync_pending(product, reason, blocked_by)
        notes.append(
            f"Auto-commit skipped: {reason}. "
            f"Framework-managed drift left in working tree; "
            f"resolve and commit when ready."
        )
        return

    # Preconditions pass — stage and commit the framework-managed paths only.
    try:
        add_result = subprocess.run(
            ["git", "-C", str(product), "add", "--", *managed_changed],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if add_result.returncode != 0:
            notes.append(
                f"Auto-commit skipped: git add failed ({add_result.stderr.strip()})"
            )
            _write_sync_pending(product, "git add failed", [add_result.stderr.strip()])
            return

        message = f"chore(sync): prawduct v{PRAWDUCT_VERSION}"
        # Use -- only to disambiguate; we already staged via add.
        commit_result = subprocess.run(
            ["git", "-C", str(product), "commit", "-m", message],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if commit_result.returncode != 0:
            # Most common cause: pre-commit hook rejected the change. Surface
            # the error and leave the staged changes for the user to inspect.
            err = commit_result.stderr.strip() or commit_result.stdout.strip()
            notes.append(
                f"Auto-commit failed at git commit ({err[:200]}); "
                f"changes remain staged for manual commit."
            )
            _write_sync_pending(product, "git commit failed", [err[:200]])
            return

        sha_result = subprocess.run(
            ["git", "-C", str(product), "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        sha = sha_result.stdout.strip() if sha_result.returncode == 0 else ""
        suffix = f" (commit {sha})" if sha else ""
        actions.append(f"Auto-committed framework sync as '{message}'{suffix}")
        _clear_sync_pending(product)
    except (subprocess.SubprocessError, OSError, FileNotFoundError) as exc:
        notes.append(f"Auto-commit skipped: {exc}")
        _write_sync_pending(product, "auto-commit subprocess error", [str(exc)])


def run_sync(product_dir: str, framework_dir: str | None = None, *, no_pull: bool = False, force: bool = False) -> dict:
    """Run the sync algorithm on a product directory.

    Returns a summary dict with actions taken, notes, and any warnings.
    """
    product = Path(product_dir).resolve()
    manifest_path = product / ".prawduct" / "sync-manifest.json"

    bootstrapped = False

    if not manifest_path.is_file():
        if not (product / ".prawduct").is_dir():
            return {
                "product_dir": str(product),
                "synced": False,
                "reason": "not a prawduct repo",
                "actions": [],
                "notes": [],
            }
        # Bootstrap: create manifest for prawduct repo that doesn't have one
        fw_dir = _resolve_framework_dir({}, framework_dir, product)
        if fw_dir is None:
            return {
                "product_dir": str(product),
                "synced": False,
                "reason": "framework not found",
                "actions": [],
                "notes": [],
            }
        manifest = _bootstrap_manifest(product, fw_dir)
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
        bootstrapped = True
    else:
        try:
            manifest = load_json(manifest_path)
        except json.JSONDecodeError:
            return {
                "product_dir": str(product),
                "synced": False,
                "reason": "invalid manifest JSON",
                "actions": [],
                "notes": [],
            }

    fw_dir = _resolve_framework_dir(manifest, framework_dir, product)
    if fw_dir is None:
        return {
            "product_dir": str(product),
            "synced": False,
            "reason": "framework not found",
            "actions": [],
            "notes": [],
        }

    # Best-effort framework pull before syncing templates
    if not no_pull:
        auto_pull = manifest.get("auto_pull", True)
        pull_notes = _try_pull_framework(fw_dir, auto_pull)
    else:
        pull_notes = []

    previous_version = manifest.get("framework_version", "")
    actions: list[str] = []
    notes: list[str] = list(pull_notes)

    # Source of truth for the product name is product_identity.name in the
    # committed project-state.yaml. The manifest-cached product_name is a legacy
    # fallback for manifests written before identity existed (pre-v1.3.9
    # bootstraps, or v4 manifests). When identity is present, use it for
    # rendering and self-heal the manifest cache to match — without this, old
    # clones whose manifest was bootstrapped against a now-fixed bug would never
    # recover. Absence of identity keeps the cached value untouched so products
    # that predate the identity block aren't disturbed.
    identity_name = infer_product_name(product)
    cached_name = manifest.get("product_name")
    product_name = identity_name or cached_name or product.name

    if identity_name and cached_name != identity_name:
        manifest["product_name"] = identity_name
        if cached_name:
            actions.append(
                f"Corrected product_name in manifest: '{cached_name}' → '{identity_name}' "
                f"(source of truth is .prawduct/project-state.yaml)"
            )
        else:
            actions.append(
                f"Populated product_name in manifest from project-state.yaml: '{identity_name}'"
            )

    subs = {"{{PRODUCT_NAME}}": product_name, "{{PRAWDUCT_VERSION}}": PRAWDUCT_VERSION}

    if bootstrapped:
        actions.append("Bootstrapped sync manifest (first framework sync for this repo)")

    # V4→V5 migration (if needed)
    v5_actions = migrate_v4_to_v5(product)
    actions.extend(v5_actions)
    if v5_actions:
        # Re-read manifest since migration updated it
        manifest = load_json(manifest_path)

    # Migrate change_log from project-state.yaml to change-log.md
    actions.extend(migrate_change_log(product))

    # Migrate remaining_work/future_work/backlog from project-state.yaml to backlog.md
    actions.extend(migrate_backlog(product))

    # v1.4: auto-enable derived views for existing repos (one-shot; mutates
    # manifest in place; existing write-back below persists the flag).
    actions.extend(enable_v1_4_views(product, manifest))

    files = manifest.get("files", {})

    # Renames: move files from old paths to new paths (e.g., commands → skills)
    if FILE_RENAMES:
        apply_renames(product, manifest, actions)

    # Backfill: add any managed files missing from the manifest (added after init)
    # Also repair stale config (e.g., old template paths from renamed entries).
    # effective_managed_files() expands MANAGED_DIRS (tools/lib) from the
    # framework, so existing synced repos self-heal: the lib package lands as
    # `New:` entries on the next sync without any per-product migration.
    for rel_path, config in effective_managed_files(fw_dir).items():
        if rel_path not in files:
            files[rel_path] = dict(config)
            files[rel_path]["generated_hash"] = None  # Forces creation on first sync
            desc = config.get("description", "")
            if desc:
                actions.append(f"New: {rel_path} — {desc}")
            else:
                actions.append(f"New: {rel_path}")
        else:
            # Repair stale config: if template/source/strategy differs from
            # canonical MANAGED_FILES, update it (preserving generated_hash)
            existing = files[rel_path]
            canonical = config
            stale = False
            for key in ("template", "source", "strategy"):
                if key in canonical and existing.get(key) != canonical.get(key):
                    stale = True
                    break
            if stale:
                saved_hash = existing.get("generated_hash")
                files[rel_path] = dict(canonical)
                files[rel_path]["generated_hash"] = saved_hash
                actions.append(f"Repaired manifest config for {rel_path}")

    updated_files = dict(files)

    # Cache for stale-clean detection (Chunk 02 of stale-clean-detection feature).
    # Shared across all files in this sync run so multiple stale files using the
    # same template don't redundantly re-render shared history. Keyed by
    # (commit_sha, historical_path) — see _match_historical_render.
    historical_render_cache: dict[tuple[str, str], str] = {}

    for rel_path, config in files.items():
        strategy = config.get("strategy", "template")
        dst = product / rel_path

        if strategy == "template":
            template_rel = config.get("template", "")
            template_path = fw_dir / template_rel
            if not template_path.is_file():
                notes.append(f"Template missing: {template_rel}")
                continue

            # Render current template
            rendered = render_template(template_path, subs)
            rendered_hash = hashlib.sha256(rendered.encode()).hexdigest()

            # Check if template has changed since last sync
            stored_hash = config.get("generated_hash")
            if stored_hash == rendered_hash:
                continue  # Template hasn't changed

            # Template changed — check if user edited the file
            current_hash = compute_hash(dst)

            # Auto-fix: local already matches current template. Catches stale
            # stored_hash, null stored_hash with matching content, and hand-pasted
            # template state. Refresh the manifest — there is nothing to merge,
            # so no warning, but record the hash repair as an action so the
            # manifest gets persisted and `git status` shows the resolved state.
            if current_hash == rendered_hash:
                updated_files[rel_path] = dict(config)
                updated_files[rel_path]["generated_hash"] = rendered_hash
                actions.append(f"Refreshed manifest for {rel_path} (file already at target)")
                continue

            if current_hash is not None and current_hash != stored_hash:
                # Stale-clean detection: when the file's content matches a
                # historical render of this template, the file is framework-
                # produced from an older version, not user-edited. Safe to
                # auto-resolve to the current template without --force. This
                # rescues the common case where sync-manifest.json is gitignored
                # and bootstraps fresh per-clone with hashes that drift from
                # what subsequent syncs would produce.
                matched_sha = _match_historical_render(
                    fw_dir, template_rel, current_hash, subs, historical_render_cache
                )
                if matched_sha is not None:
                    dst.write_text(rendered)
                    new_hash = compute_hash(dst)
                    updated_files[rel_path] = dict(config)
                    updated_files[rel_path]["generated_hash"] = new_hash
                    actions.append(
                        f"Auto-resolved {rel_path} (stale-clean from {matched_sha})"
                    )
                    continue

                if force:
                    dst.write_text(rendered)
                    new_hash = compute_hash(dst)
                    updated_files[rel_path] = dict(config)
                    updated_files[rel_path]["generated_hash"] = new_hash
                    actions.append(f"Force-updated {rel_path} (local edits overwritten)")
                    if rel_path in ("CLAUDE.md",):
                        notes.append(f"Updated {rel_path} — re-read to pick up changes")
                else:
                    notes.append(
                        f"Skipped {rel_path} — new template available but file has local edits (re-run with --force to overwrite)"
                    )
                continue

            # Safe to update
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_text(rendered)
            new_hash = compute_hash(dst)
            updated_files[rel_path] = dict(config)
            updated_files[rel_path]["generated_hash"] = new_hash
            actions.append(f"Updated {rel_path}")
            # CLAUDE.md and settings.json are pre-loaded — flag for restart
            if rel_path in ("CLAUDE.md",):
                notes.append(f"Updated {rel_path} — re-read to pick up changes")

        elif strategy == "block_template":
            # Marker contract: content between PRAWDUCT:BEGIN/END is framework-owned
            # and always overwritten. User customization belongs outside the markers
            # (before/after), which sync preserves verbatim. The stored hash is
            # informational only — we don't gate on local edits inside the block.
            template_rel = config.get("template", "")
            template_path = fw_dir / template_rel
            if not template_path.is_file():
                notes.append(f"Template missing: {template_rel}")
                continue

            rendered = render_template(template_path, subs)
            rendered_block, _, _ = extract_block(rendered)
            if rendered_block is None:
                notes.append(f"Template {template_rel} has no markers — skipping block sync")
                continue

            rendered_block_hash = hashlib.sha256(rendered_block.encode()).hexdigest()
            stored_hash = config.get("generated_hash")

            if not dst.is_file():
                dst.parent.mkdir(parents=True, exist_ok=True)
                dst.write_text(rendered)
                updated_files[rel_path] = dict(config)
                updated_files[rel_path]["generated_hash"] = rendered_block_hash
                actions.append(f"Created {rel_path}")
                notes.append(f"Created {rel_path} — re-read to pick up changes")
                continue

            product_content = dst.read_text()
            product_block, before, after = extract_block(product_content)

            if product_block is None:
                notes.append(
                    f"Skipped {rel_path} — no markers (add markers to enable sync)"
                )
                continue

            product_block_hash = hashlib.sha256(product_block.encode()).hexdigest()

            if product_block_hash == rendered_block_hash:
                # Already at target. Refresh manifest if hash drifted, silently otherwise.
                if stored_hash != rendered_block_hash:
                    updated_files[rel_path] = dict(config)
                    updated_files[rel_path]["generated_hash"] = rendered_block_hash
                    actions.append(f"Refreshed manifest for {rel_path} (block already at target)")
                continue

            new_content = before + rendered_block + after
            dst.write_text(new_content)
            updated_files[rel_path] = dict(config)
            updated_files[rel_path]["generated_hash"] = rendered_block_hash
            actions.append(f"Updated {rel_path} block")
            notes.append(f"Updated {rel_path} — re-read to pick up changes")

        elif strategy == "always_update":
            source_rel = config.get("source", "")
            source_path = fw_dir / source_rel
            if not source_path.is_file():
                notes.append(f"Source missing: {source_rel}")
                continue

            source_bytes = source_path.read_bytes()
            if dst.is_file() and dst.read_bytes() == source_bytes:
                continue  # Already up to date

            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(source_bytes)
            # Make executable
            dst.chmod(dst.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

            new_hash = compute_hash(dst)
            updated_files[rel_path] = dict(config)
            updated_files[rel_path]["generated_hash"] = new_hash
            actions.append(f"Updated {rel_path}")

        elif strategy == "merge_settings":
            template_rel = config.get("template", "")
            template_path = fw_dir / template_rel
            if not template_path.is_file():
                notes.append(f"Template missing: {template_rel}")
                continue

            if merge_settings(dst, template_path, subs):
                actions.append(f"Merged {rel_path}")
                notes.append(f"Updated {rel_path} — re-read to pick up changes")

    # Place-once files: create if missing, never tracked for ongoing sync.
    # Template hashes are recorded in manifest["place_once_templates"] so
    # future syncs can detect when the framework template has evolved.
    manifest_snapshot_pot = dict(manifest.get("place_once_templates", {}))
    pot = manifest.get("place_once_templates", {})
    for rel_path, template_rel in PLACE_ONCE_TEMPLATES.items():
        template_path = fw_dir / template_rel
        dst = product / rel_path
        if not dst.is_file():
            if not template_path.is_file():
                continue
            rendered = render_template(template_path, subs)
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_text(rendered)
            actions.append(f"Created {rel_path}")
        # Record template hash (on creation or bootstrap for pre-existing products).
        # For pre-existing products without tracking, we bootstrap using the
        # *current* template hash — we can't know what version was originally
        # deployed, but we can detect drift from this sync forward.
        if template_path.is_file() and rel_path not in pot:
            rendered_for_hash = render_template(template_path, subs)
            pot[rel_path] = {
                "template": template_rel,
                "template_hash": hashlib.sha256(rendered_for_hash.encode()).hexdigest(),
                "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            }

    # Place-once binary files: copy if missing (no template rendering)
    for rel_path, template_rel in PLACE_ONCE_COPY.items():
        template_path = fw_dir / template_rel
        dst = product / rel_path
        if not dst.is_file():
            if not template_path.is_file():
                continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(template_path, dst)
            actions.append(f"Created {rel_path}")
        # Record template hash for binary place-once files
        if template_path.is_file() and rel_path not in pot:
            content = template_path.read_bytes()
            pot[rel_path] = {
                "template": template_rel,
                "template_hash": hashlib.sha256(content).hexdigest(),
                "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            }

    if pot:
        manifest["place_once_templates"] = pot

    # Detect template drift: compare stored hashes against current templates.
    # Only check entries that existed before this sync (not freshly bootstrapped
    # ones, which by definition match the current template).
    advisories: list[dict[str, str]] = []
    for rel_path, entry in manifest_snapshot_pot.items():
        template_rel = entry.get("template", "")
        template_path = fw_dir / template_rel
        if not template_path.is_file():
            continue
        stored_hash = entry.get("template_hash", "")
        if not stored_hash:
            continue
        # Compute current template hash (same method used at storage time)
        if template_rel.endswith(".py"):
            current_hash = hashlib.sha256(template_path.read_bytes()).hexdigest()
        else:
            current_content = render_template(template_path, subs)
            current_hash = hashlib.sha256(current_content.encode()).hexdigest()
        if current_hash != stored_hash:
            # Template has evolved since this product was created/last reviewed
            short_name = rel_path.rsplit("/", 1)[-1]
            last_change = _get_template_last_change(fw_dir, template_rel) or {}
            advisories.append({
                "type": "template_drift",
                "file": rel_path,
                "template": template_rel,
                "message": f"{short_name} template has new content since project setup — run /janitor scope=templates to review",
                "last_changed_commit": last_change.get("commit", ""),
                "last_changed_date": last_change.get("date", ""),
                "last_changed_subject": last_change.get("subject", ""),
            })
            # Fire ONCE per template change, not every session forever. Refresh
            # the stored hash to current so the next sync sees no drift. Place-
            # once files are user-owned ("surface the change once, then it's
            # yours"); re-nagging indefinitely with no dismiss path was pure tax.
            live_entry = pot.get(rel_path)
            if live_entry is not None:
                live_entry["template_hash"] = current_hash
                live_entry["last_surfaced_at"] = datetime.now(timezone.utc).strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                )

    # Post-sync migration advisories (v1.6.0 Phase 1). Distinct from the
    # template-drift `advisories` collected above — these come from the probe
    # registry (empty in Phase 1, so this is a no-op) and land in the per-clone
    # nag log `.prawduct/.advisories.json`. run_sync_advisories is return-value
    # based and degrades safely; the broad guard is belt-and-suspenders so a
    # future feature's faulty probe can never block a sync.
    try:
        run_sync_advisories(
            product,
            now=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            sync_version=PRAWDUCT_VERSION,
        )
    except Exception as exc:  # prawduct:ok-broad-except — advisory probes must never block sync
        notes.append(f"Advisory probe step skipped: {exc}")

    # Ensure gitignore stays current
    gi_result = update_gitignore(product)
    if gi_result["modified"]:
        actions.append("Updated .gitignore")
    for path in gi_result["unignored"]:
        notes.append(
            f"Removed {path} from .gitignore — it should be committed. "
            f"Run: git add {path}"
        )

    # Untrack any session files that were previously committed
    untracked = untrack_gitignored_files(product)
    for path in untracked:
        actions.append(f"Untracked {path} (removed from git index, file kept locally)")

    # Always refresh freshness markers on a successful sync — even when no
    # files changed. Otherwise a repo that is byte-identical to the framework
    # keeps reporting a phantom "N commit(s) behind" in every session briefing,
    # because last_sync / framework_commit were frozen at the last sync that
    # happened to change a file. Refreshing them every sync makes a healthy,
    # up-to-date repo report "in sync" and emit zero freshness noise — the
    # whole point of the happy-path-silence work. (The manifest is gitignored,
    # so rewriting it every session creates no git churn.)
    manifest["files"] = updated_files
    manifest["framework_version"] = PRAWDUCT_VERSION
    fw_commit = _get_framework_head_commit(fw_dir)
    if fw_commit:
        manifest["framework_commit"] = fw_commit
    manifest["last_sync"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")

    # F5a: after all framework-managed mutations land on disk and the
    # manifest is updated, attempt the single marker commit. Quarantines
    # framework drift to one dated `chore(sync): prawduct vX.Y.Z` per upgrade,
    # never co-mingling with chunk diffs. Best-effort — never blocks sync.
    _try_auto_commit(product, actions=actions, notes=notes, manifest=manifest)

    # Include version change info so callers can surface upgrade notices
    version_info: dict[str, str] = {"new_version": PRAWDUCT_VERSION}
    if previous_version and previous_version != PRAWDUCT_VERSION:
        version_info["previous_version"] = previous_version

    return {
        "product_dir": str(product),
        "synced": bool(actions),
        "reason": "ok" if actions else "no updates needed",
        "actions": actions,
        "notes": notes,
        "advisories": advisories,
        "version": version_info,
    }
