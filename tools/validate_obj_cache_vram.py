#!/usr/bin/env python3
"""Validate every claimed persistent OBJ-cache slot against PPU VRAM.

This is a paused-checkpoint renderer diagnostic, not performance or gameplay
evidence.  The production hash maps each 14-bit arcade tile code to one of 128
physical 16x16 OBJ slots.  Each claimed slot must contain the corresponding
preconverted 128-byte record from the private ROM image.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, "/home/chad/Mesen2/python")

import mesen_mcp.session as _session

_session.validate_mesen_build = lambda *_args, **_kwargs: None
from mesen_mcp import McpSession


DEFAULT_MESEN = ROOT / "tools" / "mesen211_mcp_controller.sh"
NATIVE_OBJ_FILE_BASE = 0x090000
NATIVE_OBJ_RECORD_BYTES = 128
RENDER_COMPLETE_HOOK = 0x7F8924


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--mesen", type=Path, default=DEFAULT_MESEN)
    parser.add_argument("--port", type=int, default=8950)
    parser.add_argument(
        "--settle-render",
        action="store_true",
        help="Advance an in-flight renderer to its next completion hook.",
    )
    return parser.parse_args()


def configure_dotnet8() -> None:
    dotnet8 = "/home/chad/.dotnet8"
    dotnet10 = "/home/chad/.dotnet10"
    os.environ["DOTNET_ROOT"] = dotnet8
    current = [
        item
        for item in os.environ.get("PATH", "").split(":")
        if item and item not in (dotnet8, dotnet10)
    ]
    os.environ["PATH"] = ":".join([dotnet8, dotnet10, *current])


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256(path: Path) -> str:
    return digest(path.read_bytes())


def git_value(*args: str) -> str:
    try:
        return subprocess.check_output(
            ["git", *args],
            cwd=ROOT,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        return "unknown"


def le16(data: bytes) -> int:
    return int.from_bytes(data, "little")


def slot_top_left_tile(slot: int) -> int:
    return 2 * (slot & 7) + 32 * (slot >> 3)


def slot_vram_record(vram: bytes, slot: int) -> bytes:
    """Reassemble TL/TR/BL/BR bytes from the SNES 16-tile-wide OBJ grid."""
    tile = slot_top_left_tile(slot)
    top = 0x8000 + tile * 32
    bottom = top + 0x0200
    return vram[top : top + 64] + vram[bottom : bottom + 64]


def mismatch_offsets(expected: bytes, observed: bytes) -> list[int]:
    return [
        index
        for index, (left, right) in enumerate(zip(expected, observed))
        if left != right
    ]


def main() -> int:
    args = parse_args()
    args.rom = args.rom.resolve()
    args.state = args.state.resolve()
    args.output = args.output.resolve()
    args.mesen = args.mesen.resolve()
    for label, path in (
        ("ROM", args.rom),
        ("state", args.state),
        ("Mesen", args.mesen),
    ):
        if not path.is_file():
            raise FileNotFoundError(f"{label} not found: {path}")
    args.output.mkdir(parents=True, exist_ok=False)
    configure_dotnet8()

    rom = args.rom.read_bytes()
    with McpSession(
        rom=args.rom,
        mesen=args.mesen,
        cwd=ROOT,
        port=args.port,
        boot_wait=6.0,
        socket_timeout=120.0,
        stderr_log=args.output / "mesen.stderr.log",
    ) as m:
        m.pause()
        m.load_state(args.state)
        m.pause()
        settle_result = None
        if args.settle_render:
            completion = m.add_exec_hook(
                RENDER_COMPLETE_HOOK, cpu_type="Snes"
            )
            m.drain_notifications(timeout=0.05)
            settle_result = m.run_until(
                max_frames=20, hook_handle=completion
            )
            m.pause()
            m.remove_hook(completion)
            if (settle_result or {}).get("reason") != "hookFired":
                raise RuntimeError(
                    f"in-flight renderer did not complete: {settle_result!r}"
                )
        hash_bytes = bytes(m.read_memory("snesWorkRam", 0x5000, 0x1000))
        vram = bytes(m.read_memory("snesVideoRam", 0, 0x10000))
        ppu_oam = bytes(m.read_memory("snesSpriteRam", 0, 0x0220))
        staged_oam = bytes(m.read_memory("snesWorkRam", 0x8600, 0x0220))
        encoded_manifest_length = le16(
            m.read_memory("snesWorkRam", 0x89BA, 2)
        )
        manifest_length = encoded_manifest_length & 0x7FFF
        manifest = (
            bytes(m.read_memory("snesWorkRam", 0xBC00, manifest_length))
            if (
                encoded_manifest_length & 0x8000
                and manifest_length <= 0x0300
                and manifest_length % 6 == 0
            )
            else b""
        )
        state = m.get_state()
        marker = le16(m.read_memory("snesWorkRam", 0x8980, 2))
        high_water = le16(m.read_memory("snesWorkRam", 0x00DE, 2))
        free_count = le16(m.read_memory("snesWorkRam", 0x89CE, 2))
        claimed_generation = le16(
            m.read_memory("snesWorkRam", 0x89A0, 2)
        )
        rendered_generation = le16(
            m.read_memory("snesWorkRam", 0x89A4, 2)
        )
        renderer_busy = le16(m.read_memory("snesWorkRam", 0x899C, 2))
        screenshot_response = m.take_screenshot(format="path")
        screenshot = args.output / "screen.png"
        shutil.copy2(Path(screenshot_response["path"]), screenshot)

    claims: list[dict[str, Any]] = []
    codes: dict[int, list[int]] = {}
    slots: dict[int, list[int]] = {}
    for bucket in range(1024):
        code = le16(hash_bytes[bucket * 2 : bucket * 2 + 2])
        if code == 0:
            continue
        slot_offset = 0x0800 + bucket * 2
        slot = le16(hash_bytes[slot_offset : slot_offset + 2])
        codes.setdefault(code, []).append(bucket)
        slots.setdefault(slot, []).append(bucket)
        claim: dict[str, Any] = {
            "bucket": bucket,
            "code": code,
            "slot": slot,
            "slot_in_range": slot < 128,
        }
        if code >= 0x4000 or slot >= 128:
            claim.update(
                {
                    "green": False,
                    "reason": (
                        "code_out_of_range"
                        if code >= 0x4000
                        else "slot_out_of_range"
                    ),
                }
            )
            claims.append(claim)
            continue
        source = NATIVE_OBJ_FILE_BASE + code * NATIVE_OBJ_RECORD_BYTES
        expected = rom[source : source + NATIVE_OBJ_RECORD_BYTES]
        observed = slot_vram_record(vram, slot)
        mismatches = mismatch_offsets(expected, observed)
        claim.update(
            {
                "expected_sha256": digest(expected),
                "observed_sha256": digest(observed),
                "mismatch_count": len(mismatches),
                "first_mismatch_offsets": mismatches[:16],
                "green": not mismatches,
            }
        )
        claims.append(claim)

    duplicate_codes = {
        f"{code:04x}": buckets
        for code, buckets in codes.items()
        if len(buckets) > 1
    }
    duplicate_slots = {
        str(slot): buckets
        for slot, buckets in slots.items()
        if len(buckets) > 1
    }
    bad_claims = [claim for claim in claims if not claim["green"]]

    code_to_slot = {
        code: le16(
            hash_bytes[0x0800 + buckets[0] * 2 : 0x0802 + buckets[0] * 2]
        )
        for code, buckets in codes.items()
        if len(buckets) == 1
    }
    oam_tile_claims: list[dict[str, Any]] = []
    for index in range(0, len(manifest), 6):
        oam_index = index // 6
        raw_code = int.from_bytes(manifest[index + 2 : index + 4], "big")
        code = raw_code & 0x3FFF
        slot = code_to_slot.get(code)
        oam_offset = oam_index * 4
        actual_tile = ppu_oam[oam_offset + 2] | (
            (ppu_oam[oam_offset + 3] & 1) << 8
        )
        expected_tile = (
            slot_top_left_tile(slot) if slot is not None and slot < 128 else None
        )
        oam_tile_claims.append(
            {
                "oam_index": oam_index,
                "code": code,
                "slot": slot,
                "expected_tile": expected_tile,
                "actual_tile": actual_tile,
                "green": expected_tile == actual_tile,
            }
        )
    oam_alignment_applicable = bool(
        manifest
        and claimed_generation == rendered_generation
        and renderer_busy == 0
        and ppu_oam == staged_oam
    )
    bad_oam_tile_claims = [
        claim for claim in oam_tile_claims if not claim["green"]
    ]
    result = {
        "scope": (
            "paused-checkpoint persistent OBJ hash-to-PPU-VRAM byte oracle; "
            "not performance or gameplay evidence"
        ),
        "project_commit": git_value("rev-parse", "HEAD"),
        "project_status": git_value("status", "--short").splitlines(),
        "rom": str(args.rom),
        "rom_sha256": sha256(args.rom),
        "state": str(args.state),
        "state_sha256": sha256(args.state),
        "mesen": str(args.mesen),
        "mesen_sha256": sha256(args.mesen),
        "frame": int(state.get("frameCount", 0)),
        "settle_render": args.settle_render,
        "settle_result": settle_result,
        "screenshot": {
            "path": str(screenshot),
            "sha256": sha256(screenshot),
            "response": screenshot_response,
        },
        "cache_marker": marker,
        "high_water": high_water,
        "free_count": free_count,
        "effective_occupied": high_water - free_count,
        "claimed_generation": claimed_generation,
        "rendered_generation": rendered_generation,
        "renderer_busy": renderer_busy,
        "encoded_manifest_length": encoded_manifest_length,
        "manifest_length": manifest_length,
        "manifest_record_count": len(manifest) // 6,
        "ppu_oam_matches_staging": ppu_oam == staged_oam,
        "oam_alignment_applicable": oam_alignment_applicable,
        "bad_oam_tile_claim_count": len(bad_oam_tile_claims),
        "oam_tile_claims": oam_tile_claims,
        "claim_count": len(claims),
        "green_claim_count": len(claims) - len(bad_claims),
        "bad_claim_count": len(bad_claims),
        "duplicate_codes": duplicate_codes,
        "duplicate_slots": duplicate_slots,
        "claims": claims,
    }
    result["green"] = bool(
        marker == 0xA55A
        and high_water <= 128
        and free_count <= high_water
        and not bad_claims
        and not duplicate_codes
        and not duplicate_slots
        and (
            not oam_alignment_applicable
            or not bad_oam_tile_claims
        )
    )
    target = args.output / "results.json"
    target.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "green": result["green"],
                "claim_count": result["claim_count"],
                "bad_claim_count": result["bad_claim_count"],
                "duplicate_code_count": len(duplicate_codes),
                "duplicate_slot_count": len(duplicate_slots),
                "oam_alignment_applicable": oam_alignment_applicable,
                "bad_oam_tile_claim_count": len(bad_oam_tile_claims),
                "high_water": high_water,
                "free_count": free_count,
                "claimed_generation": claimed_generation,
                "rendered_generation": rendered_generation,
                "renderer_busy": renderer_busy,
                "results": str(target),
            },
            sort_keys=True,
        )
    )
    return int(not result["green"])


if __name__ == "__main__":
    raise SystemExit(main())
