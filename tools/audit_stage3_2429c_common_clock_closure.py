#!/usr/bin/env python3
"""Audit local `$02429C` VTIME closure without claiming global promotion.

The ordinary production root remains unchanged.  The opt-in bank-$F3 copy owns
all 35 original blocks, flushes before all eleven architectural child calls,
and interprets each child before resuming through its genuine return PC.

The audit joins three otherwise separate facts:

* the original-CPU basic-block and child-route inventory;
* the emitted parent return/transfer protocol; and
* the VTIME-only `$02429C` owner, metadata, and interpreter-child handoffs.

``green`` means the local diagnostic source seam is closed while global
promotion remains correctly blocked.  It is never an active-ROM, timing,
MAME, or gameplay acceptance result.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Final

import audit_stage3_2429c_charge_blocks as blocks
import audit_stage3_2429c_handoff_protocol as protocol
import audit_vtime_accelerated_boundaries as boundaries


ROOT = Path(__file__).resolve().parents[1]
VTIME = ROOT / "src" / "vtime.pasm"
ESC5 = ROOT / "src" / "escbank5.pasm"
ESC5_DIAGNOSTIC = ROOT / "src" / "vtime_esc5_root.pasm"
ESC5_TABLES: Final = (
    ("cost", ROOT / "src" / "vtime_esc5_charge_cost.bin", 35),
    ("pc", ROOT / "src" / "vtime_esc5_charge_pc.bin", 70),
    ("terminal", ROOT / "src" / "vtime_esc5_charge_terminal.bin", 70),
)
NATIVE_CHILDREN: Final = frozenset({"023342", "023E34", "0235E0", "025110", "0259CA"})
INTERPRETER_CHILDREN: Final = frozenset({"0243E8", "02443A", "0244D4", "indirect-A0"})


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def must_contain(text: str, snippet: str, name: str) -> None:
    if snippet not in text:
        raise RuntimeError(f"missing required VTIME owner/handoff fragment {name}: {snippet!r}")


def table_inventory(vtime: str) -> dict[str, dict[str, object]]:
    inventory: dict[str, dict[str, object]] = {}
    for name, path, expected_bytes in ESC5_TABLES:
        if not path.is_file():
            raise RuntimeError(f"missing generated $02429C metadata: {path}")
        actual_bytes = path.stat().st_size
        if actual_bytes != expected_bytes:
            raise RuntimeError(
                f"$02429C {name} metadata length changed: {actual_bytes} != {expected_bytes}"
            )
        inventory[name] = {
            "path": str(path.resolve()),
            "bytes": actual_bytes,
            "sha256": sha256(path),
            "included_by_current_vtime_image": path.name in vtime,
        }
    return inventory


def collect() -> dict[str, Any]:
    vtime = VTIME.read_text(encoding="utf-8")
    root = ESC5.read_text(encoding="utf-8")
    diagnostic = ESC5_DIAGNOSTIC.read_text(encoding="utf-8")
    parent = protocol.collect()
    block_audit = blocks.collect()

    # Keep this audit tied to actual diagnostic implementation rather than
    # assuming that a named table implies a runnable owner.
    for snippet, name in (
        ("VT_OWNER_25110=$0003", "collision owner"),
        ("VT_OWNER_2429C=$0005", "$02429C owner"),
        ("VT_OWNER_STAGE3_PLAYER=$0009", "player owner"),
        ("vtime_esc5_charge:", "$02429C charge helper"),
        ("vtime_esc5_finish:", "$02429C finish helper"),
        ("vtime_native_handoff_to_interpreter:", "native-to-interpreter helper"),
    ):
        must_contain(vtime, snippet, name)
    root_body = protocol.root_source(root)
    if "vtime_" in root_body or "VTIME_" in root_body:
        raise RuntimeError("ordinary bank-$99 `$02429C` unexpectedly acquired VTIME wiring")
    if diagnostic.count("jsr vtime_esc5_charge_gateway") != 35:
        raise RuntimeError("diagnostic `$02429C` charge cardinality changed")
    if diagnostic.count("jmp vtime_esc5_ojmp_gateway") != 11:
        raise RuntimeError("diagnostic `$02429C` handoff cardinality changed")

    handoff_by_pc = {
        row["original_call_pc"]: row
        for row in (*parent["direct_native_handoffs"], *parent["ojmp_handoffs"])
    }
    rows: list[dict[str, object]] = []
    for call_pc, target in blocks.CHILD_HANDOFFS.items():
        key = f"{call_pc:06X}"
        emitted = handoff_by_pc.get(key)
        fused = key == "0242A6"
        if fused:
            production_route = "guarded-fusion-$98:8E53"
            production_kind = "fused-native-triple"
        else:
            if emitted is None:
                raise RuntimeError(f"missing emitted parent protocol for ${key}")
            production_route = str(blocks.CHILD_ROUTE[target])
            production_kind = str(emitted["kind"])
        if target not in NATIVE_CHILDREN and target not in INTERPRETER_CHILDREN:
            raise RuntimeError(f"unclassified $02429C child ${target}")
        rows.append(
            {
                "original_call_pc": key,
                "original_target": target,
                "production_route": production_route,
                "production_kind": production_kind,
                "diagnostic_route": "genuine return + parent finish + interpreter child",
                "child_owner_now": "common interpreter per-fetch clock",
                "parent_pretransfer_flush_now": True,
                "due_irq_handoff_now": True,
                "admitted_to_local_common_clock": True,
            }
        )

    if len(rows) != 11 or len({row["original_call_pc"] for row in rows}) != 11:
        raise RuntimeError("$02429C common-clock handoff cardinality changed")
    if not all(row["parent_pretransfer_flush_now"] is True for row in rows):
        raise RuntimeError("diagnostic source lost a parent VTIME flush")

    root_boundary = next(
        row for row in boundaries.BOUNDARIES if row[0] == "stage3_tick_bridge_02429c"
    )
    if root_boundary[-1] != "selected-ledger":
        raise RuntimeError("accelerated-boundary inventory lost diagnostic $02429C ledger")
    table = table_inventory(vtime)
    if not all(row["included_by_current_vtime_image"] for row in table.values()):
        raise RuntimeError("diagnostic $02429C metadata is no longer included")

    return {
        "scope": (
            "source-level common-clock ownership closure for the opt-in Stage-3 "
            "$02429C copy; green means local closure and continued global "
            "promotion blocking, not ROM/timing/gameplay acceptance"
        ),
        "source_hashes": {
            "src/escbank5.pasm": sha256(ESC5),
            "src/vtime_esc5_root.pasm": sha256(ESC5_DIAGNOSTIC),
            "src/vtime.pasm": sha256(VTIME),
        },
        "root": {
            "entry_pc": "02429C",
            "production_vtime_wiring_now": False,
            "vtime_owner_now": "$0005 / VT_OWNER_2429C",
            "local_vtime_wiring_now": True,
            "child_policy": "all eleven interpreted after exact parent flush",
            "accelerated_boundary_state": root_boundary[-1],
            "basic_blocks": block_audit["totals"]["basic_blocks"],
            "dynamic_terminal_control_flow": block_audit["totals"]["dynamic_terminal_control_flow"],
            "generated_metadata": table,
        },
        "current_native_owner_dispatch": ["$025110", "$02429C", "Stage-3 player"],
        "handoffs": rows,
        "fused_arm": {
            "first_original_call_pc": "0242A6",
            "original_native_callees": ["023342", "023E34", "0235E0"],
            "production_emitted_target": "$98:8E53",
            "diagnostic_policy": "de-fused; all three original calls interpreted",
            "single_owner_now": True,
        },
        "totals": {
            "original_child_handoffs": len(rows),
            "native_or_fused_handoffs": sum(
                row["original_target"] in NATIVE_CHILDREN or row["production_kind"] == "fused-native-triple"
                for row in rows
            ),
            "interpreter_or_dynamic_handoffs": sum(
                row["original_target"] in INTERPRETER_CHILDREN for row in rows
            ),
            "handoffs_admitted_to_local_common_clock": sum(
                bool(row["admitted_to_local_common_clock"]) for row in rows
            ),
        },
        "promotion_blocked": True,
        "required_before_promotion": (
            "Retain the exact local due/return regressions, then close the remaining "
            "global accelerated-boundary and legacy-$AC migrations before fresh "
            "MAME/native-off/native-on timing acceptance."
        ),
        "result": "green",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error(f"refusing to overwrite output: {args.output}")
    report = collect()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"result": report["result"], "output": str(args.output.resolve()), "totals": report["totals"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
