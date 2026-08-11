#!/usr/bin/env python3
"""Guard checkpoint continuation when `resume_mame_tick` is an input edge."""

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
    events = [
        campaign.InputEvent(tick=9990, buttons=130, reference={}),
        campaign.InputEvent(tick=9998, buttons=128, reference={}),
        campaign.InputEvent(tick=10003, buttons=0, reference={}),
    ]

    restored = campaign.segment_initial_buttons(
        events, 221, 9998, resumed=True
    )
    if restored != 130:
        raise AssertionError(
            f"resume restored edge input early: expected 130, got {restored}"
        )
    if campaign.segment_initial_buttons(
        events, 221, 9998, resumed=False
    ) != 128:
        raise AssertionError("fresh segment did not retain inclusive input lookup")

    included = [
        event.tick
        for event in events
        if campaign.input_transition_belongs_to_segment(
            event.tick, 9998, resumed=True
        )
    ]
    if included != [9998, 10003]:
        raise AssertionError(f"resume input schedule mismatch: {included}")

    fresh_included = [
        event.tick
        for event in events
        if campaign.input_transition_belongs_to_segment(
            event.tick, 9998, resumed=False
        )
    ]
    if fresh_included != [10003]:
        raise AssertionError(f"fresh input schedule changed: {fresh_included}")

    if campaign.game_update_entries_between_ticks(6501, 6501) != 0:
        raise AssertionError("resume-tick input edge must require zero entries")
    if campaign.game_update_entries_between_ticks(6501, 6502) != 1:
        raise AssertionError("next event tick must advance one entry")
    try:
        campaign.game_update_entries_between_ticks(6502, 6501)
    except ValueError:
        pass
    else:
        raise AssertionError("backward event tick was not rejected")
    if campaign.final_span_is_interpreted([]):
        raise AssertionError("empty resume-edge batch was classified as a span")
    if not campaign.final_span_is_interpreted(
        [{"active_gate": {"mode": "interpreted"}}]
    ):
        raise AssertionError("interpreted completed span was not classified")

    print("campaign resume-at-input-edge regression: green")


if __name__ == "__main__":
    main()
