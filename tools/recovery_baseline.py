#!/usr/bin/env python3
"""Cold-boot production baseline for the Superman recovery campaign.

This deliberately avoids save states, state injection, and manual accelerator
arming. It observes the production ROM from power-on, records the exact point
where ``snd_vframe`` arms the accelerators and production pacing, drives real
coin/start inputs through Nexen's port-0 controller into the ROM's manual $4016
reader, and captures performance/render/scheduler state in one continuous run.

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
    "/mnt/sdc1/Nexen-r5-20260712/bin/linux-x64/Release/linux-x64/publish/Nexen"
)

COIN = 0x2000  # SNES Select, mapped to arcade Coin 1
START = 0x1000
GAMEPLAY_RIGHT_B = 0x8100
RENDER_COMPLETE_HOOK = 0x7F8924
VIDEO_WRAM_ROM_START = 0x298000
VIDEO_WRAM_LENGTH = 0x3000
VIDEO_WRAM_OFFSET = 0x18000
SUPERVISOR_LOOP_OFFSET = 0xF000
SUPERVISOR_LOOP_LENGTH = 0x37
PACING_CATCHUP_DEBT_MAX = 10
RENDER_QUEUE_CAPACITY = 2
# A request write is observed before the NMI can place that candidate in either
# queue.  With two retained entries, the transaction-level request/ACK delta may
# therefore reach three briefly without losing a renderable sequence.
RENDER_TRANSACTION_DEBT_MAX = RENDER_QUEUE_CAPACITY + 1


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


def frame_counter_delta(now: int, before: int) -> int:
    """Advance of the legacy frame word, tolerating its former 8-bit wrap.

    Old production ROMs sometimes executed ``INC $3300`` with M=1, wrapping
    only the low byte.  Current ROMs force M=0, but retaining this decoder
    makes the evidence harness describe transitional runs honestly instead of
    turning $01F8->$0100 into a fictitious 65,288-frame advance.
    """

    if (now & 0xFF00) == (before & 0xFF00):
        return ((now & 0xFF) - (before & 0xFF)) & 0xFF
    return modular_delta(now, before, 16)


def wait_for_stable_file(path: Path, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    previous = -1
    stable = 0
    while time.monotonic() < deadline:
        size = path.stat().st_size if path.is_file() else -1
        if size > 0 and size == previous:
            stable += 1
            if stable >= 2:
                return
        else:
            stable = 0
        previous = size
        time.sleep(0.05)
    raise TimeoutError(f"save state did not stabilize: {path}")


def adaptive_wall_chunk_seconds(
    maximum: float,
    observed_ticks_per_second: float | None,
    ticks_to_boundary: int | None,
) -> float:
    """Keep wall-time sampling responsive near an input/hook boundary.

    A fixed 30-second sample is useful on slow Nexen, but legacy Mesen can
    advance more than twenty game ticks in that interval.  Halving the
    projected time to the next boundary preserves throughput when far away
    while preventing an 8-tick button pulse from becoming a 20+-tick pulse.
    """

    if (
        maximum <= 0
        or observed_ticks_per_second is None
        or observed_ticks_per_second <= 0
        or ticks_to_boundary is None
        or ticks_to_boundary <= 0
    ):
        return maximum
    projected_half = 0.5 * ticks_to_boundary / observed_ticks_per_second
    return max(1.0, min(maximum, projected_half))


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
    parser.add_argument(
        "--wall-chunk-seconds",
        type=float,
        default=0.0,
        help="Resume for this many host seconds per sample instead of run_frames().",
    )
    parser.add_argument("--max-video-frames", type=int, default=22000)
    parser.add_argument(
        "--max-sample-ticks",
        type=int,
        default=64,
        help="Maximum projected production ticks between coherent scheduler samples.",
    )
    parser.add_argument(
        "--hook-validation-ticks",
        type=int,
        default=32,
        help="Consecutive post-arm counter ticks to cross-check with an exec hook.",
    )
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
    parser.add_argument(
        "--virtual-input",
        action="store_true",
        help=(
            "Compatibility-only: inject $41:0002 instead of driving Nexen port 0. "
            "Runs using this option are not production input evidence."
        ),
    )
    parser.add_argument(
        "--settle-ticks",
        type=int,
        default=90,
        help="Post-gameplay ticks to observe; 90 avoids a short early-fade capture.",
    )
    parser.add_argument(
        "--gameplay-right-b",
        action="store_true",
        help=(
            "Hold Right+B through the measured gameplay phase using Nexen's real "
            "port-0 controller (or the explicitly requested virtual transport)."
        ),
    )
    parser.add_argument(
        "--uninterrupted-gameplay-frames",
        type=int,
        default=0,
        help=(
            "After organic gameplay detection and --settle-ticks, run at least "
            "this many emulated video frames in one unpaused window with "
            "tick/render hooks continuously armed. Non-pausing frame polls avoid "
            "debugger stop-boundary pacing loss."
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "build/recovery-20260712/baseline",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.wall_chunk_seconds < 0 or args.wall_chunk_seconds > 60:
        raise SystemExit("--wall-chunk-seconds must be between 0 and 60")
    if args.hook_validation_ticks <= 0:
        raise SystemExit("--hook-validation-ticks must be positive")
    if args.max_sample_ticks <= 0:
        raise SystemExit("--max-sample-ticks must be positive")
    if args.uninterrupted_gameplay_frames < 0:
        raise SystemExit("--uninterrupted-gameplay-frames cannot be negative")
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
    expected_video_mirror = rom_data[
        VIDEO_WRAM_ROM_START : VIDEO_WRAM_ROM_START + VIDEO_WRAM_LENGTH
    ]
    expected_video_mirror_sha256 = hashlib.sha256(
        expected_video_mirror
    ).hexdigest()
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
        wall_chunk_seconds=args.wall_chunk_seconds,
        max_video_frames=args.max_video_frames,
        max_sample_ticks=args.max_sample_ticks,
        hook_validation_ticks=args.hook_validation_ticks,
        adaptive_wall_chunks=True,
        minimum_wall_chunk_seconds=1.0,
        input_schedule={
            "preinput_ticks": args.preinput_ticks,
            "coin_hold_ticks": args.hold_ticks,
            "intercoin_gap_ticks": args.gap_ticks,
            "prestart_gap_ticks": args.prestart_gap_ticks,
            "start_hold_ticks": args.start_hold_ticks,
            "settle_ticks": args.settle_ticks,
        },
        input_transport=(
            "virtual_injection_410002"
            if args.virtual_input
            else "nexen_port0_manual_4016"
        ),
        input_edge_clock="sa1_exec_hook_00_f5a3_after_production_arm",
        gameplay_control=("right+b_held" if args.gameplay_right_b else "idle"),
        uninterrupted_gameplay_frames=args.uninterrupted_gameplay_frames,
        video_wram_rom_span=[
            VIDEO_WRAM_ROM_START,
            VIDEO_WRAM_ROM_START + VIDEO_WRAM_LENGTH,
        ],
        video_wram_span=[VIDEO_WRAM_OFFSET, VIDEO_WRAM_OFFSET + VIDEO_WRAM_LENGTH],
        video_wram_expected_sha256=expected_video_mirror_sha256,
    )

    wall_start = time.monotonic()
    result = "max_frames"
    stage = "boot"
    stage_tick = 0
    armed_tick_total: int | None = None
    gameplay_tick_total: int | None = None
    gameplay_snapshot: dict[str, Any] | None = None
    armed_snapshot: dict[str, Any] | None = None
    first_snapshot: dict[str, Any] | None = None
    last_tick16 = 0
    total_ticks = 0
    hook_ticks_total = 0
    hook_counter_start_total: int | None = None
    hook_counter_end_total: int | None = None
    hook_validation_match: bool | None = None
    last_frame = 0
    input_word = 0
    controller_buttons = 0
    minimum_saved_stack_margin: int | None = None
    observed_ticks_per_second: float | None = None
    supervisor_loop_expected: bytes | None = None
    supervisor_loop_rom_offset: int | None = None
    renderer_ack_advances = 0
    renderer_stagnant_samples = 0
    last_renderer_ack: int | None = None
    last_renderer_request: int | None = None
    renderer_pending_since_frame: int | None = None
    uninterrupted_gameplay_measurement: dict[str, Any] | None = None

    def copy_screenshot(m: McpSession, label: str) -> dict[str, Any]:
        shot = m.take_screenshot(format="path")
        source = Path(shot["path"])
        target = args.output / f"{label}.png"
        if source.is_file():
            shutil.copy2(source, target)
        # R5 Nexen includes its own top-level ``source`` metadata.  Keep the
        # emulator response nested so it cannot collide with the retained
        # source/copy artifact paths (legacy Mesen did not expose this key).
        log.emit(
            "screenshot",
            label=label,
            source=str(source),
            copy=str(target),
            screenshot=shot,
        )
        return shot

    def save_checkpoint(m: McpSession, label: str) -> Path:
        target = (args.output / f"{label}.mss").resolve()
        response = m.save_state(target)
        wait_for_stable_file(target)
        log.emit(
            "checkpoint",
            label=label,
            path=str(target),
            sha256=sha256(target),
            response=response,
        )
        return target

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

            # Installing a debugger hook roughly halves Nexen's throughput even
            # while its gate is off.  Arm the exact $00:F5A3 hook only after the
            # production gates turn on, validate a bounded consecutive window,
            # then remove it.  The counter continues for the full run.
            tick_hook: int | None = None

            def r16(addr: int, memory_type: str = "Sa1Memory") -> int:
                return le16(m.read_memory(memory_type, addr, 2))

            def r32(addr: int, memory_type: str = "Sa1Memory") -> int:
                return le32(m.read_memory(memory_type, addr, 4))

            def task_mask() -> int:
                # BW-RAM is exposed in the SA-1's byte order here.  Existing
                # gameplay probes therefore read $3B40 as little-endian.
                return le16(m.read_memory("snesMemory", 0x400002, 2))

            floor_bytes = m.read_memory("snesMemory", 0xC10882, 16 * 4)
            stack_floors = [
                int.from_bytes(floor_bytes[index * 4 : index * 4 + 4], "big")
                for index in range(16)
            ]

            def stack_state(contract_active: bool) -> dict[str, Any]:
                a5 = r32(0x0034) & 0xFFFFFF
                if not contract_active or not 0xF00000 <= a5 <= 0xF0FFFF:
                    return {
                        "a5": a5,
                        "contract_active": contract_active,
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
                    "contract_active": True,
                    "initialized": len(tasks),
                    "minimum_margin": min(
                        (task["margin"] for task in tasks), default=None
                    ),
                    "below_floor": below_floor,
                    "tasks": tasks,
                }

            def set_input(
                value: int,
                *,
                exact_tick_total: int | None = None,
                hook_cycle: int | None = None,
                hook_frame: int | None = None,
            ) -> None:
                nonlocal input_word, controller_buttons
                input_word = value
                controller_buttons = 0
                if args.virtual_input:
                    m.write_memory(
                        "snesMemory", 0x410002, value.to_bytes(2, "little").hex()
                    )
                else:
                    controller_buttons = {
                        0: 0,
                        COIN: McpSession.BTN_SELECT,
                        START: McpSession.BTN_START,
                        GAMEPLAY_RIGHT_B: McpSession.BTN_RIGHT | McpSession.BTN_B,
                    }[value]
                    m.tool(
                        "set_input",
                        {"port": 0, "buttons": controller_buttons, "hold": True},
                    )
                log.emit(
                    "input",
                    stage=stage,
                    value=value,
                    tick_total=(
                        total_ticks
                        if exact_tick_total is None
                        else exact_tick_total
                    ),
                    exact_tick_boundary=exact_tick_total is not None,
                    hook_cycle=hook_cycle,
                    hook_frame=hook_frame,
                    transport=(
                        "virtual_injection_410002"
                        if args.virtual_input
                        else "nexen_port0_manual_4016"
                    ),
                    controller_buttons=controller_buttons,
                )

            def snapshot() -> dict[str, Any]:
                nonlocal last_tick16, total_ticks, minimum_saved_stack_margin
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
                stack = stack_state(gates["latch"] == 1)
                stack_margin = stack["minimum_margin"]
                if stack_margin is not None:
                    minimum_saved_stack_margin = (
                        stack_margin
                        if minimum_saved_stack_margin is None
                        else min(minimum_saved_stack_margin, stack_margin)
                    )
                frame_request = r16(0x3300, "snesMemory")
                frame_ack = r16(0x3302, "snesMemory")
                video_mirror = bytes(
                    m.read_memory(
                        "snesWorkRam", VIDEO_WRAM_OFFSET, VIDEO_WRAM_LENGTH
                    )
                )
                supervisor_loop = bytes(
                    m.read_memory(
                        "snesWorkRam",
                        SUPERVISOR_LOOP_OFFSET,
                        SUPERVISOR_LOOP_LENGTH,
                    )
                )
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
                    "frame_request": frame_request,
                    "frame_ack": frame_ack,
                    "render_complete_count": r16(0x89A2, "snesWorkRam"),
                    "render_complete_generation": r16(0x89A4, "snesWorkRam"),
                    "render_ready_sequence": r16(0x1F1E, "snesWorkRam"),
                    "renderer_busy": r16(0x899C, "snesWorkRam"),
                    "render_queue_primary_state": r16(0x89D2, "snesWorkRam"),
                    "render_queue_drops": r16(0x89D4, "snesWorkRam"),
                    "render_queue_secondary_state": r16(0x89D6, "snesWorkRam"),
                    "render_queue_code_mark": r16(0x89D8, "snesWorkRam"),
                    "render_palette_change_count": r16(0x89A8, "snesWorkRam"),
                    "render_bg_change_count": r16(0x89AA, "snesWorkRam"),
                    "render_obj_change_count": r16(0x89AC, "snesWorkRam"),
                    "render_last_obj_count": r16(0x89B2, "snesWorkRam"),
                    "render_last_obj_palette_banks": r16(0x89B4, "snesWorkRam"),
                    "render_obj_tile_slots": r16(0x89B6, "snesWorkRam"),
                    "render_bg_tile_slots": r16(0x00DC, "snesWorkRam"),
                    "frame_request_ack_lag": modular_delta(
                        frame_request, frame_ack, 16
                    ),
                    "video_mirror_sha256": hashlib.sha256(video_mirror).hexdigest(),
                    "video_mirror_matches_rom": video_mirror
                    == expected_video_mirror,
                    "video_mirror_diff_bytes": sum(
                        left != right
                        for left, right in zip(video_mirror, expected_video_mirror)
                    ),
                    "supervisor_loop_sha256": hashlib.sha256(
                        supervisor_loop
                    ).hexdigest(),
                    "supervisor_loop_matches_expected": (
                        None
                        if supervisor_loop_expected is None
                        else supervisor_loop == supervisor_loop_expected
                    ),
                    "gates": gates,
                    "production_pacing_gate": r16(0x0734),
                    "snapshot_arm": r16(0x410122, "snesMemory"),
                    "pacing_epoch": m.read_memory(
                        "snesMemory", 0x41012A, 1
                    )[0],
                    "pacing_last_release": m.read_memory(
                        "snesMemory", 0x41012B, 1
                    )[0],
                    "pacing_initialized": m.read_memory(
                        "snesMemory", 0x41012C, 1
                    )[0],
                    "pacing_supervisor_ready": m.read_memory(
                        "snesMemory", 0x41012D, 1
                    )[0],
                    "pacing_catchup_debt": m.read_memory(
                        "snesMemory", 0x410130, 1
                    )[0],
                    "input_mailbox": f"{r16(0x410000, 'snesMemory'):04x}",
                    "input_injection": f"{r16(0x410002, 'snesMemory'):04x}",
                    "input_real_cache": f"{r16(0x1F12, 'snesWorkRam'):04x}",
                    "controller_buttons": controller_buttons,
                    "stack": stack,
                    "sa1_cycles": int(cpu.get("cycleCount", 0)),
                    "sa1_pc": (int(cpu.get("k", 0)) << 16) | int(cpu.get("pc", 0)),
                    "emulator_running": bool(state.get("isRunning", False)),
                    "emulator_paused": bool(state.get("isPaused", False)),
                    "stage": stage,
                    "input": input_word,
                    "wall_elapsed": time.monotonic() - wall_start,
                }

            def run_exact_input_schedule(
                handle: int,
                start_tick_total: int,
            ) -> tuple[dict[str, Any], dict[str, Any]]:
                """Drive every production input edge from the real tick hook.

                Coherent sampling blocks are intentionally large during cold
                boot.  Once the port reaches realtime, however, a 150-video-
                frame block can overshoot an eight-tick coin pulse by dozens
                of game ticks and deadlock the game's coin path.  Keep the
                emulator running and consume the already-required $00:F5A3
                hook notifications until all six edges have fired.
                """

                nonlocal hook_ticks_total, stage, stage_tick

                schedule = [
                    (args.preinput_ticks, "coin1_hold", COIN),
                    (
                        args.preinput_ticks + args.hold_ticks,
                        "coin1_gap",
                        0,
                    ),
                    (
                        args.preinput_ticks + args.hold_ticks + args.gap_ticks,
                        "coin2_hold",
                        COIN,
                    ),
                    (
                        args.preinput_ticks
                        + 2 * args.hold_ticks
                        + args.gap_ticks,
                        "coin2_gap",
                        0,
                    ),
                    (
                        args.preinput_ticks
                        + 2 * args.hold_ticks
                        + args.gap_ticks
                        + args.prestart_gap_ticks,
                        "start_hold",
                        START,
                    ),
                    (
                        args.preinput_ticks
                        + 2 * args.hold_ticks
                        + args.gap_ticks
                        + args.prestart_gap_ticks
                        + args.start_hold_ticks,
                        "post_start",
                        0,
                    ),
                ]
                target_ticks = schedule[-1][0]
                hook_events = 0
                next_edge = 0
                started = time.monotonic()
                m.drain_notifications(timeout=0.05)
                resume_result = m.resume()
                while time.monotonic() - started < 300.0:
                    notifications = m.drain_notifications(timeout=0.01)
                    for note in notifications:
                        params = note.get("params", {})
                        if params.get("handle") != handle:
                            continue
                        if "cycleCount" not in params:
                            m.pause()
                            raise RuntimeError(
                                "tick hook lacks cycleCount; use the healthy R5 Nexen"
                            )
                        hook_events += 1
                        if next_edge >= len(schedule):
                            continue
                        target, next_stage, value = schedule[next_edge]
                        if hook_events < target:
                            continue
                        if hook_events != target:
                            m.pause()
                            raise RuntimeError(
                                "missed exact input edge: "
                                f"stage={next_stage}, target={target}, now={hook_events}"
                            )
                        stage = next_stage
                        set_input(
                            value,
                            exact_tick_total=start_tick_total + hook_events,
                            hook_cycle=int(params["cycleCount"]),
                            hook_frame=int(params.get("frame", 0)),
                        )
                        next_edge += 1
                    if next_edge == len(schedule) and hook_events >= target_ticks:
                        pause_result = m.pause()
                        break
                else:
                    m.pause()
                    raise TimeoutError(
                        "exact production input schedule did not finish within 300 seconds"
                    )

                # Calls made while the emulator was running can leave hook
                # notifications queued behind the pause response.  Count all
                # of them before validating the purpose-built IRAM counter.
                hook_events += sum(
                    1
                    for note in m.drain_notifications(timeout=0.05)
                    if note.get("params", {}).get("handle") == handle
                )
                hook_ticks_total += hook_events
                end = snapshot()
                counter_delta = total_ticks - start_tick_total
                if counter_delta != hook_events:
                    raise RuntimeError(
                        "exact input hook/counter mismatch: "
                        f"counter={counter_delta}, hooks={hook_events}"
                    )
                stage = "post_start"
                stage_tick = total_ticks
                details = {
                    "target_ticks": target_ticks,
                    "hook_events": hook_events,
                    "counter_ticks": counter_delta,
                    "post_schedule_ticks": hook_events - target_ticks,
                    "wall_seconds": time.monotonic() - started,
                    "resume_result": resume_result,
                    "pause_result": pause_result,
                }
                log.emit("exact_input_schedule_finished", **details)
                return end, details

            def run_uninterrupted_gameplay_measurement(
                start: dict[str, Any],
            ) -> tuple[dict[str, Any], dict[str, Any]]:
                """Measure settled production timing without debugger stop boundaries.

                Repeated short ``run_frames`` calls pause at an emulated frame edge.
                Nexen can therefore defer the NMI-owned wake until the following
                resume, producing a harness-induced lost pacing deadline.  Keep one
                unpaused window live for the complete measurement while retaining
                both exact tick and true-render completion hook stamps.
                """

                nonlocal renderer_ack_advances

                tick_handle = m.add_exec_hook(0x00F5A3, cpu_type="Sa1")
                render_handle = m.add_exec_hook(
                    RENDER_COMPLETE_HOOK, cpu_type="Snes"
                )
                request_write_handle = m.add_write_hook(
                    0x3300, 0x3301, cpu_type="Sa1"
                )
                ack_write_handle = m.add_write_hook(
                    0x3302, 0x3303, cpu_type="Snes"
                )
                handles = {
                    tick_handle: "tick",
                    render_handle: "render_complete",
                    request_write_handle: "frame_request_write",
                    ack_write_handle: "frame_ack_write",
                }
                m.drain_notifications(timeout=0.05)
                started = time.monotonic()
                notifications: list[dict[str, Any]] = []
                run_result: dict[str, Any]
                try:
                    # Nexen's run_frames safety cap assumes the emulator sustains
                    # at least 30 host frames/s.  Two retained cycle-stamped hooks
                    # make this oracle run slower than that, so a long, healthy
                    # window can be cut short and mislabeled timedOut.  Resume once
                    # and poll the moving frame counter without pausing; only the
                    # final pause is an emulation boundary.
                    requested_frames = args.uninterrupted_gameplay_frames
                    initial_state = m.get_state()
                    start_frame = int(initial_state["frameCount"])
                    m.resume()
                    deadline = time.monotonic() + max(
                        300.0, requested_frames / 5.0
                    )
                    last_frame = start_frame
                    last_progress = time.monotonic()
                    timed_out = False
                    while True:
                        moving_state = m.get_state()
                        current_frame = int(moving_state["frameCount"])
                        frames_advanced = (
                            current_frame - start_frame
                        ) & 0xFFFFFFFF
                        if frames_advanced >= requested_frames:
                            break
                        now = time.monotonic()
                        if current_frame != last_frame:
                            last_frame = current_frame
                            last_progress = now
                        elif now - last_progress >= 60.0:
                            timed_out = True
                            break
                        if now >= deadline:
                            timed_out = True
                            break
                        time.sleep(0.25)
                    m.pause()
                    final_run_state = m.get_state()
                    end_frame = int(final_run_state["frameCount"])
                    frames_advanced = (end_frame - start_frame) & 0xFFFFFFFF
                    run_result = {
                        "requested": requested_frames,
                        "startFrame": start_frame,
                        "endFrame": end_frame,
                        "framesAdvanced": frames_advanced,
                        "isPaused": bool(final_run_state.get("isPaused", False)),
                        "timedOut": timed_out,
                        "driver": "single_resume_nonpausing_frame_poll",
                    }
                    notifications = m.drain_notifications(timeout=0.5)
                    for _ in range(4):
                        more = m.drain_notifications(timeout=0.05)
                        if not more:
                            break
                        notifications.extend(more)
                finally:
                    # Keep subsequent multi-read state coherent even if the
                    # measurement driver raises before reaching its target.
                    m.pause()
                    tick_removed = m.remove_hook(tick_handle)
                    render_removed = m.remove_hook(render_handle)
                    request_write_removed = m.remove_hook(request_write_handle)
                    ack_write_removed = m.remove_hook(ack_write_handle)
                wall_seconds = time.monotonic() - started

                hook_rows: list[dict[str, Any]] = []
                for notification in notifications:
                    if notification.get("method") != "notifications/mesen/hookFired":
                        continue
                    params = notification.get("params", {})
                    handle = int(params.get("handle", -1))
                    label = handles.get(handle)
                    if label is None:
                        continue
                    if "cycleCount" not in params:
                        raise RuntimeError(
                            f"{label} hook lacks cycleCount; use the healthy R5 Nexen"
                        )
                    hook_rows.append(
                        {
                            "label": label,
                            "handle": handle,
                            "address": int(params.get("address", 0)),
                            "cycle_count": int(params["cycleCount"]),
                            "frame": int(params.get("frame", 0)),
                            "cpu_type": params.get("cpuType"),
                            "kind": params.get("kind"),
                            "value": (
                                None
                                if "value" not in params
                                else int(params["value"])
                            ),
                        }
                    )

                hook_path = args.output / "uninterrupted_gameplay_hooks.jsonl"
                hook_path.write_text(
                    "".join(
                        json.dumps(row, sort_keys=True) + "\n" for row in hook_rows
                    ),
                    encoding="utf-8",
                )
                end = snapshot()
                frame_delta = end["frame"] - start["frame"]
                tick_delta = end["tick_total"] - start["tick_total"]
                request_delta = frame_counter_delta(
                    end["frame_request"], start["frame_request"]
                )
                ack_delta = frame_counter_delta(
                    end["frame_ack"], start["frame_ack"]
                )
                render_counter_delta = frame_counter_delta(
                    end["render_complete_count"], start["render_complete_count"]
                )
                start_renderer_debt = frame_counter_delta(
                    start["frame_request"], start["frame_ack"]
                )
                end_renderer_debt = frame_counter_delta(
                    end["frame_request"], end["frame_ack"]
                )
                sa1_cycle_delta = modular_delta(
                    end["sa1_cycles"], start["sa1_cycles"], 64
                )
                tick_hook_count = sum(
                    row["label"] == "tick" for row in hook_rows
                )
                render_hook_count = sum(
                    row["label"] == "render_complete" for row in hook_rows
                )

                # Reconstruct both 16-bit doorbell words from the uninterrupted
                # write stream.  The SA-1's 16-bit INC writes high then low, so
                # $3300 completes a request transaction.  The 5A22's 16-bit STA
                # writes low then high, so $3303 completes an acknowledgement.
                # Sampling only the final pause is phase-sensitive because ACK
                # is claimed before a multi-frame render.  Retain every ACK
                # transaction so a skipped sequence cannot masquerade as
                # conservation merely because the final words are equal.
                request_bytes = bytearray(
                    int(start["frame_request"]).to_bytes(2, "little")
                )
                ack_bytes = bytearray(
                    int(start["frame_ack"]).to_bytes(2, "little")
                )
                request_transactions = 0
                ack_transactions = 0
                max_renderer_debt = start_renderer_debt
                max_ack_silence_frames = 0
                last_ack_frame = int(start["frame"])
                previous_ack_word = int(start["frame_ack"])
                nonunit_ack_steps: list[dict[str, int]] = []
                renderer_debt_samples: list[dict[str, int | str]] = []
                for row in hook_rows:
                    label = row["label"]
                    address = int(row["address"])
                    value = row.get("value")
                    if value is None:
                        continue
                    transaction_complete = False
                    if label == "frame_request_write" and 0x3300 <= address <= 0x3301:
                        request_bytes[address - 0x3300] = int(value) & 0xFF
                        if address == 0x3300:
                            request_transactions += 1
                            transaction_complete = True
                    elif label == "frame_ack_write" and 0x3302 <= address <= 0x3303:
                        ack_bytes[address - 0x3302] = int(value) & 0xFF
                        if address == 0x3303:
                            ack_transactions += 1
                            transaction_complete = True
                            ack_frame = int(row["frame"])
                            max_ack_silence_frames = max(
                                max_ack_silence_frames,
                                ack_frame - last_ack_frame,
                            )
                            last_ack_frame = ack_frame
                    if not transaction_complete:
                        continue
                    request_word = int.from_bytes(request_bytes, "little")
                    ack_word = int.from_bytes(ack_bytes, "little")
                    if label == "frame_ack_write":
                        ack_step = frame_counter_delta(ack_word, previous_ack_word)
                        if ack_step != 1:
                            nonunit_ack_steps.append(
                                {
                                    "frame": int(row["frame"]),
                                    "before": previous_ack_word,
                                    "after": ack_word,
                                    "delta": ack_step,
                                }
                            )
                        previous_ack_word = ack_word
                    debt = frame_counter_delta(request_word, ack_word)
                    max_renderer_debt = max(max_renderer_debt, debt)
                    renderer_debt_samples.append(
                        {
                            "event": label,
                            "frame": int(row["frame"]),
                            "request": request_word,
                            "ack": ack_word,
                            "debt": debt,
                        }
                    )
                max_ack_silence_frames = max(
                    max_ack_silence_frames,
                    int(end["frame"]) - last_ack_frame,
                )
                traced_request = int.from_bytes(request_bytes, "little")
                traced_ack = int.from_bytes(ack_bytes, "little")
                debt_trace_path = args.output / "renderer_debt_trace.jsonl"
                debt_trace_path.write_text(
                    "".join(
                        json.dumps(row, sort_keys=True) + "\n"
                        for row in renderer_debt_samples
                    ),
                    encoding="utf-8",
                )
                renderer_ack_advances += ack_delta
                expected_gates = {
                    "loop": 1,
                    "escape": 1,
                    "choke": 1,
                    "swin": 0xA55A,
                    "select": 0x5EEC,
                    "latch": 1,
                }
                checks = {
                    "hooks_removed": (
                        tick_removed
                        and render_removed
                        and request_write_removed
                        and ack_write_removed
                    ),
                    "frame_span_target_reached": (
                        frame_delta >= args.uninterrupted_gameplay_frames
                        and int(run_result.get("framesAdvanced", -1)) == frame_delta
                        and bool(run_result.get("isPaused", False))
                        and not bool(run_result.get("timedOut", True))
                    ),
                    "tick_hook_matches_counter": tick_hook_count == tick_delta,
                    "render_hook_matches_counter": (
                        render_hook_count == render_counter_delta
                    ),
                    "thirty_game_hz_or_better": (
                        frame_delta > 0 and tick_delta * 2 >= frame_delta
                    ),
                    "representative_cycle_budget": (
                        tick_delta > 0
                        and sa1_cycle_delta / tick_delta <= 358_000
                    ),
                    "known_ordering_event_survived": end["tick_total"] >= 800,
                    "sustained_ordering_window": tick_delta >= 530,
                    "frame_request_per_tick": request_delta == tick_delta,
                    "frame_ack_conservation": (
                        ack_delta
                        == request_delta + start_renderer_debt - end_renderer_debt
                    ),
                    "renderer_debt_trace_complete": (
                        request_transactions == request_delta
                        and traced_request == end["frame_request"]
                        and traced_ack == end["frame_ack"]
                    ),
                    # Every retained image must be acknowledged as its own
                    # transaction.  A final ACK word can otherwise hide a jump
                    # over one or more overwritten direct snapshots.
                    "renderer_ack_sequence_unit_steps": (
                        ack_transactions == ack_delta
                        and not nonunit_ack_steps
                    ),
                    # ACK is written before the real draw.  One completion can
                    # straddle either endpoint, but sustained ACK/render drift
                    # is not allowed.
                    "render_completion_conservation": (
                        abs(render_hook_count - ack_transactions) <= 1
                    ),
                    # Request writes precede queue capture.  The two-entry
                    # architecture can transiently show debt three; a real
                    # overflow is recorded separately and must remain zero.
                    "renderer_debt_bounded": (
                        max_renderer_debt <= RENDER_TRANSACTION_DEBT_MAX
                    ),
                    "render_queue_no_overflow": (
                        start["render_queue_drops"] == 0
                        and end["render_queue_drops"] == 0
                    ),
                    "render_queue_state_valid": all(
                        state in (0, 1, 2)
                        for state in (
                            start["render_queue_primary_state"],
                            start["render_queue_secondary_state"],
                            end["render_queue_primary_state"],
                            end["render_queue_secondary_state"],
                        )
                    ) and all(
                        busy in (0, 1)
                        for busy in (start["renderer_busy"], end["renderer_busy"])
                    ) and all(
                        mark in (0, 0xC0DE)
                        for mark in (
                            start["render_queue_code_mark"],
                            end["render_queue_code_mark"],
                        )
                    ),
                    "true_render_progress": render_hook_count > 0,
                    "interpreter_not_halted": end["halt"] == 0,
                    "production_gates_intact": end["gates"] == expected_gates,
                    "production_pacing_intact": (
                        end["production_pacing_gate"] == 1
                        and end["pacing_initialized"] == 0xA5
                        and end["pacing_supervisor_ready"] == 0x5A
                    ),
                    "pacing_catchup_debt_bounded": (
                        start["pacing_catchup_debt"]
                        <= PACING_CATCHUP_DEBT_MAX
                        and end["pacing_catchup_debt"]
                        <= PACING_CATCHUP_DEBT_MAX
                    ),
                    "real_right_b_reached_mailbox": (
                        not args.gameplay_right_b
                        or (
                            end["input_real_cache"] == "8100"
                            and end["input_mailbox"] == "8100"
                            and end["input_injection"] == "0000"
                        )
                    ),
                    "task_stacks_above_floors": (
                        not start["stack"]["below_floor"]
                        and not end["stack"]["below_floor"]
                        and end["stack"]["initialized"] == 16
                    ),
                    "video_mirror_exact": end["video_mirror_matches_rom"],
                    "supervisor_loop_exact": (
                        end["supervisor_loop_matches_expected"] is True
                    ),
                    "sound_ring_valid": (
                        0x00F01C20 <= int(start["sound_ring_ptr"], 16) <= 0x00F01C3F
                        and 0x00F01C20
                        <= int(end["sound_ring_ptr"], 16)
                        <= 0x00F01C3F
                    ),
                }
                details = {
                    "scope": (
                        "same-run production cold-boot settled gameplay; one "
                        "unpaused emulated-frame window with non-pausing frame polls"
                    ),
                    "frames": frame_delta,
                    "game_ticks": tick_delta,
                    "game_fps": (
                        tick_delta * 60.0 / frame_delta if frame_delta > 0 else 0.0
                    ),
                    "sa1_cycles": sa1_cycle_delta,
                    "mean_sa1_cycles_per_tick": (
                        sa1_cycle_delta / tick_delta if tick_delta else None
                    ),
                    "wall_seconds": wall_seconds,
                    "host_video_fps": frame_delta / max(1e-9, wall_seconds),
                    "frame_requests": request_delta,
                    "frame_acks": ack_delta,
                    "initial_renderer_debt": start_renderer_debt,
                    "final_renderer_debt": end_renderer_debt,
                    "max_renderer_debt": max_renderer_debt,
                    "max_ack_silence_frames": max_ack_silence_frames,
                    "request_write_transactions": request_transactions,
                    "ack_write_transactions": ack_transactions,
                    "nonunit_ack_steps": nonunit_ack_steps,
                    "renderer_transaction_debt_limit": (
                        RENDER_TRANSACTION_DEBT_MAX
                    ),
                    "renderer_debt_trace": {
                        "path": str(debt_trace_path),
                        "sha256": sha256(debt_trace_path),
                    },
                    "true_render_completions": render_hook_count,
                    "render_complete_counter": render_counter_delta,
                    "tick_hook_events": tick_hook_count,
                    "run_result": run_result,
                    "hooks": {
                        "path": str(hook_path),
                        "sha256": sha256(hook_path),
                    },
                    "checks": checks,
                    "validated": all(checks.values()),
                    "start": start,
                    "end": end,
                }
                log.emit("uninterrupted_gameplay_measurement", **details)
                return end, details

            set_input(0)
            first = snapshot()
            if not args.virtual_input and first["input_injection"] != "0000":
                raise RuntimeError(
                    "production ROM did not leave the virtual injection word idle: "
                    f"{first['input_injection']}"
                )
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
                ticks_before_run = total_ticks
                run_wall = time.monotonic()
                if args.wall_chunk_seconds > 0:
                    remaining_candidates: list[int] = [args.max_sample_ticks]
                    if tick_hook is not None and hook_counter_start_total is not None:
                        remaining_candidates.append(
                            args.hook_validation_ticks
                            - (total_ticks - hook_counter_start_total)
                        )
                    stage_limits = {
                        "preinput": args.preinput_ticks,
                        "coin1_hold": args.hold_ticks,
                        "coin1_gap": args.gap_ticks,
                        "coin2_hold": args.hold_ticks,
                        "coin2_gap": args.prestart_gap_ticks,
                        "start_hold": args.start_hold_ticks,
                        "gameplay_settle": args.settle_ticks,
                    }
                    if stage in stage_limits:
                        remaining_candidates.append(
                            stage_limits[stage] - (total_ticks - stage_tick)
                        )
                    positive_remaining = [
                        remaining for remaining in remaining_candidates if remaining > 0
                    ]
                    ticks_to_boundary = (
                        min(positive_remaining) if positive_remaining else None
                    )
                    run_target_seconds = adaptive_wall_chunk_seconds(
                        args.wall_chunk_seconds,
                        observed_ticks_per_second,
                        ticks_to_boundary,
                    )
                    resume_result = m.resume()
                    time.sleep(run_target_seconds)
                    pause_result = m.pause()
                    run_result = {
                        "mode": "wall_time",
                        "targetSeconds": run_target_seconds,
                        "resume": resume_result,
                        "pause": pause_result,
                    }
                else:
                    run_result = m.run_frames(args.chunk)
                run_seconds = time.monotonic() - run_wall
                pause_ok = (
                    bool(run_result["pause"].get("paused", False))
                    if args.wall_chunk_seconds > 0
                    else bool(run_result.get("isPaused", False))
                )
                if not pause_ok:
                    raise RuntimeError(f"emulator did not pause coherently: {run_result}")
                notifications = m.drain_notifications(timeout=0.05)
                if tick_hook is not None:
                    hook_ticks_total += sum(
                        1
                        for note in notifications
                        if note.get("params", {}).get("handle") == tick_hook
                    )
                snap = snapshot()
                tick_delta = total_ticks - ticks_before_run
                if tick_delta > 0 and run_seconds > 0:
                    observed_ticks_per_second = tick_delta / run_seconds
                frame_delta = snap["frame"] - last_frame
                last_frame = snap["frame"]
                stagnant_chunks = stagnant_chunks + 1 if frame_delta <= 0 else 0
                snap["run_mode"] = run_result.get("mode", "run_frames")
                if args.wall_chunk_seconds <= 0:
                    snap["run_frames_requested"] = args.chunk
                snap["run_frame_delta"] = frame_delta
                snap["run_tick_delta"] = tick_delta
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
                    and snap["production_pacing_gate"] == 1
                    and snap["pacing_initialized"] == 0xA5
                    and snap["pacing_supervisor_ready"] == 0x5A
                )
                if armed_tick_total is None and armed:
                    if not snap["video_mirror_matches_rom"]:
                        result = "video_mirror_corrupt_at_arm"
                        copy_screenshot(m, result)
                        break
                    supervisor_loop_expected = bytes(
                        m.read_memory(
                            "snesWorkRam",
                            SUPERVISOR_LOOP_OFFSET,
                            SUPERVISOR_LOOP_LENGTH,
                        )
                    )
                    loop_matches = [
                        offset
                        for offset in range(
                            0,
                            VIDEO_WRAM_LENGTH - SUPERVISOR_LOOP_LENGTH + 1,
                        )
                        if expected_video_mirror[
                            offset : offset + SUPERVISOR_LOOP_LENGTH
                        ]
                        == supervisor_loop_expected
                    ]
                    if len(loop_matches) != 1:
                        result = "supervisor_loop_not_unique_in_rom"
                        log.emit(
                            result,
                            matches=loop_matches,
                            supervisor_loop_sha256=hashlib.sha256(
                                supervisor_loop_expected
                            ).hexdigest(),
                        )
                        copy_screenshot(m, result)
                        break
                    supervisor_loop_rom_offset = loop_matches[0]
                    snap["supervisor_loop_matches_expected"] = True
                    snap["supervisor_loop_rom_offset"] = supervisor_loop_rom_offset
                    armed_tick_total = total_ticks
                    armed_snapshot = dict(snap)
                    last_renderer_ack = snap["frame_ack"]
                    last_renderer_request = snap["frame_request"]
                    stage_tick = total_ticks
                    stage = "preinput"
                    log.emit("accelerators_armed", **snap)
                    copy_screenshot(m, "armed")
                    save_checkpoint(m, "armed")
                    tick_hook = m.add_exec_hook(0x00F5A3, cpu_type="Sa1")
                    hook_counter_start_total = total_ticks
                    log.emit(
                        "hook_validation_started",
                        handle=tick_hook,
                        tick_total=total_ticks,
                        target_ticks=args.hook_validation_ticks,
                    )
                    schedule_start_frame = snap["frame"]
                    schedule_start_wall = time.monotonic()
                    snap, exact_schedule = run_exact_input_schedule(
                        tick_hook,
                        armed_tick_total,
                    )
                    hook_counter_end_total = total_ticks
                    hook_validation_match = (
                        exact_schedule["counter_ticks"]
                        == exact_schedule["hook_events"]
                    )
                    removed = m.remove_hook(tick_hook)
                    log.emit(
                        "hook_validation_finished",
                        counter_ticks=exact_schedule["counter_ticks"],
                        hook_events=exact_schedule["hook_events"],
                        match=hook_validation_match,
                        removed=removed,
                        target_ticks=args.hook_validation_ticks,
                    )
                    tick_hook = None
                    if not removed:
                        hook_validation_match = False
                        result = "hook_remove_failed"
                        copy_screenshot(m, "hook_remove_failed")
                        break
                    tick_delta = exact_schedule["counter_ticks"]
                    frame_delta = snap["frame"] - schedule_start_frame
                    last_frame = snap["frame"]
                    schedule_seconds = time.monotonic() - schedule_start_wall
                    if tick_delta > 0 and schedule_seconds > 0:
                        observed_ticks_per_second = tick_delta / schedule_seconds
                    snap["run_mode"] = "exact_tick_hook_input_schedule"
                    snap["run_frame_delta"] = frame_delta
                    snap["run_tick_delta"] = tick_delta
                    snap["run_wall_seconds"] = schedule_seconds
                    snap["run_result"] = exact_schedule
                    log.emit("sample", **snap)

                if armed_tick_total is not None and total_ticks > armed_tick_total:
                    if not snap["video_mirror_matches_rom"]:
                        result = "video_mirror_corruption"
                        copy_screenshot(m, result)
                        break
                    if snap["supervisor_loop_matches_expected"] is not True:
                        result = "supervisor_loop_corruption"
                        copy_screenshot(m, result)
                        break
                    if (
                        last_renderer_ack is not None
                        and last_renderer_request is not None
                    ):
                        ack_delta = frame_counter_delta(
                            snap["frame_ack"], last_renderer_ack
                        )
                        if ack_delta:
                            renderer_ack_advances += ack_delta
                            renderer_stagnant_samples = 0
                            renderer_pending_since_frame = None
                        elif snap["frame_request"] != snap["frame_ack"] and tick_delta > 0:
                            renderer_stagnant_samples += 1
                            if renderer_pending_since_frame is None:
                                renderer_pending_since_frame = snap["frame"]
                        else:
                            renderer_stagnant_samples = 0
                            renderer_pending_since_frame = None
                        if (
                            renderer_pending_since_frame is not None
                            and snap["frame"] - renderer_pending_since_frame >= 600
                        ):
                            result = "renderer_ack_stalled"
                            copy_screenshot(m, result)
                            break
                    last_renderer_ack = snap["frame_ack"]
                    last_renderer_request = snap["frame_request"]

                if tick_hook is not None and hook_counter_start_total is not None:
                    hook_counter_ticks = total_ticks - hook_counter_start_total
                    if hook_counter_ticks >= args.hook_validation_ticks:
                        hook_counter_end_total = total_ticks
                        hook_validation_match = hook_counter_ticks == hook_ticks_total
                        removed = m.remove_hook(tick_hook)
                        log.emit(
                            "hook_validation_finished",
                            counter_ticks=hook_counter_ticks,
                            hook_events=hook_ticks_total,
                            match=hook_validation_match,
                            removed=removed,
                            target_ticks=args.hook_validation_ticks,
                        )
                        tick_hook = None
                        if not removed:
                            hook_validation_match = False
                            result = "hook_remove_failed"
                            copy_screenshot(m, "hook_remove_failed")
                            break
                        if not hook_validation_match:
                            result = "counter_hook_mismatch"
                            copy_screenshot(m, "counter_hook_mismatch")
                            break

                relative = total_ticks - stage_tick
                if stage == "preinput" and relative >= args.preinput_ticks:
                    stage = "coin1_hold"
                    stage_tick = total_ticks
                    set_input(COIN)
                elif stage == "coin1_hold" and relative >= args.hold_ticks:
                    stage = "coin1_gap"
                    stage_tick = total_ticks
                    set_input(0)
                elif stage == "coin1_gap" and relative >= args.gap_ticks:
                    stage = "coin2_hold"
                    stage_tick = total_ticks
                    set_input(COIN)
                elif stage == "coin2_hold" and relative >= args.hold_ticks:
                    stage = "coin2_gap"
                    stage_tick = total_ticks
                    set_input(0)
                elif (
                    stage == "coin2_gap"
                    and relative >= args.prestart_gap_ticks
                ):
                    stage = "start_hold"
                    stage_tick = total_ticks
                    set_input(START)
                elif stage == "start_hold" and relative >= args.start_hold_ticks:
                    stage = "post_start"
                    stage_tick = total_ticks
                    set_input(0)

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
                    gameplay_snapshot = dict(snap)
                    stage = "gameplay_settle"
                    stage_tick = total_ticks
                    log.emit("gameplay_detected", **snap)
                    copy_screenshot(m, "gameplay_detected")
                    save_checkpoint(m, "gameplay_detected")
                    if args.gameplay_right_b:
                        set_input(GAMEPLAY_RIGHT_B)

                if (
                    stage == "gameplay_settle"
                    and total_ticks - stage_tick >= args.settle_ticks
                ):
                    if args.uninterrupted_gameplay_frames:
                        measurement_start = dict(snap)
                        log.emit(
                            "gameplay_settle_finished",
                            settle_ticks=total_ticks - stage_tick,
                            target_settle_ticks=args.settle_ticks,
                            **measurement_start,
                        )
                        snap, uninterrupted_gameplay_measurement = (
                            run_uninterrupted_gameplay_measurement(
                                measurement_start
                            )
                        )
                        last_frame = snap["frame"]
                        if uninterrupted_gameplay_measurement["validated"]:
                            result = "gameplay_settled"
                            copy_screenshot(m, "gameplay_settled")
                        else:
                            result = "uninterrupted_gameplay_measurement_failed"
                            copy_screenshot(m, result)
                    else:
                        result = "gameplay_settled"
                        copy_screenshot(m, "gameplay_settled")
                    break

                if snap["halt"] != 0:
                    result = f"halt_{snap['halt']:04x}"
                    copy_screenshot(m, "halt")
                    break
                if snap["stack"]["below_floor"]:
                    result = "stack_floor_violation"
                    copy_screenshot(m, "stack_floor_violation")
                    break

            final = snapshot()
            if result == "gameplay_settled":
                if renderer_ack_advances == 0:
                    result = "renderer_ack_not_observed"
                elif not final["video_mirror_matches_rom"]:
                    result = "video_mirror_corruption"
                elif final["supervisor_loop_matches_expected"] is not True:
                    result = "supervisor_loop_corruption"
            save_checkpoint(m, "final")
            ppu = m.get_ppu_state()
            cgram = bytes(m.read_memory("snesCgRam", 0, 512))
            oam = bytes(m.read_memory("snesSpriteRam", 0, 0x220))
            vram = bytes(m.read_memory("snesVideoRam", 0, 0x10000))
            bg_codes = bytes(m.read_memory("snesMemory", 0x414800, 0x400))
            bg_colors = bytes(m.read_memory("snesMemory", 0x414C00, 0x400))
            video_mirror = bytes(
                m.read_memory("snesWorkRam", VIDEO_WRAM_OFFSET, VIDEO_WRAM_LENGTH)
            )
            supervisor_loop = bytes(
                m.read_memory(
                    "snesWorkRam", SUPERVISOR_LOOP_OFFSET, SUPERVISOR_LOOP_LENGTH
                )
            )
            for name, data in (
                ("cgram.bin", cgram),
                ("oam.bin", oam),
                ("vram.bin", vram),
                ("bg_codes.bin", bg_codes),
                ("bg_colors.bin", bg_colors),
                ("video_mirror.bin", video_mirror),
                ("supervisor_loop.bin", supervisor_loop),
            ):
                (args.output / name).write_bytes(data)
            assert first_snapshot is not None
            video_delta = final["frame"] - first_snapshot["frame"]
            wall_delta = max(1e-9, final["wall_elapsed"] - first_snapshot["wall_elapsed"])
            game_fps = (total_ticks * 60.0 / video_delta) if video_delta > 0 else 0.0
            host_video_fps = video_delta / wall_delta
            post_arm = None
            boot_to_arm = None
            gameplay_phase = None
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
            if gameplay_snapshot is not None:
                gameplay_video = final["frame"] - gameplay_snapshot["frame"]
                gameplay_ticks = total_ticks - gameplay_snapshot["tick_total"]
                gameplay_wall = max(
                    1e-9,
                    final["wall_elapsed"] - gameplay_snapshot["wall_elapsed"],
                )
                gameplay_phase = {
                    "control": (
                        "right+b_held" if args.gameplay_right_b else "idle"
                    ),
                    "video_frames": gameplay_video,
                    "game_ticks": gameplay_ticks,
                    "game_fps": (
                        gameplay_ticks * 60.0 / gameplay_video
                        if gameplay_video > 0
                        else 0.0
                    ),
                    "sa1_cycles": modular_delta(
                        final["sa1_cycles"], gameplay_snapshot["sa1_cycles"], 64
                    ),
                    "host_video_fps": gameplay_video / gameplay_wall,
                    "wall_seconds": gameplay_wall,
                }
            hook_counter_stop = (
                hook_counter_end_total
                if hook_counter_end_total is not None
                else total_ticks
            )
            hook_counter_ticks = (
                hook_counter_stop - hook_counter_start_total
                if hook_counter_start_total is not None
                else 0
            )
            counter_hook_match = hook_validation_match is True
            counter_hook_validated = (
                counter_hook_match
                and hook_counter_ticks >= args.hook_validation_ticks
            )
            measured_game_fps = None
            if (
                uninterrupted_gameplay_measurement is not None
                and uninterrupted_gameplay_measurement["validated"]
                and counter_hook_validated
            ):
                measured_game_fps = uninterrupted_gameplay_measurement["game_fps"]
            elif post_arm is not None and counter_hook_validated:
                measured_game_fps = post_arm["game_fps"]
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
                measured_hook_counter_ticks=hook_counter_ticks,
                minimum_saved_stack_margin=minimum_saved_stack_margin,
                renderer_ack_advances=renderer_ack_advances,
                renderer_stagnant_samples=renderer_stagnant_samples,
                supervisor_loop_rom_offset=supervisor_loop_rom_offset,
                hook_validation_target=args.hook_validation_ticks,
                counter_hook_match=counter_hook_match,
                counter_hook_validated=counter_hook_validated,
                overall_observed_tick_rate=game_fps,
                emulated_game_fps=measured_game_fps,
                host_video_fps=host_video_fps,
                power_on_video_frames=final["frame"],
                power_on_wall_seconds=final["wall_elapsed"],
                power_on_host_video_fps=(
                    final["frame"] / max(1e-9, final["wall_elapsed"])
                ),
                startup_frames_before_first_sample=first_snapshot["frame"],
                boot_to_arm=boot_to_arm,
                post_arm=post_arm,
                gameplay_phase=gameplay_phase,
                uninterrupted_gameplay_measurement=(
                    uninterrupted_gameplay_measurement
                ),
                **final,
            )
            if not any(args.output.glob("*.png")):
                copy_screenshot(m, "final")
    finally:
        log.close()

    return 0 if result == "gameplay_settled" else 2


if __name__ == "__main__":
    sys.exit(main())
