#!/usr/bin/env python3
"""Whole-root MAME/Nexen differential for the $00C262 round-start coroutine.

MAME executes the original MC68000 body from $C262 to the fetch of its trap #5
at $C2F6.  Nexen enters the production $99:C900 wrapper and freezes at the same
emulated fetch.  The comparison covers every D/A register, CCR X/N/Z/V/C, the
complete mapped 16 KiB work-RAM window (including final-call stack residue), and
both $E0 tilemap spans including their untouched eight-byte row gaps.

Five cases, including the production low-stack class, must use the guarded
$95:A300 fast path.  A separate aliasing-stack probe must reject to the
byte-pinned generated body; it stops at that seam because executing an aliasing
synthetic call is intentionally outside the shortcut contract.  This is
function-local semantic/cycle evidence, not an end-to-end fps measurement.
"""

from __future__ import annotations

import argparse
import json
import random
import time
from pathlib import Path

import validate_render_helpers as base


ROOT = Path(__file__).resolve().parents[1]
ENTRY_PC = 0x00C262
EXIT_PC = 0x00C2F6
ENTRY_NATIVE = 0x99C900
FAST_NATIVE = 0x95A32F
FALLBACK_NATIVE = 0x99C906
DF_SPIN = 0x00E2CF
SNES_PARK_PC = 0x7EF800
VIDEO_SPAN = 0x0378
EVIDENCE_SCOPE = "whole-function $C262 MAME/Nexen differential; not fps"
MAME_BOUNDARY_METHOD = "validation-only NOP at exit trap; capture following prefetch"


def expects_fast(case: base.Case) -> bool:
    """Return whether a differential case belongs to the guarded fast domain."""

    return not case.name.startswith("fallback")


def extra_case_fields(case: base.Case, console: base.Result) -> dict:
    """Optional specialization-specific evidence attached to a case row."""

    return {}


def extra_case_green(case: base.Case, console: base.Result) -> bool:
    """Optional specialization-specific acceptance gate."""

    return True


def put32(data: bytearray, offset: int, value: int) -> None:
    data[offset:offset + 4] = base.be32(value)


def build_case(name: str, seed: int, stack: int) -> base.Case:
    rng = random.Random(seed)
    work = bytearray(rng.randrange(256) for _ in range(0x4000))
    work.extend([0xFF] * 0xC000)
    regs = {reg: rng.randrange(1 << 32) for reg in base.REG_NAMES}
    regs["A5"] = 0x00F00000
    regs["A7"] = 0x00F00000 | stack
    sr = 0x2700 | rng.randrange(0x20)
    put32(work, 0x1CBA, 0x00002742)
    return base.Case(
        name,
        ENTRY_PC,
        regs,
        sr,
        bytes(work),
        [
            (
                0xE00800,
                0x414800,
                bytes(rng.randrange(256) for _ in range(VIDEO_SPAN)),
            ),
            (
                0xE00C00,
                0x414C00,
                bytes(rng.randrange(256) for _ in range(VIDEO_SPAN)),
            ),
        ],
    )


def make_cases() -> list[base.Case]:
    return [
        build_case("fast-production-stack-a", 0xC26200, 0x3D00),
        build_case("fast-production-stack-b", 0xC26201, 0x3600),
        build_case("fast-disjoint-boundary", 0xC26202, 0x2A76),
        build_case("fast-high-stack", 0xC26203, 0x3F00),
        build_case("fast-production-low-stack", 0xC26204, 0x1500),
    ]


def make_fallback_probe() -> base.Case:
    # [A7-56,A7) overlaps the live $1CBA-$1CBD indirect target.  The guarded
    # HLE must reject before changing architectural state.
    return build_case("fallback-alias-probe", 0xC26205, 0x1CE0)


def mame_result(session: base.MameSession, case: base.Case) -> base.Result:
    session.pause()
    session.write_block(0xF00000, case.work[:0x4000])
    normalized = []
    for video_address, shadow_address, video in case.video_regions:
        session.write_block(video_address, video)
        normalized.append(
            (
                video_address,
                shadow_address,
                session.read_block(video_address, len(video)),
            )
        )
    case.video_regions = normalized

    capture_pc = EXIT_PC + 2
    tap_lines = [
        "if C262_TAPS then for _,tap in ipairs(C262_TAPS) do tap:remove() end end",
        "if C262_CALL_TAP then C262_CALL_TAP:remove(); C262_CALL_TAP=nil end",
        "if C262_BOUNDARY_TAP then C262_BOUNDARY_TAP:remove(); C262_BOUNDARY_TAP=nil end",
        "C262_TAPS = {}",
        "C262_WRITES = {}",
        "C262_BOUNDARY_WRITES = nil",
        "C262_CALLS = {}",
        'local cpu = M.devices[":maincpu"]',
        'local prog = M.devices[":maincpu"].spaces["program"]',
    ]
    for index, (video_address, _shadow_address, video) in enumerate(
        case.video_regions, 1
    ):
        tap_lines.extend(
            [
                f"C262_TAPS[{index}] = prog:install_write_tap(0x{video_address:X},",
                f'    0x{video_address + len(video) - 1:X}, "c262_write_{index}",',
                "    function(off, data, mask)",
                '      C262_WRITES[#C262_WRITES+1] = string.format("%06X,%08X,%08X", off, data, mask)',
                "      return data",
                "    end)",
            ]
        )
    if ENTRY_PC == 0x00C0BC:
        tap_lines.extend(
            [
                "C262_CALL_TAP = prog:install_read_tap(0xF01CC2, 0xF01CC5,",
                "    'c0bc_call', function(off, data, mask)",
                "      C262_CALLS[#C262_CALLS+1] = string.format(",
                "        '%08X,%08X,%08X,%08X,%08X,%08X,%08X,%06X',",
                "        cpu.state['A1'].value, cpu.state['A2'].value,",
                "        cpu.state['A7'].value, cpu.state['D0'].value,",
                "        cpu.state['D2'].value, cpu.state['D6'].value,",
                "        cpu.state['A0'].value, cpu.state['PC'].value)",
                "      return data",
                "    end)",
            ]
        )
    tap_lines.extend(
        [
            f"C262_BOUNDARY_TAP = prog:install_read_tap(0x{capture_pc:06X},",
            f"    0x{capture_pc + 1:06X}, 'c262_boundary', function(off, data, mask)",
            "      if C262_BOUNDARY_WRITES == nil then",
            "        C262_BOUNDARY_WRITES = #C262_WRITES",
            "      end",
            "      return data",
            "    end)",
        ]
    )
    tap_lines.append('return "armed"')
    session.exec_lua("\n".join(tap_lines))

    for name in base.REG_NAMES[:-1]:
        session.set_reg(name, case.regs[name])
    session.set_reg("SP", case.regs["A7"])
    session.set_reg("USP", case.regs["A7"])
    session.set_reg("SR", case.sr)
    session.set_reg("PC", ENTRY_PC)
    # MAME's arbitrary-PC hook observes the $C2F6 opcode prefetch before the
    # preceding DBRA has committed D6.w=-1.  Substitute a validation-only NOP
    # for trap #5 and capture the following $C2F8 prefetch.  NOP has no state
    # effects, so this is the committed post-function boundary.
    session.exec_lua(
        "if C262_EXIT_NOP then C262_EXIT_NOP:remove() end "
        "C262_EXIT_NOP = machine.devices[':maincpu'].spaces['program']"
        f":install_read_tap(0x{EXIT_PC:06X}, 0x{EXIT_PC + 1:06X}, "
        "'c262_exit_nop', function(offset, data, mask) return 0x4E71 end); "
        "return true"
    )
    capture = session.cmd(
        "capture_at_pc",
        pc=capture_pc,
        addr=0xF00000,
        len=0x4000,
        nth=1,
        exp_sp=case.regs["A7"] & 0xFFFFFF,
        maxFrames=30,
        timeout=30,
    )
    if not capture.get("registers"):
        raise RuntimeError(
            f"MAME did not reach ${capture_pc:06X} for {case.name}: {capture!r}"
        )
    boundary_write_count = int(
        session.exec_lua("return C262_BOUNDARY_WRITES or -1")
    )
    if boundary_write_count < 0:
        raise RuntimeError(f"MAME did not mark the exact video boundary for {case.name}")
    encoded_calls = session.exec_lua(
        'return table.concat(C262_CALLS or {}, ";")'
    )
    encoded = session.exec_lua(
        'local out = table.concat(C262_WRITES or {}, ";") '
        "if C262_TAPS then for _,tap in ipairs(C262_TAPS) do tap:remove() end; C262_TAPS=nil end "
        "if C262_CALL_TAP then C262_CALL_TAP:remove(); C262_CALL_TAP=nil end "
        "if C262_BOUNDARY_TAP then C262_BOUNDARY_TAP:remove(); C262_BOUNDARY_TAP=nil end "
        "if C262_EXIT_NOP then C262_EXIT_NOP:remove(); C262_EXIT_NOP=nil end "
        "return out"
    )
    writes: list[tuple[int, int, int]] = []
    if encoded:
        for item in encoded.split(";"):
            writes.append(tuple(int(field, 16) for field in item.split(",")))
    # emu.pause() requested inside MAME's prefetch tap takes effect
    # asynchronously.  Register/work bytes were copied synchronously by the
    # bridge, but device writes can continue briefly.  The companion boundary
    # tap above records the exact prefix before any post-boundary overshoot.
    writes = writes[:boundary_write_count]
    expected_regions = [bytearray(video) for _, _, video in case.video_regions]
    for address, data, mask in writes:
        for region_index, (video_address, _shadow_address, video) in enumerate(
            case.video_regions
        ):
            relative = address - video_address
            if mask & 0xFF00 and 0 <= relative < len(video):
                expected_regions[region_index][relative] = (data >> 8) & 0xFF
            if mask & 0x00FF and 0 <= relative + 1 < len(video):
                expected_regions[region_index][relative + 1] = data & 0xFF

    raw = capture["registers"]
    regs = {name: raw[name] & 0xFFFFFFFF for name in base.REG_NAMES[:-1]}
    regs["A7"] = raw["SP"] & 0xFFFFFFFF
    result = base.Result(
        regs,
        raw["SR"] & 0xFFFF,
        bytes.fromhex(capture["hex"]),
        [bytes(region) for region in expected_regions],
        writes,
    )
    result.call_trace = encoded_calls.split(";") if encoded_calls else []
    result.boundary_write_count = boundary_write_count
    return result


def write_u16(
    session: base.McpSession,
    address: int,
    value: int,
    space: str = base.DP_SPACE,
) -> None:
    session.write_u16(address, value & 0xFFFF, space)


def park_snes_cpu(session: base.McpSession) -> None:
    session.write_memory("snesWorkRam", SNES_PARK_PC & 0x1FFFF, "80fe")
    session.write_memory("snesMemory", 0x4200, "00")
    session.read_memory("snesMemory", 0x4210, 1)
    state = dict(session.get_cpu_state("Snes"))
    state.update(
        {
            "pc": SNES_PARK_PC & 0xFFFF,
            "k": (SNES_PARK_PC >> 16) & 0xFF,
            "d": 0,
            "dbr": 0,
            "ps": int(state.get("ps", 0)) | 0x04,
            "emulationMode": False,
        }
    )
    allowed = (
        "cpuType", "pc", "k", "a", "x", "y", "sp", "d", "dbr", "ps",
        "emulationMode",
    )
    session.tool(
        "set_cpu_state", {key: state[key] for key in allowed if key in state}
    )


def prepare_nexen_case(
    session: base.McpSession, nat: Path, case: base.Case
) -> None:
    session.load_state(str(nat))
    session.pause()
    reg_blob = b"".join(base.le32(case.regs[f"D{i}"]) for i in range(8))
    reg_blob += b"".join(base.le32(case.regs[f"A{i}"]) for i in range(8))
    session.write_memory(base.DP_SPACE, 0x00, reg_blob.hex())
    session.write_memory(base.SNES_SPACE, 0x400000, case.work[:0x4000].hex())
    for _video_address, shadow_address, video in case.video_regions:
        session.write_memory(base.SNES_SPACE, shadow_address, video.hex())
    # Renderer provenance is outside the emulated architecture.  Seed it to a
    # nonzero poison value so direct/mapped BG writers must explicitly clear it
    # before a specialization may publish a new exact-image token.
    write_u16(session, 0x41014A, 0xA55A, base.SNES_SPACE)

    flags = case.sr & base.CCR_MASK
    write_u16(session, 0x6E, flags & 1)
    write_u16(session, 0x72, (flags >> 1) & 1)
    write_u16(session, 0x60, (flags >> 2) & 1)
    write_u16(session, 0x70, (flags >> 3) & 1)
    write_u16(session, 0xA2, (flags >> 4) & 1)
    write_u16(session, 0x7C, 7)
    write_u16(session, 0x7E, 0)
    write_u16(session, 0xA4, case.regs["A7"] & 0xFFFF)
    write_u16(session, 0xA6, (case.regs["A7"] >> 16) & 0xFFFF)
    write_u16(session, 0xA8, 1)
    write_u16(session, 0xAA, 0)
    write_u16(session, 0x48, 0)
    write_u16(session, 0x4A, 0)
    write_u16(session, 0x4C, 0)
    write_u16(session, 0x4E, 0)
    write_u16(session, 0xAC, 0x7000)
    write_u16(session, 0x0718, 0xFFF8)
    write_u16(session, 0x071A, 1)
    write_u16(session, 0x0712, 0)
    write_u16(session, 0x0714, 0)
    write_u16(session, 0x0710, EXIT_PC & 0xFFFF)
    write_u16(session, 0x0716, (EXIT_PC >> 16) & 0xFF)
    write_u16(session, 0x0702, 0)
    write_u16(session, 0x0704, 1)
    write_u16(session, 0x0734, 1)
    park_snes_cpu(session)


def current_sa1_pc(session: base.McpSession) -> int:
    state = session.get_cpu_state("Sa1")
    return ((int(state.get("k", 0)) & 0xFF) << 16) | (int(state["pc"]) & 0xFFFF)


def nexen_result(
    session: base.McpSession, nat: Path, case: base.Case, spin_hook: int
) -> base.Result:
    prepare_nexen_case(session, nat, case)
    base._set_sa1_pc(session, ENTRY_NATIVE)
    start_cycles = int(session.get_cpu_state("Sa1")["cycleCount"])
    hit = session.run_until(max_frames=120, hook_handle=spin_hook)
    session.pause()
    if (hit or {}).get("reason") != "hookFired" or not session.read_u16(
        0x0712, base.DP_SPACE
    ):
        raise RuntimeError(
            f"Nexen did not freeze at ${EXIT_PC:06X} for {case.name}: "
            f"hit={hit!r}, pc=${current_sa1_pc(session):06X}"
        )
    end_cycles = int(session.get_cpu_state("Sa1")["cycleCount"])

    raw_regs = bytes(session.read_memory(base.DP_SPACE, 0x00, 0x40))
    regs = {
        name: int.from_bytes(raw_regs[index * 4:index * 4 + 4], "little")
        for index, name in enumerate(base.REG_NAMES)
    }
    ccr = (
        (1 if session.read_u16(0x6E, base.DP_SPACE) else 0)
        | ((1 if session.read_u16(0x72, base.DP_SPACE) else 0) << 1)
        | ((1 if session.read_u16(0x60, base.DP_SPACE) else 0) << 2)
        | ((1 if session.read_u16(0x70, base.DP_SPACE) else 0) << 3)
        | ((1 if session.read_u16(0xA2, base.DP_SPACE) else 0) << 4)
    )
    result = base.Result(
        regs,
        (case.sr & ~base.CCR_MASK) | ccr,
        bytes(session.read_memory(base.SNES_SPACE, 0x400000, 0x4000)),
        [
            bytes(session.read_memory(base.SNES_SPACE, shadow, len(video)))
            for _address, shadow, video in case.video_regions
        ],
        [],
        end_cycles - start_cycles,
    )
    result.renderer_provenance = session.read_u16(0x41014A, base.SNES_SPACE)
    return result


def path_probe(
    session: base.McpSession, nat: Path, case: base.Case
) -> dict[str, int]:
    expected_fast = expects_fast(case)
    target = FAST_NATIVE if expected_fast else FALLBACK_NATIVE
    prepare_nexen_case(session, nat, case)
    base._set_sa1_pc(session, ENTRY_NATIVE)
    hook = session.add_exec_hook(target, cpu_type="Sa1")
    session.drain_notifications(timeout=0.05)
    try:
        hit = session.run_until(max_frames=120, hook_handle=hook)
        session.pause()
        if (hit or {}).get("reason") != "hookFired":
            raise RuntimeError(
                f"Nexen did not take expected path ${target:06X} for {case.name}: {hit!r}"
            )
    finally:
        session.remove_hook(hook)
        session.drain_notifications(timeout=0.05)
    return {
        "fast": 1 if expected_fast else 0,
        "fallback": 0 if expected_fast else 1,
    }


def compare(case: base.Case, arcade: base.Result, console: base.Result) -> dict:
    reg_mismatches = {
        name: {"mame": arcade.regs[name], "nexen": console.regs[name]}
        for name in base.REG_NAMES
        if arcade.regs[name] != console.regs[name]
    }
    ccr_mismatch = (arcade.sr & base.CCR_MASK) != (console.sr & base.CCR_MASK)
    work_mismatches = [
        index
        for index, (left, right) in enumerate(zip(arcade.work, console.work))
        if left != right
    ]
    video_mismatches = []
    for region_index, (
        (video_address, shadow_address, _video),
        arcade_region,
        console_region,
    ) in enumerate(zip(case.video_regions, arcade.video_regions, console.video_regions)):
        for offset, (left, right) in enumerate(zip(arcade_region, console_region)):
            if left != right:
                video_mismatches.append(
                    (region_index, offset, video_address, shadow_address, left, right)
                )
    return {
        "case": case.name,
        "result": "green"
        if not reg_mismatches
        and not ccr_mismatch
        and not work_mismatches
        and not video_mismatches
        else "red",
        "reg_mismatches": reg_mismatches,
        "mame_ccr": arcade.sr & base.CCR_MASK,
        "nexen_ccr": console.sr & base.CCR_MASK,
        "work_mismatch_count": len(work_mismatches),
        "work_mismatch_first": [
            {
                "address": f"F0{offset:04X}",
                "mame": arcade.work[offset],
                "nexen": console.work[offset],
            }
            for offset in work_mismatches[:24]
        ],
        "video_mismatch_count": len(video_mismatches),
        "video_mismatch_first": [
            {
                "address": f"{video_address + offset:06X}/{shadow_address + offset:06X}",
                "mame": left,
                "nexen": right,
            }
            for _region, offset, video_address, shadow_address, left, right
            in video_mismatches[:24]
        ],
        "mame_video_write_count": len(arcade.video_writes),
        "mame_first_row_writes": [
            {"address": f"{address:06X}", "data": f"{data:08X}", "mask": f"{mask:08X}"}
            for address, data, mask in arcade.video_writes
            if 0xE00800 <= address < 0xE00840
        ][:128],
        "mame_callback_count": len(getattr(arcade, "call_trace", [])),
        "mame_callback_trace": getattr(arcade, "call_trace", []),
        "sa1_cycles_native_wrapper_to_exit_freeze": console.cycles,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, default=base.DEFAULT_ROM)
    parser.add_argument("--nexen", type=Path, default=base.DEFAULT_NEXEN)
    parser.add_argument("--nat", type=Path, default=base.DEFAULT_NAT)
    parser.add_argument("--port", type=int, default=7581)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    for path in (args.rom, args.nexen, args.nat):
        if not path.exists():
            parser.error(f"missing required input: {path}")
    rom_data = args.rom.read_bytes()
    pc_ring_call = bytes.fromhex("2081e2")
    if any(
        rom_data[offset:offset + len(pc_ring_call)] != pc_ring_call
        for offset in (0x00EB, 0x80EB)
    ):
        parser.error(
            "this differential requires a PC_RING=1 diagnostic ROM; "
            "the production ROM removes dbg_fetch and cannot reach its exit freeze"
        )
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)

    cases = make_cases()
    events: list[dict] = []
    provenance = {
        "event": "provenance",
        "scope": EVIDENCE_SCOPE,
        "mame": "/snap/bin/mame 0.287",
        "nexen": str(args.nexen.resolve()),
        "nexen_sha256": base.sha256(args.nexen),
        "rom": str(args.rom.resolve()),
        "rom_sha256": base.sha256(args.rom),
        "nat": str(args.nat.resolve()),
        "nat_sha256": base.sha256(args.nat),
        "native_wrapper": f"{ENTRY_NATIVE:06X}",
        "native_fast": f"{FAST_NATIVE:06X}",
        "native_fallback": f"{FALLBACK_NATIVE:06X}",
        "mame_boundary_method": MAME_BOUNDARY_METHOD,
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

    stderr_log = (
        args.output.with_suffix(".nexen.stderr.log")
        if args.output
        else ROOT / "build/c262-differential.nexen.stderr.log"
    )
    console: dict[str, base.Result] = {}
    with base.McpSession(
        rom=str(args.rom),
        mesen=str(args.nexen),
        cwd=str(ROOT),
        port=args.port,
        boot_wait=8.0,
        socket_timeout=120.0,
        stderr_log=stderr_log,
    ) as nexen:
        spin_hook = nexen.add_exec_hook(DF_SPIN, cpu_type="Sa1")
        for case in cases:
            console[case.name] = nexen_result(nexen, args.nat, case, spin_hook)

    path_stderr = (
        args.output.parent / f"{args.output.stem}.path.nexen.stderr.log"
        if args.output
        else ROOT / "build/c262-differential-path.nexen.stderr.log"
    )
    paths: dict[str, dict[str, int]] = {}
    fallback_probe = make_fallback_probe()
    with base.McpSession(
        rom=str(args.rom),
        mesen=str(args.nexen),
        cwd=str(ROOT),
        port=args.port + 1,
        boot_wait=8.0,
        socket_timeout=120.0,
        stderr_log=path_stderr,
    ) as nexen:
        for case in cases:
            paths[case.name] = path_probe(nexen, args.nat, case)
        fallback_trace = path_probe(nexen, args.nat, fallback_probe)

    for case in cases:
        expected_fast = expects_fast(case)
        event = {
            "event": "case",
            **compare(case, arcade[case.name], console[case.name]),
            **extra_case_fields(case, console[case.name]),
            "trace_counts": paths[case.name],
            "trace_expected": {
                "fast": 1 if expected_fast else 0,
                "fallback": 0 if expected_fast else 1,
            },
        }
        if (
            event["trace_counts"] != event["trace_expected"]
            or not extra_case_green(case, console[case.name])
        ):
            event["result"] = "red"
        events.append(event)
        print(json.dumps(event, sort_keys=True), flush=True)

    fallback_expected = {"fast": 0, "fallback": 1}
    fallback_event = {
        "event": "path_case",
        "case": fallback_probe.name,
        "scope": "guard rejection at generated-body seam; no semantic completion",
        "trace_counts": fallback_trace,
        "trace_expected": fallback_expected,
        "result": "green" if fallback_trace == fallback_expected else "red",
    }
    events.append(fallback_event)
    print(json.dumps(fallback_event, sort_keys=True), flush=True)

    green = sum(
        event.get("result") == "green"
        for event in events
        if event.get("event") == "case"
    )
    summary = {
        "event": "summary",
        "green": green,
        "red": len(cases) - green,
        "total": len(cases),
        "fallback_path_result": fallback_event["result"],
        "result": "green"
        if green == len(cases) and fallback_event["result"] == "green"
        else "red",
        "time": time.time(),
    }
    events.append(summary)
    print(json.dumps(summary, sort_keys=True), flush=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            "".join(json.dumps(event, sort_keys=True) + "\n" for event in events)
        )
    return 0 if summary["result"] == "green" else 1


if __name__ == "__main__":
    raise SystemExit(main())
