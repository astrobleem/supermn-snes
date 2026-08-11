#!/usr/bin/env python3
"""Pin the bounded interpreter-only root/child native-path exclusion."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT = (
    ROOT
    / "build/playback-watcher-20260809"
    / "vtime-interpreter-only-e00f-gate-restore-scheduler-0818-fallback-root-child-hooks-v1"
    / "watcher-report.json"
)


def main() -> None:
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    symptoms = report["specific_symptoms"]
    proof = symptoms["hook_proof"]

    assert symptoms["classification"] == (
        "ROM-migrated forensic comparison only; not fresh boot, acceptance, or rate evidence"
    )
    assert symptoms["identity"]["candidate_rom_sha256"] == (
        "7a22b81929a491d3bf0dea96835e35d8e6fe154f13bff79cff4489559296f387"
    )
    assert symptoms["identity"]["state_sha256"] == (
        "5ccbc5096c50e301331bd67e382e54c1e4d2afbdd31fd75405f8f5bb4102bfec"
    )
    native = proof["native_root_child_continuation"]
    assert native
    assert all(count == 0 for count in native.values())
    assert proof["irq_entry"]["count"] == 4
    assert proof["architectural_writes"] == []
    assert "All requested native root/child" in proof["native_zero"]

    zero_gates = {name: 0 for name in ("071a", "073a", "0736", "073c")}
    boundaries = symptoms["boundaries"]
    assert all(row["gates"] == zero_gates for row in boundaries)
    assert all(row["halt"] == 0 for row in boundaries)
    assert [row["task15_equal"] for row in boundaries] == [True, True, False, False]

    first = report["first_divergence"]
    assert first["kind"] == "authoritative_task15_frame"
    assert first["mame_tick"] == 14746
    assert first["mame"]["pc"] == "000259B0"
    assert first["snes"]["pc"] == "0002429C"
    assert [row["bytes"] for row in report["mismatch_ranges"]] == [21, 21, 78, 83]
    assert "No native root/child/continuation transition occurred" in (
        symptoms["first_missing_transition"]
    )
    print("interpreter-only Stage-3 root/child hooks: green native-path exclusion")


if __name__ == "__main__":
    main()
