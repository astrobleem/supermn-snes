#!/usr/bin/env python3
"""Sample framebuffers under a directly held MCP controller input.

This focused checkpoint diagnostic is the non-movie counterpart to
``capture_snes_input_framebuffers.py``. It requests one input step per iteration
and retains every resulting sampled image. Legacy Mesen's direct controller API
can advance zero or two actual video frames for a one-step request, so this tool
does not claim consecutive video-frame coverage. Use
``capture_snes_input_framebuffers.py`` for verified frame-exact movie replay.
Explicit cross-ROM migrations are imported from that tool and recorded in full.
It is not fresh boot, FPS, an aligned MAME pixel oracle, or aggregate gameplay
acceptance.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, "/home/chad/Mesen2/python")

import capture_mesen211_transitions as capture  # noqa: E402
from capture_snes_input_framebuffers import (  # noqa: E402
    BUTTONS,
    apply_checkpoint_migration,
    configure_dotnet,
)
from gameplay_acceptance_contract import unknown_diagnostic_gate  # noqa: E402
import mesen_mcp.session as _session  # noqa: E402

_session.validate_mesen_build = lambda *_args, **_kwargs: None
from mesen_mcp import McpSession  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--emulator", type=Path, required=True)
    parser.add_argument("--port", type=int, default=9400)
    parser.add_argument("--buttons", choices=sorted(BUTTONS), required=True)
    parser.add_argument("--frames", type=int, required=True)
    parser.add_argument("--checkpoint-step", type=int, default=30)
    parser.add_argument(
        "--stop-at-coherent-idle",
        action="store_true",
        help=(
            "treat --frames as a ceiling and stop after a nonzero frame when "
            "the renderer is idle, both queues are empty, and all generations agree"
        ),
    )
    parser.add_argument(
        "--coherent-idle-settle-frames",
        type=int,
        default=2,
        help=(
            "with --stop-at-coherent-idle, require this many additional "
            "coherent-idle video frames before saving the final state/image "
            "(default: 2, covering legacy Mesen screenshot latency)"
        ),
    )
    parser.add_argument("--refresh-video-mirror", action="store_true")
    parser.add_argument(
        "--park-sa1-at-current-pc",
        action="store_true",
        help=(
            "park the paused SA-1 with a runtime BRA -2 while the 5A22 performs "
            "a checkpoint-only forced rebuild"
        ),
    )
    parser.add_argument("--reserve-bg-slot-zero-migration", action="store_true")
    parser.add_argument("--shift-bg-slots-for-reserved-zero", action="store_true")
    return parser.parse_args()


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def coherent_idle(row: dict[str, Any]) -> bool:
    generations = (
        row["snapshot_generation"],
        row["direct_generation"],
        row["rendered_generation"],
    )
    return (
        row["renderer_busy"] == 0
        and row["render_queue_primary"] == 0
        and row["render_queue_secondary"] == 0
        and len(set(generations)) == 1
    )


def main() -> int:
    args = parse_args()
    if (
        args.frames <= 0
        or args.checkpoint_step <= 0
        or args.coherent_idle_settle_frames < 0
    ):
        raise SystemExit("invalid frame count")
    for path in (args.rom, args.state, args.emulator):
        if not path.is_file():
            raise FileNotFoundError(path)
    if (
        args.reserve_bg_slot_zero_migration
        and args.shift_bg_slots_for_reserved_zero
    ):
        raise SystemExit("select only one BG slot-zero migration strategy")
    if (
        args.reserve_bg_slot_zero_migration
        or args.shift_bg_slots_for_reserved_zero
    ) and not args.refresh_video_mirror:
        raise SystemExit("BG slot migration requires --refresh-video-mirror")
    output = args.output.resolve()
    if output.exists():
        raise SystemExit(f"refusing existing output: {output}")
    output.mkdir(parents=True)
    configure_dotnet(args.emulator)
    rom = args.rom.resolve()
    rom_bytes = rom.read_bytes()
    if len(rom_bytes) != 0x400000:
        raise SystemExit("expected a 4 MiB production ROM")
    if int.from_bytes(rom_bytes[0x77E0:0x77E2], "little") != 0:
        raise SystemExit("refusing non-production ROM: TESTFLAG is set")

    rows: list[dict[str, Any]] = []
    interventions: list[dict[str, Any]] = []
    idle_streak = 0
    settled_idle_reached = False
    parked_tick: int | None = None
    with McpSession(
        rom=rom,
        mesen=args.emulator.resolve(),
        cwd=ROOT,
        port=args.port,
        boot_wait=8.0,
        socket_timeout=300.0,
        stderr_log=output / "emulator.stderr.log",
    ) as m:
        m.pause()
        m.load_state(args.state.resolve())
        m.pause()
        if args.park_sa1_at_current_pc:
            parked_tick = capture.snapshot(m)["tick"]
            interventions.append(
                capture.park_sa1_at_current_pc(
                    m,
                    "retain the drained checkpoint producer park during the forced rebuild",
                )
            )
        if args.refresh_video_mirror:
            interventions.extend(
                apply_checkpoint_migration(
                    m,
                    rom_bytes,
                    args.reserve_bg_slot_zero_migration,
                    args.shift_bg_slots_for_reserved_zero,
                )
            )

        for relative in range(args.frames + 1):
            row = capture.snapshot(m)
            row["relative_frame"] = relative
            if parked_tick is not None and row["tick"] != parked_tick:
                raise RuntimeError(
                    "SA-1 producer park failed: "
                    f"tick changed from {parked_tick} to {row['tick']} "
                    f"at relative frame {relative}"
                )
            row["screenshot"] = capture.take_screenshot(
                m, output / f"frame-{relative:06d}.png"
            )
            if relative % args.checkpoint_step == 0:
                row["checkpoint"] = capture.save_checkpoint(
                    m, output / f"frame-{relative:06d}.mss"
                )
            rows.append(row)
            if args.stop_at_coherent_idle and relative > 0:
                if coherent_idle(row):
                    idle_streak += 1
                else:
                    idle_streak = 0
                if idle_streak > args.coherent_idle_settle_frames:
                    row["checkpoint"] = capture.save_checkpoint(
                        m, output / "coherent-idle.mss"
                    )
                    settled_idle_reached = True
                    break
            if relative == args.frames:
                break
            before = int(m.get_state().get("frameCount", 0))
            response = m.set_input(BUTTONS[args.buttons], 1)
            m.pause()
            after = int(m.get_state().get("frameCount", 0))
            row["next_input_step"] = {
                "before_video_frame": before,
                "after_video_frame": after,
                "video_frames_advanced": after - before,
                "response": response,
            }
        # The emulator is paused and will now shut down; no additional frame
        # can observe the held mask, so a synthetic release frame is omitted.

    coverage = {
        "game_tick_start": rows[0]["tick"],
        "game_tick_end": rows[-1]["tick"],
        "sample_video_frame_start": rows[0]["frame"],
        "sample_video_frame_end": rows[-1]["frame"],
        "sample_count": len(rows),
        "consecutive_video_frames": False,
        "complete": True,
    }
    acceptance_gate = unknown_diagnostic_gate(
        "direct_framebuffer_capture",
        "Sample acquisition is not consecutive coverage or visual correctness.",
    )
    acceptance_gate["rom_sha256"] = sha256(rom)
    acceptance_gate["coverage"] = coverage
    report = {
        "schema": 1,
        "scope": (
            "checkpointed direct-controller input-step framebuffer sampling; "
            "not consecutive video-frame coverage, fresh boot, FPS, aligned "
            "MAME pixels, or aggregate green"
        ),
        "rom": str(rom),
        "rom_sha256": sha256(rom),
        "state": str(args.state.resolve()),
        "state_sha256": sha256(args.state),
        "emulator": str(args.emulator.resolve()),
        "emulator_sha256": sha256(args.emulator),
        "buttons": args.buttons,
        "button_mask": BUTTONS[args.buttons],
        "requested_frame_ceiling": args.frames,
        "coherent_idle_settle_frames": args.coherent_idle_settle_frames,
        "final_coherent_idle_streak": idle_streak,
        "stopped_at_coherent_idle": settled_idle_reached,
        "runtime_memory_writes": interventions,
        "coverage": coverage,
        "start_video_frame": rows[0]["frame"],
        "end_video_frame": rows[-1]["frame"],
        "captures": rows,
        "acceptance_gate": acceptance_gate,
    }
    target = output / "results.json"
    target.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(
        json.dumps(
            {
                "result": "captured",
                "frames": len(rows),
                "start_video_frame": rows[0]["frame"],
                "end_video_frame": rows[-1]["frame"],
                "start_tick": rows[0]["tick"],
                "end_tick": rows[-1]["tick"],
                "report": str(target),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
