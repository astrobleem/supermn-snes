#!/usr/bin/env python3
"""Pin the disk-only SHAa49e root branch-context reduction."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT = (
    ROOT
    / "build/playback-watcher-20260809"
    / "vtime-interpreter-only-e00f-gate-restore-scheduler-0818-mvc-fallback-root-branch-context-v1"
    / "watcher-report.json"
)


def main() -> None:
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    ranges = report["mismatch_ranges"]
    symptoms = report["specific_symptoms"]

    assert "MAME indices 223–234" in report["first_divergence"]
    assert "MAME [5274,8244)" in ranges["largest_pc_delete"]
    assert "0007E4" in ranges["largest_pc_delete"]
    assert "000766" in ranges["largest_pc_delete"]
    assert "no candidate PCs occur between anchors" in ranges["largest_pc_delete"]
    assert "0249-prefix PCs 2096" in ranges["largest_signature"]
    assert "candidate selected-family and 0249-prefix totals are both 0" in ranges[
        "largest_signature"
    ]
    first = ranges["first_delete_context"]
    assert first["mame_before"][1] == "0008D8"
    assert first["mame_after"][1] == "0008DA"
    assert len(first["candidate_inserted_pc_order"]) == 12
    work = ranges["work_tick14745"]
    assert work["count"] == 21
    assert len(work["values"]) == 21
    values = {row["address"]: (row["mame"], row["candidate"]) for row in work["values"]}
    assert values["$F1C57"] == ("97", "96")
    assert values["$F1C5A"] == ("C0", "30")
    assert values["$F3FEF"] == ("00", "F0")
    assert "02E8B8 jsr $249C2.l" in symptoms["branch_context"]
    assert "02E8C4 jsr $2498C.l" in symptoms["branch_context"]
    assert "no listed differing byte is a directly named operand" in symptoms[
        "dependency"
    ]
    assert "disk-only reduction" in symptoms["oracle"]
    print("interpreter-only Stage-3 root branch context: green disk reduction")


if __name__ == "__main__":
    main()
