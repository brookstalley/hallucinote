"""F9 — Learnings lifecycle sentinel tracker.

Parses `.prawduct/learnings.md` for optional per-entry metadata, identifies
promotion / retirement / stale candidates, and (with ``apply=True``) moves
sentinel-protected entries to ``learnings-detail.md``'s historical section.

Schema (all fields optional; absence → "active, no lifecycle metadata"):

    ## Entry title
    <!-- prawduct-learning: confirmations=N; created=YYYY-MM-DD; sentinel=path/to/test.py::test_name -->

The HTML comment must be on the line immediately after the ``## Title`` line.
A comment placed deeper in the entry body is ignored — the strict placement
avoids parsing surprises when entries quote example metadata in their prose.

Public surface mirrors the ``run_migrate_*`` runners so JSON-mode callers
see the same dict shape (``product_dir``, ``applied``, plus per-category
lists). The runner does not raise on partial-result conditions — missing
``learnings.md`` is a clean empty result; only structural problems
(``.prawduct/`` absent) surface as ``{"error": "..."}``.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

# Threshold for "stale" entries: confirmations <= 1 AND created >= this many
# days ago. 90d matches the v1.4 plan's F9 section.
_STALE_THRESHOLD_DAYS = 90

# Metadata fields recognized in the per-entry comment. Unknown keys are
# preserved in the entry's metadata dict (so future fields don't break the
# parser) but the audit logic only consults this set.
_KNOWN_METADATA_KEYS = frozenset({"confirmations", "created", "sentinel"})

_METADATA_RE = re.compile(
    r"<!--\s*prawduct-learning:\s*(?P<body>.*?)\s*-->\s*$"
)

_HISTORICAL_SECTION_HEADER = "## Historical (structurally enforced)"
_HISTORICAL_SECTION_BLURB = (
    "Learnings retired by `audit-learnings --apply` after their declared "
    "sentinel test passed — the failure mode the rule warned about is now "
    "structurally enforced by a test. Kept here as historical context.\n"
)


@dataclass
class LearningEntry:
    """A single ``## Title`` block from ``learnings.md``.

    ``body_lines`` is the verbatim slice between the title and the next entry
    (or end of file), excluding the title itself but INCLUDING the metadata
    comment line if present. This lets the serializer round-trip without
    reconstructing comments.
    """

    title: str
    body_lines: list[str]
    metadata: dict[str, str] = field(default_factory=dict)


def parse_learning_metadata(line: str) -> dict[str, str] | None:
    """Parse a single ``<!-- prawduct-learning: ... -->`` comment line.

    Returns the metadata dict on match, ``None`` otherwise. Unknown keys are
    kept (audit logic ignores them); malformed key/value pairs (no ``=``) are
    dropped silently so a stray semicolon in prose can't break parsing.

    Whitespace and trailing semicolons are tolerated. Multiple instances of
    the same key keep the first occurrence (typical of accidental
    duplication during manual editing).
    """
    match = _METADATA_RE.match(line.strip())
    if not match:
        return None

    body = match.group("body")
    result: dict[str, str] = {}
    for raw_pair in body.split(";"):
        pair = raw_pair.strip()
        if not pair or "=" not in pair:
            continue
        key, _, value = pair.partition("=")
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if key not in result:
            result[key] = value
    return result


def parse_learnings_file(content: str) -> list[LearningEntry]:
    """Segment ``learnings.md`` content into entries by ``## `` headers.

    The metadata comment is only honored when it appears on the line
    immediately following the title — a comment in the body is ignored. This
    matters because some entries quote example metadata in their prose
    (this module's own docstring, for instance).

    Lines before the first ``## `` heading (file preamble) are discarded —
    they belong to the file structure, not to any entry. The caller
    reconstructs them in :func:`serialize_learnings`.
    """
    entries: list[LearningEntry] = []
    lines = content.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("## "):
            title = line[3:].strip()
            body_start = i + 1
            # Find next entry boundary (next ## heading or EOF).
            j = body_start
            while j < len(lines) and not lines[j].startswith("## "):
                j += 1
            body_lines = lines[body_start:j]

            metadata: dict[str, str] = {}
            # Metadata must be on the first non-blank line of the body to
            # count. Blank lines between title and comment are tolerated.
            for body_line in body_lines:
                if not body_line.strip():
                    continue
                parsed = parse_learning_metadata(body_line)
                if parsed is not None:
                    metadata = parsed
                break

            entries.append(
                LearningEntry(
                    title=title, body_lines=body_lines, metadata=metadata
                )
            )
            i = j
        else:
            i += 1
    return entries


def _entry_block(entry: LearningEntry) -> str:
    """Serialize a single entry back to its original markdown form."""
    body = "\n".join(entry.body_lines)
    return f"## {entry.title}\n{body}"


def run_sentinel(
    product_dir: Path, sentinel: str, *, timeout: int = 120
) -> tuple[bool, str]:
    """Run ``python3 -m pytest <sentinel> -q`` from ``product_dir``.

    Returns ``(passed, excerpt)``. The excerpt is the trailing portion of
    pytest's combined stdout/stderr (last ~20 lines) so callers can surface
    actionable failure context without dumping the full transcript.

    Subprocess failures (timeout, missing pytest, OS errors) return
    ``(False, "<diagnostic>")`` rather than raising — the audit must keep
    walking through remaining entries even when one sentinel is misconfigured.
    """
    try:
        result = subprocess.run(
            ["python3", "-m", "pytest", sentinel, "-q"],
            cwd=str(product_dir),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return False, f"sentinel timed out after {timeout}s"
    except (OSError, FileNotFoundError) as exc:
        return False, f"could not invoke pytest: {exc}"

    combined = (result.stdout or "") + (result.stderr or "")
    tail = "\n".join(combined.splitlines()[-20:])
    return result.returncode == 0, tail


def _parse_iso_date(value: str) -> date | None:
    """Parse ``YYYY-MM-DD``. Returns ``None`` on malformed input."""
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def _coerce_int(value: str) -> int | None:
    try:
        return int(value.strip())
    except (ValueError, TypeError):
        return None


def audit_learnings(
    product_dir: Path,
    *,
    apply: bool = False,
    today: date | None = None,
    run_sentinels: bool = True,
) -> dict:
    """Classify entries in ``learnings.md`` by lifecycle stage.

    Returns a dict with five lists plus the run mode:

      * ``promotions`` — entries with ``confirmations >= 2``. Advisory only;
        no file mutation regardless of ``apply``. Promotion in this design
        means "surface the confirmation count" — `learnings.md` doesn't have
        a sectioned active/promoted split.
      * ``retirements`` — entries with a passing sentinel. Each carries the
        sentinel string, the pass/fail bit, and the output excerpt. With
        ``apply=True`` *and* a passing sentinel, the entry is moved to
        ``learnings-detail.md`` under the historical section.
      * ``stale_flags`` — entries with ``created`` more than 90 days ago and
        ``confirmations <= 1``. The ``created`` field is required for
        staleness detection — entries that lack it never appear here.
      * ``errors`` — entries whose declared sentinel exists but failed, plus
        entries with unparseable date fields. The audit keeps going; the
        per-entry error string tells the user what to fix.
      * ``applied`` — bool mirror of the ``apply`` argument; surfaces in the
        result so JSON-mode callers know whether mutations happened.

    ``today`` and ``run_sentinels`` are test seams. ``today=None`` uses the
    real wall clock; ``run_sentinels=False`` short-circuits the subprocess
    call (entries with sentinels just appear in ``retirements`` with
    ``passed=None`` and don't trigger errors). Both default to production
    behavior.
    """
    if today is None:
        today = date.today()

    promotions: list[dict] = []
    retirements: list[dict] = []
    stale_flags: list[dict] = []
    errors: list[dict] = []

    learnings_path = product_dir / ".prawduct" / "learnings.md"
    if not learnings_path.is_file():
        return {
            "product_dir": str(product_dir),
            "applied": apply,
            "promotions": promotions,
            "retirements": retirements,
            "stale_flags": stale_flags,
            "errors": errors,
        }

    content = learnings_path.read_text()
    entries = parse_learnings_file(content)

    retained_entries: list[LearningEntry] = []
    retired_entries: list[LearningEntry] = []

    for entry in entries:
        meta = entry.metadata
        if not meta:
            retained_entries.append(entry)
            continue

        # Promotions: confirmations >= 2. Advisory only — surface but never
        # rewrite the file.
        confirmations_raw = meta.get("confirmations")
        confirmations: int | None = None
        if confirmations_raw is not None:
            confirmations = _coerce_int(confirmations_raw)
            if confirmations is None:
                errors.append({
                    "title": entry.title,
                    "error": (
                        f"could not parse confirmations='{confirmations_raw}' "
                        "as integer"
                    ),
                })
            elif confirmations >= 2:
                promotions.append({
                    "title": entry.title,
                    "confirmations": confirmations,
                })

        # Sentinel handling: an entry with a declared sentinel is a
        # retirement candidate. Whether the sentinel currently passes
        # determines whether `apply=True` actually moves the entry.
        sentinel = meta.get("sentinel")
        sentinel_passed: bool | None = None
        sentinel_excerpt = ""
        if sentinel:
            if run_sentinels:
                sentinel_passed, sentinel_excerpt = run_sentinel(
                    product_dir, sentinel
                )
            retirement_record = {
                "title": entry.title,
                "sentinel": sentinel,
                "passed": sentinel_passed,
                "output_excerpt": sentinel_excerpt,
                "applied": False,
            }
            if sentinel_passed is False:
                # Failing sentinel: surfaced as both a retirement attempt
                # (record on disk) AND an error (so users see "fix me"
                # without needing to inspect every retirement entry).
                errors.append({
                    "title": entry.title,
                    "error": (
                        f"sentinel '{sentinel}' is failing — fix the test "
                        "or update the learning before retiring"
                    ),
                })
                retirements.append(retirement_record)
                retained_entries.append(entry)
            elif sentinel_passed is True:
                if apply:
                    retirement_record["applied"] = True
                    retired_entries.append(entry)
                else:
                    retained_entries.append(entry)
                retirements.append(retirement_record)
            else:
                # run_sentinels=False — record as candidate without
                # actually trying to retire.
                retirements.append(retirement_record)
                retained_entries.append(entry)
        else:
            retained_entries.append(entry)

        # Staleness: created > 90d ago AND confirmations <= 1. The ``created``
        # field is required — entries without it never show up here. (Stale
        # check is independent of sentinel; a sentineled stale entry surfaces
        # in both lists, which is the right read for the user.)
        created_raw = meta.get("created")
        if created_raw:
            created = _parse_iso_date(created_raw)
            if created is None:
                errors.append({
                    "title": entry.title,
                    "error": (
                        f"could not parse created='{created_raw}' "
                        "as YYYY-MM-DD"
                    ),
                })
            else:
                age_days = (today - created).days
                effective_confirmations = (
                    confirmations if confirmations is not None else 0
                )
                if (
                    age_days >= _STALE_THRESHOLD_DAYS
                    and effective_confirmations <= 1
                ):
                    stale_flags.append({
                        "title": entry.title,
                        "created": created_raw,
                        "age_days": age_days,
                        "confirmations": effective_confirmations,
                    })

    if apply and retired_entries:
        _apply_retirements(learnings_path, retained_entries, retired_entries, content)

    return {
        "product_dir": str(product_dir),
        "applied": apply,
        "promotions": promotions,
        "retirements": retirements,
        "stale_flags": stale_flags,
        "errors": errors,
    }


def _apply_retirements(
    learnings_path: Path,
    retained_entries: list[LearningEntry],
    retired_entries: list[LearningEntry],
    original_content: str,
) -> None:
    """Rewrite ``learnings.md`` with retired entries removed, and append
    those entries to ``learnings-detail.md`` under the historical section.

    The preamble of ``learnings.md`` (everything before the first ``## ``
    heading) is preserved verbatim. The detail file is created with a
    minimal header if absent; the historical section is created if absent.
    """
    # Rebuild learnings.md preserving the preamble.
    lines = original_content.split("\n")
    preamble_end = len(lines)
    for idx, line in enumerate(lines):
        if line.startswith("## "):
            preamble_end = idx
            break

    preamble = "\n".join(lines[:preamble_end]).rstrip("\n")
    rebuilt_parts: list[str] = []
    if preamble:
        rebuilt_parts.append(preamble + "\n")
    for entry in retained_entries:
        rebuilt_parts.append(_entry_block(entry).rstrip("\n") + "\n")
    new_content = "\n".join(rebuilt_parts).rstrip("\n") + "\n"
    learnings_path.write_text(new_content)

    # Append to learnings-detail.md.
    detail_path = learnings_path.parent / "learnings-detail.md"
    if detail_path.is_file():
        detail_content = detail_path.read_text()
    else:
        detail_content = (
            "# Learnings — Full Detail\n\n"
            "Historical record of learnings with their full context. "
            "See `learnings.md` for the active rule list.\n"
        )

    if _HISTORICAL_SECTION_HEADER not in detail_content:
        if not detail_content.endswith("\n"):
            detail_content += "\n"
        detail_content += (
            "\n" + _HISTORICAL_SECTION_HEADER + "\n\n"
            + _HISTORICAL_SECTION_BLURB
        )

    appended_blocks = "\n".join(
        _entry_block(entry).rstrip("\n") + "\n" for entry in retired_entries
    )
    if not detail_content.endswith("\n"):
        detail_content += "\n"
    detail_content += "\n" + appended_blocks
    detail_path.write_text(detail_content)


def run_audit_learnings(product_dir: str, *, apply: bool = False) -> dict:
    """User-facing runner for ``prawduct-setup audit-learnings``.

    Matches the ``run_migrate_*`` shape so the CLI dispatch and JSON-mode
    callers see a consistent contract:

        {
          "product_dir": "/abs/path",
          "applied": bool,
          "promotions": [...],
          "retirements": [...],
          "stale_flags": [...],
          "errors": [...],
        }

    Returns ``{"error": "..."}`` only for structural problems (no
    ``.prawduct/`` directory) — a missing ``learnings.md`` is a clean empty
    result, not an error. Sentinel subprocess failures are absorbed into
    per-entry ``errors`` entries; the runner itself does not raise.
    """
    product_path = Path(product_dir).resolve()
    prawduct_dir = product_path / ".prawduct"
    if not prawduct_dir.is_dir():
        return {
            "error": (
                f"Not a prawduct product: {product_path} has no .prawduct/ "
                "directory"
            )
        }

    return audit_learnings(product_path, apply=apply)
