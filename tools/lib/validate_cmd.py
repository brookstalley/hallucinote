"""
Validate command for prawduct product repos.

Health check — verifies repo structure, configuration, and framework currency.
No mutations.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

from .core import (
    BLOCK_BEGIN,
    BLOCK_END,
    MANAGED_FILES,
    PRAWDUCT_VERSION,
    _resolve_framework_dir,
    compute_hash,
    detect_version,
    extract_block,
    load_json,
    render_template,
)
from .sync_cmd import _match_historical_render


def run_validate(target_dir: str, *, framework_dir: str | None = None) -> dict:
    """Health check for a prawduct product repo. No mutations.

    Returns structured results with per-check pass/warn/fail status,
    overall health, restart recommendation, and actionable recommendations.
    """
    target = Path(target_dir).resolve()
    checks: list[dict] = []
    recommendations: list[str] = []
    needs_restart = False

    # --- Basic structure ---
    prawduct_dir = target / ".prawduct"
    if not prawduct_dir.is_dir():
        return {
            "target": str(target),
            "overall": "broken",
            "version": "unknown",
            "checks": [{"name": "prawduct_dir", "status": "fail", "detail": ".prawduct/ directory does not exist"}],
            "needs_restart": False,
            "recommendations": ["Run prawduct-setup.py setup to initialize this repo"],
        }

    version = detect_version(target)

    # --- Managed files ---
    missing_managed = []
    for rel_path in MANAGED_FILES:
        if not (target / rel_path).is_file():
            missing_managed.append(rel_path)
    if missing_managed:
        checks.append({
            "name": "managed_files",
            "status": "fail",
            "detail": f"Missing: {', '.join(missing_managed)}",
        })
        recommendations.append("Run prawduct-setup.py setup to create missing files")
    else:
        checks.append({"name": "managed_files", "status": "pass", "detail": f"All {len(MANAGED_FILES)} managed files present"})

    # --- settings.json hooks ---
    settings_path = target / ".claude" / "settings.json"
    if settings_path.is_file():
        try:
            settings = load_json(settings_path)
            hooks = settings.get("hooks", {})
            expected_events = ["SessionStart", "Stop"]
            missing_events = [e for e in expected_events if e not in hooks]

            if missing_events:
                checks.append({
                    "name": "settings_hooks",
                    "status": "fail",
                    "detail": f"Missing hook events: {', '.join(missing_events)}",
                })
                recommendations.append("Run prawduct-setup.py setup to fix settings.json hooks")
            else:
                # Verify hooks reference product-hook
                all_point_to_hook = True
                for event in expected_events:
                    entries = hooks.get(event, [])
                    has_product_hook = any(
                        "product-hook" in h.get("command", "")
                        for entry in entries
                        for h in entry.get("hooks", [])
                    )
                    if not has_product_hook:
                        all_point_to_hook = False
                        break

                if all_point_to_hook:
                    checks.append({"name": "settings_hooks", "status": "pass", "detail": "All hook events configured correctly"})
                else:
                    checks.append({
                        "name": "settings_hooks",
                        "status": "warn",
                        "detail": "Some hooks don't reference product-hook",
                    })
        except json.JSONDecodeError:
            checks.append({"name": "settings_hooks", "status": "fail", "detail": "settings.json is not valid JSON"})
            recommendations.append("Fix or regenerate .claude/settings.json")
    else:
        checks.append({"name": "settings_hooks", "status": "fail", "detail": ".claude/settings.json does not exist"})

    # --- product-hook executable ---
    hook_path = target / "tools" / "product-hook"
    if hook_path.is_file():
        is_executable = os.access(str(hook_path), os.X_OK)
        first_line = hook_path.read_text().split("\n", 1)[0] if hook_path.stat().st_size > 0 else ""
        if is_executable and first_line.startswith("#!/usr/bin/env python3"):
            checks.append({"name": "hook_executable", "status": "pass", "detail": "product-hook exists, executable, correct shebang"})
        elif not is_executable:
            checks.append({"name": "hook_executable", "status": "fail", "detail": "product-hook exists but is not executable"})
            recommendations.append("chmod +x tools/product-hook")
        else:
            checks.append({"name": "hook_executable", "status": "warn", "detail": f"Unexpected shebang: {first_line[:50]}"})
    else:
        checks.append({"name": "hook_executable", "status": "fail", "detail": "tools/product-hook does not exist"})

    # --- product-hook runtime library (tools/lib) ---
    # product-hook imports tools/lib at runtime (regen-views, operator-
    # verification, advisories). A repo missing it crashes on those commands.
    lib_dir = target / "tools" / "lib"
    lib_modules = sorted(lib_dir.glob("*.py")) if lib_dir.is_dir() else []
    if lib_modules and (lib_dir / "__init__.py").is_file():
        checks.append({"name": "hook_library", "status": "pass", "detail": f"tools/lib present ({len(lib_modules)} modules)"})
    elif hook_path.is_file():
        # Only a problem when product-hook is present (it's the importer).
        checks.append({"name": "hook_library", "status": "fail", "detail": "tools/lib missing or incomplete — regen-views / operator-verification will crash"})
        recommendations.append("Run prawduct-setup.py sync to install tools/lib")

    # --- CLAUDE.md block markers ---
    claude_path = target / "CLAUDE.md"
    if claude_path.is_file():
        content = claude_path.read_text()
        has_begin = BLOCK_BEGIN in content
        has_end = BLOCK_END in content
        if has_begin and has_end:
            begin_idx = content.find(BLOCK_BEGIN)
            end_idx = content.find(BLOCK_END)
            if begin_idx < end_idx:
                checks.append({"name": "claude_md_markers", "status": "pass", "detail": "Block markers present and well-formed"})
            else:
                checks.append({"name": "claude_md_markers", "status": "fail", "detail": "Block markers in wrong order (END before BEGIN)"})
        elif has_begin or has_end:
            checks.append({"name": "claude_md_markers", "status": "fail", "detail": "Only one block marker found (need both BEGIN and END)"})
        else:
            checks.append({"name": "claude_md_markers", "status": "warn", "detail": "No block markers — framework updates won't sync to CLAUDE.md"})
    else:
        checks.append({"name": "claude_md_markers", "status": "fail", "detail": "CLAUDE.md does not exist"})

    # --- Sync manifest ---
    manifest_path = prawduct_dir / "sync-manifest.json"
    if manifest_path.is_file():
        try:
            manifest = load_json(manifest_path)
            fmt_ver = manifest.get("format_version", 0)
            if fmt_ver >= 2:
                checks.append({"name": "sync_manifest", "status": "pass", "detail": f"Valid manifest, format_version {fmt_ver}"})
            else:
                checks.append({"name": "sync_manifest", "status": "warn", "detail": f"Manifest format_version {fmt_ver} (expected >= 2, will auto-migrate)"})

            # Check framework reachable
            fw_source = manifest.get("framework_source", "")
            fw_dir = _resolve_framework_dir(manifest, framework_dir, target)
            if fw_dir and fw_dir.is_dir():
                checks.append({"name": "framework_reachable", "status": "pass", "detail": f"Framework at {fw_dir}"})
            else:
                checks.append({
                    "name": "framework_reachable",
                    "status": "warn",
                    "detail": f"Framework not reachable (configured: {fw_source})",
                })
                recommendations.append("Set PRAWDUCT_FRAMEWORK_DIR or clone framework as sibling ../prawduct")

            # Check last sync time
            last_sync = manifest.get("last_sync", "")
            if last_sync:
                checks.append({"name": "last_sync", "status": "pass", "detail": f"Last sync: {last_sync}"})

        except json.JSONDecodeError:
            checks.append({"name": "sync_manifest", "status": "fail", "detail": "sync-manifest.json is not valid JSON"})
    else:
        checks.append({"name": "sync_manifest", "status": "warn", "detail": "No sync manifest — will be bootstrapped on next sync"})

    # --- Template variable residue ---
    template_var_files = []
    for rel_path in MANAGED_FILES:
        file_path = target / rel_path
        if file_path.is_file():
            try:
                content = file_path.read_text()
                if re.search(r"\{\{[A-Z_]+\}\}", content):
                    template_var_files.append(rel_path)
            except Exception:  # prawduct:ok-broad-except — validation must not crash
                pass
    if template_var_files:
        checks.append({
            "name": "template_variables",
            "status": "warn",
            "detail": f"Unresolved template variables in: {', '.join(template_var_files)}",
        })
    else:
        checks.append({"name": "template_variables", "status": "pass", "detail": "No unresolved template variables"})

    # --- Gitignore ---
    gitignore = target / ".gitignore"
    if gitignore.is_file():
        gi_content = gitignore.read_text()
        gi_lines = set(gi_content.splitlines())
        essential = [".prawduct/.critic-findings.json", ".prawduct/.session-start", ".prawduct/sync-manifest.json"]
        missing_gi = [e for e in essential if e not in gi_lines]
        if missing_gi:
            checks.append({"name": "gitignore", "status": "warn", "detail": f"Missing entries: {', '.join(missing_gi)}"})
        else:
            checks.append({"name": "gitignore", "status": "pass", "detail": "Essential prawduct entries present"})

        # Check for managed files incorrectly gitignored (they should be committed)
        incorrectly_ignored = [rel for rel in MANAGED_FILES if rel in gi_lines]
        if incorrectly_ignored:
            checks.append({
                "name": "gitignore_hygiene",
                "status": "warn",
                "detail": f"Managed files incorrectly gitignored (should be committed): {', '.join(incorrectly_ignored)}",
            })
            recommendations.append("Run sync to fix .gitignore (removes incorrect entries, adds missing ones)")
        else:
            checks.append({"name": "gitignore_hygiene", "status": "pass", "detail": "No managed files incorrectly gitignored"})
    else:
        checks.append({"name": "gitignore", "status": "warn", "detail": ".gitignore does not exist"})

    # --- Session state (are hooks actually firing?) ---
    session_start = prawduct_dir / ".session-start"
    if session_start.is_file():
        try:
            stamp = session_start.read_text().strip()
            checks.append({"name": "session_state", "status": "pass", "detail": f"Last session start: {stamp}"})
        except Exception:  # prawduct:ok-broad-except — validation must not crash
            checks.append({"name": "session_state", "status": "pass", "detail": "Session start file exists"})
    else:
        checks.append({
            "name": "session_state",
            "status": "warn",
            "detail": "No .session-start file — hooks may not have fired yet (normal for first run)",
        })

    # --- Framework currency (are files up to date?) ---
    try:
        manifest_for_fw = load_json(manifest_path) if manifest_path.is_file() else {}
    except json.JSONDecodeError:
        manifest_for_fw = {}
    fw_dir_resolved = _resolve_framework_dir(
        manifest_for_fw,
        framework_dir,
        target,
    )
    if fw_dir_resolved and fw_dir_resolved.is_dir():
        # Classify each managed file:
        # - "stale-clean": current content matches a historical framework render
        #   (sync auto-resolves on next run, no --force needed)
        # - "local-edit": current content matches no known render (sync would skip
        #   without --force; user should review the diff before forcing)
        # - "missing": file expected but not present (sync creates on next run)
        # block_template and always_update strategies are always overwritten on
        # sync, so any drift is auto-resolvable (classified as stale-clean).
        per_file_class: dict[str, str] = {}
        product_name_for_check = "Unknown"
        if manifest_path.is_file():
            try:
                mf = load_json(manifest_path)
                product_name_for_check = mf.get("product_name", "Unknown")
            except json.JSONDecodeError:
                pass
        check_subs = {"{{PRODUCT_NAME}}": product_name_for_check, "{{PRAWDUCT_VERSION}}": PRAWDUCT_VERSION}
        history_cache: dict[tuple[str, str], str] = {}

        for rel_path, config in MANAGED_FILES.items():
            strategy = config.get("strategy", "template")
            dst = target / rel_path
            if not dst.is_file():
                per_file_class[rel_path] = "missing"
                continue

            if strategy == "template":
                template_rel = config.get("template", "")
                template_path = fw_dir_resolved / template_rel
                if not template_path.is_file():
                    continue
                rendered = render_template(template_path, check_subs)
                rendered_hash = hashlib.sha256(rendered.encode()).hexdigest()
                current_hash = compute_hash(dst)
                if current_hash == rendered_hash:
                    continue
                matched = _match_historical_render(
                    fw_dir_resolved, template_rel, current_hash, check_subs, history_cache
                )
                per_file_class[rel_path] = "stale-clean" if matched else "local-edit"
            elif strategy == "block_template":
                template_rel = config.get("template", "")
                template_path = fw_dir_resolved / template_rel
                if not template_path.is_file():
                    continue
                rendered = render_template(template_path, check_subs)
                rendered_block, _, _ = extract_block(rendered)
                if not rendered_block:
                    continue
                product_content = dst.read_text()
                product_block, _, _ = extract_block(product_content)
                if not product_block:
                    continue
                if hashlib.sha256(product_block.encode()).hexdigest() != hashlib.sha256(rendered_block.encode()).hexdigest():
                    # block_template always overwrites in-marker content on sync
                    # (marker contract from v1.3.13). Drift is always auto-resolvable.
                    per_file_class[rel_path] = "stale-clean"
            elif strategy == "always_update":
                source_rel = config.get("source", "")
                source_path = fw_dir_resolved / source_rel
                if source_path.is_file():
                    if source_path.read_bytes() != dst.read_bytes():
                        per_file_class[rel_path] = "stale-clean"
            # merge_settings: skip — hard to compare without side effects

        if not per_file_class:
            checks.append({"name": "framework_currency", "status": "pass", "detail": "All managed files match framework templates"})
        else:
            stale_clean = [r for r, c in per_file_class.items() if c == "stale-clean"]
            local_edit = [r for r, c in per_file_class.items() if c == "local-edit"]
            missing = [r for r, c in per_file_class.items() if c == "missing"]
            parts: list[str] = []
            if stale_clean:
                parts.append(f"{len(stale_clean)} auto-resolve on next sync ({', '.join(stale_clean)})")
            if local_edit:
                parts.append(
                    f"{len(local_edit)} have local edits ({', '.join(local_edit)} — review diff or sync --force)"
                )
            if missing:
                parts.append(f"{len(missing)} missing ({', '.join(missing)} — sync will create)")
            detail = f"{len(per_file_class)} files differ — " + "; ".join(parts)
            checks.append({
                "name": "framework_currency",
                "status": "warn",
                "detail": detail,
            })

            # Action-oriented recommendation
            if local_edit:
                recommendations.append(
                    "Review files with local edits before running sync; for stale-clean files, sync auto-resolves them on next run"
                )
            elif stale_clean or missing:
                recommendations.append("Run prawduct-sync to bring files up to date (no --force needed)")

            # Restart needed only for files that will actually change
            restart_files = [
                f for f, c in per_file_class.items()
                if f in ("CLAUDE.md", ".claude/settings.json") and c in ("stale-clean", "missing")
            ]
            if restart_files:
                needs_restart = True
                recommendations.append(f"Restart Claude Code after sync ({', '.join(restart_files)} will update)")

    # --- Compute overall ---
    overall = "healthy"
    for c in checks:
        if c["status"] == "fail":
            overall = "broken"
            break
        if c["status"] == "warn" and overall == "healthy":
            overall = "degraded"

    return {
        "target": str(target),
        "overall": overall,
        "version": version,
        "checks": checks,
        "needs_restart": needs_restart,
        "recommendations": recommendations,
    }
