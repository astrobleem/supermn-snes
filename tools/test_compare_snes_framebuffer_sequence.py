#!/usr/bin/env python3
"""Regression tests for consecutive aligned SNES framebuffer comparison."""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools/compare_snes_framebuffer_sequence.py"
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


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="snes-frame-sequence-test-") as raw:
        temp = Path(raw)
        altered = Image.open(MESEN_PROMPT).convert("RGB")
        altered.putpixel((40, 80), (255, 0, 255))
        altered_path = temp / "altered.png"
        altered.save(altered_path)
        manifest = temp / "manifest.json"
        manifest.write_text(
            json.dumps(
                {
                    "frames": [
                        {
                            "label": 100,
                            "reference": str(NEXEN_PROMPT),
                            "candidate": str(MESEN_PROMPT),
                        },
                        {
                            "label": 101,
                            "reference": str(NEXEN_PROMPT),
                            "candidate": str(altered_path),
                        },
                        {
                            "label": 102,
                            "reference": str(NEXEN_PROMPT),
                            "candidate": str(altered_path),
                        },
                        {
                            "label": 103,
                            "reference": str(NEXEN_PROMPT),
                            "candidate": str(MESEN_PROMPT),
                        },
                    ]
                }
            ),
            encoding="utf-8",
        )
        output = temp / "report.json"
        run = subprocess.run(
            [
                "python3",
                str(TOOL),
                "--manifest",
                str(manifest),
                "--output",
                str(output),
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        assert run.returncode == 1, run.stderr or run.stdout
        result = json.loads(output.read_text(encoding="utf-8"))
        assert result["frames_compared"] == 4
        assert result["mismatch_frames"] == 2
        assert result["first_divergence"]["label"] == 101
        assert result["mismatch_ranges"] == [
            {
                "start_index": 1,
                "end_index": 2,
                "start_label": 101,
                "end_label": 102,
            }
        ]
        assert len(list((temp / "report-diffs").glob("*.png"))) == 2

    print("aligned SNES framebuffer sequence comparison: green")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
