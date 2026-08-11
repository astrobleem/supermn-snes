#!/usr/bin/env python3
"""Pin the fixed candidate's first post-repair task/player divergence."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT = (
    ROOT
    / "build/playback-watcher-20260809"
    / "vtime-interpreter-only-e00f-gate-restore-scheduler-0818-mvc-fallback-choke-gate-first-player-v1"
    / "watcher-report.json"
)


def main() -> None:
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    ranges = report["mismatch_ranges"]
    symptoms = report["specific_symptoms"]

    assert report["first_divergence"].startswith("MAME tick 14747")
    assert "SR 2409 vs 2408" in report["first_divergence"]
    assert "PC 00025876 vs 0002582E" in report["first_divergence"]
    assert "first player y mismatch" in report["first_divergence"]
    assert ranges["task15"] == (
        "equal at 14744 and 14745; equal at 14746; differs at 14747 and 14748"
    )
    assert "full player record equal through 14746" in ranges["player"]
    assert "input differs at 14747" in ranges["player"]
    assert "y differs at 14748" in ranges["player"]
    assert "matches MAME exactly at 14746" in symptoms
    assert "Retained old a49 artifacts exist only at 14744..14745" in symptoms
    assert "no a49 14746..14747 artifact was available" in symptoms
    assert "forensic work-bin evidence only" in symptoms
    print("VTIME interpreter-only choke gate: green first player boundary")


if __name__ == "__main__":
    main()
