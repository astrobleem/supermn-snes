#!/usr/bin/env python3
"""Synthetic exact-Nexen first-deadline check for the VTIME `$02429C` root.

This seeds one two-cycle unit before a deadline at an exact retained `$02429C`
fixture.  It proves ordinal one publishes original PC `$02429C`, latches the
deadline, clears the native ledger, and unwinds to ``inext``.  It is not MAME,
fresh-boot, gameplay, rate, or production acceptance evidence.
"""

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
    parser.add_argument("--port", type=int, default=9357)
    args = parser.parse_args()
    for path in (args.rom, args.fixtures, args.nat, args.nexen):
        if not path.exists():
            parser.error(f"missing input: {path}")
    if args.output.exists():
        parser.error(f"output exists: {args.output}")

    case = root_validator.load_cases(args.fixtures, 1)[0]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    states = args.output.parent / f"{args.output.stem}-states"
    if states.exists():
        parser.error(f"state directory exists: {states}")
    states.mkdir()

    report: dict[str, object] = {
        "scope": (
            "synthetic exact-Nexen first-block deadline unwind for the opt-in "
            "$02429C root; not MAME, fresh boot, gameplay, rate, or acceptance"
        ),
        "rom": {"path": str(args.rom.resolve()), "sha256": sha256(args.rom)},
        "fixture": case.name,
    }
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
        forced[4:6] = (5).to_bytes(2, "little")
        forced[6:8] = (1).to_bytes(2, "little")
        m.write_memory("snesMemory", VTIME_BASE, forced.hex())
        before = {
            **probe.snapshot(m),
            "timer": timer(m),
            "state": campaign.save_state(m, states / "forced-due-prestate.mss"),
        }

        original = bytes(m.read_memory("snesPrgRom", INEXT_FILE, 2))
        if original == bytes.fromhex("80fe"):
            raise RuntimeError("inext already contains a debugger self-loop")
        try:
            m.write_memory("snesPrgRom", INEXT_FILE, "80fe")
            hit = run_to(m, INEXT, 64)
            after = {
                **probe.snapshot(m),
                "timer": timer(m),
                "state": campaign.save_state(m, states / "after-inext.mss"),
            }
        finally:
            m.write_memory("snesPrgRom", INEXT_FILE, original.hex())

    checks = {
        "forced_one_unit_before_deadline": (
            before["timer"]["remaining_lo"] == 1
            and before["timer"]["remaining_hi"] == 0
        ),
        "unwound_to_inext": hit.get("reason") == "hookFired",
        "resume_pc_is_first_root_block": after["virtual_pc"] == "02429C",
        "deadline_latched": after["timer"]["due"] == 1,
        "first_block_state_cleared": (
            after["timer"]["pending"] == 0
            and after["timer"]["current"] == 0
            and after["timer"]["owner"] == 0
            and after["timer"]["cost"] == 0
        ),
        "clock_remains_valid": after["timer"]["valid"] == 1,
        "native_gate_remains_enabled": after["gate_071a"] == 1,
    }
    report.update({
        "runtime_memory_writes": [
            {"region": "snesMemory", "address": f"{VTIME_BASE:06X}", "length": len(forced)},
            {"region": "snesPrgRom", "address": f"{INEXT_FILE:06X}", "length": 2, "restored": True},
        ],
        "before": before,
        "after": after,
        "hit": hit,
        "checks": checks,
        "result": "green" if all(checks.values()) else "red",
    })
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"result": report["result"], "checks": checks, "summary": str(args.output)}, sort_keys=True))
    return 0 if report["result"] == "green" else 1


if __name__ == "__main__":
    raise SystemExit(main())
