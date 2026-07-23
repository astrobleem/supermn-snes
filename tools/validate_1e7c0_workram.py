#!/usr/bin/env python3
"""Exact baseline/candidate differential for the guarded $01E7C0 A0 fast path.

Organic sustained-gameplay fixtures are captured at the fixed bank-$98 task
entry from the retained baseline ROM.  Two fresh Nexen processes then execute
the baseline and candidate roots from identical registers and 64 KiB work RAM,
freezing at the real $01E7BE trap boundary.  All D/A registers, CCR/mask, and
the full work-RAM image must match for nested-xlat off, on, and on+fetch-choke.

This proves the specialization is observationally identical to the retained
production baseline over the captured function spans.  Arcade truth remains a
separate full-tick MAME lockstep gate; these local cycle deltas are not fps.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path

import validate_d96_hle as base
import validate_1e7c0_native as root


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REFERENCE = (
    ROOT / "build/playability-20260720/1e7c0-workram-reference-v1/interp.sfc"
)
VARIANTS = ((0, 0), (1, 0), (1, 1))
DEFAULT_REFERENCE_BR10 = 0xE00A


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def symbol_offset(path: Path, name: str) -> int:
    for raw in path.read_text().splitlines():
        fields = raw.split()
        if len(fields) == 2 and fields[1] == name:
            bank, offset = fields[0].split(":", 1)
            if bank != "00":
                raise RuntimeError(f"unexpected symbol bank for {name}: {fields[0]}")
            return int(offset, 16)
    raise RuntimeError(f"missing symbol {name} in {path}")


def run_rom(
    rom: Path,
    nexen: Path,
    nat: Path,
    cases: list[root.LiveCase],
    port: int,
    stderr_log: Path,
) -> dict[tuple[str, int, int], base.Result]:
    results: dict[tuple[str, int, int], base.Result] = {}
    with base.McpSession(
        rom=str(rom),
        mesen=str(nexen),
        cwd=ROOT,
        port=port,
        boot_wait=8.0,
        socket_timeout=180.0,
        stderr_log=stderr_log,
    ) as m:
        for case in cases:
            for xlat_gate, choke_gate in VARIANTS:
                results[(case.name, xlat_gate, choke_gate)] = root.nexen_result(
                    m,
                    nat,
                    case,
                    xlat_gate=xlat_gate,
                    choke_gate=choke_gate,
                    work_size=root.FULL_WORK_SIZE,
                )
    return results


def compare(
    case: root.LiveCase,
    reference: base.Result,
    candidate: base.Result,
    xlat_gate: int,
    choke_gate: int,
    reference_br10: int,
    candidate_br10: int,
) -> dict:
    reg_mismatches = {
        name: {
            "reference": reference.regs[name],
            "candidate": candidate.regs[name],
        }
        for name in base.REG_NAMES
        if reference.regs[name] != candidate.regs[name]
    }
    all_work_mismatches = [
        offset
        for offset, (left, right) in enumerate(zip(reference.work, candidate.work))
        if left != right
    ]
    # The guarded jsr(a4) bridge pushes $00FB:br1e7c0_10 on the emulated
    # stack.  The call pops it, but its low address word remains as dead stack
    # residue at entry-A7-$10.  Shrinking this same body relocates br10, so
    # value-check precisely those two bytes; no other residue is exempt.
    residue = ((case.regs["A7"] & 0xFFFF) - 0x10) & 0xFFFF
    expected_layout = {
        residue: ((reference_br10 >> 8) & 0xFF, (candidate_br10 >> 8) & 0xFF),
        (residue + 1) & 0xFFFF: (reference_br10 & 0xFF, candidate_br10 & 0xFF),
    }
    allowed_layout_mismatches = [
        offset
        for offset in all_work_mismatches
        if offset in expected_layout
        and (reference.work[offset], candidate.work[offset]) == expected_layout[offset]
    ]
    work_mismatches = [
        offset for offset in all_work_mismatches if offset not in allowed_layout_mismatches
    ]
    sr_mismatch = reference.sr != candidate.sr
    green = not reg_mismatches and not work_mismatches and not sr_mismatch
    return {
        "event": "case",
        "case": case.name,
        "tick": case.tick,
        "nested_xlat_gate": xlat_gate,
        "fetch_choke_gate": choke_gate,
        "result": "green" if green else "red",
        "reg_mismatches": reg_mismatches,
        "reference_sr": reference.sr,
        "candidate_sr": candidate.sr,
        "work_mismatch_count": len(work_mismatches),
        "work_mismatch_first": [f"F0{offset:04X}" for offset in work_mismatches[:32]],
        "work_mismatch_values": [
            {
                "address": f"F0{offset:04X}",
                "reference": reference.work[offset],
                "candidate": candidate.work[offset],
            }
            for offset in work_mismatches[:32]
        ],
        "allowed_layout_residue": {
            "reason": "popped $00FB:br1e7c0_10 synthetic return at entry A7-$10",
            "offsets": [f"F0{offset:04X}" for offset in allowed_layout_mismatches],
            "reference_br10": f"98{reference_br10:04X}",
            "candidate_br10": f"98{candidate_br10:04X}",
            "exact": len(allowed_layout_mismatches) == len(all_work_mismatches),
        },
        "reference_cycles": reference.cycles,
        "candidate_cycles": candidate.cycles,
        "local_cycle_delta": (reference.cycles or 0) - (candidate.cycles or 0),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reference-rom", type=Path, default=DEFAULT_REFERENCE)
    parser.add_argument("--candidate-rom", type=Path, default=root.DEFAULT_ROM)
    parser.add_argument("--state", type=Path, default=root.DEFAULT_STATE)
    parser.add_argument("--nexen", type=Path, default=base.DEFAULT_NEXEN)
    parser.add_argument("--nat", type=Path, default=base.DEFAULT_NAT)
    parser.add_argument("--port", type=int, default=7640)
    parser.add_argument("--cases", type=int, default=6)
    parser.add_argument(
        "--reference-br10",
        type=lambda value: int(value, 0),
        default=DEFAULT_REFERENCE_BR10,
    )
    parser.add_argument(
        "--candidate-sym",
        type=Path,
        default=ROOT / "src/escbank4.sym",
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    for path in (
        args.reference_rom,
        args.candidate_rom,
        args.state,
        args.nexen,
        args.nat,
        args.candidate_sym,
    ):
        if not path.is_file():
            parser.error(f"missing required input: {path}")
    if args.cases < 1:
        parser.error("--cases must be positive")
    if args.output.exists():
        parser.error(f"output already exists: {args.output}")
    if sha256(args.reference_rom) == sha256(args.candidate_rom):
        parser.error("reference and candidate ROMs are identical")
    candidate_br10 = symbol_offset(args.candidate_sym, "br1e7c0_10")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    fixture_dir = args.output.parent / f"{args.output.stem}-fixtures"
    if fixture_dir.exists():
        parser.error(f"fixture directory already exists: {fixture_dir}")
    fixture_dir.mkdir()

    events: list[dict] = []
    provenance = {
        "event": "provenance",
        "scope": (
            "live-fixture function-local $01E7C0 Nexen baseline/candidate "
            "differential; all D/A registers, CCR/mask, full 64 KiB work RAM; not fps"
        ),
        "reference_rom": str(args.reference_rom.resolve()),
        "reference_rom_sha256": sha256(args.reference_rom),
        "candidate_rom": str(args.candidate_rom.resolve()),
        "candidate_rom_sha256": sha256(args.candidate_rom),
        "state": str(args.state.resolve()),
        "state_sha256": sha256(args.state),
        "nat": str(args.nat.resolve()),
        "nat_sha256": sha256(args.nat),
        "nexen": str(args.nexen.resolve()),
        "nexen_sha256": sha256(args.nexen),
        "entry_pc": f"{root.ENTRY_PC:06X}",
        "entry_native": f"{root.ENTRY_NATIVE:06X}",
        "terminal_pc": f"{root.EXIT_PC:06X}",
        "fixtures": args.cases,
        "variants_per_fixture": len(VARIANTS),
        "synthetic_return_layout": {
            "reference_br1e7c0_10": f"98{args.reference_br10:04X}",
            "candidate_br1e7c0_10": f"98{candidate_br10:04X}",
            "allowed_residue": "only the exact low-word bytes at entry A7-$10",
        },
        "arcade_truth_gate": "separate full-tick MAME lockstep required",
        "time": time.time(),
    }
    events.append(provenance)
    print(json.dumps(provenance, sort_keys=True), flush=True)

    cases = root.capture_live_cases(
        args.reference_rom,
        args.state,
        args.nexen,
        args.port,
        args.cases,
        fixture_dir / "capture.nexen.stderr.log",
    )
    for index, case in enumerate(cases):
        (fixture_dir / f"case-{index:02d}.work.bin").write_bytes(case.work)
        fixture = {
            "event": "fixture",
            "name": case.name,
            "tick": case.tick,
            "sr": case.sr,
            "regs": case.regs,
            "work_sha256": hashlib.sha256(case.work).hexdigest(),
        }
        (fixture_dir / f"case-{index:02d}.json").write_text(
            json.dumps(fixture, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        events.append(fixture)
        print(json.dumps(fixture, sort_keys=True), flush=True)

    reference = run_rom(
        args.reference_rom,
        args.nexen,
        args.nat,
        cases,
        args.port + 1,
        fixture_dir / "reference.nexen.stderr.log",
    )
    candidate = run_rom(
        args.candidate_rom,
        args.nexen,
        args.nat,
        cases,
        args.port + 2,
        fixture_dir / "candidate.nexen.stderr.log",
    )
    for case in cases:
        for xlat_gate, choke_gate in VARIANTS:
            key = (case.name, xlat_gate, choke_gate)
            event = compare(
                case,
                reference[key],
                candidate[key],
                xlat_gate,
                choke_gate,
                args.reference_br10,
                candidate_br10,
            )
            events.append(event)
            print(json.dumps(event, sort_keys=True), flush=True)

    case_events = [event for event in events if event.get("event") == "case"]
    green = sum(event["result"] == "green" for event in case_events)
    deltas = [event["local_cycle_delta"] for event in case_events]
    summary = {
        "event": "summary",
        "green": green,
        "red": len(case_events) - green,
        "total": len(case_events),
        "result": "green" if green == len(case_events) else "red",
        "local_cycle_delta": {
            "min": min(deltas),
            "max": max(deltas),
            "mean": sum(deltas) / len(deltas),
        },
        "time": time.time(),
    }
    events.append(summary)
    print(json.dumps(summary, sort_keys=True), flush=True)
    args.output.write_text(
        "".join(json.dumps(event, sort_keys=True) + "\n" for event in events),
        encoding="utf-8",
    )
    return 0 if summary["result"] == "green" else 1


if __name__ == "__main__":
    raise SystemExit(main())
