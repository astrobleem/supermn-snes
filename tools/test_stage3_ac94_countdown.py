#!/usr/bin/env python3
"""Pure regression guard for the retained legacy `$AC` unit mismatch."""

from __future__ import annotations

import validate_stage3_ac94_countdown as countdown


def main() -> None:
    report = countdown.validate(
        countdown.DEFAULT_ROM,
        countdown.DEFAULT_TRACE,
        countdown.DEFAULT_MAME_LEDGER,
    )
    assert report["result"] == "green", report
    assert report["timer_fix_accepted"] is False, report
    assert report["legacy_instruction_charge_triple"] == [3, 2, 5], report
    assert report["exact_mame_leaf_cycles"] == [80, 94], report
    assert report["red_tick_02e40e_transactions"] == 36, report
    print("Stage-3 legacy `$AC` countdown-unit regression: green")


if __name__ == "__main__":
    main()
