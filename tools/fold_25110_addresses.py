#!/usr/bin/env python3
"""Fold bounded $025110 work-RAM displacements into long-indexed operands.

The guarded native collision body in ``src/escbank3.pasm`` requires
``A5 == $00F00000`` and derives A0-A3 from fixed offsets below $4000.  Its
generated EA lowering nevertheless materializes every small displacement with
four instructions before accessing bank-$40 work RAM::

    lda $20
    clc
    adc #$000A
    tax
    lda $400000,x

For those proven-bounded registers, the 65816 long-indexed operand can carry
the displacement directly::

    ldx $20
    lda $40000A,x

This is a deliberately function-specific post-pass.  It refuses to touch any
other body, variable displacement, stack/frame pointer, negative displacement,
or sequence whose first X-based memory operation is not the expected bank-$40
access.  Run without ``--write`` for a count-only dry run.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / "src/escbank3.pasm"
START = "entry_25110:\n"
END = "    .org $A800\n"
BOUNDED_LO_DPS = {"20", "24", "28", "2C", "34"}

PREP_RE = re.compile(
    r"^    lda \$(20|24|28|2C|34)\n"
    r"    clc\n"
    r"    adc #\$([0-9A-F]{4})\n"
    r"    tax\n",
    re.MULTILINE,
)
MEM_RE = re.compile(r"\$(400000),x")


def fold(body: str) -> tuple[str, int]:
    out: list[str] = []
    cursor = 0
    count = 0
    for match in PREP_RE.finditer(body):
        out.append(body[cursor : match.start()])
        dp, raw_disp = match.groups()
        if dp not in BOUNDED_LO_DPS:
            raise RuntimeError(f"unexpected bounded DP ${dp}")
        disp = int(raw_disp, 16)
        if disp == 0:
            raise RuntimeError("zero displacement should already lower to LDX")
        if dp != "34" and disp > 0x00FF:
            raise RuntimeError(
                f"non-A5 displacement ${disp:04X} exceeds bounded object field"
            )
        if dp == "34" and disp >= 0x4000:
            raise RuntimeError(f"A5 displacement ${disp:04X} leaves mapped 16 KiB")

        # Generated stores can have PLA/SEP/XBA between TAX and the memory op.
        # There must be exactly one nearby bank-$40 X access and no intervening
        # label or X replacement; otherwise the lowering shape has changed.
        tail_start = match.end()
        following = body[tail_start:].splitlines(keepends=True)
        memory_line = None
        byte_count = 0
        for line_index, line in enumerate(following[:8]):
            if line_index and (not line.startswith("    ") or line.lstrip().startswith(("tax", "ldx"))):
                break
            byte_count += len(line)
            if "$400000,x" in line:
                memory_line = line_index
                break
        if memory_line is None:
            context = "".join(following[:8])
            raise RuntimeError(
                f"no immediate bank-$40 access after ${dp}+${disp:04X}:\n{context}"
            )

        window = "".join(following[: memory_line + 1])
        if len(MEM_RE.findall(window)) != 1:
            raise RuntimeError(
                f"ambiguous bank-$40 access after ${dp}+${disp:04X}:\n{window}"
            )
        folded_addr = f"${0x400000 + disp:06X},x"
        window = MEM_RE.sub(folded_addr, window, count=1)
        out.append(f"    ldx ${dp}\n")
        out.append(window)
        cursor = tail_start + len("".join(following[: memory_line + 1]))
        count += 1

    out.append(body[cursor:])
    return "".join(out), count


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--write", action="store_true")
    parser.add_argument(
        "--expect",
        type=int,
        help="fail unless exactly this many address sequences are foldable",
    )
    args = parser.parse_args()

    source = args.source.read_text(encoding="utf-8")
    try:
        prefix, rest = source.split(START, 1)
        body, suffix = rest.split(END, 1)
    except ValueError as exc:
        raise SystemExit("could not isolate entry_25110 body") from exc
    folded, count = fold(body)
    if args.expect is not None and count != args.expect:
        raise SystemExit(f"expected {args.expect} folds, found {count}")
    print(f"fold_25110_addresses: {count} bounded displacements")
    if args.write:
        args.source.write_text(prefix + START + folded + END + suffix, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
