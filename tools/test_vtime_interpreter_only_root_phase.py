#!/usr/bin/env python3
"""Pin the bounded SHA7a22 interpreter-only root-phase measurement."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT = (
    ROOT
    / "build/playback-watcher-20260809"
    / "vtime-interpreter-only-e00f-gate-restore-scheduler-0818-fallback-root-phase-v1"
    / "watcher-report.json"
)


def main() -> None:
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    symptoms = report["specific_symptoms"]
    run = symptoms["run"]
    phase = symptoms["root_phase_probe"]

    assert symptoms["identity"]["rom_sha256"] == (
        "7a22b81929a491d3bf0dea96835e35d8e6fe154f13bff79cff4489559296f387"
    )
    assert symptoms["identity"]["state_sha256"] == (
        "5ccbc5096c50e301331bd67e382e54c1e4d2afbdd31fd75405f8f5bb4102bfec"
    )
    assert symptoms["identity"]["nexen_path"].endswith(
        "mcp-combined-20260809-partial-count-publish/Nexen"
    )
    assert run["harness_v1_exit"] == 2
    assert "invalid launcher" in run["harness_v1"]
    assert run["harness_v2_exit"] == 0
    assert run["exact_entries"].startswith("4/4")
    assert "root probe 1/1" in run["exact_entries"]
    assert "halt=0" in run["terminal"]
    assert "all 0" in run["terminal"]

    assert phase["boundary_completed_tick"] == 14745
    assert phase["boundary_vtime_remain_units"] == 69603
    assert phase["root_vtime_remain_units"] == 34747
    assert phase["remain_delta_units"] == 34856
    assert phase["remain_delta_times_two"] == 69712
    assert phase["mame_boundary_to_root_cycles"] == 131286
    assert phase["root_remain_times_two"] == 69494
    assert phase["mame_root_to_irq_cycles"] == 7692
    assert phase["reload_irq_between_boundary_and_root"].startswith("none observed")
    assert phase["phase"] == "2046 at boundary and root; due=0; overshoot=0"

    first = report["first_divergence"]
    assert first["mame_tick"] == 14746
    assert first["mame"]["pc"] == "000259B0"
    assert first["snes"]["pc"] == "0002429C"
    assert [report["mismatch_ranges"][str(tick)]["bytes"] for tick in range(14744, 14748)] == [
        21,
        21,
        78,
        83,
    ]
    print("interpreter-only Stage-3 root phase: green bounded undercharge measurement")


if __name__ == "__main__":
    main()
