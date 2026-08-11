#!/usr/bin/env python3
"""Pin the asynchronous parent-charge coverage and its measurement limit."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT = (
    ROOT
    / "build/playback-watcher-20260809"
    / "vtime-interpreter-only-e00f-gate-restore-scheduler-0818-mvc-fallback-choke-gate-task15-14746-to14747-parent-charge-v1"
    / "watcher-report.json"
)


def main() -> None:
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    ranges = report["mismatch_ranges"]
    symptoms = report["specific_symptoms"]

    assert report["first_divergence"].startswith(
        "Tick14747 task15 remains PC25876/SR2409"
    )
    assert "no missing gateway/entry/finish call" in report["first_divergence"]
    assert "1214 cycles / 99 collision-loop rows" in ranges["mame_gap"]
    assert ranges["root_to_tick14747"].startswith(
        "3 root F38926/F28900 charge pairs, 3 F38938/F28B00 finish pairs"
    )
    assert "all due counters are zero" in symptoms
    assert "opcode 0x00C2, not ordinal A" in symptoms
    assert "exact table-ordinal mapping and unit deficit are unsupported" in symptoms
    assert "missing-call explanation is not supported" in symptoms
    assert "short-charge explanation remains unresolved" in symptoms
    print("VTIME interpreter-only choke gate: green parent-charge coverage")


if __name__ == "__main__":
    main()
