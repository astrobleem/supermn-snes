#!/usr/bin/env python3
"""Pin the disk-only Stage-3 remaining loop/idle owner reduction."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT = (
    ROOT
    / "build/playback-watcher-20260809"
    / "stage3-remaining-loop-idle-owner-scope-v1"
    / "watcher-report.json"
)


def main() -> None:
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    symptoms = report["specific_symptoms"]
    ranges = report["mismatch_ranges"]

    assert symptoms["scope"].startswith("read-only disk reduction")
    assert "no emulator launch" in symptoms["scope"]
    assert "no MAME-vs-SNES oracle divergence was run" in report["first_divergence"]
    assert ranges["kind"] == "cycle/path owner-coverage ranges, not RAM mismatches"
    assert ranges["failing_window"] == {
        "mame_tick": "14745->14746",
        "cycles": 139486,
        "boundary_cycles": [2064287283, 2064426769],
        "retired_rows": 11656,
    }
    assert ranges["retired_targets"]["000818"] == (
        "14744->14745:1993; 14745->14746:0; 14746->14747:0"
    )
    for target in ("003B84", "003FEA", "00ADBE"):
        assert ranges["retired_targets"][target] == "0 retained"
    assert ranges["retired_targets"]["02429C"] == "1 in failing interval"
    assert ranges["retired_targets"]["025110"] == "1 in failing interval"
    assert ranges["retired_targets"]["0259B0"] == "27 in failing interval"
    assert "$0818 is the only requested loop/idle target proven retired" in (
        symptoms["owner_finding"]
    )
    assert "target the $02429C child-handoff group" in symptoms["next_diagnostic"]
    print("Stage-3 remaining loop/idle owner scope: green disk-only reduction")


if __name__ == "__main__":
    main()
