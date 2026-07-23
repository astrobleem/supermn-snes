#!/usr/bin/env python3
"""Nexen seam proof for the guarded $028F92 initializer stack ranges.

This intentionally stops at the first hot/cold instruction.  It proves the
guard's branch decision and that it mutates neither emulated register state nor
work RAM before rejecting.  It does not replace the MAME semantic differential
for accepted stacks and is never fps evidence.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import validate_2742_hle as impl
import validate_entry_initializer as entry


PROBES = (
    ("below-work-stack-floor", 0x00F00020, "reject"),
    ("low-fast-boundary", 0x00F00040, "fast"),
    ("organic-captured-fast", 0x00F016CE, "fast"),
    ("before-clear-interval", 0x00F03130, "fast"),
    ("clear-interval-start", 0x00F03131, "reject"),
    ("conservative-interior-gap", 0x00F03200, "reject"),
    ("return-destroying-stack", 0x00F03D00, "reject"),
    ("clear-interval-end", 0x00F03ED3, "reject"),
    ("nested-return-overlap-start", 0x00F03ED4, "reject"),
    ("nested-return-overlap-end", 0x00F03ED7, "reject"),
    ("after-all-clear-overlap", 0x00F03ED8, "fast"),
    ("upper-fast-boundary", 0x00F03FFC, "fast"),
    ("crosses-mapped-window", 0x00F03FFD, "reject"),
    ("outside-mapped-window", 0x00F04000, "reject"),
    ("wrong-stack-bank", 0x00F10040, "reject"),
)


def make_probe(index: int, name: str, a7: int) -> impl.base.Case:
    original = entry.make_case(0x028F92, index % 3)
    regs = dict(original.regs)
    regs["A7"] = a7
    return impl.base.Case(
        name,
        original.target,
        regs,
        original.sr,
        original.work,
        original.video_regions,
    )


def hook_params(rows: list[dict]) -> list[dict]:
    return [
        dict(row.get("params", {}))
        for row in rows
        if row.get("method") == "notifications/mesen/hookFired"
    ]


def current_sa1_pc(session: impl.base.McpSession) -> int:
    state = session.get_cpu_state("Sa1")
    return ((int(state.get("k", 0)) & 0xFF) << 16) | (int(state["pc"]) & 0xFFFF)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, default=impl.base.DEFAULT_ROM)
    parser.add_argument("--nexen", type=Path, default=impl.base.DEFAULT_NEXEN)
    parser.add_argument("--nat", type=Path, default=impl.base.DEFAULT_NAT)
    parser.add_argument("--port", type=int, default=7592)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    for path in (args.rom, args.nexen, args.nat):
        if not path.is_file():
            parser.error(f"missing required input: {path}")

    entry.configure(0x028F92)
    rows: list[dict] = [
        {
            "event": "provenance",
            "scope": "$028F92 pre-mutation stack-guard seam proof; not fps",
            "rom": str(args.rom.resolve()),
            "rom_sha256": impl.base.sha256(args.rom),
            "nat": str(args.nat.resolve()),
            "nat_sha256": impl.base.sha256(args.nat),
            "nexen": str(args.nexen.resolve()),
            "nexen_sha256": impl.base.sha256(args.nexen),
            "native_entry": f"{impl.ENTRY_NATIVE:06X}",
            "hot_seam": f"{impl.TRACE_POINTS['fast']:06X}",
            "cold_seam": f"{impl.TRACE_POINTS['reject']:06X}",
            "cases": len(PROBES),
            "time": time.time(),
        }
    ]
    print(json.dumps(rows[0], sort_keys=True), flush=True)

    stderr_log = args.output.parent / f"{args.output.stem}.nexen.stderr.log"
    stderr_log.parent.mkdir(parents=True, exist_ok=True)
    with impl.base.McpSession(
        rom=str(args.rom),
        mesen=str(args.nexen),
        cwd=str(impl.ROOT),
        port=args.port,
        boot_wait=8.0,
        socket_timeout=120.0,
        stderr_log=stderr_log,
    ) as nexen:
        for index, (name, a7, expected_stage) in enumerate(PROBES):
            case = make_probe(index, name, a7)
            impl.prepare_nexen_case(nexen, args.nat, case)
            impl.base._set_sa1_pc(nexen, impl.ENTRY_NATIVE)
            seam = impl.TRACE_POINTS[expected_stage]
            # run_until consumes the notification for its watched handle.  A
            # duplicate exec hook retains the same seam's exact cycle stamp;
            # write hooks then prove that no emulated state was changed at or
            # before that cycle, regardless of where the asynchronous pause
            # eventually lands.
            stop_hook = nexen.add_exec_hook(seam, cpu_type="Sa1")
            stamp_hook = nexen.add_exec_hook(seam, cpu_type="Sa1")
            dp_write_hook = nexen.add_write_hook(0x0000, 0x00FF, cpu_type="Sa1")
            work_write_hook = nexen.add_write_hook(
                0x400000, 0x40FFFF, cpu_type="Sa1"
            )
            nexen.drain_notifications(timeout=0.1)
            try:
                hit = nexen.run_until(max_frames=120, hook_handle=stop_hook)
                nexen.pause()
                notifications = hook_params(nexen.drain_notifications(timeout=0.5))
            finally:
                for handle in (
                    stop_hook,
                    stamp_hook,
                    dp_write_hook,
                    work_write_hook,
                ):
                    nexen.remove_hook(handle)
                nexen.drain_notifications(timeout=0.1)

            stamps = [
                row
                for row in notifications
                if int(row.get("handle", -1)) == stamp_hook
                and "cycleCount" in row
            ]
            seam_cycle = int(stamps[0]["cycleCount"]) if stamps else None
            write_handles = {dp_write_hook, work_write_hook}
            pre_seam_writes = [
                row
                for row in notifications
                if int(row.get("handle", -1)) in write_handles
                and seam_cycle is not None
                and int(row.get("cycleCount", seam_cycle + 1)) <= seam_cycle
            ]
            result = (
                "green"
                if (hit or {}).get("reason") == "hookFired"
                and seam_cycle is not None
                and not pre_seam_writes
                else "red"
            )
            row = {
                "event": "case",
                "case": name,
                "a7": f"{a7:08X}",
                "expected_stage": expected_stage,
                "seam": f"{seam:06X}",
                "seam_cycle": seam_cycle,
                "run_until": hit,
                "post_pause_pc": f"{current_sa1_pc(nexen):06X}",
                "pre_seam_write_count": len(pre_seam_writes),
                "pre_seam_writes": pre_seam_writes[:8],
                "result": result,
            }
            rows.append(row)
            print(json.dumps(row, sort_keys=True), flush=True)

    cases = [row for row in rows if row.get("event") == "case"]
    green = sum(row["result"] == "green" for row in cases)
    summary = {
        "event": "summary",
        "green": green,
        "red": len(cases) - green,
        "total": len(cases),
        "result": "green" if green == len(cases) else "red",
        "time": time.time(),
    }
    rows.append(summary)
    print(json.dumps(summary, sort_keys=True), flush=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row, sort_keys=True) + "\n")
    return 0 if green == len(cases) else 1


if __name__ == "__main__":
    raise SystemExit(main())
