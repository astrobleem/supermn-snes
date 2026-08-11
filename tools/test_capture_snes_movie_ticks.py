#!/usr/bin/env python3
"""Regression for bounded exact-edge batching in all-native-off captures."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CAPTURE = ROOT / "tools" / "capture_snes_movie_ticks.py"
SPEC = importlib.util.spec_from_file_location("capture_snes_movie_ticks", CAPTURE)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot import {CAPTURE}")
module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)


def main() -> None:
    if module.interpreted_entry_batch_counts(0) != []:
        raise AssertionError("zero entries must not issue an exact-stop request")
    if module.interpreted_entry_batch_counts(8) != [8]:
        raise AssertionError("batch boundary changed")
    if module.interpreted_entry_batch_counts(95) != [8] * 11 + [7]:
        raise AssertionError("large interpreted run is not safely bounded")
    try:
        module.interpreted_entry_batch_counts(-1)
    except ValueError:
        pass
    else:
        raise AssertionError("negative entry request was accepted")
    print("capture native-off exact-edge batching regression: green")


if __name__ == "__main__":
    main()
