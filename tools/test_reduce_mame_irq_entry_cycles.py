#!/usr/bin/env python3
"""Regression for the retained MAME level-6 entry-cost decomposition."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="supermn-mame-irq-entry-") as temp:
        output = Path(temp) / "report.json"
        subprocess.run(
            [
                sys.executable,
                str(ROOT / "tools/reduce_mame_irq_entry_cycles.py"),
                "--output",
                str(output),
            ],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        report = json.loads(output.read_text(encoding="utf-8"))
    assert report["result"] == "green"
    assert report["entry_only_cycles"] == [56, 54, 56, 56]
    assert report["entry_only_two_cycle_units"] == [28, 27, 28, 28]
    assert report["phase_rule"] == {
        "completed_instruction_cycle_mod10": [1, 3, 5, 7, 9],
        "exception_entry_two_cycle_units": [27, 26, 25, 29, 28],
        "first_isr_cycle_mod10": 5,
    }
    rows = report["interruptions"]
    assert [
        row["preceding_instruction"]["completed_cycle_mod10"] for row in rows
    ] == [9, 1, 9, 9]
    assert [row["vpa_model"]["modeled_entry_cycles"] for row in rows] == [
        56,
        54,
        56,
        56,
    ]
    assert all(row["vpa_model"]["first_isr_cycle_mod10"] == 5 for row in rows)
    assert report["vpa_phase_delay_cycles_above_44"] == [12, 10, 12, 12]
    assert all(report["source_checks"].values())
    assert "fixed 33-unit exception-entry charge is false" in report["conclusion"]
    print("MAME level-6 entry-cost decomposition regression: green")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
