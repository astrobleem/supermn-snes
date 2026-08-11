#!/usr/bin/env python3
"""Prove that unsupported $02E49C states delegate before architectural writes.

The hand-native fast path deliberately accepts only canonical work-RAM A4/A7
values and first-table selectors 0..18.  These Nexen route checks stop at the
cold interpreter entry itself and compare the complete virtual 68000 state,
CCR/X, work backing, stack, USP, AC, and halt state to the pre-native boundary.
They complement, but do not replace, the MAME/native-off/native-on semantic
edge differential for admitted states.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from dataclasses import replace
from pathlib import Path

import validate_render_helpers as base
import validate_stage3_hot_handlers as stage3


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FIXTURES = (
    ROOT
    / "build/playtest-investigation-20260725/"
    "stage3-leaf-bundle-v1/e49c-fixtures"
)
DEFAULT_ROM = ROOT / "build/interp.sfc"
TARGET = 0x02E49C
ENTRY = 0x94D340


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def variants(source: stage3.Fixture) -> list[stage3.Fixture]:
    answer: list[stage3.Fixture] = []

    selector_work = bytearray(source.work)
    a4 = source.regs["A4"] & 0xFFFF
    selector_work[a4 + 0x0A : a4 + 0x0C] = b"\x00\x13"
    answer.append(
        replace(
            source,
            name="selector-19",
            work=bytes(selector_work),
        )
    )

    for name, register, value in (
        ("a4-first-crossing", "A4", 0x00F03FF3),
        ("a4-non-work-bank", "A4", 0x00E02DF4),
        ("a7-first-crossing", "A7", 0x00F03FFD),
        ("a7-non-work-bank", "A7", 0x00E00456),
    ):
        regs = dict(source.regs)
        regs[register] = value
        answer.append(replace(source, name=name, regs=regs))
    return answer


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixtures", type=Path, default=DEFAULT_FIXTURES)
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    parser.add_argument("--nexen", type=Path, default=base.DEFAULT_NEXEN)
    parser.add_argument("--nat", type=Path, default=base.DEFAULT_NAT)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--port", type=int, default=9410)
    args = parser.parse_args()

    for label, path in (
        ("fixture directory", args.fixtures),
        ("ROM", args.rom),
        ("Nexen", args.nexen),
        ("native base state", args.nat),
    ):
        if not path.exists():
            parser.error(f"missing {label}: {path}")
    if args.output.exists():
        parser.error(f"output already exists: {args.output}")

    source = stage3.load_fixtures(
        args.fixtures.resolve(), {TARGET}, 1
    )[0]
    cases = variants(source)
    events: list[dict] = [
        {
            "event": "provenance",
            "scope": (
                "$02E49C native guard-to-cold route conservation at the "
                "pre-inext boundary; all D/A, CCR/X, work/stack/upper backing, "
                "USP, AC, halt and virtual PC; Nexen-only guard contract, not "
                "MAME semantic, gameplay, performance, or fresh-boot evidence"
            ),
            "rom": str(args.rom.resolve()),
            "rom_sha256": sha256(args.rom),
            "nexen": str(args.nexen.resolve()),
            "nexen_sha256": sha256(args.nexen),
            "nat": str(args.nat.resolve()),
            "nat_sha256": sha256(args.nat),
            "source_fixture": str(source.metadata_path),
            "source_pre_entry_state": str(source.pre_entry_state),
            "cases": [case.name for case in cases],
            "time": time.time(),
        }
    ]

    args.output.parent.mkdir(parents=True, exist_ok=True)
    stderr_log = args.output.with_suffix(".nexen.stderr.log")
    with base.McpSession(
        rom=str(args.rom.resolve()),
        mesen=str(args.nexen.resolve()),
        cwd=ROOT,
        port=args.port,
        boot_wait=8.0,
        socket_timeout=180.0,
        stderr_log=stderr_log,
    ) as nexen:
        inext_offset = stage3.INEXT - 0x8000
        for case in cases:
            stage3.prepare_console(nexen, args.nat.resolve(), case, 1)
            before = {
                "regs": stage3.live.captured_regs(nexen),
                "ccr": stage3.live.captured_ccr(nexen),
                "work": bytes(
                    nexen.read_memory(
                        base.SNES_SPACE, 0x400000, stage3.FULL_WORK_SIZE
                    )
                ),
                "usp": (
                    stage3.live.read_u16(nexen, 0xA4)
                    | (stage3.live.read_u16(nexen, 0xA6) << 16)
                ),
                "ac": stage3.live.read_u16(nexen, 0xAC),
                "halt": stage3.live.read_u16(nexen, 0x4E),
            }
            saved_inext = bytes(
                nexen.read_memory("snesPrgRom", inext_offset, 2)
            )
            nexen.write_memory("snesPrgRom", inext_offset, "80fe")
            hook = nexen.add_exec_hook(stage3.INEXT, cpu_type="Sa1")
            nexen.drain_notifications(timeout=0.05)
            stage3.live.set_sa1_pc(nexen, ENTRY)
            try:
                hit, frames = stage3.live.run_to_hook(
                    nexen, hook, attempts=16
                )
                nexen.pause()
            finally:
                nexen.remove_hook(hook)
                nexen.write_memory(
                    "snesPrgRom", inext_offset, saved_inext.hex()
                )

            after_regs = stage3.live.captured_regs(nexen)
            after_work = bytes(
                nexen.read_memory(
                    base.SNES_SPACE, 0x400000, stage3.FULL_WORK_SIZE
                )
            )
            sa1 = nexen.get_cpu_state("Sa1")
            actual_pc = (
                ((int(sa1.get("k", 0)) & 0xFF) << 16)
                | (int(sa1["pc"]) & 0xFFFF)
            )
            virtual_pc = (
                stage3.live.read_u16(nexen, 0x40)
                | ((stage3.live.read_u16(nexen, 0x42) & 0xFF) << 16)
            )
            register_mismatches = {
                name: {
                    "before": before["regs"][name],
                    "after": after_regs[name],
                }
                for name in before["regs"]
                if before["regs"][name] != after_regs[name]
            }
            work_mismatches = [
                index
                for index, (left, right) in enumerate(
                    zip(before["work"], after_work)
                )
                if left != right
            ]
            after_values = {
                "ccr": stage3.live.captured_ccr(nexen),
                "usp": (
                    stage3.live.read_u16(nexen, 0xA4)
                    | (stage3.live.read_u16(nexen, 0xA6) << 16)
                ),
                "ac": stage3.live.read_u16(nexen, 0xAC),
                "halt": stage3.live.read_u16(nexen, 0x4E),
            }
            scalar_mismatches = {
                name: {"before": before[name], "after": after_values[name]}
                for name in after_values
                if before[name] != after_values[name]
            }
            green = (
                (hit or {}).get("reason") == "hookFired"
                and actual_pc == stage3.INEXT
                and virtual_pc == TARGET
                and not register_mismatches
                and not work_mismatches
                and not scalar_mismatches
            )
            events.append(
                {
                    "event": "guard_case",
                    "case": case.name,
                    "run_reason": (hit or {}).get("reason"),
                    "frames_advanced": frames,
                    "actual_sa1_pc": f"{actual_pc:06X}",
                    "virtual_68k_pc": f"{virtual_pc:06X}",
                    "register_mismatches": register_mismatches,
                    "work_mismatch_count": len(work_mismatches),
                    "work_mismatch_first": work_mismatches[:16],
                    "scalar_mismatches": scalar_mismatches,
                    "result": "green" if green else "red",
                }
            )

    green = sum(event.get("result") == "green" for event in events)
    summary = {
        "event": "summary",
        "cases": len(cases),
        "green": green,
        "red": len(cases) - green,
        "result": "green" if green == len(cases) else "red",
        "time": time.time(),
    }
    events.append(summary)
    args.output.write_text(
        "".join(
            json.dumps(event, sort_keys=True) + "\n" for event in events
        ),
        encoding="utf-8",
    )
    print(json.dumps(summary, sort_keys=True))
    return 0 if summary["result"] == "green" else 1


if __name__ == "__main__":
    raise SystemExit(main())
