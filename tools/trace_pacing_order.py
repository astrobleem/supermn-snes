#!/usr/bin/env python3
"""Trace the scheduler ordering failure from a healthy pacing-lab checkpoint.

This is a diagnostic harness, not an FPS measurement.  It leaves the ROM and
game state untouched, installs non-pausing cycle-stamped hooks, and resumes an
already-driven gameplay checkpoint.  The trace combines the interpreter's
always-on 68K PC ring with writes to the task mask, the $2A48/$2A49 producer
flags, and the $1C9A handler pointer.  That makes the last producer/consumer
ordering before a $080100/$DEAD derail reconstructable without a debugger stop
changing the emulated schedule.
"""

from __future__ import annotations

import argparse
import bisect
import hashlib
import json
import os
import statistics
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, "/home/chad/Mesen2/python")

import mesen_mcp.session as _session

_session.validate_mesen_build = lambda *_args, **_kwargs: None
from mesen_mcp import McpSession

from profile_continuous import EXPECTED_GATES, GATE_ADDRS, configure_dotnet
from profile_tick_ring import hook_notifications, parse_ring_writes


DEFAULT_ROM = ROOT / "build/playability-20260719/nmi-hle-lab/interp_vsync_lab.sfc"
DEFAULT_STATE = (
    ROOT / "build/recovery-20260712/r5-idle-vsync-nmi-soak-smoke/final.mss"
)
DEFAULT_NEXEN = Path(
    "/mnt/sdc1/Nexen-r5-20260712/"
    "bin/linux-x64/Release/linux-x64/publish/Nexen"
)
DEFAULT_OUTPUT = ROOT / "build/pacing-order-trace"

LAB_MARKER_OFFSET = 0x2CFF00
LAB_MARKERS = (b"R5VSYNC1", b"R5VNMI01", b"R5VNMI02", b"R5VNMI03")
RING_START = 0x000400
RING_END = 0x0005FF
CLAMP = 0x00F5A3
TAKE_IRQ = 0x00B404
ENTRY_3A92 = 0x92DC3B
ENTRY_CD1A = 0x99AACF
KBAD_HALT = 0x008BA7
TASK_MASK_START = 0x400002
TASK_MASK_END = 0x400003
TASK_CONTEXT_START = 0x40000A
TASK_CONTEXT_END = 0x40008D
HANDLER_POINTER_START = 0x401C9A
HANDLER_POINTER_END = 0x401C9D
PRODUCER_FLAGS_START = 0x402A48
PRODUCER_FLAGS_END = 0x402A49
SOUND_RING_START = 0x00F01C20
SOUND_RING_END = 0x00F01C40


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--nexen", type=Path, default=DEFAULT_NEXEN)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--port", type=int, default=7610)
    parser.add_argument(
        "--target-ticks",
        type=int,
        default=200,
        help="Maximum additional clamp ticks to trace before a clean stop.",
    )
    parser.add_argument("--timeout", type=float, default=600.0)
    parser.add_argument("--poll-seconds", type=float, default=0.03)
    parser.add_argument(
        "--context-events",
        type=int,
        default=600,
        help="Maximum final special events retained with nearby 68K PCs.",
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


def le16(data: bytes) -> int:
    return data[0] | (data[1] << 8)


def le32(data: bytes) -> int:
    return le16(data) | (le16(data[2:]) << 16)


def modular_delta(now: int, before: int, bits: int = 16) -> int:
    return (now - before) & ((1 << bits) - 1)


def stack_snapshot(m: McpSession, floors: list[int], a5: int) -> dict[str, Any]:
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
    for index, floor in enumerate(floors):
        saved_sp = int.from_bytes(
            m.read_memory("snesMemory", 0x400000 + base + 0x0A + index * 4, 4),
            "big",
        )
        descriptor = int.from_bytes(
            m.read_memory("snesMemory", 0x400000 + base + 0x4E + index * 4, 4),
            "big",
        )
        if saved_sp == 0:
            continue
        tasks.append(
            {
                "index": index,
                "descriptor": descriptor,
                "saved_sp": saved_sp,
                "floor": floor,
                "margin": saved_sp - floor,
            }
        )
    return {
        "a5": a5,
        "initialized": len(tasks),
        "minimum_margin": min((task["margin"] for task in tasks), default=None),
        "below_floor": [task for task in tasks if task["margin"] < 0],
        "tasks": tasks,
    }


def coherent_snapshot(m: McpSession, floors: list[int]) -> dict[str, Any]:
    state = m.get_state()
    cpu = m.get_cpu_state("Sa1")
    a5 = le32(m.read_memory("Sa1Memory", 0x0034, 4)) & 0xFFFFFF
    ring_pointer = int.from_bytes(
        m.read_memory("snesMemory", 0x401C40, 4), "big"
    )
    return {
        "frame": int(state.get("frameCount", 0)),
        "tick": le16(m.read_memory("Sa1Memory", 0x0760, 2)),
        "pc68k": le32(m.read_memory("Sa1Memory", 0x0040, 4)) & 0xFFFFFF,
        "steps": le32(m.read_memory("Sa1Memory", 0x004A, 4)),
        "opcode": le16(m.read_memory("Sa1Memory", 0x0044, 2)),
        "halt": le16(m.read_memory("Sa1Memory", 0x004E, 2)),
        "ac": le16(m.read_memory("Sa1Memory", 0x00AC, 2)),
        "task_mask": le16(m.read_memory("snesMemory", TASK_MASK_START, 2)),
        "handler_pointer": m.read_memory(
            "snesMemory", HANDLER_POINTER_START, 4
        ).hex(),
        "producer_flags": m.read_memory(
            "snesMemory", PRODUCER_FLAGS_START, 2
        ).hex(),
        "sound_ring_pointer": f"{ring_pointer:08x}",
        "gates": {
            name: le16(m.read_memory("Sa1Memory", address, 2))
            for name, address in GATE_ADDRS.items()
        },
        "lab_gate": le16(m.read_memory("Sa1Memory", 0x0734, 2)),
        "sa1_cycles": int(cpu.get("cycleCount", 0)),
        "sa1_pc": (int(cpu.get("k", 0)) << 16) | int(cpu.get("pc", 0)),
        "stack": stack_snapshot(m, floors, a5),
        "task_context_bytes": m.read_memory(
            "snesMemory", TASK_CONTEXT_START, TASK_CONTEXT_END - TASK_CONTEXT_START + 1
        ).hex(),
    }


def require_healthy_start(state: dict[str, Any]) -> None:
    ring = int(state["sound_ring_pointer"], 16)
    if state["halt"] != 0:
        raise RuntimeError(f"checkpoint halt word is ${state['halt']:04X}")
    if state["gates"] != EXPECTED_GATES or state["lab_gate"] != 1:
        raise RuntimeError(
            f"checkpoint gate mismatch: {state['gates']}, lab={state['lab_gate']}"
        )
    if not SOUND_RING_START <= ring <= SOUND_RING_END:
        raise RuntimeError(f"checkpoint sound pointer is ${ring:08X}")
    if state["stack"]["below_floor"]:
        raise RuntimeError(
            f"checkpoint task stack is below floor: {state['stack']['below_floor']}"
        )


def event_contexts(
    special: list[dict[str, Any]],
    pcs: list[dict[str, int]],
    clamps: list[dict[str, Any]],
    start_tick: int,
    limit: int,
) -> list[dict[str, Any]]:
    pc_cycles = [int(row["cycle"]) for row in pcs]
    clamp_cycles = [int(row["cycleCount"]) for row in clamps]
    output = []
    for event in special[-limit:]:
        cycle = int(event["cycleCount"])
        pc_index = bisect.bisect_right(pc_cycles, cycle) - 1
        clamp_count = bisect.bisect_right(clamp_cycles, cycle)
        context = pcs[max(0, pc_index - 8) : min(len(pcs), pc_index + 5)]
        output.append(
            {
                **event,
                "tick_unwrapped": start_tick + clamp_count,
                "nearest_pc_index": pc_index,
                "nearby_68k_pcs": [
                    {
                        "pc": f"{row['pc']:06X}",
                        "cycle": row["cycle"],
                        "delta": int(row["cycle"]) - cycle,
                    }
                    for row in context
                ],
            }
        )
    return output


def main() -> int:
    args = parse_args()
    if args.target_ticks <= 0 or args.timeout <= 0:
        raise SystemExit("--target-ticks and --timeout must be positive")
    if not 0 < args.poll_seconds <= 1:
        raise SystemExit("--poll-seconds must be in (0, 1]")

    rom = args.rom.resolve()
    state_path = args.state.resolve()
    nexen = args.nexen.resolve()
    output = args.output.resolve()
    if not rom.is_file() or rom.stat().st_size != 0x400000:
        raise SystemExit(f"expected a 4 MiB ROM: {rom}")
    if not state_path.is_file() or not nexen.is_file():
        raise SystemExit("checkpoint or Nexen executable is missing")
    marker = rom.read_bytes()[LAB_MARKER_OFFSET : LAB_MARKER_OFFSET + 8]
    if marker not in LAB_MARKERS:
        raise SystemExit(f"unmarked pacing lab ROM: {marker!r}")
    output.mkdir(parents=True, exist_ok=False)
    raw_path = output / "hooks.jsonl"
    summary_path = output / "summary.json"
    stderr_path = output / "nexen.stderr.log"

    configure_dotnet(nexen)
    raw_stream = raw_path.open("x", encoding="utf-8")
    hooks_by_label: dict[str, list[dict[str, Any]]] = {}
    start_wall = time.monotonic()
    stop_reason = "exception"
    start: dict[str, Any] | None = None
    end: dict[str, Any] | None = None

    try:
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
            floor_bytes = m.read_memory("snesMemory", 0xC10882, 16 * 4)
            floors = [
                int.from_bytes(floor_bytes[index * 4 : index * 4 + 4], "big")
                for index in range(16)
            ]
            start = coherent_snapshot(m, floors)
            require_healthy_start(start)
            print(json.dumps({"event": "start", **start}, sort_keys=True), flush=True)

            handles = {
                "pc_ring_write": m.add_write_hook(
                    RING_START, RING_END, cpu_type="Sa1"
                ),
                "clamp": m.add_exec_hook(CLAMP, cpu_type="Sa1"),
                "take_irq": m.add_exec_hook(TAKE_IRQ, cpu_type="Sa1"),
                "entry_3a92": m.add_exec_hook(ENTRY_3A92, cpu_type="Sa1"),
                "entry_cd1a": m.add_exec_hook(ENTRY_CD1A, cpu_type="Sa1"),
                "kbad_halt": m.add_exec_hook(KBAD_HALT, cpu_type="Sa1"),
                "task_mask_write": m.add_write_hook(
                    TASK_MASK_START, TASK_MASK_END, cpu_type="Sa1"
                ),
                "task_context_write": m.add_write_hook(
                    TASK_CONTEXT_START, TASK_CONTEXT_END, cpu_type="Sa1"
                ),
                "handler_pointer_write": m.add_write_hook(
                    HANDLER_POINTER_START, HANDLER_POINTER_END, cpu_type="Sa1"
                ),
                "producer_flags_write": m.add_write_hook(
                    PRODUCER_FLAGS_START, PRODUCER_FLAGS_END, cpu_type="Sa1"
                ),
            }
            by_handle = {handle: label for label, handle in handles.items()}
            m.drain_notifications(timeout=0.05)
            m.resume()
            last_heartbeat = time.monotonic()

            while time.monotonic() - start_wall < args.timeout:
                for params in hook_notifications(
                    m.drain_notifications(timeout=args.poll_seconds)
                ):
                    label = by_handle.get(int(params.get("handle", -1)))
                    if label is None:
                        continue
                    row = {"label": label, **params}
                    raw_stream.write(json.dumps(row, sort_keys=True) + "\n")
                    hooks_by_label.setdefault(label, []).append(row)
                raw_stream.flush()

                halt = le16(m.read_memory("Sa1Memory", 0x004E, 2))
                tick = le16(m.read_memory("Sa1Memory", 0x0760, 2))
                delta = modular_delta(tick, start["tick"])
                if halt != 0:
                    stop_reason = f"halt_{halt:04x}"
                    break
                if delta >= args.target_ticks:
                    stop_reason = "target_ticks"
                    break

                now = time.monotonic()
                if now - last_heartbeat >= 10:
                    print(
                        json.dumps(
                            {
                                "event": "heartbeat",
                                "wall_seconds": now - start_wall,
                                "tick": tick,
                                "tick_delta": delta,
                                "hook_events": sum(
                                    len(rows) for rows in hooks_by_label.values()
                                ),
                            },
                            sort_keys=True,
                        ),
                        flush=True,
                    )
                    last_heartbeat = now
                time.sleep(min(0.01, args.poll_seconds))
            else:
                stop_reason = "timeout"

            m.pause()
            for params in hook_notifications(m.drain_notifications(timeout=0.3)):
                label = by_handle.get(int(params.get("handle", -1)))
                if label is None:
                    continue
                row = {"label": label, **params}
                raw_stream.write(json.dumps(row, sort_keys=True) + "\n")
                hooks_by_label.setdefault(label, []).append(row)
            raw_stream.flush()
            for handle in handles.values():
                m.remove_hook(handle)
            end = coherent_snapshot(m, floors)
            m.save_state(output / "final.mss")
    finally:
        raw_stream.close()

    assert start is not None and end is not None
    pc_rows, malformed, unrelated = parse_ring_writes(
        hooks_by_label.get("pc_ring_write", [])
    )
    clamps = sorted(
        hooks_by_label.get("clamp", []), key=lambda row: int(row["cycleCount"])
    )
    special = sorted(
        [
            row
            for label, rows in hooks_by_label.items()
            if label != "pc_ring_write"
            for row in rows
        ],
        key=lambda row: int(row["cycleCount"]),
    )
    contexts = event_contexts(
        special, pc_rows, clamps, int(start["tick"]), args.context_events
    )
    interval_cycles = [
        int(right["cycleCount"]) - int(left["cycleCount"])
        for left, right in zip(clamps, clamps[1:])
    ]
    summary = {
        "scope": "checkpointed non-pausing scheduler-order trace; not fps",
        "stop_reason": stop_reason,
        "wall_seconds": time.monotonic() - start_wall,
        "project_commit": git_value("rev-parse", "HEAD"),
        "project_status": git_value("status", "--porcelain=v1").splitlines(),
        "rom": str(rom),
        "rom_sha256": sha256(rom),
        "marker": marker.decode("ascii"),
        "state": str(state_path),
        "state_sha256": sha256(state_path),
        "nexen": str(nexen),
        "nexen_sha256": sha256(nexen),
        "runtime_pokes": [],
        "hooks_pause_cpu": False,
        "hook_addresses": {
            "pc_ring": f"{RING_START:06X}-{RING_END:06X}",
            "clamp": f"{CLAMP:06X}",
            "take_irq": f"{TAKE_IRQ:06X}",
            "entry_3a92": f"{ENTRY_3A92:06X}",
            "entry_cd1a": f"{ENTRY_CD1A:06X}",
            "kbad_halt": f"{KBAD_HALT:06X}",
            "task_mask": f"{TASK_MASK_START:06X}-{TASK_MASK_END:06X}",
            "task_context": f"{TASK_CONTEXT_START:06X}-{TASK_CONTEXT_END:06X}",
            "handler_pointer": (
                f"{HANDLER_POINTER_START:06X}-{HANDLER_POINTER_END:06X}"
            ),
            "producer_flags": (
                f"{PRODUCER_FLAGS_START:06X}-{PRODUCER_FLAGS_END:06X}"
            ),
        },
        "start": start,
        "end": end,
        "tick_delta": modular_delta(int(end["tick"]), int(start["tick"])),
        "hook_counts": {
            label: len(rows) for label, rows in sorted(hooks_by_label.items())
        },
        "pc_records": len(pc_rows),
        "malformed_pc_ring_edge_bytes": malformed,
        "unrelated_pc_ring_range_writes": unrelated,
        "pc_top": [
            {"pc": f"{pc:06X}", "count": count}
            for pc, count in Counter(row["pc"] for row in pc_rows).most_common(40)
        ],
        "clamp_interval_cycles": {
            "count": len(interval_cycles),
            "min": min(interval_cycles, default=None),
            "max": max(interval_cycles, default=None),
            "mean": statistics.mean(interval_cycles) if interval_cycles else None,
            "median": statistics.median(interval_cycles) if interval_cycles else None,
        },
        "final_event_contexts": contexts,
    }
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    print(
        json.dumps(
            {
                "event": "summary",
                "stop_reason": stop_reason,
                "tick_delta": summary["tick_delta"],
                "start_tick": start["tick"],
                "end_tick": end["tick"],
                "start_task_mask": start["task_mask"],
                "end_task_mask": end["task_mask"],
                "end_pc68k": f"{end['pc68k']:06X}",
                "end_halt": f"{end['halt']:04X}",
                "minimum_stack_margin": end["stack"]["minimum_margin"],
                "sound_ring_pointer": end["sound_ring_pointer"],
                "pc_records": len(pc_rows),
                "hook_counts": summary["hook_counts"],
                "summary": str(summary_path),
            },
            sort_keys=True,
        ),
        flush=True,
    )
    return 0 if stop_reason == "target_ticks" else 2


if __name__ == "__main__":
    raise SystemExit(main())
