#!/usr/bin/env python3
"""Pin the bounded charge-prefix evidence and its remaining data gap."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT = (
    ROOT
    / "build/playback-watcher-20260809"
    / "vtime-interpreter-only-e00f-gate-restore-scheduler-0818-mvc-fallback-choke-gate-task15-14746-to14747-charge-prefix-v1"
    / "watcher-report.json"
)


def main() -> None:
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    ranges = report["mismatch_ranges"]
    symptoms = report["specific_symptoms"]

    assert report["first_divergence"].startswith(
        "Cumulative candidate VTIME charge divergence is UNLOCATABLE"
    )
    assert "MAME rows [0,1393): 16404 observed cycles" in ranges[
        "aligned_prefix"
    ]
    assert "3 sequences x (8 charge + 10 finish) = 54 VT units" in ranges[
        "native_parent_rows"
    ]
    assert "99 rows / 1214 cycles" in ranges["first_path_gap"]
    assert "No per-prepare VT_REMAIN/VT_COST" in symptoms
    assert "sign of overcharge versus phase offset cannot be computed" in symptoms
    assert "different MAME window" in symptoms
    assert "ROM-migrated forensic/non-acceptance scope" in symptoms
    print("VTIME interpreter-only choke gate: green charge-prefix scope")


if __name__ == "__main__":
    main()
