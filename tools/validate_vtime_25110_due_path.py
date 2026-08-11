#!/usr/bin/env python3
"""Exercise the VTIME `$025110` native-deadline unwind at one safe boundary.

This deliberately *synthetic* regression starts from a retained exact native
entry fixture and seeds the isolated diagnostic clock one two-cycle unit before
a deadline. It proves the first native charge reaches the ledger, publishes
block ordinal one, latches the deadline, clears the pending native block, and
reaches ``inext``. It retains the forced pre-failure state. It is not a MAME
timing comparison, fresh boot, gameplay, or rate result; its purpose is to
catch a native ledger keying/deadline defect before any checkpoint investigation
relies on the new diagnostic gateway. The ordinary three-way fixture remains
the stack/CCR proof; Nexen execution-hook callbacks are not exact stack stops.
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
VTIME_BASE = 0x404000
VTIME_MAGIC = 0xC71E
VTIME_CHARGE = 0xF28600
INEXT = 0x00D128

sys.path.insert(0, "/home/chad/Mesen2/python")
sys.path.insert(0, str(ROOT / "tools"))
import mesen_mcp.session as _session  # noqa: E402

_session.validate_mesen_build = lambda *_args, **_kwargs: None
from mesen_mcp import McpSession  # noqa: E402

import replay_mame_controller_campaign as campaign  # noqa: E402


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, required=True)
    parser.add_argument("--prestate", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--nexen", type=Path, default=DEFAULT_NEXEN)
    parser.add_argument("--port", type=int, default=9305)
    args = parser.parse_args()
    for label, path in (("ROM", args.rom), ("prestate", args.prestate), ("Nexen", args.nexen)):
        if not path.is_file():
            parser.error(f"missing {label}: {path}")
    if args.output.exists():
        parser.error(f"output already exists: {args.output}")
    return args


def virtual_pc(m: McpSession) -> int:
    raw = bytes(m.read_memory("Sa1Memory", 0x40, 4))
    return int.from_bytes(raw, "little") & 0xFFFFFF


def timer(m: McpSession) -> dict[str, int]:
    raw = bytes(m.read_memory("snesMemory", VTIME_BASE, 0x1A))
    return {
        name: int.from_bytes(raw[offset : offset + 2], "little")
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
        )
    }


def stack_window(m: McpSession, cpu: dict[str, Any]) -> dict[str, Any]:
    sp = int(cpu["sp"])
    start = max(0, sp - 8)
    return {
        "sp": sp,
        "address": start,
        "hex": bytes(m.read_memory("Sa1Memory", start, 32)).hex(),
    }


def main() -> int:
    args = parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True)
    states = output / "states"
    states.mkdir()
    retained_rom = output / "vtime-rom.sfc"
    shutil.copy2(args.rom, retained_rom)
    os.environ["DOTNET_ROOT"] = "/home/chad/.dotnet10"

    with McpSession(
        rom=retained_rom,
        mesen=args.nexen.resolve(),
        cwd=ROOT,
        port=args.port,
        boot_wait=6.0,
        socket_timeout=120.0,
        stderr_log=output / "emulator.stderr.log",
    ) as m:
        m.pause()
        m.load_state(str(args.prestate.resolve()))
        m.pause()
        # The retained exact entry starts directly at bank $97, bypassing the
        # ordinary fetch gateway.  Seed an explicit, documented diagnostic
        # state: five units of already-prepared JSR cost against one remaining
        # unit must cross before `$025110`'s first original block executes.
        forced = bytearray(0x1A)
        forced[0x00:0x02] = VTIME_MAGIC.to_bytes(2, "little")
        forced[0x02:0x04] = (1).to_bytes(2, "little")
        forced[0x04:0x06] = (5).to_bytes(2, "little")
        forced[0x06:0x08] = (1).to_bytes(2, "little")
        m.write_memory("snesMemory", VTIME_BASE, forced.hex())
        pre_cpu = m.get_cpu_state("Sa1")
        pre_timer = timer(m)
        pre_virtual_pc = virtual_pc(m)
        pre_state = campaign.save_state(m, states / "forced-due-prestate.mss")

        charge_hook = m.add_exec_hook(VTIME_CHARGE, cpu_type="Sa1")
        m.drain_notifications(timeout=0.05)
        try:
            charge_hit = m.run_until(max_frames=4, hook_handle=charge_hook)
            m.pause()
            charge_cpu = m.get_cpu_state("Sa1")
            charge_stack = stack_window(m, charge_cpu)
            charge_timer = timer(m)
        finally:
            m.remove_hook(charge_hook)
            m.drain_notifications(timeout=0.05)
        inext_hook = m.add_exec_hook(INEXT, cpu_type="Sa1")
        m.drain_notifications(timeout=0.05)
        try:
            inext_hit = m.run_until(max_frames=4, hook_handle=inext_hook)
            m.pause()
            inext_cpu = m.get_cpu_state("Sa1")
            inext_timer = timer(m)
            inext_virtual_pc = virtual_pc(m)
        finally:
            m.remove_hook(inext_hook)
            m.drain_notifications(timeout=0.05)
        post_cpu = m.get_cpu_state("Sa1")
        post_timer = timer(m)
        post_virtual_pc = virtual_pc(m)
        post_state = campaign.save_state(m, states / "after-inext.mss")

    checks = {
        "forced_prestate_has_one_unit_remaining": pre_timer["remaining_lo"] == 1 and pre_timer["remaining_hi"] == 0,
        "native_charge_gateway_executed": (charge_hit or {}).get("reason") == "hookFired",
        "unwound_to_inext": (inext_hit or {}).get("reason") == "hookFired",
        "first_block_ordinal_published": charge_timer["current_block"] == 1,
        "deadline_latched_for_retained_irq_path": charge_timer["due"] == 1,
        "native_pending_block_cleared": charge_timer["pending_block"] == 0,
    }
    report: dict[str, Any] = {
        "scope": (
            "synthetic VTIME native-deadline unwind regression from a retained exact $025110 "
            "entry; not MAME equivalence, fresh boot, gameplay, fps, or acceptance"
        ),
        "result": "green" if all(checks.values()) else "red",
        "checks": checks,
        "rom": {"path": str(retained_rom), "sha256": sha256(retained_rom)},
        "prestate_source": {"path": str(args.prestate.resolve()), "sha256": sha256(args.prestate)},
        "runtime_memory_writes": [
            {
                "region": "snesMemory",
                "address": f"{VTIME_BASE:06X}",
                "length": len(forced),
                "purpose": "synthetic one-unit-before-deadline VTIME diagnostic state",
            }
        ],
        "pre": {"sa1": pre_cpu, "timer": pre_timer, "virtual_pc": f"{pre_virtual_pc:06X}", "state": pre_state},
        "charge_hook": {
            "sa1": charge_cpu,
            "stack": charge_stack,
            "timer": charge_timer,
        },
        "inext_hook": {"sa1": inext_cpu, "timer": inext_timer, "virtual_pc": f"{inext_virtual_pc:06X}"},
        "post": {"sa1": post_cpu, "timer": post_timer, "virtual_pc": f"{post_virtual_pc:06X}", "state": post_state},
        "hits": {"charge": charge_hit, "inext": inext_hit},
    }
    report_path = output / "summary.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"result": report["result"], "checks": checks, "summary": str(report_path)}, sort_keys=True))
    return 0 if report["result"] == "green" else 1


if __name__ == "__main__":
    raise SystemExit(main())
