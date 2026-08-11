#!/usr/bin/env python3
"""Pin the fixed choke gate's bounded logical-PC alignment."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT = (
    ROOT
    / "build/playback-watcher-20260809"
    / "vtime-interpreter-only-e00f-gate-restore-scheduler-0818-mvc-fallback-choke-gate-root-pc-v1"
    / "watcher-report.json"
)


def main() -> None:
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    ranges = report["mismatch_ranges"]
    alignment = ranges["alignment"]
    operations = ranges["non_equal_ops"]
    symptoms = report["specific_symptoms"]

    assert report["first_divergence"].startswith(
        "MAME_SEQUENCE_DELETE_AT_INDEX_223"
    )
    assert alignment == {
        "mame_rows": 11_006,
        "candidate_prepares": 11_010,
        "prefix_drop": 3,
        "aligned_candidate_rows": 11_007,
        "equal_rows": 10_994,
        "wrong_pc_write_kind": 0,
        "same_cycle_write_ambiguity": False,
    }
    assert [item["tag"] for item in operations] == ["delete", "insert", "insert"]
    assert operations[0]["mame_range"] == "[223,235)"
    assert operations[0]["count"] == 12
    assert operations[1]["candidate_range"] == "[266,278)"
    assert operations[1]["count"] == 12
    assert operations[2]["candidate_pcs"] == ["0007E8"]
    assert "No non-equal op remains" in ranges["former_task13_gap"]
    assert "+1 after dropping the three inherited prefix entries" in ranges[
        "prepare_surplus_resolution"
    ]
    assert "does not claim whole-program equality" in symptoms["oracle_scope"]
    print("VTIME interpreter-only choke gate PC sequence: green near-closure")


if __name__ == "__main__":
    main()
