#!/usr/bin/env python3
"""Function-local MAME/Nexen differential for the $00096A palette stepper.

MAME executes the original 68000 subroutine through RTS.  Nexen enters the
production bank-$99 callable escape before its skipped JSR return has been
materialized, exactly matching the jsr.l hook contract.  The comparison covers
all D/A registers, CCR X/N/Z/V/C, and the mapped low-16K work-RAM window apart
from the synthetic return word.  Cases cover all-equal, all-changing, mixed,
and negative-final-result palette states across multiple production ROM tables,
plus a legal fourth-column input that must retain the generated fallback.

This is bounded semantic/cycle evidence, not an end-to-end performance claim.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import time
from pathlib import Path

import validate_d96_hle as base


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ROM = ROOT / "build" / "interp.sfc"
ENTRY_PC = 0x00096A
ENTRY_NATIVE = 0x99C200
CALLER_SP = 0xF03D04
RETURN_PC = 0xF03E80
NATIVE_RETURN = 0x00D15A
PALETTE_POINTERS = 0x03065C
PALETTE_CURRENT = 0x1952
PALETTE_DIRTY = 0x1B12
SELECT_ROW = 0x2930
SELECT_COLUMN = 0x2932
PALETTE_BYTES = 64 * 2
TRACE_POINTS = {
    "fast": 0x95A0F9,
    "fallback": 0x95A1D6,
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def put16(work: bytearray, offset: int, value: int) -> None:
    work[offset : offset + 2] = base.be16(value)


def put32(work: bytearray, offset: int, value: int) -> None:
    work[offset : offset + 4] = base.be32(value)


def selected_palette(image: bytes, row: int, column: int) -> bytes:
    index = PALETTE_POINTERS + row * 12 + column * 4
    pointer = int.from_bytes(image[index : index + 4], "big")
    palette = image[pointer + 10 : pointer + 10 + PALETTE_BYTES]
    if len(palette) != PALETTE_BYTES:
        raise ValueError(f"palette pointer ${pointer:06X} leaves the program image")
    return palette


def build_case(
    image: bytes,
    name: str,
    seed: int,
    *,
    row: int,
    column: int,
    palette_mode: str,
    dirty: int,
    caller_sp: int = CALLER_SP,
) -> base.Case:
    rng = random.Random(seed)
    work = bytearray(rng.randrange(256) for _ in range(0x4000))
    regs = {reg: rng.randrange(1 << 32) for reg in base.REG_NAMES}
    regs["A5"] = 0x00F00000
    regs["A7"] = caller_sp
    sr = 0x2700 | rng.randrange(0x20)
    target = selected_palette(image, row, column)

    if palette_mode == "zero":
        current = bytes(PALETTE_BYTES)
    elif palette_mode == "equal":
        current = target
    elif palette_mode == "mixed":
        current_words = []
        for index in range(64):
            value = int.from_bytes(target[index * 2 : index * 2 + 2], "big")
            if index % 4 == 0:
                current_words.append(value)
            elif index % 4 == 1:
                current_words.append(0)
            elif index % 4 == 2:
                current_words.append(value ^ 0x0842)
            else:
                current_words.append(rng.randrange(0x10000))
        current = b"".join(base.be16(value) for value in current_words)
    elif palette_mode == "above":
        current = b"".join(
            base.be16((int.from_bytes(target[i : i + 2], "big") + 0x0842) & 0xFFFF)
            for i in range(0, PALETTE_BYTES, 2)
        )
    else:
        raise ValueError(f"unknown palette mode {palette_mode!r}")

    put16(work, SELECT_ROW, row)
    put16(work, SELECT_COLUMN, column)
    work[PALETTE_CURRENT : PALETTE_CURRENT + PALETTE_BYTES] = current
    put32(work, PALETTE_DIRTY, dirty)
    put32(work, (caller_sp - 4) & 0xFFFF, RETURN_PC)
    work[RETURN_PC & 0xFFFF : (RETURN_PC & 0xFFFF) + 2] = bytes.fromhex("60fe")
    return base.Case(name, regs, sr, bytes(work))


def make_cases(rom: Path) -> list[base.Case]:
    data = rom.read_bytes()
    image = data[0x10000 : 0x90000]
    if len(image) != 0x80000:
        raise ValueError("ROM does not contain the expected 512 KiB 68000 image")
    return [
        build_case(image, "fast-row0-col0-all-zero", 0x096A00, row=0, column=0,
                   palette_mode="zero", dirty=0x00000000),
        build_case(image, "fast-row4-col2-all-equal", 0x096A01, row=4, column=2,
                   palette_mode="equal", dirty=0x00000003),
        build_case(image, "fast-row8-col0-mixed-negative-dirty", 0x096A02, row=8, column=0,
                   palette_mode="mixed", dirty=0x80000001),
        build_case(image, "fast-row3-col1-above-target", 0x096A03, row=3, column=1,
                   palette_mode="above", dirty=0x4000A5A5),
        # The original arithmetic permits column 3 (it aliases the next row's
        # first pointer), while the specialized production guard admits 0..2.
        build_case(image, "fallback-row2-col3", 0x096AF0, row=2, column=3,
                   palette_mode="mixed", dirty=0x00000000),
    ]


def mame_result(session: base.MameSession, case: base.Case) -> base.Result:
    session.pause()
    session.write_block(0xF00000, case.work)
    for name in base.REG_NAMES[:-1]:
        session.set_reg(name, case.regs[name])
    entry_sp = (case.regs["A7"] - 4) & 0xFFFFFFFF
    session.set_reg("SP", entry_sp)
    session.set_reg("USP", entry_sp)
    session.set_reg("SR", case.sr)
    session.set_reg("PC", ENTRY_PC)
    captured = session.cmd(
        "capture_at_pc",
        pc=RETURN_PC,
        addr=0xF00000,
        len=0x4000,
        nth=1,
        exp_sp=case.regs["A7"] & 0xFFFFFF,
        maxFrames=30,
        timeout=30,
    )
    if not captured.get("registers"):
        raise RuntimeError(f"MAME did not return for {case.name}: {captured!r}")
    regs = captured["registers"]
    result_regs = {name: regs[name] & 0xFFFFFFFF for name in base.REG_NAMES[:-1]}
    result_regs["A7"] = regs["SP"] & 0xFFFFFFFF
    return base.Result(
        result_regs,
        regs["SR"] & 0xFFFF,
        bytes.fromhex(captured["hex"]),
    )


def prepare_nexen_case(
    session: base.McpSession,
    nat: Path,
    case: base.Case,
) -> None:
    session.load_state(str(nat))
    session.pause()
    reg_blob = b"".join(base.le32(case.regs[f"D{i}"]) for i in range(8))
    reg_blob += b"".join(base.le32(case.regs[f"A{i}"]) for i in range(8))
    session.write_memory(base.DP_SPACE, 0x00, reg_blob.hex())
    session.write_memory(base.SNES_SPACE, 0x400000, case.work.hex())

    flags = case.sr & base.CCR_MASK
    base.write_u16(session, 0x6E, flags & 1)
    base.write_u16(session, 0x72, (flags >> 1) & 1)
    base.write_u16(session, 0x60, (flags >> 2) & 1)
    base.write_u16(session, 0x70, (flags >> 3) & 1)
    base.write_u16(session, 0xA2, (flags >> 4) & 1)
    base.write_u16(session, 0x40, NATIVE_RETURN & 0xFFFF)
    base.write_u16(session, 0x42, 0x00FF)
    base.write_u16(session, 0x7C, 7)
    base.write_u16(session, 0xA4, case.regs["A7"] & 0xFFFF)
    base.write_u16(session, 0xA6, (case.regs["A7"] >> 16) & 0xFFFF)
    base.write_u16(session, 0xA8, 1)
    base.write_u16(session, 0xAA, 0)
    base.write_u16(session, 0x4A, 0)
    base.write_u16(session, 0x4C, 0)
    base.write_u16(session, 0xAC, 0x7000)
    base.write_u16(session, 0x0718, 0xFFF8)
    base.write_u16(session, 0x071A, 1)
    base.write_u16(session, 0x0702, 0)
    base.write_u16(session, 0x0704, 1)


def nexen_result(
    session: base.McpSession,
    nat: Path,
    case: base.Case,
) -> base.Result:
    prepare_nexen_case(session, nat, case)
    hook = session.add_exec_hook(NATIVE_RETURN, cpu_type="Sa1")
    session.drain_notifications(timeout=0.05)
    try:
        base.set_sa1_pc(session, ENTRY_NATIVE)
        start_cycles = int(session.get_cpu_state("Sa1")["cycleCount"])
        hit = session.run_until(max_frames=120, hook_handle=hook)
        if (hit or {}).get("reason") != "hookFired":
            raise RuntimeError(f"Nexen did not return for {case.name}: {hit!r}")
        session.pause()
        end_cycles = int(session.get_cpu_state("Sa1")["cycleCount"])
    finally:
        session.remove_hook(hook)

    raw_regs = bytes(session.read_memory(base.DP_SPACE, 0x00, 0x40))
    result_regs = {
        name: int.from_bytes(raw_regs[index * 4 : index * 4 + 4], "little")
        for index, name in enumerate(base.REG_NAMES)
    }
    ccr = (
        (1 if session.read_u16(0x6E, base.DP_SPACE) else 0)
        | ((1 if session.read_u16(0x72, base.DP_SPACE) else 0) << 1)
        | ((1 if session.read_u16(0x60, base.DP_SPACE) else 0) << 2)
        | ((1 if session.read_u16(0x70, base.DP_SPACE) else 0) << 3)
        | ((1 if session.read_u16(0xA2, base.DP_SPACE) else 0) << 4)
    )
    return base.Result(
        result_regs,
        (case.sr & ~base.CCR_MASK) | ccr,
        bytes(session.read_memory(base.SNES_SPACE, 0x400000, 0x4000)),
        end_cycles - start_cycles,
    )


def nexen_path_probe(
    session: base.McpSession,
    nat: Path,
    case: base.Case,
) -> dict[str, int]:
    expected = "fallback" if case.name.startswith("fallback-") else "fast"
    prepare_nexen_case(session, nat, case)
    hook = session.add_exec_hook(TRACE_POINTS[expected], cpu_type="Sa1")
    session.drain_notifications(timeout=0.05)
    try:
        base.set_sa1_pc(session, ENTRY_NATIVE)
        hit = session.run_until(max_frames=120, hook_handle=hook)
        session.pause()
        if (hit or {}).get("reason") != "hookFired":
            raise RuntimeError(
                f"Nexen did not take {expected} path for {case.name}: {hit!r}"
            )
        # Hook notification delivery is asynchronous: by the time run_until
        # returns, the non-pausing CPU can be several instructions past the
        # hooked entry.  The requested-handle hit proves the branch; do not
        # misclassify the later sampled PC as a failure.
        return {
            "fast": 1 if expected == "fast" else 0,
            "fallback": 1 if expected == "fallback" else 0,
        }
    finally:
        session.remove_hook(hook)


def compare(
    case: base.Case,
    arcade: base.Result,
    console: base.Result,
    path_counts: dict[str, int],
) -> dict:
    reg_mismatches = {
        name: {"mame": arcade.regs[name], "nexen": console.regs[name]}
        for name in base.REG_NAMES
        if arcade.regs[name] != console.regs[name]
    }
    return_slot = (case.regs["A7"] - 4) & 0xFFFF
    excluded = set(range(return_slot, return_slot + 4))
    offsets = [
        offset
        for offset, (left, right) in enumerate(zip(arcade.work, console.work))
        if offset not in excluded and left != right
    ]
    ccr_mismatch = (arcade.sr & base.CCR_MASK) != (console.sr & base.CCR_MASK)
    expected_path = "fallback" if case.name.startswith("fallback-") else "fast"
    path_mismatch = path_counts != {
        "fast": 1 if expected_path == "fast" else 0,
        "fallback": 1 if expected_path == "fallback" else 0,
    }
    return {
        "case": case.name,
        "result": (
            "green"
            if not reg_mismatches and not ccr_mismatch and not offsets and not path_mismatch
            else "red"
        ),
        "reg_mismatches": reg_mismatches,
        "mame_ccr": arcade.sr & base.CCR_MASK,
        "nexen_ccr": console.sr & base.CCR_MASK,
        "work_mismatch_count": len(offsets),
        "work_mismatch_first": [f"F0{offset:04X}" for offset in offsets[:24]],
        "expected_path": expected_path,
        "path_counts": path_counts,
        "path_mismatch": path_mismatch,
        "nexen_cycles": console.cycles,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    parser.add_argument("--nexen", type=Path, default=base.DEFAULT_NEXEN)
    parser.add_argument("--nat", type=Path, default=base.DEFAULT_NAT)
    parser.add_argument("--port", type=int, default=7641)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    for path in (args.rom, args.nexen, args.nat):
        if not path.is_file():
            parser.error(f"missing required input: {path}")

    cases = make_cases(args.rom)
    events: list[dict] = []
    provenance = {
        "event": "provenance",
        "scope": "function-local 96A MAME/Nexen differential; not fps",
        "mame": "/snap/bin/mame 0.287",
        "nexen": str(args.nexen.resolve()),
        "nexen_sha256": sha256(args.nexen),
        "rom": str(args.rom.resolve()),
        "rom_sha256": sha256(args.rom),
        "nat": str(args.nat.resolve()),
        "nat_sha256": sha256(args.nat),
        "entry_native": f"{ENTRY_NATIVE:06X}",
        "cases": len(cases),
        "time": time.time(),
    }
    events.append(provenance)
    print(json.dumps(provenance, sort_keys=True), flush=True)

    arcade_results: dict[str, base.Result] = {}
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
            arcade_results[case.name] = mame_result(mame, case)
            print(json.dumps({"event": "mame_case", "case": case.name}), flush=True)
    finally:
        mame.stop()

    path_stderr_log = (
        args.output.parent / f"{args.output.stem}.path.nexen.stderr.log"
        if args.output
        else ROOT / "build" / "96a-differential-path-nexen.stderr.log"
    )
    path_counts: dict[str, dict[str, int]] = {}
    with base.McpSession(
        rom=str(args.rom),
        mesen=str(args.nexen),
        cwd=ROOT,
        port=args.port + 1,
        boot_wait=8.0,
        socket_timeout=120.0,
        stderr_log=path_stderr_log,
    ) as nexen:
        for case in cases:
            path_counts[case.name] = nexen_path_probe(nexen, args.nat, case)

    stderr_log = ROOT / "build" / "playability-20260720" / "96a-differential-nexen.stderr.log"
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
            console = nexen_result(nexen, args.nat, case)
            event = {
                "event": "case",
                **compare(
                    case,
                    arcade_results[case.name],
                    console,
                    path_counts[case.name],
                ),
            }
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
        args.output.write_text("".join(json.dumps(event, sort_keys=True) + "\n" for event in events))
    return 0 if green == len(cases) else 1


if __name__ == "__main__":
    raise SystemExit(main())
