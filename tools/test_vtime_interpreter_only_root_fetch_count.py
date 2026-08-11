#!/usr/bin/env python3
"""Pin the bounded SHA7a22 interpreter-only root fetch-count discriminator."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT = (
    ROOT
    / "build/playback-watcher-20260809"
    / "vtime-interpreter-only-e00f-gate-restore-scheduler-0818-fallback-root-fetch-count-v1"
    / "watcher-report.json"
)


def main() -> None:
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    symptoms = report["specific_symptoms"]
    identity = symptoms["identity"]
    window = symptoms["window"]
    counts = symptoms["counts"]
    extents = symptoms["event_extents"]

    assert identity["rom_sha256"] == (
        "7a22b81929a491d3bf0dea96835e35d8e6fe154f13bff79cff4489559296f387"
    )
    assert identity["state_sha256"] == (
        "5ccbc5096c50e301331bd67e382e54c1e4d2afbdd31fd75405f8f5bb4102bfec"
    )
    assert identity["nexen_path"].endswith(
        "mcp-combined-20260809-partial-count-publish/Nexen"
    )
    assert report["first_divergence"].startswith("NOT_REACHED")
    assert window["completed_mame_tick"] == 14745
    assert window["boundary_cycle"] == 114201009525
    assert window["root_cycle"] == 114215620217
    assert window["sa1_cycles"] == 14610692
    assert counts["prepare_f28001"] == 6471
    assert counts["consume_f28400"] == 6471
    assert counts["mame_retired_pre_root_intervals"] == 11006
    assert counts["prepare_deficit"] == 4535
    assert counts["prepare_fraction_of_mame"] == 0.587952
    assert counts["classification"] == (
        "materially_fewer_prepares_skipped_or_collapsed_path_still_exists"
    )
    assert extents["reload_in_window"] == 0
    assert extents["irq_in_window"] == 0
    assert "remain 69603 to 34747 units" in symptoms["root_phase"]
    assert "halt=0" in symptoms["root_phase"]
    assert "remain 0" in symptoms["root_phase"]
    assert [report["mismatch_ranges"][str(tick)]["bytes"] for tick in (14744, 14745)] == [
        21,
        21,
    ]
    print("interpreter-only Stage-3 root fetch count: green collapsed-path discriminator")


if __name__ == "__main__":
    main()
