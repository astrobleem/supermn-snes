#!/usr/bin/env python3
"""Audit the native $025110 charge sites before converting them to cycles.

The production Stage-3 collision escape currently has 226 bank-local
``esc3_ac_charge_N`` calls.  They debit the legacy virtual *instruction*
countdown, whereas the staged interpreter timer uses two-MC68000-cycle units.
It would be unsafe to replace those calls with a multiplier: a charge call is
one original basic block and its original opcode mix is known.

This read-only reducer reconstructs those blocks from the current transpiler,
checks that their logical instruction counts still agree with the assembled
bank-$97 calls, and records the static MAME CPU-000 cycle baseline and every
dynamic-cost instruction in each block.  It deliberately does *not* claim
that an ordinal source match proves a native block is semantically unchanged;
the output marks label mismatches for manual review before a timing table is
installed.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
from collections import Counter
from pathlib import Path
from types import ModuleType
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / "src/escbank3.pasm"
DEFAULT_BINARY = ROOT / "src/escbank3.bin"
DEFAULT_SYMBOLS = ROOT / "src/escbank3.sym"
DEFAULT_CYCLES = ROOT / "src/m68k_cpu000_static_cycles.bin"

ENTRY = 0x25110
SOURCE_CHARGE = re.compile(r"^    jsr esc3_ac_charge_([1-6])$", re.MULTILINE)
LABEL = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*):$", re.MULTILINE)
SYMBOL = re.compile(r"^(?:[0-9A-F]{2}:)?([0-9A-F]{4})\s+(\S+)$")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--binary", type=Path, default=DEFAULT_BINARY)
    parser.add_argument("--symbols", type=Path, default=DEFAULT_SYMBOLS)
    parser.add_argument("--cycles", type=Path, default=DEFAULT_CYCLES)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    for label, path in (
        ("escape source", args.source),
        ("assembled escape binary", args.binary),
        ("escape symbols", args.symbols),
        ("static cycle table", args.cycles),
    ):
        if not path.is_file():
            parser.error(f"missing {label}: {path}")
    if args.output.exists():
        parser.error(f"refusing to overwrite output: {args.output}")
    if len(args.cycles.read_bytes()) != 0x10000:
        parser.error("static-cycle table must contain exactly 65,536 entries")
    return args


def load_transpiler() -> ModuleType:
    path = ROOT / "tools/transpile.py"
    spec = importlib.util.spec_from_file_location("supermn_transpiler_audit", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load transpiler: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def basic_blocks(transpiler: ModuleType) -> list[list[Any]]:
    insns, (labels, _, _) = transpiler.decode(ENTRY)

    def control_flow(ins: Any) -> bool:
        base = ins.mnemonic.split(".")[0]
        return base in transpiler.CTRLFLOW or base in {"rts", "trap"}

    blocks: list[list[Any]] = []
    index = 0
    while index < len(insns):
        start = index
        while index < len(insns):
            if index > start and insns[index].address in labels:
                break
            index += 1
            if control_flow(insns[index - 1]):
                break
        blocks.append(insns[start:index])
    if len(insns) != 545 or len(blocks) != 226 or sum(map(len, blocks)) != 545:
        raise RuntimeError(
            "unexpected $025110 decode shape: "
            f"{len(insns)} instructions, {len(blocks)} blocks"
        )
    return blocks


def source_labels_for_charge(source: str) -> list[list[str]]:
    lines = source.splitlines()
    found: list[list[str]] = []
    for index, line in enumerate(lines):
        if not re.fullmatch(r"    jsr esc3_ac_charge_[1-6]", line):
            continue
        labels: list[str] = []
        cursor = index - 1
        while cursor >= 0:
            text = lines[cursor]
            match = LABEL.match(text)
            if match:
                labels.append(match.group(1))
                cursor -= 1
                continue
            if not text.strip() or text.lstrip().startswith(";"):
                cursor -= 1
                continue
            break
        found.append(list(reversed(labels)))
    return found


def parse_symbols(path: Path) -> dict[str, int]:
    symbols: dict[str, int] = {}
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        match = SYMBOL.match(raw)
        if match:
            symbols[match.group(2)] = int(match.group(1), 16)
    return symbols


def native_charge_returns(binary: bytes, symbols: dict[str, int]) -> list[tuple[int, int]]:
    helpers = {
        symbols[f"esc3_ac_charge_{amount}"]: amount for amount in range(1, 7)
    }
    entry = symbols.get("entry_25110")
    first_helper = min(helpers)
    if entry != 0x8000:
        raise RuntimeError(f"entry_25110 moved from $8000: {entry!r}")
    sites: list[tuple[int, int]] = []
    # The body ends before the local helpers.  Restricting this search range
    # avoids treating an identical byte trio in later data/code as a call.
    for offset in range(entry - 0x8000, first_helper - 0x8000 - 2):
        if binary[offset] != 0x20:  # JSR abs
            continue
        target = binary[offset + 1] | (binary[offset + 2] << 8)
        amount = helpers.get(target)
        if amount is not None:
            sites.append((offset + 0x8003, amount))
    if len(sites) != 226:
        raise RuntimeError(f"found {len(sites)} bank-$97 charge calls, expected 226")
    return sites


def dynamic_kind(mnemonic: str) -> str | None:
    base = mnemonic.split(".")[0]
    if base in {
        "bcc", "bcs", "beq", "bge", "bgt", "bhi", "ble", "blt", "bmi",
        "bne", "bpl", "bvc", "bvs", "dbra", "dbf",
    }:
        return "conditional_branch_or_loop"
    if base == "movem":
        return "movem_register_mask"
    if base in {"asl", "asr", "lsl", "lsr", "rol", "ror", "roxl", "roxr"}:
        return "shift_or_rotate_count"
    if base in {"muls", "mulu", "divs", "divu"}:
        return "multiply_or_divide_operand"
    if base == "trap":
        return "trap_vector"
    return None


def main() -> int:
    args = parse_args()
    source = args.source.read_text(encoding="utf-8")
    source_amounts = [int(value) for value in SOURCE_CHARGE.findall(source)]
    source_labels = source_labels_for_charge(source)
    if len(source_amounts) != 226 or len(source_labels) != 226:
        raise RuntimeError(
            "expected exactly 226 source esc3 charges, got "
            f"amounts={len(source_amounts)}, labels={len(source_labels)}"
        )

    blocks = basic_blocks(load_transpiler())
    expected_amounts = [len(block) for block in blocks]
    if expected_amounts != source_amounts:
        first = next(
            i for i, (expected, actual) in enumerate(zip(expected_amounts, source_amounts))
            if expected != actual
        )
        raise RuntimeError(
            f"source charge {first} is {source_amounts[first]}, "
            f"but transpiler block has {expected_amounts[first]} instructions"
        )

    symbols = parse_symbols(args.symbols)
    returns = native_charge_returns(args.binary.read_bytes(), symbols)
    binary_amounts = [amount for _, amount in returns]
    if binary_amounts != source_amounts:
        first = next(
            i for i, (source_amount, binary_amount) in enumerate(zip(source_amounts, binary_amounts))
            if source_amount != binary_amount
        )
        raise RuntimeError(
            f"assembled charge {first} is {binary_amounts[first]}, "
            f"but source says {source_amounts[first]}"
        )

    cycles = args.cycles.read_bytes()
    dynamic_counts: Counter[str] = Counter()
    records: list[dict[str, Any]] = []
    matched_labels = 0
    for ordinal, (block, (native_return, amount), current_labels) in enumerate(
        zip(blocks, returns, source_labels)
    ):
        dynamic: list[dict[str, Any]] = []
        static_cycles = 0
        for ins in block:
            opcode = int.from_bytes(bytes(ins.bytes[:2]), "big")
            raw_cycles = cycles[opcode]
            if raw_cycles == 0 or raw_cycles & 1:
                raise RuntimeError(
                    f"invalid static-cycle entry {raw_cycles} for ${ins.address:06X} opcode ${opcode:04X}"
                )
            static_cycles += raw_cycles
            kind = dynamic_kind(ins.mnemonic)
            if kind:
                dynamic_counts[kind] += 1
                dynamic.append(
                    {
                        "pc": f"{ins.address:06X}",
                        "mnemonic": ins.mnemonic,
                        "operands": ins.op_str,
                        "kind": kind,
                    }
                )
        raw_label = f"L25110_{block[0].address:05x}"
        # Early code has no emitted L-label at its function entry; later branch
        # targets can be named Lf25110_N.  The original PC remains authoritative
        # even when an assembly-local alias is needed for source navigation.
        label_match = raw_label in current_labels or ordinal == 0 and "entry_25110" in current_labels
        if label_match:
            matched_labels += 1
        records.append(
            {
                "ordinal": ordinal,
                "native_return_pc": f"{native_return:04X}",
                "logical_instruction_count": amount,
                "original_start_pc": f"{block[0].address:06X}",
                "original_end_pc_exclusive": f"{block[-1].address + block[-1].size:06X}",
                "static_cycles": static_cycles,
                "static_two_cycle_units": static_cycles // 2,
                "current_source_labels": current_labels,
                "canonical_start_label": raw_label,
                "canonical_label_present": label_match,
                "dynamic_instructions": dynamic,
            }
        )

    report = {
        "scope": (
            "read-only mapping of current $025110 native instruction-count charges to "
            "transpiler basic blocks and source-authenticated static CPU-000 costs; "
            "not a native-cycle migration or timing acceptance"
        ),
        "inputs": {
            "source": {"path": str(args.source.resolve()), "sha256": sha256(args.source)},
            "binary": {"path": str(args.binary.resolve()), "sha256": sha256(args.binary)},
            "symbols": {"path": str(args.symbols.resolve()), "sha256": sha256(args.symbols)},
            "static_cycles": {"path": str(args.cycles.resolve()), "sha256": sha256(args.cycles)},
        },
        "checks": {
            "transpiler_shape_545_instructions_226_blocks": True,
            "source_charge_amounts_match_blocks": True,
            "assembled_charge_amounts_match_source": True,
            "all_static_entries_even_nonzero": True,
        },
        "summary": {
            "charge_sites": len(records),
            "logical_instruction_total": sum(record["logical_instruction_count"] for record in records),
            "static_cycle_total": sum(record["static_cycles"] for record in records),
            "static_two_cycle_unit_total": sum(record["static_two_cycle_units"] for record in records),
            "static_two_cycle_unit_min": min(record["static_two_cycle_units"] for record in records),
            "static_two_cycle_unit_max": max(record["static_two_cycle_units"] for record in records),
            "canonical_start_label_present": matched_labels,
            "canonical_start_label_missing": len(records) - matched_labels,
            "dynamic_instruction_counts": dict(sorted(dynamic_counts.items())),
        },
        "records": records,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "summary": report["summary"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
