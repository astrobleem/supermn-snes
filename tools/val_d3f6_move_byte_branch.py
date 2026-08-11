#!/usr/bin/env python3
"""Regression for $00D3F6 MOVE.B-to-memory conditions feeding BLE.

The handler copies a signed direction byte into an object field and branches
on MOVE.B's N/Z flags.  A byte read is zero-extended in the native runtime, so
testing it as a 16-bit value turns $FF into positive 255 and spuriously
allocates a collision record.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import capstone


ROOT = Path(__file__).resolve().parents[1]
PROGRAM = ROOT / "data/superman_m68k.bin"
SOURCE = ROOT / "src/escbank2.pasm"
SOURCE6 = ROOT / "src/escbank6.pasm"
NORMALIZE = [
    "and #$00FF",
    "eor #$0080",
    "sec",
    "sbc #$0080",
]


def meaningful_lines(text: str) -> list[str]:
    return [
        line.strip()
        for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith(";")
    ]


def count_contiguous(lines: list[str], expected: list[str]) -> int:
    return sum(
        lines[index : index + len(expected)] == expected
        for index in range(len(lines) - len(expected) + 1)
    )


def handler_block(text: str) -> str:
    start = text.index("entry_d3f6:")
    marker = "; space at $94:B400."
    end = text.index(marker, start) if marker in text[start:] else len(text)
    return text[start:end]


def check_arcade_instructions() -> None:
    program = PROGRAM.read_bytes()
    md = capstone.Cs(capstone.CS_ARCH_M68K, capstone.CS_MODE_BIG_ENDIAN)
    instructions = list(md.disasm(program[0xD3F6 : 0xD420], 0xD3F6))
    pairs = [
        (instructions[index], instructions[index + 1])
        for index in range(len(instructions) - 1)
        if instructions[index].mnemonic == "move.b"
        and instructions[index + 1].mnemonic.startswith("ble")
    ]
    assert len(pairs) == 2, (
        "$00D3F6 must retain its two MOVE.B-to-memory/BLE conditions"
    )
    assert all(pair[0].op_str.replace(" ", "").endswith(",-$7(a4)") for pair in pairs), pairs


def check_generated_body(text: str) -> None:
    block = meaningful_lines(handler_block(text))
    expected = [
        "jsl.l readbyte_l",
        *NORMALIZE,
        "beq Lfd3f6_1",
        "bmi Lfd3f6_1",
    ]
    expected_fallback = [
        "jsl.l readbyte_l",
        *NORMALIZE,
        "beq Lfd3f6_4",
        "bmi Lfd3f6_4",
    ]
    assert count_contiguous(block, expected) == 1, (
        "generated body: primary MOVE.B/BLE does not normalize byte N/Z"
    )
    assert count_contiguous(block, expected_fallback) == 1, (
        "generated body: fallback MOVE.B/BLE does not normalize byte N/Z"
    )


def check_deployed_body(text: str) -> None:
    block = meaningful_lines(handler_block(text))
    assert count_contiguous(
        block,
        [
            "jsl.l $94B3E0",
            "beq Lfd3f6_1",
            "bmi Lfd3f6_1",
        ],
    ) == 1, "deployed primary MOVE.B/BLE does not use byte N/Z"
    assert count_contiguous(
        block,
        [
            "jsl.l $94B3E0",
            "beq Lfd3f6_4",
            "bmi Lfd3f6_4",
        ],
    ) == 1, "deployed fallback MOVE.B/BLE does not use byte N/Z"
    helper = meaningful_lines(text[text.index("d3f6_readbyte_move_nz:") :])
    assert count_contiguous(
        helper,
        [
            "d3f6_readbyte_move_nz:",
            "jml.l $959F70",
            "d3f6_readbyte_move_nz_end:",
        ],
    ) == 1, "deployed byte N/Z trampoline changed"
    remote = meaningful_lines(SOURCE6.read_text(encoding="utf-8"))
    assert count_contiguous(
        remote,
        [
            "d3f6_move_byte_nz:",
            "rep #$30",
            ".a16",
            ".i16",
            "jsl.l readbyte_l",
            "sep #$20",
            ".a8",
            "ora #$00",
            "php",
            "php",
            "pla",
            "rep #$30",
            ".a16",
            "pha",
            "and #$0080",
            "sta $70",
            "pla",
            "and #$0002",
            "sta $60",
            "stz $72",
            "stz $6E",
            "plp",
            "rep #$20",
            "rtl",
            "d3f6_move_byte_nz_end:",
        ],
    ) == 1, "deployed byte N/Z/CCR helper changed"


def check_codegen_and_deployed_body() -> None:
    generated = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools/transpile.py"),
            "00D3F6",
            "--bank1",
            "--coroutine",
            "--bail",
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    assert "=== all 75 instrs transpiled ===" in generated.stderr
    check_generated_body(generated.stdout)
    check_deployed_body(SOURCE.read_text(encoding="utf-8"))


def main() -> None:
    check_arcade_instructions()
    check_codegen_and_deployed_body()
    print("$00D3F6 MOVE.B/BLE byte N/Z regression: PASS")


if __name__ == "__main__":
    main()
