#!/usr/bin/env python3
"""Regression for controller coverage across safe-checkpoint continuations."""

from __future__ import annotations

import importlib.util
import sys
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
    # Button A occurs before the safe checkpoint and Button B after it.  A
    # continuation must retain whole-movie coverage while still exposing its
    # own segment coverage for auditing.
    events = [
        campaign.InputEvent(2, campaign.McpSession.BTN_A, {}),
        campaign.InputEvent(3, 0, {}),
        campaign.InputEvent(7, campaign.McpSession.BTN_B, {}),
    ]
    whole = campaign.campaign_input_coverage(
        events,
        origin_tick=1,
        end_tick=8,
        initial_buttons=0,
        cold_boot_coin_pulses=1,
        cold_boot_start_frames=1,
    )
    child = campaign.campaign_input_coverage(
        events,
        origin_tick=6,
        end_tick=8,
        initial_buttons=0,
        cold_boot_coin_pulses=0,
        cold_boot_start_frames=0,
    )
    if not whole["buttons_seen"]["a"] or not whole["buttons_seen"]["b"]:
        raise AssertionError("whole fresh-movie coverage lost a controller")
    if child["buttons_seen"]["a"] or not child["buttons_seen"]["b"]:
        raise AssertionError("child segment coverage is not independently scoped")
    print("campaign checkpoint controller-coverage regression: green")


if __name__ == "__main__":
    main()
