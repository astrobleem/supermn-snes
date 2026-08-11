#!/usr/bin/env python3
"""Regression guard for patching routed bank-$9F handler entry bytes."""

from __future__ import annotations

from validate_stage3_hot_handlers import BSR_PLAYER_TARGETS
from validate_stage3_hot_handlers import bsr_player_targets
from validate_stage3_hot_handlers import sa1_rom_file_offset
from validate_stage3_player_bsr import CALL_SITES


def main() -> int:
    assert sa1_rom_file_offset(0x928000) == 0x290000
    assert sa1_rom_file_offset(0x948000) == 0x2A0000
    assert sa1_rom_file_offset(0x978000) == 0x2B8000
    assert sa1_rom_file_offset(0x9FE000) == 0x2FE000
    assert sa1_rom_file_offset(0x9FF700) == 0x2FF700
    assert set(CALL_SITES) == set(BSR_PLAYER_TARGETS)
    assert CALL_SITES[0x013282] == 0x0126EA
    assert CALL_SITES[0x013538] == 0x01272A
    assert bsr_player_targets([0x013282, 0x027952]) == [0x013282]
    assert bsr_player_targets(CALL_SITES) == sorted(CALL_SITES)
    for address in (0x9F7FFF, 0xA08000, 0x008000):
        try:
            sa1_rom_file_offset(address)
        except ValueError:
            pass
        else:
            raise AssertionError(f"accepted invalid escape address ${address:06X}")
    print("Stage-3 routed-entry ROM-offset regression: green")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
