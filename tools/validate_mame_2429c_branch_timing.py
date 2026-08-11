#!/usr/bin/env python3
"""Check the `$02429C` dynamic root branches against retained original MAME.

This narrows the existing register-qualified MAME Stage-3 trace to branches
actually observed in the live coroutine root.  It intentionally reports
unseen root branches as coverage gaps rather than extrapolating a generic
clock rule into a native ledger.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

import validate_mame_25110_branch_timing as common


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SUMMARY = ROOT / "build/mame-25110-irq-phase-current-f369-v5/summary.json"
DEFAULT_PROGRAM = ROOT / "data/superman_m68k.bin"
ROOT_DYNAMIC_PCS = frozenset({
    0x0242A2, 0x0242C8, 0x0242E6, 0x0242EE, 0x0242FE, 0x024310, 0x02432C,
    0x02433E, 0x02437E, 0x024388, 0x02439A, 0x0243AC, 0x0243D2, 0x0243E0,
})


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def branch_prediction(pc: int, opcode: int, sr: int, d0: int, program: bytes) -> tuple[int, int, str]:
    code = (opcode >> 8) & 0x0F
    if (opcode & 0xF0F8) == 0x50C8:
        extension = int.from_bytes(program[pc + 2:pc + 4], "big")
        target = (pc + 2 + common.signed16(extension)) & 0xFFFFFF
        if common.condition(code, sr):
            return 12, (pc + 4) & 0xFFFFFF, "dbcc:condition_true_exit"
        decremented = (d0 - 1) & 0xFFFF
        if decremented == 0xFFFF:
            return 14, (pc + 4) & 0xFFFFFF, "dbcc:expired_exit"
        return 10, target, "dbcc:decrement_branch"
    extension = int.from_bytes(program[pc + 2:pc + 4], "big")
    target = (pc + 2 + common.signed16(extension)) & 0xFFFFFF
    if common.condition(code, sr):
        return 10, target, "bcc_word:taken"
    return 12, (pc + 4) & 0xFFFFFF, "bcc_word:not_taken"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY)
    parser.add_argument("--program", type=Path, default=DEFAULT_PROGRAM)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error(f"refusing to overwrite output: {args.output}")
    if not args.summary.is_file() or not args.program.is_file():
        parser.error("missing MAME summary or MC68000 program")
    summary = json.loads(args.summary.read_text(encoding="utf-8"))
    if summary.get("mame", {}).get("version") != "0.287 (mame0287)":
        raise RuntimeError("summary is not exact MAME 0.287 evidence")
    trace = common.resolve(args.summary, summary["capture"]["debugger_trace"])
    program = args.program.read_bytes()
    rows = common.parse_trace(trace)
    observed: Counter[int] = Counter()
    outcomes: Counter[str] = Counter()
    failures: list[dict[str, object]] = []
    for current, following in zip(rows, rows[1:]):
        pc = int(current["pc"])
        if pc not in ROOT_DYNAMIC_PCS or following["interrupt_before"]:
            continue
        opcode = int.from_bytes(program[pc:pc + 2], "big")
        predicted, expected_pc, outcome = branch_prediction(
            pc, opcode, int(current["sr"]), int(current["d"][0]), program
        )
        observed[pc] += 1
        outcomes[outcome] += 1
        actual_cycles = int(following["cycle"]) - int(current["cycle"])
        if int(following["pc"]) != expected_pc or actual_cycles != predicted:
            failures.append({
                "pc": f"{pc:06X}", "outcome": outcome,
                "expected_pc": f"{expected_pc:06X}",
                "actual_pc": f"{int(following['pc']):06X}",
                "predicted_cycles": predicted, "actual_cycles": actual_cycles,
            })
    report = {
        "scope": "read-only exact-MAME $02429C branch subset; not full child or SNES coverage",
        "inputs": {"summary": {"path": str(args.summary.resolve()), "sha256": sha256(args.summary)}, "trace": {"path": str(trace), "sha256": sha256(trace)}},
        "root_dynamic_pcs": [f"{pc:06X}" for pc in sorted(ROOT_DYNAMIC_PCS)],
        "observed_counts": {f"{pc:06X}": observed[pc] for pc in sorted(observed)},
        "unobserved_root_dynamic_pcs": [f"{pc:06X}" for pc in sorted(ROOT_DYNAMIC_PCS - set(observed))],
        "outcomes": dict(sorted(outcomes.items())),
        "failures": failures,
        "result": "green" if observed and not failures else "red",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"result": report["result"], "observed": sum(observed.values()), "output": str(args.output)}, sort_keys=True))
    return 0 if report["result"] == "green" else 1


if __name__ == "__main__":
    raise SystemExit(main())
