#!/usr/bin/env python3
"""Replay organic controller input from an armed production checkpoint.

This diagnostic harness exists to retain the state immediately after Start is
released, before the expensive round-start transition.  It loads a checkpoint
that was produced organically by ``recovery_baseline.py``, drives Nexen port 0
through the same manual-$4016 controller path as production, and schedules each
edge from notifications at the real $0818/$00:F5A3 tick boundary.

The result is checkpoint evidence, never an end-to-end FPS measurement.  No
emulated RAM, register, accelerator gate, or task state is written.
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

from profile_tick_ring import EXPECTED_CLAMP_BYTES, EXPECTED_GATES, GATE_ADDRS


DEFAULT_ROM = ROOT / "build/interp.sfc"
DEFAULT_STATE = ROOT / "build/playability-20260720/96a-cold-boot-300/armed.mss"
DEFAULT_NEXEN = Path(
    "/mnt/sdc1/Nexen-r5-20260712/"
    "bin/linux-x64/Release/linux-x64/publish/Nexen"
)
DEFAULT_OUTPUT = ROOT / "build/start-transition-checkpoint"
CLAMP = 0x00F5A3
COIN = 0x2000
START = 0x1000


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--nexen", type=Path, default=DEFAULT_NEXEN)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--port", type=int, default=7648)
    parser.add_argument("--preinput-ticks", type=int, default=105)
    parser.add_argument("--hold-ticks", type=int, default=8)
    parser.add_argument("--gap-ticks", type=int, default=7)
    parser.add_argument("--prestart-gap-ticks", type=int, default=12)
    parser.add_argument("--start-hold-ticks", type=int, default=10)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--poll-seconds", type=float, default=0.01)
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


def configure_dotnet(executable: Path) -> None:
    root = "/home/chad/.dotnet10" if executable.name == "Nexen" else "/home/chad/.dotnet8"
    other = "/home/chad/.dotnet8" if executable.name == "Nexen" else "/home/chad/.dotnet10"
    os.environ["DOTNET_ROOT"] = root
    current = [
        item
        for item in os.environ.get("PATH", "").split(":")
        if item and item not in (root, other)
    ]
    os.environ["PATH"] = ":".join([root, other, *current])


def le16(data: bytes) -> int:
    return data[0] | (data[1] << 8)


def modular_delta(now: int, before: int) -> int:
    return (now - before) & 0xFFFF


def snapshot(m: McpSession) -> dict[str, Any]:
    def r16(address: int, memory_type: str = "Sa1Memory") -> int:
        return le16(m.read_memory(memory_type, address, 2))

    state = m.get_state()
    cpu = m.get_cpu_state("Sa1")
    return {
        "frame": int(state.get("frameCount", 0)),
        "tick": r16(0x0760),
        "pc68k": (
            r16(0x0040) | ((r16(0x0042) & 0x00FF) << 16)
        ),
        "halt": r16(0x004E),
        "task_mask": r16(0x400002, "snesMemory"),
        "gates": {name: r16(address) for name, address in GATE_ADDRS.items()},
        "production_pacing_gate": r16(0x0734),
        "input_mailbox": m.read_memory("snesMemory", 0x410000, 2).hex(),
        "input_injection": m.read_memory("snesMemory", 0x410002, 2).hex(),
        "sa1_cycles": int(cpu.get("cycleCount", 0)),
        "sa1_pc": (int(cpu.get("k", 0)) << 16) | int(cpu.get("pc", 0)),
    }


def require_healthy(label: str, state: dict[str, Any]) -> None:
    if state["gates"] != EXPECTED_GATES:
        raise RuntimeError(
            f"{label} gate mismatch: expected {EXPECTED_GATES}, got {state['gates']}"
        )
    if state["production_pacing_gate"] != 1:
        raise RuntimeError(f"{label} production pacing gate is not armed")
    if state["halt"] != 0:
        raise RuntimeError(f"{label} halt word is ${state['halt']:04X}")


def hook_notifications(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        row.get("params", {})
        for row in rows
        if row.get("method") == "notifications/mesen/hookFired"
    ]


def main() -> int:
    args = parse_args()
    if min(
        args.preinput_ticks,
        args.hold_ticks,
        args.gap_ticks,
        args.prestart_gap_ticks,
        args.start_hold_ticks,
    ) <= 0:
        raise SystemExit("all schedule tick counts must be positive")
    if args.timeout <= 0 or not 0 < args.poll_seconds <= 1:
        raise SystemExit("--timeout must be positive and --poll-seconds must be in (0, 1]")

    rom = args.rom.resolve()
    state_path = args.state.resolve()
    nexen = args.nexen.resolve()
    output = args.output.resolve()
    for label, path in (("ROM", rom), ("state", state_path), ("Nexen", nexen)):
        if not path.is_file():
            raise SystemExit(f"{label} not found: {path}")
    if rom.stat().st_size != 0x400000:
        raise SystemExit(f"expected a 4 MiB production ROM: {rom}")
    rom_data = rom.read_bytes()
    testflag = int.from_bytes(rom_data[0x77E0:0x77E2], "little")
    if testflag != 0:
        raise SystemExit(f"TESTFLAG must be zero, got {testflag:#06x}")
    if rom_data[0x75A3:0x75A6] != EXPECTED_CLAMP_BYTES:
        raise SystemExit("real $0818 tick-hook bytes do not match this harness")
    output.mkdir(parents=True, exist_ok=False)
    log_path = output / "capture.jsonl"
    stderr_path = output / "nexen.stderr.log"
    checkpoint_path = output / "post_start.mss"
    screenshot_path = output / "post_start.png"

    configure_dotnet(nexen)
    schedule = [
        (args.preinput_ticks, "coin1_down", COIN),
        (args.preinput_ticks + args.hold_ticks, "coin1_up", 0),
        (
            args.preinput_ticks + args.hold_ticks + args.gap_ticks,
            "coin2_down",
            COIN,
        ),
        (
            args.preinput_ticks + 2 * args.hold_ticks + args.gap_ticks,
            "coin2_up",
            0,
        ),
        (
            args.preinput_ticks
            + 2 * args.hold_ticks
            + args.gap_ticks
            + args.prestart_gap_ticks,
            "start_down",
            START,
        ),
        (
            args.preinput_ticks
            + 2 * args.hold_ticks
            + args.gap_ticks
            + args.prestart_gap_ticks
            + args.start_hold_ticks,
            "start_up",
            0,
        ),
    ]

    with log_path.open("x", encoding="utf-8") as log:
        def emit(event: str, **fields: Any) -> None:
            row = {"event": event, "time": time.time(), **fields}
            line = json.dumps(row, sort_keys=True)
            print(line, flush=True)
            log.write(line + "\n")
            log.flush()

        emit(
            "provenance",
            project_commit=git_value("rev-parse", "HEAD"),
            project_status=git_value("status", "--short").splitlines(),
            rom=str(rom),
            rom_sha256=sha256(rom),
            state=str(state_path),
            state_sha256=sha256(state_path),
            nexen=str(nexen),
            nexen_sha256=sha256(nexen),
            testflag=testflag,
            tick_hook="00:F5A3",
            input_transport="nexen_port0_manual_4016",
            schedule=[
                {"clamp_delta": tick, "label": label, "value": value}
                for tick, label, value in schedule
            ],
            runtime_memory_pokes=[],
            evidence_scope="checkpointed production transition setup; not fps",
        )

        with McpSession(
            rom=rom,
            mesen=nexen,
            cwd=ROOT,
            port=args.port,
            boot_wait=6.0,
            socket_timeout=max(120.0, args.timeout),
            stderr_log=stderr_path,
        ) as m:
            m.pause()
            m.load_state(state_path)
            m.pause()
            start_state = snapshot(m)
            require_healthy("capture start", start_state)
            if start_state["task_mask"] != 0x0300:
                raise RuntimeError(
                    "armed checkpoint is not in the expected attract task state: "
                    f"${start_state['task_mask']:04X}"
                )
            emit("capture_start", **start_state)

            # Controller state belongs to Nexen rather than the save state.
            # Establish a released controller before resuming; this is the real
            # input transport, not a write to the emulated mailbox.
            m.tool("set_input", {"port": 0, "buttons": 0, "hold": True})
            handle = m.add_exec_hook(CLAMP, cpu_type="Sa1")
            m.drain_notifications(timeout=0.05)
            clamp_count = 0
            next_edge = 0
            last_hook: dict[str, Any] | None = None
            started = time.monotonic()
            m.resume()
            while time.monotonic() - started < args.timeout:
                for params in hook_notifications(
                    m.drain_notifications(timeout=args.poll_seconds)
                ):
                    if int(params.get("handle", -1)) != handle:
                        continue
                    if "cycleCount" not in params:
                        raise RuntimeError(
                            "tick hook lacks cycleCount; use the healthy R5 Nexen"
                        )
                    last_hook = params
                    clamp_count += 1
                    if next_edge >= len(schedule):
                        continue
                    target, label, value = schedule[next_edge]
                    if clamp_count < target:
                        continue
                    if clamp_count != target:
                        raise RuntimeError(
                            f"missed input edge {label}: target={target}, now={clamp_count}"
                        )
                    buttons = {
                        0: 0,
                        COIN: McpSession.BTN_SELECT,
                        START: McpSession.BTN_START,
                    }[value]
                    m.tool(
                        "set_input",
                        {"port": 0, "buttons": buttons, "hold": True},
                    )
                    emit(
                        "input_edge",
                        label=label,
                        value=value,
                        buttons=buttons,
                        clamp_delta=clamp_count,
                        hook_cycle=int(params["cycleCount"]),
                        hook_frame=int(params.get("frame", 0)),
                    )
                    next_edge += 1
                    if next_edge == len(schedule):
                        m.pause()
                        break
                if next_edge == len(schedule):
                    break
                time.sleep(min(0.005, args.poll_seconds))
            else:
                m.pause()
                raise TimeoutError(
                    f"input replay timed out after {args.timeout:.1f} seconds"
                )

            m.pause()
            m.remove_hook(handle)
            end_state = snapshot(m)
            require_healthy("capture end", end_state)
            counter_delta = modular_delta(end_state["tick"], start_state["tick"])
            if counter_delta != clamp_count:
                raise RuntimeError(
                    f"tick counter/hook mismatch: counter={counter_delta}, hooks={clamp_count}"
                )
            response = m.save_state(checkpoint_path)
            deadline = time.monotonic() + 30.0
            while time.monotonic() < deadline:
                if checkpoint_path.is_file() and checkpoint_path.stat().st_size > 0:
                    break
                time.sleep(0.05)
            else:
                raise TimeoutError(f"save state was not created: {checkpoint_path}")
            shot = m.take_screenshot(format="path")
            source = Path(shot["path"])
            if source.is_file():
                shutil.copy2(source, screenshot_path)
            emit(
                "capture_final",
                **end_state,
                clamp_events=clamp_count,
                tick_counter_delta=counter_delta,
                last_hook_cycle=(
                    int(last_hook["cycleCount"]) if last_hook is not None else None
                ),
                checkpoint=str(checkpoint_path),
                checkpoint_sha256=sha256(checkpoint_path),
                save_response=response,
                screenshot=str(screenshot_path),
                screenshot_response=shot,
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
