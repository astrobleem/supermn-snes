#!/usr/bin/env python3
"""Generate exact ordinal-indexed `$02429C` metadata for its VTIME copy.

Unlike `$025110` and the player handlers, the bank-$F3 diagnostic root owns
its generated charge sites directly and passes their one-based ordinals to
the clock.  No sparse native return-address index is needed.  Ordinary ROMs
still zero this metadata range and do not pack or route the bank-$F3 copy.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import audit_stage3_2429c_charge_blocks as audit


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_COST = ROOT / "src/vtime_esc5_charge_cost.bin"
DEFAULT_PC = ROOT / "src/vtime_esc5_charge_pc.bin"
DEFAULT_TERMINAL = ROOT / "src/vtime_esc5_charge_terminal.bin"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cost", type=Path, default=DEFAULT_COST)
    parser.add_argument("--pc", type=Path, default=DEFAULT_PC)
    parser.add_argument("--terminal", type=Path, default=DEFAULT_TERMINAL)
    parser.add_argument("--manifest", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = audit.collect()
    blocks = report["blocks"]
    if report["totals"] != audit.EXPECTED_TOTALS or len(blocks) != 35:
        raise RuntimeError("$02429C future ledger shape changed")
    transpiler = audit.common.load_transpiler()
    cycles = audit.common.CYCLES.read_bytes()
    decoded = audit.common.basic_blocks(transpiler, audit.ENTRY)
    costs = bytearray()
    pcs = bytearray()
    terminals = bytearray()
    dynamic_ordinals: list[int] = []
    for ordinal, (row, block) in enumerate(zip(blocks, decoded), 1):
        units = int(row["static_two_cycle_units"])
        if not 0 < units <= 0xFF:
            raise RuntimeError(f"$02429C block {ordinal} has unencodable cost {units}")
        costs.append(units)
        pcs.extend(int(block[0].address & 0xFFFF).to_bytes(2, "little"))
        terminal = bytes(block[-1].bytes[:2])
        terminals.extend(terminal)
        if row["dynamic_terminal_control_flow"]:
            dynamic_ordinals.append(ordinal)
        # Keep this generator independent of a source injection, but reject an
        # accidental static-table change while reducing each decoded block.
        static_units = sum(
            cycles[int.from_bytes(bytes(instruction.bytes[:2]), "big")] // 2
            for instruction in block
        )
        if static_units != units:
            raise RuntimeError(f"$02429C block {ordinal} static cost drifted")
    if len(costs) != 35 or len(pcs) != len(terminals) != 70:
        raise RuntimeError("$02429C metadata shape changed")
    if len(dynamic_ordinals) != 14:
        raise RuntimeError("$02429C dynamic-terminal inventory changed")
    for path, payload in ((args.cost, costs), (args.pc, pcs), (args.terminal, terminals)):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
    output = {
        "scope": (
            "ordinal-indexed metadata consumed only by the VTIME bank-$F3 "
            "`$02429C` diagnostic root; ordinary packing remains byte-identical"
        ),
        "input_audit": {
            "source": str((ROOT / "src/escbank5.pasm").resolve()),
            "sha256": sha256(ROOT / "src/escbank5.pasm"),
            "totals": report["totals"],
        },
        "table": {
            "blocks": len(costs),
            "cost_bytes": len(costs),
            "pc_bytes": len(pcs),
            "terminal_bytes": len(terminals),
            "dynamic_terminal_ordinals": dynamic_ordinals,
        },
        "outputs": {
            name: {"path": str(path.resolve()), "sha256": sha256(path), "bytes": len(payload)}
            for name, path, payload in (
                ("cost", args.cost, costs), ("pc", args.pc, pcs), ("terminal", args.terminal, terminals)
            )
        },
    }
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"manifest": str(args.manifest), "table": output["table"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
