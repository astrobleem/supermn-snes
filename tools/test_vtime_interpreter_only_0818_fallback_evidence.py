#!/usr/bin/env python3
"""Pin the bounded Stage-3 `$0818` fallback direct-hook negative."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT = (
    ROOT
    / "build/playback-watcher-20260809"
    / "vtime-interpreter-only-e00f-gate-restore-scheduler-0818-fallback-seam-v1"
    / "watcher-report.json"
)


def main() -> None:
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    symptoms = report["specific_symptoms"]
    proof = symptoms["hook_proof"]

    assert symptoms["classification"] == (
        "valid ROM-migrated forensic comparison; not fresh-boot or acceptance evidence"
    )
    assert symptoms["identity"]["candidate_rom_sha256"] == (
        "7a22b81929a491d3bf0dea96835e35d8e6fe154f13bff79cff4489559296f387"
    )
    assert symptoms["identity"]["state_sha256"] == (
        "5ccbc5096c50e301331bd67e382e54c1e4d2afbdd31fd75405f8f5bb4102bfec"
    )
    zero_gates = {name: 0 for name in ("071a", "073a", "0736", "073c")}
    boundaries = symptoms["boundaries"]
    assert all(row["gates"] == zero_gates for row in boundaries)
    assert all(row["halt"] == 0 for row in boundaries)
    assert [row["task15"]["equal"] for row in boundaries] == [
        True,
        True,
        False,
        False,
    ]

    assert proof["vtime_gateway_99fbb0"]["count"] == 17133
    assert proof["old_paced_helper_99fb00"]["count"] == 0
    assert proof["return_seam_00f59b"]["count"] == 0
    assert proof["nofire_00f5c0"]["count"] == 38797
    assert "gateway > 0 and old paced helper = 0" in proof["critical_result"]
    assert proof["architectural_writes"] == []

    first = report["first_divergence"]
    assert first["kind"] == "authoritative_task15_frame"
    assert first["mame_tick"] == 14746
    assert first["mame"]["pc"] == "000259B0"
    assert first["mame"]["saved_sp"] == "00F001C0"
    assert first["mame"]["sr"] == "2400"
    assert first["snes"]["pc"] == "0002429C"
    assert first["snes"]["saved_sp"] == "00F001C4"
    assert first["snes"]["sr"] == "2404"
    assert [row["bytes"] for row in report["mismatch_ranges"]] == [21, 21, 78, 83]
    assert "leaves the first task-15 split at tick 14746" in first["interpretation"]
    print("interpreter-only Stage-3 $0818 fallback evidence: green negative")


if __name__ == "__main__":
    main()
