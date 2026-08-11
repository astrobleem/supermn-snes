#!/usr/bin/env python3
"""Bisect private-IRAM dependence in the live tick-6619 $01E7C0 failure."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ROM = ROOT / "build/interp.sfc"
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
ENTRY_NATIVE = 0x98AE00
OP_TRAP = 0x00B21B
OP_TRAP_ROM_OFFSET = OP_TRAP - 0x8000
TERMINAL_PC = 0x01E7BE
IRAM_SIZE = 0x0800
WORK_BASE = 0x400000
WORK_SIZE = 0x10000

VARIANTS: tuple[tuple[str, tuple[tuple[int, int], ...]], ...] = (
    ("unchanged", ()),
    ("zero_0050_005f", ((0x0050, 0x0010),)),
    ("zero_0080_009f", ((0x0080, 0x0020),)),
    ("zero_0080_0087", ((0x0080, 0x0008),)),
    ("zero_0088_008f", ((0x0088, 0x0008),)),
    ("zero_0090_0097", ((0x0090, 0x0008),)),
    ("zero_0098_009f", ((0x0098, 0x0008),)),
    ("zero_0050_005f_0080_009f", ((0x0050, 0x0010), (0x0080, 0x0020))),
)

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
    parser.add_argument("--port", type=int, default=9590)
    parser.add_argument("--buttons", type=lambda value: int(value, 0), default=0x80)
    parser.add_argument("--max-frames", type=int, default=12)
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
        for offset in range(0, WORK_SIZE, 0x4000)
    )


def snapshot(m: McpSession) -> tuple[dict[str, Any], bytes, bytes]:
    iram = bytes(m.read_memory("Sa1Memory", 0, IRAM_SIZE))
    work = read_work(m)
    cpu = m.get_cpu_state("Sa1")
    pc68k = le32(iram[0x40:0x44]) & 0xFFFFFF
    return (
        {
            "video_frame": int(m.get_state().get("frameCount", 0)),
            "sa1_cpu": cpu,
            "pc68k": f"{pc68k:06X}",
            "opcode68k": f"{le16(iram[0x44:0x46]):04X}",
            "halt": le16(iram[0x4E:0x50]),
            "tick": le16(iram[0x760:0x762]),
            "m68k": campaign.register_snapshot(m),
            "player": campaign.player_snapshot(m),
            "irq_pending": le16(iram[0xAA:0xAC]),
            "irq_countdown": le16(iram[0xAC:0xAE]),
            "iram_sha256": hashlib.sha256(iram).hexdigest(),
            "work_sha256": hashlib.sha256(work).hexdigest(),
        },
        iram,
        work,
    )


def main() -> int:
    args = parse_args()
    args.rom = args.rom.resolve()
    args.state = args.state.resolve()
    args.nexen = args.nexen.resolve()
    args.output = args.output.resolve()
    args.output.mkdir(parents=True)
    os.environ["DOTNET_ROOT"] = "/home/chad/.dotnet10"

    results: list[dict[str, Any]] = []
    with McpSession(
        rom=args.rom,
        mesen=args.nexen,
        cwd=ROOT,
        port=args.port,
        boot_wait=6.0,
        socket_timeout=180.0,
        stderr_log=args.output / "emulator.stderr.log",
    ) as m:
        m.pause()
        trap_original = bytes(
            m.read_memory("snesPrgRom", OP_TRAP_ROM_OFFSET, 2)
        )
        for name, zero_ranges in VARIANTS:
            arm_dir = args.output / name
            arm_dir.mkdir()
            m.load_state(args.state)
            m.pause()
            campaign.set_held_input(m, args.buttons)
            start_iram = bytes(m.read_memory("Sa1Memory", 0, IRAM_SIZE))
            (arm_dir / "entry.iram.bin").write_bytes(start_iram)
            writes: list[dict[str, Any]] = []
            for address, length in zero_ranges:
                before = bytes(m.read_memory("Sa1Memory", address, length))
                m.write_memory("Sa1Memory", address, bytes(length).hex())
                writes.append(
                    {
                        "address": f"{address:04X}",
                        "length": length,
                        "before": before.hex(),
                        "after": bytes(length).hex(),
                    }
                )

            # Self-looping op_trap makes the grouped terminal reads coherent;
            # the trap handler itself has not executed at this seam.
            m.write_memory("snesPrgRom", OP_TRAP_ROM_OFFSET, "80fe")
            native_base.set_sa1_pc(m, ENTRY_NATIVE)
            hook = m.add_exec_hook(OP_TRAP, cpu_type="Sa1")
            m.drain_notifications(timeout=0.05)
            try:
                response = m.run_until(
                    max_frames=args.max_frames,
                    hook_handle=hook,
                )
                m.pause()
            finally:
                m.remove_hook(hook)
                m.write_memory(
                    "snesPrgRom",
                    OP_TRAP_ROM_OFFSET,
                    trap_original.hex(),
                )
            terminal, iram, work = snapshot(m)
            (arm_dir / "terminal.iram.bin").write_bytes(iram)
            (arm_dir / "terminal.work.bin").write_bytes(work)
            reached_hook = response.get("reason") == "hookFired"
            reached_terminal = reached_hook and terminal["pc68k"] == f"{TERMINAL_PC:06X}"
            classification = (
                "terminal"
                if reached_terminal
                else ("halt" if terminal["halt"] else "other")
            )
            results.append(
                {
                    "variant": name,
                    "zero_ranges": writes,
                    "response": response,
                    "classification": classification,
                    "reached_op_trap_hook": reached_hook,
                    "reached_expected_terminal": reached_terminal,
                    "terminal": terminal,
                    "entry_iram_path": str(arm_dir / "entry.iram.bin"),
                    "terminal_iram_path": str(arm_dir / "terminal.iram.bin"),
                    "terminal_work_path": str(arm_dir / "terminal.work.bin"),
                }
            )

    summary = {
        "scope": (
            "identical organic live $01E7C0 entry state with diagnostic-only "
            "zeroing of escape-transient private IRAM ranges; exact pre-trap "
            "terminal versus halt classification; no game work-RAM patches"
        ),
        "rom": str(args.rom),
        "rom_sha256": sha256(args.rom),
        "state": str(args.state),
        "state_sha256": sha256(args.state),
        "nexen": str(args.nexen),
        "nexen_sha256": sha256(args.nexen),
        "results": results,
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
                "results": [
                    {
                        "variant": result["variant"],
                        "classification": result["classification"],
                        "pc68k": result["terminal"]["pc68k"],
                        "halt": result["terminal"]["halt"],
                        "d3": result["terminal"]["m68k"]["registers"]["D3"],
                    }
                    for result in results
                ],
            },
            sort_keys=True,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
