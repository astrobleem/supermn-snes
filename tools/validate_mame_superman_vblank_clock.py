#!/usr/bin/env python3
"""Reduce the exact MAME Superman screen clock to an integer timer contract.

The source file is a development-only audit input.  The result deliberately
contains only public machine-clock constants and derived fractions, never ROM
content.  Pair it with the executable Stage-3 trace; this tool proves the
nominal vblank deadline, whereas the trace proves the instruction boundary at
which a pending level-6 IRQ is actually serviced.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from fractions import Fraction
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--driver", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not args.driver.is_file():
        parser.error(f"missing MAME Taito X driver: {args.driver}")
    if args.output.exists():
        parser.error(f"output already exists: {args.output}")
    source = args.driver.read_text(encoding="utf-8", errors="replace")
    required = (
        "M68000(config, m_maincpu, 16_MHz_XTAL / 2);   // verified on PCB",
        'm_maincpu->set_vblank_int("screen", FUNC(taitox_cchip_state::interrupt));',
        "screen.set_refresh_hz(57.43);",
        "m_maincpu->set_input_line(6, HOLD_LINE);",
    )
    if any(line not in source for line in required):
        raise RuntimeError("MAME Superman vblank/clock declaration changed")
    cpu_hz = Fraction(16_000_000, 2)
    refresh_hz = Fraction("57.43")
    cycles = cpu_hz / refresh_hz
    two_cycle_units = cycles / 2
    four_cycle_units = cycles / 4
    report = {
        "scope": (
            "read-only MAME 0.287 Superman nominal-vblank clock reduction; "
            "not an IRQ-service trace, SNES repair, rate result, or playthrough claim"
        ),
        "driver": {"path": str(args.driver.resolve()), "sha256": sha256(args.driver)},
        "hardware": {
            "m68000_hz": int(cpu_hz),
            "screen_refresh_hz": str(refresh_hz),
            "vblank_irq_line": 6,
            "delivery": "HOLD_LINE",
        },
        "deadline": {
            "m68000_cycles": {
                "fraction": f"{cycles.numerator}/{cycles.denominator}",
                "integer_cycles": cycles.numerator // cycles.denominator,
                "remainder_numerator": cycles.numerator % cycles.denominator,
                "remainder_denominator": cycles.denominator,
            },
            "two_cycle_units": {
                "fraction": f"{two_cycle_units.numerator}/{two_cycle_units.denominator}",
                "integer_units": two_cycle_units.numerator // two_cycle_units.denominator,
                "remainder_numerator": two_cycle_units.numerator % two_cycle_units.denominator,
                "remainder_denominator": two_cycle_units.denominator,
            },
            "four_cycle_units": {
                "fraction": f"{four_cycle_units.numerator}/{four_cycle_units.denominator}",
                "integer_units": four_cycle_units.numerator // four_cycle_units.denominator,
                "remainder_numerator": four_cycle_units.numerator % four_cycle_units.denominator,
                "remainder_denominator": four_cycle_units.denominator,
            },
        },
        "timer_requirement": (
            "A fixed 139300-cycle (69650 two-cycle-unit) reload is only the integer "
            "baseline. Preserve the 50/5743 two-cycle-unit phase remainder and service "
            "a pending IRQ on the next completed MC68000 instruction boundary."
        ),
        "result": "green",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"result": "green", "output": str(args.output)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
