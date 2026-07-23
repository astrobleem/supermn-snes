#!/usr/bin/env python3
"""Capture all fourteen pre-JSR states in MAME's original $C0BC task."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import validate_c0bc_initializer as cases
import validate_render_helpers as base


CALL_PC = 0x00C132


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--selector", type=int, required=True, choices=range(5))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    case = cases.make_cases()[args.selector]

    rows = [
        {
            "event": "provenance",
            "scope": "MAME $C0BC pre-callback register capture; not fps",
            "mame": "/snap/bin/mame 0.287",
            "selector": args.selector,
            "case": case.name,
            "call_pc": f"{CALL_PC:06X}",
        }
    ]
    print(json.dumps(rows[0], sort_keys=True), flush=True)
    mame = base.MameSession(
        mame="/snap/bin/mame",
        system="superman",
        rompath=str(base.MAME_TRACE / "roms"),
        workdir=str(base.MAME_TRACE),
        state_directory=str(base.MAME_TRACE / "sta"),
        extra_args=["-video", "none", "-sound", "none", "-nothrottle"],
    )
    try:
        mame.launch(boot_wait=25)
        for nth in range(1, 15):
            mame.pause()
            mame.write_block(0xF00000, case.work[:0x4000])
            for name in base.REG_NAMES[:-1]:
                mame.set_reg(name, case.regs[name])
            mame.set_reg("SP", case.regs["A7"])
            mame.set_reg("USP", case.regs["A7"])
            mame.set_reg("SR", case.sr)
            mame.set_reg("PC", cases.ENTRY_PC)
            capture = mame.cmd(
                "capture_at_pc",
                pc=CALL_PC,
                addr=0xF00000,
                len=0x4000,
                nth=nth,
                exp_sp=(case.regs["A7"] - 14) & 0xFFFFFF,
                maxFrames=30,
                timeout=30,
            )
            registers = capture.get("registers")
            if not registers:
                raise RuntimeError(f"MAME did not capture callback {nth}: {capture!r}")
            row = {
                "event": "call",
                "nth": nth,
                **{
                    name: f"{int(registers[name]) & 0xFFFFFFFF:08X}"
                    for name in ("A0", "A1", "A2", "SP", "D0", "D1", "D2", "D6")
                },
            }
            rows.append(row)
            print(json.dumps(row, sort_keys=True), flush=True)
    finally:
        mame.stop()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
