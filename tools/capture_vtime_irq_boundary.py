#!/usr/bin/env python3
"""Capture one VTIME IRQ boundary from an authenticated campaign checkpoint.

The controller campaign normally samples exact ``$003A92`` update entries.
This focused diagnostic advances to one selected entry with the same input
ordering, then stops at the next virtual-IRQ dispatcher entry.  It records the
VTIME state and task-15 frame on both sides of that interval and compares the
IRQ-side frame with an exact original-MAME work-RAM oracle.

The tool performs no ROM, work-RAM, IRAM, or game-state writes.  Its sole
architectural mutation is the real held controller value from the retained
movie.  The result is checkpoint-local timing evidence, never fresh-boot,
rate, or full-playthrough proof.
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

import replay_mame_controller_campaign as campaign  # noqa: E402
import capture_snes_movie_ticks as capture  # noqa: E402
import capture_stage3_irq_delivery as delivery  # noqa: E402


TAKE_IRQ = 0x00B404
VTIME_BASE = 0x404000
VTIME_DUE_SITES = {
    "interpreter_consume_due": 0xF28474,
    "esc3_charge_due": 0xF2866A,
    "charge_units_due": 0xF2873D,
    "esc3_finish_due": 0xF28854,
    "esc5_charge_due": 0xF2896D,
    "esc5_finish_due": 0xF28B3A,
    "esc9_charge_due": 0xF2B184,
    "esc9_finish_due": 0xF2B334,
    "choke_due": 0xF2B4C0,
    "native_handoff_due": 0xF2FE8B,
}
ROOT_TRACE_SITES = {
    "root_entry": 0xF38000,
    "root_charge_gateway": 0xF38926,
    "root_charge_due": 0xF38932,
    "root_child_handoff": 0xF38938,
    "root_terminal_handoff": 0xF38945,
    "root_return_dispatch": 0xF3894F,
    "root_return_miss": 0xF389F7,
    "root_return_normal": 0xF38A01,
    "root_return_interpret": 0xF38A0A,
    "esc5_charge_entry": 0xF28900,
    "esc5_finish_entry": 0xF28B00,
    "collision_native_entry": 0x978000,
    "esc3_charge_entry": 0xF28600,
    "esc3_reset_entry": 0xF28800,
    "esc3_finish_entry": 0xF28820,
}
VTIME_WORDS = (
    "magic",
    "valid",
    "cost",
    "remain_lo",
    "remain_hi",
    "phase",
    "overshoot",
    "opcode",
    "condition",
    "tmp",
    "native_pending",
    "native_current",
    "due",
    "native_owner",
)
MAME_ORIGIN_TICK = 221


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def vtime_snapshot(m: campaign.McpSession) -> dict[str, Any]:
    raw = bytes(m.read_memory("snesMemory", VTIME_BASE, len(VTIME_WORDS) * 2))
    words = {
        name: int.from_bytes(raw[index * 2 : index * 2 + 2], "little")
        for index, name in enumerate(VTIME_WORDS)
    }
    words["remaining_two_cycle_units"] = (
        (words["remain_hi"] << 16) | words["remain_lo"]
    )
    words["raw_hex"] = raw.hex()
    return words


def boundary_snapshot(m: campaign.McpSession) -> dict[str, Any]:
    result = delivery.snapshot(m)
    scheduler = bytes(m.read_memory("snesMemory", 0x400000, 6))
    result["snes_tick"] = campaign.tick16(m)
    result["scheduler"] = {
        "task_mask_f00002": int.from_bytes(scheduler[2:4], "big"),
        "current_task_f00004": int.from_bytes(scheduler[4:6], "big"),
    }
    result["vtime"] = vtime_snapshot(m)
    return result


def exec_hits(
    rows: list[dict[str, Any]], handles: dict[str, int]
) -> list[dict[str, Any]]:
    by_handle = {handle: name for name, handle in handles.items()}
    hits: list[dict[str, Any]] = []
    for row in rows:
        if row.get("method") != "notifications/mesen/hookFired":
            continue
        params = row.get("params", {})
        name = by_handle.get(int(params.get("handle", -1)))
        if name is None:
            continue
        hits.append(
            {
                "site": name,
                "address": f"{int(params.get('address', 0)):06X}",
                "frame": int(params.get("frame", 0)),
                "cycle_count": int(params.get("cycleCount", 0)),
            }
        )
    return hits


def active_entry_inventory(path: Path) -> dict[str, int]:
    report = json.loads(path.read_text(encoding="utf-8"))
    hooks: dict[str, int] = {}
    for label, count in dict(report.get("event_counts", {})).items():
        if not int(count) or "@" not in str(label):
            continue
        address_text = str(label).rsplit("@", 1)[1]
        hooks[str(label)] = int(address_text, 16)
    if not hooks:
        raise RuntimeError(f"entry-hook inventory has no active addressed entries: {path}")
    return hooks


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--state-mame-tick", type=int, required=True)
    parser.add_argument("--state-lineage-events", type=Path, required=True)
    parser.add_argument("--timeline", type=Path, default=campaign.DEFAULT_TIMELINE)
    parser.add_argument("--mame-work", type=Path, required=True)
    parser.add_argument("--target-mame-tick", type=int, required=True)
    parser.add_argument("--nexen", type=Path, default=campaign.DEFAULT_NEXEN)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--port", type=int, default=9540)
    parser.add_argument("--max-irq-frames", type=int, default=420)
    parser.add_argument(
        "--due-stop-address",
        type=lambda value: int(value, 0),
        help=(
            "optionally stop at one exact VTIME due-path PC before continuing "
            "to the virtual IRQ entry"
        ),
    )
    parser.add_argument(
        "--intermediate-stop-address",
        type=lambda value: int(value, 0),
        help=(
            "optionally stop at one exact SA-1 PC after the target entry and "
            "before continuing to the virtual IRQ entry"
        ),
    )
    parser.add_argument(
        "--pre-intermediate-hook-inventory",
        type=Path,
        help=(
            "trace the nonzero addressed event_counts from a retained native-entry "
            "inventory until --intermediate-stop-address is reached"
        ),
    )
    parser.add_argument(
        "--allow-red",
        action="store_true",
        help="retain a failing timing report with a zero process exit",
    )
    args = parser.parse_args()
    if args.target_mame_tick <= args.state_mame_tick:
        parser.error("target tick must follow the completed checkpoint tick")
    if args.max_irq_frames <= 0:
        parser.error("--max-irq-frames must be positive")
    if (
        args.due_stop_address is not None
        and args.intermediate_stop_address is not None
    ):
        parser.error(
            "--due-stop-address and --intermediate-stop-address are mutually exclusive"
        )
    if (
        args.pre_intermediate_hook_inventory is not None
        and args.intermediate_stop_address is None
    ):
        parser.error(
            "--pre-intermediate-hook-inventory requires --intermediate-stop-address"
        )
    if args.output.exists():
        parser.error(f"output already exists: {args.output}")
    for label, path in (
        ("ROM", args.rom),
        ("checkpoint", args.state),
        ("checkpoint IRAM sidecar", args.state.with_suffix(args.state.suffix + ".sa1-iram.bin")),
        ("checkpoint lineage", args.state_lineage_events),
        ("timeline", args.timeline),
        ("MAME work", args.mame_work),
        ("Nexen", args.nexen),
    ):
        if not path.is_file():
            parser.error(f"missing {label}: {path}")
    if (
        args.pre_intermediate_hook_inventory is not None
        and not args.pre_intermediate_hook_inventory.is_file()
    ):
        parser.error(
            "missing pre-intermediate hook inventory: "
            f"{args.pre_intermediate_hook_inventory}"
        )
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
        raise RuntimeError("VTIME IRQ capture requires a resumable checkpoint")

    inputs, _tick_rows = campaign.load_timeline(
        args.timeline,
        MAME_ORIGIN_TICK,
        args.target_mame_tick,
    )
    events_by_tick: dict[int, list[campaign.InputEvent]] = {}
    for event in inputs:
        if args.state_mame_tick < event.tick <= args.target_mame_tick:
            events_by_tick.setdefault(event.tick, []).append(event)

    mame_work = args.mame_work.read_bytes()
    if len(mame_work) != 0x10000:
        raise RuntimeError(
            f"MAME work image must be 65536 bytes, got {len(mame_work)}"
        )
    mame_task = delivery.task15_frame(mame_work)
    checkpoint_buttons = int(
        state_resumability["lineage"]["resume_context"]["current_buttons"]
    )

    args.output.mkdir(parents=True)
    campaign.configure_dotnet(args.nexen)
    report: dict[str, Any] = {
        "scope": (
            "authenticated checkpoint-local exact game-update/VTIME IRQ "
            "boundary with retained controller ordering; not fresh-boot, "
            "native-off, rate, renderer, or full-playthrough evidence"
        ),
        "rom": {"path": str(args.rom.resolve()), "sha256": sha256(args.rom)},
        "checkpoint": {
            "path": str(args.state.resolve()),
            "sha256": sha256(args.state),
            "mame_tick_completed": args.state_mame_tick,
        },
        "target_mame_tick": args.target_mame_tick,
        "state_resumability": state_resumability,
        "mame": {
            "work": str(args.mame_work.resolve()),
            "work_sha256": sha256(args.mame_work),
            "task15": mame_task,
        },
        "nexen": campaign.nexen_identity(args.nexen),
        "runtime_architectural_mutations": [],
        "time_unix": time.time(),
    }

    with campaign.AuditedMcpSession(
        rom=args.rom.resolve(),
        mesen=args.nexen.resolve(),
        cwd=ROOT,
        port=args.port,
        boot_wait=8.0,
        socket_timeout=240.0,
        stderr_log=args.output / "nexen.stderr.log",
    ) as m:
        campaign.pause_for_startup(m)
        report["load_state"] = dict(m.load_state(args.state.resolve()))
        campaign.require_paused(m, "checkpoint load")
        report["loaded_state_validation"] = capture.validate_loaded_start_state(
            m, state_resumability
        )
        report["initial_input"] = campaign.set_held_input(m, checkpoint_buttons)

        current_tick = args.state_mame_tick
        current_buttons = checkpoint_buttons
        entry_spans: list[dict[str, Any]] = []
        applied_inputs: list[dict[str, Any]] = []
        while current_tick < args.target_mame_tick:
            entry_spans.extend(
                campaign.run_game_update_entries(
                    m,
                    1,
                    max_entries_per_chunk=1,
                )
            )
            current_tick += 1
            for event in events_by_tick.get(current_tick, []):
                before = current_buttons
                current_buttons = event.buttons
                applied_inputs.append(
                    {
                        "mame_tick": current_tick,
                        "buttons_before": before,
                        "buttons_after": current_buttons,
                        "label": campaign.button_label(current_buttons),
                        "response": campaign.set_held_input(m, current_buttons),
                    }
                )

        report["entry_spans"] = entry_spans
        report["applied_inputs"] = applied_inputs
        report["target_entry"] = boundary_snapshot(m)
        intermediate_address = (
            args.intermediate_stop_address
            if args.intermediate_stop_address is not None
            else args.due_stop_address
        )
        if intermediate_address is not None:
            pre_handles: dict[str, int] = {}
            pre_notifications: list[dict[str, Any]] = []
            if args.pre_intermediate_hook_inventory is not None:
                inventory = active_entry_inventory(
                    args.pre_intermediate_hook_inventory
                )
                pre_handles = {
                    name: m.add_exec_hook(address, cpu_type="Sa1")
                    for name, address in inventory.items()
                }
                pre_notifications.extend(m.drain_notifications(timeout=0.05))
            try:
                intermediate_stop = dict(
                    m.tool(
                        "run_to_exact_exec_stop",
                        {
                            "address": intermediate_address,
                            "cpuType": "Sa1",
                            "maxFrames": args.max_irq_frames,
                            "occurrences": 1,
                        },
                    )
                )
            finally:
                for handle in pre_handles.values():
                    m.remove_hook(handle)
                pre_notifications.extend(m.drain_notifications(timeout=0.10))
            campaign.require_paused(m, "VTIME intermediate exact stop")
            intermediate = {
                "address": f"{intermediate_address:06X}",
                "stop": intermediate_stop,
                "snapshot": boundary_snapshot(m),
            }
            report["intermediate_boundary"] = intermediate
            if pre_handles:
                pre_hits = exec_hits(pre_notifications, pre_handles)
                report["pre_intermediate_entry_trace"] = {
                    "inventory": str(
                        args.pre_intermediate_hook_inventory.resolve()
                    ),
                    "inventory_sha256": sha256(
                        args.pre_intermediate_hook_inventory
                    ),
                    "hits": pre_hits,
                    "counts": {
                        name: sum(hit["site"] == name for hit in pre_hits)
                        for name in pre_handles
                    },
                }
            if args.due_stop_address is not None:
                report["due_boundary"] = intermediate
        due_handles = {
            name: m.add_exec_hook(address, cpu_type="Sa1")
            for name, address in VTIME_DUE_SITES.items()
        }
        root_trace_handles = {
            name: m.add_exec_hook(address, cpu_type="Sa1")
            for name, address in ROOT_TRACE_SITES.items()
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
            campaign.require_paused(m, "VTIME IRQ exact stop")
            irq_snapshot = boundary_snapshot(m)
        finally:
            for handle in due_handles.values():
                m.remove_hook(handle)
            for handle in root_trace_handles.values():
                m.remove_hook(handle)
            notifications.extend(m.drain_notifications(timeout=0.10))
        due_trace = exec_hits(notifications, due_handles)
        root_trace = exec_hits(notifications, root_trace_handles)
        report["virtual_irq_entry"] = {
            "address": f"{TAKE_IRQ:06X}",
            "stop": irq_stop,
            "snapshot": irq_snapshot,
            "vtime_due_hits": due_trace,
            "root_trace_hits": root_trace,
            "root_trace_counts": {
                name: sum(hit["site"] == name for hit in root_trace)
                for name in ROOT_TRACE_SITES
            },
        }
        report["runtime_architectural_mutations"] = list(
            m.architectural_mutations
        )

    irq = report["virtual_irq_entry"]
    irq_snapshot = irq["snapshot"]
    irq_task = irq_snapshot["task15"]
    checks = {
        "checkpoint_load_authenticated": bool(
            report["loaded_state_validation"].get("authenticated")
        ),
        "target_entry_tick_exact": (
            int(report["target_entry"]["snes_tick"])
            == args.target_mame_tick - 2
        ),
        "virtual_irq_entry_exact": delivery.exact_stop_ok(
            irq["stop"], TAKE_IRQ, 1
        ),
        "task15_frame_matches_mame": (
            irq_task["frame_plus_return_hex"]
            == mame_task["frame_plus_return_hex"]
        ),
        "task15_pc_matches_mame": irq_task["pc"] == mame_task["pc"],
        "task15_return_matches_mame": (
            irq_task["return_pc"] == mame_task["return_pc"]
        ),
        "task15_sr_matches_mame": irq_task["sr"] == mame_task["sr"],
        "live_logical_pc_matches_mame_task": (
            irq_snapshot["logical_pc"] == mame_task["pc"][-6:]
        ),
    }
    report["checks"] = checks
    report["failed_checks"] = [name for name, passed in checks.items() if not passed]
    report["result"] = "green" if all(checks.values()) else "red"
    report["diagnosis"] = {
        "mame_task15_pc": mame_task["pc"],
        "mame_task15_return_pc": mame_task["return_pc"],
        "mame_task15_sr": mame_task["sr"],
        "snes_task15_pc_at_irq": irq_task["pc"],
        "snes_task15_return_pc_at_irq": irq_task["return_pc"],
        "snes_task15_sr_at_irq": irq_task["sr"],
        "snes_live_logical_pc_at_irq": irq_snapshot["logical_pc"],
        "target_vtime": report["target_entry"]["vtime"],
        "irq_vtime": irq_snapshot["vtime"],
    }
    output = args.output / "summary.json"
    output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"result": report["result"], "output": str(output.resolve())}, sort_keys=True))
    return 0 if report["result"] == "green" or args.allow_red else 1


if __name__ == "__main__":
    raise SystemExit(main())
