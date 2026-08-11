#!/usr/bin/env python3
"""Three-way regression for the $00CC80 player-motion table update.

The retained organic fixture is the first native-on/MAME divergence in the
tick-2947 update.  The arcade enters $00CC80 with direction index seven and
the low-speed table selected; its second table word is +3 and is accumulated
into the transient player/camera delta at $F012A2.

Run the identical entry register, CCR/X, stack, and work-RAM state through
MAME, the SNES interpreter, and the bank-$97 native body.  This is a bounded
function differential, not fresh-boot or performance evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

import validate_d18a_native as shared


base = shared.base
ROOT = shared.ROOT
DEFAULT_ROM = ROOT / "build/interp.sfc"
DEFAULT_CAPTURE = (
    ROOT
    / "build/playtest-investigation-20260725"
    / "failure-3043-mame-cc80-entry-2947-v1"
    / "mame-original"
    / "capture.jsonl"
)
DEFAULT_WORK = DEFAULT_CAPTURE.parent / (
    "mame-generic-pc-tick-02947-hit-001-address-00CC80-pc-00CC80.work.bin"
)
DEFAULT_SOURCE = ROOT / "src/escbank3.pasm"
ENTRY_PC = 0x00CC80
ENTRY_NATIVE = 0x97D400
RETURN_PC = 0x011784
FIXTURE_TICK = 2947
FULL_WORK_SIZE = 0x10000
BTST_EXIT_CCR = """\
    and #$0004
    php
    php
    sep #$20
    pla
    rep #$30
    and #$0002
    sta $60
    plp
    beq Lfcc80_1
"""
FINAL_ADD_EXIT_CCR = """\
    adc $1C
    pha
    php
    sep #$20
    pla
    rep #$30
    and #$00FF
    sta $50
    and #$0002
    sta $60
    lda $50
    and #$0080
    sta $70
    lda $50
    and #$0040
    sta $72
    lda $50
    and #$0001
    sta $6E
    sta $A2
    pla
    xba
    sta $400000,x
"""
STALE_BTST_EXIT = """\
    and #$0004
    beq Lfcc80_1
    php
"""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_entry(capture: Path, work_path: Path) -> shared.Case:
    rows = [
        json.loads(line)
        for line in capture.read_text(encoding="utf-8").splitlines()
    ]
    matches = [
        row
        for row in rows
        if row.get("event") == "generic_pc"
        and int(row.get("tick", -1)) == FIXTURE_TICK
        and int(row.get("PC", -1)) == ENTRY_PC
    ]
    if not matches:
        raise RuntimeError("retained MAME capture has no $00CC80 entry")
    row = matches[0]
    work = work_path.read_bytes()
    if len(work) != FULL_WORK_SIZE:
        raise RuntimeError(f"{work_path}: expected {FULL_WORK_SIZE} bytes")
    regs = {
        name: int(row["SP" if name == "A7" and "SP" in row else name])
        for name in base.REG_NAMES
    }
    entry_sp = regs["A7"] & 0xFFFFFF
    if int.from_bytes(
        work[entry_sp & 0xFFFF : (entry_sp & 0xFFFF) + 4],
        "big",
    ) != RETURN_PC:
        raise RuntimeError("retained $00CC80 BSR return residue changed")
    return shared.Case("organic-tick-02947-index7-low-speed", regs, int(row["SR"]), work)


def derived_cases(seed: shared.Case) -> list[shared.Case]:
    """Exercise all three speed-table selector branches with index seven."""

    a6 = seed.regs["A6"] & 0xFFFFFF
    if (a6 >> 16) != 0xF0:
        raise RuntimeError("retained $00CC80 A6 is outside work RAM")
    threshold = (a6 - 0x70) & 0xFFFF
    cases = [seed]
    for name, value in (
        ("index7-medium-speed", 0x0015),
        ("index7-high-speed", 0x001F),
    ):
        work = bytearray(seed.work)
        work[threshold : threshold + 2] = value.to_bytes(2, "big")
        cases.append(shared.Case(name, dict(seed.regs), seed.sr, bytes(work)))
    return cases


def codegen_regression(source_path: Path) -> dict:
    command = [
        sys.executable,
        str(ROOT / "tools/transpile.py"),
        "00CC80",
        "--bank1",
        "--exitccr",
    ]
    generated = subprocess.run(
        command,
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    source = source_path.read_text(encoding="utf-8")
    start = source.index("entry_cc80:")
    end = source.index("; --- entry_caf6", start)
    deployed = source[start:end]
    counts = {
        "generated_btst_exit_ccr": generated.stdout.count(BTST_EXIT_CCR),
        "generated_final_add_exit_ccr": generated.stdout.count(
            FINAL_ADD_EXIT_CCR
        ),
        "deployed_btst_exit_ccr": deployed.count(BTST_EXIT_CCR),
        "deployed_final_add_exit_ccr": deployed.count(FINAL_ADD_EXIT_CCR),
        "deployed_stale_btst_exit": deployed.count(STALE_BTST_EXIT),
    }
    green = counts == {
        "generated_btst_exit_ccr": 1,
        "generated_final_add_exit_ccr": 1,
        "deployed_btst_exit_ccr": 1,
        "deployed_final_add_exit_ccr": 1,
        "deployed_stale_btst_exit": 0,
    }
    return {
        "event": "codegen",
        "command": command,
        "counts": counts,
        "result": "green" if green else "red",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    parser.add_argument("--capture", type=Path, default=DEFAULT_CAPTURE)
    parser.add_argument("--work", type=Path, default=DEFAULT_WORK)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--nexen", type=Path, default=base.DEFAULT_NEXEN)
    parser.add_argument("--nat", type=Path, default=base.DEFAULT_NAT)
    parser.add_argument("--port", type=int, default=9366)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    for path in (
        args.rom,
        args.capture,
        args.work,
        args.source,
        args.nexen,
        args.nat,
    ):
        if not path.is_file():
            parser.error(f"missing required input: {path}")
    if args.output.exists():
        parser.error(f"output already exists: {args.output}")
    args.output.parent.mkdir(parents=True, exist_ok=True)

    # Reuse the audited MAME/interpreter/native launch machinery while
    # selecting this function's exact entry and real BSR return seam.
    shared.ENTRY_PC = ENTRY_PC
    shared.ENTRY_NATIVE = ENTRY_NATIVE
    shared.RETURN_PC = RETURN_PC

    cases = derived_cases(load_entry(args.capture, args.work))
    events: list[dict] = [
        {
            "event": "provenance",
            "scope": (
                "retained organic-entry $00CC80 three-way function "
                "differential; all D/A registers, CCR/X/mask, live stack, "
                "and mapped 16 KiB work RAM; not fresh-boot or fps evidence"
            ),
            "rom": str(args.rom.resolve()),
            "rom_sha256": sha256(args.rom),
            "capture": str(args.capture.resolve()),
            "capture_sha256": sha256(args.capture),
            "fixture_work": str(args.work.resolve()),
            "fixture_work_sha256": sha256(args.work),
            "nexen": str(args.nexen.resolve()),
            "nexen_sha256": sha256(args.nexen),
            "nat": str(args.nat.resolve()),
            "nat_sha256": sha256(args.nat),
            "entry_pc": f"{ENTRY_PC:06X}",
            "entry_native": f"{ENTRY_NATIVE:06X}",
            "return_pc": f"{RETURN_PC:06X}",
            "cases": [case.name for case in cases],
            "time": time.time(),
        }
    ]
    codegen = codegen_regression(args.source)
    events.append(codegen)
    print(json.dumps(codegen, sort_keys=True), flush=True)

    oracle: dict[str, base.Result] = {}
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
        for case in cases:
            oracle[case.name] = shared.mame_result(mame, case)
    finally:
        mame.stop()

    with base.McpSession(
        rom=str(args.rom.resolve()),
        mesen=str(args.nexen.resolve()),
        cwd=ROOT,
        port=args.port,
        boot_wait=8.0,
        socket_timeout=180.0,
        stderr_log=args.output.parent / "cc80-differential.nexen.stderr.log",
    ) as nexen:
        for case in cases:
            for native in (False, True):
                result = shared.nexen_result(
                    nexen,
                    args.nat,
                    case,
                    native=native,
                )
                event = shared.compare(
                    case,
                    oracle[case.name],
                    result,
                    "native-on" if native else "native-off",
                )
                events.append(event)
                print(json.dumps(event, sort_keys=True), flush=True)

    case_events = [event for event in events if event.get("event") == "case"]
    green = sum(event["result"] == "green" for event in case_events)
    summary_green = (
        green == len(case_events) and codegen["result"] == "green"
    )
    summary = {
        "event": "summary",
        "green": green,
        "red": len(case_events) - green,
        "total": len(case_events),
        "codegen_result": codegen["result"],
        "result": "green" if summary_green else "red",
        "time": time.time(),
    }
    events.append(summary)
    args.output.write_text(
        "".join(json.dumps(event, sort_keys=True) + "\n" for event in events),
        encoding="utf-8",
    )
    print(json.dumps(summary, sort_keys=True), flush=True)
    return 0 if summary["result"] == "green" else 1


if __name__ == "__main__":
    raise SystemExit(main())
