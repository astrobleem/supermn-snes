#!/usr/bin/env python3
"""Fail when a repository-local Markdown link has no target.

The checker intentionally leaves HTTP and absolute links alone.  It validates file
targets and Markdown heading fragments for relative inline links and reference
definitions.  Build/private directories are excluded so generated evidence does not
become part of the documentation contract.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote


ROOT = Path(__file__).resolve().parents[1]
INLINE_RE = re.compile(r"!?\[[^\]\n]*\]\(([^)\n]+)\)")
REFERENCE_RE = re.compile(r"^\s*\[[^\]\n]+\]:\s*(<[^>\n]+>|\S+)", re.MULTILINE)
HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$", re.MULTILINE)
EXPLICIT_ANCHOR_RE = re.compile(r"""<(?:a\s+(?:name|id)|[^>]+\sid)=["']([^"']+)["']""", re.I)
SCHEME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")
ACTIVE_ROM_SHA256 = "7506f496669050cf188dd767810717a1c35944cd5115b667fe216f33bfe6447c"
ACTIVE_ROM_SHORT = ACTIVE_ROM_SHA256[:8]
PINNED_POPPY_SHA256 = "715b14431478b62433498cc516c1cbbb8f418c1d7b39a8e71098ed98d9c9167e"


def markdown_files() -> list[Path]:
    result = subprocess.run(
        [
            "rg",
            "--files",
            "--hidden",
            "-g",
            "*.md",
            "-g",
            "!.git/**",
            "-g",
            "!build/**",
            "-g",
            "!.claude/worktrees/**",
        ],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode not in (0, 1):
        raise RuntimeError(result.stderr.strip() or "rg failed while listing Markdown files")
    return sorted(ROOT / line for line in result.stdout.splitlines() if line)


def destination(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("<"):
        end = raw.find(">")
        return raw[1:end] if end >= 0 else raw[1:]
    return raw.split(maxsplit=1)[0] if raw else ""


def github_slug(heading: str) -> str:
    heading = re.sub(r"<[^>]+>", "", heading)
    heading = re.sub(r"[*_~`]", "", heading)
    heading = heading.strip().lower()
    heading = re.sub(r"[^\w\-\s]", "", heading, flags=re.UNICODE)
    return re.sub(r"\s+", "-", heading)


def anchors(path: Path) -> set[str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    found = {unquote(value).lower() for value in EXPLICIT_ANCHOR_RE.findall(text)}
    occurrences: dict[str, int] = {}
    for heading in HEADING_RE.findall(text):
        base = github_slug(heading)
        if not base:
            continue
        count = occurrences.get(base, 0)
        occurrences[base] = count + 1
        found.add(base if count == 0 else f"{base}-{count}")
    return found


def line_number(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def current_truth_failures() -> list[str]:
    """Keep the short authoritative layer from regressing into the history ledger."""

    failures: list[str] = []
    status = (ROOT / "docs/current/STATUS.md").read_text(encoding="utf-8")
    status_current, separator, _history = status.partition("## Superseded evidence ledger")
    if not separator:
        failures.append("docs/current/STATUS.md: missing superseded-evidence authority boundary")
    if ACTIVE_ROM_SHA256 not in status_current:
        failures.append("docs/current/STATUS.md: current verdict lacks the pinned active ROM hash")
    if PINNED_POPPY_SHA256 not in status_current:
        failures.append("docs/current/STATUS.md: current verdict lacks the pinned Poppy DLL hash")

    blockers = (ROOT / "docs/current/RELEASE_BLOCKERS.md").read_text(encoding="utf-8")
    blockers_current = blockers.partition("The August 15 exact-hash gate")[0]
    building = (ROOT / "docs/current/BUILDING.md").read_text(encoding="utf-8")
    validation = (ROOT / "docs/current/VALIDATION.md").read_text(encoding="utf-8")
    renderer = (ROOT / "docs/current/RENDERER_CONSOLIDATION.md").read_text(encoding="utf-8")
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    debugging = (ROOT / "docs/toolchain/DEBUGGING.md").read_text(encoding="utf-8")
    build_script = (ROOT / "tools/build_interp.sh").read_text(encoding="utf-8")

    for name, text in (
        ("docs/current/RELEASE_BLOCKERS.md", blockers_current),
        ("docs/current/BUILDING.md", building),
        ("docs/current/VALIDATION.md", validation),
        ("docs/current/RENDERER_CONSOLIDATION.md", renderer),
    ):
        if ACTIVE_ROM_SHORT not in text:
            failures.append(
                f"{name}: does not identify {ACTIVE_ROM_SHORT} as current"
            )

    for name, text in (
        ("AGENTS.md", agents),
        ("docs/current/BUILDING.md", building),
        ("docs/toolchain/DEBUGGING.md", debugging),
        ("tools/build_interp.sh", build_script),
    ):
        if PINNED_POPPY_SHA256 not in text:
            failures.append(f"{name}: pinned Poppy SHA-256 is missing or stale")

    if "poppy-astrobleem-latest" not in build_script:
        failures.append("tools/build_interp.sh: corrected Poppy fork is not the default")
    if "ALLOW_UNPINNED_POPPY" not in build_script:
        failures.append("tools/build_interp.sh: missing explicit unpinned-compiler override gate")
    if "poppy/issues/391" not in status_current or "poppy/issues/391" not in debugging:
        failures.append("current Poppy #391 scope is not linked from status and debugging")

    forbidden = (
        "no successor ROM has been built",
        "successor evidence is pending",
        "defaulting to the historical `/home/chad/poppy`",
        "Current `c14c0184",
        "Current `d01db972",
    )
    authoritative = "\n".join((status_current, blockers_current, building, validation))
    for phrase in forbidden:
        if phrase in authoritative:
            failures.append(f"current documentation retains contradictory phrase: {phrase!r}")
    return failures


def main() -> int:
    failures = current_truth_failures()
    checked = 0
    files = markdown_files()
    anchor_cache: dict[Path, set[str]] = {}

    for source in files:
        text = source.read_text(encoding="utf-8", errors="replace")
        matches = list(INLINE_RE.finditer(text)) + list(REFERENCE_RE.finditer(text))
        for match in matches:
            raw = destination(match.group(1))
            if not raw or raw.startswith("#"):
                target_part, fragment = "", raw[1:] if raw.startswith("#") else ""
            else:
                if SCHEME_RE.match(raw) or raw.startswith("//") or raw.startswith("/"):
                    continue
                target_part, separator, fragment = raw.partition("#")
                if not separator:
                    fragment = ""

            target = source if not target_part else (source.parent / unquote(target_part)).resolve()
            checked += 1
            display_source = source.relative_to(ROOT)
            lineno = line_number(text, match.start())

            try:
                target.relative_to(ROOT)
            except ValueError:
                failures.append(
                    f"{display_source}:{lineno}: link escapes repository: {raw}"
                )
                continue

            if not target.exists():
                failures.append(f"{display_source}:{lineno}: missing target: {raw}")
                continue

            if fragment and target.is_file() and target.suffix.lower() == ".md":
                wanted = unquote(fragment).lower()
                target_anchors = anchor_cache.setdefault(target, anchors(target))
                if wanted not in target_anchors:
                    failures.append(
                        f"{display_source}:{lineno}: missing anchor #{fragment} in "
                        f"{target.relative_to(ROOT)}"
                    )

    if failures:
        print("Documentation consistency check failed:", file=sys.stderr)
        for failure in failures:
            print(f"  {failure}", file=sys.stderr)
        return 1

    print(f"Documentation links OK: {checked} relative links across {len(files)} Markdown files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
