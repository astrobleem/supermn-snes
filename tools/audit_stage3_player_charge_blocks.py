#!/usr/bin/env python3
"""Audit the active Stage-3 player-native blocks before VTIME can charge them.

The retained tick-14,743 production trace enters six bank-$9F player handlers.
Their ``esc9_ac_charge`` calls currently debit the legacy instruction timer.
This read-only reducer proves the generated charge sites still correspond to
the original MC68000 basic blocks, and separates terminal dynamic timing from
immediate shift adjustments that can be folded into a future block-cost table.

It deliberately refuses to call a generic ``b*`` mnemonic a conditional
branch: BSR/BRA are static, and BTST/BCLR/BSET are bit operations.  Treating
those as Bcc would corrupt a deferred native-cycle ledger.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
from pathlib import Path
from types import ModuleType
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src" / "escbank9.pasm"
BINARY = ROOT / "src" / "escbank9.bin"
SYMBOLS = ROOT / "src" / "escbank9.sym"
CYCLES = ROOT / "src" / "m68k_cpu000_static_cycles.bin"

SPECS = (
    (0x013282, "entry_13282t", "entry_13282t_end", 32, 9),
    (0x013314, "entry_13314t", "entry_13314t_end", 23, 9),
    (0x01337E, "entry_1337et", "entry_1337et_end", 32, 9),
    (0x0133EA, "entry_133eat", "entry_133eat_end", 37, 17),
    (0x013468, "entry_13468t", "entry_13468t_end", 64, 24),
    (0x013538, "entry_13538t", "entry_13538t_end", 50, 15),
)

BCC = {
    "bcc", "bcs", "beq", "bge", "bgt", "bhi", "ble", "blt", "bmi",
    "bne", "bpl", "bvc", "bvs",
}
SHIFTS = {"asl", "asr", "lsl", "lsr", "rol", "ror", "roxl", "roxr"}
SYMBOL = re.compile(r"^(?:[0-9A-F]{2}:)?([0-9A-F]{4})\s+(\S+)$")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_transpiler() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "stage3_player_charge_transpiler", ROOT / "tools" / "transpile.py"
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load tools/transpile.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def parse_symbols(path: Path) -> dict[str, int]:
    symbols: dict[str, int] = {}
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        match = SYMBOL.match(line)
        if match:
            symbols[match.group(2)] = int(match.group(1), 16)
    return symbols


def basic_blocks(transpiler: ModuleType, entry: int) -> list[list[Any]]:
    instructions, (labels, _, _) = transpiler.decode(entry)
    blocks: list[list[Any]] = []
    index = 0
    while index < len(instructions):
        start = index
        while index < len(instructions):
            if index > start and instructions[index].address in labels:
                break
            index += 1
            base = instructions[index - 1].mnemonic.split(".", 1)[0]
            if base in transpiler.CTRLFLOW or base in {"rts", "trap"}:
                break
        blocks.append(instructions[start:index])
    return blocks


def timing_kind(instruction: Any) -> str | None:
    base = instruction.mnemonic.split(".", 1)[0]
    if base in BCC or base in {"dbra", "dbf"}:
        return "conditional_branch_or_loop"
    if base in SHIFTS:
        return "shift_or_rotate"
    if base == "movem":
        return "movem_register_count"
    if base in {"muls", "mulu", "divs", "divu"}:
        return "multiply_or_divide_operand"
    if base == "trap":
        return "trap_vector"
    return None


def immediate_shift_units(instruction: Any) -> int:
    """Return the two-cycle-unit adjustment for an immediate data-register shift."""

    operand = instruction.op_str.split(",", 1)[0].strip().lower()
    if not operand.startswith("#$"):
        raise RuntimeError(f"non-immediate shift cannot be pre-adjusted: {instruction}")
    count = int(operand[2:], 16)
    if count == 0:
        count = 8
    return count


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    for path in (SOURCE, BINARY, SYMBOLS, CYCLES):
        if not path.is_file():
            parser.error(f"missing required input: {path}")
    if args.output.exists():
        parser.error(f"refusing to overwrite output: {args.output}")
    if len(CYCLES.read_bytes()) != 0x10000:
        parser.error("static CPU-000 cycle table must be 65,536 bytes")
    return args


def main() -> int:
    args = parse_args()
    transpiler = load_transpiler()
    symbols = parse_symbols(SYMBOLS)
    binary = BINARY.read_bytes()
    cycles = CYCLES.read_bytes()
    charge_target = symbols.get("esc9_ac_charge")
    if charge_target is None:
        raise RuntimeError("esc9_ac_charge is absent from the assembled symbol map")

    all_records: list[dict[str, object]] = []
    totals = {"instructions": 0, "blocks": 0, "charge_sites": 0, "immediate_shift_units": 0}
    for entry, start_name, end_name, expected_instructions, expected_blocks in SPECS:
        start = symbols.get(start_name)
        end = symbols.get(end_name)
        if start is None or end is None or not start < end <= 0x10000:
            raise RuntimeError(f"invalid assembled range for ${entry:06X}")
        blocks = basic_blocks(transpiler, entry)
        if sum(map(len, blocks)) != expected_instructions or len(blocks) != expected_blocks:
            raise RuntimeError(
                f"${entry:06X} decode shape changed: {sum(map(len, blocks))} instructions, "
                f"{len(blocks)} blocks"
            )
        returns: list[int] = []
        for offset in range(start - 0xA100, end - 0xA100 - 2):
            if binary[offset] != 0x20:
                continue
            target = binary[offset + 1] | binary[offset + 2] << 8
            if target == charge_target:
                returns.append(0xA100 + offset + 3)
        if len(returns) != len(blocks):
            raise RuntimeError(
                f"${entry:06X} assembled charge-site count {len(returns)} != "
                f"{len(blocks)} decoded basic blocks"
            )

        handler_records: list[dict[str, object]] = []
        for ordinal, (block, native_return) in enumerate(zip(blocks, returns), 1):
            static_cycles = 0
            adjustments = 0
            dynamics: list[dict[str, object]] = []
            for position, instruction in enumerate(block):
                opcode = int.from_bytes(bytes(instruction.bytes[:2]), "big")
                static_cycles += cycles[opcode]
                kind = timing_kind(instruction)
                if kind is None:
                    continue
                terminal = position == len(block) - 1
                detail: dict[str, object] = {
                    "pc": f"{instruction.address:06X}",
                    "mnemonic": instruction.mnemonic,
                    "operands": instruction.op_str,
                    "kind": kind,
                    "terminal": terminal,
                }
                if kind == "shift_or_rotate":
                    adjustment = immediate_shift_units(instruction)
                    if not terminal:
                        adjustments += adjustment
                    detail["immediate_two_cycle_units"] = adjustment
                elif not terminal:
                    raise RuntimeError(
                        f"${entry:06X} block {ordinal} has unsupported non-terminal "
                        f"{kind} at ${instruction.address:06X}"
                    )
                dynamics.append(detail)
            handler_records.append(
                {
                    "ordinal": ordinal,
                    "native_return_pc": f"{native_return:04X}",
                    "original_start_pc": f"{block[0].address:06X}",
                    "original_end_pc_exclusive": f"{block[-1].address + block[-1].size:06X}",
                    "logical_instruction_count": len(block),
                    "static_cycles": static_cycles,
                    "static_two_cycle_units": static_cycles // 2,
                    "precomputed_immediate_shift_units": adjustments,
                    "dynamic_instructions": dynamics,
                }
            )
            totals["immediate_shift_units"] += adjustments
        totals["instructions"] += expected_instructions
        totals["blocks"] += expected_blocks
        totals["charge_sites"] += len(returns)
        all_records.append({"entry_pc": f"{entry:06X}", "blocks": handler_records})

    if totals != {"instructions": 238, "blocks": 83, "charge_sites": 83, "immediate_shift_units": 8}:
        raise RuntimeError(f"active-player timing inventory changed: {totals}")
    report = {
        "scope": (
            "read-only current-source audit of the six Stage-3 player handlers "
            "entered by the retained tick-14743 trace; not a virtual-IRQ repair"
        ),
        "inputs": {
            "source": {"path": str(SOURCE.resolve()), "sha256": sha256(SOURCE)},
            "binary": {"path": str(BINARY.resolve()), "sha256": sha256(BINARY)},
            "symbols": {"path": str(SYMBOLS.resolve()), "sha256": sha256(SYMBOLS)},
            "static_cycles": {"path": str(CYCLES.resolve()), "sha256": sha256(CYCLES)},
        },
        "totals": totals,
        "handlers": all_records,
        "conclusion": (
            "All 83 active-player native charge sites map one-to-one to decoded "
            "basic blocks. Four non-terminal immediate shifts contribute eight "
            "two-cycle units and can be incorporated statically; terminal Bcc/DBcc "
            "still require post-block outcome charging. No generic b* classification "
            "or global instruction multiplier is valid."
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "totals": totals}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
