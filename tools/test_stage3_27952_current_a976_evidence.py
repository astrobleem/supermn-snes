#!/usr/bin/env python3
"""Guard the non-promoted a976 $027952 direct-child candidate evidence."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ACTIVE = ROOT / "build/interp.sfc"
CANDIDATE = ROOT / "build/interp-stage3-27952-direct-27aea-current-a976-v1.sfc"
SEMANTIC = ROOT / "build/validate-stage3-27952-direct-27aea-current-a976-isolated-v1.jsonl"
FRESH = ROOT / "build/fresh-candidate-27952-direct-27aea-current-a976-to10000-v1/summary.json"
PROMPT = ROOT / "build/validate-fresh-one-credit-prompt-stage3-27952-current-a976-v1/summary.json"
RATE = ROOT / "build/measure-stage3-27952-direct-27aea-current-a976-safe14743-v1/summary.json"
ACTIVE_SHA256 = "a9765fbfbd2a0863f093ff1bb887cfd422ecde26e3c46bae0afd56bf8b1dac60"
CANDIDATE_SHA256 = "43ee45ee1bb2609173c661f639d9ff95a89d5a1c73c5a08ddaed23d94cb988f2"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    assert digest(ACTIVE) == ACTIVE_SHA256
    assert digest(CANDIDATE) == CANDIDATE_SHA256

    events = [json.loads(line) for line in SEMANTIC.read_text().splitlines()]
    provenance, summary = events[0], events[-1]
    assert provenance["rom_sha256"] == CANDIDATE_SHA256
    assert summary["semantic_cases"] == 12
    assert summary["route_probes"] == 2
    assert summary["green"] == 14 and summary["red"] == 0
    assert summary["total"] == 14 and summary["result"] == "green"

    fresh = json.loads(FRESH.read_text())
    assert fresh["rom_sha256"] == CANDIDATE_SHA256
    assert fresh["result"] == "green" and fresh["mame_end_tick"] == 10000
    assert fresh["player_reference_green"] == 2062
    assert fresh["player_reference_red"] == 0
    assert fresh["death_reference_green"] == 10
    assert fresh["death_reference_red"] == 0
    assert fresh["oracle_divergence_count"] == 0
    assert set(fresh["actions_observed"]) == {0, 1, 2, 3, 4, 5, 7, 8, 9, 10}
    assert fresh["end"]["halt"] == 0 and not fresh["end"]["invalid"]

    prompt = json.loads(PROMPT.read_text())
    assert prompt["rom_sha256"] == CANDIDATE_SHA256 and prompt["result"] == "green"
    assert all(prompt["checks"].values())

    rate = json.loads(RATE.read_text())
    assert rate["rom_sha256"] == CANDIDATE_SHA256 and rate["result"] == "green"
    comparison = rate["comparison"]
    assert comparison["budget_cycles_per_tick"] == 358000
    assert comparison["production_native_on_cycles_per_tick"] == 2375601.71875
    assert comparison["production_meets_budget"] is False
    # The command wall-time guard returned different spans than the active ROM
    # did. Preserve the candidate's liveness/rate miss, not a speed claim.
    assert rate["variants"][0]["chunks"][0]["actual_video_frames"] == 213
    assert rate["variants"][1]["chunks"][0]["actual_video_frames"] == 211
    print("a976 $027952 direct-child candidate evidence: green, non-promoted")


if __name__ == "__main__":
    main()
