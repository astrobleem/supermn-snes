#!/usr/bin/env python3
"""Pin the bounded interpreter-only remaining-owner inventory."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT = (
    ROOT
    / "build/playback-watcher-20260809"
    / "vtime-interpreter-only-e00f-gate-restore-scheduler-0818-fallback-active-owner-inventory-v1"
    / "watcher-report.json"
)


def main() -> None:
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    symptoms = report["specific_symptoms"]
    active = {
        row["label"]: row["total_count"]
        for row in symptoms["active_uncovered_or_accelerated_owners"]
    }

    assert symptoms["classification"] == (
        "ROM-migrated forensic inventory only; not fresh-boot, acceptance, or rate evidence"
    )
    assert symptoms["identity"]["candidate_rom_sha256"] == (
        "7a22b81929a491d3bf0dea96835e35d8e6fe154f13bff79cff4489559296f387"
    )
    assert symptoms["identity"]["state_sha256"] == (
        "5ccbc5096c50e301331bd67e382e54c1e4d2afbdd31fd75405f8f5bb4102bfec"
    )
    assert active["gm_memclr"] == 19262
    assert active["gm_verify_far"] == 19262
    assert active["gm_memset_far"] == 19262
    assert active["lh_sched"] == 64
    assert active["entry_swo"] == 42
    assert active["entry_swin"] == 42
    assert active["lh_0818_vtime_gateway"] == 17133
    assert active["take_irq"] == 4
    assert "entry_ce4t did not fire" in symptoms["active_result"]
    assert symptoms["unresolved_labels"] == []
    assert len(symptoms["unmigrated_writer_zero_labels"]) == 10
    assert symptoms["control_counts"]["lh_0818_vtime_gateway"] == 17133
    assert symptoms["control_counts"]["take_irq"] == 4
    assert "hook execution only" in symptoms["native_mode"]

    zero_fallback = {"071a": 0, "073a": 0, "0736": 0, "073c": 0}
    for row in symptoms["gate_values"].values():
        assert {name: row[name] for name in zero_fallback} == zero_fallback

    first = report["first_divergence"]
    assert first["mame_tick"] == 14746
    assert first["mame"]["pc"] == "000259B0"
    assert first["snes"]["pc"] == "0002429C"
    assert [row["bytes_different"] for row in report["mismatch_ranges"]] == [
        21,
        21,
        78,
        83,
    ]
    assert "narrow the active generic-loop cluster" in symptoms["safest_next_diagnostic"]
    print("interpreter-only Stage-3 active-owner inventory: green bounded scope")


if __name__ == "__main__":
    main()
