#!/usr/bin/env python3
"""Regression for immutable pre-failure input evidence in campaign continuations."""

from __future__ import annotations

import importlib.util
import io
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CAMPAIGN = ROOT / "tools" / "replay_mame_controller_campaign.py"
SPEC = importlib.util.spec_from_file_location("campaign", CAMPAIGN)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot import {CAMPAIGN}")
campaign = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = campaign
SPEC.loader.exec_module(campaign)


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="campaign-pre-failure-") as temp:
        directory = Path(temp)
        states = directory / "states"
        states.mkdir()
        source = states / "pre-input-latest.mss"
        source.write_bytes(b"exact nested pre-input state\n")
        sidecar = Path(f"{source}.sa1-iram.bin")
        sidecar.write_bytes(bytes(range(256)) * 8)
        latest = {
            "mame_tick": 14839,
            "effective_mame_tick": 14839,
            "snes_tick": 14837,
            "buttons_before": 2,
            "buttons_after": 0,
            "state": {"path": str(source), "sha256": campaign.sha256(source)},
        }
        summary = {
            "oracle_divergence_count": 0,
            "oracle_divergence_kinds": {},
            "first_oracle_divergence": None,
            "pre_failure_states": [],
        }
        log = io.StringIO()
        campaign.record_oracle_divergence(
            summary,
            log,
            states,
            latest,
            kind="input_response_compare",
            mame_tick=14841,
            detail={"source_input_tick": 14839},
        )
        retained = summary["pre_failure_states"]
        assert len(retained) == 1
        item = retained[0]
        retained_path = Path(item["path"])
        retained_iram = Path(item["sa1_iram_sidecar"]["path"])
        assert retained_path.name == "pre-failure-input_response_compare-tick-14841.mss"
        assert retained_path.read_bytes() == source.read_bytes()
        assert retained_iram.read_bytes() == sidecar.read_bytes()
        assert item["source_sha256"] == campaign.sha256(source)
        assert item["sha256"] == campaign.sha256(retained_path)
        assert summary["first_oracle_divergence"]["pre_failure_input_state"] == item
        assert '"pre_failure_input_state"' in log.getvalue()
    print("campaign immutable pre-failure input-state regression: green")


if __name__ == "__main__":
    main()
