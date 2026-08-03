"""Audio-capture take retention — the rolling window over ``captures/``.

A **take** is one render's output directory, ``songs/<slug>/captures/<utc-ts>/``:
N+R+1 WAVs plus ``manifest.json``. At 48 kHz / stereo / 32-bit float a take costs
~23 MB per surface-minute, so a 24-surface five-minute song is ~2.8 GB — and
renders accumulate. This module is the rolling window that bounds them.

**Why deleting an old take is safe.** Captures are write-once, read-once: the
render writes them, ``ableton_analysis`` reads them once and emits a
self-contained MixReport to ``songs/<slug>/analysis/<ts>.json``. Baseline
comparison resolves against those JSONs (``audio.compare.resolve_baseline`` keys
on ``db_seq``) and never re-opens a WAV. The MixReport trail IS the audit log of
mix evolution and is never swept — only the raw audio is, and only after the
window has moved past it. What a sweep costs is the ability to re-analyze that
specific take with different parameters; the durable measurement survives.

**Plan then execute**, mirroring the sync layer's discipline: :func:`plan_sweep`
resolves and classifies EVERY take while writing nothing, and
:func:`execute_sweep` removes what the plan named. A caller can therefore show
the user exactly what would go (``--dry-run``) with no risk of a half-applied
sweep, and a mid-run failure can't leave classification and deletion disagreeing.

**Two things are never swept.** A take carrying :data:`PIN_FILENAME` is pinned by
the operator and outlives the window entirely (it also does NOT consume a keep
slot — pinning a reference take must not silently evict a working one). A take
whose ``status.json`` still reads ``state="running"`` is mid-render and is left
alone. Everything outside ``captures/`` is out of reach by construction: a sweep
is always scoped to one captures root and only ever removes its immediate
subdirectories, so a song's durable files (``captured_session.json``,
``build.py``, ``analysis/``) can never be a target.
"""
from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

# Written by the render handler into each take dir; also the completion
# heartbeat. ``state`` is "running" mid-render and "done"/"error" at the end.
STATUS_FILENAME = "status.json"

# Every complete take carries one. A subdirectory of a captures root WITHOUT a
# manifest is not a take (a stray dir, or a render that died before writing it)
# and is never swept — this module removes renders, not whatever else a user
# parked in the directory.
MANIFEST_FILENAME = "manifest.json"

# Operator pin marker. Contents are ignored; presence is the signal.
PIN_FILENAME = ".pinned"

ENV_KEEP = "HALLUCINOTE_CAPTURE_KEEP"
ENV_SWEEP = "HALLUCINOTE_CAPTURE_SWEEP"

# How many takes survive a sweep by default. Two, because the only reason to
# hold raw audio after analysis is a by-ear A/B against the previous mix pass —
# that needs the current take and the one before it, and nothing more.
DEFAULT_KEEP = 2


@dataclass(frozen=True)
class Take:
    """One render's output directory, with the facts a sweep decides on."""

    path: Path
    # The manifest's recorded capture time; "" when unreadable or absent.
    captured_at: str
    # Manifest mtime — the recency tiebreaker when captured_at is missing.
    mtime: float
    size_bytes: int
    pinned: bool
    # status.json still reads state="running": a render is writing here.
    in_flight: bool


@dataclass(frozen=True)
class SweepPlan:
    """What a sweep WOULD do. Produced without writing anything."""

    captures_root: Path
    keep: int
    # Survivors, newest first: the keep-window plus every pinned take.
    kept: tuple[Take, ...]
    # Takes this sweep would remove, newest first.
    sweep: tuple[Take, ...]

    @property
    def reclaimable_bytes(self) -> int:
        return sum(t.size_bytes for t in self.sweep)


@dataclass(frozen=True)
class SweepResult:
    """What a sweep actually did."""

    removed: tuple[Path, ...]
    freed_bytes: int
    # (take path, error message) for takes that could not be removed. Collected
    # rather than raised so one locked directory can't abandon the rest.
    failures: tuple[tuple[Path, str], ...]


def recency_key(take_dir: Path) -> tuple[str, float, str]:
    """Recency sort key for a take directory, robust to non-ISO dir names.

    Renders name their dirs ISO-8601 (``20260527T200614Z``), but a dir may also
    be hand-named for a focused capture (e.g. ``v4-seam-verse2-chorus2``), and
    keying on the NAME lets such a dir shadow the newest render — ``'v'`` (0x76)
    sorts above every ``2026…`` timestamp (0x32). So key on the manifest's
    recorded ``captured_at``: the true capture time, naming-independent, and
    itself ISO-8601 so it still sorts chronologically. Fall back to the manifest
    mtime, then the dir name, when ``captured_at`` is absent (an old or partial
    manifest).

    This is the single definition of "newest take" in the tree — the analysis
    handler's captures selector reads it from here too. The two MUST agree: a
    sweep that ordered takes differently from the selector could remove the very
    take the next analysis would have chosen.
    """
    manifest = take_dir / MANIFEST_FILENAME
    captured_at = ""
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
        captured_at = str(data.get("captured_at") or "")
    except (OSError, ValueError):
        pass
    try:
        mtime = manifest.stat().st_mtime
    except OSError:
        mtime = 0.0
    return (captured_at, mtime, take_dir.name)


def keep_from_env(default: int = DEFAULT_KEEP) -> int:
    """Retention window from :data:`ENV_KEEP`, falling back to ``default``.

    A malformed or negative value falls back rather than raising: this is read
    on the render path, where a typo'd env var must not break a capture. It
    cannot silently delete MORE than intended — the fallback is the default
    window, never zero.
    """
    raw = os.environ.get(ENV_KEEP)
    if raw is None:
        return default
    try:
        value = int(raw.strip())
    except ValueError:
        return default
    return value if value >= 0 else default


def sweep_enabled() -> bool:
    """False when :data:`ENV_SWEEP` is set to a falsey value — the operator
    opt-out from automatic retention. Any other value (including unset) leaves
    the sweep on, so the disk bound is the default rather than something you
    have to remember to switch on."""
    raw = os.environ.get(ENV_SWEEP)
    if raw is None:
        return True
    return raw.strip().lower() not in {"0", "false", "no", "off", ""}


def _dir_size_bytes(path: Path) -> int:
    total = 0
    for entry in path.rglob("*"):
        try:
            if entry.is_file():
                total += entry.stat().st_size
        except OSError:
            continue  # vanished or unreadable mid-walk; it contributes nothing
    return total


def _is_in_flight(take_dir: Path) -> bool:
    """True when ``status.json`` still reads ``state="running"``.

    A terminal state ("done"/"error") and an absent status file both mean the
    render is over — pre-heartbeat takes have no status.json at all, and they
    must stay sweepable.
    """
    try:
        data = json.loads((take_dir / STATUS_FILENAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return str(data.get("state") or "") == "running"


def list_takes(captures_root: Path | str) -> list[Take]:
    """Every take under ``captures_root``, newest first.

    A subdirectory without a :data:`MANIFEST_FILENAME` is not a take and is
    omitted — so it can never be swept. Returns ``[]`` for a missing or empty
    root rather than raising; "nothing to retain" is not an error.
    """
    root = Path(captures_root)
    if not root.is_dir():
        return []
    takes: list[Take] = []
    for entry in sorted(root.iterdir()):
        if not entry.is_dir() or not (entry / MANIFEST_FILENAME).exists():
            continue
        captured_at, mtime, _ = recency_key(entry)
        takes.append(
            Take(
                path=entry,
                captured_at=captured_at,
                mtime=mtime,
                size_bytes=_dir_size_bytes(entry),
                pinned=(entry / PIN_FILENAME).exists(),
                in_flight=_is_in_flight(entry),
            )
        )
    # Sort on the fields already read above rather than re-reading each
    # manifest: one read per take, and the ordering provably matches the
    # `captured_at` / `mtime` a caller sees on the Take.
    takes.sort(key=lambda t: (t.captured_at, t.mtime, t.path.name), reverse=True)
    return takes


def plan_sweep(
    captures_root: Path | str,
    *,
    keep: int,
    protect: tuple[Path, ...] | list[Path] = (),
    force: bool = False,
) -> SweepPlan:
    """Classify every take into kept vs swept. Writes nothing.

    ``keep`` is how many UNPINNED takes survive, newest first. Pinned takes
    always survive and are excluded from the count, so pinning a reference take
    never costs you a working one. ``protect`` names directories to keep
    regardless — the render path passes the dir it is about to write, so a sweep
    can never target the capture in progress. ``force`` overrides the in-flight
    guard, for an operator clearing a take whose render died leaving a stale
    ``state="running"`` marker behind.

    Raises ``ValueError`` for a negative ``keep`` — a caller asking to keep -1
    takes has a bug, and guessing on a destructive operation is worse than
    refusing.
    """
    if keep < 0:
        raise ValueError(f"keep must be >= 0, got {keep}")
    root = Path(captures_root)
    protected = {Path(p).resolve() for p in protect}

    kept: list[Take] = []
    sweep: list[Take] = []
    budget = keep
    for take in list_takes(root):
        if take.pinned:
            kept.append(take)
            continue
        if take.path.resolve() in protected:
            kept.append(take)
            continue
        if take.in_flight and not force:
            kept.append(take)
            continue
        if budget > 0:
            budget -= 1
            kept.append(take)
            continue
        sweep.append(take)

    return SweepPlan(
        captures_root=root,
        keep=keep,
        kept=tuple(kept),
        sweep=tuple(sweep),
    )


def execute_sweep(plan: SweepPlan) -> SweepResult:
    """Remove every take the plan named. Per-take failures are collected.

    A directory that can't be removed (permissions, an open file handle, a
    vanished path) records its error and the sweep continues — one stuck take
    must not strand the rest of the reclaimable space. The caller decides
    whether a non-empty ``failures`` is worth surfacing.
    """
    removed: list[Path] = []
    freed = 0
    failures: list[tuple[Path, str]] = []
    for take in plan.sweep:
        try:
            shutil.rmtree(take.path)
        except OSError as exc:
            failures.append((take.path, str(exc)))
            continue
        removed.append(take.path)
        freed += take.size_bytes
    return SweepResult(
        removed=tuple(removed),
        freed_bytes=freed,
        failures=tuple(failures),
    )


def format_bytes(n: int) -> str:
    """Human-readable size for CLI and log output."""
    step = 1024.0
    size = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if size < step or unit == "GB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= step
    return f"{size:.1f} GB"  # pragma: no cover - loop always returns at GB


__all__ = [
    "DEFAULT_KEEP",
    "ENV_KEEP",
    "ENV_SWEEP",
    "MANIFEST_FILENAME",
    "PIN_FILENAME",
    "STATUS_FILENAME",
    "SweepPlan",
    "SweepResult",
    "Take",
    "execute_sweep",
    "format_bytes",
    "keep_from_env",
    "list_takes",
    "plan_sweep",
    "recency_key",
    "sweep_enabled",
]
