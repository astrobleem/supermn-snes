#!/usr/bin/env python3
"""Disk-only regression for exact-checkpoint recovery selection/context."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import recover_campaign_safe_checkpoint as recovery  # noqa: E402


EVENTS = ROOT / (
    "build/playback-watcher-20260809/"
    "vtime-interpreter-only-e00f-gate-restore-resume3001-to6000-v1/"
    "run/events.jsonl"
)
STATE = ROOT / (
    "build/playback-watcher-20260809/"
    "vtime-interpreter-only-e00f-gate-restore-resume3001-to6000-v1/"
    "run/states/checkpoint-04000.mss"
)


def main() -> None:
    source = recovery.source_checkpoint_bundle(EVENTS, STATE, 4000)
    assert source["state"]["boundary_kind"] == (
        "iram_exact_entry_nested_forensic"
    )
    assert source["source_state_sha256"] == (
        "1cb4dfdcaf0a01fcdcef0a0eefbca46a3617581190e8a96fa883ad22b82239e1"
    )
    assert source["context"]["processed_input_transitions"] == 272
    assert source["context"]["player_reference_green"] == 544
    assert source["context"]["first_oracle_divergence"] is None
    assert source["accepted_prefix_lines"] > 1
    print("campaign safe-checkpoint recovery selection: green")


if __name__ == "__main__":
    main()
