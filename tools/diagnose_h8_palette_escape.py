#!/usr/bin/env python3
"""Capture the live context of the $0008C2 palette dirty-block escape.

This is a narrow diagnostic for the boot black-screen regression.  It loads a
retained Mesen state, stops at entry_8c2, then stops at the first copy/fallback
event and finally at the IRAM sentinel write if the copy path corrupts state.
It records compact JSON only; no long playback and no promotion evidence.
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
MESEN_PYTHON = Path("/home/chad/Mesen2/python")
for path in (ROOT / "tools", MESEN_PYTHON):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

os.environ.setdefault("DOTNET_ROOT", "/home/chad/.dotnet8")
os.environ["PATH"] = (
    "/home/chad/.dotnet8:/home/chad/.dotnet10:" + os.environ.get("PATH", "")
)

import mesen_mcp.session as _session  # noqa: E402

_session.validate_mesen_build = lambda *_args, **_kwargs: None
from mesen_mcp import McpSession  # noqa: E402


DEFAULT_MESEN = ROOT / "tools" / "mesen211_mcp_controller.sh"
ENTRY_8C2 = 0x92B338
H8_COPY_BLOCK = 0x92B43E
H8_FALLBACK = 0x92B3F8
IRAM_SENTINEL = 0x000600
TICK = 0x0760
TASK_MASK = 0x400002


def le16(data: bytes) -> int:
    return data[0] | (data[1] << 8)


def le32(data: bytes) -> int:
    return le16(data[0:2]) | (le16(data[2:4]) << 16)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def hook_rows(notes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        dict(note.get("params", {}))
        for note in notes
        if note.get("method") == "notifications/mesen/hookFired"
    ]


def cpu_address(cpu: dict[str, Any]) -> int:
    return ((int(cpu.get("k", 0)) & 0xFF) << 16) | (int(cpu.get("pc", 0)) & 0xFFFF)


def reg_dump(dp: bytes) -> dict[str, int]:
    names = ["D0", "D1", "D2", "D3", "D4", "D5", "D6", "D7"] + [
        "A0",
        "A1",
        "A2",
        "A3",
        "A4",
        "A5",
        "A6",
        "A7",
    ]
    return {
        name: le32(dp[index * 4 : index * 4 + 4])
        for index, name in enumerate(names)
    }


def long_ptr(dp: bytes, offset: int) -> int:
    return dp[offset] | (dp[offset + 1] << 8) | (dp[offset + 2] << 16)


def sample(session: McpSession, label: str) -> dict[str, Any]:
    state = dict(session.get_state())
    snes = dict(session.get_cpu_state("Snes"))
    sa1 = dict(session.get_cpu_state("Sa1"))
    dp = bytes(session.read_memory("Sa1Memory", 0x0000, 0x0100))
    ptr84 = long_ptr(dp, 0x84)
    ptr88 = long_ptr(dp, 0x88)
    return {
        "label": label,
        "frame": int(state.get("frameCount", 0)),
        "snes_pc": cpu_address(snes),
        "sa1_pc": cpu_address(sa1),
        "snes_cpu": snes,
        "sa1_cpu": sa1,
        "regs": reg_dump(dp[0x00:0x40]),
        "interp_pc68k": le32(dp[0x40:0x44]) & 0x00FFFFFF,
        "ccr": {
            "Z": le16(dp[0x60:0x62]),
            "C": le16(dp[0x6E:0x70]),
            "N": le16(dp[0x70:0x72]),
            "V": le16(dp[0x72:0x74]),
            "X": le16(dp[0xA2:0xA4]),
        },
        "tick": le16(bytes(session.read_memory("Sa1Memory", TICK, 2))),
        "task_mask": le16(bytes(session.read_memory("snesMemory", TASK_MASK, 2))),
        "dp_18_1b_mask_copy": dp[0x18:0x1C].hex(),
        "dp_34_43_a5_pc_stack": dp[0x34:0x44].hex(),
        "dp_80_8f": dp[0x80:0x90].hex(),
        "ptr84": f"{ptr84:06X}",
        "ptr88": f"{ptr88:06X}",
        "work_dirty_mask_f0_1b12": bytes(
            session.read_memory("snesMemory", 0x401B12, 4)
        ).hex(),
        "iram_0600_061f": bytes(
            session.read_memory("Sa1Memory", 0x0600, 0x20)
        ).hex(),
    }


def run_to_exec(
    session: McpSession, label: str, address: int, max_frames: int
) -> dict[str, Any]:
    session.drain_notifications(timeout=0.05)
    handle = session.add_exec_hook(address, cpu_type="Sa1")
    try:
        hit = dict(session.run_until(max_frames=max_frames, hook_handle=handle))
        session.pause()
        events = hook_rows(session.drain_notifications(timeout=0.2))
        return {"label": label, "address": f"{address:06X}", "hit": hit, "events": events}
    finally:
        session.remove_hook(handle)


def run_to_write(
    session: McpSession, label: str, address: int, max_frames: int
) -> dict[str, Any]:
    session.drain_notifications(timeout=0.05)
    handle = session.add_write_hook(
        address,
        end_address=address + 1,
        cpu_type="Sa1",
        match_value=0,
        match_value_mask=0xFF,
    )
    try:
        hit = dict(session.run_until(max_frames=max_frames, hook_handle=handle))
        session.pause()
        events = hook_rows(session.drain_notifications(timeout=0.2))
        return {"label": label, "address": f"{address:06X}", "hit": hit, "events": events}
    finally:
        session.remove_hook(handle)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--entry-max-frames", type=int, default=80)
    parser.add_argument("--next-max-frames", type=int, default=4)
    parser.add_argument("--sentinel-max-frames", type=int, default=80)
    parser.add_argument("--port", type=int, default=8878)
    parser.add_argument("--mesen", type=Path, default=DEFAULT_MESEN)
    args = parser.parse_args()

    if args.output.exists():
        raise SystemExit(f"output already exists: {args.output}")
    args.output.mkdir(parents=True)

    result: dict[str, Any] = {
        "scope": "state-continuation diagnostic for entry_8c2; not fresh acceptance",
        "rom": str(args.rom.resolve()),
        "rom_sha256": sha256(args.rom),
        "state": str(args.state.resolve()),
        "state_sha256": sha256(args.state),
        "addresses": {
            "entry_8c2": f"{ENTRY_8C2:06X}",
            "h8_copy_block": f"{H8_COPY_BLOCK:06X}",
            "h8_fallback": f"{H8_FALLBACK:06X}",
            "iram_sentinel": f"{IRAM_SENTINEL:06X}",
        },
        "events": [],
        "samples": [],
        "states": {},
    }

    with McpSession(
        rom=args.rom.resolve(),
        mesen=args.mesen.resolve(),
        cwd=ROOT,
        port=args.port,
        boot_wait=0.0,
        socket_timeout=120.0,
        stderr_log=args.output / "emulator.stderr.log",
    ) as session:
        session.pause()
        result["load_state"] = dict(session.load_state(args.state.resolve()))
        session.pause()
        result["samples"].append(sample(session, "start"))

        entry_event = run_to_exec(
            session, "entry_8c2", ENTRY_8C2, args.entry_max_frames
        )
        result["events"].append(entry_event)
        result["samples"].append(sample(session, "entry_8c2"))
        entry_state = args.output / "entry_8c2.mss"
        session.save_state(entry_state)
        result["states"]["entry_8c2"] = str(entry_state.resolve())

        copy_event = run_to_exec(
            session, "h8_copy_block", H8_COPY_BLOCK, args.next_max_frames
        )
        result["events"].append(copy_event)
        if copy_event["hit"].get("reason") != "hookFired":
            session.load_state(entry_state)
            session.pause()
            fallback_event = run_to_exec(
                session, "h8_fallback", H8_FALLBACK, args.next_max_frames
            )
            result["events"].append(fallback_event)
        result["samples"].append(sample(session, "first_copy_or_fallback_window"))
        next_state = args.output / "first_copy_or_fallback_window.mss"
        session.save_state(next_state)
        result["states"]["first_copy_or_fallback_window"] = str(next_state.resolve())

        sentinel_event = run_to_write(
            session,
            "iram_clear_sentinel",
            IRAM_SENTINEL,
            args.sentinel_max_frames,
        )
        result["events"].append(sentinel_event)
        result["samples"].append(sample(session, "sentinel_window_end"))
        if sentinel_event["hit"].get("reason") == "hookFired":
            sentinel_state = args.output / "sentinel.mss"
            session.save_state(sentinel_state)
            result["states"]["sentinel"] = str(sentinel_state.resolve())
            result["trace_tail"] = session.trace_log(count=128, cpu_type="Sa1")

    out = args.output / "results.json"
    out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    summary = {
        "result": str(out),
        "rom_sha256": result["rom_sha256"],
        "events": [
            {
                "label": event["label"],
                "reason": event["hit"].get("reason"),
                "framesAdvanced": event["hit"].get("framesAdvanced"),
                "notifications": len(event["events"]),
            }
            for event in result["events"]
        ],
        "samples": [
            {
                "label": sample_row["label"],
                "frame": sample_row["frame"],
                "sa1_pc": f"{sample_row['sa1_pc']:06X}",
                "interp_pc68k": f"{sample_row['interp_pc68k']:06X}",
                "d6": f"{sample_row['regs']['D6']:08X}",
                "a5": f"{sample_row['regs']['A5']:08X}",
                "ptr84": sample_row["ptr84"],
                "ptr88": sample_row["ptr88"],
                "dirty_mask": sample_row["work_dirty_mask_f0_1b12"],
                "task_mask": sample_row["task_mask"],
                "tick": sample_row["tick"],
            }
            for sample_row in result["samples"]
        ],
    }
    print(json.dumps(summary, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
