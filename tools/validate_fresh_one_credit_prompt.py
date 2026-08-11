#!/usr/bin/env python3
"""Cold-boot the production ROM and regress the one-credit prompt artwork.

This is intentionally independent of the eight-coin MAME-movie alignment used
by ``replay_mame_controller_campaign.py``.  It starts at power-on, sends one
real Select/coin edge, waits for the stable prompt, and retains the exact state
and screenshot.  Pixel predicates cover the two reported renderer failures:

* the right-hand gray artwork wedge must contain no black gap;
* the CREDIT text must leave the gray artwork visible between its glyphs.

The empty lower-right prompt area is also required to remain black.  This is a
fresh-ROM renderer/HUD gate, not gameplay or full-playthrough evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ROM = ROOT / "build/interp.sfc"
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    parser.add_argument("--nexen", type=Path, default=DEFAULT_NEXEN)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--port", type=int, default=9281)
    parser.add_argument("--cold-boot-frame", type=int, default=5248)
    parser.add_argument("--coin-frames", type=int, default=4)
    parser.add_argument("--settle-frames", type=int, default=155)
    args = parser.parse_args()
    for label, path in (("ROM", args.rom), ("Nexen", args.nexen)):
        if not path.is_file():
            parser.error(f"missing {label}: {path}")
    if args.output.exists():
        parser.error(f"output already exists: {args.output}")
    if min(args.cold_boot_frame, args.coin_frames, args.settle_frames) < 1:
        parser.error("all frame counts must be positive")
    return args


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def be16(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 2], "big")


def capture_snapshot(m: McpSession) -> dict[str, Any]:
    work = b"".join(
        bytes(m.read_memory("snesMemory", 0x400000 + offset, 0x4000))
        for offset in range(0, 0x10000, 0x4000)
    )
    iram = bytes(m.read_memory("Sa1Memory", 0, 0x0800))
    return {
        "video_frame": int(m.get_state().get("frameCount", 0)),
        "credits_f01c62": be16(work, 0x1C62),
        "halt_iram_004e": int.from_bytes(
            iram[campaign.HALT_IRAM : campaign.HALT_IRAM + 2], "little"
        ),
        "task_mask_f00002": be16(work, 0x0002),
        "frame_request_f01c56": be16(work, 0x1C56),
        "frame_ack_f01c58": be16(work, 0x1C58),
        "work_64k_sha256": hashlib.sha256(work).hexdigest(),
        "mapped_work_16k_sha256": hashlib.sha256(work[:0x4000]).hexdigest(),
    }


def inspect_pixels(path: Path) -> dict[str, Any]:
    image = Image.open(path).convert("RGB")
    black = (0, 0, 0)

    # The right side of the triangular artwork is a solid gray wedge in the
    # stable prompt.  Its sloped edge is x=y-31 for y=190..220.  A missing
    # source column/row introduces black pixels in this bounded interior.
    right_wedge_black = [
        [x, y]
        for y in range(190, 221)
        for x in range(150, y - 30)
        if image.getpixel((x, y)) == black
    ]

    # CREDIT overlays the gray triangle.  Transparent glyph rendering leaves
    # both $94 and $63 gray artwork pixels visible between white glyph pixels;
    # the reported opaque backing removed nearly all of these pixels.
    credit_box = image.crop((84, 210, 170, 222))
    artwork_grays = {(148, 148, 148), (99, 99, 99)}
    credit_artwork_pixels = sum(
        pixel in artwork_grays for pixel in credit_box.getdata()
    )

    # Outside the triangle, the lower-right prompt area is intentionally
    # empty.  Off-window status strings previously leaked into this region.
    lower_right = image.crop((192, 180, 256, 239))
    lower_right_nonblack = sum(
        pixel != black for pixel in lower_right.getdata()
    )
    return {
        "size": list(image.size),
        "right_wedge_black_count": len(right_wedge_black),
        "right_wedge_black_first": right_wedge_black[:32],
        "credit_box_artwork_gray_pixels": credit_artwork_pixels,
        "credit_box_artwork_gray_minimum": 700,
        "lower_right_nonblack_pixels": lower_right_nonblack,
    }


def legacy_run_frames(m: McpSession, frames: int) -> list[dict[str, Any]]:
    """Advance idle legacy Mesen without Nexen-only persistent input.

    Legacy Mesen's MCP ``set_input`` is deliberately a timed, running input
    override.  It does not accept Nexen's ``hold`` argument, so neutral spans
    must use its ordinary exact-frame request instead.
    """
    runs: list[dict[str, Any]] = []
    remaining = frames
    while remaining:
        requested = min(120, remaining)
        before = int(m.get_state().get("frameCount", 0))
        response = m.run_frames(requested)
        m.pause()
        after = int(m.get_state().get("frameCount", 0))
        advanced = after - before
        if advanced <= 0 or advanced > requested:
            raise RuntimeError(
                "invalid legacy-Mesen frame progress: "
                f"requested={requested}, advanced={advanced}, response={response}"
            )
        runs.append(
            {
                "before": before,
                "after": after,
                "requested": requested,
                "advanced": advanced,
                "response": response,
            }
        )
        remaining -= advanced
    return runs


def legacy_coin_pulse(m: McpSession, frames: int) -> dict[str, Any]:
    before = int(m.get_state().get("frameCount", 0))
    response = m.set_input(McpSession.BTN_SELECT, frames)
    m.pause()
    after = int(m.get_state().get("frameCount", 0))
    advanced = after - before
    if advanced <= 0 or advanced > frames:
        raise RuntimeError(
            "invalid legacy-Mesen Select progress: "
            f"requested={frames}, advanced={advanced}, response={response}"
        )
    return {
        "before": before,
        "after": after,
        "requested": frames,
        "advanced": advanced,
        "response": response,
    }


def main() -> int:
    args = parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True)
    states = output / "states"
    screenshots = output / "screenshots"
    states.mkdir()
    screenshots.mkdir()
    # Nexen is built with .NET 10, whereas the retained legacy-Mesen MCP
    # launcher requires .NET 8.  Do not overwrite the latter with Nexen's
    # runtime before McpSession spawns the emulator.
    dotnet_root = (
        "/home/chad/.dotnet8"
        if args.nexen.name == "mesen211_mcp_controller.sh"
        else "/home/chad/.dotnet10"
    )
    os.environ["DOTNET_ROOT"] = dotnet_root
    os.environ["PATH"] = f"{dotnet_root}:{os.environ['PATH']}"

    retained_rom = output / "campaign-rom.sfc"
    shutil.copy2(args.rom, retained_rom)
    rom_hash = sha256(retained_rom)
    legacy_mesen = args.nexen.name == "mesen211_mcp_controller.sh"
    with McpSession(
        rom=retained_rom,
        mesen=args.nexen.resolve(),
        cwd=ROOT,
        port=args.port,
        boot_wait=6.0,
        socket_timeout=300.0,
        stderr_log=output / "emulator.stderr.log",
    ) as m:
        m.pause()
        boot_frames = max(
            0,
            args.cold_boot_frame - int(m.get_state().get("frameCount", 0)),
        )
        if legacy_mesen:
            boot_runs = legacy_run_frames(m, boot_frames)
            coin_runs = [legacy_coin_pulse(m, args.coin_frames)]
            settle_runs = legacy_run_frames(m, args.settle_frames)
        else:
            boot_runs = campaign.run_exact_frames(m, 0, boot_frames)
            coin_runs = campaign.run_coin_pulses(m, 1, args.coin_frames, 0)
            settle_runs = campaign.run_exact_frames(m, 0, args.settle_frames)
        snapshot = capture_snapshot(m)
        state = campaign.save_state(
            m, states / "one-credit-prompt.mss"
        )
        screenshot = campaign.screenshot(
            m, screenshots / "one-credit-prompt.png"
        )

    pixels = inspect_pixels(Path(screenshot["path"]))
    expected_screenshot_size = [256, 224] if legacy_mesen else [256, 239]
    checks = {
        "fresh_credit_count_is_one": snapshot["credits_f01c62"] == 1,
        "halt_zero": snapshot["halt_iram_004e"] == 0,
        "task_mask_nonzero": snapshot["task_mask_f00002"] != 0,
        "screenshot_has_expected_emulator_height": (
            pixels["size"] == expected_screenshot_size
        ),
        "right_artwork_wedge_has_no_black_gap": (
            pixels["right_wedge_black_count"] == 0
        ),
        "credit_text_preserves_artwork_underlay": (
            pixels["credit_box_artwork_gray_pixels"]
            >= pixels["credit_box_artwork_gray_minimum"]
        ),
        "lower_right_status_garbage_absent": (
            pixels["lower_right_nonblack_pixels"] == 0
        ),
    }
    result = "green" if all(checks.values()) else "red"
    summary = {
        "scope": (
            "fresh-power-on one-credit production-ROM prompt regression; one "
            "real controller Select edge; no save-state load or runtime "
            "memory write; renderer/HUD evidence, not gameplay or fps"
        ),
        "result": result,
        "checks": checks,
        "rom": str(retained_rom),
        "rom_sha256": rom_hash,
        "nexen": str(args.nexen.resolve()),
        "nexen_sha256": sha256(args.nexen),
        "configuration": {
            "cold_boot_frame": args.cold_boot_frame,
            "coin_pulses": 1,
            "coin_frames": args.coin_frames,
            "settle_frames": args.settle_frames,
            "input_transport": (
                "legacy-Mesen timed port-0 override"
                if legacy_mesen
                else "Nexen persistent controller override"
            ),
            "expected_screenshot_size": expected_screenshot_size,
        },
        "runtime_memory_writes": [],
        "snapshot": snapshot,
        "pixels": pixels,
        "state": state,
        "screenshot": screenshot,
        "runs": {
            "boot": boot_runs,
            "coin": coin_runs,
            "settle": settle_runs,
        },
    }
    summary_path = output / "summary.json"
    summary_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "result": result,
                "checks": checks,
                "rom_sha256": rom_hash,
                "summary": str(summary_path),
            },
            sort_keys=True,
        ),
        flush=True,
    )
    return 0 if result == "green" else 1


if __name__ == "__main__":
    raise SystemExit(main())
