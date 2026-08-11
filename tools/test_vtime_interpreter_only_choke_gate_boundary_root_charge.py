#!/usr/bin/env python3
"""Pin the aggregate tick-14746 boundary-to-root overcharge evidence."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT = (
    ROOT
    / "build/playback-watcher-20260809"
    / "vtime-interpreter-only-e00f-gate-restore-scheduler-0818-mvc-fallback-choke-gate-task15-14746-boundary-root-charge-v1"
    / "watcher-report.json"
)


def main() -> None:
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    ranges = report["mismatch_ranges"]
    symptoms = report["specific_symptoms"]

    assert report["first_divergence"].startswith("Endpoint phase-budget difference only")
    assert "candidate charges 122554 nominal cycles" in report["first_divergence"]
    assert "MAME 121398 (+1156)" in report["first_divergence"]
    assert "10173 prepare and 10173 consume" in ranges["candidate"]
    assert "10140 retired intervals" in ranges["mame"]
    assert ranges["aggregate"].startswith("+1156 candidate nominal cycles")
    assert "prepare/consume counts balance" in symptoms
    assert "no reload/IRQ occurs before root" in symptoms
    assert "per-fetch VT_COST, logical PC" in symptoms
    assert "safest next diagnostic" in symptoms
    print("VTIME interpreter-only choke gate: green boundary-root aggregate")


if __name__ == "__main__":
    main()
