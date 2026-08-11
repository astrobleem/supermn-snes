#!/usr/bin/env python3
"""Regression guard for production and diagnostic `$02429C` handoffs."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="supermn-2429c-handoff-") as temporary:
        output = Path(temporary) / "protocol.json"
        subprocess.run(
            [
                sys.executable,
                str(ROOT / "tools" / "audit_stage3_2429c_handoff_protocol.py"),
                "--output",
                str(output),
            ],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        report = json.loads(output.read_text(encoding="utf-8"))
    assert report["production_root_is_currently_unwired"] is True
    assert report["totals"] == {
        "direct_native_handoffs_after_fusion": 4,
        "fused_original_native_callees": 3,
        "ojmp_handoffs": 6,
        "original_child_handoff_sites": 11,
        "parent_local_charge_calls": 0,
    }
    assert all(row["must_flush_parent_before_transfer"] for row in report["direct_native_handoffs"])
    assert all(row["must_flush_parent_before_transfer"] for row in report["ojmp_handoffs"])
    diagnostic = report["diagnostic_root"]
    assert diagnostic["locally_closed"] is True, report
    assert diagnostic["basic_block_charge_sites"] == 35, report
    assert diagnostic["architectural_child_handoffs"] == 11, report
    assert diagnostic["return_dispatch_entries"] == 11, report
    assert diagnostic["mode_aware_gate_restore_calls"] == 11, report
    assert diagnostic["ordinary_vtime_restored_gate"] == 1, report
    assert diagnostic["interpreter_only_restored_gate"] == 0, report
    assert diagnostic["architectural_returns"][0] == "0242AC", report
    assert diagnostic["architectural_returns"][-1] == "0243DA", report
    print("Stage-3 $02429C handoff-protocol audit: green (diagnostic locally closed)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
