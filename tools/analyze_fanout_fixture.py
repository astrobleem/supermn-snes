#!/usr/bin/env python3
"""Describe an organic fan-out fixture's MAME entry-to-exit state delta.

This is a read-only reverse-engineering helper for the retained fixtures used
by ``validate_fanout_native.py``.  It runs exactly one bounded span in MAME,
prints the architectural register delta, and coalesces changed work-RAM bytes
into short ranges.  The output is analysis evidence, not a validator or an FPS
measurement.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import validate_d96_hle as base
import validate_fanout_native as fan


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FIXTURES = (
    ROOT
    / "build/playability-20260720/fanout-native-differential-v1/results-fixtures"
)


def changed_ranges(before: bytes, after: bytes) -> list[dict[str, object]]:
    changed = [index for index, pair in enumerate(zip(before, after)) if pair[0] != pair[1]]
    if not changed:
        return []

    ranges: list[tuple[int, int]] = []
    start = previous = changed[0]
    for index in changed[1:]:
        if index != previous + 1:
            ranges.append((start, previous + 1))
            start = index
        previous = index
    ranges.append((start, previous + 1))

    return [
        {
            "start": f"F0{start:04X}",
            "end_exclusive": f"F0{end:04X}",
            "size": end - start,
            "before": before[start:end].hex(),
            "after": after[start:end].hex(),
        }
        for start, end in ranges
    ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("case", help="fixture case name, for example task-1e71e")
    parser.add_argument("--fixture-dir", type=Path, default=DEFAULT_FIXTURES)
    parser.add_argument("--output-work", type=Path)
    args = parser.parse_args()

    cases = fan.load_cases(args.fixture_dir)
    matches = [case for case in cases if case.name == args.case]
    if len(matches) != 1:
        parser.error(
            f"expected one case named {args.case!r}; available: "
            + ", ".join(case.name for case in cases)
        )
    case = matches[0]

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
        installed = int(mame.exec_lua(fan.MAME_IRQ_ISOLATION_LUA))
        if installed != 2:
            raise RuntimeError(f"installed {installed} MAME SR taps, expected 2")
        result = fan.mame_result(mame, case)
    finally:
        mame.stop()

    if args.output_work is not None:
        args.output_work.parent.mkdir(parents=True, exist_ok=True)
        args.output_work.write_bytes(result.work)

    before_regs = case.regs
    register_delta = {
        name: {
            "before": f"{before_regs[name] & 0xFFFFFFFF:08X}",
            "after": f"{result.regs[name] & 0xFFFFFFFF:08X}",
        }
        for name in base.REG_NAMES
        if before_regs[name] != result.regs[name]
    }
    summary = {
        "case": case.name,
        "entry_pc": f"{case.span.entry_pc:06X}",
        "exit_pc": f"{case.span.exit_pc:06X}",
        "entry_sr": f"{case.sr & 0xFFFF:04X}",
        "exit_sr": f"{result.sr & 0xFFFF:04X}",
        "register_delta": register_delta,
        "changed_byte_count": sum(
            left != right
            for left, right in zip(case.work[: fan.MAPPED_WORK_SIZE], result.work)
        ),
        "changed_ranges": changed_ranges(
            case.work[: fan.MAPPED_WORK_SIZE], result.work
        ),
        "scope": "bounded MAME oracle delta; not FPS evidence",
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
