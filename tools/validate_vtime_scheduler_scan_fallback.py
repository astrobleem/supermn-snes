#!/usr/bin/env python3
"""Synthetic exact-Nexen routing check for the VTIME `$074C` fallback."""

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


VTIME_BASE = 0x404000
VTIME_MAGIC = 0xC71E


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_to(m: probe.common.base.McpSession, pc: int) -> dict:
    hook = m.add_exec_hook(pc, cpu_type="Sa1")
    m.drain_notifications(timeout=0.05)
    try:
        result = m.run_until(max_frames=8, hook_handle=hook)
        m.pause()
        return result
    finally:
        m.remove_hook(hook)
        m.drain_notifications(timeout=0.05)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, required=True)
    parser.add_argument("--nat", type=Path, default=Path("/tmp/b0_native.mss"))
    parser.add_argument("--nexen", type=Path, default=probe.common.base.DEFAULT_NEXEN)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--port", type=int, default=9359)
    args = parser.parse_args()
    for path in (args.rom, args.nat, args.nexen):
        if not path.is_file():
            parser.error(f"missing input: {path}")
    if args.output.exists():
        parser.error(f"output exists: {args.output}")

    interp = ROOT / "src/interp.sym"
    lh_sched = probe.symbol(interp, "lh_sched")
    nofire = probe.symbol(interp, "lh_nofire")
    continuation = lh_sched + 4
    report: dict[str, object] = {
        "scope": (
            "synthetic exact-Nexen active/invalid routing at the VTIME-only "
            "$074C scheduler fallback; not scheduler semantics, MAME, gameplay, "
            "rate, fresh boot, or acceptance"
        ),
        "rom": {"path": str(args.rom.resolve()), "sha256": sha256(args.rom)},
        "addresses": {
            "lh_sched": f"{lh_sched:04X}",
            "lh_nofire": f"{nofire:04X}",
            "legacy_continuation": f"{continuation:04X}",
        },
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
        m.load_state(str(args.nat.resolve()))
        m.pause()
        probe.common.write_u16(m, 0x34, 0x1234)
        forced = bytearray(0x1C)
        forced[0:2] = VTIME_MAGIC.to_bytes(2, "little")
        forced[2:4] = (1).to_bytes(2, "little")
        m.write_memory("snesMemory", VTIME_BASE, forced.hex())
        nofire_file = nofire - 0x8000
        nofire_original = bytes(m.read_memory("snesPrgRom", nofire_file, 2))
        try:
            m.write_memory("snesPrgRom", nofire_file, "80fe")
            probe.common.base.set_sa1_pc(m, lh_sched)
            active_hit = run_to(m, nofire)
        finally:
            m.write_memory("snesPrgRom", nofire_file, nofire_original.hex())

        m.load_state(str(args.nat.resolve()))
        m.pause()
        probe.common.write_u16(m, 0x34, 0x1234)
        m.write_memory("snesMemory", VTIME_BASE, bytes(0x1C).hex())
        continuation_file = continuation - 0x8000
        continuation_original = bytes(
            m.read_memory("snesPrgRom", continuation_file, 2)
        )
        try:
            m.write_memory("snesPrgRom", continuation_file, "80fe")
            probe.common.base.set_sa1_pc(m, lh_sched)
            legacy_hit = run_to(m, continuation)
            legacy_cpu = m.get_cpu_state("Sa1")
        finally:
            m.write_memory(
                "snesPrgRom", continuation_file, continuation_original.hex()
            )

    checks = {
        "active_valid_routes_to_loop_hook_nofire": active_hit.get("reason") == "hookFired",
        "invalid_clock_reproduces_source_prefix": legacy_hit.get("reason") == "hookFired",
        "invalid_clock_accumulator_is_a5_plus_two": int(legacy_cpu["a"]) & 0xFFFF == 0x1236,
    }
    report.update({
        "runtime_rom_patches_restored": True,
        "active_response": active_hit,
        "legacy_response": legacy_hit,
        "legacy_sa1": legacy_cpu,
        "checks": checks,
        "result": "green" if all(checks.values()) else "red",
    })
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"result": report["result"], "checks": checks, "summary": str(args.output)}, sort_keys=True))
    return 0 if report["result"] == "green" else 1


if __name__ == "__main__":
    raise SystemExit(main())
