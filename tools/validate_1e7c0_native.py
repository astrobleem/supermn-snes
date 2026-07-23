#!/usr/bin/env python3
"""Live-fixture MAME/Nexen differential for native task root $01E7C0.

The fixtures are captured organically at the bank-$98 entry during sustained
gameplay.  MAME executes the original MC68000 render/object visit from $01E7C0
to its real trap boundary at $01E7BE; Nexen executes the production native root
and its native/interpreted callees from the identical registers and work RAM.

The gate is exact across every D/A register, CCR and interrupt mask, and the
mapped 16 KiB work-RAM window.  This is bounded function-semantic and local
cycle evidence, not an end-to-end performance or fps result.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path

import validate_d96_hle as base
import validate_175a0_native as common


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ROM = ROOT / "build/interp.sfc"
DEFAULT_STATE = (
    ROOT / "build/playability-20260720/111a-table-active-cold-boot-v1/final.mss"
)
DEFAULT_CANDIDATE_SYM = ROOT / "src/escbank4.sym"
DEFAULT_CANDIDATE_HOT_SYM = ROOT / "src/escbank3.sym"
ENTRY_PC = 0x01E7C0
ENTRY_NATIVE = 0x98AE00
EXIT_PC = 0x01E7BE
DEBUG_SPIN = 0x00E2CF
MAPPED_WORK_SIZE = 0x4000
FULL_WORK_SIZE = 0x10000

# The real side-B tail lowers the mask from seven to four immediately before
# the terminal trap.  A local MAME process can have IRQ6 pending, which would
# preempt the terminal fetch.  Keep only the injected oracle span masked at
# seven by changing the fetched ANDI immediate; report the original mask four.
MAME_IRQ_ISOLATION_LUA = """
MCP_1E7C0_SR_TAPS = {}
MCP_1E7C0_SR_READS = 0
local p = M.devices[":maincpu"].spaces["program"]
local function preserve_mask7(offset, data, mask)
    MCP_1E7C0_SR_READS = MCP_1E7C0_SR_READS + 1
    return 0xf7ff
end
MCP_1E7C0_SR_TAPS[1] = p:install_read_tap(
    0x1e7b6, 0x1e7b7, "mcp_1e7c0_sr_tail", preserve_mask7)
return #MCP_1E7C0_SR_TAPS
"""


@dataclass
class LiveCase:
    name: str
    regs: dict[str, int]
    sr: int
    work: bytes
    tick: int


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def hot_guard_reasons(regs: dict[str, int], work: bytes) -> list[str]:
    """Mirror entry_1e7c0's bank-$98 guard without changing fixture state."""

    reasons: list[str] = []
    a5 = regs["A5"] & 0xFFFFFF
    a6 = regs["A6"] & 0xFFFFFF
    if a5 != 0xF00000:
        reasons.append(f"A5=${a5:06X}")
    if (a6 >> 16) != 0xF0 or (a6 & 0xFFFF) < 0x20:
        reasons.append(f"A6=${a6:06X}")
        return reasons

    list_offset = (a6 & 0xFFFF) - 0x20
    for slot in range(8):
        pointer = int.from_bytes(
            work[list_offset + slot * 4:list_offset + slot * 4 + 4], "big"
        )
        if pointer == 0:
            continue
        pointer_low = pointer & 0xFFFF
        if (pointer >> 16) != 0xF0 or pointer_low >= 0xFF92:
            reasons.append(f"slot{slot}.object=${pointer:08X}")
            continue
        for field in (0x46, 0x4A, 0x4E):
            subrecord = int.from_bytes(
                work[pointer_low + field:pointer_low + field + 4], "big"
            )
            if (subrecord >> 16) != 0xF0 or (subrecord & 0xFFFF) >= 0xFFF1:
                reasons.append(
                    f"slot{slot}.subrecord+${field:02X}=${subrecord:08X}"
                )
    return reasons


def symbol_offset(path: Path, name: str) -> int:
    for raw in path.read_text(encoding="utf-8").splitlines():
        fields = raw.split()
        if len(fields) != 2 or fields[1] != name:
            continue
        bank, offset = fields[0].split(":", 1)
        if bank != "00":
            raise RuntimeError(f"unexpected symbol bank for {name}: {fields[0]}")
        return int(offset, 16)
    raise RuntimeError(f"missing symbol {name} in {path}")


def capture_live_cases(
    rom: Path,
    state: Path,
    nexen: Path,
    port: int,
    count: int,
    stderr_log: Path,
    input_buttons: int | None,
    capture_native: int,
    skip_fixtures: int,
    capture_max_frames: int,
) -> tuple[list[LiveCase], list[dict]]:
    cases: list[LiveCase] = []
    rejected: list[dict] = []
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
        if input_buttons is not None:
            m.tool(
                "set_input",
                {"port": 0, "buttons": input_buttons, "hold": True},
            )
        hook = m.add_exec_hook(capture_native, cpu_type="Sa1")
        m.drain_notifications(timeout=0.05)
        previous_cycles = -1
        try:
            accepted_hits = 0
            max_hits = max(32, (count + skip_fixtures) * 8)
            for attempt in range(max_hits):
                hit = m.run_until(max_frames=capture_max_frames, hook_handle=hook)
                if (hit or {}).get("reason") != "hookFired":
                    raise RuntimeError(
                        f"production capture attempt {attempt} did not reach native entry: "
                        f"{hit!r}"
                    )
                m.pause()
                cycles = int(m.get_cpu_state("Sa1")["cycleCount"])
                if cycles <= previous_cycles:
                    raise RuntimeError("native-entry capture did not advance")
                previous_cycles = cycles
                regs = common.captured_regs(m)
                if (regs["A5"] >> 16) & 0xFFFF != 0x00F0:
                    raise RuntimeError(f"capture A5 is not work RAM: {regs['A5']:#010x}")
                if capture_native != ENTRY_NATIVE:
                    expected_a1 = (regs["A6"] - 0x20) & 0xFFFFFF
                    if (regs["D5"] & 0xFFFF) != 7 or (
                        regs["A1"] & 0xFFFFFF
                    ) != expected_a1:
                        rejected.append(
                            {
                                "attempt": attempt,
                                "tick": None,
                                "reasons": [
                                    "non-initial helper loop: "
                                    f"D5=${regs['D5'] & 0xFFFF:04X}, "
                                    f"A1=${regs['A1'] & 0xFFFFFF:06X}, "
                                    f"expected A1=${expected_a1:06X}"
                                ],
                            }
                        )
                        continue
                work = bytes(
                    m.read_memory(base.SNES_SPACE, 0x400000, FULL_WORK_SIZE)
                )
                tick = common.be16(work, 0x1C56)
                reasons = hot_guard_reasons(regs, work)
                if reasons:
                    rejected.append(
                        {
                            "attempt": attempt,
                            "tick": tick,
                            "reasons": reasons,
                        }
                    )
                    continue
                if accepted_hits < skip_fixtures:
                    rejected.append(
                        {
                            "attempt": attempt,
                            "tick": tick,
                            "reasons": ["requested fixture skip"],
                        }
                    )
                    accepted_hits += 1
                    continue
                accepted_hits += 1
                index = len(cases)
                cases.append(
                    LiveCase(
                        name=f"live-{index:02d}-tick-{tick}",
                        regs=regs,
                        sr=common.captured_sr(m),
                        work=work,
                        tick=tick,
                    )
                )
                if len(cases) == count:
                    break
        finally:
            m.remove_hook(hook)
    if len(cases) != count:
        raise RuntimeError(
            f"captured only {len(cases)}/{count} bank-$98-guarded fixtures after "
            f"{max_hits} native-entry hits"
        )
    return cases, rejected


def mame_result(
    session: base.MameSession, case: LiveCase
) -> tuple[base.Result, int]:
    session.pause()
    installed = int(session.exec_lua(MAME_IRQ_ISOLATION_LUA))
    if installed != 1:
        raise RuntimeError(f"installed {installed} MAME SR taps, expected 1")
    # capture_at_pc observes opcode prefetch.  Capturing the terminal trap
    # directly therefore snapshots the preceding jsr(a6) setup, with A6/A7
    # and several object writes still stale.  Replace only the fetched trap
    # word with a validation-only NOP and capture the following $01E7C0 fetch,
    # when every terminal-side effect has committed.  MAME has already filled
    # the injected entry prefetch before capture_at_pc arms its read tap, so
    # this post-NOP fetch is the first observed hit (an nth=2 experiment
    # demonstrably executed the body twice).
    session.exec_lua(
        "if MCP_1E7C0_EXIT_NOP then MCP_1E7C0_EXIT_NOP:remove() end "
        "MCP_1E7C0_EXIT_NOP = machine.devices[':maincpu'].spaces['program']"
        f":install_read_tap(0x{EXIT_PC:06X}, 0x{EXIT_PC + 1:06X}, "
        "'mcp_1e7c0_exit_nop', function(offset, data, mask) return 0x4E71 end); "
        "return true"
    )
    session.write_block(0xF00000, case.work[:MAPPED_WORK_SIZE])
    for name in base.REG_NAMES[:-1]:
        session.set_reg(name, case.regs[name])
    session.set_reg("SR", case.sr | 0x0700)
    session.set_reg("USP", case.regs["A7"])
    session.set_reg("SP", case.regs["A7"])
    session.set_reg("PC", ENTRY_PC)
    captured = session.cmd(
        "capture_at_pc",
        pc=ENTRY_PC,
        addr=0xF00000,
        len=MAPPED_WORK_SIZE,
        nth=1,
        exp_sp=case.regs["A7"] & 0xFFFFFF,
        maxFrames=60,
        timeout=60,
    )
    if not captured.get("registers"):
        raise RuntimeError(
            f"MAME did not reach committed post-trap seam ${ENTRY_PC:06X} "
            f"for {case.name}: "
            f"{captured!r}"
        )
    regs = captured["registers"]
    result_regs = {
        name: regs[name] & 0xFFFFFFFF for name in base.REG_NAMES[:-1]
    }
    result_regs["A7"] = regs["SP"] & 0xFFFFFFFF
    sr_reads = int(session.exec_lua("return MCP_1E7C0_SR_READS or 0"))
    session.exec_lua(
        "if MCP_1E7C0_EXIT_NOP then MCP_1E7C0_EXIT_NOP:remove(); "
        "MCP_1E7C0_EXIT_NOP=nil end; return true"
    )
    # emu.pause() takes effect at a frame boundary, so the read tap can fire
    # again after pc_snapshot has already frozen its immediate register/memory
    # result.  Require the isolated edge to have executed, but do not mistake
    # post-capture run-ahead for another function invocation in the snapshot.
    if sr_reads < 1:
        raise RuntimeError(
            "MAME terminal path never read the isolated SR immediate"
        )
    # Restore the mask selected by the original ANDI/ORI pair.  CCR bits are
    # untouched by the read-tap substitution.
    result_sr = ((regs["SR"] & 0xFFFF) & ~0x0700) | 0x0400
    return (
        base.Result(result_regs, result_sr, bytes.fromhex(captured["hex"])),
        sr_reads,
    )


def write_u16(m: base.McpSession, address: int, value: int) -> None:
    common.write_u16(m, address, value)


def nexen_result(
    m: base.McpSession,
    nat: Path,
    case: LiveCase,
    *,
    xlat_gate: int,
    choke_gate: int,
    work_size: int = MAPPED_WORK_SIZE,
) -> base.Result:
    m.load_state(str(nat))
    m.pause()
    reg_blob = b"".join(base.le32(case.regs[name]) for name in base.REG_NAMES)
    m.write_memory(base.DP_SPACE, 0x00, reg_blob.hex())
    for offset in range(0, len(case.work), 0x4000):
        m.write_memory(
            base.SNES_SPACE,
            0x400000 + offset,
            case.work[offset : offset + 0x4000].hex(),
        )
    common.park_snes_cpu(m)

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
    write_u16(m, 0xAC, 0x7000)
    write_u16(m, 0x0702, 0)
    write_u16(m, 0x0704, 1)
    write_u16(m, 0x0710, EXIT_PC & 0xFFFF)
    write_u16(m, 0x0712, 0)
    write_u16(m, 0x0714, 0)
    write_u16(m, 0x0716, (EXIT_PC >> 16) & 0xFF)
    write_u16(m, 0x0718, 0xFFF8)
    write_u16(m, 0x071A, xlat_gate)
    write_u16(m, 0x072E, 0)
    write_u16(m, 0x0730, 0)
    write_u16(m, 0x0734, 0)
    write_u16(m, 0x0736, 0)
    write_u16(m, 0x0738, 0)
    write_u16(m, 0x073A, choke_gate)
    write_u16(m, 0x073C, 0)

    seam_hook = m.add_exec_hook(DEBUG_SPIN, cpu_type="Sa1")
    m.drain_notifications(timeout=0.05)
    base.set_sa1_pc(m, ENTRY_NATIVE)
    start_cycles = int(m.get_cpu_state("Sa1")["cycleCount"])
    hit = m.run_until(max_frames=60, hook_handle=seam_hook)
    m.pause()
    m.remove_hook(seam_hook)
    if (hit or {}).get("reason") != "hookFired":
        observed_pc = common.read_u16(m, 0x40) | (
            (common.read_u16(m, 0x42) & 0xFF) << 16
        )
        cpu = m.get_cpu_state("Sa1")
        regs = common.captured_regs(m)
        raise RuntimeError(
            f"Nexen did not freeze at terminal PC ${EXIT_PC:06X} for {case.name}, "
            f"xlat={xlat_gate}, choke={choke_gate}: {hit!r}; "
            f"68K PC=${observed_pc:06X}, halt=${common.read_u16(m, 0x4E):04X}, "
            f"A7=${regs['A7'] & 0xFFFFFF:06X}, "
            f"SA1 PC=${((int(cpu.get('k', 0)) << 16) | int(cpu.get('pc', 0))):06X}, "
            f"SA1 cycles={int(cpu.get('cycleCount', 0))}"
        )
    end_cycles = int(m.get_cpu_state("Sa1")["cycleCount"])
    observed_pc = common.read_u16(m, 0x40) | (
        (common.read_u16(m, 0x42) & 0xFF) << 16
    )
    if not common.read_u16(m, 0x0712) or observed_pc != EXIT_PC:
        raise RuntimeError(
            f"Nexen froze at ${observed_pc:06X}, expected ${EXIT_PC:06X}"
        )
    sr = 0x2000 | ((common.read_u16(m, 0x7C) & 7) << 8) | common.captured_ccr(m)
    return base.Result(
        common.captured_regs(m),
        sr,
        bytes(m.read_memory(base.SNES_SPACE, 0x400000, work_size)),
        end_cycles - start_cycles,
    )


def compare(
    case: LiveCase,
    arcade: base.Result,
    console: base.Result,
    xlat_gate: int,
    choke_gate: int,
    candidate_br10: int,
    candidate_hot_return: int,
) -> dict:
    reg_mismatches = {
        name: {"mame": arcade.regs[name], "nexen": console.regs[name]}
        for name in base.REG_NAMES
        if arcade.regs[name] != console.regs[name]
    }
    all_work_mismatches = [
        offset
        for offset, (left, right) in enumerate(zip(arcade.work, console.work))
        if left != right
    ]
    # The original jsr(a4) at $01F096 pushes return address $0001F098.
    # The native guarded bridge instead pushes $00FB:br1e7c0_10.  Both calls
    # pop the value, leaving four dead bytes at entry-A7-$12; the leading zero
    # agrees, so normally only the final three appear in the diff.  Permit
    # precisely those value-checked bytes and no other stack residue.
    residue = ((case.regs["A7"] & 0xFFFF) - 0x12) & 0xFFFF
    mame_return = (0x00, 0x01, 0xF0, 0x98)
    native_returns = {
        "generated": (
            0x00,
            0xFB,
            (candidate_br10 >> 8) & 0xFF,
            candidate_br10 & 0xFF,
        ),
        "hot": (
            0x00,
            0xFC,
            (candidate_hot_return >> 8) & 0xFF,
            candidate_hot_return & 0xFF,
        ),
    }
    observed_native_return = tuple(
        console.work[(residue + index) & 0xFFFF] for index in range(4)
    )
    native_return_kind = next(
        (
            name
            for name, value in native_returns.items()
            if value == observed_native_return
        ),
        None,
    )
    native_return = (
        native_returns[native_return_kind]
        if native_return_kind is not None
        else observed_native_return
    )
    expected_residue = {
        (residue + index) & 0xFFFF: (mame_byte, native_byte)
        for index, (mame_byte, native_byte) in enumerate(
            zip(mame_return, native_return)
        )
    }
    allowed_return_residue = [
        offset
        for offset in all_work_mismatches
        if native_return_kind is not None
        if offset in expected_residue
        and (arcade.work[offset], console.work[offset]) == expected_residue[offset]
    ]
    work_mismatches = [
        offset for offset in all_work_mismatches if offset not in allowed_return_residue
    ]
    ccr_mismatch = (arcade.sr & base.CCR_MASK) != (console.sr & base.CCR_MASK)
    mask_mismatch = ((arcade.sr >> 8) & 7) != ((console.sr >> 8) & 7)
    green = not reg_mismatches and not work_mismatches and not ccr_mismatch and not mask_mismatch
    return {
        "event": "case",
        "case": case.name,
        "tick": case.tick,
        "terminal_pc": f"{EXIT_PC:06X}",
        "nested_xlat_gate": xlat_gate,
        "fetch_choke_gate": choke_gate,
        "result": "green" if green else "red",
        "reg_mismatches": reg_mismatches,
        "mame_ccr": arcade.sr & base.CCR_MASK,
        "nexen_ccr": console.sr & base.CCR_MASK,
        "mame_mask": (arcade.sr >> 8) & 7,
        "nexen_mask": (console.sr >> 8) & 7,
        "work_mismatch_count": len(work_mismatches),
        "work_mismatch_first": [f"F0{offset:04X}" for offset in work_mismatches[:24]],
        "work_mismatch_values": [
            {
                "address": f"F0{offset:04X}",
                "mame": arcade.work[offset],
                "nexen": console.work[offset],
            }
            for offset in work_mismatches[:24]
        ],
        "allowed_return_residue": {
            "reason": (
                "popped original $0001F098 versus native "
                "$00FB:br1e7c0_10 or $00FC:h1e7c0_hot_return "
                "at entry A7-$12"
            ),
            "offsets": [f"F0{offset:04X}" for offset in allowed_return_residue],
            "mame_return": "0001F098",
            "nexen_return": "".join(f"{byte:02X}" for byte in native_return),
            "nexen_return_kind": native_return_kind,
            "accepted_native_returns": {
                name: "".join(f"{byte:02X}" for byte in value)
                for name, value in native_returns.items()
            },
            "exact": len(allowed_return_residue) == len(all_work_mismatches),
        },
        "nexen_cycles": console.cycles,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--nexen", type=Path, default=base.DEFAULT_NEXEN)
    parser.add_argument("--nat", type=Path, default=base.DEFAULT_NAT)
    parser.add_argument("--port", type=int, default=7630)
    parser.add_argument("--cases", type=int, default=6)
    parser.add_argument(
        "--input-buttons",
        type=lambda value: int(value, 0),
        help="Optional held 12-bit controller mask while capturing live fixtures.",
    )
    parser.add_argument(
        "--candidate-sym",
        type=Path,
        default=DEFAULT_CANDIDATE_SYM,
    )
    parser.add_argument(
        "--candidate-hot-sym",
        type=Path,
        default=DEFAULT_CANDIDATE_HOT_SYM,
    )
    parser.add_argument(
        "--capture-hot-entry",
        action="store_true",
        help=(
            "Capture fixtures at h1e7c0_hot after the read-only bank-$98 "
            "guard instead of at the bank-$98 root."
        ),
    )
    parser.add_argument(
        "--skip-fixtures",
        type=int,
        default=0,
        help="Skip this many otherwise acceptable live fixture hits before capture.",
    )
    parser.add_argument(
        "--capture-max-frames",
        type=int,
        default=180,
        help="Maximum emulated frames allowed for each live-fixture hook hit.",
    )
    parser.add_argument(
        "--production-variants-only",
        action="store_true",
        help="Validate nested xlat on, with fetch choke both off and on.",
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    for path in (
        args.rom,
        args.state,
        args.nexen,
        args.nat,
        args.candidate_sym,
        args.candidate_hot_sym,
    ):
        if not path.is_file():
            parser.error(f"missing required input: {path}")
    if args.cases < 1:
        parser.error("--cases must be positive")
    if args.skip_fixtures < 0:
        parser.error("--skip-fixtures must not be negative")
    if args.capture_max_frames < 1:
        parser.error("--capture-max-frames must be positive")
    if args.input_buttons is not None and not 0 <= args.input_buttons <= 0xFFF:
        parser.error("--input-buttons must be a 12-bit mask")
    if args.output.exists():
        parser.error(f"output already exists: {args.output}")
    candidate_br10 = symbol_offset(args.candidate_sym, "br1e7c0_10")
    candidate_hot_return = symbol_offset(
        args.candidate_hot_sym, "h1e7c0_hot_return"
    )
    candidate_hot_entry = 0x970000 | symbol_offset(
        args.candidate_hot_sym, "h1e7c0_hot_loop"
    )
    capture_native = candidate_hot_entry if args.capture_hot_entry else ENTRY_NATIVE
    variants = (
        ((1, 0), (1, 1))
        if args.production_variants_only
        else ((0, 0), (1, 0), (1, 1))
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    fixture_dir = args.output.parent / f"{args.output.stem}-fixtures"
    if fixture_dir.exists():
        parser.error(f"fixture directory already exists: {fixture_dir}")
    fixture_dir.mkdir()

    events: list[dict] = []
    provenance = {
        "event": "provenance",
        "scope": (
            "live-fixture function-local $01E7C0 MAME/Nexen differential; "
            "all D/A registers, CCR/mask, mapped 16 KiB work RAM; not fps"
        ),
        "mame": "/snap/bin/mame 0.287",
        "nexen": str(args.nexen.resolve()),
        "nexen_sha256": sha256(args.nexen),
        "rom": str(args.rom.resolve()),
        "rom_sha256": sha256(args.rom),
        "state": str(args.state.resolve()),
        "state_sha256": sha256(args.state),
        "nat": str(args.nat.resolve()),
        "nat_sha256": sha256(args.nat),
        "entry_pc": f"{ENTRY_PC:06X}",
        "entry_native": f"{ENTRY_NATIVE:06X}",
        "capture_native": f"{capture_native:06X}",
        "capture_after_read_only_root_guard": args.capture_hot_entry,
        "capture_replayed_idempotent_prologue": args.capture_hot_entry,
        "terminal_pc": f"{EXIT_PC:06X}",
        "mame_irq_isolation": {
            "reason": "prevent unrelated held IRQ6 during local injection",
            "entry_mask": 7,
            "read_tap_immediate": "01E7B6:F4FF->F7FF",
            "reported_mask": 4,
            "rom_file_modified": False,
        },
        "mame_boundary_method": (
            "validation-only NOP at $01E7BE trap; capture following $01E7C0 "
            "prefetch with entry SP"
        ),
        "synthetic_return_layout": {
            "original_return": "0001F098",
            "native_returns": {
                "generated": f"00FB{candidate_br10:04X}",
                "hot": f"00FC{candidate_hot_return:04X}",
            },
            "allowed_residue": (
                "only exact differing bytes in the popped return at entry A7-$12"
            ),
        },
        "fixtures": args.cases,
        "variants_per_fixture": len(variants),
        "variants": [
            {"nested_xlat_gate": xlat, "fetch_choke_gate": choke}
            for xlat, choke in variants
        ],
        "capture_input_buttons": args.input_buttons,
        "capture_skipped_fixtures": args.skip_fixtures,
        "capture_max_frames": args.capture_max_frames,
        "capture_filter": (
            "exact entry_1e7c0 bank-$98 A5/A6/object/subrecord guard; rejected "
            "calls cannot execute the modified bank-$97 loop"
        ),
        "time": time.time(),
    }
    events.append(provenance)
    print(json.dumps(provenance, sort_keys=True), flush=True)

    cases, rejected = capture_live_cases(
        args.rom,
        args.state,
        args.nexen,
        args.port,
        args.cases,
        fixture_dir / "capture.nexen.stderr.log",
        args.input_buttons,
        capture_native,
        args.skip_fixtures,
        args.capture_max_frames,
    )
    filter_event = {
        "event": "capture_filter",
        "accepted": len(cases),
        "rejected": len(rejected),
        "rejected_calls": rejected,
    }
    events.append(filter_event)
    print(json.dumps(filter_event, sort_keys=True), flush=True)
    for index, case in enumerate(cases):
        (fixture_dir / f"case-{index:02d}.work.bin").write_bytes(case.work)
        fixture = {
            "name": case.name,
            "tick": case.tick,
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
            arcade[case.name], sr_reads = mame_result(mame, case)
            event = {
                "event": "mame_case",
                "case": case.name,
                "oracle_terminal_pc": f"{EXIT_PC:06X}",
                "irq_isolation_sr_reads": sr_reads,
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
            for xlat_gate, choke_gate in variants:
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
                    candidate_br10,
                    candidate_hot_return,
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
