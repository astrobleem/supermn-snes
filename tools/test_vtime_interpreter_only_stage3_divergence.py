#!/usr/bin/env python3
"""Pin the repaired interpreter-only lineage's first Stage-3 discrepancy."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUN = (
    ROOT
    / "build/playback-watcher-20260809"
    / "vtime-interpreter-only-e00f-gate-restore-resume14001-to15000-v1"
)
REPORT = RUN / "watcher-report.json"
SAFE = RUN / "run/states/safe-checkpoint-14743.mss"
SAFE_REPEATS = (
    RUN / "run/states/safe-checkpoint-14743.repeat-1.mss",
    RUN / "run/states/safe-checkpoint-14743.repeat-2.mss",
)
SAFE_SHA256 = "5ccbc5096c50e301331bd67e382e54c1e4d2afbdd31fd75405f8f5bb4102bfec"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    symptom = report["specific_symptoms"]
    first = report["first_divergence"]
    assert symptom["classification"] == (
        "hardware-boundary/timing_or_gameplay_oracle_divergence"
    )
    assert symptom["result"] == "red"
    assert symptom["oracle_divergence_count"] == 1
    assert first == {
        "mame_tick": 14841,
        "kind": "input_response_compare",
        "source_input_tick": 14839,
        "buttons": 0,
        "summary": "oracle divergence at MAME tick 14841; harness stopped normally",
    }
    assert report["mismatch_ranges"] == [
        {
            "mame_tick": 14841,
            "kind": "player_reference",
            "fields": {
                "action": {"mame": 0, "snes": 9},
                "health": {"mame": 4, "snes": 20},
                "x": {"mame": 52, "snes": 68},
                "y": {"mame": 112, "snes": 96},
            },
            "equal_fields": {"x1_ctrl_3601": 16, "x1_ctrl_3603": 33},
        }
    ]
    bounds = symptom["bounds"]
    assert bounds["segment_exact_entries_before_divergence"] == "840/840"
    assert bounds["cumulative_lineage_exact_entries_before_divergence"] == (
        "14611/14611"
    )
    assert symptom["native_off_gate_proof"] == (
        "071A and 073A remained zero through the divergence; "
        "no native gate transition"
    )
    assert sha256(SAFE) == SAFE_SHA256
    assert all(sha256(path) == SAFE_SHA256 for path in SAFE_REPEATS)
    print("interpreter-only Stage-3 divergence regression: green")


if __name__ == "__main__":
    main()
