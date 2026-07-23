#!/usr/bin/env python3
"""Organic MAME/Nexen differential for the one-shot native fan-out.

Capture the production-shaped entry state for every new fan-out root from the
last diagnostic ROM that still interpreted those roots.  MAME executes each
bounded original span, while Nexen starts the corresponding bank-$9E body and
stops at the same pre-instruction seam.  Every D/A register, X/N/Z/V/C,
interrupt mask, and byte of mapped low 16 KiB work RAM is compared.

The $008B9C resume fixture is also replayed with its two frame-local counters
set immediately before the inner rollover and final outer return.  Those two
cases cover the otherwise rare $8B7A -> $8BA2 -> $8B62 edges and the real RTS
back to $007786.  Separate probes prove each root is reachable through the
production xlat route.  This is bounded semantic evidence, never FPS evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from dataclasses import dataclass, replace
from pathlib import Path

import validate_d96_hle as base
import validate_1f2e4_native as live


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CAPTURE_ROM = (
    ROOT
    / "build/playability-20260720/11752-direct-charge-diagnostic-v1/interp.sfc"
)
DEFAULT_ROM = (
    ROOT / "build/playability-20260720/1c9ae-empty-diagnostic-v4/interp.sfc"
)
DEFAULT_STATE = (
    ROOT
    / "build/playability-20260720/"
    "11752-direct-charge-production-v1-coldboot-immediate-v1/"
    "gameplay_detected.mss"
)
DEFAULT_SYM = ROOT / "src/escbank8.sym"
FULL_WORK_SIZE = 0x10000
MAPPED_WORK_SIZE = 0x4000
CAPTURE_BUTTONS = 0x82
DEBUG_SPIN = 0x00E2CF
OJMP_HOOK = 0x00D1B3
CCR_MASK = base.CCR_MASK


@dataclass(frozen=True)
class Span:
    name: str
    entry_pc: int
    entry_symbol: str
    exit_pc: int
    # MAME's exposed PC is a prefetch address.  CURPC must equal exit_pc.
    mame_prefetch_pc: int
    # A native symbol here means stop at that body before executing it.  The
    # default stop is the diagnostic fetched-PC freeze at exit_pc.
    native_stop_symbol: str | None = None
    native_stop_address: int | None = None
    changes_mask_to_four: bool = False
    # Validation-only sequentialization for terminal TRAP/JSR instructions.
    # Returning NOP words from a MAME read tap lets the four-byte-ahead
    # prefetch observe CURPC at the desired pre-instruction seam.
    mame_nop_bytes: int = 2
    mame_spin_at_exit: bool = False


SPANS = (
    Span("task-76b6", 0x0076B6, "entry_76b6", 0x0076D2, 0x0076D6),
    Span("task-76d4", 0x0076D4, "entry_76d4", 0x0076EA, 0x0076EE),
    Span("task-76ec", 0x0076EC, "entry_76ec", 0x007702, 0x007706),
    Span("task-7704", 0x007704, "entry_7704", 0x00771A, 0x00771E),
    Span("task-771c", 0x00771C, "entry_771c", 0x007732, 0x007736),
    # Stop immediately before the JSR $91E.  This covers all three preceding
    # $8FA calls and their stack cleanup.  $91E has its own independent MAME
    # differential, and $8B46 is covered below from its organic post-JSR entry.
    Span(
        "task-7734-to-jsr-91e",
        0x007734,
        "entry_7734",
        0x00777C,
        0x007780,
        native_stop_address=0x9EAE8A,
    ),
    Span(
        "task-1e71e",
        0x01E71E,
        "entry_1e71e",
        0x01E7BE,
        0x01E7C2,
        changes_mask_to_four=True,
    ),
    Span("task-24b5a", 0x024B5A, "entry_24b5a", 0x024BC0, 0x024BC4),
    Span("task-2427c", 0x02427C, "entry_2427c", 0x02429A, 0x02429E),
    Span("8b46-first-yield", 0x008B46, "entry_8b46t", 0x008B9A, 0x008B9E),
    Span("8b9c-next-yield", 0x008B9C, "entry_8b9c", 0x008B9A, 0x008B9E),
)


MAME_IRQ_ISOLATION_LUA = """
MCP_FANOUT_SR_TAPS = MCP_FANOUT_SR_TAPS or {}
for _, tap in ipairs(MCP_FANOUT_SR_TAPS) do tap:remove() end
MCP_FANOUT_SR_TAPS = {}
MCP_FANOUT_SR_READS = 0
local p = M.devices[\":maincpu\"].spaces[\"program\"]
local function preserve_mask7(offset, data, mask)
    MCP_FANOUT_SR_READS = MCP_FANOUT_SR_READS + 1
    return 0xf7ff
end
MCP_FANOUT_SR_TAPS[1] = p:install_read_tap(
    0x1e778, 0x1e779, \"mcp_fanout_sr_first\", preserve_mask7)
MCP_FANOUT_SR_TAPS[2] = p:install_read_tap(
    0x1e7b6, 0x1e7b7, \"mcp_fanout_sr_second\", preserve_mask7)
return #MCP_FANOUT_SR_TAPS
"""


@dataclass
class Case:
    name: str
    span: Span
    regs: dict[str, int]
    sr: int
    work: bytes
    tick: int
    frame: int
    capture_frames_advanced: int


@dataclass
class Result:
    regs: dict[str, int]
    sr: int
    work: bytes
    cycles: int | None = None
    physical_mask: int | None = None


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def symbol_addresses(path: Path) -> dict[str, int]:
    result: dict[str, int] = {}
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        fields = raw.split()
        if len(fields) < 2:
            continue
        if ":" not in fields[0]:
            continue
        bank, offset = fields[0].split(":", 1)
        if bank == "00":
            result[fields[1]] = 0x9E0000 | int(offset, 16)
    required = {
        span.entry_symbol for span in SPANS
    } | {
        span.native_stop_symbol
        for span in SPANS
        if span.native_stop_symbol is not None
    }
    missing = sorted(required - result.keys())
    if missing:
        raise RuntimeError(f"missing bank-$9E symbols in {path}: {missing}")
    return result


def capture_case(
    m: base.McpSession,
    state: Path,
    span: Span,
) -> Case:
    """Freeze the retained interpreter before span.entry_pc executes."""

    m.pause()
    m.load_state(str(state))
    m.pause()
    m.tool("set_input", {"port": 0, "buttons": CAPTURE_BUTTONS, "hold": True})
    live.write_u16(m, 0x0710, span.entry_pc & 0xFFFF)
    live.write_u16(m, 0x0712, 0)
    live.write_u16(m, 0x0714, 0)
    live.write_u16(m, 0x0716, (span.entry_pc >> 16) & 0xFF)
    live.write_u16(m, 0x0718, 0xFFF8)
    live.write_u16(m, 0x0730, 0x5A5A)
    hook = m.add_exec_hook(DEBUG_SPIN, cpu_type="Sa1")
    m.drain_notifications(timeout=0.05)
    try:
        hit, frames_advanced = live.run_to_hook(m, hook, attempts=16)
        m.pause()
    finally:
        m.remove_hook(hook)
    observed_pc = live.read_u16(m, 0x40) | (
        (live.read_u16(m, 0x42) & 0xFF) << 16
    )
    if (
        (hit or {}).get("reason") != "hookFired"
        or not live.read_u16(m, 0x0712)
        or observed_pc != span.entry_pc
    ):
        raise RuntimeError(
            f"{span.name}: retained interpreter did not freeze at "
            f"${span.entry_pc:06X} after {frames_advanced} frames: "
            f"hit={hit!r}, marker={live.read_u16(m, 0x0712)}, "
            f"pc=${observed_pc:06X}"
        )
    regs = live.captured_regs(m)
    work = bytes(m.read_memory(base.SNES_SPACE, 0x400000, FULL_WORK_SIZE))
    return Case(
        name=span.name,
        span=span,
        regs=regs,
        sr=live.captured_sr(m),
        work=work,
        tick=live.work_be16(work, 0x1C56),
        frame=int(m.get_state().get("frameCount", 0)),
        capture_frames_advanced=frames_advanced,
    )


def put_be16(work: bytearray, offset: int, value: int) -> None:
    offset &= 0xFFFF
    work[offset] = (value >> 8) & 0xFF
    work[(offset + 1) & 0xFFFF] = value & 0xFF


def put_be32(work: bytearray, offset: int, value: int) -> None:
    for index in range(4):
        work[(offset + index) & 0xFFFF] = (value >> (24 - index * 8)) & 0xFF


def add_8b9c_edge_cases(cases: list[Case]) -> None:
    source = next(case for case in cases if case.span.entry_pc == 0x008B9C)
    a6 = source.regs["A6"] & 0xFFFFFF
    if (a6 >> 16) != 0xF0:
        raise RuntimeError(f"organic $008B9C A6 is not work RAM: ${a6:06X}")

    rollover_work = bytearray(source.work)
    put_be16(rollover_work, a6 - 4, 2)
    put_be16(rollover_work, a6 - 6, 0)
    cases.append(
        replace(
            source,
            name="8b9c-inner-rollover",
            work=bytes(rollover_work),
        )
    )

    final_work = bytearray(source.work)
    put_be16(final_work, a6 - 4, 2)
    put_be16(final_work, a6 - 6, 15)
    # The organic tick-276 caller left a native $FA:DD0D continuation on the
    # emulated stack.  The one-shot $007734 caller under test uses the genuine
    # arcade return $007786.  Install that exact return for both oracles.
    put_be32(final_work, a6 + 4, 0x007786)
    final_span = replace(
        source.span,
        name="8b9c-final-return",
        exit_pc=0x007786,
        mame_prefetch_pc=0x00778A,
        mame_nop_bytes=0,
    )
    cases.append(
        replace(
            source,
            name="8b9c-final-return",
            span=final_span,
            work=bytes(final_work),
        )
    )


def load_cases(fixture_dir: Path) -> list[Case]:
    """Load the exact organic fixtures retained by an earlier harness run."""

    cases: list[Case] = []
    for index, span in enumerate(SPANS):
        matches = sorted(fixture_dir.glob(f"case-{index:02d}-*.json"))
        if len(matches) != 1:
            raise RuntimeError(
                f"expected one retained fixture case-{index:02d} in "
                f"{fixture_dir}, found {len(matches)}"
            )
        metadata_path = matches[0]
        work_path = metadata_path.with_suffix(".work.bin")
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        work = work_path.read_bytes()
        if len(work) != FULL_WORK_SIZE:
            raise RuntimeError(
                f"retained fixture {work_path} is {len(work)} bytes, "
                f"expected {FULL_WORK_SIZE}"
            )
        expected_hash = metadata["work_sha256"]
        if hashlib.sha256(work).hexdigest() != expected_hash:
            raise RuntimeError(f"retained fixture hash mismatch: {work_path}")
        if metadata["entry_pc"] != f"{span.entry_pc:06X}":
            raise RuntimeError(
                f"retained fixture entry mismatch in {metadata_path}: "
                f"{metadata['entry_pc']} != {span.entry_pc:06X}"
            )
        cases.append(
            Case(
                name=span.name,
                span=span,
                regs={
                    name: int(value)
                    for name, value in metadata["regs"].items()
                },
                sr=int(metadata["sr"]),
                work=work,
                tick=int(metadata["tick"]),
                frame=int(metadata["frame"]),
                capture_frames_advanced=int(metadata["capture_frames_advanced"]),
            )
        )
    return cases


def mame_result(session: base.MameSession, case: Case) -> Result:
    session.pause()
    session.exec_lua("MCP_FANOUT_SR_READS = 0; return true")
    session.write_block(0xF00000, case.work[:MAPPED_WORK_SIZE])
    for name in base.REG_NAMES[:-1]:
        session.set_reg(name, case.regs[name])
    entry_sp = case.regs["A7"] & 0xFFFFFF
    session.set_reg("USP", entry_sp)
    session.set_reg("SP", entry_sp)
    # Suppress unrelated held VBLANK delivery.  The two $01E71E ANDI reads
    # are tapped above so its intended mask-four result can be reconstructed.
    session.set_reg("SR", case.sr | 0x0700)
    session.set_reg("PC", case.span.entry_pc)
    if case.span.mame_spin_at_exit:
        installed = session.exec_lua(
            "if MCP_FANOUT_EXIT_NOP then MCP_FANOUT_EXIT_NOP:remove() end "
            "MCP_FANOUT_EXIT_NOP = "
            "M.devices[':maincpu'].spaces['program']:install_read_tap("
            f"0x{case.span.exit_pc:06X}, 0x{case.span.exit_pc + 1:06X}, "
            "'mcp_fanout_exit_spin', "
            "function(offset, data, mask) return 0x60FE end); return true"
        )
        if not installed:
            raise RuntimeError(f"{case.name}: failed to install terminal spin tap")
    elif case.span.mame_nop_bytes:
        installed = session.exec_lua(
            "if MCP_FANOUT_EXIT_NOP then MCP_FANOUT_EXIT_NOP:remove() end "
            "MCP_FANOUT_EXIT_NOP = "
            "M.devices[':maincpu'].spaces['program']:install_read_tap("
            f"0x{case.span.exit_pc:06X}, "
            f"0x{case.span.exit_pc + case.span.mame_nop_bytes - 1:06X}, "
            "'mcp_fanout_exit_nop', "
            "function(offset, data, mask) return 0x4E71 end); return true"
        )
        if not installed:
            raise RuntimeError(f"{case.name}: failed to install terminal NOP tap")
    try:
        captured = session.cmd(
            "capture_at_pc",
            pc=(
                case.span.exit_pc
                if case.span.mame_spin_at_exit
                else case.span.mame_prefetch_pc
            ),
            addr=0xF00000,
            len=MAPPED_WORK_SIZE,
            nth=2 if case.span.mame_spin_at_exit else 1,
            maxFrames=120,
            timeout=120,
        )
    finally:
        if case.span.mame_spin_at_exit or case.span.mame_nop_bytes:
            session.exec_lua(
                "if MCP_FANOUT_EXIT_NOP then MCP_FANOUT_EXIT_NOP:remove(); "
                "MCP_FANOUT_EXIT_NOP=nil end; return true"
            )
    if not captured.get("registers"):
        raise RuntimeError(
            f"MAME did not reach {case.name} seam "
            f"${case.span.exit_pc:06X}: {captured!r}"
        )
    regs = captured["registers"]
    curpc = regs.get("CURPC", -1) & 0xFFFFFF
    if curpc != case.span.exit_pc:
        raise RuntimeError(
            f"{case.name}: MAME prefetch seam requested "
            f"${case.span.mame_prefetch_pc:06X} but CURPC=${curpc:06X}, "
            f"expected ${case.span.exit_pc:06X}"
        )
    sr_reads = int(session.exec_lua("return MCP_FANOUT_SR_READS or 0"))
    if case.span.changes_mask_to_four and sr_reads < 2:
        raise RuntimeError(
            f"{case.name}: expected at least the root's two isolated SR reads, "
            f"observed {sr_reads}"
        )
    result_regs = {
        name: regs[name] & 0xFFFFFFFF for name in base.REG_NAMES[:-1]
    }
    result_regs["A7"] = regs["SP"] & 0xFFFFFFFF
    architectural_mask = (
        4 if case.span.changes_mask_to_four else ((case.sr >> 8) & 7)
    )
    result_sr = (
        (regs["SR"] & 0xFFFF & ~0x0700) | (architectural_mask << 8)
    )
    return Result(
        regs=result_regs,
        sr=result_sr,
        work=bytes.fromhex(captured["hex"]),
        physical_mask=(regs["SR"] >> 8) & 7,
    )


def prepare_console(
    m: base.McpSession,
    nat: Path,
    case: Case,
    *,
    target_pc: int,
) -> None:
    m.load_state(str(nat))
    m.pause()
    reg_blob = b"".join(base.le32(case.regs[name]) for name in base.REG_NAMES)
    m.write_memory(base.DP_SPACE, 0x00, reg_blob.hex())
    for offset in range(0, FULL_WORK_SIZE, 0x4000):
        m.write_memory(
            base.SNES_SPACE,
            0x400000 + offset,
            case.work[offset : offset + 0x4000].hex(),
        )
    live.park_snes_cpu(m)

    flags = case.sr & CCR_MASK
    live.write_u16(m, 0x6E, flags & 1)
    live.write_u16(m, 0x72, (flags >> 1) & 1)
    live.write_u16(m, 0x60, (flags >> 2) & 1)
    live.write_u16(m, 0x70, (flags >> 3) & 1)
    live.write_u16(m, 0xA2, (flags >> 4) & 1)
    live.write_u16(m, 0x7C, 7)
    live.write_u16(m, 0x40, case.span.entry_pc & 0xFFFF)
    live.write_u16(m, 0x42, (case.span.entry_pc >> 16) & 0xFF)
    live.write_u16(m, 0x4A, 0)
    live.write_u16(m, 0x4C, 0)
    live.write_u16(m, 0xA4, case.regs["A7"] & 0xFFFF)
    live.write_u16(m, 0xA6, (case.regs["A7"] >> 16) & 0xFFFF)
    live.write_u16(m, 0xA8, 1)
    live.write_u16(m, 0xAA, 0)
    live.write_u16(m, 0xAC, 0x7000)
    live.write_u16(m, 0x0702, 0)
    live.write_u16(m, 0x0704, 1)
    live.write_u16(m, 0x0710, target_pc & 0xFFFF)
    live.write_u16(m, 0x0712, 0)
    live.write_u16(m, 0x0714, 0)
    live.write_u16(m, 0x0716, (target_pc >> 16) & 0xFF)
    live.write_u16(m, 0x0718, 0xFFF8)
    live.write_u16(m, 0x071A, 1)
    live.write_u16(m, 0x072E, 0)
    live.write_u16(m, 0x0730, 0)
    live.write_u16(m, 0x0734, 0)
    live.write_u16(m, 0x0736, 0)
    live.write_u16(m, 0x0738, 0)
    live.write_u16(m, 0x073A, 1)
    live.write_u16(m, 0x073C, 0)


def console_result(
    m: base.McpSession,
    nat: Path,
    case: Case,
    symbols: dict[str, int],
) -> Result:
    prepare_console(m, nat, case, target_pc=case.span.exit_pc)
    native_start = symbols[case.span.entry_symbol]
    native_stop = (
        case.span.native_stop_address
        if case.span.native_stop_address is not None
        else (
            symbols[case.span.native_stop_symbol]
            if case.span.native_stop_symbol is not None
            else DEBUG_SPIN
        )
    )
    stop_patch_offset: int | None = None
    stop_patch_original: bytes | None = None
    if case.span.native_stop_address is not None:
        if (native_stop >> 16) != 0x9E or (native_stop & 0xFFFF) < 0x8000:
            raise RuntimeError(
                f"unsupported stable-stop address ${native_stop:06X}"
            )
        stop_patch_offset = 0x2F0000 + (native_stop & 0x7FFF)
        stop_patch_original = bytes(
            m.read_memory("snesPrgRom", stop_patch_offset, 2)
        )
        expected = args_rom_bytes = bytes.fromhex("a982")
        if stop_patch_original != expected:
            raise RuntimeError(
                f"{case.name}: unexpected bridge bytes at ROM "
                f"${stop_patch_offset:06X}: {stop_patch_original.hex()} "
                f"!= {args_rom_bytes.hex()}"
            )
        # Stable debugger-only pre-instruction seam.  BRA does not alter any
        # emulated 68K state, and the production bytes are restored below.
        m.write_memory("snesPrgRom", stop_patch_offset, "80fe")
    try:
        live.set_sa1_pc(m, native_start)
        hook = m.add_exec_hook(native_stop, cpu_type="Sa1")
        m.drain_notifications(timeout=0.05)
        start_cycles = int(m.get_cpu_state("Sa1")["cycleCount"])
        try:
            hit = m.run_until(max_frames=180, hook_handle=hook)
            m.pause()
        finally:
            m.remove_hook(hook)
        if (hit or {}).get("reason") != "hookFired":
            raise RuntimeError(
                f"Nexen did not reach {case.name} stop "
                f"${native_stop:06X}: {hit!r}"
            )
        if (
            case.span.native_stop_symbol is None
            and case.span.native_stop_address is None
        ):
            observed_pc = live.read_u16(m, 0x40) | (
                (live.read_u16(m, 0x42) & 0xFF) << 16
            )
            if not live.read_u16(m, 0x0712) or observed_pc != case.span.exit_pc:
                raise RuntimeError(
                    f"{case.name}: Nexen froze at ${observed_pc:06X}, "
                    f"expected ${case.span.exit_pc:06X}"
                )
        end_cycles = int(m.get_cpu_state("Sa1")["cycleCount"])
        physical_mask = live.read_u16(m, 0x7C) & 7
        architectural_mask = (
            physical_mask
            if case.span.changes_mask_to_four
            else ((case.sr >> 8) & 7)
        )
        result = Result(
            regs=live.captured_regs(m),
            sr=0x2000 | (architectural_mask << 8) | live.captured_ccr(m),
            work=bytes(
                m.read_memory(base.SNES_SPACE, 0x400000, MAPPED_WORK_SIZE)
            ),
            cycles=end_cycles - start_cycles,
            physical_mask=physical_mask,
        )
    finally:
        if stop_patch_offset is not None and stop_patch_original is not None:
            m.write_memory(
                "snesPrgRom", stop_patch_offset, stop_patch_original.hex()
            )
    return result


def compare(case: Case, arcade: Result, console: Result) -> dict:
    reg_mismatches = {
        name: {"mame": arcade.regs[name], "nexen": console.regs[name]}
        for name in base.REG_NAMES
        if arcade.regs[name] != console.regs[name]
    }
    work_mismatches = [
        offset
        for offset, (left, right) in enumerate(zip(arcade.work, console.work))
        if left != right
    ]
    ccr_mismatch = (arcade.sr & CCR_MASK) != (console.sr & CCR_MASK)
    mask_mismatch = ((arcade.sr >> 8) & 7) != ((console.sr >> 8) & 7)
    green = not (
        reg_mismatches or work_mismatches or ccr_mismatch or mask_mismatch
    )
    return {
        "event": "case",
        "case": case.name,
        "entry_pc": f"{case.span.entry_pc:06X}",
        "exit_pc": f"{case.span.exit_pc:06X}",
        "tick": case.tick,
        "result": "green" if green else "red",
        "reg_mismatches": reg_mismatches,
        "mame_ccr": arcade.sr & CCR_MASK,
        "nexen_ccr": console.sr & CCR_MASK,
        "mame_mask": (arcade.sr >> 8) & 7,
        "nexen_mask": (console.sr >> 8) & 7,
        "mame_physical_mask_isolated": arcade.physical_mask,
        "nexen_physical_mask": console.physical_mask,
        "work_mismatch_count": len(work_mismatches),
        "work_mismatch_first": [f"F0{x:04X}" for x in work_mismatches[:24]],
        "work_mismatch_values": [
            {
                "address": f"F0{offset:04X}",
                "mame": arcade.work[offset],
                "nexen": console.work[offset],
            }
            for offset in work_mismatches[:24]
        ],
        "nexen_cycles_local": console.cycles,
    }


def route_probe(
    m: base.McpSession,
    nat: Path,
    case: Case,
    symbols: dict[str, int],
) -> dict:
    prepare_console(m, nat, case, target_pc=case.span.exit_pc)
    live.write_u16(m, 0x40, case.span.entry_pc & 0xFFFF)
    live.write_u16(m, 0x42, (case.span.entry_pc >> 16) & 0xFF)
    live.set_sa1_pc(m, OJMP_HOOK)
    target = symbols[case.span.entry_symbol]
    hook = m.add_exec_hook(target, cpu_type="Sa1")
    m.drain_notifications(timeout=0.05)
    start = int(m.get_cpu_state("Sa1")["cycleCount"])
    try:
        hit = m.run_until(max_frames=8, hook_handle=hook)
        m.pause()
    finally:
        m.remove_hook(hook)
    fired = (hit or {}).get("reason") == "hookFired"
    return {
        "event": "route_probe",
        "entry_pc": f"{case.span.entry_pc:06X}",
        "entry_symbol": case.span.entry_symbol,
        "entry_native": f"{target:06X}",
        "route": "ojmp_hook -> production xlat",
        "result": "green" if fired else "red",
        "hook_fired": fired,
        "cycles": int(m.get_cpu_state("Sa1")["cycleCount"]) - start,
        "hit": hit,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--capture-rom", type=Path, default=DEFAULT_CAPTURE_ROM)
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--sym", type=Path, default=DEFAULT_SYM)
    parser.add_argument("--nexen", type=Path, default=base.DEFAULT_NEXEN)
    parser.add_argument("--nat", type=Path, default=base.DEFAULT_NAT)
    parser.add_argument("--port", type=int, default=7550)
    parser.add_argument(
        "--fixture-dir",
        type=Path,
        help="reuse retained case-*.json/.work.bin organic fixtures",
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    for path in (
        args.capture_rom,
        args.rom,
        args.state,
        args.sym,
        args.nexen,
        args.nat,
    ):
        if not path.is_file():
            parser.error(f"missing required input: {path}")
    if args.output.exists():
        parser.error(f"output already exists: {args.output}")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.fixture_dir is not None:
        fixture_dir = args.fixture_dir
        if not fixture_dir.is_dir():
            parser.error(f"fixture directory does not exist: {fixture_dir}")
    else:
        fixture_dir = args.output.parent / f"{args.output.stem}-fixtures"
        if fixture_dir.exists():
            parser.error(f"fixture directory already exists: {fixture_dir}")
        fixture_dir.mkdir()
    symbols = symbol_addresses(args.sym)

    events: list[dict] = []
    provenance = {
        "event": "provenance",
        "scope": (
            "organic one-shot fan-out MAME/Nexen bounded differential; all "
            "D/A registers, CCR/mask, mapped 16 KiB work RAM, production xlat "
            "route probes; not fps"
        ),
        "mame": "/snap/bin/mame 0.287",
        "nexen": str(args.nexen.resolve()),
        "nexen_sha256": sha256(args.nexen),
        "capture_rom": str(args.capture_rom.resolve()),
        "capture_rom_sha256": sha256(args.capture_rom),
        "candidate_rom": str(args.rom.resolve()),
        "candidate_rom_sha256": sha256(args.rom),
        "state": str(args.state.resolve()),
        "state_sha256": sha256(args.state),
        "nat": str(args.nat.resolve()),
        "nat_sha256": sha256(args.nat),
        "sym": str(args.sym.resolve()),
        "sym_sha256": sha256(args.sym),
        "capture_method": "PC_RING=1 fetched-PC debug freeze from retained interpreter",
        "fixture_source": (
            str(fixture_dir.resolve())
            if args.fixture_dir is not None
            else "fresh organic capture"
        ),
        "capture_input": {"port": 0, "buttons": CAPTURE_BUTTONS},
        "irq_isolation": (
            "both oracles physically mask 7; MAME read taps preserve mask 7 "
            "at $01E71E's two ANDI immediates; architectural mask 4 is reconstructed"
        ),
        "spans": [
            {
                "name": span.name,
                "entry_pc": f"{span.entry_pc:06X}",
                "entry_native": f"{symbols[span.entry_symbol]:06X}",
                "exit_pc": f"{span.exit_pc:06X}",
            }
            for span in SPANS
        ],
        "time": time.time(),
    }
    events.append(provenance)
    print(json.dumps(provenance, sort_keys=True), flush=True)

    cases: list[Case] = []
    if args.fixture_dir is not None:
        cases = load_cases(fixture_dir)
    else:
        with base.McpSession(
            rom=str(args.capture_rom),
            mesen=str(args.nexen),
            cwd=ROOT,
            port=args.port,
            boot_wait=8.0,
            socket_timeout=180.0,
            stderr_log=fixture_dir / "capture.nexen.stderr.log",
        ) as capture:
            for span in SPANS:
                cases.append(capture_case(capture, args.state, span))

    for index, case in enumerate(cases):
        span = case.span
        event = {
            "event": "fixture",
            "case": case.name,
            "entry_pc": f"{span.entry_pc:06X}",
            "tick": case.tick,
            "frame": case.frame,
            "capture_frames_advanced": case.capture_frames_advanced,
            "sr": case.sr,
            "regs": case.regs,
            "work_sha256": hashlib.sha256(case.work).hexdigest(),
        }
        events.append(event)
        print(json.dumps(event, sort_keys=True), flush=True)
        if args.fixture_dir is None:
            stem = f"case-{index:02d}-{case.name}"
            (fixture_dir / f"{stem}.work.bin").write_bytes(case.work)
            (fixture_dir / f"{stem}.json").write_text(
                json.dumps(event, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )

    add_8b9c_edge_cases(cases)
    for case in cases[len(SPANS) :]:
        event = {
            "event": "synthetic_fixture",
            "case": case.name,
            "source": (
                "organic $008B9C fixture; -4(A6)/-6(A6) counters changed"
                + (
                    "; stacked native sentinel replaced by real $007786 return"
                    if case.name == "8b9c-final-return"
                    else ""
                )
            ),
            "entry_pc": f"{case.span.entry_pc:06X}",
            "exit_pc": f"{case.span.exit_pc:06X}",
            "work_sha256": hashlib.sha256(case.work).hexdigest(),
        }
        events.append(event)
        print(json.dumps(event, sort_keys=True), flush=True)

    arcade: dict[str, Result] = {}
    # Validation read taps can leave prefetched words cached across injected
    # PC resets in one long-lived MAME process.  Use a fresh oracle process per
    # stack-sensitive case, as the established task-root validators do.
    for case in cases:
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
            installed = int(mame.exec_lua(MAME_IRQ_ISOLATION_LUA))
            if installed != 2:
                raise RuntimeError(
                    f"installed {installed} MAME SR taps, expected 2"
                )
            arcade[case.name] = mame_result(mame, case)
            event = {
                "event": "mame_case",
                "case": case.name,
                "oracle_exit_pc": f"{case.span.exit_pc:06X}",
            }
            events.append(event)
            print(json.dumps(event, sort_keys=True), flush=True)
        finally:
            mame.stop()

    with base.McpSession(
        rom=str(args.rom),
        mesen=str(args.nexen),
        cwd=ROOT,
        port=args.port + 1,
        boot_wait=8.0,
        socket_timeout=180.0,
        stderr_log=args.output.parent / "differential.nexen.stderr.log",
    ) as nexen:
        for case in cases:
            console = console_result(nexen, args.nat, case, symbols)
            event = compare(case, arcade[case.name], console)
            events.append(event)
            print(json.dumps(event, sort_keys=True), flush=True)

        # One probe per unique production root; the two synthetic $8B9C cases
        # deliberately share the organic root's route proof.
        seen_entries: set[int] = set()
        for case in cases:
            if case.span.entry_pc in seen_entries:
                continue
            seen_entries.add(case.span.entry_pc)
            event = route_probe(nexen, args.nat, case, symbols)
            events.append(event)
            print(json.dumps(event, sort_keys=True), flush=True)

    checks = [
        event
        for event in events
        if event.get("event") in ("case", "route_probe")
    ]
    green = sum(event["result"] == "green" for event in checks)
    summary = {
        "event": "summary",
        "green": green,
        "red": len(checks) - green,
        "total": len(checks),
        "semantic_cases": sum(event.get("event") == "case" for event in checks),
        "route_probes": sum(
            event.get("event") == "route_probe" for event in checks
        ),
        "result": "green" if green == len(checks) else "red",
        "time": time.time(),
    }
    events.append(summary)
    print(json.dumps(summary, sort_keys=True), flush=True)
    args.output.write_text(
        "".join(json.dumps(event, sort_keys=True) + "\n" for event in events),
        encoding="utf-8",
    )
    return 0 if summary["result"] == "green" else 1


if __name__ == "__main__":
    raise SystemExit(main())
