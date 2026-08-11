#!/usr/bin/env python3
"""Regression-run the unconsumed Stage-3 player VTIME metadata generator."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="supermn-vtime-esc9-") as temp:
        directory = Path(temp)
        manifest = directory / "manifest.json"
        command = [
            sys.executable,
            str(ROOT / "tools" / "gen_vtime_esc9_charge_table.py"),
            "--index", str(directory / "index.bin"),
            "--cost", str(directory / "cost.bin"),
            "--pc", str(directory / "pc.bin"),
            "--terminal", str(directory / "terminal.bin"),
            "--manifest", str(manifest),
        ]
        subprocess.run(command, cwd=ROOT, check=True, capture_output=True, text=True)
        report = json.loads(manifest.read_text(encoding="utf-8"))
        table = report["table"]
        assert table == {
            "blocks": 83,
            "cost_bytes": 83,
            "index_bytes": 17011,
            "pc_bytes": 166,
            "return_pc_base": "BA00",
            "return_pc_limit_inclusive": "FC72",
            "terminal_bytes": 166,
            "terminal_dynamic_branch_or_loop_blocks": 37,
        }
    print("VTIME bank-$9F metadata regression: green")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
