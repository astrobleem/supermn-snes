#!/usr/bin/env python3
"""Synthetic execution test for the unwired VTIME native/interpreter flush."""

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
DEFAULT_NEXEN = Path("/mnt/sdc1/Nexen-r5-20260712/bin/linux-x64/Release/mcp-safe-checkpoint-publish/Nexen")
DEFAULT_FIXTURES = ROOT / "build/playtest-investigation-20260725/stage3-13282-fixtures-f05b0f3-v1"
DEFAULT_NAT = Path("/tmp/b0_native.mss")
VTIME_BASE = 0x404000
VTIME_MAGIC = 0xC71E
HANDOFF = 0xF2FE40
HANDOFF_NONE = 0xF2FE89
INEXT = 0x00D128
OWNER_25110 = 3
OWNER_PLAYER = 9

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
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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


def forced_timer(owner: int) -> bytes:
    value = bytearray(0x1C)
    value[0x00:0x02] = VTIME_MAGIC.to_bytes(2, "little")
    value[0x02:0x04] = (1).to_bytes(2, "little")
    # Far from deadline: this verifies exactly the flush/owner behavior.
    value[0x06:0x08] = (0x7FFF).to_bytes(2, "little")
    value[0x14:0x16] = (1).to_bytes(2, "little")
    value[0x16:0x18] = (1).to_bytes(2, "little")
    value[0x1A:0x1C] = owner.to_bytes(2, "little")
    return bytes(value)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--fixtures", type=Path, default=DEFAULT_FIXTURES)
    parser.add_argument("--nat", type=Path, default=DEFAULT_NAT)
    parser.add_argument("--nexen", type=Path, default=DEFAULT_NEXEN)
    parser.add_argument("--port", type=int, default=9348)
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


def normal_row(m: McpSession, nat: Path, fixture: Any, name: str, owner: int, states: Path) -> dict[str, Any]:
    hot.prepare_console(m, nat, fixture, 1)
    m.write_memory("snesMemory", VTIME_BASE, forced_timer(owner).hex())
    before = timer(m)
    prestate = campaign.save_state(m, states / f"{name}-prestate.mss")
    hook = m.add_exec_hook(HANDOFF_NONE, cpu_type="Sa1")
    m.drain_notifications(timeout=0.05)
    try:
        live.set_sa1_pc(m, HANDOFF)
        hit = m.run_until(max_frames=8, hook_handle=hook)
        m.pause()
        after = timer(m)
        cpu = m.get_cpu_state("Sa1")
    finally:
        m.remove_hook(hook)
        m.drain_notifications(timeout=0.05)
    return {"name": name, "owner": owner, "prestate": prestate, "hit": hit, "before": before, "after": after, "sa1": cpu}


def unknown_row(m: McpSession, nat: Path, fixture: Any, states: Path) -> dict[str, Any]:
    owner = 0x00A5
    hot.prepare_console(m, nat, fixture, 1)
    m.write_memory("snesMemory", VTIME_BASE, forced_timer(owner).hex())
    before = timer(m)
    prestate = campaign.save_state(m, states / "unknown-owner-prestate.mss")
    cpu_before = m.get_cpu_state("Sa1")
    stack_address = (int(cpu_before["sp"]) + 1) & 0xFFFF
    stack_return = bytes((INEXT & 0xFF, INEXT >> 8, 0x00))
    m.write_memory("Sa1Memory", stack_address, stack_return.hex())
    hook = m.add_exec_hook(INEXT, cpu_type="Sa1")
    m.drain_notifications(timeout=0.05)
    try:
        live.set_sa1_pc(m, HANDOFF)
        hit = m.run_until(max_frames=8, hook_handle=hook)
        m.pause()
        after = timer(m)
        cpu = m.get_cpu_state("Sa1")
    finally:
        m.remove_hook(hook)
        m.drain_notifications(timeout=0.05)
    return {
        "name": "unknown_owner", "owner": owner, "prestate": prestate,
        "hit": hit, "before": before, "after": after, "sa1": cpu,
        "temporary_stack_return": {"address": f"{stack_address:04X}", "bytes": stack_return.hex()},
    }


def valid_normal(row: dict[str, Any]) -> bool:
    before, after = row["before"], row["after"]
    return (
        row["hit"].get("reason") == "hookFired"
        and before["valid"] == 1
        and before["pending_block"] == before["current_block"] == 1
        and after["valid"] == 1 and after["due"] == 0
        and after["pending_block"] == after["current_block"] == after["native_owner"] == 0
        and after["remaining_lo"] < before["remaining_lo"]
    )


def main() -> int:
    args = parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True)
    states = output / "states"
    states.mkdir()
    retained_rom = output / "vtime-rom.sfc"
    shutil.copy2(args.rom, retained_rom)
    os.environ["DOTNET_ROOT"] = "/home/chad/.dotnet10"
    fixtures = hot.load_fixtures(args.fixtures.resolve(), {0x013282}, 1)
    if len(fixtures) != 1:
        raise RuntimeError("expected exactly one retained Stage-3 player fixture")
    with McpSession(
        rom=retained_rom, mesen=args.nexen.resolve(), cwd=ROOT,
        port=args.port, boot_wait=6.0, socket_timeout=120.0,
        stderr_log=output / "emulator.stderr.log",
    ) as m:
        rows = [
            normal_row(m, args.nat.resolve(), fixtures[0], "owner_25110", OWNER_25110, states),
            normal_row(m, args.nat.resolve(), fixtures[0], "owner_player", OWNER_PLAYER, states),
            unknown_row(m, args.nat.resolve(), fixtures[0], states),
        ]
    owner_25110, owner_player, unknown = rows
    checks = {
        "25110_owner_flushes_one_deferred_block": valid_normal(owner_25110),
        "player_owner_flushes_one_deferred_block": valid_normal(owner_player),
        "unknown_owner_reaches_interpreter_return": unknown["hit"].get("reason") == "hookFired",
        "unknown_owner_invalidates_vtime": unknown["after"]["valid"] == 0,
        "unknown_owner_retains_tag_for_fail_closed_diagnosis": unknown["after"]["native_owner"] == unknown["owner"],
    }
    report = {
        "scope": "synthetic direct VTIME handoff helper test; not organic reachability, MAME equivalence, IRQ, gameplay, rate, or acceptance",
        "result": "green" if all(checks.values()) else "red",
        "checks": checks,
        "rom": {"path": str(retained_rom), "sha256": sha256(retained_rom)},
        "helper": {"entry": f"{HANDOFF:06X}", "no_deadline_stop": f"{HANDOFF_NONE:06X}"},
        "fixture": str(fixtures[0].metadata_path),
        "runtime_memory_writes": [
            {"region": "snesMemory", "address": f"{VTIME_BASE:06X}", "length": 0x1C, "purpose": "synthetic deferred native block"},
            {"region": "Sa1Memory", "purpose": "unknown-owner-only temporary RTL target"},
        ],
        "rows": rows,
    }
    summary = output / "summary.json"
    summary.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"result": report["result"], "checks": checks, "summary": str(summary)}, sort_keys=True))
    return 0 if report["result"] == "green" else 1


if __name__ == "__main__":
    raise SystemExit(main())
