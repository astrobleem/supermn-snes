#!/usr/bin/env python3
"""Exact MAME/Nexen state probe at the $01E7C0 script-path join.

This diagnostic replays a retained native-entry fixture in original MAME and
the production bank-$98 root, stopping both immediately before original
$01E94A.  It reports every architectural register, CCR/X, the mapped work-RAM
window, and the native direct-page scratch image.  It is intentionally a seam
probe rather than a correctness gate; validate_1e7c0_native.py owns the
terminal function differential.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import validate_1e7c0_native as root
import validate_175a0_native as common
import validate_d96_hle as base


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FIXTURES = (
    ROOT
    / "build/playtest-investigation-20260725"
    / "failure-3043-1e7c0-frozen-entry-2927-f3b2384-on-v1"
    / "fixtures"
)
DEFAULT_OUTPUT = (
    ROOT
    / "build/playtest-investigation-20260725"
    / "failure-3043-1e7c0-script-seam-probe.json"
)
DEFAULT_MAME_SEAM = 0x01E94A
DEFAULT_NATIVE_SEAM = 0x98B814


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def setup_nexen(
    m: base.McpSession,
    nat: Path,
    case: root.LiveCase,
) -> None:
    m.load_state(str(nat))
    m.pause()
    reg_blob = b"".join(base.le32(case.regs[name]) for name in base.REG_NAMES)
    m.write_memory(base.DP_SPACE, 0x00, reg_blob.hex())
    for offset in range(0, len(case.work), 0x4000):
        m.write_memory(
            base.SNES_SPACE,
            0x400000 + offset,
            case.work[offset : offset + 0x4000].hex(),
        )
    common.park_snes_cpu(m)

    flags = case.sr & base.CCR_MASK
    root.write_u16(m, 0x6E, flags & 1)
    root.write_u16(m, 0x72, (flags >> 1) & 1)
    root.write_u16(m, 0x60, (flags >> 2) & 1)
    root.write_u16(m, 0x70, (flags >> 3) & 1)
    root.write_u16(m, 0xA2, (flags >> 4) & 1)
    root.write_u16(m, 0x7C, (case.sr >> 8) & 7)
    root.write_u16(m, 0x40, root.ENTRY_PC & 0xFFFF)
    root.write_u16(m, 0x42, (root.ENTRY_PC >> 16) & 0xFF)
    root.write_u16(m, 0x4A, 0)
    root.write_u16(m, 0x4C, 0)
    root.write_u16(m, 0x4E, 0)
    root.write_u16(m, 0x7E, 0)
    root.write_u16(m, 0xA0, 0)
    root.write_u16(m, 0xA4, case.regs["A7"] & 0xFFFF)
    root.write_u16(m, 0xA6, (case.regs["A7"] >> 16) & 0xFFFF)
    root.write_u16(m, 0xA8, 1)
    root.write_u16(m, 0xAA, 0)
    root.write_u16(m, 0xAC, 0x7000)
    root.write_u16(m, 0x071A, 1)
    root.write_u16(m, 0x073A, 0)


def mame_capture(case: root.LiveCase, mame_seam: int) -> dict:
    mame = base.MameSession(
        mame="/snap/bin/mame",
        system="superman",
        rompath=str(base.MAME_TRACE / "roms"),
        workdir=str(base.MAME_TRACE),
        state_directory=str(base.MAME_TRACE / "sta"),
        extra_args=["-video", "none", "-sound", "none", "-nothrottle"],
    )
    try:
        mame.launch(boot_wait=25)
        mame.pause()
        mame.write_block(0xF00000, case.work[: root.MAPPED_WORK_SIZE])
        for name in base.REG_NAMES[:-1]:
            mame.set_reg(name, case.regs[name])
        mame.set_reg("SR", case.sr | 0x0700)
        mame.set_reg("USP", case.regs["A7"])
        mame.set_reg("SP", case.regs["A7"])
        mame.set_reg("PC", root.ENTRY_PC)
        capture = mame.cmd(
            "capture_at_pc",
            pc=mame_seam,
            addr=0xF00000,
            len=root.MAPPED_WORK_SIZE,
            nth=1,
            exp_sp=case.regs["A7"] & 0xFFFFFF,
            maxFrames=60,
            timeout=60,
        )
        if not capture.get("registers"):
            raise RuntimeError(f"MAME missed ${mame_seam:06X}: {capture!r}")
        regs = capture["registers"]
        return {
            "registers": {
                **{
                    name: regs[name] & 0xFFFFFFFF
                    for name in base.REG_NAMES[:-1]
                },
                "A7": regs["SP"] & 0xFFFFFFFF,
            },
            "sr": regs["SR"] & 0xFFFF,
            "work": bytes.fromhex(capture["hex"]),
        }
    finally:
        mame.stop()


def nexen_capture(
    case: root.LiveCase,
    rom: Path,
    nexen: Path,
    nat: Path,
    port: int,
    stderr_log: Path,
    native_seam: int,
) -> dict:
    with base.McpSession(
        rom=str(rom),
        mesen=str(nexen),
        cwd=ROOT,
        port=port,
        boot_wait=8.0,
        socket_timeout=180.0,
        stderr_log=stderr_log,
    ) as m:
        setup_nexen(m, nat, case)
        # Nexen execution-hook notifications are asynchronous to the source
        # CPU and can otherwise observe a later pass through a hot seam.  A
        # validation-only BRA $-2 in the session's PRG-ROM copy makes the
        # first arrival a stable pre-instruction boundary.  Restore the
        # original two bytes before ending the session.
        native_seam_file = 0x2C0000 + (native_seam & 0x7FFF)
        original = bytes(
            m.read_memory("snesPrgRom", native_seam_file, 2)
        )
        if original == bytes.fromhex("80fe"):
            raise RuntimeError(
                f"native seam at file ${native_seam_file:06X} is already "
                "the validation spin"
            )
        m.write_memory("snesPrgRom", native_seam_file, "80fe")
        hook = m.add_exec_hook(native_seam, cpu_type="Sa1")
        m.drain_notifications(timeout=0.05)
        try:
            base.set_sa1_pc(m, root.ENTRY_NATIVE)
            hit = m.run_until(max_frames=60, hook_handle=hook)
            m.pause()
        finally:
            m.remove_hook(hook)
        if (hit or {}).get("reason") != "hookFired":
            m.write_memory("snesPrgRom", native_seam_file, original.hex())
            raise RuntimeError(f"Nexen missed ${native_seam:06X}: {hit!r}")
        result = {
            "registers": common.captured_regs(m),
            "sr": common.captured_sr(m),
            "work": bytes(
                m.read_memory(
                    base.SNES_SPACE,
                    0x400000,
                    root.MAPPED_WORK_SIZE,
                )
            ),
            "direct_page": bytes(
                m.read_memory(base.DP_SPACE, 0x0000, 0x0200)
            ),
            "sa1": m.get_cpu_state("Sa1"),
        }
        m.write_memory("snesPrgRom", native_seam_file, original.hex())
        return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture-dir", type=Path, default=DEFAULT_FIXTURES)
    parser.add_argument("--rom", type=Path, default=root.DEFAULT_ROM)
    parser.add_argument("--nexen", type=Path, default=base.DEFAULT_NEXEN)
    parser.add_argument("--nat", type=Path, default=base.DEFAULT_NAT)
    parser.add_argument("--port", type=int, default=7642)
    parser.add_argument(
        "--mame-pc",
        type=lambda value: int(value, 0),
        default=DEFAULT_MAME_SEAM,
    )
    parser.add_argument(
        "--native-pc",
        type=lambda value: int(value, 0),
        default=DEFAULT_NATIVE_SEAM,
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    for path in (args.fixture_dir, args.rom, args.nexen, args.nat):
        if not path.exists():
            parser.error(f"missing input: {path}")
    if args.output.exists():
        parser.error(f"output exists: {args.output}")

    case = root.load_fixture_cases(args.fixture_dir, 1)[0]
    arcade = mame_capture(case, args.mame_pc)
    console = nexen_capture(
        case,
        args.rom,
        args.nexen,
        args.nat,
        args.port,
        args.output.with_suffix(".nexen.stderr.log"),
        args.native_pc,
    )
    work_offsets = [
        offset
        for offset, (left, right) in enumerate(
            zip(arcade["work"], console["work"])
        )
        if left != right
    ]
    reg_mismatches = {
        name: {
            "mame": arcade["registers"][name],
            "nexen": console["registers"][name],
        }
        for name in base.REG_NAMES
        if arcade["registers"][name] != console["registers"][name]
    }
    payload = {
        "scope": (
            "exact retained function-entry fixture stopped before the original "
            "$01E94A script join; diagnostic seam evidence, not fps"
        ),
        "fixture": case.name,
        "rom": str(args.rom.resolve()),
        "rom_sha256": sha256(args.rom),
        "mame": "/snap/bin/mame 0.287",
        "nexen": str(args.nexen.resolve()),
        "nexen_sha256": sha256(args.nexen),
        "mame_pc": f"{args.mame_pc:06X}",
        "nexen_pc": f"{args.native_pc:06X}",
        "mame_sr": arcade["sr"],
        "nexen_sr": console["sr"],
        "register_mismatches": reg_mismatches,
        "work_mismatch_count": len(work_offsets),
        "work_mismatches": [
            {
                "address": f"F0{offset:04X}",
                "mame": arcade["work"][offset],
                "nexen": console["work"][offset],
            }
            for offset in work_offsets[:64]
        ],
        "mame_registers": arcade["registers"],
        "nexen_registers": console["registers"],
        "nexen_direct_page_0080_009f": console["direct_page"][
            0x80:0xA0
        ].hex(),
        "nexen_sa1": console["sa1"],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
