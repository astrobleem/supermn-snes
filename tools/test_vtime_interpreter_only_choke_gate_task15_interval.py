#!/usr/bin/env python3
"""Pin the fixed candidate's exact tick-14746..14747 interval scope."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT = (
    ROOT
    / "build/playback-watcher-20260809"
    / "vtime-interpreter-only-e00f-gate-restore-scheduler-0818-mvc-fallback-choke-gate-task15-14746-to14747-v1"
    / "watcher-report.json"
)


def main() -> None:
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    ranges = report["mismatch_ranges"]
    symptoms = report["specific_symptoms"]

    assert report["first_divergence"].startswith("Tick 14747 task-15 frame")
    assert "candidate PC 00025876/SR2409" in report["first_divergence"]
    assert "MAME PC 0002582E/SR2408" in report["first_divergence"]
    assert "after the exact 02429C root stop" in report["first_divergence"]
    assert ranges["hooks"] == (
        "boundary->root: 10,173 prepare and 10,173 consume, no reload/IRQ; "
        "root->14747: 1,403 prepare, 1,404 consume, one reload and one IRQ"
    )
    assert "player fields remain green" in ranges["player"]
    assert "VTime boundary/root remain 69513->8236 units" in symptoms
    assert "all four target gates and halt remain zero" in symptoms
    assert "cannot prove whether" in symptoms
    assert "instruction-order or charge undercost" in symptoms
    assert "ROM-migrated forensic scope only" in symptoms
    print("VTIME interpreter-only choke gate: green task15 interval")


if __name__ == "__main__":
    main()
