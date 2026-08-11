#!/usr/bin/env python3
"""Pin the fixed candidate's residual $1B12 mask-phase seam."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT = (
    ROOT
    / "build/playback-watcher-20260809"
    / "vtime-interpreter-only-e00f-gate-restore-scheduler-0818-mvc-fallback-root-first12-mask-v1"
    / "watcher-report.json"
)


def main() -> None:
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    first = report["first_divergence"]
    ranges = report["mismatch_ranges"]
    symptoms = report["specific_symptoms"]

    assert first["mame_index"] == 223
    assert first["candidate_full_index"] == 226
    assert first["mame_pc"] == "$0008E6"
    assert first["candidate_pc"] == "$0008DA"
    assert "$00030000" in first["cause"]
    assert "$0000C000" in first["cause"]
    assert "each 231 rows" in ranges["complete_calls"]
    assert ranges["terminal"].startswith(
        "After the explicit three-entry prefix drop"
    )
    assert symptoms["active_iterations"] == (
        "MAME ordinals [16,17], candidate [14,15]; inferred masks "
        "$00030000 versus $0000C000; active count remains 2"
    )
    assert "mask-value/branch-phase difference within one call" in symptoms[
        "interpretation"
    ]
    assert "no additional writer is asserted" in symptoms["writer_evidence"]
    assert "No emulator was launched" in symptoms["scope"]
    print("VTIME interpreter-only choke gate first12: green mask phase")


if __name__ == "__main__":
    main()
