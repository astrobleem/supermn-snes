#!/usr/bin/env python3
"""Record fresh VTIME credit recognition after each real Select pulse.

This is a bounded input-sampling diagnostic.  It does not alter emulator or
game memory, and it is not a MAME, gameplay, timing-acceptance, or rate result.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
os.environ["DOTNET_ROOT"] = "/home/chad/.dotnet10"
sys.path.insert(0, str(ROOT / "tools"))

import validate_fresh_one_credit_prompt as fresh  # noqa: E402


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sample(m: fresh.McpSession) -> dict[str, object]:
    work = bytes(m.read_memory("snesMemory", 0x401C50, 0x20))
    iram = bytes(m.read_memory("Sa1Memory", 0x0040, 0x70))
    timer = bytes(m.read_memory("snesMemory", 0x404000, 0x1C))
    rng = bytes(m.read_memory("snesMemory", 0x40170E, 2))
    u16 = lambda blob, offset: int.from_bytes(blob[offset:offset + 2], "little")
    return {
        "video_frame": int(m.get_state().get("frameCount", 0)),
        "credits": int.from_bytes(work[0x12:0x14], "big"),
        "rng_f0170e": int.from_bytes(rng, "big"),
        "pc68k": f"{int.from_bytes(iram[0:4], 'little') & 0xFFFFFF:06X}",
        "game_tick": u16(
            bytes(m.read_memory("Sa1Memory", fresh.campaign.TICK_IRAM, 2)), 0
        ),
        "ac": u16(iram, 0x6C),
        "gates": {
            name: u16(bytes(m.read_memory("Sa1Memory", address, 2)), 0)
            for name, address in (
                ("xlat", 0x071A), ("pacing", 0x0734),
                ("select", 0x0736), ("choke", 0x073A),
                ("swin", 0x073C),
            )
        },
        "vtime": {
            name: u16(timer, offset)
            for name, offset in (
                ("magic", 0x00), ("valid", 0x02), ("cost", 0x04),
                ("remaining_lo", 0x06), ("remaining_hi", 0x08),
                ("due", 0x18), ("owner", 0x1A),
            )
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--nexen", type=Path, default=fresh.DEFAULT_NEXEN)
    parser.add_argument("--port", type=int, default=9362)
    parser.add_argument("--cold-boot-frame", type=int, default=5248)
    parser.add_argument("--pulses", type=int, default=8)
    parser.add_argument("--hold-frames", type=int, default=4)
    parser.add_argument("--gap-frames", type=int, default=4)
    parser.add_argument("--settle-frames", type=int, default=155)
    args = parser.parse_args()
    for path in (args.rom, args.nexen):
        if not path.is_file():
            parser.error(f"missing input: {path}")
    if args.output.exists():
        parser.error(f"output exists: {args.output}")
    args.output.mkdir(parents=True)
    retained = args.output / "rom.sfc"
    shutil.copy2(args.rom, retained)

    rows: list[dict[str, object]] = []
    with fresh.McpSession(
        rom=retained,
        mesen=args.nexen.resolve(),
        cwd=ROOT,
        port=args.port,
        boot_wait=6.0,
        socket_timeout=300.0,
        stderr_log=args.output / "emulator.stderr.log",
    ) as m:
        m.pause()
        current = int(m.get_state().get("frameCount", 0))
        fresh.campaign.run_exact_frames(m, 0, max(0, args.cold_boot_frame - current))
        rows.append({"phase": "before", **sample(m)})
        for pulse in range(1, args.pulses + 1):
            fresh.campaign.run_exact_frames(
                m, fresh.McpSession.BTN_SELECT, args.hold_frames
            )
            rows.append({"phase": "hold", "pulse": pulse, **sample(m)})
            if pulse < args.pulses and args.gap_frames:
                fresh.campaign.run_exact_frames(m, 0, args.gap_frames)
                rows.append({"phase": "gap", "pulse": pulse, **sample(m)})
        fresh.campaign.run_exact_frames(m, 0, args.settle_frames)
        rows.append({"phase": "settled", **sample(m)})
        state = fresh.campaign.save_state(m, args.output / "settled.mss")

    credits = [int(row["credits"]) for row in rows]
    report = {
        "scope": (
            "fresh bounded per-pulse Select/credit sampling; no memory writes, "
            "MAME comparison, gameplay, rate, or acceptance claim"
        ),
        "rom": {"path": str(retained), "sha256": sha256(retained)},
        "configuration": {
            "cold_boot_frame": args.cold_boot_frame,
            "pulses": args.pulses,
            "hold_frames": args.hold_frames,
            "gap_frames": args.gap_frames,
            "settle_frames": args.settle_frames,
        },
        "samples": rows,
        "credit_sequence": credits,
        "final_credits": credits[-1],
        "retained_state": state,
        "result": "green" if credits[-1] == args.pulses else "red",
    }
    summary = args.output / "summary.json"
    summary.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({
        "result": report["result"],
        "final_credits": report["final_credits"],
        "credit_sequence": credits,
        "summary": str(summary),
    }, sort_keys=True))
    return 0 if report["result"] == "green" else 1


if __name__ == "__main__":
    raise SystemExit(main())
