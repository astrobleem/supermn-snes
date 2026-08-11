#!/usr/bin/env python3
"""Generate future VTIME metadata for active bank-$9F Stage-3 player blocks.

This is deliberately data generation only.  The ordinary ROM does not consume
these files, and the current diagnostic clock still charges only `$025110`.
The generated records are the prerequisite for a common-clock implementation:
each bank-$9F ``esc9_ac_charge`` return site maps to a decoded original block,
with immediate-shift cost folded in and only terminal Bcc/DBcc left dynamic.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import audit_stage3_player_charge_blocks as audit


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INDEX = ROOT / "src" / "vtime_esc9_charge_index.bin"
DEFAULT_COST = ROOT / "src" / "vtime_esc9_charge_cost.bin"
DEFAULT_PC = ROOT / "src" / "vtime_esc9_charge_pc.bin"
DEFAULT_TERMINAL = ROOT / "src" / "vtime_esc9_charge_terminal.bin"
RETURN_BASE = 0xBA00


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--index", type=Path, default=DEFAULT_INDEX)
    parser.add_argument("--cost", type=Path, default=DEFAULT_COST)
    parser.add_argument("--pc", type=Path, default=DEFAULT_PC)
    parser.add_argument("--terminal", type=Path, default=DEFAULT_TERMINAL)
    parser.add_argument("--manifest", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    for path in (audit.SOURCE, audit.BINARY, audit.SYMBOLS, audit.CYCLES):
        if not path.is_file():
            raise SystemExit(f"missing input: {path}")
    transpiler = audit.load_transpiler()
    symbols = audit.parse_symbols(audit.SYMBOLS)
    charge_target = symbols.get("esc9_ac_charge")
    if charge_target is None:
        raise SystemExit("missing esc9_ac_charge assembled symbol")
    binary = audit.BINARY.read_bytes()
    cycles = audit.CYCLES.read_bytes()
    records: list[dict[str, object]] = []
    for entry, start_name, end_name, expected_insns, expected_blocks in audit.SPECS:
        start = symbols[start_name]
        end = symbols[end_name]
        blocks = audit.basic_blocks(transpiler, entry)
        if sum(map(len, blocks)) != expected_insns or len(blocks) != expected_blocks:
            raise SystemExit(f"${entry:06X} decoded block shape changed")
        returns: list[int] = []
        for offset in range(start - 0xA100, end - 0xA100 - 2):
            if binary[offset] != 0x20:
                continue
            target = binary[offset + 1] | binary[offset + 2] << 8
            if target == charge_target:
                returns.append(0xA100 + offset + 3)
        if len(returns) != len(blocks):
            raise SystemExit(f"${entry:06X} assembled/native charge count diverged")
        for block, native_return in zip(blocks, returns):
            static_units = 0
            terminal = block[-1]
            for position, instruction in enumerate(block):
                opcode = int.from_bytes(bytes(instruction.bytes[:2]), "big")
                raw_cycles = cycles[opcode]
                if raw_cycles == 0 or raw_cycles & 1:
                    raise SystemExit(
                        f"invalid static timing at ${instruction.address:06X}: {raw_cycles}"
                    )
                static_units += raw_cycles // 2
                kind = audit.timing_kind(instruction)
                if kind == "shift_or_rotate":
                    # All active-player shifts are immediate and are known before
                    # execution.  Dynamic Dn-count shifts must force a new audit.
                    static_units += audit.immediate_shift_units(instruction)
                elif kind is not None and position != len(block) - 1:
                    raise SystemExit(
                        f"non-terminal {kind} at ${instruction.address:06X} needs a split block"
                    )
            if not 0 < static_units <= 0xFF:
                raise SystemExit(f"unencodable native block cost {static_units}")
            terminal_opcode = bytes(terminal.bytes[:2])
            records.append(
                {
                    "native_return": native_return,
                    "cost": static_units,
                    "pc": block[0].address,
                    "terminal": terminal_opcode,
                    "terminal_timing_kind": audit.timing_kind(terminal),
                }
            )

    if len(records) != 83:
        raise SystemExit(f"expected 83 player blocks, found {len(records)}")
    max_return = max(int(record["native_return"]) for record in records)
    if not all(RETURN_BASE <= int(record["native_return"]) <= max_return for record in records):
        raise SystemExit("bank-$9F return is outside the fixed sparse-table range")
    index = bytearray(max_return - RETURN_BASE + 1)
    costs = bytearray()
    pcs = bytearray()
    terminals = bytearray()
    dynamic = 0
    for ordinal, record in enumerate(records, 1):
        key = int(record["native_return"]) - RETURN_BASE
        if index[key]:
            raise SystemExit(f"duplicate bank-$9F native return ${key + RETURN_BASE:04X}")
        index[key] = ordinal
        costs.append(int(record["cost"]))
        pcs.extend((int(record["pc"]) & 0xFFFF).to_bytes(2, "little"))
        terminals.extend(bytes(record["terminal"]))
        if record["terminal_timing_kind"] == "conditional_branch_or_loop":
            dynamic += 1
    if (
        len(index) > 0x4300
        or len(costs) != 83
        or len(pcs) != 166
        or len(terminals) != 166
    ):
        raise SystemExit("bank-$9F VTIME metadata does not fit its reserved future layout")
    for path, payload in (
        (args.index, index), (args.cost, costs), (args.pc, pcs), (args.terminal, terminals)
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
    report = {
        "scope": (
            "generated metadata for a future bank-$9F Stage-3 player VTIME ledger; "
            "not packed or enabled by the current ROM"
        ),
        "inputs": {
            "source": {"path": str(audit.SOURCE.resolve()), "sha256": sha256(audit.SOURCE)},
            "binary": {"path": str(audit.BINARY.resolve()), "sha256": sha256(audit.BINARY)},
            "symbols": {"path": str(audit.SYMBOLS.resolve()), "sha256": sha256(audit.SYMBOLS)},
            "static_cycles": {"path": str(audit.CYCLES.resolve()), "sha256": sha256(audit.CYCLES)},
        },
        "table": {
            "blocks": len(records),
            "terminal_dynamic_branch_or_loop_blocks": dynamic,
            "return_pc_base": f"{RETURN_BASE:04X}",
            "return_pc_limit_inclusive": f"{max_return:04X}",
            "index_bytes": len(index),
            "cost_bytes": len(costs),
            "pc_bytes": len(pcs),
            "terminal_bytes": len(terminals),
        },
        "outputs": {
            label: {"path": str(path.resolve()), "sha256": sha256(path), "bytes": len(payload)}
            for label, path, payload in (
                ("index", args.index, index), ("cost", args.cost, costs),
                ("pc", args.pc, pcs), ("terminal", args.terminal, terminals),
            )
        },
    }
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"manifest": str(args.manifest), "table": report["table"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
