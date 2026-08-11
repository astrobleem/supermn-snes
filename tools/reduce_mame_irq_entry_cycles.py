#!/usr/bin/env python3
"""Separate completed-instruction and level-6 entry costs in a MAME trace."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TRACE = (
    ROOT / "build/mame-stage3-irq-phase-current-5c7e-v1/trace/m68k.log"
)
DEFAULT_PROGRAM = ROOT / "data/superman_m68k.bin"
DEFAULT_TABLE = ROOT / "src/m68k_cpu000_static_cycles.bin"
DEFAULT_M68000 = Path(
    "/home/chad/snes-outrun-sa1/build/road_instrumented_mame_trace/step123/"
    "source/mame-mame0287/src/devices/cpu/m68000/m68000.cpp"
)
DEFAULT_DRIVER = Path(
    "/home/chad/snes-outrun-sa1/build/road_instrumented_mame_trace/step123/"
    "source/mame-mame0287/src/mame/taito/taito_x.cpp"
)
STATE = re.compile(
    r"^M68K_STATE ([0-9A-F]+).*\| ([0-9A-F]{6}): (.*)$"
)
INTERRUPT = re.compile(r"\(interrupted at ([0-9A-F]{6}), IRQ ([0-7])\)")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace", type=Path, default=DEFAULT_TRACE)
    parser.add_argument("--program", type=Path, default=DEFAULT_PROGRAM)
    parser.add_argument("--cycle-table", type=Path, default=DEFAULT_TABLE)
    parser.add_argument("--m68000-source", type=Path, default=DEFAULT_M68000)
    parser.add_argument("--driver", type=Path, default=DEFAULT_DRIVER)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    for label, path in (
        ("trace", args.trace),
        ("program", args.program),
        ("cycle table", args.cycle_table),
        ("M68000 source", args.m68000_source),
        ("driver", args.driver),
    ):
        if not path.is_file():
            parser.error(f"missing {label}: {path}")
    if args.output.exists():
        parser.error(f"output already exists: {args.output}")
    return args


def main() -> int:
    args = parse_args()
    program = args.program.read_bytes()
    cycles = args.cycle_table.read_bytes()
    if len(program) != 0x80000 or len(cycles) != 0x10000:
        raise RuntimeError("unexpected program or CPU-000 cycle-table size")

    previous_state: dict[str, object] | None = None
    pending: dict[str, object] | None = None
    rows: list[dict[str, object]] = []
    with args.trace.open(encoding="utf-8", errors="replace") as stream:
        for line_number, line in enumerate(stream, 1):
            state = STATE.match(line)
            if state:
                current = {
                    "line": line_number,
                    "cycle": int(state.group(1), 16),
                    "pc": int(state.group(2), 16),
                    "asm": state.group(3),
                }
                if pending is not None:
                    if previous_state is None:
                        raise RuntimeError("interrupt marker has no preceding state")
                    opcode = int.from_bytes(
                        program[
                            int(previous_state["pc"]):
                            int(previous_state["pc"]) + 2
                        ],
                        "big",
                    )
                    instruction_cycles = cycles[opcode]
                    full_interval = int(current["cycle"]) - int(
                        previous_state["cycle"]
                    )
                    entry_cycles = full_interval - instruction_cycles
                    completed_cycle = (
                        int(previous_state["cycle"]) + instruction_cycles
                    )
                    completed_cycle_mod10 = completed_cycle % 10
                    vpa_sync_cycles = (
                        10 - completed_cycle_mod10
                        if completed_cycle_mod10 < 7
                        else 20 - completed_cycle_mod10
                    )
                    vpa_after_cycles = 1
                    modeled_entry_cycles = (
                        44 + vpa_sync_cycles + vpa_after_cycles
                    )
                    rows.append(
                        {
                            "interrupted_pc": f"{int(pending['pc']):06X}",
                            "irq_level": int(pending["level"]),
                            "preceding_instruction": {
                                "line": int(previous_state["line"]),
                                "pc": f"{int(previous_state['pc']):06X}",
                                "opcode": f"{opcode:04X}",
                                "asm": str(previous_state["asm"]),
                                "cycles": instruction_cycles,
                                "start_cycle": int(previous_state["cycle"]),
                                "start_cycle_mod10": (
                                    int(previous_state["cycle"]) % 10
                                ),
                                "completed_cycle": completed_cycle,
                                "completed_cycle_mod10": completed_cycle_mod10,
                            },
                            "first_isr_instruction": {
                                "line": int(current["line"]),
                                "pc": f"{int(current['pc']):06X}",
                                "asm": str(current["asm"]),
                            },
                            "full_preceding_instruction_to_isr_cycles": full_interval,
                            "entry_only_cycles": entry_cycles,
                            "entry_only_two_cycle_units": entry_cycles // 2,
                            "entry_minus_cpu000_autovector_44_cycles": (
                                entry_cycles - 44
                            ),
                            "vpa_model": {
                                "sync_cycles": vpa_sync_cycles,
                                "after_cycles": vpa_after_cycles,
                                "modeled_entry_cycles": modeled_entry_cycles,
                                "first_isr_cycle_mod10": (
                                    int(current["cycle"]) % 10
                                ),
                            },
                        }
                    )
                    pending = None
                previous_state = current
                continue
            interrupt = INTERRUPT.search(line)
            if interrupt:
                pending = {
                    "pc": int(interrupt.group(1), 16),
                    "level": int(interrupt.group(2)),
                }

    expected = [
        ("000818", "60FE", 10, 66, 56),
        ("0259B0", "6E00", 10, 64, 54),
        ("02582E", "4A68", 12, 68, 56),
        ("000810", "027C", 20, 76, 56),
    ]
    actual = [
        (
            row["interrupted_pc"],
            row["preceding_instruction"]["opcode"],
            row["preceding_instruction"]["cycles"],
            row["full_preceding_instruction_to_isr_cycles"],
            row["entry_only_cycles"],
        )
        for row in rows
    ]
    if actual != expected:
        raise RuntimeError(
            f"retained level-6 entry decomposition changed: {actual!r}"
        )
    if any(row["irq_level"] != 6 for row in rows):
        raise RuntimeError("retained trace contains a non-level-6 interruption")
    if any(
        row["entry_only_cycles"]
        != row["vpa_model"]["modeled_entry_cycles"]
        for row in rows
    ):
        raise RuntimeError("retained IRQ entry does not match the MAME VPA model")
    if any(row["vpa_model"]["first_isr_cycle_mod10"] != 5 for row in rows):
        raise RuntimeError("retained MAME VPA entry did not normalize to phase 5")

    m68000_source = args.m68000_source.read_text(encoding="utf-8")
    driver_source = args.driver.read_text(encoding="utf-8")
    source_checks = {
        "active_device_is_m68000": (
            "M68000(config, m_maincpu, 16_MHz_XTAL / 2);" in driver_source
        ),
        "driver_asserts_level6_hold_line": (
            "m_maincpu->set_input_line(6, HOLD_LINE);" in driver_source
        ),
        "autovector_uses_vpa_before_time": (
            "before_time(*this, FUNC(m68000_device::vpa_sync))" in m68000_source
        ),
        "autovector_uses_vpa_after_delay": (
            "after_delay(*this, FUNC(m68000_device::vpa_after))" in m68000_source
        ),
        "vpa_is_ten_clock_phase_dependent": all(
            text in m68000_source
            for text in (
                "u64 mod = current_time % 10;",
                "if(mod < 7)",
                "current_time - mod + 10",
                "current_time - mod + 20",
                "return 1;",
            )
        ),
    }
    if not all(source_checks.values()):
        raise RuntimeError(f"MAME VPA/driver source contract changed: {source_checks}")

    entry_costs = [int(row["entry_only_cycles"]) for row in rows]
    report = {
        "scope": (
            "disk-only decomposition of four retained MAME 0.287 level-6 "
            "intervals; instruction costs come from the authenticated CPU-000 "
            "table and entry totals retain M68000 VPA phase delay; no emulator "
            "run, SNES state write, source edit, or ROM claim"
        ),
        "identity": {
            label: {"path": str(path.resolve()), "sha256": sha256(path)}
            for label, path in (
                ("trace", args.trace),
                ("program", args.program),
                ("cycle_table", args.cycle_table),
                ("m68000_source", args.m68000_source),
                ("driver", args.driver),
            )
        },
        "source_checks": source_checks,
        "interruptions": rows,
        "entry_only_cycles": entry_costs,
        "entry_only_two_cycle_units": [cost // 2 for cost in entry_costs],
        "vpa_phase_delay_cycles_above_44": [cost - 44 for cost in entry_costs],
        "phase_rule": {
            "completed_instruction_cycle_mod10": [1, 3, 5, 7, 9],
            "exception_entry_two_cycle_units": [27, 26, 25, 29, 28],
            "first_isr_cycle_mod10": 5,
        },
        "conclusion": (
            "The observed 66-cycle $000818->$0006C4 interval is composite: "
            "10 cycles for BRA $0818 plus a 56-cycle entry. Across the four "
            "retained IRQs, entry alone is phase-dependent 54/56 cycles "
            "(27/28 timer units); a fixed 33-unit exception-entry charge is false."
        ),
        "result": "green",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "entry_only_cycles": entry_costs,
                "output": str(args.output),
                "result": "green",
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
