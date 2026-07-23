#!/usr/bin/env python3
"""Trace the first scheduler-context corruption near stage 1's breakable wall.

This is a checkpointed Mesen diagnostic.  It drives only real port-0 controller
input, watches the 16 saved task-stack cells at ``$F0000A-$F00049``, and records
every SA-1 write to that table.  It does not write game, gate, scheduler, or
renderer memory, and it is not production-performance evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, "/home/chad/Mesen2/python")

import mesen_mcp.session as _session

_session.validate_mesen_build = lambda *_args, **_kwargs: None
from mesen_mcp import McpSession


DEFAULT_MESEN = ROOT / "tools" / "mesen211_mcp_controller.sh"
CONTEXT_START = 0x40000A
CONTEXT_END = 0x400049
CONTEXT_ALIAS_START = 0x00600A
CONTEXT_ALIAS_END = 0x006049
FLOOR_START = 0xC10882
BUTTON_ATTACK_RIGHT = McpSession.BTN_B | McpSession.BTN_RIGHT
BUTTON_RIGHT = McpSession.BTN_RIGHT


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--mesen", type=Path, default=DEFAULT_MESEN)
    parser.add_argument("--port", type=int, default=8844)
    parser.add_argument("--iterations", type=int, default=12)
    parser.add_argument("--attack-frames", type=int, default=6)
    parser.add_argument("--walk-frames", type=int, default=30)
    return parser.parse_args()


def configure_dotnet8() -> None:
    dotnet8 = "/home/chad/.dotnet8"
    dotnet10 = "/home/chad/.dotnet10"
    os.environ["DOTNET_ROOT"] = dotnet8
    current = [
        item
        for item in os.environ.get("PATH", "").split(":")
        if item and item not in (dotnet8, dotnet10)
    ]
    os.environ["PATH"] = ":".join([dotnet8, dotnet10, *current])


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def git_value(*args: str) -> str:
    try:
        return subprocess.check_output(
            ["git", *args], cwd=ROOT, text=True, stderr=subprocess.DEVNULL
        ).strip()
    except Exception:
        return "unknown"


def hook_events(notifications: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for notification in notifications:
        if notification.get("method") != "notifications/mesen/hookFired":
            continue
        params = notification.get("params", {})
        rows.append(
            {
                "handle": int(params.get("handle", -1)),
                "address": int(params.get("address", 0)),
                "value": int(params.get("value", 0)),
                "frame": int(params.get("frame", 0)),
                "cycle_count": int(params.get("cycleCount", 0)),
                "cpu_type": params.get("cpuType"),
                "kind": params.get("kind"),
            }
        )
    return rows


def context_snapshot(m: McpSession, floors: list[int], label: str) -> dict[str, Any]:
    raw = bytes(m.read_memory("snesMemory", CONTEXT_START, 16 * 4))
    values = [
        int.from_bytes(raw[index * 4 : index * 4 + 4], "big")
        for index in range(16)
    ]
    initialized = [
        {
            "task": index,
            "saved_sp": value,
            "floor": floors[index],
            "margin": value - floors[index],
            "valid": value >= floors[index] and (value >> 16) == 0x00F0,
        }
        for index, value in enumerate(values)
        if value
    ]
    state = m.get_state()
    manifest_raw = bytes(
        m.read_memory("snesMemory", 0x410132, 0x2C)
    )

    def manifest_word(address: int) -> int:
        offset = address - 0x0132
        return int.from_bytes(manifest_raw[offset : offset + 2], "little")

    return {
        "label": label,
        "frame": int(state.get("frameCount", 0)),
        "tick": int.from_bytes(
            m.read_memory("Sa1Memory", 0x0760, 2), "little"
        ),
        "halt": int.from_bytes(
            m.read_memory("Sa1Memory", 0x004E, 2), "little"
        ),
        "pc68k": int.from_bytes(
            m.read_memory("Sa1Memory", 0x0040, 4), "little"
        )
        & 0xFFFFFF,
        "task_mask": int.from_bytes(
            m.read_memory("snesMemory", 0x400002, 2), "big"
        ),
        "raw": raw.hex(),
        "values": values,
        "initialized": initialized,
        "invalid": [row for row in initialized if not row["valid"]],
        "manifest": {
            "candidate": manifest_word(0x0132),
            "accepted": manifest_word(0x0134),
            "baseline": manifest_word(0x0136),
            "obj_length": manifest_word(0x0138),
            "bg_length": manifest_word(0x013A),
            "palette_dirty": manifest_word(0x013C),
            "producer_bg_status": manifest_word(0x014C),
            "producer_bg_length": manifest_word(0x014E),
            "loop_bound_0158": manifest_word(0x0158),
            "loop_cursor_015A": manifest_word(0x015A),
            "loop_cell_015C": manifest_word(0x015C),
            "raw": manifest_raw.hex(),
        },
    }


def take_screenshot(m: McpSession, target: Path) -> dict[str, Any]:
    response = m.take_screenshot(format="path")
    shutil.copy2(Path(response["path"]), target)
    return {
        "path": str(target),
        "sha256": sha256(target),
        "response": response,
    }


def wait_for_file(path: Path, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.is_file() and path.stat().st_size:
            return
        time.sleep(0.05)
    raise TimeoutError(f"timed out waiting for {path}")


def main() -> int:
    args = parse_args()
    if min(args.iterations, args.attack_frames, args.walk_frames) <= 0:
        raise SystemExit("iteration and frame counts must be positive")
    for label, path in (
        ("ROM", args.rom),
        ("state", args.state),
        ("Mesen", args.mesen),
    ):
        if not path.is_file():
            raise FileNotFoundError(f"{label} not found: {path}")

    rom = args.rom.resolve()
    state_path = args.state.resolve()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    configure_dotnet8()

    result: dict[str, Any] = {
        "scope": (
            "checkpointed Mesen saved-task-context diagnostic; real port-0 "
            "input; no runtime memory writes; not performance evidence"
        ),
        "project_commit": git_value("rev-parse", "HEAD"),
        "project_status": git_value("status", "--short").splitlines(),
        "rom": str(rom),
        "rom_sha256": sha256(rom),
        "state": str(state_path),
        "state_sha256": sha256(state_path),
        "mesen": str(args.mesen.resolve()),
        "schedule": {
            "iterations": args.iterations,
            "attack_right_frames": args.attack_frames,
            "right_frames": args.walk_frames,
        },
        "runtime_memory_writes": [],
        "samples": [],
        "context_writes": [],
        "context_alias_writes": [],
        "sa1_register_writes": [],
        "trace_at_invalid": None,
    }

    with McpSession(
        rom=rom,
        mesen=args.mesen.resolve(),
        cwd=ROOT,
        port=args.port,
        boot_wait=6.0,
        socket_timeout=300.0,
        stderr_log=output / "mesen.stderr.log",
    ) as m:
        m.pause()
        m.load_state(state_path)
        m.pause()
        floor_raw = bytes(
            m.read_memory("snesMemory", FLOOR_START, 16 * 4)
        )
        floors = [
            int.from_bytes(floor_raw[index * 4 : index * 4 + 4], "big")
            for index in range(16)
        ]
        result["floors"] = floors
        result["samples"].append(context_snapshot(m, floors, "initial"))
        # The first call enables Mesen's 30,000-entry SA-1 trace ring.  Read it
        # only after corruption so the diagnostic retains the instructions
        # immediately preceding the first invalid context cell.
        m.trace_log(count=1, cpu_type="Sa1")

        context_hooks = [
            m.add_write_hook(
                CONTEXT_START, CONTEXT_END, cpu_type=cpu_type
            )
            for cpu_type in ("Sa1", "Snes")
        ]
        context_alias_hooks = [
            m.add_write_hook(
                CONTEXT_ALIAS_START, CONTEXT_ALIAS_END, cpu_type=cpu_type
            )
            for cpu_type in ("Sa1", "Snes")
        ]
        register_hook = m.add_write_hook(
            0x002220, 0x002239, cpu_type="Sa1"
        )
        m.drain_notifications(timeout=0.05)

        stopped = False
        for iteration in range(1, args.iterations + 1):
            for phase, buttons, frames in (
                ("attack_right", BUTTON_ATTACK_RIGHT, args.attack_frames),
                ("right", BUTTON_RIGHT, args.walk_frames),
            ):
                before_frame = int(m.get_state().get("frameCount", 0))
                response = m.set_input(buttons, frames)
                m.pause()
                after_frame = int(m.get_state().get("frameCount", 0))
                rows = hook_events(m.drain_notifications(timeout=0.2))
                result["context_writes"].extend(
                    row
                    for row in rows
                    if CONTEXT_START <= row["address"] <= CONTEXT_END
                )
                result["context_alias_writes"].extend(
                    row
                    for row in rows
                    if (
                        CONTEXT_ALIAS_START
                        <= row["address"]
                        <= CONTEXT_ALIAS_END
                    )
                )
                result["sa1_register_writes"].extend(
                    row
                    for row in rows
                    if 0x002220 <= row["address"] <= 0x002239
                )
                sample = context_snapshot(
                    m, floors, f"{iteration:02d}_{phase}"
                )
                sample.update(
                    {
                        "buttons": buttons,
                        "requested_frames": frames,
                        "advanced_frames": after_frame - before_frame,
                        "input_response": response,
                        "context_write_count": len(rows),
                    }
                )
                result["samples"].append(sample)
                if sample["halt"] or sample["invalid"]:
                    result["trace_at_invalid"] = m.trace_log(
                        count=1000, cpu_type="Sa1"
                    )
                    stopped = True
                    break
                result["last_valid_state_response"] = m.save_state(
                    output / "last-valid.mss"
                )
            if stopped:
                break

        for context_hook in context_hooks:
            m.remove_hook(context_hook)
        for context_alias_hook in context_alias_hooks:
            m.remove_hook(context_alias_hook)
        m.remove_hook(register_hook)
        result["final"] = context_snapshot(m, floors, "final")
        result["screenshot"] = take_screenshot(m, output / "final.png")
        final_state = output / "final.mss"
        result["state_response"] = m.save_state(final_state)
        wait_for_file(final_state)
        result["final_state_sha256"] = sha256(final_state)

    suspicious = [
        row
        for row in result["context_writes"]
        if (
            (row["address"] - CONTEXT_START) % 4 == 1
            and row["value"] != 0xF0
        )
    ]
    result["suspicious_high_byte_writes"] = suspicious
    (output / "results.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "final": result["final"],
                "context_writes": len(result["context_writes"]),
                "suspicious_high_byte_writes": suspicious,
                "output": str(output),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
