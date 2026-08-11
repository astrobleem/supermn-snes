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
import os
import time
from dataclasses import dataclass
from pathlib import Path

import validate_d96_hle as base
import validate_175a0_native as common
from mame_0287 import MAME, environment as mame_environment
from mame_0287 import identity as mame_identity


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ROM = ROOT / "build/interp.sfc"
DEFAULT_STATE = (
    ROOT / "build/playability-20260720/111a-table-active-cold-boot-v1/final.mss"
)
DEFAULT_CANDIDATE_SYM = ROOT / "src/escbank4.sym"
DEFAULT_CANDIDATE_HOT_SYM = ROOT / "src/escbank3.sym"
DEFAULT_INTERP_SYM = ROOT / "src/interp.sym"
ENTRY_PC = 0x01E7C0
ENTRY_NATIVE = 0x98AE00
EXIT_PC = 0x01E7BE
OP_ILLEGAL = 0x00CDED
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


def ensure_paused(m: base.McpSession) -> None:
    """Pause only when running; a redundant Nexen pause can step the SA-1."""
    if not bool(m.get_state().get("isPaused")):
        m.pause()


@dataclass
class LiveCase:
    name: str
    regs: dict[str, int]
    sr: int
    work: bytes
    tick: int


def load_fixture_cases(fixture_dir: Path, count: int) -> list[LiveCase]:
    """Load retained organic fixtures without depending on their old ROM."""

    metadata_paths = sorted(fixture_dir.glob("case-*.json"))
    if len(metadata_paths) < count:
        raise RuntimeError(
            f"{fixture_dir} contains only {len(metadata_paths)} fixture metadata "
            f"files, need {count}"
        )
    cases: list[LiveCase] = []
    for metadata_path in metadata_paths[:count]:
        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
        work_path = metadata_path.with_suffix(".work.bin")
        if not work_path.is_file():
            raise RuntimeError(f"missing fixture work image: {work_path}")
        work = work_path.read_bytes()
        if len(work) != FULL_WORK_SIZE:
            raise RuntimeError(
                f"{work_path} is {len(work)} bytes, expected {FULL_WORK_SIZE}"
            )
        expected_sha = payload.get("work_sha256")
        observed_sha = hashlib.sha256(work).hexdigest()
        if expected_sha != observed_sha:
            raise RuntimeError(
                f"{work_path} SHA-256 {observed_sha} does not match "
                f"metadata {expected_sha}"
            )
        regs = payload.get("regs")
        if not isinstance(regs, dict) or set(regs) != set(base.REG_NAMES):
            raise RuntimeError(
                f"{metadata_path} does not contain the exact D0-D7/A0-A7 set"
            )
        reasons = hot_guard_reasons(regs, work)
        if reasons:
            raise RuntimeError(
                f"{metadata_path} fails the current native root guard: {reasons}"
            )
        cases.append(
            LiveCase(
                name=str(payload["name"]),
                regs={name: int(regs[name]) for name in base.REG_NAMES},
                sr=int(payload["sr"]),
                work=work,
                tick=int(payload["tick"]),
            )
        )
    return cases


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
        ensure_paused(m)
        m.load_state(str(state))
        ensure_paused(m)
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
                ensure_paused(m)
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
    test_idle: int,
    inext: int,
    debug_spin: int,
    diagnostic_fetch_freeze: bool,
    work_size: int = MAPPED_WORK_SIZE,
    root_native: bool = True,
    max_handoffs: int = 1024,
    pre_state: Path | None = None,
    terminal_illegal: bool = False,
    boundary_tool: str | None = None,
) -> tuple[base.Result, dict]:
    m.load_state(str(nat))
    ensure_paused(m)
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
    # The retained native harness state can leave the single-step go flag
    # armed.  If it is still one when the root reaches inext, test_idle
    # immediately consumes it, clears the done marker, and begins an
    # unrelated opcode before the boundary hook is observed.  Start the
    # injected root with the poll gate closed; the loop below explicitly
    # arms it only when advancing an intermediate interpreted opcode.
    write_u16(m, 0xA0, 0)
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
    if diagnostic_fetch_freeze and terminal_illegal:
        raise RuntimeError(
            "diagnostic fetch freeze and terminal ILLEGAL are mutually exclusive"
        )
    if diagnostic_fetch_freeze:
        # PC_RING=1 retains dbg_fetch and its exact emulated-PC freeze.  This
        # lets intervening IRQ/task work run normally and stops before the
        # terminal opcode is dispatched.
        write_u16(m, 0x7E, 0)
        seam_address = debug_spin
    elif terminal_illegal:
        # Production packs out dbg_fetch.  Replace only the terminal 68000
        # TRAP word in Nexen's mutable ROM view with ILLEGAL, and make the
        # interpreter's op_illegal entry a stable BRA -2.  The entry fixture
        # is retained before either validation-only patch.  This avoids
        # thousands of MCP single-step round trips for a true root-interpreted
        # run while stopping before op_illegal mutates architectural state.
        write_u16(m, 0x7E, 0)
        seam_address = OP_ILLEGAL
    else:
        # Production packs out dbg_fetch.  Use the interpreter's supported
        # single-step mode and advance any intermediate IRQ/task opcodes below.
        write_u16(m, 0x7E, 1)
        seam_address = test_idle

    base.set_sa1_pc(m, ENTRY_NATIVE if root_native else inext)
    pre_state_info = None
    if pre_state is not None:
        pre_state.parent.mkdir(parents=True, exist_ok=True)
        response = m.save_state(pre_state.resolve())
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            if pre_state.is_file() and pre_state.stat().st_size:
                break
            time.sleep(0.05)
        else:
            raise RuntimeError(f"save state was not flushed: {pre_state}")
        pre_state_info = {
            "path": str(pre_state.resolve()),
            "sha256": sha256(pre_state),
            "size": pre_state.stat().st_size,
            "response": response,
        }
    terminal_offset = 0x10000 + EXIT_PC
    illegal_offset = OP_ILLEGAL - 0x8000
    terminal_original = b""
    illegal_original = b""
    if terminal_illegal:
        terminal_original = bytes(
            m.read_memory("snesPrgRom", terminal_offset, 2)
        )
        illegal_original = bytes(
            m.read_memory("snesPrgRom", illegal_offset, 2)
        )
        if terminal_original != b"\x4E\x45":
            raise RuntimeError(
                f"terminal ${EXIT_PC:06X} is "
                f"{terminal_original.hex().upper()}, expected TRAP #5 4E45"
            )
        m.write_memory("snesPrgRom", terminal_offset, "4afc")
        m.write_memory("snesPrgRom", illegal_offset, "80fe")

    seam_hook = (
        None
        if boundary_tool is not None
        else m.add_exec_hook(seam_address, cpu_type="Sa1")
    )
    if seam_hook is not None:
        m.drain_notifications(timeout=0.05)
    start_cycles = int(m.get_cpu_state("Sa1")["cycleCount"])
    try:
        if boundary_tool is None:
            hit = m.run_until(
                max_frames=240 if terminal_illegal else 60,
                hook_handle=seam_hook,
            )
        else:
            hit = m.tool(
                boundary_tool,
                {
                    "address": seam_address,
                    "cpuType": "Sa1",
                    "maxFrames": 240 if terminal_illegal else 60,
                    "occurrences": 1,
                },
            )
        ensure_paused(m)
    finally:
        if seam_hook is not None:
            m.remove_hook(seam_hook)
        if terminal_illegal:
            m.write_memory(
                "snesPrgRom", terminal_offset, terminal_original.hex()
            )
            m.write_memory(
                "snesPrgRom", illegal_offset, illegal_original.hex()
            )
    expected_reason = "hookFired" if boundary_tool is None else "breakpoint"
    exact_stop_ok = True
    if boundary_tool is not None:
        exact_address = (
            ((int((hit or {}).get("k", 0)) & 0xFF) << 16)
            | (int((hit or {}).get("pc", 0)) & 0xFFFF)
        )
        exact_stop_ok = (
            exact_address == seam_address
            and int((hit or {}).get("observedOccurrences", -1)) == 1
            and (hit or {}).get("isPaused") is True
            and (hit or {}).get("scopedBreakpointRemoved") is True
        )
        if boundary_tool == "run_to_exact_exec_stop":
            exact_stop_ok = (
                exact_stop_ok
                and (hit or {}).get("exactStopTriggered") is True
                and (hit or {}).get("exactStopBreakDelivered") is True
            )
    if (
        (hit or {}).get("reason") != expected_reason
        or (
            boundary_tool is not None
            and (hit or {}).get("hit") is not True
        )
        or not exact_stop_ok
    ):
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
    observed_pc = common.read_u16(m, 0x40) | (
        (common.read_u16(m, 0x42) & 0xFF) << 16
    )
    handoff_pcs = [observed_pc]
    if diagnostic_fetch_freeze:
        if not common.read_u16(m, 0x0712) or observed_pc != EXIT_PC:
            raise RuntimeError(
                f"Nexen diagnostic freeze stopped at ${observed_pc:06X}, "
                f"marker=${common.read_u16(m, 0x0712):04X}; "
                f"expected ${EXIT_PC:06X}/$0001"
            )
        boundary_mode = "diagnostic_dbg_fetch"
    elif terminal_illegal:
        if observed_pc != EXIT_PC:
            raise RuntimeError(
                f"Nexen terminal-ILLEGAL freeze stopped at "
                f"${observed_pc:06X}, expected ${EXIT_PC:06X}"
            )
        boundary_mode = "production_terminal_illegal"
    else:
        if common.read_u16(m, 0x4E) != 1:
            raise RuntimeError(
                f"Nexen first single-step handoff at ${observed_pc:06X} has "
                f"marker ${common.read_u16(m, 0x4E):04X}, expected $0001"
            )
        # AC-charged native work can legitimately hand off to the interpreted
        # level-6 IRQ handler before the terminal trap.  Execute each such 68K
        # instruction through the interpreter's supported single-step
        # handshake, alternating exact test_idle/inext hooks.
        for _step in range(max_handoffs):
            if observed_pc == EXIT_PC:
                break
            inext_hook = m.add_exec_hook(inext, cpu_type="Sa1")
            write_u16(m, 0xA0, 1)
            step_hit = m.run_until(max_frames=8, hook_handle=inext_hook)
            ensure_paused(m)
            m.remove_hook(inext_hook)
            if (step_hit or {}).get("reason") != "hookFired":
                raise RuntimeError(
                    f"Nexen did not complete single-step opcode "
                    f"${observed_pc:06X}: {step_hit!r}"
                )
            observed_pc = common.read_u16(m, 0x40) | (
                (common.read_u16(m, 0x42) & 0xFF) << 16
            )
            handoff_pcs.append(observed_pc)
            if observed_pc == EXIT_PC:
                break
            idle_hook = m.add_exec_hook(test_idle, cpu_type="Sa1")
            idle_hit = m.run_until(max_frames=8, hook_handle=idle_hook)
            ensure_paused(m)
            m.remove_hook(idle_hook)
            if (idle_hit or {}).get("reason") != "hookFired":
                raise RuntimeError(
                    f"Nexen did not return to test_idle after opcode "
                    f"${handoff_pcs[-2]:06X}: {idle_hit!r}"
                )
        else:
            raise RuntimeError(
                f"Nexen exceeded {max_handoffs} interpreted handoffs; "
                f"last PC=${observed_pc:06X}"
            )
        if observed_pc != EXIT_PC:
            raise RuntimeError(
                f"Nexen stopped at ${observed_pc:06X}, "
                f"expected terminal ${EXIT_PC:06X}"
            )
        boundary_mode = "production_single_step"
    end_cycles = int(m.get_cpu_state("Sa1")["cycleCount"])
    sr = 0x2000 | ((common.read_u16(m, 0x7C) & 7) << 8) | common.captured_ccr(m)
    return (
        base.Result(
            common.captured_regs(m),
            sr,
            bytes(m.read_memory(base.SNES_SPACE, 0x400000, work_size)),
            end_cycles - start_cycles,
        ),
        {
            "mode": boundary_mode,
            "root_native": root_native,
            "interpreted_instruction_count": len(handoff_pcs) - 1,
            "handoff_pcs": [f"{pc:06X}" for pc in handoff_pcs],
            "pre_state": pre_state_info,
        },
    )


def compare(
    case: LiveCase,
    arcade: base.Result,
    console: base.Result,
    xlat_gate: int,
    choke_gate: int,
    boundary: dict,
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
    # Native bridges use bank-$FB/$FC sentinels to resume, so the popped stack
    # residue is observable and must match the original execution exactly.
    # Early fixtures reached this root through the jsr(a4) at $01F096 and
    # therefore left $0001F098 here.  Other organic callers legitimately
    # reuse the same stack slot before the terminal seam; use MAME as the
    # caller-specific oracle instead of hard-coding that one return address.
    residue = ((case.regs["A7"] & 0xFFFF) - 0x12) & 0xFFFF
    observed_mame_return = bytes(
        arcade.work[(residue + index) & 0xFFFF] for index in range(4)
    )
    observed_native_return = bytes(
        console.work[(residue + index) & 0xFFFF] for index in range(4)
    )
    return_residue_exact = observed_native_return == observed_mame_return
    work_mismatches = all_work_mismatches
    ccr_mismatch = (arcade.sr & base.CCR_MASK) != (console.sr & base.CCR_MASK)
    mask_mismatch = ((arcade.sr >> 8) & 7) != ((console.sr >> 8) & 7)
    green = (
        not reg_mismatches
        and not work_mismatches
        and not ccr_mismatch
        and not mask_mismatch
        and return_residue_exact
    )
    return {
        "event": "case",
        "case": case.name,
        "tick": case.tick,
        "terminal_pc": f"{EXIT_PC:06X}",
        "nested_xlat_gate": xlat_gate,
        "fetch_choke_gate": choke_gate,
        "nexen_boundary": boundary,
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
        "return_residue": {
            "reason": (
                "popped native continuation residue at entry A7-$12 must "
                "match the caller-specific MAME result"
            ),
            "address": f"F0{residue:04X}",
            "expected": "MAME_ORACLE",
            "mame": observed_mame_return.hex().upper(),
            "nexen": observed_native_return.hex().upper(),
            "exact": return_residue_exact,
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
        "--fixture-dir",
        type=Path,
        help=(
            "Replay retained case-*.json/case-*.work.bin organic fixtures "
            "instead of capturing from --state."
        ),
    )
    parser.add_argument(
        "--fixtures-captured-at-hot-entry",
        action="store_true",
        help=(
            "Record that replay fixtures were captured after the read-only "
            "bank-$98 guard and therefore replay its idempotent prologue."
        ),
    )
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
    parser.add_argument("--interp-sym", type=Path, default=DEFAULT_INTERP_SYM)
    parser.add_argument(
        "--diagnostic-fetch-freeze",
        action="store_true",
        help=(
            "Require a PC_RING=1 ROM and use dbg_fetch's exact $0710 terminal "
            "freeze. The diagnostic call is size-neutral to production."
        ),
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
    parser.add_argument(
        "--root-interpreted-native-off",
        action="store_true",
        help=(
            "run the all-gates-off variant from inext rather than the native "
            "root; required for a whole-root interpreter comparison"
        ),
    )
    parser.add_argument(
        "--terminal-illegal",
        action="store_true",
        help=(
            "use the reversible production terminal ILLEGAL trap instead of "
            "the single-step handoff loop"
        ),
    )
    parser.add_argument(
        "--retain-prestates",
        action="store_true",
        help=(
            "retain the fully configured native-off/on state before each "
            "bounded execution"
        ),
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    mame_oracle = mame_identity()
    os.environ.update(mame_environment(os.environ))
    for path in (
        args.rom,
        args.nexen,
        args.nat,
        args.candidate_sym,
        args.candidate_hot_sym,
        args.interp_sym,
    ):
        if not path.is_file():
            parser.error(f"missing required input: {path}")
    if args.fixture_dir is None:
        if not args.state.is_file():
            parser.error(f"missing required input: {args.state}")
    elif not args.fixture_dir.is_dir():
        parser.error(f"missing fixture directory: {args.fixture_dir}")
    if args.fixtures_captured_at_hot_entry and args.fixture_dir is None:
        parser.error("--fixtures-captured-at-hot-entry requires --fixture-dir")
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
    test_idle = symbol_offset(args.interp_sym, "test_idle")
    inext = symbol_offset(args.interp_sym, "inext")
    debug_spin = symbol_offset(args.interp_sym, "df_spin")
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
    artifact_dir: Path | None = None
    if args.retain_prestates:
        artifact_dir = args.output.parent / f"{args.output.stem}-artifacts"
        if artifact_dir.exists():
            parser.error(f"artifact directory already exists: {artifact_dir}")
        artifact_dir.mkdir()

    events: list[dict] = []
    provenance = {
        "event": "provenance",
        "scope": (
            "live-fixture function-local $01E7C0 MAME/Nexen differential; "
            "all D/A registers, CCR/mask, mapped 16 KiB work RAM; not fps"
        ),
        "mame": mame_oracle,
        "nexen": str(args.nexen.resolve()),
        "nexen_sha256": sha256(args.nexen),
        "rom": str(args.rom.resolve()),
        "rom_sha256": sha256(args.rom),
        "state": str(args.state.resolve()) if args.fixture_dir is None else None,
        "state_sha256": sha256(args.state) if args.fixture_dir is None else None,
        "fixture_source": (
            str(args.fixture_dir.resolve()) if args.fixture_dir is not None else None
        ),
        "nat": str(args.nat.resolve()),
        "nat_sha256": sha256(args.nat),
        "entry_pc": f"{ENTRY_PC:06X}",
        "entry_native": f"{ENTRY_NATIVE:06X}",
        "capture_native": f"{capture_native:06X}",
        "capture_after_read_only_root_guard": (
            args.capture_hot_entry
            if args.fixture_dir is None
            else args.fixtures_captured_at_hot_entry
        ),
        "capture_replayed_idempotent_prologue": (
            args.capture_hot_entry
            if args.fixture_dir is None
            else args.fixtures_captured_at_hot_entry
        ),
        "terminal_pc": f"{EXIT_PC:06X}",
        "nexen_boundary_method": (
            (
                f"PC_RING=1 dbg_fetch freeze at df_spin=${debug_spin:06X}; "
                "intermediate IRQ/task work runs normally; terminal opcode "
                "not executed"
            )
            if args.diagnostic_fetch_freeze
            else (
                f"production single-step first native-to-inext handoff; "
                f"test_idle=${test_idle:06X}, inext=${inext:06X}; "
                "intermediate IRQ/task opcodes single-stepped; terminal "
                "opcode not executed"
            )
        ),
        "pc_ring_diagnostic": args.diagnostic_fetch_freeze,
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
            "historical_01F096_caller_return": "0001F098",
            "internal_native_continuations": {
                "generated": f"00FB{candidate_br10:04X}",
                "hot": f"00FC{candidate_hot_return:04X}",
            },
            "required_post_pop_residue": (
                "exact caller-specific MAME bytes at entry A7-$12; "
                "full mapped-work equality remains mandatory"
            ),
        },
        "fixtures": args.cases,
        "variants_per_fixture": len(variants),
        "variants": [
            {"nested_xlat_gate": xlat, "fetch_choke_gate": choke}
            for xlat, choke in variants
        ],
        "root_interpreted_native_off": args.root_interpreted_native_off,
        "terminal_illegal": args.terminal_illegal,
        "retain_prestates": args.retain_prestates,
        "artifact_directory": (
            str(artifact_dir.resolve()) if artifact_dir is not None else None
        ),
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

    if args.fixture_dir is None:
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
    else:
        cases = load_fixture_cases(args.fixture_dir, args.cases)
        rejected = []
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
            mame=str(MAME),
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
                root_native = not (
                    args.root_interpreted_native_off
                    and xlat_gate == 0
                    and choke_gate == 0
                )
                configuration = (
                    "root-interpreted-gates-0-0"
                    if not root_native
                    else f"native-root-xlat-{xlat_gate}-choke-{choke_gate}"
                )
                console, boundary = nexen_result(
                    nexen,
                    args.nat,
                    case,
                    xlat_gate=xlat_gate,
                    choke_gate=choke_gate,
                    test_idle=test_idle,
                    inext=inext,
                    debug_spin=debug_spin,
                    diagnostic_fetch_freeze=args.diagnostic_fetch_freeze,
                    root_native=root_native,
                    pre_state=(
                        artifact_dir
                        / "prestates"
                        / configuration
                        / f"{case.name}.mss"
                        if artifact_dir is not None
                        else None
                    ),
                    terminal_illegal=args.terminal_illegal,
                )
                event = compare(
                    case,
                    arcade[case.name],
                    console,
                    xlat_gate,
                    choke_gate,
                    boundary,
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
