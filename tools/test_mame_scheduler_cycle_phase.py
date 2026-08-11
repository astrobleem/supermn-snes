#!/usr/bin/env python3
"""Regression for the qualified MAME scheduler-cycle evidence report."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="supermn-scheduler-cycle-phase-") as temporary:
        output = Path(temporary) / "report.json"
        subprocess.run(
            [
                sys.executable,
                str(ROOT / "tools" / "validate_mame_scheduler_cycle_phase.py"),
                "--output",
                str(output),
            ],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        report = json.loads(output.read_text(encoding="utf-8"))
    assert report["result"] == "green", report
    assert report["promotion_blocked"] is True, report
    assert report["raw_program_read_probe"]["boundaries"] == [14743, 14744, 14745, 14746, 14747], report
    assert report["instruction_only_irq_trace"]["periods"] == [139300, 139302, 139296, 139342], report
    assert [row["interrupted_pc"] for row in report["instruction_only_irq_trace"]["interruptions"]] == [
        "000818", "000818", "0259B0", "02582E", "000810"
    ], report
    assert "data reads" in report["raw_program_read_probe"]["qualification"], report
    assert "common virtual MC68000 clock" in report["not_proven"], report
    print("MAME scheduler-cycle evidence regression: green (read-tap qualification retained)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
