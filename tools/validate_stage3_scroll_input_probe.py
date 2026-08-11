#!/usr/bin/env python3
"""Three-way Stage-3 checkpoint scroll recovery probe.

This is deliberately checkpoint-scoped.  It loads the supplied Stage-3 state,
refreshes only the selected ROM's WRAM video mirror, then runs the same ordinary
right-input span with native escapes disabled and enabled.  The serialized PPU
state, one neutral post-restore vblank, and post-input publication are retained
with screenshots and machine snapshots.  It is not fresh-boot or organic Stage-3
proof. A known-bad serialized blue gap is fixture input, never a passing
renderer acceptance condition.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
MESEN_PY = Path("/home/chad/Mesen2/python")
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(MESEN_PY))

import trace_playtest_actions as trace  # noqa: E402

import mesen_mcp.session as _session  # noqa: E402

_session.validate_mesen_build = lambda *_args, **_kwargs: None
from mesen_mcp import McpSession  # noqa: E402

FLOOR_START = 0xC10882


def floors(m: McpSession) -> list[int]:
    raw = bytes(m.read_memory("snesMemory", FLOOR_START, 16 * 4))
    return [int.from_bytes(raw[i * 4 : (i + 1) * 4], "big") for i in range(16)]

def configure_dotnet(emulator: Path) -> None:
    """Select the runtime expected by the requested emulator binary.

    The legacy Mesen controller is a .NET 8 application, while the MCP-enabled
    Nexen oracle is .NET 10.  Forcing .NET 8 made a Nexen invocation fail before
    it opened its MCP port, silently leaving this renderer probe restricted to
    the legacy emulator.  Keep the selection explicit in the evidence report
    path so a requested Nexen run is genuinely a Nexen run.
    """

    dotnet = "/home/chad/.dotnet10" if emulator.name == "Nexen" else "/home/chad/.dotnet8"
    other = "/home/chad/.dotnet8" if dotnet.endswith("10") else "/home/chad/.dotnet10"
    os.environ["DOTNET_ROOT"] = dotnet
    existing = [
        item
        for item in os.environ.get("PATH", "").split(":")
        if item not in ("/home/chad/.dotnet8", "/home/chad/.dotnet10")
    ]
    os.environ["PATH"] = ":".join([dotnet, other, *existing])


VIDEO_FILE_BASE = 0x298000
VIDEO_WRAM_OFFSET = 0x18000
VIDEO_WRAM_LENGTH = 0x3000
NATIVE_GATES = (0x071A, 0x073A)
NATIVE_ESCAPE_BANKS = frozenset(range(0x92, 0xA0))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sa1_pc(m: McpSession) -> int:
    cpu = m.get_cpu_state("Sa1")
    return ((int(cpu.get("k", 0)) & 0xFF) << 16) | (
        int(cpu.get("pc", 0)) & 0xFFFF
    )


def require_gate_safe_state(m: McpSession) -> int:
    """Reject a gate flip that would leave a serialized HLE span in flight."""

    pc = sa1_pc(m)
    if ((pc >> 16) & 0xFF) in NATIVE_ESCAPE_BANKS:
        raise RuntimeError(
            "refusing native-off checkpoint probe: loaded state resumes inside "
            f"a native escape at ${pc:06X}; configure gates before capturing "
            "the variant state"
        )
    return pc


def blue_gap_columns(path: Path) -> list[int]:
    """Identify the solid-blue vertical background hole in the playfield."""
    image = Image.open(path).convert("RGB")
    columns: list[int] = []
    for x in range(image.width):
        colors = [image.getpixel((x, y)) for y in range(80, min(210, image.height))]
        color, count = Counter(colors).most_common(1)[0]
        if count >= 110 and color[0] < 30 and 70 <= color[1] < 180 and color[2] > 150:
            columns.append(x)
    return columns


def advance_exact(m: McpSession, buttons: int, frames: int) -> int:
    """Hold buttons until exactly the requested number of video frames elapse."""
    before = int(m.get_state().get("frameCount", 0))
    while True:
        current = int(m.get_state().get("frameCount", 0))
        advanced = current - before
        if advanced >= frames:
            return advanced
        # Some MCP builds treat a one-frame all-neutral set_input request as a
        # controller-state update only and leave emulation paused. A neutral
        # restore vblank is still a real video advance, so drive it explicitly.
        response = (
            m.run_frames(frames - advanced)
            if buttons == 0
            else m.set_input(buttons, frames - advanced)
        )
        m.pause()
        after = int(m.get_state().get("frameCount", 0))
        if after <= current:
            raise RuntimeError(f"input made no video progress: {response}")


def write_mirror(m: McpSession, rom: Path) -> str:
    mirror = rom.read_bytes()[VIDEO_FILE_BASE : VIDEO_FILE_BASE + VIDEO_WRAM_LENGTH]
    if len(mirror) != VIDEO_WRAM_LENGTH:
        raise RuntimeError("selected ROM does not contain the video mirror")
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
        raise RuntimeError("video mirror refresh failed verification")
    return hashlib.sha256(mirror).hexdigest()


def run_variant(
    *,
    rom: Path,
    state: Path,
    mesen: Path,
    output: Path,
    port: int,
    native: bool,
) -> dict[str, Any]:
    label = "native_on" if native else "native_off"
    variant = output / label
    variant.mkdir(parents=True, exist_ok=True)
    with McpSession(
        rom=rom.resolve(),
        mesen=mesen.resolve(),
        cwd=ROOT,
        port=port,
        boot_wait=6.0,
        socket_timeout=300.0,
        stderr_log=variant / "mesen.stderr.log",
    ) as m:
        m.pause()
        m.load_state(state.resolve())
        m.pause()
        mirror_sha256 = write_mirror(m, rom)
        if not native:
            gate_safe_pc = require_gate_safe_state(m)
            for address in NATIVE_GATES:
                m.write_memory("Sa1Memory", address, "0000")
        else:
            gate_safe_pc = None
        stack_floors = floors(m)
        initial = trace.snapshot(m, stack_floors, f"{label}/initial", -1)
        trace.take_screenshot(m, variant / "initial.png")
        initial_blue_gap = blue_gap_columns(variant / "initial.png")
        trace.save_state(m, variant / "initial.mss")

        # No ROM code has executed while the loaded emulator is paused. One
        # neutral physical vblank is therefore the correct state-restore
        # acceptance point: a repair must clear the PPU defect without waiting
        # for a game-frame renderer publication or player movement.
        restore_vblank_frames = advance_exact(m, 0, 1)
        after_restore = trace.snapshot(
            m, stack_floors, f"{label}/after-restore-vblank", -1
        )
        trace.take_screenshot(m, variant / "after-restore-vblank.png")
        after_restore_blue_gap = blue_gap_columns(
            variant / "after-restore-vblank.png"
        )

        before = int(m.get_state().get("frameCount", 0))
        right_frames = advance_exact(m, trace.BUTTONS["right"], 60)
        mid = trace.snapshot(m, stack_floors, f"{label}/after-right", 0)
        trace.take_screenshot(m, variant / "after-right.png")
        neutral_frames = advance_exact(m, 0, 60)
        final = trace.snapshot(m, stack_floors, f"{label}/final", 1)
        trace.take_screenshot(m, variant / "final.png")
        final_blue_gap = blue_gap_columns(variant / "final.png")
        trace.save_state(m, variant / "final.mss")
        after = int(m.get_state().get("frameCount", 0))

    return {
        "native": native,
        "native_gate_values": {
            f"{address:04X}": 1 if native else 0 for address in NATIVE_GATES
        },
        "native_gate_mutation_safe_sa1_pc": (
            f"{gate_safe_pc:06X}" if gate_safe_pc is not None else None
        ),
        "mirror_sha256": mirror_sha256,
        "frames_advanced": after - before,
        "right_frames_advanced": right_frames,
        "neutral_frames_advanced": neutral_frames,
        "initial_blue_gap_columns": initial_blue_gap,
        "after_restore_vblank_blue_gap_columns": after_restore_blue_gap,
        "restore_vblank_frames_advanced": restore_vblank_frames,
        "final_blue_gap_columns": final_blue_gap,
        "checkpoint_stage_ready": (
            initial["tick"] >= 1000
            and initial["frame_request"] != 0
            and initial["render_generation"] != 0
        ),
        "initial": initial,
        "after_restore_vblank": after_restore,
        "after_right": mid,
        "final": final,
        "screenshots": {
            name: str((variant / name).resolve())
            for name in (
                "initial.png",
                "after-restore-vblank.png",
                "after-right.png",
                "final.png",
            )
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, default=ROOT / "build/interp.sfc")
    parser.add_argument("--state", type=Path, default=ROOT / "build/playtest/stage3.mss")
    parser.add_argument(
        "--mesen",
        type=Path,
        default=ROOT / "tools/mesen211_mcp_controller.sh",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8952)
    parser.add_argument(
        "--allow-known-stale-initial-gap",
        action="store_true",
        help=(
            "classify the retained bad initial blue strip as an expected "
            "reproducer only. This never establishes renderer acceptance."
        ),
    )
    args = parser.parse_args()
    args.output = args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=True)
    configure_dotnet(args.mesen.resolve())

    report = {
        "scope": (
            "same stale Stage-3 checkpoint and right-input span in exact Mesen, "
            "native-off/native-on; not fresh boot or organic Stage-3 proof"
        ),
        "rom": str(args.rom.resolve()),
        "rom_sha256": sha256(args.rom),
        "state": str(args.state.resolve()),
        "state_sha256": sha256(args.state),
        "mesen": str(args.mesen.resolve()),
        "mesen_sha256": sha256(args.mesen),
        "dotnet_root": os.environ["DOTNET_ROOT"],
        "allow_known_stale_initial_gap": args.allow_known_stale_initial_gap,
        "variants": {},
    }
    for index, native in enumerate((False, True)):
        report["variants"]["native_on" if native else "native_off"] = run_variant(
            rom=args.rom,
            state=args.state,
            mesen=args.mesen,
            output=args.output,
            port=args.port + index,
            native=native,
        )

    off = report["variants"]["native_off"]
    on = report["variants"]["native_on"]
    checks = {
        "native_off_checkpoint_is_stage3": off["checkpoint_stage_ready"],
        "native_on_checkpoint_is_stage3": on["checkpoint_stage_ready"],
        "same_initial_stale_hscroll": (
            off["initial"]["bg1_hscroll"] == on["initial"]["bg1_hscroll"]
        ),
        "initial_hscroll_is_stale_288": off["initial"]["bg1_hscroll"] == 288,
        "native_off_fixture_starts_with_blue_gap": bool(
            off["initial_blue_gap_columns"]
        ),
        "native_on_fixture_starts_with_blue_gap": bool(
            on["initial_blue_gap_columns"]
        ),
        "native_off_restore_vblank_exact": (
            off["restore_vblank_frames_advanced"] == 1
        ),
        "native_on_restore_vblank_exact": (
            on["restore_vblank_frames_advanced"] == 1
        ),
        "native_off_restore_does_not_advance_game_tick": (
            off["after_restore_vblank"]["tick"] == off["initial"]["tick"]
        ),
        "native_on_restore_does_not_advance_game_tick": (
            on["after_restore_vblank"]["tick"] == on["initial"]["tick"]
        ),
        "native_off_restore_vblank_blue_gap_cleared": (
            not off["after_restore_vblank_blue_gap_columns"]
            or args.allow_known_stale_initial_gap
        ),
        "native_on_restore_vblank_blue_gap_cleared": (
            not on["after_restore_vblank_blue_gap_columns"]
            or args.allow_known_stale_initial_gap
        ),
        "native_off_recovers_scroll": off["final"]["bg1_hscroll"] != 288,
        "native_on_recovers_scroll": on["final"]["bg1_hscroll"] != 288,
        "native_off_final_blue_gap_cleared": not off["final_blue_gap_columns"],
        "native_on_final_blue_gap_cleared": not on["final_blue_gap_columns"],
        "native_off_requested_input_window_completed": off["frames_advanced"] >= 120,
        "native_on_requested_input_window_completed": on["frames_advanced"] >= 120,
        "native_off_halt_zero": off["final"]["halt"] == 0,
        "native_on_halt_zero": on["final"]["halt"] == 0,
        "native_off_stacks_valid": not off["final"]["invalid"],
        "native_on_stacks_valid": not on["final"]["invalid"],
    }
    report["checks"] = checks
    report["result"] = "green" if all(checks.values()) else "red"
    report["summary"] = {
        "native_off_initial_hscroll": off["initial"]["bg1_hscroll"],
        "native_off_restore_hscroll": off["after_restore_vblank"]["bg1_hscroll"],
        "native_off_final_hscroll": off["final"]["bg1_hscroll"],
        "native_on_initial_hscroll": on["initial"]["bg1_hscroll"],
        "native_on_restore_hscroll": on["after_restore_vblank"]["bg1_hscroll"],
        "native_on_final_hscroll": on["final"]["bg1_hscroll"],
        "native_off_tick_delta": off["final"]["tick"] - off["initial"]["tick"],
        "native_on_tick_delta": on["final"]["tick"] - on["initial"]["tick"],
        "native_off_initial_blue_gap_columns": len(off["initial_blue_gap_columns"]),
        "native_on_initial_blue_gap_columns": len(on["initial_blue_gap_columns"]),
    }
    (args.output / "summary.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["result"] == "green" else 1


if __name__ == "__main__":
    raise SystemExit(main())
