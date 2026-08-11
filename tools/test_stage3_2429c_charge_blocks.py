#!/usr/bin/env python3
"""Focused regression for the `$02429C` future-common-clock inventory."""

from __future__ import annotations

import audit_stage3_2429c_charge_blocks as audit


def main() -> int:
    report = audit.collect()
    assert report["entry_pc"] == "02429C"
    assert report["totals"] == audit.EXPECTED_TOTALS
    dynamic = [
        item
        for block in report["blocks"]
        for item in block["dynamic_terminal_control_flow"]
    ]
    assert len(dynamic) == 14
    assert {item["kind"] for item in dynamic} == {"conditional_branch_or_loop"}
    handoffs = report["unadmitted_child_handoff_sites"]
    assert len(handoffs) == 11
    assert [item["target"] for item in handoffs].count("0243E8") == 3
    assert {item["target"] for item in handoffs} == {
        "023342", "023E34", "0235E0", "025110", "0259CA", "0243E8",
        "02443A", "0244D4", "indirect-A0",
    }
    assert sum(item["route"].startswith("native-") for item in handoffs) == 5
    assert sum(item["route"] == "interpreter-xlat-miss" for item in handoffs) == 5
    assert sum(item["route"] == "dynamic-indirect-dispatch" for item in handoffs) == 1
    children = report["unadmitted_direct_child_inventory"]
    assert [item["entry_pc"] for item in children] == [
        "023342", "023E34", "0235E0", "025110", "0259CA", "0243E8",
        "02443A", "0244D4",
    ]
    assert any(
        item["dynamic_kind_counts"].get("movem_register_count", 0)
        for item in children
    )
    assert any(
        item["dynamic_kind_counts"].get("shift_or_rotate", 0)
        for item in children
    )
    print("Stage-3 $02429C block-ledger inventory: green (unadmitted diagnostic)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
