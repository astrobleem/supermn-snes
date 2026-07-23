#!/usr/bin/env python3
"""MAME/Nexen differential for the hot $012B6C -> $12B84 -> $0CE4 tree.

The arcade oracle enters the original $012B6C with each real BSR return on
the stack.  Nexen enters hle_12b6c using the production hook contract (that
push was consumed, A7 is the caller value, and $40/$42 hold the actual return).
A validation-only runtime xlat poke routes each final return dispatch to the
inert bank-$00 spin loop, so state is sampled before the real caller can
mutate it.
All D/A registers, CCR X/N/Z/V/C, and the full low-16-KiB work window are
compared.  This is bounded semantic/cycle evidence, not FPS.
"""

from __future__ import annotations

import argparse
import json
import random
import time
from dataclasses import dataclass
from pathlib import Path

import validate_d96_hle as base

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ROM = ROOT / "build" / "interp.sfc"
ENTRY_PC = 0x012B6C
ENTRY_NATIVE = 0x94E000
RETURN_NATIVE = 0x00D15A
XLAT_FILE_BASE = 0x2B0000
VALIDATION_SUBTABLE_PC = 0x01177C
SPARSE_RETURN_COMPARE_OFFSETS = (0x2EDAD9, 0x2EDADE)
CALLER_SP = 0xF03D00
A4_RECORD = 0xF02C00
A6_FRAME = 0xF03A00

# Every aligned ``bsr.w $012B6C`` in the original program ROM.  This list is
# intentionally explicit: the old test covered only $01177C, which let a
# hard-coded return survive while all other player-state callers misreturned.
CALLER_RETURN_PCS = (
    0x0114A0, 0x0114FA, 0x01151C, 0x01155E,
    0x0115FC, 0x011656, 0x011678, 0x0116BA,
    0x01171E, 0x01177C, 0x01189E, 0x011908,
    0x011940, 0x01198A, 0x0119C6, 0x011A0E,
    0x011A8A, 0x011ACC, 0x011B26, 0x011BDC,
    0x011C9A, 0x011CF4, 0x011D4A, 0x011DB8,
    0x011F08, 0x011FCE, 0x012020, 0x012082,
    0x0120D4, 0x012118, 0x012218, 0x0122BC,
    0x012320, 0x0123FA,
)


@dataclass
class Case(base.Case):
    return_pc: int
    incoming_pc: int


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
    frame_table: int,
    cursor: int,
    record_x: int,
    record_y: int,
    attr_select: int,
    x_flag: int,
    return_pc: int,
    incoming_pc: int | None = None,
) -> Case:
    rng = random.Random(seed)
    work = bytearray(rng.randrange(256) for _ in range(0x10000))
    regs = {reg: rng.randrange(1 << 32) for reg in base.REG_NAMES}
    regs.update(
        {
            "A3": frame_table,
            "A4": A4_RECORD,
            "A5": 0x00F00000,
            "A6": A6_FRAME,
            # Production HLE entry sees the pre-BSR caller stack value.
            "A7": CALLER_SP,
        }
    )
    sr = 0x2700 | rng.randrange(0x10) | ((x_flag & 1) << 4)

    # Global renderer slots used by the original and HLE trees.
    put32(work, 0xF01C8A, 0x00000CE4)
    put32(work, 0xF01C8E, 0x00000D96)

    # Select the $12B84 path with no blink-counter fallback.
    put16(work, A6_FRAME - 0x72, 0)
    put16(work, A6_FRAME - 0x18, 0)
    put16(work, A6_FRAME - 0x50, attr_select)
    put16(work, A6_FRAME - 0x68, 0)
    put16(work, A6_FRAME - 0x58, cursor)

    work[A4_RECORD & 0xFFFF] = 0                 # bit 7 clear -> CE4
    put16(work, A4_RECORD + 2, record_x)
    put16(work, A4_RECORD + 4, record_y)

    # The real BSR return is part of the expected final stack residue.  MAME
    # begins at SP=CALLER_SP-4; the native hook begins at SP=CALLER_SP and
    # hle_12b6c materializes this word itself.
    put32(work, CALLER_SP - 4, return_pc)
    return Case(
        name,
        regs,
        sr,
        bytes(work),
        return_pc,
        return_pc if incoming_pc is None else incoming_pc,
    )


def make_cases() -> list[Case]:
    shapes = (
        # ROM $3478A contains longword $0000084A; frame header 0,3.
        {
            "name": "rom-frame-084a-visible",
            "frame_table": 0x0003478A,
            "cursor": 0x0000,
            "record_x": 0x0080,
            "record_y": 0x0060,
            "attr_select": 0,
            "x_flag": 0,
        },
        # ROM $481A -> $00004E36; frame header 0,7.  Negative cursor and Y
        # clipping exercise signed output placement and final X replacement.
        {
            "name": "rom-frame-4e36-negative-cursor-offscreen",
            "frame_table": 0x0000481A,
            "cursor": 0xFFF0,
            "record_x": 0x0020,
            "record_y": 0x01B0,
            "attr_select": 1,
            "x_flag": 1,
        },
        # ROM $70F4 -> $00005BB0; frame header 1,4 (two columns).
        {
            "name": "rom-frame-5bb0-two-columns",
            "frame_table": 0x000070F4,
            "cursor": 0x0010,
            "record_x": 0x00F5,
            "record_y": 0x0010,
            "attr_select": 0,
            "x_flag": 1,
        },
    )
    cases = []
    for index, return_pc in enumerate(CALLER_RETURN_PCS):
        shape = shapes[index % len(shapes)]
        cases.append(
            build_case(
                f"{shape['name']}-return-{return_pc:06x}",
                0x12B600 + index,
                frame_table=shape["frame_table"],
                cursor=shape["cursor"],
                record_x=shape["record_x"],
                record_y=shape["record_y"],
                attr_select=shape["attr_select"],
                x_flag=shape["x_flag"],
                return_pc=return_pc,
            )
        )
    # entry_11752 links straight to $94:E000 after its native $99:B5B9
    # continuation.  Architecturally this is the old $011778 BSR and must
    # rejoin at logical $01177C.
    shape = shapes[0]
    cases.append(
        build_case(
            "native-entry-11752-return-01177c",
            0x12B6FF,
            frame_table=shape["frame_table"],
            cursor=shape["cursor"],
            record_x=shape["record_x"],
            record_y=shape["record_y"],
            attr_select=shape["attr_select"],
            x_flag=shape["x_flag"],
            return_pc=0x01177C,
            incoming_pc=0x99B5B9,
        )
    )
    return cases


def discover_caller_returns(rom: bytes) -> tuple[int, ...]:
    """Find aligned BSR.W instructions targeting $012B6C in the embedded 68K ROM."""
    program = rom[0x10000:0x90000]
    returns = []
    for pc in range(0, len(program) - 3, 2):
        if program[pc : pc + 2] != b"\x61\x00":
            continue
        displacement = int.from_bytes(program[pc + 2 : pc + 4], "big", signed=True)
        # 68000 PC-relative word displacement is based at the extension word.
        if (pc + 2 + displacement) & 0xFFFFFF == ENTRY_PC:
            returns.append(pc + 4)
    return tuple(returns)


def mame_result(session: base.MameSession, case: Case) -> base.Result:
    session.pause()
    session.write_block(0xF00000, case.work)
    for name in base.REG_NAMES[:-1]:
        session.set_reg(name, case.regs[name])
    entry_sp = case.regs["A7"] - 4
    session.set_reg("SP", entry_sp)
    session.set_reg("USP", entry_sp)
    session.set_reg("SR", case.sr)
    session.set_reg("PC", ENTRY_PC)
    captured = session.cmd(
        "capture_at_pc",
        pc=case.return_pc,
        addr=0xF00000,
        len=0x4000,
        nth=1,
        exp_sp=case.regs["A7"],
        maxFrames=30,
        timeout=30,
    )
    if not captured.get("registers"):
        raise RuntimeError(f"MAME did not return for {case.name}: {captured!r}")
    regs = captured["registers"]
    result_regs = {name: regs[name] & 0xFFFFFFFF for name in base.REG_NAMES[:-1]}
    result_regs["A7"] = regs["SP"] & 0xFFFFFFFF
    return base.Result(result_regs, regs["SR"] & 0xFFFF, bytes.fromhex(captured["hex"]))


def redirect_return_to_spin(
    m: base.McpSession,
    rom: bytes,
    return_pc: int,
) -> dict[str, int]:
    """Route one bank-$01 return through an existing dense xlat sub-table."""
    scratch_page = (VALIDATION_SUBTABLE_PC >> 8) & 0x3FF
    scratch_pointer_offset = XLAT_FILE_BASE + scratch_page * 2
    subtable_offset = int.from_bytes(
        rom[scratch_pointer_offset : scratch_pointer_offset + 2],
        "little",
    )
    if not subtable_offset:
        raise RuntimeError("validation xlat scratch page is absent from this ROM")

    return_page = (return_pc >> 8) & 0x3FF
    page_pointer_offset = XLAT_FILE_BASE + return_page * 2
    target_offset = XLAT_FILE_BASE + subtable_offset + (return_pc & 0xFF) * 3
    m.write_memory(
        "snesPrgRom",
        page_pointer_offset,
        subtable_offset.to_bytes(2, "little").hex(),
    )
    m.write_memory(
        "snesPrgRom",
        target_offset,
        RETURN_NATIVE.to_bytes(3, "little").hex(),
    )
    return {
        "page_pointer_file_offset": page_pointer_offset,
        "subtable_offset": subtable_offset,
        "target_file_offset": target_offset,
    }


def disable_production_sparse_return(
    m: base.McpSession,
    rom: bytes,
) -> None:
    """Let the validation-only dense redirect catch the two shipped hot returns."""
    expected = (b"\xDC\x1B", b"\x9A\x1C")
    for offset, operand in zip(SPARSE_RETURN_COMPARE_OFFSETS, expected):
        if rom[offset : offset + 2] != operand:
            raise RuntimeError(
                f"sparse return compare moved at ROM ${offset:06X}: "
                f"{rom[offset:offset + 2].hex()} != {operand.hex()}"
            )
        m.write_memory("snesPrgRom", offset, "ffff")


def nexen_result(
    m: base.McpSession,
    nat: Path,
    rom: bytes,
    case: Case,
) -> base.Result:
    m.load_state(str(nat))
    m.pause()
    reg_blob = b"".join(base.le32(case.regs[f"D{i}"]) for i in range(8))
    reg_blob += b"".join(base.le32(case.regs[f"A{i}"]) for i in range(8))
    m.write_memory(base.DP_SPACE, 0x00, reg_blob.hex())
    for offset in range(0, 0x10000, 0x4000):
        m.write_memory(
            base.SNES_SPACE,
            0x400000 + offset,
            case.work[offset : offset + 0x4000].hex(),
        )

    flags = case.sr & base.CCR_MASK
    base.write_u16(m, 0x6E, flags & 1)
    base.write_u16(m, 0x72, (flags >> 1) & 1)
    base.write_u16(m, 0x60, (flags >> 2) & 1)
    base.write_u16(m, 0x70, (flags >> 3) & 1)
    base.write_u16(m, 0xA2, (flags >> 4) & 1)
    base.write_u16(m, 0x40, case.incoming_pc & 0xFFFF)
    base.write_u16(m, 0x42, (case.incoming_pc >> 16) & 0xFFFF)
    base.write_u16(m, 0x7C, 7)
    base.write_u16(m, 0xA4, case.regs["A7"] & 0xFFFF)
    base.write_u16(m, 0xA6, (case.regs["A7"] >> 16) & 0xFFFF)
    base.write_u16(m, 0xA8, 1)
    base.write_u16(m, 0xAA, 0)
    base.write_u16(m, 0x4A, 0)
    base.write_u16(m, 0x4C, 0)
    base.write_u16(m, 0xAC, 0x7000)
    base.write_u16(m, 0x0718, 0xFFF8)
    base.write_u16(m, 0x071A, 1)
    base.write_u16(m, 0x0702, 0)
    base.write_u16(m, 0x0704, 1)

    # Redirect only this loaded emulator instance to the inert $00:D15A loop
    # so run_until cannot race past the comparison point.
    disable_production_sparse_return(m, rom)
    redirect_return_to_spin(m, rom, case.return_pc)

    hook = m.add_exec_hook(RETURN_NATIVE, cpu_type="Sa1")
    m.drain_notifications(timeout=0.05)
    base.set_sa1_pc(m, ENTRY_NATIVE)
    start_cycles = int(m.get_cpu_state("Sa1")["cycleCount"])
    hit = m.run_until(max_frames=120, hook_handle=hook)
    if (hit or {}).get("reason") != "hookFired":
        raise RuntimeError(f"Nexen did not return for {case.name}: {hit!r}")
    m.pause()
    m.remove_hook(hook)
    end_cycles = int(m.get_cpu_state("Sa1")["cycleCount"])

    raw_regs = bytes(m.read_memory(base.DP_SPACE, 0x00, 0x40))
    result_regs = {
        name: int.from_bytes(raw_regs[index * 4 : index * 4 + 4], "little")
        for index, name in enumerate(base.REG_NAMES)
    }
    ccr = (
        (1 if m.read_u16(0x6E, base.DP_SPACE) else 0)
        | ((1 if m.read_u16(0x72, base.DP_SPACE) else 0) << 1)
        | ((1 if m.read_u16(0x60, base.DP_SPACE) else 0) << 2)
        | ((1 if m.read_u16(0x70, base.DP_SPACE) else 0) << 3)
        | ((1 if m.read_u16(0xA2, base.DP_SPACE) else 0) << 4)
    )
    return base.Result(
        result_regs,
        (case.sr & ~base.CCR_MASK) | ccr,
        bytes(m.read_memory(base.SNES_SPACE, 0x400000, 0x4000)),
        end_cycles - start_cycles,
    )


def compare(case: Case, arcade: base.Result, console: base.Result) -> dict:
    reg_mismatches = {
        name: {"mame": arcade.regs[name], "nexen": console.regs[name]}
        for name in base.REG_NAMES
        if arcade.regs[name] != console.regs[name]
    }
    offsets = [
        offset
        for offset, (left, right) in enumerate(zip(arcade.work, console.work))
        if left != right
    ]
    ccr_mismatch = (arcade.sr & base.CCR_MASK) != (console.sr & base.CCR_MASK)
    return {
        "case": case.name,
        "return_pc": f"{case.return_pc:06X}",
        "incoming_pc": f"{case.incoming_pc:06X}",
        "result": "green" if not reg_mismatches and not ccr_mismatch and not offsets else "red",
        "reg_mismatches": reg_mismatches,
        "mame_ccr": arcade.sr & base.CCR_MASK,
        "nexen_ccr": console.sr & base.CCR_MASK,
        "work_mismatch_count": len(offsets),
        "work_mismatch_first": [f"F0{offset:04X}" for offset in offsets[:24]],
        "work_mismatch_values": [
            {
                "address": f"F0{offset:04X}",
                "mame": arcade.work[offset],
                "nexen": console.work[offset],
            }
            for offset in offsets[:24]
        ],
        "nexen_cycles": console.cycles,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    parser.add_argument("--nexen", type=Path, default=base.DEFAULT_NEXEN)
    parser.add_argument("--nat", type=Path, default=base.DEFAULT_NAT)
    parser.add_argument("--port", type=int, default=7548)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    for path in (args.rom, args.nexen, args.nat):
        if not path.is_file():
            parser.error(f"missing required input: {path}")

    cases = make_cases()
    rom = args.rom.read_bytes()
    discovered_returns = discover_caller_returns(rom)
    if discovered_returns != CALLER_RETURN_PCS:
        parser.error(
            "embedded 68K caller set changed: expected "
            f"{[f'{pc:06X}' for pc in CALLER_RETURN_PCS]}, got "
            f"{[f'{pc:06X}' for pc in discovered_returns]}"
        )
    events: list[dict] = []
    provenance = {
        "event": "provenance",
        "scope": "function-local 12B6C->12B84->CE4 MAME/Nexen differential; not fps",
        "mame": "/snap/bin/mame 0.287",
        "nexen": str(args.nexen.resolve()),
        "nexen_sha256": base.sha256(args.nexen),
        "rom": str(args.rom.resolve()),
        "rom_sha256": base.sha256(args.rom),
        "nat": str(args.nat.resolve()),
        "nat_sha256": base.sha256(args.nat),
        "entry_native": f"{ENTRY_NATIVE:06X}",
        "return_native": f"{RETURN_NATIVE:06X}",
        "runtime_xlat_redirect": {
            "strategy": (
                "disable the two production sparse-return comparisons, then repoint "
                "the return page to the existing $0117xx dense sub-table"
            ),
            "target": f"{RETURN_NATIVE:06X}",
        },
        "caller_return_pcs": [f"{pc:06X}" for pc in CALLER_RETURN_PCS],
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
            arcade[case.name] = mame_result(mame, case)
            print(json.dumps({"event": "mame_case", "case": case.name}), flush=True)
    finally:
        mame.stop()

    with base.McpSession(
        rom=str(args.rom),
        mesen=str(args.nexen),
        cwd=ROOT,
        port=args.port,
        boot_wait=8.0,
        socket_timeout=120.0,
        stderr_log=ROOT / "build" / "playability-20260719" / "12b6c-nexen.stderr.log",
    ) as nexen:
        for case in cases:
            console = nexen_result(nexen, args.nat, rom, case)
            event = {"event": "case", **compare(case, arcade[case.name], console)}
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
