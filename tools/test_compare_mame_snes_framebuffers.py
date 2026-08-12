#!/usr/bin/env python3
"""Pin the established MAME-to-SNES viewport registration."""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools/compare_mame_snes_framebuffers.py"
MAME = (
    ROOT
    / "build/playtest-investigation-20260725/mame-one-credit-oracle-v2/"
    "one-credit-prompt.png"
)
SNES = (
    ROOT
    / "build/validate-fresh-one-credit-prompt-isolated-a976-mesen211-v1/"
    "screenshots/one-credit-prompt.png"
)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="mame-snes-frame-test-") as raw:
        report = Path(raw) / "report.json"
        run = subprocess.run(
            [
                "python3",
                str(TOOL),
                "--mame",
                str(MAME),
                "--snes",
                str(SNES),
                "--output",
                str(report),
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        # The historical prompt is intentionally not pixel-exact; this test
        # pins registration and honest red reporting, not visual acceptance.
        assert run.returncode == 1, run.stderr or run.stdout
        result = json.loads(report.read_text(encoding="utf-8"))
        assert result["registration"]["mame_crop"] == [64, 1, 320, 225]
        assert result["comparison"]["changed_pixels"] == 1729
        assert result["comparison"]["playfield_changed_pixels"] == 1177
        assert result["comparison"]["result"] == "red"

    print("MAME/SNES framebuffer registration: green")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
