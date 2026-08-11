#!/usr/bin/env python3
"""Guard the native $012C1A player-action selector against stale codegen.

The organic tick-8446 failure entered with ``D2=$00000100`` and loaded
``A4+$06=$73`` using MOVE.B.  A 68000 MOVE.B preserves D2.bits8-31, while the
following CMP.B instructions consume only D2.bits0-7.  The old checked-in
bank-$97 body consequently held ``D2.w=$0173`` but subtracted ``#$0073`` in
16-bit 65816 accumulator mode, missed the arcade-equal branch, and left D7
zero instead of selecting $0120A8.

This validator authenticates the arcade instructions, requires an explicit
8-bit SEP/SBC/REP seam for every CMP.B, and—most importantly—requires the
entire deployed body to equal a fresh ``tools/transpile.py --bank3`` result.
That parity check prevents pinned native source from silently missing later
semantic code-generator repairs.
"""

from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
from pathlib import Path

import capstone


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / "src" / "escbank3.pasm"
DEFAULT_PROGRAM = ROOT / "data" / "superman_m68k.bin"
DEFAULT_TRANSPILE = ROOT / "tools" / "transpile.py"
PROGRAM_SHA256 = (
    "6aa9c5b5b55e1545b4da7c2c8610ea01addb096101a667db3f86441d454d197e"
)
BODY_START = "; --- transpiled from $012C1A"
BODY_END = "; --- entry_12a92"
CMP_IMMEDIATES = {
    0x012C44: 0x67,
    0x012C4A: 0x73,
    0x012C50: 0x76,
    0x012C56: 0x69,
    0x012D04: 0x6B,
}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def isolate_body(source: str) -> str:
    try:
        _prefix, tail = source.split(BODY_START, 1)
        body, _suffix = tail.split(BODY_END, 1)
    except ValueError as exc:
        raise AssertionError("could not isolate deployed $012C1A body") from exc
    return (BODY_START + body).rstrip() + "\n"


def validate_arcade(program: bytes) -> None:
    assert len(program) == 0x80000, (
        f"expected 512-KiB arcade program, got {len(program)} bytes"
    )
    assert sha256(program) == PROGRAM_SHA256, (
        "arcade program image is not the authenticated Superman World input"
    )
    md = capstone.Cs(
        capstone.CS_ARCH_M68K,
        capstone.CS_MODE_BIG_ENDIAN,
    )

    move = next(md.disasm(program[0x012C40 : 0x012C48], 0x012C40), None)
    assert move is not None
    assert move.mnemonic == "move.b" and move.op_str == "$6(a4), d2", (
        f"$012C40 changed: {move.mnemonic} {move.op_str}"
    )

    for pc, immediate in CMP_IMMEDIATES.items():
        instruction = next(md.disasm(program[pc : pc + 8], pc), None)
        assert instruction is not None
        expected = f"#$%x, d2" % immediate
        assert (
            instruction.mnemonic == "cmpi.b"
            and instruction.op_str == expected
        ), (
            f"${pc:06X}: expected cmpi.b {expected}, got "
            f"{instruction.mnemonic} {instruction.op_str}"
        )


def generate(transpile: Path) -> str:
    result = subprocess.run(
        [
            sys.executable,
            str(transpile),
            "12c1a",
            "--bank3",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        sys.stderr.write(result.stdout)
        sys.stderr.write(result.stderr)
        raise AssertionError("$012C1A transpilation failed")
    assert "all 80 instrs transpiled" in result.stderr, (
        "transpiler did not report a complete 80-instruction body"
    )
    return result.stdout.rstrip() + "\n"


def validate_byte_compares(body: str) -> None:
    for immediate in CMP_IMMEDIATES.values():
        seam = (
            "    lda $08\n"
            "    sep #$20\n"
            "    sec\n"
            f"    sbc #${immediate:02X}\n"
            "    rep #$20\n"
        )
        assert body.count(seam) == 1, (
            f"expected one 8-bit CMP.B seam for #${immediate:02X}"
        )
        assert f"sbc #$00{immediate:02X}" not in body, (
            f"stale 16-bit CMP.B lowering remains for #${immediate:02X}"
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--program", type=Path, default=DEFAULT_PROGRAM)
    parser.add_argument("--transpile", type=Path, default=DEFAULT_TRANSPILE)
    args = parser.parse_args()

    program = args.program.read_bytes()
    source = args.source.read_text(encoding="utf-8")
    deployed = isolate_body(source)
    generated = generate(args.transpile)

    validate_arcade(program)
    validate_byte_compares(generated)
    assert deployed == generated, (
        "deployed $012C1A differs from fresh --bank3 output; regenerate the "
        "complete pinned body before shipping"
    )
    print(
        "validate_12c1a_native: 5/5 CMP.B byte-width seams, "
        "80/80 instructions, deployed/generated parity GREEN"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
