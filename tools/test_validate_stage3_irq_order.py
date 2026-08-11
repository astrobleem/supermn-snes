#!/usr/bin/env python3
"""Pure regression for Stage-3 IRQ-order result classification."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "tools" / "validate_stage3_irq_order.py"
SPEC = importlib.util.spec_from_file_location("validate_stage3_irq_order", TARGET)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot import {TARGET}")
module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)


def row(tick: int, *, mame_off: bool, mame_on: bool, off_on: bool, regions: bool) -> dict:
    return {
        "mame_tick": tick,
        "checks": {
            "task15_frame_mame_native_off": mame_off,
            "task15_frame_mame_native_on": mame_on,
            "task15_frame_native_off_native_on": off_on,
            "game_regions_exact": regions,
        },
    }


def main() -> None:
    valid = {"same_rom": True, "same_state": True}
    tick, kind = module.classify_result(
        valid,
        [
            row(14745, mame_off=True, mame_on=True, off_on=True, regions=True),
            row(14746, mame_off=False, mame_on=False, off_on=True, regions=False),
        ],
    )
    if (tick, kind) != (14746, "hardware-boundary/virtual-IRQ timing"):
        raise AssertionError((tick, kind))
    tick, kind = module.classify_result(
        valid,
        [row(7, mame_off=False, mame_on=True, off_on=False, regions=False)],
    )
    if (tick, kind) != (7, "unclassified-three-way divergence"):
        raise AssertionError((tick, kind))
    tick, kind = module.classify_result(
        {"same_rom": False},
        [row(7, mame_off=False, mame_on=False, off_on=True, regions=False)],
    )
    if (tick, kind) != (None, "invalid-comparison-input"):
        raise AssertionError((tick, kind))
    tick, kind = module.classify_result(valid, [row(7, mame_off=True, mame_on=True, off_on=True, regions=True)])
    if (tick, kind) != (None, None):
        raise AssertionError((tick, kind))
    print("Stage-3 IRQ-order classification regression: green")


if __name__ == "__main__":
    main()
