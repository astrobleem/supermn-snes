#!/usr/bin/env python3
"""Prove repetition analysis can never grant visual acceptance."""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools/analyze_snes_framebuffer_flashes.py"


def run(frames: Path, output: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "python3",
            str(TOOL),
            "--frames",
            str(frames),
            "--output",
            str(output),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="repetition-diagnostic-test-") as raw:
        temp = Path(raw)
        repeated = temp / "repeated"
        repeated.mkdir()
        Image.new("RGB", (256, 224), (1, 2, 3)).save(repeated / "frame-000000.png")
        red_output = temp / "red.json"
        red = run(repeated, red_output)
        assert red.returncode == 1, red.stderr or red.stdout
        red_report = json.loads(red_output.read_text(encoding="utf-8"))
        assert red_report["diagnostic_result"] == "anomaly-detected"
        assert red_report["acceptance_gate"]["status"] == "unknown"

        varied = temp / "varied"
        varied.mkdir()
        image = Image.new("RGB", (256, 224))
        for y in range(224):
            for x in range(256):
                image.putpixel((x, y), ((x * 3) & 255, (y * 5) & 255, (x + y) & 255))
        image.save(varied / "frame-000000.png")
        clear_output = temp / "clear.json"
        clear = run(varied, clear_output)
        assert clear.returncode == 0, clear.stderr or clear.stdout
        clear_report = json.loads(clear_output.read_text(encoding="utf-8"))
        assert clear_report["diagnostic_result"] == "clear"
        assert clear_report["acceptance_gate"]["status"] == "unknown"
        assert "result" not in clear_report

    print("repetition heuristic remains diagnostic-only: green")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
