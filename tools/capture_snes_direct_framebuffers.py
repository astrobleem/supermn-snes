#!/usr/bin/env python3
"""Capture every framebuffer under a directly held MCP controller input.

This focused checkpoint diagnostic is the non-movie counterpart to
``capture_snes_input_framebuffers.py``. It advances exactly one video frame per
iteration and retains every image. Explicit cross-ROM migrations are imported
from that tool and recorded in full. It is not fresh boot, FPS, an aligned MAME
pixel oracle, or aggregate gameplay acceptance.
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
    parser.add_argument("--refresh-video-mirror", action="store_true")
    parser.add_argument("--reserve-bg-slot-zero-migration", action="store_true")
    parser.add_argument("--shift-bg-slots-for-reserved-zero", action="store_true")
    return parser.parse_args()


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    args = parse_args()
    if args.frames <= 0 or args.checkpoint_step <= 0:
        raise SystemExit("frame counts must be positive")
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
    if args.output.exists():
        raise SystemExit(f"refusing existing output: {args.output}")
    args.output.mkdir(parents=True)
    configure_dotnet(args.emulator)
    rom = args.rom.resolve()
    rom_bytes = rom.read_bytes()
    if len(rom_bytes) != 0x400000:
        raise SystemExit("expected a 4 MiB production ROM")
    if int.from_bytes(rom_bytes[0x77E0:0x77E2], "little") != 0:
        raise SystemExit("refusing non-production ROM: TESTFLAG is set")

    rows: list[dict[str, Any]] = []
    interventions: list[dict[str, Any]] = []
    with McpSession(
        rom=rom,
        mesen=args.emulator.resolve(),
        cwd=ROOT,
        port=args.port,
        boot_wait=8.0,
        socket_timeout=300.0,
        stderr_log=args.output / "emulator.stderr.log",
    ) as m:
        m.pause()
        m.load_state(args.state.resolve())
        m.pause()
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
            row["screenshot"] = capture.take_screenshot(
                m, args.output / f"frame-{relative:06d}.png"
            )
            if relative % args.checkpoint_step == 0:
                row["checkpoint"] = capture.save_checkpoint(
                    m, args.output / f"frame-{relative:06d}.mss"
                )
            rows.append(row)
            if relative == args.frames:
                break
            m.tool(
                "set_input",
                {"port": 0, "buttons": BUTTONS[args.buttons], "hold": True},
            )
            response = m.run_frames(1)
            m.pause()
            if int(response.get("framesAdvanced", 0)) != 1:
                raise RuntimeError(f"one-frame advance failed: {response!r}")
            row["next_frame_response"] = response
        # The emulator is paused and will now shut down; no additional frame
        # can observe the held mask, so a synthetic release frame is omitted.

    report = {
        "schema": 1,
        "scope": (
            "checkpointed direct-controller exact-one-video-frame framebuffer "
            "capture; not fresh boot, FPS, aligned MAME pixels, or aggregate green"
        ),
        "rom": str(rom),
        "rom_sha256": sha256(rom),
        "state": str(args.state.resolve()),
        "state_sha256": sha256(args.state),
        "emulator": str(args.emulator.resolve()),
        "emulator_sha256": sha256(args.emulator),
        "buttons": args.buttons,
        "button_mask": BUTTONS[args.buttons],
        "runtime_memory_writes": interventions,
        "start_video_frame": rows[0]["frame"],
        "end_video_frame": rows[-1]["frame"],
        "captures": rows,
        "acceptance_gate": unknown_diagnostic_gate(
            "direct_framebuffer_capture",
            "Capture success is evidence availability, not visual correctness.",
        ),
    }
    target = args.output / "results.json"
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
