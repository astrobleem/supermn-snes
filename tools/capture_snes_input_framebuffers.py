#!/usr/bin/env python3
"""Capture every framebuffer while replaying real controller input from a state.

This is a same-emulator continuation diagnostic.  It loads one retained state,
records an emulator movie using only the MCP controller path, then replays that
movie one frame at a time while retaining every framebuffer and PPU snapshot.
This avoids legacy Mesen's zero-frame one-frame input command without skipping
intervening frames.  By default it never writes ROM, game RAM, renderer RAM, or
gate state.  Explicit cross-ROM migration options are recorded as interventions
and exist only to diagnose a new ROM from an old checkpoint.
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


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, "/home/chad/Mesen2/python")

import capture_mesen211_transitions as capture  # noqa: E402
from gameplay_acceptance_contract import unknown_diagnostic_gate  # noqa: E402
import mesen_mcp.session as _session  # noqa: E402

_session.validate_mesen_build = lambda *_args, **_kwargs: None
from mesen_mcp import McpSession  # noqa: E402


BUTTONS = {
    "neutral": 0,
    "select": McpSession.BTN_SELECT,
    "start": McpSession.BTN_START,
    "right": McpSession.BTN_RIGHT,
    "left": McpSession.BTN_LEFT,
    "up": McpSession.BTN_UP,
    "down": McpSession.BTN_DOWN,
    "b": McpSession.BTN_B,
    "b+right": McpSession.BTN_B | McpSession.BTN_RIGHT,
}

VIDEO_FILE_BASE = 0x298000
VIDEO_WRAM_OFFSET = 0x18000
VIDEO_WRAM_LENGTH = 0x3000
QUEUE_PROMOTER_WRAM_OFFSET = 0x0ED00
QUEUE_PROMOTER_LENGTH = 0x0300
QUEUE_CODE_MARK_OFFSET = 0x089D8


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--emulator", type=Path, required=True)
    parser.add_argument("--port", type=int, default=9270)
    parser.add_argument("--buttons", choices=sorted(BUTTONS), required=True)
    parser.add_argument("--frames", type=int, required=True)
    parser.add_argument("--checkpoint-step", type=int, default=30)
    parser.add_argument(
        "--movie",
        type=Path,
        help="reuse an already recorded CurrentState input movie",
    )
    parser.add_argument(
        "--movie-frames",
        type=int,
        help="actual emulated frames in --movie (required with --movie)",
    )
    parser.add_argument(
        "--refresh-video-mirror",
        action="store_true",
        help="inject the selected ROM's 5A22 renderer mirror after state load",
    )
    parser.add_argument(
        "--reserve-bg-slot-zero-migration",
        action="store_true",
        help=(
            "reset the legacy BG cache to the slot-zero-blank contract and force "
            "one full rebuild; requires --refresh-video-mirror"
        ),
    )
    parser.add_argument(
        "--shift-bg-slots-for-reserved-zero",
        action="store_true",
        help=(
            "preserve a legacy displayed BG by shifting its tilemap, VRAM records, "
            "and cache ownership from slots 0..190 to 1..191; requires an idle, "
            "queue-free checkpoint and --refresh-video-mirror"
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


def advance_one(m: McpSession) -> dict[str, Any]:
    before = int(m.get_state().get("frameCount", 0))
    responses: list[dict[str, Any]] = []
    for _attempt in range(8):
        response = m.run_frames(1)
        m.pause()
        after = int(m.get_state().get("frameCount", 0))
        responses.append(response)
        if after == before + 1:
            return {"before": before, "after": after, "responses": responses}
        if after != before:
            raise RuntimeError(
                f"one-frame movie playback advanced {after - before} frames: "
                f"{responses}"
            )
    raise RuntimeError(f"one-frame movie playback made no progress: {responses}")


def write_checked(
    m: McpSession, offset: int, data: bytes, label: str
) -> dict[str, Any]:
    m.write_memory("snesWorkRam", offset, data.hex())
    observed = bytes(m.read_memory("snesWorkRam", offset, len(data)))
    if observed != data:
        raise RuntimeError(f"{label} intervention did not verify")
    return {
        "region": f"snesWorkRam ${offset:05X}-${offset + len(data) - 1:05X}",
        "length": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "reason": label,
    }


def shift_tilemap_slots(data: bytes) -> bytes:
    if len(data) != 0x1000:
        raise ValueError("BG tilemap must be 4 KiB")
    shifted = bytearray(data)
    for offset in range(0, len(data), 2):
        word = int.from_bytes(data[offset:offset + 2], "little")
        if word == 0:
            continue
        tile = word & 0x03FF
        if tile > 0x02FB:
            raise RuntimeError(f"BG tile {tile} cannot shift by four")
        shifted[offset:offset + 2] = (
            (word & 0xFC00) | (tile + 4)
        ).to_bytes(2, "little")
    return bytes(shifted)


def shift_legacy_bg_cache(m: McpSession) -> list[dict[str, Any]]:
    def read(offset: int, length: int) -> bytes:
        return bytes(m.read_memory("snesWorkRam", offset, length))

    busy = int.from_bytes(read(0x0899C, 2), "little")
    queue_states = [
        int.from_bytes(read(offset, 2), "little")
        for offset in (0x089D2, 0x089D6)
    ]
    if busy or any(queue_states):
        raise RuntimeError(
            "slot-shift migration requires renderer idle and both queues empty: "
            f"busy={busy}, queues={queue_states}"
        )

    high_water = int.from_bytes(read(0x000DC, 2), "little")
    free_count = int.from_bytes(read(0x089C2, 2), "little")
    if not 1 <= high_water <= 0x00BF or free_count > 0x00C0:
        raise RuntimeError(
            f"legacy BG allocator cannot shift: high_water={high_water}, "
            f"free_count={free_count}"
        )

    codes = read(0x0A000, 0x0400)
    old_slots = read(0x0A400, 0x0400)
    new_slots = bytearray(old_slots)
    reverse = bytearray(0x0180)
    live: list[tuple[int, int]] = []
    for offset in range(0, 0x0400, 2):
        code = int.from_bytes(codes[offset:offset + 2], "little")
        mapped = int.from_bytes(old_slots[offset:offset + 2], "little")
        if code == 0:
            new_slots[offset:offset + 2] = b"\x00\x00"
            continue
        if code == 0xFFFF:
            raise RuntimeError("legacy BG hash contains a tombstone")
        if mapped >= 0x00BF:
            raise RuntimeError(f"live BG slot {mapped} cannot shift")
        shifted = mapped + 1
        new_slots[offset:offset + 2] = shifted.to_bytes(2, "little")
        reverse[shifted * 2:shifted * 2 + 2] = code.to_bytes(2, "little")
        live.append((code, shifted))
    if len({slot for _code, slot in live}) != len(live):
        raise RuntimeError("legacy BG hash maps multiple codes to one slot")

    old_free = bytearray(read(0x07C00, 0x00C0))
    for index in range(free_count):
        if old_free[index] >= 0x00BF:
            raise RuntimeError(f"free BG slot {old_free[index]} cannot shift")
        old_free[index] += 1

    staged = shift_tilemap_slots(read(0x09000, 0x1000))
    displayed = bytes(m.read_memory("snesVideoRam", 0x0000, 0x1000))
    displayed_shifted = shift_tilemap_slots(displayed)
    graphics = bytes(m.read_memory("snesVideoRam", 0x2000, 0x6000))
    graphics_shifted = bytes(0x80) + graphics[:-0x80]

    writes = [
        write_checked(m, 0x0A400, bytes(new_slots), "shift live BG hash slots by one"),
        write_checked(m, 0x0D000, bytes(reverse), "rebuild shifted BG reverse ownership"),
        write_checked(m, 0x07C00, bytes(old_free), "shift BG free-list slots by one"),
        write_checked(m, 0x09000, staged, "shift staged BG tilemap by four tiles"),
        write_checked(
            m,
            0x000DC,
            (high_water + 1).to_bytes(2, "little"),
            "advance BG high-water past the reserved blank slot",
        ),
        write_checked(
            m,
            0x089D0,
            (0xB7C5).to_bytes(2, "little"),
            "install reserved-blank reverse-map marker",
        ),
    ]
    m.write_memory("snesVideoRam", 0x0000, displayed_shifted.hex())
    if bytes(m.read_memory("snesVideoRam", 0x0000, 0x1000)) != displayed_shifted:
        raise RuntimeError("shifted displayed BG tilemap did not verify")
    writes.append(
        {
            "region": "snesVideoRam $0000-$0FFF",
            "length": 0x1000,
            "sha256": hashlib.sha256(displayed_shifted).hexdigest(),
            "reason": "shift displayed BG tilemap by four tiles",
        }
    )
    m.write_memory("snesVideoRam", 0x2000, graphics_shifted.hex())
    if bytes(m.read_memory("snesVideoRam", 0x2000, 0x6000)) != graphics_shifted:
        raise RuntimeError("shifted BG graphics records did not verify")
    writes.append(
        {
            "region": "snesVideoRam $2000-$7FFF",
            "length": 0x6000,
            "sha256": hashlib.sha256(graphics_shifted).hexdigest(),
            "reason": "shift BG graphics records and clear physical slot zero",
        }
    )
    return writes


def apply_checkpoint_migration(
    m: McpSession,
    rom_bytes: bytes,
    reserve_slot_zero: bool,
    shift_slot_zero: bool,
) -> list[dict[str, Any]]:
    interventions: list[dict[str, Any]] = []
    if reserve_slot_zero:
        busy = int.from_bytes(
            m.read_memory("snesWorkRam", 0x0899C, 2), "little"
        )
        queue_states = [
            int.from_bytes(m.read_memory("snesWorkRam", offset, 2), "little")
            for offset in (0x089D2, 0x089D6)
        ]
        generations = [
            int.from_bytes(m.read_memory("snesWorkRam", offset, 2), "little")
            for offset in (0x0899A, 0x089A0, 0x089A4)
        ]
        if busy or any(queue_states) or len(set(generations)) != 1:
            raise RuntimeError(
                "full BG checkpoint migration requires a drained renderer: "
                f"busy={busy}, queues={queue_states}, generations={generations}. "
                "Continue the checkpoint without migration to an idle saved "
                "state, then retry."
            )
    mirror = rom_bytes[VIDEO_FILE_BASE:VIDEO_FILE_BASE + VIDEO_WRAM_LENGTH]
    if len(mirror) != VIDEO_WRAM_LENGTH:
        raise RuntimeError("selected ROM does not contain the video mirror span")
    for offset in range(0, VIDEO_WRAM_LENGTH, 0x1000):
        chunk = mirror[offset:offset + 0x1000]
        interventions.append(
            write_checked(
                m,
                VIDEO_WRAM_OFFSET + offset,
                chunk,
                "cross-ROM checkpoint video-mirror refresh",
            )
        )
    interventions.append(
        write_checked(
            m,
            QUEUE_CODE_MARK_OFFSET,
            bytes(2),
            "force the selected ROM's lazy queue-promoter installation",
        )
    )
    interventions.append(
        write_checked(
            m,
            QUEUE_PROMOTER_WRAM_OFFSET,
            bytes(QUEUE_PROMOTER_LENGTH),
            "remove the checkpoint's superseded queue-promoter code",
        )
    )
    if shift_slot_zero:
        interventions.extend(shift_legacy_bg_cache(m))
        return interventions
    if not reserve_slot_zero:
        return interventions

    # A cross-ROM checkpoint may originate from an in-flight capture; the
    # guard above requires a drained state before this migration runs. Merely
    # invalidating the 5A22 cache and setting its local manifest to $FFFF is
    # insufficient: snapshot_acquire_paced waits for a new private generation,
    # and the next organic producer snapshot can legitimately publish a zero
    # manifest because the SA-1 already acknowledged this live X1 image. That
    # used to replace the forced manifest before the worker claimed it.
    #
    # Seed the consumer cache from the authoritative, paused live X1 planes and
    # publish the seeded cache as one new private renderer generation. Clearing
    # old queue markers is required because their sparse payloads are relative
    # to the superseded ROM lineage.
    live_bg = bytes(m.read_memory("snesMemory", 0x414800, 0x0800))
    live_palette = bytes(m.read_memory("snesMemory", 0x412000, 0x0400))
    interventions.append(
        write_checked(
            m,
            0x02000,
            live_bg,
            "seed renderer BG code/color cache from paused live X1 planes",
        )
    )
    interventions.append(
        write_checked(
            m,
            0x02800,
            live_palette,
            "seed renderer palette cache from paused live X1 palette",
        )
    )
    for offset, label in (
        (0x089D2, "discard primary queue from superseded ROM lineage"),
        (0x089D6, "discard secondary queue from superseded ROM lineage"),
    ):
        interventions.append(write_checked(m, offset, bytes(2), label))
    for offset, length, label in (
        (0x0A000, 0x0800, "clear legacy BG code/slot hash"),
        (0x0D000, 0x0180, "clear legacy BG reverse ownership"),
        (0x07C00, 0x00C0, "clear legacy BG free list"),
    ):
        interventions.append(write_checked(m, offset, bytes(length), label))
    interventions.append(
        write_checked(
            m,
            0x089F0,
            bytes([0xFF]) * 16,
            (
                "invalidate the superseded checkpoint's applied BG column map "
                "so the selected ROM rebuilds its 1 KiB offset lookup"
            ),
        )
    )
    for offset, value, label in (
        (0x089C2, 0x0000, "reset BG free-list count"),
        (0x000DC, 0x0001, "start BG artwork allocation at physical slot one"),
        (0x089D0, 0xB7C5, "install reserved-blank reverse-map marker"),
        (0x089C4, 0x0000, "clear legacy prepared-list length"),
        (0x08982, 0x0000, "invalidate legacy raw BG cache marker"),
        (0x08990, 0x0001, "force a BG renderer event"),
        (0x089BC, 0xFFFF, "force one complete BG rebuild"),
        (0x089BE, 0x0001, "force the seeded live palette to the renderer"),
    ):
        interventions.append(
            write_checked(m, offset, value.to_bytes(2, "little"), label)
        )
    generation = int.from_bytes(
        m.read_memory("snesWorkRam", 0x089A0, 2), "little"
    )
    forced_generation = (generation + 2) & 0xFFFE
    if forced_generation == 0:
        forced_generation = 2
    interventions.append(
        write_checked(
            m,
            0x0899A,
            forced_generation.to_bytes(2, "little"),
            "publish the seeded cache as a complete private generation",
        )
    )
    frame_ack = int.from_bytes(
        m.read_memory("snesMemory", 0x003302, 2), "little"
    )
    forced_request = (frame_ack + 1) & 0xFFFF
    if forced_request == 0:
        forced_request = 1
    interventions.append(
        write_checked(
            m,
            0x01F1E,
            forced_request.to_bytes(2, "little"),
            "publish the forced local BG rebuild to the idle render worker",
        )
    )
    return interventions


def main() -> int:
    args = parse_args()
    if args.frames <= 0 or args.checkpoint_step <= 0:
        raise SystemExit("frame counts must be positive")
    if (args.movie is None) != (args.movie_frames is None):
        raise SystemExit("--movie and --movie-frames must be supplied together")
    if args.movie_frames is not None and args.movie_frames <= 0:
        raise SystemExit("--movie-frames must be positive")
    if args.reserve_bg_slot_zero_migration and not args.refresh_video_mirror:
        raise SystemExit(
            "--reserve-bg-slot-zero-migration requires --refresh-video-mirror"
        )
    if args.shift_bg_slots_for_reserved_zero and not args.refresh_video_mirror:
        raise SystemExit(
            "--shift-bg-slots-for-reserved-zero requires --refresh-video-mirror"
        )
    if (
        args.reserve_bg_slot_zero_migration
        and args.shift_bg_slots_for_reserved_zero
    ):
        raise SystemExit("select only one BG slot-zero migration strategy")
    if args.movie is not None and (
        args.refresh_video_mirror
        or args.reserve_bg_slot_zero_migration
        or args.shift_bg_slots_for_reserved_zero
    ):
        raise SystemExit(
            "cross-ROM migration must be captured in a newly recorded CurrentState movie"
        )
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
    configure_dotnet(args.emulator)
    button_mask = BUTTONS[args.buttons]
    rows: list[dict[str, Any]] = []
    interventions: list[dict[str, Any]] = []
    provenance = {
        "scope": (
            "same-emulator retained-state controller movie and frame-exact "
            "framebuffer replay; explicitly labeled cross-ROM interventions "
            "when requested"
        ),
        "rom": str(rom),
        "rom_sha256": sha256(rom),
        "state": str(args.state.resolve()),
        "state_sha256": sha256(args.state),
        "emulator": str(args.emulator.resolve()),
        "emulator_sha256": sha256(args.emulator),
        "buttons": args.buttons,
        "button_mask": button_mask,
        "frames": args.frames,
        "checkpoint_step": args.checkpoint_step,
        "runtime_memory_writes": interventions,
    }

    if args.movie is not None:
        movie_path = args.movie.resolve()
        if not movie_path.is_file():
            raise FileNotFoundError(f"movie not found: {movie_path}")
        recorded_frames = int(args.movie_frames)
        provenance["movie"] = {
            "path": str(movie_path),
            "sha256": sha256(movie_path),
            "recorded_frames": recorded_frames,
            "reused": True,
        }
    else:
        movie_path = output / "input.mmo"
        with McpSession(
            rom=rom,
            mesen=args.emulator.resolve(),
            cwd=ROOT,
            port=args.port,
            boot_wait=6.0,
            socket_timeout=300.0,
            stderr_log=output / "record-emulator.stderr.log",
        ) as m:
            m.pause()
            m.load_state(args.state.resolve())
            m.pause()
            if args.refresh_video_mirror:
                interventions.extend(
                    apply_checkpoint_migration(
                        m,
                        rom.read_bytes(),
                        args.reserve_bg_slot_zero_migration,
                        args.shift_bg_slots_for_reserved_zero,
                    )
                )
            record_start_frame = int(m.get_state().get("frameCount", 0))
            initial_shot = capture.take_screenshot(
                m, output / "record-initial.png"
            )
            record_response = m.record_movie(
                movie_path,
                author="supermn-snes framebuffer gate",
                description=(
                    f"{args.buttons} controller continuation from authenticated state"
                ),
                from_="CurrentState",
            )
            input_response = m.set_input(button_mask, args.frames)
            m.pause()
            record_end_frame = int(m.get_state().get("frameCount", 0))
            stop_response = m.stop_movie()
        capture.wait_for_file(movie_path)
        recorded_frames = record_end_frame - record_start_frame
        if recorded_frames <= 0:
            raise RuntimeError("controller movie made no emulated-frame progress")
        provenance["movie"] = {
            "path": str(movie_path),
            "sha256": sha256(movie_path),
            "record_start_frame": record_start_frame,
            "record_end_frame": record_end_frame,
            "recorded_frames": recorded_frames,
            "requested_frames": args.frames,
            "reused": False,
            "initial_screenshot": initial_shot,
            "record_response": record_response,
            "input_response": input_response,
            "stop_response": stop_response,
        }

    with McpSession(
        rom=rom,
        mesen=args.emulator.resolve(),
        cwd=ROOT,
        port=args.port,
        boot_wait=6.0,
        socket_timeout=300.0,
        stderr_log=output / "playback-emulator.stderr.log",
    ) as m:
        m.pause()
        play_response = m.play_movie(movie_path)
        m.pause()
        start_frame = int(m.get_state().get("frameCount", 0))
        initial = capture.snapshot(m)
        initial["relative_frame"] = 0
        try:
            initial["screenshot"] = capture.take_screenshot(
                m, output / "frame-000000.png"
            )
        except Exception as error:
            # Legacy Mesen can decline a screenshot immediately after restoring
            # a CurrentState movie, before the first replayed vblank.  The
            # recorder captured that exact pre-movie framebuffer already.
            fallback = (
                output / "record-initial.png"
                if (output / "record-initial.png").is_file()
                else movie_path.parent / "record-initial.png"
            )
            if not fallback.is_file():
                raise
            target = output / "frame-000000.png"
            shutil.copy2(fallback, target)
            initial["screenshot"] = {
                "path": str(target),
                "sha256": sha256(target),
                "bytes": target.stat().st_size,
                "source": str(fallback),
                "reason": "exact recorder framebuffer fallback",
                "playback_capture_error": repr(error),
            }
        initial["checkpoint"] = capture.save_checkpoint(
            m, output / "frame-000000.mss"
        )
        rows.append(initial)

        for relative in range(1, recorded_frames + 1):
            advance = advance_one(m)
            row = capture.snapshot(m)
            row["relative_frame"] = relative
            row["input_advance"] = advance
            row["screenshot"] = capture.take_screenshot(
                m, output / f"frame-{relative:06d}.png"
            )
            if relative % args.checkpoint_step == 0:
                row["checkpoint"] = capture.save_checkpoint(
                    m, output / f"frame-{relative:06d}.mss"
                )
            rows.append(row)
        movie_state_before_stop = m.movie_state()
        playback_stop_response = m.stop_movie()

    coverage = {
        "game_tick_start": rows[0]["tick"],
        "game_tick_end": rows[-1]["tick"],
        "video_frame_start": start_frame,
        "video_frame_end": rows[-1]["frame"],
        "captured_video_frames": len(rows),
        "complete": len(rows) == recorded_frames + 1,
    }
    acceptance_gate = unknown_diagnostic_gate(
        "framebuffer_capture",
        "Capture success is evidence availability, not visual correctness.",
    )
    acceptance_gate["rom_sha256"] = provenance["rom_sha256"]
    acceptance_gate["coverage"] = coverage
    report = {
        "schema": 1,
        "provenance": provenance,
        "start_video_frame": start_frame,
        "end_video_frame": rows[-1]["frame"],
        "play_response": play_response,
        "movie_state_before_stop": movie_state_before_stop,
        "playback_stop_response": playback_stop_response,
        "coverage": coverage,
        "captures": rows,
        "acceptance_gate": acceptance_gate,
    }
    report_path = output / "results.json"
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "result": "captured",
                "frames": len(rows),
                "start_video_frame": start_frame,
                "end_video_frame": rows[-1]["frame"],
                "report": str(report_path),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
