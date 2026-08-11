#!/usr/bin/env python3
"""Pure regression guard for the retained Stage-3 variable-work trigger."""

from __future__ import annotations

import validate_stage3_ac94_variable_work as trigger


def main() -> None:
    report = trigger.validate(trigger.DEFAULT_ROM, trigger.DEFAULT_TRACE)
    assert report["result"] == "green", report
    assert report["timer_fix_accepted"] is False, report
    assert report["helper_counts_by_interval_end_tick"] == {
        14744: 140,
        14745: 140,
        14746: 176,
    }, report
    assert report["red_only_02e40e_blocks"] == {
        "ac94_D548": [0, 0, 12],
        "ac94_D567": [0, 0, 12],
        "ac94_D586": [0, 0, 12],
    }, report
    print("Stage-3 $02E40E variable-work trigger regression: green")


if __name__ == "__main__":
    main()
