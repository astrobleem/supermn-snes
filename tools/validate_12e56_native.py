#!/usr/bin/env python3
"""Exact three-way regression for the $012E56 movement-response consumer.

The fixture starts from the retained organic Stage-1 work/register state used
for the $00D18A wall rollback, then replaces only the two response records and
the directly consumed player fields.  Cases deliberately poison the preserved
high byte of D0/D1 so MOVE.B-fed branches, NEG.B, CMP.B, and the later sign
tests cannot accidentally pass as word operations.

Each case executes the original MC68000 function in MAME, the complete
interpreter path in Nexen, and the bank-$97 native body (including its native
$012AF6 call).  It compares all D/A registers, CCR/X/mask, mapped work RAM,
and live/popped stack bytes at the common RTS return seam.  Prepared Nexen
states and complete input blobs are retained before execution.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import validate_d18a_native as wall


base = wall.base
shared = wall.shared
ROOT = wall.ROOT
DEFAULT_ROM = ROOT / "build/interp.sfc"
DEFAULT_TRACE = wall.DEFAULT_TRACE
DEFAULT_WORK = wall.DEFAULT_WORK
ENTRY_PC = 0x012E56
ENTRY_NATIVE = 0x97A000
INEXT = wall.INEXT
RETURN_PC = wall.RETURN_PC
OP_ILLEGAL = wall.OP_ILLEGAL
MAPPED_WORK_SIZE = wall.MAPPED_WORK_SIZE
FULL_WORK_SIZE = wall.FULL_WORK_SIZE


def put_be32(work: bytearray, address: int, value: int) -> None:
    offset = address & 0xFFFF
    work[offset : offset + 4] = (value & 0xFFFFFFFF).to_bytes(4, "big")


def make_cases(seed: wall.Case) -> list[wall.Case]:
    a6 = seed.regs["A6"] & 0xFFFFFF
    if (a6 >> 16) != 0xF0:
        raise RuntimeError(f"fixture A6 is outside work RAM: ${a6:06X}")
    input_record = 0xF02000
    output_record = 0xF02100
    a4_record = 0xF02200

    def case(
        name: str,
        *,
        command: int,
        x_byte: int,
        y_byte: int,
        d0_word: int,
        d1_word: int,
        counter: int = 0x1234,
        sr: int | None = None,
    ) -> wall.Case:
        work = bytearray(seed.work)
        put_be32(work, a6 - 0x28, input_record)
        put_be32(work, a6 - 0x34, output_record)
        work[(input_record + 0x0C) & 0xFFFF] = x_byte & 0xFF
        work[(input_record + 0x0D) & 0xFFFF] = y_byte & 0xFF
        wall.put_be16(work, input_record + 0x0E, command)
        work[(output_record + 0x0C) & 0xFFFF] = 0x5A
        work[(output_record + 0x0D) & 0xFFFF] = 0xA5
        wall.put_be16(work, output_record + 0x0E, 0x55AA)
        wall.put_be16(work, a6 - 0x70, counter)
        work[(a6 - 0x3F) & 0xFFFF] = 0xFF
        wall.put_be16(work, a6 - 0x40, 0x000F)
        wall.put_be16(work, a6 - 0x22, 0x0080)
        wall.put_be16(work, a6 - 0x1E, 0x00E0)
        wall.put_be16(work, a6 - 0x60, 0x00E0)
        wall.put_be16(work, a6 - 0x5C, 0x0080)
        work[a4_record & 0xFFFF] = 0xFF

        regs = dict(seed.regs)
        regs["A4"] = a4_record
        regs["D0"] = (regs["D0"] & 0xFFFF0000) | (d0_word & 0xFFFF)
        regs["D1"] = (regs["D1"] & 0xFFFF0000) | (d1_word & 0xFFFF)
        return wall.Case(
            name,
            regs,
            seed.sr if sr is None else sr,
            bytes(work),
        )

    return [
        case(
            "zero-command-dirty-ccr",
            command=0x0000,
            x_byte=0x80,
            y_byte=0x80,
            d0_word=0x7F55,
            d1_word=0x80AA,
            sr=(seed.sr & ~base.CCR_MASK) | 0x1B,
        ),
        case(
            "zero-command-x1",
            command=0x0000,
            x_byte=0x80,
            y_byte=0x80,
            d0_word=0x7F55,
            d1_word=0x80AA,
            sr=seed.sr | 0x10,
        ),
        case(
            "addq-no-carry",
            command=0x009D,
            x_byte=0x80,
            y_byte=0x80,
            d0_word=0x7F55,
            d1_word=0x80AA,
            counter=0x1234,
        ),
        case(
            "addq-carry",
            command=0x009D,
            x_byte=0x80,
            y_byte=0x80,
            d0_word=0x7F55,
            d1_word=0x80AA,
            counter=0xFFFF,
        ),
        case(
            "addq-overflow",
            command=0xFFFF,
            x_byte=0x80,
            y_byte=0x80,
            d0_word=0x7F55,
            d1_word=0x80AA,
            counter=0x7FFF,
            sr=(seed.sr & ~base.CCR_MASK) | 0x10,
        ),
        case(
            "special-809d-dirty-ccr",
            command=0x809D,
            x_byte=0x00,
            y_byte=0x00,
            d0_word=0x7F55,
            d1_word=0x80AA,
            sr=(seed.sr & ~base.CCR_MASK) | 0x1B,
        ),
        case(
            "x-negative-y-positive-poison",
            command=0x009E,
            x_byte=0xFE,
            y_byte=0x01,
            d0_word=0x7F55,
            d1_word=0x80AA,
        ),
        case(
            "x-positive-y-negative-poison",
            command=0x009E,
            x_byte=0x01,
            y_byte=0xFE,
            d0_word=0x8055,
            d1_word=0x7FAA,
        ),
        case(
            "x-zero-y-negative-poison",
            command=0x009E,
            x_byte=0x00,
            y_byte=0x80,
            d0_word=0x7F55,
            d1_word=0x7FAA,
        ),
        case(
            "clean-x-negative-sign",
            command=0x009E,
            x_byte=0xFD,
            y_byte=0x00,
            d0_word=0x0000,
            d1_word=0x0000,
            sr=(seed.sr & ~base.CCR_MASK) | 0x10,
        ),
        case(
            "clean-y-negative-sign",
            command=0x009E,
            x_byte=0x00,
            y_byte=0xFD,
            d0_word=0x0000,
            d1_word=0x0000,
            sr=seed.sr & ~base.CCR_MASK,
        ),
        case(
            "common-axis-flip",
            command=0x009E,
            x_byte=0xFF,
            y_byte=0xFD,
            d0_word=0x0000,
            d1_word=0x0000,
        ),
        case(
            "cmp-byte-dirty",
            command=0x009E,
            x_byte=0x03,
            y_byte=0x01,
            d0_word=0x0100,
            d1_word=0x0200,
        ),
        case(
            "neg-x-byte-width",
            command=0x009E,
            x_byte=0xFF,
            y_byte=0x02,
            d0_word=0x8000,
            d1_word=0x0000,
        ),
        case(
            "neg-y-byte-width",
            command=0x009E,
            x_byte=0x02,
            y_byte=0xFF,
            d0_word=0x0000,
            d1_word=0x8000,
        ),
        case(
            "x-minus1-y-plus1-equal",
            command=0x009E,
            x_byte=0xFF,
            y_byte=0x01,
            d0_word=0x8055,
            d1_word=0x7FAA,
        ),
    ]


def retain_case(case: wall.Case, directory: Path) -> dict:
    directory.mkdir(parents=True, exist_ok=True)
    work_path = directory / f"{case.name}.work.bin"
    json_path = directory / f"{case.name}.json"
    work_path.write_bytes(case.work)
    payload = {
        "name": case.name,
        "entry_pc": f"{ENTRY_PC:06X}",
        "entry_native": f"{ENTRY_NATIVE:06X}",
        "return_pc": f"{RETURN_PC:06X}",
        "regs": {name: case.regs[name] for name in base.REG_NAMES},
        "sr": case.sr,
        "work": str(work_path.resolve()),
        "work_sha256": wall.sha256(work_path),
    }
    json_path.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n")
    return {
        "json": str(json_path.resolve()),
        "json_sha256": wall.sha256(json_path),
        "work": str(work_path.resolve()),
        "work_sha256": wall.sha256(work_path),
    }


def mame_result(session: base.MameSession, case: wall.Case) -> base.Result:
    entry_sp = case.regs["A7"] & 0xFFFFFF
    session.pause()
    session.write_block(0xF00000, case.work[:MAPPED_WORK_SIZE])
    for name in base.REG_NAMES[:-1]:
        session.set_reg(name, case.regs[name])
    session.set_reg("SR", case.sr | 0x0700)
    session.set_reg("USP", entry_sp)
    session.set_reg("SP", entry_sp)
    session.set_reg("PC", ENTRY_PC)
    captured = session.cmd(
        "capture_at_pc",
        pc=RETURN_PC,
        addr=0xF00000,
        len=MAPPED_WORK_SIZE,
        nth=1,
        exp_sp=(entry_sp + 4) & 0xFFFFFF,
        maxFrames=60,
        timeout=60,
    )
    if not captured.get("registers"):
        raise RuntimeError(f"MAME did not return for {case.name}: {captured!r}")
    raw = captured["registers"]
    regs = {name: raw[name] & 0xFFFFFFFF for name in base.REG_NAMES[:-1]}
    regs["A7"] = raw["SP"] & 0xFFFFFFFF
    sr = ((raw["SR"] & 0xFFFF) & ~0x0700) | (case.sr & 0x0700)
    return base.Result(regs, sr, bytes.fromhex(captured["hex"]))


def wait_for_file(path: Path, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.is_file() and path.stat().st_size:
            return
        time.sleep(0.05)
    raise RuntimeError(f"save state was not flushed: {path}")


def nexen_result(
    m: base.McpSession,
    nat: Path,
    case: wall.Case,
    *,
    native: bool,
    pre_state: Path,
) -> tuple[base.Result, dict]:
    m.load_state(str(nat))
    m.pause()

    entry_sp = case.regs["A7"] & 0xFFFFFF
    launch_regs = dict(case.regs)
    launch_regs["A7"] = (entry_sp + 4) & 0xFFFFFFFF if native else entry_sp
    reg_blob = b"".join(base.le32(launch_regs[name]) for name in base.REG_NAMES)
    m.write_memory(base.DP_SPACE, 0x00, reg_blob.hex())
    for offset in range(0, len(case.work), 0x4000):
        m.write_memory(
            base.SNES_SPACE,
            0x400000 + offset,
            case.work[offset : offset + 0x4000].hex(),
        )
    shared.park_snes_cpu(m)

    flags = case.sr & base.CCR_MASK
    wall.write_u16(m, 0x6E, flags & 1)
    wall.write_u16(m, 0x72, (flags >> 1) & 1)
    wall.write_u16(m, 0x60, (flags >> 2) & 1)
    wall.write_u16(m, 0x70, (flags >> 3) & 1)
    wall.write_u16(m, 0xA2, (flags >> 4) & 1)
    wall.write_u16(m, 0x7C, (case.sr >> 8) & 7)
    logical_pc = RETURN_PC if native else ENTRY_PC
    wall.write_u16(m, 0x40, logical_pc & 0xFFFF)
    wall.write_u16(m, 0x42, (logical_pc >> 16) & 0xFF)
    wall.write_u16(m, 0x4A, 0)
    wall.write_u16(m, 0x4C, 0)
    wall.write_u16(m, 0x4E, 0)
    wall.write_u16(m, 0xA4, launch_regs["A7"] & 0xFFFF)
    wall.write_u16(m, 0xA6, (launch_regs["A7"] >> 16) & 0xFFFF)
    wall.write_u16(m, 0xA8, 1)
    wall.write_u16(m, 0xAA, 0)
    wall.write_u16(m, 0xAC, 0x7000)
    wall.write_u16(m, 0x0702, 0)
    wall.write_u16(m, 0x0704, 1)
    wall.write_u16(m, 0x0710, 0)
    wall.write_u16(m, 0x0712, 0)
    wall.write_u16(m, 0x0714, 0)
    wall.write_u16(m, 0x0716, 0)
    wall.write_u16(m, 0x0718, 0xFFF8)
    wall.write_u16(m, 0x071A, 1 if native else 0)
    for address in (0x072E, 0x0730, 0x0734, 0x0736, 0x0738, 0x073A, 0x073C):
        wall.write_u16(m, address, 0)

    base.set_sa1_pc(m, ENTRY_NATIVE if native else INEXT)
    pre_state.parent.mkdir(parents=True, exist_ok=True)
    save_response = m.save_state(pre_state.resolve())
    wait_for_file(pre_state)
    state_info = {
        "path": str(pre_state.resolve()),
        "sha256": wall.sha256(pre_state),
        "size": pre_state.stat().st_size,
        "response": save_response,
    }

    return_offset = 0x10000 + RETURN_PC
    illegal_offset = OP_ILLEGAL - 0x8000
    return_original = bytes(m.read_memory("snesPrgRom", return_offset, 2))
    illegal_original = bytes(m.read_memory("snesPrgRom", illegal_offset, 2))
    m.write_memory("snesPrgRom", return_offset, "4afc")
    m.write_memory("snesPrgRom", illegal_offset, "80fe")
    seam_hook = m.add_exec_hook(OP_ILLEGAL, cpu_type="Sa1")
    m.drain_notifications(timeout=0.05)
    start_cycles = int(m.get_cpu_state("Sa1")["cycleCount"])
    try:
        hit = m.run_until(max_frames=48, hook_handle=seam_hook)
        m.pause()
    finally:
        m.remove_hook(seam_hook)
        m.write_memory("snesPrgRom", return_offset, return_original.hex())
        m.write_memory("snesPrgRom", illegal_offset, illegal_original.hex())
    if (hit or {}).get("reason") != "hookFired":
        sa1 = m.get_cpu_state("Sa1")
        observed_pc = shared.read_u16(m, 0x40) | (
            (shared.read_u16(m, 0x42) & 0xFF) << 16
        )
        raise RuntimeError(
            f"Nexen did not return for {case.name}, native={native}: "
            f"{hit!r}; 68K_PC=${observed_pc:06X}, SA1={sa1!r}, "
            f"halt=${shared.read_u16(m, 0x4E):04X}, "
            f"stack=${shared.captured_regs(m)['A7'] & 0xFFFFFF:06X}"
        )
    end_cycles = int(m.get_cpu_state("Sa1")["cycleCount"])
    observed_pc = shared.read_u16(m, 0x40) | (
        (shared.read_u16(m, 0x42) & 0xFF) << 16
    )
    if observed_pc != RETURN_PC:
        raise RuntimeError(
            f"Nexen froze at ${observed_pc:06X}, expected ${RETURN_PC:06X}"
        )
    sr = (
        0x2000
        | ((shared.read_u16(m, 0x7C) & 7) << 8)
        | shared.captured_ccr(m)
    )
    result = base.Result(
        shared.captured_regs(m),
        sr,
        bytes(m.read_memory(base.SNES_SPACE, 0x400000, MAPPED_WORK_SIZE)),
        end_cycles - start_cycles,
    )
    return result, state_info


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    parser.add_argument("--trace", type=Path, default=DEFAULT_TRACE)
    parser.add_argument("--work", type=Path, default=DEFAULT_WORK)
    parser.add_argument("--nexen", type=Path, default=base.DEFAULT_NEXEN)
    parser.add_argument("--nat", type=Path, default=base.DEFAULT_NAT)
    parser.add_argument("--port", type=int, default=9280)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    for path in (args.rom, args.trace, args.work, args.nexen, args.nat):
        if not path.is_file():
            parser.error(f"missing required input: {path}")
    if args.output.exists():
        parser.error(f"output already exists: {args.output}")
    args.output.parent.mkdir(parents=True, exist_ok=True)

    seed = wall.load_entry(args.trace, args.work)
    cases = make_cases(seed)
    fixtures = {
        case.name: retain_case(case, args.output.parent / "fixtures")
        for case in cases
    }
    events: list[dict] = [
        {
            "event": "provenance",
            "scope": (
                "synthetic-from-retained-organic $012E56 three-way function "
                "differential; all D/A registers, CCR/X/mask, live and popped "
                "stack, mapped 16 KiB work RAM; not fresh-boot or fps evidence"
            ),
            "rom": str(args.rom.resolve()),
            "rom_sha256": wall.sha256(args.rom),
            "trace": str(args.trace.resolve()),
            "trace_sha256": wall.sha256(args.trace),
            "fixture_work": str(args.work.resolve()),
            "fixture_work_sha256": wall.sha256(args.work),
            "nexen": str(args.nexen.resolve()),
            "nexen_sha256": wall.sha256(args.nexen),
            "nat": str(args.nat.resolve()),
            "nat_sha256": wall.sha256(args.nat),
            "entry_pc": f"{ENTRY_PC:06X}",
            "entry_native": f"{ENTRY_NATIVE:06X}",
            "return_pc": f"{RETURN_PC:06X}",
            "cases": [case.name for case in cases],
            "fixtures": fixtures,
            "time": time.time(),
        }
    ]

    oracle: dict[str, base.Result] = {}
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
            oracle[case.name] = mame_result(mame, case)
    finally:
        mame.stop()

    with base.McpSession(
        rom=str(args.rom.resolve()),
        mesen=str(args.nexen.resolve()),
        cwd=ROOT,
        port=args.port,
        boot_wait=8.0,
        socket_timeout=180.0,
        stderr_log=args.output.parent / "12e56-differential.nexen.stderr.log",
    ) as nexen:
        for case in cases:
            for native in (False, True):
                result, state = nexen_result(
                    nexen,
                    args.nat,
                    case,
                    native=native,
                    pre_state=(
                        args.output.parent
                        / "states"
                        / ("native-on" if native else "native-off")
                        / f"{case.name}.mss"
                    ),
                )
                event = wall.compare(
                    case,
                    oracle[case.name],
                    result,
                    "native-on" if native else "native-off",
                )
                event["pre_state"] = state
                events.append(event)
                print(json.dumps(event, sort_keys=True), flush=True)

    cases_out = [event for event in events if event.get("event") == "case"]
    green = sum(event["result"] == "green" for event in cases_out)
    summary = {
        "event": "summary",
        "green": green,
        "red": len(cases_out) - green,
        "total": len(cases_out),
        "result": "green" if green == len(cases_out) else "red",
        "time": time.time(),
    }
    events.append(summary)
    args.output.write_text(
        "".join(json.dumps(event, sort_keys=True) + "\n" for event in events),
        encoding="utf-8",
    )
    print(json.dumps(summary, sort_keys=True), flush=True)
    return 0 if summary["result"] == "green" else 1


if __name__ == "__main__":
    raise SystemExit(main())
