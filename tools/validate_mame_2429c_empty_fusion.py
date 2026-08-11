#!/usr/bin/env python3
"""Reduce the guarded `$02429C` empty-helper fusion in exact original MAME.

The native fast arm at `$98:8E53` replaces three consecutive original native
callees.  If a future VTIME path retains that fusion, it must either charge the
complete original span exactly while no deadline can occur, or leave the fast
arm before the first original instruction.  This read-only reducer measures
that complete original span in the retained Stage-3 MAME trace.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import validate_mame_25110_branch_timing as common


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SUMMARY = ROOT / "build/mame-25110-irq-phase-current-f369-v5/summary.json"
SOURCE = ROOT / "src/escbank4.pasm"
START = 0x023342
END = 0x0242B2


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error(f"refusing to overwrite output: {args.output}")
    if not args.summary.is_file() or not SOURCE.is_file():
        parser.error("missing MAME summary or fusion source")
    summary = json.loads(args.summary.read_text(encoding="utf-8"))
    if summary.get("mame", {}).get("version") != "0.287 (mame0287)":
        raise RuntimeError("summary is not exact MAME 0.287 evidence")
    text = SOURCE.read_text(encoding="utf-8")
    for fragment in (
        "h2429c_empty_helpers:",
        "Guarded fusion for the three consecutive $02429C no-work helpers.",
        "jml.l $988000",
        "jmp entry_235e0_after_return",
    ):
        if fragment not in text:
            raise RuntimeError(f"fusion source contract missing {fragment!r}")
    trace = common.resolve(args.summary, summary["capture"]["debugger_trace"])
    rows = common.parse_trace(trace)
    spans = []
    for index, row in enumerate(rows):
        if int(row["pc"]) != START:
            continue
        end_index = next(
            (candidate for candidate in range(index + 1, len(rows)) if int(rows[candidate]["pc"]) == END),
            None,
        )
        if end_index is None:
            raise RuntimeError(f"MAME span from ${START:06X} never reaches ${END:06X}")
        if any(record["interrupt_before"] for record in rows[index + 1:end_index + 1]):
            raise RuntimeError("held IRQ cuts a retained empty-helper span")
        spans.append(
            {
                "start_cycle": int(row["cycle"]),
                "end_cycle": int(rows[end_index]["cycle"]),
                "cycles": int(rows[end_index]["cycle"]) - int(row["cycle"]),
                "instructions": end_index - index,
            }
        )
    checks = {
        "four_retained_empty_helper_spans": len(spans) == 4,
        "all_spans_have_exact_798_cpu000_cycles": bool(spans) and all(span["cycles"] == 798 for span in spans),
        "all_spans_have_exact_33_instructions": bool(spans) and all(span["instructions"] == 33 for span in spans),
        "span_is_even_two_cycle_units": bool(spans) and all(span["cycles"] % 2 == 0 for span in spans),
    }
    report = {
        "scope": "read-only exact-MAME empty-helper fusion span; not a native implementation, IRQ, rate, or gameplay result",
        "result": "green" if all(checks.values()) else "red",
        "checks": checks,
        "inputs": {
            "summary": {"path": str(args.summary.resolve()), "sha256": sha256(args.summary)},
            "trace": {"path": str(trace), "sha256": sha256(trace)},
            "fusion_source": {"path": str(SOURCE.resolve()), "sha256": sha256(SOURCE)},
        },
        "original_span": {"start_pc": f"{START:06X}", "end_pc_exclusive": f"{END:06X}", "two_cycle_units": 399},
        "spans": spans,
        "required_future_policy": (
            "an opaque native fusion may bulk-charge these 399 units only if the shared "
            "clock proves no deadline crosses; otherwise leave the fusion before `$023342` "
            "for an instruction-boundary-capable path"
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"result": report["result"], "spans": len(spans), "output": str(args.output)}, sort_keys=True))
    return 0 if report["result"] == "green" else 1


if __name__ == "__main__":
    raise SystemExit(main())
