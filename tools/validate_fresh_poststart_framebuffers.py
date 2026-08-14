#!/usr/bin/env python3
"""Fresh-power-on post-Start framebuffer regression gate.

The harness first records an organic coin/Start movie from
``StartWithoutSaveData``.  It then replays that movie from power-on, loads no
save state, retains every actual post-Start video frame, and verifies that each
stored image advances Mesen's frame counter by exactly one.  Machine checks
catch blank/repeated playfields and partial persistent-BG tile DMAs.  A contact
sheet makes human screenshot review mandatory in the handoff contract.

This is a bounded rendering regression gate, not exact-MAME pixels, temporal
conservation against MAME, aggregate gameplay acceptance, FPS, or hardware
evidence.  Its acceptance gate therefore remains UNKNOWN even when the named
regression checks are clear.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, "/home/chad/Mesen2/python")

import capture_mesen211_transitions as capture  # noqa: E402
from capture_snes_input_framebuffers import advance_one  # noqa: E402
from compare_snes_framebuffers import PLAYFIELD_BOX, repetition_metrics  # noqa: E402
from gameplay_acceptance_contract import unknown_diagnostic_gate  # noqa: E402
import mesen_mcp.session as _session  # noqa: E402

_session.validate_mesen_build = lambda *_args, **_kwargs: None
from mesen_mcp import McpSession  # noqa: E402


DEFAULT_EMULATOR = ROOT / "tools" / "mesen211_mcp_controller.sh"
BG_GRAPHICS_FILE_BASE = 0x090000
VERTICAL_BLACK_COLUMN_RATIO = 0.98
MAX_VERTICAL_BLACK_RUN = 47


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--emulator", type=Path, default=DEFAULT_EMULATOR)
    parser.add_argument("--record-port", type=int, default=43810)
    parser.add_argument("--playback-port", type=int, default=43811)
    parser.add_argument(
        "--boot-milestone-frames",
        default="1,1250,1500",
        help=(
            "comma-separated fresh-power video frames retained before the title "
            "checkpoint (default: 1,1250,1500)"
        ),
    )
    parser.add_argument("--title-frame", type=int, default=5500)
    parser.add_argument("--coin-frames", type=int, default=4)
    parser.add_argument("--credit-wait-frames", type=int, default=155)
    parser.add_argument("--credit-wait-ceiling", type=int, default=300)
    parser.add_argument("--start-frames", type=int, default=61)
    parser.add_argument("--poststart-frames", type=int, default=600)
    parser.add_argument("--checkpoint-step", type=int, default=50)
    parser.add_argument("--visual-grace-frames", type=int, default=100)
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def configure_runtime() -> None:
    dotnet8 = "/home/chad/.dotnet8"
    dotnet10 = "/home/chad/.dotnet10"
    os.environ["DOTNET_ROOT"] = dotnet8
    current = [
        item
        for item in os.environ.get("PATH", "").split(":")
        if item and item not in (dotnet8, dotnet10)
    ]
    os.environ["PATH"] = ":".join([dotnet8, dotnet10, *current])


def parse_milestone_frames(raw: str, title_frame: int) -> list[int]:
    try:
        values = [int(item.strip()) for item in raw.split(",") if item.strip()]
    except ValueError as exc:
        raise ValueError("--boot-milestone-frames must contain integers") from exc
    if not values or values != sorted(set(values)):
        raise ValueError("boot milestones must be nonempty, unique, and increasing")
    if values[0] < 0 or values[-1] >= title_frame:
        raise ValueError("boot milestones must be >= 0 and before --title-frame")
    return values


def credits(m: McpSession) -> int:
    return int.from_bytes(m.read_memory("snesMemory", 0x401C62, 2), "big")


def frame_count(m: McpSession) -> int:
    return int(m.get_state().get("frameCount", 0))


def bg_graphics_check(m: McpSession, rom_bytes: bytes) -> dict[str, Any]:
    reverse_data = bytes(m.read_memory("snesWorkRam", 0xD000, 0x0180))
    reverse = [
        int.from_bytes(reverse_data[offset:offset + 2], "little")
        for offset in range(0, len(reverse_data), 2)
    ]
    vram = bytes(m.read_memory("snesVideoRam", 0x2000, 0x6000))
    mismatches: list[dict[str, Any]] = []
    owners = 0
    for slot, code in enumerate(reverse):
        if slot == 0 or code == 0:
            continue
        owners += 1
        start = BG_GRAPHICS_FILE_BASE + code * 0x80
        expected = rom_bytes[start:start + 0x80]
        observed = vram[slot * 0x80:(slot + 1) * 0x80]
        if len(expected) != 0x80 or observed != expected:
            offsets = [
                index
                for index, (left, right) in enumerate(zip(expected, observed))
                if left != right
            ]
            mismatches.append(
                {
                    "slot": slot,
                    "code": code,
                    "changed_byte_count": len(offsets),
                    "first_changed_offsets": offsets[:64],
                    "expected_sha256": hashlib.sha256(expected).hexdigest(),
                    "observed_sha256": hashlib.sha256(observed).hexdigest(),
                }
            )
    return {
        "owned_slots": owners,
        "matching_slots": owners - len(mismatches),
        "mismatch_count": len(mismatches),
        "mismatches": mismatches[:64],
    }


def image_metrics(path: Path) -> dict[str, Any]:
    image = Image.open(path).convert("RGB")
    playfield = image.crop(PLAYFIELD_BOX)
    pixels = list(playfield.getdata())
    black = sum(pixel == (0, 0, 0) for pixel in pixels)
    black_columns = []
    for x in range(playfield.width):
        column_black = sum(
            playfield.getpixel((x, y)) == (0, 0, 0)
            for y in range(playfield.height)
        )
        black_columns.append(
            column_black / playfield.height >= VERTICAL_BLACK_COLUMN_RATIO
        )
    max_vertical_black_run = 0
    current_vertical_black_run = 0
    for is_black in black_columns:
        if is_black:
            current_vertical_black_run += 1
            max_vertical_black_run = max(
                max_vertical_black_run, current_vertical_black_run
            )
        else:
            current_vertical_black_run = 0
    repetition = repetition_metrics(image)
    return {
        "playfield_black_ratio": black / len(pixels),
        "playfield_unique_colors": len(set(pixels)),
        "max_vertical_black_run": max_vertical_black_run,
        "vertical_black_column_ratio": VERTICAL_BLACK_COLUMN_RATIO,
        "dominant_tile_ratio": repetition["dominant_tile_ratio"],
        "unique_tiles": repetition["unique_tiles"],
    }


def make_contact_sheet(paths: list[Path], target: Path) -> dict[str, Any]:
    if not paths:
        raise ValueError("contact sheet requires at least one screenshot")
    columns = 4
    width, height = 256, 224
    rows = (len(paths) + columns - 1) // columns
    sheet = Image.new("RGB", (columns * width, rows * height), (32, 32, 32))
    for index, path in enumerate(paths):
        image = Image.open(path).convert("RGB")
        if image.size != (width, height):
            image = image.crop((0, 0, width, height))
        sheet.paste(image, ((index % columns) * width, (index // columns) * height))
    sheet.save(target)
    return {
        "path": str(target),
        "sha256": sha256(target),
        "frames": [path.name for path in paths],
        "size": list(sheet.size),
    }


def advance_to(m: McpSession, target: int) -> None:
    current = frame_count(m)
    if current > target:
        raise RuntimeError(f"playback already passed frame {target}: {current}")
    while current < target:
        count = min(250, target - current)
        m.run_frames(count)
        m.pause()
        observed = frame_count(m)
        if observed <= current or observed > target:
            raise RuntimeError(
                f"chunk playback did not land monotonically: {current}->{observed}, "
                f"target={target}"
            )
        current = observed


def evaluate_rows(
    rows: list[dict[str, Any]], visual_grace_frames: int
) -> list[dict[str, Any]]:
    """Apply the bounded framebuffer gate to already-retained consecutive rows."""
    if not rows:
        raise ValueError("fresh post-Start gate requires retained capture rows")
    failures: list[dict[str, Any]] = []
    previous_frame = rows[0]["frame"] - 1
    for row in rows:
        if row["frame"] != previous_frame + 1:
            failures.append(
                {
                    "relative_frame": row["relative_frame"],
                    "kind": "nonconsecutive_video_frame",
                    "observed": row["frame"],
                    "previous": previous_frame,
                }
            )
        previous_frame = row["frame"]
        if row["halt"] != 0:
            failures.append(
                {"relative_frame": row["relative_frame"], "kind": "interpreter_halt"}
            )
        if row["relative_frame"] >= visual_grace_frames:
            metrics = row["image_metrics"]
            if metrics["playfield_black_ratio"] >= 0.90:
                failures.append(
                    {
                        "relative_frame": row["relative_frame"],
                        "kind": "blank_playfield",
                        "value": metrics["playfield_black_ratio"],
                    }
                )
            if metrics["dominant_tile_ratio"] >= 0.50:
                failures.append(
                    {
                        "relative_frame": row["relative_frame"],
                        "kind": "repeated_tile_collapse",
                        "value": metrics["dominant_tile_ratio"],
                    }
                )
            if metrics["max_vertical_black_run"] > MAX_VERTICAL_BLACK_RUN:
                failures.append(
                    {
                        "relative_frame": row["relative_frame"],
                        "kind": "vertical_black_band",
                        "value": metrics["max_vertical_black_run"],
                        "maximum": MAX_VERTICAL_BLACK_RUN,
                    }
                )
            if row["forced_blank"] or not (row["main_screen_layers"] & 0x01):
                failures.append(
                    {
                        "relative_frame": row["relative_frame"],
                        "kind": "bg1_not_visible",
                        "forced_blank": row["forced_blank"],
                        "main_screen_layers": row["main_screen_layers"],
                    }
                )
        graphics = row.get("bg_graphics")
        if graphics:
            if (
                row["relative_frame"] >= visual_grace_frames
                and graphics["owned_slots"] == 0
            ):
                failures.append(
                    {
                        "relative_frame": row["relative_frame"],
                        "kind": "missing_bg_cache_ownership",
                    }
                )
            if graphics["mismatch_count"]:
                failures.append(
                    {
                        "relative_frame": row["relative_frame"],
                        "kind": "partial_or_wrong_bg_tile_dma",
                        "mismatches": graphics["mismatches"],
                    }
                )
    return failures


def main() -> int:
    args = parse_args()
    for value in (
        args.title_frame,
        args.coin_frames,
        args.credit_wait_frames,
        args.credit_wait_ceiling,
        args.start_frames,
        args.poststart_frames,
        args.checkpoint_step,
    ):
        if value <= 0:
            raise SystemExit("frame counts must be positive")
    if args.visual_grace_frames < 0 or args.visual_grace_frames > args.poststart_frames:
        raise SystemExit("invalid --visual-grace-frames")
    try:
        boot_milestone_frames = parse_milestone_frames(
            args.boot_milestone_frames, args.title_frame
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    for path in (args.rom, args.emulator):
        if not path.is_file():
            raise FileNotFoundError(path)
    rom = args.rom.resolve()
    if rom.stat().st_size != 0x400000:
        raise SystemExit("expected a 4 MiB production ROM")
    rom_bytes = rom.read_bytes()
    if int.from_bytes(rom_bytes[0x77E0:0x77E2], "little") != 0:
        raise SystemExit("refusing non-production ROM: TESTFLAG is set")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    configure_runtime()
    movie = output / "fresh-poststart.mmo"

    with McpSession(
        rom=rom,
        mesen=args.emulator.resolve(),
        cwd=ROOT,
        port=args.record_port,
        boot_wait=6.0,
        socket_timeout=300.0,
        stderr_log=output / "record-emulator.stderr.log",
    ) as m:
        m.pause()
        record_response = m.record_movie(
            movie,
            author="supermn-snes fresh post-Start framebuffer gate",
            description="power-on, coin, Start, neutral post-Start coverage",
            from_="StartWithoutSaveData",
        )
        advance_to(m, args.title_frame)
        title_frame = frame_count(m)
        title_credits = credits(m)
        coin_response = m.set_input(McpSession.BTN_SELECT, args.coin_frames)
        m.pause()
        release_coin_response = m.set_input(0, 1)
        m.pause()
        coin_end_frame = frame_count(m)
        m.run_frames(args.credit_wait_frames)
        m.pause()
        waited = args.credit_wait_frames
        while credits(m) == 0 and waited < args.credit_wait_ceiling:
            m.run_frames(1)
            m.pause()
            waited += 1
        credit_frame = frame_count(m)
        credit_count = credits(m)
        if credit_count <= 0:
            raise RuntimeError("organic coin did not produce a credit")
        start_response = m.set_input(McpSession.BTN_START, args.start_frames)
        m.pause()
        release_start_response = m.set_input(0, 1)
        m.pause()
        poststart_frame = frame_count(m)
        poststart_credits = credits(m)
        if poststart_credits >= credit_count:
            raise RuntimeError(
                f"organic Start did not consume credit: {credit_count}->{poststart_credits}"
            )
        m.run_frames(args.poststart_frames)
        m.pause()
        record_end_frame = frame_count(m)
        stop_record_response = m.stop_movie()
    capture.wait_for_file(movie)
    if record_end_frame - poststart_frame != args.poststart_frames:
        raise RuntimeError("recording did not retain the requested post-Start span")

    phases = {
        "title": title_frame,
        "coin_end": coin_end_frame,
        "credit_ready": credit_frame,
        "poststart": poststart_frame,
        "end": record_end_frame,
    }
    if boot_milestone_frames[-1] >= title_frame:
        raise RuntimeError(
            "configured boot milestone is not before the movie's actual title "
            f"boundary: milestone={boot_milestone_frames[-1]}, title={title_frame}"
        )
    milestone_rows: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    with McpSession(
        rom=rom,
        mesen=args.emulator.resolve(),
        cwd=ROOT,
        port=args.playback_port,
        boot_wait=6.0,
        socket_timeout=300.0,
        stderr_log=output / "playback-emulator.stderr.log",
    ) as m:
        m.pause()
        play_response = m.play_movie(movie)
        m.pause()
        playback_start_frame = frame_count(m)
        if playback_start_frame != 0:
            raise RuntimeError(
                f"StartWithoutSaveData movie did not begin at frame zero: {playback_start_frame}"
            )
        for milestone_frame in boot_milestone_frames:
            advance_to(m, milestone_frame)
            row = capture.snapshot(m)
            row["phase"] = f"boot-{milestone_frame:06d}"
            row["screenshot"] = capture.take_screenshot(
                m, output / f"milestone-boot-{milestone_frame:06d}.png"
            )
            milestone_rows.append(row)
        for name in ("title", "coin_end", "credit_ready"):
            advance_to(m, phases[name])
            row = capture.snapshot(m)
            row["phase"] = name
            row["screenshot"] = capture.take_screenshot(
                m, output / f"milestone-{name}.png"
            )
            milestone_rows.append(row)
        advance_to(m, poststart_frame)
        for relative in range(args.poststart_frames + 1):
            observed_frame = frame_count(m)
            expected_frame = poststart_frame + relative
            if observed_frame != expected_frame:
                raise RuntimeError(
                    f"post-Start coverage gap at {relative}: "
                    f"expected {expected_frame}, got {observed_frame}"
                )
            row = capture.snapshot(m)
            row["relative_frame"] = relative
            screenshot_path = output / f"frame-{relative:06d}.png"
            row["screenshot"] = capture.take_screenshot(m, screenshot_path)
            row["image_metrics"] = image_metrics(screenshot_path)
            if relative % args.checkpoint_step == 0:
                row["checkpoint"] = capture.save_checkpoint(
                    m, output / f"frame-{relative:06d}.mss"
                )
                row["bg_graphics"] = bg_graphics_check(m, rom_bytes)
            rows.append(row)
            if relative == args.poststart_frames:
                break
            row["advance"] = advance_one(m)
        movie_state_before_stop = m.movie_state()
        stop_playback_response = m.stop_movie()

    failures = evaluate_rows(rows, args.visual_grace_frames)

    selected_paths = [
        Path(row["screenshot"]["path"])
        for row in milestone_rows
    ] + [
        Path(row["screenshot"]["path"])
        for row in rows
        if row["relative_frame"] % args.checkpoint_step == 0
    ]
    contact_sheet = make_contact_sheet(selected_paths, output / "contact-sheet.png")
    rom_sha256 = sha256(rom)
    coverage = {
        "fresh_video_frame_start": 0,
        "fresh_video_frame_end": record_end_frame,
        "poststart_relative_start": 0,
        "poststart_relative_end": args.poststart_frames,
        "poststart_video_frame_start": rows[0]["frame"],
        "poststart_video_frame_end": rows[-1]["frame"],
        "complete": len(rows) == args.poststart_frames + 1,
    }
    acceptance_gate = unknown_diagnostic_gate(
        "fresh_poststart_framebuffers",
        (
            "Machine and screenshot regression checks cannot replace exact-MAME "
            "pixels, every-frame MAME conservation, or human visual review."
        ),
    )
    acceptance_gate["rom_sha256"] = rom_sha256
    acceptance_gate["coverage"] = coverage
    report = {
        "schema": 1,
        "scope": (
            "fresh StartWithoutSaveData organic coin/Start movie replay; every "
            "actual post-Start video frame retained; bounded visual regression only"
        ),
        "rom": str(rom),
        "rom_sha256": rom_sha256,
        "emulator": str(args.emulator.resolve()),
        "emulator_sha256": sha256(args.emulator),
        "movie": str(movie),
        "movie_sha256": sha256(movie),
        "movie_start": "StartWithoutSaveData",
        "runtime_memory_writes": [],
        "obj_temporal_capture": True,
        "recording": {
            "record_response": record_response,
            "coin_response": coin_response,
            "release_coin_response": release_coin_response,
            "start_response": start_response,
            "release_start_response": release_start_response,
            "stop_response": stop_record_response,
            "title_credits": title_credits,
            "credit_count_before_start": credit_count,
            "credit_count_after_start": poststart_credits,
            "credit_wait_actual_frames": waited,
            "phases": phases,
        },
        "playback": {
            "play_response": play_response,
            "movie_state_before_stop": movie_state_before_stop,
            "stop_response": stop_playback_response,
        },
        "coverage": coverage,
        "visual_grace_frames": args.visual_grace_frames,
        "milestones": milestone_rows,
        "captures": rows,
        "contact_sheet": contact_sheet,
        "manual_review_required": True,
        "visual_regression_result": "red" if failures else "clear",
        "first_failure": failures[0] if failures else None,
        "failures": failures,
        "acceptance_gate": acceptance_gate,
    }
    target = output / "results.json"
    target.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(
        json.dumps(
            {
                "visual_regression_result": report["visual_regression_result"],
                "frames": len(rows),
                "first_failure": report["first_failure"],
                "contact_sheet": contact_sheet["path"],
                "report": str(target),
                "acceptance_status": "unknown",
            },
            sort_keys=True,
        )
    )
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
