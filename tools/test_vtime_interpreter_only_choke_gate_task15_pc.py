#!/usr/bin/env python3
"""Pin the corrected root-to-IRQ PC alignment for tick 14747."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT = (
    ROOT
    / "build/playback-watcher-20260809"
    / "vtime-interpreter-only-e00f-gate-restore-scheduler-0818-mvc-fallback-choke-gate-task15-14746-to14747-pc-v1"
    / "watcher-report.json"
)


def main() -> None:
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    first = report["first_divergence"]
    ranges = report["mismatch_ranges"]
    symptoms = report["specific_symptoms"]

    assert first["kind"].startswith("same-order virtual-clock/IRQ cutoff")
    assert first["mame"]["raw_bridge_observation_gap"] == [
        "0242AC",
        "0242B2",
        "0242B8",
    ]
    assert first["mame"]["first_substantive_extra_pc"] == "025876"
    assert first["mame"]["mame_extra_rows_before_common_0006C4"] == 99
    assert first["mame"]["mame_cycles_first_extra_to_common_0006C4"] == 1214
    assert len(ranges["pc_order"]) == 4
    assert all(
        row["classification"].startswith("expected native-root CALL-BRIDGE")
        for row in ranges["pc_order"][:3]
    )
    assert ranges["pc_order"][3]["classification"] == (
        "substantive same-order virtual-clock/IRQ cutoff"
    )
    assert ranges["sequence_totals"] == {
        "mame_retired_rows": 1505,
        "candidate_prepare_rows": 1403,
        "equal_rows": 1403,
        "mame_deleted_or_replaced": 102,
        "candidate_inserted_or_replaced": 0,
    }
    assert "F28900/F28B00 were not hooked" in symptoms
    assert "route/charge loss is unproven" in symptoms
    assert "consistent with same-order virtual-clock cutoff" in symptoms
    print("VTIME interpreter-only choke gate: green corrected task15 PC seam")


if __name__ == "__main__":
    main()
