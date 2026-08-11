#!/usr/bin/env python3
"""Pin the bounded SHA7a22 interpreter-only root logical-PC alignment."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT = (
    ROOT
    / "build/playback-watcher-20260809"
    / "vtime-interpreter-only-e00f-gate-restore-scheduler-0818-fallback-root-pc-sequence-v1"
    / "watcher-report.json"
)


def main() -> None:
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    first = report["first_divergence"]
    ranges = report["mismatch_ranges"]
    symptoms = report["specific_symptoms"]

    assert first["classification"].startswith("logical-PC sequence deletion")
    assert first["mame_index"] == [223, 235]
    assert first["mame_cycle"] == [2064289715, 2064289805]
    assert first["mame_pcs"] == [
        "0008E6",
        "0008EA",
        "0008EE",
        "0008F0",
        "0008D6",
        "0008D8",
    ]
    assert first["mame_count"] == 12
    assert first["snes_count"] == 0
    assert ranges["alignment_ops"] == 34
    assert ranges["mame_retired_pre_root"] == 11006
    assert ranges["snes_prepare"] == 6471
    assert ranges["mame_deleted"] == 4551
    assert ranges["snes_inserted"] == 13
    assert ranges["largest_delete"]["count"] == 2970
    assert "024998" in ranges["largest_delete"]["dominant_pcs"]
    assert ranges["mvc_check_00_95EE_candidate"]["deleted_move_l_rows"] == 759
    assert ranges["mvc_check_00_95EE_candidate"]["explains_all"] is False
    assert "exactly 6471" in symptoms["validity"]
    assert "no same-cycle ambiguity" in symptoms["validity"]
    assert "gates 071A=073A=0736=073C=0" in symptoms["gates_and_state"]
    assert "halt=0" in symptoms["gates_and_state"]
    print("interpreter-only Stage-3 root PC sequence: green first-owner alignment")


if __name__ == "__main__":
    main()
