#!/usr/bin/env python3
"""Cold-boot production baseline for the Superman recovery campaign.

This deliberately avoids save states, state injection, and manual accelerator
arming.  It observes the production ROM from power-on, records the exact point
where ``snd_vframe`` arms the accelerators, drives coin/start through the
project's virtual-controller mailbox, and captures performance/render state in
one continuous Nexen session.

The output distinguishes three currencies that older reports conflated:

* emulated SNES video frames (Nexen frameCount),
* emulated Superman game ticks (the purpose-built $0760 counter incremented at
  the $0818 frame boundary), and
* host wall time spent producing those frames.

No rate is called trustworthy unless the production gates are observed armed.
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
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, "/home/chad/Mesen2/python")

import mesen_mcp.session as _session

_session.validate_mesen_build = lambda *_args, **_kwargs: None
from mesen_mcp import McpSession

DEFAULT_ROM = ROOT / "build/interp.sfc"
DEFAULT_NEXEN = Path(
    "/home/chad/Nexen/bin/linux-x64/Release/linux-x64/publish/Nexen"
)

COIN = 0x2000  # SNES Select, mapped to arcade Coin 1
START = 0x1000


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def le16(data: bytes) -> int:
    return data[0] | (data[1] << 8)


def le32(data: bytes) -> int:
    return le16(data) | (le16(data[2:]) << 16)


def modular_delta(now: int, before: int, bits: int) -> int:
    return (now - before) & ((1 << bits) - 1)


class Recorder:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._stream = path.open("x", encoding="utf-8")

    def emit(self, event: str, **fields: Any) -> None:
        row = {"event": event, "time": time.time(), **fields}
        line = json.dumps(row, sort_keys=True)
        print(line, flush=True)
        self._stream.write(line + "\n")
        self._stream.flush()

    def close(self) -> None:
        self._stream.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    parser.add_argument("--nexen", type=Path, default=DEFAULT_NEXEN)
    parser.add_argument("--port", type=int, default=7467)
    parser.add_argument("--chunk", type=int, default=150)
    parser.add_argument("--max-video-frames", type=int, default=18000)
    parser.add_argument(
        "--preinput-ticks",
        type=int,
        default=105,
        help="Observed production ticks after arming before the first coin pulse.",
    )
    parser.add_argument("--hold-ticks", type=int, default=8, help="Each coin pulse.")
    parser.add_argument("--gap-ticks", type=int, default=7, help="Between coin pulses.")
    parser.add_argument(
        "--prestart-gap-ticks", type=int, default=12, help="Second coin to Start."
    )
    parser.add_argument("--start-hold-ticks", type=int, default=10)
    parser.add_argument("--settle-ticks", type=int, default=12)
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "build/recovery-20260712/baseline",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    if any(args.output.iterdir()):
        raise SystemExit(f"refusing to overwrite non-empty evidence directory: {args.output}")

    rom = args.rom.resolve()
    nexen = args.nexen.resolve()
    is_nexen = nexen.name == "Nexen"
    dotnet_root = "/home/chad/.dotnet10" if is_nexen else "/home/chad/.dotnet8"
    other_dotnet = "/home/chad/.dotnet8" if is_nexen else "/home/chad/.dotnet10"
    os.environ["DOTNET_ROOT"] = dotnet_root
    path = [
        item
        for item in os.environ.get("PATH", "").split(":")
        if item and item not in (dotnet_root, other_dotnet)
    ]
    os.environ["PATH"] = ":".join([dotnet_root, other_dotnet, *path])
    if not rom.is_file() or rom.stat().st_size != 0x400000:
        raise SystemExit(f"expected a 4 MiB production ROM: {rom}")
    if not nexen.is_file():
        raise SystemExit(f"Nexen not found: {nexen}")
    rom_data = rom.read_bytes()
    testflag = int.from_bytes(rom_data[0x77E0:0x77E2], "little")
    if testflag != 0:
        raise SystemExit(f"refusing non-production ROM: TESTFLAG={testflag:#06x}")
    tick_hook_bytes = rom_data[0x75A3:0x75A6]
    if tick_hook_bytes != bytes.fromhex("ee6007"):
        raise SystemExit(
            "tick hook address is stale: expected INC $0760 at ROM $75A3, "
            f"found {tick_hook_bytes.hex()}"
        )

    try:
        commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip()
        git_status = subprocess.check_output(
            ["git", "status", "--porcelain=v1"], cwd=ROOT, text=True
        ).splitlines()
    except Exception:
        commit = "unknown"
        git_status = ["status unavailable"]

    log = Recorder(args.output / "baseline.jsonl")
    log.emit(
        "provenance",
        git_commit=commit,
        git_dirty=bool(git_status),
        git_status=git_status,
        harness_sha256=sha256(Path(__file__).resolve()),
        tick_counter_iram="0760",
        tick_hook_cpu_address="00:F5A3",
        tick_hook_rom_bytes=tick_hook_bytes.hex(),
        rom=str(rom),
        rom_sha256=sha256(rom),
        rom_size=rom.stat().st_size,
        testflag=testflag,
        nexen=str(nexen),
        nexen_sha256=sha256(nexen),
        dotnet_root=dotnet_root,
        chunk=args.chunk,
        max_video_frames=args.max_video_frames,
        input_schedule={
            "preinput_ticks": args.preinput_ticks,
            "coin_hold_ticks": args.hold_ticks,
            "intercoin_gap_ticks": args.gap_ticks,
            "prestart_gap_ticks": args.prestart_gap_ticks,
            "start_hold_ticks": args.start_hold_ticks,
            "settle_ticks": args.settle_ticks,
        },
    )

    wall_start = time.monotonic()
    result = "max_frames"
    stage = "boot"
    stage_tick = 0
    armed_tick_total: int | None = None
    gameplay_tick_total: int | None = None
    armed_snapshot: dict[str, Any] | None = None
    first_snapshot: dict[str, Any] | None = None
    last_tick16 = 0
    total_ticks = 0
    hook_ticks_total = 0
    last_frame = 0
    input_word = 0

    def copy_screenshot(m: McpSession, label: str) -> dict[str, Any]:
        shot = m.take_screenshot(format="path")
        source = Path(shot["path"])
        target = args.output / f"{label}.png"
        if source.is_file():
            shutil.copy2(source, target)
        log.emit("screenshot", label=label, source=str(source), copy=str(target), **shot)
        return shot

    try:
        with McpSession(
            rom=rom,
            mesen=nexen,
            cwd=ROOT,
            port=args.port,
            boot_wait=6.0,
            socket_timeout=300.0,
            stderr_log=args.output / "emulator.stderr.log",
        ) as m:
            # Nexen runs while the client waits for its MCP socket.  Freeze it
            # before installing hooks or taking the first multi-read sample so
            # every recorded snapshot is coherent.
            pause_result = m.pause()
            log.emit(
                "emulator_ready",
                ping=m.ping(),
                state=m.get_state(),
                pause=pause_result,
            )

            # $00:F5A3 is the assembled ``inc $0760`` instruction in lh_0818.
            # This independent execution hook cross-checks that the purpose-built
            # counter advances exactly once per observed frame-boundary clamp.
            tick_hook = m.add_exec_hook(0x00F5A3, cpu_type="Sa1")

            def r16(addr: int, memory_type: str = "Sa1Memory") -> int:
                return le16(m.read_memory(memory_type, addr, 2))

            def r32(addr: int, memory_type: str = "Sa1Memory") -> int:
                return le32(m.read_memory(memory_type, addr, 4))

            def task_mask() -> int:
                # BW-RAM is exposed in the SA-1's byte order here.  Existing
                # gameplay probes therefore read $3B40 as little-endian.
                return le16(m.read_memory("snesMemory", 0x400002, 2))

            def set_virtual_input(value: int) -> None:
                nonlocal input_word
                input_word = value
                m.write_memory(
                    "snesMemory", 0x410002, value.to_bytes(2, "little").hex()
                )
                log.emit("input", stage=stage, value=value, tick_total=total_ticks)

            def snapshot() -> dict[str, Any]:
                nonlocal last_tick16, total_ticks
                state = m.get_state()
                frame = int(state.get("frameCount", 0))
                tick16 = r16(0x0760)
                total_ticks += modular_delta(tick16, last_tick16, 16)
                last_tick16 = tick16
                cpu = m.get_cpu_state("Sa1")
                ring = m.read_memory("snesMemory", 0x401C40, 4)
                gates = {
                    "loop": r16(0x072E),
                    "escape": r16(0x071A),
                    "choke": r16(0x073A),
                    "swin": r16(0x073C),
                    "select": r16(0x0736),
                    "latch": r16(0x0768),
                }
                return {
                    "frame": frame,
                    "tick16": tick16,
                    "tick_total": total_ticks,
                    "tick_hook_total": hook_ticks_total,
                    "steps": r32(0x4A),
                    "pc68k": r32(0x40) & 0xFFFFFF,
                    "opcode": r16(0x44),
                    "halt": r16(0x4E),
                    "ac": r16(0xAC),
                    "task_mask": task_mask(),
                    "sound_ring_ptr": ring.hex(),
                    "gates": gates,
                    "sa1_cycles": int(cpu.get("cycleCount", 0)),
                    "sa1_pc": (int(cpu.get("k", 0)) << 16) | int(cpu.get("pc", 0)),
                    "emulator_running": bool(state.get("isRunning", False)),
                    "emulator_paused": bool(state.get("isPaused", False)),
                    "stage": stage,
                    "input": input_word,
                    "wall_elapsed": time.monotonic() - wall_start,
                }

            first = snapshot()
            m.drain_notifications(timeout=0.05)
            last_tick16 = first["tick16"]
            total_ticks = 0
            hook_ticks_total = 0
            first["tick_total"] = 0
            first["tick_hook_total"] = 0
            first_snapshot = dict(first)
            last_frame = first["frame"]
            log.emit("sample", **first)

            stagnant_chunks = 0
            while last_frame - first_snapshot["frame"] < args.max_video_frames:
                run_wall = time.monotonic()
                run_result = m.run_frames(args.chunk)
                run_seconds = time.monotonic() - run_wall
                notifications = m.drain_notifications(timeout=0.05)
                hook_ticks_total += sum(
                    1
                    for note in notifications
                    if note.get("params", {}).get("handle") == tick_hook
                )
                snap = snapshot()
                frame_delta = snap["frame"] - last_frame
                last_frame = snap["frame"]
                stagnant_chunks = stagnant_chunks + 1 if frame_delta <= 0 else 0
                snap["run_frames_requested"] = args.chunk
                snap["run_frame_delta"] = frame_delta
                snap["run_wall_seconds"] = run_seconds
                snap["run_result"] = run_result
                log.emit("sample", **snap)

                if stagnant_chunks >= 3:
                    result = "no_video_progress"
                    copy_screenshot(m, "no_video_progress")
                    break

                gates = snap["gates"]
                armed = (
                    gates["loop"] == 1
                    and gates["escape"] == 1
                    and gates["choke"] == 1
                    and gates["swin"] == 0xA55A
                    and gates["select"] == 0x5EEC
                    and gates["latch"] == 1
                )
                if armed_tick_total is None and armed:
                    armed_tick_total = total_ticks
                    armed_snapshot = dict(snap)
                    stage_tick = total_ticks
                    stage = "preinput"
                    log.emit("accelerators_armed", **snap)
                    copy_screenshot(m, "armed")

                relative = total_ticks - stage_tick
                if stage == "preinput" and relative >= args.preinput_ticks:
                    stage = "coin1_hold"
                    stage_tick = total_ticks
                    set_virtual_input(COIN)
                elif stage == "coin1_hold" and relative >= args.hold_ticks:
                    stage = "coin1_gap"
                    stage_tick = total_ticks
                    set_virtual_input(0)
                elif stage == "coin1_gap" and relative >= args.gap_ticks:
                    stage = "coin2_hold"
                    stage_tick = total_ticks
                    set_virtual_input(COIN)
                elif stage == "coin2_hold" and relative >= args.hold_ticks:
                    stage = "coin2_gap"
                    stage_tick = total_ticks
                    set_virtual_input(0)
                elif (
                    stage == "coin2_gap"
                    and relative >= args.prestart_gap_ticks
                ):
                    stage = "start_hold"
                    stage_tick = total_ticks
                    set_virtual_input(START)
                elif stage == "start_hold" and relative >= args.start_hold_ticks:
                    stage = "post_start"
                    stage_tick = total_ticks
                    set_virtual_input(0)

                # The boot RAM test writes patterns through $40:0002, including
                # transient values that can resemble a gameplay task mask.  A
                # $3Bxx mask is meaningful only after this same run delivered
                # and released Start.
                in_gameplay = (
                    stage in ("post_start", "gameplay_settle")
                    and (snap["task_mask"] >> 8) == 0x3B
                )
                if gameplay_tick_total is None and in_gameplay:
                    gameplay_tick_total = total_ticks
                    stage = "gameplay_settle"
                    stage_tick = total_ticks
                    log.emit("gameplay_detected", **snap)
                    copy_screenshot(m, "gameplay_detected")

                if (
                    stage == "gameplay_settle"
                    and total_ticks - stage_tick >= args.settle_ticks
                ):
                    result = "gameplay_settled"
                    copy_screenshot(m, "gameplay_settled")
                    break

                if snap["halt"] != 0:
                    result = f"halt_{snap['halt']:04x}"
                    copy_screenshot(m, "halt")
                    break

            final = snapshot()
            ppu = m.get_ppu_state()
            cgram = bytes(m.read_memory("snesCgRam", 0, 512))
            oam = bytes(m.read_memory("snesSpriteRam", 0, 0x220))
            vram = bytes(m.read_memory("snesVideoRam", 0, 0x10000))
            bg_codes = bytes(m.read_memory("snesMemory", 0x414800, 0x400))
            bg_colors = bytes(m.read_memory("snesMemory", 0x414C00, 0x400))
            for name, data in (
                ("cgram.bin", cgram),
                ("oam.bin", oam),
                ("vram.bin", vram),
                ("bg_codes.bin", bg_codes),
                ("bg_colors.bin", bg_colors),
            ):
                (args.output / name).write_bytes(data)
            assert first_snapshot is not None
            video_delta = final["frame"] - first_snapshot["frame"]
            wall_delta = max(1e-9, final["wall_elapsed"] - first_snapshot["wall_elapsed"])
            game_fps = (total_ticks * 60.0 / video_delta) if video_delta > 0 else 0.0
            host_video_fps = video_delta / wall_delta
            post_arm = None
            boot_to_arm = None
            if armed_snapshot is not None:
                boot_to_arm = {
                    "power_on_video_frames": armed_snapshot["frame"],
                    "power_on_wall_seconds": armed_snapshot["wall_elapsed"],
                    "video_frames": armed_snapshot["frame"] - first_snapshot["frame"],
                    "wall_seconds": (
                        armed_snapshot["wall_elapsed"] - first_snapshot["wall_elapsed"]
                    ),
                    "sa1_cycles": modular_delta(
                        armed_snapshot["sa1_cycles"], first_snapshot["sa1_cycles"], 64
                    ),
                    "interpreted_steps": modular_delta(
                        armed_snapshot["steps"], first_snapshot["steps"], 32
                    ),
                }
                arm_video = final["frame"] - armed_snapshot["frame"]
                arm_ticks = total_ticks - armed_snapshot["tick_total"]
                arm_wall = max(1e-9, final["wall_elapsed"] - armed_snapshot["wall_elapsed"])
                post_arm = {
                    "video_frames": arm_video,
                    "game_ticks": arm_ticks,
                    "game_fps": (arm_ticks * 60.0 / arm_video) if arm_video > 0 else 0.0,
                    "host_video_fps": arm_video / arm_wall,
                    "wall_seconds": arm_wall,
                }
            counter_hook_match = total_ticks == hook_ticks_total
            counter_hook_validated = hook_ticks_total > 0 and counter_hook_match
            log.emit(
                "final",
                result=result,
                armed_tick_total=armed_tick_total,
                gameplay_tick_total=gameplay_tick_total,
                ppu=ppu,
                cgram_unique=len({le16(cgram[i : i + 2]) for i in range(0, 512, 2)}),
                bg_codes_nonzero=sum(byte != 0 for byte in bg_codes),
                bg_colors_nonzero=sum(byte != 0 for byte in bg_colors),
                wall_total=time.monotonic() - wall_start,
                measured_video_frames=video_delta,
                measured_game_ticks=total_ticks,
                measured_tick_hook_events=hook_ticks_total,
                counter_hook_match=counter_hook_match,
                counter_hook_validated=counter_hook_validated,
                overall_observed_tick_rate=game_fps,
                emulated_game_fps=(
                    post_arm["game_fps"]
                    if post_arm is not None and counter_hook_validated
                    else None
                ),
                host_video_fps=host_video_fps,
                power_on_video_frames=final["frame"],
                power_on_wall_seconds=final["wall_elapsed"],
                power_on_host_video_fps=(
                    final["frame"] / max(1e-9, final["wall_elapsed"])
                ),
                startup_frames_before_first_sample=first_snapshot["frame"],
                boot_to_arm=boot_to_arm,
                post_arm=post_arm,
                **final,
            )
            if not any(args.output.glob("*.png")):
                copy_screenshot(m, "final")
    finally:
        log.close()

    return 0 if result == "gameplay_settled" else 2


if __name__ == "__main__":
    sys.exit(main())
