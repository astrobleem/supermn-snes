#!/usr/bin/env python3
"""Pin the task-13 PC-write proof that the pool route was not skipped."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT = (
    ROOT
    / "build/playback-watcher-20260809"
    / "vtime-interpreter-only-e00f-gate-restore-scheduler-0818-mvc-fallback-root-task13-pcwrite-v1"
    / "watcher-report.json"
)


def main() -> None:
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    candidate = report["mismatch_ranges"]["candidate_pcwrite_window"]
    mame = report["mismatch_ranges"]["mame_task13_comparison"]
    symptoms = report["specific_symptoms"]

    assert report["first_divergence"].startswith("VTIME_PREPARE_BYPASS_AFTER_0007E4")
    assert candidate["pc_write_events"] == 14_718
    assert candidate["same_cycle_write_groups"] == 0
    assert candidate["byte3_completion_states"] == 3_330
    assert candidate["vtime_prepare_events"] == 1
    counts = candidate["target_entry_runs"]
    assert counts["$0007E8"]["count"] == 1
    assert counts["$02E864"]["count"] == 1
    for pc in ("$02E8B8", "$0249C2", "$02498C"):
        assert counts[pc]["count"] == 12
        assert mame["target_counts"][pc] == 12
    assert counts["$000532"]["count"] == 1
    assert counts["$000766"]["count"] == 1
    assert "ordered PC-state values and updates only" in candidate[
        "evidence_semantics"
    ]
    assert "VTIME-instrumentation/clock-ownership bypass" in symptoms[
        "classification"
    ]
    assert "no emulator launch" in symptoms["scope"]
    print("interpreter-only Stage-3 task13 PC writes: green route proof")


if __name__ == "__main__":
    main()
