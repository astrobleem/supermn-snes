#!/usr/bin/env python3
"""Pin the bounded task-13 evidence for the absolute `$072E` choke gate."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT = (
    ROOT
    / "build/playback-watcher-20260809"
    / "vtime-interpreter-only-e00f-gate-restore-scheduler-0818-mvc-fallback-choke-gate-root-task13-fetch-control-v1"
    / "watcher-report.json"
)


def main() -> None:
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    interval = report["mismatch_ranges"]["fixed_interval"]
    counts = interval["hook_counts"]
    comparison = interval["red_comparison"]
    symptoms = report["specific_symptoms"]

    assert report["first_divergence"].startswith(
        "NOT_REACHED_IN_BOUNDED_FETCH_CONTROL"
    )
    for label in (
        "ifetch_timer_continue_0080ee",
        "loop_hook_00f58c",
        "lh_off_0080fb",
        "choke_tramp_00f980",
        "vtime_choke_f2b480",
        "vtime_consume_f28400",
        "vtime_consume_virtual_f2841d",
        "vtime_consume_no_deadline_f2845c",
        "vtime_prepare_f28001",
        "relocated_legacy_choke_00e281",
    ):
        assert counts[label] == 2_971
    assert counts["vtime_reload_f28500"] == 0
    assert counts["take_irq_00b404"] == 0
    assert comparison["red_prepare"] == 1
    assert comparison["fixed_prepare"] == 2_971
    assert comparison["red_choke"] == comparison["fixed_choke"] == 2_971
    assert comparison["cycle_delta"] == 1_537_352
    assert "one prepare per ifetch/loop/choke path" in symptoms[
        "repair_discriminator"
    ]
    assert "Positive bounded choke-gate control-flow result only" in symptoms[
        "classification"
    ]
    print("VTIME interpreter-only choke gate evidence: green bounded task13")


if __name__ == "__main__":
    main()
