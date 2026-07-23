#!/usr/bin/env python3
"""Function-local MAME/Nexen differential for the callable $00CAF6 tree.

MAME executes the original 68000 $CAF6->$CB9E sprite-list builder through
RTS.  Nexen enters the production bank-$97 callable entry before the skipped
BSR return has been materialized.  The comparison covers every emulated
register, CCR X/N/Z/V/C, and mapped low-16K work RAM apart from the synthetic
outer/native return words.  Cases exercise both production five-record ROM
lists, both rendering orientations/attribute widths, and each live
list-selection branch.

This is bounded semantic/cycle evidence, not an FPS measurement.
"""

from __future__ import annotations

import argparse
import json
import random
import time
from pathlib import Path

import validate_d96_hle as base


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ROM = ROOT / "build/interp.sfc"
ENTRY_PC = 0x00CAF6
ENTRY_NATIVE = 0x97D800
CALLER_SP = 0xF01284
RETURN_PC = 0xF03E80
NATIVE_RETURN = 0x00D15A
A2_RECORD = 0xF03574
A6_FRAME = 0xF01302
A1_BASE = 0xF03A04


def symbol_address(path: Path, mapped_bank: int, name: str) -> int:
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        fields = raw.split()
        if len(fields) >= 2 and fields[1] == name:
            return (mapped_bank << 16) | int(fields[0].split(":", 1)[1], 16)
    raise RuntimeError(f"missing symbol {name!r} in {path}")


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
    selection: str,
    mirrored: bool,
    wide_attribute: bool,
    table_index: int = 0x000C,
) -> base.Case:
    rng = random.Random(seed)
    work = bytearray(rng.randrange(256) for _ in range(0x10000))
    regs = {reg: rng.randrange(1 << 32) for reg in base.REG_NAMES}
    regs.update(
        {
            "A0": 0x00032F26,
            "A1": A1_BASE,
            "A2": 0x0004288A,
            "A5": 0x00F00000,
            "A6": A6_FRAME,
            # The native callable entry sees the pre-BSR stack value.
            "A7": CALLER_SP,
        }
    )
    sr = 0x2700 | rng.randrange(0x20)

    # $CB9E frame inputs shared by all five records.
    put16(work, A6_FRAME - 0x22, 0x0014)
    work[(A6_FRAME - 0x24) & 0xFFFF] = 0x80 if mirrored else 0x00
    put16(work, A6_FRAME - 0x1E, 0x0124)
    put32(work, A6_FRAME - 0x54, A2_RECORD)
    put16(work, A6_FRAME - 0x50, 1 if wide_attribute else 0)

    # Every production list used here has five records whose first words are
    # 0,4,8,12,16.  $CAF6 uses those as offsets into the A6 pointer table.
    for record_index, pointer_offset in enumerate(range(0, 0x14, 4)):
        target = A1_BASE + record_index * 0x10
        put32(work, A6_FRAME - 0x38 + pointer_offset, target)
        for byte_index in range(0x10):
            work[(target + byte_index) & 0xFFFF] = rng.randrange(256)
    put16(work, A2_RECORD + 0, 0xAAAA)
    put16(work, A2_RECORD + 2, 0xBBBB)
    put16(work, A2_RECORD + 4, 0xCCCC)

    if selection == "direct-index":
        # Equal D2, then positive ([A6-$16]-1), reaches cb28 with D7 from
        # [A6-$18].  Index $0C selects pointer $032F78 (five records).
        put16(work, A6_FRAME - 0x1A, 0x0042)
        put16(work, A6_FRAME - 0x04, 0x0042)
        put16(work, A6_FRAME - 0x18, table_index)
        put16(work, A6_FRAME - 0x16, 2)
    elif selection == "d1-negative-list32f78":
        # Equal D2 and ([A6-$16]-1)==0 then make D1 negative.  D2=4 routes
        # $03257C->$0326B2->$000C, selecting the same $032F78 list as the
        # direct production indices.  Make every CB9E record early-return so
        # the selector's D1=$FFFF result remains directly observable.
        put16(work, A6_FRAME - 0x1A, 4)
        put16(work, A6_FRAME - 0x04, 4)
        put16(work, A6_FRAME - 0x18, 0x0124)
        put16(work, A6_FRAME - 0x16, 1)
        put16(work, A6_FRAME - 0x14, 0)
        for record_index in range(5):
            put16(work, A1_BASE + record_index * 0x10, 0)
    elif selection == "frame-pointer-list32f78":
        # The adjacent boundary state leaves D1=0 and reads selector $0124
        # from exact production frame pointer $0326B8.  As above, force all
        # nested CB9E calls to return early so D1 remains observable.
        put16(work, A6_FRAME - 0x1A, 4)
        put16(work, A6_FRAME - 0x04, 4)
        put16(work, A6_FRAME - 0x18, 0x000C)
        put16(work, A6_FRAME - 0x16, 1)
        put16(work, A6_FRAME - 0x14, 1)
        put32(work, A6_FRAME - 0x12, 0x000326B8)
        for record_index in range(5):
            put16(work, A1_BASE + record_index * 0x10, 0)
    elif selection == "d1-negative-list32fca-d2-8":
        # Right+B boundary form: equal D2=8, D0 becomes zero and D1 becomes
        # negative.  $032580->$0326BC->$0010 selects immutable $032FCA.
        put16(work, A6_FRAME - 0x1A, 8)
        put16(work, A6_FRAME - 0x04, 8)
        put16(work, A6_FRAME - 0x18, 0x0014)
        put16(work, A6_FRAME - 0x16, 1)
        put16(work, A6_FRAME - 0x14, 0)
        for record_index in range(5):
            put16(work, A1_BASE + record_index * 0x10, 0)
    elif selection == "frame-pointer-list32fca-d2-8":
        # Adjacent Right+B boundary form: D0/D1 both become zero and exact
        # frame pointer $0326C2 supplies $0014, the same $032FCA list alias.
        put16(work, A6_FRAME - 0x1A, 8)
        put16(work, A6_FRAME - 0x04, 8)
        put16(work, A6_FRAME - 0x18, 0x0010)
        put16(work, A6_FRAME - 0x16, 1)
        put16(work, A6_FRAME - 0x14, 1)
        put32(work, A6_FRAME - 0x12, 0x000326C2)
        for record_index in range(5):
            put16(work, A1_BASE + record_index * 0x10, 0)
    elif selection == "d2-table":
        # Unequal D2 reaches cb00.  $032578[0] -> $0326AC; its second
        # word is index 8, selecting pointer $032F26 (five records).
        put16(work, A6_FRAME - 0x1A, 0)
        put16(work, A6_FRAME - 0x04, 1)
    elif selection == "d2-table-list32f78-d2-4":
        # Live transition form: unequal D2=4 reaches cb00, where
        # $03257C->$0326B2->$000C selects immutable list $032F78.  The
        # selector skips cb0e, so D0 and D1 must remain untouched.
        put16(work, A6_FRAME - 0x1A, 4)
        put16(work, A6_FRAME - 0x04, 8)
        put16(work, A6_FRAME - 0x18, 0x0014)
        put16(work, A6_FRAME - 0x16, 3)
        put16(work, A6_FRAME - 0x14, 0)
        put32(work, A6_FRAME - 0x12, 0x000326C6)
    elif selection == "d2-table-list32fca-d2-8":
        # Live transition form: unequal D2=8 reaches cb00, where
        # $032580->$0326BC->$0010 selects immutable list $032FCA.  Use the
        # hostile frame values from the capture to prove they are ignored.
        put16(work, A6_FRAME - 0x1A, 8)
        put16(work, A6_FRAME - 0x04, 0x00AC)
        put16(work, A6_FRAME - 0x18, 0x000C)
        put16(work, A6_FRAME - 0x16, 4)
        put16(work, A6_FRAME - 0x14, 7)
        put32(work, A6_FRAME - 0x12, 0x000329F4)
    elif selection == "frame-pointer":
        # Equal D2, non-positive D0, non-negative D1 loads A0 from the
        # frame.  $0326AE contains index 8, again selecting $032F26.
        put16(work, A6_FRAME - 0x1A, 0x0033)
        put16(work, A6_FRAME - 0x04, 0x0033)
        put16(work, A6_FRAME - 0x18, 0x7777)
        put16(work, A6_FRAME - 0x16, 1)
        put16(work, A6_FRAME - 0x14, 2)
        put32(work, A6_FRAME - 0x12, 0x000326AE)
    elif selection == "d1-negative":
        # Equal D2, non-positive D0, then negative D1 returns to cb00.
        put16(work, A6_FRAME - 0x1A, 0)
        put16(work, A6_FRAME - 0x04, 0)
        put16(work, A6_FRAME - 0x16, 1)
        put16(work, A6_FRAME - 0x14, 0)
    else:
        raise ValueError(f"unknown selection {selection!r}")

    # MAME begins after a real BSR has pushed RETURN_PC.  The native entry
    # begins at CALLER_SP and materializes its $00FF sentinel itself.
    put32(work, CALLER_SP - 4, RETURN_PC)
    work[RETURN_PC & 0xFFFF : (RETURN_PC & 0xFFFF) + 2] = bytes.fromhex("60fe")
    return base.Case(name, regs, sr, bytes(work))


def make_cases() -> list[base.Case]:
    return [
        build_case(
            "production-list-32f78-normal-attr20",
            0xCAF600,
            selection="direct-index",
            mirrored=False,
            wide_attribute=False,
            table_index=0x000C,
        ),
        build_case(
            "production-list-32f78-mirrored-attr40",
            0xCAF605,
            selection="direct-index",
            mirrored=True,
            wide_attribute=True,
            table_index=0x000C,
        ),
        build_case(
            "production-list-32f78-index-0124",
            0xCAF606,
            selection="direct-index",
            mirrored=True,
            wide_attribute=False,
            table_index=0x0124,
        ),
        build_case(
            "production-list-32f78-negative-d1",
            0xCAF607,
            selection="d1-negative-list32f78",
            mirrored=False,
            wide_attribute=True,
        ),
        build_case(
            "production-list-32f78-frame-pointer",
            0xCAF608,
            selection="frame-pointer-list32f78",
            mirrored=True,
            wide_attribute=True,
        ),
        build_case(
            "production-list-32fca-mirrored-attr40",
            0xCAF601,
            selection="direct-index",
            mirrored=True,
            wide_attribute=True,
            table_index=0x0010,
        ),
        build_case(
            "production-list-32fca-normal-attr20",
            0xCAF609,
            selection="direct-index",
            mirrored=False,
            wide_attribute=False,
            table_index=0x0010,
        ),
        build_case(
            "production-list-32fca-index-0014",
            0xCAF60A,
            selection="direct-index",
            mirrored=True,
            wide_attribute=False,
            table_index=0x0014,
        ),
        build_case(
            "production-list-32fca-negative-d1-d2-8",
            0xCAF60B,
            selection="d1-negative-list32fca-d2-8",
            mirrored=False,
            wide_attribute=True,
        ),
        build_case(
            "production-list-32fca-frame-pointer-d2-8",
            0xCAF60C,
            selection="frame-pointer-list32fca-d2-8",
            mirrored=True,
            wide_attribute=True,
        ),
        build_case(
            "production-list-32f78-d2-table-d2-4",
            0xCAF60D,
            selection="d2-table-list32f78-d2-4",
            mirrored=True,
            wide_attribute=False,
        ),
        build_case(
            "production-list-32fca-d2-table-d2-8",
            0xCAF60E,
            selection="d2-table-list32fca-d2-8",
            mirrored=False,
            wide_attribute=True,
        ),
        build_case(
            "d2-table-list-32f26",
            0xCAF602,
            selection="d2-table",
            mirrored=False,
            wide_attribute=True,
        ),
        build_case(
            "frame-pointer-list-32f26",
            0xCAF603,
            selection="frame-pointer",
            mirrored=True,
            wide_attribute=False,
        ),
        build_case(
            "negative-d1-falls-back-to-d2-table",
            0xCAF604,
            selection="d1-negative",
            mirrored=False,
            wide_attribute=False,
        ),
    ]


def mame_result(session: base.MameSession, case: base.Case) -> base.Result:
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
        pc=RETURN_PC,
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
    result_regs = {
        name: regs[name] & 0xFFFFFFFF for name in base.REG_NAMES[:-1]
    }
    result_regs["A7"] = regs["SP"] & 0xFFFFFFFF
    return base.Result(
        result_regs,
        regs["SR"] & 0xFFFF,
        bytes.fromhex(captured["hex"]),
    )


def prepare_nexen_case(
    m: base.McpSession, nat: Path, case: base.Case
) -> None:
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
    base.write_u16(m, 0x40, NATIVE_RETURN & 0xFFFF)
    base.write_u16(m, 0x42, 0x00FF)
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


def nexen_result(
    m: base.McpSession,
    nat: Path,
    case: base.Case,
    *,
    trace: bool = False,
    walk: bool = False,
) -> base.Result:
    prepare_nexen_case(m, nat, case)

    esc3 = ROOT / "src/escbank3.sym"
    esc6 = ROOT / "src/escbank6.sym"
    esc7 = ROOT / "src/escbank7.sym"
    route_addresses = {
        "fallback": symbol_address(esc3, 0x97, "hcaf6_fallback"),
        "const_32f78": symbol_address(esc6, 0x95, "hcaf6_const_list"),
        "const_32fca": symbol_address(esc7, 0x9D, "hcaf6_32fca"),
    }
    if "32fca" in case.name:
        expected_route = "const_32fca"
    elif "32f78" in case.name:
        expected_route = "const_32f78"
    else:
        expected_route = "fallback"
    route_address = route_addresses[expected_route]

    # Nexen's run-until helper can return on any simultaneously armed execution
    # hook, and a hot SA-1 may advance to the native-return spin before the MCP
    # pause is observed.  Probe the expected route in its own replay with
    # exactly one hook.  Then reload the pristine case and run the semantic
    # capture with exactly one completion hook.  This keeps route evidence from
    # truncating the state comparison.
    route_hook = m.add_exec_hook(route_address, cpu_type="Sa1")
    m.drain_notifications(timeout=0.05)
    base.set_sa1_pc(m, ENTRY_NATIVE)
    route_hit = m.run_until(max_frames=120, hook_handle=route_hook)
    m.pause()
    route_state = m.get_cpu_state("Sa1")
    route_actual = (
        (int(route_state.get("k", 0)) << 16)
        | int(route_state.get("pc", 0))
    )
    m.remove_hook(route_hook)
    route_observed = (route_hit or {}).get("reason") == "hookFired"
    if not route_observed:
        raise RuntimeError(
            f"Nexen missed expected {expected_route} route for {case.name}: "
            f"hit={route_hit!r} stop=${route_actual:06X} target=${route_address:06X}"
        )

    prepare_nexen_case(m, nat, case)
    hook = m.add_exec_hook(NATIVE_RETURN, cpu_type="Sa1")
    m.drain_notifications(timeout=0.05)
    base.set_sa1_pc(m, ENTRY_NATIVE)
    start_cycles = int(m.get_cpu_state("Sa1")["cycleCount"])
    hit = m.run_until(max_frames=120, hook_handle=hook)
    m.pause()
    return_state = m.get_cpu_state("Sa1")
    return_actual = (
        (int(return_state.get("k", 0)) << 16)
        | int(return_state.get("pc", 0))
    )
    print(
        json.dumps(
            {
                "event": "route_probe",
                "case": case.name,
                "route": expected_route,
                "target_pc": f"{route_address:06X}",
                "stop_pc": f"{route_actual:06X}",
                "observed": route_observed,
            },
            sort_keys=True,
        ),
        flush=True,
    )
    if (hit or {}).get("reason") != "hookFired" or return_actual != NATIVE_RETURN:
        pc68k = int.from_bytes(
            bytes(m.read_memory(base.DP_SPACE, 0x40, 4)), "little"
        )
        raise RuntimeError(
            f"Nexen did not return for {case.name}: {hit!r}; "
            f"sa1=${return_actual:06X} "
            f"sp=${int(return_state.get('sp', 0)):04X} pc68k=${pc68k:08X} "
            f"a7=${m.read_u16(0x3E, base.DP_SPACE):04X}"
            f"{m.read_u16(0x3C, base.DP_SPACE):04X} "
            f"d7=${m.read_u16(0x1C, base.DP_SPACE):04X}"
        )
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
    result = base.Result(
        result_regs,
        (case.sr & ~base.CCR_MASK) | ccr,
        bytes(m.read_memory(base.SNES_SPACE, 0x400000, 0x4000)),
        end_cycles - start_cycles,
    )
    result.route_probe = {
        "route": expected_route,
        "target_pc": route_address,
        "stop_pc": route_actual,
        "observed": route_observed,
    }
    return result


def compare(case: base.Case, arcade: base.Result, console: base.Result) -> dict:
    reg_mismatches = {
        name: {"mame": arcade.regs[name], "nexen": console.regs[name]}
        for name in base.REG_NAMES
        if arcade.regs[name] != console.regs[name]
    }
    # The callable native hierarchy uses synthetic outer and inner return PCs;
    # those dead stack residues intentionally differ from the real 68K BSRs.
    outer_return = (case.regs["A7"] - 4) & 0xFFFF
    inner_return = (case.regs["A7"] - 8) & 0xFFFF
    excluded = set(range(inner_return, outer_return + 4))
    offsets = [
        offset
        for offset, (left, right) in enumerate(zip(arcade.work, console.work))
        if offset not in excluded and left != right
    ]
    ccr_mismatch = (arcade.sr & base.CCR_MASK) != (
        console.sr & base.CCR_MASK
    )
    route_probe = getattr(console, "route_probe", {})
    if "32fca" in case.name:
        expected_route = "const_32fca"
    elif "32f78" in case.name:
        expected_route = "const_32f78"
    else:
        expected_route = "fallback"
    route_ok = route_probe.get("route") == expected_route and bool(
        route_probe.get("observed")
    )
    return {
        "case": case.name,
        "result": (
            "green"
            if not reg_mismatches and not ccr_mismatch and not offsets and route_ok
            else "red"
        ),
        "reg_mismatches": reg_mismatches,
        "mame_ccr": arcade.sr & base.CCR_MASK,
        "nexen_ccr": console.sr & base.CCR_MASK,
        "work_mismatch_count": len(offsets),
        "work_mismatch_first": [f"F0{offset:04X}" for offset in offsets[:24]],
        "nexen_cycles": console.cycles,
        "route_probe": route_probe,
        "expected_route": expected_route,
        "route_ok": route_ok,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    parser.add_argument("--nexen", type=Path, default=base.DEFAULT_NEXEN)
    parser.add_argument("--nat", type=Path, default=base.DEFAULT_NAT)
    parser.add_argument("--port", type=int, default=7610)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--case", action="append", dest="case_names")
    parser.add_argument("--trace", action="store_true")
    parser.add_argument("--walk", action="store_true")
    args = parser.parse_args()
    for path in (args.rom, args.nexen, args.nat):
        if not path.is_file():
            parser.error(f"missing required input: {path}")

    cases = make_cases()
    if args.case_names:
        wanted = set(args.case_names)
        cases = [case for case in cases if case.name in wanted]
        missing = wanted - {case.name for case in cases}
        if missing:
            parser.error(f"unknown case(s): {', '.join(sorted(missing))}")
    events: list[dict] = []
    provenance = {
        "event": "provenance",
        "scope": "function-local CAF6/CB9E MAME/Nexen differential; not fps",
        "mame": "/snap/bin/mame 0.287",
        "nexen": str(args.nexen.resolve()),
        "nexen_sha256": base.sha256(args.nexen),
        "rom": str(args.rom.resolve()),
        "rom_sha256": base.sha256(args.rom),
        "nat": str(args.nat.resolve()),
        "nat_sha256": base.sha256(args.nat),
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

    with base.McpSession(
        rom=str(args.rom),
        mesen=str(args.nexen),
        cwd=ROOT,
        port=args.port,
        boot_wait=8.0,
        socket_timeout=120.0,
        stderr_log=ROOT / "build/playability-20260719/caf6-nexen.stderr.log",
    ) as nexen:
        for case in cases:
            console = nexen_result(
                nexen, args.nat, case, trace=args.trace, walk=args.walk
            )
            event = {
                "event": "case",
                **compare(case, arcade_results[case.name], console),
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
        args.output.write_text(
            "".join(json.dumps(event, sort_keys=True) + "\n" for event in events)
        )
    return 0 if green == len(cases) else 1


if __name__ == "__main__":
    raise SystemExit(main())
