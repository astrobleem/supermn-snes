#!/usr/bin/env python3
"""Regression for campaign continuation after a player-state mismatch."""

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
    if not campaign.fail_on_player_reference_mismatch(True, False):
        raise AssertionError("strict exact campaign must stop on a mismatch")
    if campaign.fail_on_player_reference_mismatch(True, True):
        raise AssertionError(
            "--continue-oracle-divergences must retain, not abort on, "
            "a strict player mismatch"
        )
    if campaign.fail_on_player_reference_mismatch(False, False):
        raise AssertionError("non-strict campaign must not stop on a mismatch")
    if campaign.fail_on_player_reference_mismatch(False, True):
        raise AssertionError("continuation cannot make a non-strict run fatal")
    for legacy in campaign.RESUME_COMPATIBLE_CAMPAIGN_SCRIPT_SHA256S:
        if not campaign.allowed_resume_identity_mismatch(
            "campaign_script_sha256", "new-runner", legacy
        ):
            raise AssertionError("audited predecessor runner was not admitted")
    if campaign.allowed_resume_identity_mismatch(
        "campaign_script_sha256", "new-runner", "arbitrary-old-runner"
    ):
        raise AssertionError("arbitrary runner drift must remain rejected")
    if campaign.allowed_resume_identity_mismatch("mame_sha256", "new", legacy):
        raise AssertionError("only the runner hash may use compatibility")
    print("campaign oracle-divergence continuation regression: green")


if __name__ == "__main__":
    main()
