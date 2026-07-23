#!/usr/bin/env python3
"""Function-local MAME/Nexen differential for table-dispatched $00111A.

MAME executes the original MC68000 routine with a real return at A7.  Nexen
enters the production $95:A700 table-convention body with an equivalent native
sentinel at A7 and returns through op_rts/ors_pre.  The comparison covers every
D/A register, CCR X/N/Z/V/C, and the complete mapped 16 KiB work-RAM window;
only the deliberately different four-byte synthetic return value is excluded.

This is bounded semantic and local-cycle evidence, not an FPS measurement.
The production xlat-route firing is proven separately by profile_tick_ring.py.
"""

from __future__ import annotations

import argparse
import json
import random
import time
from pathlib import Path

import validate_d96_hle as base


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ROM = ROOT / "build" / "interp.sfc"
ENTRY_PC = 0x00111A
ENTRY_NATIVE = 0x95A700
RETURN_PC = 0x000400
ENTRY_SP = 0xF03D00
SOURCE = 0xF01000

# Reuse the mature table-convention oracle plumbing while selecting this
# function's addresses.  The helpers resolve these module globals at runtime.
base.ENTRY_PC = ENTRY_PC
base.ENTRY_NATIVE = ENTRY_NATIVE
base.RETURN_PC = RETURN_PC
base.ENTRY_SP = ENTRY_SP


def put16(work: bytearray, address: int, value: int) -> None:
    offset = address & 0xFFFF
    work[offset : offset + 2] = base.be16(value)


def put32(work: bytearray, address: int, value: int) -> None:
    offset = address & 0xFFFF
    work[offset : offset + 4] = base.be32(value)


def build_case(
    name: str,
    seed: int,
    *,
    outer_count: int,
    inner_count: int,
    source_words: list[int],
    output_offset: int,
    x_bias: int,
    initial_y: int,
    capacity_minus_one: int,
    x_flag: int,
    source_address: int = SOURCE,
) -> base.Case:
    expected = (outer_count + 1) * (inner_count + 1)
    if len(source_words) != expected:
        raise ValueError(f"{name}: expected {expected} source words")

    rng = random.Random(seed)
    work = bytearray(rng.randrange(256) for _ in range(0x10000))
    regs = {reg: rng.randrange(1 << 32) for reg in base.REG_NAMES}
    regs.update({"A5": 0x00F00000, "A7": ENTRY_SP})
    sr = 0x2700 | rng.randrange(0x10) | ((x_flag & 1) << 4)

    source = base.be16(outer_count) + base.be16(inner_count)
    source += b"".join(base.be16(word) for word in source_words)
    if (source_address >> 16) == 0xF0:
        source_offset = source_address & 0xFFFF
        work[source_offset : source_offset + len(source)] = source
    elif not 0 <= source_address < 0x80000:
        raise ValueError(f"{name}: unsupported source ${source_address:06X}")

    # After LINK A6,#0, these are $8/$C/$E/$10/$14(A6).  The word at
    # entry A7+6 is intentionally unused by the original routine.
    put32(work, ENTRY_SP, RETURN_PC)
    put16(work, ENTRY_SP + 4, output_offset)
    put16(work, ENTRY_SP + 6, rng.randrange(1 << 16))
    put16(work, ENTRY_SP + 8, x_bias)
    put16(work, ENTRY_SP + 10, initial_y)
    put32(work, ENTRY_SP + 12, source_address)
    put16(work, ENTRY_SP + 16, capacity_minus_one)
    return base.Case(name, regs, sr, bytes(work))


def make_cases() -> list[base.Case]:
    return [
        build_case(
            "zero-skip-and-fill",
            0x111A00,
            outer_count=0,
            inner_count=2,
            source_words=[0x0001, 0x0000, 0x0345],
            output_offset=0,
            x_bias=0,
            initial_y=0x0020,
            capacity_minus_one=4,
            x_flag=0,
        ),
        build_case(
            "two-rows-capacity-exhausted",
            0x111A01,
            outer_count=1,
            inner_count=1,
            source_words=[0x0001, 0x0002, 0x0003, 0x0004],
            output_offset=4,
            x_bias=0x0010,
            initial_y=0x0040,
            capacity_minus_one=1,
            x_flag=1,
        ),
        build_case(
            "all-zero-fill-only",
            0x111A02,
            outer_count=0,
            inner_count=3,
            source_words=[0, 0, 0, 0],
            output_offset=8,
            x_bias=0x00F0,
            initial_y=0x0170,
            capacity_minus_one=2,
            x_flag=1,
        ),
        build_case(
            "negative-capacity-immediate-exit",
            0x111A03,
            outer_count=0,
            inner_count=0,
            source_words=[0x7FFF],
            output_offset=12,
            x_bias=0x00EA,
            initial_y=0xFFF0,
            capacity_minus_one=0xFFFF,
            x_flag=0,
        ),
        build_case(
            "signed-clamps-and-y-clipping",
            0x111A04,
            outer_count=1,
            inner_count=2,
            source_words=[1, 2, 3, 4, 5, 6],
            output_offset=16,
            x_bias=0x0200,
            initial_y=0x0180,
            capacity_minus_one=5,
            x_flag=1,
        ),
        # Exercise the production-hot ROM source path.  $002B04 begins with
        # outer=0, inner=2, followed by these three words in the arcade image.
        build_case(
            "rom-source-fast-path",
            0x111A05,
            outer_count=0,
            inner_count=2,
            source_words=[0x13FC, 0x0002, 0x0090],
            output_offset=20,
            x_bias=0x0018,
            initial_y=0x0040,
            capacity_minus_one=3,
            x_flag=0,
            source_address=0x002B04,
        ),
        # Production-hot immutable shape classes.  The source_words argument
        # only supplies the expected dimensions for ROM-backed fixtures; MAME
        # and Nexen both read the actual arcade image at source_address.
        build_case(
            "rom-shape-337f0-hot",
            0x111A06,
            outer_count=4,
            inner_count=4,
            source_words=[0] * 25,
            output_offset=0x0100,
            x_bias=0x002C,
            initial_y=0x0086,
            capacity_minus_one=0x0011,
            x_flag=1,
            source_address=0x0337F0,
        ),
        build_case(
            "rom-shape-33c0a-hot",
            0x111A07,
            outer_count=4,
            inner_count=4,
            source_words=[0] * 25,
            output_offset=0x0140,
            x_bias=0x0070,
            initial_y=0x00AE,
            capacity_minus_one=0x0011,
            x_flag=0,
            source_address=0x033C0A,
        ),
        build_case(
            "rom-shape-33c76-live",
            0x111A10,
            outer_count=4,
            inner_count=4,
            source_words=[0] * 25,
            output_offset=0x0248,
            x_bias=0x005F,
            initial_y=0x010E,
            capacity_minus_one=0x0011,
            x_flag=0,
            source_address=0x033C76,
        ),
        build_case(
            "rom-shape-33cac-live",
            0x111A11,
            outer_count=4,
            inner_count=4,
            source_words=[0] * 25,
            output_offset=0x0248,
            x_bias=0x005F,
            initial_y=0x010E,
            capacity_minus_one=0x0011,
            x_flag=1,
            source_address=0x033CAC,
        ),
        # Exact organic Right+B call classes captured atomically at $95:A700
        # from the production ROM.  The $033C0A case exercises the narrow
        # negative-X/all-hidden specialization; $0337F0 proves the companion
        # live stream and its real output offset.
        build_case(
            "rom-shape-33c0a-live-negative-x",
            0x111A0A,
            outer_count=4,
            inner_count=4,
            source_words=[0] * 25,
            output_offset=0x0204,
            x_bias=0xFFA1,
            initial_y=0x00FA,
            capacity_minus_one=0x0011,
            x_flag=0,
            source_address=0x033C0A,
        ),
        build_case(
            "rom-shape-33c40-live",
            0x111A15,
            outer_count=4,
            inner_count=4,
            source_words=[0] * 25,
            output_offset=0x0248,
            x_bias=0x005F,
            initial_y=0x010E,
            capacity_minus_one=0x0011,
            x_flag=0,
            source_address=0x033C40,
        ),
        build_case(
            "rom-shape-337f0-live",
            0x111A0B,
            outer_count=4,
            inner_count=4,
            source_words=[0] * 25,
            output_offset=0x0248,
            x_bias=0x002C,
            initial_y=0x00FD,
            capacity_minus_one=0x0011,
            x_flag=1,
            source_address=0x0337F0,
        ),
        build_case(
            "rom-shape-337f0-live-hidden-y",
            0x111A12,
            outer_count=4,
            inner_count=4,
            source_words=[0] * 25,
            output_offset=0x026C,
            x_bias=0xFF82,
            initial_y=0x0183,
            capacity_minus_one=0x0011,
            x_flag=0,
            source_address=0x0337F0,
        ),
        build_case(
            "rom-shape-344c6-hidden-y-upper-edge",
            0x111A13,
            outer_count=4,
            inner_count=5,
            source_words=[0] * 30,
            output_offset=0x01C0,
            x_bias=0x0040,
            initial_y=0xFFA0,
            capacity_minus_one=0x000F,
            x_flag=1,
            source_address=0x0344C6,
        ),
        build_case(
            "rom-shape-344c6-hidden-y-wrap-fallback",
            0x111A14,
            outer_count=4,
            inner_count=5,
            source_words=[0] * 30,
            output_offset=0x01C0,
            x_bias=0x0040,
            initial_y=0xFFA1,
            capacity_minus_one=0x000F,
            x_flag=0,
            source_address=0x0344C6,
        ),
        build_case(
            "rom-shape-33c0a-hidden-x-lower-edge",
            0x111A0C,
            outer_count=4,
            inner_count=4,
            source_words=[0] * 25,
            output_offset=0x0204,
            x_bias=0x8000,
            initial_y=0x0102,
            capacity_minus_one=0x0011,
            x_flag=1,
            source_address=0x033C0A,
        ),
        build_case(
            "rom-shape-33c0a-hidden-x-upper-edge",
            0x111A0D,
            outer_count=4,
            inner_count=4,
            source_words=[0] * 25,
            output_offset=0x0204,
            x_bias=0xFFB0,
            initial_y=0x0112,
            capacity_minus_one=0x0011,
            x_flag=0,
            source_address=0x033C0A,
        ),
        build_case(
            "rom-shape-33c0a-visible-boundary-fallback",
            0x111A0E,
            outer_count=4,
            inner_count=4,
            source_words=[0] * 25,
            output_offset=0x0204,
            x_bias=0xFFB1,
            initial_y=0x0112,
            capacity_minus_one=0x0011,
            x_flag=1,
            source_address=0x033C0A,
        ),
        build_case(
            "rom-shape-344c6-hot",
            0x111A08,
            outer_count=4,
            inner_count=5,
            source_words=[0] * 30,
            output_offset=0x0180,
            x_bias=0x0029,
            initial_y=0x00AF,
            capacity_minus_one=0x000F,
            x_flag=1,
            source_address=0x0344C6,
        ),
        build_case(
            "rom-shape-344c6-hot-guard-edge",
            0x111A09,
            outer_count=4,
            inner_count=5,
            source_words=[0] * 30,
            output_offset=0x01C0,
            x_bias=0x00AA,
            initial_y=0x013F,
            capacity_minus_one=0x000F,
            x_flag=0,
            source_address=0x0344C6,
        ),
    ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    parser.add_argument("--nexen", type=Path, default=base.DEFAULT_NEXEN)
    parser.add_argument("--nat", type=Path, default=base.DEFAULT_NAT)
    parser.add_argument("--port", type=int, default=7568)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    for path in (args.rom, args.nexen, args.nat):
        if not path.is_file():
            parser.error(f"missing required input: {path}")

    cases = make_cases()
    events: list[dict] = []
    provenance = {
        "event": "provenance",
        "scope": (
            "function-local $00111A table-convention MAME/Nexen "
            "differential; mapped 16 KiB work RAM; not fps"
        ),
        "mame": "/snap/bin/mame 0.287",
        "nexen": str(args.nexen.resolve()),
        "nexen_sha256": base.sha256(args.nexen),
        "rom": str(args.rom.resolve()),
        "rom_sha256": base.sha256(args.rom),
        "nat": str(args.nat.resolve()),
        "nat_sha256": base.sha256(args.nat),
        "entry_pc": f"{ENTRY_PC:06X}",
        "entry_native": f"{ENTRY_NATIVE:06X}",
        "cases": len(cases),
        "time": time.time(),
    }
    events.append(provenance)
    print(json.dumps(provenance, sort_keys=True), flush=True)

    arcade: dict[str, base.Result] = {}
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
        for case in cases:
            arcade[case.name] = base.mame_result(mame, case)
            print(json.dumps({"event": "mame_case", "case": case.name}), flush=True)
    finally:
        mame.stop()

    stderr_log = (
        args.output.with_suffix(".nexen.stderr.log")
        if args.output
        else ROOT / "build" / "111a-table-nexen.stderr.log"
    )
    stderr_log.parent.mkdir(parents=True, exist_ok=True)
    with base.McpSession(
        rom=str(args.rom),
        mesen=str(args.nexen),
        cwd=ROOT,
        port=args.port,
        boot_wait=8.0,
        socket_timeout=120.0,
        stderr_log=stderr_log,
    ) as nexen:
        for case in cases:
            console = base.nexen_result(nexen, args.nat, case)
            event = {"event": "case", **base.compare(case, arcade[case.name], console)}
            events.append(event)
            print(json.dumps(event, sort_keys=True), flush=True)

    green = sum(event.get("result") == "green" for event in events)
    summary = {
        "event": "summary",
        "green": green,
        "red": len(cases) - green,
        "total": len(cases),
        "result": "green" if green == len(cases) else "red",
        "time": time.time(),
    }
    events.append(summary)
    print(json.dumps(summary, sort_keys=True), flush=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            "".join(json.dumps(event, sort_keys=True) + "\n" for event in events)
        )
    return 0 if green == len(cases) else 1


if __name__ == "__main__":
    raise SystemExit(main())
