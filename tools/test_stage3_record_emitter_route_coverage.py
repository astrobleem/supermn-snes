#!/usr/bin/env python3
"""Regression guard for the retained Stage-3 emitter-route diagnosis."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import validate_stage3_record_emitter_route_coverage as coverage


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="supermn-emitter-coverage-") as temporary:
        output = Path(temporary) / "coverage.json"
        report = coverage.collect()
        output.write_text(json.dumps(report), encoding="utf-8")
        loaded = json.loads(output.read_text(encoding="utf-8"))
    assert loaded["result"] == "red"
    assert loaded["classification"]["cause"] == "native_hle"
    assert all(value == 0 for value in loaded["active"]["native_on_emitter_entry_counts"].values())
    assert all(value > 0 for value in loaded["candidate"]["native_on_emitter_entry_counts"].values())
    assert loaded["candidate"]["bounded_same_state_three_way"]["result"] == "green"
    sustained = loaded["candidate"]["sustained_checkpoint"]
    assert sustained["native_on_cycles_per_tick"] > sustained["budget_cycles_per_tick"]
    fresh = loaded["candidate"]["fresh_power_on"]
    assert fresh["result"] == "red"
    assert not fresh["promotion_eligible"]
    assert fresh["input_tick"] == 2956
    assert fresh["response_tick"] == 2958
    assert fresh["mame_action"] == 1
    assert fresh["native_on_action"] == 0
    remaining = loaded["newly_exposed_remaining_gap"]
    assert remaining["mame_instruction_count"] > 0
    assert remaining["candidate_native_on_entry_count"] == 0
    assert not remaining["sparse_dispatcher_has_exact_case"]
    print("Stage-3 record-emitter route coverage: rejected fresh, rate still red")


if __name__ == "__main__":
    main()
