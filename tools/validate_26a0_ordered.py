#!/usr/bin/env python3
"""Exact live-fixture A/B differential for the ordered $26A0 fast path.

Capture organic production inputs at the retained callable bank-$92 $26A0
entry, then execute the reference and candidate from identical registers,
direct page, all 64 KiB of game RAM, and all 64 KiB of the video-shadow bank.
Both runs preserve the original helper's push/pop boundary and stop before
``br3a92_9`` executes.

The suite includes six organic cases, two synthetic hot record patterns, and
one noncanonical-A5 fallback plus a low-stack edge case.  Every D/A register,
CCR/mask bit, direct-page byte,
game-RAM byte, video-shadow byte, and final native X/Y value must match.  This
is bounded semantic evidence, not fps or end-to-end performance evidence.
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
    "interp-v118-2be2-f6d7ab43.sfc"
)
DEFAULT_CANDIDATE = ROOT / "build/interp.sfc"
DEFAULT_STATE = (
    ROOT
    / "build/user-playtest-v105-investigation/"
    "production-v110-combat-caf6-111a-safe-coldboot-uninterrupted-3600f-v1/"
    "final.mss"
)
ENTRY_REFERENCE = 0x928EF6
ENTRY_CANDIDATE = 0x928EF6
RETURN_NATIVE = 0x92DF62
RETURN_ROM_OFFSET = 0x295F62
RECORDS_OFFSET = 0x28EA
IRAM_COMPARE_SIZE = 0x0100
WORK_SIZE = 0x10000
SHADOW_SIZE = 0x10000


@dataclass
class Fixture:
    name: str
    tick: int
    path: str
    regs: dict[str, int]
    sr: int
    iram: bytes
    work: bytes
    shadow: bytes


@dataclass
class Result:
    regs: dict[str, int]
    sr: int
    iram: bytes
    work: bytes
    shadow: bytes
    host_x: int
    host_y: int


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_u16(m: base.McpSession, address: int, value: int) -> None:
    m.write_u16(address, value & 0xFFFF, base.DP_SPACE)


def record_mask(work: bytes, a5_low: int = 0) -> int:
    mask = 0
    start = (a5_low + RECORDS_OFFSET) & 0xFFFF
    for index in range(16):
        if work[(start + index * 4) & 0xFFFF] & 1:
            mask |= 1 << index
    return mask


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
        hook = m.add_exec_hook(ENTRY_REFERENCE, cpu_type="Sa1")
        m.drain_notifications(timeout=0.05)
        previous_cycles = -1
        try:
            for index in range(count):
                hit = m.run_until(max_frames=180, hook_handle=hook)
                if (hit or {}).get("reason") != "hookFired":
                    raise RuntimeError(
                        f"capture {index} did not reach the $26A0 call: {hit!r}"
                    )
                m.pause()
                cycles = int(m.get_cpu_state("Sa1")["cycleCount"])
                if cycles <= previous_cycles:
                    raise RuntimeError("$26A0 capture did not advance")
                previous_cycles = cycles
                regs = common.captured_regs(m)
                if regs["A5"] != 0x00F00000:
                    raise RuntimeError(
                        f"capture A5 is not canonical work RAM: "
                        f"${regs['A5'] & 0xFFFFFF:06X}"
                    )
                if (regs["A7"] >> 16) != 0x00F0:
                    raise RuntimeError(
                        f"capture A7 is not work RAM: "
                        f"${regs['A7'] & 0xFFFFFF:06X}"
                    )
                a7_low = regs["A7"] & 0xFFFF
                if a7_low < 4:
                    raise RuntimeError(
                        f"capture A7 cannot accept the helper return: ${a7_low:04X}"
                    )
                iram = bytes(
                    m.read_memory(base.DP_SPACE, 0, IRAM_COMPARE_SIZE)
                )
                work = bytes(
                    m.read_memory(base.SNES_SPACE, 0x400000, WORK_SIZE)
                )
                shadow = bytes(
                    m.read_memory(base.SNES_SPACE, 0x410000, SHADOW_SIZE)
                )
                tick = common.be16(work, 0x1C56)
                fixtures.append(
                    Fixture(
                        name=f"live-hot-{index:02d}-tick-{tick}",
                        tick=tick,
                        path="hot-canonical",
                        regs=regs,
                        sr=common.captured_sr(m),
                        iram=iram,
                        work=work,
                        shadow=shadow,
                    )
                )
        finally:
            m.remove_hook(hook)
    return fixtures


def with_work(
    fixture: Fixture,
    work: bytes,
    *,
    case_name: str,
    path: str,
) -> Fixture:
    return Fixture(
        name=case_name,
        tick=fixture.tick,
        path=path,
        regs=dict(fixture.regs),
        sr=fixture.sr,
        iram=fixture.iram,
        work=work,
        shadow=fixture.shadow,
    )


def replace_reg_iram(
    fixture: Fixture,
    name: str,
    value: int,
    *,
    case_name: str,
    path: str,
) -> Fixture:
    regs = dict(fixture.regs)
    regs[name] = value
    iram = bytearray(fixture.iram)
    index = base.REG_NAMES.index(name)
    iram[index * 4 : index * 4 + 4] = value.to_bytes(4, "little")
    return Fixture(
        name=case_name,
        tick=fixture.tick,
        path=path,
        regs=regs,
        sr=fixture.sr,
        iram=bytes(iram),
        work=fixture.work,
        shadow=fixture.shadow,
    )


def add_synthetic_fixtures(fixtures: list[Fixture]) -> list[Fixture]:
    first = fixtures[0]

    patterned_work = bytearray(first.work)
    for index in range(16):
        offset = RECORDS_OFFSET + index * 4
        patterned_work[offset : offset + 4] = bytes(
            (
                ((index * 0x10) & 0xFE) | (1 if index in (0, 3, 7, 15) else 0),
                (0x40 + index) & 0xFF,
                0x80 if index == 15 else index,
                (0xA0 + index) & 0xFF,
            )
        )
    patterned = with_work(
        first,
        bytes(patterned_work),
        case_name=f"hot-patterned-records-tick-{first.tick}",
        path="hot-patterned-records",
    )

    zero_work = bytearray(first.work)
    zero_work[RECORDS_OFFSET : RECORDS_OFFSET + 64] = bytes(64)
    zero = with_work(
        first,
        bytes(zero_work),
        case_name=f"hot-zero-records-tick-{first.tick}",
        path="hot-zero-records",
    )

    noncanonical = replace_reg_iram(
        first,
        "A5",
        0x00F00010,
        case_name=f"fallback-noncanonical-a5-tick-{first.tick}",
        path="fallback-noncanonical-a5",
    )
    low_stack = replace_reg_iram(
        first,
        "A7",
        0x00F00008,
        case_name=f"hot-low-stack-tick-{first.tick}",
        path="hot-low-stack",
    )
    return [*fixtures, patterned, zero, noncanonical, low_stack]


def run_fixture(
    m: base.McpSession,
    nat: Path,
    fixture: Fixture,
    entry: int,
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
        m.write_memory(
            base.SNES_SPACE,
            0x410000 + offset,
            fixture.shadow[offset : offset + 0x4000].hex(),
        )
    common.park_snes_cpu(m)

    # Isolate this bounded, already-native span from asynchronous delivery.
    write_u16(m, 0x7C, 7)
    write_u16(m, 0x7E, 0)
    write_u16(m, 0xAA, 0)
    write_u16(m, 0xAC, 0x7000)
    write_u16(m, 0x4A, 0)
    write_u16(m, 0x4C, 0)
    write_u16(m, 0x4E, 0)
    # Give both implementations one common native continuation.  The helper
    # treats this marker as opaque stack data until h26_return normalizes
    # $00FE to physical bank $92.
    write_u16(m, 0x40, RETURN_NATIVE & 0xFFFF)
    write_u16(m, 0x42, 0x00FE)
    write_u16(m, 0xA4, fixture.regs["A7"] & 0xFFFF)
    write_u16(m, 0xA6, (fixture.regs["A7"] >> 16) & 0xFFFF)
    write_u16(m, 0xA8, 1)
    write_u16(m, 0x071A, 1)
    write_u16(m, 0x073A, 1)

    # Prevent a late hook poll from executing the caller continuation.
    m.write_memory("snesPrgRom", RETURN_ROM_OFFSET, "80fe")
    if bytes(m.read_memory("snesPrgRom", RETURN_ROM_OFFSET, 2)) != b"\x80\xfe":
        raise RuntimeError("failed to install validation-only continuation spin")

    hook = m.add_exec_hook(RETURN_NATIVE, cpu_type="Sa1")
    m.drain_notifications(timeout=0.05)
    base.set_sa1_pc(m, entry)
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
    cpu = m.get_cpu_state("Sa1")
    sr = 0x2000 | (fixture.sr & 0x0700) | common.captured_ccr(m)
    return Result(
        regs=common.captured_regs(m),
        sr=sr,
        iram=bytes(m.read_memory(base.DP_SPACE, 0, IRAM_COMPARE_SIZE)),
        work=bytes(m.read_memory(base.SNES_SPACE, 0x400000, WORK_SIZE)),
        shadow=bytes(m.read_memory(base.SNES_SPACE, 0x410000, SHADOW_SIZE)),
        host_x=int(cpu.get("x", 0)) & 0xFFFF,
        host_y=int(cpu.get("y", 0)) & 0xFFFF,
    )


def run_rom(
    rom: Path,
    nexen: Path,
    nat: Path,
    fixtures: list[Fixture],
    entry: int,
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
            results[fixture.name] = run_fixture(m, nat, fixture, entry)
    return results


def mismatch_offsets(reference: bytes, candidate: bytes) -> list[int]:
    return [
        offset
        for offset, pair in enumerate(zip(reference, candidate))
        if pair[0] != pair[1]
    ]


def compare(fixture: Fixture, reference: Result, candidate: Result) -> dict:
    reg_mismatches = {
        name: {
            "reference": reference.regs[name],
            "candidate": candidate.regs[name],
        }
        for name in base.REG_NAMES
        if reference.regs[name] != candidate.regs[name]
    }
    iram_mismatches = mismatch_offsets(reference.iram, candidate.iram)
    work_mismatches = mismatch_offsets(reference.work, candidate.work)
    shadow_mismatches = mismatch_offsets(reference.shadow, candidate.shadow)
    host_mismatches = {
        name: {"reference": ref, "candidate": cand}
        for name, ref, cand in (
            ("X", reference.host_x, candidate.host_x),
            ("Y", reference.host_y, candidate.host_y),
        )
        if ref != cand
    }
    sr_mismatch = reference.sr != candidate.sr
    green = (
        not reg_mismatches
        and not iram_mismatches
        and not work_mismatches
        and not shadow_mismatches
        and not host_mismatches
        and not sr_mismatch
    )
    return {
        "event": "case",
        "case": fixture.name,
        "tick": fixture.tick,
        "path": fixture.path,
        "record_mask": record_mask(fixture.work, fixture.regs["A5"] & 0xFFFF),
        "result": "green" if green else "red",
        "reg_mismatches": reg_mismatches,
        "host_mismatches": host_mismatches,
        "reference_sr": reference.sr,
        "candidate_sr": candidate.sr,
        "iram_mismatch_count": len(iram_mismatches),
        "iram_mismatch_first": [f"{offset:04X}" for offset in iram_mismatches[:32]],
        "work_mismatch_count": len(work_mismatches),
        "work_mismatch_first": [
            f"F0{offset:04X}" for offset in work_mismatches[:32]
        ],
        "shadow_mismatch_count": len(shadow_mismatches),
        "shadow_mismatch_first": [
            f"41{offset:04X}" for offset in shadow_mismatches[:32]
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reference-rom", type=Path, default=DEFAULT_REFERENCE)
    parser.add_argument("--candidate-rom", type=Path, default=DEFAULT_CANDIDATE)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--nexen", type=Path, default=base.DEFAULT_NEXEN)
    parser.add_argument("--nat", type=Path, default=base.DEFAULT_NAT)
    parser.add_argument("--port", type=int, default=7960)
    parser.add_argument("--organic-cases", type=int, default=6)
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
    if args.organic_cases < 1:
        parser.error("--organic-cases must be positive")
    if args.output.exists():
        parser.error(f"output already exists: {args.output}")
    args.output.mkdir(parents=True)

    provenance = {
        "event": "provenance",
        "scope": (
            "live-fixture function-local game-tick $26A0 Nexen "
            "reference/candidate differential; organic and patterned hot "
            "paths plus an A5 fallback and low-stack edge case; all D/A registers, "
            "CCR/mask, first 256 direct-page bytes, full 64 KiB game RAM, "
            "full 64 KiB video shadow, native X/Y; not fps"
        ),
        "reference_rom": str(args.reference_rom.resolve()),
        "reference_rom_sha256": sha256(args.reference_rom),
        "candidate_rom": str(args.candidate_rom.resolve()),
        "candidate_rom_sha256": sha256(args.candidate_rom),
        "state": str(args.state.resolve()),
        "state_sha256": sha256(args.state),
        "entry_reference": f"{ENTRY_REFERENCE:06X}",
        "entry_candidate": f"{ENTRY_CANDIDATE:06X}",
        "return_native": f"{RETURN_NATIVE:06X}",
        "organic_cases": args.organic_cases,
        "synthetic_hot_cases": 2,
        "fallback_cases": 1,
        "edge_cases": 1,
        "time": time.time(),
    }
    events: list[dict] = [provenance]
    print(json.dumps(provenance, sort_keys=True), flush=True)
    fixtures = capture_fixtures(
        args.reference_rom,
        args.state,
        args.nexen,
        args.port,
        args.organic_cases,
        args.output / "capture.stderr.log",
    )
    fixtures = add_synthetic_fixtures(fixtures)
    for fixture in fixtures:
        event = {
            "event": "fixture",
            "name": fixture.name,
            "tick": fixture.tick,
            "path": fixture.path,
            "record_mask": record_mask(
                fixture.work, fixture.regs["A5"] & 0xFFFF
            ),
            "sr": fixture.sr,
            "regs": fixture.regs,
            "iram_sha256": hashlib.sha256(fixture.iram).hexdigest(),
            "work_sha256": hashlib.sha256(fixture.work).hexdigest(),
            "shadow_sha256": hashlib.sha256(fixture.shadow).hexdigest(),
        }
        events.append(event)
        print(json.dumps(event, sort_keys=True), flush=True)

    reference = run_rom(
        args.reference_rom,
        args.nexen,
        args.nat,
        fixtures,
        ENTRY_REFERENCE,
        args.port + 1,
        args.output / "reference.stderr.log",
    )
    candidate = run_rom(
        args.candidate_rom,
        args.nexen,
        args.nat,
        fixtures,
        ENTRY_CANDIDATE,
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
