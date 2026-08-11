#!/usr/bin/env python3
"""Pin the bounded task-13 choke/VTIME control-flow localization."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT = (
    ROOT
    / "build/playback-watcher-20260809"
    / "vtime-interpreter-only-e00f-gate-restore-scheduler-0818-mvc-fallback-root-task13-fetch-control-v1"
    / "watcher-report.json"
)


def main() -> None:
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    interval = report["mismatch_ranges"]["strict_task13_interval"]
    counts = interval["hook_counts"]
    symptoms = report["specific_symptoms"]

    assert report["first_divergence"].startswith(
        "FETCH_CONTROL_VTIME_BRANCH_AFTER_SECOND_CHOKE"
    )
    assert interval["cycles"] == 2_739_176
    for label in (
        "ifetch_timer_continue_0080ee",
        "loop_hook_00f58c",
        "lh_off_0080fb",
        "choke_tramp_00f980",
    ):
        assert counts[label] == 2_971
    assert counts["lh_nofire_00f5c0"] == 2_951
    assert counts["gm_memclr_00f60a"] == 19
    assert counts["gm_verify_far_99f4a0"] == 19
    assert counts["gm_memset_far_99f5c0"] == 19
    assert counts["vtime_choke_f2b480"] == 1
    assert counts["vtime_consume_f28400"] == 1
    assert counts["vtime_prepare_f28001"] == 1
    assert counts["vtime_reload_f28500"] == 0
    assert counts["take_irq_00b404"] == 0
    assert "subsequent paths omit vtime_choke" in symptoms["branch_order"]
    assert "post-choke branch condition" in symptoms["classification"]
    print("interpreter-only Stage-3 task13 fetch control: green red-localization guard")


if __name__ == "__main__":
    main()
