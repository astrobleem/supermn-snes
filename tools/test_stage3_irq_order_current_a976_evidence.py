#!/usr/bin/env python3
"""Guard the active-ROM Stage-3 IRQ/rate blocker evidence."""

from __future__ import annotations

import json
import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
IRQ_REPORT = ROOT / "build/validate-stage3-irq-order-current-a976-v1.json"
RATE_REPORT = ROOT / "build/measure-stage3-current-a976-safe14743-v1/summary.json"
FRESH_STAGE3_SCREENSHOT = (
    ROOT
    / "build/fresh-campaign-current-a976-to14746-native-on-v1/screenshots/campaign-end.png"
)
ROM_SHA256 = "a9765fbfbd2a0863f093ff1bb887cfd422ecde26e3c46bae0afd56bf8b1dac60"
FRESH_STAGE3_SCREENSHOT_SHA256 = (
    "ced0774869a61e75ec788339206446777d04d4f82c03092bc9a7a7d958855e25"
)


def main() -> int:
    irq = json.loads(IRQ_REPORT.read_text(encoding="utf-8"))
    assert irq["rom_sha256"] == ROM_SHA256
    assert irq["result"] == "red"
    assert irq["classification"] == "hardware-boundary/virtual-IRQ timing"
    assert irq["first_failure_tick"] == 14746
    assert all(irq["configuration_checks"].values())
    rows = {row["mame_tick"]: row for row in irq["ticks"]}
    for tick in (14744, 14745):
        assert all(rows[tick]["checks"].values()), tick
    failure = rows[14746]["checks"]
    assert not failure["task15_frame_mame_native_off"]
    assert not failure["task15_frame_mame_native_on"]
    assert failure["task15_frame_native_off_native_on"]
    assert not failure["game_regions_exact"]
    assert Path(irq["pre_failure_state"]).is_file()

    rate = json.loads(RATE_REPORT.read_text(encoding="utf-8"))
    assert rate["rom_sha256"] == ROM_SHA256
    assert rate["result"] == "green"
    comparison = rate["comparison"]
    assert comparison["production_meets_budget"] is False
    assert comparison["budget_cycles_per_tick"] == 358000
    assert comparison["production_native_on_cycles_per_tick"] == 2471287.6964285714
    assert comparison["all_native_off_cycles_per_tick"] == 11320496.0
    assert FRESH_STAGE3_SCREENSHOT.is_file()
    assert hashlib.sha256(FRESH_STAGE3_SCREENSHOT.read_bytes()).hexdigest() == (
        FRESH_STAGE3_SCREENSHOT_SHA256
    )
    print("active a976 Stage-3 IRQ/rate blocker evidence: retained")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
