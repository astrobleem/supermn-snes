#!/usr/bin/env python3
"""Read-only timing probe for an explicitly forensic VTIME checkpoint run.

This does not authenticate a ROM-mismatched state as production evidence.  It
exists to distinguish timer-state initialization/consumption defects from
native-span accounting while a VTIME diagnostic is being developed.
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
sys.path.insert(0, "/home/chad/Mesen2/python")
sys.path.insert(0, str(ROOT / "tools"))

import mesen_mcp.session as _session  # noqa: E402

_session.validate_mesen_build = lambda *_args, **_kwargs: None
from mesen_mcp import McpSession  # noqa: E402


DEFAULT_NEXEN = Path(
    "/mnt/sdc1/Nexen-r5-20260712/bin/linux-x64/Release/"
    "mcp-iram-edge-publish/Nexen"
)
VTIME_BASE = 0x404000
VTIME_SIZE = 0x1A
NATIVE_GATES = (0x072E, 0x071A, 0x0734, 0x0736, 0x073A, 0x073C)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--frames", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--nexen", type=Path, default=DEFAULT_NEXEN)
    parser.add_argument("--port", type=int, default=7988)
    parser.add_argument("--all-native-off", action="store_true")
    parser.add_argument(
        "--watch-magic",
        action="store_true",
        help="record writes to VTIME magic/valid bytes; excludes high-volume timer fields",
    )
    parser.add_argument(
        "--watch-state-transitions",
        action="store_true",
        help="record sparse VTIME high-word/phase/due writes, not every low-word debit",
    )
    parser.add_argument(
        "--watch-low-remainder",
        action="store_true",
        help="record every low-remainder write; use only for a one-frame forensic probe",
    )
    args = parser.parse_args()
    for name, path in (("ROM", args.rom), ("state", args.state), ("Nexen", args.nexen)):
        if not path.is_file():
            parser.error(f"missing {name}: {path}")
    if args.frames < 1:
        parser.error("--frames must be positive")
    if args.output.exists():
        parser.error(f"output already exists: {args.output}")
    return args


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def le16(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 2], "little")


def snapshot(m: McpSession) -> dict[str, Any]:
    iram = bytes(m.read_memory("Sa1Memory", 0, 0x800))
    timer = bytes(m.read_memory("snesMemory", VTIME_BASE, VTIME_SIZE))
    work = bytes(m.read_memory("snesMemory", 0x4012A2, 0x48))
    state = m.get_state()
    return {
        "frame": int(state.get("frameCount", 0)),
        "sa1": m.get_cpu_state("Sa1"),
        "virtual_pc": f"{int.from_bytes(iram[0x40:0x44], 'little') & 0xFFFFFF:06X}",
        "virtual_opcode": f"{le16(iram, 0x44):04X}",
        "virtual_irq": {
            "pending_00aa": le16(iram, 0xAA),
            "legacy_countdown_00ac": le16(iram, 0xAC),
        },
        "timer": {
            "magic": f"{le16(timer, 0x00):04X}",
            "valid": le16(timer, 0x02),
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
        "game": {
            "player_health": int.from_bytes(work[0x12:0x14], "big"),
            "player_action": work[0x3D],
            "tick_0760": le16(iram, 0x760),
        },
    }


def main() -> int:
    args = parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    dotnet10 = "/home/chad/.dotnet10"
    dotnet8 = "/home/chad/.dotnet8"
    os.environ["DOTNET_ROOT"] = dotnet10
    current_path = [
        entry
        for entry in os.environ.get("PATH", "").split(":")
        if entry and entry not in (dotnet10, dotnet8)
    ]
    os.environ["PATH"] = ":".join([dotnet10, dotnet8, *current_path])
    stderr = args.output.with_suffix(".stderr.log")
    with McpSession(
        rom=args.rom.resolve(),
        mesen=args.nexen.resolve(),
        cwd=ROOT,
        port=args.port,
        boot_wait=6.0,
        socket_timeout=300.0,
        stderr_log=stderr,
    ) as m:
        m.pause()
        m.load_state(args.state.resolve())
        m.pause()
        if args.all_native_off:
            for address in NATIVE_GATES:
                m.write_u16(address, 0, "Sa1Memory")
        magic_hook = None
        if args.watch_magic:
            magic_hook = m.add_write_hook(
                VTIME_BASE,
                VTIME_BASE + 3,
                cpu_type="Sa1",
            )
            m.drain_notifications(timeout=0.02)
        transition_hooks: list[int] = []
        if args.watch_state_transitions:
            transition_hooks.extend(
                (
                    # A 16-bit high countdown decrements its low byte at +8;
                    # watching only +9 misses the real $0001 -> $0000 carry.
                    m.add_write_hook(VTIME_BASE + 0x08, VTIME_BASE + 0x09, cpu_type="Sa1"),
                    m.add_write_hook(VTIME_BASE + 0x0A, VTIME_BASE + 0x0B, cpu_type="Sa1"),
                    m.add_write_hook(VTIME_BASE + 0x18, VTIME_BASE + 0x19, cpu_type="Sa1"),
                )
            )
            m.drain_notifications(timeout=0.02)
        low_remainder_hook = None
        if args.watch_low_remainder:
            low_remainder_hook = m.add_write_hook(
                VTIME_BASE + 0x06,
                VTIME_BASE + 0x07,
                cpu_type="Sa1",
            )
            m.drain_notifications(timeout=0.02)
        before = snapshot(m)
        runs: list[dict[str, Any]] = []
        remaining = args.frames
        while remaining:
            requested = min(120, remaining)
            frame_before = int(m.get_state().get("frameCount", 0))
            response = m.run_frames(requested)
            m.pause()
            frame_after = int(m.get_state().get("frameCount", 0))
            advanced = frame_after - frame_before
            if advanced <= 0 or advanced > requested:
                raise RuntimeError(
                    f"invalid frame progress requested={requested} advanced={advanced}"
                )
            state_writes = [
                notification
                for notification in m.drain_notifications(timeout=0.02)
                if notification.get("method") == "notifications/mesen/hookFired"
            ]
            runs.append(
                {
                    "requested": requested,
                    "advanced": advanced,
                    "before": frame_before,
                    "after": frame_after,
                    "response": response,
                    "snapshot": snapshot(m),
                    "state_writes": state_writes,
                }
            )
            remaining -= advanced
        after = snapshot(m)
        if magic_hook is not None:
            m.remove_hook(magic_hook)
        for handle in transition_hooks:
            m.remove_hook(handle)
        if low_remainder_hook is not None:
            m.remove_hook(low_remainder_hook)

    report = {
        "scope": (
            "forensic VTIME checkpoint probe; ROM and checkpoint may differ; "
            "not production behavior, fresh-boot, or timer acceptance evidence"
        ),
        "rom": str(args.rom.resolve()),
        "rom_sha256": sha256(args.rom),
        "state": str(args.state.resolve()),
        "state_sha256": sha256(args.state),
        "all_native_off": args.all_native_off,
        "watch_magic": args.watch_magic,
        "watch_state_transitions": args.watch_state_transitions,
        "watch_low_remainder": args.watch_low_remainder,
        "frames": args.frames,
        "before": before,
        "runs": runs,
        "after": after,
    }
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output.resolve()), "before": before["timer"], "after": after["timer"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
