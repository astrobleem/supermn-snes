#!/usr/bin/env python3
"""Pin the disk-only task-13 VTIME-prepare gap reduction."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT = (
    ROOT
    / "build/playback-watcher-20260809"
    / "vtime-interpreter-only-e00f-gate-restore-scheduler-0818-mvc-fallback-root-task13-pc-v1"
    / "watcher-report.json"
)


def main() -> None:
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    candidate = report["mismatch_ranges"]["candidate_task13_window"]
    mame = report["mismatch_ranges"]["mame_task13_window"]
    symptoms = report["specific_symptoms"]

    assert report["first_divergence"].startswith("TASK13_PC_GAP_AFTER_0007E4")
    assert candidate["pc_stream_handoff"]["pc"] == "$0007E4"
    assert candidate["pc_stream_next_scan"]["pc"] == "$000766"
    assert candidate["strict_window_prepare_count"] == 1
    assert candidate["strict_window_interior_prepare_count"] == 0
    assert candidate["target_pc_counts"] == {
        "$02E8B8": 0,
        "$0249C2": 0,
        "$02498C": 0,
        "$000766_endpoint": 1,
    }
    assert mame["retired_instruction_count"] == 2_970
    assert mame["target_pc_counts"] == {
        "$02E8B8": 12,
        "$0249C2": 12,
        "$02498C": 12,
    }
    assert "absolute cycle coordinates are not identical" in symptoms[
        "authentication"
    ]
    assert "no logical-PC reconstruction" not in symptoms["candidate_logical_route"]
    assert "notification-only physical hooks remain separate evidence" in symptoms[
        "physical_route"
    ]
    assert "Disk-only reduction" in symptoms["scope"]
    print("interpreter-only Stage-3 task13 prepare stream: green gap")


if __name__ == "__main__":
    main()
