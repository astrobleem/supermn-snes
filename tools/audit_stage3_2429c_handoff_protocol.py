#!/usr/bin/env python3
"""Inventory production and VTIME-only `$02429C` ownership boundaries.

The ordinary bank-$99 root retains its guarded three-callee fusion and private
native continuations.  The opt-in bank-$F3 diagnostic instead reproduces all
35 original blocks, flushes before all eleven architectural child transfers,
interprets each child on the common per-fetch clock, and resumes through exact
genuine MC68000 return PCs.

The tool is intentionally read-only.  It distinguishes local diagnostic
closure from production routing and from global common-clock promotion.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src" / "escbank5.pasm"
DIAGNOSTIC_SOURCE = ROOT / "src" / "vtime_esc5_root.pasm"
ARCHITECTURAL_RETURNS = (
    0x0242AC, 0x0242B2, 0x0242B8, 0x0242BE, 0x0242C4, 0x024306,
    0x024334, 0x02436E, 0x024378, 0x0243B4, 0x0243DA,
)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def root_source(source: str) -> str:
    start = source.index("entry_2429c:")
    end = source.index("; --- entry_23e34", start)
    return source[start:end]


def require_in_order(haystack: str, snippets: tuple[str, ...], label: str) -> None:
    position = 0
    for snippet in snippets:
        found = haystack.find(snippet, position)
        if found < 0:
            raise RuntimeError(f"{label}: missing or reordered source fragment {snippet!r}")
        position = found + len(snippet)


def collect() -> dict[str, object]:
    text = SOURCE.read_text(encoding="utf-8")
    body = root_source(text)
    diagnostic = DIAGNOSTIC_SOURCE.read_text(encoding="utf-8")
    if "VTIME_" in body or "vtime_" in body:
        raise RuntimeError("$02429C is no longer an unwired VTIME root; revise this audit")
    if "ac_charge" in body:
        raise RuntimeError("$02429C gained a legacy/local charge; revise ownership audit")

    # The guarded fast arm represents three original static native callees,
    # not one ordinary direct transfer. Its hit must acquire exact ledgers for
    # all three before a common clock can include it.
    require_in_order(
        body,
        (
            "Size-neutral guarded fusion of the three consecutive no-work helpers.",
            "jml.l $988E53",
            "br2429c_1:",
        ),
        "fused $023342/$023E34/$0235E0 arm",
    )

    direct = (
        {
            "original_call_pc": "0242AC",
            "kind": "direct-native",
            "target": "entry_23e34",
            "return_protocol": "br2429c_2 via $00FA sentinel",
            "must_flush_parent_before_transfer": True,
        },
        {
            "original_call_pc": "0242B2",
            "kind": "direct-native",
            "target": "entry_235e0",
            "return_protocol": "br2429c_3 via $00FA sentinel",
            "must_flush_parent_before_transfer": True,
        },
        {
            "original_call_pc": "0242B8",
            "kind": "direct-native",
            "target": "entry_25110",
            "return_protocol": "logical $0242BE through xlat_dispatch",
            "must_flush_parent_before_transfer": True,
        },
        {
            "original_call_pc": "0242BE",
            "kind": "direct-native",
            "target": "entry_259ca",
            "return_protocol": "br2429c_5 via $00FA sentinel",
            "must_flush_parent_before_transfer": True,
        },
    )
    for record, snippets in zip(
        direct,
        (
            ("CALL-BRIDGE jsr $23e34.l", "lda #br2429c_2", "jmp entry_23e34"),
            ("CALL-BRIDGE jsr $235e0.l", "lda #br2429c_3", "jml.l entry_235e0"),
            ("CALL-BRIDGE jsr $25110.l", "lda #$42BE", "jml.l entry_25110"),
            ("CALL-BRIDGE jsr $259ca.l", "lda #br2429c_5", "jmp entry_259ca"),
        ),
    ):
        require_in_order(body, snippets, f"${record['original_call_pc']}")

    ojmp = (
        ("024302", "static $0243E8", "br2429c_6"),
        ("024330", "static $0243E8", "br2429c_7"),
        ("02436C", "dynamic (A0)", "br2429c_8"),
        ("024374", "static $02443A", "br2429c_9"),
        ("0243B0", "static $0243E8", "br2429c_10"),
        ("0243D6", "static $0244D4", "br2429c_11"),
    )
    ojmp_records: list[dict[str, object]] = []
    for pc, target, resume in ojmp:
        if target == "dynamic (A0)":
            marker = "INDIRECT-BRIDGE jsr (a0)"
        else:
            logical_target = int(target.split()[-1].removeprefix("$"), 16)
            marker = f"CALL-BRIDGE bsr.w ${logical_target:x}"
        start = body.find(marker)
        if start < 0:
            raise RuntimeError(f"${pc}: missing {marker}")
        end = body.find(f"{resume}:", start)
        if end < 0:
            raise RuntimeError(f"${pc}: missing continuation {resume}")
        bridge = body[start:end]
        if "jsl.l push32_l" not in bridge or "jml.l ojmp_hook" not in bridge:
            raise RuntimeError(f"${pc}: no complete OJMP return/transfer protocol")
        ojmp_records.append(
            {
                "original_call_pc": pc,
                "kind": "ojmp-dynamic-dispatch",
                "target": target,
                "return_protocol": f"{resume} via pushed $00FA sentinel",
                "must_flush_parent_before_transfer": True,
            }
        )

    if body.count("jml.l ojmp_hook") != len(ojmp_records):
        raise RuntimeError("$02429C OJMP-transfer count changed")
    if body.count("jsl.l push32_l") < len(ojmp_records):
        raise RuntimeError("$02429C lost an OJMP push/transfer protocol")

    if diagnostic.count("jsr vtime_esc5_charge_gateway") != 35:
        raise RuntimeError("VTIME-only `$02429C` block-charge cardinality changed")
    if diagnostic.count("jmp vtime_esc5_ojmp_gateway") != 11:
        raise RuntimeError("VTIME-only `$02429C` child-handoff cardinality changed")
    if "jml.l ojmp_hook" in diagnostic or "jml.l ibridge" in diagnostic:
        raise RuntimeError("VTIME-only `$02429C` retained a private child route")
    require_in_order(
        diagnostic,
        (
            "vtime_esc5_ojmp_gateway:",
            "jsl.l VTIME_ESC5_FINISH",
            "stz $071A",
            "jml.l inext",
        ),
        "VTIME-only child flush/interpreter gateway",
    )
    require_in_order(
        diagnostic,
        (
            "vtime_esc5_return_dispatch:",
            "cmp #$0002",
            "vtime_esc5_return_bank2:",
        ),
        "VTIME-only architectural return dispatcher",
    )
    for ordinal, return_pc in enumerate(ARCHITECTURAL_RETURNS, 1):
        require_in_order(
            diagnostic,
            (
                f"cmp #${return_pc & 0xFFFF:04X}",
                "jsr vtime_esc5_restore_gate",
                f"jmp br2429c_{ordinal}",
            ),
            f"VTIME-only return ${return_pc:06X}",
        )
    require_in_order(
        diagnostic,
        (
            "vtime_esc5_restore_gate:",
            "and #VTIME_FLAG_INTERPRETER_ONLY",
            "lda #$0001",
            "sta $071A",
            "vtime_esc5_restore_gate_off:",
            "stz $071A",
        ),
        "VTIME mode-aware native gate restoration",
    )

    return {
        "scope": (
            "source ownership/return protocol for the ordinary bank-$99 root "
            "and the opt-in bank-$F3 diagnostic; no global timing claim"
        ),
        "inputs": {
            "production": {"source": str(SOURCE.resolve()), "sha256": digest(SOURCE)},
            "diagnostic": {
                "source": str(DIAGNOSTIC_SOURCE.resolve()),
                "sha256": digest(DIAGNOSTIC_SOURCE),
            },
        },
        "production_root_is_currently_unwired": True,
        "parent_local_charge_calls": 0,
        "fused_predecessor": {
            "first_original_call_pc": "0242A6",
            "represents_original_native_callees": ["023342", "023E34", "0235E0"],
            "emitted_target": "$98:8E53",
            "required_future_policy": (
                "account for all three original callees on the guarded-hit arm, "
                "or route the arm through individually ledgered/interpreted paths"
            ),
        },
        "direct_native_handoffs": direct,
        "ojmp_handoffs": ojmp_records,
        "totals": {
            "original_child_handoff_sites": 11,
            "fused_original_native_callees": 3,
            "direct_native_handoffs_after_fusion": len(direct),
            "ojmp_handoffs": len(ojmp_records),
            "parent_local_charge_calls": 0,
        },
        "diagnostic_root": {
            "routing": "VTIME-only bank-$F3 copy; ordinary bank-$99 bytes unchanged",
            "basic_block_charge_sites": 35,
            "architectural_child_handoffs": 11,
            "parent_flush_gateway": "vtime_esc5_ojmp_gateway -> VTIME_ESC5_FINISH",
            "child_clock": "interpreter per-fetch after native gate clear",
            "architectural_returns": [f"{pc:06X}" for pc in ARCHITECTURAL_RETURNS],
            "return_dispatch_entries": 11,
            "mode_aware_gate_restore_calls": 11,
            "ordinary_vtime_restored_gate": 1,
            "interpreter_only_restored_gate": 0,
            "locally_closed": True,
        },
        "conclusion": (
            "The production root remains unwired. The VTIME-only copy locally "
            "closes all parent-to-interpreter child transfers and exact returns; "
            "that diagnostic result does not close other accelerator boundaries."
        ),
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
    print(json.dumps({"output": str(args.output), "totals": report["totals"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
