#!/usr/bin/env python3
"""Exercise a forced deadline through the bank-$9F player exit gateway.

This is a deliberately synthetic diagnostic test.  It proves the shared
``vtime_esc9_finish`` path used by the OJMP, interpreter-bridge, and ORS
handoff gateways clears a pending player block, latches a deadline, and
returns to ``inext`` without changing the already-materialized virtual PC.
It does not prove an organic handler reaches any one gateway, MAME
equivalence, gameplay, timing rate, or production acceptance.
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
DEFAULT_NEXEN = Path(
    "/mnt/sdc1/Nexen-r5-20260712/"
    "bin/linux-x64/Release/mcp-safe-checkpoint-publish/Nexen"
)
DEFAULT_FIXTURES = (
    ROOT / "build/playtest-investigation-20260725/"
    "stage3-13282-fixtures-f05b0f3-v1"
)
DEFAULT_NAT = Path("/tmp/b0_native.mss")
VTIME_BASE = 0x404000
VTIME_MAGIC = 0xC71E
OJMP_GATEWAY = 0x9FFFBB
INEXT = 0x00D128
INEXT_FILE_OFFSET = INEXT - 0x8000
PLAYER_TARGET = 0x013282

sys.path.insert(0, "/home/chad/Mesen2/python")
sys.path.insert(0, str(ROOT / "tools"))
import mesen_mcp.session as _session  # noqa: E402

_session.validate_mesen_build = lambda *_args, **_kwargs: None
from mesen_mcp import McpSession  # noqa: E402

import replay_mame_controller_campaign as campaign  # noqa: E402
import validate_1f2e4_native as live  # noqa: E402
import validate_stage3_hot_handlers as hot  # noqa: E402


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def virtual_pc(m: McpSession) -> int:
    return int.from_bytes(bytes(m.read_memory("Sa1Memory", 0x40, 4)), "little") & 0xFFFFFF


def timer(m: McpSession) -> dict[str, int]:
    raw = bytes(m.read_memory("snesMemory", VTIME_BASE, 0x1C))
    return {
        name: int.from_bytes(raw[offset:offset + 2], "little")
        for name, offset in (
            ("magic", 0x00), ("valid", 0x02), ("cost", 0x04),
            ("remaining_lo", 0x06), ("remaining_hi", 0x08),
            ("phase", 0x0A), ("overshoot", 0x0C),
            ("pending_block", 0x14), ("current_block", 0x16),
            ("due", 0x18), ("native_owner", 0x1A),
        )
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--fixtures", type=Path, default=DEFAULT_FIXTURES)
    parser.add_argument("--nat", type=Path, default=DEFAULT_NAT)
    parser.add_argument("--nexen", type=Path, default=DEFAULT_NEXEN)
    parser.add_argument("--port", type=int, default=9310)
    args = parser.parse_args()
    for label, path in (("ROM", args.rom), ("fixtures", args.fixtures),
                        ("native base state", args.nat), ("Nexen", args.nexen)):
        if not path.exists():
            parser.error(f"missing {label}: {path}")
    if args.output.exists():
        parser.error(f"output already exists: {args.output}")
    return args


def main() -> int:
    args = parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True)
    states = output / "states"
    states.mkdir()
    os.environ["DOTNET_ROOT"] = "/home/chad/.dotnet10"
    fixtures = hot.load_fixtures(args.fixtures.resolve(), {PLAYER_TARGET}, 1)
    if len(fixtures) != 1:
        raise RuntimeError("expected one retained $013282 fixture")
    retained_rom = output / "vtime-rom.sfc"
    shutil.copy2(args.rom, retained_rom)

    with McpSession(
        rom=retained_rom, mesen=args.nexen.resolve(), cwd=ROOT,
        port=args.port, boot_wait=6.0, socket_timeout=120.0,
        stderr_log=output / "emulator.stderr.log",
    ) as m:
        # A valid native stack/register image makes this direct gateway test
        # use the same SA-1 environment as the real $013282 route, while the
        # forced PC below intentionally bypasses organic path selection.
        hot.prepare_console(m, args.nat.resolve(), fixtures[0], 1)
        forced = bytearray(0x1C)
        forced[0:2] = VTIME_MAGIC.to_bytes(2, "little")
        forced[2:4] = (1).to_bytes(2, "little")
        forced[6:8] = (1).to_bytes(2, "little")
        forced[0x14:0x16] = (1).to_bytes(2, "little")
        forced[0x16:0x18] = (1).to_bytes(2, "little")
        forced[0x1A:0x1C] = (9).to_bytes(2, "little")
        m.write_memory("snesMemory", VTIME_BASE, forced.hex())
        before = {
            "timer": timer(m),
            "virtual_pc": f"{virtual_pc(m):06X}",
            "sa1": m.get_cpu_state("Sa1"),
            "state": campaign.save_state(m, states / "forced-finish-prestate.mss"),
        }
        original_inext = bytes(m.read_memory("snesPrgRom", INEXT_FILE_OFFSET, 2))
        if original_inext == bytes.fromhex("80fe"):
            raise RuntimeError("inext already contains a debugger self-loop")
        m.write_memory("snesPrgRom", INEXT_FILE_OFFSET, "80fe")
        inext_hook = m.add_exec_hook(INEXT, cpu_type="Sa1")
        m.drain_notifications(timeout=0.05)
        try:
            live.set_sa1_pc(m, OJMP_GATEWAY)
            inext_hit = m.run_until(max_frames=8, hook_handle=inext_hook)
            m.pause()
            after = {
                "timer": timer(m),
                "virtual_pc": f"{virtual_pc(m):06X}",
                "sa1": m.get_cpu_state("Sa1"),
            }
        finally:
            m.remove_hook(inext_hook)
            m.write_memory("snesPrgRom", INEXT_FILE_OFFSET, original_inext.hex())
            m.drain_notifications(timeout=0.05)
        after["state"] = campaign.save_state(m, states / "after-inext.mss")

    checks = {
        "forced_prestate_has_pending_player_block": (
            before["timer"]["native_owner"] == 9
            and before["timer"]["pending_block"] == 1
        ),
        "forced_prestate_has_one_unit_remaining": (
            before["timer"]["remaining_lo"] == 1
            and before["timer"]["remaining_hi"] == 0
        ),
        "unwound_to_inext": (inext_hit or {}).get("reason") == "hookFired",
        "deadline_latched": after["timer"]["due"] == 1,
        "pending_player_block_cleared": after["timer"]["pending_block"] == 0,
        "player_owner_retained_until_irq": after["timer"]["native_owner"] == 9,
        "post_handoff_virtual_pc_preserved": after["virtual_pc"] == before["virtual_pc"],
    }
    report: dict[str, Any] = {
        "scope": (
            "synthetic forced-deadline check through the pack-injected "
            "bank-$9F OJMP handoff gateway; proves only diagnostic finish/"
            "unwind behavior, not organic reachability, MAME equivalence, "
            "fresh boot, gameplay, rate, or acceptance."
        ),
        "result": "green" if all(checks.values()) else "red",
        "checks": checks,
        "rom": {"path": str(retained_rom), "sha256": sha256(retained_rom)},
        "fixture": str(fixtures[0].metadata_path),
        "gateway": f"{OJMP_GATEWAY:06X}",
        "runtime_memory_writes": [
            {"region": "snesMemory", "address": f"{VTIME_BASE:06X}",
             "length": len(forced), "purpose": "synthetic pending player block one unit before deadline"},
            {"region": "snesPrgRom", "address": f"{INEXT_FILE_OFFSET:06X}",
             "length": 2, "purpose": "temporary exact-inext debugger self-loop, restored before after-state save"},
        ],
        "before": before,
        "after_inext": {"response": inext_hit, **after},
    }
    path = output / "summary.json"
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"result": report["result"], "checks": checks, "summary": str(path)}, sort_keys=True))
    return 0 if report["result"] == "green" else 1


if __name__ == "__main__":
    raise SystemExit(main())
