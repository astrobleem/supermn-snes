#!/usr/bin/env python3
"""Guard the real call-site classification for Stage-3 native routes."""

from __future__ import annotations

from pathlib import Path

import validate_stage3_player_bsr as calls


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    assert calls.CALL_KINDS[0x02E42C] == "jsr d16(pc)"
    assert calls.SELECTOR_CALL_SITES == {
        0x0278E6: 0x0278E2,
        0x02F2DE: 0x02F2DA,
    }
    program = (ROOT / "data/superman_m68k.bin").read_bytes()
    # JSR $02E42C(PC) with its four-byte return at $0278E6.
    assert program[0x0278E2:0x0278E6] == bytes.fromhex("4eba6b48")
    assert program[0x0278E6:0x0278E8] == bytes.fromhex("4e75")
    # The Stage-3 task selector has a second genuine JSR caller.
    assert program[0x02F2DA:0x02F2DE] == bytes.fromhex("4ebaf150")
    assert program[0x02F2DE:0x02F2E0] == bytes.fromhex("4e75")
    assert calls.CALL_SITES[0x013282] == 0x0126EA
    assert calls.CALL_KINDS[0x013282] == "bsr.w"
    print("Stage-3 native call-site route classification: green")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
