#!/usr/bin/env python3
"""Pin the fixed candidate's salvaged tick-14744..14832 comparison."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUN = (
    ROOT
    / "build/playback-watcher-20260809"
    / "vtime-interpreter-only-e00f-gate-restore-scheduler-0818-mvc-fallback-choke-gate-resume14743-to14841-v1"
)


def main() -> None:
    report = json.loads((RUN / "watcher-report.json").read_text(encoding="utf-8"))
    detail = json.loads(
        (RUN / "partial-comparison-report.json").read_text(encoding="utf-8")
    )
    coverage = detail["coverage"]
    first = detail["first_selected_field_mismatch"]

    assert coverage["candidate_ticks"] == "14744..14832"
    assert coverage["candidate_count"] == 89
    assert coverage["contiguous"] is True
    assert coverage["capture_exit_status"] == 143
    assert first == {
        "mame_tick": 14748,
        "field": "y",
        "candidate": 139,
        "accepted_mame": 136,
        "comparison_basis": "old lineage comparison.mame at the same event tick",
    }
    assert report["first_divergence"].startswith("MAME tick 14748")
    assert report["mismatch_ranges"]["continuous_range_claim"].startswith(
        "not made"
    )
    assert "89/89 contiguous" in report["specific_symptoms"]
    assert "0xD07F at 14744..14745" in report["specific_symptoms"]
    assert "0xF07F at 14746..14832" in report["specific_symptoms"]
    assert "forensic cross-ROM state salvage" in report["specific_symptoms"]
    assert "not a resumable or acceptance playback" in report["specific_symptoms"]
    print("VTIME interpreter-only choke gate: green partial continuation evidence")


if __name__ == "__main__":
    main()
