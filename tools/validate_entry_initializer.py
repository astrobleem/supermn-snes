#!/usr/bin/env python3
"""Function-local MAME/Nexen differential for one-shot gameplay initializers.

The three supported roots use the same table-call contract: the caller's real
return is already on the emulated MC68000 stack.  MAME executes the original
routine through RTS; Nexen enters the guarded bank-$9D native body and returns
through the validation sentinel.  Every D/A register, X/N/Z/V/C, and the full
mapped 16 KiB work-RAM window are compared.

This is bounded semantic and local-cycle evidence, never an fps result.
"""

from __future__ import annotations

import random
import sys
from pathlib import Path

import validate_2742_hle as impl


ROOT = Path(__file__).resolve().parents[1]

TARGETS = {
    0x024AA8: ("entry_24aa8t", "h24aa8t_hot", "h24aa8t_cold"),
    0x028F92: ("entry_28f92t", "h28f92_hot", "h28f92_cold"),
    0x00091E: ("entry_91et", "h91et_hot", "h91et_cold"),
}


def symbol_address(name: str) -> int:
    for raw in (ROOT / "src/escbank7.sym").read_text(
        encoding="utf-8-sig"
    ).splitlines():
        fields = raw.split()
        if len(fields) >= 2 and fields[1] == name:
            return 0x9D0000 | int(fields[0].split(":", 1)[1], 16)
    raise RuntimeError(f"missing src/escbank7.sym symbol {name}")


def put16(data: bytearray, offset: int, value: int) -> None:
    data[offset : offset + 2] = (value & 0xFFFF).to_bytes(2, "big")


def make_case(target: int, index: int) -> impl.base.Case:
    seed = (target << 4) ^ index
    rng = random.Random(seed)
    work = bytearray(rng.randrange(256) for _ in range(0x4000))
    work.extend([0xFF] * 0xC000)
    regs = {reg: rng.randrange(1 << 32) for reg in impl.base.REG_NAMES}
    regs["A5"] = 0x00F00000
    if target == 0x028F92:
        # Cover both guarded fast intervals.  $F03D00 is not a valid fixture:
        # the original routine legitimately erases its own return there and
        # cannot RTS.  The conservative guard sends the entire containing
        # interval to the interpreter, including harmless interior gaps.
        regs["A7"] = (0x00F03000, 0x00F03ED8, 0x00F03F00)[index]
    else:
        regs["A7"] = impl.ENTRY_SP
    sr = 0x2700 | rng.randrange(0x20)

    # $091E indexes a ROM pointer table using these two signed word fields.
    # Exercise three distinct, in-range production-shaped selections.
    if target == 0x00091E:
        selectors = ((0, 0), (1, 2), (3, 1))
        first, second = selectors[index]
        put16(work, 0x2930, first)
        put16(work, 0x2932, second)

    stack = regs["A7"] & 0xFFFF
    work[stack : stack + 4] = impl.base.be32(impl.RETURN_PC)
    work[impl.RETURN_PC & 0xFFFF : (impl.RETURN_PC & 0xFFFF) + 2] = bytes.fromhex(
        "60fe"
    )
    return impl.base.Case(
        f"{target:06x}-canonical-{index}",
        target,
        regs,
        sr,
        bytes(work),
        [],
    )


def make_91e_fallback_case() -> impl.base.Case:
    """Exercise the pre-mutation fallback with a valid noncanonical A5."""

    canonical = make_case(0x00091E, 0)
    work = bytearray(canonical.work)
    # A5+$2930/$2932 remains mapped and selects the first immutable record;
    # only the fixed-base native alias is unavailable.
    put16(work, 0x2932, 0)
    put16(work, 0x2934, 0)
    regs = dict(canonical.regs)
    regs["A5"] = 0x00F00002
    return impl.base.Case(
        "fallback-work-source",
        canonical.target,
        regs,
        canonical.sr,
        bytes(work),
        canonical.video_regions,
    )


def configure(target: int) -> None:
    entry_symbol, hot_symbol, cold_symbol = TARGETS[target]
    native = symbol_address(entry_symbol)
    impl.ENTRY_PC = target
    impl.ENTRY_NATIVE = native
    impl.TRACE_POINTS = {
        "hle": native,
        "fast": symbol_address(hot_symbol),
        "reject": symbol_address(cold_symbol),
    }
    impl.EVIDENCE_SCOPE = (
        f"function-local ${target:06X} gameplay-entry initializer "
        "MAME/Nexen differential; not fps"
    )
    impl.LOG_STEM = f"{target:06x}-initializer-differential"
    impl.make_cases = lambda: [
        *[make_case(target, index) for index in range(3)],
        *([make_91e_fallback_case()] if target == 0x00091E else []),
    ]
    impl.base.NATIVE_ENTRIES[target] = native


def main() -> int:
    if len(sys.argv) < 2:
        raise SystemExit(
            "usage: validate_entry_initializer.py <024AA8|028F92|00091E> "
            "[validate_2742_hle options]"
        )
    try:
        target = int(sys.argv[1], 16)
    except ValueError as exc:
        raise SystemExit(f"invalid target: {sys.argv[1]}") from exc
    if target not in TARGETS:
        choices = ", ".join(f"{value:06X}" for value in TARGETS)
        raise SystemExit(f"unsupported target ${target:06X}; choose {choices}")
    configure(target)
    sys.argv = [sys.argv[0], *sys.argv[2:]]
    return impl.main()


if __name__ == "__main__":
    raise SystemExit(main())
