#!/usr/bin/env python3
"""Pin the ROM-migrated origin scope of the `$F01C56` phase offset."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT = (
    ROOT
    / "build/playback-watcher-20260809"
    / "vtime-interpreter-only-e00f-origin-phase-bytes-v1"
    / "watcher-report.json"
)


def main() -> None:
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    first = report["first_divergence"]
    symptoms = report["specific_symptoms"]

    assert first.startswith("ORIGIN_OFFSET_PRESENT")
    assert "tick221 00DA vs 00DB" in first
    assert "tick250 00F7 vs 00F8" in first
    assert "No replay divergence was tested" in first
    assert report["mismatch_ranges"]["tick221"]["mapped_count"] == 28
    assert report["mismatch_ranges"]["tick250"]["mapped_count"] == 20
    assert "ROM-migration carrier" in symptoms
    assert "no architectural writes" in symptoms
    assert "checkpointed ROM-migrated evidence only" in symptoms
    assert "not fresh or acceptance evidence" in symptoms
    print("interpreter-only origin phase bytes: green baseline scope")


if __name__ == "__main__":
    main()
