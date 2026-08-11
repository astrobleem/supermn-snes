#!/usr/bin/env python3
"""Pin the disk-only Stage-3 root/child/continuation owner ledger."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT = (
    ROOT
    / "build/playback-watcher-20260809"
    / "stage3-2429c-25110-259b0-owner-ledger-v1"
    / "watcher-report.json"
)


def main() -> None:
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    first = report["first_divergence"]
    ranges = report["mismatch_ranges"]
    symptoms = report["specific_symptoms"]

    assert first["kind"] == "first_missing_common_clock_ownership_not_new_oracle_divergence"
    assert first["failing_interval"] == "MAME tick 14745->14746"
    assert first["retired_evidence"] == {
        "root_cycle": 2064418589,
        "child_cycle": 2064420143,
        "first_259b0_cycle": 2064421465,
    }
    assert ranges["kind"] == "cycle/path ownership ranges, not RAM mismatches"
    assert ranges["failing_interval"]["cycles"] == 139486
    assert ranges["failing_interval"]["retired_instruction_rows"] == 11656

    path = ranges["path_cycle_ranges"]
    assert [row["name"] for row in path] == [
        "root_entry_to_child",
        "child_to_first_loop_branch",
        "first_loop_branch_to_first_continuation",
        "collision_continuation",
        "continuation_to_irq_boundary",
        "irq_entry_gap",
        "irq_to_tick_boundary",
    ]
    assert [row["cycles"] for row in path] == [1554, 1176, 146, 4580, 216, 64, 428]
    assert path[3]["retired_rows"] == 27

    lateness = symptoms["root_entry_lateness_vs_in_group"]
    assert lateness["in_group_retired_cycles_root_to_first_259b0"] == 2876
    assert lateness["pre_root_deficit_cycles"] == 114978
    assert lateness["phase_lateness_cycles"] == 115204
    assert "no single owner is isolated" in lateness["interpretation"]
    assert symptoms["ownership_classification"]["audit_promotion_blocked"] is True
    assert symptoms["ownership_classification"]["audit_unmigrated_ac_writer_count"] == 11
    assert symptoms["scope"].startswith("disk-only, read-only reduction")
    assert "Read-only, source-authenticated root-to-child handoff ledger" in (
        symptoms["safest_next_bounded_diagnostic"]
    )
    print("Stage-3 $02429C/$025110/$0259B0 owner ledger: green disk-only reduction")


if __name__ == "__main__":
    main()
