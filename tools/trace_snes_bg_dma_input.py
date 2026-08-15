#!/usr/bin/env python3
"""Trace BG DMA execution during one real-controller input span.

The run starts from a retained same-emulator state, applies only port-0 input,
records every rendered framebuffer through the emulator core, and retains raw
exec/write-hook events.  It is a focused renderer diagnostic, not fresh-boot,
performance, or gameplay-oracle evidence.
"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
REAL_MESEN = Path("/home/chad/Mesen2/bin/linux-x64/Release/Mesen")
REAL_MESEN_DLL = REAL_MESEN.with_name("Mesen.dll")
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, "/home/chad/Mesen2/python")

import capture_mesen211_transitions as capture  # noqa: E402
import capture_snes_direct_framebuffers as direct_capture  # noqa: E402
from gameplay_acceptance_contract import unknown_diagnostic_gate  # noqa: E402
import mesen_mcp.session as _session  # noqa: E402
import replay_mame_controller_campaign as campaign  # noqa: E402

_session.validate_mesen_build = lambda *_args, **_kwargs: None
from mesen_mcp import McpSession  # noqa: E402


BUTTONS = {
    "neutral": 0,
    "right": McpSession.BTN_RIGHT,
    "b+right": McpSession.BTN_B | McpSession.BTN_RIGHT,
}

EXEC_HOOKS = {
    "nmi_present_arbitrate": 0xE9CF00,
    "nmi_present_before_dma": 0xE9CD20,
    "nmi_batch_present_then_wake": 0xE9D160,
    "nmi_obj_tile_batch_dispatch": 0xE9D600,
    "nmi_obj_tile_batch_staged": 0xE9D640,
    "nmi_obj_tile_batch_group": 0xE9D900,
    "nmi_batch_present_arbitrate": 0xE9DA40,
    "bg_scroll_present_step": 0xE9C200,
    "obj_present_nmi": 0xE9CA80,
    "obj_present_dma_base": 0xE9CC80,
    "capture_bg_vscroll": 0xE9A7BC,
    "pacing_try_wake": 0x7F8E00,
    "pacing_publish_input_and_scroll": 0x7F8ED0,
    "pacing_snapshot_direct": 0x7FA300,
    "vid_bg_heavy": 0x7F847E,
    "vid_bg_incremental": 0x7FA680,
    "bg_cache_reclaim": 0x7FA899,
    "bg_prepared_render": 0x7FAA99,
    "bg_tile_run_dma": 0x7FAB3A,
    "bg_chunk_start": 0x7F8A00,
    "bg_final_chunk": 0x7F8A22,
    "pending_dma_service": 0x7F8A33,
    "pending_dma_start": 0x7F8A60,
    "bg_upload": 0x7F86D0,
    "bg_upload_commit": 0x7F86D4,
    "bg_write_cell": 0xE9B700,
    "bg_column_map_update": 0xE9B780,
    "bcmu_layout_changed": 0xE9B7CA,
    "bcmu_force_full": 0xE9B800,
    "bcmu_same_layout": 0xE9BC80,
    "bcmu_c0bc_prepare": 0xE9BCCC,
    "bcmu_prepared_only": 0xE9BCE5,
    "prepared_bg_map_remap": 0xE9BD00,
}

SA1_EXEC_HOOKS = {
    "sa1_manifest_call": 0x99FB3F,
    "sa1_camera_mailbox_helper": 0x99FBC5,
    "sa1_camera_mailbox_helper_tail": 0x99FBD7,
    "sa1_manifest_build": 0x9EDC00,
    "sa1_manifest_rtl": 0x9EDE13,
    "sa1_camera_mailbox_helper_rtl": 0x99FBDE,
    "sa1_manifest_resume": 0x99FB43,
    "sa1_arm1_publish": 0x99FB46,
    "sa1_deadline_irq_request": 0x99FB4E,
    "sa1_pacing_wai": 0x99FB51,
}

WRITE_HOOKS = {
    "latest_scrollx_write": 0x7E72B2,
    "presented_scrollx_write": 0x7E72B4,
    "obj_present_valid_write": 0x7E7184,
    "obj_dma_pending_write": 0x7E7189,
    "obj_presented_this_nmi_write": 0x7E719B,
    "dma0_size_low_write": 0x4305,
    "dma0_size_high_write": 0x4306,
    "dma_enable_write": 0x420B,
    "pending_flag_write": 0x1F11,
    "bg_dirty_low_write": 0x7E8990,
    "bg_dirty_high_write": 0x7E8991,
    "bg_layout_low_write": 0x7E8996,
    "bg_layout_high_write": 0x7E8997,
    "bg_manifest_low_write": 0x7E89BC,
    "bg_manifest_high_write": 0x7E89BD,
    "bg_prepared_length_low_write": 0x7E89C4,
    "bg_prepared_length_high_write": 0x7E89C5,
    "bg_c0bc_token_low_write": 0x7E7492,
    "bg_c0bc_token_high_write": 0x7E7493,
    "bg_c0bc_applied_low_write": 0x7E7498,
    "bg_c0bc_applied_high_write": 0x7E7499,
    "render_queue1_low_write": 0x7E89D2,
    "render_queue1_high_write": 0x7E89D3,
    "render_queue2_low_write": 0x7E89D6,
    "render_queue2_high_write": 0x7E89D7,
    "obj_tile_batch_due_low_write": 0x7E74A2,
    "obj_tile_batch_due_high_write": 0x7E74A3,
}

SA1_WRITE_HOOKS = {
    "sa1_pacing_arm_write": 0x410122,
    "sa1_camera_mailbox_raw_write": 0x410162,
    "sa1_camera_mailbox_valid_write": 0x410163,
}

WRITE_RANGE_HOOKS = {
    "bg_map_write": (0x7E9000, 0x7E9FFF),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--emulator", type=Path, required=True)
    parser.add_argument("--port", type=int, default=9272)
    parser.add_argument("--buttons", choices=sorted(BUTTONS), required=True)
    parser.add_argument("--frames", type=int, required=True)
    parser.add_argument(
        "--refresh-video-wram",
        action="store_true",
        help=(
            "checkpoint diagnostic only: reapply the selected ROM's rc_copy "
            "window after loading a state from another ROM identity"
        ),
    )
    parser.add_argument(
        "--early-camera-mailbox-lab",
        action="store_true",
        help="checkpoint-only runtime camera-mailbox ordering intervention",
    )
    parser.add_argument(
        "--early-camera-valid-mailbox-lab",
        action="store_true",
        help=(
            "checkpoint-only raw-camera/A5 producer-consumer intervention; "
            "trace the first patched producer call before accepting liveness"
        ),
    )
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def configure_dotnet(emulator: Path) -> None:
    selected = (
        "/home/chad/.dotnet10"
        if emulator.name == "Nexen"
        else "/home/chad/.dotnet8"
    )
    other = (
        "/home/chad/.dotnet8"
        if selected.endswith("dotnet10")
        else "/home/chad/.dotnet10"
    )
    os.environ["DOTNET_ROOT"] = selected
    existing = [
        item
        for item in os.environ.get("PATH", "").split(":")
        if item and item not in (selected, other)
    ]
    os.environ["PATH"] = ":".join([selected, other, *existing])


def hook_events(
    notifications: list[dict[str, Any]], handles: dict[int, str]
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for notification in notifications:
        if notification.get("method") != "notifications/mesen/hookFired":
            continue
        params = notification.get("params", {})
        handle = int(params.get("handle", -1))
        label = handles.get(handle)
        if label is None:
            continue
        events.append(
            {
                "label": label,
                "handle": handle,
                "frame": int(params.get("frame", 0)),
                "cycle_count": int(params.get("cycleCount", 0)),
                "address": int(params.get("address", 0)),
                "value": int(params.get("value", 0)),
                "cpu_type": params.get("cpuType"),
                "kind": params.get("kind"),
            }
        )
    return events


def main() -> int:
    args = parse_args()
    if args.frames <= 0:
        raise SystemExit("--frames must be positive")
    if args.early_camera_mailbox_lab and args.early_camera_valid_mailbox_lab:
        raise SystemExit("select only one camera-mailbox intervention")
    for label, path in (
        ("ROM", args.rom),
        ("state", args.state),
        ("emulator", args.emulator),
    ):
        if not path.is_file():
            raise FileNotFoundError(f"{label} not found: {path}")
    rom = args.rom.resolve()
    if rom.stat().st_size != 0x400000:
        raise SystemExit("expected a 4 MiB production ROM")
    if int.from_bytes(rom.read_bytes()[0x77E0:0x77E2], "little") != 0:
        raise SystemExit("refusing non-production ROM: TESTFLAG is set")

    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    gif_path = output / "framebuffers.gif"
    configure_dotnet(args.emulator)
    handles: dict[int, str] = {}
    notifications: list[dict[str, Any]] = []
    video_wram_migration: dict[str, Any] | None = None
    runtime_memory_writes: list[dict[str, Any]] = []

    with McpSession(
        rom=rom,
        mesen=args.emulator.resolve(),
        cwd=ROOT,
        port=args.port,
        boot_wait=6.0,
        socket_timeout=300.0,
        stderr_log=output / "emulator.stderr.log",
    ) as m:
        m.pause()
        m.load_state(args.state.resolve())
        m.pause()
        if args.refresh_video_wram:
            video_wram_migration = campaign.refresh_video_wram(m, rom)
            runtime_memory_writes.append(video_wram_migration)
        if args.early_camera_mailbox_lab:
            runtime_memory_writes.extend(direct_capture.early_camera_mailbox_lab(m))
        if args.early_camera_valid_mailbox_lab:
            runtime_memory_writes.extend(
                direct_capture.early_camera_valid_mailbox_lab(m)
            )
        # Install hooks before any screenshot/movie operation.  Some emulator
        # capture operations can execute to a video boundary; installing after
        # the initial image would miss the first patched producer return, which
        # is the exact liveness seam this diagnostic exists to authenticate.
        for label, address in EXEC_HOOKS.items():
            handles[m.add_exec_hook(address, cpu_type="Snes")] = label
        for label, address in WRITE_HOOKS.items():
            handles[m.add_write_hook(address, cpu_type="Snes")] = label
        for label, address in SA1_EXEC_HOOKS.items():
            handles[m.add_exec_hook(address, cpu_type="Sa1")] = label
        for label, address in SA1_WRITE_HOOKS.items():
            handles[m.add_write_hook(address, cpu_type="Sa1")] = label
        for label, (start, end) in WRITE_RANGE_HOOKS.items():
            handles[m.add_write_hook(start, end, cpu_type="Snes")] = label
        m.drain_notifications(timeout=0.05)
        initial = capture.snapshot(m)
        initial["frame_request"] = m.read_u16(0x003300)
        initial["frame_ack"] = m.read_u16(0x003302)
        initial["published_frame_request"] = m.read_u16(0x7E1F1E)
        initial["render_queue1_state"] = m.read_u16(0x7E89D2)
        initial["render_queue2_state"] = m.read_u16(0x7E89D6)
        initial_screenshot = capture.take_screenshot(m, output / "initial.png")
        record_response = m.tool("record_video", {"path": str(gif_path)})
        input_start_frame = int(m.get_state().get("frameCount", 0))
        input_responses = [
            {
                "operation": "set_input",
                "response": m.set_input(BUTTONS[args.buttons], args.frames),
            }
        ]
        m.pause()
        input_after_set_frame = int(m.get_state().get("frameCount", 0))
        input_target_frame = input_start_frame + args.frames
        if input_after_set_frame < input_target_frame:
            # Legacy Mesen may return from a timed input request before all
            # requested video frames execute (including zero progress from a
            # loaded paused state).  The held mask remains installed; advance
            # only the exact remainder without rewriting controller state.
            input_remainder = input_target_frame - input_after_set_frame
            input_responses.append(
                {
                    "operation": "run_frames_after_partial_set_input",
                    "requested_remainder": input_remainder,
                    "response": m.run_frames(input_remainder),
                }
            )
            m.pause()
        input_end_frame = int(m.get_state().get("frameCount", 0))
        input_advanced_frames = input_end_frame - input_start_frame
        stop_response = m.tool("stop_video")
        notifications.extend(m.drain_notifications(timeout=1.0))
        for handle in handles:
            m.remove_hook(handle)
        final = capture.snapshot(m)
        final["frame_request"] = m.read_u16(0x003300)
        final["frame_ack"] = m.read_u16(0x003302)
        final["published_frame_request"] = m.read_u16(0x7E1F1E)
        final["render_queue1_state"] = m.read_u16(0x7E89D2)
        final["render_queue2_state"] = m.read_u16(0x7E89D6)
        final_screenshot = capture.take_screenshot(m, output / "final.png")
        final_state = capture.save_checkpoint(m, output / "final.mss")

    capture.wait_for_file(gif_path, timeout=60.0)
    events = hook_events(notifications, handles)
    raw_path = output / "hooks.jsonl"
    raw_path.write_text(
        "".join(json.dumps(event, sort_keys=True) + "\n" for event in events),
        encoding="utf-8",
    )
    labels = [
        *EXEC_HOOKS,
        *WRITE_HOOKS,
        *SA1_EXEC_HOOKS,
        *SA1_WRITE_HOOKS,
        *WRITE_RANGE_HOOKS,
    ]
    counts = {
        label: sum(event["label"] == label for event in events)
        for label in labels
    }
    frames_by_label = {
        label: sorted(
            set(event["frame"] for event in events if event["label"] == label)
        )
        for label in labels
    }
    bg_map = bytearray(0x1000)
    bg_map_known = bytearray(0x1000)
    bg_map_uploads: list[dict[str, Any]] = []
    queue_state = [
        int(initial["render_queue1_state"]),
        int(initial["render_queue2_state"]),
    ]
    queue_write_parts = {
        "render_queue1_low_write": (0, 0xFF00, 0),
        "render_queue1_high_write": (0, 0x00FF, 8),
        "render_queue2_low_write": (1, 0xFF00, 0),
        "render_queue2_high_write": (1, 0x00FF, 8),
    }
    for event in events:
        if event["label"] in queue_write_parts:
            queue, preserved_mask, shift = queue_write_parts[event["label"]]
            queue_state[queue] = (
                queue_state[queue] & preserved_mask
            ) | ((int(event["value"]) & 0xFF) << shift)
        elif event["label"] == "bg_map_write":
            offset = int(event["address"]) - 0x7E9000
            if 0 <= offset < len(bg_map):
                bg_map[offset] = int(event["value"]) & 0xFF
                bg_map_known[offset] = 1
        elif event["label"] == "bg_upload_commit":
            words = [
                bg_map[index] | (bg_map[index + 1] << 8)
                for index in range(0, len(bg_map), 2)
            ]
            word_counts = Counter(words)
            tile_counts = Counter(word & 0x03FF for word in words)
            dominant_word, dominant_word_count = word_counts.most_common(1)[0]
            dominant_tile, dominant_tile_count = tile_counts.most_common(1)[0]
            bg_map_uploads.append(
                {
                    "frame": int(event["frame"]),
                    "render_queue1_state": queue_state[0],
                    "render_queue2_state": queue_state[1],
                    "known_bytes": sum(bg_map_known),
                    "zero_words": word_counts[0],
                    "unique_words": len(word_counts),
                    "dominant_word": dominant_word,
                    "dominant_word_count": dominant_word_count,
                    "dominant_word_ratio": dominant_word_count / len(words),
                    "unique_tile_numbers": len(tile_counts),
                    "dominant_tile_number": dominant_tile,
                    "dominant_tile_count": dominant_tile_count,
                    "dominant_tile_ratio": dominant_tile_count / len(words),
                }
            )
    advanced = int(final["frame"]) - int(initial["frame"])
    result = {
        "schema": 1,
        "scope": (
            "same-emulator BG-DMA execution trace plus lossless framebuffer "
            "recording under real controller input; any executable video-WRAM "
            "migration is explicit below; no game-state writes"
        ),
        "rom": str(rom),
        "rom_sha256": sha256(rom),
        "state": str(args.state.resolve()),
        "state_sha256": sha256(args.state),
        "emulator": str(args.emulator.resolve()),
        "emulator_sha256": sha256(args.emulator),
        "mesen_2_1_1_binary": str(REAL_MESEN),
        "mesen_2_1_1_binary_sha256": sha256(REAL_MESEN),
        "mesen_2_1_1_managed_assembly": str(REAL_MESEN_DLL),
        "mesen_2_1_1_managed_assembly_sha256": sha256(REAL_MESEN_DLL),
        "buttons": args.buttons,
        "button_mask": BUTTONS[args.buttons],
        "requested_input_frames": args.frames,
        "input_start_frame": input_start_frame,
        "input_end_frame": input_end_frame,
        "input_advanced_frames": input_advanced_frames,
        "advanced_video_frames": advanced,
        "runtime_memory_writes": runtime_memory_writes,
        "video_wram_migration": video_wram_migration,
        "initial": initial,
        "initial_screenshot": initial_screenshot,
        "final": final,
        "final_screenshot": final_screenshot,
        "final_state": final_state,
        "record_response": record_response,
        "input_response": {
            "after_set_frame": input_after_set_frame,
            "responses": input_responses,
        },
        "stop_response": stop_response,
        "framebuffers": {
            "path": str(gif_path),
            "sha256": sha256(gif_path),
        },
        "hooks": {
            "path": str(raw_path),
            "sha256": sha256(raw_path),
            "events": len(events),
            "counts": counts,
            "frames_by_label": frames_by_label,
            "bg_map_uploads": bg_map_uploads,
            "bg_map_upload_attempts": counts["bg_upload"],
            "bg_map_upload_commits": counts["bg_upload_commit"],
            "bg_map_uploads_suppressed": (
                counts["bg_upload"] - counts["bg_upload_commit"]
            ),
        },
        "checks": {
            "interpreter_not_halted": int(final["halt"]) == 0,
            "video_frames_advanced": advanced > 0,
            "input_frames_exact": input_advanced_frames == args.frames,
            "bg_chunk_path_fired": counts["bg_chunk_start"] > 0,
            "dma_enable_fired": counts["dma_enable_write"] > 0,
            "bg_upload_fired": counts["bg_upload"] > 0,
        },
        "acceptance_gate": unknown_diagnostic_gate(
            "renderer_trace",
            (
                "Trace/capture success and repetition metrics cannot establish "
                "aligned pixels or temporal renderer conservation."
            ),
        ),
    }
    result["result"] = (
        "captured" if all(result["checks"].values()) else "red"
    )
    result_path = output / "results.json"
    result_path.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "result": result["result"],
                "advanced_video_frames": advanced,
                "hook_counts": counts,
                "report": str(result_path),
            },
            sort_keys=True,
        )
    )
    return 0 if result["result"] == "captured" else 1


if __name__ == "__main__":
    raise SystemExit(main())
