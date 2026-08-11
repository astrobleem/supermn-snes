#!/usr/bin/env python3
"""Regression guard for the `$02E524` parent-local evidence set."""

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ROM = "91cf499f40a8d296a820f5badc36ca8f0e0bf5e25ede3e9399fb71fae458f34b"


def main() -> None:
    semantic = [json.loads(line) for line in (ROOT / "build/validate-stage3-parent-local-draw-current-a976-isolated-v1.jsonl").read_text().splitlines()][-1]
    trace = json.loads((ROOT / "build/trace-stage3-parent-local-draw-current-a976-safe14743-native-on-v1/trace.json").read_text())
    fresh = json.loads((ROOT / "build/fresh-campaign-stage3-parent-local-draw-current-a976-to3000-native-on-v1/summary.json").read_text())
    rate = json.loads((ROOT / "build/measure-stage3-parent-local-draw-current-a976-safe14743-v1/summary.json").read_text())
    assert semantic["result"] == "green" and semantic["green"] == 14
    assert trace["rom_sha256"] == fresh["rom_sha256"] == rate["rom_sha256"] == ROM
    assert trace["event_counts"]["entry_2e524@9DE190"] == 12
    assert fresh["oracle_divergence_count"] == 0
    assert fresh["failure"]["classification"] == "coverage"
    assert rate["result"] == "red"
    assert rate["comparison"]["production_native_on_cycles_per_tick"] == 1571650.5454545454
    print("Stage-3 parent-local draw evidence: exact/fresh segment green, rate red")


if __name__ == "__main__":
    main()
