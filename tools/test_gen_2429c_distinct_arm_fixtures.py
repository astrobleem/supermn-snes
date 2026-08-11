#!/usr/bin/env python3
"""Static guard for the controlled `$02429C` distinct-arm fixture generator."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "tools/gen_2429c_distinct_arm_fixtures.py"


def main() -> int:
    source = SOURCE.read_text(encoding="utf-8")
    for required in (
        'SOURCE_WORK_SHA256 = "161b44cdd0430ef3e8f191a7653cff58a71790776fac73199d09a1716264a175"',
        "active-child-overlap-and-status-counter",
        "active-root-upper-timer-path",
        "active-root-lower-render-and-expiry-path",
        "active-child-and-root-alternate-branches",
        "Mutation(0x3574",
        "Mutation(0x3CB6",
        "Mutation(0x365E + 0x19",
        "Mutation(0x1CCC",
        "Mutation(0x355A, bytes.fromhex(\"0030\")",
        "Mutation(0x365E + 0x18, bytes.fromhex(\"02\")",
        "refusing to overwrite output",
    ):
        assert required in source, f"missing distinct-arm fixture contract: {required}"
    print("$02429C distinct-arm fixture generator regression guard OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
