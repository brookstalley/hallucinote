"""
Init command for prawduct product repos.

Initializes a new product repo with all prawduct files, hooks, and settings.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from .core import (
    BLOCK_BEGIN,
    FRAMEWORK_DIR,
    PLACE_ONCE_COPY,
    PLACE_ONCE_TEMPLATES,
    PRAWDUCT_VERSION,
    SKILL_PLACEMENTS,
    TEMPLATES_DIR,
    compute_block_hash,
    compute_hash,
    copy_hook,
    create_manifest,
    ensure_dir,
    merge_settings,
    render_template,
    update_gitignore,
    write_template,
)


def run_init(target_dir: str, product_name: str) -> dict:
    """Initialize a product repo. Returns a summary of actions taken."""
    target = Path(target_dir).resolve()
    actions: list[str] = []

    subs = {
        "{{PRODUCT_NAME}}": product_name,
        "{{PRAWDUCT_VERSION}}": PRAWDUCT_VERSION,
    }

    # 1. .prawduct/ structure
    for subdir in [".prawduct", ".prawduct/artifacts"]:
        path = target / subdir
        if ensure_dir(path):
            actions.append(f"Created {subdir}/")

    # 2. CLAUDE.md — three-way handling for existing repos
    claude_dst = target / "CLAUDE.md"
    if not claude_dst.is_file():
        # New file — write full template
        if write_template(TEMPLATES_DIR / "product-claude.md", claude_dst, subs):
            actions.append("Created CLAUDE.md")
    elif BLOCK_BEGIN not in claude_dst.read_text():
        # Existing file without markers — merge: template + user content below
        existing_content = claude_dst.read_text()
        template_content = render_template(TEMPLATES_DIR / "product-claude.md", subs)
        merged = template_content.rstrip("\n") + "\n\n" + existing_content
        claude_dst.write_text(merged)
        actions.append("Merged framework content into existing CLAUDE.md")
    # else: already has markers — skip (sync handles updates)

    # 3. Critic review instructions
    if write_template(
        TEMPLATES_DIR / "critic-review.md",
        target / ".prawduct" / "critic-review.md",
        subs,
    ):
        actions.append("Created .prawduct/critic-review.md")

    # 4. Project state
    if write_template(
        TEMPLATES_DIR / "project-state.yaml",
        target / ".prawduct" / "project-state.yaml",
        subs,
    ):
        actions.append("Created .prawduct/project-state.yaml")

    # 5. Project preferences template
    if write_template(
        TEMPLATES_DIR / "project-preferences.md",
        target / ".prawduct" / "artifacts" / "project-preferences.md",
        subs,
    ):
        actions.append("Created .prawduct/artifacts/project-preferences.md")

    # 6. Boundary patterns template
    if write_template(
        TEMPLATES_DIR / "boundary-patterns.md",
        target / ".prawduct" / "artifacts" / "boundary-patterns.md",
        subs,
    ):
        actions.append("Created .prawduct/artifacts/boundary-patterns.md")

    # 6.5. PR review evidence directory
    pr_reviews_dir = target / ".prawduct" / ".pr-reviews"
    if ensure_dir(pr_reviews_dir):
        actions.append("Created .prawduct/.pr-reviews/")

    # 6.7. PR review instructions
    if write_template(
        TEMPLATES_DIR / "pr-review.md",
        target / ".prawduct" / "pr-review.md",
        subs,
    ):
        actions.append("Created .prawduct/pr-review.md")

    # 6.72. Build governance
    if write_template(
        TEMPLATES_DIR / "build-governance.md",
        target / ".prawduct" / "build-governance.md",
        subs,
    ):
        actions.append("Created .prawduct/build-governance.md")

    # 6.75. Backlog
    if write_template(
        TEMPLATES_DIR / "backlog.md",
        target / ".prawduct" / "backlog.md",
        subs,
    ):
        actions.append("Created .prawduct/backlog.md")

    # 6.8–6.12. Skills
    for skill_name, skill_src in SKILL_PLACEMENTS:
        skill_dir = target / ".claude" / "skills" / skill_name
        if ensure_dir(skill_dir):
            actions.append(f"Created .claude/skills/{skill_name}/")
        skill_dst = skill_dir / "SKILL.md"
        if skill_src.is_file() and write_template(skill_src, skill_dst, subs):
            actions.append(f"Created .claude/skills/{skill_name}/SKILL.md")

    # 7. Test infrastructure (conftest.py — only for Python projects)
    is_python = any(
        (target / f).is_file()
        for f in ("pyproject.toml", "setup.py", "setup.cfg", "Pipfile", "requirements.txt")
    )
    tests_dir = target / "tests"
    if ensure_dir(tests_dir):
        actions.append("Created tests/")
    if is_python:
        conftest_dst = tests_dir / "conftest.py"
        if not conftest_dst.is_file():
            shutil.copy2(TEMPLATES_DIR / "conftest.py", conftest_dst)
            actions.append("Created tests/conftest.py (parallel test support)")

    # 8. Learnings starter
    learnings = target / ".prawduct" / "learnings.md"
    if not learnings.is_file():
        learnings.write_text(
            "# Learnings\n\nAccumulated wisdom from building this product.\n"
        )
        actions.append("Created .prawduct/learnings.md")

    # 9. Product hook
    if copy_hook(
        FRAMEWORK_DIR / "tools" / "product-hook",
        target / "tools" / "product-hook",
    ):
        actions.append("Created tools/product-hook")

    # 10. Settings.json (with subs for banner)
    if merge_settings(
        target / ".claude" / "settings.json",
        TEMPLATES_DIR / "product-settings.json",
        subs,
    ):
        actions.append("Created/updated .claude/settings.json")

    # 11. .gitignore
    if update_gitignore(target)["modified"]:
        actions.append("Updated .gitignore")

    # 12. Sync manifest
    manifest_path = target / ".prawduct" / "sync-manifest.json"
    if not manifest_path.is_file():
        claude_content = (target / "CLAUDE.md").read_text()
        file_hashes = {
            "CLAUDE.md": compute_block_hash(claude_content),
            ".prawduct/critic-review.md": compute_hash(
                target / ".prawduct" / "critic-review.md"
            ),
            ".prawduct/pr-review.md": compute_hash(
                target / ".prawduct" / "pr-review.md"
            ),
            "tools/product-hook": compute_hash(target / "tools" / "product-hook"),
            ".claude/settings.json": None,  # merge_settings doesn't use hash
        }
        for skill_name, _ in SKILL_PLACEMENTS:
            rel = f".claude/skills/{skill_name}/SKILL.md"
            file_hashes[rel] = compute_hash(target / rel)
        manifest = create_manifest(target, FRAMEWORK_DIR, product_name, file_hashes)

        # Record place-once template hashes so sync can detect template drift
        pot: dict[str, dict] = {}
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        for rel_path, template_rel in PLACE_ONCE_TEMPLATES.items():
            template_path = TEMPLATES_DIR / template_rel.removeprefix("templates/")
            if template_path.is_file():
                rendered = render_template(template_path, subs)
                pot[rel_path] = {
                    "template": template_rel,
                    "template_hash": hashlib.sha256(rendered.encode()).hexdigest(),
                    "created_at": now,
                }
        for rel_path, template_rel in PLACE_ONCE_COPY.items():
            template_path = TEMPLATES_DIR / template_rel.removeprefix("templates/")
            if template_path.is_file():
                content = template_path.read_bytes()
                pot[rel_path] = {
                    "template": template_rel,
                    "template_hash": hashlib.sha256(content).hexdigest(),
                    "created_at": now,
                }
        if pot:
            manifest["place_once_templates"] = pot

        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
        actions.append("Created .prawduct/sync-manifest.json")

    return {
        "target": str(target),
        "product_name": product_name,
        "actions": actions,
        "files_written": len(actions),
    }
