#!/usr/bin/env python3
"""Validate the `$025110` charge-block map against retained exact-MAME trace.

This reducer consumes the read-only native charge inventory and the retained
uninterrupted MAME 0.287 debugger trace.  It recognizes complete original
basic-block executions, records their observed MC68000 cycle totals, and
separates static matches from the branch/loop blocks whose outcome changes the
cost.  It neither runs an emulator nor modifies a ROM or state.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_AUDIT = ROOT / "build/audit-native-charge-blocks-25110-current-v1.json"
DEFAULT_MAME = ROOT / "build/mame-25110-irq-phase-current-f369-v5/summary.json"
TRACE = re.compile(
    r"^M68K_STATE (?P<cycle>[0-9A-F]+) [0-9A-F]+ (?:[0-9A-F]+ ){17}"
    r"\| (?P<pc>[0-9A-F]{6}): (?P<disassembly>.+)$"
)
INTERRUPT = re.compile(r"^\s*\(interrupted at [0-9A-F]{6}, IRQ 6\)$")


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
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    for label, path in (("charge audit", args.audit), ("MAME summary", args.mame_summary)):
        if not path.is_file():
            parser.error(f"missing {label}: {path}")
    if args.output.exists():
        parser.error(f"refusing to overwrite output: {args.output}")
    return args


def load_trace(summary_path: Path) -> tuple[Path, list[dict[str, Any]]]:
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    if summary.get("mame", {}).get("version") != "0.287 (mame0287)":
        raise RuntimeError("MAME summary is not the exact 0.287 oracle")
    metadata = summary.get("capture", {}).get("debugger_trace", {})
    trace_path = Path(str(metadata.get("path", "")))
    if not trace_path.is_file():
        raise RuntimeError(f"missing retained MAME trace: {trace_path}")
    expected_hash = str(metadata.get("sha256", ""))
    if sha256(trace_path) != expected_hash:
        raise RuntimeError(f"MAME trace hash mismatch: {trace_path}")
    records: list[dict[str, Any]] = []
    pending_interrupt = False
    for line_number, line in enumerate(trace_path.read_text(encoding="utf-8").splitlines(), 1):
        match = TRACE.match(line)
        if match:
            records.append(
                {
                    "cycle": int(match.group("cycle"), 16),
                    "pc": int(match.group("pc"), 16),
                    "line": line_number,
                    "interrupt_before": pending_interrupt,
                }
            )
            pending_interrupt = False
        elif INTERRUPT.match(line):
            pending_interrupt = True
    if len(records) < 2:
        raise RuntimeError("MAME trace has too few instruction records")
    return trace_path, records


def main() -> int:
    args = parse_args()
    audit = json.loads(args.audit.read_text(encoding="utf-8"))
    if audit.get("summary", {}).get("charge_sites") != 226:
        raise RuntimeError("charge audit is not the expected 226-site $025110 map")
    records = list(audit.get("records", []))
    if len(records) != 226:
        raise RuntimeError("charge audit has no complete record list")
    trace_path, trace = load_trace(args.mame_summary)

    # The audit stores only block endpoints, so reconstruct each original
    # instruction address sequence from the raw program image.  This is a
    # lightweight decoder: every interior address is recovered by walking
    # Capstone through the immutable private image, not by parsing disassembly.
    import importlib.util

    transpiler_path = ROOT / "tools/transpile.py"
    spec = importlib.util.spec_from_file_location("charge_block_transpiler", transpiler_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load transpiler decoder")
    transpiler = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(transpiler)
    insns, (labels, _, _) = transpiler.decode(0x25110)

    def control_flow(ins: Any) -> bool:
        base = ins.mnemonic.split(".")[0]
        return base in transpiler.CTRLFLOW or base in {"rts", "trap"}

    decoded: list[list[Any]] = []
    index = 0
    while index < len(insns):
        start = index
        while index < len(insns):
            if index > start and insns[index].address in labels:
                break
            index += 1
            if control_flow(insns[index - 1]):
                break
        decoded.append(insns[start:index])
    if len(decoded) != len(records):
        raise RuntimeError("decoded block count no longer matches the audit")

    by_start = {block[0].address: (ordinal, block) for ordinal, block in enumerate(decoded)}
    completions: Counter[int] = Counter()
    observed: dict[int, Counter[int]] = defaultdict(Counter)
    interrupted = 0
    malformed = 0
    for position, current in enumerate(trace):
        mapping = by_start.get(int(current["pc"]))
        if mapping is None:
            continue
        ordinal, block = mapping
        # Need all block instructions plus the successor record to measure the
        # terminal branch/loop/JSR timing. The successor PC itself is allowed
        # to differ, because it is the observed control-flow outcome.
        stop = position + len(block)
        if stop >= len(trace):
            continue
        expected_pcs = [ins.address for ins in block]
        actual_pcs = [int(row["pc"]) for row in trace[position:stop]]
        if actual_pcs != expected_pcs:
            malformed += 1
            continue
        if any(bool(row["interrupt_before"]) for row in trace[position + 1:stop + 1]):
            interrupted += 1
            continue
        total = int(trace[stop]["cycle"]) - int(current["cycle"])
        if total <= 0:
            raise RuntimeError("nonpositive MAME block timing delta")
        completions[ordinal] += 1
        observed[ordinal][total] += 1

    per_block: list[dict[str, Any]] = []
    static_match = 0
    dynamic_observed = 0
    for ordinal, record in enumerate(records):
        costs = observed.get(ordinal, Counter())
        static_cycles = int(record["static_cycles"])
        dynamic = list(record.get("dynamic_instructions", []))
        if costs and not dynamic and set(costs) == {static_cycles}:
            static_match += 1
        if costs and dynamic:
            dynamic_observed += 1
        per_block.append(
            {
                "ordinal": ordinal,
                "original_start_pc": record["original_start_pc"],
                "static_cycles": static_cycles,
                "dynamic_instruction_count": len(dynamic),
                "complete_executions": completions[ordinal],
                "observed_cycle_histogram": {
                    str(cycles): count for cycles, count in sorted(costs.items())
                },
            }
        )

    report = {
        "scope": (
            "retained original-MAME trace validation of the $025110 native charge-block map; "
            "read-only timing evidence, not a SNES run or a native-clock repair"
        ),
        "inputs": {
            "charge_audit": {"path": str(args.audit.resolve()), "sha256": sha256(args.audit)},
            "mame_summary": {"path": str(args.mame_summary.resolve()), "sha256": sha256(args.mame_summary)},
            "trace": {"path": str(trace_path.resolve()), "sha256": sha256(trace_path)},
        },
        "checks": {
            "charge_blocks_226": True,
            "decoded_blocks_226": True,
            "trace_exact_mame_0287": True,
        },
        "summary": {
            "block_starts_seen": sum(1 for count in completions.values() if count),
            "complete_block_executions": sum(completions.values()),
            "unambiguous_static_blocks_matching_static_cost": static_match,
            "dynamic_blocks_observed": dynamic_observed,
            "interrupted_block_candidates_excluded": interrupted,
            "noncontiguous_block_candidates_excluded": malformed,
        },
        "blocks": per_block,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "summary": report["summary"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
