#!/usr/bin/env python3
"""Fresh-boot liveness and ownership probe for the opt-in VTIME diagnostic.

This is deliberately narrower than the one-credit renderer regression.  It
starts a newly copied VTIME ROM at power-on, advances a bounded number of real
video frames with neutral controller input, and records the isolated timer
workspace alongside its untouched adjacent bytes.  It does not load a state,
write runtime memory, establish gameplay timing, or claim a production path.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_NEXEN = Path(
    "/mnt/sdc1/Nexen-r5-20260712/"
    "bin/linux-x64/Release/mcp-safe-checkpoint-publish/Nexen"
)

sys.path.insert(0, "/home/chad/Mesen2/python")
sys.path.insert(0, str(ROOT / "tools"))
import mesen_mcp.session as _session  # noqa: E402

_session.validate_mesen_build = lambda *_args, **_kwargs: None
from mesen_mcp import McpSession  # noqa: E402

import replay_mame_controller_campaign as campaign  # noqa: E402


VTIME_BASE = 0x404000
VTIME_SIZE = 0x1A
VTIME_MAGIC = 0xC71E


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def u16le(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 2], "little")


def write_progress(path: Path, payload: dict[str, Any]) -> None:
    """Publish a recoverable host-side boundary between emulator RPCs.

    A VTIME experiment can make even an otherwise small batch unexpectedly
    expensive.  This deliberately contains no emulator-memory claim (only a
    successful request boundary), but it prevents an interrupted run from
    losing the last known emulated frame to a buffered terminal report.
    """
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--nexen", type=Path, default=DEFAULT_NEXEN)
    # Twenty-four frames deterministically span a complete virtual deadline on
    # the retained diagnostic image.  A shorter no-halt check can miss a
    # countdown high-word alias that prevents reload/phase advancement.
    parser.add_argument("--frames", type=int, default=24)
    parser.add_argument(
        "--single-frame-after",
        type=int,
        default=0,
        help=(
            "Switch to one-frame MCP requests at this emulated video frame. "
            "Use near an experimental activation boundary so an unexpectedly "
            "slow frame still leaves a coherent post-frame state."
        ),
    )
    parser.add_argument(
        "--max-wall-seconds",
        type=float,
        default=0.0,
        help=(
            "Stop between completed frame requests after this host-time budget "
            "and retain an inconclusive state; zero means no host-time limit."
        ),
    )
    parser.add_argument("--port", type=int, default=9299)
    args = parser.parse_args()
    for label, path in (("ROM", args.rom), ("Nexen", args.nexen)):
        if not path.is_file():
            parser.error(f"missing {label}: {path}")
    if args.output.exists():
        parser.error(f"output already exists: {args.output}")
    if args.frames < 1 or args.single_frame_after < 0 or args.max_wall_seconds < 0:
        parser.error("frame counts and wall-time budget must be nonnegative; --frames must be positive")
    return args


def timer_snapshot(m: McpSession) -> dict[str, Any]:
    timer = bytes(m.read_memory("snesMemory", VTIME_BASE, VTIME_SIZE))
    before = bytes(m.read_memory("snesMemory", VTIME_BASE - 0x10, 0x10))
    after = bytes(m.read_memory("snesMemory", VTIME_BASE + VTIME_SIZE, 0x10))
    iram = bytes(m.read_memory("Sa1Memory", 0, 0x0800))
    return {
        "timer_bytes_hex": timer.hex(),
        "magic": u16le(timer, 0x00),
        "valid": u16le(timer, 0x02),
        "cost_units": u16le(timer, 0x04),
        "remaining_lo_units": u16le(timer, 0x06),
        "remaining_hi_units": u16le(timer, 0x08),
        "phase": u16le(timer, 0x0A),
        "overshoot_units": u16le(timer, 0x0C),
        "opcode": u16le(timer, 0x0E),
        "condition": u16le(timer, 0x10),
        "temporary": u16le(timer, 0x12),
        "native_pending_block": u16le(timer, 0x14),
        "native_current_block": u16le(timer, 0x16),
        "native_deadline_due": u16le(timer, 0x18),
        "adjacent_before_hex": before.hex(),
        "adjacent_after_hex": after.hex(),
        # Legacy scheduling fields remain observable even in VTIME mode.  A
        # nonzero `$AC` written by an old accelerator is especially useful
        # evidence: the virtual consumer deliberately ignores it, so this
        # exposes a mixed-clock boundary instead of hiding it in a screenshot.
        "legacy_instruction_countdown_ac": u16le(iram, 0x00AC),
        "irq_pending_aa": u16le(iram, 0x00AA),
        "sr_mask_7c": u16le(iram, 0x007C),
        "game_tick_0760": u16le(iram, 0x0760),
        "halt_iram_004e": u16le(iram, campaign.HALT_IRAM),
        "virtual_pc": int.from_bytes(iram[0x40:0x44], "little"),
        "interpreter_step": int.from_bytes(iram[0x4A:0x4E], "little"),
        "iram_stack_07e0_07ff_hex": iram[0x7E0:0x800].hex(),
        "sa1_cpu": m.get_cpu_state("Sa1"),
        "gameplay_native_gates": {
            "xlat_071a": u16le(iram, 0x071A),
            "fetch_chokepoint_073a": u16le(iram, 0x073A),
        },
    }


def main() -> int:
    args = parse_args()
    interpreter_only = bool(args.rom.read_bytes()[0x328000] & 0x02)
    output = args.output.resolve()
    output.mkdir(parents=True)
    states = output / "states"
    screenshots = output / "screenshots"
    states.mkdir()
    screenshots.mkdir()
    os.environ["DOTNET_ROOT"] = "/home/chad/.dotnet10"
    retained_rom = output / "vtime-rom.sfc"
    shutil.copy2(args.rom, retained_rom)
    with McpSession(
        rom=retained_rom,
        mesen=args.nexen.resolve(),
        cwd=ROOT,
        port=args.port,
        boot_wait=6.0,
        socket_timeout=120.0,
        stderr_log=output / "emulator.stderr.log",
    ) as m:
        m.pause()
        before_frame = int(m.get_state().get("frameCount", 0))
        before = timer_snapshot(m)
        # First call enables Nexen's bounded SA-1 trace ring; it intentionally
        # returns little/no history.  The post-run tail is retained for any
        # red liveness result rather than guessed from a screenshot.
        m.trace_log(1, "Sa1")
        # Keep each emulator RPC below the MCP socket timeout.  A single
        # thousands-of-frames run can complete in Nexen after the client has
        # already given up, which loses the after-state and makes a host-side
        # transport timeout look like a timer result.  ``run_frames`` resumes
        # the emulator rather than pausing at its response, so explicitly
        # rendezvous after every 120-frame slice before reading its boundary.
        # Nexen may acknowledge a loaded SA-1 request a few frames short of
        # its requested boundary.  Retain and retry that shortfall rather
        # than calling it a VTIME failure.  That accounting is part of this
        # probe's evidence.
        input_response = campaign.set_held_input(m, 0)
        run_response: list[dict[str, Any]] = []
        remaining = args.frames
        started = time.monotonic()
        timed_out = False
        progress_path = output / "progress.json"
        while remaining:
            slice_before = int(m.get_state().get("frameCount", 0))
            if (
                args.max_wall_seconds
                and time.monotonic() - started >= args.max_wall_seconds
            ):
                timed_out = True
                break
            requested = min(120, remaining)
            if args.single_frame_after:
                if slice_before >= args.single_frame_after:
                    requested = 1
                else:
                    requested = min(requested, args.single_frame_after - slice_before)
            write_progress(
                progress_path,
                {
                    "scope": (
                        "host-side completed-RPC progress only; this is not "
                        "an emulation-state snapshot or a validation result"
                    ),
                    "before_frame": before_frame,
                    "last_completed_frame": slice_before,
                    "next_requested_frames": requested,
                    "completed_requests": len(run_response),
                    "elapsed_wall_seconds": time.monotonic() - started,
                },
            )
            response = m.run_frames(requested)
            pause_response = m.pause()
            slice_after = int(m.get_state().get("frameCount", 0))
            advanced = slice_after - slice_before
            if advanced <= 0:
                raise RuntimeError(
                    "VTIME frame slice did not advance: "
                    f"requested={requested} advanced={advanced} "
                    f"response={response}"
                )
            run_response.append(
                {
                    "before": slice_before,
                    "after": slice_after,
                    "requested": requested,
                    "advanced": advanced,
                    "shortfall": requested - advanced,
                    "response": response,
                    "pause_response": pause_response,
                }
            )
            remaining -= min(remaining, advanced)
        write_progress(
            progress_path,
            {
                "scope": (
                    "host-side completed-RPC progress only; the completed "
                    "summary.json is the only emulation-state evidence"
                ),
                "before_frame": before_frame,
                "last_completed_frame": int(m.get_state().get("frameCount", 0)),
                "completed_requests": len(run_response),
                "timed_out_between_requests": timed_out,
                "elapsed_wall_seconds": time.monotonic() - started,
            },
        )
        after_frame = int(m.get_state().get("frameCount", 0))
        after = timer_snapshot(m)
        sa1_trace = m.trace_log(128, "Sa1")
        state = campaign.save_state(m, states / "fresh-vtime-liveness.mss")
        screenshot = campaign.screenshot(m, screenshots / "fresh-vtime-liveness.png")

    checks = {
        "requested_frames_advanced_at_least": (
            not timed_out and after_frame - before_frame >= args.frames
        ),
        "timer_magic_initialized": after["magic"] == VTIME_MAGIC,
        "timer_marked_valid": after["valid"] == 1,
        "timer_has_prepared_positive_cost": after["cost_units"] > 0,
        "timer_phase_in_fraction_range": 0 <= after["phase"] < 5743,
        "virtual_deadline_reloaded": after["phase"] != before["phase"],
        "no_interpreter_halt": after["halt_iram_004e"] == 0,
        "interpreter_retired_after_boot": (
            after["interpreter_step"] > before["interpreter_step"]
        ),
        # Both gates power up clear, so clear values alone are not proof that
        # the interpreter-only switch executed.  Require initialized virtual
        # state before attaching that meaning to their values.
        "interpreter_only_native_gates_disabled_after_timer_activation": (
            not interpreter_only
            or (
                after["magic"] == VTIME_MAGIC
                and after["valid"] == 1
                and (
                    after["gameplay_native_gates"]["xlat_071a"] == 0
                    and after["gameplay_native_gates"]["fetch_chokepoint_073a"] == 0
                )
            )
        ),
        "no_open_bus_brk_in_sa1_trace_tail": not any(
            row.get("text", "").startswith("BRK")
            and (int(row.get("pc", 0)) >> 16) == 0xFF
            for row in sa1_trace.get("rows", [])
        ),
    }
    phase_delta_units = (after["phase"] - before["phase"]) % 5743
    report = {
        "scope": (
            "fresh-power-on VTIME diagnostic liveness/ownership probe; neutral "
            "bounded real-video-frame run; no state load and no runtime memory "
            "write. It is not a gameplay, rate, renderer, or production proof."
        ),
        "result": "inconclusive" if timed_out else ("green" if all(checks.values()) else "red"),
        "checks": checks,
        "rom": str(retained_rom),
        "rom_sha256": sha256(retained_rom),
        "interpreter_only": interpreter_only,
        "nexen": str(args.nexen.resolve()),
        "nexen_sha256": sha256(args.nexen),
        "frames": {
            "before": before_frame,
            "requested": args.frames,
            "after": after_frame,
            "single_frame_after": args.single_frame_after,
            "max_wall_seconds": args.max_wall_seconds,
            "timed_out": timed_out,
        },
        "virtual_deadline_phase": {
            "increment_units": 50,
            "modulus_units": 5743,
            "delta_units_modulo_period": phase_delta_units,
            "whole_reloads_modulo_period": phase_delta_units // 50,
            "delta_is_whole_reload_count": phase_delta_units % 50 == 0,
            "note": (
                "This is modulo one 5,743-reload fractional period; it is a "
                "lower-bound phase observation, not a total-reload counter."
            ),
        },
        "before": before,
        "after": after,
        "runs": {"input": input_response, "responses": run_response},
        "sa1_trace_tail": sa1_trace,
        "state": state,
        "screenshot": screenshot,
        "runtime_memory_writes": [],
    }
    path = output / "summary.json"
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"result": report["result"], "checks": checks, "summary": str(path)}, sort_keys=True))
    return 0 if report["result"] == "green" else 1


if __name__ == "__main__":
    raise SystemExit(main())
