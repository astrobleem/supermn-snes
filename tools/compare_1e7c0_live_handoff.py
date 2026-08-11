#!/usr/bin/env python3
"""Compare the live $01E7C0 native/interpreted handoff at $01EB8E.

The retained input state is paused at the production bank-$98 native entry
from the deterministic tick-6619 campaign failure.  The native arm stops
immediately before the generated ``jml inext`` that publishes MC68000 PC
$01EB8E, then attempts to reach the generic DIVS dispatcher.  The comparison
arm redirects only this root through its existing interpreter fallback and
stops at that same logical DIVS dispatch.

This deliberately preserves the complete live SA-1 IRAM image.  It is an
integration-state differential, complementary to validate_1e7c0_native.py's
clean injected semantic fixture.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ROM = ROOT / "build/interp.sfc"
DEFAULT_STATE = (
    ROOT
    / "build/playtest-investigation-20260725"
    / "campaign-halt-1e7c0-entry-a08508d-tick6619-v1"
    / "post-trace.mss"
)
DEFAULT_NEXEN = Path(
    "/mnt/sdc1/Nexen-r5-20260712/"
    "bin/linux-x64/Release/linux-x64/publish/Nexen"
)
ENTRY_NATIVE = 0x98AE00
ENTRY_ROM_OFFSET = 0x2C2E00
ENTRY_ORIGINAL = bytes.fromhex("c230a534")
ENTRY_FALLBACK_JML = bytes.fromhex("5cb8ae98")
NATIVE_HANDOFF_JML = 0x98C4A7
NATIVE_HANDOFF_ROM_OFFSET = 0x2C44A7
NATIVE_HANDOFF_BYTES = bytes.fromhex("5c28d100")
NATIVE_HANDOFF_SEAMS = (
    (0x98C49D, "pre-lda-pc-low"),
    (0x98C4A0, "pre-sta-pc-low"),
    (0x98C4A2, "pre-lda-pc-bank"),
    (0x98C4A5, "pre-sta-pc-bank"),
    (NATIVE_HANDOFF_JML, "pre-jml-inext"),
)
OP_DIVS = 0x00CC43
OP_DIVS_ROM_OFFSET = OP_DIVS - 0x8000
LOGICAL_DIVS_PC = 0x01EB8E
HALT_IRAM = 0x004E
IRAM_SIZE = 0x0800
WORK_BASE = 0x400000
WORK_SIZE = 0x10000

sys.path.insert(0, "/home/chad/Mesen2/python")
sys.path.insert(0, str(ROOT / "tools"))
import mesen_mcp.session as _session  # noqa: E402

_session.validate_mesen_build = lambda *_args, **_kwargs: None
from mesen_mcp import McpSession  # noqa: E402

import replay_mame_controller_campaign as campaign  # noqa: E402
import validate_d96_hle as native_base  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--nexen", type=Path, default=DEFAULT_NEXEN)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--port", type=int, default=9570)
    parser.add_argument("--buttons", type=lambda value: int(value, 0), default=0x80)
    args = parser.parse_args()
    for label, path in (
        ("ROM", args.rom),
        ("state", args.state),
        ("Nexen", args.nexen),
    ):
        if not path.is_file():
            parser.error(f"missing {label}: {path}")
    if args.output.exists():
        parser.error(f"output already exists: {args.output}")
    return args


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def le16(raw: bytes | bytearray | list[int]) -> int:
    return int.from_bytes(bytes(raw), "little")


def le32(raw: bytes | bytearray | list[int]) -> int:
    return int.from_bytes(bytes(raw), "little")


def read_work(m: McpSession) -> bytes:
    return b"".join(
        bytes(m.read_memory("snesMemory", WORK_BASE + offset, 0x4000))
        for offset in range(0, WORK_SIZE, 0x4000)
    )


def snapshot(m: McpSession, label: str) -> tuple[dict[str, Any], bytes, bytes]:
    iram = bytes(m.read_memory("Sa1Memory", 0, IRAM_SIZE))
    work = read_work(m)
    cpu = m.get_cpu_state("Sa1")
    logical_pc = le32(iram[0x40:0x44]) & 0xFFFFFF
    return (
        {
            "label": label,
            "video_frame": int(m.get_state().get("frameCount", 0)),
            "sa1_cpu": cpu,
            "pc68k": f"{logical_pc:06X}",
            "opcode68k": f"{le16(iram[0x44:0x46]):04X}",
            "halt": le16(iram[HALT_IRAM : HALT_IRAM + 2]),
            "tick": le16(iram[0x760:0x762]),
            "irq_pending": le16(iram[0xAA:0xAC]),
            "irq_countdown": le16(iram[0xAC:0xAE]),
            "m68k": campaign.register_snapshot(m),
            "player": campaign.player_snapshot(m),
            "task_context_hex": work[4:68].hex(),
            "task_mask": int.from_bytes(work[2:4], "big"),
            "iram_sha256": hashlib.sha256(iram).hexdigest(),
            "work_sha256": hashlib.sha256(work).hexdigest(),
        },
        iram,
        work,
    )


def differences(left: bytes, right: bytes) -> list[dict[str, Any]]:
    return [
        {"offset": f"{offset:04X}", "native": a, "interpreted": b}
        for offset, (a, b) in enumerate(zip(left, right))
        if a != b
    ]


def write_snapshot(
    output: Path,
    name: str,
    result: tuple[dict[str, Any], bytes, bytes],
) -> dict[str, Any]:
    metadata, iram, work = result
    (output / f"{name}.iram.bin").write_bytes(iram)
    (output / f"{name}.work.bin").write_bytes(work)
    return metadata


def validate_rom_seams(m: McpSession) -> None:
    entry = bytes(m.read_memory("snesPrgRom", ENTRY_ROM_OFFSET, 4))
    if entry != ENTRY_ORIGINAL:
        raise RuntimeError(
            f"entry_1e7c0 moved: {entry.hex()} != {ENTRY_ORIGINAL.hex()}"
        )
    handoff = bytes(
        m.read_memory("snesPrgRom", NATIVE_HANDOFF_ROM_OFFSET, 4)
    )
    if handoff != NATIVE_HANDOFF_BYTES:
        raise RuntimeError(
            "native $01EB8E handoff moved: "
            f"{handoff.hex()} != {NATIVE_HANDOFF_BYTES.hex()}"
        )


def reach_matching_divs(
    m: McpSession,
    max_hits: int = 64,
    max_frames_per_hit: int = 4,
) -> tuple[dict[str, Any], list[str]]:
    original = bytes(m.read_memory("snesPrgRom", OP_DIVS_ROM_OFFSET, 2))
    m.write_memory("snesPrgRom", OP_DIVS_ROM_OFFSET, "80fe")
    hook = m.add_exec_hook(OP_DIVS, cpu_type="Sa1")
    logical_hits: list[str] = []
    try:
        m.drain_notifications(timeout=0.05)
        for _index in range(max_hits):
            response = m.run_until(
                max_frames=max_frames_per_hit,
                hook_handle=hook,
            )
            m.pause()
            if response.get("reason") != "hookFired":
                return response, logical_hits
            logical_pc = le32(
                m.read_memory("Sa1Memory", 0x0040, 4)
            ) & 0xFFFFFF
            logical_hits.append(f"{logical_pc:06X}")
            if logical_pc == LOGICAL_DIVS_PC:
                return response, logical_hits
        raise RuntimeError(
            f"exceeded {max_hits} DIVS dispatches before ${LOGICAL_DIVS_PC:06X}"
        )
    finally:
        m.remove_hook(hook)
        m.write_memory("snesPrgRom", OP_DIVS_ROM_OFFSET, original.hex())


def bank98_rom_offset(address: int) -> int:
    if (address >> 16) != 0x98 or (address & 0xFFFF) < 0x8000:
        raise ValueError(f"not a bank-$98 ROM address: ${address:06X}")
    return 0x2B8000 + (address & 0xFFFF)


def reach_stabilized_seam(
    m: McpSession,
    target: int,
    resume_pc: int,
    max_frames: int = 8,
) -> tuple[dict[str, Any], bytes]:
    """Stop coherently before *target* without executing its instruction."""

    rom_offset = bank98_rom_offset(target)
    original = bytes(m.read_memory("snesPrgRom", rom_offset, 2))
    m.write_memory("snesPrgRom", rom_offset, "80fe")
    native_base.set_sa1_pc(m, resume_pc)
    hook = m.add_exec_hook(target, cpu_type="Sa1")
    try:
        m.drain_notifications(timeout=0.05)
        response = m.run_until(max_frames=max_frames, hook_handle=hook)
        m.pause()
    finally:
        m.remove_hook(hook)
    if response.get("reason") != "hookFired":
        m.write_memory("snesPrgRom", rom_offset, original.hex())
        raise RuntimeError(
            f"did not reach stabilized seam ${target:06X}: {response!r}"
        )
    cpu = m.get_cpu_state("Sa1")
    physical_pc = (
        (int(cpu.get("k", 0)) << 16) | int(cpu.get("pc", 0))
    )
    if physical_pc != target:
        m.write_memory("snesPrgRom", rom_offset, original.hex())
        raise RuntimeError(
            f"seam ${target:06X} hook ran ahead to ${physical_pc:06X}"
        )
    return response, original


def run_native(args: argparse.Namespace, output: Path) -> dict[str, Any]:
    output.mkdir(parents=True)
    with McpSession(
        rom=args.rom,
        mesen=args.nexen,
        cwd=ROOT,
        port=args.port,
        boot_wait=6.0,
        socket_timeout=180.0,
        stderr_log=output / "emulator.stderr.log",
    ) as m:
        m.pause()
        load_response = m.load_state(args.state)
        m.pause()
        input_response = campaign.set_held_input(m, args.buttons)
        validate_rom_seams(m)
        # The retained debugger checkpoint serialized a temporary BRA -2 in
        # the SA-1 prefetch pipeline.  Reasserting the already captured entry
        # PC flushes only that diagnostic prefetch.
        instruction_seams: list[dict[str, Any]] = []
        handoff_response: dict[str, Any] = {}
        handoff: dict[str, Any] = {}
        resume_pc = ENTRY_NATIVE
        for address, name in NATIVE_HANDOFF_SEAMS:
            response, original = reach_stabilized_seam(
                m,
                address,
                resume_pc,
            )
            seam = write_snapshot(
                output, name, snapshot(m, name.replace("-", "_"))
            )
            instruction_seams.append(
                {
                    "address": f"{address:06X}",
                    "response": response,
                    "snapshot": seam,
                }
            )
            if address == NATIVE_HANDOFF_JML:
                handoff_response = response
                handoff = seam
            m.write_memory(
                "snesPrgRom",
                bank98_rom_offset(address),
                original.hex(),
            )
            resume_pc = address
        handoff_state = campaign.save_state(m, output / "pre-jml-inext.mss")
        native_base.set_sa1_pc(m, NATIVE_HANDOFF_JML)
        divs_response, logical_hits = reach_matching_divs(m)
        m.pause()
        divs = write_snapshot(
            output, "pre-op-divs", snapshot(m, "pre_op_divs")
        )
        divs_state = campaign.save_state(m, output / "pre-op-divs.mss")
        trace = m.trace_log(count=1000, cpu_type="Sa1")
    return {
        "load_response": load_response,
        "input_response": input_response,
        "handoff_response": handoff_response,
        "instruction_seams": instruction_seams,
        "handoff": handoff,
        "handoff_state": handoff_state,
        "divs_response": divs_response,
        "divs_logical_hits": logical_hits,
        "reached_matching_divs": (
            divs_response.get("reason") == "hookFired"
            and logical_hits
            and logical_hits[-1] == f"{LOGICAL_DIVS_PC:06X}"
        ),
        "divs": divs,
        "divs_state": divs_state,
        "trace": trace,
    }


def run_interpreted(args: argparse.Namespace, output: Path) -> dict[str, Any]:
    output.mkdir(parents=True)
    with McpSession(
        rom=args.rom,
        mesen=args.nexen,
        cwd=ROOT,
        port=args.port + 1,
        boot_wait=6.0,
        socket_timeout=180.0,
        stderr_log=output / "emulator.stderr.log",
    ) as m:
        m.pause()
        load_response = m.load_state(args.state)
        m.pause()
        input_response = campaign.set_held_input(m, args.buttons)
        validate_rom_seams(m)
        m.write_memory(
            "snesPrgRom",
            ENTRY_ROM_OFFSET,
            ENTRY_FALLBACK_JML.hex(),
        )
        # Prevent the normal fetch-time translation table from re-entering
        # native subsegments while deriving the fully interpreted seam.
        xlat_before = bytes(m.read_memory("Sa1Memory", 0x071A, 2))
        m.write_memory("Sa1Memory", 0x071A, "0000")
        native_base.set_sa1_pc(m, ENTRY_NATIVE)
        divs_response, logical_hits = reach_matching_divs(
            m,
            max_hits=256,
            max_frames_per_hit=120,
        )
        m.pause()
        divs = write_snapshot(
            output, "pre-op-divs", snapshot(m, "pre_op_divs")
        )
        divs_state = campaign.save_state(m, output / "pre-op-divs.mss")
        trace = m.trace_log(count=1000, cpu_type="Sa1")
        m.write_memory(
            "snesPrgRom",
            ENTRY_ROM_OFFSET,
            ENTRY_ORIGINAL.hex(),
        )
        m.write_memory("Sa1Memory", 0x071A, xlat_before.hex())
    reached = (
        divs_response.get("reason") == "hookFired"
        and logical_hits
        and logical_hits[-1] == f"{LOGICAL_DIVS_PC:06X}"
    )
    if not reached:
        raise RuntimeError(
            "interpreted root did not reach matching DIVS: "
            f"{divs_response!r}, logical hits={logical_hits!r}"
        )
    return {
        "load_response": load_response,
        "input_response": input_response,
        "temporary_entry_patch": {
            "entry": f"{ENTRY_NATIVE:06X}",
            "before": ENTRY_ORIGINAL.hex(),
            "temporary": ENTRY_FALLBACK_JML.hex(),
        },
        "temporary_xlat_gate": {
            "address": "071A",
            "before": xlat_before.hex(),
            "temporary": "0000",
        },
        "divs_response": divs_response,
        "divs_logical_hits": logical_hits,
        "reached_matching_divs": reached,
        "divs": divs,
        "divs_state": divs_state,
        "trace": trace,
    }


def main() -> int:
    args = parse_args()
    args.rom = args.rom.resolve()
    args.state = args.state.resolve()
    args.nexen = args.nexen.resolve()
    args.output = args.output.resolve()
    args.output.mkdir(parents=True)
    os.environ["DOTNET_ROOT"] = "/home/chad/.dotnet10"

    native = run_native(args, args.output / "native-production")
    interpreted = run_interpreted(args, args.output / "root-interpreted")

    native_handoff_iram = (
        args.output / "native-production/pre-jml-inext.iram.bin"
    ).read_bytes()
    native_handoff_work = (
        args.output / "native-production/pre-jml-inext.work.bin"
    ).read_bytes()
    native_divs_iram = (
        args.output / "native-production/pre-op-divs.iram.bin"
    ).read_bytes()
    native_divs_work = (
        args.output / "native-production/pre-op-divs.work.bin"
    ).read_bytes()
    interpreted_divs_iram = (
        args.output / "root-interpreted/pre-op-divs.iram.bin"
    ).read_bytes()
    interpreted_divs_work = (
        args.output / "root-interpreted/pre-op-divs.work.bin"
    ).read_bytes()

    handoff_vs_interpreted_iram = differences(
        native_handoff_iram, interpreted_divs_iram
    )
    handoff_vs_interpreted_work = differences(
        native_handoff_work, interpreted_divs_work
    )
    native_vs_interpreted_iram = differences(
        native_divs_iram, interpreted_divs_iram
    )
    native_vs_interpreted_work = differences(
        native_divs_work, interpreted_divs_work
    )
    summary = {
        "scope": (
            "exact organic tick-6619 live state; production native pre-JML "
            "handoff and pre-op_divs versus only $01E7C0 interpreted at the "
            "same logical $01EB8E DIVS; complete IRAM/work/register/stack "
            "capture; checkpoint integration evidence, not fresh boot"
        ),
        "rom": str(args.rom),
        "rom_sha256": sha256(args.rom),
        "state": str(args.state),
        "state_sha256": sha256(args.state),
        "nexen": str(args.nexen),
        "nexen_sha256": sha256(args.nexen),
        "native": native,
        "interpreted": interpreted,
        "native_handoff_vs_interpreted_divs": {
            "m68k_equal": (
                native["handoff"]["m68k"] == interpreted["divs"]["m68k"]
            ),
            "work_difference_count": len(handoff_vs_interpreted_work),
            "work_differences_first": handoff_vs_interpreted_work[:256],
            "iram_difference_count": len(handoff_vs_interpreted_iram),
            "iram_differences": handoff_vs_interpreted_iram,
        },
        "native_divs_vs_interpreted_divs": {
            "m68k_equal": (
                native["divs"]["m68k"] == interpreted["divs"]["m68k"]
            ),
            "work_difference_count": len(native_vs_interpreted_work),
            "work_differences_first": native_vs_interpreted_work[:256],
            "iram_difference_count": len(native_vs_interpreted_iram),
            "iram_differences": native_vs_interpreted_iram,
        },
    }
    output = args.output / "summary.json"
    output.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "summary": str(output),
                "native_reached_divs": native["reached_matching_divs"],
                "native_handoff_pc": native["handoff"]["pc68k"],
                "native_divs_pc": native["divs"]["pc68k"],
                "interpreted_divs_pc": interpreted["divs"]["pc68k"],
                "handoff_m68k_equal": summary[
                    "native_handoff_vs_interpreted_divs"
                ]["m68k_equal"],
                "handoff_work_differences": len(
                    handoff_vs_interpreted_work
                ),
                "native_divs_m68k_equal": summary[
                    "native_divs_vs_interpreted_divs"
                ]["m68k_equal"],
                "native_divs_work_differences": len(
                    native_vs_interpreted_work
                ),
            },
            sort_keys=True,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
