#!/usr/bin/env python3
"""Regression for rejecting late native-gate changes in an in-flight handler."""

from __future__ import annotations

from argparse import Namespace

from trace_player_native_tick import (
    gate_mutation_requested,
    native_escape_in_flight,
    sa1_program_counter,
)


def requests(**overrides: str) -> Namespace:
    values = {
        "xlat_gate": "preserve",
        "choke_gate": "preserve",
        "scheduler_gates": "preserve",
        "loop_gate": "preserve",
        "pacing_gate": "preserve",
    }
    values.update(overrides)
    return Namespace(**values)


def main() -> int:
    assert sa1_program_counter({"k": 0x92, "pc": 0xD02A}) == 0x92D02A
    assert native_escape_in_flight({"k": 0x92, "pc": 0xD02A})
    assert native_escape_in_flight({"k": 0x9F, "pc": 0x8000})
    assert not native_escape_in_flight({"k": 0x00, "pc": 0xD16F})
    assert not native_escape_in_flight({"k": 0xC1, "pc": 0x8000})
    assert not gate_mutation_requested(requests())
    assert gate_mutation_requested(requests(xlat_gate="off"))
    assert gate_mutation_requested(requests(scheduler_gates="on"))
    print("trace native-gate state regression: green")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
