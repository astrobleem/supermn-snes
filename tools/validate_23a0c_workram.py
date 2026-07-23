#!/usr/bin/env python3
"""Exact live-fixture A/B differential for the guarded $023A0C family.

Capture organic production inputs at bank-$98 entry_23a0c, then execute the
retained generated reference and the guarded work-RAM candidate from identical
registers and 64 KiB work RAM.  Both runs push the same real $023A02 return and
freeze before that caller continuation executes.

Every D/A register, CCR/mask bit, and work-RAM byte must match.  The only
permitted differences are value-checked popped bank-$98 continuation sentinels
whose low words moved when the same native body shrank.  This is bounded
function-semantic and local-cycle evidence, not fps evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path

import validate_d96_hle as base
import validate_175a0_native as common


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REFERENCE = (
    ROOT
    / "build/user-playtest-v105-investigation/"
    "interp-v111-six-shape-5fcaebb7.sfc"
)
DEFAULT_CANDIDATE = ROOT / "build/interp.sfc"
DEFAULT_STATE = (
    ROOT
    / "build/user-playtest-v105-investigation/"
    "production-v110-combat-caf6-111a-safe-coldboot-uninterrupted-3600f-v1/"
    "final.mss"
)
ENTRY_NATIVE = 0x98A200
EXIT_PC = 0x023A02
RETURN_NATIVE = 0x989CF5
RETURN_ROM_OFFSET = 0x2C1CF5
FULL_WORK_SIZE = 0x10000
# This nested native family is production-only: its callback/return chain
# requires the production xlat and fetch-choke gates.  The legal guard-miss
# interpreter path is covered separately; disabling the nested dispatcher
# mid-function is not a meaningful supported configuration.
VARIANTS = ((1, 1),)

# Retained v111 generated-body labels and the current compact-body labels.
# Each sequence is a popped synthetic bank-$98 return left as dead stack
# residue.  The validator scans for the complete exact four-byte pair.
REFERENCE_RETURNS = {
    "ce4": bytes.fromhex("00fba36d"),
    "sfx_2d8a": bytes.fromhex("00fba521"),
    "23ae2": bytes.fromhex("00fba6d3"),
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def symbol_offset(path: Path, name: str) -> int:
    for raw in path.read_text(encoding="utf-8").splitlines():
        fields = raw.split()
        if len(fields) == 2 and fields[1] == name:
            return int(fields[0].split(":", 1)[1], 16)
    raise RuntimeError(f"missing symbol {name} in {path}")


def capture_cases(
    rom: Path,
    state: Path,
    nexen: Path,
    port: int,
    count: int,
    stderr_log: Path,
) -> list[common.LiveCase]:
    cases: list[common.LiveCase] = []
    with base.McpSession(
        rom=str(rom),
        mesen=str(nexen),
        cwd=ROOT,
        port=port,
        boot_wait=8.0,
        socket_timeout=180.0,
        stderr_log=stderr_log,
    ) as m:
        m.pause()
        m.load_state(str(state))
        m.pause()
        hook = m.add_exec_hook(ENTRY_NATIVE, cpu_type="Sa1")
        m.drain_notifications(timeout=0.05)
        previous_cycles = -1
        try:
            for index in range(count):
                hit = m.run_until(max_frames=180, hook_handle=hook)
                if (hit or {}).get("reason") != "hookFired":
                    raise RuntimeError(
                        f"capture {index} did not reach entry_23a0c: {hit!r}"
                    )
                m.pause()
                cycles = int(m.get_cpu_state("Sa1")["cycleCount"])
                if cycles <= previous_cycles:
                    raise RuntimeError("entry capture did not advance")
                previous_cycles = cycles
                regs = common.captured_regs(m)
                if regs["A5"] != 0x00F00000:
                    raise RuntimeError(
                        f"capture A5 is not canonical work RAM: "
                        f"${regs['A5'] & 0xFFFFFF:06X}"
                    )
                work = bytes(
                    m.read_memory(base.SNES_SPACE, 0x400000, FULL_WORK_SIZE)
                )
                tick = common.be16(work, 0x1C56)
                cases.append(
                    common.LiveCase(
                        name=f"live-{index:02d}-tick-{tick}",
                        regs=regs,
                        sr=common.captured_sr(m),
                        work=work,
                        tick=tick,
                        exit_pc=EXIT_PC,
                    )
                )
        finally:
            m.remove_hook(hook)
    return cases


def write_u16(m: base.McpSession, address: int, value: int) -> None:
    m.write_u16(address, value & 0xFFFF, base.DP_SPACE)


def run_case(
    m: base.McpSession,
    nat: Path,
    case: common.LiveCase,
    xlat_gate: int,
    choke_gate: int,
) -> base.Result:
    m.load_state(str(nat))
    m.pause()
    reg_blob = b"".join(base.le32(case.regs[name]) for name in base.REG_NAMES)
    m.write_memory(base.DP_SPACE, 0x00, reg_blob.hex())
    for offset in range(0, FULL_WORK_SIZE, 0x4000):
        m.write_memory(
            base.SNES_SPACE,
            0x400000 + offset,
            case.work[offset : offset + 0x4000].hex(),
        )
    common.park_snes_cpu(m)
    # run_until observes hook counters on a polling cadence.  Replace only
    # the not-yet-executed caller continuation with a validation-only BRA
    # self-loop so any polling tail cannot mutate emulated state.
    m.write_memory("snesPrgRom", RETURN_ROM_OFFSET, "80fe")
    if bytes(m.read_memory("snesPrgRom", RETURN_ROM_OFFSET, 2)) != b"\x80\xfe":
        raise RuntimeError("failed to install validation-only return spin")

    flags = case.sr & base.CCR_MASK
    write_u16(m, 0x6E, flags & 1)
    write_u16(m, 0x72, (flags >> 1) & 1)
    write_u16(m, 0x60, (flags >> 2) & 1)
    write_u16(m, 0x70, (flags >> 3) & 1)
    write_u16(m, 0xA2, (flags >> 4) & 1)
    # Mask unrelated asynchronous SA-1 IRQ delivery for this bounded local
    # span.  The function never changes the 68K mask; report its captured
    # entry mask in the result below.
    write_u16(m, 0x7C, 7)
    # entry_23a0c recreates the skipped JSR push from $40:$42.  Use its real
    # bank-$98 caller continuation and stop on that native PC before the
    # caller executes entry_23b52.
    write_u16(m, 0x40, RETURN_NATIVE & 0xFFFF)
    write_u16(m, 0x42, 0x00FB)
    write_u16(m, 0x4A, 0)
    write_u16(m, 0x4C, 0)
    write_u16(m, 0xA4, case.regs["A7"] & 0xFFFF)
    write_u16(m, 0xA6, (case.regs["A7"] >> 16) & 0xFFFF)
    write_u16(m, 0xA8, 1)
    write_u16(m, 0xAA, 0)
    write_u16(m, 0xAC, 0x7000)
    write_u16(m, 0x0702, 0)
    write_u16(m, 0x0704, 1)
    write_u16(m, 0x0710, EXIT_PC & 0xFFFF)
    write_u16(m, 0x0712, 0)
    write_u16(m, 0x0714, 0)
    write_u16(m, 0x0716, (EXIT_PC >> 16) & 0xFF)
    write_u16(m, 0x0718, 0xFFF8)
    write_u16(m, 0x071A, xlat_gate)
    write_u16(m, 0x072E, 0)
    write_u16(m, 0x0730, 0)
    write_u16(m, 0x0734, 0)
    write_u16(m, 0x0736, 0)
    write_u16(m, 0x0738, 0)
    write_u16(m, 0x073A, choke_gate)
    write_u16(m, 0x073C, 0)

    hook = m.add_exec_hook(RETURN_NATIVE, cpu_type="Sa1")
    m.drain_notifications(timeout=0.05)
    base.set_sa1_pc(m, ENTRY_NATIVE)
    start_cycles = int(m.get_cpu_state("Sa1")["cycleCount"])
    hit = m.run_until(max_frames=60, hook_handle=hook)
    m.pause()
    m.remove_hook(hook)
    if (hit or {}).get("reason") != "hookFired":
        cpu = m.get_cpu_state("Sa1")
        observed = (
            (int(cpu.get("k", 0)) << 16) | int(cpu.get("pc", 0))
        )
        raise RuntimeError(
            f"{case.name} did not reach native return ${RETURN_NATIVE:06X}; "
            f"observed ${observed:06X}, xlat={xlat_gate}, choke={choke_gate}: "
            f"{hit!r}"
        )
    end_cycles = int(m.get_cpu_state("Sa1")["cycleCount"])
    sr = 0x2000 | (case.sr & 0x0700) | common.captured_ccr(m)
    return base.Result(
        common.captured_regs(m),
        sr,
        bytes(m.read_memory(base.SNES_SPACE, 0x400000, FULL_WORK_SIZE)),
        end_cycles - start_cycles,
    )


def run_rom(
    rom: Path,
    nexen: Path,
    nat: Path,
    cases: list[common.LiveCase],
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
                results[(case.name, xlat_gate, choke_gate)] = run_case(
                    m, nat, case, xlat_gate, choke_gate
                )
    return results


def compare(
    case: common.LiveCase,
    reference: base.Result,
    candidate: base.Result,
    candidate_returns: dict[str, bytes],
    xlat_gate: int,
    choke_gate: int,
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
        for offset, pair in enumerate(zip(reference.work, candidate.work))
        if pair[0] != pair[1]
    ]
    allowed: set[int] = set()
    residue_rows: list[dict] = []
    for name, reference_bytes in REFERENCE_RETURNS.items():
        candidate_bytes = candidate_returns[name]
        positions = []
        for offset in range(FULL_WORK_SIZE - 3):
            if (
                reference.work[offset : offset + 4] == reference_bytes
                and candidate.work[offset : offset + 4] == candidate_bytes
            ):
                positions.append(offset)
                allowed.update(range(offset, offset + 4))
        residue_rows.append(
            {
                "name": name,
                "reference": reference_bytes.hex(),
                "candidate": candidate_bytes.hex(),
                "addresses": [f"F0{offset:04X}" for offset in positions],
            }
        )
    work_mismatches = [
        offset for offset in all_work_mismatches if offset not in allowed
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
        "work_mismatch_first": [
            f"F0{offset:04X}" for offset in work_mismatches[:32]
        ],
        "allowed_return_residue": residue_rows,
        "reference_cycles": reference.cycles,
        "candidate_cycles": candidate.cycles,
        "local_cycle_delta": (reference.cycles or 0) - (candidate.cycles or 0),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reference-rom", type=Path, default=DEFAULT_REFERENCE)
    parser.add_argument("--candidate-rom", type=Path, default=DEFAULT_CANDIDATE)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--nexen", type=Path, default=base.DEFAULT_NEXEN)
    parser.add_argument("--nat", type=Path, default=base.DEFAULT_NAT)
    parser.add_argument("--candidate-sym", type=Path, default=ROOT / "src/escbank4.sym")
    parser.add_argument("--port", type=int, default=7760)
    parser.add_argument("--cases", type=int, default=6)
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
    if args.output.exists():
        parser.error(f"output already exists: {args.output}")
    args.output.mkdir(parents=True)

    candidate_returns = {
        name: bytes(
            (
                0x00,
                0xFB,
                (symbol_offset(args.candidate_sym, symbol) >> 8) & 0xFF,
                symbol_offset(args.candidate_sym, symbol) & 0xFF,
            )
        )
        for name, symbol in {
            "ce4": "br23a0c_1",
            "sfx_2d8a": "br23a0c_2",
            "23ae2": "br23a0c_3",
        }.items()
    }
    provenance = {
        "event": "provenance",
        "scope": (
            "live-fixture function-local $023A0C Nexen reference/candidate "
            "differential; all D/A registers, CCR/mask, full 64 KiB work RAM; "
            "not fps"
        ),
        "reference_rom": str(args.reference_rom.resolve()),
        "reference_rom_sha256": sha256(args.reference_rom),
        "candidate_rom": str(args.candidate_rom.resolve()),
        "candidate_rom_sha256": sha256(args.candidate_rom),
        "state": str(args.state.resolve()),
        "state_sha256": sha256(args.state),
        "entry_native": f"{ENTRY_NATIVE:06X}",
        "return_native": f"{RETURN_NATIVE:06X}",
        "cases": args.cases,
        "variants_per_case": len(VARIANTS),
        "reference_returns": {
            name: value.hex() for name, value in REFERENCE_RETURNS.items()
        },
        "candidate_returns": {
            name: value.hex() for name, value in candidate_returns.items()
        },
        "time": time.time(),
    }
    print(json.dumps(provenance, sort_keys=True), flush=True)
    cases = capture_cases(
        args.reference_rom,
        args.state,
        args.nexen,
        args.port,
        args.cases,
        args.output / "capture.stderr.log",
    )
    events: list[dict] = [provenance]
    for index, case in enumerate(cases):
        (args.output / f"case-{index:02d}.work.bin").write_bytes(case.work)
        fixture = {
            "event": "fixture",
            "name": case.name,
            "tick": case.tick,
            "sr": case.sr,
            "regs": case.regs,
            "work_sha256": hashlib.sha256(case.work).hexdigest(),
        }
        (args.output / f"case-{index:02d}.json").write_text(
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
        args.output / "reference.stderr.log",
    )
    candidate = run_rom(
        args.candidate_rom,
        args.nexen,
        args.nat,
        cases,
        args.port + 2,
        args.output / "candidate.stderr.log",
    )
    for case in cases:
        for xlat_gate, choke_gate in VARIANTS:
            key = (case.name, xlat_gate, choke_gate)
            event = compare(
                case,
                reference[key],
                candidate[key],
                candidate_returns,
                xlat_gate,
                choke_gate,
            )
            events.append(event)
            print(json.dumps(event, sort_keys=True), flush=True)

    case_events = [event for event in events if event.get("event") == "case"]
    green = sum(event["result"] == "green" for event in case_events)
    summary = {
        "event": "summary",
        "green": green,
        "red": len(case_events) - green,
        "total": len(case_events),
        "result": "green" if green == len(case_events) else "red",
        "time": time.time(),
    }
    events.append(summary)
    print(json.dumps(summary, sort_keys=True), flush=True)
    (args.output / "results.jsonl").write_text(
        "".join(json.dumps(event, sort_keys=True) + "\n" for event in events),
        encoding="utf-8",
    )
    return 0 if summary["result"] == "green" else 1


if __name__ == "__main__":
    raise SystemExit(main())
