#!/usr/bin/env python3
"""Pin the bounded SHAa49e missing-path real-bank owner probe."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT = (
    ROOT
    / "build/playback-watcher-20260809"
    / "vtime-interpreter-only-e00f-gate-restore-scheduler-0818-mvc-fallback-root-native-owner-v1"
    / "watcher-report.json"
)


def main() -> None:
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    symptoms = report["specific_symptoms"]

    assert report["first_divergence"].startswith("NOT_REACHED")
    assert "candidate a49eedc7" in symptoms["scope"]
    assert "exact root $02429C hit" in symptoms["window"]
    for count in (
        "$00:D360 hit=0",
        "miss=$00:D36E=0",
        "$9D:C000=0",
        "$9D:B000=0",
        "$9D:B800=0",
        "prepare/consume=7230/7230",
        "reload/IRQ=0/0",
    ):
        assert count in symptoms["owner_counts"]
    assert "gates $071A/$073A/$0736/$073C=0" in symptoms["state"]
    assert "task/player green" in symptoms["state"]
    assert "does not own the missing $0249xx path" in symptoms["interpretation"]
    assert [report["mismatch_ranges"][str(tick)]["bytes"] for tick in (14744, 14745)] == [
        21,
        21,
    ]
    print("interpreter-only Stage-3 root native owner: green exclusion")


if __name__ == "__main__":
    main()
