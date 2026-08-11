#!/usr/bin/env python3
"""Generate sparse $025110 native-charge lookup tables for the VTIME lab.

The bank-$97 collision body calls one of six ``esc3_ac_charge_N`` helpers at
the beginning of each translated basic block.  The 65816 return address of
that JSR is therefore a stable, assembly-checked key for the corresponding
original MC68000 block.  This generator emits only metadata -- no arcade bytes
-- so a later diagnostic can look up a block's original PC and static CPU-000
two-cycle cost without assigning a global instruction-to-cycle multiplier.

The tables are deliberately *not* an acceptance model.  They retain static
costs only, and branch/loop outcomes still need the trace-proven dynamic rules
before any native VTIME path is enabled.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import audit_native_charge_blocks as audit


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / "src/escbank3.pasm"
DEFAULT_BINARY = ROOT / "src/escbank3.bin"
DEFAULT_SYMBOLS = ROOT / "src/escbank3.sym"
DEFAULT_CYCLES = ROOT / "src/m68k_cpu000_static_cycles.bin"
DEFAULT_INDEX = ROOT / "src/vtime_esc3_charge_index.bin"
DEFAULT_COST = ROOT / "src/vtime_esc3_charge_cost.bin"
DEFAULT_PC = ROOT / "src/vtime_esc3_charge_pc.bin"
DEFAULT_TERMINAL = ROOT / "src/vtime_esc3_charge_terminal.bin"


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
    parser.add_argument("--index", type=Path, default=DEFAULT_INDEX)
    parser.add_argument("--cost", type=Path, default=DEFAULT_COST)
    parser.add_argument("--pc", type=Path, default=DEFAULT_PC)
    parser.add_argument("--terminal", type=Path, default=DEFAULT_TERMINAL)
    parser.add_argument("--manifest", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    for label, path in (
        ("source", args.source),
        ("binary", args.binary),
        ("symbols", args.symbols),
        ("static cycle table", args.cycles),
    ):
        if not path.is_file():
            raise SystemExit(f"missing {label}: {path}")

    source = args.source.read_text(encoding="utf-8")
    source_amounts = [int(value) for value in audit.SOURCE_CHARGE.findall(source)]
    blocks = audit.basic_blocks(audit.load_transpiler())
    expected_amounts = [len(block) for block in blocks]
    if len(blocks) != 226 or source_amounts != expected_amounts:
        raise SystemExit("$025110 source charges no longer match the decoded basic blocks")

    symbols = audit.parse_symbols(args.symbols)
    returns = audit.native_charge_returns(args.binary.read_bytes(), symbols)
    if [amount for _, amount in returns] != source_amounts:
        raise SystemExit("assembled $025110 charge calls no longer match the source")
    if any(pc < 0x8000 for pc, _ in returns):
        raise SystemExit("unexpected bank-$97 charge return below $8000")

    static = args.cycles.read_bytes()
    if len(static) != 0x10000:
        raise SystemExit("static CPU-000 table must be exactly 65,536 bytes")
    max_return = max(pc for pc, _ in returns)
    index = bytearray(max_return - 0x8000 + 1)
    costs = bytearray()
    pcs = bytearray()
    terminals = bytearray()
    dynamic_terminal_control_flow = True
    dynamic_terminal_details: list[dict[str, object]] = []
    for ordinal, (block, (return_pc, _)) in enumerate(zip(blocks, returns), 1):
        key = return_pc - 0x8000
        if index[key]:
            raise SystemExit(f"duplicate native charge return ${return_pc:04X}")
        index[key] = ordinal
        total_cycles = 0
        for ins in block:
            opcode = int.from_bytes(bytes(ins.bytes[:2]), "big")
            cycles = static[opcode]
            if cycles == 0 or cycles & 1:
                raise SystemExit(
                    f"invalid static cycle entry {cycles} at ${ins.address:06X} opcode ${opcode:04X}"
                )
            total_cycles += cycles
        units = total_cycles // 2
        if not 0 < units <= 0xFF:
            raise SystemExit(f"block {ordinal} has unencodable two-cycle cost {units}")
        costs.append(units)
        pcs.extend((block[0].address & 0xFFFF).to_bytes(2, "little"))
        terminals.extend(bytes(block[-1].bytes[:2]))
        for offset, ins in enumerate(block):
            kind = audit.dynamic_kind(ins.mnemonic)
            if kind is None:
                continue
            terminal = offset == len(block) - 1
            supported = kind == "conditional_branch_or_loop"
            dynamic_terminal_control_flow &= terminal and supported
            dynamic_terminal_details.append(
                {
                    "ordinal": ordinal,
                    "pc": f"{ins.address:06X}",
                    "mnemonic": ins.mnemonic,
                    "terminal": terminal,
                    "kind": kind,
                    "supported": supported,
                }
            )

    if not dynamic_terminal_control_flow:
        unsupported = next(
            item
            for item in dynamic_terminal_details
            if not bool(item["terminal"]) or not bool(item["supported"])
        )
        raise SystemExit(
            "deferred native charging requires every dynamic instruction to be a "
            f"terminal branch/loop; first unsupported record: {unsupported}"
        )

    if (
        len(costs) != 226
        or len(pcs) != 452
        or len(terminals) != 452
        or index.count(0) + len(costs) != len(index)
    ):
        raise SystemExit("generated sparse native-charge table shape is invalid")

    for path, payload in (
        (args.index, index),
        (args.cost, costs),
        (args.pc, pcs),
        (args.terminal, terminals),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
    report = {
        "scope": (
            "generated lookup metadata for a future diagnostic $025110 native-cycle "
            "path; static costs only, not an enabled timing repair"
        ),
        "inputs": {
            "source": {"path": str(args.source.resolve()), "sha256": sha256(args.source)},
            "binary": {"path": str(args.binary.resolve()), "sha256": sha256(args.binary)},
            "symbols": {"path": str(args.symbols.resolve()), "sha256": sha256(args.symbols)},
            "static_cycles": {"path": str(args.cycles.resolve()), "sha256": sha256(args.cycles)},
        },
        "outputs": {
            "index": {
                "path": str(args.index.resolve()),
                "sha256": sha256(args.index),
                "bytes": len(index),
                "return_pc_base": "8000",
                "return_pc_limit_inclusive": f"{max_return:04X}",
            },
            "cost": {"path": str(args.cost.resolve()), "sha256": sha256(args.cost), "bytes": len(costs)},
            "pc": {"path": str(args.pc.resolve()), "sha256": sha256(args.pc), "bytes": len(pcs)},
            "terminal": {
                "path": str(args.terminal.resolve()),
                "sha256": sha256(args.terminal),
                "bytes": len(terminals),
            },
        },
        "checks": {
            "decoded_blocks": len(blocks) == 226,
            "source_calls": len(source_amounts) == 226,
            "assembled_calls": len(returns) == 226,
            "static_costs_nonzero_even": True,
            "all_dynamic_instructions_are_terminal_supported_control_flow": dynamic_terminal_control_flow,
        },
        "dynamic_terminal_control_flow": dynamic_terminal_details,
    }
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"manifest": str(args.manifest), "outputs": report["outputs"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
