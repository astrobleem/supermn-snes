#!/usr/bin/env python3
"""Validate visible punch/kick responses from a production gameplay checkpoint.

Each variant starts in a fresh Nexen process from the same checkpoint and is
synchronized at the native player-input copier.  The active variants press B
(arcade Button 1 / punch) or A (arcade Button 2 / kick) for a short, realistic
tap and then release it.  Per-video-frame player locals and selected screenshots
are compared with an idle control.

This is checkpointed controller/gameplay/rendering evidence, not an end-to-end
performance measurement.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import time
from pathlib import Path
from typing import Any

from PIL import Image, ImageChops, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, "/home/chad/Mesen2/python")

import mesen_mcp.session as _session

_session.validate_mesen_build = lambda *_args, **_kwargs: None
from mesen_mcp import McpSession


DEFAULT_NEXEN = Path(
    "/mnt/sdc1/Nexen-r5-20260712/"
    "bin/linux-x64/Release/linux-x64/publish/Nexen"
)
PLAYER_INPUT_ENTRY = 0x97B800
EXPECTED_PLAYER_A6 = 0xF01302
CAPTURE_FRAMES = {0, 1, 2, 3, 4, 6, 8, 10, 12, 16, 20, 24, 32, 40, 48}
VARIANTS = {
    "idle": 0,
    "punch": McpSession.BTN_B,
    "kick": McpSession.BTN_A,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, default=ROOT / "build/interp.sfc")
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--nexen", type=Path, default=DEFAULT_NEXEN)
    parser.add_argument("--port", type=int, default=8131)
    parser.add_argument("--tap-frames", type=int, default=4)
    parser.add_argument("--observe-frames", type=int, default=48)
    parser.add_argument(
        "--prelude-buttons",
        type=lambda value: int(value, 0),
        default=0,
        help="Optional controller mask used to position the player before the tap.",
    )
    parser.add_argument(
        "--prelude-frames",
        type=int,
        default=0,
        help="Video frames to hold --prelude-buttons before the synchronized tap.",
    )
    parser.add_argument(
        "--sync-max-frames",
        type=int,
        default=600,
        help="Maximum video frames to wait for the live player-input boundary.",
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


def be16(data: bytes) -> int:
    return int.from_bytes(data, "big")


def read_player_a6(m: McpSession) -> int:
    return le32(m.read_memory("Sa1Memory", 0x0038, 4)) & 0xFFFFFF


def bwram_address(address: int) -> int:
    if not 0xF00000 <= address <= 0xF0FFFF:
        raise ValueError(f"not a canonical game work-RAM address: {address:#08x}")
    return 0x400000 | (address & 0xFFFF)


def synchronize_player(
    m: McpSession, max_frames: int
) -> tuple[dict[str, Any], list[int]]:
    hook = m.add_exec_hook(PLAYER_INPUT_ENTRY, cpu_type="Sa1")
    observed_a6: list[int] = []
    result: dict[str, Any] = {}
    try:
        for _attempt in range(max_frames * 16):
            result = m.run_until(max_frames=max_frames, hook_handle=hook)
            m.pause()
            if (result or {}).get("reason") != "hookFired":
                break
            a6 = read_player_a6(m)
            observed_a6.append(a6)
            if a6 == EXPECTED_PLAYER_A6:
                return result, observed_a6
    finally:
        m.remove_hook(hook)
    return result, observed_a6


def take_screenshot(m: McpSession, target: Path) -> dict[str, Any]:
    response = m.take_screenshot(format="path")
    shutil.copy2(Path(response["path"]), target)
    return {
        "path": str(target),
        "sha256": sha256(target),
        "response": response,
    }


def snapshot(m: McpSession, player_a6: int, relative_frame: int) -> dict[str, Any]:
    local = m.read_memory(
        "snesMemory", bwram_address(player_a6 - 0x60), 0x80
    )
    manifest_length = le16(m.read_memory("snesWorkRam", 0x89BA, 2))
    packed_length = manifest_length & 0x7FFF
    if packed_length > 0x0300:
        packed_length = 0
    manifest = m.read_memory("snesWorkRam", 0xBC00, packed_length)
    oam = m.read_memory("snesWorkRam", 0x8600, 0x0220)
    state = m.get_state()

    def local_byte(offset: int) -> int:
        return local[0x60 + offset]

    def local_word(offset: int) -> int:
        index = 0x60 + offset
        return be16(local[index : index + 2])

    return {
        "relative_frame": relative_frame,
        "video_frame": int(state.get("frameCount", 0)),
        "game_tick": le16(m.read_memory("Sa1Memory", 0x0760, 2)),
        "pc68k": le32(m.read_memory("Sa1Memory", 0x0040, 4)) & 0xFFFFFF,
        "game_p1": m.read_memory("snesMemory", 0x401C4E, 1)[0],
        "input_real_cache": le16(
            m.read_memory("snesWorkRam", 0x1F12, 2)
        ),
        "input_mailbox": le16(m.read_memory("snesMemory", 0x410000, 2)),
        "player": {
            "a6": player_a6,
            "health": local_word(-0x4E),
            "previous_input": local_byte(-0x43),
            "input": local_byte(-0x44),
            "action_state": local_byte(-0x23),
            "animation": local_word(-0x1A),
            "animation_step": local_word(-0x18),
            "animation_delay": local_word(-0x16),
            "animation_substep": local_word(-0x14),
            "animation_pointer": int.from_bytes(
                local[0x60 - 0x12 : 0x60 - 0x0E], "big"
            ),
            "x": local_word(-0x1E),
            "y": local_word(-0x22),
            "flags": local_byte(-0x24),
            "locals_sha256": digest(local),
        },
        "renderer": {
            "manifest_length": manifest_length,
            "manifest_sha256": digest(manifest),
            "oam_sha256": digest(oam),
            "render_complete_count": le16(
                m.read_memory("snesWorkRam", 0x89A2, 2)
            ),
            "last_obj_count": le16(
                m.read_memory("snesWorkRam", 0x89B2, 2)
            ),
        },
    }


def prepare_checkpoint(args: argparse.Namespace) -> dict[str, Any]:
    prepared_path = args.output / "prepared.mss"
    with McpSession(
        rom=args.rom.resolve(),
        mesen=args.nexen.resolve(),
        cwd=ROOT,
        port=args.port,
        boot_wait=6.0,
        socket_timeout=180.0,
        stderr_log=args.output / "prepare.stderr.log",
    ) as m:
        m.pause()
        m.load_state(args.state.resolve())
        m.pause()
        m.tool("set_input", {"port": 0, "buttons": 0, "hold": True})
        synchronized, observed_a6 = synchronize_player(
            m, args.sync_max_frames
        )
        if read_player_a6(m) != EXPECTED_PLAYER_A6:
            raise RuntimeError(
                "preparation did not reach the player task: "
                f"{[hex(value) for value in observed_a6[-32:]]}"
            )
        if args.prelude_frames:
            m.tool(
                "set_input",
                {
                    "port": 0,
                    "buttons": args.prelude_buttons,
                    "hold": True,
                },
            )
            m.run_frames(args.prelude_frames)
            m.pause()
            m.tool("set_input", {"port": 0, "buttons": 0, "hold": True})
            m.run_frames(8)
            m.pause()
            synchronized, observed_a6 = synchronize_player(m, 30)
            if read_player_a6(m) != EXPECTED_PLAYER_A6:
                raise RuntimeError(
                    "post-prelude preparation did not reach the player task: "
                    f"{[hex(value) for value in observed_a6[-32:]]}"
                )
        prepared_snapshot = snapshot(m, EXPECTED_PLAYER_A6, -1)
        save_response = m.save_state(prepared_path.resolve())
        deadline = time.monotonic() + 5.0
        while (
            (not prepared_path.is_file() or prepared_path.stat().st_size == 0)
            and time.monotonic() < deadline
        ):
            time.sleep(0.05)
        if not prepared_path.is_file() or prepared_path.stat().st_size == 0:
            raise RuntimeError(f"Nexen did not flush prepared state: {prepared_path}")
        screenshot = take_screenshot(m, args.output / "prepared.png")
    return {
        "path": str(prepared_path),
        "sha256": sha256(prepared_path),
        "save_response": save_response,
        "synchronized": synchronized,
        "observed_a6": observed_a6,
        "snapshot": prepared_snapshot,
        "screenshot": screenshot,
    }


def run_variant(
    args: argparse.Namespace,
    prepared: dict[str, Any],
    name: str,
    buttons: int,
    port: int,
) -> dict[str, Any]:
    variant_dir = args.output / name
    variant_dir.mkdir()
    with McpSession(
        rom=args.rom.resolve(),
        mesen=args.nexen.resolve(),
        cwd=ROOT,
        port=port,
        boot_wait=6.0,
        socket_timeout=180.0,
        stderr_log=variant_dir / "nexen.stderr.log",
    ) as m:
        m.pause()
        m.load_state(Path(prepared["path"]).resolve())
        m.pause()
        m.tool("set_input", {"port": 0, "buttons": 0, "hold": True})
        player_a6 = read_player_a6(m)
        if player_a6 != EXPECTED_PLAYER_A6:
            raise RuntimeError(
                f"{name}: prepared player A6 changed to {player_a6:#08x}"
            )

        records = [snapshot(m, player_a6, -1)]
        expected = prepared["snapshot"]
        for field in ("video_frame", "game_tick", "pc68k"):
            if records[0][field] != expected[field]:
                raise RuntimeError(
                    f"{name}: prepared {field} changed: "
                    f"{records[0][field]} != {expected[field]}"
                )
        screenshots: dict[int, dict[str, Any]] = {
            -1: take_screenshot(m, variant_dir / "frame-before.png")
        }
        m.tool("set_input", {"port": 0, "buttons": buttons, "hold": True})
        for relative_frame in range(args.observe_frames + 1):
            if relative_frame == args.tap_frames:
                m.tool("set_input", {"port": 0, "buttons": 0, "hold": True})
            m.run_frames(1)
            m.pause()
            records.append(snapshot(m, player_a6, relative_frame))
            if relative_frame in CAPTURE_FRAMES:
                screenshots[relative_frame] = take_screenshot(
                    m, variant_dir / f"frame-{relative_frame:02d}.png"
                )

        return {
            "buttons": buttons,
            "tap_frames": args.tap_frames,
            "player_a6": player_a6,
            "records": records,
            "screenshots": {
                str(frame): shot for frame, shot in sorted(screenshots.items())
            },
        }


def pixel_difference(left_path: Path, right_path: Path) -> dict[str, Any]:
    left = Image.open(left_path).convert("RGB")
    right = Image.open(right_path).convert("RGB")
    difference = ImageChops.difference(left, right)
    bbox = difference.getbbox()
    changed = sum(pixel != (0, 0, 0) for pixel in difference.getdata())
    return {
        "changed_pixels": changed,
        "bounding_box": list(bbox) if bbox is not None else None,
    }


def make_contact_sheet(
    output: Path,
    variants: dict[str, dict[str, Any]],
    frames: list[int],
) -> None:
    sample = Image.open(
        Path(variants["idle"]["screenshots"][str(frames[0])]["path"])
    ).convert("RGB")
    label_height = 18
    sheet = Image.new(
        "RGB",
        (sample.width * len(frames), (sample.height + label_height) * len(VARIANTS)),
        "black",
    )
    draw = ImageDraw.Draw(sheet)
    for row, name in enumerate(VARIANTS):
        for column, frame in enumerate(frames):
            source = Image.open(
                Path(variants[name]["screenshots"][str(frame)]["path"])
            ).convert("RGB")
            x = column * sample.width
            y = row * (sample.height + label_height)
            sheet.paste(source, (x, y))
            draw.text((x + 3, y + sample.height + 2), f"{name} f{frame}", fill="white")
    sheet.save(output)


def main() -> int:
    args = parse_args()
    if args.tap_frames <= 0:
        raise SystemExit("--tap-frames must be positive")
    if args.observe_frames < args.tap_frames:
        raise SystemExit("--observe-frames must include the complete tap")
    for path in (args.rom, args.state, args.nexen):
        if not path.is_file():
            raise FileNotFoundError(path)
    args.output.mkdir(parents=True, exist_ok=False)

    prepared = prepare_checkpoint(args)
    variants = {
        name: run_variant(args, prepared, name, buttons, args.port + 1 + index)
        for index, (name, buttons) in enumerate(VARIANTS.items())
    }
    common_frames = sorted(
        set(int(frame) for frame in variants["idle"]["screenshots"])
        & set(int(frame) for frame in variants["punch"]["screenshots"])
        & set(int(frame) for frame in variants["kick"]["screenshots"])
    )
    comparisons: dict[str, dict[str, Any]] = {}
    for name in ("punch", "kick"):
        comparisons[name] = {}
        for frame in common_frames:
            idle_path = Path(
                variants["idle"]["screenshots"][str(frame)]["path"]
            )
            active_path = Path(variants[name]["screenshots"][str(frame)]["path"])
            comparisons[name][str(frame)] = pixel_difference(idle_path, active_path)

    contact_sheet = args.output / "contact-sheet.png"
    make_contact_sheet(contact_sheet, variants, common_frames)
    result = {
        "scope": (
            "same-checkpoint real-controller visible-action differential; not FPS"
        ),
        "rom": str(args.rom.resolve()),
        "rom_sha256": sha256(args.rom),
        "state": str(args.state.resolve()),
        "state_sha256": sha256(args.state),
        "nexen": str(args.nexen.resolve()),
        "nexen_sha256": sha256(args.nexen),
        "tap_frames": args.tap_frames,
        "prelude_buttons": args.prelude_buttons,
        "prelude_frames": args.prelude_frames,
        "observe_frames": args.observe_frames,
        "prepared": prepared,
        "variants": variants,
        "comparisons": comparisons,
        "contact_sheet": {
            "path": str(contact_sheet),
            "sha256": sha256(contact_sheet),
        },
        "verdict": {
            "punch_changes_visible_output": any(
                comparison["changed_pixels"] > 0
                for frame, comparison in comparisons["punch"].items()
                if int(frame) >= args.tap_frames
            ),
            "kick_changes_visible_output": any(
                comparison["changed_pixels"] > 0
                for frame, comparison in comparisons["kick"].items()
                if int(frame) >= args.tap_frames
            ),
        },
    }
    target = args.output / "results.json"
    target.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"results": str(target), **result["verdict"]}, sort_keys=True))
    return 0 if all(result["verdict"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
