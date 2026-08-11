#!/usr/bin/env python3
"""Live-fixture MAME/Nexen differential for the native $0175A0 task root.

Capture organic sustained-gameplay inputs at the bank-$95 coroutine entry,
execute the original MC68000 root in MAME to its real terminal branch target,
and compare that state with Nexen.  Each fixture runs once with xlat return
continuations disabled (faithful interpreted tail) and once enabled (production
native continuations at $0175E8/$017612).

The gate is exact across all D/A registers, CCR X/N/Z/V/C, and the complete
mapped 16 KiB work-RAM window, including live and popped JSR/MOVEM stack bytes.
This is bounded function-semantic and local-cycle evidence, not an FPS result.

The local MAME process can have a held VBLANK IRQ6 when a fixture is injected.
Both return continuations deliberately lower the interrupt mask to four, so an
uncontrolled pending IRQ would leave the fixture and resume MAME's unrelated
organic scheduler.  The oracle run therefore starts masked at seven and uses
read taps to change only the two ``andi #$f4ff,sr`` immediates to ``#$f7ff``.
This preserves every CCR bit and all non-mask behavior while suppressing real
hardware delivery.  The reported SR mask is reconstructed from whether either
instrumented continuation executed; the original ROM bytes are never changed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path

import validate_d96_hle as base


ROOT = Path(__file__).resolve().parents[1]


def native_symbol(label: str) -> int:
    """Resolve a generated bank-$95 entry without baking in layout churn."""
    sym = ROOT / "src/escbank6.sym"
    for line in sym.read_text(encoding="utf-8").splitlines():
        fields = line.split()
        if len(fields) >= 2 and fields[1] == label:
            return 0x950000 | (int(fields[0].split(":")[-1], 16) & 0xFFFF)
    raise RuntimeError(f"{sym}: missing symbol {label}")


DEFAULT_ROM = ROOT / "build" / "interp.sfc"
DEFAULT_STATE = (
    ROOT
    / "build/playability-20260720/111a-table-active-cold-boot-v1/final.mss"
)
ENTRY_PC = 0x0175A0
ENTRY_NATIVE = native_symbol("entry_175a0")
EXIT_LOOP_PC = 0x01759E
EXIT_EMPTY_PC = 0x01757A
CONT_STATIC_PC = 0x0175E8
CONT_DYNAMIC_PC = 0x017612
DEBUG_SPIN = 0x00E2CF
SNES_PARK_PC = 0x7EF800
MAPPED_WORK_SIZE = 0x4000
FULL_WORK_SIZE = 0x10000

MAME_IRQ_ISOLATION_LUA = """
MCP_175A0_SR_TAPS = {}
MCP_175A0_SR_READS = 0
local p = M.devices[":maincpu"].spaces["program"]
local function preserve_mask7(offset, data, mask)
    MCP_175A0_SR_READS = MCP_175A0_SR_READS + 1
    return 0xf7ff
end
MCP_175A0_SR_TAPS[1] = p:install_read_tap(
    0x175ee, 0x175ef, "mcp_175a0_sr_static", preserve_mask7)
MCP_175A0_SR_TAPS[2] = p:install_read_tap(
    0x17618, 0x17619, "mcp_175a0_sr_dynamic", preserve_mask7)
return #MCP_175A0_SR_TAPS
"""


@dataclass
class LiveCase:
    name: str
    regs: dict[str, int]
    sr: int
    work: bytes
    tick: int
    exit_pc: int


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_u16(m: base.McpSession, address: int) -> int:
    return int(m.read_u16(address, base.DP_SPACE))


def write_u16(m: base.McpSession, address: int, value: int) -> None:
    m.write_u16(address, value & 0xFFFF, base.DP_SPACE)


def captured_ccr(m: base.McpSession) -> int:
    return (
        (1 if read_u16(m, 0x6E) else 0)
        | ((1 if read_u16(m, 0x72) else 0) << 1)
        | ((1 if read_u16(m, 0x60) else 0) << 2)
        | ((1 if read_u16(m, 0x70) else 0) << 3)
        | ((1 if read_u16(m, 0xA2) else 0) << 4)
    )


def captured_sr(m: base.McpSession) -> int:
    return 0x2000 | ((read_u16(m, 0x7C) & 7) << 8) | captured_ccr(m)


def captured_regs(m: base.McpSession) -> dict[str, int]:
    raw = bytes(m.read_memory(base.DP_SPACE, 0x00, 0x40))
    return {
        name: int.from_bytes(raw[index * 4 : index * 4 + 4], "little")
        for index, name in enumerate(base.REG_NAMES)
    }


def be16(work: bytes, offset: int) -> int:
    offset &= 0xFFFF
    return (work[offset] << 8) | work[(offset + 1) & 0xFFFF]


def signed16(value: int) -> int:
    return value - 0x10000 if value & 0x8000 else value


def expected_exit(regs: dict[str, int], work: bytes) -> int:
    """Resolve the root's only two terminal edges from its entry state."""

    a5 = regs["A5"] & 0xFFFFFF
    if (a5 >> 16) != 0xF0:
        raise RuntimeError(f"A5 is not work RAM: ${a5:06X}")
    base_offset = a5 & 0xFFFF
    d3 = signed16(
        (be16(work, base_offset + 0x3108) - be16(work, base_offset + 0x2A32))
        & 0xFFFF
    )
    all_empty = all(
        be16(work, base_offset + 0x2BB4 + slot * 0xAA + 0xA8) == 0
        for slot in range(8)
    )
    return EXIT_EMPTY_PC if d3 < 0x40 and all_empty else EXIT_LOOP_PC


def capture_live_cases(
    rom: Path,
    state: Path,
    nexen: Path,
    port: int,
    count: int,
    stderr_log: Path,
) -> list[LiveCase]:
    cases: list[LiveCase] = []
    with base.McpSession(
        rom=str(rom),
        mesen=str(nexen),
        cwd=ROOT,
        port=port,
        boot_wait=8.0,
        socket_timeout=180.0,
        stderr_log=stderr_log,
    ) as m:
        m.pause()
        m.load_state(str(state))
        m.pause()
        hook = m.add_exec_hook(ENTRY_NATIVE, cpu_type="Sa1")
        m.drain_notifications(timeout=0.05)
        previous_cycles = -1
        try:
            for index in range(count):
                hit = m.run_until(max_frames=180, hook_handle=hook)
                if (hit or {}).get("reason") != "hookFired":
                    raise RuntimeError(
                        f"production capture {index} did not reach native entry: {hit!r}"
                    )
                m.pause()
                cycles = int(m.get_cpu_state("Sa1")["cycleCount"])
                if cycles <= previous_cycles:
                    raise RuntimeError("native-entry capture did not advance")
                previous_cycles = cycles
                regs = captured_regs(m)
                work = bytes(
                    m.read_memory(base.SNES_SPACE, 0x400000, FULL_WORK_SIZE)
                )
                tick = be16(work, 0x1C56)
                exit_pc = expected_exit(regs, work)
                cases.append(
                    LiveCase(
                        name=f"live-{index:02d}-tick-{tick}",
                        regs=regs,
                        sr=captured_sr(m),
                        work=work,
                        tick=tick,
                        exit_pc=exit_pc,
                    )
                )
        finally:
            m.remove_hook(hook)
    return cases


def mame_result(
    session: base.MameSession, case: LiveCase
) -> tuple[base.Result, int]:
    session.pause()
    installed = int(session.exec_lua(MAME_IRQ_ISOLATION_LUA))
    if installed != 2:
        raise RuntimeError(f"installed {installed} MAME SR taps, expected 2")
    session.write_block(0xF00000, case.work[:MAPPED_WORK_SIZE])
    for name in base.REG_NAMES[:-1]:
        session.set_reg(name, case.regs[name])
    # Mask real MAME IRQ delivery before entering the bounded oracle span.  The
    # taps above keep it masked when the original continuations would lower it.
    session.set_reg("SR", case.sr | 0x0700)
    session.set_reg("USP", case.regs["A7"])
    session.set_reg("SP", case.regs["A7"])
    session.set_reg("PC", ENTRY_PC)
    captured = session.cmd(
        "capture_at_pc",
        pc=case.exit_pc,
        addr=0xF00000,
        len=MAPPED_WORK_SIZE,
        nth=1,
        exp_sp=case.regs["A7"] & 0xFFFFFF,
        maxFrames=60,
        timeout=60,
    )
    if not captured.get("registers"):
        raise RuntimeError(
            f"MAME did not reach terminal PC ${case.exit_pc:06X} "
            f"for {case.name}: {captured!r}"
        )
    regs = captured["registers"]
    result_regs = {
        name: regs[name] & 0xFFFFFFFF for name in base.REG_NAMES[:-1]
    }
    result_regs["A7"] = regs["SP"] & 0xFFFFFFFF
    sr_reads = int(session.exec_lua("return MCP_175A0_SR_READS or 0"))
    # The original ANDI/ORI pair selects mask four.  If neither continuation
    # ran (the early-empty edge), the routine preserves its entry mask.
    original_mask = 0x0400 if sr_reads else (case.sr & 0x0700)
    result_sr = ((regs["SR"] & 0xFFFF) & ~0x0700) | original_mask
    return (
        base.Result(
            result_regs,
            result_sr,
            bytes.fromhex(captured["hex"]),
        ),
        sr_reads,
    )


def park_snes_cpu(m: base.McpSession) -> None:
    """Keep the unrelated 5A22 from writing shared BW-RAM in this local lab."""

    m.write_memory("snesWorkRam", SNES_PARK_PC & 0x1FFFF, "80fe")
    m.write_memory("snesMemory", 0x4200, "00")
    m.read_memory("snesMemory", 0x4210, 1)
    state = dict(m.get_cpu_state("Snes"))
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
    m.tool("set_cpu_state", {key: state[key] for key in allowed if key in state})


def nexen_result(
    m: base.McpSession,
    nat: Path,
    case: LiveCase,
    *,
    xlat_gate: int,
    choke_gate: int,
    irq_countdown: int = 0x7000,
    enable_debug_fetch: bool = False,
    pre_state: Path | None = None,
    max_frames: int = 24,
) -> base.Result:
    m.load_state(str(nat))
    m.pause()
    if enable_debug_fetch:
        # Production packs the source-level JSR dbg_fetch as BRA.B + NOP.
        # Re-enable it only in this disposable validation process so a
        # bounded oracle can freeze before executing its terminal 68000
        # instruction.  Patch both bank-$00 ROM mirrors and reject any
        # unrecognized bytes instead of silently altering candidate code.
        for rom_offset in (0x0000EB, 0x0080EB):
            actual = bytes(m.read_memory("snesPrgRom", rom_offset, 3))
            if actual not in (bytes.fromhex("8001ea"), bytes.fromhex("2081e2")):
                raise RuntimeError(
                    f"unexpected dbg_fetch pack bytes at ROM ${rom_offset:06X}: "
                    f"{actual.hex()}"
                )
            m.write_memory("snesPrgRom", rom_offset, "2081e2")

        # VTIME packing reuses dbg_fetch's otherwise-dead 42-byte body for a
        # relocated choke tail.  A bounded function oracle still needs the
        # exact debug freeze at its terminal virtual PC, so restore the source
        # PC_RING body in this disposable emulator process as well as its call.
        # Ordinary ROMs already contain these bytes; writing the same payload
        # keeps the established validator behavior unchanged.
        interp = (ROOT / "src/interp.bin").read_bytes()
        dbg_relative = 0xE281 - 0x8000
        dbg_size = 42
        dbg_body = (
            bytes.fromhex("daa448a540")
            + interp[dbg_relative + 5:dbg_relative + dbg_size]
        )
        if len(dbg_body) != dbg_size:
            raise RuntimeError("could not reconstruct exact dbg_fetch body")
        for rom_offset in (dbg_relative, dbg_relative + 0x8000):
            m.write_memory("snesPrgRom", rom_offset, dbg_body.hex())

    reg_blob = b"".join(base.le32(case.regs[name]) for name in base.REG_NAMES)
    m.write_memory(base.DP_SPACE, 0x00, reg_blob.hex())
    for offset in range(0, len(case.work), 0x4000):
        m.write_memory(
            base.SNES_SPACE,
            0x400000 + offset,
            case.work[offset : offset + 0x4000].hex(),
        )
    park_snes_cpu(m)

    flags = case.sr & base.CCR_MASK
    write_u16(m, 0x6E, flags & 1)
    write_u16(m, 0x72, (flags >> 1) & 1)
    write_u16(m, 0x60, (flags >> 2) & 1)
    write_u16(m, 0x70, (flags >> 3) & 1)
    write_u16(m, 0xA2, (flags >> 4) & 1)
    write_u16(m, 0x7C, (case.sr >> 8) & 7)
    write_u16(m, 0x40, ENTRY_PC & 0xFFFF)
    write_u16(m, 0x42, (ENTRY_PC >> 16) & 0xFF)
    write_u16(m, 0x4A, 0)
    write_u16(m, 0x4C, 0)
    write_u16(m, 0xA4, case.regs["A7"] & 0xFFFF)
    write_u16(m, 0xA6, (case.regs["A7"] >> 16) & 0xFFFF)
    write_u16(m, 0xA8, 1)
    write_u16(m, 0xAA, 0)
    write_u16(m, 0xAC, irq_countdown)
    write_u16(m, 0x0702, 0)
    write_u16(m, 0x0704, 1)
    write_u16(m, 0x0710, case.exit_pc & 0xFFFF)
    write_u16(m, 0x0712, 0)
    write_u16(m, 0x0714, 0)
    write_u16(m, 0x0716, (case.exit_pc >> 16) & 0xFF)
    write_u16(m, 0x0718, 0xFFF8)
    write_u16(m, 0x071A, xlat_gate)
    write_u16(m, 0x072E, 0)
    write_u16(m, 0x0730, 0)
    write_u16(m, 0x0734, 0)
    write_u16(m, 0x0736, 0)
    write_u16(m, 0x0738, 0)
    write_u16(m, 0x073A, choke_gate)
    write_u16(m, 0x073C, 0)

    # The direct fixture is the deterministic pre-failure state.  Retain it
    # only after every architectural register, mapped work-RAM byte, gate,
    # virtual-PC word, and IRQ control field has been installed, but before
    # the target native/interpreter route starts running.
    if pre_state is not None:
        pre_state.parent.mkdir(parents=True, exist_ok=True)
        response = m.save_state(pre_state.resolve())
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            if pre_state.is_file() and pre_state.stat().st_size:
                break
            time.sleep(0.05)
        else:
            raise RuntimeError(f"save state was not flushed: {pre_state}; response={response!r}")
        # Nexen's save operation itself can advance/perturb internal renderer
        # bookkeeping.  The subsequent execution must start from the retained
        # pre-failure state, not from that post-save live process state.
        m.load_state(pre_state.resolve())
        m.pause()

    seam_hook = m.add_exec_hook(DEBUG_SPIN, cpu_type="Sa1")
    m.drain_notifications(timeout=0.05)
    base.set_sa1_pc(m, ENTRY_NATIVE)
    start_cycles = int(m.get_cpu_state("Sa1")["cycleCount"])
    hit = m.run_until(max_frames=max_frames, hook_handle=seam_hook)
    m.pause()
    m.remove_hook(seam_hook)
    if (hit or {}).get("reason") != "hookFired":
        stalled_pc = read_u16(m, 0x40) | (
            (read_u16(m, 0x42) & 0xFF) << 16
        )
        stalled_sa1 = m.get_cpu_state("Sa1")
        raise RuntimeError(
            f"Nexen did not freeze at terminal PC ${case.exit_pc:06X} "
            f"for {case.name}, xlat={xlat_gate}, choke={choke_gate}: {hit!r}; "
            f"virtual_pc=${stalled_pc:06X}, sa1_pc=${int(stalled_sa1['pc']):06X}"
        )
    end_cycles = int(m.get_cpu_state("Sa1")["cycleCount"])
    observed_pc = read_u16(m, 0x40) | ((read_u16(m, 0x42) & 0xFF) << 16)
    if not read_u16(m, 0x0712) or observed_pc != case.exit_pc:
        raise RuntimeError(
            f"Nexen froze at ${observed_pc:06X}, expected ${case.exit_pc:06X}"
        )
    sr = 0x2000 | ((read_u16(m, 0x7C) & 7) << 8) | captured_ccr(m)
    return base.Result(
        captured_regs(m),
        sr,
        bytes(m.read_memory(base.SNES_SPACE, 0x400000, MAPPED_WORK_SIZE)),
        end_cycles - start_cycles,
    )


def compare(
    case: LiveCase,
    arcade: base.Result,
    console: base.Result,
    xlat_gate: int,
    choke_gate: int,
) -> dict:
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
    ccr_mismatch = (
        arcade.sr & base.CCR_MASK
    ) != (console.sr & base.CCR_MASK)
    mask_mismatch = ((arcade.sr >> 8) & 7) != ((console.sr >> 8) & 7)
    return {
        "event": "case",
        "case": case.name,
        "tick": case.tick,
        "terminal_pc": f"{case.exit_pc:06X}",
        "nested_xlat_gate": xlat_gate,
        "fetch_choke_gate": choke_gate,
        "result": (
            "green"
            if not reg_mismatches
            and not ccr_mismatch
            and not mask_mismatch
            and not work_mismatches
            else "red"
        ),
        "reg_mismatches": reg_mismatches,
        "mame_ccr": arcade.sr & base.CCR_MASK,
        "nexen_ccr": console.sr & base.CCR_MASK,
        "mame_mask": (arcade.sr >> 8) & 7,
        "nexen_mask": (console.sr >> 8) & 7,
        "work_mismatch_count": len(work_mismatches),
        "work_mismatch_first": [
            f"F0{offset:04X}" for offset in work_mismatches[:24]
        ],
        "work_mismatch_values": [
            {
                "address": f"F0{offset:04X}",
                "mame": arcade.work[offset],
                "nexen": console.work[offset],
            }
            for offset in work_mismatches[:24]
        ],
        "nexen_cycles": console.cycles,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    parser.add_argument(
        "--capture-rom",
        type=Path,
        help=(
            "ROM used only to capture organic entry fixtures; defaults to --rom. "
            "Use a retained reference when candidate timing changes pre-entry state."
        ),
    )
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--nexen", type=Path, default=base.DEFAULT_NEXEN)
    parser.add_argument("--nat", type=Path, default=base.DEFAULT_NAT)
    parser.add_argument("--port", type=int, default=7610)
    parser.add_argument("--cases", type=int, default=6)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.capture_rom is None:
        args.capture_rom = args.rom
    for path in (args.rom, args.capture_rom, args.state, args.nexen, args.nat):
        if not path.is_file():
            parser.error(f"missing required input: {path}")
    if args.cases < 1:
        parser.error("--cases must be positive")
    if args.output.exists():
        parser.error(f"output already exists: {args.output}")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    fixture_dir = args.output.parent / f"{args.output.stem}-fixtures"
    if fixture_dir.exists():
        parser.error(f"fixture directory already exists: {fixture_dir}")
    fixture_dir.mkdir()

    events: list[dict] = []
    provenance = {
        "event": "provenance",
        "scope": (
            "live-fixture function-local $0175A0 MAME/Nexen differential; "
            "all D/A registers, CCR/mask, mapped 16 KiB work RAM; not fps"
        ),
        "mame": "/snap/bin/mame 0.287",
        "nexen": str(args.nexen.resolve()),
        "nexen_sha256": sha256(args.nexen),
        "rom": str(args.rom.resolve()),
        "rom_sha256": sha256(args.rom),
        "capture_rom": str(args.capture_rom.resolve()),
        "capture_rom_sha256": sha256(args.capture_rom),
        "state": str(args.state.resolve()),
        "state_sha256": sha256(args.state),
        "nat": str(args.nat.resolve()),
        "nat_sha256": sha256(args.nat),
        "entry_pc": f"{ENTRY_PC:06X}",
        "entry_native": f"{ENTRY_NATIVE:06X}",
        "continuations": [f"{CONT_STATIC_PC:06X}", f"{CONT_DYNAMIC_PC:06X}"],
        "terminal_pcs": [f"{EXIT_LOOP_PC:06X}", f"{EXIT_EMPTY_PC:06X}"],
        "mame_irq_isolation": {
            "reason": "prevent unrelated held VBLANK IRQ6 during local injection",
            "entry_mask": 7,
            "read_tap_immediates": ["0175EE:F4FF->F7FF", "017618:F4FF->F7FF"],
            "reported_mask": "4 after a tapped continuation, otherwise entry mask",
            "rom_file_modified": False,
        },
        "fixtures": args.cases,
        "variants_per_fixture": 3,
        "time": time.time(),
    }
    events.append(provenance)
    print(json.dumps(provenance, sort_keys=True), flush=True)

    cases = capture_live_cases(
        args.capture_rom,
        args.state,
        args.nexen,
        args.port,
        args.cases,
        fixture_dir / "capture.nexen.stderr.log",
    )
    for index, case in enumerate(cases):
        (fixture_dir / f"case-{index:02d}.work.bin").write_bytes(case.work)
        fixture = {
            "name": case.name,
            "tick": case.tick,
            "terminal_pc": f"{case.exit_pc:06X}",
            "sr": case.sr,
            "regs": case.regs,
            "work_sha256": hashlib.sha256(case.work).hexdigest(),
        }
        (fixture_dir / f"case-{index:02d}.json").write_text(
            json.dumps(fixture, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        event = {"event": "fixture", **fixture}
        events.append(event)
        print(json.dumps(event, sort_keys=True), flush=True)

    arcade: dict[str, base.Result] = {}
    mame_sr_reads: dict[str, int] = {}
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
            arcade[case.name], mame_sr_reads[case.name] = mame_result(mame, case)
            event = {
                "event": "mame_case",
                "case": case.name,
                "oracle_terminal_pc": f"{case.exit_pc:06X}",
                "irq_isolation_sr_reads": mame_sr_reads[case.name],
                "irq_isolation": (
                    "entry mask forced to 7; two ANDI-to-SR immediate read "
                    "taps preserve mask 7; reported mask reconstructed"
                ),
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
        stderr_log=fixture_dir / "differential.nexen.stderr.log",
    ) as nexen:
        for case in cases:
            for xlat_gate, choke_gate in ((0, 0), (1, 0), (1, 1)):
                console = nexen_result(
                    nexen,
                    args.nat,
                    case,
                    xlat_gate=xlat_gate,
                    choke_gate=choke_gate,
                )
                event = compare(
                    case,
                    arcade[case.name],
                    console,
                    xlat_gate,
                    choke_gate,
                )
                events.append(event)
                print(json.dumps(event, sort_keys=True), flush=True)

    case_events = [event for event in events if event.get("event") == "case"]
    green = sum(event["result"] == "green" for event in case_events)
    summary = {
        "event": "summary",
        "green": green,
        "red": len(case_events) - green,
        "total": len(case_events),
        "result": "green" if green == len(case_events) else "red",
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
