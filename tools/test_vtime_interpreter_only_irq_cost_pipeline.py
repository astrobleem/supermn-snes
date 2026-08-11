#!/usr/bin/env python3
"""Pin the current-hash Stage-3 IRQ endpoint/cost-pipeline evidence."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FOCUSED = (
    ROOT
    / "build/playback-watcher-20260810"
    / "vtime-interpreter-only-paced0818-dbcc-resume14001-to15500-v1"
    / "focused-y-write-v1"
)


def load(relative: str) -> dict[str, object]:
    return json.loads((FOCUSED / relative).read_text(encoding="utf-8"))


def main() -> int:
    branch = load("branch-2584a-v1/branch-2584a-report.json")
    assert branch["mismatch_ranges"]["branch_seam"] == []
    assert branch["mismatch_ranges"]["operand"] == {
        "address": "F03CB4",
        "mame": "0001",
        "candidate": "0001",
    }
    assert "both read F03CB4=0001" in branch["first_divergence"]
    assert "prior apparent mismatch came from a different repeated MAME" in (
        branch["first_divergence"]
    )

    child = load(
        "corrected-child-alignment-v1/corrected-child-report.json"
    )
    ranges = child["mismatch_ranges"]
    assert ranges["mame_window"] == [2_064_420_123, 2_064_426_261]
    assert ranges["sequence"]["common_paired_rows"] == 553
    assert ranges["sequence"]["pc_or_opcode_mismatches"] == 0
    assert ranges["common_cost_delta_cycles"] == 0
    assert ranges["endpoint_extra_units"] == 26
    assert ranges["endpoint_extra_cycles"] == 52
    assert ranges["net_vs_scheduler_cycles"] == 32
    assert "wrong repeated MAME window" in child["specific_symptoms"]["invalidated"]
    assert child["specific_symptoms"]["causal_status"].startswith(
        "Bounded endpoint/deadline accounting residual"
    )

    irq = load("irq-cost-pipeline-v1/irq-cost-report.json")
    irq_ranges = irq["mismatch_ranges"]
    assert irq_ranges["candidate_debit_units"] == 47
    assert irq_ranges["candidate_debit_cycles"] == 94
    assert irq_ranges["mame_visible_isr_units"] == 49
    assert irq_ranges["mame_visible_isr_cycles"] == 98
    assert irq_ranges["mame_irq_edge_cycles"] == 66
    assert irq_ranges["candidate_paired_consume_rows"] == [
        ["000818", "4E75", 8],
        ["0006C4", "007C", 10],
        ["0006C8", "1B6D", 10],
        ["0006CE", "662E", 5],
        ["0006FE", "4FF9", 6],
        ["000704", "422D", 8],
    ]
    assert irq_ranges["candidate_prepared_rows"][-1] == [
        "000708",
        "4EB9",
        10,
    ]
    assert irq_ranges["requested_3a92_to_25110"] == {
        "candidate_cycles": 133_046,
        "candidate_minus_mame_cycles": 26,
        "mame_cycles": 133_020,
    }
    assert "consumes stale 000818/4E75 cost8" in irq["first_divergence"]
    assert "leaves final 000708/4EB9 cost10 unconsumed" in (
        irq["first_divergence"]
    )
    assert irq["specific_symptoms"]["source_owner"].startswith(
        "Only VTIME prepare/consume endpoint ownership is directly supported"
    )
    assert "rebuild_required_now=false" in irq["specific_symptoms"]["source_owner"]

    print("VTIME interpreter-only IRQ endpoint evidence: green")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
