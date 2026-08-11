#!/usr/bin/env python3
"""Regression metadata for the fresh Stage-1 shared-dispatch failure.

This is deliberately an evidence guard, not a replay substitute.  The full
fresh controller reproduction is expensive and retained separately; this test
makes its ROM identity, deterministic pre-input state, and observed mismatch
auditable before anyone treats the rejected experiment as a route fix.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import build_stage3_record_emitter_route_candidate as candidate


ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "build" / "fresh-campaign-stage3-record-emitter-route-current-a976-to2958-prefailure-v1"
PRE_STATE_SHA256 = "80799f44083734c947586833b16fd7399c6336e32ed79a56f9f4521f694d1b05"
PRE_IRAM_SHA256 = "ca40bb349a879023367d2e1853f01d97d8d6bceacd6767f02b093b549a08b37e"


def main() -> None:
    summary = json.loads((RUN / "summary.json").read_text(encoding="utf-8"))
    assert summary["result"] == "red"
    assert summary["rom_sha256"] == candidate.REJECTED_SHA256
    failure = summary["failure"]
    assert failure["reason"] == "organic_player_input_response_diverged"
    assert failure["mame_tick"] == 2958
    assert failure["source_input_tick"] == 2956
    comparison = failure["comparison"]
    assert comparison["result"] == "red"
    assert comparison["mismatches"] == {"action": {"mame": 1, "snes": 0}}
    assert comparison["mame"] == {
        "action": 1,
        "health": 20,
        "x": 226,
        "x1_ctrl_3601": 16,
        "x1_ctrl_3603": 33,
        "y": 127,
    }
    assert comparison["snes"] == {
        "action": 0,
        "health": 20,
        "x": 226,
        "x1_ctrl_3601": 16,
        "x1_ctrl_3603": 33,
        "y": 127,
    }
    pre = failure["pre_failure_input_state"]
    assert pre["boundary_kind"] == "pre_input_apply"
    assert pre["input"]["mame_tick"] == 2956
    assert pre["input"]["buttons_before"] == 128
    assert pre["input"]["buttons_after"] == 2
    assert pre["sha256"] == PRE_STATE_SHA256
    assert pre["sa1_iram_sidecar"]["sha256"] == PRE_IRAM_SHA256
    assert hashlib.sha256((RUN / "states" / "pre-failure-input.mss").read_bytes()).hexdigest() == PRE_STATE_SHA256
    assert hashlib.sha256((RUN / "states" / "pre-failure-input.mss.sa1-iram.bin").read_bytes()).hexdigest() == PRE_IRAM_SHA256
    print("Rejected shared-dispatch fresh Stage-1 failure evidence: green")


if __name__ == "__main__":
    main()
