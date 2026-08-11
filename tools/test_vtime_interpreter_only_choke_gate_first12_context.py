#!/usr/bin/env python3
"""Pin the fixed candidate's residual scheduler-loop order seam."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT = (
    ROOT
    / "build/playback-watcher-20260809"
    / "vtime-interpreter-only-e00f-gate-restore-scheduler-0818-mvc-fallback-root-first12-context-v1"
    / "watcher-report.json"
)


def main() -> None:
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    ranges = report["mismatch_ranges"]
    alternate = ranges["alternate_alignment"]
    symptoms = report["specific_symptoms"]

    assert report["first_divergence"].startswith(
        "MAME_PC_0008E6_VS_CANDIDATE_0008DA_AT_INDEX_223"
    )
    assert "repeated twice" in ranges["sequence_matcher_view"]["mame_delete"]
    assert "repeated twice" in ranges["sequence_matcher_view"]["candidate_insert"]
    assert alternate["exact_body_match"] == (
        "MAME [223,235) equals candidate [270,282) exactly"
    )
    assert alternate["preterminal_lengths"] == (
        "excluding terminal $0007E8, both sequences are 11006 PCs and their "
        "PC counters are identical"
    )
    assert alternate["all_rows_equal"] is False
    assert "cyclic scheduler-loop phase/order shift" in symptoms["classification"]
    assert "No monotonic alignment makes all preterminal rows equal" in symptoms[
        "classification"
    ]
    assert "not endpoint bookkeeping alone" in symptoms["endpoint"]
    assert "Disk-only reduction" in symptoms["scope"]
    print("VTIME interpreter-only choke gate first12: green order seam")


if __name__ == "__main__":
    main()
