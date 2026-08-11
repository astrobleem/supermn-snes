#!/usr/bin/env python3
"""Capture a coherent pre-instruction $01E7C0 entry from the campaign prestate."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ROM = ROOT / "build/interp.sfc"
DEFAULT_STATE = (
    ROOT
    / "build/playtest-investigation-20260725"
    / "campaign-halt-prestate-a08508d-tick6619-v1"
    / "post-event-06619.mss"
)
DEFAULT_NEXEN = Path(
    "/mnt/sdc1/Nexen-r5-20260712/"
    "bin/linux-x64/Release/linux-x64/publish/Nexen"
)
ENTRY_NATIVE = 0x98AE00
ENTRY_ROM_OFFSET = 0x2C2E00
ENTRY_BYTES = bytes.fromhex("c230")
IRAM_SIZE = 0x0800
WORK_BASE = 0x400000
WORK_SIZE = 0x10000

sys.path.insert(0, "/home/chad/Mesen2/python")
sys.path.insert(0, str(ROOT / "tools"))
import mesen_mcp.session as _session  # noqa: E402

_session.validate_mesen_build = lambda *_args, **_kwargs: None
from mesen_mcp import McpSession  # noqa: E402

import replay_mame_controller_campaign as campaign  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--nexen", type=Path, default=DEFAULT_NEXEN)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--port", type=int, default=9600)
    parser.add_argument("--buttons", type=lambda value: int(value, 0), default=0x80)
    parser.add_argument("--max-frames", type=int, default=8)
    args = parser.parse_args()
    for label, path in (
        ("ROM", args.rom),
        ("prestate", args.state),
        ("Nexen", args.nexen),
    ):
        if not path.is_file():
            parser.error(f"missing {label}: {path}")
    if args.output.exists():
        parser.error(f"output already exists: {args.output}")
    return args


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_work(m: McpSession) -> bytes:
    return b"".join(
        bytes(m.read_memory("snesMemory", WORK_BASE + offset, 0x4000))
        for offset in range(0, WORK_SIZE, 0x4000)
    )


def main() -> int:
    args = parse_args()
    args.rom = args.rom.resolve()
    args.state = args.state.resolve()
    args.nexen = args.nexen.resolve()
    args.output = args.output.resolve()
    args.output.mkdir(parents=True)
    os.environ["DOTNET_ROOT"] = "/home/chad/.dotnet10"

    with McpSession(
        rom=args.rom,
        mesen=args.nexen,
        cwd=ROOT,
        port=args.port,
        boot_wait=6.0,
        socket_timeout=180.0,
        stderr_log=args.output / "emulator.stderr.log",
    ) as m:
        m.pause()
        load_response = m.load_state(args.state)
        m.pause()
        input_response = campaign.set_held_input(m, args.buttons)
        entry_original = bytes(
            m.read_memory("snesPrgRom", ENTRY_ROM_OFFSET, 2)
        )
        if entry_original != ENTRY_BYTES:
            raise RuntimeError(
                f"entry bytes moved: {entry_original.hex()} != {ENTRY_BYTES.hex()}"
            )
        # Hold the very first entry instruction in a two-byte self-loop.  The
        # hook can notify late, but no architectural/native instruction can
        # commit while the entry remains this loop.
        m.write_memory("snesPrgRom", ENTRY_ROM_OFFSET, "80fe")
        hook = m.add_exec_hook(ENTRY_NATIVE, cpu_type="Sa1")
        m.drain_notifications(timeout=0.05)
        try:
            response = m.run_until(
                max_frames=args.max_frames,
                hook_handle=hook,
            )
            m.pause()
        finally:
            m.remove_hook(hook)
        if response.get("reason") != "hookFired":
            m.write_memory(
                "snesPrgRom",
                ENTRY_ROM_OFFSET,
                entry_original.hex(),
            )
            raise RuntimeError(
                f"campaign did not reach ${ENTRY_NATIVE:06X}: {response!r}"
            )
        cpu = m.get_cpu_state("Sa1")
        physical_pc = (
            (int(cpu.get("k", 0)) << 16) | int(cpu.get("pc", 0))
        )
        if physical_pc != ENTRY_NATIVE:
            m.write_memory(
                "snesPrgRom",
                ENTRY_ROM_OFFSET,
                entry_original.hex(),
            )
            raise RuntimeError(
                f"entry hook ran ahead to ${physical_pc:06X}"
            )

        iram = bytes(m.read_memory("Sa1Memory", 0, IRAM_SIZE))
        work = read_work(m)
        (args.output / "entry.iram.bin").write_bytes(iram)
        (args.output / "entry.work.bin").write_bytes(work)
        m68k = campaign.register_snapshot(m)
        fixture_regs = {
            name: int(value, 16)
            for name, value in m68k["registers"].items()
        }
        fixture_sr = (
            0x2000
            | ((int(m68k["interrupt_mask"]) & 7) << 8)
            | (int(m68k["ccr_xnzvc"]) & 0x1F)
        )
        fixture_dir = args.output / "fixtures"
        fixture_dir.mkdir()
        fixture_work = fixture_dir / "case-00.work.bin"
        fixture_work.write_bytes(work)
        fixture = {
            "name": f"exact-live-tick-{campaign.tick16(m)}",
            "regs": fixture_regs,
            "sr": fixture_sr,
            "tick": campaign.tick16(m),
            "work_sha256": hashlib.sha256(work).hexdigest(),
        }
        fixture_metadata = fixture_dir / "case-00.json"
        fixture_metadata.write_text(
            json.dumps(fixture, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        snapshot = {
            "video_frame": int(m.get_state().get("frameCount", 0)),
            "snes_tick": campaign.tick16(m),
            "halt": campaign.halt16(m),
            "sa1_cpu": cpu,
            "m68k": m68k,
            "player": campaign.player_snapshot(m),
            "task_mask": int.from_bytes(work[2:4], "big"),
            "task_context_hex": work[4:68].hex(),
            "irq_pending": int.from_bytes(iram[0xAA:0xAC], "little"),
            "irq_countdown": int.from_bytes(iram[0xAC:0xAE], "little"),
            "iram_sha256": hashlib.sha256(iram).hexdigest(),
            "work_sha256": hashlib.sha256(work).hexdigest(),
            "object_pointer_list_hex": work[0x0BE2:0x0C02].hex(),
            "a2_record_hex": work[0x3A74:0x3A84].hex(),
            "a3_record_hex": work[0x3A84:0x3A94].hex(),
        }
        # Saving while the self-loop remains installed prevents frame-boundary
        # state serialization from running the native root.  Consumers restore
        # the on-disk ROM bytes and reassert $98:AE00 to flush this diagnostic
        # prefetch before executing.
        state = campaign.save_state(m, args.output / "pre-entry.mss")
        screenshot = campaign.screenshot(m, args.output / "pre-entry.png")
        m.write_memory(
            "snesPrgRom",
            ENTRY_ROM_OFFSET,
            entry_original.hex(),
        )

    result = {
        "scope": (
            "authenticated tick-6619 checkpoint continuation to an exact "
            "pre-instruction production $01E7C0 native entry; entry held in "
            "a temporary ROM self-loop during grouped reads/save; checkpoint "
            "evidence, not fresh-boot proof"
        ),
        "rom": str(args.rom),
        "rom_sha256": sha256(args.rom),
        "prestate": str(args.state),
        "prestate_sha256": sha256(args.state),
        "nexen": str(args.nexen),
        "nexen_sha256": sha256(args.nexen),
        "buttons": args.buttons,
        "load_response": load_response,
        "input_response": input_response,
        "response": response,
        "temporary_entry_stabilizer": {
            "address": f"{ENTRY_NATIVE:06X}",
            "before": entry_original.hex(),
            "temporary": "80fe",
            "architectural_effect_before_capture": "none",
        },
        "saved_state_prefetch_recovery": (
            "restore production ROM and reassert SA-1 PC $98:AE00"
        ),
        "snapshot": snapshot,
        "state": state,
        "screenshot": screenshot,
        "iram_path": str(args.output / "entry.iram.bin"),
        "work_path": str(args.output / "entry.work.bin"),
        "fixture_metadata": str(fixture_metadata),
        "fixture_metadata_sha256": sha256(fixture_metadata),
        "fixture_work": str(fixture_work),
        "fixture_work_sha256": sha256(fixture_work),
    }
    output = args.output / "result.json"
    output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "result": str(output),
                "state": state,
                "snes_tick": snapshot["snes_tick"],
                "halt": snapshot["halt"],
                "pc": f"{physical_pc:06X}",
                "work_sha256": snapshot["work_sha256"],
                "a2_record": snapshot["a2_record_hex"],
                "a3_record": snapshot["a3_record_hex"],
            },
            sort_keys=True,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
