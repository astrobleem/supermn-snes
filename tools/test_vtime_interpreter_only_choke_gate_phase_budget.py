#!/usr/bin/env python3
"""Pin the exact aggregate phase-budget decomposition at tick 14747."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT = (
    ROOT
    / "build/playback-watcher-20260809"
    / "vtime-interpreter-only-e00f-gate-restore-scheduler-0818-mvc-fallback-choke-gate-task15-14746-to14747-phase-budget-v1"
    / "watcher-report.json"
)


def main() -> None:
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    ranges = report["mismatch_ranges"]
    symptoms = report["specific_symptoms"]

    assert "+1156" in report["first_divergence"]
    assert "root budget is 1146 cycles short" in report["first_divergence"]
    assert ranges["boundary_to_root"].endswith(
        "candidate remain69513->8236 = 61277 VT units = 122554 nominal cycles."
    )
    assert ranges["root_to_common_irq"].endswith(
        "candidate root budget8236 units = 16472 cycles, short by1146."
    )
    assert ranges["missing_tail"].endswith(
        "exact arithmetic is 1146 preceding cycles + 68-cycle terminal "
        "$02582A interval."
    )
    assert "No reload/IRQ occurs in candidate boundary->root" in symptoms
    assert "1146+68 decomposition is arithmetically verified" in symptoms
    assert "causal per-instruction attribution is not" in symptoms
    assert "Disk-only ROM-migrated forensic scope" in symptoms
    print("VTIME interpreter-only choke gate: green phase-budget join")


if __name__ == "__main__":
    main()
