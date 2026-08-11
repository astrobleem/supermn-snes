#!/usr/bin/env python3
"""Pin the fixed choke gate's bounded boundary-to-root fetch recovery."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT = (
    ROOT
    / "build/playback-watcher-20260809"
    / "vtime-interpreter-only-e00f-gate-restore-scheduler-0818-mvc-fallback-choke-gate-root-fetch-v1"
    / "watcher-report.json"
)


def main() -> None:
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    ranges = report["mismatch_ranges"]
    comparison = ranges["count_comparison"]
    symptoms = report["specific_symptoms"]

    assert report["first_divergence"].startswith(
        "NOT_REACHED_IN_BOUNDED_ROOT_FETCH"
    )
    assert ranges["14744"]["bytes"] == ranges["14745"]["bytes"] == 21
    assert comparison["fixed_prepare_consume"] == [11_010, 11_010]
    assert comparison["prior_a49e_prepare_consume"] == [7_230, 7_230]
    assert comparison["mame_retired_pre_root"] == 11_006
    assert comparison["recovered_vs_prior"] == 3_780
    assert comparison["fixed_minus_mame"] == 4
    assert "task 0, task 13, and task 15 saved frames match" in ranges[
        "task_frames"
    ]
    assert "reload and IRQ are 0" in symptoms["hooks"]
    assert "root remain 3545" in symptoms["phase"]
    assert "requires path alignment" in symptoms["classification"]
    print("VTIME interpreter-only choke gate root fetch: green bounded recovery")


if __name__ == "__main__":
    main()
