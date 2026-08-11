#!/usr/bin/env python3
"""Focused recovery regression for a stranded NMI-owned DMA0 descriptor.

The retained fixture stops with the 5A22 foreground spinning on $7E:1F11
after an OAM descriptor was rejected on every NMI.  A save state also retains
the old $7F:8000-$AFFF executable mirror, so this validator explicitly performs
the same mirror copy as a reset before resuming it.  That intervention is
recorded and is checkpoint-only evidence, never fresh-boot proof.
"""

from __future__ import annotations

import argparse
import json
import shutil
import time
from pathlib import Path
from typing import Any

import validate_gameplay_controls as controls
from replay_mame_controller_campaign import configure_dotnet, refresh_video_wram


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ROM = ROOT / "build" / "interp.sfc"
DEFAULT_NEXEN = controls.DEFAULT_NEXEN
PENDING_FLAG = 0x1F11
DMA0_REGISTERS = 0x4300
RENDER_COMPLETE_HOOK = 0x7F8924


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--nexen", type=Path, default=DEFAULT_NEXEN)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--port", type=int, default=9460)
    parser.add_argument("--frames", type=int, default=300)
    args = parser.parse_args()
    if args.frames < 4:
        parser.error("--frames must be at least 4")
    for label, path in (
        ("ROM", args.rom),
        ("failure state", args.state),
        ("Nexen", args.nexen),
    ):
        if not path.is_file():
            parser.error(f"missing {label}: {path}")
    if args.output.exists():
        parser.error(f"output already exists: {args.output}")
    return args


def hook_events(
    notifications: list[dict[str, Any]], handles: dict[int, str]
) -> list[dict[str, Any]]:
    rows = []
    for notification in notifications:
        if notification.get("method") != "notifications/mesen/hookFired":
            continue
        params = notification.get("params", {})
        label = handles.get(int(params.get("handle", -1)))
        if label is None:
            continue
        rows.append(
            {
                "label": label,
                "frame": int(params.get("frame", 0)),
                "cycle_count": int(params.get("cycleCount", 0)),
                "address": int(params.get("address", 0)),
                "value": int(params.get("value", 0)),
            }
        )
    return rows


def main() -> int:
    args = parse_args()
    configure_dotnet(args.nexen)
    args.output.mkdir(parents=True)

    stderr_path = args.output / "nexen.stderr.log"
    with controls.McpSession(
        rom=args.rom.resolve(),
        mesen=args.nexen.resolve(),
        cwd=ROOT,
        port=args.port,
        boot_wait=6.0,
        socket_timeout=300.0,
        stderr_log=stderr_path,
    ) as m:
        m.pause()
        load_response = m.load_state(args.state.resolve())
        m.pause()
        initial_cpu = m.get_cpu_state("Snes")
        initial_pending = m.read_memory(
            "snesWorkRam", PENDING_FLAG, 1
        )[0]
        initial_descriptor = m.read_memory(
            "snesMemory", DMA0_REGISTERS, 8
        )
        initial = controls.snapshot(m, "initial_stranded_state")

        intervention = refresh_video_wram(m, args.rom.resolve())
        handles = {
            m.add_write_hook(
                PENDING_FLAG,
                cpu_type="Snes",
                match_value=0,
                match_value_mask=0xFF,
            ): "pending_flag_clear",
            m.add_write_hook(
                0x420B,
                cpu_type="Snes",
                match_value=1,
                match_value_mask=0xFF,
            ): "dma0_start",
            m.add_exec_hook(
                RENDER_COMPLETE_HOOK, cpu_type="Snes"
            ): "render_complete",
        }
        m.drain_notifications(timeout=0.05)

        start_wall = time.monotonic()
        run_results = []
        notifications = []
        frames_left = args.frames
        while frames_left:
            span = min(40, frames_left)
            run_result = m.run_frames(span)
            advanced = int(run_result.get("framesAdvanced", 0))
            if advanced <= 0 or advanced > span:
                raise RuntimeError(
                    "Nexen made invalid frame progress: "
                    f"remaining={frames_left}, result={run_result}"
                )
            run_results.append(run_result)
            notifications.extend(m.drain_notifications(timeout=0.05))
            frames_left -= advanced
        run_wall_seconds = time.monotonic() - start_wall
        notifications.extend(m.drain_notifications(timeout=0.5))
        events = hook_events(notifications, handles)
        for handle in handles:
            m.remove_hook(handle)

        final = controls.snapshot(m, "final_recovered_state")
        final_pending = m.read_memory("snesWorkRam", PENDING_FLAG, 1)[0]
        final_descriptor = m.read_memory("snesMemory", DMA0_REGISTERS, 8)
        observed_mirror = m.read_memory("snesWorkRam", 0x18000, 0x3000)

        final_state = args.output / "final.mss"
        m.save_state(final_state.resolve())
        deadline = time.monotonic() + 5.0
        while (
            (not final_state.is_file() or final_state.stat().st_size == 0)
            and time.monotonic() < deadline
        ):
            time.sleep(0.05)
        screenshot_response = m.take_screenshot(format="path")
        screenshot = args.output / "final.png"
        shutil.copy2(Path(screenshot_response["path"]), screenshot)

    expected_mirror = args.rom.read_bytes()[0x298000:0x29B000]
    tick_delta = (final["tick"] - initial["tick"]) & 0xFFFF
    ack_delta = (final["frame_ack"] - initial["frame_ack"]) & 0xFFFF
    complete_delta = (
        final["render_complete_count"] - initial["render_complete_count"]
    ) & 0xFFFF
    generation_delta = (
        final["render_complete_generation"]
        - initial["render_complete_generation"]
    ) & 0xFFFF
    clear_events = [
        event for event in events if event["label"] == "pending_flag_clear"
    ]
    render_events = [
        event for event in events if event["label"] == "render_complete"
    ]
    checks = {
        "frame_span_exact": (
            final["frame"] - initial["frame"] == args.frames
            and sum(
                int(run.get("framesAdvanced", -1)) for run in run_results
            )
            == args.frames
        ),
        "fixture_was_stranded_oam_544": (
            initial_pending == 1
            and initial_descriptor[:7] == bytes.fromhex("000400867e2002")
            and initial["render_queue_primary_state"] == 1
            and initial["render_queue_secondary_state"] == 1
        ),
        "pending_descriptor_was_serviced": bool(clear_events),
        "game_ticks_resumed": tick_delta > 0,
        "frame_ack_resumed": ack_delta > 0,
        "completed_renders_resumed": (
            complete_delta > 0
            and generation_delta > 0
            and len(render_events) == complete_delta
        ),
        "interpreter_not_halted": final["halt"] == 0,
        "task_stacks_above_floors": not final["stack"]["below_floor"],
        "production_gates_intact": final["gates"] == controls.EXPECTED_GATES,
        "current_video_mirror_exact": observed_mirror == expected_mirror,
    }
    result = {
        "scope": (
            "focused checkpoint recovery from the deterministic pending-DMA0 "
            "failure; explicit WRAM code-mirror migration; not fresh boot, "
            "not fps, and not a gameplay-path continuation"
        ),
        "result": "green" if all(checks.values()) else "red",
        "checks": checks,
        "rom": str(args.rom.resolve()),
        "rom_sha256": controls.sha256(args.rom),
        "failure_state": str(args.state.resolve()),
        "failure_state_sha256": controls.sha256(args.state),
        "nexen": str(args.nexen.resolve()),
        "nexen_sha256": controls.sha256(args.nexen),
        "load_response": load_response,
        "checkpoint_intervention": intervention,
        "initial_snes_cpu": initial_cpu,
        "initial_pending_flag": initial_pending,
        "initial_dma0_descriptor": initial_descriptor.hex(),
        "initial": initial,
        "frames_requested": args.frames,
        "run_results": run_results,
        "run_wall_seconds": run_wall_seconds,
        "events": events,
        "deltas": {
            "game_ticks": tick_delta,
            "frame_ack": ack_delta,
            "render_complete": complete_delta,
            "render_generation": generation_delta,
        },
        "final_pending_flag": final_pending,
        "final_dma0_descriptor": final_descriptor.hex(),
        "final": final,
        "final_state": {
            "path": str(final_state),
            "sha256": controls.sha256(final_state),
        },
        "screenshot": {
            "path": str(screenshot),
            "sha256": controls.sha256(screenshot),
            "response": screenshot_response,
        },
    }
    summary = args.output / "summary.json"
    summary.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(
        {
            "result": result["result"],
            "summary": str(summary),
            "checks": checks,
            "deltas": result["deltas"],
        },
        sort_keys=True,
    ))
    return 0 if result["result"] == "green" else 1


if __name__ == "__main__":
    raise SystemExit(main())
