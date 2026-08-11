#!/usr/bin/env python3
"""Pin the bounded SHAa49e MVC-fallback logical-PC alignment."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT = (
    ROOT
    / "build/playback-watcher-20260809"
    / "vtime-interpreter-only-e00f-gate-restore-scheduler-0818-mvc-fallback-root-pc-v1"
    / "watcher-report.json"
)


def main() -> None:
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    first = report["first_divergence"]
    ranges = report["mismatch_ranges"]
    symptoms = report["specific_symptoms"]

    assert first["mame_index"] == [223, 235]
    assert first["mame_count"] == 12
    assert first["snes_count"] == 0
    assert "same first 12-row deletion remains" in first["candidate_note"]
    lengths = ranges["sequence_lengths"]
    assert lengths["mame"] == 11006
    assert lengths["snes"] == 7230
    assert lengths["mame_deleted"] == 3792
    assert lengths["snes_inserted"] == 13
    assert len(ranges["non_equal_ops"]) == 14
    assert ranges["largest_delete"]["count"] == 2970
    assert "024998" in ranges["largest_delete"]["dominant_pcs"]
    assert ranges["mvc_00_95EE"]["deleted_rows"] == 0
    assert ranges["mvc_00_95EE"]["prior_recovered_rows"] == 759
    assert ranges["mvc_00_95EE"]["candidate_rows_now_aligned"] == 759
    assert "exactly 7230 prepares" in symptoms["validity"]
    assert "0249 prefix=2096" in symptoms["repeated_signature"]
    assert "candidate selected-family=0" in symptoms["repeated_signature"]
    assert "not proven dispatch ownership" in symptoms["repeated_signature"]
    print("interpreter-only Stage-3 MVC PC sequence: green partial recovery")


if __name__ == "__main__":
    main()
