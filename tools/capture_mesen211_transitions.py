#!/usr/bin/env python3
"""Capture a fresh-power-on title/transition sequence in legacy Mesen 2.1.1.

This harness deliberately does not load a Nexen checkpoint.  Mesen and Nexen
save states are not interchangeable evidence for emulator-specific rendering
failures.  The coarse pass saves same-emulator checkpoints so a suspicious
window can later be replayed frame by frame with ``--state``.

The capture is a rendering compatibility diagnostic, not performance evidence.
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
REAL_MESEN = Path("/home/chad/Mesen2/bin/linux-x64/Release/Mesen")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--mesen", type=Path, default=DEFAULT_MESEN)
    parser.add_argument("--state", type=Path)
    parser.add_argument("--port", type=int, default=8814)
    parser.add_argument("--start-frame", type=int, default=4500)
    parser.add_argument("--end-frame", type=int, default=6500)
    parser.add_argument("--step", type=int, default=30)
    parser.add_argument("--checkpoint-step", type=int, default=150)
    parser.add_argument("--boot-wait", type=float, default=6.0)
    return parser.parse_args()


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


def le16(data: bytes) -> int:
    return int.from_bytes(data, "little")


def snapshot(m: McpSession) -> dict[str, Any]:
    state = m.get_state()
    ppu = m.get_ppu_state()
    return {
        "frame": int(state.get("frameCount", 0)),
        "tick": le16(m.read_memory("Sa1Memory", 0x0760, 2)),
        "halt": le16(m.read_memory("Sa1Memory", 0x004E, 2)),
        "pc68k": int.from_bytes(
            m.read_memory("Sa1Memory", 0x0040, 4), "little"
        )
        & 0xFFFFFF,
        "task_mask": int.from_bytes(
            m.read_memory("snesMemory", 0x400002, 2), "big"
        ),
        "render_complete": le16(
            m.read_memory("snesWorkRam", 0x89A2, 2)
        ),
        "brightness": int(ppu.get("brightness", -1)),
        "forced_blank": bool(ppu.get("forcedBlank", False)),
        "ppu_frame": int(ppu.get("frameCount", 0)),
    }


def wait_for_file(path: Path, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.is_file() and path.stat().st_size:
            return
        time.sleep(0.05)
    raise TimeoutError(f"timed out waiting for {path}")


def save_checkpoint(m: McpSession, path: Path) -> dict[str, Any]:
    response = m.save_state(path)
    wait_for_file(path)
    return {
        "path": str(path),
        "sha256": sha256(path),
        "response": response,
    }


def take_screenshot(m: McpSession, path: Path) -> dict[str, Any]:
    response = m.take_screenshot(format="path")
    shutil.copy2(Path(response["path"]), path)
    return {
        "path": str(path),
        "sha256": sha256(path),
        "bytes": path.stat().st_size,
        "response": response,
    }


def main() -> int:
    args = parse_args()
    if args.start_frame < 0 or args.end_frame < args.start_frame:
        raise SystemExit("invalid capture frame range")
    if args.step <= 0 or args.checkpoint_step <= 0:
        raise SystemExit("step sizes must be positive")
    for label, path in (
        ("ROM", args.rom),
        ("Mesen", args.mesen),
    ):
        if not path.is_file():
            raise FileNotFoundError(f"{label} not found: {path}")
    if args.state is not None and not args.state.is_file():
        raise FileNotFoundError(f"state not found: {args.state}")
    rom = args.rom.resolve()
    if rom.stat().st_size != 0x400000:
        raise SystemExit("expected a 4 MiB production ROM")
    if int.from_bytes(rom.read_bytes()[0x77E0:0x77E2], "little") != 0:
        raise SystemExit("refusing non-production ROM: TESTFLAG is set")

    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    configure_dotnet8()
    rows: list[dict[str, Any]] = []
    provenance = {
        "scope": (
            "Mesen 2.1.1 rendering compatibility capture; fresh power-on unless "
            "--state is named; not gameplay, stability, or performance evidence"
        ),
        "project_commit": git_value("rev-parse", "HEAD"),
        "project_status": git_value("status", "--short").splitlines(),
        "rom": str(rom),
        "rom_sha256": sha256(rom),
        "mesen": str(args.mesen.resolve()),
        "mesen_sha256": sha256(args.mesen),
        "mesen_2_1_1_binary": str(REAL_MESEN),
        "mesen_2_1_1_binary_sha256": sha256(REAL_MESEN),
        "state": str(args.state.resolve()) if args.state else None,
        "state_sha256": sha256(args.state) if args.state else None,
        "frame_range": [args.start_frame, args.end_frame],
        "capture_step": args.step,
        "checkpoint_step": args.checkpoint_step,
        "runtime_memory_pokes": [],
        "input": "controller idle",
    }
    print(json.dumps({"event": "provenance", **provenance}, sort_keys=True))

    stderr_path = output / "mesen.stderr.log"
    with McpSession(
        rom=rom,
        mesen=args.mesen.resolve(),
        cwd=ROOT,
        port=args.port,
        boot_wait=args.boot_wait,
        socket_timeout=300.0,
        stderr_log=stderr_path,
    ) as m:
        m.pause()
        if args.state is not None:
            m.load_state(args.state.resolve())
            m.pause()
        current = int(m.get_state().get("frameCount", 0))
        if current > args.start_frame:
            raise RuntimeError(
                f"starting state frame {current} is past requested frame "
                f"{args.start_frame}"
            )

        while current < args.start_frame:
            count = min(250, args.start_frame - current)
            result = m.run_frames(count)
            current = int(m.get_state().get("frameCount", 0))
            print(
                json.dumps(
                    {
                        "event": "advance",
                        "frame": current,
                        "requested": count,
                        "result": result,
                    },
                    sort_keys=True,
                ),
                flush=True,
            )

        next_checkpoint = args.start_frame
        while current <= args.end_frame:
            snap = snapshot(m)
            if snap["frame"] != current:
                raise RuntimeError(
                    f"frame changed while paused: expected {current}, got "
                    f"{snap['frame']}"
                )
            frame_name = f"frame-{current:06d}"
            row = {
                **snap,
                "screenshot": take_screenshot(
                    m, output / f"{frame_name}.png"
                ),
            }
            if current >= next_checkpoint:
                row["checkpoint"] = save_checkpoint(
                    m, output / f"{frame_name}.mss"
                )
                while next_checkpoint <= current:
                    next_checkpoint += args.checkpoint_step
            rows.append(row)
            print(
                json.dumps(
                    {
                        "event": "capture",
                        "frame": current,
                        "tick": snap["tick"],
                        "halt": snap["halt"],
                        "pc68k": snap["pc68k"],
                        "task_mask": snap["task_mask"],
                        "render_complete": snap["render_complete"],
                        "brightness": snap["brightness"],
                        "forced_blank": snap["forced_blank"],
                        "screenshot_sha256": row["screenshot"]["sha256"],
                        "checkpoint": row.get("checkpoint", {}).get("path"),
                    },
                    sort_keys=True,
                ),
                flush=True,
            )
            if current == args.end_frame:
                break
            count = min(args.step, args.end_frame - current)
            m.run_frames(count)
            current = int(m.get_state().get("frameCount", 0))

    result = {"provenance": provenance, "captures": rows}
    result_path = output / "results.json"
    result_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(
        json.dumps(
            {
                "event": "complete",
                "results": str(result_path),
                "captures": len(rows),
                "first_frame": rows[0]["frame"] if rows else None,
                "last_frame": rows[-1]["frame"] if rows else None,
            },
            sort_keys=True,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
