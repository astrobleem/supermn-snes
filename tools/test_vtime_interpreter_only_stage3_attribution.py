#!/usr/bin/env python3
"""Pin exact Stage-3 task-frame attribution for repaired interpreter-only VTIME."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT = (
    ROOT
    / "build/playback-watcher-20260809"
    / "vtime-interpreter-only-e00f-gate-restore-stage3-attribution-v1"
    / "watcher-report.json"
)


def main() -> None:
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    first = report["first_divergence"]
    assert first["kind"] == "authoritative_task15_frame"
    assert first["mame_tick"] == 14746
    assert first["mame"] == {
        "pc": "000259B0",
        "return_pc": "000242BE",
        "sr": "2400",
        "saved_sp": "00F001C0",
    }
    assert first["snes"] == {
        "pc": "0002429C",
        "return_pc": "0000044E",
        "sr": "2404",
        "saved_sp": "00F001C4",
    }
    symptom = report["specific_symptoms"]
    ticks = symptom["ticks"]
    assert ticks["14744"]["task15_equal"] is True
    assert ticks["14745"]["task15_equal"] is True
    assert ticks["14746"]["task15_equal"] is False
    assert ticks["14747"]["task15_equal"] is False
    assert ticks["14746"]["rng_bytes"] == 2
    assert ticks["14746"]["collision_bytes"] == 1
    assert all(row["gates"] == "071A=0,073A=0" for row in ticks.values())
    assert all(row["halt"] == 0 for row in ticks.values())
    phase = symptom["charged_vs_mame_pre_root"]
    assert phase["mame_boundary_to_root_cycles"] == 131286
    assert phase["charged_pre_root_cycle_deficit"] == 114978
    assert phase["root_entry_phase_lateness"] == 115204
    assert symptom["classification"] == (
        "upstream/common-clock timing deficit manifested as task-15 frame "
        "divergence; not a halt, gate, player-oracle, or capture-tool failure"
    )
    print("interpreter-only Stage-3 attribution regression: green")


if __name__ == "__main__":
    main()
