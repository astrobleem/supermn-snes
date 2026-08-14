#!/usr/bin/env python3
"""Trace one fresh-movie BG native-record DMA at its real PPU deadline.

This is a read-only fresh replay diagnostic.  It stops at the selected BG code
and physical slot, records the PPU scanline at ``dma0_blank_pulse_extended``,
and compares the destination VRAM record before/after the actual helper.  It
does not issue input, write memory, or establish framebuffer acceptance.
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
sys.path.insert(0, "/home/chad/Mesen2/python")

import mesen_mcp.session as _session

_session.validate_mesen_build = lambda *_args, **_kwargs: None
from mesen_mcp import McpSession


DEFAULT_MESEN = ROOT / "tools/mesen211_mcp_controller.sh"
BG_GRAPHICS_FILE_BASE = 0x090000
TILE_DMA_ENTRY = 0x7FAA0A
DMA_HELPER_ENTRY = 0x7F8A7F
DMA_DIRECT_ENTRY = 0x7F8ACB
DMA_PUBLISH_ENTRY = 0x7F8AD2
TILE_DMA_RETURN = 0x7FAA68
BG_REVERSE_OWNER_BASE = 0x7ED000


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


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def le16(data: bytes) -> int:
    return int.from_bytes(data, "little")


def ppu_boundary(m: McpSession) -> dict[str, Any]:
    state = dict(m.get_state())
    ppu = dict(m.get_ppu_state())
    return {
        "frame": int(state.get("frameCount", 0)),
        "scanline": int(ppu.get("scanline", -1)),
        "cpu": dict(m.get_cpu_state("Snes")),
        "hvbjoy": m.read_memory("snesMemory", 0x4212, 1)[0],
        "dma0_descriptor": m.read_memory("snesMemory", 0x4300, 7).hex(),
        "pending_dma0": m.read_memory("snesWorkRam", 0x1F11, 1)[0],
    }


def hook_events(rows: list[dict[str, Any]], handles: dict[int, str]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for row in rows:
        if row.get("method") != "notifications/mesen/hookFired":
            continue
        params = dict(row.get("params", {}))
        handle = int(params.get("handle", -1))
        if handle not in handles:
            continue
        events.append(
            {
                "label": handles[handle],
                "frame": int(params.get("frame", 0)),
                "address": int(params.get("address", 0)),
                "value": int(params.get("value", 0)),
                "kind": params.get("kind"),
            }
        )
    return events


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, required=True)
    parser.add_argument("--movie", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--emulator", type=Path, default=DEFAULT_MESEN)
    parser.add_argument("--port", type=int, default=9310)
    parser.add_argument("--target-code", type=lambda value: int(value, 0), default=0x19AE)
    parser.add_argument("--target-slot", type=lambda value: int(value, 0), default=2)
    parser.add_argument(
        "--verify-frame",
        type=int,
        default=0,
        help="skip event tracing; inspect the selected owner/VRAM record at this movie frame",
    )
    parser.add_argument(
        "--trace-frame",
        type=int,
        default=0,
        help="passively retain two frames of selected BG DMA path events from this frame",
    )
    parser.add_argument("--arm-frame", type=int, default=5000)
    parser.add_argument("--max-frames", type=int, default=5600)
    args = parser.parse_args()

    for path in (args.rom, args.movie, args.emulator):
        if not path.is_file():
            raise FileNotFoundError(path)
    if args.output.exists():
        raise SystemExit(f"output already exists: {args.output}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    configure_dotnet8()

    hits: list[dict[str, Any]] = []
    with McpSession(
        rom=args.rom.resolve(),
        mesen=args.emulator.resolve(),
        cwd=ROOT,
        port=args.port,
        boot_wait=6.0,
        socket_timeout=300.0,
        stderr_log=args.output.with_suffix(".stderr.log"),
    ) as m:
        m.pause()
        play_response = m.play_movie(args.movie.resolve())
        m.pause()
        if args.trace_frame:
            while True:
                current_frame = int(m.get_state().get("frameCount", 0))
                if current_frame >= args.trace_frame:
                    break
                result = m.run_frames(min(250, args.trace_frame - current_frame))
                m.pause()
                advanced_frame = int(m.get_state().get("frameCount", 0))
                if advanced_frame <= current_frame:
                    raise RuntimeError(
                        f"movie made no progress at frame {current_frame}: {result!r}"
                    )
            if current_frame != args.trace_frame:
                raise RuntimeError(
                    f"movie overshot trace frame {args.trace_frame}: {current_frame}"
                )
            owner_address = BG_REVERSE_OWNER_BASE + args.target_slot * 2
            handles = {
                m.add_exec_hook(TILE_DMA_ENTRY, cpu_type="Snes"): "tile_dma_entry",
                m.add_exec_hook(DMA_HELPER_ENTRY, cpu_type="Snes"): "dma_helper_entry",
                m.add_exec_hook(DMA_DIRECT_ENTRY, cpu_type="Snes"): "dma_direct_entry",
                m.add_exec_hook(DMA_PUBLISH_ENTRY, cpu_type="Snes"): "dma_publish_entry",
                m.add_exec_hook(TILE_DMA_RETURN, cpu_type="Snes"): "tile_dma_return",
                m.add_write_hook(owner_address, cpu_type="Snes"): "slot2_owner_low",
                m.add_write_hook(owner_address + 1, cpu_type="Snes"): "slot2_owner_high",
                m.add_write_hook(0x420B, cpu_type="Snes"): "mdmaen_write",
                m.add_write_hook(0x7E1F11, cpu_type="Snes"): "pending_dma0_write",
                m.add_read_hook(0x4212, cpu_type="Snes"): "hvbjoy_read",
                m.add_read_hook(0x213D, cpu_type="Snes"): "opvct_read",
                m.add_read_hook(0x4306, cpu_type="Snes"): "dma0_size_high_read",
            }
            m.drain_notifications(timeout=0.05)
            run_result = m.run_frames(2)
            m.pause()
            notifications = m.drain_notifications(timeout=0.5)
            events = hook_events(notifications, handles)
            for handle in handles:
                m.remove_hook(handle)
            owner = le16(
                m.read_memory(
                    "snesWorkRam", 0xD000 + args.target_slot * 2, 2
                )
            )
            observed = bytes(
                m.read_memory(
                    "snesVideoRam", 0x2000 + args.target_slot * 128, 128
                )
            )
            rom_bytes = args.rom.read_bytes()
            expected_start = BG_GRAPHICS_FILE_BASE + args.target_code * 128
            expected = rom_bytes[expected_start:expected_start + 128]
            report = {
                "schema": 1,
                "scope": "fresh movie passive two-frame BG DMA path trace",
                "rom_sha256": sha256(args.rom),
                "movie_sha256": sha256(args.movie),
                "trace_frame_start": args.trace_frame,
                "trace_frame_end": int(m.get_state().get("frameCount", 0)),
                "run_result": run_result,
                "target_code": args.target_code,
                "target_slot": args.target_slot,
                "observed_owner": owner,
                "owner_matches": owner == args.target_code,
                "expected_sha256": hashlib.sha256(expected).hexdigest(),
                "observed_sha256": hashlib.sha256(observed).hexdigest(),
                "record_matches": len(expected) == 128 and observed == expected,
                "changed_bytes": sum(
                    left != right for left, right in zip(expected, observed)
                ),
                "events": events,
                "boundary": ppu_boundary(m),
                "runtime_memory_writes": [],
            }
            m.stop_movie()
            args.output.write_text(
                json.dumps(report, indent=2, sort_keys=True) + "\n"
            )
            print(
                json.dumps(
                    {
                        "frames": [report["trace_frame_start"], report["trace_frame_end"]],
                        "events": len(events),
                        "owner_matches": report["owner_matches"],
                        "record_matches": report["record_matches"],
                        "changed_bytes": report["changed_bytes"],
                        "output": str(args.output),
                    },
                    sort_keys=True,
                )
            )
            return 0
        if args.verify_frame:
            while True:
                current_frame = int(m.get_state().get("frameCount", 0))
                if current_frame >= args.verify_frame:
                    break
                result = m.run_frames(min(250, args.verify_frame - current_frame))
                m.pause()
                advanced_frame = int(m.get_state().get("frameCount", 0))
                if advanced_frame <= current_frame:
                    raise RuntimeError(
                        f"movie made no progress at frame {current_frame}: {result!r}"
                    )
            if current_frame != args.verify_frame:
                raise RuntimeError(
                    f"movie overshot verification frame {args.verify_frame}: {current_frame}"
                )
            owner = le16(
                m.read_memory(
                    "snesWorkRam", 0xD000 + args.target_slot * 2, 2
                )
            )
            observed = bytes(
                m.read_memory(
                    "snesVideoRam", 0x2000 + args.target_slot * 128, 128
                )
            )
            rom_bytes = args.rom.read_bytes()
            expected_start = BG_GRAPHICS_FILE_BASE + args.target_code * 128
            expected = rom_bytes[expected_start:expected_start + 128]
            report = {
                "schema": 1,
                "scope": "fresh movie selected BG owner/VRAM record checkpoint",
                "rom_sha256": sha256(args.rom),
                "movie_sha256": sha256(args.movie),
                "frame": int(m.get_state().get("frameCount", 0)),
                "target_code": args.target_code,
                "target_slot": args.target_slot,
                "observed_owner": owner,
                "owner_matches": owner == args.target_code,
                "expected_sha256": hashlib.sha256(expected).hexdigest(),
                "observed_sha256": hashlib.sha256(observed).hexdigest(),
                "record_matches": len(expected) == 128 and observed == expected,
                "changed_bytes": sum(
                    left != right for left, right in zip(expected, observed)
                ),
                "boundary": ppu_boundary(m),
                "runtime_memory_writes": [],
            }
            m.stop_movie()
            args.output.write_text(
                json.dumps(report, indent=2, sort_keys=True) + "\n"
            )
            print(
                json.dumps(
                    {
                        "frame": report["frame"],
                        "owner_matches": report["owner_matches"],
                        "record_matches": report["record_matches"],
                        "changed_bytes": report["changed_bytes"],
                        "output": str(args.output),
                    },
                    sort_keys=True,
                )
            )
            return 0 if report["owner_matches"] and report["record_matches"] else 1
        if args.arm_frame:
            m.run_frames(args.arm_frame)
            m.pause()
        # Stop on the selected reverse-owner publication rather than relying on
        # the direct-upload entry hook.  Movie playback can cross this routine
        # while the debugger reports no execute notification, but the cache
        # publication is the exact immediately-preceding observable event and
        # must occur before bg_tile_dma is called.
        owner_address = BG_REVERSE_OWNER_BASE + args.target_slot * 2
        tile_hook = m.add_write_hook(owner_address, cpu_type="Snes")
        target: dict[str, Any] | None = None
        for _index in range(64):
            result = m.run_until(max_frames=args.max_frames, hook_handle=tile_hook)
            m.pause()
            if (result or {}).get("reason") != "hookFired":
                break
            # A 16-bit STA exposes its low-byte bus write to the hook before
            # the high owner byte is visible.  $E4/$DA are the stable source
            # operands at this exact bse_store boundary.
            code = le16(m.read_memory("snesWorkRam", 0x00E4, 2))
            slot = le16(m.read_memory("snesWorkRam", 0x00DA, 2))
            hit = {"code": code, "slot": slot, **ppu_boundary(m)}
            hits.append(hit)
            if code == args.target_code:
                target = hit
                break
        m.remove_hook(tile_hook)
        if target is None:
            args.output.write_text(
                json.dumps(
                    {
                        "schema": 1,
                        "scope": "failed fresh slot-owner target acquisition diagnostic",
                        "rom_sha256": sha256(args.rom),
                        "movie_sha256": sha256(args.movie),
                        "arm_frame": args.arm_frame,
                        "target_code": args.target_code,
                        "target_slot": args.target_slot,
                        "entry_hits": hits,
                        "error": "target owner publication not reached",
                        "runtime_memory_writes": [],
                    },
                    indent=2,
                    sort_keys=True,
                )
                + "\n"
            )
            raise RuntimeError(
                f"target code ${args.target_code:04X}/slot {args.target_slot} not reached"
            )

        vram_offset = 0x2000 + args.target_slot * 128
        before = bytes(m.read_memory("snesVideoRam", vram_offset, 128))
        helper_hook = m.add_exec_hook(DMA_HELPER_ENTRY, cpu_type="Snes")
        helper_result = m.run_until(max_frames=2, hook_handle=helper_hook)
        m.pause()
        if (helper_result or {}).get("reason") != "hookFired":
            raise RuntimeError(f"DMA helper did not fire: {helper_result!r}")
        helper = ppu_boundary(m)
        m.remove_hook(helper_hook)

        handles = {
            m.add_write_hook(0x420B, cpu_type="Snes"): "mdmaen_write",
            m.add_write_hook(0x7E1F11, cpu_type="Snes"): "pending_dma0_write",
        }
        return_hook = m.add_exec_hook(TILE_DMA_RETURN, cpu_type="Snes")
        return_result = m.run_until(max_frames=2, hook_handle=return_hook)
        m.pause()
        if (return_result or {}).get("reason") != "hookFired":
            raise RuntimeError(f"tile DMA did not return: {return_result!r}")
        after_boundary = ppu_boundary(m)
        notifications = m.drain_notifications(timeout=0.25)
        events = hook_events(notifications, handles)
        after = bytes(m.read_memory("snesVideoRam", vram_offset, 128))
        for handle in handles:
            m.remove_hook(handle)
        m.remove_hook(return_hook)
        movie_state = m.movie_state()
        m.stop_movie()

    report = {
        "schema": 1,
        "scope": (
            "fresh StartWithoutSaveData movie replay; one selected BG native-record "
            "DMA deadline; read-only diagnostic, not framebuffer acceptance"
        ),
        "rom": str(args.rom.resolve()),
        "rom_sha256": sha256(args.rom),
        "movie": str(args.movie.resolve()),
        "movie_sha256": sha256(args.movie),
        "play_response": play_response,
        "movie_state": movie_state,
        "target_code": args.target_code,
        "target_slot": args.target_slot,
        "entry_hits": hits,
        "target_entry": target,
        "helper_entry": helper,
        "return_boundary": after_boundary,
        "events": events,
        "vram": {
            "byte_offset": vram_offset,
            "before_sha256": hashlib.sha256(before).hexdigest(),
            "after_sha256": hashlib.sha256(after).hexdigest(),
            "changed_bytes": sum(left != right for left, right in zip(before, after)),
            "before": before.hex(),
            "after": after.hex(),
        },
        "runtime_memory_writes": [],
    }
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(
        json.dumps(
            {
                "target": f"${args.target_code:04X}/slot{args.target_slot}",
                "frame": target["frame"],
                "helper_scanline": helper["scanline"],
                "events": events,
                "changed_bytes": report["vram"]["changed_bytes"],
                "output": str(args.output),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
