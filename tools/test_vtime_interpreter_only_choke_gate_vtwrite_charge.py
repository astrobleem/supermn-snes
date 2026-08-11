#!/usr/bin/env python3
"""Guard the tick-14746 filtered VTIME-write charge ledger."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = (
    ROOT
    / "build/playback-watcher-20260809"
    / "vtime-interpreter-only-e00f-gate-restore-scheduler-0818-mvc-fallback-"
    "choke-gate-task15-14746-boundary-root-vtwrite-v1"
)


def main() -> int:
    report = json.loads((EVIDENCE / "watcher-report.json").read_text(encoding="utf-8"))
    assert set(report) == {
        "first_divergence",
        "mismatch_ranges",
        "specific_symptoms",
        "artifact_filenames",
    }
    first = report["first_divergence"]
    assert first["candidate_boundary_to_root"]["remain_delta_units"] == 61_277
    assert first["mame_boundary_to_root"] == {
        "cycles": 121_398,
        "retired_pre_root_rows": 10_140,
    }
    assert first["endpoint_delta"] == {"units": 578.0, "cycles": 1156.0}
    assert first["first_pc_alignment_gap"]["mame_len"] == 12

    charge = report["mismatch_ranges"]["charge"]
    assert charge["candidate_units"] == 61_277
    assert charge["mame_equivalent_units"] == 60_699.0
    assert charge["non_consume_adjustment_units"] == 186
    contributors = {row["pc"]: row for row in charge["top_contributors"]}
    assert contributors["000FD4"]["delta_units"] == 108.0
    assert contributors["0259C0"]["delta_units"] == 76.0
    assert contributors["0008F0"]["delta_units"] == 58.0

    symptoms = report["specific_symptoms"]
    assert symptoms["counts"] == {
        "events": 138_966,
        "prepares": 10_173,
        "consumes": 10_173,
        "mame_pre_root_rows": 10_140,
        "equal_pc_pairs": 10_100,
    }
    assert symptoms["assertions"]["same_cycle_pc_write_ambiguity"] is False
    assert all(
        value
        for key, value in symptoms["assertions"].items()
        if key != "same_cycle_pc_write_ambiguity"
    )
    for relative in report["artifact_filenames"]:
        path = ROOT / relative if relative.startswith("build/") else EVIDENCE / relative
        assert path.exists(), path
    print("VTIME choke-gate filtered charge ledger: green")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
