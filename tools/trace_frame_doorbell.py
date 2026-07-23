#!/usr/bin/env python3
"""Locate a production FRAME_REQ regression from a retained arm checkpoint.

This is a checkpointed diagnostic, never FPS evidence.  It drives the same
real Nexen port-0 Select/Start sequence as ``recovery_baseline.py`` while a
value-filtered SA-1 write hook detects when byte $0300 is written as zero.
Near the observed $012F/$0131->$0100 regression it records the complete mailbox bus
traffic and exact native handoff landmarks without pausing either CPU.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
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


DEFAULT_ROM = ROOT / "build/interp.sfc"
DEFAULT_STATE = (
    ROOT
    / "build/playability-20260720/renderer-bounds-live-v2/"
    "cold-boot-300/armed.mss"
)
DEFAULT_NEXEN = Path(
    "/mnt/sdc1/Nexen-r5-20260712/"
    "bin/linux-x64/Release/linux-x64/publish/Nexen"
)
DEFAULT_OUTPUT = (
    ROOT
    / "build/playability-20260720/renderer-bounds-live-v2/"
    "frame-doorbell-writer-trace"
)

COIN = 0x2000
START = 0x1000
RING_START = 0x0400
RING_END = 0x05FF

# These hooks are notification-only context.  The physical-$0300 zero hook is
# the sole early stop condition before this set is armed.  Once armed, the
# harness uses free-running notification mode because Nexen run_until stops at
# every installed hook regardless of the requested handle.
LATE_EXEC_HOOKS = {
    "lhp_entry": 0x99FB00,
    "lhp_wai": 0x99FB47,
    "lhp_after_wai": 0x99FB48,
    "lhp_rtl": 0x99FB6D,
    "tick_0818": 0x00F5A3,
    "vid_frame_call": 0x0080B6,
    "vid_frame_wrapper": 0xE98000,
    "snd_vframe": 0xE99900,
    "snapshot_publish": 0xE99F34,
    "frame_req_inc": 0xE9997F,
    "frame_req_plp": 0xE99982,
    "take_irq": 0x00B404,
    "hle_158e": 0x99F800,
}

LATE_READ_HOOKS = {
    "mailbox_read_sa1_physical": ("Sa1", 0x0300, 0x0303),
    "mailbox_read_sa1_mirror": ("Sa1", 0x3300, 0x3303),
    "mailbox_read_snes_mirror": ("Snes", 0x3300, 0x3303),
}

LATE_WRITE_HOOKS = {
    "mailbox_write_sa1_physical": ("Sa1", 0x0300, 0x0303),
    "mailbox_write_sa1_mirror": ("Sa1", 0x3300, 0x3303),
    "mailbox_write_snes_mirror": ("Snes", 0x3300, 0x3303),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--nexen", type=Path, default=DEFAULT_NEXEN)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--port", type=int, default=7493)
    parser.add_argument("--max-relative-ticks", type=int, default=500)
    parser.add_argument("--max-frames-per-run", type=int, default=8)
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument(
        "--ring-arm-request",
        type=lambda value: int(value, 0),
        default=0x012A,
        help="Install cycle-stamped PC-ring/context hooks at this FRAME_REQ.",
    )
    parser.add_argument(
        "--pc-ring",
        action="store_true",
        help="Also trace the high-volume always-on 68K PC ring.",
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


def configure_dotnet(executable: Path) -> None:
    dotnet10 = "/home/chad/.dotnet10"
    dotnet8 = "/home/chad/.dotnet8"
    os.environ["DOTNET_ROOT"] = dotnet10
    current = [
        item
        for item in os.environ.get("PATH", "").split(":")
        if item and item not in (dotnet10, dotnet8)
    ]
    os.environ["PATH"] = ":".join([dotnet10, dotnet8, *current])


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


def cpu_brief(m: McpSession, cpu_type: str) -> dict[str, Any]:
    state = dict(m.get_cpu_state(cpu_type))
    result = {
        key: state.get(key)
        for key in ("pc", "k", "sp", "ps", "a", "x", "y", "d", "dbr", "cycleCount")
        if key in state
    }
    if "pc" in state:
        result["linear_pc"] = (int(state.get("k", 0)) << 16) | int(state["pc"])
    return result


def parse_ring_writes(writes: list[dict[str, Any]]) -> list[dict[str, int]]:
    """Reassemble each four-byte dbg_fetch record in cycle order."""
    ordered = sorted(writes, key=lambda event: int(event["cycleCount"]))
    records: list[dict[str, int]] = []
    index = 0
    while index + 3 < len(ordered):
        group = ordered[index : index + 4]
        address = int(group[0]["address"])
        if (
            address % 4 == 0
            and [int(event["address"]) for event in group]
            == [address + offset for offset in range(4)]
            and int(group[-1]["cycleCount"]) - int(group[0]["cycleCount"]) <= 64
        ):
            values = [int(event["value"]) & 0xFF for event in group]
            low = values[0] | (values[1] << 8)
            bank_word = values[2] | (values[3] << 8)
            records.append(
                {
                    "cycle": int(group[0]["cycleCount"]),
                    "frame": int(group[0].get("frame", 0)),
                    "ring_address": address,
                    "pc": ((bank_word & 0xFF) << 16) | low,
                }
            )
            index += 4
        else:
            index += 1
    return records


def main() -> int:
    args = parse_args()
    rom = args.rom.resolve()
    state_path = args.state.resolve()
    nexen = args.nexen.resolve()
    output = args.output.resolve()
    for label, path in (("ROM", rom), ("state", state_path), ("Nexen", nexen)):
        if not path.is_file():
            raise SystemExit(f"{label} not found: {path}")
    if output.exists():
        raise SystemExit(f"refusing existing output: {output}")
    output.mkdir(parents=True)
    rom_data = rom.read_bytes()
    if len(rom_data) != 0x400000 or int.from_bytes(rom_data[0x77E0:0x77E2], "little"):
        raise SystemExit("requires a 4 MiB TESTFLAG=0 production ROM")
    configure_dotnet(nexen)

    rows: list[dict[str, Any]] = [
        {
            "event": "provenance",
            "time": time.time(),
            "git_commit": git_value("rev-parse", "HEAD"),
            "git_status": git_value("status", "--porcelain=v1").splitlines(),
            "harness": str(Path(__file__).resolve()),
            "harness_sha256": sha256(Path(__file__).resolve()),
            "rom": str(rom),
            "rom_sha256": sha256(rom),
            "state": str(state_path),
            "state_sha256": sha256(state_path),
            "nexen": str(nexen),
            "nexen_sha256": sha256(nexen),
            "runtime_pokes": [],
            "input_transport": "nexen_port0_manual_4016",
            "scope": "checkpointed writer diagnostic; not cold boot and not FPS",
        }
    ]

    with McpSession(
        rom=rom,
        mesen=nexen,
        cwd=ROOT,
        port=args.port,
        boot_wait=8.0,
        socket_timeout=max(180.0, args.timeout),
        stderr_log=output / "nexen.stderr.log",
    ) as m:
        m.pause()
        m.load_state(state_path)
        m.pause()

        def r16(address: int, memory_type: str = "Sa1Memory") -> int:
            return int.from_bytes(m.read_memory(memory_type, address, 2), "little")

        start_tick = r16(0x0760)
        last_tick = start_tick
        relative_ticks = 0
        previous_request = r16(0x3300, "snesMemory")
        stage = "preinput"
        stage_tick = 0

        def set_input(value: int) -> None:
            buttons = {
                0: 0,
                COIN: McpSession.BTN_SELECT,
                START: McpSession.BTN_START,
            }[value]
            response = m.tool(
                "set_input", {"port": 0, "buttons": buttons, "hold": True}
            )
            rows.append(
                {
                    "event": "input",
                    "time": time.time(),
                    "stage": stage,
                    "relative_ticks": relative_ticks,
                    "value": value,
                    "buttons": buttons,
                    "response": response,
                }
            )

        set_input(0)
        # $3300 is the CPU mirror used by snd_vframe.  The physical IRAM alias
        # is $0300; an indexed/direct write there can overwrite the same byte
        # without matching a logical-$3300 hook.  Pause on the physical alias
        # and keep both logical writers notification-visible.
        zero_sa1_physical = m.add_write_hook(
            0x0300,
            cpu_type="Sa1",
            match_value=0,
            match_value_mask=0xFF,
        )
        zero_sa1_mirror = m.add_write_hook(
            0x3300,
            cpu_type="Sa1",
            match_value=0,
            match_value_mask=0xFF,
        )
        zero_snes = m.add_write_hook(
            0x3300,
            cpu_type="Snes",
            match_value=0,
            match_value_mask=0xFF,
        )
        labels = {
            zero_sa1_physical: "sa1_physical_0300_zero_write",
            zero_sa1_mirror: "sa1_mirror_3300_zero_write",
            zero_snes: "snes_mirror_3300_zero_write",
        }
        ring_handle: int | None = None
        late_handles: list[int] = []
        ring_events: list[dict[str, Any]] = []
        context_events: list[dict[str, Any]] = []

        def arm_cycle_context() -> None:
            nonlocal ring_handle
            if ring_handle is not None:
                return
            # A negative sentinel means context is armed without the optional
            # high-volume PC ring.  Native landmarks are sufficient for the
            # mailbox-clobber diagnosis and perturb the run far less.
            ring_handle = -1
            if args.pc_ring:
                ring_handle = m.add_write_hook(
                    RING_START, RING_END, cpu_type="Sa1"
                )
                labels[ring_handle] = "pc_ring_write"
                late_handles.append(ring_handle)
            for label, address in LATE_EXEC_HOOKS.items():
                handle = m.add_exec_hook(address, cpu_type="Sa1")
                labels[handle] = label
                late_handles.append(handle)
            for label, (cpu_type, start_address, end_address) in LATE_READ_HOOKS.items():
                handle = m.add_read_hook(
                    start_address, end_address, cpu_type=cpu_type
                )
                labels[handle] = label
                late_handles.append(handle)
            for label, (cpu_type, start_address, end_address) in LATE_WRITE_HOOKS.items():
                handle = m.add_write_hook(
                    start_address, end_address, cpu_type=cpu_type
                )
                labels[handle] = label
                late_handles.append(handle)
            rows.append(
                {
                    "event": "cycle_context_armed",
                    "time": time.time(),
                    "relative_ticks": relative_ticks,
                    "frame_request": request,
                    "ring_span": (
                        [RING_START, RING_END] if args.pc_ring else None
                    ),
                    "exec_hooks": LATE_EXEC_HOOKS,
                    "read_hooks": LATE_READ_HOOKS,
                    "write_hooks": LATE_WRITE_HOOKS,
                }
            )
            target = output / "pre_regression.mss"
            m.save_state(target)
            wait_for_stable_file(target)
            rows.append(
                {
                    "event": "pre_regression_checkpoint",
                    "time": time.time(),
                    "path": str(target),
                    "sha256": sha256(target),
                    "relative_ticks": relative_ticks,
                    "frame_request": request,
                    "frame_ack": r16(0x3302, "snesMemory"),
                }
            )
        m.drain_notifications(timeout=0.05)
        rows.append(
            {
                "event": "start",
                "time": time.time(),
                "tick": start_tick,
                "frame_request": previous_request,
                "frame_ack": r16(0x3302, "snesMemory"),
                "sa1_cpu": cpu_brief(m, "Sa1"),
                "snes_cpu": cpu_brief(m, "Snes"),
            }
        )

        anomaly: dict[str, Any] | None = None
        wall_start = time.monotonic()
        iterations = 0
        while (
            relative_ticks < args.max_relative_ticks
            and time.monotonic() - wall_start < args.timeout
        ):
            if ring_handle is None:
                # Once the request approaches the observed $012F-$0131 race, use
                # one-video-frame chunks so the late hooks can be installed at
                # $0131 rather than several requests too early.
                max_frames = (
                    1
                    if previous_request >= args.ring_arm_request - 1
                    else args.max_frames_per_run
                )
                run_result = m.run_until(
                    max_frames=max_frames,
                    hook_handle=zero_sa1_physical,
                )
                m.pause()
                notifications = m.drain_notifications(timeout=0.05)
            else:
                # run_until treats every installed hook as a stop, even when a
                # different handle is supplied.  Resume freely and consume the
                # cycle-stamped notifications instead; this is the non-pausing
                # mode used by profile_tick_ring.py.
                notifications = []
                writer_seen = False
                late_tick_hits = 0
                target_late_ticks = max(
                    1, args.max_relative_ticks - relative_ticks
                )
                m.resume()
                late_deadline = min(
                    wall_start + args.timeout,
                    time.monotonic() + 30.0,
                )
                while time.monotonic() < late_deadline and not writer_seen:
                    batch = m.drain_notifications(timeout=0.05)
                    notifications.extend(batch)
                    for row in batch:
                        if row.get("method") != "notifications/mesen/hookFired":
                            continue
                        handle = int(row.get("params", {}).get("handle", -1))
                        if handle == zero_sa1_physical:
                            writer_seen = True
                        if labels.get(handle) == "tick_0818":
                            late_tick_hits += 1
                    if late_tick_hits >= target_late_ticks:
                        break
                    if not batch:
                        time.sleep(0.005)
                m.pause()
                notifications.extend(m.drain_notifications(timeout=0.3))
                run_result = {
                    "framesAdvanced": 0,
                    "isPaused": True,
                    "reason": (
                        "hookNotification"
                        if writer_seen
                        else "targetTicks"
                        if late_tick_hits >= target_late_ticks
                        else "lateTimeout"
                    ),
                    "lateTickHits": late_tick_hits,
                }
            hook_rows = []
            for notification in notifications:
                if notification.get("method") != "notifications/mesen/hookFired":
                    continue
                params = dict(notification.get("params", {}))
                handle = int(params.get("handle", -1))
                if handle in labels:
                    event = {"label": labels[handle], **params}
                    if args.pc_ring and handle == ring_handle:
                        ring_events.append(params)
                    else:
                        hook_rows.append(event)
                        context_events.append(event)

            tick = r16(0x0760)
            relative_ticks += (tick - last_tick) & 0xFFFF
            last_tick = tick
            request = r16(0x3300, "snesMemory")
            ack = r16(0x3302, "snesMemory")
            regressed = request < previous_request and not (
                previous_request >= 0xFFF0 and request <= 0x000F
            )
            if hook_rows or regressed or iterations % 16 == 0:
                row = {
                    "event": "sample",
                    "time": time.time(),
                    "iteration": iterations,
                    "stage": stage,
                    "relative_ticks": relative_ticks,
                    "tick": tick,
                    "frame": int(m.get_state().get("frameCount", 0)),
                    "frame_request_before": previous_request,
                    "frame_request": request,
                    "frame_ack": ack,
                    "regressed": regressed,
                    "run_result": run_result,
                    "hooks": hook_rows,
                    "sa1_cpu": cpu_brief(m, "Sa1"),
                    "snes_cpu": cpu_brief(m, "Snes"),
                }
                rows.append(row)
                if regressed:
                    anomaly = row
                    target = output / "request_regression.mss"
                    m.save_state(target)
                    wait_for_stable_file(target)
                    rows.append(
                        {
                            "event": "checkpoint",
                            "time": time.time(),
                            "path": str(target),
                            "sha256": sha256(target),
                        }
                    )
                    break
            previous_request = request

            if request >= args.ring_arm_request:
                arm_cycle_context()

            relative = relative_ticks - stage_tick
            if stage == "preinput" and relative >= 105:
                stage, stage_tick = "coin1_hold", relative_ticks
                set_input(COIN)
            elif stage == "coin1_hold" and relative >= 8:
                stage, stage_tick = "coin1_gap", relative_ticks
                set_input(0)
            elif stage == "coin1_gap" and relative >= 7:
                stage, stage_tick = "coin2_hold", relative_ticks
                set_input(COIN)
            elif stage == "coin2_hold" and relative >= 8:
                stage, stage_tick = "coin2_gap", relative_ticks
                set_input(0)
            elif stage == "coin2_gap" and relative >= 12:
                stage, stage_tick = "start_hold", relative_ticks
                set_input(START)
            elif stage == "start_hold" and relative >= 10:
                stage, stage_tick = "post_start", relative_ticks
                set_input(0)
            iterations += 1

        ring_records = parse_ring_writes(ring_events)
        writer_cycles = [
            int(event["cycleCount"])
            for event in context_events
            if event["label"] == "sa1_physical_0300_zero_write"
        ]
        cycle_correlation: dict[str, Any] = {
            "event": "cycle_correlation",
            "ring_event_count": len(ring_events),
            "ring_record_count": len(ring_records),
            "context_events": context_events,
        }
        if writer_cycles:
            writer_cycle = writer_cycles[-1]
            before = [record for record in ring_records if record["cycle"] <= writer_cycle]
            nearest_index = len(before) - 1
            mailbox_labels = set(LATE_READ_HOOKS) | set(LATE_WRITE_HOOKS) | {
                "sa1_physical_0300_zero_write",
                "sa1_mirror_3300_zero_write",
                "snes_mirror_3300_zero_write",
            }
            cycle_correlation.update(
                {
                    "writer_cycle": writer_cycle,
                    "nearest_pc_index": nearest_index,
                    "nearby_68k_pcs": ring_records[
                        max(0, nearest_index - 12) : nearest_index + 9
                    ],
                    "nearby_context_events": [
                        event
                        for event in context_events
                        if abs(int(event["cycleCount"]) - writer_cycle) <= 100_000
                    ],
                    "mailbox_bus_events": [
                        event
                        for event in context_events
                        if event["label"] in mailbox_labels
                        and abs(int(event["cycleCount"]) - writer_cycle) <= 2_000
                    ],
                }
            )
        rows.append(cycle_correlation)

        for handle in (
            zero_sa1_physical,
            zero_sa1_mirror,
            zero_snes,
            *late_handles,
        ):
            m.remove_hook(handle)

    summary = {
        "event": "summary",
        "time": time.time(),
        "result": "request_regression" if anomaly is not None else "no_regression",
        "relative_ticks": relative_ticks,
        "wall_seconds": time.monotonic() - wall_start,
        "anomaly": anomaly,
    }
    rows.append(summary)
    with (output / "trace.jsonl").open("x", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row, sort_keys=True) + "\n")
    print(json.dumps(summary, sort_keys=True), flush=True)
    return 0 if anomaly is not None else 2


if __name__ == "__main__":
    raise SystemExit(main())
