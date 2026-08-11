#!/usr/bin/env python3
"""Pin the bounded SHAa49e MVC fallback root-fetch evidence."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT = (
    ROOT
    / "build/playback-watcher-20260809"
    / "vtime-interpreter-only-e00f-gate-restore-scheduler-0818-mvc-fallback-root-fetch-v1"
    / "watcher-report.json"
)


def main() -> None:
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    symptoms = report["specific_symptoms"]

    assert report["first_divergence"].startswith("NOT_REACHED")
    assert "candidate ROM a49eedc7" in symptoms["scope"]
    assert "candidate prepare/consume 7230/7230" in symptoms["fetch_counts"]
    assert "prior SHA7a22 6471/6471" in symptoms["fetch_counts"]
    assert "MAME retired pre-root 11006" in symptoms["fetch_counts"]
    assert "recovered +759" in symptoms["fetch_counts"]
    assert "remaining deficit 3776" in symptoms["fetch_counts"]
    assert "remain 69603->27157 units" in symptoms["phase"]
    assert "delta 42446" in symptoms["phase"]
    assert "no reload/IRQ" in symptoms["phase"]
    assert "gates $071A/$073A/$0736/$073C=0" in symptoms["state"]
    assert "halt=0" in symptoms["state"]
    assert "fallback is positive" in symptoms["state"]
    assert [report["mismatch_ranges"][str(tick)]["bytes"] for tick in (14744, 14745)] == [
        21,
        21,
    ]
    print("interpreter-only Stage-3 MVC fallback: green exact +759 recovery")


if __name__ == "__main__":
    main()
