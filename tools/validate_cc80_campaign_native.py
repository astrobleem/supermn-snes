#!/usr/bin/env python3
"""Three-way $00CC80 differential from the tick-6619 campaign failure.

The input state is frozen before the first instruction of the bank-$97 native
body, at a real ``bsr.w $00CC80`` from ``$011A16``.  The native dispatcher has
not yet materialized the MC68000 return.  Convert that state into the canonical
post-BSR function-entry form, then execute the identical registers, CCR/X,
stack, and work RAM through:

* MAME 0.287 original MC68000 code;
* the SNES interpreter with native dispatch disabled;
* the production bank-$97 native body.

This is a bounded function differential from an authenticated fresh-campaign
checkpoint.  It is not itself fresh-boot, whole-tick, or performance evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ROM = ROOT / "build" / "interp.sfc"
DEFAULT_STATE = (
    ROOT
    / "build/playtest-investigation-20260725"
    / "campaign-halt-cc80-entry-a08508d-tick6619-v1"
    / "post-trace.mss"
)
ENTRY_PC = 0x00CC80
ENTRY_NATIVE = 0x97D400
RETURN_PC = 0x011A1A
MAPPED_WORK_SIZE = 0x4000
FULL_WORK_SIZE = 0x10000

sys.path.insert(0, "/home/chad/Mesen2/python")
sys.path.insert(0, str(ROOT / "tools"))
import mesen_mcp.session as _session  # noqa: E402

_session.validate_mesen_build = lambda *_args, **_kwargs: None
from mesen_mcp import McpSession  # noqa: E402

import validate_cc80_native as cc80  # noqa: E402


base = cc80.base
shared = cc80.shared


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--nexen", type=Path, default=base.DEFAULT_NEXEN)
    parser.add_argument("--nat", type=Path, default=base.DEFAULT_NAT)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--port", type=int, default=9510)
    args = parser.parse_args()
    for label, path in (
        ("ROM", args.rom),
        ("entry state", args.state),
        ("Nexen", args.nexen),
        ("native launch state", args.nat),
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


def read_u16(m: McpSession, address: int) -> int:
    return int(m.read_u16(address, base.DP_SPACE))


def captured_ccr(m: McpSession) -> int:
    return (
        (1 if read_u16(m, 0x6E) else 0)
        | ((1 if read_u16(m, 0x72) else 0) << 1)
        | ((1 if read_u16(m, 0x60) else 0) << 2)
        | ((1 if read_u16(m, 0x70) else 0) << 3)
        | ((1 if read_u16(m, 0xA2) else 0) << 4)
    )


def extract_case(args: argparse.Namespace, output: Path) -> tuple[Any, dict]:
    with McpSession(
        rom=args.rom.resolve(),
        mesen=args.nexen.resolve(),
        cwd=ROOT,
        port=args.port,
        boot_wait=6.0,
        socket_timeout=180.0,
        stderr_log=output.parent / "fixture-extract.nexen.stderr.log",
    ) as m:
        m.pause()
        load_response = m.load_state(args.state.resolve())
        m.pause()
        raw_regs = bytes(m.read_memory(base.DP_SPACE, 0x00, 0x40))
        regs = {
            name: int.from_bytes(
                raw_regs[index * 4 : index * 4 + 4], "little"
            )
            for index, name in enumerate(base.REG_NAMES)
        }
        ccr = captured_ccr(m)
        sr = 0x2000 | ((read_u16(m, 0x7C) & 7) << 8) | ccr
        logical_pc = read_u16(m, 0x40) | (
            (read_u16(m, 0x42) & 0xFF) << 16
        )
        halt = read_u16(m, 0x4E)
        work = b"".join(
            bytes(
                m.read_memory(
                    base.SNES_SPACE,
                    0x400000 + offset,
                    0x4000,
                )
            )
            for offset in range(0, FULL_WORK_SIZE, 0x4000)
        )
        sa1 = m.get_cpu_state("Sa1")

    if halt:
        raise RuntimeError(f"entry state is already halted: ${halt:04X}")
    if logical_pc != RETURN_PC:
        raise RuntimeError(
            f"native entry return PC is ${logical_pc:06X}, "
            f"expected ${RETURN_PC:06X}"
        )
    native_pre_push_sp = regs["A7"] & 0xFFFFFF
    if (native_pre_push_sp >> 16) != 0xF0:
        raise RuntimeError(
            f"unsupported native pre-push SP ${native_pre_push_sp:06X}"
        )
    entry_sp = (native_pre_push_sp - 4) & 0xFFFFFF
    fixture = bytearray(work)
    fixture[entry_sp & 0xFFFF : (entry_sp & 0xFFFF) + 4] = (
        RETURN_PC.to_bytes(4, "big")
    )
    regs["A7"] = entry_sp
    output.write_bytes(fixture)
    case = shared.Case(
        "organic-carry-tick-06619-return-011A1A",
        regs,
        sr,
        bytes(fixture),
    )
    metadata = {
        "load_response": load_response,
        "logical_return_pc": f"{logical_pc:06X}",
        "native_pre_push_sp": f"{native_pre_push_sp:06X}",
        "canonical_post_bsr_sp": f"{entry_sp:06X}",
        "sr": f"{sr:04X}",
        "ccr_xnzvc": ccr,
        "registers": {
            name: f"{value & 0xFFFFFFFF:08X}"
            for name, value in regs.items()
        },
        "sa1_cpu": sa1,
        "fixture_work": str(output),
        "fixture_work_sha256": sha256(output),
    }
    return case, metadata


def result_dict(result: base.Result) -> dict[str, Any]:
    return {
        "registers": {
            name: f"{result.regs[name] & 0xFFFFFFFF:08X}"
            for name in base.REG_NAMES
        },
        "sr": f"{result.sr & 0xFFFF:04X}",
        "ccr_xnzvc": result.sr & base.CCR_MASK,
        "interrupt_mask": (result.sr >> 8) & 7,
        "mapped_work_sha256": hashlib.sha256(result.work).hexdigest(),
        "cycles": result.cycles,
    }


def main() -> int:
    args = parse_args()
    args.rom = args.rom.resolve()
    args.state = args.state.resolve()
    args.nexen = args.nexen.resolve()
    args.nat = args.nat.resolve()
    args.output = args.output.resolve()
    args.output.mkdir(parents=True)
    os.environ["DOTNET_ROOT"] = "/home/chad/.dotnet10"

    # Select this organic caller's real return seam in the shared audited
    # launch machinery.
    shared.ENTRY_PC = ENTRY_PC
    shared.ENTRY_NATIVE = ENTRY_NATIVE
    shared.RETURN_PC = RETURN_PC
    case, fixture = extract_case(args, args.output / "entry.work.bin")

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
        oracle = shared.mame_result(mame, case)
    finally:
        mame.stop()

    observations: dict[str, base.Result] = {}
    comparisons: list[dict[str, Any]] = []
    with base.McpSession(
        rom=str(args.rom),
        mesen=str(args.nexen),
        cwd=ROOT,
        port=args.port + 1,
        boot_wait=8.0,
        socket_timeout=180.0,
        stderr_log=args.output / "differential.nexen.stderr.log",
    ) as nexen:
        for native in (False, True):
            label = "native-on" if native else "native-off"
            observed = shared.nexen_result(
                nexen,
                args.nat,
                case,
                native=native,
            )
            observations[label] = observed
            event = shared.compare(case, oracle, observed, label)
            comparisons.append(event)
            print(json.dumps(event, sort_keys=True), flush=True)

    result = {
        "scope": (
            "authenticated campaign tick-6619 $00CC80 function-entry "
            "differential; MAME original, SNES interpreter/native-off, and "
            "bank-$97 native-on; all D/A registers, CCR/X/mask, live return "
            "stack, and mapped 16 KiB work RAM; bounded checkpoint evidence"
        ),
        "time": time.time(),
        "rom": str(args.rom),
        "rom_sha256": sha256(args.rom),
        "entry_state": str(args.state),
        "entry_state_sha256": sha256(args.state),
        "nexen": str(args.nexen),
        "nexen_sha256": sha256(args.nexen),
        "mame": "/snap/bin/mame",
        "mame_version": "0.287",
        "entry_pc": f"{ENTRY_PC:06X}",
        "native_entry": f"{ENTRY_NATIVE:06X}",
        "return_pc": f"{RETURN_PC:06X}",
        "fixture": fixture,
        "results": {
            "mame-original": result_dict(oracle),
            **{
                label: result_dict(observed)
                for label, observed in observations.items()
            },
        },
        "comparisons": comparisons,
        "result": (
            "green"
            if all(event["result"] == "green" for event in comparisons)
            else "red"
        ),
    }
    output = args.output / "result.json"
    output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "output": str(output),
                "result": result["result"],
                "comparisons": [
                    {
                        "configuration": event["configuration"],
                        "result": event["result"],
                        "register_mismatches": event[
                            "register_mismatches"
                        ],
                        "mame_ccr_xnzvc": event["mame_ccr_xnzvc"],
                        "snes_ccr_xnzvc": event["snes_ccr_xnzvc"],
                        "work_mismatch_count": event[
                            "work_mismatch_count"
                        ],
                    }
                    for event in comparisons
                ],
            },
            sort_keys=True,
        ),
        flush=True,
    )
    return 0 if result["result"] == "green" else 1


if __name__ == "__main__":
    raise SystemExit(main())
