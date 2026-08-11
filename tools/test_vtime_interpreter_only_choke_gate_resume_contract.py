#!/usr/bin/env python3
"""Pin the retained pre-migration cross-ROM blocker artifact."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUN = (
    ROOT
    / "build/playback-watcher-20260809"
    / "vtime-interpreter-only-e00f-gate-restore-scheduler-0818-mvc-fallback-choke-gate-resume14743-to14841-v1"
)


def main() -> None:
    command = json.loads(
        (RUN / "resume-command-report.json").read_text(encoding="utf-8")
    )
    support = command["start_at_14743_supported"]
    paths = command["required_state_oracle_input_paths"]
    blocker = command["blocker"]

    assert support["same_rom_authenticated_safe_checkpoint"] is True
    assert support["cross_rom_selected_candidate_d91_from_old_state"] is False
    assert "--resume-mame-tick 14744" in support["required_state_tick_contract"]
    assert paths["selected_candidate_rom_sha256"] == (
        "d91e28e99e1c2c04e8c3d539b69195ce744697ded1cd577981e692c8401f2b28"
    )
    assert blocker["classification"] == "unsupported_cross_rom_campaign_resume"
    assert blocker["exact_cli_error"].startswith(
        "cross-ROM checkpoint continuation is disabled"
    )
    assert "no MAME rerun occurred" in blocker["evidence"]
    assert "ticks 14744..14832" in blocker["partial_capture"]
    assert "not campaign acceptance evidence" in blocker["partial_capture"]
    print("VTIME interpreter-only choke gate: green historical resume blocker")


if __name__ == "__main__":
    main()
