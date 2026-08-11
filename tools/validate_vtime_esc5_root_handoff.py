#!/usr/bin/env python3
"""Exact Nexen check of one F3 `$02429C` interpreted-child handoff."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
os.environ["DOTNET_ROOT"] = "/home/chad/.dotnet10"
sys.path.insert(0, str(ROOT / "tools"))

import probe_vtime_esc5_child_route as probe  # noqa: E402
import replay_mame_controller_campaign as campaign  # noqa: E402
import validate_2429c_native as root_validator  # noqa: E402


VTIME_BASE = 0x404000
VTIME_MAGIC = 0xC71E
INEXT = 0x00D128
INEXT_FILE = INEXT - 0x8000


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def timer(m: probe.common.base.McpSession) -> dict[str, int]:
    raw = bytes(m.read_memory("snesMemory", VTIME_BASE, 0x1C))
    return {
        name: int.from_bytes(raw[offset:offset + 2], "little")
        for name, offset in (
            ("magic", 0x00), ("valid", 0x02), ("cost", 0x04),
            ("remaining_lo", 0x06), ("remaining_hi", 0x08),
            ("pending", 0x14), ("current", 0x16), ("due", 0x18),
            ("owner", 0x1A),
        )
    }


def run_to(m: probe.common.base.McpSession, pc: int, frames: int) -> dict:
    hook = m.add_exec_hook(pc, cpu_type="Sa1")
    m.drain_notifications(timeout=0.05)
    try:
        response = m.run_until(max_frames=frames, hook_handle=hook)
        m.pause()
        return response
    finally:
        m.remove_hook(hook)
        m.drain_notifications(timeout=0.05)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, required=True)
    parser.add_argument("--fixtures", type=Path, required=True)
    parser.add_argument("--nat", type=Path, default=Path("/tmp/b0_native.mss"))
    parser.add_argument("--nexen", type=Path, default=probe.common.base.DEFAULT_NEXEN)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--port", type=int, default=9356)
    args = parser.parse_args()
    for path in (args.rom, args.fixtures, args.nat, args.nexen):
        if not path.exists():
            parser.error(f"missing input: {path}")
    if args.output.exists():
        parser.error(f"output exists: {args.output}")

    case = root_validator.load_cases(args.fixtures, 1)[0]
    syms = ROOT / "src/vtime_esc5_root.sym"
    continuation = probe.symbol(syms, "br2429c_1")
    continuation_file = 0x338000 + continuation - 0x8000
    rows: dict[str, object] = {
        "scope": (
            "one synthetic exact-Nexen F3 parent flush, interpreted-child "
            "entry, genuine-return dispatch, and gate restoration; not MAME, "
            "fresh boot, gameplay, rate, or production acceptance"
        ),
        "rom": {"path": str(args.rom.resolve()), "sha256": sha256(args.rom)},
        "fixture": case.name,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    states = args.output.parent / f"{args.output.stem}-states"
    if states.exists():
        parser.error(f"state directory exists: {states}")
    states.mkdir()

    with probe.common.base.McpSession(
        rom=str(args.rom.resolve()),
        mesen=str(args.nexen.resolve()),
        cwd=ROOT,
        port=args.port,
        boot_wait=6.0,
        socket_timeout=120.0,
        stderr_log=args.output.with_suffix(".stderr.log"),
    ) as m:
        probe.prepare(m, args.nat.resolve(), case)
        forced = bytearray(0x1C)
        forced[0:2] = VTIME_MAGIC.to_bytes(2, "little")
        forced[2:4] = (1).to_bytes(2, "little")
        forced[6:8] = (0xFFFF).to_bytes(2, "little")
        forced[8:10] = (1).to_bytes(2, "little")
        m.write_memory("snesMemory", VTIME_BASE, forced.hex())

        inext_original = bytes(m.read_memory("snesPrgRom", INEXT_FILE, 2))
        continuation_original = bytes(
            m.read_memory("snesPrgRom", continuation_file, 2)
        )
        try:
            m.write_memory("snesPrgRom", INEXT_FILE, "80fe")
            first_hit = run_to(m, INEXT, 64)
            first = {**probe.snapshot(m), "timer": timer(m), "response": first_hit}
            first["state"] = campaign.save_state(m, states / "child-entry.mss")

            m.write_memory("snesPrgRom", INEXT_FILE, inext_original.hex())
            m.write_memory("snesPrgRom", continuation_file, "80fe")
            probe.common.base.set_sa1_pc(m, INEXT)
            return_hit = run_to(m, 0xF30000 | continuation, 1000)
            returned = {
                **probe.snapshot(m),
                "timer": timer(m),
                "response": return_hit,
            }
            a7 = int(str(returned["a7"]), 16)
            returned["return_residue_below_a7"] = bytes(
                m.read_memory("snesMemory", 0x400000 + ((a7 - 4) & 0xFFFF), 4)
            ).hex()
            returned["state"] = campaign.save_state(m, states / "parent-return.mss")
        finally:
            m.write_memory("snesPrgRom", INEXT_FILE, inext_original.hex())
            m.write_memory(
                "snesPrgRom", continuation_file, continuation_original.hex()
            )

    checks = {
        "first_handoff_reached_inext": first_hit.get("reason") == "hookFired",
        "child_pc_is_023342": first["virtual_pc"] == "023342",
        "genuine_0242ac_on_stack": str(first["stack_top"]).startswith("000242ac"),
        "parent_ledger_flushed_and_cleared": (
            first["timer"]["pending"] == 0
            and first["timer"]["current"] == 0
            and first["timer"]["owner"] == 0
            and first["timer"]["valid"] == 1
            and first["timer"]["due"] == 0
        ),
        "child_native_gate_is_off": first["gate_071a"] == 0,
        "return_reached_f3_continuation": return_hit.get("reason") == "hookFired",
        "return_restored_native_gate": returned["gate_071a"] == 1,
        "return_restored_entry_a7": returned["a7"] == f"{case.regs['A7']:08X}",
        "return_residue_is_exact_0242ac": returned["return_residue_below_a7"] == "000242ac",
    }
    rows.update({
        "runtime_memory_writes": [
            {"region": "snesMemory", "address": f"{VTIME_BASE:06X}", "length": len(forced)},
            {"region": "snesPrgRom", "address": f"{INEXT_FILE:06X}", "length": 2, "restored": True},
            {"region": "snesPrgRom", "address": f"{continuation_file:06X}", "length": 2, "restored": True},
        ],
        "first_handoff": first,
        "parent_return": returned,
        "checks": checks,
        "result": "green" if all(checks.values()) else "red",
    })
    args.output.write_text(json.dumps(rows, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"result": rows["result"], "checks": checks, "summary": str(args.output)}, sort_keys=True))
    return 0 if rows["result"] == "green" else 1


if __name__ == "__main__":
    raise SystemExit(main())
