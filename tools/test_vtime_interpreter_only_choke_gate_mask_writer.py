#!/usr/bin/env python3
"""Pin the retained-origin classification of the residual palette mask seam."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT = (
    ROOT
    / "build/playback-watcher-20260809"
    / "vtime-interpreter-only-e00f-gate-restore-scheduler-0818-mvc-fallback-choke-gate-root-first12-mask-writer-v1"
    / "watcher-report.json"
)


def main() -> None:
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    first = report["first_divergence"]
    ranges = report["mismatch_ranges"]
    symptoms = report["specific_symptoms"]

    assert first.startswith("MASK_PRODUCER_PHASE")
    assert "MAME produces/loads $00030000" in first
    assert "candidate produces/loads $0000C000" in first
    assert "pre-existing one-count rolling-origin lag" in first
    assert "F01C56 MAME $3997 vs candidate $3996" in ranges["tick14745"]
    assert "resulting D0/D6 $00030000 vs $0000C000" in ranges["tick14745"]
    assert "intermediate candidate old/new was not directly captured" in ranges[
        "f01b12"
    ]
    assert "same active count" in ranges["sequence"]
    assert "$003B50 calls $8C2" in symptoms["direct_mame"]
    assert "Candidate intermediate F01B12 write remains inference" in symptoms[
        "candidate"
    ]
    assert "current-task-15" in symptoms["ownership"]
    assert symptoms["classification"].startswith("Origin/checkpoint phase seam")
    assert "not retried" not in symptoms["classification"]
    assert "ended hardware-boundary/timing before target" in symptoms[
        "classification"
    ]
    print("VTIME interpreter-only choke gate: green retained mask origin")


if __name__ == "__main__":
    main()
