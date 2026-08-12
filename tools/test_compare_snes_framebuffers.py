#!/usr/bin/env python3
"""Regression tests for aligned SNES framebuffer comparison."""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools/compare_snes_framebuffers.py"
NEXEN_PROMPT = (
    ROOT
    / "build/validate-fresh-one-credit-prompt-isolated-a976-v1/"
    "screenshots/one-credit-prompt.png"
)
MESEN_PROMPT = (
    ROOT
    / "build/validate-fresh-one-credit-prompt-isolated-a976-mesen211-v1/"
    "screenshots/one-credit-prompt.png"
)


def run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["python3", str(TOOL), *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="snes-framebuffer-test-") as raw:
        temp = Path(raw)
        exact_report = temp / "exact.json"
        exact = run(
            "--reference", str(NEXEN_PROMPT),
            "--candidate", str(MESEN_PROMPT),
            "--output", str(exact_report),
        )
        assert exact.returncode == 0, exact.stderr or exact.stdout
        exact_data = json.loads(exact_report.read_text(encoding="utf-8"))
        assert exact_data["comparison"]["changed_pixels"] == 0
        assert exact_data["comparison"]["result"] == "green"

        altered = Image.open(MESEN_PROMPT).convert("RGB")
        altered.putpixel((32, 64), (255, 0, 255))
        altered_path = temp / "altered.png"
        altered.save(altered_path)
        red_report = temp / "red.json"
        red = run(
            "--reference", str(NEXEN_PROMPT),
            "--candidate", str(altered_path),
            "--output", str(red_report),
        )
        assert red.returncode == 1, red.stderr or red.stdout
        red_data = json.loads(red_report.read_text(encoding="utf-8"))
        assert red_data["comparison"]["changed_pixels"] == 1
        assert red_data["comparison"]["playfield_changed_pixels"] == 1
        assert red_data["comparison"]["result"] == "red"
        assert Path(red_data["artifacts"]["difference_mask"]).is_file()

    print("aligned SNES framebuffer comparison: green")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
