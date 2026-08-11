#!/usr/bin/env python3
"""Regression for signed address displacements in native MC68000 bodies.

LINK and LEA add a sign-extended 16-bit displacement to a 32-bit address.
The low-word carry therefore feeds ``#$FFFF`` for a negative displacement,
not ``#$0000``.  A stale $0046DE body used the latter and changed task 0's
saved stack bank from $F0 to $F1 during the game-over transition.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROGRAM = ROOT / "data/superman_m68k.bin"


def meaningful_lines(text: str) -> list[str]:
    return [
        line.strip()
        for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith(";")
    ]


def require_contiguous(
    lines: list[str],
    expected: list[str],
    context: str,
) -> None:
    for index in range(len(lines) - len(expected) + 1):
        if lines[index : index + len(expected)] == expected:
            return
    raise AssertionError(
        f"{context} does not contain the required sequence:\n"
        + "\n".join(expected)
    )


def transpile(entry: str, *flags: str) -> str:
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools/transpile.py"),
            entry,
            *flags,
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    assert "all " in result.stderr and "instrs transpiled" in result.stderr
    return result.stdout


def check_arcade_instructions() -> None:
    program = PROGRAM.read_bytes()
    assert program[0x46DE : 0x46E2] == bytes.fromhex("4E56FFFA")
    assert program[0x4A9E : 0x4AA2] == bytes.fromhex("4E56FFFC")
    assert program[0xD086 : 0xD08A] == bytes.fromhex("47EEFF1E")
    assert program[0xD090 : 0xD094] == bytes.fromhex("47EEFF1C")


def check_link_body(
    generated: str,
    deployed: str,
    displacement: str,
    context: str,
) -> None:
    expected = [
        "lda $3C",
        "clc",
        f"adc #${displacement}",
        "sta $3C",
        "lda $3E",
        "adc #$FFFF",
        "sta $3E",
    ]
    require_contiguous(meaningful_lines(generated), expected, f"generated {context}")
    require_contiguous(meaningful_lines(deployed), expected, f"deployed {context}")


def check_lea_body(generated: str, deployed: str) -> None:
    lines_generated = meaningful_lines(generated)
    lines_deployed = meaningful_lines(deployed)
    for displacement in ("FF1E", "FF1C"):
        expected = [
            "lda $38",
            "clc",
            f"adc #${displacement}",
            "sta $2C",
            "lda $3A",
            "adc #$FFFF",
            "sta $2E",
        ]
        require_contiguous(
            lines_generated,
            expected,
            f"generated $00D07A LEA #${displacement}",
        )
        require_contiguous(
            lines_deployed,
            expected,
            f"deployed $00D07A LEA #${displacement}",
        )


def check_32bit_model() -> None:
    for base in (0x00F00000, 0x00F00002, 0x00F015BC, 0xFFFFFFFF):
        for displacement in (-0xE4, -6, -4, -1):
            low = (base & 0xFFFF) + (displacement & 0xFFFF)
            carry = int(low > 0xFFFF)
            high = ((base >> 16) + 0xFFFF + carry) & 0xFFFF
            observed = (high << 16) | (low & 0xFFFF)
            expected = (base + displacement) & 0xFFFFFFFF
            assert observed == expected, (base, displacement, observed, expected)


def main() -> None:
    check_arcade_instructions()
    check_32bit_model()

    generated_46de = transpile(
        "46DE",
        "--bank5",
        "--fnfrag",
        "--coroutine",
        "--xflag",
    )
    deployed_46de = (ROOT / "src/escbank5.pasm").read_text(encoding="utf-8")
    check_link_body(
        generated_46de,
        deployed_46de,
        "FFFA",
        "$0046DE LINK A6,#-6",
    )

    generated_4a9e = transpile("4A9E", "--bank5", "--bail", "--xflag")
    check_link_body(
        generated_4a9e,
        deployed_46de,
        "FFFC",
        "$004A9E LINK A6,#-4",
    )

    generated_d07a = transpile(
        "D07A",
        "--bank2",
        "--coroutine",
        "--bail",
        "--xflag",
    )
    deployed_d07a = (ROOT / "src/escbank2.pasm").read_text(encoding="utf-8")
    check_lea_body(generated_d07a, deployed_d07a)

    print("negative address-displacement sign extension regression: PASS")


if __name__ == "__main__":
    main()
