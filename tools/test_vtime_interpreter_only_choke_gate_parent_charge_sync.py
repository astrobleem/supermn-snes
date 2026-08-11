#!/usr/bin/env python3
"""Pin the successful synchronous root parent-charge snapshots."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT = (
    ROOT
    / "build/playback-watcher-20260809"
    / "vtime-interpreter-only-e00f-gate-restore-scheduler-0818-mvc-fallback-choke-gate-task15-14746-to14747-parent-charge-sync-v1"
    / "watcher-report.json"
)


def main() -> None:
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    ranges = report["mismatch_ranges"]
    symptoms = report["specific_symptoms"]

    assert report["first_divergence"].startswith(
        "Tick14747 task15 remains candidate PC25876/SR2409"
    )
    assert "1214 MAME cycles" in ranges["retained_mame_gap"]
    assert "Three root sequences" in ranges["synchronous_charge_deltas"]
    assert "decremented VTIME by 8 units" in ranges["synchronous_charge_deltas"]
    assert "decremented 10 units" in ranges["synchronous_charge_deltas"]
    assert "No missing gateway/entry/finish call" in ranges[
        "synchronous_charge_deltas"
    ]
    assert "Corrected run exit=0" in symptoms
    assert "Gateway CPU-A values are 3,4,5" in symptoms
    assert "native pending/current values are 3,4,5" in symptoms
    assert "all gates 071A/073A/0736/073C=0 and halt=0" in symptoms
    assert "ROM-migrated forensic/non-acceptance scope" in symptoms
    print("VTIME interpreter-only choke gate: green synchronous parent charge")


if __name__ == "__main__":
    main()
