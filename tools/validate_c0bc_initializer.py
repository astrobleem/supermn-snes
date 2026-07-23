#!/usr/bin/env python3
"""Whole-root MAME/Nexen differential for the $00C0BC initializer task.

The original and native paths each run all fourteen organic $29B6 callbacks,
then stop at the committed $C170 trap boundary.  Five ROM-table selectors are
covered.  Comparison includes all D/A registers, X/N/Z/V/C, mapped 16 KiB work
RAM with stack residue, and both complete overlapping tilemap spans.

This is function-local semantic and cycle evidence, never fps evidence.
"""

from __future__ import annotations

import os
import random
from pathlib import Path

import validate_c262_hle as impl


ENTRY_PC = 0x00C0BC
EXIT_PC = 0x00C170
# Compare both complete 1 KiB planes.  $C0BC writes a 14x28 footprint; the
# remaining 120 cells are the renderer-provenance guard and must stay exact.
VIDEO_SPAN = 0x0400


def symbol_address(path: str, bank: int, name: str) -> int:
    for raw in Path(path).read_text(
        encoding="utf-8-sig"
    ).splitlines():
        fields = raw.split()
        if len(fields) >= 2 and fields[1] == name:
            return (bank << 16) | int(fields[0].split(":", 1)[1], 16)
    raise RuntimeError(f"missing {path} symbol {name}")


def put16(data: bytearray, offset: int, value: int) -> None:
    data[offset : offset + 2] = (value & 0xFFFF).to_bytes(2, "big")


def put32(data: bytearray, offset: int, value: int) -> None:
    data[offset : offset + 4] = impl.base.be32(value)


def build_case(
    name: str,
    seed: int,
    *,
    selector: int,
    stack: int,
    empty_video: bool = False,
) -> impl.base.Case:
    rng = random.Random(seed)
    work = bytearray(rng.randrange(256) for _ in range(0x4000))
    work.extend([0xFF] * 0xC000)
    regs = {reg: rng.randrange(1 << 32) for reg in impl.base.REG_NAMES}
    regs["A5"] = 0x00F00000
    regs["A7"] = 0x00F00000 | stack
    sr = 0x2700 | rng.randrange(0x20)
    put32(work, 0x1CC2, 0x000029B6)
    put16(work, 0x2930, selector)
    def video_plane() -> bytes:
        if empty_video:
            return bytes(VIDEO_SPAN)
        return bytes(rng.randrange(256) for _ in range(VIDEO_SPAN))

    return impl.base.Case(
        name,
        ENTRY_PC,
        regs,
        sr,
        bytes(work),
        [
            (
                0xE00800,
                0x414800,
                video_plane(),
            ),
            (
                0xE00C00,
                0x414C00,
                video_plane(),
            ),
        ],
    )


def make_cases() -> list[impl.base.Case]:
    cases = [
        build_case(
            "selector-0-production-stack", 0xC0BC00, selector=0, stack=0x16CE
        ),
        build_case("selector-1", 0xC0BC01, selector=1, stack=0x1800),
        build_case("selector-2", 0xC0BC02, selector=2, stack=0x2000),
        build_case("selector-3", 0xC0BC03, selector=3, stack=0x3000),
        build_case("selector-4-high-stack", 0xC0BC04, selector=4, stack=0x3F00),
        build_case(
            "selector-0-empty-bg",
            0xC0BC10,
            selector=0,
            stack=0x16CE,
            empty_video=True,
        ),
    ]
    selected = os.environ.get("C0BC_SELECTORS")
    if selected:
        indexes = {int(value, 0) for value in selected.split(",")}
        return [case for index, case in enumerate(cases) if index in indexes]
    return cases


def make_fallback_probe() -> impl.base.Case:
    original = build_case(
        "fallback-wrong-a5", 0xC0BCF0, selector=0, stack=0x16CE
    )
    regs = dict(original.regs)
    regs["A5"] = 0x00E00000
    return impl.base.Case(
        original.name,
        original.target,
        regs,
        original.sr,
        original.work,
        original.video_regions,
    )


def main() -> int:
    impl.ENTRY_PC = ENTRY_PC
    impl.EXIT_PC = EXIT_PC
    impl.ENTRY_NATIVE = symbol_address("src/escbank7.sym", 0x9D, "entry_c0bc")
    impl.FAST_NATIVE = symbol_address("src/escbank8.sym", 0x9E, "hc0bc_hle_fast")
    impl.FALLBACK_NATIVE = symbol_address(
        "src/escbank7.sym", 0x9D, "entry_c0bc_generated"
    )
    impl.make_cases = make_cases
    impl.make_fallback_probe = make_fallback_probe
    impl.expects_fast = lambda case: case.name.startswith(
        "selector-0-production-stack"
    ) or case.name == "selector-0-empty-bg"
    impl.extra_case_fields = lambda case, result: {
        "renderer_provenance": f"{getattr(result, 'renderer_provenance', 0):04X}",
        "renderer_provenance_expected": (
            "C0BC" if case.name == "selector-0-empty-bg" else "0000"
        ),
        "renderer_provenance_result": (
            "green"
            if getattr(result, "renderer_provenance", 0)
            == (0xC0BC if case.name == "selector-0-empty-bg" else 0)
            else "red"
        ),
    }
    impl.extra_case_green = lambda case, result: (
        getattr(result, "renderer_provenance", 0)
        == (0xC0BC if case.name == "selector-0-empty-bg" else 0)
    )
    impl.EVIDENCE_SCOPE = (
        "whole-function $C0BC with 14 organic $29B6 callbacks "
        "MAME/Nexen differential; not fps"
    )
    impl.MAME_BOUNDARY_METHOD = (
        "validation-only NOP at $C170 trap #5; synchronous $C172 write-log "
        "mark plus $C172 register/work prefetch snapshot"
    )
    impl.base.NATIVE_ENTRIES[ENTRY_PC] = impl.ENTRY_NATIVE
    return impl.main()


if __name__ == "__main__":
    raise SystemExit(main())
