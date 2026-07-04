"""W9-A: scaffold a new song from templates.

The `/song-new` skill orchestrates user input; this module does the
filesystem work — parameterized + unit-testable + no I/O surprises.

CLI:
    python -m hallucinote.tools.scaffold_song <slug> --title "..." --tempo 120 \
        --signature 4/4 --sections intro,verse,chorus,bridge,outro \
        [--key Cm] [--intent "your one-paragraph concept"] [--root songs]

Refuses on:
  - invalid slug (must match [a-z0-9_-]+)
  - existing songs/<slug>/ directory (offer --reset to overwrite — caller's call)
  - missing/malformed template directory
  - inconsistent section list (must be ordered, unique names recommended)

Returns 0 on success; non-zero exit code + stderr message on refusal.
Successful scaffold prints the new directory + next-step hint to stdout.

Designed to be invoked from `skills/song-new/SKILL.md` after the
skill has prompted the user for slug/title/tempo/signature/sections.
"""
from __future__ import annotations

import argparse
import re
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from hallucinote.capture import utc_now_eventlike


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
SIGNATURE_RE = re.compile(r"^(\d+)/(\d+)$")


def validate_slug(slug: str) -> None:
    if not SLUG_RE.fullmatch(slug):
        raise ValueError(
            f"invalid slug {slug!r}: must match [a-z0-9][a-z0-9_-]* "
            "(lowercase letters, digits, hyphens, underscores; no leading "
            "hyphen or underscore; no uppercase, no spaces, no dots)"
        )


def parse_signature(signature: str) -> tuple[int, int]:
    m = SIGNATURE_RE.fullmatch(signature.strip())
    if m is None:
        raise ValueError(
            f"invalid signature {signature!r}: expected 'N/D' (e.g. '4/4', '7/8')"
        )
    num, den = int(m.group(1)), int(m.group(2))
    if num <= 0 or den <= 0:
        raise ValueError(
            f"invalid signature {signature!r}: numerator and denominator must be positive"
        )
    return num, den


def parse_sections(sections_csv: str) -> list[str]:
    parts = [s.strip() for s in sections_csv.split(",") if s.strip()]
    if not parts:
        raise ValueError(
            "sections list is empty: pass at least one section "
            "(e.g. --sections intro,verse,chorus,outro)"
        )
    return parts


# ---------------------------------------------------------------------------
# Plan + render
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ScaffoldRequest:
    slug: str
    title: str
    tempo: float
    numerator: int
    denominator: int
    sections: tuple[str, ...]
    key: str | None = None
    intent: str = ""
    section_length_bars: int = 8  # default 8 bars per section


def section_constants(req: ScaffoldRequest) -> str:
    """Render `INTRO_BAR = 1\nVERSE_BAR = 9\n...` for build.py."""
    lines = []
    bar = 1
    for s in req.sections:
        const = _section_const_name(s)
        lines.append(f"{const} = {bar}")
        bar += req.section_length_bars
    lines.append(f"END_BAR = {bar}")
    return "\n".join(lines)


def _section_const_name(section: str) -> str:
    """`intro` → `INTRO_BAR`. Handles slugified section names (e.g. `chorus_twist`)."""
    return re.sub(r"[^a-zA-Z0-9_]", "_", section).upper() + "_BAR"


def section_layout(req: ScaffoldRequest) -> str:
    """Render docstring layout block."""
    lines = []
    bar = 1
    for s in req.sections:
        end = bar + req.section_length_bars
        lines.append(
            f"    {s:<12} bars {bar:>2}-{end - 1:<3}  "
            f"({req.section_length_bars} bars)"
        )
        bar = end
    return "\n".join(lines)


def section_creates(req: ScaffoldRequest) -> str:
    """Render `M.create_section(...)` calls block."""
    lines = []
    for i, s in enumerate(req.sections):
        start_const = _section_const_name(s)
        if i + 1 < len(req.sections):
            end_const = _section_const_name(req.sections[i + 1])
        else:
            end_const = "END_BAR"
        lines.append(
            f"        M.create_section(\n"
            f"            conn, song_id=song_id, name={s!r},\n"
            f"            start_bar=float({start_const}),\n"
            f"            end_bar=float({end_const}),\n"
            f"        )"
        )
    return "\n".join(lines)


def cue_creates(req: ScaffoldRequest) -> str:
    """Render cue-point creates — one per section boundary."""
    if not req.sections:
        return "        # (no sections — no cues)"
    pairs = ", ".join(
        f"({_section_const_name(s)}, {s!r})" for s in req.sections
    )
    return (
        f"        for bar, name in [{pairs}]:\n"
        f"            M.add_cue_point(\n"
        f"                conn, song_id=song_id,\n"
        f"                position_bar=float(bar), name=name,\n"
        f"            )"
    )


def section_table(req: ScaffoldRequest) -> str:
    """Render the song.md section markdown table."""
    lines = [
        "| Section | Bars | Feel |",
        "|---------|------|------|",
    ]
    bar = 1
    for s in req.sections:
        end = bar + req.section_length_bars - 1
        lines.append(f"| `{s}` | {bar}–{end} | _TODO: fill in_ |")
        bar += req.section_length_bars
    return "\n".join(lines)


def slug_to_python(slug: str) -> str:
    """Slugs allow hyphens; Python identifiers don't. `solo-piano` → `solo_piano`."""
    return slug.replace("-", "_")


def render_template(
    template: str, req: ScaffoldRequest,
) -> str:
    """Substitute {{var}} placeholders in `template`.

    Deliberately not jinja: zero deps + the substitutions are simple.
    """
    section_names_literal = (
        "[" + ", ".join(repr(s) for s in req.sections) + "]"
    )
    key_literal = repr(req.key) if req.key else "None"
    key_display = req.key if req.key else "_unset_"
    sub = {
        "slug": req.slug,
        "title": req.title,
        "tempo": str(req.tempo),
        "numerator": str(req.numerator),
        "denominator": str(req.denominator),
        "key_literal": key_literal,
        "key_display": key_display,
        "intent_hint": req.intent or "_TODO: one-paragraph composer intent._",
        "section_constants": section_constants(req),
        "section_layout": section_layout(req),
        "section_creates": section_creates(req),
        "cue_creates": cue_creates(req),
        "section_table": section_table(req),
        "section_names_literal": section_names_literal,
        "slug_python": slug_to_python(req.slug),
        # BAK-7D2V: stamp the synthetic snapshot with its authoring time so a
        # brand-new song gets the exact (refusing) pull-durability guard from
        # day one instead of the legacy warn-only path.
        "captured_at": utc_now_eventlike(),
    }
    out = template
    for k, v in sub.items():
        out = out.replace("{{" + k + "}}", v)
    return out


# ---------------------------------------------------------------------------
# Scaffold
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ScaffoldResult:
    """What the scaffold produced — paths written, total bytes."""
    song_dir: Path
    files_written: tuple[Path, ...]


def template_root() -> Path:
    """Path to hallucinote/tools/templates/song/. Override-friendly for tests."""
    return Path(__file__).resolve().parent / "templates" / "song"


def scaffold_song(
    req: ScaffoldRequest,
    *,
    songs_root: Path = Path("songs"),
    template_dir: Path | None = None,
) -> ScaffoldResult:
    """Scaffold `songs_root/<slug>/` from templates. Returns paths written.

    Raises FileExistsError if `songs_root/<slug>/` exists (caller decides).
    Raises FileNotFoundError if `template_dir` is missing.
    """
    validate_slug(req.slug)
    if template_dir is None:
        template_dir = template_root()
    if not template_dir.is_dir():
        raise FileNotFoundError(
            f"template directory missing: {template_dir} — "
            "is hallucinote/tools/templates/song/ shipped with the package?"
        )
    song_dir = songs_root / req.slug
    if song_dir.exists():
        raise FileExistsError(
            f"songs/{req.slug}/ already exists — refusing to overwrite. "
            "Either pick a different slug, or remove the existing dir first."
        )

    # Plan: walk template_dir, render each .tmpl into the target dir,
    # copy non-template files (.gitkeep) verbatim.
    targets: list[tuple[Path, bytes]] = []
    for src in sorted(template_dir.rglob("*")):
        if src.is_dir():
            continue
        rel = src.relative_to(template_dir)
        if src.name.endswith(".tmpl"):
            content = render_template(src.read_text(), req)
            # Strip .tmpl from output filename, and handle the special
            # test_build.py.tmpl → test_<slug>_build.py rename (Wave 0 I3).
            out_name = src.name[: -len(".tmpl")]
            if out_name == "test_build.py":
                out_name = f"test_{slug_to_python(req.slug)}_build.py"
            elif out_name == "song.md":
                out_name = f"{req.slug}.md"
            target_rel = rel.with_name(out_name)
            targets.append((song_dir / target_rel, content.encode("utf-8")))
        else:
            targets.append((song_dir / rel, src.read_bytes()))

    # Write atomically per-file (no partial dir leakage on filesystem error).
    written: list[Path] = []
    song_dir.mkdir(parents=True, exist_ok=False)
    try:
        for path, data in targets:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            written.append(path)
    except OSError:
        # Roll back: rmtree the partial dir so re-runs aren't poisoned.
        # OSError covers the realistic write failures (FileNotFoundError,
        # PermissionError, OSError on full-disk, etc.); we re-raise.
        shutil.rmtree(song_dir, ignore_errors=True)
        raise

    return ScaffoldResult(song_dir=song_dir, files_written=tuple(written))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Scaffold a new Hallucinote song from templates."
    )
    parser.add_argument("slug", help="filesystem-safe identifier (e.g. 'punk-fate')")
    parser.add_argument("--title", required=True, help="human-facing display name")
    parser.add_argument("--tempo", type=float, required=True, help="BPM")
    parser.add_argument("--signature", required=True, help="time signature (e.g. '4/4')")
    parser.add_argument(
        "--sections", required=True,
        help="comma-separated section names (e.g. 'intro,verse,chorus,outro')",
    )
    parser.add_argument("--key", default=None, help="optional musical key (e.g. 'Dm')")
    parser.add_argument(
        "--intent", default="",
        help="optional one-paragraph composer intent for song.md",
    )
    parser.add_argument(
        "--section-bars", type=int, default=8,
        help="default bars per section (default: 8)",
    )
    parser.add_argument(
        "--root", default="songs", help="root songs directory (default: songs)",
    )

    args = parser.parse_args(argv)

    try:
        validate_slug(args.slug)
        num, den = parse_signature(args.signature)
        sections = parse_sections(args.sections)
    except ValueError as e:
        print(f"scaffold-song: {e}", file=sys.stderr)
        return 2

    req = ScaffoldRequest(
        slug=args.slug,
        title=args.title,
        tempo=float(args.tempo),
        numerator=num,
        denominator=den,
        sections=tuple(sections),
        key=args.key,
        intent=args.intent,
        section_length_bars=args.section_bars,
    )

    try:
        result = scaffold_song(req, songs_root=Path(args.root))
    except FileExistsError as e:
        print(f"scaffold-song: {e}", file=sys.stderr)
        return 3
    except FileNotFoundError as e:
        print(f"scaffold-song: {e}", file=sys.stderr)
        return 4

    print(f"Scaffolded {len(result.files_written)} files at {result.song_dir}/")
    print()
    print("Next steps:")
    print(f"  1. python songs/{args.slug}/build.py --reset    # populate the DB from the synthetic snapshot")
    print(f"  2. pytest songs/{args.slug}/tests/ -v           # confirm shape tests pass")
    print(f"  3. Open songs/{args.slug}/build.py — replace the `=== Compose-half ===` placeholder with your music")
    print(f"  4. /ableton-push {args.slug} <session_id>       # push to a running Live set")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
