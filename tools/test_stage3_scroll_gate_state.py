#!/usr/bin/env python3
"""Static regression for the Stage-3 checkpoint native-gate safety guard."""

from __future__ import annotations

from validate_stage3_scroll_input_probe import NATIVE_ESCAPE_BANKS


def in_escape(pc: int) -> bool:
    return ((pc >> 16) & 0xFF) in NATIVE_ESCAPE_BANKS


def main() -> int:
    assert in_escape(0x92DB8C)
    assert in_escape(0x9F8000)
    assert not in_escape(0x00D16F)
    assert not in_escape(0xC18000)
    print("Stage-3 scroll checkpoint gate-state regression: green")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
