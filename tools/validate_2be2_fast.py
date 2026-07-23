#!/usr/bin/env python3
"""Exact live-fixture A/B differential for guarded native $002BE2.

Capture organic production inputs at bank-$92 ``entry_2be2``, then execute the
retained generated reference and the guarded canonical-work-RAM candidate from
identical registers, direct page, and all 64 KiB of mapped 68K work RAM.  Both
runs use the real bank-$FE physical continuation and stop before that caller
continuation executes.

Every D/A register, CCR/mask bit, direct-page byte, and work-RAM byte must
match.  This is bounded function-semantic and local-cycle evidence, not fps
evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path

import validate_d96_hle as base
import validate_175a0_native as common


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REFERENCE = (
    ROOT
    / "build/user-playtest-v105-investigation/rom-history/"
    "interp-v116-122a4-accharge-c912fe63.sfc"
)
DEFAULT_CANDIDATE = ROOT / "build/interp.sfc"
DEFAULT_STATE = (
    ROOT
    / "build/user-playtest-v105-investigation/"
    "production-v110-combat-caf6-111a-safe-coldboot-uninterrupted-3600f-v1/"
    "final.mss"
)
ENTRY_NATIVE = 0x92B794
RETURN_NATIVE = 0x92DDB3
RETURN_ROM_OFFSET = 0x295DB3
IRAM_COMPARE_SIZE = 0x0100
WORK_SIZE = 0x10000


@dataclass
class Fixture:
    name: str
    tick: int
    regs: dict[str, int]
    sr: int
    iram: bytes
    work: bytes


@dataclass
class Result:
    regs: dict[str, int]
    sr: int
    iram: bytes
    work: bytes
    cycles: int


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_u16(m: base.McpSession, address: int, value: int) -> None:
    m.write_u16(address, value & 0xFFFF, base.DP_SPACE)


def capture_fixtures(
    rom: Path,
    state: Path,
    nexen: Path,
    port: int,
    count: int,
    stderr_log: Path,
) -> list[Fixture]:
    fixtures: list[Fixture] = []
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
        m.tool("set_input", {"port": 0, "buttons": 0x82, "hold": True})
        hook = m.add_exec_hook(ENTRY_NATIVE, cpu_type="Sa1")
        m.drain_notifications(timeout=0.05)
        previous_cycles = -1
        try:
            for index in range(count):
                hit = m.run_until(max_frames=180, hook_handle=hook)
                if (hit or {}).get("reason") != "hookFired":
                    raise RuntimeError(
                        f"capture {index} did not reach entry_2be2: {hit!r}"
                    )
                m.pause()
                cycles = int(m.get_cpu_state("Sa1")["cycleCount"])
                if cycles <= previous_cycles:
                    raise RuntimeError("entry_2be2 capture did not advance")
                previous_cycles = cycles
                regs = common.captured_regs(m)
                if regs["A5"] != 0x00F00000:
                    raise RuntimeError(
                        f"capture A5 is not canonical work RAM: "
                        f"${regs['A5'] & 0xFFFFFF:06X}"
                    )
                iram = bytes(
                    m.read_memory(base.DP_SPACE, 0, IRAM_COMPARE_SIZE)
                )
                work = bytes(
                    m.read_memory(base.SNES_SPACE, 0x400000, WORK_SIZE)
                )
                tick = common.be16(work, 0x1C56)
                fixtures.append(
                    Fixture(
                        name=f"live-{index:02d}-tick-{tick}",
                        tick=tick,
                        regs=regs,
                        sr=common.captured_sr(m),
                        iram=iram,
                        work=work,
                    )
                )
        finally:
            m.remove_hook(hook)
    return fixtures


def run_fixture(
    m: base.McpSession,
    nat: Path,
    fixture: Fixture,
) -> Result:
    m.load_state(str(nat))
    m.pause()
    m.write_memory(base.DP_SPACE, 0, fixture.iram.hex())
    for offset in range(0, WORK_SIZE, 0x4000):
        m.write_memory(
            base.SNES_SPACE,
            0x400000 + offset,
            fixture.work[offset : offset + 0x4000].hex(),
        )
    common.park_snes_cpu(m)

    # Keep the already-native span isolated from asynchronous delivery.  These
    # values are identical in both runs and do not change the function's own
    # architectural result.
    write_u16(m, 0x7C, 7)
    write_u16(m, 0x7E, 0)
    write_u16(m, 0xAA, 0)
    write_u16(m, 0xAC, 0x7000)
    write_u16(m, 0x4A, 0)
    write_u16(m, 0x4C, 0)
    write_u16(m, 0x4E, 0)
    # Use one common validation-only physical continuation.  Organic
    # continuation labels moved elsewhere in bank $92 between the retained
    # and candidate builds, but $2BE2 treats the return as opaque data.
    write_u16(m, 0x40, RETURN_NATIVE & 0xFFFF)
    write_u16(m, 0x42, 0x00FE)
    write_u16(m, 0xA4, fixture.regs["A7"] & 0xFFFF)
    write_u16(m, 0xA6, (fixture.regs["A7"] >> 16) & 0xFFFF)
    write_u16(m, 0xA8, 1)
    write_u16(m, 0x071A, 1)
    write_u16(m, 0x073A, 1)

    # A polling tail must not execute the caller if run_until observes the
    # hook one poll late.
    m.write_memory("snesPrgRom", RETURN_ROM_OFFSET, "80fe")
    if bytes(m.read_memory("snesPrgRom", RETURN_ROM_OFFSET, 2)) != b"\x80\xfe":
        raise RuntimeError("failed to install validation-only return spin")

    hook = m.add_exec_hook(RETURN_NATIVE, cpu_type="Sa1")
    m.drain_notifications(timeout=0.05)
    base.set_sa1_pc(m, ENTRY_NATIVE)
    start_cycles = int(m.get_cpu_state("Sa1")["cycleCount"])
    hit = m.run_until(max_frames=60, hook_handle=hook)
    m.pause()
    m.remove_hook(hook)
    if (hit or {}).get("reason") != "hookFired":
        cpu = m.get_cpu_state("Sa1")
        observed = (int(cpu.get("k", 0)) << 16) | int(cpu.get("pc", 0))
        raise RuntimeError(
            f"{fixture.name} did not reach ${RETURN_NATIVE:06X}; "
            f"observed ${observed:06X}: {hit!r}"
        )
    end_cycles = int(m.get_cpu_state("Sa1")["cycleCount"])
    sr = 0x2000 | (fixture.sr & 0x0700) | common.captured_ccr(m)
    return Result(
        regs=common.captured_regs(m),
        sr=sr,
        iram=bytes(m.read_memory(base.DP_SPACE, 0, IRAM_COMPARE_SIZE)),
        work=bytes(m.read_memory(base.SNES_SPACE, 0x400000, WORK_SIZE)),
        cycles=end_cycles - start_cycles,
    )


def run_rom(
    rom: Path,
    nexen: Path,
    nat: Path,
    fixtures: list[Fixture],
    port: int,
    stderr_log: Path,
) -> dict[str, Result]:
    results: dict[str, Result] = {}
    with base.McpSession(
        rom=str(rom),
        mesen=str(nexen),
        cwd=ROOT,
        port=port,
        boot_wait=8.0,
        socket_timeout=180.0,
        stderr_log=stderr_log,
    ) as m:
        for fixture in fixtures:
            results[fixture.name] = run_fixture(m, nat, fixture)
    return results


def compare(fixture: Fixture, reference: Result, candidate: Result) -> dict:
    reg_mismatches = {
        name: {
            "reference": reference.regs[name],
            "candidate": candidate.regs[name],
        }
        for name in base.REG_NAMES
        if reference.regs[name] != candidate.regs[name]
    }
    iram_mismatches = [
        offset
        for offset, pair in enumerate(zip(reference.iram, candidate.iram))
        if pair[0] != pair[1]
    ]
    work_mismatches = [
        offset
        for offset, pair in enumerate(zip(reference.work, candidate.work))
        if pair[0] != pair[1]
    ]
    sr_mismatch = reference.sr != candidate.sr
    green = (
        not reg_mismatches
        and not iram_mismatches
        and not work_mismatches
        and not sr_mismatch
    )
    return {
        "event": "case",
        "case": fixture.name,
        "tick": fixture.tick,
        "result": "green" if green else "red",
        "reg_mismatches": reg_mismatches,
        "reference_sr": reference.sr,
        "candidate_sr": candidate.sr,
        "iram_mismatch_count": len(iram_mismatches),
        "iram_mismatch_first": [f"{offset:04X}" for offset in iram_mismatches[:32]],
        "work_mismatch_count": len(work_mismatches),
        "work_mismatch_first": [
            f"F0{offset:04X}" for offset in work_mismatches[:32]
        ],
        "reference_cycles": reference.cycles,
        "candidate_cycles": candidate.cycles,
        "local_cycle_delta": reference.cycles - candidate.cycles,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reference-rom", type=Path, default=DEFAULT_REFERENCE)
    parser.add_argument("--candidate-rom", type=Path, default=DEFAULT_CANDIDATE)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--nexen", type=Path, default=base.DEFAULT_NEXEN)
    parser.add_argument("--nat", type=Path, default=base.DEFAULT_NAT)
    parser.add_argument("--port", type=int, default=7930)
    parser.add_argument("--cases", type=int, default=6)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    for path in (
        args.reference_rom,
        args.candidate_rom,
        args.state,
        args.nexen,
        args.nat,
    ):
        if not path.is_file():
            parser.error(f"missing required input: {path}")
    if args.cases < 1:
        parser.error("--cases must be positive")
    if args.output.exists():
        parser.error(f"output already exists: {args.output}")
    args.output.mkdir(parents=True)

    provenance = {
        "event": "provenance",
        "scope": (
            "live-fixture function-local $002BE2 Nexen reference/candidate "
            "differential; all D/A registers, CCR/mask, first 256 direct-page "
            "bytes, full 64 KiB work RAM; not fps"
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
        "time": time.time(),
    }
    events: list[dict] = [provenance]
    print(json.dumps(provenance, sort_keys=True), flush=True)
    fixtures = capture_fixtures(
        args.reference_rom,
        args.state,
        args.nexen,
        args.port,
        args.cases,
        args.output / "capture.stderr.log",
    )
    for fixture in fixtures:
        event = {
            "event": "fixture",
            "name": fixture.name,
            "tick": fixture.tick,
            "sr": fixture.sr,
            "regs": fixture.regs,
            "iram_sha256": hashlib.sha256(fixture.iram).hexdigest(),
            "work_sha256": hashlib.sha256(fixture.work).hexdigest(),
        }
        events.append(event)
        print(json.dumps(event, sort_keys=True), flush=True)

    reference = run_rom(
        args.reference_rom,
        args.nexen,
        args.nat,
        fixtures,
        args.port + 1,
        args.output / "reference.stderr.log",
    )
    candidate = run_rom(
        args.candidate_rom,
        args.nexen,
        args.nat,
        fixtures,
        args.port + 2,
        args.output / "candidate.stderr.log",
    )
    for fixture in fixtures:
        event = compare(
            fixture,
            reference[fixture.name],
            candidate[fixture.name],
        )
        events.append(event)
        print(json.dumps(event, sort_keys=True), flush=True)

    cases = [event for event in events if event.get("event") == "case"]
    green = sum(event["result"] == "green" for event in cases)
    summary = {
        "event": "summary",
        "green": green,
        "red": len(cases) - green,
        "total": len(cases),
        "result": "green" if green == len(cases) else "red",
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
