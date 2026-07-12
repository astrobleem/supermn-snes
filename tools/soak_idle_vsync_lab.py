#!/usr/bin/env python3
"""Long-form behavioral soak for the isolated R5 NMI/WAI lab ROM.

This runner starts from a same-ROM, pre-hook checkpoint, drives the normal
virtual coin/start mailbox, and runs past the historical $0818-corruption
window near game tick $9F05.  It does not install debugger hooks.  At every
sample it checks the production accelerator gates, sound-ring identity,
interpreter halt word, forward tick progress, and every initialized task's
saved-stack pointer against the game's real floor table at 68K ROM $0882.

The lab remains explicitly off-production: the ROM must contain the R5VSYNC1
or R5VNMI01 marker and IRAM $0734 must already be one in the supplied checkpoint.
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

from profile_continuous import (
    EXPECTED_GATES,
    GATE_ADDRS,
    configure_dotnet,
    sha256,
    wait_for_stable_file,
)


DEFAULT_ROM = ROOT / "build/r5-idle-vsync-nmi-lab/interp_vsync_lab.sfc"
DEFAULT_NEXEN = Path(
    "/mnt/sdc1/Nexen-r5-20260712/"
    "bin/linux-x64/Release/linux-x64/publish/Nexen"
)
DEFAULT_STATE = (
    ROOT
    / "build/recovery-20260712/r5-idle-vsync-nmi-wram-cold/production-arm.mss"
)
DEFAULT_OUTPUT = ROOT / "build/recovery-20260712/r5-idle-vsync-nmi-soak"

COIN = 0x2000
START = 0x1000
LAB_MARKER_OFFSET = 0x2CFF00
LAB_MARKERS = (b"R5VSYNC1", b"R5VNMI01")
HISTORICAL_WINDOW_START = 0x9E00
HISTORICAL_EVENT = 0x9F05
HISTORICAL_DERAIL = 0xA005


def int_auto(value: str) -> int:
    return int(value, 0)


def le16(data: bytes) -> int:
    return data[0] | (data[1] << 8)


def le32(data: bytes) -> int:
    return le16(data) | (le16(data[2:]) << 16)


def modular_delta(now: int, before: int, bits: int) -> int:
    return (now - before) & ((1 << bits) - 1)


def git_value(*args: str) -> str:
    try:
        return subprocess.check_output(
            ["git", *args], cwd=ROOT, text=True, stderr=subprocess.DEVNULL
        ).strip()
    except Exception:
        return "unknown"


class Recorder:
    def __init__(self, path: Path) -> None:
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
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--port", type=int, default=7483)
    parser.add_argument(
        "--target-ticks",
        type=int_auto,
        default=0xA100,
        help="Total post-checkpoint ticks; default passes the historical $9F05/$A005 window.",
    )
    parser.add_argument("--chunk-frames", type=int, default=600)
    parser.add_argument("--sample-ticks", type=int, default=256)
    parser.add_argument("--timeout", type=float, default=7200.0)
    parser.add_argument("--preinput-ticks", type=int, default=105)
    parser.add_argument("--hold-ticks", type=int, default=8)
    parser.add_argument("--gap-ticks", type=int, default=7)
    parser.add_argument("--prestart-gap-ticks", type=int, default=12)
    parser.add_argument("--start-hold-ticks", type=int, default=10)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.target_ticks <= 0:
        raise SystemExit("--target-ticks must be positive")
    if args.chunk_frames <= 0 or args.sample_ticks <= 0:
        raise SystemExit("--chunk-frames and --sample-ticks must be positive")
    if args.timeout <= 0:
        raise SystemExit("--timeout must be positive")

    rom = args.rom.resolve()
    nexen = args.nexen.resolve()
    checkpoint = args.state.resolve()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise SystemExit(f"refusing to overwrite non-empty evidence directory: {output}")
    if not rom.is_file() or rom.stat().st_size != 0x400000:
        raise SystemExit(f"expected a 4 MiB lab ROM: {rom}")
    if not nexen.is_file():
        raise SystemExit(f"Nexen not found: {nexen}")
    if not checkpoint.is_file():
        raise SystemExit(f"checkpoint not found: {checkpoint}")
    rom_data = rom.read_bytes()
    marker = rom_data[LAB_MARKER_OFFSET : LAB_MARKER_OFFSET + 8]
    if marker not in LAB_MARKERS:
        raise SystemExit(
            f"refusing unmarked lab ROM: expected one of {LAB_MARKERS!r}, got {marker!r}"
        )
    if rom_data[0x75A3:0x75A6] != bytes.fromhex("ee6007"):
        raise SystemExit("lab moved the exact $00:F5A3 INC $0760 boundary")

    configure_dotnet(nexen)
    log = Recorder(output / "soak.jsonl")
    wall_start = time.monotonic()
    result = "exception"
    failure: str | None = None
    total_ticks = 0
    gameplay_tick: int | None = None
    min_stack_margin: int | None = None
    samples = 0
    milestones_seen: list[int] = []

    log.emit(
        "provenance",
        git_commit=git_value("rev-parse", "HEAD"),
        git_status=git_value("status", "--porcelain=v1").splitlines(),
        harness_sha256=sha256(Path(__file__).resolve()),
        rom=str(rom),
        rom_sha256=sha256(rom),
        marker=marker.decode("ascii"),
        checkpoint=str(checkpoint),
        checkpoint_sha256=sha256(checkpoint),
        nexen=str(nexen),
        nexen_sha256=sha256(nexen),
        target_ticks=args.target_ticks,
        historical_window={
            "start": HISTORICAL_WINDOW_START,
            "mass_coroutine_event": HISTORICAL_EVENT,
            "old_derail_observed": HISTORICAL_DERAIL,
        },
        chunk_frames=args.chunk_frames,
        sample_ticks=args.sample_ticks,
        input_schedule={
            "preinput_ticks": args.preinput_ticks,
            "coin_hold_ticks": args.hold_ticks,
            "intercoin_gap_ticks": args.gap_ticks,
            "prestart_gap_ticks": args.prestart_gap_ticks,
            "start_hold_ticks": args.start_hold_ticks,
        },
    )

    try:
        with McpSession(
            rom=rom,
            mesen=nexen,
            cwd=ROOT,
            port=args.port,
            boot_wait=6.0,
            socket_timeout=max(300.0, args.timeout),
            stderr_log=output / "emulator.stderr.log",
        ) as m:
            m.pause()
            load_result = m.load_state(checkpoint)
            m.pause()

            floor_bytes = m.read_memory("snesMemory", 0xC10882, 16 * 4)
            stack_floors = [
                int.from_bytes(floor_bytes[index * 4 : index * 4 + 4], "big")
                for index in range(16)
            ]

            def r16(address: int, memory_type: str = "Sa1Memory") -> int:
                return le16(m.read_memory(memory_type, address, 2))

            def r32(address: int, memory_type: str = "Sa1Memory") -> int:
                return le32(m.read_memory(memory_type, address, 4))

            def stack_state() -> dict[str, Any]:
                a5 = r32(0x0034) & 0xFFFFFF
                if not 0xF00000 <= a5 <= 0xF0FFFF:
                    return {
                        "a5": a5,
                        "initialized": 0,
                        "minimum_margin": None,
                        "below_floor": [],
                        "tasks": [],
                    }
                base = a5 - 0xF00000
                tasks = []
                below_floor = []
                for index, floor in enumerate(stack_floors):
                    saved_sp = int.from_bytes(
                        m.read_memory(
                            "snesMemory", 0x400000 + base + 0x0A + index * 4, 4
                        ),
                        "big",
                    )
                    descriptor = int.from_bytes(
                        m.read_memory(
                            "snesMemory", 0x400000 + base + 0x4E + index * 4, 4
                        ),
                        "big",
                    )
                    if saved_sp == 0:
                        continue
                    margin = saved_sp - floor
                    task = {
                        "index": index,
                        "descriptor": descriptor,
                        "saved_sp": saved_sp,
                        "floor": floor,
                        "margin": margin,
                    }
                    tasks.append(task)
                    if margin < 0:
                        below_floor.append(task)
                return {
                    "a5": a5,
                    "initialized": len(tasks),
                    "minimum_margin": min(
                        (task["margin"] for task in tasks), default=None
                    ),
                    "below_floor": below_floor,
                    "tasks": tasks,
                }

            last_tick16 = r16(0x0760)
            start_frame = int(m.get_state().get("frameCount", 0))
            last_frame = start_frame
            last_tick_progress_frame = start_frame
            last_sample_tick = -args.sample_ticks
            stage = "preinput"
            stage_tick = 0
            input_word = 0
            frames_per_tick = 5.0

            def set_input(value: int) -> None:
                nonlocal input_word
                input_word = value
                m.write_u16(0x410002, value, "snesMemory")
                log.emit("input", stage=stage, tick_total=total_ticks, value=value)

            def take_screenshot(label: str) -> None:
                shot = m.take_screenshot(format="path")
                source = Path(shot["path"])
                target = output / f"{label}.png"
                if source.is_file():
                    shutil.copy2(source, target)
                log.emit(
                    "screenshot",
                    label=label,
                    source=str(source),
                    copy=str(target),
                    response=shot,
                )

            def sample(label: str) -> dict[str, Any]:
                nonlocal min_stack_margin, samples
                state = m.get_state()
                cpu = m.get_cpu_state("Sa1")
                stack = stack_state()
                margin = stack["minimum_margin"]
                if margin is not None:
                    min_stack_margin = (
                        margin
                        if min_stack_margin is None
                        else min(min_stack_margin, margin)
                    )
                snap = {
                    "label": label,
                    "wall_elapsed": time.monotonic() - wall_start,
                    "frame": int(state.get("frameCount", 0)),
                    "tick16": r16(0x0760),
                    "tick_total": total_ticks,
                    "pc68k": r32(0x0040) & 0xFFFFFF,
                    "steps": r32(0x004A),
                    "opcode": r16(0x0044),
                    "halt": r16(0x004E),
                    "ac": r16(0x00AC),
                    "task_mask": r16(0x400002, "snesMemory"),
                    "sound_ring_ptr": m.read_memory(
                        "snesMemory", 0x401C40, 4
                    ).hex(),
                    "gates": {
                        name: r16(address) for name, address in GATE_ADDRS.items()
                    },
                    "idle_vsync_lab_gate": r16(0x0734),
                    "sa1_cycles": int(cpu.get("cycleCount", 0)),
                    "sa1_pc": (int(cpu.get("k", 0)) << 16)
                    | int(cpu.get("pc", 0)),
                    "stage": stage,
                    "input": input_word,
                    "stack": stack,
                }
                log.emit("sample", **snap)
                samples += 1
                return snap

            first = sample("loaded_checkpoint")
            if first["gates"] != EXPECTED_GATES:
                raise RuntimeError(
                    f"checkpoint gate mismatch: {first['gates']} != {EXPECTED_GATES}"
                )
            if first["idle_vsync_lab_gate"] != 1:
                raise RuntimeError("checkpoint does not have the explicit $0734 lab gate set")
            if first["halt"] != 0 or first["sound_ring_ptr"] != "00f01c20":
                raise RuntimeError("checkpoint is not a healthy production-armed state")
            log.emit("emulator_ready", load=load_result, start=first)

            while total_ticks < args.target_ticks:
                wall_elapsed = time.monotonic() - wall_start
                if wall_elapsed >= args.timeout:
                    result = "timeout"
                    failure = f"wall timeout after {wall_elapsed:.1f}s"
                    break

                stage_limits = {
                    "preinput": args.preinput_ticks,
                    "coin1_hold": args.hold_ticks,
                    "coin1_gap": args.gap_ticks,
                    "coin2_hold": args.hold_ticks,
                    "coin2_gap": args.prestart_gap_ticks,
                    "start_hold": args.start_hold_ticks,
                }
                run_frames = args.chunk_frames
                if stage in stage_limits:
                    remaining = stage_limits[stage] - (total_ticks - stage_tick)
                    if remaining > 0:
                        run_frames = max(
                            1,
                            min(
                                args.chunk_frames,
                                int(max(1.0, frames_per_tick * remaining * 0.45)),
                            ),
                        )

                tick_before = total_ticks
                frame_before = last_frame
                run_result = m.run_frames(run_frames)
                if not bool(run_result.get("isPaused", False)):
                    raise RuntimeError(f"run_frames did not pause: {run_result}")
                frame_now = int(m.get_state().get("frameCount", 0))
                tick16 = r16(0x0760)
                tick_delta = modular_delta(tick16, last_tick16, 16)
                total_ticks += tick_delta
                last_tick16 = tick16
                frame_delta = frame_now - frame_before
                last_frame = frame_now
                if tick_delta > 0:
                    frames_per_tick = frame_delta / tick_delta
                    last_tick_progress_frame = frame_now

                transitioned = False
                relative = total_ticks - stage_tick
                if stage == "preinput" and relative >= args.preinput_ticks:
                    stage = "coin1_hold"
                    stage_tick = total_ticks
                    set_input(COIN)
                    transitioned = True
                elif stage == "coin1_hold" and relative >= args.hold_ticks:
                    stage = "coin1_gap"
                    stage_tick = total_ticks
                    set_input(0)
                    transitioned = True
                elif stage == "coin1_gap" and relative >= args.gap_ticks:
                    stage = "coin2_hold"
                    stage_tick = total_ticks
                    set_input(COIN)
                    transitioned = True
                elif stage == "coin2_hold" and relative >= args.hold_ticks:
                    stage = "coin2_gap"
                    stage_tick = total_ticks
                    set_input(0)
                    transitioned = True
                elif stage == "coin2_gap" and relative >= args.prestart_gap_ticks:
                    stage = "start_hold"
                    stage_tick = total_ticks
                    set_input(START)
                    transitioned = True
                elif stage == "start_hold" and relative >= args.start_hold_ticks:
                    stage = "post_start"
                    stage_tick = total_ticks
                    set_input(0)
                    transitioned = True

                must_sample = (
                    transitioned
                    or total_ticks - last_sample_tick >= args.sample_ticks
                    or total_ticks >= args.target_ticks
                )
                snap: dict[str, Any] | None = None
                if must_sample:
                    snap = sample("progress")
                    last_sample_tick = total_ticks

                if snap is None:
                    # The inexpensive health words are still checked every run chunk.
                    halt = r16(0x004E)
                    gates = {name: r16(address) for name, address in GATE_ADDRS.items()}
                    lab_gate = r16(0x0734)
                    ring = m.read_memory("snesMemory", 0x401C40, 4).hex()
                    task_mask = r16(0x400002, "snesMemory")
                else:
                    halt = snap["halt"]
                    gates = snap["gates"]
                    lab_gate = snap["idle_vsync_lab_gate"]
                    ring = snap["sound_ring_ptr"]
                    task_mask = snap["task_mask"]

                if halt != 0:
                    result = f"halt_{halt:04x}"
                    failure = f"interpreter halt word became ${halt:04X}"
                    break
                if gates != EXPECTED_GATES or lab_gate != 1:
                    result = "gate_corruption"
                    failure = f"gate mismatch: production={gates}, lab={lab_gate}"
                    break
                if ring != "00f01c20":
                    result = "sound_ring_corruption"
                    failure = f"sound ring pointer changed to {ring}"
                    break
                if snap is not None and snap["stack"]["below_floor"]:
                    result = "stack_floor_violation"
                    failure = f"saved task stack below floor: {snap['stack']['below_floor']}"
                    break
                if frame_now - last_tick_progress_frame > 1800:
                    result = "tick_stall"
                    failure = (
                        f"no game-tick progress for {frame_now - last_tick_progress_frame} "
                        "video frames"
                    )
                    break

                if gameplay_tick is None and stage == "post_start" and task_mask >> 8 == 0x3B:
                    gameplay_tick = total_ticks
                    log.emit(
                        "gameplay_detected",
                        tick_total=total_ticks,
                        frame=frame_now,
                        task_mask=task_mask,
                    )
                    take_screenshot("gameplay_detected")

                for milestone, label in (
                    (HISTORICAL_WINDOW_START, "historical_window_start"),
                    (HISTORICAL_EVENT, "mass_coroutine_event_passed"),
                    (HISTORICAL_DERAIL, "old_derail_tick_passed"),
                ):
                    if total_ticks >= milestone and milestone not in milestones_seen:
                        milestones_seen.append(milestone)
                        milestone_snap = sample(label)
                        last_sample_tick = total_ticks
                        log.emit(
                            "milestone",
                            label=label,
                            nominal_tick=milestone,
                            observed_tick=total_ticks,
                            state=milestone_snap,
                        )
                        take_screenshot(label)

                if tick_before == total_ticks and frame_now == frame_before:
                    result = "no_emulator_progress"
                    failure = "neither video frames nor game ticks advanced"
                    break

            if total_ticks >= args.target_ticks:
                result = "target_reached"

            m.pause()
            final = sample("final")
            take_screenshot("final")
            state_path = output / "final.mss"
            m.save_state(state_path)
            wait_for_stable_file(state_path, timeout=30.0)
            log.emit(
                "final",
                result=result,
                failure=failure,
                target_ticks=args.target_ticks,
                measured_ticks=total_ticks,
                measured_video_frames=final["frame"] - start_frame,
                gameplay_tick=gameplay_tick,
                historical_milestones_seen=milestones_seen,
                minimum_saved_stack_margin=min_stack_margin,
                samples=samples,
                wall_seconds=time.monotonic() - wall_start,
                final_state_sha256=sha256(state_path),
                state=final,
            )
    except Exception as exc:
        failure = f"{type(exc).__name__}: {exc}"
        log.emit(
            "exception",
            result=result,
            failure=failure,
            measured_ticks=total_ticks,
            gameplay_tick=gameplay_tick,
            minimum_saved_stack_margin=min_stack_margin,
            wall_seconds=time.monotonic() - wall_start,
        )
        raise
    finally:
        log.close()

    return 0 if result == "target_reached" and gameplay_tick is not None else 2


if __name__ == "__main__":
    sys.exit(main())
