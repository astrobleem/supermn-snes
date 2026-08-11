#!/usr/bin/env python3
"""Capture the exact Stage-3 IRQ delivery that diverges at MAME tick 14746.

This is a focused *red-until-fixed* forensic regression.  It starts from an
authenticated post-entry-safe checkpoint at MAME tick 14743, verifies that a
fresh Nexen process restored the complete recorded public state and SA-1 IRAM
before it runs, stops at the third native $025110 collision entry (the update
that maps to tick 14746), then stops immediately before the interpreter's
virtual-IRQ entry.  It never writes ROM, work RAM, IRAM, or a save state; its
only runtime mutation is the real port-0 held-input value recorded by that
checkpoint.

The MAME work-RAM oracle contains the expected task-15 frame.  At the faulty
boundary it is $0259B0 / return $0242BE / SR $2400.  Current SNES reaches the
virtual IRQ only after logical PC $0818, after task 15 was saved at $02429C.
The broader native-off/native-on/MAME gate remains
tools/validate_stage3_irq_order.py; this capture pins the physical delivery
site that a future repair must change without perturbing the task frame.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, "/home/chad/Mesen2/python")

import mesen_mcp.session as _session  # type: ignore  # noqa: E402

_session.validate_mesen_build = lambda *_args, **_kwargs: None

import replay_mame_controller_campaign as campaign  # noqa: E402
import capture_snes_movie_ticks as capture  # noqa: E402


TASK = 15
TASK_CONTEXT_SLOT = 0x000A + TASK * 4
FRAME_REGISTER_NAMES = tuple(
    [f"D{number}" for number in range(8)]
    + [f"A{number}" for number in range(7)]
)
FRAME_REGISTER_BYTES = len(FRAME_REGISTER_NAMES) * 4
FRAME_BYTES = FRAME_REGISTER_BYTES + 2 + 4
NATIVE_25110 = 0x978000
TAKE_IRQ = 0x00B404
YIELD_SITES = {
    "yield_2582a": 0x97E5D9,
    "yield_2582e": 0x97E5E7,
    "yield_259b0": 0x97E5F5,
}
EXPECTED_PC = 0x000259B0
EXPECTED_RETURN = 0x000242BE
EXPECTED_SR = 0x2400

DEFAULT_ROM = ROOT / "build" / "interp.sfc"
DEFAULT_STATE = (
    ROOT
    / "build/fresh-campaign-current-5c7e-resume14743-v1/states/"
    "safe-checkpoint-14743.mss"
)
DEFAULT_MAME_WORK = (
    ROOT
    / "build/mame-current-5c7e-fresh-stage3-irq-v3/"
    "mame-tick-14746.work.bin"
)
DEFAULT_TIMELINE = (
    ROOT
    / "build/playtest-investigation-20260725/full-playback-timeline-v1/"
    "timeline.jsonl"
)
DEFAULT_LINEAGE_EVENTS = (
    ROOT / "build/fresh-campaign-current-5c7e-resume14743-v1/events.jsonl"
)
DEFAULT_NEXEN = Path(
    "/mnt/sdc1/Nexen-r5-20260712/bin/linux-x64/Release/"
    "mcp-safe-checkpoint-publish/Nexen"
)
DEFAULT_STATE_MAME_TICK = 14743


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def le16(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 2], "little")


def be16(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 2], "big")


def be32(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 4], "big")


def exact_address(result: dict[str, Any]) -> int:
    return ((int(result.get("k", 0)) & 0xFF) << 16) | (
        int(result.get("pc", 0)) & 0xFFFF
    )


def exact_stop_ok(result: dict[str, Any], address: int, occurrences: int) -> bool:
    return (
        result.get("reason") == "breakpoint"
        and result.get("hit") is True
        and result.get("isPaused") is True
        and result.get("exactStopTriggered") is True
        and result.get("exactStopBreakDelivered") is True
        and int(result.get("requestedOccurrences", -1)) == occurrences
        and int(result.get("observedOccurrences", -1)) == occurrences
        and exact_address(result) == address
    )


def task15_frame(work: bytes) -> dict[str, Any]:
    if len(work) != 0x10000:
        raise RuntimeError(f"task frame needs 64 KiB work RAM, got {len(work)}")
    saved_sp = be32(work, TASK_CONTEXT_SLOT)
    if saved_sp >> 16 != 0x00F0:
        raise RuntimeError(f"task 15 saved SP outside F0 work RAM: {saved_sp:08X}")
    offset = saved_sp & 0xFFFF
    if offset + FRAME_BYTES + 4 > len(work):
        raise RuntimeError("task 15 frame crosses work-RAM end")
    registers = {
        name: f"{be32(work, offset + index * 4):08X}"
        for index, name in enumerate(FRAME_REGISTER_NAMES)
    }
    sr = be16(work, offset + FRAME_REGISTER_BYTES)
    pc = be32(work, offset + FRAME_REGISTER_BYTES + 2)
    return_pc = be32(work, offset + FRAME_BYTES)
    return {
        "saved_sp": f"{saved_sp:08X}",
        "live_a7": f"{0x00F00000 | (offset + FRAME_BYTES):08X}",
        "registers": registers,
        "sr": f"{sr:04X}",
        "ccr_xnzvc": sr & 0x1F,
        "interrupt_mask": (sr >> 8) & 7,
        "pc": f"{pc:08X}",
        "return_pc": f"{return_pc:08X}",
        "frame_plus_return_hex": work[offset : offset + FRAME_BYTES + 4].hex(),
    }


def snapshot(m: campaign.McpSession) -> dict[str, Any]:
    iram = bytes(m.read_memory("Sa1Memory", 0, 0xB0))
    work = bytes(m.read_memory("snesMemory", 0x400000, 0x10000))
    cpu = dict(m.get_cpu_state("Sa1"))
    logical_pc = le16(iram, 0x40) | ((le16(iram, 0x42) & 0xFF) << 16)
    return {
        "video_frame": int(m.get_state().get("frameCount", 0)),
        "sa1": cpu,
        "logical_pc": f"{logical_pc:06X}",
        "m68k": campaign.register_snapshot(m),
        "virtual_irq": {
            "countdown_00ac": le16(iram, 0xAC),
            "pending_00aa": le16(iram, 0xAA),
        },
        "task15": task15_frame(work),
        "work_sha256": hashlib.sha256(work).hexdigest(),
        "collision_tables_sha256": hashlib.sha256(work[0x3734:0x3CC4]).hexdigest(),
        "player_record_sha256": hashlib.sha256(work[0x12A2:0x1312]).hexdigest(),
        "rng_hex": work[0x170E:0x1710].hex(),
    }


def hook_hits(rows: list[dict[str, Any]], handles: dict[str, int]) -> dict[str, int]:
    by_handle = {handle: name for name, handle in handles.items()}
    counts = {name: 0 for name in handles}
    for row in rows:
        if row.get("method") != "notifications/mesen/hookFired":
            continue
        name = by_handle.get(int(row.get("params", {}).get("handle", -1)))
        if name is not None:
            counts[name] += 1
    return counts


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument(
        "--state-mame-tick",
        type=int,
        default=DEFAULT_STATE_MAME_TICK,
        help="last original-MAME tick completed by --state",
    )
    parser.add_argument(
        "--state-lineage-events",
        type=Path,
        default=DEFAULT_LINEAGE_EVENTS,
        help="authenticated fresh-campaign lineage for --state",
    )
    parser.add_argument("--timeline", type=Path, default=DEFAULT_TIMELINE)
    parser.add_argument("--mame-work", type=Path, default=DEFAULT_MAME_WORK)
    parser.add_argument("--nexen", type=Path, default=DEFAULT_NEXEN)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--port", type=int, default=9280)
    parser.add_argument(
        "--collision-occurrence",
        type=int,
        default=3,
        help="third $025110 entry is MAME tick 14746 from the retained state",
    )
    parser.add_argument("--max-entry-frames", type=int, default=120)
    parser.add_argument("--max-irq-frames", type=int, default=120)
    parser.add_argument(
        "--allow-red",
        action="store_true",
        help="retain the known-failing diagnostic and exit zero",
    )
    args = parser.parse_args()
    for label, path in (
        ("ROM", args.rom),
        ("checkpoint", args.state),
        ("checkpoint IRAM sidecar", args.state.with_suffix(args.state.suffix + ".sa1-iram.bin")),
        ("checkpoint lineage", args.state_lineage_events),
        ("MAME timeline", args.timeline),
        ("MAME tick-14746 work oracle", args.mame_work),
        ("Nexen", args.nexen),
    ):
        if not path.is_file():
            parser.error(f"missing {label}: {path}")
    if args.output.exists():
        parser.error(f"output exists: {args.output}")
    if args.collision_occurrence < 1:
        parser.error("--collision-occurrence must be positive")
    if args.state_mame_tick < 0:
        parser.error("--state-mame-tick must be nonnegative")
    return args


def main() -> int:
    args = parse_args()
    state_resumability = capture.authenticate_start_state(
        state=args.state,
        state_mame_tick=args.state_mame_tick,
        rom=args.rom,
        timeline=args.timeline,
        nexen=args.nexen,
        lineage_events=args.state_lineage_events,
        allow_forensic_nonresumable_state=False,
    )
    if not state_resumability.get("resumable_checkpoint"):
        raise RuntimeError("Stage-3 IRQ delivery requires a resumable checkpoint")
    checkpoint_buttons = int(
        state_resumability["lineage"]["resume_context"]["current_buttons"]
    )
    args.output.mkdir(parents=True)
    campaign.configure_dotnet(args.nexen)
    mame_work = args.mame_work.read_bytes()
    mame_frame = task15_frame(mame_work)
    if (
        int(mame_frame["pc"], 16) != EXPECTED_PC
        or int(mame_frame["return_pc"], 16) != EXPECTED_RETURN
        or int(mame_frame["sr"], 16) != EXPECTED_SR
    ):
        raise RuntimeError(f"unexpected MAME tick-14746 frame: {mame_frame}")

    report: dict[str, Any] = {
        "scope": (
            "forensic exact-stop capture from an authenticated fresh-lineage "
            "Stage-3 safe checkpoint; exact MAME tick-14746 native-on "
            "virtual-IRQ delivery; "
            "not fresh-boot, native-off, FPS, or full-playthrough proof"
        ),
        "classification": "hardware-boundary/virtual-IRQ timing",
        "expected_result": "red until scheduler-safe IRQ delivery is repaired",
        "rom": {"path": str(args.rom.resolve()), "sha256": sha256(args.rom)},
        "pre_failure_state": {
            "path": str(args.state.resolve()),
            "sha256": sha256(args.state),
            "sa1_iram_sidecar": str(
                args.state.with_suffix(args.state.suffix + ".sa1-iram.bin").resolve()
            ),
            "sa1_iram_sidecar_sha256": sha256(
                args.state.with_suffix(args.state.suffix + ".sa1-iram.bin")
            ),
            "retained_not_overwritten": True,
            "mame_tick_completed": args.state_mame_tick,
        },
        "state_resumability": state_resumability,
        "mame_tick_14746": {
            "work": str(args.mame_work.resolve()),
            "work_sha256": sha256(args.mame_work),
            "task15": mame_frame,
        },
        "nexen": campaign.nexen_identity(args.nexen),
        "validator": {"path": str(Path(__file__).resolve()), "sha256": sha256(Path(__file__))},
        "runtime_architectural_mutations": [],
        "time_unix": time.time(),
    }

    with campaign.AuditedMcpSession(
        rom=str(args.rom.resolve()),
        mesen=str(args.nexen.resolve()),
        cwd=ROOT,
        port=args.port,
        boot_wait=8.0,
        socket_timeout=180.0,
        stderr_log=args.output / "nexen.stderr.log",
    ) as m:
        campaign.pause_for_startup(m)
        report["load_state"] = dict(m.load_state(str(args.state.resolve())))
        campaign.require_paused(m, "checkpoint load")
        report["loaded_state_validation"] = capture.validate_loaded_start_state(
            m, state_resumability
        )
        report["initial"] = snapshot(m)
        report["input"] = campaign.set_held_input(m, checkpoint_buttons)

        collision_stop = dict(
            m.tool(
                "run_to_exact_exec_stop",
                {
                    "address": NATIVE_25110,
                    "cpuType": "Sa1",
                    "maxFrames": args.max_entry_frames,
                    "occurrences": args.collision_occurrence,
                },
            )
        )
        campaign.require_paused(m, "collision exact stop")
        report["collision_entry"] = {
            "stop": collision_stop,
            "snapshot": snapshot(m),
        }

        handles = {
            name: m.add_exec_hook(address, cpu_type="Sa1")
            for name, address in YIELD_SITES.items()
        }
        notifications = list(m.drain_notifications(timeout=0.05))
        try:
            irq_stop = dict(
                m.tool(
                    "run_to_exact_exec_stop",
                    {
                        "address": TAKE_IRQ,
                        "cpuType": "Sa1",
                        "maxFrames": args.max_irq_frames,
                        "occurrences": 1,
                    },
                )
            )
            campaign.require_paused(m, "virtual IRQ exact stop")
            irq_snapshot = snapshot(m)
        finally:
            for handle in handles.values():
                m.remove_hook(handle)
            notifications.extend(m.drain_notifications(timeout=0.10))

        report["virtual_irq_entry"] = {
            "address": f"{TAKE_IRQ:06X}",
            "stop": irq_stop,
            "snapshot": irq_snapshot,
            "h25110_midcall_yield_hits": hook_hits(notifications, handles),
        }
        report["runtime_architectural_mutations"] = list(m.architectural_mutations)

    entry = report["collision_entry"]
    irq = report["virtual_irq_entry"]
    irq_snapshot = irq["snapshot"]
    irq_task = irq_snapshot["task15"]
    yield_count = sum(irq["h25110_midcall_yield_hits"].values())
    checks = {
        "checkpoint_load_is_authenticated": bool(
            report["loaded_state_validation"].get("authenticated")
        ),
        "checkpoint_load_used_no_architectural_writes": (
            report["runtime_architectural_mutations"] == []
        ),
        "third_collision_entry_exact": exact_stop_ok(
            entry["stop"], NATIVE_25110, args.collision_occurrence
        ),
        "virtual_irq_entry_exact": exact_stop_ok(irq["stop"], TAKE_IRQ, 1),
        "mame_expected_task15_pc_0259b0": (
            int(mame_frame["pc"], 16) == EXPECTED_PC
        ),
        "mame_expected_return_0242be": (
            int(mame_frame["return_pc"], 16) == EXPECTED_RETURN
        ),
        "mame_expected_sr_2400": int(mame_frame["sr"], 16) == EXPECTED_SR,
        "virtual_irq_reaches_mame_task15_pc": (
            int(irq_task["pc"], 16) == EXPECTED_PC
        ),
        "virtual_irq_reaches_mame_task15_return": (
            int(irq_task["return_pc"], 16) == EXPECTED_RETURN
        ),
        "virtual_irq_reaches_mame_task15_sr": (
            int(irq_task["sr"], 16) == EXPECTED_SR
        ),
        "virtual_irq_delivered_at_mame_resume_pc": (
            int(irq_snapshot["logical_pc"], 16) == EXPECTED_PC
        ),
        "h25110_published_midcall_yield": yield_count > 0,
    }
    report["checks"] = checks
    report["failed_checks"] = [name for name, passed in checks.items() if not passed]
    report["result"] = "green" if all(checks.values()) else "red"
    report["diagnosis"] = {
        "mame_expected_task15_pc": f"{EXPECTED_PC:06X}",
        "snes_task15_pc_at_irq": irq_task["pc"],
        "snes_live_logical_pc_at_irq": irq_snapshot["logical_pc"],
        "h25110_midcall_yield_count": yield_count,
        "interpretation": (
            "The virtual IRQ is delivered only after the task has left the "
            "arcade $025110 mid-call seam. The paired all-native-off gate "
            "also fails at this tick, so this is a scheduler/hardware-boundary "
            "fault rather than a native-only escape semantic fault."
        ),
    }
    output = args.output / "summary.json"
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"result": report["result"], "output": str(output.resolve())}, sort_keys=True))
    return 0 if report["result"] == "green" or args.allow_red else 1


if __name__ == "__main__":
    raise SystemExit(main())
