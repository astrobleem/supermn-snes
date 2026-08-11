#!/usr/bin/env python3
"""Capture exact virtual-IRQ entries from one forensic Nexen save state.

This read-only diagnostic reloads the same state for each requested IRQ
occurrence, stops before the SA-1 virtual-IRQ dispatcher body, and records the
live MC68000 state plus serialized task frames.  It does not authenticate an
arbitrary state as resumable or production evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import replay_mame_controller_campaign as campaign


ROOT = Path(__file__).resolve().parents[1]
TAKE_IRQ = 0x00B404
VTIME_BASE = 0x404000
FRAME_REGISTER_NAMES = tuple(
    [f"D{index}" for index in range(8)]
    + [f"A{index}" for index in range(7)]
)
FRAME_REGISTER_BYTES = len(FRAME_REGISTER_NAMES) * 4
FRAME_BYTES = FRAME_REGISTER_BYTES + 2 + 4


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def be16(raw: bytes, offset: int) -> int:
    return int.from_bytes(raw[offset : offset + 2], "big")


def be32(raw: bytes, offset: int) -> int:
    return int.from_bytes(raw[offset : offset + 4], "big")


def le16(raw: bytes, offset: int) -> int:
    return int.from_bytes(raw[offset : offset + 2], "little")


def task_frame(work: bytes, task: int) -> dict[str, Any] | None:
    saved_sp = be32(work, 0x000A + task * 4)
    if saved_sp >> 16 != 0x00F0:
        return None
    offset = saved_sp & 0xFFFF
    if offset + FRAME_BYTES + 4 > len(work):
        return None
    sr = be16(work, offset + FRAME_REGISTER_BYTES)
    return {
        "task": task,
        "saved_sp": f"{saved_sp:08X}",
        "registers": {
            name: f"{be32(work, offset + index * 4):08X}"
            for index, name in enumerate(FRAME_REGISTER_NAMES)
        },
        "sr": f"{sr:04X}",
        "interrupt_mask": (sr >> 8) & 7,
        "ccr_xnzvc": sr & 0x1F,
        "pc": f"{be32(work, offset + FRAME_REGISTER_BYTES + 2):08X}",
        "return_pc": f"{be32(work, offset + FRAME_BYTES):08X}",
        "frame_plus_return_hex": work[
            offset : offset + FRAME_BYTES + 4
        ].hex(),
    }


def snapshot(m: campaign.McpSession) -> dict[str, Any]:
    iram = bytes(m.read_memory("Sa1Memory", 0, 0x800))
    work = bytes(m.read_memory("snesMemory", 0x400000, 0x10000))
    timer = bytes(m.read_memory("snesMemory", VTIME_BASE, 0x1A))
    mask = be16(work, 0x0002)
    current_task = be16(work, 0x0004)
    initialized = [
        frame
        for task in range(16)
        if (frame := task_frame(work, task)) is not None
    ]
    return {
        "video_frame": int(m.get_state().get("frameCount", 0)),
        "sa1": dict(m.get_cpu_state("Sa1")),
        "iram_sha256": hashlib.sha256(iram).hexdigest(),
        "work_sha256": hashlib.sha256(work).hexdigest(),
        "logical_pc": (
            f"{int.from_bytes(iram[0x40:0x44], 'little') & 0xFFFFFF:06X}"
        ),
        "logical_opcode": f"{le16(iram, 0x44):04X}",
        "logical_state": campaign.register_snapshot(m),
        "tick_0760": le16(iram, 0x760),
        "virtual_irq": {
            "pending_00aa": le16(iram, 0xAA),
            "legacy_countdown_00ac": le16(iram, 0xAC),
        },
        "vtime": {
            "cost": le16(timer, 0x04),
            "remain_lo": le16(timer, 0x06),
            "remain_hi": le16(timer, 0x08),
            "phase": le16(timer, 0x0A),
            "overshoot": le16(timer, 0x0C),
            "opcode": f"{le16(timer, 0x0E):04X}",
            "native_pending": le16(timer, 0x14),
            "native_current": le16(timer, 0x16),
            "due": le16(timer, 0x18),
        },
        "scheduler": {
            "task_mask": f"{mask:04X}",
            "current_task": current_task,
            "initialized_frames": initialized,
            "task15": next(
                (frame for frame in initialized if frame["task"] == 15),
                None,
            ),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--nexen", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--port", type=int, default=9390)
    parser.add_argument("--max-frames", type=int, default=600)
    parser.add_argument(
        "--occurrence",
        type=int,
        action="append",
        default=[],
        help="one-based virtual-IRQ occurrence to capture; may repeat",
    )
    args = parser.parse_args()
    occurrences = args.occurrence or [1, 2, 3, 4, 8, 16]
    if any(value < 1 for value in occurrences):
        parser.error("--occurrence values must be positive")
    for label, path in (
        ("ROM", args.rom),
        ("state", args.state),
        ("Nexen", args.nexen),
    ):
        if not path.is_file():
            parser.error(f"missing {label}: {path}")
    if args.output.exists():
        parser.error(f"output already exists: {args.output}")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    campaign.configure_dotnet(args.nexen)
    captures: list[dict[str, Any]] = []
    with campaign.McpSession(
        rom=args.rom.resolve(),
        mesen=args.nexen.resolve(),
        cwd=ROOT,
        port=args.port,
        boot_wait=6.0,
        socket_timeout=300.0,
        stderr_log=args.output.with_suffix(".stderr.log"),
    ) as m:
        for occurrence in occurrences:
            m.pause()
            load_response = dict(m.load_state(args.state.resolve()))
            m.pause()
            before = snapshot(m)
            stop = dict(
                m.tool(
                    "run_to_exact_exec_stop",
                    {
                        "address": TAKE_IRQ,
                        "cpuType": "Sa1",
                        "maxFrames": args.max_frames,
                        "occurrences": occurrence,
                    },
                )
            )
            campaign.require_paused(m, "forensic virtual-IRQ exact stop")
            captures.append(
                {
                    "occurrence": occurrence,
                    "load_response": load_response,
                    "before": before,
                    "stop": stop,
                    "at_irq": snapshot(m),
                }
            )

    report = {
        "scope": (
            "read-only forensic exact virtual-IRQ sequence from one retained "
            "state; not resumable-state, fresh-boot, production, or rate proof"
        ),
        "rom": {"path": str(args.rom.resolve()), "sha256": sha256(args.rom)},
        "state": {
            "path": str(args.state.resolve()),
            "sha256": sha256(args.state),
        },
        "nexen": {
            "path": str(args.nexen.resolve()),
            "sha256": sha256(args.nexen),
        },
        "take_irq_address": f"{TAKE_IRQ:06X}",
        "occurrences": occurrences,
        "captures": captures,
    }
    args.output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "output": str(args.output.resolve()),
                "captures": [
                    {
                        "occurrence": row["occurrence"],
                        "frame": row["at_irq"]["video_frame"],
                        "tick": row["at_irq"]["tick_0760"],
                        "logical_pc": row["at_irq"]["logical_pc"],
                        "current_task": row["at_irq"]["scheduler"][
                            "current_task"
                        ],
                    }
                    for row in captures
                ],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
