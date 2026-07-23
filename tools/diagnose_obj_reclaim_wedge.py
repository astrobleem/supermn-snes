#!/usr/bin/env python3
"""Reproduce and preserve the v55 production-input renderer wedge.

This is a checkpointed diagnostic, not performance or cold-boot evidence.  It
loads an organically armed recovery_baseline checkpoint, repeats that harness's
exact first-coin schedule against the real controller port, and pauses when the
next $00:F5A3 tick fails to arrive.  The saved state and JSON snapshot retain
both CPU PCs plus the OBJ manifest/hash/reclamation telemetry for root-cause
work that the cold-boot harness's fail-fast shutdown cannot preserve.
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

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, "/home/chad/Mesen2/python")

import mesen_mcp.session as _session

_session.validate_mesen_build = lambda *_args, **_kwargs: None
from mesen_mcp import McpSession


DEFAULT_NEXEN = Path(
    "/mnt/sdc1/Nexen-r5-20260712/"
    "bin/linux-x64/Release/linux-x64/publish/Nexen"
)
TICK_HOOK = 0x00F5A3
VIDEO_FILE_BASE = 0x298000
VIDEO_WRAM_OFFSET = 0x18000
VIDEO_WRAM_LENGTH = 0x3000


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--nexen", type=Path, default=DEFAULT_NEXEN)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--port", type=int, default=36100)
    parser.add_argument("--preinput-ticks", type=int, default=105)
    parser.add_argument("--coin-hold-ticks", type=int, default=8)
    parser.add_argument("--missing-tick-seconds", type=float, default=3.0)
    parser.add_argument(
        "--reclaim-hooks",
        action="store_true",
        help="Trace OBJ hash clears, preflight/reclaim entries, and free-list writes.",
    )
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def tool_text(response: Any) -> Any:
    return response


def main() -> int:
    args = parse_args()
    for path in (args.rom, args.state, args.nexen):
        if not path.is_file():
            raise FileNotFoundError(path)
    args.output.mkdir(parents=True, exist_ok=False)

    result: dict[str, Any] = {
        "scope": "organically-armed checkpointed exact-input wedge diagnostic; not FPS",
        "rom": str(args.rom.resolve()),
        "rom_sha256": sha256(args.rom),
        "state": str(args.state.resolve()),
        "state_sha256": sha256(args.state),
        "nexen": str(args.nexen.resolve()),
        "nexen_sha256": sha256(args.nexen),
        "schedule": {
            "preinput_ticks": args.preinput_ticks,
            "coin_hold_ticks": args.coin_hold_ticks,
            "missing_tick_seconds": args.missing_tick_seconds,
            "transport": "nexen_port0_manual_4016",
        },
    }

    with McpSession(
        rom=args.rom.resolve(),
        mesen=args.nexen.resolve(),
        cwd=ROOT,
        port=args.port,
        boot_wait=6.0,
        socket_timeout=60.0,
        stderr_log=args.output / "emulator.stderr.log",
    ) as m:
        m.pause()
        m.load_state(args.state.resolve())
        m.pause()
        rom_mirror = args.rom.read_bytes()[
            VIDEO_FILE_BASE : VIDEO_FILE_BASE + VIDEO_WRAM_LENGTH
        ]
        old_mirror = m.read_memory(
            "snesWorkRam", VIDEO_WRAM_OFFSET, VIDEO_WRAM_LENGTH
        )
        for offset in range(0, VIDEO_WRAM_LENGTH, 0x1000):
            m.write_memory(
                "snesWorkRam",
                VIDEO_WRAM_OFFSET + offset,
                rom_mirror[offset : offset + 0x1000].hex(),
            )
        if m.read_memory(
            "snesWorkRam", VIDEO_WRAM_OFFSET, VIDEO_WRAM_LENGTH
        ) != rom_mirror:
            raise RuntimeError("production WRAM video mirror did not verify")
        result["mirror_intervention"] = {
            "differing_bytes": sum(
                old != new for old, new in zip(old_mirror, rom_mirror)
            ),
            "sha256": hashlib.sha256(rom_mirror).hexdigest(),
        }
        initial_state = m.get_state()
        initial_tick = int.from_bytes(
            m.read_memory("Sa1Memory", 0x0760, 2), "little"
        )
        result["initial"] = {
            "emulator": initial_state,
            "tick": initial_tick,
            "snes_cpu": m.get_cpu_state("Snes"),
            "sa1_cpu": m.get_cpu_state("Sa1"),
        }

        hook = m.add_exec_hook(TICK_HOOK, cpu_type="Sa1")
        diagnostic_hooks: dict[int, str] = {}
        if args.reclaim_hooks:
            for address, label in (
                (0x7F8740, "obj_hclr"),
                (0x7FAE2B, "obj_cache_preflight"),
                (0x7FAECB, "obj_cache_reclaim_fast"),
                (0x7FAF06, "ocr_slot_loop"),
            ):
                diagnostic_hooks[
                    m.add_exec_hook(address, cpu_type="Snes")
                ] = label
            diagnostic_hooks[
                m.add_write_hook(
                    0x7E7B00, end_address=0x7E7B7F, cpu_type="Snes"
                )
            ] = "obj_free_list_write"
        m.drain_notifications(timeout=0.05)
        m.tool("set_input", {"port": 0, "buttons": 0, "hold": True})
        m.resume()

        hook_events = 0
        edge_events: list[dict[str, Any]] = []
        diagnostic_counts = {
            label: 0 for label in diagnostic_hooks.values()
        }
        diagnostic_events: list[dict[str, Any]] = []
        release_event_time: float | None = None
        last_hook_time: float | None = None
        post_release_hooks = 0
        schedule_complete = False
        overall_deadline = time.monotonic() + 30.0
        while time.monotonic() < overall_deadline:
            for note in m.drain_notifications(timeout=0.02):
                params = note.get("params", {})
                note_handle = params.get("handle")
                if note_handle in diagnostic_hooks:
                    label = diagnostic_hooks[note_handle]
                    diagnostic_counts[label] += 1
                    if len(diagnostic_events) < 256:
                        diagnostic_events.append(
                            {
                                "label": label,
                                "address": params.get("address"),
                                "value": params.get("value"),
                                "cycle": params.get("cycleCount"),
                                "frame": params.get("frame"),
                            }
                        )
                    continue
                if note_handle != hook:
                    continue
                hook_events += 1
                last_hook_time = time.monotonic()
                event = {
                    "hook_event": hook_events,
                    "cycle": params.get("cycleCount"),
                    "frame": params.get("frame"),
                }
                if hook_events == args.preinput_ticks:
                    m.tool(
                        "set_input",
                        {
                            "port": 0,
                            "buttons": McpSession.BTN_SELECT,
                            "hold": True,
                        },
                    )
                    event["input"] = "coin_hold"
                    edge_events.append(event)
                elif hook_events == args.preinput_ticks + args.coin_hold_ticks:
                    m.tool("set_input", {"port": 0, "buttons": 0, "hold": True})
                    event["input"] = "coin_release"
                    edge_events.append(event)
                    release_event_time = time.monotonic()
                elif release_event_time is not None:
                    post_release_hooks += 1
                    coin2_hold = (
                        args.preinput_ticks + args.coin_hold_ticks + 7
                    )
                    coin2_release = coin2_hold + args.coin_hold_ticks
                    start_hold = coin2_release + 12
                    start_release = start_hold + 10
                    if hook_events == coin2_hold:
                        m.tool(
                            "set_input",
                            {
                                "port": 0,
                                "buttons": McpSession.BTN_SELECT,
                                "hold": True,
                            },
                        )
                        edge_events.append({**event, "input": "coin2_hold"})
                    elif hook_events == coin2_release:
                        m.tool(
                            "set_input", {"port": 0, "buttons": 0, "hold": True}
                        )
                        edge_events.append({**event, "input": "coin2_release"})
                    elif hook_events == start_hold:
                        m.tool(
                            "set_input",
                            {
                                "port": 0,
                                "buttons": McpSession.BTN_START,
                                "hold": True,
                            },
                        )
                        edge_events.append({**event, "input": "start_hold"})
                    elif hook_events == start_release:
                        m.tool(
                            "set_input", {"port": 0, "buttons": 0, "hold": True}
                        )
                        edge_events.append({**event, "input": "start_release"})
                    elif hook_events >= start_release + 5:
                        schedule_complete = True
                        edge_events.append(
                            {**event, "input": "schedule_survived_plus_5"}
                        )
            if schedule_complete:
                break
            if (
                release_event_time is not None
                and last_hook_time is not None
                and time.monotonic() - last_hook_time
                >= args.missing_tick_seconds
            ):
                break

        pause_result = m.pause()
        m.drain_notifications(timeout=0.05)
        paused_state = m.get_state()
        snes_cpu = m.get_cpu_state("Snes")
        sa1_cpu = m.get_cpu_state("Sa1")

        def u16(memory_type: str, address: int) -> int:
            return int.from_bytes(
                m.read_memory(memory_type, address, 2), "little"
            )

        manifest_length = u16("snesWorkRam", 0x89BA)
        safe_manifest_length = min(manifest_length & 0xFFFE, 0x0400)
        manifest = m.read_memory("snesWorkRam", 0xBC00, safe_manifest_length)
        obj_hash = m.read_memory("snesWorkRam", 0xA800, 0x0400)
        obj_slots = m.read_memory("snesWorkRam", 0xAC00, 0x0400)
        used_bitmap = m.read_memory("snesWorkRam", 0x2E00, 0x0080)
        free_list = m.read_memory("snesWorkRam", 0x7B00, 0x0080)
        hash_words = [
            int.from_bytes(obj_hash[index : index + 2], "little")
            for index in range(0, len(obj_hash), 2)
        ]
        live_hash_indices = [
            index
            for index, code in enumerate(hash_words)
            if code not in (0x0000, 0xFFFF)
        ]
        live_slots = [
            int.from_bytes(
                obj_slots[index * 2 : index * 2 + 2], "little"
            )
            for index in live_hash_indices
        ]

        snes_pc = (int(snes_cpu.get("k", 0)) << 16) | int(
            snes_cpu.get("pc", 0)
        )
        sa1_pc = (int(sa1_cpu.get("k", 0)) << 16) | int(
            sa1_cpu.get("pc", 0)
        )
        telemetry = {
            "frame_request": u16("snesMemory", 0x3300),
            "frame_ack": u16("snesMemory", 0x3302),
            "tick": u16("Sa1Memory", 0x0760),
            "ac": u16("Sa1Memory", 0x00AC),
            "pc68k_low": u16("Sa1Memory", 0x0040),
            "pc68k_high": u16("Sa1Memory", 0x0042),
            "halt": u16("Sa1Memory", 0x004E),
            "obj_slots_high_water": u16("snesWorkRam", 0x00DE),
            "renderer_busy": u16("snesWorkRam", 0x899C),
            "manifest_length": manifest_length,
            "obj_queue_count": u16("snesWorkRam", 0x89C6),
            "obj_restart_reason": u16("snesWorkRam", 0x89C8),
            "obj_restart_slots": u16("snesWorkRam", 0x89CA),
            "obj_restart_queue": u16("snesWorkRam", 0x89CC),
            "obj_free_count": u16("snesWorkRam", 0x89CE),
            "obj_hash_zero_words": hash_words.count(0x0000),
            "obj_hash_tombstones": hash_words.count(0xFFFF),
            "obj_hash_live_words": len(live_hash_indices),
            "obj_live_unique_slots": len(set(live_slots)),
            "obj_live_slot_min": min(live_slots, default=None),
            "obj_live_slot_max": max(live_slots, default=None),
            "used_bitmap_nonzero": sum(value != 0 for value in used_bitmap),
            "free_list_prefix": list(
                free_list[: min(u16("snesWorkRam", 0x89CE), 128)]
            ),
        }

        screenshot_response = m.take_screenshot(format="path")
        screenshot = args.output / "wedge.png"
        shutil.copy2(Path(screenshot_response["path"]), screenshot)
        wedge_state = args.output / "wedge.mss"
        save_response = m.save_state(wedge_state.resolve())
        result["observation"] = {
            "hook_events": hook_events,
            "edge_events": edge_events,
            "diagnostic_counts": diagnostic_counts,
            "diagnostic_events": diagnostic_events,
            "post_release_hooks": post_release_hooks,
            "schedule_complete": schedule_complete,
            "hooks_went_silent": (
                release_event_time is not None
                and last_hook_time is not None
                and time.monotonic() - last_hook_time
                >= args.missing_tick_seconds
            ),
            "pause": pause_result,
            "emulator": paused_state,
            "snes_cpu": snes_cpu,
            "sa1_cpu": sa1_cpu,
            "snes_pc": snes_pc,
            "sa1_pc": sa1_pc,
            "snes_disassembly": tool_text(
                m.disassemble(snes_pc, count=24, cpu_type="Snes")
            ),
            "sa1_disassembly": tool_text(
                m.disassemble(sa1_pc, count=24, cpu_type="Sa1")
            ),
            "snes_trace": m.trace_log(count=64, cpu_type="Snes"),
            "sa1_trace": m.trace_log(count=64, cpu_type="Sa1"),
            "telemetry": telemetry,
            "manifest_sha256": hashlib.sha256(manifest).hexdigest(),
            "manifest_hex": manifest.hex(),
            "obj_hash_sha256": hashlib.sha256(obj_hash).hexdigest(),
            "screenshot": {
                "path": str(screenshot),
                "sha256": sha256(screenshot),
                "response": screenshot_response,
            },
            "state": {
                "path": str(wedge_state),
                "sha256": sha256(wedge_state),
                "response": save_response,
            },
        }

    result_path = args.output / "results.json"
    result_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(
        json.dumps(
            {
                "hook_events": result["observation"]["hook_events"],
                "post_release_hooks": result["observation"]["post_release_hooks"],
                "hooks_went_silent": result["observation"]["hooks_went_silent"],
                "snes_pc": result["observation"]["snes_pc"],
                "sa1_pc": result["observation"]["sa1_pc"],
                "telemetry": result["observation"]["telemetry"],
                "results": str(result_path),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
