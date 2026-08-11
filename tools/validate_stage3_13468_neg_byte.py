#!/usr/bin/env python3
"""Internal-seam three-way differential for $013468 ``NEG.B Dn``.

The ordinary whole-function Stage-3 validator could not expose this defect:
later ``CLR.W``/``EXT.W`` instructions overwrite both affected low words and
the final flags.  This harness stops immediately after $0134E0 or $0134EA in
all three configurations:

* MAME 0.287 at the corresponding original 68000 pre-instruction seam;
* Nexen with both native gates disabled at the same virtual-PC seam; and
* Nexen with both gates enabled at the generated bank-$9F label.

It compares every D/A register, effective CCR including X, the exact stack and
all mapped work RAM.  Every case retains a prepared native-on save state before
the handler executes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
import subprocess
import sys
import time
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import capstone

import validate_1f2e4_native as live
import validate_render_helpers as base
import validate_stage3_hot_handlers as hot


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FIXTURES = (
    ROOT
    / "build/playtest-investigation-20260725/"
    "stage3-13468-neg-edge-fixtures-v1"
)
DEFAULT_ROM = ROOT / "build/interp.sfc"
DEFAULT_SOURCE = ROOT / "src/escbank9.pasm"
DEFAULT_PANSY = ROOT / "src/escbank9.pansy"
TARGET = 0x013468
MAPPED_WORK_SIZE = 0x4000
FULL_WORK_SIZE = 0x10000
CCR_MASK = 0x1F

SEAMS = {
    "first": {
        "original_pc": 0x0134E2,
        "native_label": "L13468_134e2",
        "neg_pc": 0x0134E0,
        "register": "D0",
        "operand": "$00",
    },
    "second": {
        "original_pc": 0x0134EC,
        "native_label": "L13468_134ec",
        "neg_pc": 0x0134EA,
        "register": "D1",
        "operand": "$04",
    },
}

TRANSPILE_COMMAND = [
    sys.executable,
    str(ROOT / "tools/transpile.py"),
    "013468",
    "--bank7",
    "--table",
    "--exitccr",
    "--xflag",
    "--accharge",
    "--restore-static-residue",
]


@dataclass(frozen=True)
class SeamCase:
    name: str
    fixture: hot.Fixture
    seam_name: str
    original_pc: int
    native_pc: int
    register: str


@dataclass
class SeamResult:
    regs: dict[str, int]
    ccr: int
    work: bytes
    cycles: int | None
    observed_pc: int
    stored_ccr: int | None = None
    host_ps: int | None = None
    pre_state: dict[str, Any] | None = None


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def wait_for_file(path: Path) -> None:
    for _ in range(600):
        if path.is_file() and path.stat().st_size:
            return
        time.sleep(0.05)
    raise TimeoutError(f"save state did not appear: {path}")


def pansy_symbols(path: Path) -> dict[str, int]:
    """Read the Poppy-emitted symbol section needed for native seam hooks."""

    data = path.read_bytes()
    if data[:5] != b"PANSY":
        raise RuntimeError(f"{path} has invalid Pansy magic")
    section_count = struct.unpack_from("<I", data, 24)[0]
    symbol_data: bytes | None = None
    for index in range(section_count):
        section_type, offset, compressed, uncompressed = struct.unpack_from(
            "<IIII", data, 32 + index * 16
        )
        if section_type != 2:
            continue
        raw = data[offset : offset + compressed]
        if compressed == uncompressed:
            symbol_data = raw
        else:
            try:
                symbol_data = zlib.decompress(raw, -zlib.MAX_WBITS)
            except zlib.error:
                symbol_data = raw
        break
    if symbol_data is None:
        raise RuntimeError(f"{path} has no symbol section")

    result: dict[str, int] = {}
    position = 0
    while position + 10 <= len(symbol_data):
        address = struct.unpack_from("<I", symbol_data, position)[0]
        name_length = struct.unpack_from("<H", symbol_data, position + 6)[0]
        position += 8
        name = symbol_data[
            position : position + name_length
        ].decode("utf-8")
        position += name_length
        value_length = struct.unpack_from("<H", symbol_data, position)[0]
        position += 2 + value_length
        result[name] = address
    return result


def neg_pattern(operand: str) -> str:
    return (
        "    sep #$20\n"
        "    lda #$00\n"
        "    sec\n"
        f"    sbc {operand}\n"
        f"    sta {operand}\n"
        "    rep #$20\n"
        "    php\n"
        "    lda #$0000\n"
        "    rol a\n"
        "    eor #$0001\n"
        "    sta $A2\n"
        "    plp\n"
    )


def generated_handler_block(text: str) -> str:
    if "entry_13468t:" in text:
        start = text.index("entry_13468t:")
    else:
        start = text.index("entry_13468:")
    end = (
        text.index("entry_13468t_end:", start)
        if "entry_13468t_end:" in text[start:]
        else len(text)
    )
    return text[start:end]


def validate_codegen(source: Path) -> dict[str, Any]:
    program = (ROOT / "data/superman_m68k.bin").read_bytes()
    md = capstone.Cs(
        capstone.CS_ARCH_M68K,
        capstone.CS_MODE_BIG_ENDIAN,
    )
    decoded: dict[str, dict[str, str]] = {}
    arcade_green = True
    for seam_name, spec in SEAMS.items():
        pc = int(spec["neg_pc"])
        instruction = next(md.disasm(program[pc : pc + 2], pc))
        decoded[seam_name] = {
            "pc": f"{pc:06X}",
            "mnemonic": instruction.mnemonic,
            "operands": instruction.op_str,
        }
        expected_register = str(spec["register"]).lower()
        arcade_green &= (
            instruction.mnemonic == "neg.b"
            and instruction.op_str == expected_register
        )

    generated = subprocess.run(
        TRANSPILE_COMMAND,
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    generated_block = generated_handler_block(generated.stdout)
    deployed_block = generated_handler_block(
        source.read_text(encoding="utf-8")
    )
    generated_counts = {
        name: generated_block.count(neg_pattern(str(spec["operand"])))
        for name, spec in SEAMS.items()
    }
    deployed_counts = {
        name: deployed_block.count(neg_pattern(str(spec["operand"])))
        for name, spec in SEAMS.items()
    }
    stale_fragments = {
        name: deployed_block.count(
            f"    lda {spec['operand']}\n"
            "    eor #$FFFF\n"
            "    inc a\n"
        )
        for name, spec in SEAMS.items()
    }
    generated_green = all(value == 1 for value in generated_counts.values())
    deployed_green = (
        all(value == 1 for value in deployed_counts.values())
        and all(value == 0 for value in stale_fragments.values())
    )
    return {
        "arcade_instructions": decoded,
        "arcade_result": "green" if arcade_green else "red",
        "transpile_command": TRANSPILE_COMMAND,
        "transpiler_stderr": generated.stderr.strip(),
        "generated_pattern_counts": generated_counts,
        "generated_result": "green" if generated_green else "red",
        "deployed_pattern_counts": deployed_counts,
        "deployed_stale_fragment_counts": stale_fragments,
        "deployed_result": "green" if deployed_green else "red",
        "result": (
            "green"
            if arcade_green and generated_green and deployed_green
            else "red"
        ),
    }


def load_cases(
    directory: Path,
    symbols: dict[str, int],
) -> list[SeamCase]:
    fixtures = hot.load_fixtures(directory, {TARGET}, None)
    cases: list[SeamCase] = []
    for fixture in fixtures:
        metadata = json.loads(
            fixture.metadata_path.read_text(encoding="utf-8")
        )
        intervention = metadata.get("intervention", {})
        for seam_name, flag in (
            ("first", "first_neg_seam"),
            ("second", "second_neg_seam"),
        ):
            if not intervention.get(flag):
                continue
            spec = SEAMS[seam_name]
            label = str(spec["native_label"])
            if label not in symbols:
                raise RuntimeError(f"Pansy metadata lacks {label}")
            cases.append(
                SeamCase(
                    name=f"{fixture.name}-{seam_name}",
                    fixture=fixture,
                    seam_name=seam_name,
                    original_pc=int(spec["original_pc"]),
                    native_pc=0x9F0000 | symbols[label],
                    register=str(spec["register"]),
                )
            )
    if not cases:
        raise RuntimeError(f"no NEG.B seam cases found in {directory}")
    return cases


def mame_result(
    session: base.MameSession,
    case: SeamCase,
    state_name: str,
) -> SeamResult:
    fixture = case.fixture
    tap_name = f"mcp_{case.name.replace('-', '_')}"
    session.pause()
    session.exec_lua(
        "if MCP_NEG_SEAM then MCP_NEG_SEAM:remove() end; "
        "MCP_NEG_SEAM = "
        "machine.devices[':maincpu'].spaces['program']"
        f":install_read_tap(0x{case.original_pc:06X}, "
        f"0x{case.original_pc + 1:06X}, '{tap_name}', "
        "function(offset, data, mask) return 0x60FE end); return true"
    )
    session.write_block(
        0xF00000, fixture.work[:MAPPED_WORK_SIZE]
    )
    for name in base.REG_NAMES[:-1]:
        session.set_reg(name, fixture.regs[name])
    entry_sp = fixture.regs["A7"] & 0xFFFFFF
    session.set_reg("SP", entry_sp)
    session.set_reg("USP", entry_sp)
    session.set_reg("SR", fixture.sr | 0x0700)
    session.set_reg("PC", fixture.target)
    pre_state = session.save_state(state_name)
    captured = session.cmd(
        "capture_at_pc",
        pc=case.original_pc,
        addr=0xF00000,
        len=MAPPED_WORK_SIZE,
        nth=2,
        exp_sp=entry_sp,
        maxFrames=180,
        timeout=180,
    )
    session.exec_lua(
        "if MCP_NEG_SEAM then MCP_NEG_SEAM:remove(); "
        "MCP_NEG_SEAM=nil end; return true"
    )
    if not captured.get("registers"):
        raise RuntimeError(f"MAME missed {case.name}: {captured!r}")
    registers = captured["registers"]
    result_regs = {
        name: int(registers[name]) & 0xFFFFFFFF
        for name in base.REG_NAMES[:-1]
    }
    result_regs["A7"] = int(registers["SP"]) & 0xFFFFFFFF
    work = bytearray(fixture.work)
    work[:MAPPED_WORK_SIZE] = bytes.fromhex(captured["hex"])
    return SeamResult(
        regs=result_regs,
        ccr=int(registers["SR"]) & CCR_MASK,
        work=bytes(work),
        cycles=None,
        observed_pc=case.original_pc,
        pre_state=pre_state,
    )


def save_prepared_state(
    session: base.McpSession,
    path: Path,
) -> dict[str, Any]:
    response = session.save_state(path.resolve())
    wait_for_file(path)
    return {
        "path": str(path.resolve()),
        "sha256": sha256(path),
        "response": response,
    }


def captured_console_result(
    session: base.McpSession,
    fixture: hot.Fixture,
    *,
    ccr: int,
    cycles: int,
    observed_pc: int,
    stored_ccr: int,
    host_ps: int | None,
    pre_state: dict[str, Any],
) -> SeamResult:
    return SeamResult(
        regs=live.captured_regs(session),
        ccr=ccr & CCR_MASK,
        work=bytes(
            session.read_memory(
                base.SNES_SPACE, 0x400000, FULL_WORK_SIZE
            )
        ),
        cycles=cycles,
        observed_pc=observed_pc,
        stored_ccr=stored_ccr,
        host_ps=host_ps,
        pre_state=pre_state,
    )


def native_off_result(
    session: base.McpSession,
    nat: Path,
    case: SeamCase,
    pre_state_path: Path,
) -> SeamResult:
    fixture = case.fixture
    hot.prepare_console(session, nat, fixture, 0)
    pre_state = save_prepared_state(session, pre_state_path)

    seam_file = 0x10000 + case.original_pc
    illegal_file = hot.OP_ILLEGAL - 0x8000
    original_seam = bytes(
        session.read_memory("snesPrgRom", seam_file, 2)
    )
    original_illegal = bytes(
        session.read_memory("snesPrgRom", illegal_file, 2)
    )
    session.write_memory("snesPrgRom", seam_file, "4afc")
    session.write_memory("snesPrgRom", illegal_file, "80fe")
    hook = session.add_exec_hook(hot.OP_ILLEGAL, cpu_type="Sa1")
    session.drain_notifications(timeout=0.05)
    live.set_sa1_pc(session, hot.OJMP_HOOK)
    start = int(session.get_cpu_state("Sa1")["cycleCount"])
    try:
        hit, _frames = live.run_to_hook(session, hook, attempts=16)
        session.pause()
    finally:
        session.remove_hook(hook)
        session.write_memory(
            "snesPrgRom", seam_file, original_seam.hex()
        )
        session.write_memory(
            "snesPrgRom", illegal_file, original_illegal.hex()
        )
    if (hit or {}).get("reason") != "hookFired":
        raise RuntimeError(f"native-off missed {case.name}: {hit!r}")
    observed_pc = live.read_u16(session, 0x40) | (
        (live.read_u16(session, 0x42) & 0xFF) << 16
    )
    if observed_pc != case.original_pc:
        raise RuntimeError(
            f"native-off {case.name} virtual PC ${observed_pc:06X}"
        )
    end = int(session.get_cpu_state("Sa1")["cycleCount"])
    stored_ccr = live.captured_ccr(session)
    return captured_console_result(
        session,
        fixture,
        ccr=stored_ccr,
        cycles=end - start,
        observed_pc=observed_pc,
        stored_ccr=stored_ccr,
        host_ps=None,
        pre_state=pre_state,
    )


def native_effective_ccr(session: base.McpSession, ps: int) -> int:
    x = 1 if live.read_u16(session, 0xA2) else 0
    n = 1 if ps & 0x80 else 0
    z = 1 if ps & 0x02 else 0
    v = 1 if ps & 0x40 else 0
    # Native NEG is SEC:SBC, so host C means no borrow and the 68000
    # carry/extend bits are its inverse.
    c = 0 if ps & 0x01 else 1
    return (x << 4) | (n << 3) | (z << 2) | (v << 1) | c


def native_on_result(
    session: base.McpSession,
    nat: Path,
    case: SeamCase,
    pre_state_path: Path,
) -> SeamResult:
    fixture = case.fixture
    hot.prepare_console(session, nat, fixture, 1)
    pre_state = save_prepared_state(session, pre_state_path)

    seam_file = 0x2F0000 + (case.native_pc & 0xFFFF)
    original_word = bytes(
        session.read_memory("snesPrgRom", seam_file, 2)
    )
    # Keep the asynchronous hook at a flag-neutral BRA spin.  Even if Nexen
    # executes the replacement before pausing, BRA preserves the NEG NZVC.
    session.write_memory("snesPrgRom", seam_file, "80fe")
    hook = session.add_exec_hook(case.native_pc, cpu_type="Sa1")
    session.drain_notifications(timeout=0.05)
    live.set_sa1_pc(session, hot.OJMP_HOOK)
    start = int(session.get_cpu_state("Sa1")["cycleCount"])
    try:
        hit, _frames = live.run_to_hook(session, hook, attempts=16)
        session.pause()
    finally:
        session.remove_hook(hook)
        session.write_memory(
            "snesPrgRom", seam_file, original_word.hex()
        )
    if (hit or {}).get("reason") != "hookFired":
        raise RuntimeError(f"native-on missed {case.name}: {hit!r}")
    sa1 = session.get_cpu_state("Sa1")
    actual_pc = ((int(sa1["k"]) & 0xFF) << 16) | (
        int(sa1["pc"]) & 0xFFFF
    )
    if actual_pc != case.native_pc:
        raise RuntimeError(
            f"native-on {case.name} stopped at ${actual_pc:06X}, "
            f"expected ${case.native_pc:06X}"
        )
    ps = int(sa1["ps"]) & 0xFF
    end = int(sa1["cycleCount"])
    stored_ccr = live.captured_ccr(session)
    return captured_console_result(
        session,
        fixture,
        ccr=native_effective_ccr(session, ps),
        cycles=end - start,
        observed_pc=actual_pc,
        stored_ccr=stored_ccr,
        host_ps=ps,
        pre_state=pre_state,
    )


def mismatch_map(
    expected: SeamResult,
    actual: SeamResult,
) -> tuple[dict[str, dict[str, int]], list[int], bool]:
    registers = {
        name: {
            "mame": expected.regs[name],
            "nexen": actual.regs[name],
        }
        for name in base.REG_NAMES
        if expected.regs[name] != actual.regs[name]
    }
    work = [
        offset
        for offset, (left, right) in enumerate(
            zip(
                expected.work[:MAPPED_WORK_SIZE],
                actual.work[:MAPPED_WORK_SIZE],
            )
        )
        if left != right
    ]
    return registers, work, expected.ccr != actual.ccr


def compare_case(
    case: SeamCase,
    arcade: SeamResult,
    native_off: SeamResult,
    native_on: SeamResult,
) -> dict[str, Any]:
    off_regs, off_work, off_ccr = mismatch_map(arcade, native_off)
    on_regs, on_work, on_ccr = mismatch_map(arcade, native_on)
    off_high = [
        offset
        for offset, (before, after) in enumerate(
            zip(
                case.fixture.work[MAPPED_WORK_SIZE:],
                native_off.work[MAPPED_WORK_SIZE:],
            ),
            start=MAPPED_WORK_SIZE,
        )
        if before != after
    ]
    on_high = [
        offset
        for offset, (before, after) in enumerate(
            zip(
                case.fixture.work[MAPPED_WORK_SIZE:],
                native_on.work[MAPPED_WORK_SIZE:],
            ),
            start=MAPPED_WORK_SIZE,
        )
        if before != after
    ]
    green = not any(
        (
            off_regs,
            off_work,
            off_ccr,
            on_regs,
            on_work,
            on_ccr,
            off_high,
            on_high,
        )
    )
    return {
        "event": "case",
        "case": case.name,
        "fixture": case.fixture.name,
        "seam": case.seam_name,
        "original_pc": f"{case.original_pc:06X}",
        "native_pc": f"{case.native_pc:06X}",
        "negated_register": case.register,
        "input_register": f"{case.fixture.regs[case.register]:08X}",
        "mame_register": f"{arcade.regs[case.register]:08X}",
        "native_off_register": f"{native_off.regs[case.register]:08X}",
        "native_on_register": f"{native_on.regs[case.register]:08X}",
        "mame_ccr_xnzvc": arcade.ccr,
        "native_off": {
            "cycles_local": native_off.cycles,
            "effective_ccr_xnzvc": native_off.ccr,
            "stored_ccr_xnzvc": native_off.stored_ccr,
            "register_mismatches": off_regs,
            "ccr_mismatch": off_ccr,
            "mapped_work_mismatch_count": len(off_work),
            "mapped_work_mismatch_first": [
                f"F0{offset:04X}" for offset in off_work[:24]
            ],
            "upper_backing_mutation_count": len(off_high),
            "pre_state": native_off.pre_state,
        },
        "native_on": {
            "cycles_local": native_on.cycles,
            "effective_ccr_xnzvc": native_on.ccr,
            "stored_ccr_xnzvc": native_on.stored_ccr,
            "host_ps": native_on.host_ps,
            "register_mismatches": on_regs,
            "ccr_mismatch": on_ccr,
            "mapped_work_mismatch_count": len(on_work),
            "mapped_work_mismatch_first": [
                f"F0{offset:04X}" for offset in on_work[:24]
            ],
            "upper_backing_mutation_count": len(on_high),
            "pre_state": native_on.pre_state,
        },
        "stack_address": f"{case.fixture.regs['A7'] & 0xFFFFFF:06X}",
        "input_stack_hex": case.fixture.work[
            case.fixture.regs["A7"] & 0xFFFF :
            (case.fixture.regs["A7"] & 0xFFFF) + 16
        ].hex(),
        "result": "green" if green else "red",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixtures", type=Path, default=DEFAULT_FIXTURES)
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    parser.add_argument("--nexen", type=Path, default=base.DEFAULT_NEXEN)
    parser.add_argument("--nat", type=Path, default=base.DEFAULT_NAT)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--pansy", type=Path, default=DEFAULT_PANSY)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--port", type=int, default=9315)
    args = parser.parse_args()

    for label, path in (
        ("fixtures", args.fixtures),
        ("ROM", args.rom),
        ("Nexen", args.nexen),
        ("native base state", args.nat),
        ("generated source", args.source),
        ("Pansy metadata", args.pansy),
    ):
        if not path.exists():
            parser.error(f"missing {label}: {path}")
    if args.output.exists():
        parser.error(f"output already exists: {args.output}")
    args.output.mkdir(parents=True)
    states = args.output / "states"
    states.mkdir()

    symbols = pansy_symbols(args.pansy)
    cases = load_cases(args.fixtures.resolve(), symbols)
    codegen = validate_codegen(args.source.resolve())
    events: list[dict[str, Any]] = []
    provenance = {
        "event": "provenance",
        "scope": (
            "internal post-NEG.B seam MAME original / Nexen native-off / "
            "Nexen native-on differential; all D/A, effective CCR/X, exact "
            "stack, mapped work RAM, upper-backing conservation, and "
            "retained prepared save states; bounded synthetic fixtures, not "
            "fresh-boot or performance evidence"
        ),
        "classification_if_native_off_green_native_on_red": "native/HLE",
        "mame": "/snap/bin/mame 0.287",
        "nexen": str(args.nexen.resolve()),
        "nexen_sha256": sha256(args.nexen),
        "rom": str(args.rom.resolve()),
        "rom_sha256": sha256(args.rom),
        "nat": str(args.nat.resolve()),
        "nat_sha256": sha256(args.nat),
        "fixtures": str(args.fixtures.resolve()),
        "case_count": len(cases),
        "codegen": codegen,
        "native_seams": {
            name: f"9F{symbols[str(spec['native_label'])]:04X}"
            for name, spec in SEAMS.items()
        },
        "time": time.time(),
    }
    events.append(provenance)
    print(json.dumps(provenance, sort_keys=True), flush=True)

    mame_workdir = args.output / "mame-session"
    mame_states = mame_workdir / "states"
    mame_workdir.mkdir()
    mame_states.mkdir()
    arcade: dict[str, SeamResult] = {}
    mame = base.MameSession(
        mame="/snap/bin/mame",
        system="superman",
        rompath=str(base.MAME_TRACE / "roms"),
        workdir=str(mame_workdir),
        state_directory=str(mame_states),
        extra_args=["-video", "none", "-sound", "none", "-nothrottle"],
    )
    try:
        mame.launch(boot_wait=25)
        for case in cases:
            arcade[case.name] = mame_result(
                mame, case, f"pre-{case.name}"
            )
    finally:
        mame.stop()

    stderr_log = args.output / "nexen.stderr.log"
    with base.McpSession(
        rom=str(args.rom.resolve()),
        mesen=str(args.nexen.resolve()),
        cwd=ROOT,
        port=args.port,
        boot_wait=8.0,
        socket_timeout=240.0,
        stderr_log=stderr_log,
    ) as nexen:
        for case in cases:
            native_off = native_off_result(
                nexen,
                args.nat.resolve(),
                case,
                states / f"{case.name}-native-off-pre.mss",
            )
            native_on = native_on_result(
                nexen,
                args.nat.resolve(),
                case,
                states / f"{case.name}-native-on-pre.mss",
            )
            event = compare_case(
                case, arcade[case.name], native_off, native_on
            )
            events.append(event)
            print(json.dumps(event, sort_keys=True), flush=True)

    case_events = [event for event in events if event["event"] == "case"]
    green = sum(event["result"] == "green" for event in case_events)
    off_green = sum(
        not event["native_off"]["register_mismatches"]
        and not event["native_off"]["ccr_mismatch"]
        and event["native_off"]["mapped_work_mismatch_count"] == 0
        and event["native_off"]["upper_backing_mutation_count"] == 0
        for event in case_events
    )
    on_green = sum(
        not event["native_on"]["register_mismatches"]
        and not event["native_on"]["ccr_mismatch"]
        and event["native_on"]["mapped_work_mismatch_count"] == 0
        and event["native_on"]["upper_backing_mutation_count"] == 0
        for event in case_events
    )
    if off_green == len(case_events) and on_green != len(case_events):
        classification = "native/HLE"
    elif off_green != len(case_events):
        classification = "interpreter_or_harness"
    else:
        classification = "no semantic discrepancy"
    overall_green = (
        green == len(case_events) and codegen["result"] == "green"
    )
    summary = {
        "event": "summary",
        "semantic_cases": len(case_events),
        "native_off_green": off_green,
        "native_on_green": on_green,
        "all_green": green,
        "classification": classification,
        "codegen": codegen["result"],
        "result": "green" if overall_green else "red",
        "time": time.time(),
    }
    events.append(summary)
    print(json.dumps(summary, sort_keys=True), flush=True)
    (args.output / "result.json").write_text(
        json.dumps(
            {
                "provenance": provenance,
                "cases": case_events,
                "summary": summary,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return 0 if overall_green else 1


if __name__ == "__main__":
    raise SystemExit(main())
