#!/usr/bin/env python3
"""Measure sustained Stage-3 checkpoint behavior in a caller-selected MCP oracle.

Two independent emulator processes load the same caller-supplied checkpoint.
The control disables both native mechanisms (``$071A=0`` and ``$073A=0``);
the production variant enables both.  Each process receives neutral real
port-0 input in uninterrupted chunks.  The tool retains normalized pre-run
states, final states/screenshots, cycle/tick and frame/tick deltas, route-entry
counts, IRQ/scheduler cadence, renderer progress, and task-stack floors.

The selected ROM's WRAM video-supervisor mirror and its renderer handoff
metadata are explicitly migrated after loading an older compatible checkpoint.
This is checkpointed performance/liveness evidence, not FPS, fresh-boot proof,
or a same-tick whole-game semantic differential.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import trace_playtest_actions as trace
import validate_render_helpers as nexen_base


DEFAULT_ROM = ROOT / "build/interp.sfc"
DEFAULT_STATE = ROOT / "build/playtest/stage3.mss"
DEFAULT_MESEN = ROOT / "tools/mesen211_mcp_controller.sh"
REAL_MESEN = Path("/home/chad/Mesen2/bin/linux-x64/Release/Mesen")

VIDEO_FILE_BASE = 0x298000
VIDEO_WRAM_OFFSET = 0x18000
VIDEO_WRAM_LENGTH = 0x3000
FLOOR_START = 0xC10882
CHUNK = 0x4000

GATE_ADDRS = {
    "loop_072e": 0x072E,
    "xlat_071a": 0x071A,
    "pacing_0734": 0x0734,
    "select_0736": 0x0736,
    "fetch_chokepoint_073a": 0x073A,
    "switch_in_073c": 0x073C,
    "production_latch_0768": 0x0768,
}

SA1_HOOKS = {
    "tick_boundary_00f5a3": 0x00F5A3,
    "take_irq_00b404": 0x00B404,
    "game_tick_92db82": 0x92DB82,
    "scheduler_switch_out_92fa00": 0x92FA00,
    "stage3_027952_94b600": 0x94B600,
    "stage3_0279d2_94bc00": 0x94BC00,
    "stage3_02f3ba_94c200": 0x94C200,
    "stage3_027b44_94cb40": 0x94CB40,
    "stage3_02f56a_94cd00": 0x94CD00,
    "stage3_027b7c_94cec0": 0x94CEC0,
    "stage3_02f5a2_94d100": 0x94D100,
    "stage3_02e49c_94d340": 0x94D340,
    "stage3_0296c6_94d480": 0x94D480,
    "stage3_02e40e_94d540": 0x94D540,
    "stage3_0135e0_94db20": 0x94DB20,
    "stage3_0135e0_direct_94db26": 0x94DB26,
    "stage3_02e4b8_9ddc00": 0x9DDC00,
    "stage3_02e524_9de190": 0x9DE190,
    "stage3_02e42c_9fa140": 0x9FA140,
    "stage3_027912_9fa500": 0x9FA500,
    "stage3_02f2e0_9fa680": 0x9FA680,
    "stage3_00bd1c_9fb000": 0x9FB000,
    "stage3_027aea_9fc000": 0x9FC000,
    "stage3_0278e8_9fd000": 0x9FD000,
    "stage3_013282_9fe000": 0x9FE000,
    "stage3_013314_9fd800": 0x9FD800,
    "stage3_02e676_9fe400": 0x9FE400,
    "stage3_0133ea_9fec00": 0x9FEC00,
    "stage3_01337e_9fba00": 0x9FBA00,
    "stage3_013468_9ff100": 0x9FF100,
    "stage3_013538_9ff700": 0x9FF700,
    "stage3_02f542_9ffe00": 0x9FFE00,
    "ce4_fast_charge_9fe700": 0x9FE700,
    "stage3_box_leaf_9fe800": 0x9FE800,
    "stage3_collision_leaf_9fe900": 0x9FE900,
    "ce4_94fa00": 0x94FA00,
}

NATIVE_HOOK_NAMES = (
    "stage3_027952_94b600",
    "stage3_0279d2_94bc00",
    "stage3_02f3ba_94c200",
    "stage3_027b44_94cb40",
    "stage3_02f56a_94cd00",
    "stage3_027b7c_94cec0",
    "stage3_02f5a2_94d100",
    "stage3_02e49c_94d340",
    "stage3_02e40e_94d540",
    "stage3_0135e0_direct_94db26",
    "stage3_02e4b8_9ddc00",
    "stage3_02e524_9de190",
    "stage3_02e42c_9fa140",
    "stage3_027912_9fa500",
    "stage3_02f2e0_9fa680",
    "stage3_00bd1c_9fb000",
    "stage3_027aea_9fc000",
    "stage3_0278e8_9fd000",
    "stage3_013282_9fe000",
    "stage3_013314_9fd800",
    "stage3_02e676_9fe400",
    "stage3_0133ea_9fec00",
    "stage3_01337e_9fba00",
    "stage3_013468_9ff100",
    "stage3_013538_9ff700",
    "stage3_02f542_9ffe00",
    "ce4_fast_charge_9fe700",
    "stage3_box_leaf_9fe800",
    "stage3_collision_leaf_9fe900",
)

# The collision-record helper inlines $0296C6, and the guarded $013538 parent
# now enters $0135E0 through its direct ABI after reproducing BSR residue
# locally.  Their old public table-dispatch entries must remain quiet in this
# checkpoint while the corresponding fused/direct routes fire.
FUSED_QUIET_HOOK_NAMES = (
    "stage3_0296c6_94d480",
    "stage3_0135e0_94db20",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--mesen", type=Path, default=DEFAULT_MESEN)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--port", type=int, default=9120)
    parser.add_argument(
        "--chunks",
        type=int,
        default=4,
        help="Number of uninterrupted neutral-input commands per variant.",
    )
    parser.add_argument(
        "--frames-per-chunk",
        type=int,
        default=300,
        help=(
            "Requested video frames per command. Exact Mesen may return early "
            "under the MCP command wall-time guard; actual frames are recorded."
        ),
    )
    parser.add_argument(
        "--no-refresh-video-mirror",
        action="store_true",
        help="Do not migrate the selected ROM's video mirror/renderer metadata.",
    )
    parser.add_argument(
        "--no-hooks",
        action="store_true",
        help=(
            "Do not install execution hooks. This removes hook-dispatch cost "
            "from the sustained cadence measurement, but cannot prove native "
            "route coverage."
        ),
    )
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def git_value(*args: str) -> str:
    try:
        return subprocess.check_output(
            ["git", *args],
            cwd=ROOT,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        return "unknown"


def configure_dotnet(executable: Path) -> None:
    """Select the runtime required by the caller-selected emulator."""

    root = "/home/chad/.dotnet10" if executable.name == "Nexen" else "/home/chad/.dotnet8"
    other = "/home/chad/.dotnet8" if root.endswith("10") else "/home/chad/.dotnet10"
    os.environ["DOTNET_ROOT"] = root
    path = [
        item
        for item in os.environ.get("PATH", "").split(":")
        if item and item not in (root, other)
    ]
    os.environ["PATH"] = ":".join([root, other, *path])


def oracle_identity(executable: Path) -> dict[str, str]:
    """Describe the launched emulator without relabeling Nexen as Mesen."""

    if executable.name == "Nexen":
        return {
            "name": "Nexen safe-checkpoint publish",
            "path": str(executable),
            "sha256": sha256(executable),
        }
    return {
        "name": "Mesen 2.1.1",
        "path": str(REAL_MESEN),
        "sha256": sha256(REAL_MESEN),
    }


def le16(data: bytes) -> int:
    return int.from_bytes(data, "little")


def read_u16(m: trace.McpSession, address: int) -> int:
    return le16(m.read_memory("Sa1Memory", address, 2))


def write_u16(m: trace.McpSession, address: int, value: int) -> None:
    m.write_memory(
        "Sa1Memory", address, (value & 0xFFFF).to_bytes(2, "little").hex()
    )


def read_chunks(
    m: trace.McpSession, space: str, address: int, length: int
) -> bytes:
    data = bytearray()
    for offset in range(0, length, CHUNK):
        size = min(CHUNK, length - offset)
        data.extend(m.read_memory(space, address + offset, size))
    return bytes(data)


def hook_events(rows: Iterable[dict[str, Any]]) -> Iterable[dict[str, Any]]:
    for row in rows:
        if row.get("method") == "notifications/mesen/hookFired":
            yield row.get("params", {})


def drain_hook_counts(
    m: trace.McpSession, by_handle: dict[int, str]
) -> Counter[str]:
    counts: Counter[str] = Counter()
    for _attempt in range(12):
        rows = m.drain_notifications(timeout=0.05)
        for params in hook_events(rows):
            label = by_handle.get(int(params.get("handle", -1)))
            if label is not None:
                counts[label] += 1
        if not rows:
            break
    return counts


def cpu_pc(state: dict[str, Any]) -> int:
    return ((int(state.get("k", 0)) & 0xFF) << 16) | (
        int(state.get("pc", 0)) & 0xFFFF
    )


def gates(m: trace.McpSession) -> dict[str, int]:
    return {name: read_u16(m, address) for name, address in GATE_ADDRS.items()}


def floors(m: trace.McpSession) -> list[int]:
    raw = bytes(m.read_memory("snesMemory", FLOOR_START, 16 * 4))
    return [
        int.from_bytes(raw[index * 4 : index * 4 + 4], "big")
        for index in range(16)
    ]


def snapshot(
    m: trace.McpSession,
    stack_floors: list[int],
    label: str,
) -> dict[str, Any]:
    base = trace.snapshot(m, stack_floors, label, -1)
    sa1 = dict(m.get_cpu_state("Sa1"))
    game_ram = read_chunks(m, "snesMemory", 0x400000, 0x10000)
    object_ram = game_ram[0x3000:0x4000]
    renderer_source = read_chunks(m, "snesMemory", 0x412000, 0x3000)
    base.update(
        {
            "sa1_cycles": int(sa1.get("cycleCount", 0)),
            "sa1_step_count": int(sa1.get("instructionCount", 0)),
            "sa1_pc_full": cpu_pc(sa1),
            "gates": gates(m),
            "game_ram_sha256": sha256_bytes(game_ram),
            "object_ram_f03000_f03fff_sha256": sha256_bytes(object_ram),
            "renderer_source_sha256": sha256_bytes(renderer_source),
        }
    )
    return base


def migrate_checkpoint_video(
    m: trace.McpSession, rom_bytes: bytes
) -> list[dict[str, Any]]:
    mirror = rom_bytes[VIDEO_FILE_BASE : VIDEO_FILE_BASE + VIDEO_WRAM_LENGTH]
    if len(mirror) != VIDEO_WRAM_LENGTH:
        raise RuntimeError("selected ROM does not contain the video mirror span")
    old_mirror = bytes(
        m.read_memory("snesWorkRam", VIDEO_WRAM_OFFSET, VIDEO_WRAM_LENGTH)
    )
    for offset in range(0, VIDEO_WRAM_LENGTH, 0x1000):
        m.write_memory(
            "snesWorkRam",
            VIDEO_WRAM_OFFSET + offset,
            mirror[offset : offset + 0x1000].hex(),
        )
    observed = bytes(
        m.read_memory("snesWorkRam", VIDEO_WRAM_OFFSET, VIDEO_WRAM_LENGTH)
    )
    if observed != mirror:
        raise RuntimeError("selected-ROM video mirror migration did not verify")

    old_ready = le16(m.read_memory("snesWorkRam", 0x1F1E, 2))
    frame_ack = read_u16(m, 0x3302)
    m.write_memory(
        "snesWorkRam", 0x1F1E, frame_ack.to_bytes(2, "little").hex()
    )
    if le16(m.read_memory("snesWorkRam", 0x1F1E, 2)) != frame_ack:
        raise RuntimeError("renderer ready-sequence migration did not verify")

    bg_dirty = le16(m.read_memory("snesMemory", 0x410140, 2))
    old_status = le16(m.read_memory("snesMemory", 0x41014C, 2))
    old_length = le16(m.read_memory("snesMemory", 0x41014E, 2))
    producer_status = 0xFFFF if bg_dirty else 0
    m.write_memory(
        "snesMemory",
        0x41014C,
        producer_status.to_bytes(2, "little").hex(),
    )
    m.write_memory("snesMemory", 0x41014E, "0000")
    return [
        {
            "kind": "checkpoint_video_mirror_refresh",
            "region": "snesWorkRam $7F:8000-$AFFF",
            "length": VIDEO_WRAM_LENGTH,
            "differing_bytes": sum(
                left != right for left, right in zip(old_mirror, mirror)
            ),
            "sha256": sha256_bytes(mirror),
        },
        {
            "kind": "renderer_ready_sequence_normalization",
            "address": "7E:1F1E",
            "before": old_ready,
            "frame_ack_4003302": frame_ack,
            "after": frame_ack,
        },
        {
            "kind": "bg_producer_metadata_normalization",
            "dirty_410140": bg_dirty,
            "status_41014c_before": old_status,
            "length_41014e_before": old_length,
            "status_41014c_after": producer_status,
            "length_41014e_after": 0,
        },
    ]


def delta(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    tick_delta = (int(after["tick"]) - int(before["tick"])) & 0xFFFF
    frame_delta = int(after["frame"]) - int(before["frame"])
    cycle_delta = int(after["sa1_cycles"]) - int(before["sa1_cycles"])
    ack_delta = (
        int(after["frame_ack"]) - int(before["frame_ack"])
    ) & 0xFFFF
    request_delta = (
        int(after["frame_request"]) - int(before["frame_request"])
    ) & 0xFFFF
    render_delta = (
        int(after["render_generation"]) - int(before["render_generation"])
    ) & 0xFFFF
    return {
        "ticks": tick_delta,
        "video_frames": frame_delta,
        "sa1_cycles": cycle_delta,
        "frame_requests": request_delta,
        "frame_acks": ack_delta,
        "render_generations": render_delta,
        "cycles_per_tick": cycle_delta / tick_delta if tick_delta else None,
        "video_frames_per_tick": frame_delta / tick_delta if tick_delta else None,
        "requests_per_tick": request_delta / tick_delta if tick_delta else None,
        "acks_per_tick": ack_delta / tick_delta if tick_delta else None,
    }


def capture_variant(
    *,
    name: str,
    gate: int,
    args: argparse.Namespace,
    rom_bytes: bytes,
    port: int,
) -> dict[str, Any]:
    variant_dir = args.output / name
    variant_dir.mkdir()
    interventions: list[dict[str, Any]] = []
    # ``trace_playtest_actions`` imports the legacy .NET-8 client at module
    # import time.  It cannot establish a socket to the supported safe Nexen
    # fork, despite this harness accepting a caller-selected emulator.  The
    # render validator owns the compatible client shim (with the exact-build
    # guard intentionally bypassed for Nexen), and its session API is the
    # same here.  Keep the trace helpers for snapshots/state metadata only.
    with nexen_base.McpSession(
        rom=args.rom,
        mesen=args.mesen,
        cwd=ROOT,
        port=port,
        boot_wait=6.0,
        socket_timeout=300.0,
        stderr_log=variant_dir / "mesen.stderr.log",
    ) as m:
        m.pause()
        m.load_state(args.state)
        m.pause()
        if not args.no_refresh_video_mirror:
            interventions.extend(migrate_checkpoint_video(m, rom_bytes))

        old_xlat = read_u16(m, 0x071A)
        old_choke = read_u16(m, 0x073A)
        write_u16(m, 0x071A, gate)
        write_u16(m, 0x073A, gate)
        interventions.append(
            {
                "kind": "native_configuration",
                "xlat_071a_before": old_xlat,
                "fetch_chokepoint_073a_before": old_choke,
                "xlat_071a_after": gate,
                "fetch_chokepoint_073a_after": gate,
            }
        )

        stack_floors = floors(m)
        before = snapshot(m, stack_floors, f"{name}/before")
        before_state = trace.save_state(m, variant_dir / "pre-run.mss")
        before_screen = trace.take_screenshot(m, variant_dir / "pre-run.png")

        handles = (
            {
                label: m.add_exec_hook(address, cpu_type="Sa1")
                for label, address in SA1_HOOKS.items()
            }
            if not args.no_hooks
            else {}
        )
        by_handle = {handle: label for label, handle in handles.items()}
        m.drain_notifications(timeout=0.05)
        counts: Counter[str] = Counter()
        chunks: list[dict[str, Any]] = []
        wall_start = time.monotonic()
        try:
            for index in range(args.chunks):
                frame_before = int(m.get_state().get("frameCount", 0))
                response = m.set_input(0, args.frames_per_chunk)
                m.pause()
                frame_after = int(m.get_state().get("frameCount", 0))
                observed = drain_hook_counts(m, by_handle)
                counts.update(observed)
                chunks.append(
                    {
                        "index": index,
                        "requested_video_frames": args.frames_per_chunk,
                        "actual_video_frames": frame_after - frame_before,
                        "input_response": response,
                        "hook_counts": dict(sorted(observed.items())),
                    }
                )
        finally:
            counts.update(drain_hook_counts(m, by_handle))
            for handle in handles.values():
                m.remove_hook(handle)
        wall_seconds = time.monotonic() - wall_start

        after = snapshot(m, stack_floors, f"{name}/after")
        after_state = trace.save_state(m, variant_dir / "post-run.mss")
        after_screen = trace.take_screenshot(m, variant_dir / "post-run.png")

    run_delta = delta(before, after)
    native_counts = (
        {label: counts[label] for label in NATIVE_HOOK_NAMES}
        if not args.no_hooks
        else None
    )
    fused_quiet_counts = (
        {label: counts[label] for label in FUSED_QUIET_HOOK_NAMES}
        if not args.no_hooks
        else None
    )
    gates_stable = (
        after["gates"]["xlat_071a"] == gate
        and after["gates"]["fetch_chokepoint_073a"] == gate
    )
    route_expectation = (
        (
            all(count == 0 for count in native_counts.values())
            and all(count == 0 for count in fused_quiet_counts.values())
            if gate == 0
            else (
                all(count > 0 for count in native_counts.values())
                and all(count == 0 for count in fused_quiet_counts.values())
            )
        )
        if not args.no_hooks
        else None
    )
    healthy = (
        run_delta["ticks"] > 0
        and run_delta["frame_acks"] > 0
        and int(after["halt"]) == 0
        and not after["invalid"]
        and gates_stable
        and (route_expectation is not False)
    )
    return {
        "name": name,
        "configuration": {
            "xlat_gate_071a": gate,
            "fetch_chokepoint_gate_073a": gate,
            "execution_hook_instrumentation": not args.no_hooks,
        },
        "interventions": interventions,
        "before": before,
        "after": after,
        "delta": run_delta,
        "hook_counts": dict(sorted(counts.items())),
        "native_route_counts": native_counts,
        "fused_quiet_route_counts": fused_quiet_counts,
        "chunks": chunks,
        "wall_seconds_informational": wall_seconds,
        "pre_run_state": before_state,
        "post_run_state": after_state,
        "pre_run_screenshot": before_screen,
        "post_run_screenshot": after_screen,
        "gates_stable": gates_stable,
        "native_route_expectation_met": route_expectation,
        "result": "green" if healthy else "red",
    }


def main() -> int:
    args = parse_args()
    args.rom = args.rom.resolve()
    args.state = args.state.resolve()
    args.mesen = args.mesen.resolve()
    args.output = args.output.resolve()
    if args.chunks <= 0 or args.frames_per_chunk <= 0:
        raise SystemExit("chunk count and frame count must be positive")
    required_paths = [
        ("ROM", args.rom),
        ("state", args.state),
        ("Mesen controller", args.mesen),
    ]
    if args.mesen.name != "Nexen":
        required_paths.append(("exact Mesen binary", REAL_MESEN))
    for label, path in required_paths:
        if not path.is_file() or path.stat().st_size == 0:
            raise FileNotFoundError(f"{label} not found: {path}")
    if args.output.exists():
        raise SystemExit(f"refusing existing output: {args.output}")
    if int.from_bytes(args.rom.read_bytes()[0x77E0:0x77E2], "little") != 0:
        raise SystemExit("refusing non-production ROM: TESTFLAG is set")
    args.output.mkdir(parents=True)
    # Select the runtime for the requested oracle.  Forcing the legacy
    # .NET-8 setting here prevents the supported Nexen publish from starting,
    # leaving a misleading socket-timeout artifact instead of a measurement.
    configure_dotnet(args.mesen)
    rom_bytes = args.rom.read_bytes()

    oracle = oracle_identity(args.mesen)
    provenance = {
        "scope": (
            "checkpointed %s Stage-3 sustained liveness/performance "
            "A/B with neutral real port-0 input; cycles/tick and frames/tick, "
            "not FPS, fresh-boot proof, or whole-game same-tick semantics"
        ) % oracle["name"],
        "project_commit": git_value("rev-parse", "HEAD"),
        "project_status": git_value("status", "--short").splitlines(),
        "rom": str(args.rom),
        "rom_sha256": sha256(args.rom),
        "state": str(args.state),
        "state_sha256": sha256(args.state),
        "oracle": oracle,
        "requested_chunks": args.chunks,
        "requested_frames_per_chunk": args.frames_per_chunk,
        "video_mirror_migration": not args.no_refresh_video_mirror,
        "input": "neutral controller through MCP set_input",
    }
    print(json.dumps({"event": "provenance", **provenance}, sort_keys=True))

    variants = [
        capture_variant(
            name="all_native_off",
            gate=0,
            args=args,
            rom_bytes=rom_bytes,
            port=args.port,
        ),
        capture_variant(
            name="production_native_on",
            gate=1,
            args=args,
            rom_bytes=rom_bytes,
            port=args.port + 1,
        ),
    ]
    off, on = variants
    off_cpt = off["delta"]["cycles_per_tick"]
    on_cpt = on["delta"]["cycles_per_tick"]
    speedup = off_cpt / on_cpt if off_cpt and on_cpt else None
    result = (
        "green"
        if all(variant["result"] == "green" for variant in variants)
        else "red"
    )
    summary = {
        **provenance,
        "variants": variants,
        "comparison": {
            "all_native_off_cycles_per_tick": off_cpt,
            "production_native_on_cycles_per_tick": on_cpt,
            "native_on_speedup_ratio": speedup,
            "budget_cycles_per_tick": 358000,
            "production_meets_budget": (
                on_cpt is not None and on_cpt <= 358000
            ),
            "semantic_scope": (
                "focused handler semantics are owned by "
                "validate_stage3_hot_handlers.py; this run compares sustained "
                "liveness/cadence and intentionally does not compare end RAM "
                "because equal video time advances unequal game ticks"
            ),
        },
        "result": result,
    }
    summary_path = args.output / "summary.json"
    summary_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "event": "summary",
                "result": result,
                "all_native_off_cycles_per_tick": off_cpt,
                "production_native_on_cycles_per_tick": on_cpt,
                "native_on_speedup_ratio": speedup,
                "production_meets_budget": summary["comparison"][
                    "production_meets_budget"
                ],
                "summary": str(summary_path),
            },
            sort_keys=True,
        ),
        flush=True,
    )
    return 0 if result == "green" else 2


if __name__ == "__main__":
    raise SystemExit(main())
