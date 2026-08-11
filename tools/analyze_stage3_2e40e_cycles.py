#!/usr/bin/env python3
"""Reduce exact-MAME cycle records for the `$02E40E` address leaf.

The leaf's three native charge blocks are 3/2/5 instructions, but the original
CPU-000 cost is path-dependent: D0.b below seven is 80 cycles and D0.b at or
above seven is 94.  This reducer derives those totals from the retained
cycle-stamped MAME trace; it is a ledger input, not a ROM timing repair.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ARTIFACT = ROOT / "build" / "mame-stage3-irq-phase-current-5c7e-v1"
START = 0x02E40E
RTS = 0x02E42A
STATE = re.compile(r"^M68K_STATE ([0-9A-F]+) ([0-9A-F]+) (.+?) \| ([0-9A-F]{6}):")


@dataclass(frozen=True)
class Row:
    cycles: int
    d0: int
    address: int


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def boundaries(meta: Path) -> list[tuple[int, int]]:
    answer = []
    for line in meta.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        if row.get("event") == "boundary":
            answer.append((int(row["tick"]), int(row["cycles"])))
    return answer


def parse_rows(trace: Path) -> list[Row]:
    rows: list[Row] = []
    for line in trace.read_text(encoding="utf-8").splitlines():
        match = STATE.match(line)
        if match is None:
            continue
        fields = match.group(3).split()
        if not fields:
            raise RuntimeError(f"missing D0 in trace line: {line}")
        rows.append(
            Row(
                cycles=int(match.group(1), 16),
                d0=int(fields[0], 16) & 0xFF,
                address=int(match.group(4), 16),
            )
        )
    if not rows:
        raise RuntimeError(f"no M68K state rows in {trace}")
    return rows


def tick_for_cycle(cycle: int, marks: list[tuple[int, int]]) -> int | None:
    for (tick, start), (_, end) in zip(marks, marks[1:]):
        if start <= cycle < end:
            return tick
    return None


def reduce(artifact: Path) -> dict[str, object]:
    meta = artifact / "meta.jsonl"
    trace = artifact / "trace" / "m68k.log"
    if not meta.is_file() or not trace.is_file():
        raise RuntimeError(f"incomplete MAME artifact: {artifact}")
    marks = boundaries(meta)
    rows = parse_rows(trace)
    samples: list[dict[str, int]] = []
    for index, row in enumerate(rows):
        if row.address != START:
            continue
        rts_index = next(
            (
                candidate
                for candidate in range(index + 1, len(rows))
                if rows[candidate].address == RTS
            ),
            None,
        )
        if rts_index is None or rts_index + 1 >= len(rows):
            raise RuntimeError(f"unterminated $02E40E sample at cycle {row.cycles:X}")
        elapsed = rows[rts_index + 1].cycles - row.cycles
        expected = 80 if row.d0 < 7 else 94
        if elapsed != expected:
            raise RuntimeError(
                f"$02E40E D0={row.d0:X}: {elapsed} cycles, expected {expected}"
            )
        samples.append(
            {
                "tick": tick_for_cycle(row.cycles, marks),
                "d0_byte": row.d0,
                "cycles": elapsed,
            }
        )
    if not samples:
        raise RuntimeError("trace contains no $02E40E samples")
    by_cost = {str(cost): sum(row["cycles"] == cost for row in samples) for cost in (80, 94)}
    return {
        "result": "green",
        "scope": (
            "exact-MAME CPU-000 `$02E40E` leaf cycle reduction; ledger evidence "
            "only, not an SNES timing repair, rate result, or full replay"
        ),
        "artifact": str(artifact),
        "meta_sha256": sha256(meta),
        "trace_sha256": sha256(trace),
        "samples": samples,
        "sample_count": len(samples),
        "cycles_by_path": by_cost,
        "rules": {"d0_below_7": 80, "d0_at_least_7": 94},
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact", type=Path, default=DEFAULT_ARTIFACT)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error(f"output exists: {args.output}")
    report = reduce(args.artifact.resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"result": report["result"], "samples": report["sample_count"], "output": str(args.output.resolve())}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
