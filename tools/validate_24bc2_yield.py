#!/usr/bin/env python3
"""Three-way regression for the $024BC2 task's terminal TRAP #5 state.

The campaign boundary at movie tick 7498 exposed a saved task frame at
``$F00D00`` whose SR differed as MAME/native-off/native-on
``$2404/$2414/$2419``.  A checkpoint replay is not a valid native-off oracle
when that checkpoint was created with native escapes enabled, so this harness
extracts the complete task context from the MAME work image and injects that
one identical architectural state into all three configurations:

* MAME 0.287 executes the original $024BC2 body to its $024BC0 TRAP;
* Nexen interprets the body with both gameplay native gates disabled; and
* Nexen enters the production coroutine xlat route with both gates enabled.

Every D/A register, X/N/Z/V/C, interrupt mask, and mapped 16 KiB work byte is
compared.  Native continuation addresses below the restored terminal A7 are
reported and accepted only as popped task-stack residue; no live byte at or
above A7, and no non-stack work byte, may differ.

This is a deterministic function-level differential from a fresh-campaign
fixture.  It is not fresh-boot, whole-program, performance, or FPS evidence.
The Nexen ROM must be a current ``PC_RING=1`` diagnostic build so the
pre-TRAP instruction boundary can be frozen without executing the trap.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import validate_d96_hle as base
import validate_1f2e4_native as live
import validate_fanout_native as fanout
from mame_0287 import MAME, environment as mame_environment
from mame_0287 import identity as mame_identity


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "build" / "playtest-investigation-20260725"
DEFAULT_WORK = (
    EVIDENCE
    / "mame-crate-held-downright-3213-3300-mame0287-v7"
    / "mame-branch-entry-tick-03295.work.bin"
)
DEFAULT_NAT = Path("/tmp/b0_native.mss")
ENTRY_PC = 0x024BC2
EXIT_PC = 0x024BC0
INEXT = 0x00D128
OJMP_HOOK = 0x00D1B3
DEBUG_SPIN = 0x00E2CF
MAPPED_WORK_SIZE = 0x4000
FULL_WORK_SIZE = 0x10000
CCR_MASK = 0x1F
TASK_REGISTER_COUNT = 15
TASK_FRAME_BYTES = TASK_REGISTER_COUNT * 4
EXCEPTION_FRAME_BYTES = 6
POPPED_STACK_WINDOW = 0x0200
REG_NAMES = tuple(
    [f"D{index}" for index in range(8)]
    + [f"A{index}" for index in range(8)]
)


@dataclass(frozen=True)
class Fixture:
    name: str
    regs: dict[str, int]
    sr: int
    work: bytes
    task: int
    saved_sp: int
    sr_offset: int
    entry_a7: int
    tick: int


@dataclass(frozen=True)
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


def be16(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 2], "big")


def be32(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 4], "big")


def extract_fixture(work: bytes, task: int) -> Fixture:
    if len(work) != FULL_WORK_SIZE:
        raise RuntimeError(
            f"fixture work image is {len(work)} bytes, expected {FULL_WORK_SIZE}"
        )
    if not 0 <= task < 16:
        raise RuntimeError(f"invalid task index {task}")
    saved_sp = be32(work, 0x0A + task * 4)
    if saved_sp >> 16 != 0x00F0:
        raise RuntimeError(
            f"task {task} saved SP is not work RAM: ${saved_sp:08X}"
        )
    saved_offset = saved_sp & 0xFFFF
    sr_offset = saved_offset + TASK_FRAME_BYTES
    if sr_offset + EXCEPTION_FRAME_BYTES > FULL_WORK_SIZE:
        raise RuntimeError("task context crosses the work-RAM allocation")
    resume_pc = be32(work, sr_offset + 2) & 0xFFFFFF
    if resume_pc != ENTRY_PC:
        raise RuntimeError(
            f"task {task} resumes at ${resume_pc:06X}, expected ${ENTRY_PC:06X}"
        )
    restored_names = REG_NAMES[:-1]
    regs = {
        name: be32(work, saved_offset + index * 4)
        for index, name in enumerate(restored_names)
    }
    entry_a7 = 0x00F00000 | (sr_offset + EXCEPTION_FRAME_BYTES)
    regs["A7"] = entry_a7
    sr = be16(work, sr_offset)
    return Fixture(
        name="campaign-task6-x0",
        regs=regs,
        sr=sr,
        work=work,
        task=task,
        saved_sp=saved_sp,
        sr_offset=sr_offset,
        entry_a7=entry_a7,
        tick=be16(work, 0x1C56),
    )


def mame_result(session: base.MameSession, fixture: Fixture) -> Result:
    session.pause()
    installed = session.exec_lua(
        "if MCP_24BC2_EXIT_NOP then MCP_24BC2_EXIT_NOP:remove() end "
        "MCP_24BC2_EXIT_NOP = "
        "M.devices[':maincpu'].spaces['program']:install_read_tap("
        f"0x{EXIT_PC:06X}, 0x{EXIT_PC + 1:06X}, "
        "'mcp_24bc2_exit_nop', "
        "function(offset, data, mask) return 0x4E71 end); return true"
    )
    if not installed:
        raise RuntimeError("failed to install the MAME terminal NOP tap")
    session.write_block(0xF00000, fixture.work[:MAPPED_WORK_SIZE])
    for name in REG_NAMES[:-1]:
        session.set_reg(name, fixture.regs[name])
    session.set_reg("USP", fixture.regs["A7"])
    session.set_reg("SP", fixture.regs["A7"])
    # Mask unrelated VBLANK only for this bounded function.  The tested path
    # neither reads nor writes SR; the architectural entry mask is restored
    # in the reported result.
    session.set_reg("SR", fixture.sr | 0x0700)
    session.set_reg("PC", ENTRY_PC)
    try:
        captured = session.cmd(
            "capture_at_pc",
            pc=ENTRY_PC,
            addr=0xF00000,
            len=MAPPED_WORK_SIZE,
            nth=1,
            exp_sp=fixture.regs["A7"] & 0xFFFFFF,
            maxFrames=120,
            timeout=120,
        )
    finally:
        session.exec_lua(
            "if MCP_24BC2_EXIT_NOP then MCP_24BC2_EXIT_NOP:remove(); "
            "MCP_24BC2_EXIT_NOP=nil end; return true"
        )
    if not captured.get("registers"):
        raise RuntimeError(
            f"MAME did not reach the committed post-NOP seam for {fixture.name}: "
            f"{captured!r}"
        )
    raw = captured["registers"]
    regs = {
        name: raw[name] & 0xFFFFFFFF for name in REG_NAMES[:-1]
    }
    regs["A7"] = raw["SP"] & 0xFFFFFFFF
    sr = (
        (raw["SR"] & 0xFFFF & ~0x0700)
        | (fixture.sr & 0x0700)
    )
    return Result(
        regs=regs,
        sr=sr,
        work=bytes.fromhex(captured["hex"]),
        physical_mask=(raw["SR"] >> 8) & 7,
    )


def fanout_case(fixture: Fixture) -> fanout.Case:
    span = fanout.Span(
        name=fixture.name,
        entry_pc=ENTRY_PC,
        entry_symbol="entry_24bc2",
        exit_pc=EXIT_PC,
        mame_prefetch_pc=ENTRY_PC,
    )
    return fanout.Case(
        name=fixture.name,
        span=span,
        regs=fixture.regs,
        sr=fixture.sr,
        work=fixture.work,
        tick=fixture.tick,
        frame=0,
        capture_frames_advanced=0,
    )


def nexen_result(
    session: base.McpSession,
    nat: Path,
    fixture: Fixture,
    *,
    native: bool,
) -> Result:
    case = fanout_case(fixture)
    fanout.prepare_console(session, nat, case, target_pc=EXIT_PC)
    live.write_u16(session, 0x071A, 1 if native else 0)
    live.write_u16(session, 0x073A, 1 if native else 0)
    start_pc = OJMP_HOOK if native else INEXT
    live.set_sa1_pc(session, start_pc)
    hook = session.add_exec_hook(DEBUG_SPIN, cpu_type="Sa1")
    session.drain_notifications(timeout=0.05)
    start_cycles = int(session.get_cpu_state("Sa1")["cycleCount"])
    try:
        hit = session.run_until(max_frames=240, hook_handle=hook)
        session.pause()
    finally:
        session.remove_hook(hook)
    if (hit or {}).get("reason") != "hookFired":
        raise RuntimeError(
            f"Nexen {'native' if native else 'interpreted'} arm did not "
            f"freeze before ${EXIT_PC:06X}: {hit!r}"
        )
    observed_pc = live.read_u16(session, 0x40) | (
        (live.read_u16(session, 0x42) & 0xFF) << 16
    )
    if not live.read_u16(session, 0x0712) or observed_pc != EXIT_PC:
        raise RuntimeError(
            f"Nexen {'native' if native else 'interpreted'} arm froze at "
            f"${observed_pc:06X}, expected ${EXIT_PC:06X}"
        )
    end_cycles = int(session.get_cpu_state("Sa1")["cycleCount"])
    return Result(
        regs=live.captured_regs(session),
        sr=(
            0x2000
            | (fixture.sr & 0x0700)
            | live.captured_ccr(session)
        ),
        work=bytes(
            session.read_memory(
                base.SNES_SPACE, 0x400000, MAPPED_WORK_SIZE
            )
        ),
        cycles=end_cycles - start_cycles,
        physical_mask=live.read_u16(session, 0x7C) & 7,
    )


def compare(
    fixture: Fixture,
    arcade: Result,
    console: Result,
    *,
    native: bool,
) -> dict[str, Any]:
    reg_mismatches = {
        name: {
            "mame": f"{arcade.regs[name]:08X}",
            "nexen": f"{console.regs[name]:08X}",
        }
        for name in REG_NAMES
        if arcade.regs[name] != console.regs[name]
    }
    all_work_mismatches = [
        offset
        for offset, (left, right) in enumerate(
            zip(arcade.work, console.work, strict=True)
        )
        if left != right
    ]
    entry_sp = fixture.entry_a7 & 0xFFFF
    residue_start = max(0, entry_sp - POPPED_STACK_WINDOW)
    popped_residue = [
        offset
        for offset in all_work_mismatches
        if residue_start <= offset < entry_sp
    ]
    live_work_mismatches = [
        offset
        for offset in all_work_mismatches
        if offset not in set(popped_residue)
    ]
    # The interpreted arm executes the same 68000 calls and returns, so even
    # popped residue must match.  Only native continuation sentinels may use
    # the explicit dead-stack allowance.
    residue_valid = native or not popped_residue
    ccr_match = (arcade.sr & CCR_MASK) == (console.sr & CCR_MASK)
    mask_match = ((arcade.sr >> 8) & 7) == ((console.sr >> 8) & 7)
    green = (
        not reg_mismatches
        and ccr_match
        and mask_match
        and not live_work_mismatches
        and residue_valid
    )
    return {
        "event": "case",
        "fixture": fixture.name,
        "configuration": "native-on" if native else "native-off",
        "result": "green" if green else "red",
        "entry_sr": f"{fixture.sr:04X}",
        "mame_terminal_sr": f"{arcade.sr:04X}",
        "nexen_terminal_sr": f"{console.sr:04X}",
        "mame_terminal_ccr_xnzvc": arcade.sr & CCR_MASK,
        "nexen_terminal_ccr_xnzvc": console.sr & CCR_MASK,
        "register_mismatches": reg_mismatches,
        "interrupt_mask_match": mask_match,
        "work_mismatch_count": len(all_work_mismatches),
        "live_work_mismatch_count": len(live_work_mismatches),
        "live_work_mismatch_first": [
            f"F0{offset:04X}" for offset in live_work_mismatches[:32]
        ],
        "popped_task_stack_residue": {
            "accepted": native,
            "range": f"F0{residue_start:04X}-F0{entry_sp - 1:04X}",
            "terminal_a7": f"F0{entry_sp:04X}",
            "different_bytes": len(popped_residue),
            "rows": [
                {
                    "address": f"F0{offset:04X}",
                    "mame": arcade.work[offset],
                    "nexen": console.work[offset],
                }
                for offset in popped_residue[:96]
            ],
        },
        "nexen_cycles_local": console.cycles,
        "physical_irq_mask": {
            "mame": arcade.physical_mask,
            "nexen": console.physical_mask,
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, required=True)
    parser.add_argument("--work", type=Path, default=DEFAULT_WORK)
    parser.add_argument("--task", type=int, default=6)
    parser.add_argument("--nexen", type=Path, default=base.DEFAULT_NEXEN)
    parser.add_argument("--nat", type=Path, default=DEFAULT_NAT)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--port", type=int, default=9560)
    args = parser.parse_args()
    for label, path in (
        ("diagnostic ROM", args.rom),
        ("campaign work fixture", args.work),
        ("Nexen", args.nexen),
        ("native initialization state", args.nat),
    ):
        if not path.is_file():
            parser.error(f"missing {label}: {path}")
    if args.output.exists():
        parser.error(f"output already exists: {args.output}")
    rom = args.rom.read_bytes()
    if len(rom) != 0x400000:
        parser.error("expected a 4 MiB diagnostic ROM")
    recorder = bytes.fromhex("2081e2")
    if [rom[offset : offset + 3] for offset in (0x00EB, 0x80EB)] != [
        recorder,
        recorder,
    ]:
        parser.error("selected ROM is not a PC_RING=1 diagnostic build")
    if int.from_bytes(rom[0x77E0:0x77E2], "little") != 0:
        parser.error("TESTFLAG must remain zero")
    return args


def main() -> int:
    args = parse_args()
    mame_oracle = mame_identity()
    os.environ.update(mame_environment(os.environ))
    args.output.mkdir(parents=True)
    retained_rom = args.output / "diagnostic-rom.sfc"
    shutil.copy2(args.rom, retained_rom)
    if sha256(retained_rom) != sha256(args.rom):
        raise RuntimeError("failed to retain the exact diagnostic ROM")
    work = args.work.read_bytes()
    base_fixture = extract_fixture(work, args.task)
    fixtures = [
        base_fixture,
        replace(
            base_fixture,
            name="campaign-task6-x1",
            sr=base_fixture.sr | 0x0010,
        ),
    ]
    fixture_copy = args.output / "source.work.bin"
    fixture_copy.write_bytes(work)
    metadata = {
        "event": "provenance",
        "scope": (
            "same-input function-level MAME 0.287/native-off/native-on "
            "$024BC2-to-$024BC0 differential; all D/A, X/N/Z/V/C, mask, "
            "and mapped 16 KiB work RAM; not fresh-boot or FPS evidence"
        ),
        "classification_target": (
            "native/HLE terminal CCR and CMP-preserves-X semantics; separates "
            "them from stale native-on task-frame data in checkpoint replays"
        ),
        "mame": mame_oracle,
        "nexen": str(args.nexen.resolve()),
        "nexen_sha256": sha256(args.nexen),
        "rom": str(args.rom.resolve()),
        "rom_sha256": sha256(args.rom),
        "retained_rom": str(retained_rom.resolve()),
        "retained_rom_sha256": sha256(retained_rom),
        "pc_ring": True,
        "work_source": str(args.work.resolve()),
        "work_source_sha256": sha256(args.work),
        "retained_work_copy": str(fixture_copy.resolve()),
        "retained_work_copy_sha256": sha256(fixture_copy),
        "task": args.task,
        "saved_sp": f"{base_fixture.saved_sp:08X}",
        "saved_sr_address": f"F0{base_fixture.sr_offset:04X}",
        "saved_resume_pc": f"{ENTRY_PC:06X}",
        "entry_a7": f"{base_fixture.entry_a7:08X}",
        "entry_tick": base_fixture.tick,
        "variants": [
            {"name": fixture.name, "entry_sr": f"{fixture.sr:04X}"}
            for fixture in fixtures
        ],
        "irq_isolation": (
            "both oracles physically mask level 7 for the bounded span; "
            "the architectural fixture mask is restored in comparisons"
        ),
        "time_unix": time.time(),
    }
    events: list[dict[str, Any]] = [metadata]
    print(json.dumps(metadata, sort_keys=True), flush=True)

    arcade: dict[str, Result] = {}
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
        for fixture in fixtures:
            arcade[fixture.name] = mame_result(mame, fixture)
            row = {
                "event": "mame_case",
                "fixture": fixture.name,
                "terminal_sr": f"{arcade[fixture.name].sr:04X}",
            }
            events.append(row)
            print(json.dumps(row, sort_keys=True), flush=True)
    finally:
        mame.stop()

    with base.McpSession(
        rom=str(args.rom.resolve()),
        mesen=str(args.nexen.resolve()),
        cwd=ROOT,
        port=args.port,
        boot_wait=8.0,
        socket_timeout=300.0,
        stderr_log=args.output / "nexen.stderr.log",
    ) as nexen:
        for fixture in fixtures:
            for native in (False, True):
                console = nexen_result(
                    nexen,
                    args.nat.resolve(),
                    fixture,
                    native=native,
                )
                row = compare(
                    fixture,
                    arcade[fixture.name],
                    console,
                    native=native,
                )
                events.append(row)
                print(json.dumps(row, sort_keys=True), flush=True)

    rows = [row for row in events if row.get("event") == "case"]
    green = sum(row["result"] == "green" for row in rows)
    summary = {
        "event": "summary",
        "result": "green" if green == len(rows) else "red",
        "green": green,
        "red": len(rows) - green,
        "total": len(rows),
        "classification": (
            "same_input_interpreter_and_native_semantics_exact"
            if green == len(rows)
            else "same_input_semantic_difference"
        ),
        "checkpoint_observation": {
            "mame": "2404",
            "native_off_from_native_on_checkpoint": "2414",
            "native_on": "2419",
            "note": (
                "the old native-off arm inherited X from a native-on-created "
                "checkpoint and was not a same-prestate comparison"
            ),
        },
        "time_unix": time.time(),
    }
    events.append(summary)
    (args.output / "events.jsonl").write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in events),
        encoding="utf-8",
    )
    event_path = args.output / "events.jsonl"
    (args.output / "summary.json").write_text(
        json.dumps(
            {
                **summary,
                "provenance": metadata,
                "cases": rows,
                "events": str(event_path.resolve()),
                "events_sha256": sha256(event_path),
                "validator": str(Path(__file__).resolve()),
                "validator_sha256": sha256(Path(__file__).resolve()),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, sort_keys=True), flush=True)
    return 0 if summary["result"] == "green" else 1


if __name__ == "__main__":
    raise SystemExit(main())
