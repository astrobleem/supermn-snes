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


def main() -> int:
    failures: list[str] = []
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
        print("Documentation link check failed:", file=sys.stderr)
        for failure in failures:
            print(f"  {failure}", file=sys.stderr)
        return 1

    print(f"Documentation links OK: {checked} relative links across {len(files)} Markdown files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
