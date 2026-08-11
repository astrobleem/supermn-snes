#!/usr/bin/env python3
"""Exercise one forced deadline at a real Stage-3 player BSR boundary.

This is a synthetic diagnostic guard for the opt-in VTIME bank-$9F player
ledger.  It starts at the authentic $0126EA BSR that reaches $013282, retains
the prepared pre-failure state, and seeds one two-cycle unit before a virtual
deadline.  It proves the patched player charge finds its sparse-table entry,
unwinds its PHP/JSR frames, and resumes the interpreter at the first original
player block.  It is neither a MAME comparison nor a gameplay/rate acceptance.
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
    ROOT
    / "build/playtest-investigation-20260725/"
    "stage3-13282-fixtures-f05b0f3-v1"
)
DEFAULT_NAT = Path("/tmp/b0_native.mss")
VTIME_BASE = 0x404000
VTIME_MAGIC = 0xC71E
VTIME_CHARGE = 0xF2B100
VTIME_CHARGE_FILE_OFFSET = 0x32B100
INEXT = 0x00D128
INEXT_FILE_OFFSET = INEXT - 0x8000
PLAYER_TARGET = 0x013282
PLAYER_BSR = 0x0126EA

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
            ("magic", 0x00),
            ("valid", 0x02),
            ("cost", 0x04),
            ("remaining_lo", 0x06),
            ("remaining_hi", 0x08),
            ("phase", 0x0A),
            ("overshoot", 0x0C),
            ("pending_block", 0x14),
            ("current_block", 0x16),
            ("due", 0x18),
            ("native_owner", 0x1A),
        )
    }


def stack_window(m: McpSession, cpu: dict[str, Any]) -> dict[str, Any]:
    sp = int(cpu["sp"])
    return {
        "sp": sp,
        "address": sp,
        "hex": bytes(m.read_memory("Sa1Memory", sp, 24)).hex(),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--fixtures", type=Path, default=DEFAULT_FIXTURES)
    parser.add_argument("--nat", type=Path, default=DEFAULT_NAT)
    parser.add_argument("--nexen", type=Path, default=DEFAULT_NEXEN)
    parser.add_argument("--port", type=int, default=9308)
    args = parser.parse_args()
    for label, path in (
        ("ROM", args.rom),
        ("fixtures", args.fixtures),
        ("native base state", args.nat),
        ("Nexen", args.nexen),
    ):
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
    fixture = fixtures[0]
    pre_bsr = replace(
        fixture,
        name=fixture.name + "-vtime-pre-bsr",
        target=PLAYER_BSR,
        regs={**fixture.regs, "A7": (fixture.regs["A7"] + 4) & 0xFFFFFFFF},
    )
    retained_rom = output / "vtime-rom.sfc"
    shutil.copy2(args.rom, retained_rom)

    with McpSession(
        rom=retained_rom,
        mesen=args.nexen.resolve(),
        cwd=ROOT,
        port=args.port,
        boot_wait=6.0,
        socket_timeout=120.0,
        stderr_log=output / "emulator.stderr.log",
    ) as m:
        hot.prepare_console(m, args.nat.resolve(), pre_bsr, 1)
        live.set_sa1_pc(m, INEXT)
        original_charge = bytes(
            m.read_memory("snesPrgRom", VTIME_CHARGE_FILE_OFFSET, 2)
        )
        if original_charge != bytes.fromhex("c230"):
            raise RuntimeError(
                "VTIME player charge entry changed: expected c230, found "
                + original_charge.hex()
            )
        # Nexen's ordinary hook callback can arrive after the first F2
        # instructions have run.  A temporary self-loop gives this synthetic
        # guard an exact stack image at the cross-bank charge ABI, then the
        # original bytes are restored before the ledger executes.
        m.write_memory("snesPrgRom", VTIME_CHARGE_FILE_OFFSET, "80fe")
        charge_hook = m.add_exec_hook(VTIME_CHARGE, cpu_type="Sa1")
        m.drain_notifications(timeout=0.05)
        try:
            charge_hit = m.run_until(max_frames=8, hook_handle=charge_hook)
            m.pause()
            charge_cpu = m.get_cpu_state("Sa1")
            at_charge = {
                "timer": timer(m),
                "virtual_pc": f"{virtual_pc(m):06X}",
                "sa1": charge_cpu,
                "stack": stack_window(m, charge_cpu),
            }
        finally:
            m.remove_hook(charge_hook)
            # The fetch gateway computes the BSR's normal cost on its way to
            # this seam, so install the synthetic one-unit-before-deadline
            # state only after that fetch and before F2 executes the player
            # ledger.  Restore the diagnostic instruction first so the saved
            # pre-failure state is a real resumable ROM boundary, not a
            # debugger self-loop.
            forced = bytearray(0x1C)
            forced[0x00:0x02] = VTIME_MAGIC.to_bytes(2, "little")
            forced[0x02:0x04] = (1).to_bytes(2, "little")
            forced[0x04:0x06] = (5).to_bytes(2, "little")
            forced[0x06:0x08] = (1).to_bytes(2, "little")
            m.write_memory("snesMemory", VTIME_BASE, forced.hex())
            m.write_memory(
                "snesPrgRom", VTIME_CHARGE_FILE_OFFSET, original_charge.hex()
            )
            m.drain_notifications(timeout=0.05)
        pre = {
            "timer": timer(m),
            "virtual_pc": f"{virtual_pc(m):06X}",
            "sa1": m.get_cpu_state("Sa1"),
            "state": campaign.save_state(
                m, states / "forced-due-prestate.mss"
            ),
        }
        original_inext = bytes(
            m.read_memory("snesPrgRom", INEXT_FILE_OFFSET, 2)
        )
        if original_inext == bytes.fromhex("80fe"):
            raise RuntimeError("inext already contains a debugger self-loop")
        # Stop exactly at inext.  Without this temporary loop Nexen can run
        # through the retained deadline consumer/reload before the execution
        # hook acknowledgement arrives, hiding the due/owner state this guard
        # is intended to prove.
        m.write_memory("snesPrgRom", INEXT_FILE_OFFSET, "80fe")
        inext_hook = m.add_exec_hook(INEXT, cpu_type="Sa1")
        m.drain_notifications(timeout=0.05)
        try:
            inext_hit = m.run_until(max_frames=8, hook_handle=inext_hook)
            m.pause()
            after = {
                "timer": timer(m),
                "virtual_pc": f"{virtual_pc(m):06X}",
                "sa1": m.get_cpu_state("Sa1"),
                "state": campaign.save_state(m, states / "after-inext.mss"),
            }
        finally:
            m.remove_hook(inext_hook)
            m.write_memory(
                "snesPrgRom", INEXT_FILE_OFFSET, original_inext.hex()
            )
            m.drain_notifications(timeout=0.05)

    checks = {
        "forced_prestate_has_one_unit_remaining": (
            pre["timer"]["remaining_lo"] == 1
            and pre["timer"]["remaining_hi"] == 0
        ),
        "native_player_charge_gateway_executed": (
            (charge_hit or {}).get("reason") == "hookFired"
        ),
        "unwound_to_inext": (inext_hit or {}).get("reason") == "hookFired",
        "first_player_block_published": after["timer"]["current_block"] == 1,
        "player_ledger_owner_retained_until_irq": after["timer"]["native_owner"] == 9,
        "deadline_latched": after["timer"]["due"] == 1,
        "pending_player_block_cleared": after["timer"]["pending_block"] == 0,
        "resume_pc_is_first_player_block": after["virtual_pc"] == "013282",
    }
    report: dict[str, Any] = {
        "scope": (
            "synthetic forced-deadline check at the real $0126EA BSR into "
            "$013282; proves only the diagnostic bank-$9F ledger/unwind. "
            "Not MAME equivalence, fresh boot, gameplay, rate, or acceptance."
        ),
        "result": "green" if all(checks.values()) else "red",
        "checks": checks,
        "rom": {"path": str(retained_rom), "sha256": sha256(retained_rom)},
        "fixture": {
            "metadata": str(fixture.metadata_path),
            "target": f"{fixture.target:06X}",
            "pre_bsr": f"{PLAYER_BSR:06X}",
        },
        "runtime_memory_writes": [
            {
                "region": "snesMemory",
                "address": f"{VTIME_BASE:06X}",
                "length": len(forced),
                "purpose": "synthetic one-unit-before-deadline VTIME state",
            },
            {
                "region": "snesPrgRom",
                "address": f"{INEXT_FILE_OFFSET:06X}",
                "length": 2,
                "purpose": "temporary exact-inext debugger self-loop, restored before save",
            },
        ],
        "pre": pre,
        "charge_hook": {"response": charge_hit, **at_charge},
        "after_inext": {"response": inext_hit, **after},
    }
    path = output / "summary.json"
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"result": report["result"], "checks": checks, "summary": str(path)}, sort_keys=True))
    return 0 if report["result"] == "green" else 1


if __name__ == "__main__":
    raise SystemExit(main())
