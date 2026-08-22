#!/usr/bin/env python3
"""Focused unit checks for the transformed Superman HUD placement."""

from compare_transformed_mame_snes_hud_sequence import transformed_x


def main() -> int:
    assert transformed_x(42) == 26
    assert transformed_x(71) == 55
    assert transformed_x(153) == 89
    assert transformed_x(231) == 167
    assert transformed_x(321) == 209
    assert transformed_x(351) == 239
    print("transformed HUD mapping: green")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
