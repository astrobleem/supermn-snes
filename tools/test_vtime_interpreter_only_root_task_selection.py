#!/usr/bin/env python3
"""Pin the bounded SHAa49e scheduler selection order before task 15."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT = (
    ROOT
    / "build/playback-watcher-20260809"
    / "vtime-interpreter-only-e00f-gate-restore-scheduler-0818-mvc-fallback-root-task-selection-v1"
    / "watcher-report.json"
)


def main() -> None:
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    probe = report["mismatch_ranges"]["task_selection_probe"]
    selections = probe["selections"]
    symptoms = report["specific_symptoms"]

    assert probe["completed_ticks"] == [14744, 14745]
    assert "all logical $0007E4/$000766 stops passed" in probe[
        "exact_stop_predicates"
    ]
    assert [row["selector_d0"] for row in selections] == [
        0,
        1,
        2,
        3,
        4,
        5,
        6,
        12,
        13,
        14,
        15,
    ]
    task13 = selections[8]
    assert task13["restored_pc"] == "$0002E864"
    assert task13["saved_sp"] == "$00F00444"
    assert task13["sr"] == "$2400"
    assert task13["return"] == "$0000044E"
    assert task13["interval_cycles"] == 2_739_176
    assert task13["hooks"]["prepare"] == 1
    assert task13["hooks"]["consume"] == 1
    assert task13["hooks"]["old_helper"] == 2_951
    assert task13["hooks"]["entry_2429c"] == 0
    assert task13["hooks"]["entry_ce4t"] == 0
    assert "task 13 is unambiguously before task 15" in symptoms["ordering"]
    assert "$071A=$073A=$0736=$073C=0" in symptoms["gates_and_halt"]
    assert "no logical-PC reconstruction" in symptoms["pool_path"]
    print("interpreter-only Stage-3 root task selection: green bounded order")


if __name__ == "__main__":
    main()
