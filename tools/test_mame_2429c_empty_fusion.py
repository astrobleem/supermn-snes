#!/usr/bin/env python3
"""Regression guard for the retained `$02429C` empty-helper MAME span."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="supermn-2429c-fusion-") as temporary:
        output = Path(temporary) / "fusion.json"
        subprocess.run(
            [sys.executable, str(ROOT / "tools/validate_mame_2429c_empty_fusion.py"), "--output", str(output)],
            cwd=ROOT, check=True, capture_output=True, text=True,
        )
        report = json.loads(output.read_text(encoding="utf-8"))
    assert report["result"] == "green" and all(report["checks"].values())
    assert report["original_span"] == {"start_pc": "023342", "end_pc_exclusive": "0242B2", "two_cycle_units": 399}
    assert [(span["cycles"], span["instructions"]) for span in report["spans"]] == [(798, 33)] * 4
    print("MAME $02429C empty-helper fusion timing: green (bounded oracle span)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
