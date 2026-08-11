#!/usr/bin/env python3
"""Capture an interpreted MC68000 logical entry at a stable Nexen stop.

Native-off execution has no SA-1 entry address to hook.  This diagnostic
temporarily replaces the selected MC68000 opcode with the interpreter's
unsupported-opcode sentinel, waits for the stable halt, restores the ROM, and
retains the pre-instruction registers/work RAM.  The interpreter leaves the
logical PC on the rejected opcode; no game instruction at the selected PC has
executed.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

import replay_mame_controller_campaign as campaign


ROOT = Path(__file__).resolve().parents[1]
PROGRAM_ROM_BASE = 0x010000
HALT_IRAM = 0x004E
TEST_FLAG_IRAM = 0x007E
TEST_GO_IRAM = 0x00A0
ILOOP_NATIVE = 0x0080A5
# The live paced-gameplay reload is the immediate in bank-$97
# campaign_irq_reload.  The historical bank-$00 boot literal at $0000AD and
# the following opcode bytes in the bank-$97 helper are not the seam.
IRQ_RELOAD_IMMEDIATE_ROM_OFFSET = 0x2BE5C3
IRQ_RELOAD_IMMEDIATE_EXPECTED = bytes.fromhex("0070")
PACING_ONLY_GATES = (0x071A, 0x0736, 0x073A, 0x073C)
PACING_ONLY_ROM_PATCHES = (
    # Preserve loop_hook's $0818 paced-tick bridge, but make every other
    # logical-PC lookup return through the existing CLC;RTS miss path.
    ("non_0818_loop_hook", 0x0075A8, "c9843b", "4cc0f5"),
    # Park the three scheduler accelerators individually.  Clearing $072E
    # would also remove the mandatory $0818 bridge and is not comparable.
    ("switch_out_0532", 0x007FCB, "3205", "ffff"),
    ("scheduler_scan_074c", 0x0079AB, "4c07", "ffff"),
    ("switch_in_0796", 0x007FD4, "9607", "ffff"),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, default=campaign.DEFAULT_ROM)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--logical-pc", type=lambda value: int(value, 0), required=True)
    parser.add_argument("--advance-ticks", type=int, default=0)
    parser.add_argument(
        "--skip-logical-hits",
        type=int,
        default=0,
        help=(
            "execute this many earlier occurrences of --logical-pc exactly "
            "before retaining the next one; the diagnostic resumes each "
            "sentinel halt through iloop's built-in one-opcode test path"
        ),
    )
    parser.add_argument(
        "--gameplay-native",
        choices=("preserve", "off", "pacing-only"),
        default="off",
        help=(
            "preserve the checkpoint configuration, disable translated and "
            "fetch-chokepoint gameplay roots, or retain only the mandatory "
            "$0818 paced-tick bridge while interpreting gameplay, loop, and "
            "scheduler paths"
        ),
    )
    parser.add_argument(
        "--irq-reload",
        type=lambda value: int(value, 0),
        help=(
            "diagnostic only: temporarily replace the gameplay virtual-IRQ "
            "reload immediate; ROM bytes are restored and recorded"
        ),
    )
    parser.add_argument("--nexen", type=Path, default=campaign.DEFAULT_NEXEN)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--port", type=int, default=9528)
    parser.add_argument("--max-frames", type=int, default=480)
    args = parser.parse_args()
    for label, path in (
        ("ROM", args.rom),
        ("state", args.state),
        ("Nexen", args.nexen),
    ):
        if not path.is_file():
            parser.error(f"missing {label}: {path}")
    if args.output.exists():
        parser.error(f"output already exists: {args.output}")
    if not 0 <= args.logical_pc < 0x80000 or args.logical_pc & 1:
        parser.error("--logical-pc must be an even address in 0..0x7fffe")
    if args.advance_ticks < 0:
        parser.error("--advance-ticks cannot be negative")
    if args.skip_logical_hits < 0:
        parser.error("--skip-logical-hits cannot be negative")
    if args.max_frames < 1:
        parser.error("--max-frames must be positive")
    if args.irq_reload is not None and not 1 <= args.irq_reload <= 0xFFFF:
        parser.error("--irq-reload must be in 1..0xffff")
    return args


def full_work(m: campaign.McpSession) -> bytes:
    return b"".join(
        bytes(m.read_memory("snesMemory", 0x400000 + offset, 0x4000))
        for offset in range(0, 0x10000, 0x4000)
    )


def logical_state(m: campaign.McpSession) -> dict[str, Any]:
    iram = bytes(m.read_memory("Sa1Memory", 0, 0x0800))
    return {
        "frame": int(m.get_state().get("frameCount", 0)),
        "snes_tick": campaign.tick16(m),
        "halt": campaign.halt16(m),
        "logical_pc": (
            int.from_bytes(iram[0x40:0x44], "little") & 0xFFFFFF
        ),
        "opcode": int.from_bytes(iram[0x44:0x46], "little"),
        "virtual_irq_pending": int.from_bytes(iram[0xAA:0xAC], "little"),
        "virtual_irq_countdown": int.from_bytes(iram[0xAC:0xAE], "little"),
        "m68k": campaign.register_snapshot(m),
        "player": campaign.player_snapshot(m),
        "sa1_cpu": m.get_cpu_state("Sa1"),
    }


def run_to_sentinel(
    m: campaign.McpSession,
    max_frames: int,
) -> list[dict[str, Any]]:
    """Run until the unsupported-opcode sentinel sets the halt word."""
    attempts: list[dict[str, Any]] = []
    for _frame in range(max_frames):
        response = dict(m.run_frames(1))
        m.pause()
        attempts.append(response)
        if campaign.halt16(m):
            break
    return attempts


def resume_one_original_opcode(
    m: campaign.McpSession,
    *,
    logical_pc: int,
) -> dict[str, Any]:
    """Resume a sentinel halt and execute exactly the rejected opcode once."""
    before = logical_state(m)
    if before["halt"] != 0xDEAD or before["logical_pc"] != logical_pc:
        raise RuntimeError(
            "cannot resume skipped logical hit from unexpected state: "
            f"{before}"
        )
    old_test_flag = bytes(
        m.read_memory("Sa1Memory", TEST_FLAG_IRAM, 1)
    )
    m.write_u16(HALT_IRAM, 0, "Sa1Memory")
    m.write_memory("Sa1Memory", TEST_FLAG_IRAM, "01")
    redirect = dict(
        m.tool(
            "set_cpu_state",
            {
                "cpuType": "Sa1",
                "k": 0,
                "pc": ILOOP_NATIVE & 0xFFFF,
            },
        )
    )
    response = dict(m.run_frames(1))
    m.pause()
    after_step = logical_state(m)
    if (
        after_step["halt"] != 1
        or after_step["logical_pc"] == logical_pc
    ):
        raise RuntimeError(
            "one-opcode sentinel resume failed: "
            f"response={response}, state={after_step}"
        )
    m.write_memory(
        "Sa1Memory", TEST_FLAG_IRAM, old_test_flag.hex()
    )
    m.write_u16(HALT_IRAM, 0, "Sa1Memory")
    m.write_memory("Sa1Memory", TEST_GO_IRAM, "01")
    return {
        "before": before,
        "native_iloop_redirect": redirect,
        "step_response": response,
        "after_step": after_step,
        "test_flag_restored": old_test_flag.hex(),
        "continuation": (
            "test_idle consumes the diagnostic go byte and refetches the "
            "next logical instruction through the unmodified iloop"
        ),
    }


def main() -> int:
    args = parse_args()
    campaign.configure_dotnet(args.nexen)
    os.environ.setdefault("DOTNET_ROOT", "/home/chad/.dotnet10")
    output = args.output.resolve()
    output.mkdir(parents=True)
    rom = args.rom.resolve()
    rom_offset = PROGRAM_ROM_BASE + args.logical_pc
    source_rom = rom.read_bytes()
    original = source_rom[rom_offset : rom_offset + 2]
    if len(original) != 2:
        raise RuntimeError("logical opcode lies outside the selected ROM")
    sentinel = bytes.fromhex("a000")
    spans: list[dict[str, Any]] = []
    interventions: list[dict[str, Any]] = []
    rom_patches: list[dict[str, Any]] = []

    with campaign.McpSession(
        rom=rom,
        mesen=args.nexen.resolve(),
        cwd=ROOT,
        port=args.port,
        boot_wait=6.0,
        socket_timeout=300.0,
        stderr_log=output / "emulator.stderr.log",
    ) as m:
        m.pause()
        load_response = m.load_state(args.state.resolve())
        m.pause()
        try:
            gate_addresses = (
                (0x071A, 0x073A)
                if args.gameplay_native == "off"
                else (
                    PACING_ONLY_GATES
                    if args.gameplay_native == "pacing-only"
                    else ()
                )
            )
            for address in gate_addresses:
                before_gate = int.from_bytes(
                    m.read_memory("Sa1Memory", address, 2), "little"
                )
                m.write_u16(address, 0, "Sa1Memory")
                interventions.append(
                    {
                        "kind": "native_gate_classification",
                        "address": f"{address:04X}",
                        "before": before_gate,
                        "after": 0,
                    }
                )
            if args.gameplay_native == "pacing-only":
                for label, patch_offset, expected_hex, replacement_hex in (
                    PACING_ONLY_ROM_PATCHES
                ):
                    expected = bytes.fromhex(expected_hex)
                    live = bytes(
                        m.read_memory(
                            "snesPrgRom", patch_offset, len(expected)
                        )
                    )
                    if live != expected:
                        raise RuntimeError(
                            f"{label} seam changed: expected {expected_hex}, "
                            f"found {live.hex()}"
                        )
                    m.write_memory(
                        "snesPrgRom", patch_offset, replacement_hex
                    )
                    patch = {
                        "kind": "debugger_pacing_only_classification",
                        "label": label,
                        "rom_offset": f"{patch_offset:06X}",
                        "before": expected_hex,
                        "temporary": replacement_hex,
                        "restored": True,
                    }
                    rom_patches.append(patch)
                    interventions.append(patch)
            if args.irq_reload is not None:
                live = bytes(
                    m.read_memory(
                        "snesPrgRom",
                        IRQ_RELOAD_IMMEDIATE_ROM_OFFSET,
                        2,
                    )
                )
                expected = IRQ_RELOAD_IMMEDIATE_EXPECTED
                if live != expected:
                    raise RuntimeError(
                        "virtual-IRQ reload seam changed: expected "
                        f"{expected.hex()}, found {live.hex()}"
                    )
                replacement = args.irq_reload.to_bytes(2, "little")
                m.write_memory(
                    "snesPrgRom",
                    IRQ_RELOAD_IMMEDIATE_ROM_OFFSET,
                    replacement.hex(),
                )
                patch = {
                    "kind": "debugger_virtual_irq_reload_classification",
                    "rom_offset": (
                        f"{IRQ_RELOAD_IMMEDIATE_ROM_OFFSET:06X}"
                    ),
                    "before": expected.hex(),
                    "temporary": replacement.hex(),
                    "value": args.irq_reload,
                    "restored": True,
                }
                rom_patches.append(patch)
                interventions.append(patch)

            if args.advance_ticks:
                spans = campaign.run_tick_delta(m, args.advance_ticks)
            before = logical_state(m)
            before_work = full_work(m)
            before_path = output / "before.work.bin"
            before_path.write_bytes(before_work)

            live_original = bytes(
                m.read_memory("snesPrgRom", rom_offset, 2)
            )
            if live_original != original:
                raise RuntimeError(
                    f"logical opcode seam changed: file={original.hex()} "
                    f"live={live_original.hex()}"
                )
            attempts: list[dict[str, Any]] = []
            skipped_hits: list[dict[str, Any]] = []
            after: dict[str, Any] | None = None
            for hit_index in range(args.skip_logical_hits + 1):
                live_original = bytes(
                    m.read_memory("snesPrgRom", rom_offset, 2)
                )
                if live_original != original:
                    raise RuntimeError(
                        "logical opcode seam was not restored between hits: "
                        f"expected {original.hex()}, "
                        f"found {live_original.hex()}"
                    )
                m.write_memory(
                    "snesPrgRom", rom_offset, sentinel.hex()
                )
                try:
                    hit_attempts = run_to_sentinel(
                        m, args.max_frames
                    )
                finally:
                    m.write_memory(
                        "snesPrgRom", rom_offset, original.hex()
                    )
                    m.drain_notifications(timeout=0.02)
                hit_state = logical_state(m)
                attempts.append(
                    {
                        "hit": hit_index + 1,
                        "run_attempts": hit_attempts,
                        "state": hit_state,
                    }
                )
                if hit_state["halt"] == 0:
                    raise RuntimeError(
                        "logical entry did not reach the sentinel: "
                        f"attempts={hit_attempts}, state={hit_state}"
                    )
                if hit_state["logical_pc"] != args.logical_pc:
                    raise RuntimeError(
                        "sentinel stopped at the wrong logical PC: "
                        f"{hit_state['logical_pc']:#x}"
                    )
                if hit_index == args.skip_logical_hits:
                    after = hit_state
                    break
                skipped_hits.append(
                    {
                        "hit": hit_index + 1,
                        "captured": hit_state,
                        "resume": resume_one_original_opcode(
                            m,
                            logical_pc=args.logical_pc,
                        ),
                    }
                )
            if after is None:
                raise RuntimeError("logical-hit loop ended without a capture")
            after_work = full_work(m)
            after_path = output / "entry.work.bin"
            after_path.write_bytes(after_work)
        finally:
            for patch in reversed(rom_patches):
                m.write_memory(
                    "snesPrgRom",
                    int(patch["rom_offset"], 16),
                    patch["before"],
                )
            m.drain_notifications(timeout=0.05)
        state = campaign.save_state(m, output / "entry-halted.mss")

    result = {
        "scope": (
            f"checkpointed {args.gameplay_native} same-logical-PC capture; "
            "transient "
            "unsupported-opcode sentinel restored before state save; selected "
            "game instruction not executed; no work-RAM injection; not "
            "fresh-boot or performance proof"
        ),
        "rom": str(rom),
        "rom_sha256": campaign.sha256(rom),
        "state": str(args.state.resolve()),
        "state_sha256": campaign.sha256(args.state),
        "nexen": str(args.nexen.resolve()),
        "nexen_sha256": campaign.sha256(args.nexen),
        "logical_pc": f"{args.logical_pc:06X}",
        "advance_ticks": args.advance_ticks,
        "skip_logical_hits": args.skip_logical_hits,
        "gameplay_native": args.gameplay_native,
        "irq_reload": args.irq_reload,
        "diagnostic_interventions": interventions,
        "load_response": load_response,
        "spans": spans,
        "before": before,
        "entry": after,
        "attempts": attempts,
        "skipped_hits": skipped_hits,
        "opcode_patch": {
            "rom_offset": f"{rom_offset:06X}",
            "before": original.hex(),
            "temporary": sentinel.hex(),
            "restored": True,
            "instruction_executed": False,
        },
        "before_work": {
            "path": str(before_path),
            "sha256": campaign.digest(before_work),
        },
        "entry_work": {
            "path": str(after_path),
            "sha256": campaign.digest(after_work),
            "changed_from_before_bytes": sum(
                left != right
                for left, right in zip(before_work, after_work, strict=True)
            ),
        },
        "entry_state": state,
    }
    summary = output / "summary.json"
    summary.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "summary": str(summary),
                "logical_pc": result["logical_pc"],
                "captured_pc": f"{after['logical_pc']:06X}",
                "halt": f"{after['halt']:04X}",
                "snes_tick": after["snes_tick"],
                "frame": after["frame"],
            },
            sort_keys=True,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
