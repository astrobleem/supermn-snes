#!/usr/bin/env python3
"""Force a deadline at an audited Stage-3 player logical-JSR handoff.

This synthetic VTIME regression complements the first-block unwind fixture.
It reaches the real $013282 generated call-out, stops at the pack-injected
bank-$9F OJMP handoff, retains that pre-failure state, then forces the pending
player block across a deadline.  The required outcome is an inext unwind with
the source-prepared callee PC intact.  It is not a MAME/gameplay/rate proof.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
from dataclasses import replace
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
PLAYER_TARGET = 0x013282
PLAYER_BSR = 0x0126EA
OJMP_HANDOFF = 0x9FFFBB
OJMP_HANDOFF_FILE_OFFSET = 0x2FFFBB
INEXT = 0x00D128
INEXT_FILE_OFFSET = INEXT - 0x8000

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
    parser.add_argument("--port", type=int, default=9309)
    parser.add_argument("--case-index", type=int, default=0)
    args = parser.parse_args()
    for label, path in (("ROM", args.rom), ("fixtures", args.fixtures),
                        ("native base state", args.nat), ("Nexen", args.nexen)):
        if not path.exists():
            parser.error(f"missing {label}: {path}")
    if args.output.exists():
        parser.error(f"output already exists: {args.output}")
    if args.case_index < 0:
        parser.error("--case-index must be non-negative")
    return args


def patch_loop(m: McpSession, offset: int, expected: bytes | None = None) -> bytes:
    original = bytes(m.read_memory("snesPrgRom", offset, 2))
    if expected is not None and original != expected:
        raise RuntimeError(
            f"diagnostic seam ${offset:06X} changed: expected {expected.hex()}, got {original.hex()}"
        )
    if original == bytes.fromhex("80fe"):
        raise RuntimeError(f"diagnostic seam ${offset:06X} is already a self-loop")
    m.write_memory("snesPrgRom", offset, "80fe")
    return original


def main() -> int:
    args = parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True)
    states = output / "states"
    states.mkdir()
    os.environ["DOTNET_ROOT"] = "/home/chad/.dotnet10"
    fixtures = hot.load_fixtures(args.fixtures.resolve(), {PLAYER_TARGET}, None)
    if args.case_index >= len(fixtures):
        raise RuntimeError(
            f"--case-index {args.case_index} outside {len(fixtures)} retained $013282 fixtures"
        )
    fixture = fixtures[args.case_index]
    pre_bsr = replace(
        fixture,
        name=fixture.name + "-vtime-handoff-pre-bsr",
        target=PLAYER_BSR,
        regs={**fixture.regs, "A7": (fixture.regs["A7"] + 4) & 0xFFFFFFFF},
    )
    retained_rom = output / "vtime-rom.sfc"
    shutil.copy2(args.rom, retained_rom)

    with McpSession(
        rom=retained_rom, mesen=args.nexen.resolve(), cwd=ROOT,
        port=args.port, boot_wait=6.0, socket_timeout=120.0,
        stderr_log=output / "emulator.stderr.log",
    ) as m:
        hot.prepare_console(m, args.nat.resolve(), pre_bsr, 1)
        armed = bytearray(0x1C)
        armed[0:2] = VTIME_MAGIC.to_bytes(2, "little")
        armed[2:4] = (1).to_bytes(2, "little")
        armed[6:8] = (0xFFFF).to_bytes(2, "little")
        armed[8:10] = (0xFFFF).to_bytes(2, "little")
        m.write_memory("snesMemory", VTIME_BASE, armed.hex())
        live.set_sa1_pc(m, INEXT)
        original_handoff = patch_loop(
            m, OJMP_HANDOFF_FILE_OFFSET, bytes.fromhex("c230")
        )
        handoff_hook = m.add_exec_hook(OJMP_HANDOFF, cpu_type="Sa1")
        m.drain_notifications(timeout=0.05)
        try:
            handoff_hit = m.run_until(max_frames=8, hook_handle=handoff_hook)
            m.pause()
            arrival = {
                "timer": timer(m),
                "virtual_pc": f"{virtual_pc(m):06X}",
                "sa1": m.get_cpu_state("Sa1"),
            }
        finally:
            m.remove_hook(handoff_hook)
            m.write_memory(
                "snesPrgRom", OJMP_HANDOFF_FILE_OFFSET, original_handoff.hex()
            )
            m.drain_notifications(timeout=0.05)
        # The prior player block is pending at this exact source-prepared
        # callee boundary.  Leave all other state intact and make that commit
        # cross a deadline.
        m.write_memory("snesMemory", VTIME_BASE + 0x06, "01000000")
        pre = {
            "timer": timer(m),
            "virtual_pc": f"{virtual_pc(m):06X}",
            "sa1": m.get_cpu_state("Sa1"),
            "state": campaign.save_state(m, states / "forced-handoff-prestate.mss"),
        }
        original_inext = patch_loop(m, INEXT_FILE_OFFSET)
        inext_hook = m.add_exec_hook(INEXT, cpu_type="Sa1")
        m.drain_notifications(timeout=0.05)
        try:
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
        "real_player_handoff_reached": (handoff_hit or {}).get("reason") == "hookFired",
        "arrival_has_pending_player_block": (
            arrival["timer"]["native_owner"] == 9
            and arrival["timer"]["pending_block"] > 0
        ),
        "forced_handoff_has_one_unit_remaining": (
            pre["timer"]["remaining_lo"] == 1 and pre["timer"]["remaining_hi"] == 0
        ),
        "unwound_to_inext": (inext_hit or {}).get("reason") == "hookFired",
        "deadline_latched": after["timer"]["due"] == 1,
        "pending_player_block_cleared": after["timer"]["pending_block"] == 0,
        "player_owner_retained_until_irq": after["timer"]["native_owner"] == 9,
        "post_jsr_callee_pc_preserved": after["virtual_pc"] == pre["virtual_pc"],
    }
    report: dict[str, Any] = {
        "scope": (
            "synthetic forced-deadline check at a real $013282 logical-JSR "
            "OJMP handoff; proves only diagnostic player-ledger flush/unwind, "
            "not MAME equivalence, fresh boot, gameplay, rate, or acceptance."
        ),
        "result": "green" if all(checks.values()) else "red",
        "checks": checks,
        "rom": {"path": str(retained_rom), "sha256": sha256(retained_rom)},
        "fixture": {
            "metadata": str(fixture.metadata_path),
            "case_index": args.case_index,
            "pre_bsr": f"{PLAYER_BSR:06X}",
        },
        "runtime_memory_writes": [
            {"region": "snesMemory", "address": f"{VTIME_BASE:06X}",
             "length": len(armed), "purpose": "synthetic no-deadline player-ledger arm"},
            {"region": "snesMemory", "address": f"{VTIME_BASE + 6:06X}",
             "length": 4, "purpose": "synthetic one-unit-before-handoff deadline"},
            {"region": "snesPrgRom", "address": f"{OJMP_HANDOFF_FILE_OFFSET:06X}",
             "length": 2, "purpose": "temporary exact-handoff self-loop, restored before save"},
            {"region": "snesPrgRom", "address": f"{INEXT_FILE_OFFSET:06X}",
             "length": 2, "purpose": "temporary exact-inext self-loop, restored before save"},
        ],
        "arrival_at_handoff": {"response": handoff_hit, **arrival},
        "pre": pre,
        "after_inext": {"response": inext_hit, **after},
    }
    path = output / "summary.json"
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"result": report["result"], "checks": checks, "summary": str(path)}, sort_keys=True))
    return 0 if report["result"] == "green" else 1


if __name__ == "__main__":
    raise SystemExit(main())
