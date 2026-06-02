"""
prawduct lib — extracted modules from prawduct-setup.py.

Re-exports all public names for backward compatibility. Consumers that
import via importlib (tests, shim scripts) see the same namespace as before.
"""

# Core utilities and constants
from .core import (  # noqa: F401
    BLOCK_BEGIN,
    BLOCK_END,
    BUILD_PLAN_POINTER_KEY,
    DEFAULT_BUILD_PLAN_REL,
    FILE_RENAMES,
    FRAMEWORK_DIR,
    GITIGNORE_ENTRIES,
    MANAGED_FILES,
    PRAWDUCT_VERSION,
    SKILL_PLACEMENTS,
    TEMPLATES_DIR,
    resolve_build_plan_path,
    read_str_yaml_key,
    V1_GITIGNORE_ENTRIES,
    V1_SESSION_FILES,
    V3_GITIGNORE_ENTRIES,
    V4_GITIGNORE_ENTRIES,
    _resolve_framework_dir,
    _try_pull_framework,
    compute_block_hash,
    compute_hash,
    copy_hook,
    create_manifest,
    detect_version,
    ensure_dir,
    extract_block,
    infer_product_name,
    load_json,
    log,
    merge_settings,
    render_template,
    replace_settings,
    untrack_gitignored_files,
    update_gitignore,
    write_template,
    write_template_overwrite,
)

# Init command
from .init_cmd import run_init  # noqa: F401

# Migration operations
from .migrate_cmd import (  # noqa: F401
    add_block_markers,
    archive_v1_dirs,
    clean_gitignore,
    clean_v1_session_files,
    delete_v1_files,
    enable_v1_4_coverage,
    enable_v1_4_operator_verification,
    enable_v1_4_settings_layout,
    enable_v1_4_views,
    generate_sync_manifest,
    migrate_backlog,
    migrate_change_log,
    migrate_project_state_v5,
    run_migrate,
    run_migrate_coverage,
    run_migrate_operator_verification,
    run_migrate_settings_layout,
    split_learnings_v5,
    upgrade_manifest_strategy,
)

# Post-sync advisory infrastructure (v1.6.0 Phase 1 — store + registry + diff)
from .advisory_store import (  # noqa: F401
    AdvisoryCandidate,
    Codebase,
    ProjectState,
    clear_registry,
    compute_id,
    dismiss,
    load_project_state,
    make_codebase,
    read_store,
    reconcile,
    register_probe,
    resolve,
    run_all_probes,
    run_sync_advisories,
    undismiss,
    write_store,
)

# Post-sync advisory management CLI (v1.6.0 Chunk 05 — /prawduct-advisory)
from .advisory_cmd import (  # noqa: F401
    dismiss_advisory,
    list_advisories,
    resolve_advisory,
    show_advisory,
    undismiss_advisory,
)

# Sync operations
from .sync_cmd import (  # noqa: F401
    _HISTORICAL_RENDER_DEPTH_CAP,
    _bootstrap_manifest,
    _match_historical_render,
    apply_renames,
    migrate_v4_to_v5,
    run_sync,
)

# Validate command
from .validate_cmd import run_validate  # noqa: F401

# Views command (doctor `views` subcommand)
from .views_cmd import run_views_command  # noqa: F401

# Audit-learnings command (F9 — learnings lifecycle sentinel tracker)
from .audit_learnings_cmd import (  # noqa: F401
    LearningEntry,
    audit_learnings,
    parse_learning_metadata,
    parse_learnings_file,
    run_audit_learnings,
    run_sentinel,
)

# Critic mode inference (v1.5 Chunk 03 — no-arg /critic picks mode from state)
from .critic_mode import infer_mode  # noqa: F401

# Operator-verification queue (F10 — pre-merge human-verification gate)
from .operator_verification import (  # noqa: F401
    VerificationEntry,
    count_pending,
    format_operator_verification,
    is_operator_verification_required,
    mark_accepted,
    mark_verified,
    parse_operator_verification,
    pending_entries,
    run_accept_pending,
    run_check_operator_verification,
    run_verify_entry,
)
