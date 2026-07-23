#!/usr/bin/env python3
"""Exercise Superman's charged shot and preserve the first liveness failure.

This is a focused, checkpointed gameplay diagnostic, not cold-boot or FPS
evidence.  It loads an organically armed production checkpoint, holds the real
port-0 B button, releases it, and observes the game and renderer for a
configurable number of video frames.  The capture retains the projectile pool,
both CPU PCs, virtual 68000 state, scheduler/stack state, and a save state at
the first sustained post-release game-tick stall.
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
import validate_visible_actions as actions


ROOT = Path(__file__).resolve().parents[1]
TICK_HOOK = 0x00F5A3
PROJECTILE_ALLOCATOR_HOOK = 0x99E5CB
CHARGED_SHOT_ENTRY_HOOK = 0x92EFFB
CHARGED_SHOT_CONTINUATION_HOOK = 0x94B580
PROJECTILE_POOL_ADDRESS = 0x4039F4
PROJECTILE_POOL_LENGTH = 5 * 0x10


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, default=ROOT / "build/interp.sfc")
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--nexen", type=Path, default=controls.DEFAULT_NEXEN)
    parser.add_argument("--port", type=int, default=8330)
    parser.add_argument(
        "--hold-frames",
        type=int,
        default=120,
        help="Emulated video frames to hold B before releasing it.",
    )
    parser.add_argument(
        "--observe-frames",
        type=int,
        default=1200,
        help="Maximum emulated video frames to observe after release.",
    )
    parser.add_argument(
        "--stall-frames",
        type=int,
        default=60,
        help="Unchanged game-tick frames required to preserve a stall.",
    )
    parser.add_argument(
        "--sample-frames",
        type=int,
        default=30,
        help="Maximum video frames between lightweight progress samples.",
    )
    parser.add_argument(
        "--continue-after-stall",
        type=int,
        default=30,
        help="Extra video frames to observe after the first detected stall.",
    )
    parser.add_argument(
        "--screenshot-frames",
        type=str,
        default="0,2,8,16,32,60,120,240,480,960",
        help="Comma-separated post-release video frames to capture.",
    )
    parser.add_argument(
        "--cpu-trace",
        action="store_true",
        help=(
            "Enable Nexen's SA-1/S-CPU trace rings before release so a "
            "detected stall retains the preceding physical instructions."
        ),
    )
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def le16(data: bytes) -> int:
    return int.from_bytes(data, "little")


def le32(data: bytes) -> int:
    return int.from_bytes(data, "little")


def cpu_pc(state: dict[str, Any]) -> int:
    return ((int(state.get("k", 0)) & 0xFF) << 16) | (
        int(state.get("pc", 0)) & 0xFFFF
    )


def save_state(m: controls.McpSession, target: Path) -> dict[str, Any]:
    response = m.save_state(target.resolve())
    deadline = time.monotonic() + 5.0
    while (
        (not target.is_file() or target.stat().st_size == 0)
        and time.monotonic() < deadline
    ):
        time.sleep(0.05)
    if not target.is_file() or target.stat().st_size == 0:
        raise RuntimeError(f"Nexen did not flush save state: {target}")
    return {
        "path": str(target),
        "sha256": sha256(target),
        "response": response,
    }


def screenshot(m: controls.McpSession, target: Path) -> dict[str, Any]:
    response = m.take_screenshot(format="path")
    shutil.copy2(Path(response["path"]), target)
    return {
        "path": str(target),
        "sha256": sha256(target),
        "response": response,
    }


def player_state(m: controls.McpSession) -> dict[str, Any]:
    active_a6 = actions.read_player_a6(m)
    a6 = actions.EXPECTED_PLAYER_A6
    local = m.read_memory(
        "snesMemory", actions.bwram_address(a6 - 0x60), 0x80
    )

    def byte(offset: int) -> int:
        return local[0x60 + offset]

    def word(offset: int) -> int:
        index = 0x60 + offset
        return int.from_bytes(local[index : index + 2], "big")

    return {
        "a6": a6,
        "active_task_a6": active_a6,
        "canonical": True,
        "health": word(-0x4E),
        "previous_input": byte(-0x43),
        "input": byte(-0x44),
        "action_state": byte(-0x23),
        "animation": word(-0x1A),
        "animation_step": word(-0x18),
        "animation_delay": word(-0x16),
        "animation_substep": word(-0x14),
        "animation_pointer": int.from_bytes(
            local[0x60 - 0x12 : 0x60 - 0x0E], "big"
        ),
        "x": word(-0x1E),
        "y": word(-0x22),
        "flags": byte(-0x24),
        "locals_sha256": digest(local),
    }


def projectile_pool(m: controls.McpSession) -> dict[str, Any]:
    raw = m.read_memory(
        "snesMemory", PROJECTILE_POOL_ADDRESS, PROJECTILE_POOL_LENGTH
    )
    records = []
    for index in range(5):
        record = raw[index * 0x10 : (index + 1) * 0x10]
        records.append(
            {
                "index": index,
                "active": int.from_bytes(record[0:2], "big"),
                "hex": record.hex(),
            }
        )
    return {
        "address": f"{PROJECTILE_POOL_ADDRESS:06x}",
        "sha256": digest(raw),
        "records": records,
    }


def snapshot(
    m: controls.McpSession, label: str, relative_frame: int
) -> dict[str, Any]:
    base = controls.snapshot(m, label)
    sa1 = m.get_cpu_state("Sa1")
    snes = m.get_cpu_state("Snes")
    base.update(
        {
            "relative_frame": relative_frame,
            "ac": le16(m.read_memory("Sa1Memory", 0x00AC, 2)),
            "opcode68k": le16(m.read_memory("Sa1Memory", 0x0044, 2)),
            "sa1_pc": cpu_pc(sa1),
            "snes_pc": cpu_pc(snes),
            "sa1_cpu": sa1,
            "snes_cpu": snes,
            "player": player_state(m),
            "projectile_pool": projectile_pool(m),
        }
    )
    return base


def progress_snapshot(
    m: controls.McpSession, label: str, relative_frame: int
) -> dict[str, Any]:
    """Read liveness and charged-shot state without the full stack audit."""

    virtual = m.read_memory("Sa1Memory", 0x0040, 0x70)
    video = m.read_memory("snesMemory", 0x3300, 4)
    render = m.read_memory("snesWorkRam", 0x89A2, 4)
    state = m.get_state()
    return {
        "label": label,
        "relative_frame": relative_frame,
        "video_frame": int(state.get("frameCount", 0)),
        "tick": le16(m.read_memory("Sa1Memory", 0x0760, 2)),
        "pc68k": le32(virtual[0:4]) & 0xFFFFFF,
        "opcode68k": le16(virtual[4:6]),
        "halt": le16(virtual[0x0E:0x10]),
        "ac": le16(virtual[0x6C:0x6E]),
        "frame_request": le16(video[0:2]),
        "frame_ack": le16(video[2:4]),
        "render_complete_count": le16(render[0:2]),
        "render_complete_generation": le16(render[2:4]),
        "player": player_state(m),
        "projectile_pool": projectile_pool(m),
    }


def hook_events(
    notifications: list[dict[str, Any]], handles: dict[int, str]
) -> list[dict[str, Any]]:
    events = []
    for notification in notifications:
        if notification.get("method") != "notifications/mesen/hookFired":
            continue
        params = notification.get("params", {})
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
            }
        )
    return events


def main() -> int:
    args = parse_args()
    if args.hold_frames <= 0:
        raise SystemExit("--hold-frames must be positive")
    if args.observe_frames <= 0:
        raise SystemExit("--observe-frames must be positive")
    if args.stall_frames <= 2:
        raise SystemExit("--stall-frames must exceed normal 30 Hz pacing")
    if args.sample_frames <= 0:
        raise SystemExit("--sample-frames must be positive")
    if args.continue_after_stall < 0:
        raise SystemExit("--continue-after-stall must be non-negative")
    capture_frames = {
        int(value, 0)
        for value in args.screenshot_frames.split(",")
        if value.strip()
    }
    for path in (args.rom, args.state, args.nexen):
        if not path.is_file():
            raise FileNotFoundError(path)
    args.output.mkdir(parents=True, exist_ok=False)

    result: dict[str, Any] = {
        "scope": (
            "checkpointed real-controller charged-shot liveness diagnostic; "
            "not FPS and not cold-boot evidence"
        ),
        "rom": str(args.rom.resolve()),
        "rom_sha256": sha256(args.rom),
        "checkpoint": str(args.state.resolve()),
        "checkpoint_sha256": sha256(args.state),
        "nexen": str(args.nexen.resolve()),
        "nexen_sha256": sha256(args.nexen),
        "input_transport": "nexen_port0_manual_4016",
        "hold_frames": args.hold_frames,
        "observe_frames": args.observe_frames,
        "stall_frames": args.stall_frames,
        "sample_frames": args.sample_frames,
    }

    records: list[dict[str, Any]] = []
    screenshots: dict[int, dict[str, Any]] = {}
    events: list[dict[str, Any]] = []
    first_stall_frame: int | None = None
    stall_state: dict[str, Any] | None = None
    with controls.McpSession(
        rom=args.rom.resolve(),
        mesen=args.nexen.resolve(),
        cwd=ROOT,
        port=args.port,
        boot_wait=6.0,
        socket_timeout=300.0,
        stderr_log=args.output / "nexen.stderr.log",
    ) as m:
        m.pause()
        m.load_state(args.state.resolve())
        m.pause()
        m.tool("set_input", {"port": 0, "buttons": 0, "hold": True})
        initial = snapshot(m, "initial", -args.hold_frames - 1)
        controls.require_healthy("initial", initial)

        handles: dict[int, str] = {}
        for address, label, cpu in (
            (TICK_HOOK, "game_tick", "Sa1"),
            (PROJECTILE_ALLOCATOR_HOOK, "projectile_allocator", "Sa1"),
            (CHARGED_SHOT_ENTRY_HOOK, "charged_shot_entry", "Sa1"),
            (
                CHARGED_SHOT_CONTINUATION_HOOK,
                "charged_shot_continuation",
                "Sa1",
            ),
        ):
            handle = m.add_exec_hook(address, cpu_type=cpu)
            handles[handle] = label
        m.drain_notifications(timeout=0.05)

        m.tool(
            "set_input",
            {"port": 0, "buttons": controls.McpSession.BTN_B, "hold": True},
        )
        hold_run_results = []
        hold_remaining = args.hold_frames
        while hold_remaining:
            run_result = m.run_frames(hold_remaining)
            advanced = int(run_result.get("framesAdvanced", 0))
            if advanced <= 0 or advanced > hold_remaining:
                raise RuntimeError(
                    "invalid frame progress while holding B: "
                    f"remaining={hold_remaining}, result={run_result}"
                )
            hold_run_results.append(run_result)
            hold_remaining -= advanced
            m.pause()
            events.extend(
                hook_events(m.drain_notifications(timeout=0.05), handles)
            )
        held = snapshot(m, "held", -1)
        controls.require_healthy("held", held)
        held_state = save_state(m, args.output / "held.mss")
        held_screenshot = screenshot(m, args.output / "held.png")
        release_event_index = len(events)
        if args.cpu_trace:
            m.trace_log(count=1, cpu_type="Sa1")
            m.trace_log(count=1, cpu_type="Snes")

        m.tool("set_input", {"port": 0, "buttons": 0, "hold": True})
        stagnant_frames = 0
        frames_observed = 0
        stop_after_frames = args.observe_frames
        mandatory_samples = {
            1,
            3,
            9,
            args.observe_frames,
            *(frame + 1 for frame in capture_frames),
        }
        while frames_observed < stop_after_frames:
            future_samples = [
                frame
                for frame in mandatory_samples
                if frames_observed < frame <= stop_after_frames
            ]
            next_mandatory = min(future_samples, default=stop_after_frames)
            chunk = min(
                args.sample_frames,
                next_mandatory - frames_observed,
                stop_after_frames - frames_observed,
            )
            run_result = m.run_frames(chunk)
            advanced = int(run_result.get("framesAdvanced", 0))
            if advanced <= 0 or advanced > chunk:
                raise RuntimeError(
                    "invalid frame progress after release: "
                    f"requested={chunk}, observed={advanced}, result={run_result}"
                )
            frames_observed += advanced
            m.pause()
            chunk_events = hook_events(
                m.drain_notifications(timeout=0.05), handles
            )
            events.extend(chunk_events)
            relative_frame = frames_observed - 1
            current = progress_snapshot(
                m, f"post_release_{relative_frame}", relative_frame
            )
            records.append(current)
            if relative_frame in capture_frames:
                screenshots[relative_frame] = screenshot(
                    m, args.output / f"release-{relative_frame:04d}.png"
                )

            if any(event["label"] == "game_tick" for event in chunk_events):
                stagnant_frames = 0
            else:
                stagnant_frames += advanced

            if first_stall_frame is None and stagnant_frames >= args.stall_frames:
                first_stall_frame = relative_frame
                full_stall_snapshot = snapshot(
                    m, "first_sustained_stall", relative_frame
                )
                stall_state = {
                    "detected_at_relative_frame": relative_frame,
                    "stagnant_frames": stagnant_frames,
                    "snapshot": full_stall_snapshot,
                    "state": save_state(m, args.output / "first-stall.mss"),
                    "screenshot": screenshot(
                        m, args.output / "first-stall.png"
                    ),
                    "sa1_trace": m.trace_log(count=128, cpu_type="Sa1"),
                    "snes_trace": m.trace_log(count=128, cpu_type="Snes"),
                    "sa1_disassembly": m.disassemble(
                        full_stall_snapshot["sa1_pc"],
                        count=32,
                        cpu_type="Sa1",
                    ),
                    "snes_disassembly": m.disassemble(
                        full_stall_snapshot["snes_pc"],
                        count=32,
                        cpu_type="Snes",
                    ),
                }
                stop_after_frames = min(
                    args.observe_frames,
                    frames_observed + args.continue_after_stall,
                )

        for handle in handles:
            m.remove_hook(handle)
        final = snapshot(m, "final", records[-1]["relative_frame"])
        final_state = save_state(m, args.output / "final.mss")
        final_screenshot = screenshot(m, args.output / "final.png")

    events_path = args.output / "hooks.jsonl"
    events_path.write_text(
        "".join(json.dumps(event, sort_keys=True) + "\n" for event in events),
        encoding="utf-8",
    )
    records_path = args.output / "frames.jsonl"
    records_path.write_text(
        "".join(json.dumps(record, sort_keys=True) + "\n" for record in records),
        encoding="utf-8",
    )

    ticks_after_release = (final["tick"] - held["tick"]) & 0xFFFF
    render_completions_after_release = (
        final["render_complete_count"] - held["render_complete_count"]
    ) & 0xFFFF
    event_counts = {
        label: sum(event["label"] == label for event in events)
        for label in (
            "game_tick",
            "projectile_allocator",
            "charged_shot_entry",
            "charged_shot_continuation",
        )
    }
    release_events = events[release_event_index:]
    release_event_counts = {
        label: sum(event["label"] == label for event in release_events)
        for label in (
            "game_tick",
            "projectile_allocator",
            "charged_shot_entry",
            "charged_shot_continuation",
        )
    }
    release_seen = (
        held["player"].get("input") == 0xEF
        and any(
            record["player"].get("input") == 0xFF for record in records
        )
    )
    shot_animation_seen = any(
        record["player"].get("animation") == 0x7C for record in records
    )
    projectile_pool_changed = any(
        record["projectile_pool"]["sha256"]
        != held["projectile_pool"]["sha256"]
        for record in records
    )
    checks = {
        "real_b_reached_game": (
            held["frame"] - initial["frame"] == args.hold_frames
            and held["input_real_cache"] == "8000"
            and held["input_mailbox"] == "8000"
            and held["input_injection"] == "0000"
            and held["game_p1"] == "ef"
        ),
        "release_reached_game": release_seen,
        "charged_shot_animation_seen": shot_animation_seen,
        "charged_shot_handler_reached": (
            release_event_counts["charged_shot_entry"] > 0
        ),
        "charged_shot_continuation_reached": (
            release_event_counts["charged_shot_continuation"] > 0
        ),
        "projectile_path_observed": (
            event_counts["projectile_allocator"] > 0 or projectile_pool_changed
        ),
        "no_sustained_game_tick_stall": first_stall_frame is None,
        "interpreter_not_halted": final["halt"] == 0,
        "production_gates_intact": final["gates"] == controls.EXPECTED_GATES,
        "task_stacks_above_floors": not final["stack"]["below_floor"],
        "renderer_kept_completing": render_completions_after_release > 0,
    }
    result.update(
        {
            "initial": initial,
            "held": held,
            "hold_run_results": hold_run_results,
            "held_frames_actual": held["frame"] - initial["frame"],
            "held_state": held_state,
            "held_screenshot": held_screenshot,
            "frames_observed": records[-1]["relative_frame"] + 1,
            "sample_count": len(records),
            "final": final,
            "final_state": final_state,
            "final_screenshot": final_screenshot,
            "stall": stall_state,
            "deltas": {
                "ticks_after_release": ticks_after_release,
                "render_completions_after_release": (
                    render_completions_after_release
                ),
            },
            "event_counts": event_counts,
            "release_event_counts": release_event_counts,
            "projectile_pool_changed": projectile_pool_changed,
            "release_seen": release_seen,
            "shot_animation_seen": shot_animation_seen,
            "screenshots": {
                str(frame): value for frame, value in sorted(screenshots.items())
            },
            "hooks": {"path": str(events_path), "sha256": sha256(events_path)},
            "frames": {
                "path": str(records_path),
                "sha256": sha256(records_path),
            },
            "checks": checks,
            "result": "green" if all(checks.values()) else "red",
        }
    )
    result_path = args.output / "results.json"
    result_path.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "result": result["result"],
                "rom_sha256": result["rom_sha256"],
                "frames_observed": result["frames_observed"],
                "first_stall_frame": first_stall_frame,
                "deltas": result["deltas"],
                "event_counts": event_counts,
                "failed_checks": [
                    name for name, passed in checks.items() if not passed
                ],
                "results": str(result_path),
            },
            sort_keys=True,
        )
    )
    return 0 if result["result"] == "green" else 1


if __name__ == "__main__":
    raise SystemExit(main())
