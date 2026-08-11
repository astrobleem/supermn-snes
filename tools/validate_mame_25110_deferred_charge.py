#!/usr/bin/env python3
"""Regression for post-block native `$025110` virtual-cycle charging.

The bank-$97 VTIME diagnostic commits a generated basic block at the following
charge site.  Consequently a terminal Bcc sees its unchanged CCR and a
terminal DBcc sees the *post*-decrement Dn word.  This reducer proves those
rules against the register-qualified exact-MAME trace, rather than treating a
static block sum as a timing model.  It is read-only MAME evidence; it does
not claim that a SNES ROM run has passed the corresponding three-way gate.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any

import audit_native_charge_blocks as audit
import validate_mame_25110_branch_timing as branch


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_AUDIT = ROOT / "build/audit-native-charge-blocks-25110-current-v2.json"
DEFAULT_MAME = ROOT / "build/mame-25110-irq-phase-current-f369-v5/summary.json"
DEFAULT_TABLE = ROOT / "build/gen-vtime-esc3-charge-table-build.json"
STATIC = ROOT / "src/m68k_cpu000_static_cycles.bin"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--audit", type=Path, default=DEFAULT_AUDIT)
    parser.add_argument("--mame-summary", type=Path, default=DEFAULT_MAME)
    parser.add_argument("--table-manifest", type=Path, default=DEFAULT_TABLE)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    for label, path in (
        ("charge audit", args.audit),
        ("MAME summary", args.mame_summary),
        ("generated table manifest", args.table_manifest),
        ("static-cycle table", STATIC),
    ):
        if not path.is_file():
            parser.error(f"missing {label}: {path}")
    if args.output.exists():
        parser.error(f"refusing to overwrite output: {args.output}")
    return args


def trace_path(summary_path: Path) -> Path:
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    if summary.get("mame", {}).get("version") != "0.287 (mame0287)":
        raise RuntimeError("MAME summary is not the exact 0.287 oracle")
    item = summary.get("capture", {}).get("debugger_trace", {})
    path = Path(str(item.get("path", "")))
    if not path.is_file() or sha256(path) != str(item.get("sha256", "")):
        raise RuntimeError("retained MAME trace is missing or unauthenticated")
    return path


def decode_blocks() -> list[list[Any]]:
    transpiler_path = ROOT / "tools/transpile.py"
    spec = importlib.util.spec_from_file_location("deferred_charge_transpiler", transpiler_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load transpiler decoder: {transpiler_path}")
    transpiler = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(transpiler)
    insns, (labels, _, _) = transpiler.decode(0x25110)

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
    if len(blocks) != 226 or sum(map(len, blocks)) != 545:
        raise RuntimeError("unexpected $025110 basic-block decode")
    return blocks


def terminal_cycles(opcode: int, current: dict[str, Any], following: dict[str, Any], static: int) -> int:
    """Compute the exact terminal cost using the state available post-block."""

    if 0x6200 <= opcode <= 0x6FFF:
        condition = (opcode >> 8) & 0x0F
        if condition < 2:  # BRA/BSR are static and not generated as dynamic entries.
            return static
        taken = branch.condition(condition, int(current["sr"]))
        if taken:
            return 10
        return 12 if (opcode & 0xFF) == 0 else 8
    if (opcode & 0xF0F8) == 0x50C8:
        condition = (opcode >> 8) & 0x0F
        if branch.condition(condition, int(current["sr"])):
            return 12
        register = opcode & 7
        pre = int(current["d"][register]) & 0xFFFF
        post = int(following["d"][register]) & 0xFFFF
        expected_post = (pre - 1) & 0xFFFF
        if post != expected_post:
            raise RuntimeError(
                f"DBcc post-state mismatch at ${int(current['pc']):06X}: "
                f"expected D{register}.w=${expected_post:04X}, got ${post:04X}"
            )
        return 14 if post == 0xFFFF else 10
    return static


def main() -> int:
    args = parse_args()
    audit_report = json.loads(args.audit.read_text(encoding="utf-8"))
    records = list(audit_report.get("records", []))
    if len(records) != 226 or audit_report.get("summary", {}).get("charge_sites") != 226:
        raise RuntimeError("charge audit is not the expected 226-block map")
    table = json.loads(args.table_manifest.read_text(encoding="utf-8"))
    if table.get("checks", {}).get("all_dynamic_instructions_are_terminal_supported_control_flow") is not True:
        raise RuntimeError("generated table does not prove deferred dynamic-charge safety")
    blocks = decode_blocks()
    if [len(block) for block in blocks] != [int(row["logical_instruction_count"]) for row in records]:
        raise RuntimeError("audit instruction counts no longer match decoded blocks")
    trace_file = trace_path(args.mame_summary)
    trace = branch.parse_trace(trace_file)
    static_table = STATIC.read_bytes()
    if len(static_table) != 0x10000:
        raise RuntimeError("static-cycle table shape changed")
    by_start = {block[0].address: (ordinal, block) for ordinal, block in enumerate(blocks)}

    checked = 0
    dynamic_checked = 0
    skipped_interrupt = 0
    malformed = 0
    failures: list[dict[str, object]] = []
    samples: list[dict[str, object]] = []
    for index, current in enumerate(trace):
        mapping = by_start.get(int(current["pc"]))
        if mapping is None:
            continue
        ordinal, block = mapping
        stop = index + len(block)
        if stop >= len(trace):
            continue
        rows = trace[index:stop]
        following = trace[stop]
        if [int(row["pc"]) for row in rows] != [ins.address for ins in block]:
            malformed += 1
            continue
        if any(bool(row["interrupt_before"]) for row in trace[index + 1 : stop + 1]):
            skipped_interrupt += 1
            continue
        terminal = block[-1]
        opcode = int.from_bytes(bytes(terminal.bytes[:2]), "big")
        terminal_static = static_table[opcode]
        if terminal_static == 0 or terminal_static & 1:
            raise RuntimeError(f"invalid terminal static cost at ${terminal.address:06X}")
        predicted_terminal = terminal_cycles(opcode, rows[-1], following, terminal_static)
        predicted = int(records[ordinal]["static_cycles"]) - terminal_static + predicted_terminal
        observed = int(following["cycle"]) - int(current["cycle"])
        kind = audit.dynamic_kind(terminal.mnemonic)
        if kind:
            dynamic_checked += 1
        checked += 1
        item = {
            "ordinal": ordinal + 1,
            "start_pc": f"{block[0].address:06X}",
            "terminal_pc": f"{terminal.address:06X}",
            "terminal_mnemonic": terminal.mnemonic,
            "terminal_static_cycles": terminal_static,
            "post_state_predicted_cycles": predicted,
            "observed_cycles": observed,
        }
        if predicted != observed:
            if len(failures) < 32:
                failures.append(item)
        elif kind and len(samples) < 32:
            samples.append(item)

    checks = {
        "generated_dynamic_instructions_are_terminal_supported_control_flow": True,
        "complete_blocks_checked": checked > 0,
        "dynamic_terminal_blocks_checked": dynamic_checked > 0,
        "post_state_deferred_charge_matches_exact_mame_cycles": not failures,
        "exact_mame_0287_trace_authenticated": True,
    }
    report = {
        "scope": (
            "exact-MAME regression for the post-block Bcc/DBcc cycle algorithm used by "
            "the diagnostic $025110 native ledger; not a SNES run or acceptance result"
        ),
        "inputs": {
            "charge_audit": {"path": str(args.audit.resolve()), "sha256": sha256(args.audit)},
            "mame_summary": {"path": str(args.mame_summary.resolve()), "sha256": sha256(args.mame_summary)},
            "trace": {"path": str(trace_file.resolve()), "sha256": sha256(trace_file)},
            "table_manifest": {"path": str(args.table_manifest.resolve()), "sha256": sha256(args.table_manifest)},
            "static_cycles": {"path": str(STATIC.resolve()), "sha256": sha256(STATIC)},
        },
        "checks": checks,
        "summary": {
            "complete_blocks_checked": checked,
            "dynamic_terminal_blocks_checked": dynamic_checked,
            "interrupted_candidates_excluded": skipped_interrupt,
            "noncontiguous_candidates_excluded": malformed,
            "mismatches": len(failures),
        },
        "dynamic_samples": samples,
        "failures": failures,
        "result": "green" if all(checks.values()) else "red",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"result": report["result"], "summary": report["summary"], "output": str(args.output)}, sort_keys=True))
    return 0 if report["result"] == "green" else 1


if __name__ == "__main__":
    raise SystemExit(main())
