#!/usr/bin/env python3
"""Trace `$02429C` native-return seams from retained controlled fixtures.

This is a forensic companion to ``validate_2429c_native.py``.  It starts
each run from an immutable, documented direct fixture (not a newly saved
emulator state), masks unrelated IRQ delivery, and records the virtual
MC68000 CCR/X, stack pointer, virtual PC, task scheduler fields, register
file, and work-RAM fingerprints at each callable return seam.  Original
MAME 0.287 supplies corresponding MC68000 return-PC snapshots; those are
prefetch snapshots, so they are suitable for CCR/register attribution but
not an RTS-stack precision claim.

The scope is specifically the two native-only red arms discovered by the
three-way distinct-arm gate.  It is not a fresh gameplay replay, an IRQ-cadence
measurement, or a save-state-resume test.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from dataclasses import replace
from pathlib import Path

import validate_175a0_native as common
import validate_2429c_native as root
import validate_d96_hle as base
from mame_0287 import MAME, environment as mame_environment
from mame_0287 import identity as mame_identity


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FIXTURES = ROOT / "build/gen-2429c-distinct-arm-fixtures-current-5c7e-v1"
DEFAULT_ROM = ROOT / "build/interp.sfc"

# Each row pairs an original 68000 post-call PC with the native continuation
# that owns the same point when nested translation is enabled.
ROUTES = {
    "synthetic-active-child-overlap-and-status-counter": (
        ("after_235e0", 0x0242B8, 0x998613),
        ("after_25110", 0x0242BE, 0x998621),
    ),
    "synthetic-active-root-lower-render-and-expiry-path": (
        ("after_indirect_ce4", 0x02436E, 0x998964),
        ("after_2443a", 0x024378, 0x99898F),
        ("after_244d4", 0x0243DA, 0x998B2F),
    ),
}


def sha256(data: bytes | Path) -> str:
    if isinstance(data, Path):
        data = data.read_bytes()
    return hashlib.sha256(data).hexdigest()


def virtual_pc(m: base.McpSession) -> int:
    return common.read_u16(m, 0x40) | ((common.read_u16(m, 0x42) & 0xFF) << 16)


def snapshot_nexen(m: base.McpSession, name: str, address: int) -> dict:
    work = bytes(m.read_memory(base.SNES_SPACE, 0x400000, root.MAPPED_WORK_SIZE))
    return {
        "seam": name,
        "native_address": f"{address:06X}",
        "virtual_pc": f"{virtual_pc(m):06X}",
        "sr": common.captured_sr(m),
        "ccr": common.captured_ccr(m),
        "sp": common.captured_regs(m)["A7"] & 0xFFFFFFFF,
        "scheduler": {
            "ac": common.read_u16(m, 0xAC),
            "task_mask": common.read_u16(m, 0x0702),
            "task_active": common.read_u16(m, 0x0704),
            "irq_count": common.read_u16(m, 0x4A),
            "irq_pending": common.read_u16(m, 0x4C),
        },
        "regs": common.captured_regs(m),
        "work_sha256": sha256(work),
        "stack_around_a7": bytes(
            m.read_memory(
                base.SNES_SPACE,
                0x400000 + ((common.captured_regs(m)["A7"] - 16) & 0xFFFF),
                48,
            )
        ).hex(),
    }


def prepare_nexen(
    m: base.McpSession,
    nat: Path,
    case: common.LiveCase,
    *,
    xlat_gate: int,
) -> None:
    """Install exactly the no-save state used by the root differential."""

    m.load_state(str(nat))
    m.pause()
    # The direct differential activates this packed debug seam only in RAM so
    # it can freeze at the original coroutine boundary.  Route stops happen
    # earlier, but preserve identical process setup.
    for rom_offset in (0x0000EB, 0x0080EB):
        actual = bytes(m.read_memory("snesPrgRom", rom_offset, 3))
        if actual not in (bytes.fromhex("8001ea"), bytes.fromhex("2081e2")):
            raise RuntimeError(
                f"unexpected dbg_fetch pack at ROM ${rom_offset:06X}: {actual.hex()}"
            )
        m.write_memory("snesPrgRom", rom_offset, "2081e2")

    isolated = replace(case, sr=case.sr | 0x0700)
    reg_blob = b"".join(base.le32(isolated.regs[name]) for name in base.REG_NAMES)
    m.write_memory(base.DP_SPACE, 0x00, reg_blob.hex())
    for offset in range(0, len(isolated.work), 0x4000):
        m.write_memory(
            base.SNES_SPACE,
            0x400000 + offset,
            isolated.work[offset : offset + 0x4000].hex(),
        )
    common.park_snes_cpu(m)

    flags = isolated.sr & base.CCR_MASK
    common.write_u16(m, 0x6E, flags & 1)
    common.write_u16(m, 0x72, (flags >> 1) & 1)
    common.write_u16(m, 0x60, (flags >> 2) & 1)
    common.write_u16(m, 0x70, (flags >> 3) & 1)
    common.write_u16(m, 0xA2, (flags >> 4) & 1)
    common.write_u16(m, 0x7C, (isolated.sr >> 8) & 7)
    common.write_u16(m, 0x40, root.ENTRY_PC & 0xFFFF)
    common.write_u16(m, 0x42, root.ENTRY_PC >> 16)
    common.write_u16(m, 0x4A, 0)
    common.write_u16(m, 0x4C, 0)
    common.write_u16(m, 0xA4, isolated.regs["A7"] & 0xFFFF)
    common.write_u16(m, 0xA6, isolated.regs["A7"] >> 16)
    common.write_u16(m, 0xA8, 1)
    common.write_u16(m, 0xAA, 0)
    common.write_u16(m, 0xAC, 0xFFFF)
    common.write_u16(m, 0x0702, 0)
    common.write_u16(m, 0x0704, 1)
    common.write_u16(m, 0x0710, case.exit_pc & 0xFFFF)
    common.write_u16(m, 0x0712, 0)
    common.write_u16(m, 0x0714, 0)
    common.write_u16(m, 0x0716, case.exit_pc >> 16)
    common.write_u16(m, 0x0718, 0xFFF8)
    common.write_u16(m, 0x071A, xlat_gate)
    common.write_u16(m, 0x072E, 0)
    common.write_u16(m, 0x0730, 0)
    common.write_u16(m, 0x0734, 0)
    common.write_u16(m, 0x0736, 0)
    common.write_u16(m, 0x0738, 0)
    common.write_u16(m, 0x073A, 0)
    common.write_u16(m, 0x073C, 0)
    base.set_sa1_pc(m, root.ENTRY_NATIVE)


def nexen_route(
    rom: Path,
    nexen: Path,
    nat: Path,
    case: common.LiveCase,
    route: tuple[tuple[str, int, int], ...],
    *,
    xlat_gate: int,
    port: int,
    stderr_log: Path,
) -> dict:
    record: dict = {
        "xlat_gate": xlat_gate,
        "route": [],
        "missing": [],
    }
    with base.McpSession(
        rom=str(rom), mesen=str(nexen), cwd=ROOT, port=port,
        boot_wait=8.0, socket_timeout=180.0, stderr_log=stderr_log,
    ) as m:
        prepare_nexen(m, nat, case, xlat_gate=xlat_gate)
        for seam, _mame_pc, native_address in route:
            hook = m.add_exec_hook(native_address, cpu_type="Sa1")
            m.drain_notifications(timeout=0.05)
            hit = m.run_until(max_frames=24, hook_handle=hook)
            m.pause()
            m.remove_hook(hook)
            if (hit or {}).get("reason") != "hookFired":
                record["missing"].append(
                    {"seam": seam, "native_address": f"{native_address:06X}", "hit": hit}
                )
                break
            record["route"].append(snapshot_nexen(m, seam, native_address))
    return record


def mame_snapshot(
    session: base.MameSession, case: common.LiveCase, seam: str, pc: int
) -> dict:
    session.pause()
    session.write_block(0xF00000, case.work[:root.MAPPED_WORK_SIZE])
    for name in base.REG_NAMES[:-1]:
        session.set_reg(name, case.regs[name])
    session.set_reg("SR", case.sr | 0x0700)
    session.set_reg("USP", case.regs["A7"])
    session.set_reg("SP", case.regs["A7"])
    session.set_reg("PC", root.ENTRY_PC)
    captured = session.cmd(
        "capture_at_pc", pc=pc, addr=0xF00000, len=root.MAPPED_WORK_SIZE,
        nth=1, maxFrames=60, timeout=60,
    )
    if not captured.get("registers"):
        raise RuntimeError(f"MAME did not reach ${pc:06X} for {case.name}/{seam}: {captured!r}")
    regs = captured["registers"]
    work = bytes.fromhex(captured["hex"])
    return {
        "seam": seam,
        "mame_pc": f"{pc:06X}",
        "prefetch_snapshot": bool(not captured.get("precise", False)),
        "sr": regs["SR"] & 0xFFFF,
        "ccr": regs["SR"] & base.CCR_MASK,
        "sp": regs["SP"] & 0xFFFFFFFF,
        "regs": {name: regs[name] & 0xFFFFFFFF for name in base.REG_NAMES[:-1]} | {"A7": regs["SP"] & 0xFFFFFFFF},
        "work_sha256": sha256(work),
        "stack_around_sp": bytes(
            session.read_block(((regs["SP"] - 16) & 0xFFFFFF), 48)
        ).hex(),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    parser.add_argument("--fixtures", type=Path, default=DEFAULT_FIXTURES)
    parser.add_argument("--nexen", type=Path, default=base.DEFAULT_NEXEN)
    parser.add_argument("--nat", type=Path, default=base.DEFAULT_NAT)
    parser.add_argument("--port", type=int, default=7680)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    for path in (args.rom, args.fixtures, args.nexen, args.nat):
        if not path.exists():
            parser.error(f"missing required input: {path}")
    if args.output.exists():
        parser.error(f"refusing to overwrite output: {args.output}")

    oracle = mame_identity()
    os.environ.update(mame_environment())
    cases = {case.name: case for case in root.load_cases(args.fixtures, 3)}
    events: list[dict] = [{
        "event": "provenance",
        "scope": (
            "controlled `$02429C` return-seam forensic; direct fixtures, IRQ masked; "
            "not fresh gameplay, save-resume, or rate evidence"
        ),
        "mame": oracle,
        "nexen": str(args.nexen.resolve()),
        "nexen_sha256": sha256(args.nexen),
        "rom": str(args.rom.resolve()),
        "rom_sha256": sha256(args.rom),
        "nat": str(args.nat.resolve()),
        "nat_sha256": sha256(args.nat),
        "fixtures": str(args.fixtures.resolve()),
        "time": time.time(),
    }]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    for case_index, (case_name, route) in enumerate(ROUTES.items()):
        case = cases[case_name]
        mame_rows = []
        for seam_index, (seam, mame_pc, _native_address) in enumerate(route):
            mame = base.MameSession(
                mame=str(MAME), system="superman", rompath=str(base.MAME_TRACE / "roms"),
                workdir=str(base.MAME_TRACE), extra_args=["-video", "none", "-sound", "none", "-nothrottle"],
            )
            try:
                mame.launch(boot_wait=25)
                mame_rows.append(mame_snapshot(mame, case, seam, mame_pc))
            finally:
                mame.stop()
        nexen_rows = {
            str(gate): nexen_route(
                args.rom, args.nexen, args.nat, case, route, xlat_gate=gate,
                port=args.port + case_index * 4 + gate,
                stderr_log=args.output.parent / f"{args.output.stem}-{case_index}-gate{gate}.nexen.stderr.log",
            )
            for gate in (0, 1)
        }
        event = {
            "event": "case",
            "case": case_name,
            "fixture_work_sha256": sha256(case.work),
            "mame": mame_rows,
            "nexen": nexen_rows,
        }
        events.append(event)
        print(json.dumps(event, sort_keys=True), flush=True)

    events.append({"event": "summary", "cases": len(ROUTES), "result": "green"})
    args.output.write_text("".join(json.dumps(event, sort_keys=True) + "\n" for event in events), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
