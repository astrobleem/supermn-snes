#!/usr/bin/env python3
"""Pin the bounded interpreter-only generic-loop accept/decline ledger."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT = (
    ROOT
    / "build/playback-watcher-20260809"
    / "vtime-interpreter-only-e00f-gate-restore-scheduler-0818-fallback-generic-loop-ledger-v1"
    / "watcher-report.json"
)


def main() -> None:
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    symptoms = report["specific_symptoms"]
    families = symptoms["family_results"]

    assert symptoms["classification"] == (
        "ROM-migrated forensic ledger only; not fresh-boot, acceptance, or rate evidence"
    )
    assert symptoms["identity"]["candidate_rom_sha256"] == (
        "7a22b81929a491d3bf0dea96835e35d8e6fe154f13bff79cff4489559296f387"
    )
    assert symptoms["identity"]["state_sha256"] == (
        "5ccbc5096c50e301331bd67e382e54c1e4d2afbdd31fd75405f8f5bb4102bfec"
    )
    assert symptoms["symbol_authentication"] == {
        "authenticated": True,
        "unresolved_labels": [],
    }
    for name in ("memclr", "verify", "memset"):
        assert families[name]["entry_count"] == 19262
        assert families[name]["accepted_call_count"] == 0
        assert families[name]["decline_or_failure_count"] == 19262
    assert families["memset"]["other_path_counts"]["gms_word_99f5d6"] == 1594
    assert families["memset"]["other_path_counts"]["gms_byte_99f5d1"] == 0
    assert families["verify"]["other_path_counts"]["gvf_match_99f4b4"] == 0
    assert symptoms["accepted_mutation_relative_to_irq"]["accepted_calls_total"] == 0
    assert symptoms["controls"] == {
        "all_four_gates_zero": True,
        "gateway_count": 17133,
        "scheduler_count": 64,
        "swin_count": 42,
        "swo_count": 42,
    }

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
    assert "do not add a generic fallback" in symptoms["safest_next_diagnostic"]
    print("interpreter-only Stage-3 generic-loop ledger: green no-accept exclusion")


if __name__ == "__main__":
    main()
