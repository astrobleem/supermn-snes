#!/usr/bin/env python3
"""Regression-run the consumed `$02429C` VTIME metadata generator."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="supermn-vtime-esc5-") as temporary:
        directory = Path(temporary)
        manifest = directory / "manifest.json"
        command = [
            sys.executable, str(ROOT / "tools/gen_vtime_esc5_charge_table.py"),
            "--cost", str(directory / "cost.bin"),
            "--pc", str(directory / "pc.bin"),
            "--terminal", str(directory / "terminal.bin"),
            "--manifest", str(manifest),
        ]
        subprocess.run(command, cwd=ROOT, check=True, capture_output=True, text=True)
        report = json.loads(manifest.read_text(encoding="utf-8"))
    assert report["table"] == {
        "blocks": 35,
        "cost_bytes": 35,
        "pc_bytes": 70,
        "terminal_bytes": 70,
        "dynamic_terminal_ordinals": [1, 7, 11, 12, 13, 16, 18, 21, 25, 26, 28, 29, 32, 34],
    }
    print("VTIME $02429C ordinal metadata regression: green (consumed by VTIME-only root)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
