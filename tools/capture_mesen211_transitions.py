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
import fcntl
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
VIDEO_FILE_BASE = 0x298000
VIDEO_WRAM_OFFSET = 0x18000
VIDEO_WRAM_LENGTH = 0x3000
SCREENSHOT_LOCK = ROOT / "build" / ".mesen-screenshot-capture.lock"


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
    parser.add_argument(
        "--refresh-video-mirror",
        action="store_true",
        help=(
            "Checkpoint lab only: replace saved $7F:8000-$AFFF with the "
            "selected ROM's video supervisor before resuming."
        ),
    )
    parser.add_argument(
        "--mirror-live-scroll",
        action="store_true",
        help=(
            "Checkpoint diagnostic only: before each resumed video frame, "
            "copy live X1 column-0 scroll X into the renderer's cached scroll "
            "byte. This tests register-only temporal decoupling without a ROM build."
        ),
    )
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


def park_sa1_at_current_pc(m: McpSession, reason: str) -> dict[str, Any]:
    """Park the paused SA-1 CPU without stopping the 5A22/NMI consumer.

    MCP debugger writes to I/O memory do not guarantee device side effects, so
    checkpoint diagnostics cannot reliably freeze the SA-1 by poking CCNT.
    Replacing the instruction at the exact paused SA-1 PC with ``BRA -2`` keeps
    the coprocessor on that address while normal SNES frames and NMI continue.
    The edit is emulator-runtime-only; it does not modify the ROM file.
    """
    cpu = m.get_cpu_state("Sa1")
    address = ((int(cpu["k"]) & 0xFF) << 16) | (int(cpu["pc"]) & 0xFFFF)
    original = bytes(m.read_memory("sa1Memory", address, 2))
    parked = b"\x80\xFE"
    m.write_memory("sa1Memory", address, parked.hex())
    observed = bytes(m.read_memory("sa1Memory", address, 2))
    if observed != parked:
        raise RuntimeError(
            f"SA-1 park did not verify at ${address:06X}: {observed.hex()}"
        )
    return {
        "region": f"sa1Memory ${address:06X}-${address + 1:06X}",
        "bytes": parked.hex(),
        "original_bytes": original.hex(),
        "sa1_pc": address,
        "reason": reason,
    }


def snapshot(m: McpSession) -> dict[str, Any]:
    state = m.get_state()
    snes_cpu = m.get_cpu_state("Snes")
    sa1_cpu = m.get_cpu_state("Sa1")
    ppu = m.get_ppu_state()
    bg1 = ppu["layers"][0]
    live_scrollx = int(
        m.read_memory("snesMemory", 0x413409, 1)[0]
    )
    live_scrolly = int(
        m.read_memory("snesMemory", 0x413481, 1)[0]
    )
    bg_cgram = bytes(m.read_memory("snesCgRam", 0, 0x100))
    bg_cgram_staging = bytes(
        m.read_memory("snesWorkRam", 0x8000, 0x100)
    )
    raw_palette = bytes(
        m.read_memory("snesWorkRam", 0x2800, 0x400)
    )
    displayed_bg_map = bytes(
        m.read_memory("snesVideoRam", 0x0000, 0x1000)
    )
    displayed_bg_graphics = bytes(
        m.read_memory("snesVideoRam", 0x2000, 0x6000)
    )
    displayed_opt_table = bytes(
        m.read_memory("snesVideoRam", 0xF000, 0x80)
    )
    staged_bg_map = bytes(
        m.read_memory("snesWorkRam", 0x9000, 0x1000)
    )
    return {
        "frame": int(state.get("frameCount", 0)),
        "snes_pc": (
            ((int(snes_cpu.get("k", 0)) & 0xFF) << 16)
            | (int(snes_cpu.get("pc", 0)) & 0xFFFF)
        ),
        "sa1_pc": (
            ((int(sa1_cpu.get("k", 0)) & 0xFF) << 16)
            | (int(sa1_cpu.get("pc", 0)) & 0xFFFF)
        ),
        "tick": le16(m.read_memory("Sa1Memory", 0x0760, 2)),
        "halt": le16(m.read_memory("Sa1Memory", 0x004E, 2)),
        "pc68k": int.from_bytes(
            m.read_memory("Sa1Memory", 0x0040, 4), "little"
        )
        & 0xFFFFFF,
        "task_mask": int.from_bytes(
            m.read_memory("snesMemory", 0x400002, 2), "big"
        ),
        "credits": int.from_bytes(
            m.read_memory("snesMemory", 0x401C62, 2), "big"
        ),
        "render_complete": le16(
            m.read_memory("snesWorkRam", 0x89A2, 2)
        ),
        "renderer_busy": le16(
            m.read_memory("snesWorkRam", 0x899C, 2)
        ),
        "snapshot_generation": le16(
            m.read_memory("snesWorkRam", 0x899A, 2)
        ),
        "direct_generation": le16(
            m.read_memory("snesWorkRam", 0x89A0, 2)
        ),
        "rendered_generation": le16(
            m.read_memory("snesWorkRam", 0x89A4, 2)
        ),
        "render_queue_primary": le16(
            m.read_memory("snesWorkRam", 0x89D2, 2)
        ),
        "render_queue_secondary": le16(
            m.read_memory("snesWorkRam", 0x89D6, 2)
        ),
        "render_queue_drops": le16(
            m.read_memory("snesWorkRam", 0x89D4, 2)
        ),
        "boot_activity": int(
            m.read_memory("snesWorkRam", 0x1F1B, 1)[0]
        ),
        "bg_mode": int(ppu.get("bgMode", -1)),
        "bg1_hscroll": int(bg1["hscroll"]),
        "bg1_vscroll": int(bg1["vscroll"]),
        "scroll_packed": le16(
            m.read_memory("snesWorkRam", 0x8994, 2)
        ),
        # The renderer-owned packed value above can lag while its queues are
        # saturated.  Retain the coherent live X1 source too so temporal-scroll
        # diagnostics can distinguish a slow producer from dropped snapshots.
        "live_scroll_packed": (live_scrollx << 8)
        | ((live_scrolly + 7) & 0xFF),
        "live_scrollx_column0": live_scrollx,
        "live_scrolly_column4": live_scrolly,
        "latest_scrollx": int(
            m.read_memory("snesWorkRam", 0x72B2, 1)[0]
        ),
        "latest_scroll_valid": int(
            m.read_memory("snesWorkRam", 0x72B3, 1)[0]
        ),
        "presented_scrollx": int(
            m.read_memory("snesWorkRam", 0x72B4, 1)[0]
        ),
        "presented_hofs": le16(
            m.read_memory("snesWorkRam", 0x72B5, 2)
        ),
        "displayed_map_scrollx": int(
            m.read_memory("snesWorkRam", 0x72B7, 1)[0]
        ),
        "displayed_map_valid": int(
            m.read_memory("snesWorkRam", 0x72B8, 1)[0]
        ),
        "map_commit_pending": int(
            m.read_memory("snesWorkRam", 0x72B9, 1)[0]
        ),
        "bg_column_kind": le16(
            m.read_memory("snesWorkRam", 0x8996, 2)
        ),
        "bg_dirty": le16(
            m.read_memory("snesWorkRam", 0x8990, 2)
        ),
        "bg_manifest": le16(
            m.read_memory("snesWorkRam", 0x89BC, 2)
        ),
        # Retain the displayed/staged BG colors and their logical source.  A
        # geometrically aligned framebuffer can still flash when a palette
        # slot is republished or overwritten between video frames.
        "bg_cgram": bg_cgram.hex(),
        "bg_cgram_sha256": hashlib.sha256(bg_cgram).hexdigest(),
        "bg_cgram_staging": bg_cgram_staging.hex(),
        "bg_cgram_staging_sha256": hashlib.sha256(
            bg_cgram_staging
        ).hexdigest(),
        "raw_palette_sha256": hashlib.sha256(raw_palette).hexdigest(),
        "bg_palette_bank_map": bytes(
            m.read_memory("snesWorkRam", 0x8940, 0x20)
        ).hex(),
        "displayed_bg_map_sha256": hashlib.sha256(
            displayed_bg_map
        ).hexdigest(),
        "displayed_bg_map": displayed_bg_map.hex(),
        "staged_bg_map_sha256": hashlib.sha256(staged_bg_map).hexdigest(),
        "staged_bg_map": staged_bg_map.hex(),
        "dma0_pending": int(
            m.read_memory("snesWorkRam", 0x1F11, 1)[0]
        ),
        "dma0_descriptor": bytes(
            m.read_memory("snesMemory", 0x004300, 7)
        ).hex(),
        "displayed_bg_graphics_sha256": hashlib.sha256(
            displayed_bg_graphics
        ).hexdigest(),
        "displayed_bg_graphics_record_sha256": [
            hashlib.sha256(
                displayed_bg_graphics[offset : offset + 0x80]
            ).hexdigest()
            for offset in range(0, len(displayed_bg_graphics), 0x80)
        ],
        "displayed_opt_table": displayed_opt_table.hex(),
        "displayed_opt_table_sha256": hashlib.sha256(
            displayed_opt_table
        ).hexdigest(),
        "bg_cache_marker": le16(
            m.read_memory("snesWorkRam", 0x8982, 2)
        ),
        "bg_column_map": bytes(
            m.read_memory("snesWorkRam", 0x89E0, 16)
        ).hex(),
        "bg_column_y_direct": bytes(
            m.read_memory("snesWorkRam", 0x72C0, 16)
        ).hex(),
        "bg_column_y_physical": bytes(
            m.read_memory("snesWorkRam", 0x72A0, 16)
        ).hex(),
        "bg_opt_global_vofs": int(
            m.read_memory("snesWorkRam", 0x72B0, 1)[0]
        ),
        "bg_opt_enabled": int(
            m.read_memory("snesWorkRam", 0x72B1, 1)[0]
        ),
        "x1_scrolly_columns_2_4_6_8_9": [
            m.read_memory(
                "snesMemory", 0x413401 + column * 0x20, 1
            )[0]
            for column in (2, 4, 6, 8, 9)
        ],
        "title_text_meta": le16(
            m.read_memory("snesWorkRam", 0x89BE, 2)
        ),
        "main_screen_layers": int(ppu.get("mainScreenLayers", -1)),
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
    # Separate Mesen processes share one screenshot directory and can choose
    # the same numeric filename.  Serialize the emulator write plus our copy;
    # otherwise parallel captures can silently import another process's frame.
    SCREENSHOT_LOCK.parent.mkdir(parents=True, exist_ok=True)
    with SCREENSHOT_LOCK.open("a+", encoding="utf-8") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
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
    if args.mirror_live_scroll and args.step != 1:
        raise SystemExit("--mirror-live-scroll requires --step 1")
    for label, path in (
        ("ROM", args.rom),
        ("Mesen", args.mesen),
    ):
        if not path.is_file():
            raise FileNotFoundError(f"{label} not found: {path}")
    if args.state is not None and not args.state.is_file():
        raise FileNotFoundError(f"state not found: {args.state}")
    if args.refresh_video_mirror and args.state is None:
        raise SystemExit("--refresh-video-mirror requires --state")
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
        "runtime_memory_pokes": (
            ([
                {
                    "region": "snesWorkRam $7F:8000-$AFFF",
                    "source": (
                        f"selected ROM file ${VIDEO_FILE_BASE:06X}-"
                        f"${VIDEO_FILE_BASE + VIDEO_WRAM_LENGTH - 1:06X}"
                    ),
                    "reason": "cross-version checkpoint video-mirror refresh",
                }
            ]
            if args.refresh_video_mirror
            else [])
            + ([
                {
                    "region": "snesWorkRam $7E:8995",
                    "source": "live X1 column-0 scroll byte at $41:3409",
                    "cadence": "once before every resumed video frame",
                    "reason": "same-ROM register-only temporal-scroll diagnostic",
                }
            ] if args.mirror_live_scroll else [])
        ),
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
        if args.refresh_video_mirror:
            video_mirror = rom.read_bytes()[
                VIDEO_FILE_BASE : VIDEO_FILE_BASE + VIDEO_WRAM_LENGTH
            ]
            if len(video_mirror) != VIDEO_WRAM_LENGTH:
                raise RuntimeError("selected ROM does not contain the video mirror span")
            for offset in range(0, VIDEO_WRAM_LENGTH, 0x1000):
                chunk = video_mirror[offset : offset + 0x1000]
                m.write_memory(
                    "snesWorkRam",
                    VIDEO_WRAM_OFFSET + offset,
                    chunk.hex(),
                )
            observed = bytes(
                m.read_memory(
                    "snesWorkRam", VIDEO_WRAM_OFFSET, VIDEO_WRAM_LENGTH
                )
            )
            if observed != video_mirror:
                raise RuntimeError("selected-ROM video mirror injection did not verify")
            print(
                json.dumps(
                    {
                        "event": "video_mirror_refresh",
                        "region": "$7F:8000-$AFFF",
                        "length": VIDEO_WRAM_LENGTH,
                        "sha256": hashlib.sha256(video_mirror).hexdigest(),
                    },
                    sort_keys=True,
                ),
                flush=True,
            )
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
                        "boot_activity": snap["boot_activity"],
                        "bg_mode": snap["bg_mode"],
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
            if args.mirror_live_scroll:
                live_scrollx = int(
                    m.read_memory("snesMemory", 0x413409, 1)[0]
                )
                m.write_memory(
                    "snesWorkRam", 0x8995, f"{live_scrollx:02x}"
                )
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
