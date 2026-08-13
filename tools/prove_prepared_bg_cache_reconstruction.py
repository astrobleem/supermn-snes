#!/usr/bin/env python3
"""Prove prepared-BG raw-cache reconstruction at a retained Mesen checkpoint.

This is an explicitly intervened diagnostic.  It advances a retained state to
an already-captured primary ``$FFFE`` queue entry, derives the canonical raw
BG code/color planes from that entry's logical prepared map, writes only the
5A22-private raw caches, and continues the same ROM.  It does not modify the
ROM and is not organic acceptance evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import struct
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, "/home/chad/Mesen2/python")

import mesen_mcp.session as _session  # noqa: E402

_session.validate_mesen_build = lambda *_args, **_kwargs: None
from mesen_mcp import McpSession  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--emulator", type=Path, required=True)
    parser.add_argument("--port", type=int, default=43770)
    parser.add_argument("--advance-frames", type=int, default=21)
    parser.add_argument("--continue-frames", type=int, default=500)
    parser.add_argument("--capture-step", type=int, default=50)
    parser.add_argument(
        "--video-mirror-bin",
        type=Path,
        help=(
            "diagnostic intervention: inject the first $3000 bytes of this "
            "assembled video image into serialized $7F:8000-$AFFF"
        ),
    )
    parser.add_argument(
        "--video-symbols",
        type=Path,
        help=(
            "with --execute-assembled-fix, Poppy symbols for the assembled "
            "video image"
        ),
    )
    parser.add_argument(
        "--execute-assembled-fix",
        action="store_true",
        help=(
            "execute the assembled reconstructor through the patched WRAM "
            "promoter instead of writing reconstructed raw planes directly"
        ),
    )
    return parser.parse_args()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def write_artifact(path: Path, data: bytes) -> dict[str, object]:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return {
        "path": str(path),
        "bytes": len(data),
        "sha256": sha256_bytes(data),
    }


def wait_for_file(path: Path, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.is_file() and path.stat().st_size:
            return
        time.sleep(0.05)
    raise TimeoutError(f"timed out waiting for {path}")


def le16(data: bytes, offset: int = 0) -> int:
    return int.from_bytes(data[offset : offset + 2], "little")


def words_be_to_le(data: bytes) -> bytes:
    if len(data) % 2:
        raise ValueError("word plane has odd length")
    words = struct.unpack(f">{len(data) // 2}H", data)
    return struct.pack(f"<{len(words)}H", *words)


def symbol_address(path: Path, name: str) -> int:
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        fields = raw.split()
        if len(fields) == 2 and fields[1] == name:
            return int(fields[0].split(":")[-1], 16)
    raise RuntimeError(f"{path}: missing symbol {name}")


def reconstruct(
    tilemap: bytes, sorted_codes: bytes, palette_map: bytes
) -> tuple[bytes, bytes]:
    if len(tilemap) != 0x1000 or len(palette_map) != 0x20:
        raise ValueError("invalid prepared payload shape")
    inverse = {
        slot: bank
        for bank, slot in enumerate(palette_map)
        if slot != 0xFF
    }
    codes = bytearray(0x0400)
    colors = bytearray(0x0400)
    for cell in range(512):
        column, row = divmod(cell, 32)
        raw_x = column * 8 + (row & 1) * 4
        offset = (
            (row & ~1) * 64
            + (raw_x & 0x3F)
            + (0x0800 if raw_x & 0x40 else 0)
        )
        word = le16(tilemap, offset)
        tile = word & 0x03FF
        if tile == 0:
            continue
        if tile & 3:
            raise RuntimeError(
                f"prepared cell {cell} has non-TL tile ${tile:03X}"
            )
        code_offset = (tile // 4 - 1) * 2
        if code_offset < 0 or code_offset + 2 > len(sorted_codes):
            raise RuntimeError(
                f"prepared cell {cell} tile ${tile:03X} exceeds code list"
            )
        code = le16(sorted_codes, code_offset) & 0x3FFF
        flips = word & 0xC000
        if flips not in (0, 0xC000):
            flips ^= 0xC000
        raw_code = code | flips
        palette_slot = (word >> 10) & 7
        if palette_slot not in inverse:
            raise RuntimeError(
                f"prepared cell {cell} uses unmapped palette slot {palette_slot}"
            )
        raw_color = inverse[palette_slot] << 11
        codes[cell * 2 : cell * 2 + 2] = raw_code.to_bytes(2, "big")
        colors[cell * 2 : cell * 2 + 2] = raw_color.to_bytes(2, "big")
    return bytes(codes), bytes(colors)


def screenshot(m: McpSession, target: Path) -> dict[str, object]:
    response = m.take_screenshot(format="path")
    source = Path(response["path"])
    shutil.copy2(source, target)
    return {
        "path": str(target),
        "sha256": sha256_file(target),
        "bytes": target.stat().st_size,
        "response": response,
    }


def main() -> int:
    args = parse_args()
    paths = [args.rom, args.state, args.emulator]
    if args.video_mirror_bin is not None:
        paths.append(args.video_mirror_bin)
    if args.video_symbols is not None:
        paths.append(args.video_symbols)
    for path in paths:
        if not path.is_file():
            raise FileNotFoundError(path)
    if args.execute_assembled_fix and (
        args.video_mirror_bin is None or args.video_symbols is None
    ):
        raise SystemExit(
            "--execute-assembled-fix requires --video-mirror-bin and --video-symbols"
        )
    args.output = args.output.resolve()
    if args.output.exists():
        raise SystemExit(f"refusing existing output: {args.output}")
    args.output.mkdir(parents=True)
    os.environ["DOTNET_ROOT"] = "/home/chad/.dotnet8"

    rows: list[dict[str, object]] = []
    intervention: dict[str, object]
    runtime_memory_writes: list[dict[str, object]] = []
    with McpSession(
        rom=args.rom.resolve(),
        mesen=args.emulator.resolve(),
        cwd=ROOT,
        port=args.port,
        boot_wait=6.0,
        socket_timeout=120.0,
        stderr_log=args.output / "emulator.stderr.log",
    ) as m:
        m.pause()
        m.load_state(args.state.resolve())
        m.pause()
        if args.video_mirror_bin is not None:
            assembled = args.video_mirror_bin.read_bytes()
            if len(assembled) < 0x3000:
                raise RuntimeError("assembled video image is shorter than $3000 bytes")
            mirror = assembled[:0x3000]
            mirror_artifact = write_artifact(
                args.output / "injected-video-mirror.bin", mirror
            )
            m.write_memory("snesWorkRam", 0x18000, mirror.hex())
            if bytes(m.read_memory("snesWorkRam", 0x18000, 0x3000)) != mirror:
                raise RuntimeError("video mirror intervention did not verify")
            runtime_memory_writes.append(
                {
                    "region": "snesWorkRam $18000-$1AFFF",
                    "length": len(mirror),
                    "sha256": mirror_artifact["sha256"],
                    "artifact": mirror_artifact["path"],
                    "reason": "assembled renderer-mirror diagnostic refresh",
                }
            )
            if args.execute_assembled_fix:
                helper_start = symbol_address(
                    args.video_symbols, "prepared_bg_cache_reconstruct"
                )
                helper_end = symbol_address(
                    args.video_symbols, "prepared_bg_cache_reconstruct_end"
                )
                promoter_start = symbol_address(
                    args.video_symbols, "render_queue_promote"
                )
                promoter_end = symbol_address(
                    args.video_symbols, "render_queue_promote_end"
                )
                helper = assembled[helper_start - 0x8000:helper_end - 0x8000]
                promoter = assembled[
                    promoter_start - 0x8000:promoter_end - 0x8000
                ]
                call = bytes.fromhex("2200c4e9")
                call_offset = promoter.find(call)
                if call_offset < 0 or helper_start != 0xC400:
                    raise RuntimeError("assembled prepared-fix call layout changed")
                helper_rom_offset = 0x290000 + helper_start
                m.write_memory("snesPrgRom", helper_rom_offset, helper.hex())
                if bytes(
                    m.read_memory("snesPrgRom", helper_rom_offset, len(helper))
                ) != helper:
                    raise RuntimeError("assembled reconstructor patch did not verify")
                m.write_memory("snesWorkRam", promoter_start, promoter.hex())
                if bytes(
                    m.read_memory("snesWorkRam", promoter_start, len(promoter))
                ) != promoter:
                    raise RuntimeError("assembled promoter patch did not verify")
                runtime_memory_writes.extend(
                    [
                        {
                            "region": (
                                f"snesPrgRom ${helper_rom_offset:06X}-"
                                f"${helper_rom_offset + len(helper) - 1:06X}"
                            ),
                            "length": len(helper),
                            "sha256": sha256_bytes(helper),
                            "reason": "execute assembled prepared-cache reconstructor",
                        },
                        {
                            "region": (
                                f"snesWorkRam ${promoter_start:04X}-"
                                f"${promoter_end - 1:04X}"
                            ),
                            "length": len(promoter),
                            "sha256": sha256_bytes(promoter),
                            "reason": "execute assembled queue promoter with reconstructor call",
                        },
                    ]
                )
                assembled_return_hook = (
                    0x7E0000 + promoter_start + call_offset + len(call)
                )
        if args.advance_frames:
            m.run_frames(args.advance_frames)
            m.pause()

        queue_state = le16(bytes(m.read_memory("snesWorkRam", 0x89D2, 2)))
        metadata = bytes(m.read_memory("snesWorkRam", 0xD180, 0x10))
        bg_kind = le16(metadata, 4)
        prepared_length = le16(metadata, 8)
        if queue_state != 1 or bg_kind != 0xFFFE or prepared_length == 0:
            raise RuntimeError(
                "expected complete primary prepared entry, got "
                f"state={queue_state} bg=${bg_kind:04X} len={prepared_length}"
            )
        tilemap = bytes(m.read_memory("snesWorkRam", 0xD8A0, 0x1000))
        sorted_codes = bytes(
            m.read_memory("snesWorkRam", 0xE8A0, prepared_length)
        )
        palette_map = bytes(m.read_memory("snesWorkRam", 0xEA20, 0x20))
        raw_codes, raw_colors = reconstruct(
            tilemap, sorted_codes, palette_map
        )
        live_codes = bytes(m.read_memory("snesMemory", 0x414800, 0x0400))
        live_colors = bytes(m.read_memory("snesMemory", 0x414C00, 0x0400))
        if raw_codes != live_codes or raw_colors != live_colors:
            raise RuntimeError("reconstructed prepared planes do not match live X1")

        before_codes = bytes(m.read_memory("snesWorkRam", 0x2000, 0x0400))
        before_colors = bytes(m.read_memory("snesWorkRam", 0x2400, 0x0400))
        prepared_artifacts = {
            "prepared_tilemap": write_artifact(
                args.output / "prepared-tilemap.bin", tilemap
            ),
            "prepared_sorted_codes": write_artifact(
                args.output / "prepared-sorted-codes.bin", sorted_codes
            ),
            "prepared_palette_map": write_artifact(
                args.output / "prepared-palette-map.bin", palette_map
            ),
            "reconstructed_raw_codes": write_artifact(
                args.output / "reconstructed-raw-codes.bin", raw_codes
            ),
            "reconstructed_raw_colors": write_artifact(
                args.output / "reconstructed-raw-colors.bin", raw_colors
            ),
            "live_x1_codes": write_artifact(
                args.output / "live-x1-codes.bin", live_codes
            ),
            "live_x1_colors": write_artifact(
                args.output / "live-x1-colors.bin", live_colors
            ),
            "stale_cache_codes": write_artifact(
                args.output / "stale-cache-codes.bin", before_codes
            ),
            "stale_cache_colors": write_artifact(
                args.output / "stale-cache-colors.bin", before_colors
            ),
        }
        if args.execute_assembled_fix:
            hook = m.add_exec_hook(assembled_return_hook, cpu_type="Snes")
            try:
                result = m.run_until(max_frames=10, hook_handle=hook)
                m.pause()
            finally:
                m.remove_hook(hook)
            after_codes = bytes(m.read_memory("snesWorkRam", 0x2000, 0x0400))
            after_colors = bytes(m.read_memory("snesWorkRam", 0x2400, 0x0400))
            assembled_outputs = {
                "actual_raw_codes": write_artifact(
                    args.output / "assembled-actual-raw-codes.bin", after_codes
                ),
                "actual_raw_colors": write_artifact(
                    args.output / "assembled-actual-raw-colors.bin", after_colors
                ),
            }
            if after_codes != raw_codes or after_colors != raw_colors:
                mismatch = {
                    "execution_result": result,
                    "return_hook": f"${assembled_return_hook:06X}",
                    "code_mismatch_offsets": [
                        index
                        for index, (expected, actual) in enumerate(
                            zip(raw_codes, after_codes)
                        )
                        if expected != actual
                    ],
                    "color_mismatch_offsets": [
                        index
                        for index, (expected, actual) in enumerate(
                            zip(raw_colors, after_colors)
                        )
                        if expected != actual
                    ],
                    "assembled_outputs": assembled_outputs,
                }
                (args.output / "assembled-mismatch.json").write_text(
                    json.dumps(mismatch, indent=2, sort_keys=True) + "\n"
                )
                raise RuntimeError(
                    "assembled reconstructor did not publish the exact prepared planes"
                )
            intervention = {
                "reason": "execute assembled prepared-entry raw-cache reconstruction",
                "frame": int(m.get_state().get("frameCount", 0)),
                "execution_result": result,
                "return_hook": f"${assembled_return_hook:06X}",
                "before_code_sha256": sha256_bytes(before_codes),
                "before_color_sha256": sha256_bytes(before_colors),
                "after_code_sha256": sha256_bytes(after_codes),
                "after_color_sha256": sha256_bytes(after_colors),
                "exact_live_match": True,
            }
        else:
            m.write_memory("snesWorkRam", 0x2000, raw_codes.hex())
            m.write_memory("snesWorkRam", 0x2400, raw_colors.hex())
            if bytes(m.read_memory("snesWorkRam", 0x2000, 0x0400)) != raw_codes:
                raise RuntimeError("raw code cache write did not verify")
            if bytes(m.read_memory("snesWorkRam", 0x2400, 0x0400)) != raw_colors:
                raise RuntimeError("raw color cache write did not verify")
            intervention = {
                "reason": "simulate prepared-entry canonical raw-cache reconstruction",
                "frame": int(m.get_state().get("frameCount", 0)),
                "before_code_sha256": sha256_bytes(before_codes),
                "before_color_sha256": sha256_bytes(before_colors),
                "after_code_sha256": sha256_bytes(raw_codes),
                "after_color_sha256": sha256_bytes(raw_colors),
                "exact_live_match": True,
            }
            runtime_memory_writes.append(
                {
                    "regions": [
                        "snesWorkRam $2000-$23FF",
                        "snesWorkRam $2400-$27FF",
                    ],
                    "reason": intervention["reason"],
                    "after_code_sha256": intervention["after_code_sha256"],
                    "after_color_sha256": intervention["after_color_sha256"],
                }
            )

        elapsed = 0
        while True:
            frame = int(m.get_state().get("frameCount", 0))
            x1_dir = args.output / f"x1-{elapsed:06d}"
            palette = bytes(m.read_memory("snesMemory", 0x412000, 0x1000))
            y_control = bytes(m.read_memory("snesMemory", 0x413000, 0x1000))
            code_x = bytes(m.read_memory("snesMemory", 0x414000, 0x4000))
            row = {
                "elapsed_frames": elapsed,
                "frame": frame,
                "screenshot": screenshot(
                    m, args.output / f"frame-{elapsed:06d}.png"
                ),
                "x1_source": {
                    "palette": write_artifact(x1_dir / "palette.bin", palette),
                    "y_control": write_artifact(
                        x1_dir / "y-control.bin", y_control
                    ),
                    "code_x": write_artifact(x1_dir / "code-x.bin", code_x),
                    "renderer_palette": write_artifact(
                        x1_dir / "c_palette.bin", words_be_to_le(palette)
                    ),
                    "renderer_spritecode": write_artifact(
                        x1_dir / "c_spritecode_full.bin", words_be_to_le(code_x)
                    ),
                    "renderer_spriteylow": write_artifact(
                        x1_dir / "c_spriteylow.bin", y_control[1:0x0600:2]
                    ),
                    "renderer_spritectrl": write_artifact(
                        x1_dir / "c_spritectrl.bin",
                        words_be_to_le(y_control[0x0600:0x0608]),
                    ),
                },
            }
            rows.append(row)
            if elapsed >= args.continue_frames:
                break
            count = min(args.capture_step, args.continue_frames - elapsed)
            m.run_frames(count)
            m.pause()
            elapsed += count
        final_state = args.output / "final.mss"
        m.save_state(final_state.resolve())
        wait_for_file(final_state)

    report = {
        "schema": 1,
        "scope": "intervened same-ROM prepared-BG raw-cache reconstruction proof; not organic acceptance",
        "rom": str(args.rom.resolve()),
        "rom_sha256": sha256_file(args.rom),
        "state": str(args.state.resolve()),
        "state_sha256": sha256_file(args.state),
        "advance_frames": args.advance_frames,
        "prepared_artifacts": prepared_artifacts,
        "intervention": intervention,
        "captures": rows,
        "final_state": {
            "path": str(final_state),
            "sha256": sha256_file(final_state),
            "bytes": final_state.stat().st_size,
        },
        "runtime_memory_writes": runtime_memory_writes,
    }
    target = args.output / "results.json"
    target.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"results": str(target), "captures": len(rows)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
