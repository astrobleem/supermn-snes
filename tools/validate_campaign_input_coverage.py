#!/usr/bin/env python3
"""Regression for pre-game Select/Start controller coverage accounting."""

from __future__ import annotations

from replay_mame_controller_campaign import (
    BUTTON_NAMES,
    InputEvent,
    campaign_input_coverage,
)


def main() -> None:
    bits = {name: bit for bit, name in BUTTON_NAMES}
    events = [
        InputEvent(11, bits["right"], {}),
        InputEvent(12, 0x0000, {}),
        InputEvent(13, bits["left"], {}),
    ]
    coverage = campaign_input_coverage(
        events,
        10,
        20,
        0,
        cold_boot_coin_pulses=8,
        cold_boot_start_frames=61,
    )
    assert not coverage["gameplay_buttons_seen"]["select"]
    assert not coverage["gameplay_buttons_seen"]["start"]
    assert coverage["cold_boot_buttons_seen"]["select"]
    assert coverage["cold_boot_buttons_seen"]["start"]
    assert coverage["buttons_seen"]["select"]
    assert coverage["buttons_seen"]["start"]
    assert coverage["buttons_seen"]["right"]
    assert coverage["buttons_seen"]["left"]

    no_boot = campaign_input_coverage(
        events,
        10,
        20,
        0,
        cold_boot_coin_pulses=0,
        cold_boot_start_frames=0,
    )
    assert not no_boot["buttons_seen"]["select"]
    assert not no_boot["buttons_seen"]["start"]
    print("campaign pre-game controller coverage regression: PASS")


if __name__ == "__main__":
    main()
