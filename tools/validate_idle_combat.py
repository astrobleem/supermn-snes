#!/usr/bin/env python3
"""Checkpointed idle-combat liveness check against the production ROM.

The harness loads a gameplay checkpoint, leaves the real controller idle, and
runs one uninterrupted emulator window.  It retains player health/position,
enemy object state, collision records, and cycle-stamped writes to the first
enemy attack record.  This is focused checkpoint evidence, not an end-to-end
performance or playability measurement.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, "/home/chad/Mesen2/python")

import mesen_mcp.session as _session

_session.validate_mesen_build = lambda *_args, **_kwargs: None
from mesen_mcp import McpSession


DEFAULT_NEXEN = Path(
    "/mnt/sdc1/Nexen-r5-20260712/"
    "bin/linux-x64/Release/linux-x64/publish/Nexen"
)
PLAYER_A6 = 0xF01302
PLAYER_HEALTH = 0x4012B4
PLAYER_Y = 0x4012E0
PLAYER_X = 0x4012E4
FIRST_ATTACK = 0x4037F4
FIRST_ATTACK_END = FIRST_ATTACK + 0x0F
ENEMY_OBJECT = 0x4002DA
GATE_ADDRS = {
    "loop": 0x072E,
    "escape": 0x071A,
    "choke": 0x073A,
    "swin": 0x073C,
    "select": 0x0736,
    "latch": 0x0768,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, default=ROOT / "build/interp.sfc")
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--nexen", type=Path, default=DEFAULT_NEXEN)
    parser.add_argument("--port", type=int, default=7620)
    parser.add_argument("--video-frames", type=int, default=1600)
    parser.add_argument("--timeout", type=float, default=300.0)
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def le16(data: bytes) -> int:
    return int.from_bytes(data, "little")


def le32(data: bytes) -> int:
    return int.from_bytes(data, "little")


def be16(data: bytes) -> int:
    return int.from_bytes(data, "big")


def take_screenshot(m: McpSession, target: Path) -> dict[str, Any]:
    response = m.take_screenshot(format="path")
    shutil.copy2(Path(response["path"]), target)
    return {
        "path": str(target),
        "sha256": sha256(target),
        "response": response,
    }


def decode_object(raw: bytes) -> dict[str, Any]:
    return {
        "raw": raw.hex(),
        "type": be16(raw[0x00:0x02]),
        "flags": [raw[offset] for offset in (0x04, 0x06, 0x07, 0x08)],
        "animation_count": be16(raw[0x0E:0x10]),
        "animation_pointer": int.from_bytes(raw[0x10:0x14], "big"),
        "frame_pointer": int.from_bytes(raw[0x14:0x18], "big"),
        "world_x": be16(raw[0x2E:0x30]),
        "world_y": be16(raw[0x32:0x34]),
        "screen_x": be16(raw[0x3E:0x40]),
        "screen_y": be16(raw[0x40:0x42]),
        "subrecords": [
            int.from_bytes(raw[offset : offset + 4], "big")
            for offset in (0x46, 0x4A, 0x4E)
        ],
        "timer": be16(raw[0x5E:0x60]),
    }


def decode_record(address: int, raw: bytes) -> dict[str, Any]:
    return {
        "address": f"{address:06X}",
        "raw": raw.hex(),
        "words": [
            be16(raw[offset : offset + 2]) for offset in range(0, 0x10, 2)
        ],
        "active": be16(raw[0:2]),
    }


def snapshot(m: McpSession, label: str) -> dict[str, Any]:
    def r16(address: int, memory_type: str = "Sa1Memory") -> int:
        return le16(m.read_memory(memory_type, address, 2))

    def r32(address: int, memory_type: str = "Sa1Memory") -> int:
        return le32(m.read_memory(memory_type, address, 4))

    player_collision_pointers = []
    for index in range(3):
        address = 0x4012CE + index * 4
        pointer = int.from_bytes(m.read_memory("snesMemory", address, 4), "big")
        item: dict[str, Any] = {"pointer": f"{pointer:08X}"}
        if 0xF00000 <= pointer <= 0xF0FFF0:
            raw = bytes(
                m.read_memory("snesMemory", 0x400000 | (pointer & 0xFFFF), 0x10)
            )
            item["record"] = decode_record(pointer, raw)
        player_collision_pointers.append(item)

    outer = bytes(m.read_memory("snesMemory", 0x403734, 0x02C0))
    positive_records = []
    for offset in range(0, len(outer), 0x10):
        raw = outer[offset : offset + 0x10]
        active = be16(raw[0:2])
        if 0 < active < 0x8000:
            positive_records.append(decode_record(0xF03734 + offset, raw))

    state = m.get_state()
    cpu = m.get_cpu_state("Sa1")
    return {
        "label": label,
        "video_frame": int(state.get("frameCount", 0)),
        "tick": r16(0x0760),
        "halt": r16(0x004E),
        "pc68k": r32(0x0040) & 0xFFFFFF,
        "opcode": r16(0x0044),
        "sa1_cycle": int(cpu.get("cycleCount", 0)),
        "sa1_pc": (int(cpu.get("k", 0)) << 16) | int(cpu.get("pc", 0)),
        "task_mask": r16(0x400002, "snesMemory"),
        "gates": {
            name: r16(address) for name, address in GATE_ADDRS.items()
        },
        "player": {
            "health": be16(m.read_memory("snesMemory", PLAYER_HEALTH, 2)),
            "x": be16(m.read_memory("snesMemory", PLAYER_X, 2)),
            "y": be16(m.read_memory("snesMemory", PLAYER_Y, 2)),
            "collision_records": player_collision_pointers,
        },
        "enemy_object": decode_object(
            bytes(m.read_memory("snesMemory", ENEMY_OBJECT, 0x70))
        ),
        "first_attack_record": decode_record(
            0xF037F4,
            bytes(m.read_memory("snesMemory", FIRST_ATTACK, 0x10)),
        ),
        "positive_outer_records": positive_records,
    }


def main() -> int:
    args = parse_args()
    if args.video_frames <= 0 or args.timeout <= 0:
        raise SystemExit("--video-frames and --timeout must be positive")
    for path in (args.rom, args.state, args.nexen):
        if not path.is_file():
            raise FileNotFoundError(path)
    args.output.mkdir(parents=True, exist_ok=False)

    raw_path = args.output / "hooks.jsonl"
    stderr_path = args.output / "nexen.stderr.log"
    hook_rows: list[dict[str, Any]] = []
    stop_reason = "exception"

    with McpSession(
        rom=args.rom.resolve(),
        mesen=args.nexen.resolve(),
        cwd=ROOT,
        port=args.port,
        boot_wait=6.0,
        socket_timeout=max(120.0, args.timeout),
        stderr_log=stderr_path,
    ) as m:
        m.pause()
        m.load_state(args.state.resolve())
        m.pause()
        m.tool("set_input", {"port": 0, "buttons": 0, "hold": True})
        start = snapshot(m, "start")
        start_shot = take_screenshot(m, args.output / "start.png")

        handles = {
            m.add_write_hook(
                PLAYER_HEALTH, PLAYER_HEALTH + 1, cpu_type="Sa1"
            ): "player_health_write",
            m.add_write_hook(
                FIRST_ATTACK, FIRST_ATTACK_END, cpu_type="Sa1"
            ): "first_attack_write",
            m.add_write_hook(0x004E, 0x004F, cpu_type="Sa1"): "halt_write",
        }
        m.drain_notifications(timeout=0.05)
        start_frame = start["video_frame"]
        deadline = time.monotonic() + args.timeout
        m.resume()
        while time.monotonic() < deadline:
            for notification in m.drain_notifications(timeout=0.1):
                if notification.get("method") != "notifications/mesen/hookFired":
                    continue
                params = dict(notification.get("params", {}))
                label = handles.get(int(params.get("handle", -1)))
                if label is not None:
                    hook_rows.append({"label": label, **params})
            frame = int(m.get_state().get("frameCount", 0))
            if (frame - start_frame) & 0xFFFFFFFF >= args.video_frames:
                stop_reason = "target_video_frames"
                break
            if le16(m.read_memory("Sa1Memory", 0x004E, 2)):
                stop_reason = "halt"
                break
        else:
            stop_reason = "timeout"

        m.pause()
        for notification in m.drain_notifications(timeout=0.25):
            if notification.get("method") != "notifications/mesen/hookFired":
                continue
            params = dict(notification.get("params", {}))
            label = handles.get(int(params.get("handle", -1)))
            if label is not None:
                hook_rows.append({"label": label, **params})
        for handle in handles:
            m.remove_hook(handle)

        end = snapshot(m, "end")
        end_shot = take_screenshot(m, args.output / "end.png")

    raw_path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in hook_rows)
    )
    counts = Counter(row["label"] for row in hook_rows)
    attack_activated = any(
        row["label"] == "first_attack_write"
        and int(row.get("address", -1)) == FIRST_ATTACK + 1
        and int(row.get("value", -1)) == 1
        for row in hook_rows
    )
    attack_activation_events = [
        row
        for row in hook_rows
        if row["label"] == "first_attack_write"
        and int(row.get("address", -1)) == FIRST_ATTACK + 1
        and int(row.get("value", -1)) == 1
    ]
    player_damaged = end["player"]["health"] < start["player"]["health"]
    verdict = {
        "target_window_completed": stop_reason == "target_video_frames",
        "no_halt": end["halt"] == 0,
        "player_landed_at_arcade_y_0070": start["player"]["y"] == 0x0070,
        "enemy_attack_record_activated": attack_activated,
        "player_damaged": player_damaged,
    }
    result = {
        "scope": "checkpointed uninterrupted idle-combat liveness; not FPS",
        "rom": str(args.rom.resolve()),
        "rom_sha256": sha256(args.rom),
        "state": str(args.state.resolve()),
        "state_sha256": sha256(args.state),
        "nexen": str(args.nexen.resolve()),
        "nexen_sha256": sha256(args.nexen),
        "requested_video_frames": args.video_frames,
        "stop_reason": stop_reason,
        "start": start,
        "end": end,
        "video_frames_advanced": (
            end["video_frame"] - start["video_frame"]
        ) & 0xFFFFFFFF,
        "ticks_advanced": (end["tick"] - start["tick"]) & 0xFFFF,
        "hooks": {
            "path": str(raw_path),
            "sha256": sha256(raw_path),
            "counts": dict(sorted(counts.items())),
            "first_attack_events": [
                row for row in hook_rows if row["label"] == "first_attack_write"
            ][:128],
            "attack_activation_events": attack_activation_events,
            "health_events": [
                row for row in hook_rows if row["label"] == "player_health_write"
            ][:128],
        },
        "screenshots": {"start": start_shot, "end": end_shot},
        "verdict": verdict,
    }
    result_path = args.output / "results.json"
    result_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"results": str(result_path), **verdict}, sort_keys=True))
    return 0 if all(verdict.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
