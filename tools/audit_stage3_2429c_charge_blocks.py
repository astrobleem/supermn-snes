#!/usr/bin/env python3
"""Reduce the live Stage-3 `$02429C` bridge to exact future clock blocks.

The tick-14,746 IRQ-order failure enters this native coroutine root.  Before
it can participate in the shared virtual clock, its own original CPU-000
blocks must be separated from the child call routes it dispatches.  This is a
read-only source/ROM-derived ledger audit: it neither patches an escape nor
claims that the root's children, scheduler, renderer, or pacing already share
the clock.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

import audit_stage3_player_charge_blocks as common


ROOT = Path(__file__).resolve().parents[1]
ENTRY = 0x02429C
EXPECTED_TOTALS = {
    "logical_instructions": 78,
    "basic_blocks": 35,
    "static_two_cycle_units_once_each": 520,
    "dynamic_terminal_control_flow": 14,
}
CHILD_HANDOFFS = {
    0x0242A6: "023342",
    0x0242AC: "023E34",
    0x0242B2: "0235E0",
    0x0242B8: "025110",
    0x0242BE: "0259CA",
    0x024302: "0243E8",
    0x024330: "0243E8",
    0x02436C: "indirect-A0",
    0x024374: "02443A",
    0x0243B0: "0243E8",
    0x0243D6: "0244D4",
}
CHILD_ROUTE = {
    "023342": "native-entry_23342-bank98",
    "023E34": "native-entry_23e34-bank99",
    "0235E0": "native-entry_235e0-bank98",
    "025110": "native-entry_25110-bank97",
    "0259CA": "native-entry_259ca-bank99",
    "0243E8": "interpreter-xlat-miss",
    "02443A": "interpreter-xlat-miss",
    "0244D4": "interpreter-xlat-miss",
    "indirect-A0": "dynamic-indirect-dispatch",
}
CHILD_ENTRIES = (
    (0x023342, "023342"),
    (0x023E34, "023E34"),
    (0x0235E0, "0235E0"),
    (0x025110, "025110"),
    (0x0259CA, "0259CA"),
    (0x0243E8, "0243E8"),
    (0x02443A, "02443A"),
    (0x0244D4, "0244D4"),
)
EXPECTED_CHILD_SHAPES = {
    "023342": (7, 4, 48),
    "023E34": (4, 2, 27),
    "0235E0": (38, 16, 235),
    "025110": (545, 226, 3064),
    "0259CA": (21, 7, 147),
    "0243E8": (22, 8, 140),
    "02443A": (37, 8, 246),
    "0244D4": (15, 7, 118),
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def child_inventory(transpiler: Any, cycles: bytes) -> list[dict[str, Any]]:
    """Describe direct original children without pretending they are charged.

    Static opcode costs are deliberately reported before MOVEM mask and shift
    adjustments.  A prospective native ledger must derive those adjustments
    from the actual original instruction/extensions, then prove its terminal
    state rule; a parent-only total would be an invalid common-clock charge.
    """
    rows: list[dict[str, Any]] = []
    for entry, key in CHILD_ENTRIES:
        instructions, _ = transpiler.decode(entry)
        blocks = common.basic_blocks(transpiler, entry)
        static_units = 0
        dynamic_kinds: Counter[str] = Counter()
        nonterminal_dynamic: list[dict[str, str]] = []
        for block in blocks:
            for position, instruction in enumerate(block):
                opcode = int.from_bytes(bytes(instruction.bytes[:2]), "big")
                raw_cycles = cycles[opcode]
                if raw_cycles == 0 or raw_cycles & 1:
                    raise RuntimeError(
                        f"invalid timing in child ${entry:06X} at "
                        f"${instruction.address:06X}"
                    )
                static_units += raw_cycles // 2
                kind = common.timing_kind(instruction)
                if kind is None:
                    continue
                dynamic_kinds[kind] += 1
                if position != len(block) - 1:
                    nonterminal_dynamic.append(
                        {
                            "pc": f"{instruction.address:06X}",
                            "mnemonic": instruction.mnemonic,
                            "kind": kind,
                        }
                    )
        observed = (len(instructions), len(blocks), static_units)
        if observed != EXPECTED_CHILD_SHAPES[key]:
            raise RuntimeError(
                f"$02429C child ${key} timing shape changed: {observed}"
            )
        rows.append(
            {
                "entry_pc": key,
                "logical_instructions": observed[0],
                "basic_blocks": observed[1],
                "static_two_cycle_units_once_each_before_adjustments": observed[2],
                "dynamic_kind_counts": dict(sorted(dynamic_kinds.items())),
                "nonterminal_dynamic_instructions": nonterminal_dynamic,
            }
        )
    return rows


def collect() -> dict[str, Any]:
    transpiler = common.load_transpiler()
    cycles = common.CYCLES.read_bytes()
    children = child_inventory(transpiler, cycles)
    blocks = common.basic_blocks(transpiler, ENTRY)
    records: list[dict[str, Any]] = []
    child_handoffs: list[dict[str, str]] = []
    dynamic_count = 0
    total_units = 0
    for ordinal, block in enumerate(blocks, 1):
        static_cycles = 0
        dynamic: list[dict[str, str]] = []
        for position, instruction in enumerate(block):
            opcode = int.from_bytes(bytes(instruction.bytes[:2]), "big")
            raw_cycles = cycles[opcode]
            if raw_cycles == 0 or raw_cycles & 1:
                raise RuntimeError(
                    f"invalid static CPU-000 timing at ${instruction.address:06X}: "
                    f"opcode=${opcode:04X} cycles={raw_cycles}"
                )
            static_cycles += raw_cycles
            kind = common.timing_kind(instruction)
            if kind is None:
                continue
            if kind != "conditional_branch_or_loop" or position != len(block) - 1:
                raise RuntimeError(
                    f"$02429C block {ordinal} has unsupported {kind} at "
                    f"${instruction.address:06X}; split or derive a dedicated rule"
                )
            dynamic.append(
                {
                    "pc": f"{instruction.address:06X}",
                    "mnemonic": instruction.mnemonic,
                    "operands": instruction.op_str,
                    "kind": kind,
                }
            )
        units = static_cycles // 2
        total_units += units
        dynamic_count += len(dynamic)
        terminal = block[-1]
        target = CHILD_HANDOFFS.get(terminal.address)
        if target is not None:
            child_handoffs.append(
                {
                    "call_pc": f"{terminal.address:06X}",
                    "mnemonic": terminal.mnemonic,
                    "operands": terminal.op_str,
                    "target": target,
                    "route": CHILD_ROUTE[target],
                }
            )
        records.append(
            {
                "ordinal": ordinal,
                "original_start_pc": f"{block[0].address:06X}",
                "original_end_pc_exclusive": f"{terminal.address + terminal.size:06X}",
                "logical_instruction_count": len(block),
                "static_two_cycle_units": units,
                "terminal": {
                    "pc": f"{terminal.address:06X}",
                    "mnemonic": terminal.mnemonic,
                    "operands": terminal.op_str,
                },
                "dynamic_terminal_control_flow": dynamic,
            }
        )
    totals = {
        "logical_instructions": sum(row["logical_instruction_count"] for row in records),
        "basic_blocks": len(records),
        "static_two_cycle_units_once_each": total_units,
        "dynamic_terminal_control_flow": dynamic_count,
    }
    if totals != EXPECTED_TOTALS:
        raise RuntimeError(f"$02429C timing shape changed: {totals}")
    if len(child_handoffs) != len(CHILD_HANDOFFS):
        raise RuntimeError(
            "$02429C child handoff inventory changed: " f"{child_handoffs}"
        )
    if any(item["route"] != CHILD_ROUTE[item["target"]] for item in child_handoffs):
        raise RuntimeError("$02429C child route classification drifted")
    return {
        "scope": (
            "read-only exact CPU-000 block inventory for native Stage-3 root "
            "$02429C; one execution does not traverse every listed block, and "
            "the child calls remain unadmitted to the common clock"
        ),
        "inputs": {
            "transpiler": str((ROOT / "tools/transpile.py").resolve()),
            "static_cycles": {
                "path": str(common.CYCLES.resolve()),
                "sha256": sha256(common.CYCLES),
            },
            "native_source": {
                "path": str((ROOT / "src/escbank5.pasm").resolve()),
                "sha256": sha256(ROOT / "src/escbank5.pasm"),
            },
        },
        "entry_pc": f"{ENTRY:06X}",
        "totals": totals,
        "blocks": records,
        "unadmitted_child_handoff_sites": child_handoffs,
        "unadmitted_direct_child_inventory": children,
        "conclusion": (
            "The root can be charged only as deferred original basic blocks: "
            "all 14 path-dependent instructions are terminal Bcc/DBcc and use "
            "the existing post-block CCR/Dn rule. Its eleven JSR/BSR/indirect "
            "child handoff sites require explicit ownership/return handoff before "
            "any VTIME enable."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error(f"refusing to overwrite output: {args.output}")
    for path in (common.CYCLES, ROOT / "src/escbank5.pasm"):
        if not path.is_file():
            parser.error(f"missing required input: {path}")
    report = collect()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"entry_pc": report["entry_pc"], "output": str(args.output), "totals": report["totals"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
