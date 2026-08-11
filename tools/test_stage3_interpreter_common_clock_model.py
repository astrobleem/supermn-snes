#!/usr/bin/env python3
"""Pin the disk-only Stage-3 interpreter/common-clock model audit."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT = (
    ROOT
    / "build/playback-watcher-20260809"
    / "stage3-interpreter-common-clock-model-v1"
    / "watcher-report.json"
)


def main() -> None:
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    ranges = report["mismatch_ranges"]
    symptoms = report["specific_symptoms"]

    assert report["first_divergence"].startswith("CYCLE_MODEL_SCOPE_GAP:")
    assert "not a measured SHA7a22 bit-1 phase" in report["first_divergence"]
    assert ranges["kind"] == "cycle/model ranges, not RAM mismatches"
    assert ranges["mame_boundary_to_root_cycles"] == 131286
    assert ranges["selected_vtime_charge_cycles"] == 16308
    assert ranges["unaccounted_cycles"] == 114978
    assert ranges["root_entry_phase_lateness_cycles"] == 115204

    trace = symptoms["pre_root_trace"]
    assert trace == {
        "mame_cycles": 131286,
        "retired_instruction_intervals": 11006,
        "static_comparable": 11006,
        "static_exact": 9193,
        "static_mismatch": 1813,
    }
    assert "not an instruction count" in symptoms["current_charge"]
    assert "not a bit-1 SHA7a22 measurement" in symptoms["current_charge"]
    assert "38,888 exact / 46,874 comparable" in symptoms["global_dynamic_evidence"]
    assert "filtered read-only vtime_prepare_gateway" in symptoms["safe_next_slice"]
    assert symptoms["scope"] == (
        "disk-only/no emulator/no new oracle; retained original-MAME trace and prior validation artifacts"
    )
    print("Stage-3 interpreter/common-clock model audit: green provenance bound")


if __name__ == "__main__":
    main()
