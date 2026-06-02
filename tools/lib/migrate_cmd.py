"""
Migration operations for prawduct product repos.

Handles v1→v3→v4→v5 migrations, changelog/backlog extraction,
and sync manifest generation.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from .core import (
    BLOCK_BEGIN,
    BLOCK_END,
    FRAMEWORK_DIR,
    PRAWDUCT_VERSION,
    TEMPLATES_DIR,
    V1_GITIGNORE_ENTRIES,
    V1_SESSION_FILES,
    V4_GITIGNORE_ENTRIES,
    _resolve_framework_dir,
    compute_block_hash,
    compute_hash,
    copy_hook,
    create_manifest,
    detect_version,
    infer_product_name,
    load_json,
    merge_settings,
    render_template,
    write_template,
)


def delete_v1_files(target: Path) -> list[str]:
    """Remove v1-only marker files. Returns list of deleted file names."""
    v1_files = [
        ".prawduct/framework-path",
        ".prawduct/framework-version",
        ".prawduct/.cross-repo-edits",
    ]
    deleted = []
    for rel in v1_files:
        path = target / rel
        if path.is_file():
            path.unlink()
            deleted.append(rel)
    return deleted


def archive_v1_dirs(target: Path) -> list[str]:
    """Move v1 directories to .prawduct/archive/. Returns list of archived dir names."""
    v1_dirs = [
        ".prawduct/framework-observations",
        ".prawduct/traces",
    ]
    archived = []
    for rel in v1_dirs:
        src = target / rel
        if not src.is_dir():
            continue
        archive_dir = target / ".prawduct" / "archive"
        dst = archive_dir / Path(rel).name
        if dst.exists():
            continue  # Already archived
        archive_dir.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
        archived.append(rel)
    return archived


def clean_v1_session_files(target: Path) -> list[str]:
    """Remove transient v1 session files. Returns list of deleted file names."""
    deleted = []
    for rel in V1_SESSION_FILES:
        path = target / rel
        if path.is_file():
            path.unlink()
            deleted.append(rel)
    return deleted


def clean_gitignore(target: Path) -> bool:
    """Remove v1-specific entries, add v4 entries. Returns True if modified."""
    gitignore = target / ".gitignore"
    changed = False

    if gitignore.is_file():
        content = gitignore.read_text()
        lines = content.splitlines()
    else:
        content = ""
        lines = []

    # Remove v1 entries
    filtered = []
    for line in lines:
        stripped = line.strip()
        if stripped in V1_GITIGNORE_ENTRIES:
            changed = True
            continue
        filtered.append(line)

    # Add missing v4 entries
    existing_set = set(l.strip() for l in filtered)
    missing = [e for e in V4_GITIGNORE_ENTRIES if e not in existing_set]

    if missing:
        changed = True
        if filtered and filtered[-1].strip():
            filtered.append("")
        filtered.append("# Prawduct session files")
        for entry in missing:
            filtered.append(entry)

    if not changed:
        return False

    gitignore.write_text("\n".join(filtered) + "\n")
    return True


def add_block_markers(target: Path, subs: dict[str, str]) -> bool:
    """Add PRAWDUCT block markers to CLAUDE.md if missing.

    - If already has markers → no-op.
    - Otherwise → wrap the body (everything from the first ## heading onward)
      in markers.

    Returns True if the file was modified.
    """
    claude_path = target / "CLAUDE.md"
    if not claude_path.is_file():
        return False

    content = claude_path.read_text()

    # Already has markers — no-op
    if BLOCK_BEGIN in content and BLOCK_END in content:
        return False

    # Wrap everything from the first ## heading onward in markers
    lines = content.split("\n")
    body_start = 0
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("## "):
            body_start = i
            break
    else:
        # No section headers found — wrap everything after first non-empty lines
        body_start = min(2, len(lines))

    before_lines = lines[:body_start]
    body_lines = lines[body_start:]

    # Build new content
    before = "\n".join(before_lines)
    if before and not before.endswith("\n"):
        before += "\n"
    before += "\n"

    body = "\n".join(body_lines)
    if body and not body.endswith("\n"):
        body += "\n"

    new_content = before + BLOCK_BEGIN + "\n\n" + body + "\n" + BLOCK_END + "\n"
    claude_path.write_text(new_content)
    return True


def upgrade_manifest_strategy(target: Path) -> bool:
    """Upgrade manifest CLAUDE.md strategy from 'template' to 'block_template'.

    Recomputes the hash as a block hash. Returns True if modified.
    """
    manifest_path = target / ".prawduct" / "sync-manifest.json"
    if not manifest_path.is_file():
        return False

    try:
        manifest = load_json(manifest_path)
    except json.JSONDecodeError:
        return False

    files = manifest.get("files", {})
    claude_config = files.get("CLAUDE.md")
    if claude_config is None:
        return False

    if claude_config.get("strategy") == "block_template":
        return False  # Already upgraded

    # Change strategy
    claude_config["strategy"] = "block_template"

    # Recompute hash as block hash
    claude_path = target / "CLAUDE.md"
    if claude_path.is_file():
        content = claude_path.read_text()
        claude_config["generated_hash"] = compute_block_hash(content)

    manifest["files"]["CLAUDE.md"] = claude_config
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    return True


def split_learnings_v5(product_dir: Path) -> list[str]:
    """Create learnings-detail.md as reference backup of learnings.md.

    Part of v4→v5 migration. If learnings.md exists with meaningful content
    and learnings-detail.md doesn't exist yet, copies the content.
    Idempotent: skips if detail file already exists.

    Returns list of actions taken.
    """
    actions: list[str] = []
    learnings = product_dir / ".prawduct" / "learnings.md"
    detail = product_dir / ".prawduct" / "learnings-detail.md"

    if not learnings.is_file():
        return actions
    if detail.is_file():
        return actions  # Already split

    content = learnings.read_text()
    # Only split if there's meaningful content beyond the header
    lines = [l for l in content.strip().splitlines()
             if l.strip() and not l.startswith("#")]
    if not lines:
        return actions

    detail.write_text(content)
    actions.append("Created .prawduct/learnings-detail.md (reference backup)")
    return actions


def strip_test_tracking(product_dir: Path) -> list[str]:
    """Remove build_state.test_tracking from project-state.yaml.

    Test count is derived data — computed dynamically by the hook, never tracked
    as a static artifact. Idempotent: no-op if test_tracking is absent.

    Returns list of actions taken.
    """
    actions: list[str] = []
    state_path = product_dir / ".prawduct" / "project-state.yaml"
    if not state_path.is_file():
        return actions

    content = state_path.read_text()
    if "test_tracking:" not in content:
        return actions

    lines = content.split("\n")
    tt_start = None
    tt_end = None

    for i, line in enumerate(lines):
        if tt_start is None:
            stripped = line.strip()
            if stripped.startswith("test_tracking:") and line.startswith("  "):
                tt_start = i
        elif tt_start is not None:
            # End when we hit a non-blank/non-comment line at indent <= 2
            if line.strip() and not line.strip().startswith("#"):
                indent = len(line) - len(line.lstrip())
                if indent <= 2:
                    tt_end = i
                    break

    if tt_start is None:
        return actions
    if tt_end is None:
        tt_end = len(lines)

    new_lines = lines[:tt_start] + lines[tt_end:]
    cleaned = "\n".join(new_lines)
    while "\n\n\n" in cleaned:
        cleaned = cleaned.replace("\n\n\n", "\n\n")
    state_path.write_text(cleaned)
    actions.append("Removed build_state.test_tracking from project-state.yaml")
    return actions


def enable_v1_4_views(product_dir: Path, manifest: dict) -> list[str]:
    """One-shot v1.4 migration: auto-enable derived views for existing repos.

    Per the v1.4 rollout decision ("all users should get views for free, no
    mandatory opt-in"), sync silently upgrades v1.3.x product repos so the
    next ``regen-views`` run produces the three derived views (Status,
    release-notes, scope_rollups).

    Operates on ``.prawduct/project-state.yaml``:
      * Adds ``scope_rollups: {}`` block with header comment if absent.
      * Adds ``views_enabled: true`` with header if absent.
      * Flips ``views_enabled: false`` → ``views_enabled: true`` (the post-Chunk-06
        template default that v1.3.x bootstrapped products will be holding).

    One-shot tracking via ``manifest['v1_4_views_enabled']``. After the first
    successful run, the flag is set and subsequent syncs are no-ops — users who
    edit ``views_enabled`` back to ``false`` afterwards aren't fought.

    Mutates ``manifest`` in place (caller persists via existing write-back).
    Returns list of action strings.
    """
    actions: list[str] = []

    if manifest.get("v1_4_views_enabled"):
        return actions  # Already migrated this repo

    state_path = product_dir / ".prawduct" / "project-state.yaml"
    if not state_path.is_file():
        return actions

    content = state_path.read_text()
    original = content

    has_views_key = "\nviews_enabled:" in content or content.startswith("views_enabled:")
    has_scope_key = "\nscope_rollups:" in content or content.startswith("scope_rollups:")

    # Flip false → true when key already present (post-Chunk-06 template default).
    # We only rewrite the standalone ``views_enabled: false`` line, leaving any
    # commented-out occurrences or unrelated substrings alone.
    if has_views_key:
        new_lines: list[str] = []
        flipped = False
        for line in content.split("\n"):
            if line.strip() == "views_enabled: false" and not flipped:
                new_lines.append("views_enabled: true")
                flipped = True
            else:
                new_lines.append(line)
        if flipped:
            content = "\n".join(new_lines)
            actions.append(
                "Flipped views_enabled: false → true in project-state.yaml "
                "(v1.4 derived views auto-enabled)"
            )

    # Append scope_rollups: {} placeholder if absent.
    if not has_scope_key:
        if content and not content.endswith("\n"):
            content += "\n"
        content += (
            "\n"
            "# =============================================================================\n"
            "# SCOPE ROLLUPS (derived view, v1.4+)\n"
            "# =============================================================================\n"
            "# Auto-generated by `python3 tools/product-hook regen-views` from\n"
            "# .prawduct/change-log.md `scope=` tags. Do not hand-edit — edits will be\n"
            "# overwritten on next regen.\n"
            "\n"
            "scope_rollups: {}\n"
        )
        actions.append("Added scope_rollups: {} placeholder to project-state.yaml")

    # Append views_enabled: true if absent (pre-Chunk-06 v1.3.x bootstrap).
    if not has_views_key:
        if content and not content.endswith("\n"):
            content += "\n"
        content += (
            "\n"
            "# =============================================================================\n"
            "# DERIVED VIEWS (enabled by default, v1.4+)\n"
            "# =============================================================================\n"
            "# When true (default), three derived views are regenerated from\n"
            "# change-log.md tagged entries (see that file for the tag format):\n"
            "#   * build-plan `## Status` block (checkboxes from `status=shipped` tags)\n"
            "#   * `.prawduct/release-notes.md` (from `release=` tags)\n"
            "#   * `scope_rollups:` block above (from `scope=` tags)\n"
            "# Run `python3 tools/product-hook regen-views` to apply. Set to `false`\n"
            "# to opt out.\n"
            "\n"
            "views_enabled: true\n"
        )
        actions.append(
            "Added views_enabled: true to project-state.yaml "
            "(v1.4 derived views auto-enabled)"
        )

    if content != original:
        state_path.write_text(content)

    # Record one-shot completion regardless of whether the file needed changes —
    # an already-on repo still counts as migrated, and we want subsequent syncs
    # to skip the file read entirely.
    manifest["v1_4_views_enabled"] = True

    return actions


def enable_v1_4_coverage(
    product_dir: Path,
    manifest: dict,
    *,
    force: bool = False,
) -> tuple[list[str], list[str]]:
    """User-invoked v1.4 migration: enable F4 coverage enforcement.

    Unlike ``enable_v1_4_views`` (silent auto-enable on every sync — the
    decision was "all users should get views for free"), coverage
    enforcement is opt-in: turning it on commits the project to BLOCKING
    Critic findings whenever a changed file is missing from
    ``.test-evidence.json``'s ``changes_referenced``. The migration is
    intentionally explicit — invoked via the new ``prawduct-setup migrate
    --enable-coverage`` subcommand, never silently from sync.

    Mutates ``.prawduct/project-state.yaml`` in place:
      * Flips standalone ``coverage_required: false`` → ``true``.
      * Appends a ``coverage_required: true`` block with header comment
        when the key is absent entirely.
      * No rewrite when the key is already ``true``.

    Mutates ``manifest`` to set ``v1_4_coverage_enabled: True`` so a later
    accidental re-invocation short-circuits. ``force=True`` ignores the
    one-shot flag and re-surfaces NOTEs (useful when a user re-runs to
    re-check evidence shape after wiring up a verifier).

    Returns ``(actions, notes)``. Actions are file mutations; notes
    surface deprecation + next-step guidance:
      * Legacy-shape ``.test-evidence.json`` (no ``verifier`` field) →
        a v1.5-removal-warning NOTE pointing at ``tools/test-reference-verify``
        as the floor (or a stronger product-supplied verifier).
      * Missing evidence file → a NOTE telling the user to run the test
        suite + verifier before relying on the new gate.
      * Successful flip → a NOTE summarizing the next-PR consequence
        (Critic Goal 1 now BLOCKS on missing coverage).
    """
    actions: list[str] = []
    notes: list[str] = []

    if manifest.get("v1_4_coverage_enabled") and not force:
        return actions, notes

    state_path = product_dir / ".prawduct" / "project-state.yaml"
    if not state_path.is_file():
        return actions, notes

    content = state_path.read_text()
    original = content

    # ``has_*_key`` checks scan column-0 occurrences (preceded by a newline
    # or at start-of-file) so a comment-quoted ``coverage_required:`` or
    # an indented nested mention doesn't trick the detector.
    has_coverage_key = (
        "\ncoverage_required:" in content
        or content.startswith("coverage_required:")
    )

    already_on = False
    if has_coverage_key:
        for raw in content.splitlines():
            if raw[:1] in (" ", "\t"):
                continue
            stripped = raw.split("#", 1)[0].rstrip()
            if stripped.startswith("coverage_required:"):
                value = stripped.split(":", 1)[1].strip().lower()
                already_on = value == "true"
                break

    if has_coverage_key and not already_on:
        # Flip the first column-0 ``coverage_required: false`` line, regardless
        # of trailing inline comment (``false  # opt-in``). Detector and
        # mutator must agree on shape — Critic Chunk 10 NOTE flagged the
        # earlier asymmetry where the detector stripped comments but the
        # mutator only matched the bare line, leaving inline-commented forms
        # in a silent no-op state.
        new_lines: list[str] = []
        flipped = False
        for line in content.split("\n"):
            if flipped or line[:1] in (" ", "\t"):
                new_lines.append(line)
                continue
            stripped = line.split("#", 1)[0].rstrip()
            if (
                stripped.startswith("coverage_required:")
                and stripped.split(":", 1)[1].strip().lower() == "false"
            ):
                # Preserve any inline comment by re-attaching the post-#
                # tail; only the value changes.
                tail = line.split("#", 1)[1] if "#" in line else ""
                rewritten = "coverage_required: true"
                if tail:
                    rewritten += "  #" + tail
                new_lines.append(rewritten)
                flipped = True
            else:
                new_lines.append(line)
        if flipped:
            content = "\n".join(new_lines)
            actions.append(
                "Flipped coverage_required: false → true in project-state.yaml "
                "(v1.4 F4 symbol-coverage enforcement enabled)"
            )

    if not has_coverage_key:
        if content and not content.endswith("\n"):
            content += "\n"
        content += (
            "\n"
            "# =============================================================================\n"
            "# COVERAGE EVIDENCE (opt-in, v1.4+)\n"
            "# =============================================================================\n"
            "# When true, the Critic's Goal 1 requires every changed file to appear\n"
            "# in `.test-evidence.json`'s `changes_referenced` list and scales severity\n"
            "# language to the declared `coverage_level` (`referenced` floor vs.\n"
            "# `executed` real). See `methodology/building.md` + the reference\n"
            "# verifier at `tools/test-reference-verify`. Enabled by\n"
            "# `prawduct-setup migrate --enable-coverage`.\n"
            "\n"
            "coverage_required: true\n"
        )
        actions.append(
            "Added coverage_required: true to project-state.yaml "
            "(v1.4 F4 symbol-coverage enforcement enabled)"
        )

    if content != original:
        state_path.write_text(content)

    if already_on and not actions:
        notes.append(
            "coverage_required is already true — nothing to flip. "
            "Re-running with --force re-surfaces evidence-shape NOTEs."
        )

    # Inspect the latest test evidence to surface deprecation / next-step
    # guidance. The evidence file is gitignored in normal product layouts,
    # so missing-file is a likely state for a project that has never run
    # the verifier — surface explicitly rather than failing silently.
    evidence_path = product_dir / ".prawduct" / ".test-evidence.json"
    if not evidence_path.is_file():
        notes.append(
            "No .prawduct/.test-evidence.json on disk — run the test suite and "
            "`python3 tools/test-reference-verify --merge-into .prawduct/.test-evidence.json` "
            "before relying on the new Critic gate."
        )
    else:
        try:
            evidence = json.loads(evidence_path.read_text())
        except (json.JSONDecodeError, OSError) as exc:
            notes.append(
                f"Could not parse .prawduct/.test-evidence.json ({exc}); "
                "re-emit with `python3 tools/test-reference-verify` "
                "before relying on the new gate."
            )
        else:
            if "verifier" not in evidence:
                notes.append(
                    "Legacy evidence shape detected (no `verifier` field). "
                    "v1.5 will drop the legacy-shape compat path — emit the "
                    "F4a fields with `python3 tools/test-reference-verify "
                    "--merge-into .prawduct/.test-evidence.json` (Python "
                    "floor) or plug in a language-native coverage tool "
                    "and set `coverage_level: executed`."
                )

    # One-shot manifest tracking. Set even when nothing changed in the
    # YAML (an already-on repo still counts as migrated) so accidental
    # re-runs short-circuit. ``--force`` callers bypass this check at the
    # top of the function.
    manifest["v1_4_coverage_enabled"] = True

    if actions and not already_on:
        notes.append(
            "Next-PR consequence: Critic Goal 1 will BLOCK on changed files "
            "missing from changes_referenced. Wire a verifier into your test "
            "command — `tools/test-reference-verify` is the shipped Python "
            "floor; see `methodology/building.md` for stronger alternatives."
        )

    return actions, notes


def run_migrate_coverage(product_dir: str, *, force: bool = False) -> dict:
    """User-facing runner for ``prawduct-setup migrate --enable-coverage``.

    Loads ``sync-manifest.json``, invokes :func:`enable_v1_4_coverage`,
    persists the manifest, and returns a dict shaped for both human and
    JSON output:

        {
          "product_dir": "/abs/path",
          "enabled": bool,           # True iff coverage_required ended up true
          "force": bool,
          "actions": [str, ...],     # file mutations
          "notes": [str, ...],       # deprecation + next-step guidance
        }

    On error returns ``{"error": "..."}`` and skips manifest write-back.

    The runner is intentionally thin: the policy lives in
    :func:`enable_v1_4_coverage`. This wrapper exists so the CLI surface
    matches the other ``run_*`` commands (init / sync / validate / views)
    — a single dict result that the ``prawduct-setup.py`` layer can
    render or json-dump uniformly.
    """
    product_path = Path(product_dir).resolve()
    prawduct_dir = product_path / ".prawduct"
    if not prawduct_dir.is_dir():
        return {
            "error": f"Not a prawduct product: {product_path} has no .prawduct/ directory"
        }

    manifest_path = prawduct_dir / "sync-manifest.json"
    if not manifest_path.is_file():
        return {
            "error": (
                f"No sync-manifest.json at {manifest_path} — run "
                "`prawduct-setup setup` to initialize the product repo before "
                "migrating."
            )
        }

    try:
        manifest = load_json(manifest_path)
    except (json.JSONDecodeError, OSError) as exc:
        return {"error": f"Could not read sync-manifest.json: {exc}"}

    try:
        actions, notes = enable_v1_4_coverage(product_path, manifest, force=force)
    except OSError as exc:
        return {"error": f"Migration failed: {exc}"}

    # Persist manifest regardless of whether anything changed in the YAML —
    # the one-shot flag may have been set even on a no-op so subsequent
    # accidental invocations short-circuit.
    try:
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    except OSError as exc:
        return {"error": f"Could not write sync-manifest.json: {exc}"}

    # Re-read coverage_required from the on-disk state to report ground
    # truth (the manifest flag tracks "we ran the migration", not "the
    # YAML currently says true" — a user could re-edit between runs).
    state_path = prawduct_dir / "project-state.yaml"
    enabled = False
    if state_path.is_file():
        for raw in state_path.read_text().splitlines():
            if raw[:1] in (" ", "\t"):
                continue
            stripped = raw.split("#", 1)[0].rstrip()
            if stripped.startswith("coverage_required:"):
                enabled = stripped.split(":", 1)[1].strip().lower() == "true"
                break

    return {
        "product_dir": str(product_path),
        "enabled": enabled,
        "force": force,
        "actions": actions,
        "notes": notes,
    }


# =============================================================================
# F5b — settings.json layout migration (manifest flag + legacy_cleanup pass).
# =============================================================================
#
# Unlike ``enable_v1_4_views`` (silent auto-enable every sync) and unlike
# ``enable_v1_4_coverage`` (commits the project to BLOCKING Critic findings),
# the settings-layout migration is mostly a *signal* operation: it stamps
# ``v1_4_settings_migrated: true`` in the manifest as the explicit user opt-in.
# For products already on the canonical minimal layout (the framework's own
# template since v1.3.x), the file mutation is a no-op; for older repos with
# v1/v3 hook markers that normal sync skipped, the ``legacy_cleanup=True``
# pass strips them. The flag exists so v1.4.1's Critic NOTE on unmigrated
# repos has a single state bit to read — not so this migration does anything
# load-bearing in v1.4.0.

def enable_v1_4_settings_layout(
    product_dir: Path,
    template_path: Path,
    subs: dict[str, str],
    manifest: dict,
    *,
    force: bool = False,
) -> tuple[list[str], list[str]]:
    """User-invoked v1.4 migration: stamp settings.json as on the canonical
    minimal layout.

    Invokes :func:`merge_settings` with ``legacy_cleanup=True`` against the
    product's ``.claude/settings.json``, then records the migration in the
    manifest. The cleanup pass is the same one used by v1→v5 migration
    (``migrate_cmd.py:run_migrate``); running it again on a v5 product is a
    no-op when nothing predates the current layout, which is the expected
    state for products that have been syncing regularly.

    Sets ``manifest["v1_4_settings_migrated"] = True`` on success so an
    accidental re-invocation short-circuits. The flag means "the user
    explicitly opted into the canonical layout," not "the file changed" —
    products already minimal get the flag and a single explanatory NOTE.

    Returns ``(actions, notes)``:
      * Actions are file mutations (one line if settings.json was rewritten).
      * Notes surface the already-minimal-no-op case, parse failures, and
        the v1.4.1-NOTE consequence.

    Tolerates missing settings.json (returns empty, no flag) and unparseable
    settings.json (returns empty, surfaces diagnostic note, no flag). In both
    cases the migration didn't actually run to completion, so flipping the
    flag would falsely advertise success.
    """
    actions: list[str] = []
    notes: list[str] = []

    if manifest.get("v1_4_settings_migrated") and not force:
        return actions, notes

    settings_path = product_dir / ".claude" / "settings.json"
    if not settings_path.is_file():
        return actions, notes

    # Validate JSON shape up front. ``merge_settings`` already handles bad
    # JSON by logging and returning False, but we need to surface the parse
    # failure as a NOTE *and* refuse to set the manifest flag — otherwise a
    # silently-broken settings.json gets "migrated" with no diagnostic trail.
    try:
        json.loads(settings_path.read_text())
    except json.JSONDecodeError as exc:
        notes.append(
            f"Could not parse .claude/settings.json ({exc}); fix the JSON "
            "syntax and re-run migrate --enable-settings-layout."
        )
        return actions, notes

    changed = merge_settings(
        settings_path, template_path, subs, legacy_cleanup=True
    )

    if changed:
        actions.append(
            "Normalized .claude/settings.json (stripped legacy hooks, "
            "regenerated banner; user hooks preserved)"
        )
    else:
        # Distinguish "already minimal" from "we wrote something" so the user
        # knows whether their file changed. Without this NOTE, a no-op migration
        # is indistinguishable from a silently-failed one.
        notes.append(
            "Settings.json was already on the canonical minimal layout; "
            "no file changes were necessary. Manifest flag updated."
        )

    notes.append(
        "Next-release consequence: v1.4.1's Critic surfaces a NOTE on "
        "products that haven't run this migration. Running migrate "
        "--enable-settings-layout silences that NOTE going forward."
    )

    # One-shot manifest tracking. Set after the cleanup pass succeeds so a
    # parse-failure path above can't silently advertise migration.
    manifest["v1_4_settings_migrated"] = True

    return actions, notes


def run_migrate_settings_layout(
    product_dir: str, *, force: bool = False
) -> dict:
    """User-facing runner for ``prawduct-setup migrate --enable-settings-layout``.

    Loads ``sync-manifest.json``, resolves the framework path the same way
    ``run_sync`` does (manifest ``framework_source`` → ``PRAWDUCT_FRAMEWORK_DIR``
    env → sibling ``../prawduct`` fallback), constructs the canonical
    ``{{PRODUCT_NAME}}`` / ``{{PRAWDUCT_VERSION}}`` subs, invokes
    :func:`enable_v1_4_settings_layout`, and persists the manifest.

    Returns a dict shaped for both human and JSON output:

        {
          "product_dir": "/abs/path",
          "migrated": bool,           # True iff manifest flag ended up true
          "force": bool,
          "actions": [str, ...],     # file mutations
          "notes": [str, ...],       # already-minimal / next-release guidance
        }

    On error returns ``{"error": "..."}`` and skips manifest write-back.
    Errors are actionable: each names the next command to run rather than
    just "not found" (mirrors ``run_migrate_coverage`` shape).

    The runner is intentionally thin: policy lives in
    :func:`enable_v1_4_settings_layout`. The framework-resolution layer
    matches ``run_sync`` so the recovery advice users see is consistent
    across commands.
    """
    product_path = Path(product_dir).resolve()
    prawduct_dir = product_path / ".prawduct"
    if not prawduct_dir.is_dir():
        return {
            "error": f"Not a prawduct product: {product_path} has no .prawduct/ directory"
        }

    manifest_path = prawduct_dir / "sync-manifest.json"
    if not manifest_path.is_file():
        return {
            "error": (
                f"No sync-manifest.json at {manifest_path} — run "
                "`prawduct-setup setup` to initialize the product repo before "
                "migrating."
            )
        }

    try:
        manifest = load_json(manifest_path)
    except (json.JSONDecodeError, OSError) as exc:
        return {"error": f"Could not read sync-manifest.json: {exc}"}

    framework = _resolve_framework_dir(manifest, None, product_path)
    if framework is None:
        return {
            "error": (
                "Could not resolve framework directory (checked manifest "
                "framework_source, PRAWDUCT_FRAMEWORK_DIR env, and sibling "
                "../prawduct). Set PRAWDUCT_FRAMEWORK_DIR or clone the "
                "framework as a sibling directory, then re-run."
            )
        }

    template_path = framework / "templates" / "product-settings.json"
    if not template_path.is_file():
        return {
            "error": (
                f"Framework at {framework} is missing "
                "templates/product-settings.json — the resolved framework "
                "checkout looks incomplete."
            )
        }

    product_name = (
        infer_product_name(product_path)
        or manifest.get("product_name")
        or product_path.name
    )
    subs = {
        "{{PRODUCT_NAME}}": product_name,
        "{{PRAWDUCT_VERSION}}": PRAWDUCT_VERSION,
    }

    try:
        actions, notes = enable_v1_4_settings_layout(
            product_path, template_path, subs, manifest, force=force
        )
    except OSError as exc:
        return {"error": f"Migration failed: {exc}"}

    # Persist manifest regardless of whether anything changed in the file —
    # the one-shot flag may have been set even on a no-op so subsequent
    # accidental invocations short-circuit.
    try:
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    except OSError as exc:
        return {"error": f"Could not write sync-manifest.json: {exc}"}

    return {
        "product_dir": str(product_path),
        "migrated": bool(manifest.get("v1_4_settings_migrated")),
        "force": force,
        "actions": actions,
        "notes": notes,
    }


def migrate_project_state_v5(product_dir: Path) -> list[str]:
    """Add v5 sections to project-state.yaml, remove v4-only fields.

    Adds work_in_progress (backward compat for existing repos) and
    health_check sections if missing. Removes current_phase if present.
    Idempotent.

    Note: New repos (v6+) no longer include work_in_progress or build_plan
    in the template — build plan Status is the source of truth. This
    migration keeps adding work_in_progress so existing repos that read
    from it continue to work during the transition.

    Returns list of actions taken.
    """
    actions: list[str] = []
    state_path = product_dir / ".prawduct" / "project-state.yaml"

    if not state_path.is_file():
        return actions

    content = state_path.read_text()
    original = content

    # Remove current_phase field (v4 artifact) — top-level key, single line
    if "\ncurrent_phase:" in content or content.startswith("current_phase:"):
        lines = content.split("\n")
        new_lines = [l for l in lines if not l.startswith("current_phase:")]
        content = "\n".join(new_lines)

    # Add work_in_progress section if missing
    if "work_in_progress:" not in content:
        content = content.rstrip("\n") + "\n\n" + (
            "# =============================================================================\n"
            "# WORK IN PROGRESS (branch-scoped)\n"
            "# =============================================================================\n"
            "# Each branch gets its own entry. See project-state.yaml template for format.\n"
            "\n"
            "work_in_progress: {}\n"
        )

    # Add health_check section if missing
    if "health_check:" not in content:
        content = content.rstrip("\n") + "\n\n" + (
            "# =============================================================================\n"
            "# HEALTH CHECK\n"
            "# =============================================================================\n"
            "# Tracks periodic health check state.\n"
            "\n"
            "health_check:\n"
            "  last_full_check: null\n"
            "  last_check_findings: null\n"
        )

    if content != original:
        state_path.write_text(content)
        actions.append("Updated .prawduct/project-state.yaml for v5")

    return actions


def migrate_change_log(product_dir: Path) -> list[str]:
    """Move change_log from project-state.yaml to .prawduct/change-log.md.

    Parses YAML change_log entries, converts to markdown sections, writes
    to change-log.md (appending if it exists), and removes the change_log
    section from project-state.yaml. Idempotent: skips if no change_log
    section exists in project-state.yaml.

    Returns list of actions taken.
    """
    actions: list[str] = []
    state_path = product_dir / ".prawduct" / "project-state.yaml"
    if not state_path.is_file():
        return actions

    content = state_path.read_text()

    # Check if change_log: exists with actual entries (not just [] or {})
    if "\nchange_log:" not in content and not content.startswith("change_log:"):
        return actions

    # Find the change_log section boundaries
    lines = content.split("\n")
    cl_start = None
    cl_end = None
    for i, line in enumerate(lines):
        if line.startswith("change_log:") or line.strip() == "change_log:":
            cl_start = i
        elif cl_start is not None and not line.startswith(" ") and not line.startswith("#") and line.strip() and not line.startswith("change_log"):
            # Hit next top-level key
            cl_end = i
            break
    if cl_start is None:
        return actions

    if cl_end is None:
        cl_end = len(lines)

    # Also capture any comment lines immediately before change_log:
    comment_start = cl_start
    while comment_start > 0 and (lines[comment_start - 1].startswith("#") or lines[comment_start - 1].strip() == ""):
        if lines[comment_start - 1].startswith("# ===") or "CHANGE LOG" in lines[comment_start - 1]:
            comment_start -= 1
        elif lines[comment_start - 1].strip() == "":
            comment_start -= 1
        elif lines[comment_start - 1].startswith("#"):
            comment_start -= 1
        else:
            break

    cl_section = lines[cl_start:cl_end]

    # Parse entries from the YAML section (lightweight, no PyYAML)
    entries: list[dict[str, str]] = []
    current_entry: dict[str, str] = {}
    current_key: str | None = None

    for line in cl_section:
        stripped = line.strip()
        if stripped.startswith("- what:") or stripped.startswith("- what :"):
            if current_entry:
                entries.append(current_entry)
            current_entry = {}
            current_key = "what"
            val = stripped.split(":", 1)[1].strip().strip("\"'")
            if val:
                current_entry["what"] = val
        elif stripped.startswith("why:") and current_entry is not None:
            current_key = "why"
            val = stripped.split(":", 1)[1].strip().strip("\"'")
            if val:
                current_entry["why"] = val
        elif stripped.startswith("blast_radius:") and current_entry is not None:
            current_key = "blast_radius"
            val = stripped.split(":", 1)[1].strip().strip("\"'")
            if val:
                current_entry["blast_radius"] = val
        elif stripped.startswith("classification:") and current_entry is not None:
            current_key = "classification"
            val = stripped.split(":", 1)[1].strip().strip("\"'")
            if val:
                current_entry["classification"] = val
        elif stripped.startswith("date:") and current_entry is not None:
            current_key = "date"
            val = stripped.split(":", 1)[1].strip().strip("\"'")
            if val:
                current_entry["date"] = val
        elif current_key and current_entry is not None and stripped and not stripped.startswith("#") and not stripped.startswith("- "):
            # Continuation line for multiline YAML value
            prev = current_entry.get(current_key, "")
            continuation = stripped.strip("\"'")
            if prev:
                current_entry[current_key] = prev + " " + continuation
            else:
                current_entry[current_key] = continuation

    if current_entry:
        entries.append(current_entry)

    if not entries:
        # change_log: exists but is empty ([] or no entries) — just remove the section
        new_lines = lines[:comment_start] + lines[cl_end:]
        # Clean up double blank lines
        cleaned = "\n".join(new_lines)
        while "\n\n\n" in cleaned:
            cleaned = cleaned.replace("\n\n\n", "\n\n")
        state_path.write_text(cleaned)
        actions.append("Removed empty change_log section from project-state.yaml")
        return actions

    # Convert entries to markdown
    md_entries: list[str] = []
    for entry in entries:
        date = entry.get("date", "unknown")
        what = entry.get("what", "Untitled change")
        md = f"## {date}: {what}"
        if entry.get("why"):
            md += f"\n\n**Why:** {entry['why']}"
        if entry.get("blast_radius"):
            md += f"\n\n**Blast radius:** {entry['blast_radius']}"
        if entry.get("classification"):
            md += f"\n\n**Classification:** {entry['classification']}"
        md_entries.append(md)

    # Write to change-log.md
    cl_path = product_dir / ".prawduct" / "change-log.md"
    product_name = product_dir.name
    if cl_path.is_file():
        existing = cl_path.read_text()
        # Append migrated entries at the end with a separator
        separator = "\n\n<!-- Migrated from project-state.yaml -->\n\n"
        cl_path.write_text(existing.rstrip("\n") + separator + "\n\n".join(md_entries) + "\n")
    else:
        header = f"# Change Log — {product_name}\n\n<!-- Append new entries at the top. -->\n\n"
        cl_path.write_text(header + "\n\n".join(md_entries) + "\n")

    actions.append(f"Migrated {len(entries)} change_log entries to .prawduct/change-log.md")

    # Remove change_log section from project-state.yaml
    # Replace with a pointer comment
    pointer = (
        "# =============================================================================\n"
        "# CHANGE LOG\n"
        "# =============================================================================\n"
        "# Change log moved to .prawduct/change-log.md (separate file for merge-friendliness).\n"
    )
    new_lines = lines[:comment_start] + pointer.split("\n") + lines[cl_end:]
    cleaned = "\n".join(new_lines)
    while "\n\n\n" in cleaned:
        cleaned = cleaned.replace("\n\n\n", "\n\n")
    state_path.write_text(cleaned)
    actions.append("Removed change_log section from project-state.yaml (replaced with pointer)")

    return actions


def migrate_backlog(product_dir: Path) -> list[str]:
    """Move remaining_work/future_work/deferred_work from project-state.yaml to backlog.md.

    For remaining_work (under build_plan): parses item/description/phase fields,
    skips completed items, converts pending items to markdown bullets.
    For other sections (future_work, deferred_work, backlog): extracts raw YAML
    and wraps in a code block with cleanup marker.

    Idempotent: skips if no matching sections exist in project-state.yaml.
    Returns list of actions taken.
    """
    actions: list[str] = []
    state_path = product_dir / ".prawduct" / "project-state.yaml"
    if not state_path.is_file():
        return actions

    content = state_path.read_text()
    lines = content.split("\n")
    backlog_items: list[str] = []
    raw_sections: list[str] = []
    sections_removed: list[tuple[int, int, str]] = []  # (start, end, pointer)

    # --- remaining_work under build_plan ---
    rw_start = None
    rw_end = None
    rw_comment_start = None
    for i, line in enumerate(lines):
        if rw_start is None:
            # Match indented remaining_work: under build_plan
            stripped = line.strip()
            if stripped.startswith("remaining_work:") and line.startswith("  "):
                rw_start = i
                # Capture preceding comment lines at same or deeper indent
                rw_comment_start = i
                while rw_comment_start > 0:
                    prev = lines[rw_comment_start - 1]
                    if prev.strip().startswith("#") and prev.startswith("  "):
                        rw_comment_start -= 1
                    else:
                        break
        elif rw_start is not None and rw_end is None:
            # Find end: next line at same or lesser indentation (not blank/comment)
            if line.strip() and not line.strip().startswith("#"):
                indent = len(line) - len(line.lstrip())
                if indent <= 2:
                    rw_end = i
                    break

    if rw_start is not None:
        if rw_end is None:
            rw_end = len(lines)

        rw_section = lines[rw_start:rw_end]

        # Parse remaining_work entries
        entries: list[dict[str, str]] = []
        current_entry: dict[str, str] = {}
        current_key: str | None = None

        for line in rw_section:
            stripped = line.strip()
            if stripped.startswith("- item:"):
                if current_entry:
                    entries.append(current_entry)
                current_entry = {}
                current_key = "item"
                val = stripped.split(":", 1)[1].strip().strip("\"'")
                if val:
                    current_entry["item"] = val
            elif stripped.startswith("description:") and current_entry:
                current_key = "description"
                val = stripped.split(":", 1)[1].strip().strip("\"'")
                if val:
                    current_entry["description"] = val
            elif stripped.startswith("phase:") and current_entry:
                current_key = "phase"
                val = stripped.split(":", 1)[1].strip().strip("\"'")
                if val:
                    current_entry["phase"] = val
            elif current_key and current_entry and stripped and not stripped.startswith("#") and not stripped.startswith("- "):
                # Continuation line
                prev = current_entry.get(current_key, "")
                continuation = stripped.strip("\"'")
                if prev:
                    current_entry[current_key] = prev + " " + continuation
                else:
                    current_entry[current_key] = continuation

        if current_entry:
            entries.append(current_entry)

        # Convert non-completed entries to markdown
        for entry in entries:
            phase = entry.get("phase", "").lower()
            if phase == "completed":
                continue
            item = entry.get("item", "Untitled")
            desc = entry.get("description", "")
            bullet = f"- **{item}**"
            if desc:
                bullet += f" — {desc}"
            bullet += " (migrated)"
            backlog_items.append(bullet)

        # Mark for removal (use comment_start to capture preceding comments)
        pointer = "    # remaining_work: migrated to .prawduct/backlog.md\n"
        sections_removed.append((rw_comment_start, rw_end, pointer))

    # --- Top-level sections: future_work, deferred_work, backlog ---
    top_level_keys = ["future_work", "deferred_work", "backlog"]
    for key in top_level_keys:
        marker = f"{key}:"
        if f"\n{marker}" not in content and not content.startswith(marker):
            continue

        sec_start = None
        sec_end = None
        for i, line in enumerate(lines):
            if sec_start is None:
                if line.startswith(marker) or line.strip() == marker:
                    sec_start = i
            elif sec_start is not None:
                if line.strip() and not line.startswith(" ") and not line.startswith("#"):
                    sec_end = i
                    break

        if sec_start is None:
            continue
        if sec_end is None:
            sec_end = len(lines)

        # Capture preceding comments
        comment_start = sec_start
        while comment_start > 0:
            prev = lines[comment_start - 1]
            if prev.strip().startswith("#") or prev.strip() == "":
                comment_start -= 1
            else:
                break

        raw_yaml = "\n".join(lines[sec_start:sec_end]).rstrip()
        raw_sections.append(
            f"<!-- CLEANUP: Migrated from project-state.yaml ({key}).\n"
            f"     Review and convert to standard backlog items, then delete this block. -->\n"
            f"```yaml\n{raw_yaml}\n```"
        )

        pointer = f"# {key}: migrated to .prawduct/backlog.md\n"
        sections_removed.append((comment_start, sec_end, pointer))

    if not backlog_items and not raw_sections:
        return actions

    # Build backlog content
    md_parts: list[str] = []
    if backlog_items:
        md_parts.extend(backlog_items)
    if raw_sections:
        md_parts.extend(raw_sections)
    migrated_content = "\n".join(md_parts)

    # Write to backlog.md
    backlog_path = product_dir / ".prawduct" / "backlog.md"
    product_name = product_dir.name
    if backlog_path.is_file():
        existing = backlog_path.read_text()
        separator = "\n\n<!-- Migrated from project-state.yaml -->\n\n"
        backlog_path.write_text(existing.rstrip("\n") + separator + migrated_content + "\n")
    else:
        header = (
            f"# Backlog — {product_name}\n\n"
            "<!-- Work discovered during sessions but out of current scope.\n"
            "     Add items at the top. Each is a bullet with source marker:\n"
            "     (builder), (critic), (reflection), or (migrated).\n"
            "     Review with /janitor or when planning new work. -->\n\n"
        )
        backlog_path.write_text(header + migrated_content + "\n")

    item_count = len(backlog_items) + len(raw_sections)
    actions.append(f"Migrated {item_count} backlog item(s) to .prawduct/backlog.md")

    # Remove sections from project-state.yaml (process in reverse order to preserve indices)
    sections_removed.sort(key=lambda x: x[0], reverse=True)
    for start, end, pointer in sections_removed:
        lines[start:end] = pointer.split("\n")

    cleaned = "\n".join(lines)
    while "\n\n\n" in cleaned:
        cleaned = cleaned.replace("\n\n\n", "\n\n")
    state_path.write_text(cleaned)
    actions.append("Removed migrated sections from project-state.yaml")

    return actions


def generate_sync_manifest(target: Path, product_name: str) -> bool:
    """Generate sync manifest for the product repo. Returns True if created."""
    manifest_path = target / ".prawduct" / "sync-manifest.json"
    if manifest_path.is_file():
        return False

    claude_path = target / "CLAUDE.md"
    if claude_path.is_file():
        claude_hash = compute_block_hash(claude_path.read_text())
        if claude_hash is None:
            claude_hash = compute_hash(claude_path)
    else:
        claude_hash = None

    file_hashes = {
        "CLAUDE.md": claude_hash,
        ".prawduct/critic-review.md": compute_hash(
            target / ".prawduct" / "critic-review.md"
        ),
        "tools/product-hook": compute_hash(target / "tools" / "product-hook"),
        ".claude/settings.json": None,
    }
    manifest = create_manifest(target, FRAMEWORK_DIR, product_name, file_hashes)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    return True


def run_migrate(target_dir: str, product_name: str | None = None) -> dict:
    """Migrate a product repo to v5. Returns a summary of actions taken."""
    target = Path(target_dir).resolve()
    actions: list[str] = []

    version = detect_version(target)

    # Safety: refuse to migrate directories that aren't Prawduct repos
    if version == "unknown":
        return {
            "target": str(target),
            "product_name": product_name or target.name,
            "version_before": version,
            "version_after": version,
            "actions": [],
            "files_changed": 0,
            "error": "Not a Prawduct repo (no .prawduct/framework-path or tools/product-hook found)",
        }

    # Infer product name if not provided
    if product_name is None:
        product_name = infer_product_name(target)
    if product_name is None:
        product_name = target.name

    subs = {"{{PRODUCT_NAME}}": product_name, "{{PRAWDUCT_VERSION}}": PRAWDUCT_VERSION}

    # Deprecation notice for old versions
    if version == "v1":
        actions.append(
            "DEPRECATION: v1 repos are no longer supported. "
            "Migrating to v5 — review CLAUDE.md and .prawduct/ after migration."
        )
    elif version == "v3":
        actions.append(
            "DEPRECATION: v3 repos are no longer supported. "
            "Migrating to v5 — review CLAUDE.md and .prawduct/ after migration."
        )
    elif version == "partial":
        actions.append(
            "DEPRECATION: partial (v1→v3) repos are no longer supported. "
            "Migrating to v5 — review CLAUDE.md and .prawduct/ after migration."
        )

    # === V1-specific steps (v1 and partial) ===
    if version in ("v1", "partial"):
        # 1. Overwrite CLAUDE.md with current template
        if write_template(
            TEMPLATES_DIR / "product-claude.md", target / "CLAUDE.md", subs, overwrite=True
        ):
            actions.append("Overwrote CLAUDE.md with current template")

        # 2. Delete v1 marker files
        deleted = delete_v1_files(target)
        for f in deleted:
            actions.append(f"Deleted {f}")

        # 3. Archive v1 directories
        archived = archive_v1_dirs(target)
        for d in archived:
            actions.append(f"Archived {d} → .prawduct/archive/")

        # 4. Clean v1 session files
        cleaned = clean_v1_session_files(target)
        for f in cleaned:
            actions.append(f"Deleted session file {f}")

    # === Steps for all non-v4 repos (v1, v3, partial) ===

    # Replace hooks in settings.json (handles v1, v3 bash, and adds banner)
    if merge_settings(
        target / ".claude" / "settings.json",
        TEMPLATES_DIR / "product-settings.json",
        subs,
        legacy_cleanup=True,
    ):
        actions.append("Updated .claude/settings.json (hooks + banner)")

    # Copy product-hook (Python version)
    if copy_hook(
        FRAMEWORK_DIR / "tools" / "product-hook",
        target / "tools" / "product-hook",
    ):
        actions.append("Installed tools/product-hook (Python)")

    # Ship tools/lib alongside the hook — product-hook imports it at runtime
    # (regen-views, operator-verification). Eager + idempotent so a migrated
    # repo is never in the degraded "hook present, lib absent" state that
    # crashes those commands; mirrors init step 9b and MANAGED_DIRS.
    lib_src = FRAMEWORK_DIR / "tools" / "lib"
    if lib_src.is_dir():
        lib_dst = target / "tools" / "lib"
        lib_dst.mkdir(parents=True, exist_ok=True)
        wrote_lib = False
        for module in sorted(lib_src.glob("*.py")):
            dst_module = lib_dst / module.name
            if compute_hash(dst_module) != compute_hash(module):
                shutil.copy2(module, dst_module)
                wrote_lib = True
        if wrote_lib:
            actions.append("Installed tools/lib/")

    # Create critic-review.md if missing
    if write_template(
        TEMPLATES_DIR / "critic-review.md",
        target / ".prawduct" / "critic-review.md",
        subs,
    ):
        actions.append("Created .prawduct/critic-review.md")

    # Create learnings.md if missing
    learnings = target / ".prawduct" / "learnings.md"
    if not learnings.is_file():
        learnings.parent.mkdir(parents=True, exist_ok=True)
        learnings.write_text(
            "# Learnings\n\nAccumulated wisdom from building this product.\n"
        )
        actions.append("Created .prawduct/learnings.md")

    # Generate sync manifest
    if generate_sync_manifest(target, product_name):
        actions.append("Created .prawduct/sync-manifest.json")

    # Clean gitignore
    if clean_gitignore(target):
        actions.append("Updated .gitignore")

    # Add block markers to CLAUDE.md if missing
    if add_block_markers(target, subs):
        actions.append("Added block markers to CLAUDE.md")

    # Upgrade manifest strategy from template to block_template
    if upgrade_manifest_strategy(target):
        actions.append("Upgraded CLAUDE.md sync strategy to block_template")

    # === V5 migration steps (idempotent, applies to all repos) ===

    # Remove stale test_tracking from project-state.yaml (test count is derived)
    actions.extend(strip_test_tracking(target))

    # Split learnings into active rules + reference detail
    actions.extend(split_learnings_v5(target))

    # Update project-state.yaml (add v5 sections, remove v4 fields)
    actions.extend(migrate_project_state_v5(target))

    # Place boundary-patterns.md if missing
    bp_src = TEMPLATES_DIR / "boundary-patterns.md"
    bp_dst = target / ".prawduct" / "artifacts" / "boundary-patterns.md"
    if bp_src.is_file() and not bp_dst.is_file():
        rendered = render_template(bp_src, subs)
        bp_dst.parent.mkdir(parents=True, exist_ok=True)
        bp_dst.write_text(rendered)
        actions.append("Created .prawduct/artifacts/boundary-patterns.md")

    # Bump manifest version to 2 if needed
    manifest_path = target / ".prawduct" / "sync-manifest.json"
    if manifest_path.is_file():
        try:
            mf = load_json(manifest_path)
            if mf.get("format_version", 1) < 2:
                mf["format_version"] = 2
                manifest_path.write_text(json.dumps(mf, indent=2) + "\n")
                actions.append("Bumped manifest to format_version 2 (v5)")
        except json.JSONDecodeError:
            pass

    return {
        "target": str(target),
        "product_name": product_name,
        "version_before": version,
        "version_after": detect_version(target),
        "actions": actions,
        "files_changed": len(actions),
    }


# =============================================================================
# F10 — operator-verification queue (manifest flag + project-state flip +
# template placement). Mirrors ``enable_v1_4_coverage`` rather than
# ``enable_v1_4_settings_layout``: the migration is enforcement-touching, so
# turning it on commits the project to BLOCKING /pr gates whenever the queue
# has pending entries. Per the "Auto-enable belongs with visibility, not
# enforcement" learning, this never auto-fires from sync — only from explicit
# ``prawduct-setup migrate --enable-operator-verification``.
# =============================================================================


def enable_v1_4_operator_verification(
    product_dir: Path,
    manifest: dict,
    *,
    force: bool = False,
) -> tuple[list[str], list[str]]:
    """User-invoked v1.4 migration: enable F10 operator-verification gate.

    Three side effects, each idempotent:

      1. Flips ``operator_verification_required: false`` → ``true`` in
         ``project-state.yaml`` (appends a documented block when the key
         is absent — same column-0 detector/mutator pattern as
         ``enable_v1_4_coverage`` so inline-comment forms are tolerated).
      2. Places ``.prawduct/operator-verification.md`` from the framework
         template if absent (the queue file must exist before the
         ``/pr`` gate can read it).
      3. Sets ``manifest['v1_4_operator_verification_enabled'] = True`` so
         accidental re-invocations short-circuit. ``force=True`` bypasses
         the one-shot check.

    Returns ``(actions, notes)``. Actions are file mutations; notes
    surface the next-PR consequence (Critic Goal 2 NOTE for visual-change
    chunks; ``/pr create`` BLOCKING on pending entries).
    """
    actions: list[str] = []
    notes: list[str] = []

    if manifest.get("v1_4_operator_verification_enabled") and not force:
        return actions, notes

    prawduct_dir = product_dir / ".prawduct"
    state_path = prawduct_dir / "project-state.yaml"
    queue_path = prawduct_dir / "operator-verification.md"

    if not state_path.is_file():
        return actions, notes

    content = state_path.read_text()
    original = content

    has_key = (
        "\noperator_verification_required:" in content
        or content.startswith("operator_verification_required:")
    )

    already_on = False
    if has_key:
        for raw in content.splitlines():
            if raw[:1] in (" ", "\t"):
                continue
            stripped = raw.split("#", 1)[0].rstrip()
            if stripped.startswith("operator_verification_required:"):
                value = stripped.split(":", 1)[1].strip().lower()
                already_on = value == "true"
                break

    if has_key and not already_on:
        new_lines: list[str] = []
        flipped = False
        for line in content.split("\n"):
            if flipped or line[:1] in (" ", "\t"):
                new_lines.append(line)
                continue
            stripped = line.split("#", 1)[0].rstrip()
            if (
                stripped.startswith("operator_verification_required:")
                and stripped.split(":", 1)[1].strip().lower() == "false"
            ):
                tail = line.split("#", 1)[1] if "#" in line else ""
                rewritten = "operator_verification_required: true"
                if tail:
                    rewritten += "  #" + tail
                new_lines.append(rewritten)
                flipped = True
            else:
                new_lines.append(line)
        if flipped:
            content = "\n".join(new_lines)
            actions.append(
                "Flipped operator_verification_required: false → true in "
                "project-state.yaml (v1.4 F10 operator-verification gate enabled)"
            )

    if not has_key:
        if content and not content.endswith("\n"):
            content += "\n"
        content += (
            "\n"
            "# =============================================================================\n"
            "# OPERATOR VERIFICATION (opt-in, v1.4+)\n"
            "# =============================================================================\n"
            "# When true, `/pr create` BLOCKS if `.prawduct/operator-verification.md`\n"
            "# has any entry with `**Status:** pending`. Drain via\n"
            "# `python3 tools/prawduct-setup.py verify <product_dir> <VRF-ID>` or\n"
            "# override per-PR with `--accept-pending-verification \"rationale\"`.\n"
            "# Enabled by `prawduct-setup migrate --enable-operator-verification`.\n"
            "\n"
            "operator_verification_required: true\n"
        )
        actions.append(
            "Added operator_verification_required: true to project-state.yaml "
            "(v1.4 F10 operator-verification gate enabled)"
        )

    if content != original:
        state_path.write_text(content)

    if already_on and not actions:
        notes.append(
            "operator_verification_required is already true — nothing to "
            "flip. Re-running with --force re-places the queue template if missing."
        )

    # Place the queue template if absent. Mutates only on first run (and on
    # --force re-placement when the file is missing); existing queues are
    # never overwritten — they are append-only user state.
    if not queue_path.is_file():
        template_path = TEMPLATES_DIR / "operator-verification.md"
        if template_path.is_file():
            prawduct_dir.mkdir(parents=True, exist_ok=True)
            queue_path.write_text(template_path.read_text())
            actions.append(
                f"Placed {queue_path.relative_to(product_dir)} from template "
                "(empty queue; ready for chunk-close enqueues)"
            )
        else:
            notes.append(
                f"Could not place {queue_path.relative_to(product_dir)}: "
                f"framework template missing at {template_path}. "
                "Verify the framework checkout is complete."
            )

    notes.append(
        "Next-PR consequence: `/pr create` will BLOCK whenever "
        "`.prawduct/operator-verification.md` has pending entries. "
        "Append entries during chunk-close for visual / live-integration "
        "changes (see methodology/building.md). Override with "
        "`/pr create --accept-pending-verification \"rationale\"`."
    )

    manifest["v1_4_operator_verification_enabled"] = True

    return actions, notes


def run_migrate_operator_verification(
    product_dir: str, *, force: bool = False
) -> dict:
    """User-facing runner for ``prawduct-setup migrate --enable-operator-verification``.

    Loads ``sync-manifest.json``, invokes :func:`enable_v1_4_operator_verification`,
    persists the manifest, and returns a dict shaped like the other migrate
    runners (``product_dir``, ``enabled``, ``force``, ``actions``, ``notes``)
    or ``{"error": "..."}``.

    Re-reads ``operator_verification_required`` from on-disk state after
    the migration so ``enabled`` reflects ground truth (the manifest flag
    records "we ran the migration"; the YAML may have been hand-edited
    between runs).
    """
    product_path = Path(product_dir).resolve()
    prawduct_dir = product_path / ".prawduct"
    if not prawduct_dir.is_dir():
        return {
            "error": (
                f"Not a prawduct product: {product_path} has no .prawduct/ directory"
            )
        }

    manifest_path = prawduct_dir / "sync-manifest.json"
    if not manifest_path.is_file():
        return {
            "error": (
                f"No sync-manifest.json at {manifest_path} — run "
                "`prawduct-setup setup` to initialize the product repo before "
                "migrating."
            )
        }

    try:
        manifest = load_json(manifest_path)
    except (json.JSONDecodeError, OSError) as exc:
        return {"error": f"Could not read sync-manifest.json: {exc}"}

    try:
        actions, notes = enable_v1_4_operator_verification(
            product_path, manifest, force=force
        )
    except OSError as exc:
        return {"error": f"Migration failed: {exc}"}

    try:
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    except OSError as exc:
        return {"error": f"Could not write sync-manifest.json: {exc}"}

    state_path = prawduct_dir / "project-state.yaml"
    enabled = False
    if state_path.is_file():
        for raw in state_path.read_text().splitlines():
            if raw[:1] in (" ", "\t"):
                continue
            stripped = raw.split("#", 1)[0].rstrip()
            if stripped.startswith("operator_verification_required:"):
                enabled = stripped.split(":", 1)[1].strip().lower() == "true"
                break

    return {
        "product_dir": str(product_path),
        "enabled": enabled,
        "force": force,
        "actions": actions,
        "notes": notes,
    }
