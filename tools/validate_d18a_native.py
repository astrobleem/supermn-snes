#!/usr/bin/env python3
"""Three-way semantic regression for the $00D18A camera/player rollback.

The retained MAME movie fixture is captured synchronously at the original
function entry, after the real BSR return is on the MC68000 stack and before
the first instruction executes.  The same complete register/SR/work state is
then run through:

* MAME 0.287 original code;
* the SNES interpreter with native dispatch disabled; and
* the repaired bank-$92 native body.

All D/A registers, CCR/X, interrupt mask, the live return stack, and the
complete mapped 16 KiB work-RAM window are compared at a self-loop return seam.
This is bounded function evidence, not fresh-boot or performance evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path

import validate_175a0_native as shared


base = shared.base
ROOT = shared.ROOT
DEFAULT_ROM = ROOT / "build/interp.sfc"
DEFAULT_TRACE = (
    ROOT
    / "build/playtest-investigation-20260725"
    / "organic-player-right-clamp-mame-write-trace-v2"
    / "trace.jsonl"
)
DEFAULT_WORK = DEFAULT_TRACE.parent / "mame-d18a-entry-tick-02305.work.bin"
ENTRY_PC = 0x00D18A
# `entry_d18a` moved when the preceding generated body grew.  Keep this in
# sync with the packed-ROM seam asserted by the build rather than launching
# the fixture at a stale instruction stream.
ENTRY_NATIVE = 0x92ABE2
INEXT = 0x00D128
RETURN_PC = 0x002B16
OP_ILLEGAL = 0x00CDED
MAPPED_WORK_SIZE = 0x4000
FULL_WORK_SIZE = 0x10000


@dataclass
class Case:
    name: str
    regs: dict[str, int]
    sr: int
    work: bytes


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def be16(work: bytes | bytearray, address: int) -> int:
    offset = address & 0xFFFF
    return (work[offset] << 8) | work[(offset + 1) & 0xFFFF]


def put_be16(work: bytearray, address: int, value: int) -> None:
    offset = address & 0xFFFF
    work[offset : offset + 2] = (value & 0xFFFF).to_bytes(2, "big")


def load_entry(trace: Path, work_path: Path) -> Case:
    rows = [
        json.loads(line)
        for line in trace.read_text(encoding="utf-8").splitlines()
    ]
    matches = [
        row
        for row in rows
        if row.get("event") == "function_entry"
        and row.get("function") == "00D18A"
        and int(row.get("tick", -1)) == 2305
    ]
    if len(matches) != 1:
        raise RuntimeError(f"expected one retained D18A entry, got {len(matches)}")
    row = matches[0]
    work = bytearray(work_path.read_bytes())
    if len(work) != FULL_WORK_SIZE:
        raise RuntimeError(f"{work_path}: expected {FULL_WORK_SIZE} bytes")
    regs = {
        name: int(row["SP" if name == "A7" and "SP" in row else name])
        for name in base.REG_NAMES
    }
    entry_sp = regs["A7"] & 0xFFFFFF
    if (entry_sp >> 16) != 0xF0 or entry_sp + 4 > 0xF10000:
        raise RuntimeError(f"unsupported retained entry SP ${entry_sp:06X}")
    work[entry_sp & 0xFFFF : (entry_sp & 0xFFFF) + 4] = (
        RETURN_PC.to_bytes(4, "big")
    )
    return Case("organic-wall-tick-02305", regs, int(row["SR"]), bytes(work))


def derived_cases(seed: Case) -> list[Case]:
    cases = [seed]
    a5 = seed.regs["A5"] & 0xFFFFFF
    a3 = seed.regs["A3"] & 0xFFFFFF
    a1 = seed.regs["A1"] & 0xFFFFFF
    if any((pointer >> 16) != 0xF0 for pointer in (a5, a3, a1)):
        raise RuntimeError("D18A fixture pointers are outside canonical work RAM")

    def add(name: str, edits: list[tuple[int, int]], sr: int | None = None) -> None:
        work = bytearray(seed.work)
        for address, value in edits:
            put_be16(work, address, value)
        cases.append(
            Case(
                name,
                dict(seed.regs),
                seed.sr if sr is None else sr,
                bytes(work),
            )
        )

    flags_address = a5 + 0x2A4A
    original_flags_word = be16(seed.work, flags_address)
    for name, low_byte in (
        ("second-player-bit", 0x02),
        ("both-player-bits", 0x03),
    ):
        add(
            name,
            [(flags_address, (original_flags_word & 0xFF00) | low_byte)],
        )

    for x in (0, 1):
        add(
            f"no-rollback-x{x}",
            [(flags_address, original_flags_word & 0xFF00)],
            (seed.sr & ~0x10) | (x << 4),
        )

    # Preserve all branch guards while making the positive rollback larger
    # than both target words.  The final SUB.W must wrap and leave X=1.
    add(
        "first-player-borrow",
        [
            (flags_address, (original_flags_word & 0xFF00) | 0x01),
            (a3 - 0x60, 0x0200),
            (a1 - 0x60, 0x0200),
        ],
    )
    return cases


def mame_result(session: base.MameSession, case: Case) -> base.Result:
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
    regs = {
        name: raw[name] & 0xFFFFFFFF for name in base.REG_NAMES[:-1]
    }
    regs["A7"] = raw["SP"] & 0xFFFFFFFF
    sr = ((raw["SR"] & 0xFFFF) & ~0x0700) | (case.sr & 0x0700)
    return base.Result(regs, sr, bytes.fromhex(captured["hex"]))


def write_u16(m: base.McpSession, address: int, value: int) -> None:
    m.write_u16(address, value & 0xFFFF, base.DP_SPACE)


def nexen_result(
    m: base.McpSession,
    nat: Path,
    case: Case,
    *,
    native: bool,
) -> base.Result:
    m.load_state(str(nat))
    m.pause()

    entry_sp = case.regs["A7"] & 0xFFFFFF
    launch_regs = dict(case.regs)
    launch_regs["A7"] = (entry_sp + 4) & 0xFFFFFFFF if native else entry_sp
    reg_blob = b"".join(
        base.le32(launch_regs[name]) for name in base.REG_NAMES
    )
    m.write_memory(base.DP_SPACE, 0x00, reg_blob.hex())
    for offset in range(0, len(case.work), 0x4000):
        m.write_memory(
            base.SNES_SPACE,
            0x400000 + offset,
            case.work[offset : offset + 0x4000].hex(),
        )
    shared.park_snes_cpu(m)

    flags = case.sr & base.CCR_MASK
    write_u16(m, 0x6E, flags & 1)
    write_u16(m, 0x72, (flags >> 1) & 1)
    write_u16(m, 0x60, (flags >> 2) & 1)
    write_u16(m, 0x70, (flags >> 3) & 1)
    write_u16(m, 0xA2, (flags >> 4) & 1)
    write_u16(m, 0x7C, (case.sr >> 8) & 7)
    start_pc = RETURN_PC if native else ENTRY_PC
    write_u16(m, 0x40, start_pc & 0xFFFF)
    write_u16(m, 0x42, (start_pc >> 16) & 0xFF)
    write_u16(m, 0x4A, 0)
    write_u16(m, 0x4C, 0)
    write_u16(m, 0xA4, launch_regs["A7"] & 0xFFFF)
    write_u16(m, 0xA6, (launch_regs["A7"] >> 16) & 0xFFFF)
    write_u16(m, 0xA8, 1)
    write_u16(m, 0xAA, 0)
    write_u16(m, 0xAC, 0x7000)
    write_u16(m, 0x0702, 0)
    write_u16(m, 0x0704, 1)
    # Production packs the per-fetch dbg_fetch call to NOPs, so its $0710
    # freeze target is unavailable.  nexen_result instead patches the
    # retained return word to ILLEGAL and stops at op_illegal before it
    # mutates architectural state.
    write_u16(m, 0x0710, 0)
    write_u16(m, 0x0712, 0)
    write_u16(m, 0x0714, 0)
    write_u16(m, 0x0716, (RETURN_PC >> 16) & 0xFF)
    write_u16(m, 0x0718, 0xFFF8)
    write_u16(m, 0x071A, 1 if native else 0)
    for address in (0x072E, 0x0730, 0x0734, 0x0736, 0x0738, 0x073A, 0x073C):
        write_u16(m, address, 0)

    return_offset = 0x10000 + RETURN_PC
    illegal_offset = OP_ILLEGAL - 0x8000
    return_original = bytes(m.read_memory("snesPrgRom", return_offset, 2))
    illegal_original = bytes(m.read_memory("snesPrgRom", illegal_offset, 2))
    m.write_memory("snesPrgRom", return_offset, "4afc")
    m.write_memory("snesPrgRom", illegal_offset, "80fe")
    seam_hook = m.add_exec_hook(OP_ILLEGAL, cpu_type="Sa1")
    m.drain_notifications(timeout=0.05)
    base.set_sa1_pc(m, ENTRY_NATIVE if native else INEXT)
    start_cycles = int(m.get_cpu_state("Sa1")["cycleCount"])
    try:
        hit = m.run_until(max_frames=24, hook_handle=seam_hook)
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
            f"AC=${shared.read_u16(m, 0xAC):04X}, "
            f"stack=${shared.captured_regs(m)['A7'] & 0xFFFFFF:06X}, "
            f"stop_marker=${shared.read_u16(m, 0x0712):04X}"
        )
    end_cycles = int(m.get_cpu_state("Sa1")["cycleCount"])
    observed_pc = shared.read_u16(m, 0x40) | (
        (shared.read_u16(m, 0x42) & 0xFF) << 16
    )
    if observed_pc != RETURN_PC:
        raise RuntimeError(
            f"Nexen froze at ${observed_pc:06X}, expected ${RETURN_PC:06X}"
        )
    sr = 0x2000 | (
        (shared.read_u16(m, 0x7C) & 7) << 8
    ) | shared.captured_ccr(m)
    return base.Result(
        shared.captured_regs(m),
        sr,
        bytes(m.read_memory(base.SNES_SPACE, 0x400000, MAPPED_WORK_SIZE)),
        end_cycles - start_cycles,
    )


def compare(
    case: Case,
    oracle: base.Result,
    result: base.Result,
    configuration: str,
) -> dict:
    reg_mismatches = {
        name: {"mame": oracle.regs[name], "snes": result.regs[name]}
        for name in base.REG_NAMES
        if oracle.regs[name] != result.regs[name]
    }
    ccr_mismatch = (oracle.sr & base.CCR_MASK) != (
        result.sr & base.CCR_MASK
    )
    mask_mismatch = ((oracle.sr >> 8) & 7) != ((result.sr >> 8) & 7)
    work_mismatches = [
        offset
        for offset, (left, right) in enumerate(zip(oracle.work, result.work))
        if left != right
    ]
    return {
        "event": "case",
        "case": case.name,
        "configuration": configuration,
        "result": (
            "green"
            if not reg_mismatches
            and not ccr_mismatch
            and not mask_mismatch
            and not work_mismatches
            else "red"
        ),
        "register_mismatches": reg_mismatches,
        "mame_ccr_xnzvc": oracle.sr & base.CCR_MASK,
        "snes_ccr_xnzvc": result.sr & base.CCR_MASK,
        "interrupt_mask_mismatch": mask_mismatch,
        "work_mismatch_count": len(work_mismatches),
        "work_mismatch_offsets": work_mismatches[:64],
        "sa1_cycles": result.cycles,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    parser.add_argument("--trace", type=Path, default=DEFAULT_TRACE)
    parser.add_argument("--work", type=Path, default=DEFAULT_WORK)
    parser.add_argument("--nexen", type=Path, default=base.DEFAULT_NEXEN)
    parser.add_argument("--nat", type=Path, default=base.DEFAULT_NAT)
    parser.add_argument("--port", type=int, default=9275)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    for path in (args.rom, args.trace, args.work, args.nexen, args.nat):
        if not path.is_file():
            parser.error(f"missing required input: {path}")
    if args.output.exists():
        parser.error(f"output already exists: {args.output}")
    args.output.parent.mkdir(parents=True, exist_ok=True)

    cases = derived_cases(load_entry(args.trace, args.work))
    events: list[dict] = [
        {
            "event": "provenance",
            "scope": (
                "retained organic-entry $00D18A three-way function "
                "differential; all D/A registers, CCR/X/mask, live stack, "
                "mapped 16 KiB work RAM; not fresh-boot or fps evidence"
            ),
            "rom": str(args.rom.resolve()),
            "rom_sha256": sha256(args.rom),
            "trace": str(args.trace.resolve()),
            "trace_sha256": sha256(args.trace),
            "fixture_work": str(args.work.resolve()),
            "fixture_work_sha256": sha256(args.work),
            "nexen": str(args.nexen.resolve()),
            "nexen_sha256": sha256(args.nexen),
            "nat": str(args.nat.resolve()),
            "nat_sha256": sha256(args.nat),
            "entry_pc": f"{ENTRY_PC:06X}",
            "entry_native": f"{ENTRY_NATIVE:06X}",
            "return_pc": f"{RETURN_PC:06X}",
            "cases": [case.name for case in cases],
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
        stderr_log=args.output.parent / "d18a-differential.nexen.stderr.log",
    ) as nexen:
        for case in cases:
            for native in (False, True):
                result = nexen_result(
                    nexen,
                    args.nat,
                    case,
                    native=native,
                )
                event = compare(
                    case,
                    oracle[case.name],
                    result,
                    "native-on" if native else "native-off",
                )
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
