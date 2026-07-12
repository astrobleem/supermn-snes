#!/usr/bin/env python3
"""Continuously attribute production game-tick cycles with Nexen exec hooks.

The older profilers repeatedly stopped at individual hooks.  Those stops changed
the host timing, interacted with Nexen's global run-until counter, and omitted
the long $0818 wait between the active game work and the next vblank.  This
harness instead installs all phase hooks at once and lets the emulator run.  A
small Nexen MCP extension stamps every notification with the source SA-1 CPU's
exact ``cycleCount``, so host delivery latency cannot change the deltas.

With no ``--state``, the harness cold-boots an unmodified production ROM, saves
a checkpoint when all production gates latch, then loads that checkpoint into
the profiling Nexen.  The default uses the same Nexen build on both sides;
legacy Mesen checkpoints do not preserve this fork's SA-1 IRAM state across a
cross-load and are therefore rejected by the gate check.  All reported cycles
come from one uninterrupted Nexen interval after the load.  ``--drive-gameplay``
uses the documented coin/start mailbox without hooks, saves a settled same-ROM
gameplay checkpoint, and profiles that state instead of the initial attract mode.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import statistics
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, "/home/chad/Mesen2/python")

import mesen_mcp.session as _session

_session.validate_mesen_build = lambda *_args, **_kwargs: None
from mesen_mcp import McpSession


DEFAULT_ROM = ROOT / "build/interp.sfc"
DEFAULT_NEXEN = Path(
    "/mnt/sdc1/Nexen-r5-20260712/"
    "bin/linux-x64/Release/linux-x64/publish/Nexen"
)
DEFAULT_BOOTSTRAP = DEFAULT_NEXEN
DEFAULT_OUTPUT = ROOT / "build/recovery-20260712/r5-continuous-profile"

CLAMP = 0x00F5A3
TAKE_IRQ = 0x00B404
ENTRY_3A92 = 0x92DC3B
IDLE_ENTRY_LAB = 0x00F597
IDLE_VSYNC_LAB_MARKER_OFFSET = 0x2CFF00
IDLE_VSYNC_LAB_MARKERS = (b"R5VSYNC1", b"R5VNMI01")
EXPECTED_GATES = {
    "loop": 1,
    "escape": 1,
    "choke": 1,
    "swin": 0xA55A,
    "select": 0x5EEC,
    "latch": 1,
}
GATE_ADDRS = {
    "loop": 0x072E,
    "escape": 0x071A,
    "choke": 0x073A,
    "swin": 0x073C,
    "select": 0x0736,
    "latch": 0x0768,
}
CANONICAL_POST_ARM_CYCLES_PER_TICK = 8_099_238
COIN = 0x2000
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


def git_value(repo: Path, *args: str) -> str:
    try:
        return subprocess.check_output(
            ["git", *args], cwd=repo, text=True, stderr=subprocess.DEVNULL
        ).strip()
    except Exception:
        return "unknown"


def repo_for(path: Path) -> Path | None:
    for parent in (path, *path.parents):
        if (parent / ".git").exists():
            return parent
    return None


def wait_for_stable_file(path: Path, timeout: float = 10.0) -> None:
    """Wait for Nexen's asynchronous save-state write to finish."""
    deadline = time.monotonic() + timeout
    previous_size = -1
    stable_samples = 0
    while time.monotonic() < deadline:
        size = path.stat().st_size if path.exists() else 0
        if size > 0 and size == previous_size:
            stable_samples += 1
            if stable_samples >= 3:
                return
        else:
            stable_samples = 0
        previous_size = size
        time.sleep(0.1)
    raise TimeoutError(f"save state did not finish writing: {path}")


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
    parser.add_argument(
        "--bootstrap-emulator",
        type=Path,
        default=DEFAULT_BOOTSTRAP,
        help="Cold-boot emulator used only to create a production checkpoint.",
    )
    parser.add_argument(
        "--state",
        type=Path,
        help="Existing production checkpoint; skips the bootstrap cold boot.",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--port", type=int, default=7476)
    parser.add_argument("--bootstrap-port", type=int, default=7477)
    parser.add_argument(
        "--intervals",
        type=int,
        default=16,
        help="Number of complete clamp-to-clamp intervals to collect.",
    )
    parser.add_argument("--arm-timeout", type=float, default=2100.0)
    parser.add_argument("--profile-timeout", type=float, default=300.0)
    parser.add_argument("--poll-seconds", type=float, default=0.25)
    parser.add_argument(
        "--idle-vsync-lab",
        action="store_true",
        help="Require the marked lab ROM and set its explicit IRAM $0734 experiment gate.",
    )
    parser.add_argument(
        "--drive-gameplay",
        action="store_true",
        help="Drive coin/start from the arm checkpoint and profile a settled gameplay state.",
    )
    parser.add_argument(
        "--gameplay-settle-ticks",
        type=int,
        default=60,
        help="Ticks to run after gameplay task-mask detection before profiling.",
    )
    parser.add_argument("--drive-chunk-frames", type=int, default=300)
    return parser.parse_args()


def configure_dotnet(executable: Path) -> None:
    is_nexen = executable.name == "Nexen"
    root = "/home/chad/.dotnet10" if is_nexen else "/home/chad/.dotnet8"
    other = "/home/chad/.dotnet8" if is_nexen else "/home/chad/.dotnet10"
    os.environ["DOTNET_ROOT"] = root
    current = [
        item
        for item in os.environ.get("PATH", "").split(":")
        if item and item not in (root, other)
    ]
    os.environ["PATH"] = ":".join([root, other, *current])


def hook_events(rows: Iterable[dict[str, Any]], handle: int | None = None) -> list[dict]:
    events = []
    for row in rows:
        if row.get("method") != "notifications/mesen/hookFired":
            continue
        params = row.get("params", {})
        if handle is None or params.get("handle") == handle:
            events.append(params)
    return events


def wait_for_production_gates(
    m: McpSession,
    timeout: float,
    poll_seconds: float,
    log: Recorder,
) -> dict[str, Any]:
    start = time.monotonic()
    last_heartbeat = start
    m.resume()
    while time.monotonic() - start < timeout:
        # $072E is written once when snd_vframe arms the production accelerators
        # and remains latched.  Polling this one word avoids the substantial
        # all-instruction debugger-hook overhead during the 5K-frame cold boot.
        if le16(m.read_memory("Sa1Memory", GATE_ADDRS["loop"], 2)) == 1:
            m.pause()
            state = snapshot(m)
            if state["gates"] == EXPECTED_GATES:
                return state
            m.resume()
        now = time.monotonic()
        if now - last_heartbeat >= 30.0:
            state = m.get_state()
            log.emit(
                "heartbeat",
                phase="bootstrap_to_production_gates",
                wall_seconds=now - start,
                frame=state.get("frameCount"),
                is_running=state.get("isRunning"),
                is_paused=state.get("isPaused"),
            )
            last_heartbeat = now
        time.sleep(max(2.0, poll_seconds))
    m.pause()
    raise TimeoutError(f"production gates timed out after {timeout:.1f} seconds")


def snapshot(m: McpSession) -> dict[str, Any]:
    def r16(address: int, memory_type: str = "Sa1Memory") -> int:
        return le16(m.read_memory(memory_type, address, 2))

    def r32(address: int, memory_type: str = "Sa1Memory") -> int:
        return le32(m.read_memory(memory_type, address, 4))

    state = m.get_state()
    cpu = m.get_cpu_state("Sa1")
    return {
        "frame": int(state.get("frameCount", 0)),
        "tick": r16(0x0760),
        "pc68k": r32(0x0040) & 0xFFFFFF,
        "steps": r32(0x004A),
        "opcode": r16(0x0044),
        "halt": r16(0x004E),
        "ac": r16(0x00AC),
        "task_mask": r16(0x400002, "snesMemory"),
        "sound_ring_ptr": m.read_memory("snesMemory", 0x401C40, 4).hex(),
        "gates": {name: r16(address) for name, address in GATE_ADDRS.items()},
        "idle_vsync_lab_gate": r16(0x0734),
        "sa1_cycles": int(cpu.get("cycleCount", 0)),
        "sa1_pc": (int(cpu.get("k", 0)) << 16) | int(cpu.get("pc", 0)),
        "emulator_running": bool(state.get("isRunning", False)),
        "emulator_paused": bool(state.get("isPaused", False)),
    }


def require_production_state(label: str, state: dict[str, Any]) -> None:
    if state["gates"] != EXPECTED_GATES:
        raise RuntimeError(
            f"{label} gate mismatch: expected {EXPECTED_GATES}, got {state['gates']}"
        )
    if state["halt"] != 0:
        raise RuntimeError(f"{label} interpreter halted: $4E={state['halt']:#06x}")
    if state["sound_ring_ptr"] != "00f01c20":
        raise RuntimeError(
            f"{label} sound ring mismatch: {state['sound_ring_ptr']} != 00f01c20"
        )


def bootstrap_state(args: argparse.Namespace, log: Recorder, checkpoint: Path) -> Path:
    executable = args.bootstrap_emulator.resolve()
    configure_dotnet(executable)
    log.emit(
        "bootstrap_start",
        emulator=str(executable),
        emulator_sha256=sha256(executable),
        timing_evidence=False,
    )
    with McpSession(
        rom=args.rom.resolve(),
        mesen=executable,
        cwd=ROOT,
        port=args.bootstrap_port,
        boot_wait=6.0,
        socket_timeout=max(120.0, args.arm_timeout),
        stderr_log=args.output / "bootstrap.stderr.log",
    ) as m:
        m.pause()
        state = wait_for_production_gates(
            m,
            args.arm_timeout,
            args.poll_seconds,
            log,
        )
        require_production_state("bootstrap", state)
        if args.idle_vsync_lab:
            m.write_u16(0x0734, 1, "Sa1Memory")
            state = snapshot(m)
            log.emit(
                "lab_intervention",
                action="set_idle_vsync_gate",
                address="00:0734",
                value=1,
            )
        m.save_state(checkpoint)
        wait_for_stable_file(checkpoint)
        log.emit(
            "bootstrap_checkpoint",
            checkpoint=str(checkpoint),
            checkpoint_sha256=sha256(checkpoint),
            **state,
        )
    return checkpoint


def drive_gameplay_state(
    args: argparse.Namespace,
    source_state: Path,
    log: Recorder,
    gameplay_state: Path,
) -> Path:
    """Create a same-ROM gameplay checkpoint without debugger hooks or gate pokes."""
    configure_dotnet(args.nexen)
    start = time.monotonic()
    last_heartbeat = start
    with McpSession(
        rom=args.rom.resolve(),
        mesen=args.nexen.resolve(),
        cwd=ROOT,
        port=args.bootstrap_port,
        boot_wait=6.0,
        socket_timeout=max(300.0, args.arm_timeout),
        stderr_log=args.output / "gameplay-drive.stderr.log",
    ) as m:
        m.pause()
        m.load_state(source_state.resolve())
        m.pause()
        initial = snapshot(m)
        require_production_state("gameplay drive start", initial)
        last_tick = initial["tick"]
        total_ticks = 0
        stage = "preinput"
        stage_tick = 0
        input_word = 0
        gameplay_tick: int | None = None
        gameplay_frame: int | None = None
        frames_per_tick = 45.0
        last_progress_frame = initial["frame"]

        log.emit(
            "gameplay_drive_start",
            source_state=str(source_state),
            source_state_sha256=sha256(source_state),
            settle_ticks=args.gameplay_settle_ticks,
            **initial,
        )

        def set_input(value: int) -> None:
            nonlocal input_word
            input_word = value
            m.write_u16(0x410002, value, "snesMemory")
            log.emit(
                "gameplay_drive_input",
                stage=stage,
                tick_total=total_ticks,
                value=value,
            )

        while time.monotonic() - start < args.arm_timeout:
            limits = {
                "preinput": 105,
                "coin1_hold": 8,
                "coin1_gap": 7,
                "coin2_hold": 8,
                "coin2_gap": 12,
                "start_hold": 10,
            }
            frames = args.drive_chunk_frames
            if stage in limits:
                remaining = limits[stage] - (total_ticks - stage_tick)
                if remaining > 0:
                    frames = max(
                        1,
                        min(
                            args.drive_chunk_frames,
                            int(max(1.0, frames_per_tick * remaining * 0.45)),
                        ),
                    )

            before_frame = int(m.get_state().get("frameCount", 0))
            run_result = m.run_frames(frames)
            if not bool(run_result.get("isPaused", False)):
                raise RuntimeError(f"gameplay drive did not pause: {run_result}")
            state = snapshot(m)
            tick_delta = (state["tick"] - last_tick) & 0xFFFF
            total_ticks += tick_delta
            last_tick = state["tick"]
            frame_delta = state["frame"] - before_frame
            if tick_delta:
                frames_per_tick = frame_delta / tick_delta
                last_progress_frame = state["frame"]

            require_production_state("gameplay drive", state)
            if state["idle_vsync_lab_gate"] != 0:
                raise RuntimeError("production gameplay drive unexpectedly has $0734 set")

            relative = total_ticks - stage_tick
            transitioned = False
            if stage == "preinput" and relative >= 105:
                stage = "coin1_hold"
                stage_tick = total_ticks
                set_input(COIN)
                transitioned = True
            elif stage == "coin1_hold" and relative >= 8:
                stage = "coin1_gap"
                stage_tick = total_ticks
                set_input(0)
                transitioned = True
            elif stage == "coin1_gap" and relative >= 7:
                stage = "coin2_hold"
                stage_tick = total_ticks
                set_input(COIN)
                transitioned = True
            elif stage == "coin2_hold" and relative >= 8:
                stage = "coin2_gap"
                stage_tick = total_ticks
                set_input(0)
                transitioned = True
            elif stage == "coin2_gap" and relative >= 12:
                stage = "start_hold"
                stage_tick = total_ticks
                set_input(START)
                transitioned = True
            elif stage == "start_hold" and relative >= 10:
                stage = "post_start"
                stage_tick = total_ticks
                set_input(0)
                transitioned = True

            if (
                gameplay_tick is None
                and stage == "post_start"
                and state["task_mask"] >> 8 == 0x3B
            ):
                gameplay_tick = total_ticks
                gameplay_frame = state["frame"]
                log.emit(
                    "gameplay_drive_detected",
                    tick_total=total_ticks,
                    input=input_word,
                    **state,
                )

            now = time.monotonic()
            if transitioned or now - last_heartbeat >= 30.0:
                log.emit(
                    "gameplay_drive_progress",
                    stage=stage,
                    tick_total=total_ticks,
                    input=input_word,
                    gameplay_tick=gameplay_tick,
                    **state,
                )
                last_heartbeat = now

            if state["frame"] - last_progress_frame > 1800:
                raise RuntimeError("gameplay drive made no tick progress for 1800 frames")
            if (
                gameplay_tick is not None
                and total_ticks - gameplay_tick >= args.gameplay_settle_ticks
            ):
                m.save_state(gameplay_state)
                wait_for_stable_file(gameplay_state, timeout=30.0)
                log.emit(
                    "gameplay_checkpoint",
                    checkpoint=str(gameplay_state),
                    checkpoint_sha256=sha256(gameplay_state),
                    gameplay_tick=gameplay_tick,
                    gameplay_frame=gameplay_frame,
                    total_ticks=total_ticks,
                    **state,
                )
                return gameplay_state

        raise TimeoutError(
            f"gameplay drive timed out after {args.arm_timeout:.1f} seconds"
        )


def summarize(values: list[int]) -> dict[str, float | int] | None:
    if not values:
        return None
    return {
        "count": len(values),
        "min": min(values),
        "median": statistics.median(values),
        "mean": statistics.fmean(values),
        "max": max(values),
    }


def analyze(events: list[dict[str, Any]]) -> tuple[list[dict], dict[str, Any]]:
    ordered = sorted(events, key=lambda event: int(event["cycleCount"]))
    clamps = [event for event in ordered if event["label"] == "clamp"]
    intervals = []
    for index, (left, right) in enumerate(zip(clamps, clamps[1:])):
        start = int(left["cycleCount"])
        end = int(right["cycleCount"])
        inside = [
            event
            for event in ordered
            if start < int(event["cycleCount"]) < end
        ]
        irqs = [event for event in inside if event["label"] == "take_irq"]
        entries = [event for event in inside if event["label"] == "entry_3a92"]
        idle_entries = [event for event in inside if event["label"] == "idle_entry"]
        entry = entries[0] if entries else None
        idle_entry = idle_entries[0] if idle_entries else None
        wake_irq = None
        if entry is not None:
            preceding = [
                irq
                for irq in irqs
                if int(irq["cycleCount"]) <= int(entry["cycleCount"])
            ]
            if preceding:
                wake_irq = preceding[-1]
        timeline = [left, *inside, right]
        intervals.append(
            {
                "index": index,
                "start_cycle": start,
                "end_cycle": end,
                "total_cycles": end - start,
                "start_frame": left.get("frame"),
                "end_frame": right.get("frame"),
                "frame_delta": int(right.get("frame", 0)) - int(left.get("frame", 0)),
                "irq_count": len(irqs),
                "entry_count": len(entries),
                "idle_entry_count": len(idle_entries),
                "clamp_to_wake_irq_cycles": (
                    int(wake_irq["cycleCount"]) - start if wake_irq else None
                ),
                "wake_irq_to_entry_cycles": (
                    int(entry["cycleCount"]) - int(wake_irq["cycleCount"])
                    if entry and wake_irq
                    else None
                ),
                "entry_to_next_clamp_cycles": (
                    end - int(entry["cycleCount"]) if entry else None
                ),
                "entry_to_idle_entry_cycles": (
                    int(idle_entry["cycleCount"]) - int(entry["cycleCount"])
                    if entry and idle_entry
                    else None
                ),
                "idle_entry_to_next_clamp_cycles": (
                    end - int(idle_entry["cycleCount"]) if idle_entry else None
                ),
                "timeline": [
                    {
                        "label": event["label"],
                        "cycle": int(event["cycleCount"]),
                        "delta_from_previous": (
                            0
                            if pos == 0
                            else int(event["cycleCount"])
                            - int(timeline[pos - 1]["cycleCount"])
                        ),
                        "frame": event.get("frame"),
                        "address": event.get("address"),
                    }
                    for pos, event in enumerate(timeline)
                ],
            }
        )

    def present(name: str) -> list[int]:
        return [
            int(interval[name])
            for interval in intervals
            if interval.get(name) is not None
        ]

    totals = present("total_cycles")
    mean_total = statistics.fmean(totals) if totals else 0.0
    summary = {
        "intervals": len(intervals),
        "complete_entry_intervals": sum(
            1 for interval in intervals if interval["entry_count"] == 1
        ),
        "total_cycles": summarize(totals),
        "clamp_to_wake_irq_cycles": summarize(
            present("clamp_to_wake_irq_cycles")
        ),
        "wake_irq_to_entry_cycles": summarize(
            present("wake_irq_to_entry_cycles")
        ),
        "entry_to_next_clamp_cycles": summarize(
            present("entry_to_next_clamp_cycles")
        ),
        "entry_to_idle_entry_cycles": summarize(
            present("entry_to_idle_entry_cycles")
        ),
        "idle_entry_to_next_clamp_cycles": summarize(
            present("idle_entry_to_next_clamp_cycles")
        ),
        "irq_counts": sorted({interval["irq_count"] for interval in intervals}),
        "entry_counts": sorted({interval["entry_count"] for interval in intervals}),
        "idle_entry_counts": sorted(
            {interval["idle_entry_count"] for interval in intervals}
        ),
        "canonical_post_arm_cycles_per_tick": CANONICAL_POST_ARM_CYCLES_PER_TICK,
        "mean_vs_canonical_percent": (
            100.0
            * (mean_total - CANONICAL_POST_ARM_CYCLES_PER_TICK)
            / CANONICAL_POST_ARM_CYCLES_PER_TICK
            if totals
            else None
        ),
    }
    return intervals, summary


def profile(args: argparse.Namespace, state_path: Path, log: Recorder) -> dict[str, Any]:
    configure_dotnet(args.nexen)
    with McpSession(
        rom=args.rom.resolve(),
        mesen=args.nexen.resolve(),
        cwd=ROOT,
        port=args.port,
        boot_wait=8.0,
        socket_timeout=max(120.0, args.profile_timeout),
        stderr_log=args.output / "nexen.stderr.log",
    ) as m:
        m.pause()
        m.load_state(state_path.resolve())
        m.pause()
        start_state = snapshot(m)
        require_production_state("profiling Nexen", start_state)
        if args.idle_vsync_lab and start_state["idle_vsync_lab_gate"] != 1:
            raise RuntimeError("idle-vsync lab checkpoint does not have $0734=1")
        log.emit("profile_start", state=str(state_path), **start_state)

        handles = {
            "clamp": m.add_exec_hook(CLAMP, cpu_type="Sa1"),
            "take_irq": m.add_exec_hook(TAKE_IRQ, cpu_type="Sa1"),
            "entry_3a92": m.add_exec_hook(ENTRY_3A92, cpu_type="Sa1"),
        }
        if args.idle_vsync_lab:
            handles["idle_entry"] = m.add_exec_hook(IDLE_ENTRY_LAB, cpu_type="Sa1")
        by_handle = {handle: label for label, handle in handles.items()}
        m.drain_notifications(timeout=0.05)
        collected: list[dict[str, Any]] = []
        start = time.monotonic()
        last_heartbeat = start
        target_clamps = args.intervals + 1
        m.resume()
        while time.monotonic() - start < args.profile_timeout:
            rows = m.drain_notifications(timeout=min(0.1, args.poll_seconds))
            for params in hook_events(rows):
                handle = int(params.get("handle", -1))
                if handle not in by_handle:
                    continue
                if "cycleCount" not in params:
                    raise RuntimeError(
                        "profiling Nexen hook notification lacks cycleCount; "
                        "use the R5 cycle-stamped build"
                    )
                event = {**params, "label": by_handle[handle]}
                collected.append(event)
                log.emit("phase_hook", **event)
            clamp_count = sum(1 for event in collected if event["label"] == "clamp")
            if clamp_count >= target_clamps:
                m.pause()
                break
            now = time.monotonic()
            if now - last_heartbeat >= 15.0:
                log.emit(
                    "heartbeat",
                    phase="continuous_profile",
                    wall_seconds=now - start,
                    clamps=clamp_count,
                    hook_events=len(collected),
                )
                last_heartbeat = now
            time.sleep(args.poll_seconds)
        else:
            m.pause()
            raise TimeoutError(
                f"continuous profile timed out after {args.profile_timeout:.1f} seconds"
            )

        for params in hook_events(m.drain_notifications(timeout=0.2)):
            handle = int(params.get("handle", -1))
            if handle in by_handle and "cycleCount" in params:
                event = {**params, "label": by_handle[handle]}
                collected.append(event)
                log.emit("phase_hook", **event)
        for handle in handles.values():
            m.remove_hook(handle)
        end_state = snapshot(m)
        require_production_state("profile end", end_state)

    intervals, summary = analyze(collected)
    for interval in intervals:
        log.emit("interval", **interval)
    log.emit("profile_summary", **summary)
    return {
        "start_state": start_state,
        "end_state": end_state,
        "hook_counts": {
            label: sum(1 for event in collected if event["label"] == label)
            for label in handles
        },
        "summary": summary,
    }


def main() -> int:
    args = parse_args()
    if args.intervals < 2:
        raise SystemExit("--intervals must be at least 2")
    if args.poll_seconds <= 0 or args.poll_seconds > 5:
        raise SystemExit("--poll-seconds must be in (0, 5]")
    if args.gameplay_settle_ticks < 0:
        raise SystemExit("--gameplay-settle-ticks cannot be negative")
    if args.drive_chunk_frames <= 0:
        raise SystemExit("--drive-chunk-frames must be positive")
    if args.drive_gameplay and args.idle_vsync_lab:
        raise SystemExit("--drive-gameplay profiles production, not an idle-vsync lab")
    args.rom = args.rom.resolve()
    args.nexen = args.nexen.resolve()
    args.bootstrap_emulator = args.bootstrap_emulator.resolve()
    args.output = args.output.resolve()
    for label, path in (
        ("ROM", args.rom),
        ("profiling Nexen", args.nexen),
    ):
        if not path.is_file():
            raise SystemExit(f"{label} not found: {path}")
    if args.state is None and not args.bootstrap_emulator.is_file():
        raise SystemExit(f"bootstrap emulator not found: {args.bootstrap_emulator}")
    if args.state is not None and not args.state.resolve().is_file():
        raise SystemExit(f"state not found: {args.state}")
    if args.output.exists() and any(args.output.iterdir()):
        raise SystemExit(f"refusing to overwrite non-empty output: {args.output}")
    args.output.mkdir(parents=True, exist_ok=True)

    rom = args.rom.read_bytes()
    if len(rom) != 0x400000:
        raise SystemExit(f"expected 4 MiB production ROM, got {len(rom)} bytes")
    testflag = int.from_bytes(rom[0x77E0:0x77E2], "little")
    if testflag != 0:
        raise SystemExit(f"refusing non-production ROM: TESTFLAG={testflag:#06x}")
    if rom[0x75A3:0x75A6] != bytes.fromhex("ee6007"):
        raise SystemExit("stale $00:F5A3 clamp hook address")
    if args.idle_vsync_lab:
        marker = rom[
            IDLE_VSYNC_LAB_MARKER_OFFSET:
            IDLE_VSYNC_LAB_MARKER_OFFSET + 8
        ]
        if marker not in IDLE_VSYNC_LAB_MARKERS:
            raise SystemExit("--idle-vsync-lab requires a marked R5VSYNC1/R5VNMI01 lab ROM")

    nexen_repo = repo_for(args.nexen)
    log = Recorder(args.output / "profile.jsonl")
    log.emit(
        "provenance",
        project_commit=git_value(ROOT, "rev-parse", "HEAD"),
        project_status=git_value(ROOT, "status", "--porcelain=v1").splitlines(),
        harness=str(Path(__file__).resolve()),
        harness_sha256=sha256(Path(__file__).resolve()),
        rom=str(args.rom),
        rom_sha256=sha256(args.rom),
        testflag=testflag,
        nexen=str(args.nexen),
        nexen_sha256=sha256(args.nexen),
        nexen_repo=str(nexen_repo) if nexen_repo else None,
        nexen_commit=(
            git_value(nexen_repo, "rev-parse", "HEAD") if nexen_repo else "unknown"
        ),
        hook_addresses={
            "clamp": f"{CLAMP:06X}",
            "take_irq": f"{TAKE_IRQ:06X}",
            "entry_3a92": f"{ENTRY_3A92:06X}",
        },
        intervals_requested=args.intervals,
        continuous_no_hook_pauses=True,
        idle_vsync_lab=args.idle_vsync_lab,
        idle_vsync_lab_marker=(marker.decode() if args.idle_vsync_lab else None),
        drive_gameplay=args.drive_gameplay,
        gameplay_settle_ticks=(
            args.gameplay_settle_ticks if args.drive_gameplay else None
        ),
    )
    try:
        if args.state is not None:
            state_path = args.state.resolve()
            log.emit(
                "checkpoint_reused",
                checkpoint=str(state_path),
                checkpoint_sha256=sha256(state_path),
            )
        else:
            state_path = bootstrap_state(
                args, log, args.output / "production-arm.mss"
            )
        if args.drive_gameplay:
            state_path = drive_gameplay_state(
                args,
                state_path,
                log,
                args.output / "production-gameplay.mss",
            )
        result = profile(args, state_path, log)
        log.emit("final", result="complete", **result)
        return 0
    except Exception as exc:
        log.emit("final", result="error", error=repr(exc))
        raise
    finally:
        log.close()


if __name__ == "__main__":
    raise SystemExit(main())
