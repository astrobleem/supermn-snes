#!/usr/bin/env python3
"""Regression for the qualified current Stage-3 hotspot-region reduction."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="supermn-stage3-hot-regions-") as temporary:
        output = Path(temporary) / "report.json"
        subprocess.run(
            [
                sys.executable,
                str(ROOT / "tools" / "analyze_stage3_current_a976_hot_regions.py"),
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
    assert report["complete_tick_cycles"] == 1_936_861, report
    assert report["profiled_row_cycles"] == 1_714_156, report
    assert [
        (row["name"], row["cycles"], row["observed_row_count"])
        for row in report["regions"]
    ] == [
        ("box_and_collision_record_emitters", 629_772, 33),
        ("draw_dispatch_and_indirect_callers", 362_358, 21),
        ("task15_2429c_root", 101_454, 1),
        ("scheduler_and_idle", 156_010, 5),
    ], report
    assert report["assigned_profiled_row_cycles"] == 1_249_594, report
    assert report["unassigned_cycles_in_top_rows"] == 464_562, report
    assert "selection only" in report["scope"], report
    print("active a976 Stage-3 hotspot-region reduction: green")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
