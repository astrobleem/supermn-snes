#!/usr/bin/env python3
"""Static regression for the MAME scheduler-cycle oracle capture contract."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LUA = ROOT / "tools" / "mame-trace" / "capture_scheduler_cycle_phase.lua"
CAPTURE = ROOT / "tools" / "capture_mame_scheduler_cycle_phase.py"


def main() -> int:
    lua = LUA.read_text(encoding="utf-8")
    capture = CAPTURE.read_text(encoding="utf-8")
    for literal in (
        "SCHEDULER_CYCLE_OUT",
        "SCHEDULER_CYCLE_TICK_MIN",
        "SCHEDULER_CYCLE_TICK_MAX",
        "SCHEDULER_CYCLE %X",
        "0x000532",
        "0x0006C4",
        "0x00074C",
        "0x00075C",
        "0x000796",
        "0x000814",
        "0x000818",
        "0x02429C",
        "0x0242BE",
        "0x025110",
        "0x02582E",
        "0x0259B0",
        "0x0259C8",
        'debugger.execution_state = "run"',
    ):
        assert literal in lua, literal
    for literal in (
        '"-debug"',
        '"-debugger"',
        '"none"',
        "read-only program taps",
        "cycles != sorted(cycles)",
        "boundary mismatch",
        "not a SNES comparison, FPS, repair",
    ):
        assert literal in capture, literal
    print("MAME scheduler-cycle capture contract: green")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
