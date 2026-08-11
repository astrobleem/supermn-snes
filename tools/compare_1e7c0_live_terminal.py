#!/usr/bin/env python3
"""Compare native and selectively interpreted $01E7C0 live terminals.

Load the exact organic state frozen at bank-$98 entry and run to the first
physical ``op_trap`` dispatch at $00:B21B, which is the terminal MC68000
``trap #5`` at $01E7BE.  One arm runs production unchanged.  The second
temporarily redirects only entry_1e7c0 to its existing interpreter fallback;
all other native, scheduler, choke, loop, and pacing gates remain untouched.

The comparison includes complete SA-1 IRAM/private interpreter state, all
64 KiB of work RAM, virtual MC68000 registers/CCR/X/stack, SA-1 hardware
registers, task contexts, and the elapsed video/cycle interval.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ROM = ROOT / "build" / "interp.sfc"
DEFAULT_STATE = (
    ROOT
    / "build/playtest-investigation-20260725"
    / "campaign-halt-1e7c0-entry-a08508d-tick6619-v1"
    / "post-trace.mss"
)
DEFAULT_NEXEN = Path(
    "/mnt/sdc1/Nexen-r5-20260712/"
    "bin/linux-x64/Release/linux-x64/publish/Nexen"
)
OP_TRAP = 0x00B21B
ENTRY_ROM_OFFSET = 0x2C2E00
ENTRY_ORIGINAL = bytes.fromhex("c230a534")
ENTRY_FALLBACK_JML = bytes.fromhex("5cb8ae98")
OP_TRAP_ROM_OFFSET = OP_TRAP - 0x8000
WORK_BASE = 0x400000
FULL_WORK_SIZE = 0x10000
IRAM_SIZE = 0x0800

sys.path.insert(0, "/home/chad/Mesen2/python")
sys.path.insert(0, str(ROOT / "tools"))
import mesen_mcp.session as _session  # noqa: E402

_session.validate_mesen_build = lambda *_args, **_kwargs: None
from mesen_mcp import McpSession  # noqa: E402

import replay_mame_controller_campaign as campaign  # noqa: E402
import validate_d96_hle as native_base  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--nexen", type=Path, default=DEFAULT_NEXEN)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--port", type=int, default=9550)
    parser.add_argument("--buttons", type=lambda value: int(value, 0), default=0x80)
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
    return args


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def le16(raw: bytes | bytearray | list[int]) -> int:
    return int.from_bytes(bytes(raw), "little")


def le32(raw: bytes | bytearray | list[int]) -> int:
    return int.from_bytes(bytes(raw), "little")


def read_work(m: McpSession) -> bytes:
    return b"".join(
        bytes(m.read_memory("snesMemory", WORK_BASE + offset, 0x4000))
        for offset in range(0, FULL_WORK_SIZE, 0x4000)
    )


def snapshot(
    m: McpSession,
    start_frame: int,
    start_cycles: int,
) -> tuple[dict[str, Any], bytes, bytes]:
    iram = bytes(m.read_memory("Sa1Memory", 0, IRAM_SIZE))
    work = read_work(m)
    cpu = m.get_cpu_state("Sa1")
    logical_pc = le32(iram[0x40:0x44]) & 0xFFFFFF
    return (
        {
            "video_frame": int(m.get_state().get("frameCount", 0)),
            "video_frames_elapsed": (
                int(m.get_state().get("frameCount", 0)) - start_frame
            ),
            "sa1_cycles_elapsed": int(cpu.get("cycleCount", 0)) - start_cycles,
            "sa1_cpu": cpu,
            "pc68k": f"{logical_pc:06X}",
            "opcode68k": f"{le16(iram[0x44:0x46]):04X}",
            "halt": le16(iram[0x4E:0x50]),
            "tick": le16(iram[0x760:0x762]),
            "irq_pending": le16(iram[0xAA:0xAC]),
            "irq_countdown": le16(iram[0xAC:0xAE]),
            "m68k": campaign.register_snapshot(m),
            "player": campaign.player_snapshot(m),
            "task_context_hex": work[4:68].hex(),
            "task_mask": int.from_bytes(work[2:4], "big"),
            "iram_sha256": hashlib.sha256(iram).hexdigest(),
            "work_sha256": hashlib.sha256(work).hexdigest(),
        },
        iram,
        work,
    )


def run_arm(
    args: argparse.Namespace,
    output: Path,
    port: int,
    interpreted_root: bool,
) -> dict[str, Any]:
    output.mkdir(parents=True)
    with McpSession(
        rom=args.rom.resolve(),
        mesen=args.nexen.resolve(),
        cwd=ROOT,
        port=port,
        boot_wait=6.0,
        socket_timeout=180.0,
        stderr_log=output / "emulator.stderr.log",
    ) as m:
        m.pause()
        load_response = m.load_state(args.state.resolve())
        m.pause()
        input_response = campaign.set_held_input(m, args.buttons)

        entry_original = bytes(
            m.read_memory("snesPrgRom", ENTRY_ROM_OFFSET, 4)
        )
        if entry_original != ENTRY_ORIGINAL:
            raise RuntimeError(
                "entry_1e7c0 bytes moved: "
                f"{entry_original.hex()} != {ENTRY_ORIGINAL.hex()}"
            )
        if interpreted_root:
            m.write_memory(
                "snesPrgRom",
                ENTRY_ROM_OFFSET,
                ENTRY_FALLBACK_JML.hex(),
            )

        trap_original = bytes(
            m.read_memory("snesPrgRom", OP_TRAP_ROM_OFFSET, 2)
        )
        # Stabilize debugger pause at the exact pre-op_trap seam.
        m.write_memory("snesPrgRom", OP_TRAP_ROM_OFFSET, "80fe")
        # The source checkpoint was made while a debugger-only BRA -2
        # stabilized the entry hook.  Its ROM bytes were restored before the
        # save, but Nexen serializes the SA-1 prefetch pipeline.  Reasserting
        # the already-recorded $98:AE00 hardware PC flushes that diagnostic
        # prefetch without changing any emulated MC68000 or game state.
        native_base.set_sa1_pc(m, 0x98AE00)
        hook = m.add_exec_hook(OP_TRAP, cpu_type="Sa1")
        m.drain_notifications(timeout=0.05)
        start_frame = int(m.get_state().get("frameCount", 0))
        start_cpu = m.get_cpu_state("Sa1")
        start_cycles = int(start_cpu.get("cycleCount", 0))
        m.trace_log(count=1, cpu_type="Sa1")
        try:
            response = m.run_until(max_frames=60, hook_handle=hook)
            m.pause()
            terminal, iram, work = snapshot(
                m,
                start_frame,
                start_cycles,
            )
            trace = m.trace_log(count=1000, cpu_type="Sa1")
        finally:
            m.remove_hook(hook)
            m.write_memory(
                "snesPrgRom",
                OP_TRAP_ROM_OFFSET,
                trap_original.hex(),
            )
            if interpreted_root:
                m.write_memory(
                    "snesPrgRom",
                    ENTRY_ROM_OFFSET,
                    entry_original.hex(),
                )
        reached_terminal = response.get("reason") == "hookFired"
        if reached_terminal and (
            terminal["pc68k"] != "01E7BE"
            or terminal["opcode68k"] != "4E45"
        ):
            raise RuntimeError(
                "wrong logical terminal: "
                f"{terminal['pc68k']}/{terminal['opcode68k']}"
            )
        (output / "terminal.iram.bin").write_bytes(iram)
        (output / "terminal.work.bin").write_bytes(work)
        state = campaign.save_state(m, output / "terminal.mss")
        screenshot = campaign.screenshot(m, output / "terminal.png")

    result = {
        "interpreted_root": interpreted_root,
        "load_response": load_response,
        "input_response": input_response,
        "response": response,
        "reached_terminal": reached_terminal,
        "temporary_rom_patch": (
            {
                "entry": "98AE00",
                "target": "98AEB8 h1e7c0_guard_fallback",
                "before": entry_original.hex(),
                "temporary": ENTRY_FALLBACK_JML.hex(),
            }
            if interpreted_root
            else None
        ),
        "terminal_stabilizer": {
            "entry": f"{OP_TRAP:06X}",
            "before": trap_original.hex(),
            "temporary": "80fe",
            "architectural_effect_before_hook": "none",
        },
        "hardware_pc_reassertion": {
            "address": "98AE00",
            "reason": (
                "flush serialized debugger BRA prefetch from the retained "
                "entry-hook checkpoint; emulated state unchanged"
            ),
        },
        "terminal": terminal,
        "trace": trace,
        "state": state,
        "screenshot": screenshot,
        "iram_path": str(output / "terminal.iram.bin"),
        "work_path": str(output / "terminal.work.bin"),
    }
    result_path = output / "result.json"
    result_path.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {
        "result_path": str(result_path),
        "result_sha256": sha256(result_path),
        "reached_terminal": reached_terminal,
        "terminal": terminal,
        "iram": iram,
        "work": work,
    }


def difference_rows(left: bytes, right: bytes) -> list[dict[str, Any]]:
    return [
        {"offset": f"{offset:04X}", "native": a, "interpreted": b}
        for offset, (a, b) in enumerate(zip(left, right))
        if a != b
    ]


def main() -> int:
    args = parse_args()
    args.rom = args.rom.resolve()
    args.state = args.state.resolve()
    args.nexen = args.nexen.resolve()
    args.output = args.output.resolve()
    args.output.mkdir(parents=True)
    os.environ["DOTNET_ROOT"] = "/home/chad/.dotnet10"

    native = run_arm(
        args,
        args.output / "native-production",
        args.port,
        False,
    )
    interpreted = run_arm(
        args,
        args.output / "root-interpreted",
        args.port + 1,
        True,
    )
    iram_differences = difference_rows(native["iram"], interpreted["iram"])
    work_differences = difference_rows(native["work"], interpreted["work"])
    summary = {
        "scope": (
            "exact live $01E7C0 entry to pre-$01E7BE TRAP #5 terminal; "
            "production native root versus only that root interpreted; all "
            "other gates unchanged; full IRAM/work/task/register/CCR/stack "
            "comparison; checkpoint integration evidence, not fresh boot"
        ),
        "rom": str(args.rom),
        "rom_sha256": sha256(args.rom),
        "state": str(args.state),
        "state_sha256": sha256(args.state),
        "nexen": str(args.nexen),
        "nexen_sha256": sha256(args.nexen),
        "native": {
            "result_path": native["result_path"],
            "result_sha256": native["result_sha256"],
            "terminal": native["terminal"],
        },
        "interpreted": {
            "result_path": interpreted["result_path"],
            "result_sha256": interpreted["result_sha256"],
            "terminal": interpreted["terminal"],
        },
        "architectural_registers_equal": (
            native["terminal"]["m68k"]
            == interpreted["terminal"]["m68k"]
        ),
        "player_equal": (
            native["terminal"]["player"]
            == interpreted["terminal"]["player"]
        ),
        "task_context_equal": (
            native["terminal"]["task_context_hex"]
            == interpreted["terminal"]["task_context_hex"]
        ),
        "work_difference_count": len(work_differences),
        "work_differences_first": work_differences[:256],
        "iram_difference_count": len(iram_differences),
        "iram_differences": iram_differences,
    }
    output = args.output / "summary.json"
    output.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "summary": str(output),
                "architectural_registers_equal": summary[
                    "architectural_registers_equal"
                ],
                "player_equal": summary["player_equal"],
                "task_context_equal": summary["task_context_equal"],
                "work_difference_count": len(work_differences),
                "iram_difference_count": len(iram_differences),
                "native_frames": native["terminal"]["video_frames_elapsed"],
                "interpreted_frames": interpreted["terminal"][
                    "video_frames_elapsed"
                ],
                "native_cycles": native["terminal"]["sa1_cycles_elapsed"],
                "interpreted_cycles": interpreted["terminal"][
                    "sa1_cycles_elapsed"
                ],
            },
            sort_keys=True,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
