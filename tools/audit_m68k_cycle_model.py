#!/usr/bin/env python3
"""Audit where a retained MAME trace disagrees with a static 68000 cycle table.

The MAME debugger trace is the executable timing oracle.  This read-only
reducer reconstructs a *development-only* static table through the exact
``m68kmake.py`` generator supplied on the command line and compares it with
that trace.  A mismatch means the static table alone cannot reproduce the
observed instruction-to-instruction timing.  It does *not* by itself assert
which component of the MAME core produced the difference: the debugger clock,
handler adjustment, and source/binary provenance must remain distinguishable.

It deliberately emits only hashes, PC/opcode/timing facts and aggregate
counts.  It never writes a ROM image or an emulator save state.  The purpose
is to keep a future virtual-IRQ implementation honest: a static opcode table
is a useful baseline, but it is not a complete cycle model.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
from collections import Counter
from pathlib import Path
from types import ModuleType
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROGRAM = ROOT / "data" / "superman_m68k.bin"
TRACE_LINE = re.compile(r"^([0-9A-F]+)\s+([0-9A-F]{6}):\s+(.+)$")
STATE_TRACE_LINE = re.compile(
    r"^M68K_STATE "
    r"(?P<cycle>[0-9A-F]+) "
    r"(?P<state_pc>[0-9A-F]+)"
    r"(?: [0-9A-F]+){17}"
    r" \| (?P<trace_pc>[0-9A-F]{6}): (?P<disassembly>.+)$"
)
INTERRUPT = re.compile(r"^\s*\(interrupted at [0-9A-F]{6}, IRQ 6\)$")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def resolve(owner: Path, metadata: dict[str, Any]) -> Path:
    path = Path(str(metadata["path"]))
    path = path if path.is_absolute() else owner.parent / path
    if not path.is_file():
        raise RuntimeError(f"missing retained artifact: {path}")
    if sha256(path) != metadata["sha256"]:
        raise RuntimeError(f"retained-artifact SHA-256 mismatch: {path}")
    return path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--summary",
        type=Path,
        required=True,
        help="green capture_mame_25110_irq_phase.py summary JSON",
    )
    parser.add_argument(
        "--m68kmake",
        type=Path,
        required=True,
        help="exact MAME m68kmake.py used only to reconstruct the static table",
    )
    parser.add_argument(
        "--m68k-list",
        type=Path,
        required=True,
        help="m68k_in.lst paired with --m68kmake",
    )
    parser.add_argument("--program", type=Path, default=DEFAULT_PROGRAM)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    for label, path in (
        ("capture summary", args.summary),
        ("MAME m68kmake.py", args.m68kmake),
        ("MAME m68k_in.lst", args.m68k_list),
        ("program image", args.program),
    ):
        if not path.is_file():
            parser.error(f"missing {label}: {path}")
    if args.output.exists():
        parser.error(f"output already exists: {args.output}")
    return args


def load_m68kmake(path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location("m68kmake_oracle", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load MAME cycle generator: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def build_static_cycles(module: ModuleType, opcode_list: Path) -> list[int]:
    """Mirror m68ki_build_opcode_table() for the CPU_TYPE_000 column."""

    info = module.Info(str(opcode_list))
    handlers = info.opcode_handlers
    # save_source() orders the emitted m68k_opcode_table this way.  The core
    # walks that emitted table in this order, so preserving it matters for any
    # overlapping opcode masks.
    order = list(range(len(handlers)))
    order.sort(
        key=lambda index: "%02d %04x %04x"
        % (
            handlers[index].bits,
            handlers[index].op_mask,
            handlers[index].op_value,
        )
    )
    table = [0] * 0x10000
    for index in order:
        handler = handlers[index]
        cycles = handler.cycles[0]  # CPU_000 / TMP68000N-8
        if cycles is None:
            continue
        extra = 0
        while True:
            table[(handler.op_value | extra) & 0xFFFF] = int(cycles)
            # m68ki_build_opcode_table uses u16 extraval.  Python integers do
            # not wrap, so make the C++ narrowing explicit here.
            extra = (((extra | handler.op_mask) + 1) & ~handler.op_mask) & 0xFFFF
            if extra == 0:
                break
    return table


def timing_class(disassembly: str) -> str:
    mnemonic = disassembly.split(maxsplit=1)[0].lower().split(".", 1)[0]
    if mnemonic in {
        "bcc", "bcs", "beq", "bge", "bgt", "bhi", "ble", "blt", "bmi",
        "bne", "bpl", "bvc", "bvs", "dbra", "dbf",
    }:
        return "conditional_branch_or_loop"
    if mnemonic in {"asl", "asr", "lsl", "lsr", "rol", "ror", "roxl", "roxr"}:
        return "variable_shift_or_rotate"
    if mnemonic.startswith("movem"):
        return "movem_register_count"
    if mnemonic.startswith(("muls", "mulu", "divs", "divu")):
        return "multiply_or_divide_operand"
    return "other_dynamic_or_trace_boundary"


def main() -> int:
    args = parse_args()
    summary = json.loads(args.summary.read_text(encoding="utf-8"))
    mame = dict(summary.get("mame", {}))
    if mame.get("version") != "0.287 (mame0287)":
        raise RuntimeError(f"capture is not the exact MAME 0.287 oracle: {mame}")
    mame_root = args.m68kmake.parents[4]
    makefile = mame_root / "makefile"
    if not makefile.is_file() or '#define BARE_BUILD_VERSION "0.287"' not in makefile.read_text(
        encoding="utf-8", errors="replace"
    ):
        raise RuntimeError(f"MAME source does not identify as 0.287: {mame_root}")
    trace = resolve(args.summary, summary["capture"]["debugger_trace"])
    program = args.program.read_bytes()
    if len(program) != 0x80000:
        raise RuntimeError(f"expected 512 KiB 68000 image, got {len(program)} bytes")
    static_cycles = build_static_cycles(load_m68kmake(args.m68kmake), args.m68k_list)

    records: list[dict[str, Any]] = []
    pending_interrupt = False
    state_trace_records = 0
    state_trace_pc_skew: Counter[int] = Counter()
    for line_number, raw in enumerate(trace.read_text(encoding="utf-8").splitlines(), 1):
        state_match = STATE_TRACE_LINE.match(raw)
        if state_match:
            cycle = int(state_match.group("cycle"), 16)
            state_pc = int(state_match.group("state_pc"), 16)
            trace_pc = int(state_match.group("trace_pc"), 16)
            # The MAME debugger's ``pc`` expression is the instruction
            # pipeline state, while the trace disassembly uses the explicit
            # instruction-hook address.  On this core the former commonly
            # points at the post-opcode-word address.  Keep both fields and
            # account for the skew; do not silently mislabel it as the
            # architectural instruction address.
            state_trace_pc_skew[(state_pc - trace_pc) & 0xFFFFFF] += 1
            records.append(
                {
                    "cycle": cycle,
                    "pc": trace_pc,
                    "state_pc": state_pc,
                    "disassembly": state_match.group("disassembly"),
                    "interrupt_before": pending_interrupt,
                    "line": line_number,
                }
            )
            pending_interrupt = False
            state_trace_records += 1
            continue
        match = TRACE_LINE.match(raw)
        if match:
            cycle, pc, disassembly = match.groups()
            records.append(
                {
                    "cycle": int(cycle, 16),
                    "pc": int(pc, 16),
                    "disassembly": disassembly,
                    "interrupt_before": pending_interrupt,
                    "line": line_number,
                }
            )
            pending_interrupt = False
            continue
        if INTERRUPT.match(raw):
            pending_interrupt = True

    if len(records) < 2:
        raise RuntimeError("debugger trace has too few instruction records")

    exact_static = 0
    static_mismatch = 0
    ignored_interrupt_boundary = 0
    non_program_pairs_excluded = 0
    by_class: Counter[str] = Counter()
    by_signature: Counter[tuple[str, int, int, str]] = Counter()
    by_site: Counter[tuple[int, int, int, int, str]] = Counter()
    special_sites = {0x02582E, 0x0259B6, 0x0259C0}
    special: dict[str, Counter[tuple[int, int, int, str]]] = {
        f"{site:06X}": Counter() for site in special_sites
    }

    for current, following in zip(records, records[1:]):
        if following["interrupt_before"]:
            ignored_interrupt_boundary += 1
            continue
        pc = int(current["pc"])
        if pc + 1 >= len(program):
            # The arcade scheduler also executes generated/relocated routines
            # from $F0 work RAM.  This retained debugger log does not include
            # instruction words, so this reducer cannot reconstruct their
            # static opcode entries without making an unverified inference
            # from disassembly text.  Count and exclude them explicitly.
            non_program_pairs_excluded += 1
            continue
        opcode = int.from_bytes(program[pc : pc + 2], "big")
        static = static_cycles[opcode]
        observed = int(following["cycle"]) - int(current["cycle"])
        if observed <= 0:
            raise RuntimeError(f"nonpositive timing delta after trace line {current['line']}")
        disassembly = str(current["disassembly"])
        if observed == static:
            exact_static += 1
            continue
        static_mismatch += 1
        category = timing_class(disassembly)
        by_class[category] += 1
        mnemonic = disassembly.split(maxsplit=1)[0].lower()
        by_signature[(category, static, observed, mnemonic)] += 1
        by_site[(pc, opcode, static, observed, disassembly)] += 1
        if pc in special_sites:
            special[f"{pc:06X}"][(opcode, static, observed, disassembly)] += 1

    total = exact_static + static_mismatch
    if total == 0:
        raise RuntimeError("trace has no comparable adjacent instruction pairs")
    report = {
        "scope": (
            "read-only static-table-versus-trace MC68000 timing audit for the retained "
            "original-MAME Stage-3 trace; it is a timing-model requirement, not a "
            "SNES repair, performance measurement, or playthrough claim"
        ),
        "inputs": {
            "capture_summary": {"path": str(args.summary.resolve()), "sha256": sha256(args.summary)},
            "debugger_trace": {"path": str(trace.resolve()), "sha256": sha256(trace)},
            "m68kmake": {"path": str(args.m68kmake.resolve()), "sha256": sha256(args.m68kmake)},
            "m68k_list": {"path": str(args.m68k_list.resolve()), "sha256": sha256(args.m68k_list)},
            "mame_makefile": {"path": str(makefile.resolve()), "sha256": sha256(makefile)},
            "program": {"path": str(args.program.resolve()), "sha256": sha256(args.program)},
        },
        "static_table": {
            "entries": len(static_cycles),
            "zero_or_illegal_entries": static_cycles.count(0),
            "maximum_cycles": max(static_cycles),
        },
        "trace_accounting": {
            "records": len(records),
            "interrupt_boundaries_excluded": ignored_interrupt_boundary,
            "work_ram_or_non_program_pairs_excluded": non_program_pairs_excluded,
            "comparable_instruction_pairs": total,
            "static_cycle_exact": exact_static,
            "static_cycle_mismatch": static_mismatch,
            "static_cycle_exact_fraction": exact_static / total,
            "static_cycle_mismatch_fraction": static_mismatch / total,
            "register_qualified_trace_records": state_trace_records,
            "register_trace_pc_pipeline_skew": [
                {"bytes": skew, "samples": samples}
                for skew, samples in state_trace_pc_skew.most_common()
            ],
        },
        "static_cycle_mismatches": {
            "by_class": dict(sorted(by_class.items())),
            "signatures": [
                {
                    "class": category,
                    "static_cycles": static,
                    "observed_cycles": observed,
                    "delta": observed - static,
                    "mnemonic": mnemonic,
                    "samples": samples,
                }
                for (category, static, observed, mnemonic), samples in by_signature.most_common()
            ],
            "sites": [
                {
                    "pc": f"{pc:06X}",
                    "opcode": f"{opcode:04X}",
                    "static_cycles": static,
                    "observed_cycles": observed,
                    "delta": observed - static,
                    "disassembly": disassembly,
                    "samples": samples,
                }
                for (pc, opcode, static, observed, disassembly), samples in by_site.most_common()
            ],
        },
        "stage3_irq_seam_sites": {
            pc: [
                {
                    "opcode": f"{opcode:04X}",
                    "static_cycles": static,
                    "observed_cycles": observed,
                    "delta": observed - static,
                    "disassembly": disassembly,
                    "samples": samples,
                }
                for (opcode, static, observed, disassembly), samples in outcomes.most_common()
            ]
            for pc, outcomes in sorted(special.items())
        },
        "conclusion": (
            "The MAME static opcode table explains only the named static subset. "
            "This exact Stage-3 trace has mismatches concentrated at branch/loop, "
            "shift/rotate, MOVEM-register-count, and arithmetic sites. The trace "
            "establishes the timing requirement; this development-only source-table "
            "comparison does not attribute every mismatch to a particular MAME-core "
            "mechanism. An accepted virtual-IRQ repair must charge both interpreted "
            "instructions and native/HLE spans in common MC68000-cycle units; a static "
            "opcode table or global reload literal alone is insufficient."
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"result": "green", "output": str(args.output)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
