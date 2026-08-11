#!/usr/bin/env python3
"""Regression guard for local `$02429C` closure and global blocking."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="supermn-2429c-clock-closure-") as temporary:
        output = Path(temporary) / "closure.json"
        subprocess.run(
            [
                sys.executable,
                str(ROOT / "tools" / "audit_stage3_2429c_common_clock_closure.py"),
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
    assert report["root"]["vtime_owner_now"] == "$0005 / VT_OWNER_2429C", report
    assert report["root"]["local_vtime_wiring_now"] is True, report
    assert report["root"]["production_vtime_wiring_now"] is False, report
    assert report["root"]["accelerated_boundary_state"] == "selected-ledger", report
    assert report["root"]["basic_blocks"] == 35, report
    assert report["root"]["dynamic_terminal_control_flow"] == 14, report
    assert all(
        row["included_by_current_vtime_image"] is True
        for row in report["root"]["generated_metadata"].values()
    ), report
    assert report["current_native_owner_dispatch"] == ["$025110", "$02429C", "Stage-3 player"], report
    assert report["totals"] == {
        "original_child_handoffs": 11,
        "native_or_fused_handoffs": 5,
        "interpreter_or_dynamic_handoffs": 6,
        "handoffs_admitted_to_local_common_clock": 11,
    }, report
    assert all(row["parent_pretransfer_flush_now"] is True for row in report["handoffs"]), report
    assert all(row["due_irq_handoff_now"] is True for row in report["handoffs"]), report
    assert all(row["admitted_to_local_common_clock"] is True for row in report["handoffs"]), report
    fusion = next(row for row in report["handoffs"] if row["original_call_pc"] == "0242A6")
    assert fusion["production_kind"] == "fused-native-triple", report
    assert fusion["original_target"] == "023342", report
    collision = next(row for row in report["handoffs"] if row["original_call_pc"] == "0242B8")
    assert collision["child_owner_now"] == "common interpreter per-fetch clock", report
    dynamic = next(row for row in report["handoffs"] if row["original_call_pc"] == "02436C")
    assert dynamic["original_target"] == "indirect-A0", report
    print("Stage-3 $02429C common-clock closure regression: green (local closure; global promotion blocked)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
