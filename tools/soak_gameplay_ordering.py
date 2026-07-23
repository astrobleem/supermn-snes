#!/usr/bin/env python3
"""Checkpointed Right+B soak for the tick-765 ordering/renderer failure.

This is a focused bisection tool, not FPS evidence.  It loads a production
gameplay checkpoint, holds the real Nexen port-0 Right+B input through one
continuous loaded-state session, and cross-checks the real $00:F5A3 tick
boundary against 5A22 renderer counters.  It also retains scheduler, stack,
sound, input, video-mirror, screenshot, and final-state evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import time
from pathlib import Path
from typing import Any

import validate_gameplay_controls as controls


ROOT = Path(__file__).resolve().parents[1]
TICK_HOOK = 0x00F5A3
RENDER_COMPLETE_HOOK = 0x7F8924


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--nexen", type=Path, default=controls.DEFAULT_NEXEN)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8060)
    parser.add_argument(
        "--refresh-video-mirror",
        action="store_true",
        help=(
            "Lab only: replace the checkpoint's $7F:8000-$AFFF WRAM "
            "supervisor mirror with the current ROM bytes before running."
        ),
    )
    parser.add_argument(
        "--frames",
        type=int,
        default=1200,
        help="Completed emulated video frames to run after loading the checkpoint.",
    )
    parser.add_argument(
        "--chunk-frames",
        type=int,
        default=300,
        help=(
            "Frames per Nexen run command. Chunking avoids the transport's "
            "40-second command timeout; it does not reload or alter emulated state."
        ),
    )
    parser.add_argument(
        "--min-ticks",
        type=int,
        default=530,
        help="Minimum game-tick delta required to cross the known 765-767 event.",
    )
    parser.add_argument(
        "--max-render-debt",
        type=int,
        default=64,
        help="Maximum tick/ACK or request/ACK debt accepted at the final pause.",
    )
    parser.add_argument(
        "--dma-trace",
        action="store_true",
        help=(
            "Add bounded 5A22 renderer/NMI/DMA execution and register-write "
            "hooks. Intended for short checkpointed diagnostics only."
        ),
    )
    return parser.parse_args()


def hook_events(
    notifications: list[dict[str, Any]], handles: dict[int, str]
) -> list[dict[str, Any]]:
    events = []
    for notification in notifications:
        if notification.get("method") != "notifications/mesen/hookFired":
            continue
        params = dict(notification.get("params", {}))
        label = handles.get(int(params.get("handle", -1)))
        if label is None:
            continue
        events.append(
            {
                "label": label,
                "address": int(params.get("address", 0)),
                "cycle_count": int(params.get("cycleCount", 0)),
                "frame": int(params.get("frame", 0)),
                "cpu_type": params.get("cpuType"),
                "kind": params.get("kind"),
                "value": int(params.get("value", 0)),
            }
        )
    return events


def main() -> int:
    args = parse_args()
    if args.frames <= 0:
        raise SystemExit("--frames must be positive")
    if args.chunk_frames <= 0:
        raise SystemExit("--chunk-frames must be positive")
    if args.min_ticks <= 0:
        raise SystemExit("--min-ticks must be positive")
    if args.max_render_debt < 0:
        raise SystemExit("--max-render-debt must be non-negative")
    for path in (args.rom, args.state, args.nexen):
        if not path.is_file():
            raise FileNotFoundError(path)
    args.output.mkdir(parents=True, exist_ok=False)

    stderr_log = args.output / "nexen.stderr.log"
    with controls.McpSession(
        rom=args.rom.resolve(),
        mesen=args.nexen.resolve(),
        cwd=ROOT,
        port=args.port,
        boot_wait=6.0,
        socket_timeout=300.0,
        stderr_log=stderr_log,
    ) as m:
        m.pause()
        m.load_state(args.state.resolve())
        m.pause()
        mirror_intervention = None
        if args.refresh_video_mirror:
            cpu = m.get_cpu_state("Snes")
            cpu_pc = (int(cpu.get("k", 0)) << 16) | int(cpu.get("pc", 0))
            rom_bytes = args.rom.read_bytes()[0x298000 : 0x298000 + 0x3000]
            old_bytes = m.read_memory("snesWorkRam", 0x18000, 0x3000)
            differing = [
                index
                for index, (old, new) in enumerate(zip(old_bytes, rom_bytes))
                if old != new
            ]
            pc_offset = cpu_pc - 0x7F8000
            if any(pc_offset - 4 <= index <= pc_offset + 4 for index in differing):
                raise RuntimeError(
                    "refusing to replace WRAM bytes around the 5A22's current "
                    f"instruction: PC={cpu_pc:#08x}"
                )
            for offset in range(0, len(rom_bytes), 0x1000):
                chunk = rom_bytes[offset : offset + 0x1000]
                m.write_memory("snesWorkRam", 0x18000 + offset, chunk.hex())
            observed = m.read_memory("snesWorkRam", 0x18000, 0x3000)
            if observed != rom_bytes:
                raise RuntimeError("WRAM video mirror refresh did not read back exactly")
            old_ready_sequence = int.from_bytes(
                m.read_memory("snesWorkRam", 0x1F1E, 2), "little"
            )
            checkpoint_frame_ack = int.from_bytes(
                m.read_memory("Sa1Memory", 0x3302, 2), "little"
            )
            m.write_memory(
                "snesWorkRam",
                0x1F1E,
                checkpoint_frame_ack.to_bytes(2, "little").hex(),
            )
            if int.from_bytes(
                m.read_memory("snesWorkRam", 0x1F1E, 2), "little"
            ) != checkpoint_frame_ack:
                raise RuntimeError("render-ready checkpoint migration did not verify")
            offset_table = controls.bg_offset_table()
            m.write_memory("snesWorkRam", 0x7500, offset_table.hex())
            if m.read_memory("snesWorkRam", 0x7500, len(offset_table)) != offset_table:
                raise RuntimeError("BG offset-table checkpoint migration did not verify")
            mirror_intervention = {
                "kind": "checkpoint_lab_wram_video_mirror_refresh",
                "cpu_pc": cpu_pc,
                "length": len(rom_bytes),
                "differing_bytes": len(differing),
                "first_differing_offsets": differing[:64],
                "sha256": hashlib.sha256(observed).hexdigest(),
                "render_ready_sequence": {
                    "address": "7E:1F1E",
                    "checkpoint": old_ready_sequence,
                    "normalized_to_frame_ack": checkpoint_frame_ack,
                },
                "bg_offset_table": {
                    "address": "7E:7500",
                    "length": len(offset_table),
                    "sha256": hashlib.sha256(offset_table).hexdigest(),
                },
            }
        m.tool("set_input", {"port": 0, "buttons": 0, "hold": True})
        initial = controls.snapshot(m, "initial")
        controls.require_healthy("initial", initial)

        tick_handle = m.add_exec_hook(TICK_HOOK, cpu_type="Sa1")
        render_handle = m.add_exec_hook(RENDER_COMPLETE_HOOK, cpu_type="Snes")
        handles = {tick_handle: "tick", render_handle: "render_complete"}
        if args.dma_trace:
            for label, address in {
                "render_start": 0x7F8918,
                "dma_call": 0x7F88CC,
                "dma_direct": 0x7F8AB0,
                "dma_publish": 0x7F8AB7,
                "bg_chunk_start": 0x7F8A00,
                "bg_final_chunk": 0x7F8A22,
                "pending_dma_service": 0x7F8A33,
                "pending_dma_seen": 0x7F8A38,
                "pending_dma_in_vblank": 0x7F8A3D,
                "pending_dma_small_line_ok": 0x7F8A50,
                "pending_dma_line_ok": 0x7F8A57,
                "pending_dma_line_high_ok": 0x7F8A5E,
                "pending_dma_start": 0x7F8A60,
                "pacing_deadline": 0x7F8E2B,
                "renderer_queue_full": 0x7F8E67,
                "nmi": 0x7F8F00,
            }.items():
                handles[m.add_exec_hook(address, cpu_type="Snes")] = label
            for label, address in {
                "dma0_size_low_write": 0x4305,
                "dma0_size_high_write": 0x4306,
                "snapshot_size_low_write": 0x4375,
                "snapshot_size_high_write": 0x4376,
                "dma_enable_write": 0x420B,
                "pending_flag_write": 0x1F11,
            }.items():
                handles[m.add_write_hook(address, cpu_type="Snes")] = label
            handles[m.add_read_hook(0x213D, cpu_type="Snes")] = (
                "vertical_counter_read"
            )
        m.drain_notifications(timeout=0.05)

        buttons = controls.McpSession.BTN_RIGHT | controls.McpSession.BTN_B
        m.tool("set_input", {"port": 0, "buttons": buttons, "hold": True})
        start_wall = time.monotonic()
        run_results = []
        notifications = []
        frames_remaining = args.frames
        while frames_remaining:
            frame_count = min(args.chunk_frames, frames_remaining)
            run_result = m.run_frames(frame_count)
            frames_advanced = int(run_result.get("framesAdvanced", 0))
            if frames_advanced <= 0 or frames_advanced > frame_count:
                raise RuntimeError(
                    "Nexen made invalid frame progress: "
                    f"remaining={frames_remaining}, result={run_result}"
                )
            run_results.append(run_result)
            notifications.extend(m.drain_notifications(timeout=0.05))
            frames_remaining -= frames_advanced
        run_wall_seconds = time.monotonic() - start_wall
        notifications.extend(m.drain_notifications(timeout=0.5))
        events = hook_events(notifications, handles)
        for handle in handles:
            m.remove_hook(handle)
        final = controls.snapshot(m, "final")

        final_state_path = args.output / "final.mss"
        m.save_state(final_state_path.resolve())
        deadline = time.monotonic() + 5.0
        while (
            (not final_state_path.is_file() or final_state_path.stat().st_size == 0)
            and time.monotonic() < deadline
        ):
            time.sleep(0.05)
        if not final_state_path.is_file() or final_state_path.stat().st_size == 0:
            raise RuntimeError("Nexen did not flush the final checkpoint")

        screenshot_response = m.take_screenshot(format="path")
        screenshot_path = args.output / "final.png"
        shutil.copy2(Path(screenshot_response["path"]), screenshot_path)
        observed_mirror = m.read_memory("snesWorkRam", 0x18000, 0x3000)

    raw_hook_path = args.output / "hooks.jsonl"
    raw_hook_path.write_text(
        "".join(json.dumps(event, sort_keys=True) + "\n" for event in events),
        encoding="utf-8",
    )

    expected_mirror = args.rom.read_bytes()[0x298000 : 0x298000 + 0x3000]
    mirror_differences = [
        index
        for index, (observed, expected) in enumerate(
            zip(observed_mirror, expected_mirror)
        )
        if observed != expected
    ]
    tick_delta = (final["tick"] - initial["tick"]) & 0xFFFF
    ack_delta = (final["frame_ack"] - initial["frame_ack"]) & 0xFFFF
    request_delta = (final["frame_request"] - initial["frame_request"]) & 0xFFFF
    tick_hook_count = sum(event["label"] == "tick" for event in events)
    render_complete_count = sum(
        event["label"] == "render_complete" for event in events
    )
    render_complete_counter_delta = (
        final["render_complete_count"] - initial["render_complete_count"]
    ) & 0xFFFF
    tick_ack_debt = max(0, tick_delta - ack_delta)
    request_ack_debt = (final["frame_request"] - final["frame_ack"]) & 0xFFFF

    checks = {
        "frame_span_exact": (
            final["frame"] - initial["frame"] == args.frames
            and sum(int(result.get("framesAdvanced", -1)) for result in run_results)
            == args.frames
        ),
        "ordering_window_crossed": tick_delta >= args.min_ticks,
        "tick_hook_matches_counter": tick_hook_count == tick_delta,
        "render_hook_matches_counter": (
            render_complete_count == render_complete_counter_delta
        ),
        "renderer_queue_no_new_overflow": (
            final["render_queue_drops"] == initial["render_queue_drops"]
        ),
        "interpreter_not_halted": final["halt"] == 0,
        "production_gates_intact": final["gates"] == controls.EXPECTED_GATES,
        "production_pacing_intact": (
            final["production_pacing_gate"] == 1
            and final["pacing_initialized"] == 0xA5
            and final["pacing_supervisor_ready"] == 0x5A
            and initial["pacing_catchup_debt"]
            <= controls.PACING_CATCHUP_DEBT_MAX
            and final["pacing_catchup_debt"]
            <= controls.PACING_CATCHUP_DEBT_MAX
        ),
        "real_right_b_reached_mailbox": (
            final["input_real_cache"] == "8100"
            and final["input_mailbox"] == "8100"
            and final["input_injection"] == "0000"
        ),
        "task_stacks_above_floors": not final["stack"]["below_floor"],
        "video_mirror_exact": not mirror_differences,
        "renderer_ack_debt_bounded": (
            tick_ack_debt <= args.max_render_debt
            and request_ack_debt <= args.max_render_debt
        ),
    }
    result = {
        "scope": (
            "checkpointed real-input ordering/renderer bisection; not fps and "
            "not cold-boot evidence"
        ),
        "rom": str(args.rom.resolve()),
        "rom_sha256": controls.sha256(args.rom),
        "checkpoint": str(args.state.resolve()),
        "checkpoint_sha256": controls.sha256(args.state),
        "nexen": str(args.nexen.resolve()),
        "nexen_sha256": controls.sha256(args.nexen),
        "buttons": buttons,
        "input_transport": "nexen_port0_manual_4016",
        "checkpoint_intervention": mirror_intervention,
        "frames_requested": args.frames,
        "chunk_frames": args.chunk_frames,
        "minimum_tick_delta": args.min_ticks,
        "dma_trace": args.dma_trace,
        "run_results": run_results,
        "run_wall_seconds": run_wall_seconds,
        "initial": initial,
        "final": final,
        "deltas": {
            "ticks": tick_delta,
            "tick_hooks": tick_hook_count,
            "frame_requests": request_delta,
            "frame_acks": ack_delta,
            "true_render_completions": render_complete_count,
            "render_complete_counter": render_complete_counter_delta,
            "tick_ack_debt": tick_ack_debt,
            "request_ack_debt": request_ack_debt,
        },
        "video_mirror": {
            "differing_bytes": len(mirror_differences),
            "first_differing_offsets": mirror_differences[:64],
        },
        "hooks": {
            "path": str(raw_hook_path),
            "sha256": controls.sha256(raw_hook_path),
        },
        "final_state": {
            "path": str(final_state_path),
            "sha256": controls.sha256(final_state_path),
        },
        "screenshot": {
            "path": str(screenshot_path),
            "sha256": controls.sha256(screenshot_path),
            "response": screenshot_response,
        },
        "checks": checks,
        "result": "green" if all(checks.values()) else "red",
    }
    result_path = args.output / "results.json"
    result_path.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "result": result["result"],
                "rom_sha256": result["rom_sha256"],
                "deltas": result["deltas"],
                "failed_checks": [name for name, passed in checks.items() if not passed],
                "results": str(result_path),
            },
            sort_keys=True,
        )
    )
    return 0 if result["result"] == "green" else 1


if __name__ == "__main__":
    raise SystemExit(main())
