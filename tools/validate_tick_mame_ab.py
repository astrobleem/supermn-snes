#!/usr/bin/env python3
"""Modern injected whole-tick MAME-diff-set A/B validator.

For each stored MAME GAME_TICK triple, inject regsA/wramA into a fresh Nexen
process, start at the production native $003A92 entry, and stop at the first
$000818 production wait boundary using the diagnostic ROM's exact PC-freeze.  Run the
retained reference ROM and candidate ROM from identical inputs, then compare
their complete arcade work RAM, register files, CCR/mask, and their mismatch
sets against MAME wramB.

The execution hook watches the freeze's stable spin, not the moving game PC.
Nexen's ``run_until`` polls hook counters every 10 ms and therefore advances an
arbitrary distance past a normal execution hook; using that moving hook made
even identical-ROM A/B arms diverge.  Completion requires both the spin hook and
the exact frozen 68K PC.  `$003A92` itself cannot be the freeze target while
production escapes are enabled because its native entry bypasses interpreter
fetch.  Cycle counts include a variable spin tail and are
non-gating.  This is injected whole-tick semantic evidence, not production fps.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, "/home/chad/Mesen2/python")
os.environ["DOTNET_ROOT"] = "/home/chad/.dotnet10"
os.environ["PATH"] = "/home/chad/.dotnet10:" + os.environ.get("PATH", "")

import mesen_mcp.session as _session

_session.validate_mesen_build = lambda *_args, **_kwargs: None
from mesen_mcp import McpSession

from validate_d96_hle import set_sa1_pc


DEFAULT_NEXEN = Path(
    "/mnt/sdc1/Nexen-r5-20260712/"
    "bin/linux-x64/Release/linux-x64/publish/Nexen"
)
DEFAULT_NAT = Path("/tmp/b0_native.mss")
DEFAULT_REFERENCE = (
    ROOT / "build/playability-20260720/1e7c0-workram-reference-v1/interp.sfc"
)
DEFAULT_CANDIDATE = ROOT / "build/interp.sfc"
ENTRY_NATIVE = 0x92DB82
ENTRY_68K = 0x003A92
BOUNDARY_68K = 0x000818
DEBUG_SPIN = 0x00E2CF


@dataclass
class Triple:
    name: str
    path: Path
    regs: bytes
    work_a: bytes
    work_b: bytes

    @property
    def values(self) -> list[int]:
        return [
            int.from_bytes(self.regs[index : index + 4], "big")
            for index in range(0, len(self.regs), 4)
        ]


@dataclass
class Run:
    first_hit: dict[str, Any]
    second_hit: dict[str, Any]
    cycles: int
    work: bytes
    regs: bytes
    ccr_mask: dict[str, int]
    end: dict[str, Any]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def le16(data: bytes) -> int:
    return data[0] | (data[1] << 8)


def read_triple(path: Path) -> Triple:
    regs = (path / "regsA.bin").read_bytes()
    work_a = (path / "wramA.bin").read_bytes()
    work_b = (path / "wramB.bin").read_bytes()
    if (
        len(regs) != 72
        or len(work_a) not in (0x4000, 0x10000)
        or len(work_b) != len(work_a)
    ):
        raise RuntimeError(
            f"bad triple sizes in {path}: regs={len(regs)} "
            f"wramA={len(work_a)} wramB={len(work_b)}"
        )
    return Triple(path.name, path, regs, work_a, work_b)


def differing_rom_blocks(
    reference: bytes,
    candidate: bytes,
    block_size: int = 0x8000,
) -> list[int]:
    if len(reference) != len(candidate):
        raise RuntimeError(
            f"ROM sizes differ: reference={len(reference)} candidate={len(candidate)}"
        )
    return [
        offset
        for offset in range(0, len(reference), block_size)
        if reference[offset : offset + block_size]
        != candidate[offset : offset + block_size]
    ]


def install_rom_blocks(
    m: McpSession,
    image: bytes,
    block_offsets: list[int],
    block_size: int = 0x8000,
) -> None:
    """Install and verify only ROM blocks that differ between the A/B arms."""
    chunk_size = 0x2000
    for block in block_offsets:
        expected = image[block : block + block_size]
        for inner in range(0, len(expected), chunk_size):
            chunk = expected[inner : inner + chunk_size]
            m.write_memory("snesPrgRom", block + inner, chunk.hex())
        actual = bytes(m.read_memory("snesPrgRom", block, len(expected)))
        if actual != expected:
            raise RuntimeError(f"ROM debugger write failed at file offset ${block:06X}")


def execute_prepared_tick(
    m: McpSession,
    prepared_state: Path,
    rom_image: bytes,
    rom_blocks: list[int],
    triple: Triple,
    return_pc: int,
    entry_sp: int,
    native_pre_jsr_sp: int,
) -> Run:
    m.load_state(str(prepared_state))
    m.pause()
    install_rom_blocks(m, rom_image, rom_blocks)

    hook = m.add_exec_hook(DEBUG_SPIN, cpu_type="Sa1")
    m.drain_notifications(timeout=0.05)
    cycle_start = int(m.get_cpu_state("Sa1")["cycleCount"])
    first_hit = {
        "reason": "injectedEntry",
        "pc": ENTRY_NATIVE,
    }
    # The injected tick starts directly at the native entry.  Its first $0818
    # production wait fetch enters dbg_fetch's stable spin, so run_until's coarse hook
    # polling cannot advance any game state beyond the comparison boundary.
    second_hit = m.run_until(max_frames=1200, hook_handle=hook)
    m.pause()
    cycle_end = int(m.get_cpu_state("Sa1")["cycleCount"])
    m.remove_hook(hook)
    second_hit = dict(second_hit or {})
    frozen_pc = (
        le16(m.read_memory("Sa1Memory", 0x0040, 2))
        | ((le16(m.read_memory("Sa1Memory", 0x0042, 2)) & 0xFF) << 16)
    )
    second_hit.update(
        {
            "frozenMarker": le16(m.read_memory("Sa1Memory", 0x0712, 2)),
            "frozenPc68k": frozen_pc,
        }
    )

    work_size = len(triple.work_a)
    work = bytes(m.read_memory("snesMemory", 0x400000, work_size))
    regs = bytes(m.read_memory("Sa1Memory", 0x0000, 0x40))
    ccr_mask = {
        "c": le16(m.read_memory("Sa1Memory", 0x006E, 2)),
        "v": le16(m.read_memory("Sa1Memory", 0x0072, 2)),
        "z": le16(m.read_memory("Sa1Memory", 0x0060, 2)),
        "n": le16(m.read_memory("Sa1Memory", 0x0070, 2)),
        "x": le16(m.read_memory("Sa1Memory", 0x00A2, 2)),
        "mask": le16(m.read_memory("Sa1Memory", 0x007C, 2)) & 7,
    }
    end = {
        "pc68k": int.from_bytes(
            m.read_memory("Sa1Memory", 0x0040, 4), "little"
        )
        & 0xFFFFFF,
        "halt": le16(m.read_memory("Sa1Memory", 0x004E, 2)),
        "task_mask": le16(m.read_memory("snesMemory", 0x400002, 2)),
        "tick_1c56": int.from_bytes(work[0x1C56:0x1C58], "big"),
        "sound_ring": work[0x1C40:0x1C44].hex(),
        "injected_return_pc": return_pc,
        "injected_mame_entry_sp": entry_sp,
        "injected_native_pre_jsr_sp": native_pre_jsr_sp,
    }
    return Run(
        first_hit=first_hit,
        second_hit=second_hit,
        cycles=cycle_end - cycle_start,
        work=work,
        regs=regs,
        ccr_mask=ccr_mask,
        end=end,
    )


def run_pair(
    reference_rom: Path,
    candidate_rom: Path,
    triple: Triple,
    nexen: Path,
    nat: Path,
    ac: int,
    port: int,
    stderr_log: Path,
    prepared_state: Path,
) -> tuple[Run, Run, list[int]]:
    values = triple.values
    sr = values[17] & 0xFFFF
    entry_sp = values[15] & 0xFFFFFF
    return_pc = int.from_bytes(
        triple.work_a[entry_sp & 0xFFFF : (entry_sp & 0xFFFF) + 4], "big"
    ) & 0xFFFFFF
    # entry_3a92 is an old-convention jah2 escape: the intercepted JSR has not
    # pushed yet.  MAME's captured A7 is post-JSR, so restore pre-JSR A7 and
    # put the real stacked return in $40:$42; the native prologue pushes it and
    # recreates the captured MAME entry exactly.
    native_values = list(values[:16])
    native_values[15] = (values[15] + 4) & 0xFFFFFFFF
    reference_image = reference_rom.read_bytes()
    candidate_image = candidate_rom.read_bytes()
    rom_blocks = differing_rom_blocks(reference_image, candidate_image)

    with McpSession(
        rom=str(candidate_rom),
        mesen=str(nexen),
        cwd=ROOT,
        port=port,
        boot_wait=8.0,
        socket_timeout=300.0,
        stderr_log=stderr_log,
    ) as m:
        m.pause()
        work_size = len(triple.work_a)
        m.load_state(str(nat))
        m.pause()

        reg_blob = b"".join(
            int(value & 0xFFFFFFFF).to_bytes(4, "little")
            for value in native_values
        )
        m.write_memory("Sa1Memory", 0x0000, reg_blob.hex())
        for offset in range(0, work_size, 0x2000):
            m.write_memory(
                "snesMemory",
                0x400000 + offset,
                triple.work_a[offset : offset + 0x2000].hex(),
            )

        def w16(address: int, value: int) -> None:
            m.write_u16(address, value & 0xFFFF, "Sa1Memory")

        w16(0x40, return_pc & 0xFFFF)
        w16(0x42, (return_pc >> 16) & 0xFF)
        w16(0x60, (sr >> 2) & 1)
        w16(0x6E, sr & 1)
        w16(0x70, (sr >> 3) & 1)
        w16(0x72, (sr >> 1) & 1)
        w16(0xA2, (sr >> 4) & 1)
        w16(0x7C, (sr >> 8) & 7 or 7)
        w16(0xA4, values[16] & 0xFFFF)
        w16(0xA6, (values[16] >> 16) & 0xFFFF)
        w16(0xA8, 1)
        w16(0xAA, 0)
        w16(0x4A, 0)
        w16(0x4C, 0)
        w16(0xAC, ac)

        # Disable historical injection traps/counters, but arm exactly the
        # production escape/scheduler gates used by the current checkpoint.
        gates = {
            0x0700: 0,
            0x0702: 0,
            0x0704: 1,
            0x0710: BOUNDARY_68K & 0xFFFF,
            0x0712: 0,
            0x0714: 0,
            0x0716: (BOUNDARY_68K >> 16) & 0xFF,
            0x0718: 0xFFF8,
            0x071A: 1,
            0x072E: 1,
            0x0730: 0,
            0x0734: 0,
            0x0736: 0x5EEC,
            0x0738: 0,
            0x073A: 1,
            0x073C: 0xA55A,
            0x0768: 1,
        }
        for address, value in gates.items():
            w16(address, value)
        m.write_u16(0x410000, 0, "snesMemory")
        m.write_u16(0x410002, 0, "snesMemory")
        set_sa1_pc(m, ENTRY_NATIVE)
        m.save_state(str(prepared_state))
        m.pause()

        reference = execute_prepared_tick(
            m,
            prepared_state,
            reference_image,
            rom_blocks,
            triple,
            return_pc,
            entry_sp,
            native_values[15] & 0xFFFFFF,
        )
        candidate = execute_prepared_tick(
            m,
            prepared_state,
            candidate_image,
            rom_blocks,
            triple,
            return_pc,
            entry_sp,
            native_values[15] & 0xFFFFFF,
        )
        return reference, candidate, rom_blocks


def diff_offsets(left: bytes, right: bytes) -> list[int]:
    return [index for index, pair in enumerate(zip(left, right)) if pair[0] != pair[1]]


def summarize_run(run: Run) -> dict[str, Any]:
    return {
        "first_hit": run.first_hit,
        "second_hit": run.second_hit,
        "cycles": run.cycles,
        "ccr_mask": run.ccr_mask,
        "end": run.end,
        "work_sha256": hashlib.sha256(run.work).hexdigest(),
        "regs_sha256": hashlib.sha256(run.regs).hexdigest(),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("triples", nargs="+", type=Path)
    parser.add_argument("--reference-rom", type=Path, default=DEFAULT_REFERENCE)
    parser.add_argument("--candidate-rom", type=Path, default=DEFAULT_CANDIDATE)
    parser.add_argument("--nexen", type=Path, default=DEFAULT_NEXEN)
    parser.add_argument("--nat", type=Path, default=DEFAULT_NAT)
    parser.add_argument("--ac", type=lambda value: int(value, 0), default=0x2F60)
    parser.add_argument("--port", type=int, default=7680)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    for path in (
        args.reference_rom,
        args.candidate_rom,
        args.nexen,
        args.nat,
        *args.triples,
    ):
        if not path.exists():
            parser.error(f"missing input: {path}")
    if args.output.exists():
        parser.error(f"output already exists: {args.output}")
    args.output.mkdir(parents=True)

    triples = [read_triple(path) for path in args.triples]
    events: list[dict[str, Any]] = []
    provenance = {
        "event": "provenance",
        "scope": (
            "injected whole-tick Nexen reference/candidate A/B against stored MAME "
            "triples; native $003A92 start to exact first $000818 production "
            "wait-boundary diagnostic PC-freeze; not fps"
        ),
        "reference_rom": str(args.reference_rom.resolve()),
        "reference_rom_sha256": sha256(args.reference_rom),
        "candidate_rom": str(args.candidate_rom.resolve()),
        "candidate_rom_sha256": sha256(args.candidate_rom),
        "nexen": str(args.nexen.resolve()),
        "nexen_sha256": sha256(args.nexen),
        "nat": str(args.nat.resolve()),
        "nat_sha256": sha256(args.nat),
        "entry_native": f"{ENTRY_NATIVE:06X}",
        "entry_68k": f"{ENTRY_68K:06X}",
        "boundary_68k": f"{BOUNDARY_68K:06X}",
        "debug_spin": f"{DEBUG_SPIN:06X}",
        "cycle_scope": "includes variable PC-freeze spin polling tail; non-gating",
        "ac": args.ac,
        "triples": [str(triple.path.resolve()) for triple in triples],
        "time": time.time(),
    }
    events.append(provenance)
    print(json.dumps(provenance, sort_keys=True), flush=True)

    all_green = True
    for index, triple in enumerate(triples):
        prepared_state = args.output / f"{triple.name}-injected.mss"
        reference, candidate, rom_blocks = run_pair(
            args.reference_rom,
            args.candidate_rom,
            triple,
            args.nexen,
            args.nat,
            args.ac,
            args.port + index,
            args.output / f"{triple.name}.stderr.log",
            prepared_state,
        )
        (args.output / f"{triple.name}-reference.bin").write_bytes(reference.work)
        (args.output / f"{triple.name}-candidate.bin").write_bytes(candidate.work)
        (args.output / f"{triple.name}-reference-regs.bin").write_bytes(reference.regs)
        (args.output / f"{triple.name}-candidate-regs.bin").write_bytes(candidate.regs)

        ab_work = diff_offsets(reference.work, candidate.work)
        ab_regs = diff_offsets(reference.regs, candidate.regs)
        ref_mame = diff_offsets(reference.work, triple.work_b)
        cand_mame = diff_offsets(candidate.work, triple.work_b)
        completed = all(
            run.second_hit.get("reason") == "hookFired"
            and run.second_hit.get("frozenMarker") == 1
            and run.second_hit.get("frozenPc68k") == BOUNDARY_68K
            for run in (reference, candidate)
        )
        green = (
            completed
            and not ab_work
            and not ab_regs
            and reference.ccr_mask == candidate.ccr_mask
            and ref_mame == cand_mame
        )
        all_green &= green
        event = {
            "event": "triple",
            "triple": triple.name,
            "result": "green" if green else "red",
            "completed": completed,
            "reference": summarize_run(reference),
            "candidate": summarize_run(candidate),
            "local_cycle_delta_non_gating": reference.cycles - candidate.cycles,
            "ab_work_mismatch_count": len(ab_work),
            "ab_work_mismatch_first": [f"F0{offset:04X}" for offset in ab_work[:32]],
            "ab_work_mismatch_values": [
                {
                    "address": f"F0{offset:04X}",
                    "reference": reference.work[offset],
                    "candidate": candidate.work[offset],
                }
                for offset in ab_work[:32]
            ],
            "ab_reg_byte_mismatches": ab_regs,
            "ab_reg_mismatch_values": [
                {
                    "offset": offset,
                    "reference": reference.regs[offset],
                    "candidate": candidate.regs[offset],
                }
                for offset in ab_regs
            ],
            "mame_diff_sets_equal": ref_mame == cand_mame,
            "same_process_rom_blocks": [f"{offset:06X}" for offset in rom_blocks],
            "reference_mame_diff_count": len(ref_mame),
            "candidate_mame_diff_count": len(cand_mame),
            "reference_mame_diff_first": [f"F0{offset:04X}" for offset in ref_mame[:32]],
            "candidate_mame_diff_first": [f"F0{offset:04X}" for offset in cand_mame[:32]],
        }
        events.append(event)
        print(json.dumps(event, sort_keys=True), flush=True)

    summary = {
        "event": "summary",
        "result": "green" if all_green else "red",
        "green": sum(event.get("result") == "green" for event in events),
        "red": sum(event.get("result") == "red" for event in events),
        "total": len(triples),
        "time": time.time(),
    }
    events.append(summary)
    (args.output / "results.jsonl").write_text(
        "".join(json.dumps(event, sort_keys=True) + "\n" for event in events),
        encoding="utf-8",
    )
    print(json.dumps(summary, sort_keys=True), flush=True)
    return 0 if all_green else 1


if __name__ == "__main__":
    raise SystemExit(main())
